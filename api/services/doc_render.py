"""Rich document render — builds the {cover, toc, sections, meta} payload
from real analyzer output under ``output/<group>/``.

The section hierarchy mirrors ``src/docx_exporter.py`` exactly:
  1 Introduction
    1.1 Purpose  /  1.2 Scope  /  1.3 Terms, Abbreviations and Definitions
  N ComponentName
    N.1 Static Design
      [container diagram]  [dependency diagram]  [component/unit table]
      N.1.1 UnitName
        N.1.1.1 unit header   (global vars / typedefs / enums / defines)
        N.1.1.2 unit interface (8-column interface table)
        N.1.1.3 UnitName-FuncName   (flowchart_table section)
        …
    N.2 Dynamic Behaviour
      N.2.1 UnitName - FuncName  (behavior_table section)
  M Code Metrics, Coding Rule, Test Coverage
  Appendix A Design Guideline

When no live output exists for a group, the caller (routes/documents.py)
falls back to a synthesised payload built from stored section bodies.
"""
from __future__ import annotations
import json
import re as _re
from pathlib import Path
from typing import Any, Optional

from .settings import get_settings as _get_settings
_REPO_ROOT = _get_settings().repo_root
OUTPUT_ROOT = _REPO_ROOT / "output"

KEY_SEP = "|"
_INCLUDE_GUARD_RE = _re.compile(r"^_*[A-Z][A-Z0-9_]*(?:_H|_HPP)_*$")


# ── output dir lookup (path-traversal safe) ──────────────────────────────────

def output_group_dir(group: Optional[str]) -> Optional[Path]:
    """The live output dir for ``group`` if it exists and is safely inside OUTPUT_ROOT."""
    if not group or not OUTPUT_ROOT.is_dir():
        return None
    d = (OUTPUT_ROOT / group).resolve()
    if d.is_dir() and (d == OUTPUT_ROOT or OUTPUT_ROOT in d.parents):
        return d
    return None


def resolve_asset(group: Optional[str], asset_path: str) -> Optional[Path]:
    """Resolve ``<group>/<asset_path>`` inside the live output, or None if unsafe/absent."""
    base = output_group_dir(group)
    if not base:
        return None
    target = (base / asset_path).resolve()
    if target.is_file() and base in target.parents:
        return target
    return None


def find_docx(group: Optional[str]) -> Optional[Path]:
    """Return the real DOCX path for ``group`` if it exists."""
    if not group:
        return None
    base = output_group_dir(group)
    if not base:
        return None
    p = base / f"software_detailed_design_{group}.docx"
    return p if p.is_file() else None


# ── small utilities ───────────────────────────────────────────────────────────

def _readable_label(name: str) -> str:
    """Convert an identifier like 'g_readWrite' into a human label (mirrors docx_exporter)."""
    if not name:
        return ""
    for prefix in ("g_", "s_", "t_"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    name = name.replace("_", " ")
    if len(name.strip()) <= 2:
        return ""
    return name[:1].upper() + name[1:] if name else ""


def _safe_fn(name: str) -> str:
    """Filename-safe version of a function name (mirrors utils.safe_filename)."""
    name = name.replace(" ", "-")
    return _re.sub(r"[^\w\-.]", "_", name)


def _strip_jsonc(text: str) -> str:
    """Strip // and /* */ comments + trailing commas from JSONC."""
    text = _re.sub(r"//[^\n]*", "", text)
    text = _re.sub(r"/\*.*?\*/", "", text, flags=_re.DOTALL)
    text = _re.sub(r",\s*([}\]])", r"\1", text)
    return text


# ── model / config loaders ────────────────────────────────────────────────────

def _load_model_json(model_dir: Path, name: str) -> dict:
    p = model_dir / f"{name}.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_config() -> dict:
    cfg: dict = {}
    for fname in ("config.json", "config.local.json"):
        p = _REPO_ROOT / "config" / fname
        if not p.exists():
            continue
        try:
            text = _strip_jsonc(p.read_text(encoding="utf-8"))
            chunk = json.loads(text)
            _deep_merge(cfg, chunk)
        except Exception:
            pass
    return cfg


def _deep_merge(base: dict, override: dict) -> None:
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def _load_abbreviations(config: dict) -> dict:
    path = (config.get("llm") or {}).get("abbreviationsPath", "").strip()
    if not path:
        return {}
    full_path = Path(path) if Path(path).is_absolute() else _REPO_ROOT / path
    if not full_path.is_file():
        return {}
    result: dict = {}
    try:
        for line in full_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                k, _, v = line.partition(":")
            elif "=" in line:
                k, _, v = line.partition("=")
            else:
                continue
            k, v = k.strip(), v.strip()
            if k:
                result[k] = v
    except OSError:
        pass
    return result


# ── unit header table builder (model-only, no source file reads) ──────────────

def _build_unit_header_rows(
    unit_info: dict,
    data_dictionary: dict,
    global_variables_data: dict,
) -> list[dict]:
    """Build unit-header rows from model data (no source file access required)."""
    rows: list[dict] = []
    dd = data_dictionary or {}

    # Collect the unit's source-file paths (without extension) for DD matching
    path = unit_info.get("path") or ""
    if isinstance(path, list):
        unit_paths: set[str] = {p.replace("\\", "/").rsplit(".", 1)[0] for p in path}
    elif path:
        unit_paths = {path.replace("\\", "/").rsplit(".", 1)[0]}
    else:
        unit_paths = set()

    # Public global variables
    for gid in (unit_info.get("globalVariableIds") or []):
        g = (global_variables_data or {}).get(gid) or {}
        if (g.get("visibility") or "").lower() == "private":
            continue
        decl = g.get("qualifiedName") or g.get("name") or str(gid) or "N/A"
        info = g.get("value") or "N/A"
        rows.append({"declaration": decl, "information": info})

    # typedefs / enums / defines from data dictionary
    _seen_typedef_locs: set = set()
    for type_name, t in dd.items():
        loc = t.get("location") or {}
        rel_file = (loc.get("file") or "").replace("\\", "/")
        type_file = rel_file.rsplit(".", 1)[0] if "." in rel_file else rel_file
        if not type_file or type_file not in unit_paths:
            continue
        kind = t.get("kind", "")
        if kind not in ("typedef", "enum", "define"):
            continue
        line = loc.get("line") or 0
        if kind == "typedef":
            loc_key = (rel_file, line)
            if loc_key in _seen_typedef_locs:
                continue
            _seen_typedef_locs.add(loc_key)

        if kind == "define":
            macro_name = t.get("name") or type_name or ""
            macro_value = t.get("value", "") or ""
            if not macro_value and _INCLUDE_GUARD_RE.match(macro_name):
                continue
            decl = t.get("text") or macro_name or "N/A"
            info = macro_value or "N/A"
            rows.append({"declaration": decl, "information": info})
            continue

        if kind == "typedef":
            decl = t.get("name") or type_name or "N/A"
            underlying = (t.get("underlyingType") or "").strip()
            enum_ent = dd.get(underlying)
            if isinstance(enum_ent, dict) and enum_ent.get("kind") == "enum":
                enums = enum_ent.get("enumerators") or []
                parts = []
                for e in enums:
                    n = e.get("name", "")
                    v = e.get("value")
                    if n:
                        parts.append(f"{n}={v}" if v is not None else n)
                info = ", ".join(parts) if parts else "N/A"
            else:
                info = "N/A"
        elif kind == "enum":
            decl = t.get("name") or type_name or "N/A"
            enums = t.get("enumerators") or []
            parts = []
            for e in enums:
                n = e.get("name", "")
                v = e.get("value")
                if n:
                    parts.append(f"{n}={v}" if v is not None else n)
            info = ", ".join(parts) if parts else "N/A"
        else:
            continue

        rows.append({"declaration": decl, "information": info})

    # Deduplicate preserving richest info
    dedup: dict = {}
    for r in rows:
        d = (r.get("declaration") or "N/A").strip()
        if d not in dedup:
            dedup[d] = r
    out = list(dedup.values())
    out.sort(key=lambda r: (r.get("declaration") or "").lower())
    return out


# ── flowchart / behavior-diagram loaders ─────────────────────────────────────

def _load_flowcharts_from_dir(flowcharts_dir: Path) -> dict:
    """Return {unit_prefix: {func_name: mermaid_str}}."""
    result: dict = {}
    if not flowcharts_dir.is_dir():
        return result
    for p in flowcharts_dir.iterdir():
        if p.suffix != ".json":
            continue
        stem = p.stem
        try:
            arr = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(arr, list):
                continue
            result[stem] = {}
            for item in arr:
                name = (item.get("name") or "").strip()
                flowchart = (item.get("flowchart") or "").strip()
                if name and flowchart:
                    result[stem][name] = flowchart
        except Exception:
            pass
    return result


def _load_behavior_diagrams(group_dir: Path) -> dict:
    """Return the _docxRows dict from behaviour_diagrams/_behaviour_pngs.json."""
    p = group_dir / "behaviour_diagrams" / "_behaviour_pngs.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("_docxRows", {})
    except Exception:
        return {}


# ── section helpers ───────────────────────────────────────────────────────────

def _sec(sid: str, number: str, title: str, level: int, *, type: str = "richtext",
         content: Any = None, table: Any = None, image_url: Any = None,
         mermaid: Any = None, children: Any = None,
         flowchart_table: Any = None, behavior_table: Any = None) -> dict:
    d: dict = {
        "id": sid, "number": number, "title": title, "level": level, "type": type,
        "content": content, "table": table, "image_url": image_url,
        "mermaid": mermaid, "children": children or [],
    }
    if flowchart_table is not None:
        d["flowchart_table"] = flowchart_table
    if behavior_table is not None:
        d["behavior_table"] = behavior_table
    return d


def _pngs(group_dir: Path, subdir: str, pred) -> list[str]:
    d = group_dir / subdir
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if p.suffix == ".png" and pred(p.name))


def _diagram_sec(asset_base: str, group_dir: Path, subdir: str, fn: str,
                 sid: str, number: str, title: str, level: int, caption: str) -> dict:
    rel = f"{subdir}/{fn}"
    mmd = (group_dir / subdir / fn).with_suffix(".mmd")
    return _sec(
        sid, number, title, level, type="diagram", content=caption,
        image_url=f"{asset_base}/{rel}",
        mermaid=mmd.read_text(encoding="utf-8") if mmd.exists() else None,
    )


def _flatten_toc(sections: list[dict]) -> list[dict]:
    """Flatten nested sections into a TOC list; skip unnumbered (diagram/table) entries."""
    out: list[dict] = []
    for s in sections:
        if s.get("number"):
            out.append({"id": s["id"], "number": s["number"], "title": s["title"], "level": s["level"]})
        out.extend(_flatten_toc(s["children"]))
    return out


# ── interfaces table (8-column, mirrors docx_exporter) ───────────────────────

def _interfaces_table_8col(ifaces: list) -> Optional[dict]:
    rows: list[list[str]] = []
    for iface in ifaces:
        iface_type = iface.get("type", "") or "-"
        if "variableType" in iface:
            data_type = iface.get("variableType", "") or "-"
            data_range = iface.get("range", "") or "NA"
        else:
            params = iface.get("parameters", []) or []
            data_type = "; ".join(p.get("type", "") for p in params) if params else "VOID"
            data_range = "; ".join(p.get("range", "") for p in params) if params else "NA"
        rows.append([
            str(iface.get("interfaceId", "")),
            str(iface.get("interfaceName") or iface.get("name", "")),
            str(iface.get("description", "") or "-"),
            data_type,
            data_range,
            str(iface.get("direction") or "-"),
            str(iface.get("sourceDest") or "-"),
            iface_type,
        ])
    if not rows:
        return None
    return {
        "headers": ["Interface ID", "Interface Name", "Information", "Data Type",
                    "Data Range", "Direction(In/Out)", "Source/Destination", "Interface Type"],
        "rows": rows,
    }


# ── main builder ──────────────────────────────────────────────────────────────

def build_render(doc, project, version, group_dir: Path, project_id: str,
                 *, model_root: Optional[Path] = None,
                 asset_base: Optional[str] = None) -> dict:
    """Build a rich {cover, toc, sections, meta} payload mirroring the DOCX structure.

    ``model_root`` overrides where model/*.json is read from (defaults to the live
    ``model/`` dir); ``asset_base`` overrides the URL prefix used for diagram assets
    (defaults to the live document-asset route). Both let the compare engine build
    a render from a per-version snapshot instead of the live working tree.
    """
    group = doc.group
    if asset_base is None:
        asset_base = f"projects/{project_id}/documents/{doc.id}/assets"

    # Load interface data
    itf: dict = {}
    itf_path = group_dir / "interface_tables.json"
    if itf_path.exists():
        itf = json.loads(itf_path.read_text(encoding="utf-8"))
    unit_names: dict[str, str] = itf.get("unitNames", {}) or {}

    # Group unit keys by component
    comps: dict[str, list[str]] = {}
    for uk in unit_names:
        comps.setdefault(uk.split(KEY_SEP, 1)[0], []).append(uk)

    # Load model files
    model_dir = model_root or (_REPO_ROOT / "model")
    units_data = _load_model_json(model_dir, "units")
    dd_data = _load_model_json(model_dir, "dataDictionary")
    globals_data = _load_model_json(model_dir, "globalVariables")
    functions_data = _load_model_json(model_dir, "functions")
    meta_data = _load_model_json(model_dir, "metadata")
    project_name = meta_data.get("projectName") or project.name

    # Load config + abbreviations
    config = _load_config()
    abbreviations = _load_abbreviations(config)
    intro_cfg = (config.get("docx") or {}).get("introduction") or {}
    purpose_text = intro_cfg.get("purpose", "[Purpose of this document.]")
    purpose_text = purpose_text.replace("{project_name}", project_name)
    scope_intro = intro_cfg.get("scopeIntro", "[Scope of the software detailed design.]")
    scope_intro = scope_intro.replace("{project_name}", project_name)
    scope_body = intro_cfg.get("scopeBody", "")
    scope_items: list[str] = intro_cfg.get("scopeItems") or []

    # Load flowcharts + behavior diagrams
    flowcharts_dir = group_dir / "flowcharts"
    flowcharts_map = _load_flowcharts_from_dir(flowcharts_dir)
    behavior_rows = _load_behavior_diagrams(group_dir)

    # Hidden functions
    hidden_fids: set = {fid for fid, f in functions_data.items() if f.get("hidden", False)}

    # Hidden functions by (component, unit) for behavior section filter
    _hidden_by_mod_unit: dict = {}
    for _fid in hidden_fids:
        _fp = _fid.split(KEY_SEP)
        if len(_fp) >= 3:
            _qn = (functions_data[_fid].get("qualifiedName") or "")
            _base = _qn.split("::")[-1] if _qn else _fp[2]
            _hidden_by_mod_unit.setdefault((_fp[0], _fp[1]), set()).add(_base)

    sorted_comps = sorted(comps.keys())

    # ── 1. Introduction ──────────────────────────────────────────────────────
    comp_bullets = "\n".join(f"• {c.replace('-', ' ')}" for c in sorted_comps)
    scope_text = scope_intro
    if comp_bullets:
        scope_text += "\n" + comp_bullets
    if scope_body:
        scope_text += "\n" + scope_body
    if scope_items:
        scope_text += "\n" + "\n".join(f"- {item}" for item in scope_items)

    if abbreviations:
        abbr_table = {
            "headers": ["Term", "Description"],
            "rows": [[k, v] for k, v in sorted(abbreviations.items())],
        }
        terms_sec = _sec("intro-terms", "1.3", "Terms, Abbreviations and Definitions", 2,
                         type="table", table=abbr_table)
    else:
        terms_sec = _sec("intro-terms", "1.3", "Terms, Abbreviations and Definitions", 2,
                         type="richtext", content="[Terms, abbreviations and definitions.]")

    intro_sec = _sec("intro", "1", "Introduction", 1, type="richtext", content=None, children=[
        _sec("intro-purpose", "1.1", "Purpose", 2, type="richtext", content=purpose_text),
        _sec("intro-scope", "1.2", "Scope", 2, type="richtext", content=scope_text),
        terms_sec,
    ])

    sections: list[dict] = [intro_sec]

    # ── 2+. Per component ────────────────────────────────────────────────────
    for comp_idx, comp in enumerate(sorted_comps):
        n = comp_idx + 2
        comp_display = comp.replace("-", " ")
        unit_keys = sorted(comps[comp])

        # Build (unit_key, display_name, interfaces) triples
        unit_rows: list[tuple] = []
        for uk in unit_keys:
            uname = unit_names.get(uk, uk.split(KEY_SEP)[-1])
            ifaces = [
                i for i in (itf.get(uk, {}) or {}).get("entries", []) or []
                if i.get("functionId") not in hidden_fids
            ]
            unit_rows.append((uk, uname, ifaces))

        # ── N.1 Static Design ────────────────────────────────────────────────
        static_children: list[dict] = []

        # Container diagram (unnumbered — not a heading in DOCX)
        for fn in _pngs(group_dir, "component_container_diagrams",
                        lambda nm, c=comp: nm == f"{c}.png"):
            static_children.append(_diagram_sec(
                asset_base, group_dir, "component_container_diagrams", fn,
                f"{comp}-container", "", "Component Structure", 2,
                f"Component structure for {comp_display}.",
            ))

        # Header dependency diagram (unnumbered)
        for fn in _pngs(group_dir, "component_header_dependency_diagrams",
                        lambda nm, c=comp: nm == f"{c}.png"):
            static_children.append(_diagram_sec(
                asset_base, group_dir, "component_header_dependency_diagrams", fn,
                f"{comp}-dep", "", "Include Dependencies", 2,
                f"Include dependencies for {comp_display}.",
            ))

        # Component / Unit / Description / Note summary table (unnumbered)
        comp_unit_rows: list[list[str]] = []
        for uk, uname, ifaces in unit_rows:
            fn_items: list[tuple] = []
            gv_items: list[tuple] = []
            for iface in ifaces:
                d = str(iface.get("description") or "").strip()
                if not d or d in ("-", "N/A"):
                    continue
                d_clean = " ".join(d.split())
                iname = (iface.get("interfaceName") or iface.get("name") or "").strip()
                if iface.get("type") == "Global Variable":
                    gv_items.append((iname, d_clean))
                else:
                    fn_items.append((iname, d_clean))
            seen_descs: set = set()
            all_descs: list[str] = []
            for _, d in fn_items + gv_items:
                if d not in seen_descs:
                    seen_descs.add(d)
                    all_descs.append(d)
            desc = "; ".join(all_descs)[:120] if all_descs else "N/A"
            comp_unit_rows.append([comp_display, uname, desc, "N/A"])

        if comp_unit_rows:
            static_children.append(_sec(
                f"{comp}-unit-table", "", "Component/Unit Table", 2,
                type="table",
                table={"headers": ["Component", "Unit", "Description", "Note"],
                       "rows": comp_unit_rows},
            ))

        # ── Per unit subsections ─────────────────────────────────────────────
        for unit_idx, (uk, uname, ifaces) in enumerate(unit_rows, start=1):
            unit_sec_num = f"{n}.1.{unit_idx}"
            unit_prefix = uk.replace(KEY_SEP, "_").replace(" ", "_")
            unit_name_fc = uk.split(KEY_SEP)[-1] if KEY_SEP in uk else uname
            unit_children: list[dict] = []

            # Unit diagram (unnumbered)
            for fn in _pngs(group_dir, "unit_diagrams",
                            lambda nm, p=f"{comp}_{uname}": nm == f"{p}.png"):
                unit_children.append(_diagram_sec(
                    asset_base, group_dir, "unit_diagrams", fn,
                    f"unit-{uk}", "", f"Unit — {uname}", 3,
                    f"Static structure of unit {uname}.",
                ))

            # N.1.U.1 unit header
            unit_info = units_data.get(uk) or {}
            header_rows = _build_unit_header_rows(unit_info, dd_data, globals_data)
            if header_rows:
                hdr_table = {
                    "headers": ["global variables / typedef / enum / define", "information"],
                    "rows": [[r.get("declaration", "N/A"), r.get("information", "N/A")]
                             for r in header_rows],
                }
                unit_children.append(_sec(f"{uk}-header", f"{unit_sec_num}.1", "unit header", 4,
                                          type="table", table=hdr_table))
            else:
                unit_children.append(_sec(f"{uk}-header", f"{unit_sec_num}.1", "unit header", 4,
                                          type="richtext", content="NA"))

            # N.1.U.2 unit interface (8-column)
            iface_table = _interfaces_table_8col(ifaces)
            if iface_table:
                unit_children.append(_sec(f"{uk}-iface", f"{unit_sec_num}.2", "unit interface", 4,
                                          type="table", table=iface_table))
            else:
                unit_children.append(_sec(f"{uk}-iface", f"{unit_sec_num}.2", "unit interface", 4,
                                          type="richtext", content="NA"))

            # N.1.U.3+ per function (functions only, starting at index 3)
            iface_idx = 3
            rendered_private_fids: set = set()
            for iface in (i for i in ifaces if i.get("type") != "Global Variable"):
                func_name = iface.get("name", "") or iface.get("interfaceName", "")
                if not func_name:
                    continue

                # Flowchart lookup (mirrors docx_exporter)
                fc_mermaid = (
                    flowcharts_map.get(unit_prefix, {}).get(func_name)
                    or flowcharts_map.get(unit_name_fc, {}).get(func_name)
                )
                flowchart_entries: list[dict] = []

                if fc_mermaid:
                    safe = _safe_fn(func_name)
                    png_rel: Optional[str] = f"flowcharts/{unit_prefix}_{safe}.png"
                    if not (group_dir / png_rel).is_file():
                        alt = f"flowcharts/{unit_name_fc}_{safe}.png"
                        png_rel = alt if (group_dir / alt).is_file() else None
                    params = iface.get("parameters") or []
                    params_str = ", ".join(
                        f"{p.get('type', '')} {p.get('name', '')}".strip() for p in params
                    )
                    ret = iface.get("returnType", "") or ""
                    signature = f"{ret} {func_name}({params_str})".strip()
                    flowchart_entries.append({
                        "image_url": (
                            f"{asset_base}/{png_rel}"
                            if png_rel else None
                        ),
                        "mermaid": fc_mermaid,
                        "label": signature,
                    })

                # Private callee flowcharts (mirrors docx_exporter)
                fid = iface.get("functionId")
                if fid and functions_data:
                    callee_fids = (functions_data.get(fid) or {}).get("callsIds") or []
                    for callee_fid in callee_fids:
                        if callee_fid in hidden_fids or callee_fid in rendered_private_fids:
                            continue
                        callee = functions_data.get(callee_fid) or {}
                        if (callee.get("visibility") or "").lower() != "private":
                            continue
                        callee_qn = callee.get("qualifiedName", "")
                        callee_fn = callee_qn.split("::")[-1] if callee_qn else ""
                        if not callee_fn:
                            continue
                        callee_parts = callee_fid.split(KEY_SEP)
                        c_unit_key = KEY_SEP.join(callee_parts[:2]) if len(callee_parts) >= 2 else ""
                        c_prefix = c_unit_key.replace(KEY_SEP, "_").replace(" ", "_")
                        c_unit_name = callee_parts[1] if len(callee_parts) > 1 else ""
                        callee_fc = (
                            flowcharts_map.get(c_prefix, {}).get(callee_fn)
                            or flowcharts_map.get(c_unit_name, {}).get(callee_fn)
                        )
                        if not callee_fc:
                            continue
                        rendered_private_fids.add(callee_fid)
                        csafe = _safe_fn(callee_fn)
                        cpng_rel: Optional[str] = f"flowcharts/{c_prefix}_{csafe}.png"
                        if not (group_dir / cpng_rel).is_file():
                            alt = f"flowcharts/{c_unit_name}_{csafe}.png"
                            cpng_rel = alt if (group_dir / alt).is_file() else None
                        callee_params = callee.get("params") or callee.get("parameters") or []
                        cparams_str = ", ".join(
                            f"{p.get('type', '')} {p.get('name', '')}".strip()
                            for p in callee_params
                        )
                        callee_sig = f"{callee.get('returnType', '')} {callee_fn}({cparams_str})".strip()
                        flowchart_entries.append({
                            "image_url": (
                                f"{asset_base}/{cpng_rel}"
                                if cpng_rel else None
                            ),
                            "mermaid": callee_fc,
                            "label": callee_sig,
                        })

                # Input / output names (mirrors docx_exporter)
                fn_data = (functions_data.get(fid) or {}) if fid else {}
                input_name = (fn_data.get("behaviourInputName") or "").strip()
                output_name = (fn_data.get("behaviourOutputName") or "").strip()
                if not input_name:
                    lbl = _readable_label(func_name)
                    input_name = (lbl + " input").strip() if lbl else ""
                if not output_name:
                    lbl = _readable_label(func_name)
                    output_name = (lbl + " result").strip() if lbl else ""

                description = iface.get("description", "") or "-"
                sec_id = f"{uk}-fn-{_safe_fn(func_name)}"
                sec_title = f"{uname}-{func_name}"

                if flowchart_entries:
                    unit_children.append(_sec(
                        sec_id, f"{unit_sec_num}.{iface_idx}", sec_title, 4,
                        type="flowchart_table", content=description,
                        flowchart_table={
                            "description": description,
                            "flowcharts": flowchart_entries,
                            "risk": "Medium",
                            "capacity": "Common",
                            "input_name": input_name,
                            "output_name": output_name,
                        },
                    ))
                else:
                    unit_children.append(_sec(
                        sec_id, f"{unit_sec_num}.{iface_idx}", sec_title, 4,
                        type="richtext", content=description,
                    ))
                iface_idx += 1

            static_children.append(_sec(
                f"{comp}-unit-{unit_idx}", unit_sec_num, uname, 3,
                type="richtext", content=None, children=unit_children,
            ))

        # ── N.2 Dynamic Behaviour ────────────────────────────────────────────
        dyn_children: list[dict] = []
        dyn_idx = 1
        for unit_name_beh, entries in sorted((behavior_rows.get(comp) or {}).items()):
            for row in entries:
                current_fn = row.get("currentFunctionName", "") or ""
                if current_fn in _hidden_by_mod_unit.get((comp, unit_name_beh), set()):
                    continue
                ext = row.get("externalUnitFunction", "") or ""
                subheader = f"{unit_name_beh} - {current_fn}"
                if ext:
                    subheader += f" ({ext})"

                # Input / output names from functions model
                input_label = ""
                output_label = ""
                for fid, f in functions_data.items():
                    fp = fid.split(KEY_SEP)
                    if len(fp) < 3 or fp[0] != comp or fp[1] != unit_name_beh:
                        continue
                    qn = f.get("qualifiedName", "") or ""
                    if (qn.split("::")[-1] if qn else "") != current_fn:
                        continue
                    input_label = (f.get("behaviourInputName") or "").strip()
                    output_label = (f.get("behaviourOutputName") or "").strip()
                    break
                if not input_label:
                    lbl = _readable_label(current_fn)
                    input_label = (lbl + " input").strip() if lbl else "Behaviour input"
                if not output_label:
                    lbl = _readable_label(current_fn)
                    output_label = (lbl + " result").strip() if lbl else "Behaviour result"

                # Behavior PNG URL
                png_abs = row.get("pngPath")
                diagram_url: Optional[str] = None
                if png_abs:
                    try:
                        rel = Path(str(png_abs)).relative_to(group_dir)
                        diagram_url = (
                            f"{asset_base}/{rel.as_posix()}"
                        )
                    except (ValueError, TypeError):
                        pass

                dyn_children.append(_sec(
                    f"{comp}-dyn-{dyn_idx}", f"{n}.2.{dyn_idx}", subheader, 3,
                    type="behavior_table", content=None,
                    behavior_table={
                        "description_list": row.get("behaviorDescription") or [],
                        "risk": "Medium",
                        "capacity": "Common",
                        "input_name": input_label,
                        "output_name": output_label,
                        "diagram_url": diagram_url,
                    },
                ))
                dyn_idx += 1

        sections.append(_sec(
            f"comp-{comp}", str(n), comp_display, 1, type="richtext", content=None,
            children=[
                _sec(f"{comp}-static", f"{n}.1", "Static Design", 2,
                     type="richtext", content=None, children=static_children),
                _sec(f"{comp}-dynamic", f"{n}.2", "Dynamic Behaviour", 2,
                     type="richtext", content=None, children=dyn_children),
            ],
        ))

    # ── Code Metrics ─────────────────────────────────────────────────────────
    metrics_n = len(sorted_comps) + 2
    sections.append(_sec(
        "metrics", str(metrics_n),
        "Code Metrics, Coding Rule, Test Coverage", 1,
        type="richtext", content="[Code metrics, coding rules and test coverage.]",
    ))

    # ── Appendix A ────────────────────────────────────────────────────────────
    sections.append(_sec(
        "appendix-a", "Appendix A",
        "Appendix A. Design Guideline", 1,
        type="richtext", content="[Design guidelines.]",
    ))

    # ── Meta ─────────────────────────────────────────────────────────────────
    all_entries = [
        e for uk in unit_names
        for e in (itf.get(uk, {}) or {}).get("entries", []) or []
    ]
    functions_total = sum(1 for e in all_entries if e.get("type") == "Function")
    globals_total = sum(1 for e in all_entries
                        if e.get("type") in ("Variable", "Global", "GlobalVariable"))

    cover = {
        "project_name": project_name,
        "subtitle": doc.subtitle or "Software Detailed Design Specification",
        "version": version.tag if version else doc.version_id,
        "layer": doc.layer,
        "group": group,
        "standard": project.compliance_standard,
        "process": doc.process,
        "generated_at": doc.updated_at.isoformat(),
    }
    meta = {
        "pipeline_data_available": True,
        "model_data_available": True,
        "source": "pipeline",
        "layers": [doc.layer] if doc.layer else [],
        "components": sorted_comps,
        "units_total": len(unit_names),
        "functions_total": functions_total,
        "globals_total": globals_total,
    }
    return {"cover": cover, "toc": _flatten_toc(sections), "sections": sections, "meta": meta}
