"""Version-producing FULL generation (M1.3, doc 04 §5 full path / §9 M1).

Runs the analyzer for a project at a commit, then captures the result as an
immutable *version* and seeds the cross-version reuse index. This is the
foundation every incremental run diffs against; the M2 incremental path will
reuse the same stores + fingerprints.

Flow (full / first-version / mode:"full"):
  1. checkout <commit> in the workspace repo
  2. build the resolved per-run config = global config (clang/llm/views) + the
     project's layers; write it to versions/<id>/config.json
  3. run.py --config <that> [scope flags] <repo>  -> model/ + output/ + documents
  4. capture model/output/documents + hashes.json + edges.json into versions/<id>/
  5. compute fingerprints, seed cache/index.json (reuse pointers)
  6. write manifest.json, append versions/index.json

Everything that persists goes through the D9 stores (stores.py).

CLI:
  python -m incremental.generate --project-id samplecpp --branch main \
         --commit <sha> --scope group:Support --no-llm
"""
from __future__ import annotations

import argparse
import copy
import datetime as _dt
import os
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

# Allow `python src/incremental/generate.py ...` and `python -m incremental.generate`
# by ensuring src/ (this file's package parent) is importable.
_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from core.paths import paths as _paths, set_output_dir, set_model_dir
from core.config import load_config
from core.run_context import effective_model_store, DatabaseRequired as _DatabaseRequired
from incremental import git_ops
from incremental.stores import Workspace, VersionStore, _rmtree_force
from incremental.clone import ensure_commit_checkout
from incremental.project_db import get_project, resolve_project_repo
from incremental.fingerprint import compute_fingerprints
from incremental.edges import build_edges  # noqa: F401  (kept for symmetry / future use)


class AnalyzerRunFailed(RuntimeError):
    """A phase subprocess exited non-zero. Carries the code so the CLI can tell a USAGE error
    (exit 2 — the analyzer already printed exactly what was wrong) from a real crash."""

    def __init__(self, message: str, returncode: int = 1):
        super().__init__(message)
        self.returncode = returncode


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# The post-Phase-1 (blank-skeleton) parser artifacts. Snapshotted per version so a future
# narrowed parse (M4) can merge against the baseline's skeleton, not its finished model.
_PARSE_SNAPSHOT_FILES = ("functions.json", "globalVariables.json", "dataDictionary.json",
                         "hashes.json", "edges.json", "tu_includes.json",
                         "entity_files.json", "func_keys.json", "override_pairs.json",
                         "address_taken.json", "metadata.json")


def snapshot_parse_model(model_dir: str, version_dir: str, store=None,
                         version_id: str = "") -> None:
    """Capture the post-Phase-1 model (blank skeleton — no LLM descriptions yet) into the
    version's parse snapshot. MUST run right after Phase 1, before Phase 2 fills descriptions
    in. This is the baseline a narrowed parse (M4) merges against, so impacted functions arrive
    blank and get regenerated (doc 04 §11).

    Stored, never copied to disk (doc 09, C2). On disk a snapshot only existed on the machine
    that produced the baseline, so narrowed parse could not work across nodes and was lost with
    any workspace clean. Best-effort — a snapshot failure must not fail a good run.
    """
    if store is not None and version_id:
        try:
            # Built from what the database HAS, not from the model dir. After a narrowed parse
            # that directory holds the PARTIAL parse, and a snapshot of it would be a baseline
            # full of holes — which is how an incremental version once ended up with a
            # versions/<id>/parse/ of incomplete JSON while a full version's stayed empty.
            _m = store.read_model(version_id) or {}
            _snap = {f"{k}.json": _m.get(v) or {} for k, v in (
                ("functions", "functions"), ("globalVariables", "globals"),
                ("dataDictionary", "datadict"), ("hashes", "hashes"),
                ("edges", "edges"))}
            # tu_includes / entity_files / func_keys / override_pairs / address_taken /
            # metadata are NOT read back off disk: Phase 1 wrote them straight into
            # parse_snapshots through the repository. Hence merge rather than replace — a
            # replace here would delete exactly those rows.
            n = store.write_parse_snapshot_data(version_id, _snap, replace=False)
            if n:
                from core.logging_setup import get_logger as _gl
                _gl("incremental").info(f"C2: stored {n} parse-snapshot file(s) for {version_id}")
        except Exception as exc:
            from core.logging_setup import get_logger as _gl
            _gl("incremental").warning(f"C2: could not store the parse snapshot: {exc}")


def run_metadata(store, version_id: str, project_id: str) -> Dict[str, Any]:
    """The run's identity metadata — basePath / projectName / parseFingerprint.

    Read from the parse snapshot Phase 1 wrote. Both orchestrators used to open
    `model/metadata.json` directly; step 11a moved `metadata` into `parse_snapshots`, so that
    file stopped existing and the read silently produced nothing. `versions.base_path` was then
    NULL, and the flowchart engine — which takes base_path from that column — built a
    SourceExtractor rooted at "", so every function failed with "Source file not found:
    <relative path>" and every flowchart came back empty.

    Silent because both sites tolerated a missing file: one skipped the write, the other wrote
    an empty dict. Neither is wrong on its own; both stopped being reachable at the same time.
    """
    from core.model_repo import DbRepository
    try:
        return DbRepository(version_id, project_id or "").read(
            "metadata", required=False, default={}) or {}
    except Exception:
        return {}


def _persist_run_metadata(store, version_id: str, project_id: str) -> bool:
    """Write basePath / projectName / parseFingerprint to the store. True if it had something.

    Called right after Phase 1 — see the call site for why the timing matters — and again at the
    end of the run, which is idempotent and covers a metadata refresh.
    """
    meta = run_metadata(store, version_id, project_id)
    from core.logging_setup import get_logger as _gl
    if not meta:
        _gl("incremental").warning(
            "run metadata is empty — versions.base_path/project_name stay NULL, and the "
            "flowchart engine resolves every source file from base_path")
        return False
    store.write_run_metadata(version_id, meta)
    return True


# What the orchestrators actually consume out of the model. Loading all eight artifacts to use
# four meant two of the three expensive entity joins were pure waste, once per run per
# orchestrator.
_ORCH_PARTS = ("functions", "globals", "hashes", "edges")


def llm_call_counts(version_id: str) -> Dict[str, int]:
    """{"kind|outcome": n} for a version, summed over every phase subprocess.

    Read at report time, not accumulated in the orchestrator: the phases are separate
    processes, so the orchestrator's own counter would always be empty. Best-effort — the
    report must still print if the accounting is unavailable.
    """
    if not version_id:
        return {}
    try:
        from core.db import get_engine, is_database_configured
        if not is_database_configured():
            return {}
        from llm_core.callstats import load_for_version, load_timing_for_version
        with get_engine().connect() as cx:
            out = {f"{k}|{o}": n for (k, o), n in load_for_version(cx, version_id).items()}
            # Prefixed so it cannot collide with a "kind|outcome" key. The report reads it to
            # say where the wall-clock went — on a throttled gateway that is the whole story,
            # and a call count alone never shows it.
            for f, v in load_timing_for_version(cx, version_id).items():
                out[f"__timing__|{f}"] = v
            return out
    except Exception as exc:
        # Do NOT return {} here. An empty dict means "no LLM calls", and the report then omits
        # the section entirely — so a missing `llm_call_stats` table (migration 0007 not
        # applied) looks exactly like a --no-llm run. The section going quiet is precisely the
        # kind of silent absence this accounting exists to end.
        from core.logging_setup import get_logger as _gl
        _gl("incremental").warning("LLM call accounting unavailable (%s) — the report's LLM "
                                   "section will say so rather than be omitted", exc)
        return {"__unavailable__": str(exc)}

def _orchestrator_model(store, version_id: str, parts=_ORCH_PARTS) -> Dict[str, Any]:
    """The finished model, for the orchestrator's own bookkeeping (report + fingerprints).

    The phases write to the database, so this reads the store. Returns
    `core.model_store.load_model`'s keys — functions / globals / hashes / edges / …
    """
    return store.read_model_parts(version_id, parts) or {}


def scope_to_args(scope: Dict[str, Any]) -> List[str]:
    """Map a scope object to run.py flags (doc 04 §8 / D5)."""
    stype = (scope or {}).get("type", "project")
    names = (scope or {}).get("names") or []
    if stype == "project":
        return []
    # Every name, not just the first. `names[0]` meant `--scope group:App,Math` generated App
    # and silently dropped Math: the run succeeded, the reuse report looked healthy, and the
    # document simply had one group in it.
    if stype == "layer":
        out: List[str] = []
        for n in names:
            out += ["--selected-layer", n]
        return out
    if stype == "group":
        out = []
        for n in names:
            out += ["--selected-group", n]
        return out
    if stype == "component":
        out = []
        for n in names:
            out += ["--selected-component", n]
        return out
    raise ValueError(f"unknown scope type {stype!r}")


def per_component_docx_args(scope: Dict[str, Any]) -> List[str]:
    """Generate one DOCX *per component* (the default) instead of one per group.

    Mutually exclusive with --selected-component (run.py errors if combined), so a
    specific-component run gets nothing extra; project / layer / group scope all get
    --component-per-docx. Groups with no components defined simply produce nothing."""
    stype = (scope or {}).get("type", "project")
    return [] if stype == "component" else ["--component-per-docx"]


def resolve_run_config(config_path: Optional[str], *, no_llm: bool = False) -> Dict[str, Any]:
    """Load the PER-PROJECT config (workspaces/<pid>/config.json, written by the API from the
    project's architecture_layers + build_config — see api/PROJECT_CONTEXT). The engine does
    NOT build config: if it's missing, that's an error (the API creates it at onboarding /
    when a job runs). Applies the no_llm kill switch last."""
    if not (config_path and os.path.isfile(config_path)):
        raise RuntimeError(
            f"per-project config not found ({config_path!r}). It is created by the API "
            f"(POST /projects onboarding, or when a job runs). Onboard the project / run a "
            f"job, or pass --config <path>.")
    import json as _json
    with open(config_path, "r", encoding="utf-8") as fh:
        cfg = _json.load(fh)
    if no_llm:
        apply_no_llm(cfg)
    return cfg


def apply_no_llm(cfg: Dict[str, Any]) -> None:
    """Make `--no-llm` a TRUE kill switch (M-D): disable every LLM-backed enrichment in the
    resolved config — Phase 2 function descriptions + behaviour names, the DOCX struct/unit
    summaries (gated on llm.descriptions), and (via flowcharts.py) the flowchart node labels.
    Hierarchy summaries are already off via --no-llm-summarize. For deterministic, LLM-free
    runs (timing tests); the output keeps structure but loses LLM prose / labels."""
    llm = cfg.setdefault("llm", {})
    llm["descriptions"] = False
    llm["behaviourNames"] = False


def generate_full(
    project_id: str,
    branch: str,
    commit: str,
    scope: Optional[Dict[str, Any]] = None,
    *,
    workspaces_root: Optional[str] = None,
    data_dict_id: Optional[str] = None,
    no_llm: bool = False,
    force: bool = False,
    version_id: Optional[str] = None,
    repo_url: Optional[str] = None,
    repo_token: Optional[str] = None,
    config_path: Optional[str] = None,
    create_version: bool = False,
) -> Dict[str, Any]:
    """Produce a new full-generation version. Returns the manifest dict.

    `version_id` may be pre-allocated by the caller (the backend reserves it so
    the API can return it immediately); otherwise the next sequential id is used.
    Analyzer stdout/stderr are *inherited* (not captured) so the caller controls
    where they land — the backend points them at the per-job log so progress
    markers are visible to the existing job-status machinery.
    """
    _t0 = time.perf_counter()
    scope = scope or {"type": "project"}
    project_root = _paths().project_root

    ws = Workspace(project_id, workspaces_root)
    project = get_project(project_id)        # api/db/data/projects.json (no project.json)
    project_name = (project.get("name") or "").strip()
    vstore = VersionStore(ws)
    # ridx is bound after make_store below (the reuse index now lives in the store).

    data_dict_id = data_dict_id or project.get("currentDataDictId")

    # 1. ensure the per-commit checkout. The repo for a commit IS its version dir,
    #    workspaces/<pid>/<commit[:16]>/. The API pre-clones it for a Job; the CLI clones
    #    on demand (repo_url/token from the project record when not passed explicitly).
    repo_dir = ws.commit_dir(commit)
    if not repo_url and not os.path.isdir(os.path.join(repo_dir, ".git")):
        repo_url, _rb, repo_token = resolve_project_repo(project_id)
    ensure_commit_checkout(repo_dir, repo_url or "", branch, commit, token=(repo_token or ""))
    actual_commit = git_ops.current_commit(repo_dir)
    # Version identity (08): the checkout DIR stays commit-keyed (commit_key); the version
    # IDENTITY is the real `ver…` id supplied by the backend (`--version`), falling back to
    # commit[:16] for standalone CLI use. The store keys artifacts by version_id.
    from incremental.store import make_store
    commit_key = os.path.basename(repo_dir)
    version_id = version_id or commit_key
    # Step 9: 'db' is the default, so resolve it once here against what this machine can do and
    # pass the ANSWER down. Everything below — the phase flags, the snapshot source, the
    # orchestrator's own model read — keys off this one value.
    # Not a choice any more — a check. Raises DatabaseRequired when this run cannot reach the
    # database, which is the only backing there is.
    effective_model_store(version_id, project_id=project_id, commit=actual_commit,
                          create_version=create_version)
    store = make_store(project_id, workspaces_root)
    from incremental.engine import StoreReuseIndex
    ridx = StoreReuseIndex(store)      # reuse index via the store: Postgres under PgStore

    # 2. resolved config -> <commit_key>/config.json + a "running" manifest so the
    #    version is queryable immediately (status flips to complete/failed below).
    vdir = vstore.create_dir(commit_key)     # == repo_dir; ensured, never wiped
    # Config is PER-PROJECT: workspaces/<pid>/config.json (the API writes it from the
    # project's architecture_layers + build_config). Use it as-is (or an explicit --config).
    # Only when --no-llm must rewrite it, or no per-project config exists, do we materialize
    # a per-run copy in the version dir.
    if not config_path:
        _proj_cfg = os.path.join(ws.root, "config.json")
        config_path = _proj_cfg if os.path.isfile(_proj_cfg) else None
    cfg = resolve_run_config(config_path, no_llm=no_llm)
    # Per-version artifacts belong in the VERSION dir, not the per-commit dir — the latter is
    # shared by every version built from that commit, so a second generation of the same
    # commit silently overwrote the first's config/parse/manifest. The git checkout stays
    # shared (read-only once checked out; identical source for both).
    _adir = store.create_version(version_id)
    if config_path and not no_llm:
        vcfg_path = config_path                       # run.py uses the per-project config as-is
    else:
        store.write_config(version_id, cfg)
        vcfg_path = os.path.join(_adir, "config.json")
    store.write_manifest(version_id, _manifest(
        version_id, branch, actual_commit, scope, data_dict_id,
        decision="full", regenerated=0, reused=0, status="running", warnings=[]))

    # 3. run the analyzer (full) against the workspace repo (stdout/stderr inherited).
    # Render STRAIGHT into this version's own output dir (doc 09, B1). Previously every run
    # wrote the shared <root>/output and was copied into the version afterwards — so a second
    # concurrent job's _rmtree_force below would delete this one's work. Writing to a
    # version-scoped dir removes both the shared state and the copy step.
    _out_root = os.path.join(store.artifact_dir(version_id), "output")
    _model_root = os.path.join(store.artifact_dir(version_id), "model")
    set_output_dir(_out_root)                       # this process (rmtree + capture below)
    set_model_dir(_model_root)                      # C11b: this version owns its model dir
    # Still cleaned, but this is now THIS version's own dir — nobody else can be using it.
    _rmtree_force(_paths().output_dir)
    base_cmd = [sys.executable, os.path.join(_SRC, "run.py"), "--config", vcfg_path,
                "--output-root", _out_root,         # and the analyzer process
                "--model-root", _model_root,
                # C11a: each phase persists its model to the DB at its own boundary. The
                # end-of-run store.write_model below still runs — dual-write until C11b.
                "--version-id", version_id, "--project-id", project_id]
    # doc 10: which backing the PHASES use for the model. Forwarded so every phase process
    # agrees with the orchestrator — a phase writing files while the orchestrator reads the
    # database (or the reverse) is the worst of both.
    base_cmd += scope_to_args(scope)
    base_cmd += per_component_docx_args(scope)
    if project_name:
        # Otherwise parser.py defaults projectName to the checkout dir basename
        # (commit[:16]) — the sha would surface in the DOCX cover + 1.1 Purpose.
        base_cmd += ["--project-name", project_name]
    if no_llm:
        base_cmd += ["--no-llm-summarize"]
    if data_dict_id:
        dd = ws.datadict_path(data_dict_id)
        if os.path.isfile(dd):
            base_cmd += ["--data-dictionary", dd]

    model_dir = _paths().model_dir

    def _fail_full(rc):
        m = _manifest(
            version_id, branch, actual_commit, scope, data_dict_id,
            decision="full", regenerated=0, reused=0, status="failed",
            warnings=[f"analyzer exited {rc}"])
        store.write_manifest(version_id, m)     # close the lifecycle: 'failed', not mid-phase
        raise AnalyzerRunFailed(f"analyzer run failed (exit {rc})", rc)

    # Phase-split (M4.4): Phase 1 (parse) -> snapshot the blank-skeleton model into the
    # version (the baseline a future narrowed parse merges against) -> Phase 2+.
    rc = subprocess.run(base_cmd + ["--to-phase", "1", repo_dir],
                        cwd=project_root, shell=(os.name == "nt")).returncode
    if rc != 0:
        _fail_full(rc)
    snapshot_parse_model(model_dir, _adir, store, version_id)
    # Run identity lands HERE, not at the end of the run. Phase 3's flowchart engine reads
    # base_path from `versions` to resolve source files, and Phase 3 executes inside the
    # subprocess below — so writing this after it returns is too late: the engine sees NULL,
    # roots its SourceExtractor at "", and every function fails with
    # "Source file not found: <relative path>" while the run reports success.
    _persist_run_metadata(store, version_id, project_id)
    # --model-from-db re-materialized the stored model to disk between Phase 1 and Phase 2, so
    # Phase 2+ consumed the STORED copy rather than Phase 1's files. Removed with step 11b: the
    # phases read the database directly, so there is nothing to re-materialize and nothing left
    # for the two copies to disagree about.
    rc = subprocess.run(base_cmd + ["--from-phase", "2", repo_dir],
                        cwd=project_root, shell=(os.name == "nt")).returncode
    if rc != 0:
        _fail_full(rc)

    # 4. capture artifacts (model/output/documents) + hashes/edges snapshots
    output_dir = _paths().output_dir
    # Structured model (+ hashes + edges) -> the store, keyed by the real ver id. This is what
    # the NEXT run reads as its baseline (store.read_hashes/functions), replacing the on-disk
    # HashStore/EdgeStore. Postgres under PgStore; versions/<ver…>/model under FileStore.
    # NB: no store.write_model() here. That reads model FILES
    # (persist_model_from_dir -> clear_version + persist); the phases have already flushed
    # their own writes, so calling it would CLEAR the version and store an empty model over
    # the real one.
    # Run identity (basePath/projectName/parseFingerprint) -> the store: the `versions` columns
    # under PgStore. Replaces the API reading model/metadata.json off disk (doc 07 §3).
    _persist_run_metadata(store, version_id, project_id)
    # Rendered output -> versions/<ver id>/ (what every reader resolves) + the .docx list.
    documents = store.capture_output(version_id, output_dir)
    _m = _orchestrator_model(store, version_id)
    hashes, edges, functions = _m.get("hashes") or {}, _m.get("edges") or {}, _m.get("functions") or {}

    # 5. fingerprints -> seed reuse index (content-only key; recipe is intentionally
    #    not folded in — an approved doc is reused regardless of model/prompt).
    llm = cfg.get("llm") or {}
    fps = compute_fingerprints(hashes, functions, edges)
    # One existence query for the whole project instead of one per entity (doc 09, B5a).
    # This is the worst case of the two seeding loops — a full generation fingerprints
    # EVERY function and global. First writer of a fingerprint still keeps it.
    ridx.put_many((fp, version_id, entity_key) for entity_key, fp in fps.items())
    ridx.save()

    # 6. manifest + index
    manifest = _manifest(version_id, branch, actual_commit, scope, data_dict_id,
                         decision="full",
                         regenerated=len(fps), reused=0, status="complete", warnings=[])
    manifest["documents"] = documents
    # AND to the store, which is what reaches Postgres (doc 09, C1). These are two different
    # stores keyed two different ways: `vstore` is the file VersionStore keyed by COMMIT,
    # `store` is the artifact store keyed by the real VERSION id. Writing only the first
    # leaves versions.pipeline_status at its last in-progress phase, and
    # pg_stores.list_versions then refuses the version as a baseline forever - so every
    # later run falls back to a full generation and reuses nothing.
    store.write_manifest(version_id, manifest)

    # End-of-run report (M3.4): a full generation regenerates everything (it becomes
    # the baseline future incrementals diff against).
    globals_ = _m.get("globals") or {}
    files_total = len({(f.get("location") or {}).get("file") for f in functions.values()} - {None})
    stype = (scope or {}).get("type", "project")
    names = (scope or {}).get("names") or []
    from incremental.report import build_report, emit_report
    _report_lines = build_report({
        "versionId": version_id, "decision": "full", "status": "complete",
        "projectId": project_id, "branch": branch, "commit": actual_commit,
        "scope": stype if (stype == "project" or not names) else f"{stype}:{','.join(names)}",
        "dataDictId": data_dict_id,
        "llmModel": llm.get("defaultModel"), "elapsedSeconds": time.perf_counter() - _t0,
        "functions": {"total": len(functions), "regenerated": len(functions), "reused": 0},
        "globals": {"total": len(globals_), "regenerated": len(globals_), "reused": 0},
        "flowcharts": {"total": len(functions), "regenerated": len(functions), "carried": 0},
        "files": {"total": files_total, "regenerated": files_total, "carried": 0},
        "documents": documents, "warnings": [],
        "llmCalls": llm_call_counts(version_id),
    })
    # report.txt is not written in database mode: the report is stored verbatim in
    # versions.report, nothing reads the file, and the log still carries every line.
    emit_report(_report_lines, version_dir=vdir, write_file=False)
    # ...and to the store, so the report is readable from any node (versions.report existed
    # but was never written).
    try:
        store.write_report(version_id, "\n".join(_report_lines))
    except Exception:
        pass                           # already logged + on disk
    # C11c — last thing, so nothing downstream can still need the files.
    return manifest


def _manifest(version_id, branch, commit, scope, data_dict_id, *,
              decision, regenerated, reused, status, warnings) -> Dict[str, Any]:
    return {
        "versionId": version_id, "branch": branch, "commit": commit,
        "scope": scope, "dataDictId": data_dict_id, "baselineVersionId": None,
        "decision": decision,
        "regenerated": regenerated, "reused": reused,
        "status": status, "warnings": warnings, "createdAt": _now_iso(),
    }


def _parse_scope(s: str) -> Dict[str, Any]:
    if not s or s == "project":
        return {"type": "project"}
    kind, _, names = s.partition(":")
    return {"type": kind, "names": [n for n in names.split(",") if n]}


def main() -> None:
    ap = argparse.ArgumentParser(description="Produce a full-generation version (M1.3).")
    ap.add_argument("--project-id", required=True)
    ap.add_argument("--branch", required=True)
    ap.add_argument("--commit", required=True)
    ap.add_argument("--scope", default="project",
                    help="project | layer:L | group:G | component:C1,C2")
    ap.add_argument("--data-dict-id", default=None)
    ap.add_argument("--version-id", default=None, help="(derived from the commit; kept for compat)")
    ap.add_argument("--no-llm", action="store_true", help="skip LLM hierarchy summarization")
    ap.add_argument("--force", action="store_true", help="(no-op; the commit dir is reused)")
    ap.add_argument("--create-version", action="store_true",
                    help="reserve the versions row if it does not exist. The API normally owns "
                         "that row; without this a missing one is an error, so a mistyped "
                         "--version-id fails instead of silently starting a new version.")
    ap.add_argument("--config", default=None, help="per-project config.json to use as-is")
    ap.add_argument("--repo-url", default=None, help="clone URL (else resolved from the project record)")
    args = ap.parse_args()
    try:
        m = generate_full(args.project_id, args.branch, args.commit, _parse_scope(args.scope),
                          data_dict_id=args.data_dict_id, no_llm=args.no_llm, force=args.force,
                          version_id=args.version_id, config_path=args.config,
                          repo_url=args.repo_url,
                          create_version=args.create_version)
    except AnalyzerRunFailed as exc:
        # Exit 2 is the analyzer's USAGE code: it already printed the reason — an unknown group,
        # a bad flag — in a form built to be acted on. A traceback here adds nothing and pushes
        # that message fifteen lines up the terminal, which is exactly where it stops being read.
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
          f"decision={m['decision']}, regenerated={m['regenerated']}, "
          f"documents={m.get('documents')}")


if __name__ == "__main__":
    main()
