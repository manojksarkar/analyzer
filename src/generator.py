"""Model -> views."""
import os
import sys
import json
import re
from collections import defaultdict

from utils import get_module_name, norm_path, load_config, short_name, make_function_key, make_global_key, make_unit_key, path_from_unit_rel, KEY_SEP
from interface_tables import build_interface_tables

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
MODEL_DIR = os.path.join(PROJECT_ROOT, "model")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
os.makedirs(MODEL_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

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

    # Normalize to dict (support list input from older model)
    if isinstance(functions_data, list):
        functions_data = {make_function_key("", f.get("location",{}).get("file",""),
                         f.get("qualifiedName",""), f.get("parameters",f.get("params",[]))): f
                         for f in functions_data}
    if isinstance(global_variables_data, list):
        global_variables_data = {g["location"]["file"] + ":" + str(g["location"]["line"]): g for g in global_variables_data}

    config = load_config(PROJECT_ROOT)
    return base_path, project_name, functions_data, global_variables_data, config


def _file_path(data: dict, base_path: str) -> str:
    """Get normalized file path from location.file."""
    return norm_path((data.get("location") or {}).get("file", ""), base_path)


def _compute_unit_maps(base_path: str, functions_data: dict, global_variables_data: dict):
    all_file_paths = set(_file_path(f, base_path) for f in functions_data.values())
    all_file_paths.update(_file_path(g, base_path) for g in global_variables_data.values())
    file_paths = sorted(fp for fp in all_file_paths if fp)

    qualified_to_file = defaultdict(set)  # qualifiedName -> files (overloads may span files)
    for fid, f in functions_data.items():
        fp = _file_path(f, base_path)
        if fp:
            qualified_to_file[f.get("qualifiedName", "")].add(fp)

    # Unit key: module|filestem (preferred); use module|path when collision
    unit_by_file = {}
    key_to_fp = {}  # unit_key -> fp (to detect collisions)
    for fp in file_paths:
        try:
            rel = os.path.relpath(fp, base_path)
        except ValueError:
            rel = fp
        rel_norm = rel.replace("\\", "/")
        path_no_ext = path_from_unit_rel(rel_norm)
        base = os.path.basename(fp)
        filestem = os.path.splitext(base)[0]
        module = get_module_name(fp, base_path)
        preferred_key = make_unit_key(rel_norm)
        if preferred_key in key_to_fp and key_to_fp[preferred_key] != fp:
            unit_key = path_no_ext.replace("/", KEY_SEP)
        else:
            unit_key = preferred_key
        key_to_fp[unit_key] = fp
        unit_by_file[fp] = unit_key

    return file_paths, qualified_to_file, unit_by_file


def _build_units_modules(base_path: str, file_paths: list, functions_data: dict, global_variables_data: dict, qualified_to_file: dict, unit_by_file: dict):
    module_names = sorted({u.split(KEY_SEP)[0] for u in unit_by_file.values() if u and KEY_SEP in u})

    units_data = {}
    for fp in file_paths:
        base = os.path.basename(fp)
        if not base.lower().endswith((".cpp", ".cc", ".cxx")):
            continue
        unit_key = unit_by_file.get(fp) or make_unit_key(os.path.relpath(fp, base_path).replace("\\", "/") if fp else "")
        try:
            rel = os.path.relpath(fp, base_path)
        except ValueError:
            rel = fp
        path_no_ext = path_from_unit_rel(rel.replace("\\", "/"))

        func_ids = sorted([fid for fid, f in functions_data.items() if _file_path(f, base_path) == fp],
                         key=lambda x: functions_data[x].get("location", {}).get("line", 0))
        var_ids = sorted([vid for vid, g in global_variables_data.items() if _file_path(g, base_path) == fp],
                        key=lambda x: (global_variables_data[x].get("location") or {}).get("line", 0))

        caller_unit_names = set()
        callee_unit_names = set()
        for fid in func_ids:
            f = functions_data.get(fid, {})
            # Caller units from calledByIds
            for caller_id in f.get("calledByIds", []) or []:
                caller_func = functions_data.get(caller_id, {})
                cf = _file_path(caller_func, base_path)
                u = unit_by_file.get(cf)
                if u and u != unit_key:
                    caller_unit_names.add(u)
            # Callee units from callsIds
            for callee_id in f.get("callsIds", []) or []:
                callee_func = functions_data.get(callee_id, {})
                cf = _file_path(callee_func, base_path)
                u = unit_by_file.get(cf)
                if u and u != unit_key:
                    callee_unit_names.add(u)

        filestem = os.path.splitext(base)[0]
        units_data[unit_key] = {
            "name": filestem,
            "path": path_no_ext,
            "fileName": os.path.basename(fp),
            "functionIds": func_ids,
            "globalVariableIds": var_ids,
            "callerUnits": sorted(caller_unit_names),
            "calleesUnits": sorted(callee_unit_names),
        }

    modules_data = {
        mod: {"units": sorted(un for un in units_data if un.split(KEY_SEP)[0] == mod)}
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
    # Per-file index 01, 02, ... for stable interfaceId suffix
    all_entries = []
    for fid, f in functions_data.items():
        all_entries.append(("function", fid, f))
    for vid, g in global_variables_data.items():
        all_entries.append(("globalVariable", vid, g))

    by_file = defaultdict(list)
    for kind, iid, data in all_entries:
        fp = _file_path(data, base_path)
        if fp:
            by_file[fp].append((kind, iid, data))

    interface_index = {}
    for fp in sorted(by_file.keys()):
        entries = sorted(by_file[fp], key=lambda x: (x[2].get("location") or {}).get("line", 0))
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
    llm_data: dict,
):
    project_code = project_name.upper()

    for kind, iid, data in all_entries:
        loc = data.get("location") or {}
        fp = loc.get("file", "")
        try:
            rel = os.path.relpath(norm_path(fp, base_path), base_path).replace("\\", "/") if fp else fp
        except ValueError:
            rel = fp
        unit = os.path.splitext(rel)[0] if rel else ""
        unit_code = unit.replace("/", "_").upper()
        idx_code = f"{interface_index.get(iid, 0):02d}"
        interface_id = f"IF_{project_code}_{unit_code}_{idx_code}"

        if kind == "function":
            raw_params = data.get("params", data.get("parameters", []))
            parameters = [{"name": p.get("name", ""), "type": p.get("type", "")} for p in raw_params]
            functions_data[iid].update({"interfaceId": interface_id, "parameters": parameters})
            functions_data[iid].pop("params", None)
            llm_key = f"{loc.get('file', '')}:{loc.get('line', '')}"
            if llm_data.get(llm_key, {}).get("description"):
                functions_data[iid]["description"] = llm_data[llm_key]["description"]
        else:
            global_variables_data[iid].update({"interfaceId": interface_id})


def _infer_direction_from_code(
    base_path: str,
    functions_data: dict,
    global_variables_data: dict,
    config: dict,
    *,
    qualified_to_file: dict = None,
    unit_by_file: dict = None,
):
    try:
        # Reuse the same source extraction logic as the LLM client.
        from llm_client import extract_source as _extract_source
    except Exception:
        _extract_source = None

    global_names = sorted(
        {(short_name(g.get("qualifiedName", "")) or g.get("name", "") or "").strip()
         for g in global_variables_data.values()}
    )
    global_names = [n for n in global_names if n]

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
    if _extract_source and global_names:
        for fid, f in functions_data.items():
            loc = f.get("location") or {}
            if loc:
                func_sources[fid] = _extract_source(base_path, loc) or ""

    global_rw = {name: {"read": False, "write": False} for name in global_names}
    for src in func_sources.values():
        for name in global_names:
            word, assign, incdec = patterns[name]
            if assign.search(src) or incdec.search(src):
                global_rw[name]["write"] = True
            if word.search(src):
                global_rw[name]["read"] = True

    def _rw_to_dir(read_flag: bool, write_flag: bool) -> str:
        # Set (written) → In; not set (read-only) → Out; both → In/Out
        if read_flag and write_flag:
            return "In/Out"
        if write_flag:
            return "In"
        if read_flag:
            return "Out"
        return "-"

    for gid, g in global_variables_data.items():
        name = (short_name(g.get("qualifiedName", "")) or g.get("name", "") or "").strip()
        rw = global_rw.get(name, {"read": False, "write": False}) if global_names else {"read": False, "write": False}
        g["direction"] = _rw_to_dir(rw["read"], rw["write"])

    func_dir = {fid: None for fid in functions_data.keys()}
    for fid, f in functions_data.items():
        src = func_sources.get(fid, "")

        read_any = False
        write_any = False
        if src and global_names:
            for name in global_names:
                word, assign, incdec = patterns[name]
                if assign.search(src) or incdec.search(src):
                    write_any = True
                if word.search(src):
                    read_any = True
                if read_any and write_any:
                    break

        if write_any:
            func_dir[fid] = "Out"
        elif read_any:
            func_dir[fid] = "In"

    # Single-layer call-graph: if calls Out function (via precise ids), mark Out
    for fid, f in functions_data.items():
        if func_dir[fid] is not None:
            continue
        callees = f.get("callsIds", []) or []
        called_out = False
        for target_id in callees:
            if func_dir.get(target_id) == "Out":
                called_out = True
                break
        if called_out:
            func_dir[fid] = "Out"

    # If called from another unit → In (function is an input to this unit)
    for fid, f in functions_data.items():
        if func_dir[fid] is not None:
            continue
        if not unit_by_file:
            continue
        own_fp = _file_path(f, base_path)
        own_unit = unit_by_file.get(own_fp, "")
        caller_units = set()
        for caller_id in f.get("calledByIds", []) or []:
            cf = _file_path(functions_data.get(caller_id, {}), base_path)
            u = unit_by_file.get(cf, "")
            if u and u != own_unit:
                caller_units.add(u)
        if caller_units:
            func_dir[fid] = "In"

    undecided_fids = []
    for fid in functions_data.keys():
        if func_dir[fid] is None:
            func_dir[fid] = "In"
            undecided_fids.append(fid)

    for fid, direction in func_dir.items():
        functions_data[fid]["direction"] = direction

    if not config.get("enableDirectionLLM"):
        return
    try:
        from llm_client import enrich_functions_with_direction as _enrich_dir
    except Exception:
        return

    funcs_for_llm = [functions_data[fid] for fid in undecided_fids if functions_data[fid].get("location")]
    if not funcs_for_llm:
        return

    print("Enriching function directions with LLM (Ollama)...")
    dir_data = _enrich_dir(funcs_for_llm, base_path, config)
    for fid in undecided_fids:
        f = functions_data[fid]
        loc = f.get("location") or {}
        key = f"{loc.get('file', '')}:{loc.get('line', '')}" if loc else ""
        info = dir_data.get(key, {}) if key else {}
        label = info.get("direction")
        if label in ("In", "Out", "In/Out"):
            f["direction"] = label


def _write_interface_tables_json(output_dir: str, units_data: dict, functions_data: dict, global_variables_data: dict):
    data_dict = {}
    dd_path = os.path.join(MODEL_DIR, "dataDictionary.json")
    if os.path.exists(dd_path):
        with open(dd_path, "r", encoding="utf-8") as f:
            data_dict = json.load(f)
    interface_tables = build_interface_tables(units_data, functions_data, global_variables_data, data_dict)
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

    all_entries, interface_index = _build_interface_index(base_path, functions_data, global_variables_data)
    llm_data = _maybe_enrich_descriptions(base_path, functions_data, config)
    _enrich_interfaces(
        base_path=base_path,
        project_name=project_name,
        all_entries=all_entries,
        interface_index=interface_index,
        functions_data=functions_data,
        global_variables_data=global_variables_data,
        llm_data=llm_data,
    )
    _infer_direction_from_code(
        base_path, functions_data, global_variables_data, config,
        qualified_to_file=qualified_to_file,
        unit_by_file=unit_by_file,
    )

    # Persist enriched model (single source of truth, non-redundant)
    for f in functions_data.values():
        f.pop("name", None)
        f.pop("interfaceName", None)
        f.pop("module", None)
    for g in global_variables_data.values():
        g.pop("name", None)
        g.pop("interfaceName", None)
        g.pop("module", None)
    with open(os.path.join(MODEL_DIR, "functions.json"), "w", encoding="utf-8") as f:
        json.dump(functions_data, f, indent=2)
    with open(os.path.join(MODEL_DIR, "globalVariables.json"), "w", encoding="utf-8") as f:
        json.dump(global_variables_data, f, indent=2)

    _write_interface_tables_json(OUTPUT_DIR, units_data, functions_data, global_variables_data)


if __name__ == "__main__":
    main()
