"""The incremental generation engine (M2.3, doc 04 §5).

generate_incremental() produces a new version for a target commit by reusing the
baseline version's work and regenerating only what changed plus its dependents:

  baseline-pick (M2.1) -> checkout -> FULL parse (D10) -> classify vs baseline
  hashes (M2.2) -> impact BFS (M2.2) -> carry forward baseline OUTPUTS for the
  reuse set, regenerate the impact set -> reassemble (Phase 3/4) -> record version
  + seed the reuse index.

Parse strategy is FULL parse (D10): the call graph is correct by construction, so
impact analysis can't go stale. The hours->minutes win is selective LLM work:
  * function descriptions: the version3 EntityCache (composite source+callee hash,
    persisted under <repo>/.flowchart_cache) already reuses unchanged ones across
    runs automatically;
  * this engine additionally carries forward the per-version OUTPUT snapshot
    (descriptions/behaviour names) for the reuse set and records reuse accounting.
Flowchart-level reuse (restrict the flowchart engine to the impact set) is M2.4.

The two planning helpers are pure (unit-testable); generate_incremental does I/O.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Set

_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from core.paths import paths as _paths
from incremental import git_ops
from incremental.stores import Workspace, VersionStore, HashStore, EdgeStore, ReuseIndex, _rmtree_force
from incremental.clone import ensure_commit_checkout
from incremental.project_db import get_project, list_versions, resolve_project_repo
from incremental.baseline import select_baseline
from incremental.impact import classify, impact_set
from incremental.fingerprint import compute_fingerprints
from incremental.affected import affected_tus, full_reparse_reason
from incremental.parse_merge import merge_model, diff_models
from incremental.report import build_report, emit_report
from incremental.generate import (_manifest, scope_to_args, resolve_run_config,
                                  generate_full, _now_iso, snapshot_parse_model, apply_no_llm)


def _entity_kind(key: str) -> str:
    """Classify an entity key by shape (for the report)."""
    if "@" in key and "|" not in key:
        return "macro"
    if key.count("|") >= 3:
        return "function"
    if key.count("|") == 2:
        return "global"
    return "type"


def _scope_label(scope: Dict[str, Any]) -> str:
    stype = (scope or {}).get("type", "project")
    names = (scope or {}).get("names") or []
    return stype if (stype == "project" or not names) else f"{stype}:{','.join(names)}"

# Output fields carried forward from a baseline function entry for reused fids.
_CARRY_FIELDS = ("description", "behaviourInputName", "behaviourOutputName", "comment", "phases")


def plan_incremental(baseline_hashes: Dict[str, str],
                     target_hashes: Dict[str, str],
                     target_functions: Dict[str, dict],
                     target_edges: Dict[str, Any],
                     baseline_functions: Dict[str, dict]) -> Dict[str, Any]:
    """Pure: from the two hash snapshots + the target/baseline models, compute the
    classification, the impact set (functions to regenerate) and the reuse set."""
    cls = classify(baseline_hashes, target_hashes)
    # A deleted function's callers (from the baseline) must regenerate — they can't
    # be discovered from the target model (the deleted fn isn't there).
    deleted_callers: List[str] = []
    for k in cls["deleted"]:
        bf = baseline_functions.get(k)
        if bf:
            deleted_callers += list(bf.get("calledByIds") or [])
    changed_seed = cls["changed"] | cls["new"]
    impact = impact_set(changed_seed, target_functions, target_edges,
                        extra_seed_functions=deleted_callers)
    reused = set(target_functions) - impact
    return {"classify": cls, "impact": impact, "reused": reused,
            "deletedCallers": set(deleted_callers)}


def carry_forward_descriptions(reused_fids: Iterable[str],
                               target_functions: Dict[str, dict],
                               baseline_functions: Dict[str, dict]) -> int:
    """Pure (mutates target_functions): copy the baseline's LLM outputs into the
    reuse set so reused functions keep their good descriptions without an LLM call.
    Returns the count carried forward."""
    n = 0
    for fid in reused_fids:
        bf = baseline_functions.get(fid)
        tf = target_functions.get(fid)
        if not bf or tf is None:
            continue
        for field in _CARRY_FIELDS:
            if field in bf:
                tf[field] = bf[field]
        n += 1
    return n


def carry_forward_globals(reused_keys: Iterable[str],
                          target_globals: Dict[str, dict],
                          baseline_globals: Dict[str, dict]) -> int:
    """Pure (mutates target_globals): copy the baseline's `description` into the
    reuse set so reused globals keep their description without an LLM call."""
    n = 0
    for key in reused_keys:
        bg = baseline_globals.get(key)
        tg = target_globals.get(key)
        if bg and tg is not None and "description" in bg:
            tg["description"] = bg["description"]
            n += 1
    return n


def carry_forward_from_index(impact_keys: Iterable[str],
                             target_fps: Dict[str, str],
                             target_entities: Dict[str, dict],
                             index,
                             current_version_id: str,
                             src_loader,
                             fields: Iterable[str]) -> Dict[str, str]:
    """Cross-version reuse (M3.7, doc 04 §5 step 6). For each IMPACT-set entity whose
    CONTENT fingerprint already exists in the reuse index (produced by a *prior* version
    — a revert, or code identical to another branch), copy its stored output `fields`
    from that version into `target_entities` instead of regenerating them. Returns
    {entityKey -> sourceVersionId} for the entities reused.

    The reuse index is content-addressed across ALL versions (D3), so this catches reuse
    the baseline carry-forward (parent->child only) cannot. `index.get(fp)` returns
    {"versionId", "entityKey"} or None (a ReuseIndex or a plain dict both work);
    `src_loader(version_id)` returns that version's {entityKey: entity} mapping (the
    caller should cache it). Pure given index + src_loader."""
    fields = tuple(fields)
    reused: Dict[str, str] = {}
    for key in impact_keys:
        fp = target_fps.get(key)
        if not fp:
            continue
        hit = index.get(fp)
        if not hit or hit.get("versionId") == current_version_id:
            continue
        src = (src_loader(hit["versionId"]) or {}).get(hit.get("entityKey"))
        tgt = target_entities.get(key)
        if not isinstance(src, dict) or not isinstance(tgt, dict):
            continue
        copied = False
        for f in fields:
            if f in src:
                tgt[f] = src[f]
                copied = True
        if copied:
            reused[key] = hit["versionId"]
    return reused


def _run_analyzer(vcfg_path: str, scope: Dict[str, Any], no_llm: bool,
                  data_dict_path: Optional[str], repo_dir: str, project_root: str,
                  extra_args: Optional[List[str]] = None) -> int:
    cmd = [sys.executable, "run.py", "--config", vcfg_path]
    cmd += scope_to_args(scope)
    if no_llm:
        cmd += ["--no-llm-summarize"]
    if data_dict_path:
        cmd += ["--data-dictionary", data_dict_path]
    cmd += list(extra_args or [])
    cmd += [repo_dir]
    return subprocess.run(cmd, cwd=project_root, shell=(os.name == "nt")).returncode


def _read(model_dir: str, name: str) -> dict:
    p = os.path.join(model_dir, name)
    return json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else {}


# Parser-level artifacts captured per version under versions/<id>/parse/ (the blank
# skeleton a narrowed parse merges against). Keys match parse_merge / snapshot.
_PARSE_ARTIFACTS = ("functions", "globalVariables", "dataDictionary", "hashes",
                    "edges", "tu_includes", "entity_files", "override_pairs", "metadata")


def _load_parse_dir(d: str) -> Dict[str, Any]:
    return {n: _read(d, f"{n}.json") for n in _PARSE_ARTIFACTS}


def _write_parse_artifacts(model_dir: str, merged: Dict[str, Any]) -> None:
    for n in _PARSE_ARTIFACTS:
        if n in merged:
            with open(os.path.join(model_dir, f"{n}.json"), "w", encoding="utf-8") as fh:
                json.dump(merged[n], fh, indent=2)


def _try_narrowed_parse(vcfg_path, scope, no_llm, dd_path, repo_dir, project_root, model_dir,
                        *, target, base_commit, base_parse_dir) -> bool:
    """Narrowed parse (M4.4, doc 04 §11): re-parse ONLY the affected TUs and merge them
    into the baseline's parser-level snapshot, so the resulting model/ is the SAME blank
    skeleton a full parse would produce (impacted functions arrive blank -> Phase 2
    regenerates them). Returns True if model/ now holds the merged skeleton; False to fall
    back to a full parse (always the safe choice)."""
    from core.logging_setup import get_logger
    log = get_logger("incremental")
    if not os.path.isfile(os.path.join(base_parse_dir, "tu_includes.json")) \
            or not os.path.isfile(os.path.join(base_parse_dir, "entity_files.json")):
        log.info("narrowed parse unavailable: baseline has no parser-level snapshot — full parse")
        return False
    tu_includes = _read(base_parse_dir, "tu_includes.json")
    status = git_ops.changed_files_status(repo_dir, base_commit, target)
    reason = full_reparse_reason(status, tu_includes)
    if reason:
        log.info(f"narrowed parse skipped ({reason}) — full parse")
        return False

    changed = [p for _s, p in status]
    affected = affected_tus(changed, tu_includes)
    deleted = {p for s, p in status if s == "D"}
    base_model = _load_parse_dir(base_parse_dir)
    if not affected:                       # no TU changed -> merged skeleton == baseline
        _write_parse_artifacts(model_dir, base_model)
        log.info("narrowed parse: 0 affected TU(s) — reused the baseline skeleton")
        return True

    listfile = os.path.join(model_dir, ".affected_tus.txt")
    os.makedirs(model_dir, exist_ok=True)
    with open(listfile, "w", encoding="utf-8") as fh:
        fh.write("\n".join(sorted(affected)) + "\n")
    # M4.4: hand the partial parse the baseline's func-key map (via env, inherited by the
    # run.py -> parser.py subprocess) so calls into UN-parsed files still resolve to edges.
    bfk = os.path.join(base_parse_dir, "func_keys.json")
    prev_bfk = os.environ.get("ANALYZER_BASELINE_FUNCKEYS")
    if os.path.isfile(bfk):
        os.environ["ANALYZER_BASELINE_FUNCKEYS"] = bfk
    try:
        rc = _run_analyzer(vcfg_path, scope, no_llm, dd_path, repo_dir, project_root,
                           extra_args=["--to-phase", "1", "--only-files", listfile])
    finally:
        if prev_bfk is None:
            os.environ.pop("ANALYZER_BASELINE_FUNCKEYS", None)
        else:
            os.environ["ANALYZER_BASELINE_FUNCKEYS"] = prev_bfk
    if rc != 0:
        log.info(f"narrowed parse: partial parse failed (exit {rc}) — full parse")
        return False

    partial = _load_parse_dir(model_dir)
    # M4.6 parse-fingerprint gate: if the clang flags / std / libclang toolchain changed
    # since the baseline was parsed, the baseline skeleton was built differently and a merge
    # would be unsound — discard the partial and fall back to a full parse.
    base_fp = (base_model.get("metadata") or {}).get("parseFingerprint")
    part_fp = (partial.get("metadata") or {}).get("parseFingerprint")
    if base_fp and part_fp and base_fp != part_fp:
        log.info("narrowed parse: parse fingerprint changed (clang flags / std / toolchain) — full parse")
        return False
    # Drop (use fresh for) the files that were actually re-parsed: the affected TUs + any
    # CHANGED header (refreshed via the including TUs) + deletions. NOT every file the
    # partial transitively saw — those were only partially parsed, so keep their baseline.
    drop = set(affected) | set(changed) | deleted
    merged = merge_model(base_model, partial, drop)
    _write_parse_artifacts(model_dir, merged)
    log.info(f"narrowed parse: re-parsed {len(affected)} affected TU(s), merged into the baseline "
             f"skeleton — {len(merged.get('functions') or {})} functions total")
    return True


def generate_incremental(project_id: str, branch: str, commit: str,
                         scope: Optional[Dict[str, Any]] = None, *,
                         workspaces_root: Optional[str] = None,
                         base_version_id: Optional[str] = None,
                         data_dict_id: Optional[str] = None,
                         no_llm: bool = False,
                         version_id: Optional[str] = None,
                         force: bool = False,
                         narrowed_parse: bool = False,
                         verify_parse: bool = False,
                         repo_url: Optional[str] = None,
                         repo_token: Optional[str] = None,
                         config_path: Optional[str] = None) -> Dict[str, Any]:
    """Produce an incremental version. Falls back to a FULL generation when there is
    no usable baseline (first version / no ancestor).

    `narrowed_parse` (M4.4, opt-in) re-parses only the affected TUs and merges them into
    the baseline's parser-level snapshot instead of re-parsing the whole project; it falls
    back to a full parse whenever that isn't provably safe. Default off (full parse).
    `verify_parse` (M4.5) additionally runs a FULL parse, diffs it against the narrowed
    result, logs any mismatch, and then USES the full parse (source of truth) — the gate to
    trust narrowed parse before making it the default."""
    _t0 = time.perf_counter()
    scope = scope or {"type": "project"}
    project_root = _paths().project_root
    ws = Workspace(project_id, workspaces_root)
    vstore = VersionStore(ws)

    # Ensure the target's per-commit checkout (clone on demand for the CLI; the API
    # pre-clones it). The repo for a commit IS its version dir workspaces/<pid>/<commit[:16]>.
    repo_dir = ws.commit_dir(commit)
    if not repo_url and not os.path.isdir(os.path.join(repo_dir, ".git")):
        repo_url, _rb, repo_token = resolve_project_repo(project_id)
    ensure_commit_checkout(repo_dir, repo_url or "", branch, commit, token=(repo_token or ""))

    target = git_ops.resolve(repo_dir, commit)
    if not target:
        raise ValueError(f"commit {commit!r} not found in repo")

    decision = select_baseline(repo_dir, list_versions(project_id), target, base_version_id)
    if decision["decision"] == "full":
        return generate_full(project_id, branch, commit, scope,
                             workspaces_root=workspaces_root, data_dict_id=data_dict_id,
                             no_llm=no_llm, version_id=version_id, force=force,
                             repo_url=repo_url, repo_token=repo_token, config_path=config_path)

    base_vid = decision["chosenBaseVersionId"]
    project = get_project(project_id)        # api/db/data/projects.json (no project.json)
    hstore, estore, ridx = HashStore(vstore), EdgeStore(vstore), ReuseIndex(ws)
    version_id = os.path.basename(repo_dir)  # the version id IS the checkout dir name (commit[:16])
    data_dict_id = data_dict_id or project.get("currentDataDictId")

    vdir = vstore.create_dir(version_id)  # == repo_dir (already checked out); never wiped
    # Config is PER-PROJECT: workspaces/<pid>/config.json (written by the API). Use it as-is
    # (or an explicit --config); only when --no-llm rewrites it, or none exists, write a copy.
    if not config_path:
        _proj_cfg = os.path.join(ws.root, "config.json")
        config_path = _proj_cfg if os.path.isfile(_proj_cfg) else None
    cfg = resolve_run_config(config_path, no_llm=no_llm)
    if config_path and not no_llm:
        vcfg_path = config_path
    else:
        vstore.write_config(version_id, cfg)
        vcfg_path = os.path.join(vdir, "config.json")
    vstore.write_manifest(version_id, _manifest(
        version_id, branch, target, scope, data_dict_id,
        decision="incremental", regenerated=0, reused=0, status="running", warnings=decision["warnings"]))

    dd_path = ws.datadict_path(data_dict_id) if data_dict_id and os.path.isfile(
        ws.datadict_path(data_dict_id)) else None
    model_dir = os.path.join(project_root, "model")
    # Clean the shared output/ so this version captures only its own documents
    # (the flowchart-reuse step re-seeds output/<scope>/flowcharts from the baseline).
    _rmtree_force(os.path.join(project_root, "output"))

    def _fail(stage: str, rc: int):
        vstore.write_manifest(version_id, _manifest(
            version_id, branch, target, scope, data_dict_id,
            decision="incremental", regenerated=0, reused=0, status="failed",
            warnings=decision["warnings"] + [f"{stage} exited {rc}"]))
        raise RuntimeError(f"{stage} failed (exit {rc})")

    # PHASE-SPLIT (M3.2) — produce the blank-skeleton model in model/ (Phase 1). This gives
    # the fresh hashes + call graph + edges to compute the precise impact, AND lets us carry
    # forward the baseline's summaries BEFORE Phase 2 (the summarizer only fills functions
    # with no `description`). M4.4: when narrowed parse is on AND provably safe, re-parse only
    # the affected TUs and MERGE into the baseline's parser-level snapshot (same skeleton,
    # far less parsing); otherwise a FULL parse. Either way model/ ends up identical.
    used_narrowed = False
    if narrowed_parse:
        used_narrowed = _try_narrowed_parse(
            vcfg_path, scope, no_llm, dd_path, repo_dir, project_root, model_dir,
            target=target, base_commit=decision["chosenBaseCommit"],
            base_parse_dir=os.path.join(vstore.version_dir(base_vid), "parse"))
    if used_narrowed and verify_parse:
        # M4.5 self-check: shadow-validate the narrowed model against a FULL parse, then use
        # the full parse as the source of truth (a verify run is slow but always safe).
        from core.logging_setup import get_logger as _get_logger
        _vlog = _get_logger("incremental")
        narrowed_model = _load_parse_dir(model_dir)
        rc = _run_analyzer(vcfg_path, scope, no_llm, dd_path, repo_dir, project_root,
                           extra_args=["--to-phase", "1"])
        if rc != 0:
            _fail("parse", rc)
        mism = diff_models(narrowed_model, _load_parse_dir(model_dir))
        if mism:
            _vlog.error(f"--verify-parse: narrowed parse DIFFERS from a full parse "
                        f"({len(mism)} mismatch(es)) — narrowed parse is NOT safe for this diff:")
            for m in mism[:20]:
                _vlog.error(f"      {m}")
            decision["warnings"].append(
                f"--verify-parse: narrowed != full ({len(mism)} mismatch(es)) — see log")
        else:
            _vlog.info("--verify-parse: narrowed parse is byte-identical (set-equal) to a full parse ✓")
        # model/ now holds the FULL parse -> trusted regardless of the narrowed result.
    elif not used_narrowed:
        rc = _run_analyzer(vcfg_path, scope, no_llm, dd_path, repo_dir, project_root,
                           extra_args=["--to-phase", "1"])
        if rc != 0:
            _fail("parse", rc)

    # Snapshot THIS version's blank skeleton for future narrowed parses (M4.4).
    snapshot_parse_model(model_dir, vdir)

    base_model_dir = os.path.join(vstore.version_dir(base_vid), "model")
    target_hashes = _read(model_dir, "hashes.json")
    target_functions = _read(model_dir, "functions.json")
    target_edges = _read(model_dir, "edges.json")
    target_globals = _read(model_dir, "globalVariables.json")
    base_hashes = hstore.read(base_vid)
    base_functions = _read(base_model_dir, "functions.json")
    base_globals = _read(base_model_dir, "globalVariables.json")

    # Precise impact (classify + reverse-BFS over the fresh model) drives ALL reuse:
    # function descriptions/behaviour-names/summaries (Phase 2) AND flowcharts (Phase 3).
    plan = plan_incremental(base_hashes, target_hashes, target_functions, target_edges, base_functions)

    # Impacted GLOBALS = changed/new globals + globals used by impacted functions.
    cls = plan["classify"]
    impacted_globals = {k for k in (cls["changed"] | cls["new"]) if k.count("|") == 2}
    for fid in plan["impact"]:
        f = target_functions.get(fid) or {}
        impacted_globals.update(f.get("readsGlobalIds") or [])
        impacted_globals.update(f.get("writesGlobalIds") or [])
    impacted_globals &= set(target_globals)
    reused_globals = set(target_globals) - impacted_globals

    # Carry forward baseline outputs for the reuse set so Phase 2 skips them.
    n_carried = carry_forward_descriptions(plan["reused"], target_functions, base_functions)
    n_carried_g = carry_forward_globals(reused_globals, target_globals, base_globals)

    # M3.7 — cross-version reuse (D3 / §5 step 6): for IMPACT-set entities whose content
    # fingerprint was already produced by a *prior* version (a revert, or code identical
    # to another branch), copy that version's stored output instead of regenerating it.
    # The reuse index is content-addressed across ALL versions, so this catches reuse the
    # baseline carry-forward (parent->child only) can't. Fingerprints are content-only, so
    # the same dict is reused to seed the index at the end (descriptions don't affect it).
    target_fps = compute_fingerprints(target_hashes, target_functions, target_edges)
    _func_cache: Dict[str, dict] = {}
    _glob_cache: Dict[str, dict] = {}

    def _src_funcs(vid: str) -> dict:
        if vid not in _func_cache:
            _func_cache[vid] = _read(os.path.join(vstore.version_dir(vid), "model"), "functions.json")
        return _func_cache[vid]

    def _src_globs(vid: str) -> dict:
        if vid not in _glob_cache:
            _glob_cache[vid] = _read(os.path.join(vstore.version_dir(vid), "model"), "globalVariables.json")
        return _glob_cache[vid]

    index_reused = carry_forward_from_index(plan["impact"], target_fps, target_functions,
                                            ridx, version_id, _src_funcs, _CARRY_FIELDS)
    index_reused_g = carry_forward_from_index(impacted_globals, target_fps, target_globals,
                                              ridx, version_id, _src_globs, ("description",))
    # Entities satisfied from the index drop out of the LLM regen sets (Phase 2 skips them
    # because they now carry a description + behaviour names).
    regen_impact = [k for k in plan["impact"] if k not in index_reused]
    regen_globals = {k for k in impacted_globals if k not in index_reused_g}

    with open(os.path.join(model_dir, "functions.json"), "w", encoding="utf-8") as fh:
        json.dump(target_functions, fh, indent=2)
    with open(os.path.join(model_dir, "globalVariables.json"), "w", encoding="utf-8") as fh:
        json.dump(target_globals, fh, indent=2)

    # impactedFiles (for SUMMARIES) = files of the full impact set (a caller's
    # description/file-summary does depend on its callees). flowchartFiles (for
    # FLOWCHARTS) = files of only the DIRECTLY changed/new/deleted functions — a
    # function's flowchart is its own control flow + call-site labels, so it does NOT
    # change when a callee's *body* changes. This keeps flowchart regen (the dominant
    # LLM cost) scoped to what actually changed, not its (often large) callers.
    impacted_files = sorted({
        (target_functions.get(fid) or {}).get("location", {}).get("file")
        for fid in plan["impact"]
    } - {None})
    cls = plan["classify"]
    direct_fns = {k for k in (cls["changed"] | cls["new"]) if k in target_functions}
    flowchart_files = {(target_functions.get(fid) or {}).get("location", {}).get("file")
                       for fid in direct_fns}
    for fid in cls["deleted"]:                      # a deleted fn's file must drop its flowchart
        bf = base_functions.get(fid)
        if bf:
            flowchart_files.add((bf.get("location") or {}).get("file"))
    flowchart_files = sorted(flowchart_files - {None})
    # M3.7b — flowchart cross-version reuse: a DIRECTLY-changed function that was reused
    # from the index (a revert / cross-branch-identical fn) has the SAME content -> the
    # SAME flowchart as its source version, so don't regenerate it. The view splices its
    # flowchart in from the source version instead (and falls back to regenerating if that
    # version has no flowchart for it). The rest of direct_fns regenerate as before (M3.6).
    xver_flowcharts = {fid: vstore.version_dir(index_reused[fid])
                       for fid in direct_fns if fid in index_reused}
    flowchart_fids_regen = sorted(direct_fns - set(xver_flowcharts))
    # flowchartFids (for FUNCTION-LEVEL flowchart reuse, M3.6) = the directly changed/
    # new function fids themselves. The flowcharts view regenerates ONLY these and
    # splices them into the baseline file JSONs, instead of regenerating every function
    # in a changed file. (flowchartFiles is kept for older readers / file-level fallback.)
    with open(os.path.join(model_dir, "incremental_plan.json"), "w", encoding="utf-8") as fh:
        json.dump({"impactFids": sorted(regen_impact),
                   "impactedGlobals": sorted(regen_globals),
                   "impactedFiles": impacted_files,
                   "flowchartFiles": flowchart_files,
                   "flowchartFids": flowchart_fids_regen,
                   "crossVersionFlowcharts": xver_flowcharts,
                   "baselineVersionDir": vstore.version_dir(base_vid)}, fh, indent=2)

    # Resume derive+views+export: Phase 2 summarizer skips the carried-forward reuse
    # set; Phase 3 flowcharts restricted to impacted files (rest carried forward).
    rc = _run_analyzer(vcfg_path, scope, no_llm, dd_path, repo_dir, project_root,
                       extra_args=["--from-phase", "2"])
    if rc != 0:
        _fail("derive+views+export", rc)

    # The plan file has done its job (Phase 3 read it); remove so it isn't captured.
    try:
        os.remove(os.path.join(model_dir, "incremental_plan.json"))
    except OSError:
        pass

    # Capture artifacts + snapshots, seed the reuse index, finalize the manifest.
    documents = vstore.capture_artifacts(version_id, model_dir=model_dir,
                                         output_dir=os.path.join(project_root, "output"))
    hstore.write(version_id, target_hashes)
    estore.write(version_id, target_edges)
    llm = cfg.get("llm") or {}
    # Content-only reuse key (recipe intentionally not folded in — approved outputs are
    # reused regardless of which model/prompt produced them). Reuse the fingerprints
    # computed for the M3.7 lookup (descriptions added since don't affect the content key).
    for entity_key, fp in target_fps.items():
        ridx.put(fp, version_id, entity_key)  # first version that produced a fp keeps it
    ridx.save()

    manifest = _manifest(version_id, branch, target, scope, data_dict_id,
                         decision="incremental", regenerated=len(regen_impact),
                         reused=len(plan["reused"]) + len(index_reused),
                         status="complete", warnings=decision["warnings"])
    manifest["baselineVersionId"] = base_vid
    manifest["baselineCommit"] = decision["chosenBaseCommit"]
    manifest["documents"] = documents
    manifest["carriedForward"] = n_carried
    manifest["crossVersionReused"] = len(index_reused) + len(index_reused_g)
    vstore.write_manifest(version_id, manifest)

    # End-of-run report (M3.4): inputs + change classification + reuse accounting.
    cls = plan["classify"]
    classification = {b: dict(Counter(_entity_kind(k) for k in cls[b]))
                      for b in ("changed", "new", "deleted", "unchanged")}
    all_files = {(f.get("location") or {}).get("file") for f in target_functions.values()} - {None}
    fn_total, fn_regen = len(target_functions), len(regen_impact)
    gl_total, gl_regen = len(target_globals), len(regen_globals)
    stats = {
        "versionId": version_id, "decision": "incremental", "status": "complete",
        "projectId": project_id, "branch": branch, "commit": target,
        "scope": _scope_label(scope), "baselineVersionId": base_vid,
        "baselineCommit": decision["chosenBaseCommit"], "changedFiles": decision.get("changedFiles"),
        "dataDictId": data_dict_id,
        "llmModel": llm.get("defaultModel"), "elapsedSeconds": time.perf_counter() - _t0,
        "classification": classification,
        "functions": {"total": fn_total, "regenerated": fn_regen, "reused": fn_total - fn_regen},
        "globals": {"total": gl_total, "regenerated": gl_regen, "reused": gl_total - gl_regen},
        # M3.7 — how many of the reused entities came from the cross-version index
        # (reverts / cross-branch), vs the baseline carry-forward. flowcharts = directly
        # changed fns whose flowchart was spliced from a prior version (M3.7b).
        "crossVersion": {"functions": len(index_reused), "globals": len(index_reused_g),
                         "flowcharts": len(xver_flowcharts)},
        # Flowcharts reuse at FUNCTION granularity (M3.6): only directly changed/new
        # functions are re-labelled; the rest are spliced from the baseline. M3.7b further
        # excludes directly-changed fns whose flowchart is reused cross-version (reverts).
        "flowcharts": {"total": fn_total, "regenerated": len(flowchart_fids_regen),
                       "carried": fn_total - len(flowchart_fids_regen)},
        # files = file-level SUMMARIES (a caller's file-summary depends on its callees),
        # so it tracks the full impact set's files, not the directly-changed ones.
        "files": {"total": len(all_files), "regenerated": len(impacted_files),
                  "carried": len(all_files) - len(impacted_files)},
        "documents": documents, "warnings": decision["warnings"],
    }
    emit_report(build_report(stats), version_dir=vdir)
    return manifest


def _parse_scope(s: str) -> Dict[str, Any]:
    if not s or s == "project":
        return {"type": "project"}
    kind, _, names = s.partition(":")
    return {"type": kind, "names": [n for n in names.split(",") if n]}


def main() -> None:
    ap = argparse.ArgumentParser(description="Produce an incremental version (M2.3).")
    ap.add_argument("--project-id", required=True)
    ap.add_argument("--branch", required=True)
    ap.add_argument("--commit", required=True)
    ap.add_argument("--scope", default="project")
    ap.add_argument("--base-version-id", default=None)
    ap.add_argument("--data-dict-id", default=None)
    ap.add_argument("--version-id", default=None)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--narrowed-parse", action="store_true",
                    help="M4.4 (opt-in): re-parse only affected TUs + merge into the baseline "
                         "skeleton, instead of a full re-parse. Falls back to full when unsafe.")
    ap.add_argument("--verify-parse", action="store_true",
                    help="M4.5: with --narrowed-parse, also run a full parse and diff it against "
                         "the narrowed result (logs mismatches; uses the full parse). Slow; for validation.")
    ap.add_argument("--config", default=None, help="per-project config.json to use as-is")
    ap.add_argument("--repo-url", default=None, help="clone URL (else resolved from the project record)")
    args = ap.parse_args()
    m = generate_incremental(args.project_id, args.branch, args.commit, _parse_scope(args.scope),
                             base_version_id=args.base_version_id, data_dict_id=args.data_dict_id,
                             no_llm=args.no_llm, version_id=args.version_id, force=args.force,
                             narrowed_parse=args.narrowed_parse, verify_parse=args.verify_parse,
                             config_path=args.config, repo_url=args.repo_url)
    print(f"\nversion {m['versionId']} ({m['status']}): commit {m['commit'][:10]}, "
          f"decision={m['decision']}, baseline={m.get('baselineVersionId')}, "
          f"regenerated={m['regenerated']}, reused={m['reused']}, "
          f"carriedForward={m.get('carriedForward')}, documents={m.get('documents')}")


if __name__ == "__main__":
    main()
