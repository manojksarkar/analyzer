"""
Document Preparer — builds a structured JSON document from model/ directory metadata.

This service generates the same JSON structure as ``src/docx_exporter.py`` produces
as a DOCX, but as a JSON tree suitable for UI rendering.  It reads directly from
the pipeline model files (``model/*.json``) via ``ModelReader`` and optionally from
pipeline output artefacts (``output/interface_tables.json``, ``output/flowcharts/``).

Unlike ``document_renderer.py`` (which requires an existing ``Document`` DB record),
this module can operate on **model data alone** — it synthesises all document metadata
(project name, layer, group, version) from ``model/metadata.json`` without needing a
pre-existing DB document.

Entry points
------------
``prepare_from_model(model_dir, output_dir, group, layer, version_tag)``
    Build the full document JSON for a group/layer directly from model/.

``prepare_document(doc, db, project_id, root)``
    Same as ``build_document_structure`` in document_renderer, but uses ModelReader
    more aggressively and exposes richer model-sourced content.

JSON shape (identical to document_renderer output + extra model fields)
-----------------------------------------------------------------------
{
  "cover": { project_name, subtitle, version, document_name, layer, group,
             project_path, components },
  "toc": [ {id, number, title, level} ... ],
  "sections": [ <Section> ... ],  # recursive, with children
  "meta": {
    "pipeline_data_available": bool,
    "model_data_available": bool,
    "source": "model" | "pipeline" | "stored_sections",
    "components": [...],
    "layers": [...],
    "units_total": int,
    "functions_total": int,
    "globals_total": int,
  }
}

Section shape (same as document_renderer._sec())
{
  "id", "number", "title", "level", "type",
  "content": str | null,
  "table": dict | null,        # type-specific structured table
  "review_state": null,
  "reviewed_by": null,
  "reviewed_at": null,
  "children": [...]
}

Table types
-----------
  interface_table     — 8-column interface rows (functions + globals)
  unit_header_table   — globals / typedef / enum / define rows
  component_unit_table — Component | Unit | Description | Note
  abbreviations_table  — Term | Description
  flowchart            — function_name, signature, input_label, output_label, flowcharts[]
  behaviour            — current_function, external_unit_function, png_path
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

from .model_reader import ModelReader

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_KEY_SEP = "|"   # same as utils.KEY_SEP

_IFACE_COLS = (
    "Interface ID", "Interface Name", "Information",
    "Data Type", "Data Range", "Direction(In/Out)",
    "Source/Destination", "Interface Type",
)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _find_root() -> Path:
    here = Path(__file__).resolve().parent
    for candidate in [here, here.parent, here.parent.parent, here.parent.parent.parent]:
        if (candidate / "run.py").exists():
            return candidate
    return here.parent.parent


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Section builder
# ---------------------------------------------------------------------------

def _sec(
    id: str,
    number: str,
    title: str,
    level: int,
    type: str,
    *,
    content: Optional[str] = None,
    table: Optional[dict] = None,
    review_state: Optional[str] = None,
    reviewed_by: Optional[str] = None,
    reviewed_at: Optional[str] = None,
    children: Optional[list] = None,
) -> dict:
    return {
        "id": id,
        "number": number,
        "title": title,
        "level": level,
        "type": type,
        "content": content,
        "table": table,
        "review_state": review_state,
        "reviewed_by": reviewed_by,
        "reviewed_at": reviewed_at,
        "children": children or [],
    }


# ---------------------------------------------------------------------------
# Table builders — match doc_exporter column names exactly
# ---------------------------------------------------------------------------

def _interface_table(interfaces: list[dict]) -> dict:
    """Build structured interface table dict (8 columns)."""
    rows = []
    for iface in interfaces:
        iface_type = iface.get("type", "") or "-"
        if "variableType" in iface:
            # Global variable row
            data_type = iface.get("variableType", "") or "-"
            data_range = iface.get("range", "") or "NA"
        else:
            params = iface.get("parameters", []) or []
            if params:
                data_type = "; ".join(p.get("type", "") for p in params)
                data_range = "; ".join(p.get("range", "") or "NA" for p in params)
            else:
                data_type = iface.get("returnType", "") or "VOID"
                data_range = "NA"

        rows.append({
            "interface_id":   str(iface.get("interfaceId", "")),
            "interface_name": str(iface.get("interfaceName", "") or iface.get("name", "")),
            "information":    str(iface.get("description", "") or "-"),
            "data_type":      data_type,
            "data_range":     data_range,
            "direction":      str(iface.get("direction", "") or "-"),
            "source_dest":    str(iface.get("sourceDest", "") or "-"),
            "interface_type": iface_type,
        })
    return {
        "type": "interface_table",
        "columns": list(_IFACE_COLS),
        "rows": rows,
    }


def _unit_header_table(rows: list[dict]) -> dict:
    return {
        "type": "unit_header_table",
        "columns": ["global variables / typedef / enum / define", "information"],
        "rows": [
            {
                "declaration": r.get("declaration", ""),
                "information": r.get("information", ""),
            }
            for r in rows
        ],
    }


def _component_unit_table(component_name: str, rows: list[dict]) -> dict:
    return {
        "type": "component_unit_table",
        "columns": ["Component", "Unit", "Description", "Note"],
        "component": component_name,
        "rows": rows,
    }


def _abbreviations_table(abbreviations: dict) -> dict:
    return {
        "type": "abbreviations_table",
        "columns": ["Term", "Description"],
        "rows": [{"term": k, "description": v} for k, v in sorted(abbreviations.items())],
    }


# ---------------------------------------------------------------------------
# Pipeline artefact loaders
# ---------------------------------------------------------------------------

def _load_interface_tables(output_dir: Path, group: str) -> Optional[dict]:
    """Try group-scoped path first, then top-level."""
    candidates = []
    if group:
        candidates.append(output_dir / group.replace(" ", "-") / "interface_tables.json")
    candidates.append(output_dir / "interface_tables.json")
    for p in candidates:
        data = _load_json(p)
        if data:
            return data
    return None


def _load_behaviour_pngs(output_dir: Path, group: str) -> dict:
    candidates = []
    if group:
        candidates.append(output_dir / group.replace(" ", "-") / "behaviour_diagrams" / "_behaviour_pngs.json")
    candidates.append(output_dir / "behaviour_diagrams" / "_behaviour_pngs.json")
    for p in candidates:
        data = _load_json(p)
        if data and "_docxRows" in data:
            return data["_docxRows"]
    return {}


def _load_flowcharts(output_dir: Path, group: str) -> dict:
    """Return {unit_name: {func_name: mermaid_str}}."""
    candidates = []
    if group:
        candidates.append(output_dir / group.replace(" ", "-") / "flowcharts")
    candidates.append(output_dir / "flowcharts")
    for fc_dir in candidates:
        if not fc_dir.is_dir():
            continue
        result: dict = {}
        for fname in os.listdir(fc_dir):
            if not fname.endswith(".json"):
                continue
            unit_name = fname[:-5]
            data = _load_json(fc_dir / fname)
            if not isinstance(data, list):
                continue
            result[unit_name] = {}
            for item in data:
                name = (item.get("name") or "").strip()
                flowchart = (item.get("flowchart") or "").strip()
                if name and flowchart:
                    result[unit_name][name] = flowchart
        if result:
            return result
    return {}


# ---------------------------------------------------------------------------
# Readable label helper (mirrors docx_exporter._readable_label)
# ---------------------------------------------------------------------------

def _readable_label(qn: str) -> str:
    """Convert a qualified name to a human-readable label."""
    name = qn.split("::")[-1] if "::" in qn else qn
    # Strip common prefixes
    for prefix in ("g_", "s_", "t_", "m_", "p_"):
        if name.lower().startswith(prefix):
            name = name[len(prefix):]
    # CamelCase / underscores → spaces
    name = re.sub(r"_", " ", name)
    name = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    return name.strip()


# ---------------------------------------------------------------------------
# Unit header row builder (from model data)
# ---------------------------------------------------------------------------

def _build_unit_header_rows_from_model(
    unit_info: dict,
    global_variables_data: dict,
    data_dictionary: dict,
) -> list[dict]:
    """
    Build unit header rows (globals, typedefs, enums, defines) from model data.
    Mirrors docx_exporter._build_unit_header_table logic.
    """
    rows: list[dict] = []
    seen_decls: set = set()

    # --- Global variables ---
    for gid in unit_info.get("globalVariableIds", []) or []:
        g = (global_variables_data or {}).get(gid) or {}
        if (g.get("visibility") or "").lower() == "private":
            continue
        name = g.get("qualifiedName") or g.get("name") or str(gid)
        info = g.get("value") or g.get("initializer") or "N/A"
        decl = f"{g.get('type', '')} {name}".strip()
        key = decl or name
        if key not in seen_decls:
            seen_decls.add(key)
            rows.append({"declaration": decl, "information": str(info)})

    # --- data dictionary (typedefs / enums / defines) ---
    unit_paths: set = set()
    path_val = unit_info.get("path")
    if path_val:
        path_list = path_val if isinstance(path_val, list) else [path_val]
        for p in path_list:
            unit_paths.add(os.path.splitext(str(p).replace("\\", "/"))[0])

    for type_name, t in (data_dictionary or {}).items():
        if not isinstance(t, dict):
            continue
        kind = t.get("kind", "")
        if kind not in ("typedef", "enum", "define"):
            continue

        # Only include entries whose source file matches this unit
        loc = t.get("location") or {}
        rel_file = (loc.get("file") or "").replace("\\", "/")
        type_file = os.path.splitext(rel_file)[0]
        if unit_paths and type_file and type_file not in unit_paths:
            continue

        decl = t.get("text") or t.get("name") or type_name or "N/A"

        if kind == "enum":
            enums = t.get("enumerators", []) or []
            parts = []
            for e in enums:
                n = e.get("name", "")
                v = e.get("value")
                if n:
                    parts.append(f"{n}={v}" if v is not None else n)
            info = ", ".join(parts) if parts else "N/A"
        elif kind == "define":
            info = t.get("value", "") or "N/A"
            # Skip include guards
            val_empty = not (t.get("value") or "").strip()
            if val_empty and re.match(r"^_*[A-Z][A-Z0-9_]*(?:_H|_HPP)_*$", type_name):
                continue
        else:  # typedef
            info = t.get("underlyingType") or "N/A"

        key = str(decl).strip()
        if key and key not in seen_decls:
            seen_decls.add(key)
            rows.append({"declaration": str(decl), "information": str(info)})

    return rows


# ---------------------------------------------------------------------------
# Interface rows builder from model data (no interface_tables.json needed)
# ---------------------------------------------------------------------------

def _build_interface_rows_from_model(
    unit_key: str,
    functions_data: dict,
    global_variables_data: dict,
    hidden_fids: set,
) -> list[dict]:
    """
    Build interface rows for a unit directly from model/functions.json and
    model/globalVariables.json — mirrors docx_exporter interface table logic.

    This is used when output/interface_tables.json does not exist.
    """
    rows: list[dict] = []
    component = unit_key.split(_KEY_SEP, 1)[0] if _KEY_SEP in unit_key else ""
    unit_name = unit_key.split(_KEY_SEP, 1)[1] if _KEY_SEP in unit_key else unit_key

    # Collect public functions for this unit
    fn_items = []
    for fn_key, fn in (functions_data or {}).items():
        if not isinstance(fn, dict):
            continue
        if fn_key in hidden_fids or fn.get("hidden", False):
            continue
        fn_comp = fn.get("componentName") or fn.get("group") or ""
        fn_unit = fn.get("unitName") or (fn.get("file", "").replace("\\", "/").split("/")[-1].split(".")[0])
        # match by component + unit name
        if fn_comp != component or fn_unit != unit_name:
            continue
        vis = (fn.get("visibility") or "").lower()
        if vis == "private":
            continue
        fn_items.append((fn.get("line", 9999), fn_key, fn))

    fn_items.sort(key=lambda x: x[0])

    for _, fn_key, fn in fn_items:
        params = fn.get("parameters") or []
        if params and isinstance(params[0], dict):
            param_types = "; ".join(p.get("type", "") for p in params)
            param_ranges = "; ".join(p.get("range", "") or "NA" for p in params)
        else:
            param_types = "VOID"
            param_ranges = "NA"

        callers = fn.get("calledByIds") or []
        source_dest = ",".join(
            (functions_data.get(c) or {}).get("unitName", c) for c in callers[:3]
        ) or "-"

        rows.append({
            "interfaceId": fn.get("interfaceId", ""),
            "interfaceName": _readable_label(fn.get("qualifiedName") or fn.get("name") or fn_key),
            "name": fn.get("name") or fn_key.split("::")[-1],
            "description": fn.get("description") or "-",
            "parameters": params,
            "returnType": fn.get("returnType") or "",
            "data_type": param_types,
            "data_range": param_ranges,
            "direction": fn.get("direction") or "-",
            "sourceDest": source_dest,
            "type": "Function",
            "functionId": fn_key,
        })

    # Collect public global variables for this unit
    for gv_key, gv in (global_variables_data or {}).items():
        if not isinstance(gv, dict):
            continue
        gv_comp = gv.get("componentName") or gv.get("group") or ""
        gv_unit = gv.get("unitName") or (gv.get("file", "").replace("\\", "/").split("/")[-1].split(".")[0])
        if gv_comp != component or gv_unit != unit_name:
            continue
        vis = (gv.get("visibility") or "").lower()
        if vis == "private":
            continue

        rows.append({
            "interfaceId": gv.get("interfaceId", ""),
            "interfaceName": _readable_label(gv.get("qualifiedName") or gv.get("name") or gv_key),
            "name": gv.get("name") or gv_key,
            "description": gv.get("description") or "-",
            "variableType": gv.get("type") or "",
            "range": gv.get("range") or "NA",
            "direction": "In/Out",
            "sourceDest": "-",
            "type": "Global Variable",
        })

    return rows


# ---------------------------------------------------------------------------
# TOC builder
# ---------------------------------------------------------------------------

def _build_toc(sections: list[dict]) -> list[dict]:
    toc: list[dict] = []

    def _walk(nodes: list):
        for node in nodes:
            toc.append({
                "id": node["id"],
                "number": node["number"],
                "title": node["title"],
                "level": node["level"],
            })
            if node.get("children"):
                _walk(node["children"])

    _walk(sections)
    return toc


# ---------------------------------------------------------------------------
# Core: build document from pipeline artefacts + model
# ---------------------------------------------------------------------------

def _build_sections_from_pipeline(
    project_name: str,
    group: str,
    layer: str,
    version_tag: str,
    iface_tables: dict,
    behaviour_rows: dict,
    flowcharts_map: dict,
    units_data: dict,
    functions_data: dict,
    global_variables_data: dict,
    data_dictionary: dict,
    metadata: dict,
    doc_name: str = "",
    doc_process: str = "SWE.3",
) -> dict:
    """
    Build the full document JSON from pipeline artefacts (interface_tables.json)
    and model/ data — equivalent to the DOCX produced by Phase 4.
    """
    # Use project name from metadata if available
    if metadata.get("projectName"):
        project_name = metadata["projectName"]

    hidden_fids: set = {
        fid for fid, f in functions_data.items()
        if isinstance(f, dict) and f.get("hidden", False)
    }

    # Organise units by component
    by_component: dict[str, list] = {}
    for unit_key, unit_data in iface_tables.items():
        if unit_key in ("basePath", "projectName", "unitNames"):
            continue
        if not isinstance(unit_data, dict) or "entries" not in unit_data:
            continue
        parts = unit_key.split(_KEY_SEP, 1)
        component_name = parts[0]
        unit_name_display = unit_data.get(
            "name",
            (unit_key.split(_KEY_SEP)[-1] if _KEY_SEP in unit_key else unit_key),
        )
        interfaces = [
            i for i in unit_data["entries"]
            if i.get("functionId") not in hidden_fids
        ]
        by_component.setdefault(component_name, []).append(
            (unit_key, unit_name_display, interfaces)
        )

    sorted_components = sorted(by_component.keys())

    cover_group = (
        f"{layer} {group}".strip() if (layer and group) else (group or "All Components")
    )

    # ------- Section 1: Introduction -------
    intro_content_scope = "\n".join(
        [
            f"This document covers the {cover_group} component(s) of {project_name}.",
            "",
            "Components in scope:",
        ]
        + [f"• {c.replace('-', ' ')}" for c in sorted_components]
    )

    intro_sec = _sec(
        "s1", "1", "1 Introduction", 1, "introduction",
        children=[
            _sec("s1_1", "1.1", "1.1 Purpose", 2, "purpose",
                 content=f"This document describes the Software Detailed Design for {project_name}."),
            _sec("s1_2", "1.2", "1.2 Scope", 2, "scope",
                 content=intro_content_scope),
            _sec("s1_3", "1.3", "1.3 Terms, Abbreviations and Definitions", 2, "terms",
                 content="[Terms, abbreviations and definitions.]"),
        ],
    )
    sections = [intro_sec]

    # ------- Sections 2…N: Per-component -------
    for sec_idx, component_name in enumerate(sorted_components):
        sec_num = sec_idx + 2
        component_display = component_name.replace("-", " ")
        comp_sec_id = f"s{sec_num}"
        comp_children: list = []

        unit_rows_component = sorted(by_component[component_name])

        # N.1 Static Design
        static_children: list = []

        # Component-unit overview table
        cu_rows = []
        for _, unit_name_display, interfaces in unit_rows_component:
            descs = [
                " ".join((i.get("description") or "").split())
                for i in interfaces
                if (i.get("description") or "").strip() not in ("", "-", "N/A")
            ]
            unique_descs = list(dict.fromkeys(descs))
            desc = "; ".join(unique_descs)[:120] if unique_descs else "N/A"
            cu_rows.append({"unit": unit_name_display, "description": desc, "note": "N/A"})

        static_children.append(_sec(
            f"s{sec_num}_1_overview",
            f"{sec_num}.1.0",
            f"{sec_num}.1 Component Overview",
            3,
            "component_overview",
            table=_component_unit_table(component_display, cu_rows),
        ))

        # Per-unit subsections
        for unit_idx, (unit_key, unit_name_display, interfaces) in enumerate(
            unit_rows_component, start=1
        ):
            unit_sec_id = f"s{sec_num}_1_{unit_idx}"
            unit_info = units_data.get(unit_key, {})

            header_rows = _build_unit_header_rows_from_model(
                unit_info, global_variables_data, data_dictionary
            )

            unit_name_flowchart = (
                unit_key.split(_KEY_SEP)[-1] if _KEY_SEP in unit_key else unit_name_display
            )
            unit_prefix = unit_key.replace(_KEY_SEP, "_").replace(" ", "_")

            # Per-function flowchart sections (functions only, not globals)
            fn_sections: list = []
            rendered_private_fids: set = set()
            fn_interfaces = [i for i in interfaces if i.get("type") != "Global Variable"]

            for iface_idx, iface in enumerate(fn_interfaces, start=3):
                func_name = iface.get("name", "")
                iface_sec_id = f"{unit_sec_id}_{iface_idx}"

                flowchart = (
                    (flowcharts_map.get(unit_prefix) or {}).get(func_name)
                    or (flowcharts_map.get(unit_name_flowchart) or {}).get(func_name)
                ) if func_name else None

                iface_params = ", ".join(
                    f"{p.get('type', '')} {p.get('name', '')}".strip()
                    for p in (iface.get("parameters") or [])
                )
                iface_return = iface.get("returnType", "") or ""
                iface_signature = f"{iface_return} {func_name}({iface_params})".strip()

                fn_func_data = functions_data.get(iface.get("functionId", "")) or {}
                input_label = (fn_func_data.get("behaviourInputName") or "").strip()
                output_label = (fn_func_data.get("behaviourOutputName") or "").strip()

                flowcharts_payload: list = []
                if flowchart:
                    png_key = f"{unit_prefix}_{func_name}"
                    flowcharts_payload.append({
                        "signature": iface_signature,
                        "mermaid": flowchart,
                        "png_key": png_key,
                    })

                # Private callee flowcharts
                for callee_fid in (fn_func_data.get("callsIds") or []):
                    if callee_fid in hidden_fids:
                        continue
                    callee = functions_data.get(callee_fid) or {}
                    if (callee.get("visibility") or "").lower() != "private":
                        continue
                    if callee_fid in rendered_private_fids:
                        continue
                    rendered_private_fids.add(callee_fid)
                    callee_parts = callee_fid.split(_KEY_SEP)
                    callee_unit_key = _KEY_SEP.join(callee_parts[:2]) if len(callee_parts) >= 2 else ""
                    callee_unit_prefix = callee_unit_key.replace(_KEY_SEP, "_").replace(" ", "_")
                    callee_unit_name = callee_parts[1] if len(callee_parts) > 1 else ""
                    callee_qn = callee.get("qualifiedName", "")
                    callee_func_name = callee_qn.split("::")[-1] if callee_qn else ""
                    if not callee_func_name:
                        continue
                    callee_fc = (
                        (flowcharts_map.get(callee_unit_prefix) or {}).get(callee_func_name)
                        or (flowcharts_map.get(callee_unit_name) or {}).get(callee_func_name)
                    )
                    if not callee_fc:
                        continue
                    callee_params = ", ".join(
                        f"{p.get('type', '')} {p.get('name', '')}".strip()
                        for p in (callee.get("params") or callee.get("parameters") or [])
                    )
                    callee_return = callee.get("returnType", "")
                    callee_sig = f"{callee_return} {callee_func_name}({callee_params})".strip()
                    flowcharts_payload.append({
                        "signature": callee_sig,
                        "mermaid": callee_fc,
                        "png_key": f"{callee_unit_prefix}_{callee_func_name}",
                    })

                fn_sec = _sec(
                    iface_sec_id,
                    f"{sec_num}.1.{unit_idx}.{iface_idx}",
                    f"{sec_num}.1.{unit_idx}.{iface_idx} {unit_name_display}-{func_name}",
                    4,
                    "flowchart",
                    content=iface.get("description", "") or "-",
                    table={
                        "type": "flowchart",
                        "function_name": func_name,
                        "signature": iface_signature,
                        "input_label": input_label,
                        "output_label": output_label,
                        "flowcharts": flowcharts_payload,
                    } if flowcharts_payload else None,
                )
                fn_sections.append(fn_sec)

            unit_sec = _sec(
                unit_sec_id,
                f"{sec_num}.1.{unit_idx}",
                f"{sec_num}.1.{unit_idx} {unit_name_display}",
                3,
                "unit",
                children=[
                    _sec(
                        f"{unit_sec_id}_1",
                        f"{sec_num}.1.{unit_idx}.1",
                        f"{sec_num}.1.{unit_idx}.1 unit header",
                        4,
                        "unit_header",
                        table=_unit_header_table(header_rows) if header_rows else None,
                        content=None if header_rows else "NA",
                    ),
                    _sec(
                        f"{unit_sec_id}_2",
                        f"{sec_num}.1.{unit_idx}.2",
                        f"{sec_num}.1.{unit_idx}.2 unit interface",
                        4,
                        "unit_interface",
                        table=_interface_table(interfaces),
                    ),
                ] + fn_sections,
            )
            static_children.append(unit_sec)

        comp_children.append(_sec(
            f"{comp_sec_id}_1",
            f"{sec_num}.1",
            f"{sec_num}.1 Static Design",
            2,
            "static_design",
            children=static_children,
        ))

        # N.2 Dynamic Behaviour
        beh_children: list = []
        beh_idx = 0
        comp_beh = behaviour_rows.get(component_name) or {}
        for unit_name_beh, entries in sorted(comp_beh.items()):
            for row in entries:
                current_fn = row.get("currentFunctionName", "") or ""
                beh_idx += 1
                ext = row.get("externalUnitFunction", "")
                subheader = f"{unit_name_beh} - {current_fn}"
                if ext:
                    subheader += f" ({ext})"
                beh_desc = row.get("behaviorDescription") or row.get("behaviourDescription") or []
                png_path = row.get("pngPath")
                beh_children.append(_sec(
                    f"{comp_sec_id}_2_{beh_idx}",
                    f"{sec_num}.2.{beh_idx}",
                    f"{sec_num}.2.{beh_idx} {subheader}",
                    3,
                    "behaviour_entry",
                    table={
                        "type": "behaviour",
                        "current_function": current_fn,
                        "external_unit_function": ext,
                        "behaviour_description": beh_desc,
                        "png_path": png_path,
                    },
                ))

        comp_children.append(_sec(
            f"{comp_sec_id}_2",
            f"{sec_num}.2",
            f"{sec_num}.2 Dynamic Behaviour",
            2,
            "dynamic_behaviour",
            children=beh_children,
        ))

        sections.append(_sec(
            comp_sec_id,
            str(sec_num),
            f"{sec_num} {component_display}",
            1,
            "component",
            children=comp_children,
        ))

    # Code Metrics section
    metrics_sec_num = len(sorted_components) + 2
    sections.append(_sec(
        f"s{metrics_sec_num}",
        str(metrics_sec_num),
        f"{metrics_sec_num} Code Metrics, Coding Rule, Test Coverage",
        1,
        "metrics",
        content="[Code metrics, coding rules and test coverage.]",
    ))

    # Appendix A
    sections.append(_sec(
        "s_appendix_a",
        "A",
        "Appendix A. Design Guideline",
        1,
        "appendix",
        content="[Design guidelines.]",
    ))

    cover = {
        "project_name": project_name,
        "subtitle": f"Software Detailed Design Specification — {cover_group}",
        "version": version_tag,
        "document_name": doc_name or f"{cover_group} SDD",
        "document_process": doc_process,
        "layer": layer,
        "group": group,
    }

    return {
        "cover": cover,
        "toc": _build_toc(sections),
        "sections": sections,
        "meta": {
            "pipeline_data_available": True,
            "model_data_available": True,
            "source": "pipeline",
            "components": sorted_components,
            "layers": [],
            "units_total": sum(len(v) for v in by_component.values()),
            "functions_total": sum(
                sum(1 for i in interfaces if i.get("type") != "Global Variable")
                for units in by_component.values()
                for _, _, interfaces in units
            ),
            "globals_total": sum(
                sum(1 for i in interfaces if i.get("type") == "Global Variable")
                for units in by_component.values()
                for _, _, interfaces in units
            ),
        },
    }


# ---------------------------------------------------------------------------
# Build from model data only (no interface_tables.json)
# ---------------------------------------------------------------------------

def _build_sections_from_model(
    project_name: str,
    group: str,
    layer: str,
    version_tag: str,
    reader: ModelReader,
    doc_name: str = "",
    doc_process: str = "SWE.3",
) -> dict:
    """
    Build document JSON purely from model/ data files, without needing
    output/interface_tables.json.  Used when the pipeline has run Phases 1-2
    but Phase 3 (views) hasn't completed yet.
    """
    metadata = reader.metadata
    if metadata.get("projectName"):
        project_name = metadata["projectName"]

    units_data = reader.units
    functions_data = reader.functions
    global_variables_data = reader.global_variables
    data_dictionary = reader.data_dictionary

    hidden_fids: set = {
        fid for fid, f in functions_data.items()
        if isinstance(f, dict) and f.get("hidden", False)
    }

    # Group units by component
    by_component: dict[str, list[str]] = {}
    for unit_key in units_data:
        parts = unit_key.split(_KEY_SEP, 1)
        comp = parts[0]
        # Optional group/layer filter
        unit_info = units_data[unit_key]
        if not isinstance(unit_info, dict):
            continue
        unit_layer = unit_info.get("layer") or unit_info.get("layerName") or ""
        if layer and unit_layer and unit_layer != layer:
            continue
        by_component.setdefault(comp, []).append(unit_key)

    # If group filter is set, restrict to components in that group
    if group:
        components_config = reader.components
        group_components: set = set()
        for comp_name, comp_data in components_config.items():
            if not isinstance(comp_data, dict):
                continue
            comp_group = comp_data.get("group") or comp_data.get("groupName") or ""
            if comp_group == group or not comp_group:
                group_components.add(comp_name)
        if group_components:
            by_component = {
                k: v for k, v in by_component.items() if k in group_components
            }

    sorted_components = sorted(by_component.keys())
    cover_group = (
        f"{layer} {group}".strip() if (layer and group) else (group or "All Components")
    )

    # Introduction
    intro_sec = _sec(
        "s1", "1", "1 Introduction", 1, "introduction",
        children=[
            _sec("s1_1", "1.1", "1.1 Purpose", 2, "purpose",
                 content=f"This document describes the Software Detailed Design for {project_name}."),
            _sec("s1_2", "1.2", "1.2 Scope", 2, "scope",
                 content="\n".join(
                     [f"This document covers the {cover_group} component(s) of {project_name}.", "",
                      "Components in scope:"]
                     + [f"• {c.replace('-', ' ')}" for c in sorted_components]
                 )),
            _sec("s1_3", "1.3", "1.3 Terms, Abbreviations and Definitions", 2, "terms",
                 content="[Terms, abbreviations and definitions.]"),
        ],
    )
    sections = [intro_sec]

    for sec_idx, component_name in enumerate(sorted_components):
        sec_num = sec_idx + 2
        component_display = component_name.replace("-", " ")
        comp_sec_id = f"s{sec_num}"
        comp_children: list = []

        unit_keys = sorted(by_component[component_name])
        unit_rows: list[tuple] = []
        for uk in unit_keys:
            ui = units_data.get(uk) or {}
            unit_display = ui.get("unitName") or (
                uk.split(_KEY_SEP)[-1] if _KEY_SEP in uk else uk
            )
            interfaces = _build_interface_rows_from_model(
                uk, functions_data, global_variables_data, hidden_fids
            )
            unit_rows.append((uk, unit_display, interfaces))

        # N.1 Static Design
        static_children: list = []

        # Component-unit overview table
        cu_rows = [
            {
                "unit": udisp,
                "description": (
                    "; ".join(
                        list(dict.fromkeys(
                            " ".join((i.get("description") or "").split())
                            for i in interfaces
                            if (i.get("description") or "").strip() not in ("", "-", "N/A")
                        ))
                    )[:120] or "N/A"
                ),
                "note": "N/A",
            }
            for _, udisp, interfaces in unit_rows
        ]
        static_children.append(_sec(
            f"s{sec_num}_1_overview",
            f"{sec_num}.1.0",
            f"{sec_num}.1 Component Overview",
            3,
            "component_overview",
            table=_component_unit_table(component_display, cu_rows),
        ))

        # Per-unit subsections
        for unit_idx, (unit_key, unit_name_display, interfaces) in enumerate(unit_rows, start=1):
            unit_sec_id = f"s{sec_num}_1_{unit_idx}"
            unit_info = units_data.get(unit_key, {})

            header_rows = _build_unit_header_rows_from_model(
                unit_info, global_variables_data, data_dictionary
            )

            fn_sections: list = []
            fn_interfaces = [i for i in interfaces if i.get("type") != "Global Variable"]
            for iface_idx, iface in enumerate(fn_interfaces, start=3):
                func_name = iface.get("name", "")
                iface_sec_id = f"{unit_sec_id}_{iface_idx}"

                iface_params = ", ".join(
                    f"{p.get('type', '')} {p.get('name', '')}".strip()
                    for p in (iface.get("parameters") or [])
                )
                iface_return = iface.get("returnType", "") or ""
                iface_signature = f"{iface_return} {func_name}({iface_params})".strip()

                fn_func_data = functions_data.get(iface.get("functionId", "")) or {}
                input_label = (fn_func_data.get("behaviourInputName") or "").strip()
                output_label = (fn_func_data.get("behaviourOutputName") or "").strip()

                fn_sec = _sec(
                    iface_sec_id,
                    f"{sec_num}.1.{unit_idx}.{iface_idx}",
                    f"{sec_num}.1.{unit_idx}.{iface_idx} {unit_name_display}-{func_name}",
                    4,
                    "flowchart",
                    content=iface.get("description", "") or "-",
                    table={
                        "type": "flowchart",
                        "function_name": func_name,
                        "signature": iface_signature,
                        "input_label": input_label,
                        "output_label": output_label,
                        "flowcharts": [],  # no flowchart output yet at this stage
                    },
                )
                fn_sections.append(fn_sec)

            unit_sec = _sec(
                unit_sec_id,
                f"{sec_num}.1.{unit_idx}",
                f"{sec_num}.1.{unit_idx} {unit_name_display}",
                3,
                "unit",
                children=[
                    _sec(
                        f"{unit_sec_id}_1",
                        f"{sec_num}.1.{unit_idx}.1",
                        f"{sec_num}.1.{unit_idx}.1 unit header",
                        4,
                        "unit_header",
                        table=_unit_header_table(header_rows) if header_rows else None,
                        content=None if header_rows else "NA",
                    ),
                    _sec(
                        f"{unit_sec_id}_2",
                        f"{sec_num}.1.{unit_idx}.2",
                        f"{sec_num}.1.{unit_idx}.2 unit interface",
                        4,
                        "unit_interface",
                        table=_interface_table(interfaces),
                    ),
                ] + fn_sections,
            )
            static_children.append(unit_sec)

        comp_children.append(_sec(
            f"{comp_sec_id}_1",
            f"{sec_num}.1",
            f"{sec_num}.1 Static Design",
            2,
            "static_design",
            children=static_children,
        ))

        # N.2 Dynamic Behaviour (model-only: no behaviour PNGs)
        comp_children.append(_sec(
            f"{comp_sec_id}_2",
            f"{sec_num}.2",
            f"{sec_num}.2 Dynamic Behaviour",
            2,
            "dynamic_behaviour",
            children=[],
        ))

        sections.append(_sec(
            comp_sec_id,
            str(sec_num),
            f"{sec_num} {component_display}",
            1,
            "component",
            children=comp_children,
        ))

    metrics_sec_num = len(sorted_components) + 2
    sections.append(_sec(
        f"s{metrics_sec_num}",
        str(metrics_sec_num),
        f"{metrics_sec_num} Code Metrics, Coding Rule, Test Coverage",
        1,
        "metrics",
        content="[Code metrics, coding rules and test coverage.]",
    ))
    sections.append(_sec(
        "s_appendix_a",
        "A",
        "Appendix A. Design Guideline",
        1,
        "appendix",
        content="[Design guidelines.]",
    ))

    cover = {
        "project_name": project_name,
        "subtitle": f"Software Detailed Design Specification — {cover_group}",
        "version": version_tag,
        "document_name": doc_name or f"{cover_group} SDD",
        "document_process": doc_process,
        "layer": layer,
        "group": group,
    }

    return {
        "cover": cover,
        "toc": _build_toc(sections),
        "sections": sections,
        "meta": {
            "pipeline_data_available": False,
            "model_data_available": True,
            "source": "model",
            "components": sorted_components,
            "layers": reader.list_layer_names(),
            "units_total": sum(len(v) for v in by_component.values()),
            "functions_total": len([
                f for f in functions_data.values()
                if isinstance(f, dict) and not f.get("hidden", False)
            ]),
            "globals_total": len(global_variables_data),
        },
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def prepare_from_model(
    *,
    model_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    group: str = "",
    layer: str = "",
    version_tag: str = "v1.0.0",
    project_name: str = "",
    doc_name: str = "",
    doc_process: str = "SWE.3",
) -> dict:
    """
    Build a structured document JSON directly from model/ and output/ data.

    This is the primary entry point for ``POST /api/v1/model/prepare-document``
    and ``GET /api/v1/projects/{id}/documents/{doc_id}/prepare``.

    Parameters
    ----------
    model_dir
        Path to the ``model/`` directory.  Auto-detected if None.
    output_dir
        Path to the ``output/`` directory.  Auto-detected if None.
    group
        Group name (e.g. ``"Sample"`` or ``"Platform"``).  When empty, all
        components are included.
    layer
        Layer name (e.g. ``"Layer1"``).  Used for filtering and cover page.
    version_tag
        Version string to display on the cover page.
    project_name
        Override project name; defaults to ``metadata.json → projectName``.
    doc_name
        Document name for the cover page.
    doc_process
        Process identifier (``"SWE.3"`` by default).

    Returns
    -------
    dict
        Full structured document JSON with cover, toc, sections, and meta.
        Structure is identical to ``document_renderer.build_document_structure``
        with ``?structured=true``.
    """
    root = _find_root()
    if model_dir is None:
        model_dir = root / "model"
    if output_dir is None:
        output_dir = root / "output"

    reader = ModelReader(model_dir=model_dir)

    # Determine project name
    if not project_name:
        project_name = reader.project_name() or "Unknown Project"

    # Try to load pipeline artefacts first (Phase 3 output)
    iface_tables = _load_interface_tables(output_dir, group)

    if iface_tables is not None:
        # Phase 3 output available — use it for rich interface data
        behaviour_rows = _load_behaviour_pngs(output_dir, group)
        flowcharts_map = _load_flowcharts(output_dir, group)

        return _build_sections_from_pipeline(
            project_name=project_name,
            group=group,
            layer=layer,
            version_tag=version_tag,
            iface_tables=iface_tables,
            behaviour_rows=behaviour_rows,
            flowcharts_map=flowcharts_map,
            units_data=reader.units,
            functions_data=reader.functions,
            global_variables_data=reader.global_variables,
            data_dictionary=reader.data_dictionary,
            metadata=reader.metadata,
            doc_name=doc_name,
            doc_process=doc_process,
        )
    else:
        # No Phase 3 output — build directly from model/ data
        return _build_sections_from_model(
            project_name=project_name,
            group=group,
            layer=layer,
            version_tag=version_tag,
            reader=reader,
            doc_name=doc_name,
            doc_process=doc_process,
        )


def prepare_document(
    doc,
    db,
    project_id: str,
    *,
    root: Optional[Path] = None,
) -> dict:
    """
    Build the structured document JSON for an existing Document DB record.

    This wraps ``prepare_from_model`` using the document's group, layer,
    and version as inputs.  It is called by the ``?prepare=true`` query
    parameter on the document detail endpoint.

    Parameters
    ----------
    doc
        The ``Document`` domain object from the DB.
    db
        Database adapter (used to resolve project name and version tag).
    project_id
        Project ID for resolving project metadata.
    root
        Project root path.  Auto-detected if None.

    Returns
    -------
    dict
        Full structured document JSON.
    """
    if root is None:
        root = _find_root()
    root = Path(root)

    project = db.projects.get(project_id)
    project_name = project.name if project else doc.project_id
    version_obj = db.versions.get(doc.version_id)
    version_tag = version_obj.tag if version_obj else doc.version_id

    result = prepare_from_model(
        model_dir=root / "model",
        output_dir=root / "output",
        group=doc.group or "",
        layer=doc.layer or "",
        version_tag=version_tag,
        project_name=project_name,
        doc_name=doc.name,
        doc_process=doc.process,
    )

    return result
