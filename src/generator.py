"""
Generator: model/ (raw model) -> output/ (design views)

Option A: Raw model -> Design views
- model/: functions.json, globalVariables.json, units.json, modules.json (single source of truth)
- output/: interface_tables.json { unit_name: [{ interfaceId, type, ... }] }
"""
import os
import sys
import json
from collections import defaultdict

from utils import get_module_name, norm_path, get_range_for_type, load_config

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
MODEL_DIR = os.path.join(PROJECT_ROOT, "model")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
os.makedirs(MODEL_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)


def main():
    funcs_path = os.path.join(MODEL_DIR, "functions.json")
    globals_path = os.path.join(MODEL_DIR, "globalVariables.json")
    metadata_path = os.path.join(MODEL_DIR, "metadata.json")
    if not os.path.exists(funcs_path) or not os.path.exists(globals_path):
        print("Error: model not found. Run parser first: python run.py test_cpp_project")
        sys.exit(1)

    with open(funcs_path, "r", encoding="utf-8") as f:
        functions_data = json.load(f)
    with open(globals_path, "r", encoding="utf-8") as f:
        global_variables_data = json.load(f)

    if os.path.exists(metadata_path):
        with open(metadata_path, "r", encoding="utf-8") as f:
            meta_info = json.load(f)
        base_path = meta_info["basePath"]
        project_name = meta_info.get("projectName", os.path.basename(base_path))
    else:
        print("Error: metadata.json not found. Run parser first.")
        sys.exit(1)
    meta = {"basePath": base_path, "projectName": project_name}
    config = load_config(PROJECT_ROOT) or {}

    if isinstance(functions_data, list):
        functions_data = {f["location"]["file"] + ":" + str(f["location"]["line"]): f for f in functions_data}
    if isinstance(global_variables_data, list):
        global_variables_data = {g["location"]["file"] + ":" + str(g["location"]["line"]): g for g in global_variables_data}

    project_code = project_name.upper()

    def _func_entry(fid, f):
        loc = f["location"]
        return {
            "functionId": fid,
            "functionName": f["name"],
            "qualifiedName": f.get("qualifiedName", f["name"]),
            "moduleName": f.get("module", ""),
            "parameters": f.get("params", []),
            "callersFunctionNames": f.get("callersFunctionNames", []),
            "calleesFunctionNames": f.get("calleesFunctionNames", []),
        }

    functions_list = [_func_entry(fid, f) for fid, f in functions_data.items()]

    all_file_paths = set(norm_path(fid.rsplit(":", 1)[0], base_path) for fid in functions_data.keys())
    all_file_paths.update(norm_path(vid.rsplit(":", 1)[0], base_path) for vid in global_variables_data.keys())
    file_paths = sorted(all_file_paths)
    qualified_to_file = defaultdict(set)
    for fid, f in functions_data.items():
        fp = norm_path(fid.rsplit(":", 1)[0], base_path)
        qualified_to_file[f.get("qualifiedName", f["name"])].add(fp)

    unit_by_file = {}
    for fp in file_paths:
        try:
            rel = os.path.relpath(fp, base_path)
        except ValueError:
            rel = fp
        unit_module = get_module_name(rel.replace("\\", "/"), base_path)
        unit_by_file[fp] = f"{unit_module}/{os.path.basename(fp)}"

    module_names = sorted({f.get("module", "") for f in functions_data.values() if f.get("module")} |
                        {g.get("module", "") for g in global_variables_data.values() if g.get("module")})

    # --- Component design: modules with units and incoming/outgoing for diagram ---
    caller_sets = defaultdict(set)
    callee_sets = defaultdict(set)
    for mod in module_names:
        for f in functions_data.values():
            if f.get("module") != mod:
                continue
            for cn in f.get("callersFunctionNames", []):
                for cf in qualified_to_file.get(cn, []):
                    u = unit_by_file.get(cf, "")
                    um = u.split("/")[0] if u else ""
                    if um and um != mod:
                        caller_sets[mod].add(um)
            for cn in f.get("calleesFunctionNames", []):
                for cf in qualified_to_file.get(cn, []):
                    u = unit_by_file.get(cf, "")
                    um = u.split("/")[0] if u else ""
                    if um and um != mod:
                        callee_sets[mod].add(um)

    components_data = {}
    for mod in module_names:
        mod_units = sorted({unit_by_file[fp] for fp in file_paths
            if unit_by_file.get(fp, "").split("/")[0] == mod})
        components_data[mod] = {
            "units": mod_units,
            "incoming": sorted(caller_sets[mod]),
            "outgoing": sorted(callee_sets[mod]),
        }

    # --- Raw model: units ---
    units_data = {}
    for fp in file_paths:
        unit_name = unit_by_file.get(fp) or f"{get_module_name(fp, base_path)}/{os.path.basename(fp)}"

        func_ids = sorted([fid for fid in functions_data if norm_path(fid.rsplit(":", 1)[0], base_path) == fp])
        var_ids = sorted([vid for vid in global_variables_data if norm_path(vid.rsplit(":", 1)[0], base_path) == fp])

        caller_unit_names = set()
        callee_unit_names = set()
        for fid in func_ids:
            f = functions_data.get(fid, {})
            for cn in f.get("callersFunctionNames", []):
                for cf in qualified_to_file.get(cn, []):
                    u = unit_by_file.get(cf)
                    if u and u != unit_name:
                        caller_unit_names.add(u)
            for cn in f.get("calleesFunctionNames", []):
                for cf in qualified_to_file.get(cn, []):
                    u = unit_by_file.get(cf)
                    if u and u != unit_name:
                        callee_unit_names.add(u)

        units_data[unit_name] = {
            "fileName": os.path.basename(fp),
            "functions": func_ids,
            "globalVariables": var_ids,
            "callerUnits": sorted(caller_unit_names),
            "calleesUnits": sorted(callee_unit_names),
        }

    # --- Raw model: units, modules -> model/ ---
    modules_data = {mod: {"units": sorted({unit_by_file[fp] for fp in file_paths
        if unit_by_file.get(fp, "").split("/")[0] == mod})} for mod in module_names}
    with open(os.path.join(MODEL_DIR, "units.json"), "w", encoding="utf-8") as f:
        json.dump(units_data, f, indent=2)
    with open(os.path.join(MODEL_DIR, "modules.json"), "w", encoding="utf-8") as f:
        json.dump(modules_data, f, indent=2)
    print("  model/units.json (%d)" % len(units_data))
    print("  model/modules.json (%d)" % len(modules_data))

    # --- Design view: interface_table -> output/ ---
    all_entries = []
    for fid, f in functions_data.items():
        all_entries.append(("function", fid, f))
    for vid, g in global_variables_data.items():
        all_entries.append(("globalVariable", vid, g))

    by_file = defaultdict(list)
    for kind, iid, data in all_entries:
        fp = norm_path(iid.rsplit(":", 1)[0], base_path)
        by_file[fp].append((kind, iid, data))

    interface_index = {}
    for fp in sorted(by_file.keys()):
        entries = sorted(by_file[fp], key=lambda x: int(x[1].rsplit(":", 1)[1]))
        for idx, (_, iid, _) in enumerate(entries, 1):
            interface_index[iid] = idx

    llm_data = {}
    if config.get("enableDescriptions") or config.get("enableFlowcharts"):
        try:
            from llm_client import enrich_functions_with_llm
            funcs_only = [f for f in functions_data.values() if f.get("location")]
            if funcs_only:
                print("Enriching with LLM (Ollama)...")
                llm_data = enrich_functions_with_llm(
                    funcs_only,
                    base_path,
                    config,
                    descriptions=config.get("enableDescriptions", False),
                    flowcharts=config.get("enableFlowcharts", False),
                )
                has_any = any(v.get("description") or v.get("flowchart") for v in llm_data.values())
                if not has_any:
                    print("  Warning: No descriptions/flowcharts received. Is Ollama running? (ollama serve)")
        except ImportError as e:
            print(f"LLM disabled: {e}")

    for kind, iid, data in all_entries:
        fp = iid.rsplit(":", 1)[0]
        abs_fp = norm_path(fp, base_path)
        try:
            rel = os.path.relpath(abs_fp, base_path).replace("\\", "/")
        except ValueError:
            rel = fp
        module_name = get_module_name(rel, base_path)
        file_code = os.path.splitext(os.path.basename(fp))[0].upper()
        idx_code = f"{interface_index.get(iid, 0):02d}"
        interface_id = f"IF_{project_code}_{module_name.upper()}_{file_code}_{idx_code}"

        if kind == "function":
            base_name = data["name"]
            interface_name = f"{file_code}_{base_name}" if base_name else file_code
            callers = data.get("callersFunctionNames", [])
            callees = data.get("calleesFunctionNames", [])
            caller_units_set = set()
            callee_units_set = set()
            for cn in callers:
                for cf in qualified_to_file.get(cn, []):
                    caller_units_set.add(unit_by_file.get(cf, ""))
            for cn in callees:
                for cf in qualified_to_file.get(cn, []):
                    callee_units_set.add(unit_by_file.get(cf, ""))
            caller_units_set.discard("")
            callee_units_set.discard("")
            params = data.get("params", [])
            params_with_range = [
                {"name": p.get("name", ""), "type": p.get("type", ""), "range": get_range_for_type(p.get("type", ""))}
                for p in params
            ]
            functions_data[iid].update({
                "interfaceId": interface_id,
                "interfaceName": interface_name,
                "callerUnits": sorted(caller_units_set),
                "calleesUnits": sorted(callee_units_set),
                "parameters": params_with_range,
            })
            loc = data.get("location", {})
            lookup_key = f"{loc.get('file', '')}:{loc.get('line', '')}" if loc else ""
            llm_info = llm_data.get(lookup_key, {}) if lookup_key else {}
            if llm_info.get("description"):
                functions_data[iid]["description"] = llm_info["description"]
            if llm_info.get("flowchart"):
                functions_data[iid]["flowchart"] = llm_info["flowchart"]
        else:
            base_name = data["name"]
            interface_name = f"{file_code}_{base_name}" if base_name else file_code
            global_variables_data[iid].update({
                "interfaceId": interface_id,
                "interfaceName": interface_name,
                "callerUnits": [],
                "calleesUnits": [],
            })

    # Build interface_tables: { unit_name: [ { interfaceId, type, ... }, ... ] }
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
            if f.get("flowchart"):
                e["flowchart"] = f["flowchart"]
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

    with open(os.path.join(OUTPUT_DIR, "interface_tables.json"), "w", encoding="utf-8") as f:
        json.dump(interface_tables, f, indent=2)
    n_funcs = len(functions_data)
    n_vars = len(global_variables_data)
    print("  output/interface_tables.json (%d units, %d functions, %d globals)" % (
        len(interface_tables), n_funcs, n_vars))


if __name__ == "__main__":
    main()
