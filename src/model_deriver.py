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


def _enrich_from_llm(base_path: str, functions_data: dict, global_variables_data: dict, config: dict):
    """LLM enrichment for descriptions only. Direction comes from parser (global read/write analysis)."""
    llm = config.get("llm") or {}
    if not llm.get("descriptions", True):
        return
    try:
        from llm_client import enrich_functions_with_descriptions, enrich_globals_with_descriptions
    except ImportError:
        return
    funcs_list = [{"id": key, **value} for key, value in functions_data.items() ]
    desc = enrich_functions_with_descriptions(funcs_list, base_path, config)
    for key, f in functions_data.items():
        if desc.get(key, {}).get("description"):
            f["description"] = desc[key]["description"]
    globals_list = list(global_variables_data.values())
    g_desc = enrich_globals_with_descriptions(globals_list, base_path, config)
    for g in globals_list:
        key = f"{g.get('location', {}).get('file', '')}:{g.get('location', {}).get('line', '')}"
        if g_desc.get(key, {}).get("description"):
            g["description"] = g_desc[key]["description"]


def _readable_label(name: str) -> str:
    """Convert identifier or type name into a short human label."""
    if not name:
        return ""
    # Strip common prefixes
    for prefix in ("g_", "s_", "t_"):
        if name.startswith(prefix):
            name = name[len(prefix) :]
            break
    name = name.replace("_", " ")
    name = name.strip()
    # Ignore very short/meaningless identifiers (e.g. "i", "v", "x")
    if len(name) <= 2:
        return ""
    # Simple capitalization
    return name[:1].upper() + name[1:] if name else ""


def _propagate_global_access(functions_data: dict):
    """Propagate global reads/writes along call graph so outers see inner globals."""
    # Build adjacency and initial direct sets
    calls_map = {}
    reads_map = {}
    writes_map = {}
    for fid, f in functions_data.items():
        calls_map[fid] = list(f.get("callsIds") or [])
        reads_map[fid] = set(f.get("readsGlobalIds") or [])
        writes_map[fid] = set(f.get("writesGlobalIds") or [])

    # Fixed-point propagation: repeatedly add callee globals to caller
    changed = True
    while changed:
        changed = False
        for fid, callees in calls_map.items():
            for cid in callees:
                if cid not in reads_map or cid not in writes_map:
                    continue
                before_r = len(reads_map[fid])
                before_w = len(writes_map[fid])
                reads_map[fid] |= reads_map[cid]
                writes_map[fid] |= writes_map[cid]
                if len(reads_map[fid]) != before_r or len(writes_map[fid]) != before_w:
                    changed = True

    # Store transitive sets back into functions_data
    for fid, f in functions_data.items():
        if reads_map.get(fid):
            f["readsGlobalIdsTransitive"] = sorted(reads_map[fid])
        if writes_map.get(fid):
            f["writesGlobalIdsTransitive"] = sorted(writes_map[fid])


def _enrich_behaviour_names(functions_data: dict, global_variables_data: dict):
    """Populate behaviourInputName / behaviourOutputName statically from params, globals, returnType."""
    primitive_types = {"void", "int", "bool", "float", "double", "char", "short", "long"}
    for fid, f in functions_data.items():
        params = f.get("parameters") or f.get("params") or []
        # Prefer transitive read/write sets if present (includes inner calls)
        reads_ids = f.get("readsGlobalIdsTransitive") or f.get("readsGlobalIds") or []
        writes_ids = f.get("writesGlobalIdsTransitive") or f.get("writesGlobalIds") or []
        return_type = (f.get("returnType") or "").strip()
        return_expr = (f.get("returnExpr") or "").strip()

        in_label = ""
        out_label = ""

        # Input Name: prefer main parameter; fall back to first written global; then first read global.
        main_param_name = ""
        if isinstance(params, list) and params:
            main_param_name = (params[0].get("name") or "").strip()
        if main_param_name:
            in_label = _readable_label(main_param_name)
        elif writes_ids:
            g = (global_variables_data or {}).get(writes_ids[0]) or {}
            g_name = (g.get("qualifiedName") or "").split("::")[-1]
            in_label = _readable_label(g_name)
        elif reads_ids:
            g = (global_variables_data or {}).get(reads_ids[0]) or {}
            g_name = (g.get("qualifiedName") or "").split("::")[-1]
            in_label = _readable_label(g_name)

        # Output Name: prefer simple return expression identifier; then non-primitive return type; else written/read global.
        # Try to use a simple identifier from the return expression, e.g. 'release_status'
        simple_ret_ident = ""
        if return_expr:
            # Heuristic: take first token before any operators or punctuation
            for ch in "();,+-*/%&|^<>!?:":
                return_expr = return_expr.replace(ch, " ")
            parts = [p for p in return_expr.split() if p]
            cand = parts[0] if parts else ""
            if cand and (cand[0].isalpha() or cand[0] == "_"):
                simple_ret_ident = cand
        if simple_ret_ident:
            out_label = _readable_label(simple_ret_ident)
        else:
            base_ret = return_type.split()[-1] if return_type else ""
            if base_ret and base_ret not in primitive_types:
                out_label = _readable_label(base_ret)
        if not out_label and writes_ids:
            g = (global_variables_data or {}).get(writes_ids[0]) or {}
            g_name = (g.get("qualifiedName") or "").split("::")[-1]
            out_label = _readable_label(g_name)
        elif not out_label and reads_ids:
            g = (global_variables_data or {}).get(reads_ids[0]) or {}
            g_name = (g.get("qualifiedName") or "").split("::")[-1]
            out_label = _readable_label(g_name)

        # As a last resort, derive from function base name itself.
        if (not in_label) or (not out_label):
            qn = f.get("qualifiedName", "") or ""
            base_name = qn.split("::")[-1] if qn else ""
            base_fn = _readable_label(base_name)
            if not in_label:
                in_label = (base_fn + " input").strip() if base_fn else "Behaviour input"
            if not out_label:
                out_label = (base_fn + " result").strip() if base_fn else "Behaviour result"

        f["behaviourInputName"] = in_label
        f["behaviourOutputName"] = out_label


def _static_behaviour_name_is_poor(f: dict) -> bool:
    """True if we should ask LLM to improve Input/Output names (generic or function-name fallback)."""
    inp = (f.get("behaviourInputName") or "").strip()
    out = (f.get("behaviourOutputName") or "").strip()
    if not inp or not out:
        return True
    if inp.endswith(" input") or inp.endswith(" result"):
        return True
    if out.endswith(" input") or out.endswith(" result"):
        return True
    return False


def _enrich_behaviour_names_llm(
    base_path: str,
    functions_data: dict,
    global_variables_data: dict,
    config: dict,
):
    """Use LLM to improve behaviourInputName/behaviourOutputName when static names are poor. Uses abbreviations."""
    llm = config.get("llm") or {}
    if not llm.get("behaviourNames", True):
        return
    try:
        from llm_client import (
            _ollama_available,
            extract_source,
            get_behaviour_names,
            load_abbreviations,
        )
    except ImportError:
        return
    if not _ollama_available(config):
        return
    abbreviations = load_abbreviations(PROJECT_ROOT, config)
    order = list(functions_data.keys())
    n = len(order)
    for idx, fid in enumerate(order):
        f = functions_data.get(fid)
        if not f or not _static_behaviour_name_is_poor(f):
            continue
        loc = f.get("location") or {}
        source = extract_source(base_path, loc)
        if not source:
            continue
        params = f.get("parameters") or f.get("params") or []
        reads_ids = f.get("readsGlobalIdsTransitive") or f.get("readsGlobalIds") or []
        writes_ids = f.get("writesGlobalIdsTransitive") or f.get("writesGlobalIds") or []
        def _globals_list(gids):
            out = []
            for gid in gids:
                g = (global_variables_data or {}).get(gid) or {}
                out.append({
                    "name": (g.get("qualifiedName") or "").split("::")[-1],
                    "qualifiedName": g.get("qualifiedName", ""),
                    "type": g.get("type", ""),
                    "description": g.get("description", ""),
                })
            return out
        globals_read = _globals_list(reads_ids)
        globals_written = _globals_list(writes_ids)
        return_type = (f.get("returnType") or "").strip()
        return_expr = (f.get("returnExpr") or "").strip()
        draft_input = (f.get("behaviourInputName") or "").strip()
        draft_output = (f.get("behaviourOutputName") or "").strip()
        res = get_behaviour_names(
            source, params, globals_read, globals_written, return_type, return_expr,
            draft_input, draft_output, config, abbreviations,
        )
        if res.get("behaviourInputName"):
            f["behaviourInputName"] = res["behaviourInputName"]
        if res.get("behaviourOutputName"):
            f["behaviourOutputName"] = res["behaviourOutputName"]
        qn = (f.get("qualifiedName") or "").split("::")[-1]
        print(f"  LLM behaviour names [{idx + 1}/{n}] {qn or fid}", end="\r", flush=True)
    print(flush=True)


def main():
    base_path, project_name, functions_data, global_variables_data = _load_model()
    config = load_config(PROJECT_ROOT)

    units_data, unit_by_file = _build_units_modules(base_path, functions_data, global_variables_data)
    idx_by_id = _build_interface_index(base_path, functions_data, global_variables_data)
    _enrich_interfaces(base_path, project_name, functions_data, global_variables_data, idx_by_id)
    # Propagate global access along call graph so outers inherit inner globals
    _propagate_global_access(functions_data)
    # Static behaviour names (Input Name / Output Name) from params/globals/returnType
    _enrich_behaviour_names(functions_data, global_variables_data)
    # LLM polish for poor static names (uses abbreviations)
    _enrich_behaviour_names_llm(base_path, functions_data, global_variables_data, config)
    _enrich_from_llm(base_path, functions_data, global_variables_data, config)

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
