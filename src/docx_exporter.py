"""
Export interface_tables.json to interface_tables.docx.
Reads output/interface_tables.json, writes output/interface_tables.docx.
"""
import os
import sys
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
JSON_PATH = os.path.join(OUTPUT_DIR, "interface_tables.json")
DOCX_PATH = os.path.join(OUTPUT_DIR, "interface_tables.docx")

COLS = ("Interface ID", "Interface Name", "Information", "Data Type", "Data Range", "Direction(In/Out)", "Source/Destination", "Interface Type")


def _set_cell_font(cell, font_pt, bold=False):
    for p in cell.paragraphs:
        for r in p.runs:
            r.font.size = font_pt
            r.font.bold = bold


def export_docx(json_path: str = JSON_PATH, docx_path: str = DOCX_PATH) -> bool:
    """Generate interface_tables.docx from interface_tables.json."""
    if not os.path.isfile(json_path):
        print(f"Error: {json_path} not found. Run pipeline first.")
        return False

    try:
        from docx import Document
        from docx.shared import Pt
        font_small = Pt(8)
    except ImportError:
        print("Error: python-docx not installed. pip install python-docx")
        return False

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    doc = Document()
    doc.add_heading("Interface Tables", 0)

    for unit_name in sorted(data.keys()):
        if unit_name in ("basePath", "projectName"):
            continue
        interfaces = data[unit_name]
        if not isinstance(interfaces, list):
            continue

        parts = unit_name.split("/", 1)
        module_name = parts[0]
        file_name = parts[1] if len(parts) > 1 else unit_name

        doc.add_heading(module_name, level=1)
        doc.add_heading(file_name, level=2)

        table = doc.add_table(rows=1, cols=len(COLS))
        table.style = "Table Grid"
        hdr = table.rows[0].cells
        for i, c in enumerate(COLS):
            hdr[i].text = c
            _set_cell_font(hdr[i], font_small, bold=True)

        for iface in interfaces:
            iface_type = iface.get("type", "") or "-"
            if iface_type == "globalVariable":
                data_type = iface.get("variableType", "-") or "-"
                data_range = "-"
            else:
                params = iface.get("parameters", [])
                data_type = "; ".join(p.get("type", "") for p in params) if params else "-"
                data_range = "; ".join(p.get("range", "") for p in params) if params else "-"

            callers = iface.get("callerUnits", [])
            callees = iface.get("calleesUnits", [])
            dirs = []
            if callers:
                dirs.append("In")
            if callees:
                dirs.append("Out")
            direction = "/".join(dirs) if dirs else "-"
            src_dest = f"Source: {', '.join(callers)}; Dest: {', '.join(callees)}" if (callers or callees) else "-"
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

    os.makedirs(os.path.dirname(docx_path) or ".", exist_ok=True)
    doc.save(docx_path)
    return True


def main():
    if len(sys.argv) >= 2:
        json_path = sys.argv[1]
    else:
        json_path = JSON_PATH
    docx_path = sys.argv[2] if len(sys.argv) >= 3 else DOCX_PATH
    ok = export_docx(json_path, docx_path)
    if ok:
        print(f"Exported: {docx_path}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
