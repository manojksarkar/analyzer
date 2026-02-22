"""Export interface_tables.json -> Software Detailed Design DOCX. Data only; no derivation logic."""
import os
import sys
import json
import subprocess
from typing import Optional, Tuple

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
COLS = ("Interface ID", "Interface Name", "Information", "Data Type", "Data Range", "Direction(In/Out)", "Source/Destination", "Interface Type")


def _set_cell_font(cell, font_pt, bold=False):
    for p in cell.paragraphs:
        for r in p.runs:
            r.font.size = font_pt
            r.font.bold = bold


def _add_para(doc, text, style="Normal"):
    p = doc.add_paragraph(text, style=style)
    return p


def _add_requirement_image_table(doc, png_path: str, flowchart_mermaid: str, font_small):
    import os
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_ALIGN_VERTICAL, WD_ROW_HEIGHT_RULE
    from docx.shared import Inches

    table = doc.add_table(rows=1, cols=2)
    table.style = "Table Grid"

    table.rows[0].height_rule = WD_ROW_HEIGHT_RULE.AUTO

    row = table.rows[0].cells

    # Vertical align TOP
    row[0].vertical_alignment = WD_ALIGN_VERTICAL.TOP
    row[1].vertical_alignment = WD_ALIGN_VERTICAL.TOP

    row[0].text = "Requirements"
    _set_cell_font(row[0], font_small)

    # Right align text
    for para in row[0].paragraphs:
        para.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    # Remove extra spacing in both cells
    for cell in row:
        for para in cell.paragraphs:
            para.paragraph_format.space_before = 0
            para.paragraph_format.space_after = 0
            para.paragraph_format.line_spacing = 1

    # Clear second cell
    row[1].text = ""
    p = row[1].paragraphs[0]

    if png_path and os.path.isfile(png_path):
        try:
            run = p.add_run()
            run.add_picture(png_path, width=Inches(4))
        except Exception:
            run = p.add_run(flowchart_mermaid.strip())
            run.font.name = "Consolas"
            run.font.size = font_small
    else:
        run = p.add_run(flowchart_mermaid.strip())
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
                    png_path = None
                    if flowcharts_render_png:
                        png_path = os.path.join(flowcharts_dir, f"{unit_prefix}_{safe_filename(func_name)}.png")
                        if not os.path.isfile(png_path):
                            png_path = os.path.join(flowcharts_dir, f"{unit_name_flowchart}_{safe_filename(func_name)}.png")
                    print(f" png_path: {png_path}")
                    _add_requirement_image_table(doc, png_path or "", flowchart, font_small)
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
                doc.add_heading(f"{sec_num}.2.{beh_idx} {unit_name} - {row.get('externalUnitFunction', '')}", level=3)
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
