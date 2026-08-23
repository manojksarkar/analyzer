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

from core.paths import paths as _paths, set_output_dir, set_model_dir
from core.run_context import (effective_model_store,
                              DatabaseRequired as _DatabaseRequired)
from incremental import git_ops
from incremental.stores import Workspace, VersionStore, _rmtree_force
from incremental.clone import ensure_commit_checkout
from incremental.project_db import get_project, list_versions, resolve_project_repo
from incremental.baseline import select_baseline
from incremental.impact import classify, impact_set
from incremental.fingerprint import compute_fingerprints
from incremental.affected import affected_tus, full_reparse_reason
from incremental.parse_merge import merge_model, diff_models
from incremental.report import build_report, emit_report
from incremental.generate import (AnalyzerRunFailed, _manifest, scope_to_args,
                                  per_component_docx_args,
                                  resolve_run_config, generate_full, _now_iso,
                                  snapshot_parse_model, apply_no_llm,
                                  _orchestrator_model,
                                  _persist_run_metadata,
                                  llm_call_counts as _llm_call_counts)


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


# Set by generate_incremental before it runs any phase. A module-level value rather than
# another _run_analyzer parameter: that function is called from four places and its
# signature is already long, and the value is constant for the whole run.


def _run_analyzer(vcfg_path: str, scope: Dict[str, Any], no_llm: bool,
                  data_dict_path: Optional[str], repo_dir: str, project_root: str,
                  extra_args: Optional[List[str]] = None,
                  project_name: Optional[str] = None,
                  version_id: Optional[str] = None,
                  project_id: Optional[str] = None,
                  scratch_model: bool = False) -> int:
    """Run the analyzer as a subprocess.

    `scratch_model` sends this invocation's model to a scratch directory instead of the
    version. Only the narrowed parse sets it: its output is a PARTIAL model that is not valid
    until `parse_merge` has combined it with the baseline, so it must not reach the version's
    rows.
    """
    cmd = [sys.executable, os.path.join(_SRC, "run.py"), "--config", vcfg_path]
    # This run's own output dir (doc 09, B1) — set_output_dir was already applied in THIS
    # process; the analyzer is a separate process, so it needs telling on its command line.
    cmd += ["--output-root", _paths().output_dir, "--model-root", _paths().model_dir]
    if scratch_model:
        # The narrowed parse's partial pass: its model is scratch for parse_merge, not this
        # version's. Passing the version id as well would let the phase write rows.
        cmd += ["--model-scratch"]
    elif version_id and project_id:
        # Each phase persists the model at its own boundary, against this version.
        cmd += ["--version-id", version_id, "--project-id", project_id]
    cmd += scope_to_args(scope)
    cmd += per_component_docx_args(scope)
    if project_name:
        # Otherwise parser.py defaults projectName to the checkout dir basename
        # (commit[:16]) — the sha would surface in the DOCX cover + 1.1 Purpose.
        cmd += ["--project-name", project_name]
    if no_llm:
        cmd += ["--no-llm-summarize"]
    if data_dict_path:
        cmd += ["--data-dictionary", data_dict_path]
    cmd += list(extra_args or [])
    cmd += [repo_dir]
    return subprocess.run(cmd, cwd=project_root, shell=(os.name == "nt")).returncode


# `edges.json` shape when absent, so classify/impact get the keys they expect.
_EMPTY_EDGES_SHAPE = {"typeUsers": {}, "macroUsers": {}}


def _write_plan(version_id: str, project_id: str, plan: Dict[str, Any]) -> None:
    """Publish the incremental plan where Phases 2 and 3 will read it.

    The orchestrator has no model repository installed, so it must name the backing itself —
    exactly as `_publish_model_for_next_phase` does for the carried-forward model.
    """
    from core.model_repo import DbRepository
    DbRepository(version_id, project_id or "").write("incremental_plan", plan)


def _publish_model_for_next_phase(store, version_id, project_id, model_dir,
                                  functions, globals_, hashes) -> None:
    """Make the carried-forward model visible to Phase 2, in the right backing.

    Carry-forward copies the baseline's descriptions/behaviour names onto the reuse set so
    Phase 2 can skip them. Phase 2 reads through `core.model_io`, so in database mode the
    values have to be in the DATABASE — writing model files there would leave every reused
    entity blank and Phase 2 would regenerate the lot, losing the reuse the run just computed.
    """
    from core.model_repo import DbRepository
    from core.model_io import FUNCTIONS, GLOBALS, HASHES
    repo = DbRepository(version_id, project_id or "")
    repo.write(FUNCTIONS, functions)
    repo.write(GLOBALS, globals_)
    repo.write(HASHES, hashes)              # persist_functions needs them in the same call
    repo.flush()


def _read(model_dir: str, name: str) -> dict:
    p = os.path.join(model_dir, name)
    return json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else {}


# Parser-level artifacts captured per version under versions/<id>/parse/ (the blank
# skeleton a narrowed parse merges against). Keys match parse_merge / snapshot.
_PARSE_ARTIFACTS = ("functions", "globalVariables", "dataDictionary", "hashes",
                    "edges", "tu_includes", "entity_files", "override_pairs",
                    # func_keys was missing here, so a narrowed parse never republished it and
                    # the resulting version could not serve as a narrowed-parse baseline without
                    # losing cross-TU call edges. address_taken arrives with the same duty.
                    "func_keys", "address_taken", "metadata")


def _load_parse_dir(d: str) -> Dict[str, Any]:
    return {n: _read(d, f"{n}.json") for n in _PARSE_ARTIFACTS}


def _clear_scratch_parse_files(model_dir: str) -> int:
    """Delete the PARTIAL model files the narrowed parse wrote as scratch. Returns the count.

    The partial parse deliberately runs with `--model-scratch` — its output is only valid
    after `parse_merge`, so it must not reach the version's rows. What it leaves behind is a
    directory of INCOMPLETE model files, and nothing removed them: an incremental run therefore
    ended with a `model/` full of partial JSON, and `snapshot_parse_model` copied that straight
    into `versions/<id>/parse/`. A full run produced a clean version, an incremental one did not
    — which is exactly the inconsistency this was reported as.

    Worse than untidy: those files describe only the re-parsed translation units, so anything
    reading the on-disk snapshot got a model missing most of the project.
    """
    removed = 0
    for name in _PARSE_ARTIFACTS:
        p = os.path.join(model_dir, f"{name}.json")
        try:
            if os.path.isfile(p):
                os.unlink(p)
                removed += 1
        except OSError:
            pass                      # a file we cannot delete is untidy, not fatal
    return removed


def _load_parse_model(model_dir: str, *, version_id: str = "",
                      project_id: str = "") -> Dict[str, Any]:
    """The nine parse artifacts from whichever backing this run uses.

    `_load_parse_dir` reads files, which is right for the PARTIAL parse (deliberately run in
    files mode) and wrong for anything a phase produced in database mode. `--verify-parse`
    compares a narrowed model against a full one; reading files there would compare two stale
    copies and report a match that means nothing — the exact shape of failure that check exists
    to prevent.
    """
    if not version_id:
        return _load_parse_dir(model_dir)
    from core.model_repo import DbRepository
    repo = DbRepository(version_id, project_id or "")
    out: Dict[str, Any] = {}
    for n in _PARSE_ARTIFACTS:
        try:
            out[n] = repo.read(n, required=False, default={}) or {}
        except Exception:
            out[n] = {}
    return out


def _load_baseline_parse(store, base_vid: str, base_parse_dir: str) -> Dict[str, Any]:
    """The baseline's post-Phase-1 skeleton — from the STORE first, disk as fallback.

    Store first because the disk copy only exists on the machine that produced the baseline
    (doc 09, C2), so on any other node a narrowed parse would find nothing and fall back to a
    full parse — correct, but the whole point of the feature is lost. Disk still answers for
    versions written before C2 and for DB-less runs.

    Returned in `_load_parse_dir`'s shape either way, so callers need no branch.
    """
    snap = {}
    try:
        snap = store.read_parse_snapshot(base_vid) or {}
    except Exception:
        snap = {}
    if snap:
        out = {}
        for n in _PARSE_ARTIFACTS:
            out[n] = snap.get(f"{n}.json") or {}
        # `tu_includes` is NOT in parse_snapshots: step 6 gave it its own table so the flowchart
        # engine could query the header->TU map on an index instead of loading a blob. Reading
        # only the snapshot therefore returned an empty map, the caller concluded the baseline
        # had no skeleton, and narrowed parse refused EVERY time — silently, as a fallback to a
        # full parse, which is correct output and none of the speed-up.
        if not out.get("tu_includes"):
            out["tu_includes"] = _stored_tu_includes(base_vid)
        if any(out.values()):
            return out
    return _load_parse_dir(base_parse_dir)


def _stored_tu_includes(version_id: str) -> Dict[str, Any]:
    """A version's header->TU map from its own table, or {}."""
    if not version_id:
        return {}
    try:
        from core.db import get_engine, is_database_configured
        from core import model_store
        if not is_database_configured():
            return {}
        with get_engine().connect() as cx:
            return model_store.load_tu_includes(cx, version_id) or {}
    except Exception:
        return {}


def _write_parse_artifacts(model_dir: str, merged: Dict[str, Any],
                           *, version_id: str = "", project_id: str = "") -> None:
    """Publish the merged skeleton where the NEXT phase will look for it.

    In database mode that is the version's rows, not `model/*.json` — Phase 2 reads through
    `core.model_io`, so writing files would leave it reading whatever the partial parse left
    behind and it would derive a model containing only the changed files' functions. A wrong
    document, produced without an error, which is the failure this whole feature must not have.

    All nine artifacts are written through the repository and take three different routes into
    the database (coupled model / own table / parse_snapshots); the flush covers the coupled
    ones. Verified lossless end to end before this was wired up.
    """
    from core.model_repo import DbRepository
    repo = DbRepository(version_id, project_id or "")
    for n in _PARSE_ARTIFACTS:
        if n in merged:
            repo.write(n, merged[n])
    repo.flush()


def _baseline_parse_fingerprint(base_fingerprint: Optional[str],
                                base_model: Dict[str, Any]) -> Optional[str]:
    """The baseline's clang-flag fingerprint for the narrowed-parse gate (M4.6).

    The STORE's value wins — versions.parse_fingerprint under PgStore (doc 07 §3) — falling back
    to the baseline's parse-dir snapshot for versions written before that column was populated.
    None when neither has one, which disables the gate rather than failing the run."""
    if base_fingerprint:
        return base_fingerprint
    return ((base_model or {}).get("metadata") or {}).get("parseFingerprint")


class StoreReuseIndex:
    """Adapts ArtifactStore's reuse API to the ``.get(fp)`` shape `carry_forward_from_index`
    expects, so cross-version reuse resolves through the STORE — the `reuse_index` table under
    PgStore — instead of the legacy ``cache/index.json`` file. FileStore keeps writing that same
    file, so DB-less runs are byte-for-byte unchanged."""

    def __init__(self, store):
        self._store = store

    def get(self, fingerprint):
        return self._store.reuse_get(fingerprint)

    def get_many(self, fingerprints):
        return self._store.reuse_get_many(fingerprints)

    def put(self, fingerprint, version_id, entity_key, *, overwrite: bool = False):
        return self._store.reuse_put(fingerprint, version_id, entity_key, overwrite=overwrite)

    def put_many(self, entries, *, overwrite: bool = False):
        return self._store.reuse_put_many(entries, overwrite=overwrite)

    def save(self) -> None:
        self._store.reuse_save()


def _parse_dir_for(store, vstore, version_id: Optional[str], commit: Optional[str]) -> str:
    """Where a version's post-Phase-1 skeleton lives on disk.

    Prefers the version-keyed `versions/<ver>/parse/`; falls back to the legacy
    `<commit>/parse/` so versions produced before the move still resolve. The legacy location
    is SHARED by every version of that commit, which is exactly the bug being fixed — two
    versions built from one commit overwrote each other's skeleton, sequentially, with no
    concurrency needed.
    """
    if version_id:
        d = os.path.join(store.artifact_dir(version_id), "parse")
        if os.path.isdir(d):
            return d
    return os.path.join(vstore.version_dir(commit or ""), "parse")


def _artifact_dir_for(store, vstore, version_id: Optional[str], commit: Optional[str]) -> str:
    """The dir holding a version's rendered artifacts, for baseline / cross-version reuse.

    Prefers the version-keyed layout ``versions/<ver…>/`` that `store.capture_output` writes
    (08 step 3) and falls back to the legacy commit-keyed dir, so reuse keeps working for
    versions produced before the switch — and keeps working once the commit-dir copy is dropped.
    """
    if version_id:
        d = store.artifact_dir(version_id)
        if os.path.isdir(os.path.join(d, "output")):
            return d
    return vstore.version_dir(commit or version_id or "")


def _try_narrowed_parse(vcfg_path, scope, no_llm, dd_path, repo_dir, project_root, model_dir,
                        *, target, base_commit, base_parse_dir, project_name=None,
                        base_fingerprint: Optional[str] = None,
                        store=None, base_vid: str = "",
                        version_id: str = "", project_id: str = "") -> bool:
    """Narrowed parse (M4.4, doc 04 §11): re-parse ONLY the affected TUs and merge them
    into the baseline's parser-level snapshot, so the resulting model/ is the SAME blank
    skeleton a full parse would produce (impacted functions arrive blank -> Phase 2
    regenerates them). Returns True if model/ now holds the merged skeleton; False to fall
    back to a full parse (always the safe choice)."""
    from core.logging_setup import get_logger
    log = get_logger("incremental")
    # The baseline's skeleton, store-first (doc 09, C2): on disk it exists only on the machine
    # that produced the baseline. Loaded ONCE, up front, and the availability check reads from
    # it — the check used to inspect the raw snapshot keys instead, which stopped matching what
    # the loader actually assembles and made every narrowed parse refuse.
    base_model = (_load_baseline_parse(store, base_vid, base_parse_dir)
                  if store is not None else _load_parse_dir(base_parse_dir))
    tu_includes = base_model.get("tu_includes") or {}
    if not (tu_includes and base_model.get("entity_files")):
        log.info("narrowed parse unavailable: baseline has no parser-level snapshot — full parse")
        return False
    status = git_ops.changed_files_status(repo_dir, base_commit, target)
    reason = full_reparse_reason(status, tu_includes)
    if reason:
        log.info(f"narrowed parse skipped ({reason}) — full parse")
        return False

    changed = [p for _s, p in status]
    affected = affected_tus(changed, tu_includes)
    deleted = {p for s, p in status if s == "D"}
    if not affected:                       # no TU changed -> merged skeleton == baseline
        _write_parse_artifacts(model_dir, base_model, version_id=version_id,
                               project_id=project_id)
        log.info("narrowed parse: 0 affected TU(s) — reused the baseline skeleton")
        return True

    listfile = os.path.join(model_dir, ".affected_tus.txt")
    os.makedirs(model_dir, exist_ok=True)
    with open(listfile, "w", encoding="utf-8") as fh:
        fh.write("\n".join(sorted(affected)) + "\n")
    # M4.4: tell the partial parse WHICH version holds the baseline's func-key map, so calls
    # into files we did not re-parse still resolve to edges. A CLI argument reaching parser.py
    # through the planner, replacing ANALYZER_BASELINE_FUNCKEYS — a path to func_keys.json in
    # an environment variable. The file moved into `parse_snapshots` at step 11a, and an
    # environment variable must not decide run behaviour (D10-3).
    _extra = ["--to-phase", "1", "--only-files", listfile]
    if base_vid:
        _extra += ["--baseline-version-id", base_vid]
    rc = _run_analyzer(vcfg_path, scope, no_llm, dd_path, repo_dir, project_root,
                       extra_args=_extra, project_name=project_name,
                       # PARTIAL output: valid only after parse_merge, so it must not reach the
                       # version's rows. A resume (--use-model --from-phase 4) would otherwise
                       # export a document containing just the changed files.
                       scratch_model=True)
    if rc != 0:
        log.info(f"narrowed parse: partial parse failed (exit {rc}) — full parse")
        return False

    partial = _load_parse_dir(model_dir)
    # M4.6 parse-fingerprint gate: if the clang flags / std / libclang toolchain changed
    # since the baseline was parsed, the baseline skeleton was built differently and a merge
    # would be unsound — discard the partial and fall back to a full parse.
    base_fp = _baseline_parse_fingerprint(base_fingerprint, base_model)
    part_fp = (partial.get("metadata") or {}).get("parseFingerprint")
    if base_fp and part_fp and base_fp != part_fp:
        log.info("narrowed parse: parse fingerprint changed (clang flags / std / toolchain) — full parse")
        # The caller runs a FULL parse next, which rewrites these anyway in file mode; in
        # database mode nothing would, so a partial model would survive as the version's
        # on-disk skeleton. Clear it either way — the partial is never valid on its own.
        _clear_scratch_parse_files(model_dir)
        return False
    # Drop (use fresh for) the files that were actually re-parsed: the affected TUs + any
    # CHANGED header (refreshed via the including TUs) + deletions. NOT every file the
    # partial transitively saw — those were only partially parsed, so keep their baseline.
    drop = set(affected) | set(changed) | deleted
    merged = merge_model(base_model, partial, drop)
    _write_parse_artifacts(model_dir, merged, version_id=version_id,
                           project_id=project_id)
    # The merged model went to the database; the scratch files are the PARTIAL parse and must
    # not be left lying in the version's model dir.
    n = _clear_scratch_parse_files(model_dir)
    if n:
        log.debug("narrowed parse: removed %d scratch model file(s)", n)
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
                         narrowed_parse: bool = True,
                         verify_parse: bool = False,
                         repo_url: Optional[str] = None,
                         repo_token: Optional[str] = None,
                         config_path: Optional[str] = None,
                         create_version: bool = False) -> Dict[str, Any]:
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

    # A version can never be its own baseline: the API reserves this run's version row before the
    # engine starts, so it would otherwise be offered as a candidate at its own commit (nearest
    # possible match) -> 0 changed files -> nothing regenerated.
    _versions = [v for v in list_versions(project_id) if v.get("versionId") != version_id]
    _ver_commit = {v["versionId"]: v["commit"] for v in _versions}   # real ver id -> commit (dir)
    decision = select_baseline(repo_dir, _versions, target, base_version_id)
    if decision["decision"] == "full":
        return generate_full(project_id, branch, commit, scope,
                             workspaces_root=workspaces_root, data_dict_id=data_dict_id,
                             no_llm=no_llm, version_id=version_id, force=force,
                             repo_url=repo_url, repo_token=repo_token, config_path=config_path)

    base_vid = decision["chosenBaseVersionId"]           # real ver… id (from list_versions)
    base_commit = decision["chosenBaseCommit"]            # resolves the baseline's checkout dir
    project = get_project(project_id)        # api/db/data/projects.json (no project.json)
    project_name = (project.get("name") or "").strip() or None
    from incremental.store import make_store
    store = make_store(project_id, workspaces_root)
    ridx = StoreReuseIndex(store)      # reuse index via the store: Postgres under PgStore
    # Version identity (08): the checkout DIR stays commit-keyed; version_id is the real ver…
    # id (--version) supplied by the backend, else commit[:16] for standalone CLI use.
    commit_key = os.path.basename(repo_dir)
    version_id = version_id or commit_key
    # Step 9: resolve the default 'db' once, here, and pass the answer down (the delegation to
    # generate_full above happens before version_id is known, so that path resolves its own).
    effective_model_store(version_id, project_id=project_id, commit=target,
                          create_version=create_version)
    data_dict_id = data_dict_id or project.get("currentDataDictId")

    vdir = vstore.create_dir(commit_key)  # == repo_dir (already checked out); never wiped
    # Config is PER-PROJECT: workspaces/<pid>/config.json (written by the API). Use it as-is
    # (or an explicit --config); only when --no-llm rewrites it, or none exists, write a copy.
    if not config_path:
        _proj_cfg = os.path.join(ws.root, "config.json")
        config_path = _proj_cfg if os.path.isfile(_proj_cfg) else None
    cfg = resolve_run_config(config_path, no_llm=no_llm)
    # Per-version artifacts go in the VERSION dir, never the per-commit dir. The commit dir is
    # shared by every version built from that commit, so config/parse/manifest written there
    # were overwritten by the next run of the same commit — no concurrency required, just two
    # generations of one commit. The git checkout stays shared: it is read-only once checked
    # out, and two versions of a commit want byte-identical source.
    _adir = store.create_version(version_id)
    if config_path and not no_llm:
        vcfg_path = config_path
    else:
        store.write_config(version_id, cfg)
        vcfg_path = os.path.join(_adir, "config.json")
    store.write_manifest(version_id, _manifest(
        version_id, branch, target, scope, data_dict_id,
        decision="incremental", regenerated=0, reused=0, status="running", warnings=decision["warnings"]))

    dd_path = ws.datadict_path(data_dict_id) if data_dict_id and os.path.isfile(
        ws.datadict_path(data_dict_id)) else None
    # Relocate BEFORE reading model_dir. Capturing it first bound the local to the OLD
    # (shared) dir while the phases were told the new one — a split brain in which the
    # phases parsed into versions/<ver>/model but classify compared the STALE shared model,
    # found every hash identical, and reported "nothing changed / 0 regenerated".
    set_output_dir(os.path.join(store.artifact_dir(version_id), "output"))
    set_model_dir(os.path.join(store.artifact_dir(version_id), "model"))   # C11b
    model_dir = _paths().model_dir
    # Clean it so this version captures only its own documents (the flowchart-reuse step
    # re-seeds output/<scope>/flowcharts from the baseline). Now scoped to THIS version.
    _rmtree_force(_paths().output_dir)

    def _fail(stage: str, rc: int):
        m = _manifest(
            version_id, branch, target, scope, data_dict_id,
            decision="incremental", regenerated=0, reused=0, status="failed",
            warnings=decision["warnings"] + [f"{stage} exited {rc}"])
        store.write_manifest(version_id, m)     # close the lifecycle: 'failed', not mid-phase
        raise AnalyzerRunFailed(f"{stage} failed (exit {rc})", rc)

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
            project_name=project_name,
            target=target, base_commit=decision["chosenBaseCommit"],
            base_parse_dir=_parse_dir_for(store, vstore, base_vid, base_commit),
            store=store, base_vid=base_vid, version_id=version_id, project_id=project_id,
            base_fingerprint=(store.read_run_metadata(base_vid) or {}).get("parseFingerprint"))
    if used_narrowed and verify_parse:
        # M4.5 self-check: shadow-validate the narrowed model against a FULL parse, then use
        # the full parse as the source of truth (a verify run is slow but always safe).
        from core.logging_setup import get_logger as _get_logger
        _vlog = _get_logger("incremental")
        narrowed_model = _load_parse_model(model_dir, version_id=version_id,
                                           project_id=project_id)
        rc = _run_analyzer(vcfg_path, scope, no_llm, dd_path, repo_dir, project_root,
                           extra_args=["--to-phase", "1"], project_name=project_name,
                           version_id=version_id, project_id=project_id)
        if rc != 0:
            _fail("parse", rc)
        mism = diff_models(narrowed_model,
                           _load_parse_model(model_dir, version_id=version_id,
                                             project_id=project_id))
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
        # A full parse leaves a COMPLETE model in model/, so it is safe to persist at this
        # boundary. The narrowed path above is not: it produces a PARTIAL model that is only
        # complete after parse_merge, so it deliberately passes no version id.
        rc = _run_analyzer(vcfg_path, scope, no_llm, dd_path, repo_dir, project_root,
                           extra_args=["--to-phase", "1"], project_name=project_name,
                           version_id=version_id, project_id=project_id)
        if rc != 0:
            _fail("parse", rc)

    # Snapshot THIS version's blank skeleton for future narrowed parses (M4.4).
    snapshot_parse_model(model_dir, _adir, store, version_id)
    # Run identity lands HERE, not at the end. Phase 3's flowchart engine reads base_path from
    # `versions` to resolve source files, and Phase 3 runs before the end-of-run write — so the
    # engine saw NULL, rooted its SourceExtractor at "", and every flowchart came back
    # "Source file not found: <relative path>" while the run reported success.
    _persist_run_metadata(store, version_id, project_id)

    # The target model as Phase 1 just produced it. In database mode Phase 1 flushed to the
    # database and these files are not written, so reading them would yield four empty dicts —
    # classify would then see every entity as DELETED, impact would be empty, and the run would
    # regenerate nothing while reporting success. Read whichever backing the run actually used.
    _tm = _orchestrator_model(store, version_id)
    target_hashes = _tm.get("hashes") or {}
    target_functions = _tm.get("functions") or {}
    target_edges = _tm.get("edges") or _EMPTY_EDGES_SHAPE
    target_globals = _tm.get("globals") or {}
    # Baseline read from the store by the real ver id (FileStore -> versions/<ver>/model,
    # PgStore -> Postgres). Replaces the on-disk HashStore read, the commit-dir model read, and
    # the separate DATABASE_URL branch — the store resolves file-vs-DB by construction.
    # ONE connection for all three, instead of one each. They are the same version and the
    # same join; splitting them tripled the connection acquisitions for no benefit.
    _bm = store.read_model_parts(base_vid, ("hashes", "functions", "globals"))
    base_hashes = _bm.get("hashes") or {}
    base_functions = _bm.get("functions") or {}
    base_globals = _bm.get("globals") or {}

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
            _func_cache[vid] = store.read_functions(vid)   # by real ver id
        return _func_cache[vid]

    def _src_globs(vid: str) -> dict:
        if vid not in _glob_cache:
            _glob_cache[vid] = store.read_globals(vid)
        return _glob_cache[vid]

    # Resolve every impact-set fingerprint in ONE query, then hand
    # `carry_forward_from_index` a plain dict (doc 09, B5a). It stays pure and still just
    # needs something with `.get(fp)` — the batching lives here, at the call site, so its
    # unit tests keep passing a plain dict and the abstraction is unchanged.
    _lookup_keys = [k for k in (list(plan["impact"]) + list(impacted_globals))]
    _index_hits = ridx.get_many(
        [fp for fp in (target_fps.get(k) for k in _lookup_keys) if fp])

    index_reused = carry_forward_from_index(plan["impact"], target_fps, target_functions,
                                            _index_hits, version_id, _src_funcs, _CARRY_FIELDS)
    index_reused_g = carry_forward_from_index(impacted_globals, target_fps, target_globals,
                                              _index_hits, version_id, _src_globs, ("description",))
    # Entities satisfied from the index drop out of the LLM regen sets (Phase 2 skips them
    # because they now carry a description + behaviour names).
    regen_impact = [k for k in plan["impact"] if k not in index_reused]
    regen_globals = {k for k in impacted_globals if k not in index_reused_g}

    # Hand the carried-forward descriptions to Phase 2 through whatever it will READ. Writing
    # files in database mode would put them somewhere Phase 2 never looks, so every reused
    # entity would arrive blank and be regenerated — reuse silently lost.
    _publish_model_for_next_phase(store, version_id, project_id, model_dir,
                                  target_functions, target_globals, target_hashes)

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
    # index_reused[fid] is a real ver id; the flowchart view needs that version's checkout DIR,
    # so map it back to its commit (fall back to the id for a commit-keyed CLI run).
    xver_flowcharts = {fid: _artifact_dir_for(store, vstore, index_reused[fid],
                                              _ver_commit.get(index_reused[fid], index_reused[fid]))
                       for fid in direct_fns if fid in index_reused}
    flowchart_fids_regen = sorted(direct_fns - set(xver_flowcharts))
    # flowchartFids (for FUNCTION-LEVEL flowchart reuse, M3.6) = the directly changed/
    # new function fids themselves. The flowcharts view regenerates ONLY these and
    # splices them into the baseline file JSONs, instead of regenerating every function
    # in a changed file. (flowchartFiles is kept for older readers / file-level fallback.)
    # Make sure the baseline's Phase-3 output actually EXISTS before the plan points at it
    # (doc 09, IN-3). Flowchart carry-forward copies the baseline's <unit>.json files, and
    # those are a genuine INPUT: the flowchart engine writes the DOT text into them in one
    # process and the view reads them back in another to render each PNG. On a machine that
    # did not produce the baseline those files are simply absent — carry-forward finds
    # nothing, every flowchart is re-rendered, and the run still "succeeds" with 0% flowchart
    # reuse and no error. The text has been in Postgres since PG-5a; this restores it.
    _base_dir = _artifact_dir_for(store, vstore, base_vid, base_commit)
    _base_out = os.path.join(_base_dir, "output")
    if not os.path.isdir(_base_out) or not os.listdir(_base_out):
        try:
            n = store.hydrate_output(base_vid, _base_out)
            if n:
                from core.logging_setup import get_logger as _gl
                _gl("incremental").info(
                    f"IN-3: restored {n} baseline output file(s) for {base_vid} from the "
                    f"database — flowchart carry-forward can run on this node")
        except Exception as exc:
            from core.logging_setup import get_logger as _gl
            _gl("incremental").warning(f"IN-3: could not restore baseline output: {exc}")

    # Written to the backing the PHASES read (doc 10, step 6). The orchestrator installs no
    # model repository, so `write_model_file` here would use the FILE default and drop the plan
    # into model/incremental_plan.json — while Phase 3, running in database mode, looks in
    # `incremental_plans` and finds nothing. It then treats the run as non-incremental and
    # rebuilds EVERY flowchart, which is the largest cost in Phase 3, with no error and a reuse
    # report that still claims the carry-forward happened.
    _write_plan(version_id, project_id, {"impactFids": sorted(regen_impact),
                                   "impactedGlobals": sorted(regen_globals),
                                   "impactedFiles": impacted_files,
                                   "flowchartFiles": flowchart_files,
                                   "flowchartFids": flowchart_fids_regen,
                                   "crossVersionFlowcharts": xver_flowcharts,
                                   "baselineVersionDir": _base_dir})

    # Resume derive+views+export: Phase 2 summarizer skips the carried-forward reuse
    # set; Phase 3 flowcharts restricted to impacted files (rest carried forward).
    rc = _run_analyzer(vcfg_path, scope, no_llm, dd_path, repo_dir, project_root,
                       extra_args=["--from-phase", "2"], project_name=project_name,
                       version_id=version_id, project_id=project_id)
    if rc != 0:
        _fail("derive+views+export", rc)

    # The plan file has done its job (Phase 3 read it); remove so it isn't captured.
    try:
        # Clearing it is as important as writing it: a stale plan would make the NEXT run
        # inherit this run's restriction and regenerate almost nothing.
        _write_plan(version_id, project_id, {})
    except OSError:
        pass

    # Capture artifacts + snapshots, seed the reuse index, finalize the manifest.
    # Structured model (+ hashes + edges) -> store, keyed by the real ver id; this is what the
    # NEXT run reads as its baseline (Postgres under PgStore, versions/<ver…>/model under FileStore).
    # NB: no store.write_model() — see generate.py. It would clear the version and persist an
    # EMPTY model read from a directory the phases never wrote to.
    # Run identity (basePath/projectName/parseFingerprint) -> the store: the `versions` columns
    # under PgStore. Replaces the API reading model/metadata.json off disk (doc 07 §3).
    _persist_run_metadata(store, version_id, project_id)
    # Rendered output -> versions/<ver id>/ (what every reader resolves) + the .docx list.
    documents = store.capture_output(version_id, _paths().output_dir)
    llm = cfg.get("llm") or {}
    # Content-only reuse key (recipe intentionally not folded in — approved outputs are
    # reused regardless of which model/prompt produced them). Reuse the fingerprints
    # computed for the M3.7 lookup (descriptions added since don't affect the content key).
    # One existence query for the whole project instead of one per entity (doc 09, B5a).
    # First version that produced a fingerprint keeps it — semantics unchanged.
    ridx.put_many((fp, version_id, entity_key) for entity_key, fp in target_fps.items())
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
    # AND to the store -> Postgres (doc 09, C1). `vstore` is the file store keyed by COMMIT;
    # `store` is the artifact store keyed by the real VERSION id and is the only one that
    # closes versions.pipeline_status. Without this the version stays at its last in-progress
    # phase and is never again eligible as a baseline.
    store.write_manifest(version_id, manifest)

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
        "llmCalls": _llm_call_counts(version_id),
    }
    _report_lines = build_report(stats)
    # report.txt is not written in database mode: the report is stored verbatim in
    # versions.report, nothing reads the file, and the log still carries every line.
    emit_report(_report_lines, version_dir=vdir, write_file=False)
    # ...and to the store, so the report is readable from any node rather than only the
    # one that ran the job (versions.report existed but was never written).
    try:
        store.write_report(version_id, "\n".join(_report_lines))
    except Exception:
        pass                       # the report is already logged + on disk
    # C11c — last thing, so nothing downstream can still need the files.

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
    ap.add_argument("--no-narrowed-parse", dest="narrowed_parse", action="store_false",
                    default=True,
                    help="Force a FULL re-parse. Narrowed parse is ON by default: it re-parses "
                         "only the affected TUs and merges them into the baseline skeleton, "
                         "which is the single biggest non-LLM saving (parsing is ~65%% of a "
                         "run). It falls back to a full parse by itself whenever it cannot "
                         "prove the merge safe — changed compiler flags, a rename it cannot "
                         "track, a baseline with no stored skeleton.")
    ap.add_argument("--verify-parse", action="store_true",
                    help="M4.5: with --narrowed-parse, also run a full parse and diff it against "
                         "the narrowed result (logs mismatches; uses the full parse). Slow; for validation.")
    ap.add_argument("--create-version", action="store_true",
                    help="reserve the versions row if it does not exist (see generate.py).")
    ap.add_argument("--config", default=None, help="per-project config.json to use as-is")
    ap.add_argument("--repo-url", default=None, help="clone URL (else resolved from the project record)")
    args = ap.parse_args()
    try:
        m = generate_incremental(args.project_id, args.branch, args.commit,
                                 _parse_scope(args.scope),
                                 base_version_id=args.base_version_id,
                                 data_dict_id=args.data_dict_id,
                                 no_llm=args.no_llm, version_id=args.version_id,
                                 force=args.force,
                                 narrowed_parse=args.narrowed_parse,
                                 verify_parse=args.verify_parse,
                                 config_path=args.config, repo_url=args.repo_url,
                                 create_version=args.create_version)
    except AnalyzerRunFailed as exc:
        # See generate.main(): exit 2 means the analyzer rejected the request and already
        # explained why. Print a pointer, not a stack trace that buries the explanation.
        if exc.returncode == 2:
            print("\nStopped: see the error above. (No traceback — the "
                  "analyzer already said what was wrong and how to fix it.)",
                  file=sys.stderr)
            raise SystemExit(2)
        raise
    except _DatabaseRequired as exc:
        print(f"\n{exc}", file=sys.stderr)
        raise SystemExit(2)
    print(f"\nversion {m['versionId']} ({m['status']}): commit {m['commit'][:10]}, "
          f"decision={m['decision']}, baseline={m.get('baselineVersionId')}, "
          f"regenerated={m['regenerated']}, reused={m['reused']}, "
          f"carriedForward={m.get('carriedForward')}, documents={m.get('documents')}")


if __name__ == "__main__":
    main()
