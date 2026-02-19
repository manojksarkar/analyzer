"""Derive model: units, modules, enrichment. Phase 2."""
import os
import sys
import json

from utils import load_config, norm_path, make_unit_key, path_from_unit_rel, KEY_SEP

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
MODEL_DIR = os.path.join(PROJECT_ROOT, "model")
os.makedirs(MODEL_DIR, exist_ok=True)


def _load_model():
    for name in ("metadata", "functions", "globalVariables"):
        path = os.path.join(MODEL_DIR, f"{name}.json")
        if not os.path.isfile(path):
            print(f"Error: {path} not found. Run Phase 1 (parser) first.")
            raise SystemExit(1)
    with open(os.path.join(MODEL_DIR, "metadata.json"), "r", encoding="utf-8") as f:
        meta = json.load(f)
    base_path = meta["basePath"]
    project_name = meta.get("projectName", os.path.basename(base_path))
    with open(os.path.join(MODEL_DIR, "functions.json"), "r", encoding="utf-8") as f:
        functions_data = json.load(f)
    with open(os.path.join(MODEL_DIR, "globalVariables.json"), "r", encoding="utf-8") as f:
        global_variables_data = json.load(f)
    return base_path, project_name, functions_data, global_variables_data


def _file_path(data: dict, base_path: str) -> str:
    return norm_path((data.get("location") or {}).get("file", ""), base_path)


def _build_units_modules(base_path: str, functions_data: dict, global_variables_data: dict):
    all_files = set()
    for f in functions_data.values():
        fp = _file_path(f, base_path)
        if fp:
            all_files.add(fp)
    for g in global_variables_data.values():
        fp = _file_path(g, base_path)
        if fp:
            all_files.add(fp)

    unit_by_file = {}
    for fp in sorted(all_files):
        try:
            rel = os.path.relpath(fp, base_path).replace("\\", "/")
        except ValueError:
            rel = fp.replace("\\", "/")
        unit_by_file[fp] = make_unit_key(rel)

    units_data = {}
    for fp in sorted(all_files):
        base = os.path.basename(fp)
        if not base.lower().endswith((".cpp", ".cc", ".cxx")):
            continue
        try:
            rel = os.path.relpath(fp, base_path).replace("\\", "/")
        except ValueError:
            rel = fp.replace("\\", "/")
        unit_key = unit_by_file[fp]
        path_no_ext = path_from_unit_rel(rel)
        func_ids = sorted([fid for fid, f in functions_data.items() if _file_path(f, base_path) == fp],
                         key=lambda x: functions_data[x].get("location", {}).get("line", 0))
        var_ids = sorted([vid for vid, g in global_variables_data.items() if _file_path(g, base_path) == fp],
                        key=lambda x: (global_variables_data[x].get("location") or {}).get("line", 0))

        caller_units = set()
        callee_units = set()
        for fid in func_ids:
            f = functions_data.get(fid, {})
            for cid in f.get("calledByIds", []) or []:
                cf = _file_path(functions_data.get(cid, {}), base_path)
                u = unit_by_file.get(cf)
                if u and u != unit_key:
                    caller_units.add(u)
            for cid in f.get("callsIds", []) or []:
                cf = _file_path(functions_data.get(cid, {}), base_path)
                u = unit_by_file.get(cf)
                if u and u != unit_key:
                    callee_units.add(u)

        unitname = os.path.splitext(base)[0]
        if unit_key in units_data:
            u = units_data[unit_key]
            u["functionIds"] = u["functionIds"] + func_ids
            u["globalVariableIds"] = u["globalVariableIds"] + var_ids
            u["callerUnits"] = sorted(set(u["callerUnits"]) | caller_units)
            u["calleesUnits"] = sorted(set(u["calleesUnits"]) | callee_units)
        else:
            units_data[unit_key] = {
                "name": unitname,
                "path": path_no_ext,
                "fileName": base,
                "functionIds": func_ids,
                "globalVariableIds": var_ids,
                "callerUnits": sorted(caller_units),
                "calleesUnits": sorted(callee_units),
            }

    module_names = sorted({u.split(KEY_SEP)[0] for u in units_data if KEY_SEP in u})
    modules_data = {m: {"units": [u for u in units_data if u.split(KEY_SEP)[0] == m]} for m in module_names}

    with open(os.path.join(MODEL_DIR, "units.json"), "w", encoding="utf-8") as f:
        json.dump(units_data, f, indent=2)
    with open(os.path.join(MODEL_DIR, "modules.json"), "w", encoding="utf-8") as f:
        json.dump(modules_data, f, indent=2)
    print(f"  model/units.json ({len(units_data)})")
    print(f"  model/modules.json ({len(modules_data)})")
    return units_data, unit_by_file


def _build_interface_index(base_path: str, functions_data: dict, global_variables_data: dict):
    all_entries = []
    for fid, f in functions_data.items():
        all_entries.append(("f", fid, f))
    for vid, g in global_variables_data.items():
        all_entries.append(("g", vid, g))

    by_file = {}
    for kind, iid, data in all_entries:
        fp = _file_path(data, base_path)
        if fp:
            by_file.setdefault(fp, []).append((kind, iid, data))

    idx_by_id = {}
    for fp in sorted(by_file):
        for idx, (_, iid, data) in enumerate(sorted(by_file[fp], key=lambda x: (x[2].get("location") or {}).get("line", 0)), 1):
            idx_by_id[iid] = idx
    return idx_by_id


def _enrich_interfaces(base_path: str, project_name: str, functions_data: dict, global_variables_data: dict, idx_by_id: dict):
    proj_code = project_name.upper()
    for fid, f in functions_data.items():
        loc = f.get("location") or {}
        fp = loc.get("file", "")
        try:
            rel = os.path.relpath(norm_path(fp, base_path), base_path).replace("\\", "/") if fp else fp
        except ValueError:
            rel = fp or ""
        unit = os.path.splitext(rel)[0] if rel else ""
        unit_code = unit.replace("/", "_").upper()
        idx_code = f"{idx_by_id.get(fid, 0):02d}"
        interface_id = f"IF_{proj_code}_{unit_code}_{idx_code}"
        raw_params = f.get("parameters", f.get("params", []))
        params = [{"name": p.get("name", ""), "type": p.get("type", "")} for p in raw_params]
        f["interfaceId"] = interface_id
        f["parameters"] = params
    for vid, g in global_variables_data.items():
        loc = g.get("location") or {}
        fp = loc.get("file", "")
        try:
            rel = os.path.relpath(norm_path(fp, base_path), base_path).replace("\\", "/") if fp else fp
        except ValueError:
            rel = fp or ""
        unit = os.path.splitext(rel)[0] if rel else ""
        unit_code = unit.replace("/", "_").upper()
        idx_code = f"{idx_by_id.get(vid, 0):02d}"
        g["interfaceId"] = f"IF_{proj_code}_{unit_code}_{idx_code}"


def _enrich_from_llm(base_path: str, functions_data: dict, config: dict):
    """LLM enrichment for descriptions only. Direction comes from parser (global read/write analysis)."""
    try:
        from llm_client import enrich_functions_with_descriptions
    except ImportError:
        return
    funcs_list = list(functions_data.values())
    desc = enrich_functions_with_descriptions(funcs_list, base_path, config)
    for f in funcs_list:
        key = f"{f.get('location', {}).get('file', '')}:{f.get('location', {}).get('line', '')}"
        if desc.get(key, {}).get("description"):
            f["description"] = desc[key]["description"]


def main():
    base_path, project_name, functions_data, global_variables_data = _load_model()
    config = load_config(PROJECT_ROOT)

    units_data, unit_by_file = _build_units_modules(base_path, functions_data, global_variables_data)
    idx_by_id = _build_interface_index(base_path, functions_data, global_variables_data)
    _enrich_interfaces(base_path, project_name, functions_data, global_variables_data, idx_by_id)
    _enrich_from_llm(base_path, functions_data, config)

    # Functions: must be In or Out (never -)
    for f in functions_data.values():
        d = f.get("direction", "").strip()
        f["direction"] = "Out" if d == "Out" else "In"
    # Globals: In/Out
    for g in global_variables_data.values():
        g["direction"] = "In/Out"

    # Clean and persist
    for f in functions_data.values():
        f.pop("params", None)
    with open(os.path.join(MODEL_DIR, "functions.json"), "w", encoding="utf-8") as f:
        json.dump(functions_data, f, indent=2)
    with open(os.path.join(MODEL_DIR, "globalVariables.json"), "w", encoding="utf-8") as f:
        json.dump(global_variables_data, f, indent=2)
    print(f"  model/functions.json ({len(functions_data)})")
    print(f"  model/globalVariables.json ({len(global_variables_data)})")


if __name__ == "__main__":
    main()
