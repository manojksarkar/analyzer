"""Interface tables view: model -> output/interface_tables.json."""
import json
import os
import re

from .registry import register
from utils import get_range, log, scoped_name, short_name, KEY_SEP


def _iface_order(entry):
    """Sort rows by the interface ID's trailing index.

    The table must read 01, 02, 03… Sorting by source line instead only agreed
    with the numbering while a unit's interfaces all lived in ONE file; once a
    unit spans Foo.h + Foo.cpp (public inline header functions) the two orders
    diverge and IDs appear shuffled. Ordering by the ID itself keeps the table in
    step with the numbering by construction, whatever the numbering is derived
    from. Compared numerically, not lexically, so _99 sorts before _100.
    IDs are assigned functions-then-globals within a unit, so that grouping is
    preserved; an entry with no parseable index sorts last, insertion order kept.
    """
    m = re.search(r"(\d+)$", entry.get("interfaceId") or "")
    return (0, int(m.group(1))) if m else (1, 0)


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


def _build_interface_tables(
    units_data,
    functions_data,
    global_variables_data,
    data_dictionary=None,
    *,
    allowed_components: set | None = None,
):
    # Only .cpp units; entries sorted by line; caller/callee units derived from calledByIds/callsIds
    fid_to_unit = _fid_to_unit(units_data)
    dd = data_dictionary or {}
    unit_names = {uk: u.get("name", uk.split(KEY_SEP)[-1] if KEY_SEP in uk else uk) for uk, u in units_data.items()}

    result = {"unitNames": unit_names}
    for unit_key, unit_info in units_data.items():
        if allowed_components:
            if KEY_SEP in unit_key and unit_key.split(KEY_SEP, 1)[0].lower() not in allowed_components:
                continue
        if not (unit_info.get("fileName") or "").endswith(".cpp"):
            continue
        unit_name_display = unit_info.get("name", unit_key.split(KEY_SEP)[-1] if KEY_SEP in unit_key else unit_key)
        entries = []
        for fid in sorted(unit_info.get("functionIds", []),
                         key=lambda x: functions_data.get(x, {}).get("location", {}).get("line", 0)):
            if fid not in functions_data:
                continue
            f = functions_data[fid]
            if (f.get("visibility") or "").lower() == "private":
                continue
            qn = f.get("qualifiedName", "")
            # `name` stays SHORT — downstream code uses it as a lookup key (flowchart stems,
            # behaviour rows), not only for display. `interfaceName` carries the class-qualified
            # display form so two same-named methods in one unit (AddOperation::apply vs
            # MultiplyOperation::apply) are distinguishable wherever a name is rendered.
            name = short_name(qn)
            loc = dict(f.get("location", {}))
            if loc.get("file"):
                loc["file"] = _strip_ext(loc["file"])
            interface_name = scoped_name(qn, f.get("className", ""))
            caller_units = {
                u for cid in f.get("calledByIds", []) or []
                for u in fid_to_unit.get(cid, []) if u
            }
            callee_units = {
                u for cid in f.get("callsIds", []) or []
                for u in fid_to_unit.get(cid, []) if u
            }
            # Include every caller/callee unit except this function's own unit — mirrors the
            # static diagram (unit_diagrams), which only skips same-unit self-loops, so the
            # table's Source/Destination stays consistent with it. Same-component (different-
            # unit) and same-group peer units are now kept instead of dropped (3.5, REQ-IT-12).
            def _keep_unit(u: str) -> bool:
                return u != unit_key

            # 3.15: Source/Destination lists CALLERS only. Every cross-unit relationship is
            # documented once, from the provider (callee unit)'s perspective; a function's own
            # callee side is surfaced in those partner units' rows instead. callee_units is still
            # computed and emitted as the calleesUnits field below for completeness.
            callers_fmt = sorted(set(u.replace(KEY_SEP, "/") for u in caller_units if _keep_unit(u)))
            source_dest = ', '.join(callers_fmt) if callers_fmt else "-"
            raw_params = f.get("parameters", [])
            params = [{**p, "range": get_range(p.get("type", ""), dd)} for p in raw_params]
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
                "returnType": f.get("returnType", ""),
                "returnRange": get_range(f.get("returnType", ""), dd),
                "direction": f.get("direction") or "In",
                "reason": f.get("reason") or f.get("directionReason") or "",
                "sourceDest": source_dest,
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
            if (g.get("visibility") or "").lower() == "private":
                continue
            qn = g.get("qualifiedName", "")
            name = short_name(qn)
            loc = dict(g.get("location", {}))
            if loc.get("file"):
                loc["file"] = _strip_ext(loc["file"])
            interface_name = scoped_name(qn, g.get("className", ""))
            ge = {
                "interfaceId": g.get("interfaceId", ""),
                "globalId": vid,
                "type": "Global Variable",
                "interfaceName": interface_name,
                "name": name,
                "qualifiedName": qn,
                "unitKey": unit_key,
                "unitName": unit_name_display,
                "location": loc,
                "variableType": g.get("type", ""),
                "range": get_range(g.get("type", ""), dd),
                "direction": g.get("direction") or "In/Out",
                "reason": g.get("reason") or g.get("directionReason") or "",
                "sourceDest": unit_key.replace(KEY_SEP, "/"),
                "callerUnits": [],
                "calleesUnits": [],
            }
            if g.get("value"):
                ge["value"] = g["value"]
            if g.get("description"):
                ge["description"] = g["description"]
            entries.append(ge)
        entries.sort(key=_iface_order)
        result[unit_key] = {"name": unit_name_display, "entries": entries}
    result["unitNames"] = {k: unit_names[k] for k in result if k != "unitNames" and k in unit_names}
    return result


def _range_coverage(interface_tables):
    """How many Data Range cells got a real answer -> (resolved, total, {type: count}).

    Reported as a single line rather than stored on each entry: the provenance has no
    reader in the DOCX (nothing renders `directionReason` either), and a per-cell field
    would ride on every row and churn the snapshot for an audit aid.
    """
    resolved = 0
    total = 0
    unresolved: dict = {}
    for key, unit in interface_tables.items():
        if key == "unitNames" or not isinstance(unit, dict):
            continue
        for e in unit.get("entries", []) or []:
            cells = [(p.get("type", ""), p.get("range", ""))
                     for p in (e.get("parameters") or [])]
            if e.get("type") == "Global Variable":
                cells.append((e.get("variableType", ""), e.get("range", "")))
            else:
                cells.append((e.get("returnType", ""), e.get("returnRange", "")))
            for type_name, rng in cells:
                total += 1
                if rng and rng != "NA":
                    resolved += 1
                elif type_name:
                    unresolved[type_name] = unresolved.get(type_name, 0) + 1
    return resolved, total, unresolved


def _format_range_coverage(resolved, total, unresolved, *, limit=8):
    worst = sorted(unresolved.items(), key=lambda kv: (-kv[1], kv[0]))
    shown = ", ".join(f"{t} x{n}" for t, n in worst[:limit])
    if len(worst) > limit:
        shown += f", +{len(worst) - limit} more"
    msg = f"data ranges: {resolved}/{total} resolved"
    if worst:
        msg += f", {total - resolved} NA ({shown})"
    return msg


@register("interfaceTables")
def run(model, output_dir, model_dir, config):
    units_data = model.get("units", {})
    functions_data = model.get("functions", {})
    global_variables_data = model.get("globalVariables", {})
    data_dict = model.get("dataDictionary", {})
    allowed_components = {m.lower() for m in (config.get("_analyzerAllowedComponents") or [])}

    interface_tables = _build_interface_tables(
        units_data,
        functions_data,
        global_variables_data,
        data_dict,
        allowed_components=allowed_components,
    )
    out_path = os.path.join(output_dir, "interface_tables.json")
    os.makedirs(output_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(interface_tables, f, indent=2)
    unit_count = len([k for k in interface_tables if k != "unitNames"])
    log("%s (%d units, %d functions, %d globals)" % (
        out_path, unit_count, len(functions_data), len(global_variables_data)
    ), component="interfaceTables")
    _resolved, _total, _unresolved = _range_coverage(interface_tables)
    if _total:
        log(_format_range_coverage(_resolved, _total, _unresolved),
            component="interfaceTables")
