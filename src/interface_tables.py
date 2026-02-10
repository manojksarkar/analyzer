"""
Build interface tables: { unit_name: [ { interfaceId, type, interfaceName, ... }, ... ] }.
Single place that defines the interface-table structure. Used by generator (writes JSON)
and docx_exporter (reads JSON produced from this structure).
"""


def build_interface_tables(units_data, functions_data, global_variables_data):
    """
    Build interface tables from units and enriched functions/globalVariables.
    Returns dict: unit_name -> list of interface entries (each with interfaceId, type, interfaceName, etc.).
    """
    interface_tables = {}
    for unit_name, unit_info in units_data.items():
        entries = []
        for fid in sorted(unit_info["functions"], key=lambda x: int(x.rsplit(":", 1)[1])):
            if fid not in functions_data:
                continue
            f = functions_data[fid]
            e = {
                "interfaceId": f.get("interfaceId", ""),
                "type": "function",
                "interfaceName": f.get("interfaceName", ""),
                "name": f.get("name", ""),
                "qualifiedName": f.get("qualifiedName", ""),
                "location": f.get("location", {}),
                "parameters": f.get("parameters", []),
                "callerUnits": f.get("callerUnits", []),
                "calleesUnits": f.get("calleesUnits", []),
            }
            if f.get("description"):
                e["description"] = f["description"]
            entries.append(e)
        for vid in sorted(unit_info["globalVariables"], key=lambda x: int(x.rsplit(":", 1)[1])):
            if vid not in global_variables_data:
                continue
            g = global_variables_data[vid]
            entries.append({
                "interfaceId": g.get("interfaceId", ""),
                "type": "globalVariable",
                "interfaceName": g.get("interfaceName", ""),
                "name": g.get("name", ""),
                "qualifiedName": g.get("qualifiedName", ""),
                "location": g.get("location", {}),
                "variableType": g.get("type", ""),
                "callerUnits": g.get("callerUnits", []),
                "calleesUnits": g.get("calleesUnits", []),
            })
        interface_tables[unit_name] = entries
    return interface_tables
