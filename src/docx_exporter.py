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


def _param_str(p):
    """Format parameter as 'name: type'."""
    return f"{p.get('name', '')}: {p.get('type', '')}"


def export_docx(json_path: str = JSON_PATH, docx_path: str = DOCX_PATH) -> bool:
    """Generate interface_tables.docx from interface_tables.json."""
    if not os.path.isfile(json_path):
        print(f"Error: {json_path} not found. Run pipeline first.")
        return False

    try:
        from docx import Document
        from docx.shared import Pt
    except ImportError:
        print("Error: python-docx not installed. pip install python-docx")
        return False

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    doc = Document()
    doc.add_heading("Interface Tables", 0)

    cols = ("Interface ID", "Type", "Name", "Qualified Name", "Parameters", "Caller Units", "Callee Units", "Description")

    for unit_name in sorted(data.keys()):
        if unit_name in ("basePath", "projectName"):
            continue
        interfaces = data[unit_name]
        if not isinstance(interfaces, list):
            continue

        doc.add_heading(unit_name, level=2)
        table = doc.add_table(rows=1, cols=len(cols))
        table.style = "Table Grid"
        hdr = table.rows[0].cells
        for i, c in enumerate(cols):
            hdr[i].text = c

        for iface in interfaces:
            if iface.get("type") == "globalVariable":
                params_str = iface.get("variableType", "-") or "-"
            else:
                params = iface.get("parameters", [])
                params_str = "; ".join(_param_str(p) for p in params) if params else "-"
            caller = ", ".join(iface.get("callerUnits", [])) or "-"
            callee = ", ".join(iface.get("calleesUnits", [])) or "-"
            desc = iface.get("description", "") or "-"

            row = table.add_row().cells
            row[0].text = str(iface.get("interfaceId", ""))
            row[1].text = str(iface.get("type", ""))
            row[2].text = str(iface.get("name", ""))
            row[3].text = str(iface.get("qualifiedName", ""))
            row[4].text = params_str
            row[5].text = caller
            row[6].text = callee
            row[7].text = desc

    os.makedirs(os.path.dirname(docx_path), exist_ok=True)
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
