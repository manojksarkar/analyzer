"""Interface tables view: model -> output/interface_tables.json."""
import os
import json

from .registry import register
from utils import get_range, short_name, KEY_SEP


def _strip_ext(name):
    if not name:
        return name
    base, ext = os.path.splitext(name)
    return base if ext else name


def _fid_to_unit(units_data):
    """functionId -> set of unit names (derived from model, not stored)."""
    out = {}
    for unit_name, unit_info in units_data.items():
        for fid in unit_info.get("functionIds", []):
            out.setdefault(fid, set()).add(unit_name)
    return out


def _build_interface_tables(units_data, functions_data, global_variables_data, data_dictionary=None):
    # Only .cpp units; entries sorted by line; caller/callee units derived from calledByIds/callsIds
    fid_to_unit = _fid_to_unit(units_data)
    dd = data_dictionary or {}
    unit_names = {uk: u.get("name", uk.split(KEY_SEP)[-1] if KEY_SEP in uk else uk) for uk, u in units_data.items()}

    result = {"unitNames": unit_names}
    for unit_key, unit_info in units_data.items():
        if not (unit_info.get("fileName") or "").endswith(".cpp"):
            continue
        unit_name_display = unit_info.get("name", unit_key.split(KEY_SEP)[-1] if KEY_SEP in unit_key else unit_key)
        entries = []
        for fid in sorted(unit_info.get("functionIds", []),
                         key=lambda x: functions_data.get(x, {}).get("location", {}).get("line", 0)):
            if fid not in functions_data:
                continue
            f = functions_data[fid]
            qn = f.get("qualifiedName", "")
            name = short_name(qn)
            loc = dict(f.get("location", {}))
            if loc.get("file"):
                loc["file"] = _strip_ext(loc["file"])
            file_code = os.path.splitext(os.path.basename(loc.get("file", "") or ""))[0].upper()
            interface_name = f"{file_code}_{name}" if (file_code and name) else (name or file_code or "")
            caller_units = {
                u
                for cid in f.get("calledByIds", []) or []
                for u in fid_to_unit.get(cid, []) if u
            }
            callee_units = {
                u
                for cid in f.get("callsIds", []) or []
                for u in fid_to_unit.get(cid, []) if u
            }
            raw_params = f.get("parameters", [])
            params = [
                {**p, "range": get_range(p.get("type", ""), dd)}
                for p in raw_params
            ]
            e = {
                "interfaceId": f.get("interfaceId", ""),
                "functionId": fid,
                "type": "Function",
                "interfaceName": interface_name,
                "name": name,
                "qualifiedName": qn,
                "unitKey": unit_key,
                "unitName": unit_name_display,
                "location": loc,
                "parameters": params,
                "direction": f.get("direction", "-"),
                "reason": f.get("reason") or f.get("directionReason") or "",
                "callerUnits": sorted(caller_units),
                "calleesUnits": sorted(callee_units),
            }
            if f.get("description"):
                e["description"] = f["description"]
            entries.append(e)
        for vid in sorted(unit_info.get("globalVariableIds", []),
                         key=lambda x: global_variables_data.get(x, {}).get("location", {}).get("line", 0)):
            if vid not in global_variables_data:
                continue
            g = global_variables_data[vid]
            qn = g.get("qualifiedName", "")
            name = short_name(qn)
            loc = dict(g.get("location", {}))
            if loc.get("file"):
                loc["file"] = _strip_ext(loc["file"])
            file_code = os.path.splitext(os.path.basename(loc.get("file", "") or ""))[0].upper()
            interface_name = f"{file_code}_{name}" if (file_code and name) else (name or file_code or "")
            entries.append({
                "interfaceId": g.get("interfaceId", ""),
                "type": "Global Variable",
                "interfaceName": interface_name,
                "name": name,
                "qualifiedName": qn,
                "unitKey": unit_key,
                "unitName": unit_name_display,
                "location": loc,
                "variableType": g.get("type", ""),
                "range": get_range(g.get("type", ""), dd),
                "direction": g.get("direction", "-"),
                "reason": g.get("reason") or g.get("directionReason") or "",
                "callerUnits": [],
                "calleesUnits": [],
            })
        result[unit_key] = {"name": unit_name_display, "entries": entries}
    return result


@register("interfaceTables")
def run(model, output_dir, model_dir, config):
    units_data = model.get("units", {})
    functions_data = model.get("functions", {})
    global_variables_data = model.get("globalVariables", {})
    data_dict = model.get("dataDictionary", {})

    interface_tables = _build_interface_tables(
        units_data, functions_data, global_variables_data, data_dict
    )
    out_path = os.path.join(output_dir, "interface_tables.json")
    os.makedirs(output_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(interface_tables, f, indent=2)
    unit_count = len([k for k in interface_tables if k != "unitNames"])
    print("  output/interface_tables.json (%d units, %d functions, %d globals)" % (
        unit_count, len(functions_data), len(global_variables_data)
    ))
