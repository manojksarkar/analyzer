"""Build interface tables from units and enriched functions/globals."""
import os

from utils import short_name


def _strip_ext(name):
    if not name:
        return name
    base, ext = os.path.splitext(name)
    return base if ext else name


def _qualified_to_unit(units_data, functions_data):
    """qualifiedName -> set of unit names (derived from model, not stored)."""
    out = {}
    for unit_name, unit_info in units_data.items():
        for fid in unit_info.get("functions", []):
            f = functions_data.get(fid, {})
            qn = f.get("qualifiedName", "")
            if qn:
                out.setdefault(qn, set()).add(unit_name)
    return out


def build_interface_tables(units_data, functions_data, global_variables_data):
    # Only .cpp units; entries sorted by line; caller/callee units derived from calledBy/calls
    qualified_to_unit = _qualified_to_unit(units_data, functions_data)

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
            qn = f.get("qualifiedName", "")
            name = short_name(qn)
            loc = dict(f.get("location", {}))
            if loc.get("file"):
                loc["file"] = _strip_ext(loc["file"])
            file_code = os.path.splitext(os.path.basename(loc.get("file", "") or fid.rsplit(":", 1)[0]))[0].upper()
            interface_name = f"{file_code}_{name}" if (file_code and name) else (name or file_code or "")
            caller_units = {_strip_ext(u) for cn in f.get("calledBy", [])
                           for u in qualified_to_unit.get(cn, []) if u}
            callee_units = {_strip_ext(u) for cn in f.get("calls", [])
                            for u in qualified_to_unit.get(cn, []) if u}
            e = {
                "interfaceId": f.get("interfaceId", ""),
                "type": "function",
                "interfaceName": interface_name,
                "name": name,
                "qualifiedName": qn,
                "location": loc,
                "parameters": f.get("parameters", []),
                "direction": f.get("direction", "-"),
                "callerUnits": sorted(caller_units),
                "calleesUnits": sorted(callee_units),
            }
            if f.get("description"):
                e["description"] = f["description"]
            entries.append(e)
        for vid in sorted(unit_info["globalVariables"], key=lambda x: int(x.rsplit(":", 1)[1])):
            if vid not in global_variables_data:
                continue
            g = global_variables_data[vid]
            qn = g.get("qualifiedName", "")
            name = short_name(qn)
            loc = dict(g.get("location", {}))
            if loc.get("file"):
                loc["file"] = _strip_ext(loc["file"])
            file_code = os.path.splitext(os.path.basename(loc.get("file", "") or vid.rsplit(":", 1)[0]))[0].upper()
            interface_name = f"{file_code}_{name}" if (file_code and name) else (name or file_code or "")
            entries.append({
                "interfaceId": g.get("interfaceId", ""),
                "type": "globalVariable",
                "interfaceName": interface_name,
                "name": name,
                "qualifiedName": qn,
                "location": loc,
                "variableType": g.get("type", ""),
                "direction": g.get("direction", "-"),
                "callerUnits": [],
                "calleesUnits": [],
            })
        interface_tables[unit_key] = entries
    return interface_tables
