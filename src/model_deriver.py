"""Derive model: units, modules, enrichment. Phase 2."""
import os
import re
import sys
import json

from utils import load_config, norm_path, make_unit_key, path_from_unit_rel, KEY_SEP
from core.paths import paths as _paths

_p = _paths()
SCRIPT_DIR = _p.src_dir
PROJECT_ROOT = _p.project_root
MODEL_DIR = _p.model_dir
os.makedirs(MODEL_DIR, exist_ok=True)


def _load_model():
    from core.model_io import load_model, METADATA, FUNCTIONS, GLOBALS, ModelFileMissing
    try:
        m = load_model(METADATA, FUNCTIONS, GLOBALS)
    except ModelFileMissing as e:
        print(f"Error: {e}. Run Phase 1 (parser) first.")
        raise SystemExit(1)
    meta = m[METADATA]
    base_path = meta["basePath"]
    project_name = meta.get("projectName", os.path.basename(base_path))
    return base_path, project_name, m[FUNCTIONS], m[GLOBALS]


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

    from core.model_io import write_model_file, UNITS, MODULES
    write_model_file(UNITS, units_data)
    write_model_file(MODULES, modules_data)
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
        from llm_enrichment import (
            enrich_functions_with_descriptions, enrich_globals_with_descriptions,
            enrich_functions_rich, enrich_globals_rich,
        )
    except ImportError:
        return

    # Try to load existing knowledge_base.json for richer context.
    # On first run it won't exist — the rich path still works (just without
    # repo map and sibling context), and the knowledge base is generated after.
    knowledge = None
    try:
        from flowchart.pkb.knowledge import load_knowledge
        from core.paths import paths
        import os
        kb_path = os.path.join(paths().model_dir, "knowledge_base.json")
        knowledge = load_knowledge(kb_path)
    except Exception:
        pass

    # Rich enrichment path — budget-aware with degradation ladder
    desc = enrich_functions_rich(functions_data, base_path, config, knowledge=knowledge)
    for key, f in functions_data.items():
        if desc.get(key, {}).get("description"):
            f["description"] = desc[key]["description"]

    # Rich global enrichment
    enrichment_cfg = llm.get("enrichment") or {}
    if enrichment_cfg.get("variableEnrichment", True):
        g_desc = enrich_globals_rich(
            global_variables_data, functions_data, base_path, config,
            knowledge=knowledge,
        )
    else:
        globals_list = list(global_variables_data.values())
        g_desc = enrich_globals_with_descriptions(globals_list, base_path, config)
    for g in global_variables_data.values():
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
        from llm_enrichment import (
            llm_provider_reachable,
            extract_source,
            get_behaviour_names,
            load_abbreviations,
        )
    except ImportError:
        return
    if not llm_provider_reachable(config):
        return
    from core.progress import ProgressReporter
    from core.logging_setup import get_logger
    abbreviations = load_abbreviations(PROJECT_ROOT, config)
    order = list(functions_data.keys())
    n = len(order)
    progress = ProgressReporter("LLM-behaviour-names", total=n, logger=get_logger("model_deriver"))
    progress.start()
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
        progress.step(label=qn or fid)
    progress.done()


# ---------------------------------------------------------------------------
# LLM summarization (--llm-summarize) — delegates to Flowchart's HierarchySummarizer
# ---------------------------------------------------------------------------

def _build_signature(f: dict) -> str:
    """Build a C++ function signature string from a function data dict."""
    qn = f.get("qualifiedName", "")
    ret = f.get("returnType", "")
    params = f.get("parameters") or f.get("params") or []
    param_str = ", ".join(
        f"{p.get('type', '')} {p.get('name', '')}".strip()
        for p in params
    )
    return f"{ret} {qn}({param_str})".strip()


def _run_hierarchy_summarizer(
    base_path: str,
    project_name: str,
    functions_data: dict,
    config: dict,
) -> dict:
    """
    Run the Flowchart engine's HierarchySummarizer on the current model data.

    Reuses the existing implementation in src/flowchart/project_scanner.py rather
    than duplicating the prompts and logic here.

    Steps:
      1. Build a ProjectKnowledge object from functions_data (no extra LLM calls)
      2. Run HierarchySummarizer.summarize() — 4 levels: function, file, module, project
      3. Write phases back into functions_data in place
      4. Return {"project", "modules", "files"} for knowledge_base.json

    Returns empty summaries dict if the flowchart module cannot be imported.
    """
    # Import the shared LLM client from src/llm_core BEFORE inserting
    # src/flowchart into sys.path — once flowchart is on the path, the bare
    # name `llm` would resolve to src/flowchart/llm/ (which is itself a shim).
    from llm_core.client import from_config as _build_llm_client_from_config
    _fc_dir = os.path.join(SCRIPT_DIR, "flowchart")
    if _fc_dir not in sys.path:
        sys.path.insert(0, _fc_dir)
    try:
        from project_scanner import HierarchySummarizer
        from pkb.knowledge import FunctionKnowledge, ProjectKnowledge
    except ImportError as exc:
        print(f"  Cannot import Flowchart HierarchySummarizer: {exc}", file=sys.stderr)
        return {"project": "", "modules": {}, "files": {}}

    # Build ProjectKnowledge from already-parsed model data (no extra LLM/libclang calls)
    knowledge = ProjectKnowledge(project_name=project_name, base_path=base_path)
    for fid, f in functions_data.items():
        qn = f.get("qualifiedName", "")
        if not qn:
            continue
        fk = FunctionKnowledge(
            qualified_name=qn,
            signature=_build_signature(f),
            file=(f.get("location") or {}).get("file", ""),
            line=(f.get("location") or {}).get("line", 0),
            description=f.get("description", ""),
            calls=[
                functions_data[c].get("qualifiedName", c)
                for c in (f.get("callsIds") or [])
                if c in functions_data
            ],
            phases=f.get("phases", []),
        )
        knowledge.functions[qn] = fk

    # Create LlmClient via the unified config loader so the provider switch
    # (ollama / openai) and custom headers / retries / timeouts all work.
    from utils import load_llm_config
    client = _build_llm_client_from_config(load_llm_config(config))

    # Run the 4-level summarization (function summaries, phases, file, module, project)
    summarizer = HierarchySummarizer(knowledge, client, base_path)
    summarizer.summarize()

    # Write phases back into functions_data in place
    qn_to_fid = {f.get("qualifiedName", ""): fid for fid, f in functions_data.items()}
    for qn, fk in knowledge.functions.items():
        if fk.phases:
            fid = qn_to_fid.get(qn)
            if fid and fid in functions_data:
                functions_data[fid]["phases"] = fk.phases
        # Also back-fill description if HierarchySummarizer added one for an undocumented function
        if fk.description:
            fid = qn_to_fid.get(qn)
            if fid and fid in functions_data and not functions_data[fid].get("description"):
                functions_data[fid]["description"] = fk.description

    return {
        "project": knowledge.project_summary,
        "modules": knowledge.module_summaries,
        "files": knowledge.file_summaries,
    }


def _generate_knowledge_base(
    base_path: str,
    project_name: str,
    functions_data: dict,
    global_variables_data: dict,
    data_dict: dict,
    summaries: dict,
) -> None:
    """Write model/knowledge_base.json in the format expected by Flowchart's pkb/builder.py."""
    # Build fid → qualifiedName mapping for reverse lookups
    fid_to_qn = {fid: f.get("qualifiedName", "") for fid, f in functions_data.items()}

    functions_kb: dict = {}
    for fid, fentry in functions_data.items():
        qn = fentry.get("qualifiedName", "")
        if not qn:
            continue
        calls_qnames = [
            functions_data[c].get("qualifiedName", c)
            for c in (fentry.get("callsIds") or [])
            if c in functions_data
        ]
        # Reverse call graph: resolve calledByIds to qualified names
        called_by_qnames = [
            fid_to_qn[c]
            for c in (fentry.get("calledByIds") or [])
            if c in fid_to_qn and fid_to_qn[c]
        ]
        # Global variable names this function reads/writes (transitive)
        reads_globals = [
            (global_variables_data.get(gid) or {}).get("qualifiedName", gid)
            for gid in (fentry.get("readsGlobalIdsTransitive") or fentry.get("readsGlobalIds") or [])
        ]
        writes_globals = [
            (global_variables_data.get(gid) or {}).get("qualifiedName", gid)
            for gid in (fentry.get("writesGlobalIdsTransitive") or fentry.get("writesGlobalIds") or [])
        ]
        functions_kb[qn] = {
            "qualifiedName": qn,
            "signature": _build_signature(fentry),
            "returnType": fentry.get("returnType", ""),
            "parameters": fentry.get("parameters") or fentry.get("params") or [],
            "file": (fentry.get("location") or {}).get("file", ""),
            "line": (fentry.get("location") or {}).get("line", 0),
            "description": fentry.get("description", ""),
            "calls": calls_qnames,
            "calledBy": called_by_qnames,
            "readsGlobals": reads_globals,
            "writesGlobals": writes_globals,
            "phases": fentry.get("phases", []),
        }

    enums_kb: dict = {}
    macros_kb: dict = {}
    typedefs_kb: dict = {}
    structs_kb: dict = {}
    for key, entry in data_dict.items():
        kind = entry.get("kind", "")
        file_val = (entry.get("location") or {}).get("file", "")
        if kind == "enum":
            qn = entry.get("qualifiedName", key)
            values: dict = {}
            for e in entry.get("enumerators", []):
                ename = e.get("name", "")
                if ename:
                    values[ename] = {"value": str(e.get("value", "")), "comment": e.get("comment", "")}
            enums_kb[qn] = {
                "qualifiedName": qn,
                "file": file_val,
                "comment": entry.get("comment", ""),
                "values": values,
            }
        elif kind == "define":
            name = entry.get("name", "")
            if name:
                macros_kb[name] = {
                    "name": name,
                    "value": entry.get("value", ""),
                    "file": file_val,
                    "comment": entry.get("comment", ""),
                }
        elif kind == "typedef":
            qn = entry.get("qualifiedName", key)
            if qn:
                typedefs_kb[qn] = {
                    "name": entry.get("name", qn),
                    "underlying": entry.get("underlyingType", ""),
                    "file": file_val,
                    "comment": entry.get("comment", ""),
                }
        elif kind in ("struct", "class"):
            qn = entry.get("qualifiedName", key)
            if qn:
                members: dict = {}
                for field_item in entry.get("fields", []):
                    fname = field_item.get("name", "")
                    if fname:
                        members[fname] = {
                            "type": field_item.get("type", ""),
                            "comment": field_item.get("comment", ""),
                        }
                structs_kb[qn] = {
                    "qualifiedName": qn,
                    "file": file_val,
                    "comment": entry.get("comment", ""),
                    "members": members,
                }

    # Build globals section: each global with its type, value, and access context.
    # Resolve read_by / written_by by scanning functions for global references.
    globals_kb: dict = {}
    for gid, gentry in global_variables_data.items():
        gqn = gentry.get("qualifiedName", "")
        if not gqn:
            continue
        # Find which functions read/write this global (transitive)
        read_by = []
        written_by = []
        for fid2, f2 in functions_data.items():
            f2_qn = f2.get("qualifiedName", "")
            if not f2_qn:
                continue
            reads = set(f2.get("readsGlobalIdsTransitive") or f2.get("readsGlobalIds") or [])
            writes = set(f2.get("writesGlobalIdsTransitive") or f2.get("writesGlobalIds") or [])
            if gid in reads:
                read_by.append(f2_qn)
            if gid in writes:
                written_by.append(f2_qn)
        raw_value = (gentry.get("value") or "").split(";")[0].strip()
        globals_kb[gqn] = {
            "qualifiedName": gqn,
            "type": gentry.get("type", ""),
            "file": (gentry.get("location") or {}).get("file", ""),
            "description": gentry.get("description", ""),
            "value": raw_value,
            "readBy": read_by,
            "writtenBy": written_by,
        }

    kb = {
        "project_name": project_name,
        "base_path": base_path,
        "project_summary": summaries.get("project", ""),
        "module_summaries": summaries.get("modules", {}),
        "file_summaries": summaries.get("files", {}),
        "functions": functions_kb,
        "enums": enums_kb,
        "macros": macros_kb,
        "typedefs": typedefs_kb,
        "structs": structs_kb,
        "globals": globals_kb,
    }
    from core.model_io import write_model_file, KNOWLEDGE_BASE
    write_model_file(KNOWLEDGE_BASE, kb, ensure_ascii=False)
    print(
        f"  model/knowledge_base.json (functions={len(functions_kb)}, "
        f"enums={len(enums_kb)}, macros={len(macros_kb)}, "
        f"typedefs={len(typedefs_kb)}, structs={len(structs_kb)}, "
        f"globals={len(globals_kb)})"
    )


def main():
    llm_summarize = "--llm-summarize" in sys.argv

    from core.config import app_config
    from core.model_io import read_model_file, DATA_DICTIONARY
    base_path, project_name, functions_data, global_variables_data = _load_model()
    config = app_config()

    # Backward-compat: migrate old "comment" field to "description" in functions_data
    for f in functions_data.values():
        if "comment" in f and "description" not in f:
            f["description"] = f.pop("comment")
        elif "comment" in f:
            f.pop("comment")

    # Load dataDictionary for knowledge_base.json generation
    data_dict = read_model_file(DATA_DICTIONARY, required=False, default={})

    units_data, unit_by_file = _build_units_modules(base_path, functions_data, global_variables_data)
    idx_by_id = _build_interface_index(base_path, functions_data, global_variables_data)
    _enrich_interfaces(base_path, project_name, functions_data, global_variables_data, idx_by_id)
    # Propagate global access along call graph so outers inherit inner globals
    _propagate_global_access(functions_data)
    # Static behaviour names (Input Name / Output Name) from params/globals/returnType
    _enrich_behaviour_names(functions_data, global_variables_data)
    # LLM polish for poor static names (uses abbreviations)
    _enrich_behaviour_names_llm(base_path, functions_data, global_variables_data, config)

    # LLM summarization (--llm-summarize only): phases + file/module/project hierarchy.
    # Runs before _enrich_from_llm so that phases are in functions_data when knowledge_base
    # is written, and before description enrichment so already-commented functions are skipped.
    summaries: dict = {}
    if llm_summarize:
        from core.model_io import write_model_file as _write, SUMMARIES
        print("Running LLM summarization (phases + hierarchy)...")
        summaries = _run_hierarchy_summarizer(base_path, project_name, functions_data, config)
        _write(SUMMARIES, summaries, ensure_ascii=False)
        print("  model/summaries.json")

    _enrich_from_llm(base_path, functions_data, global_variables_data, config)

    # Functions: must be In or Out (never -)
    for fentry in functions_data.values():
        d = fentry.get("direction", "").strip()
        fentry["direction"] = "Out" if d == "Out" else "In"
    # Globals: In/Out
    for g in global_variables_data.values():
        g["direction"] = "In/Out"

    # Clean and persist
    for fentry in functions_data.values():
        fentry.pop("params", None)
    from core.model_io import write_model_file as _write, FUNCTIONS, GLOBALS
    _write(FUNCTIONS, functions_data)
    _write(GLOBALS, global_variables_data)
    print(f"  model/functions.json ({len(functions_data)})")
    print(f"  model/globalVariables.json ({len(global_variables_data)})")

    # Always generate knowledge_base.json (Flowchart engine reads this)
    _generate_knowledge_base(base_path, project_name, functions_data, global_variables_data, data_dict, summaries)


if __name__ == "__main__":
    main()
