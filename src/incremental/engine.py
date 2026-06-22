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
from incremental.baseline import select_baseline
from incremental.impact import classify, impact_set
from incremental.fingerprint import recipe_fingerprint, compute_fingerprints
from incremental.report import build_report, emit_report
from incremental.generate import (_resolved_config, _manifest, scope_to_args,
                                  generate_full, _now_iso)


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


def generate_incremental(project_id: str, branch: str, commit: str,
                         scope: Optional[Dict[str, Any]] = None, *,
                         workspaces_root: Optional[str] = None,
                         base_version_id: Optional[str] = None,
                         data_dict_id: Optional[str] = None,
                         no_llm: bool = False,
                         version_id: Optional[str] = None,
                         force: bool = False) -> Dict[str, Any]:
    """Produce an incremental version. Falls back to a FULL generation when there is
    no usable baseline (first version / no ancestor)."""
    _t0 = time.perf_counter()
    scope = scope or {"type": "project"}
    project_root = _paths().project_root
    ws = Workspace(project_id, workspaces_root)
    vstore = VersionStore(ws)

    target = git_ops.resolve(ws.repo_dir, commit)
    if not target:
        raise ValueError(f"commit {commit!r} not found in repo")

    decision = select_baseline(ws.repo_dir, vstore.list(), target, base_version_id)
    if decision["decision"] == "full":
        return generate_full(project_id, branch, commit, scope,
                             workspaces_root=workspaces_root, data_dict_id=data_dict_id,
                             no_llm=no_llm, version_id=version_id, force=force)

    base_vid = decision["chosenBaseVersionId"]
    project = ws.project()
    hstore, estore, ridx = HashStore(vstore), EdgeStore(vstore), ReuseIndex(ws)
    version_id = version_id or vstore.next_version_id()
    data_dict_id = data_dict_id or project.get("currentDataDictId")

    git_ops.checkout(ws.repo_dir, target)
    vdir = vstore.create_dir(version_id, force=force)
    cfg = _resolved_config(project, project_root)
    vstore.write_config(version_id, cfg)
    vcfg_path = os.path.join(vdir, "config.json")
    vstore.write_manifest(version_id, _manifest(
        version_id, branch, target, scope, data_dict_id, recipe_fp="",
        decision="incremental", regenerated=0, reused=0, status="running", warnings=decision["warnings"]))

    dd_path = ws.datadict_path(data_dict_id) if data_dict_id and os.path.isfile(
        ws.datadict_path(data_dict_id)) else None
    model_dir = os.path.join(project_root, "model")
    # Clean the shared output/ so this version captures only its own documents
    # (the flowchart-reuse step re-seeds output/<scope>/flowcharts from the baseline).
    _rmtree_force(os.path.join(project_root, "output"))

    def _fail(stage: str, rc: int):
        vstore.write_manifest(version_id, _manifest(
            version_id, branch, target, scope, data_dict_id, recipe_fp="",
            decision="incremental", regenerated=0, reused=0, status="failed",
            warnings=decision["warnings"] + [f"{stage} exited {rc}"]))
        raise RuntimeError(f"{stage} failed (exit {rc})")

    # PHASE-SPLIT (M3.2) — run PARSE only (Phase 1). This gives the fresh hashes +
    # call graph + edges to compute the precise impact, AND lets us carry forward
    # the baseline's summaries BEFORE Phase 2 runs — the hierarchy summarizer only
    # summarizes functions with no `description`, so carrying it forward makes it
    # skip the reuse set (the dominant LLM cost) with no model_deriver change.
    rc = _run_analyzer(vcfg_path, scope, no_llm, dd_path, ws.repo_dir, project_root,
                       extra_args=["--to-phase", "1"])
    if rc != 0:
        _fail("parse", rc)

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
    with open(os.path.join(model_dir, "incremental_plan.json"), "w", encoding="utf-8") as fh:
        json.dump({"impactFids": sorted(plan["impact"]),
                   "impactedGlobals": sorted(impacted_globals),
                   "impactedFiles": impacted_files,
                   "flowchartFiles": flowchart_files,
                   "baselineVersionDir": vstore.version_dir(base_vid)}, fh, indent=2)

    # Resume derive+views+export: Phase 2 summarizer skips the carried-forward reuse
    # set; Phase 3 flowcharts restricted to impacted files (rest carried forward).
    rc = _run_analyzer(vcfg_path, scope, no_llm, dd_path, ws.repo_dir, project_root,
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
    recipe_fp = recipe_fingerprint(llm.get("defaultModel", ""), cache_version=llm.get("cacheVersion", 1))
    for entity_key, fp in compute_fingerprints(target_hashes, target_functions, target_edges, recipe_fp).items():
        ridx.put(fp, version_id, entity_key)  # first version that produced a fp keeps it
    ridx.save()

    manifest = _manifest(version_id, branch, target, scope, data_dict_id, recipe_fp=recipe_fp,
                         decision="incremental", regenerated=len(plan["impact"]),
                         reused=len(plan["reused"]), status="complete", warnings=decision["warnings"])
    manifest["baselineVersionId"] = base_vid
    manifest["baselineCommit"] = decision["chosenBaseCommit"]
    manifest["documents"] = documents
    manifest["carriedForward"] = n_carried
    vstore.write_manifest(version_id, manifest)

    # End-of-run report (M3.4): inputs + change classification + reuse accounting.
    cls = plan["classify"]
    classification = {b: dict(Counter(_entity_kind(k) for k in cls[b]))
                      for b in ("changed", "new", "deleted", "unchanged")}
    all_files = {(f.get("location") or {}).get("file") for f in target_functions.values()} - {None}
    fn_total, fn_regen = len(target_functions), len(plan["impact"])
    gl_total, gl_regen = len(target_globals), len(impacted_globals)
    stats = {
        "versionId": version_id, "decision": "incremental", "status": "complete",
        "projectId": project_id, "branch": branch, "commit": target,
        "scope": _scope_label(scope), "baselineVersionId": base_vid,
        "baselineCommit": decision["chosenBaseCommit"], "changedFiles": decision.get("changedFiles"),
        "dataDictId": data_dict_id, "recipeFingerprint": recipe_fp,
        "llmModel": llm.get("defaultModel"), "elapsedSeconds": time.perf_counter() - _t0,
        "classification": classification,
        "functions": {"total": fn_total, "regenerated": fn_regen, "reused": fn_total - fn_regen},
        "globals": {"total": gl_total, "regenerated": gl_regen, "reused": gl_total - gl_regen},
        "files": {"total": len(all_files), "regenerated": len(flowchart_files),
                  "carried": len(all_files) - len(flowchart_files)},
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
    args = ap.parse_args()
    m = generate_incremental(args.project_id, args.branch, args.commit, _parse_scope(args.scope),
                             base_version_id=args.base_version_id, data_dict_id=args.data_dict_id,
                             no_llm=args.no_llm, version_id=args.version_id, force=args.force)
    print(f"\nversion {m['versionId']} ({m['status']}): commit {m['commit'][:10]}, "
          f"decision={m['decision']}, baseline={m.get('baselineVersionId')}, "
          f"regenerated={m['regenerated']}, reused={m['reused']}, "
          f"carriedForward={m.get('carriedForward')}, documents={m.get('documents')}")


if __name__ == "__main__":
    main()
