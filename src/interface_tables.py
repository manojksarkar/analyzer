"""
Build interface tables: { unit_name: [ { interfaceId, type, interfaceName, ... }, ... ] }.
Include only .cpp units; all names stored without file extensions.
"""
import os


def _strip_ext(name):
    """Remove file extension (e.g. main.cpp -> main, path/to/foo.cpp -> path/to/foo)."""
    if not name:
        return name
    base, ext = os.path.splitext(name)
    return base if ext else name


def build_interface_tables(units_data, functions_data, global_variables_data):
    """
    Build interface tables from units and enriched functions/globalVariables.
    Only includes .cpp units. Unit keys and location/caller/callee names have no file extension.
    Returns dict: unit_name (no ext) -> list of interface entries.
    """
    interface_tables = {}
    for unit_name, unit_info in units_data.items():
        if not unit_name.endswith(".cpp"):
            continue
        unit_key = _strip_ext(unit_name)
        entries = []
        for fid in sorted(unit_info["functions"], key=lambda x: int(x.rsplit(":", 1)[1])):
            if fid not in functions_data:
                continue
            f = functions_data[fid]
            loc = dict(f.get("location", {}))
            if loc.get("file"):
                loc["file"] = _strip_ext(loc["file"])
            e = {
                "interfaceId": f.get("interfaceId", ""),
                "type": "function",
                "interfaceName": f.get("interfaceName", ""),
                "name": f.get("name", ""),
                "qualifiedName": f.get("qualifiedName", ""),
                "location": loc,
                "parameters": f.get("parameters", []),
                "direction": f.get("direction", "-"),
                "callerUnits": [_strip_ext(u) for u in f.get("callerUnits", [])],
                "calleesUnits": [_strip_ext(u) for u in f.get("calleesUnits", [])],
            }
            if f.get("description"):
                e["description"] = f["description"]
            entries.append(e)
        for vid in sorted(unit_info["globalVariables"], key=lambda x: int(x.rsplit(":", 1)[1])):
            if vid not in global_variables_data:
                continue
            g = global_variables_data[vid]
            loc = dict(g.get("location", {}))
            if loc.get("file"):
                loc["file"] = _strip_ext(loc["file"])
            entries.append({
                "interfaceId": g.get("interfaceId", ""),
                "type": "globalVariable",
                "interfaceName": g.get("interfaceName", ""),
                "name": g.get("name", ""),
                "qualifiedName": g.get("qualifiedName", ""),
                "location": loc,
                "variableType": g.get("type", ""),
                "direction": g.get("direction", "-"),
                "callerUnits": [_strip_ext(u) for u in g.get("callerUnits", [])],
                "calleesUnits": [_strip_ext(u) for u in g.get("calleesUnits", [])],
            })
        interface_tables[unit_key] = entries
    return interface_tables
