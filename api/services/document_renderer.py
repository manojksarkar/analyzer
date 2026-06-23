"""
Document renderer — builds a structured JSON document tree that mirrors
the layout produced by src/docx_exporter.py.

The output is consumed by the UI renderer and represents the full SDD
(Software Detailed Design) document hierarchy:

  cover          — project name, group, subtitle, version
  toc            — list of {number, title, level, anchor}
  sections       — list of Section nodes (recursive)

Each Section node has:
  id             — anchor / unique key
  number         — "1", "2.1", "2.1.3" …
  title          — full heading string
  level          — 1–4
  type           — "introduction" | "static_design" | "unit_header" |
                   "unit_interface" | "flowchart" | "dynamic_behaviour" |
                   "metrics" | "appendix" | "component_overview" |
                   "scope" | "terms" | "purpose" | "behaviour_entry"
  content        — nullable string (markdown / plain text)
  table          — nullable structured table (type-specific)
  review_state   — "accepted" | "declined" | "edited" | null
  reviewed_by    — user id | null
  reviewed_at    — ISO datetime | null
  children       — list of nested Section nodes

When pipeline output files (output/interface_tables.json, output/
behaviour_diagrams/_behaviour_pngs.json, output/flowcharts/*.json,
model/*.json) are present the renderer populates rich content from
them.  When they are absent it falls back to the flat sections stored
in the DB (what the reviewer typed in), keeping the endpoint always
usable.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

# Interface-table column order (matches docx_exporter.COLS)
_IFACE_COLS = (
    "Interface ID", "Interface Name", "Information",
    "Data Type", "Data Range", "Direction(In/Out)",
    "Source/Destination", "Interface Type",
)

_KEY_SEP = "|"   # matches utils.KEY_SEP


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
# Section node builder helpers
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
    node = {
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
    return node


# ---------------------------------------------------------------------------
# Interface table builder
# ---------------------------------------------------------------------------

def _iface_table(interfaces: list[dict]) -> dict:
    """Build a structured table dict matching the DOCX interface table layout."""
    rows = []
    for iface in interfaces:
        iface_type = iface.get("type", "") or "-"
        if "variableType" in iface:
            data_type = iface.get("variableType", "") or "-"
            data_range = iface.get("range", "") or "NA"
        else:
            params = iface.get("parameters", []) or []
            data_type = "; ".join(p.get("type", "") for p in params) if params else "VOID"
            data_range = "; ".join(p.get("range", "") for p in params) if params else "NA"

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


def _unit_header_table(header_rows: list[dict]) -> dict:
    return {
        "type": "unit_header_table",
        "columns": ["global variables / typedef / enum / define", "information"],
        "rows": [
            {"declaration": r.get("declaration", ""), "information": r.get("information", "")}
            for r in header_rows
        ],
    }


def _component_unit_table(component_name: str, unit_rows: list[dict]) -> dict:
    """
    Component-level unit index table.
    unit_rows = [{unit_name, description, note}]
    """
    return {
        "type": "component_unit_table",
        "columns": ["Component", "Unit", "Description", "Note"],
        "component": component_name,
        "rows": unit_rows,
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
    """Try group-specific then generic interface_tables.json."""
    candidates = []
    if group:
        candidates.append(output_dir / group / "interface_tables.json")
    candidates.append(output_dir / "interface_tables.json")
    for p in candidates:
        data = _load_json(p)
        if data:
            return data
    return None


def _load_behaviour_pngs(output_dir: Path, group: str) -> dict:
    candidates = []
    if group:
        candidates.append(output_dir / group / "behaviour_diagrams" / "_behaviour_pngs.json")
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
        candidates.append(output_dir / group / "flowcharts")
    candidates.append(output_dir / "flowcharts")
    for flowcharts_dir in candidates:
        if not flowcharts_dir.is_dir():
            continue
        result = {}
        for fname in os.listdir(flowcharts_dir):
            if not fname.endswith(".json"):
                continue
            unit_name = fname[:-5]
            data = _load_json(flowcharts_dir / fname)
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


def _load_model_file(model_dir: Path, name: str) -> dict:
    data = _load_json(model_dir / f"{name}.json")
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# Helper: build unit header rows from model data
# ---------------------------------------------------------------------------

def _build_unit_header_rows(
    unit_info: dict,
    global_variables_data: dict,
    data_dictionary: dict,
) -> list[dict]:
    """
    Extract globals / typedefs / enums / defines visible in this unit.
    Mirrors the logic in docx_exporter._build_unit_header_table but
    without file-reading (we only have what's in the model JSON).
    """
    rows: list[dict] = []
    dd = data_dictionary or {}

    # Global variables
    for gid in unit_info.get("globalVariableIds", []) or []:
        g = (global_variables_data or {}).get(gid) or {}
        if (g.get("visibility") or "").lower() == "private":
            continue
        name = g.get("qualifiedName") or g.get("name") or str(gid)
        info = g.get("value") or "N/A"
        rows.append({"declaration": name, "information": str(info)})

    # typedef / enum / define from data dictionary
    unit_paths = set()
    path = unit_info.get("path")
    if path:
        paths = path if isinstance(path, list) else [path]
        for p in paths:
            unit_paths.add(os.path.splitext(p.replace("\\", "/"))[0])

    for type_name, t in dd.items():
        loc = t.get("location") or {}
        rel_file = (loc.get("file") or "").replace("\\", "/")
        type_file = os.path.splitext(rel_file)[0]
        if not type_file or type_file not in unit_paths:
            continue
        kind = t.get("kind", "")
        if kind not in ("typedef", "enum", "define"):
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
        else:
            info = t.get("underlyingType") or "N/A"

        rows.append({"declaration": str(decl), "information": str(info)})

    # Deduplicate
    seen = {}
    for r in rows:
        key = (r.get("declaration") or "").strip()
        if key not in seen:
            seen[key] = r
    return list(seen.values())


# ---------------------------------------------------------------------------
# Core renderer
# ---------------------------------------------------------------------------

def build_document_structure(
    doc,
    db,
    project_id: str,
    *,
    root: Optional[Path] = None,
) -> dict:
    """
    Build the full structured document tree for one Document domain object.

    Returns a dict:
    {
      "cover":    {...},
      "toc":      [...],
      "sections": [...],
      "meta": {
        "pipeline_data_available": bool,
        "source": "pipeline" | "stored_sections"
      }
    }
    """
    if root is None:
        root = _find_root()
    root = Path(root)
    output_dir = root / "output"
    model_dir = root / "model"

    # Metadata
    project = db.projects.get(project_id)
    project_name = project.name if project else doc.project_id
    group = doc.group or ""
    layer = doc.layer or ""
    version_obj = db.versions.get(doc.version_id)
    version_tag = version_obj.tag if version_obj else doc.version_id

    # Try to load pipeline artefacts
    iface_tables = _load_interface_tables(output_dir, group)
    pipeline_available = iface_tables is not None

    behaviour_rows = _load_behaviour_pngs(output_dir, group)
    flowcharts_map = _load_flowcharts(output_dir, group)
    metadata = _load_model_file(model_dir, "metadata")
    units_data = _load_model_file(model_dir, "units")
    functions_data = _load_model_file(model_dir, "functions")
    global_variables_data = _load_model_file(model_dir, "globalVariables")
    data_dictionary = _load_model_file(model_dir, "dataDictionary")

    if pipeline_available:
        return _build_from_pipeline(
            doc, db, project_name, group, layer, version_tag,
            iface_tables, behaviour_rows, flowcharts_map,
            units_data, functions_data, global_variables_data,
            data_dictionary, metadata,
        )
    else:
        return _build_from_stored_sections(doc, db, project_name, group, layer, version_tag)


# ---------------------------------------------------------------------------
# Build from pipeline output (interface_tables.json + model files)
# ---------------------------------------------------------------------------

def _build_from_pipeline(
    doc, db, project_name: str, group: str, layer: str, version_tag: str,
    iface_tables: dict,
    behaviour_rows: dict,
    flowcharts_map: dict,
    units_data: dict,
    functions_data: dict,
    global_variables_data: dict,
    data_dictionary: dict,
    metadata: dict,
) -> dict:
    # Resolve project name from metadata (pipeline may use base path name)
    if metadata.get("projectName"):
        project_name = metadata["projectName"]

    # Collect hidden function IDs
    hidden_fids: set = {fid for fid, f in functions_data.items() if f.get("hidden", False)}

    # Group units by component (same logic as docx_exporter)
    by_component: dict[str, list] = {}
    unit_names_map: dict = iface_tables.get("unitNames", {})

    for unit_key, unit_data in iface_tables.items():
        if unit_key in ("basePath", "projectName", "unitNames"):
            continue
        if not isinstance(unit_data, dict) or "entries" not in unit_data:
            continue
        parts = unit_key.split(_KEY_SEP, 1)
        component_name = parts[0]
        unit_name_display = unit_data.get("name", unit_key.split(_KEY_SEP)[-1] if _KEY_SEP in unit_key else unit_key)
        interfaces = [
            i for i in unit_data["entries"]
            if i.get("functionId") not in hidden_fids
        ]
        by_component.setdefault(component_name, []).append((unit_key, unit_name_display, interfaces))

    sorted_components = sorted(by_component.keys())

    # Cover
    cover_group = f"{layer} {group}".strip() if (layer and group) else (group or "All Components")
    cover = {
        "project_name": project_name,
        "subtitle": f"Software Detailed Design Specification — {cover_group}",
        "version": version_tag,
        "document_name": doc.name,
        "document_process": doc.process,
        "layer": layer,
        "group": group,
    }

    # Build section tree
    sections = []

    # --- Section 1: Introduction ---
    intro_sec = _sec("s1", "1", "1 Introduction", 1, "introduction",
                     children=[
                         _sec("s1_1", "1.1", "1.1 Purpose", 2, "purpose",
                              content=f"This document describes the Software Detailed Design for {project_name}."),
                         _sec("s1_2", "1.2", "1.2 Scope", 2, "scope",
                              content="\n".join([
                                  f"This document covers the {cover_group} component(s) of {project_name}.",
                                  "",
                                  "Components in scope:",
                              ] + [f"• {c.replace('-', ' ')}" for c in sorted_components])),
                         _sec("s1_3", "1.3", "1.3 Terms, Abbreviations and Definitions", 2, "terms",
                              content="[Terms, abbreviations and definitions.]"),
                     ])
    sections.append(intro_sec)

    # --- Sections 2…N: Per-component ---
    for sec_idx, component_name in enumerate(sorted_components):
        sec_num = sec_idx + 2
        component_display = component_name.replace("-", " ")
        comp_sec_id = f"s{sec_num}"
        comp_children = []

        unit_rows_component = sorted(by_component[component_name])

        # N.1 Static Design
        static_children = []

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
        for unit_idx, (unit_key, unit_name_display, interfaces) in enumerate(unit_rows_component, start=1):
            unit_sec_id = f"s{sec_num}_1_{unit_idx}"
            unit_info = units_data.get(unit_key, {})

            # Unit header rows
            header_rows = _build_unit_header_rows(unit_info, global_variables_data, data_dictionary)

            # Flowchart lookup prefix
            unit_name_flowchart = unit_key.split(_KEY_SEP)[-1] if _KEY_SEP in unit_key else unit_name_display
            unit_prefix = unit_key.replace(_KEY_SEP, "_").replace(" ", "_")

            # Per-function flowchart sections
            fn_sections = []
            rendered_private_fids: set = set()
            for iface_idx, iface in enumerate(
                (i for i in interfaces if i.get("type") != "Global Variable"), start=3
            ):
                func_name = iface.get("name", "")
                iface_sec_id = f"{unit_sec_id}_{iface_idx}"

                flowchart = (
                    flowcharts_map.get(unit_prefix, {}).get(func_name)
                    or flowcharts_map.get(unit_name_flowchart, {}).get(func_name)
                ) if func_name else None

                # Parameters and signature
                iface_params = ", ".join(
                    f"{p.get('type', '')} {p.get('name', '')}".strip()
                    for p in (iface.get("parameters") or [])
                )
                iface_return = iface.get("returnType", "") or ""
                iface_signature = f"{iface_return} {func_name}({iface_params})".strip()

                fn_func_data = functions_data.get(iface.get("functionId", "")) or {}
                input_label = (fn_func_data.get("behaviourInputName") or "").strip()
                output_label = (fn_func_data.get("behaviourOutputName") or "").strip()

                flowcharts_payload = []
                if flowchart:
                    png_key = f"{unit_prefix}_{func_name}"
                    flowcharts_payload.append({
                        "signature": iface_signature,
                        "mermaid": flowchart,
                        "png_key": png_key,
                    })

                # Private callee flowcharts
                callee_fids = fn_func_data.get("callsIds") or []
                for callee_fid in callee_fids:
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
                    callee_flowchart = (
                        flowcharts_map.get(callee_unit_prefix, {}).get(callee_func_name)
                        or flowcharts_map.get(callee_unit_name, {}).get(callee_func_name)
                    )
                    if not callee_flowchart:
                        continue
                    callee_params = ", ".join(
                        f"{p.get('type', '')} {p.get('name', '')}".strip()
                        for p in (callee.get("params") or callee.get("parameters") or [])
                    )
                    callee_return = callee.get("returnType", "")
                    callee_signature = f"{callee_return} {callee_func_name}({callee_params})".strip()
                    flowcharts_payload.append({
                        "signature": callee_signature,
                        "mermaid": callee_flowchart,
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
                        table=_iface_table(interfaces),
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
        beh_children = []
        beh_idx = 0
        comp_beh_data = behaviour_rows.get(component_name) or {}
        for unit_name, entries in sorted(comp_beh_data.items()):
            for row in entries:
                current_fn = row.get("currentFunctionName", "") or ""
                beh_idx += 1
                ext = row.get("externalUnitFunction", "")
                subheader = f"{unit_name} - {current_fn}"
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

    toc = _build_toc(sections)

    return {
        "cover": cover,
        "toc": toc,
        "sections": sections,
        "meta": {
            "pipeline_data_available": True,
            "source": "pipeline",
            "components": sorted_components,
        },
    }


# ---------------------------------------------------------------------------
# Build from stored sections (fallback when pipeline hasn't run)
# ---------------------------------------------------------------------------

def _build_from_stored_sections(
    doc, db, project_name: str, group: str, layer: str, version_tag: str,
) -> dict:
    """
    Fallback: reconstruct a document from the flat DocumentSection records
    stored in the DB (e.g. what the reviewer typed in the UI).

    The stored sections use keys like "intro", "interfaces", "static_design",
    "dynamic_design" that map to the top-level DOCX sections.
    """
    stored = db.documents.list_sections(doc.id)

    cover_group = f"{layer} {group}".strip() if (layer and group) else (group or "All Components")
    cover = {
        "project_name": project_name,
        "subtitle": f"Software Detailed Design Specification — {cover_group}",
        "version": version_tag,
        "document_name": doc.name,
        "document_process": doc.process,
        "layer": layer,
        "group": group,
    }

    # Map stored section_key -> standard type
    _KEY_TO_TYPE = {
        "intro": "introduction",
        "interfaces": "unit_interface",
        "static_design": "static_design",
        "dynamic_design": "dynamic_behaviour",
        "requirements": "purpose",
    }

    sections = []
    for idx, s in enumerate(sorted(stored, key=lambda x: x.order), start=1):
        sec_type = _KEY_TO_TYPE.get(s.section_key, "introduction")

        # Parse markdown table content into structured table for interface sections
        table = None
        if s.section_key == "interfaces":
            table = _parse_markdown_table(s.content)

        sections.append(_sec(
            f"stored_{s.id}",
            str(idx),
            s.title,
            2,
            sec_type,
            content=s.content,
            table=table,
            review_state=s.review_state,
            reviewed_by=s.reviewed_by,
            reviewed_at=s.reviewed_at.isoformat() if s.reviewed_at else None,
        ))

    toc = _build_toc(sections)
    return {
        "cover": cover,
        "toc": toc,
        "sections": sections,
        "meta": {
            "pipeline_data_available": False,
            "source": "stored_sections",
            "components": [],
        },
    }


def _parse_markdown_table(content: str) -> Optional[dict]:
    """
    Parse a markdown table string into a structured table dict.
    Returns None if content doesn't look like a table.
    """
    if not content or "|" not in content:
        return None
    lines = [l.strip() for l in content.strip().splitlines() if l.strip()]
    if len(lines) < 2:
        return None
    # First line = headers; second line = separator; rest = rows
    header_line = lines[0]
    if not header_line.startswith("|"):
        return None
    cols = [c.strip() for c in header_line.strip("|").split("|")]
    rows = []
    for line in lines[2:]:   # skip separator
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        row = {}
        for i, col in enumerate(cols):
            row[col.lower().replace(" ", "_")] = cells[i] if i < len(cells) else ""
        rows.append(row)
    return {"type": "markdown_table", "columns": cols, "rows": rows}


# ---------------------------------------------------------------------------
# TOC builder
# ---------------------------------------------------------------------------

def _build_toc(sections: list[dict]) -> list[dict]:
    """Flatten the section tree into a TOC entry list."""
    toc = []

    def _walk(nodes):
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
