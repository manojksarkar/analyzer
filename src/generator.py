"""
Generator: model/ (raw model) -> output/ (design views)

Option A: Raw model -> Design views
- model/: functions.json, globalVariables.json, units.json, modules.json (single source of truth)
- output/: interface_tables.json { unit_name: [{ interfaceId, type, ... }] }
"""
import os
import sys
import json
import re
from collections import defaultdict

from utils import get_module_name, norm_path, get_range_for_type, load_config
from interface_tables import build_interface_tables

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
MODEL_DIR = os.path.join(PROJECT_ROOT, "model")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
os.makedirs(MODEL_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

GETTER_PREFIXES = ("get", "is", "has", "read", "fetch", "load")
SETTER_PREFIXES = ("set", "add", "update", "write", "save", "put", "push", "insert", "remove", "delete", "clear")


def _load_model_inputs():
    funcs_path = os.path.join(MODEL_DIR, "functions.json")
    globals_path = os.path.join(MODEL_DIR, "globalVariables.json")
    metadata_path = os.path.join(MODEL_DIR, "metadata.json")
    if not os.path.exists(funcs_path) or not os.path.exists(globals_path):
        print("Error: model not found. Run parser first: python run.py test_cpp_project")
        raise SystemExit(1)

    with open(funcs_path, "r", encoding="utf-8") as f:
        functions_data = json.load(f)
    with open(globals_path, "r", encoding="utf-8") as f:
        global_variables_data = json.load(f)

    if not os.path.exists(metadata_path):
        print("Error: metadata.json not found. Run parser first.")
        raise SystemExit(1)
    with open(metadata_path, "r", encoding="utf-8") as f:
        meta_info = json.load(f)
    base_path = meta_info["basePath"]
    project_name = meta_info.get("projectName", os.path.basename(base_path))

    if isinstance(functions_data, list):
        functions_data = {f["location"]["file"] + ":" + str(f["location"]["line"]): f for f in functions_data}
    if isinstance(global_variables_data, list):
        global_variables_data = {g["location"]["file"] + ":" + str(g["location"]["line"]): g for g in global_variables_data}

    config = load_config(PROJECT_ROOT)
    return base_path, project_name, functions_data, global_variables_data, config


def _compute_unit_maps(base_path: str, functions_data: dict, global_variables_data: dict):
    """Compute file list, qualified name mapping, and unit names per file."""
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

    return file_paths, qualified_to_file, unit_by_file


def _build_units_modules(base_path: str, file_paths: list, functions_data: dict, global_variables_data: dict, qualified_to_file: dict, unit_by_file: dict):
    """Build units_data and modules_data and persist to model/."""
    module_names = sorted(
        {f.get("module", "") for f in functions_data.values() if f.get("module")}
        | {g.get("module", "") for g in global_variables_data.values() if g.get("module")}
    )

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

    modules_data = {
        mod: {
            "units": sorted(
                {unit_by_file[fp] for fp in file_paths if unit_by_file.get(fp, "").split("/")[0] == mod}
            )
        }
        for mod in module_names
    }

    with open(os.path.join(MODEL_DIR, "units.json"), "w", encoding="utf-8") as f:
        json.dump(units_data, f, indent=2)
    with open(os.path.join(MODEL_DIR, "modules.json"), "w", encoding="utf-8") as f:
        json.dump(modules_data, f, indent=2)
    print("  model/units.json (%d)" % len(units_data))
    print("  model/modules.json (%d)" % len(modules_data))

    return units_data, modules_data


def _build_interface_index(base_path: str, functions_data: dict, global_variables_data: dict):
    """Stable per-file index: file -> (sorted by line) => 01, 02, ..."""
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
    return all_entries, interface_index


def _maybe_enrich_descriptions(base_path: str, functions_data: dict, config: dict) -> dict:
    if not config.get("enableDescriptions"):
        return {}
    try:
        from llm_client import enrich_functions_with_descriptions
    except ImportError as e:
        print(f"LLM disabled: {e}")
        return {}

    funcs_only = [f for f in functions_data.values() if f.get("location")]
    if not funcs_only:
        return {}
    print("Enriching with LLM (Ollama)...")
    llm_data = enrich_functions_with_descriptions(funcs_only, base_path, config)
    if not any(v.get("description") for v in llm_data.values()):
        print("  Warning: No descriptions received. Is Ollama running? (ollama serve)")
    return llm_data


def _enrich_interfaces(
    base_path: str,
    project_name: str,
    all_entries: list,
    interface_index: dict,
    functions_data: dict,
    global_variables_data: dict,
    qualified_to_file: dict,
    unit_by_file: dict,
    llm_data: dict,
):
    project_code = project_name.upper()

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
            functions_data[iid].update(
                {
                    "interfaceId": interface_id,
                    "interfaceName": interface_name,
                    "callerUnits": sorted(caller_units_set),
                    "calleesUnits": sorted(callee_units_set),
                    "parameters": params_with_range,
                }
            )
            if llm_data.get(iid, {}).get("description"):
                functions_data[iid]["description"] = llm_data[iid]["description"]
        else:
            base_name = data["name"]
            interface_name = f"{file_code}_{base_name}" if base_name else file_code
            global_variables_data[iid].update(
                {
                    "interfaceId": interface_id,
                    "interfaceName": interface_name,
                    "callerUnits": [],
                    "calleesUnits": [],
                }
            )


def _infer_direction_from_code(base_path: str, functions_data: dict, global_variables_data: dict):
    """Populate functions_data[*]['direction'] and global_variables_data[*]['direction']."""
    try:
        # Reuse the same source extraction logic as the LLM client.
        from llm_client import extract_source as _extract_source
    except Exception:
        _extract_source = None

    global_names = sorted({(g.get("name") or "").strip() for g in global_variables_data.values() if (g.get("name") or "").strip()})
    if not global_names:
        return

    patterns = {}
    for name in global_names:
        word = re.compile(r"\b" + re.escape(name) + r"\b")
        assign = re.compile(r"\b" + re.escape(name) + r"\b\s*([+\-*/%&|^]?=)")
        incdec = re.compile(
            r"(\+\+\s*\b"
            + re.escape(name)
            + r"\b|\b"
            + re.escape(name)
            + r"\b\s*\+\+|--\s*\b"
            + re.escape(name)
            + r"\b|\b"
            + re.escape(name)
            + r"\b\s*--)"
        )
        patterns[name] = (word, assign, incdec)

    func_sources = {}
    if _extract_source:
        for fid, f in functions_data.items():
            loc = f.get("location") or {}
            if loc:
                func_sources[fid] = _extract_source(base_path, loc) or ""

    # Aggregate global read/write across all function bodies
    global_rw = {name: {"read": False, "write": False} for name in global_names}
    for src in func_sources.values():
        for name in global_names:
            word, assign, incdec = patterns[name]
            if assign.search(src) or incdec.search(src):
                global_rw[name]["write"] = True
            if word.search(src):
                global_rw[name]["read"] = True

    def _rw_to_dir(read_flag: bool, write_flag: bool) -> str:
        if read_flag and write_flag:
            return "In/Out"
        if write_flag:
            return "Out"
        if read_flag:
            return "In"
        return "-"

    for gid, g in global_variables_data.items():
        name = (g.get("name") or "").strip()
        rw = global_rw.get(name, {"read": False, "write": False})
        g["direction"] = _rw_to_dir(rw["read"], rw["write"])

    for fid, f in functions_data.items():
        fname = (f.get("name") or "").strip()
        lname = fname.lower()
        src = func_sources.get(fid, "")

        read_any = False
        write_any = False
        if src:
            for name in global_names:
                word, assign, incdec = patterns[name]
                if assign.search(src) or incdec.search(src):
                    write_any = True
                if word.search(src):
                    read_any = True
                if read_any and write_any:
                    break

        has_in = False
        has_out = False

        if lname.startswith(GETTER_PREFIXES):
            has_out = True
        if lname.startswith(SETTER_PREFIXES):
            has_in = True

        if write_any:
            has_in = True
        if read_any and not write_any and not has_in:
            has_out = True
        if read_any and write_any:
            has_in = True
            has_out = True

        params = f.get("params", []) or []
        if params and not has_out:
            has_in = True
        for p in params:
            t = (p.get("type") or "")
            tl = t.lower()
            if "&" in t and "const" not in tl:
                has_out = True
            if "*" in t and "const" not in tl:
                has_out = True

        if not has_in and not has_out:
            f["direction"] = "In/Out" if params else "Out"
        else:
            f["direction"] = "In/Out" if (has_in and has_out) else ("In" if has_in else "Out")


def _write_interface_tables_json(output_dir: str, units_data: dict, functions_data: dict, global_variables_data: dict):
    interface_tables = build_interface_tables(units_data, functions_data, global_variables_data)
    with open(os.path.join(output_dir, "interface_tables.json"), "w", encoding="utf-8") as f:
        json.dump(interface_tables, f, indent=2)
    print(
        "  output/interface_tables.json (%d units, %d functions, %d globals)"
        % (len(interface_tables), len(functions_data), len(global_variables_data))
    )


def main():
    base_path, project_name, functions_data, global_variables_data, config = _load_model_inputs()
    file_paths, qualified_to_file, unit_by_file = _compute_unit_maps(base_path, functions_data, global_variables_data)
    units_data, _modules_data = _build_units_modules(
        base_path, file_paths, functions_data, global_variables_data, qualified_to_file, unit_by_file
    )

    # View generation (interface tables)
    all_entries, interface_index = _build_interface_index(base_path, functions_data, global_variables_data)
    llm_data = _maybe_enrich_descriptions(base_path, functions_data, config)
    _enrich_interfaces(
        base_path=base_path,
        project_name=project_name,
        all_entries=all_entries,
        interface_index=interface_index,
        functions_data=functions_data,
        global_variables_data=global_variables_data,
        qualified_to_file=qualified_to_file,
        unit_by_file=unit_by_file,
        llm_data=llm_data,
    )
    _infer_direction_from_code(base_path, functions_data, global_variables_data)
    _write_interface_tables_json(OUTPUT_DIR, units_data, functions_data, global_variables_data)


if __name__ == "__main__":
    main()
