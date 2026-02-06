"""
Generator: metadata.json -> interfaces, component, units
"""
import os
import sys
import json
from collections import defaultdict

from utils import get_module_name, norm_path, get_range_for_type

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

    base_path = meta["basePath"]
    project_name = meta.get("projectName", os.path.basename(base_path))
    project_code = project_name.upper()
    functions_data = meta.get("functions", [])
    global_variables_data = meta.get("globalVariables", [])

    functions_list = []
    for f in functions_data:
        loc = f["location"]
        full_path = norm_path(loc["file"], base_path)
        functions_list.append({
            "functionName": f["name"],
            "qualifiedName": f.get("qualifiedName", f["name"]),
            "functionId": f"{full_path}:{loc['line']}",
            "moduleName": f.get("module", ""),
            "parameters": f.get("params", []),
            "callersFunctionNames": f.get("callersFunctionNames", []),
            "calleesFunctionNames": f.get("calleesFunctionNames", []),
        })

    file_paths = sorted(set(norm_path(f["functionId"].rsplit(":", 1)[0], base_path) for f in functions_list))
    qualified_to_file = defaultdict(set)
    for f in functions_list:
        fp = norm_path(f["functionId"].rsplit(":", 1)[0], base_path)
        qualified_to_file[f["qualifiedName"]].add(fp)

    unit_by_file = {}
    for fp in file_paths:
        try:
            rel = os.path.relpath(fp, base_path)
        except ValueError:
            rel = fp
        unit_module = get_module_name(rel.replace("\\", "/"), base_path)
        unit_by_file[fp] = f"{unit_module}/{os.path.basename(fp)}"

    # --- Component diagram ---
    module_to_funcs = defaultdict(list)
    for f in functions_list:
        module_to_funcs[f["moduleName"]].append(f)
    module_names = sorted(module_to_funcs.keys())
    caller_sets = defaultdict(set)
    callee_sets = defaultdict(set)

    for mod in module_names:
        for f in module_to_funcs[mod]:
            for c in f["callersFunctionNames"]:
                for cf in qualified_to_file.get(c, []):
                    try:
                        rel_cf = os.path.relpath(cf, base_path)
                    except ValueError:
                        rel_cf = cf
                    um = get_module_name(rel_cf.replace("\\", "/"), base_path)
                    if um != mod:
                        caller_sets[mod].add(um)
            for c in f["calleesFunctionNames"]:
                for cf in qualified_to_file.get(c, []):
                    try:
                        rel_cf = os.path.relpath(cf, base_path)
                    except ValueError:
                        rel_cf = cf
                    um = get_module_name(rel_cf.replace("\\", "/"), base_path)
                    if um != mod:
                        callee_sets[mod].add(um)

    components_data = []
    for mod in module_names:
        components_data.append({
            "name": mod,
            "incoming": sorted(caller_sets[mod]),
            "outgoing": sorted(callee_sets[mod]),
            "functions": [f["functionName"] for f in module_to_funcs[mod]],
        })

    with open(os.path.join(OUTPUT_DIR, "component.json"), "w", encoding="utf-8") as f:
        json.dump({"basePath": base_path, "components": components_data}, f, indent=2)
    print(f"Generated: output/component.json ({len(components_data)} components)")

    # --- Unit design ---
    units_data = []
    for fp in file_paths:
        funcs_in = [f for f in functions_list if norm_path(f["functionId"].rsplit(":", 1)[0], base_path) == fp]
        unit_name = unit_by_file.get(fp) or f"{get_module_name(fp, base_path)}/{os.path.basename(fp)}"
        caller_units = defaultdict(set)
        callee_units = defaultdict(set)
        for f in funcs_in:
            for cn in f["callersFunctionNames"]:
                for cf in qualified_to_file.get(cn, []):
                    u = unit_by_file.get(cf)
                    if u and u != unit_name:
                        caller_units[u].add(cn)
            for cn in f["calleesFunctionNames"]:
                for cf in qualified_to_file.get(cn, []):
                    u = unit_by_file.get(cf)
                    if u and u != unit_name:
                        callee_units[u].add(cn)
        units_data.append({
            "unitName": unit_name,
            "fileName": os.path.basename(fp),
            "moduleName": unit_name.split("/")[0],
            "functionNames": sorted(set(f["qualifiedName"] for f in funcs_in)),
            "callerUnits": [{"unitName": u, "functionNames": sorted(fns)} for u, fns in sorted(caller_units.items())],
            "calleesUnits": [{"unitName": u, "functionNames": sorted(fns)} for u, fns in sorted(callee_units.items())],
        })

    with open(os.path.join(OUTPUT_DIR, "units.json"), "w", encoding="utf-8") as f:
        json.dump({"basePath": base_path, "units": units_data}, f, indent=2)
    print(f"Generated: output/units.json ({len(units_data)} units)")

    # --- Interface table ---
    all_entries = []
    for f in functions_data:
        all_entries.append(("function", f["id"], f))
    for g in global_variables_data:
        all_entries.append(("globalVariable", g["id"], g))

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

    interfaces_data = []
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
            interfaces_data.append({
                "interfaceId": interface_id,
                "interfaceName": interface_name,
                "interfaceType": "function",
                "parameters": params_with_range,
                "callerUnits": sorted(caller_units_set),
                "calleesUnits": sorted(callee_units_set),
            })
        else:
            base_name = data["name"]
            interface_name = f"{file_code}_{base_name}" if base_name else file_code
            interfaces_data.append({
                "interfaceId": interface_id,
                "interfaceName": interface_name,
                "interfaceType": "globalVariable",
                "parameters": [],
                "callerUnits": [],
                "calleesUnits": [],
            })

    with open(os.path.join(OUTPUT_DIR, "interfaces.json"), "w", encoding="utf-8") as f:
        json.dump({"basePath": base_path, "interfaces": interfaces_data}, f, indent=2)
    print(f"Generated: output/interfaces.json ({len(interfaces_data)} interfaces)")


if __name__ == "__main__":
    main()
