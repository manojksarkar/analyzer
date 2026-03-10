"""Export interface_tables.json -> Software Detailed Design DOCX. Unit header table built from model."""
import os
import sys
import json
from typing import Optional, Tuple, List, Dict, Any

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
MODEL_DIR = os.path.join(PROJECT_ROOT, "model")
COLS = ("Interface ID", "Interface Name", "Information", "Data Type", "Data Range", "Direction(In/Out)", "Source/Destination", "Interface Type")


def _strip_ext(path: str) -> str:
    if not path:
        return path
    return (path or "").replace("\\", "/")


def _path_no_ext(path: str) -> str:
    base, _ = os.path.splitext(path)
    return base.replace("\\", "/")


def _unit_paths(unit_info: dict) -> List[str]:
    """Path(s) without extension for this unit (for matching dataDictionary locations)."""
    path = unit_info.get("path")
    if not path:
        return []
    if isinstance(path, list):
        return [_strip_ext(p) for p in path]
    return [_strip_ext(path)]


def _read_decl_snippet(abs_file: str, start_line: int, *, kind: str) -> str:
    """Extract a full declaration snippet starting at start_line (1-based)."""
    if not abs_file or not os.path.isfile(abs_file) or start_line < 1:
        return "-"
    try:
        with open(abs_file, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except (OSError, IOError):
        return "-"
    if start_line > len(lines):
        return "-"

    i = start_line - 1
    buf: List[str] = []
    max_lines = 50

    # For struct/class/enum: only stop at }; (not at ; inside the body)
    # For var/typedef: stop at ;
    if kind in ("enum", "struct", "class"):
        end_marker = "};"
    else:
        end_marker = ";"

    for _ in range(max_lines):
        if i >= len(lines):
            break
        buf.append(lines[i].rstrip("\n"))
        joined = "\n".join(buf).rstrip()
        if end_marker in joined:
            break
        i += 1

    out = "\n".join(buf).strip()
    return out if out else "-"


def _load_model_json(name: str) -> dict:
    path = os.path.join(MODEL_DIR, f"{name}.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _load_base_path() -> str:
    meta = _load_model_json("metadata")
    return (meta.get("basePath") or "").strip()


def _build_unit_header_table(
    unit_info: dict,
    interfaces: list,
    data_dictionary: dict,
    global_variables_data: dict,
    base_path: str,
) -> List[Dict[str, str]]:
    """Build rows for unit header table.

    - Column 1: full declaration as in code
    - Column 2: value (initializer / underlying type / enumerator values)
    """
    rows: List[Dict[str, str]] = []
    dd = data_dictionary or {}
    unit_paths_set = set(_unit_paths(unit_info))

    # Globals: use model/globalVariables.json so we can read exact line(s)
    for gid in unit_info.get("globalVariableIds", []) or []:
        g = (global_variables_data or {}).get(gid) or {}
        loc = g.get("location") or {}
        rel_file = (loc.get("file") or "").replace("\\", "/")
        line = int(loc.get("line") or 0)
        abs_file = os.path.join(base_path, rel_file) if base_path and rel_file else ""
        decl = _read_decl_snippet(abs_file, line, kind="var")
        info = g.get("value") or "-"
        rows.append({"declaration": decl, "information": info})

    # typedef, enum, struct, class, define: match by unit file(s)
    for _type_name, t in dd.items():
        loc = t.get("location") or {}
        rel_file = (loc.get("file") or "").replace("\\", "/")
        type_file = _path_no_ext(rel_file)
        if not type_file or type_file not in unit_paths_set:
            continue
        kind = t.get("kind", "")
        if kind not in ("typedef", "enum", "struct", "class", "define"):
            continue
        line = int(loc.get("line") or 0)
        abs_file = os.path.join(base_path, rel_file) if base_path and rel_file else ""
        # Defines: use stored text/value from parser for exact macro
        if kind == "define":
            decl = t.get("text") or _read_decl_snippet(abs_file, line, kind="var")
            info = t.get("value", "") or "-"
            rows.append({"declaration": decl, "information": info})
            continue

        decl = _read_decl_snippet(abs_file, line, kind=kind)

        if kind == "typedef":
            info = t.get("underlyingType", "") or "-"
        elif kind == "enum":
            enums = t.get("enumerators", [])
            parts = []
            for e in enums:
                n = e.get("name", "")
                v = e.get("value")
                if n:
                    parts.append(f"{n}={v}" if v is not None else n)
            info = ", ".join(parts) if parts else "-"
        else:
            info = "-"

        rows.append({"declaration": decl, "information": info})

    rows.sort(key=lambda r: (r.get("declaration") or "").lower())
    return rows


def _load_model_for_unit_headers() -> Tuple[dict, dict]:
    """Load units and dataDictionary from model/ for unit header table. Returns (units_data, data_dictionary)."""
    units_data = _load_model_json("units")
    data_dictionary = _load_model_json("dataDictionary")
    return units_data, data_dictionary


def _set_cell_font(cell, font_pt, bold=False):
    for p in cell.paragraphs:
        for r in p.runs:
            r.font.size = font_pt
            r.font.bold = bold


def _add_para(doc, text, style="Normal"):
    p = doc.add_paragraph(text, style=style)
    return p


def _add_mermaid_as_text(doc, mermaid: str, font_small):
    """Add Mermaid flowchart as monospace text block."""
    p = doc.add_paragraph()
    run = p.add_run(mermaid.strip())
    run.font.name = "Consolas"
    run.font.size = font_small


def _load_flowcharts(flowcharts_dir: str) -> dict:
    """Return { unit_name: { func_name: flowchart_str } }."""
    result = {}
    if not os.path.isdir(flowcharts_dir):
        return result
    for fname in os.listdir(flowcharts_dir):
        if not fname.endswith(".json"):
            continue
        unit_name = fname[:-5]
        path = os.path.join(flowcharts_dir, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                arr = json.load(f)
            if not isinstance(arr, list):
                continue
            result[unit_name] = {}
            for item in arr:
                name = (item.get("name") or "").strip()
                flowchart = (item.get("flowchart") or "").strip()
                if name and flowchart:
                    result[unit_name][name] = flowchart
        except (json.JSONDecodeError, OSError):
            pass
    return result


def _add_unit_header_table(doc, unit_header_rows: List[Dict[str, str]], font_small) -> None:
    """Add 2-column table under unit header: global variables/typedef/enum/define | information."""
    if not unit_header_rows:
        return
    table = doc.add_table(rows=1, cols=2)
    table.style = "Table Grid"
    hdr = table.rows[0].cells
    hdr[0].text = "global variables / typedef / enum / define"
    hdr[1].text = "information"
    _set_cell_font(hdr[0], font_small, bold=True)
    _set_cell_font(hdr[1], font_small, bold=True)
    for row_data in unit_header_rows:
        row = table.add_row().cells
        row[0].text = str(row_data.get("declaration", "-"))
        row[1].text = str(row_data.get("information", "-"))
        _set_cell_font(row[0], font_small)
        _set_cell_font(row[1], font_small)


def _add_interface_table(doc, interfaces, font_small):
    table = doc.add_table(rows=1, cols=len(COLS))
    table.style = "Table Grid"
    hdr = table.rows[0].cells
    for i, c in enumerate(COLS):
        hdr[i].text = c
        _set_cell_font(hdr[i], font_small, bold=True)

    for iface in interfaces:
        iface_type = iface.get("type", "") or "-"
        if "variableType" in iface:
            data_type = iface.get("variableType", "-") or "-"
            data_range = iface.get("range", "-") or "-"
        else:
            params = iface.get("parameters", [])
            data_type = "; ".join(p.get("type", "") for p in params) if params else "-"
            data_range = "; ".join(p.get("range", "") for p in params) if params else "-"

        src_dest = iface.get("sourceDest") or "-"
        direction = iface.get("direction") or "-"
        info = iface.get("description", "") or "-"

        row = table.add_row().cells
        cells_text = (
            str(iface.get("interfaceId", "")),
            str(iface.get("interfaceName", "")),
            info,
            data_type,
            data_range,
            direction,
            src_dest,
            iface_type,
        )
        for i, txt in enumerate(cells_text):
            row[i].text = str(txt)
            _set_cell_font(row[i], font_small)


def export_docx(json_path: str = None, docx_path: str = None) -> Tuple[bool, Optional[str]]:
    from utils import load_config, safe_filename, KEY_SEP
    config = load_config(PROJECT_ROOT)
    export_cfg = config.get("export", {})
    json_path = json_path or os.path.join(OUTPUT_DIR, "interface_tables.json")
    docx_path = docx_path or os.path.join(PROJECT_ROOT, export_cfg.get("docxPath", "output/software_detailed_design.docx"))
    font_size = int(export_cfg.get("docxFontSize", 8))
    views_cfg = config.get("views", {})
    fc_cfg = views_cfg.get("flowcharts") if isinstance(views_cfg.get("flowcharts"), dict) else {}
    flowcharts_enabled = bool(views_cfg.get("flowcharts"))
    flowcharts_render_png = fc_cfg.get("renderPng", True)
    flowcharts_dir = os.path.abspath(os.path.join(OUTPUT_DIR, "flowcharts"))
    flowcharts_map = _load_flowcharts(flowcharts_dir) if flowcharts_enabled else {}

    if not os.path.isfile(json_path):
        print(f"Error: {json_path} not found. Run pipeline first.")
        return (False, None)

    try:
        from docx import Document
        from docx.shared import Pt, Inches
        font_small = Pt(font_size)
    except ImportError:
        print("Error: python-docx not installed. pip install python-docx")
        return (False, None)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    units_data, data_dictionary = _load_model_for_unit_headers()
    global_variables_data = _load_model_json("globalVariables")
    base_path = _load_base_path()

    doc = Document()
    doc.add_heading("Software Detailed Design", 0)

    # Group by module; use data as-is from view output
    by_module = {}
    for unit_key in data.keys():
        if unit_key in ("basePath", "projectName", "unitNames"):
            continue
        unit_data = data[unit_key]
        if not isinstance(unit_data, dict) or "entries" not in unit_data:
            continue
        unit_name_display = unit_data.get("name", unit_key.split(KEY_SEP)[-1] if KEY_SEP in unit_key else unit_key)
        interfaces = unit_data["entries"]
        parts = unit_key.split(KEY_SEP, 1)
        module_name = parts[0]
        by_module.setdefault(module_name, []).append((unit_key, unit_name_display, interfaces))

    sorted_modules = sorted(by_module.keys())

    # 1 Introduction
    doc.add_heading("1 Introduction", level=1)
    doc.add_heading("1.1 Purpose", level=2)
    _add_para(doc, "[Purpose of this document.]")
    doc.add_heading("1.2 Scope", level=2)
    _add_para(doc, "[Scope of the software detailed design.]")
    doc.add_heading("1.3 Terms, Abbreviations and Definitions", level=2)
    _add_para(doc, "[Terms, abbreviations and definitions.]")

    # 2, 3, ... Modules
    n_modules = len(sorted_modules)
    for sec_idx, module_name in enumerate(sorted_modules, start=0):
        sec_num = sec_idx + 2
        print(f"  docx_exporter: {sec_idx + 1}/{n_modules} modules...", end="\r", flush=True)
        doc.add_heading(f"{sec_num} {module_name}", level=1)

        # 2.1 Static Design
        doc.add_heading(f"{sec_num}.1 Static Design", level=2)

        unit_diag_dir = os.path.join(OUTPUT_DIR, "unit_diagrams")
        for unit_idx, (unit_key, unit_name_display, interfaces) in enumerate(sorted(by_module[module_name]), start=1):
            # 2.1.1 unit1
            doc.add_heading(f"{sec_num}.1.{unit_idx} {unit_name_display}", level=3)

            # Unit diagram (before unit header)
            unit_png = os.path.join(unit_diag_dir, f"{safe_filename(unit_key)}.png")
            if os.path.isfile(unit_png):
                try:
                    doc.add_picture(unit_png, width=Inches(6))
                except Exception:
                    _add_para(doc, f"[Unit diagram: {unit_png}]")

            # 2.1.1.1 unit header
            path_str = interfaces[0].get("location", {}).get("file", "-") if interfaces else "-"
            doc.add_heading(f"{sec_num}.1.{unit_idx}.1 unit header", level=4)
            _add_para(doc, f"Unit: {unit_name_display}")
            _add_para(doc, f"Path: {path_str}")
            unit_info = units_data.get(unit_key, {})
            unit_header_rows = _build_unit_header_table(
                unit_info,
                interfaces,
                data_dictionary,
                global_variables_data,
                base_path,
            )
            _add_unit_header_table(doc, unit_header_rows, font_small)

            # 2.1.1.2 unit interface (table)
            doc.add_heading(f"{sec_num}.1.{unit_idx}.2 unit interface", level=4)
            _add_interface_table(doc, interfaces, font_small)

            # 2.1.1.3, 2.1.1.4, ... per interface
            unit_name_flowchart = unit_key.split(KEY_SEP)[-1] if KEY_SEP in unit_key else unit_name_display
            for iface_idx, iface in enumerate(interfaces, start=3):
                iface_id = iface.get("interfaceId", "")
                doc.add_heading(f"{sec_num}.1.{unit_idx}.{iface_idx} {unit_name_display}-{iface_id}", level=4)
                func_name = iface.get("name", "")
                unit_prefix = unit_key.replace(KEY_SEP, "_")
                flowchart = (
                    flowcharts_map.get(unit_prefix, {}).get(func_name)
                    or flowcharts_map.get(unit_name_flowchart, {}).get(func_name)
                ) if flowcharts_enabled and func_name else None
                if flowchart:
                    if flowcharts_render_png:
                        png_path = os.path.join(flowcharts_dir, f"{unit_prefix}_{safe_filename(func_name)}.png")
                        if not os.path.isfile(png_path):
                            png_path = os.path.join(flowcharts_dir, f"{unit_name_flowchart}_{safe_filename(func_name)}.png")
                        if os.path.isfile(png_path):
                            try:
                                doc.add_picture(png_path, width=Inches(6))
                            except Exception:
                                _add_mermaid_as_text(doc, flowchart, font_small)
                        else:
                            _add_mermaid_as_text(doc, flowchart, font_small)
                    else:
                        _add_mermaid_as_text(doc, flowchart, font_small)
                else:
                    _add_para(doc, iface.get("description", "") or "-")

        # 2.2 Dynamic Behaviour: one sub-header per external call (from view output)
        doc.add_heading(f"{sec_num}.2 Dynamic Behaviour", level=2)
        docx_rows = {}
        pngs_path = os.path.join(OUTPUT_DIR, "behaviour_diagrams", "_behaviour_pngs.json")
        if os.path.isfile(pngs_path):
            try:
                with open(pngs_path, "r", encoding="utf-8") as f:
                    docx_rows = json.load(f).get("_docxRows", {})
            except (json.JSONDecodeError, IOError):
                pass
        beh_idx = 0
        for unit_name, entries in sorted((docx_rows.get(module_name) or {}).items()):
            for row in entries:
                beh_idx += 1
                ext = row.get("externalUnitFunction", "")
                subheader = f"{unit_name} - {row.get('currentFunctionName', '')}"
                if ext:
                    subheader += f" ({ext})"
                doc.add_heading(f"{sec_num}.2.{beh_idx} {subheader}", level=3)
                png_path = row.get("pngPath")
                if png_path and os.path.isfile(png_path):
                    try:
                        doc.add_picture(png_path, width=Inches(6))
                    except Exception:
                        _add_para(doc, f"[Behaviour diagram: {png_path}]")
                elif png_path:
                    _add_para(doc, f"[Behaviour diagram: {png_path}]")

    print()  # newline after progress
    # N Code Metrics, Coding rule, test coverage
    metrics_sec = len(sorted_modules) + 2
    doc.add_heading(f"{metrics_sec} Code Metrics, Coding Rule, Test Coverage", level=1)
    _add_para(doc, "[Code metrics, coding rules and test coverage.]")

    # Appendix A
    doc.add_heading("Appendix A. Design Guideline", level=1)
    _add_para(doc, "[Design guidelines.]")

    os.makedirs(os.path.dirname(docx_path) or ".", exist_ok=True)
    doc.save(docx_path)
    return (True, docx_path)


def main():
    json_path = sys.argv[1] if len(sys.argv) >= 2 else None
    docx_path = sys.argv[2] if len(sys.argv) >= 3 else None
    ok, out_path = export_docx(json_path, docx_path)
    if ok:
        print(f"Exported: {out_path}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
