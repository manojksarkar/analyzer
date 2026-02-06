"""
Generator: metadata.json -> interfaces, modules, units
Optionally enriches with LLM-generated descriptions and flowcharts (Ollama).
"""
import os
import sys
import json
from collections import defaultdict

from utils import get_module_name, norm_path, get_range_for_type, load_config

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
METADATA_PATH = os.path.join(PROJECT_ROOT, "output", "metadata.json")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def main():
    if not os.path.exists(METADATA_PATH):
        print(f"Error: metadata not found at {METADATA_PATH}")
        print("Run parser first: python run.py test_cpp_project")
        sys.exit(1)

    with open(METADATA_PATH, "r", encoding="utf-8") as f:
        meta = json.load(f)

    config = load_config(PROJECT_ROOT)
    base_path = meta["basePath"]
    project_name = meta.get("projectName", os.path.basename(base_path))
    project_code = project_name.upper()

    # Support both dict (new) and list (legacy) format
    _raw_functions = meta.get("functions", {})
    if isinstance(_raw_functions, list):
        functions_data = {f["location"]["file"] + ":" + str(f["location"]["line"]): f for f in _raw_functions}
    else:
        functions_data = _raw_functions

    _raw_globals = meta.get("globalVariables", {})
    if isinstance(_raw_globals, list):
        global_variables_data = {g["location"]["file"] + ":" + str(g["location"]["line"]): g for g in _raw_globals}
    else:
        global_variables_data = _raw_globals

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

    file_paths = sorted(set(norm_path(fid.rsplit(":", 1)[0], base_path) for fid in functions_data.keys()))
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

    module_names = sorted({f.get("module", "") for f in functions_data.values() if f.get("module")})

    modules_data = {}
    for mod in module_names:
        mod_units = sorted({unit_by_file[fp] for fp in file_paths
            if unit_by_file.get(fp, "").split("/")[0] == mod})
        modules_data[mod] = {"units": mod_units}

    with open(os.path.join(OUTPUT_DIR, "modules.json"), "w", encoding="utf-8") as f:
        json.dump({"basePath": base_path, "modules": modules_data}, f, indent=2)
    print(f"Generated: output/modules.json ({len(modules_data)} modules)")

    # --- Unit design ---
    units_data = {}
    for fp in file_paths:
        unit_name = unit_by_file.get(fp) or f"{get_module_name(fp, base_path)}/{os.path.basename(fp)}"
        func_ids = sorted([fid for fid in functions_data if norm_path(fid.rsplit(":", 1)[0], base_path) == fp])
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
            "callerUnits": sorted(caller_unit_names),
            "calleesUnits": sorted(callee_unit_names),
        }

    with open(os.path.join(OUTPUT_DIR, "units.json"), "w", encoding="utf-8") as f:
        json.dump({"basePath": base_path, "units": units_data}, f, indent=2)
    print(f"Generated: output/units.json ({len(units_data)} units)")

    # --- Interface table ---
    all_entries = []
    for fid, f in functions_data.items():
        all_entries.append(("function", fid, {**f, "id": fid}))
    for vid, g in global_variables_data.items():
        all_entries.append(("globalVariable", vid, {**g, "id": vid}))

    by_file = defaultdict(list)
    for kind, iid, data in all_entries:
        fp = norm_path(iid.rsplit(":", 1)[0], base_path)
        by_file[fp].append((kind, iid, data))
    ordered = []
    for fp in sorted(by_file.keys()):
        entries = sorted(by_file[fp], key=lambda x: int(x[1].rsplit(":", 1)[1]))
        ordered.extend(entries)

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

    interfaces_data = {}
    for kind, iid, data in ordered:
        fp = iid.rsplit(":", 1)[0]
        abs_fp = norm_path(fp, base_path)
        try:
            rel = os.path.relpath(abs_fp, base_path)
        except ValueError:
            rel = fp
        module_name = get_module_name(rel.replace("\\", "/"), base_path)
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
            entry = {
                "interfaceName": interface_name,
                "interfaceType": "function",
                "functionId": iid,
                "parameters": params_with_range,
                "callerUnits": sorted(caller_units_set),
                "calleesUnits": sorted(callee_units_set),
            }
            loc = data.get("location", {})
            lookup_key = f"{loc.get('file', '')}:{loc.get('line', '')}" if loc else ""
            llm_info = llm_data.get(lookup_key, {}) if lookup_key else {}
            if llm_info.get("description"):
                entry["description"] = llm_info["description"]
            if llm_info.get("flowchart"):
                entry["flowchart"] = llm_info["flowchart"]
            interfaces_data[interface_id] = entry
        else:
            base_name = data["name"]
            interface_name = f"{file_code}_{base_name}" if base_name else file_code
            interfaces_data[interface_id] = {
                "interfaceName": interface_name,
                "interfaceType": "globalVariable",
                "variableId": iid,
                "parameters": [],
                "callerUnits": [],
                "calleesUnits": [],
            }

    with open(os.path.join(OUTPUT_DIR, "interfaces.json"), "w", encoding="utf-8") as f:
        json.dump({"basePath": base_path, "interfaces": interfaces_data}, f, indent=2)
    print(f"Generated: output/interfaces.json ({len(interfaces_data)} interfaces)")


if __name__ == "__main__":
    main()
