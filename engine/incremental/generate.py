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
from incremental import git_ops
from incremental.stores import Workspace, VersionStore, HashStore, EdgeStore, ReuseIndex, _rmtree_force
from incremental.clone import ensure_commit_checkout
from incremental.project_db import get_project, resolve_project_repo
from incremental.fingerprint import compute_fingerprints
from incremental.edges import build_edges  # noqa: F401  (kept for symmetry / future use)


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# The post-Phase-1 (blank-skeleton) parser artifacts. Snapshotted per version so a future
# narrowed parse (M4) can merge against the baseline's skeleton, not its finished model.
_PARSE_SNAPSHOT_FILES = ("functions.json", "globalVariables.json", "dataDictionary.json",
                         "hashes.json", "edges.json", "tu_includes.json",
                         "entity_files.json", "func_keys.json", "override_pairs.json",
                         "metadata.json")


def snapshot_parse_model(model_dir: str, version_dir: str, store=None,
                         version_id: str = "") -> None:
    """Capture the post-Phase-1 model (blank skeleton — no LLM descriptions yet) into
    `versions/<id>/parse/`. MUST run right after Phase 1, before Phase 2 fills
    descriptions into model/. This is the baseline a narrowed parse (M4) merges against
    so impacted functions arrive blank and get regenerated (doc 04 §11)."""
    dst = os.path.join(version_dir, "parse")
    os.makedirs(dst, exist_ok=True)
    for fn in _PARSE_SNAPSHOT_FILES:
        src = os.path.join(model_dir, fn)
        if os.path.isfile(src):
            shutil.copyfile(src, os.path.join(dst, fn))
    # AND into the store (doc 09, C2). On disk this snapshot only exists on the machine that
    # produced the baseline, so narrowed parse could not work across nodes and was lost with
    # any workspace clean. Additive: the files above still get written until C11c, so the
    # readers can fall back. Best-effort — a snapshot failure must not fail a good run.
    if store is not None and version_id:
        try:
            n = store.write_parse_snapshot(version_id, model_dir, _PARSE_SNAPSHOT_FILES)
            if n:
                from core.logging_setup import get_logger as _gl
                _gl("incremental").info(f"C2: stored {n} parse-snapshot file(s) for {version_id}")
        except Exception as exc:
            from core.logging_setup import get_logger as _gl
            _gl("incremental").warning(f"C2: could not store the parse snapshot: {exc}")


def prune_model_files(store, version_id: str, model_dir: str, *, enabled: bool) -> bool:
    """Delete a version's model FILES once the database provably holds them (doc 09, C11c).

    The files stay the channel BETWEEN phases — the phases are separate processes that read
    and write JSON, so they cannot be removed without rewriting all four. What C11c removes is
    keeping them AFTER the run, where Postgres is the durable copy and the directory is dead
    weight (functions.json alone is tens of MB per version on a large project).

    Three guards, because this deletes data:

      * off unless asked (`enabled`) — the caller opts in;
      * `store.model_is_persisted` must say YES. A store with no database always says no, so a
        DB-less run keeps its files, which are then the ONLY copy;
      * failures are swallowed. A directory that will not delete is untidy; a run that fails at
        the last step because of tidying is worse.

    Trade-off worth stating: `tools/verify_model_parity.py` compares the database against these
    files, so pruning removes the ability to re-check a version after the fact. That is why it
    is opt-in rather than the default.
    """
    if not enabled or not version_id or not model_dir:
        return False
    if not os.path.isdir(model_dir):
        return False
    if not store.model_is_persisted(version_id):
        from core.logging_setup import get_logger as _gl
        _gl("incremental").warning(
            f"C11c: keeping {model_dir} — the database does not confirm the model for "
            f"{version_id}, so the files may be the only copy")
        return False
    try:
        _rmtree_force(model_dir)
        from core.logging_setup import get_logger as _gl
        _gl("incremental").info(f"C11c: model files pruned for {version_id} "
                                f"(the model is in the database)")
        return True
    except OSError as exc:
        from core.logging_setup import get_logger as _gl
        _gl("incremental").warning(f"C11c: could not prune {model_dir}: {exc}")
        return False


def scope_to_args(scope: Dict[str, Any]) -> List[str]:
    """Map a scope object to run.py flags (doc 04 §8 / D5)."""
    stype = (scope or {}).get("type", "project")
    names = (scope or {}).get("names") or []
    if stype == "project":
        return []
    if stype == "layer":
        return ["--selected-layer", names[0]]
    if stype == "group":
        return ["--selected-group", names[0]]
    if stype == "component":
        out: List[str] = []
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
    model_from_db: bool = False,
    prune_model_files_after: bool = False,
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
    hstore, estore = HashStore(vstore), EdgeStore(vstore)
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
        vstore.write_manifest(commit_key, m)
        store.write_manifest(version_id, m)     # close the lifecycle: 'failed', not mid-phase
        raise RuntimeError(f"analyzer run failed (exit {rc})")

    # Phase-split (M4.4): Phase 1 (parse) -> snapshot the blank-skeleton model into the
    # version (the baseline a future narrowed parse merges against) -> Phase 2+.
    rc = subprocess.run(base_cmd + ["--to-phase", "1", repo_dir],
                        cwd=project_root, shell=(os.name == "nt")).returncode
    if rc != 0:
        _fail_full(rc)
    snapshot_parse_model(model_dir, _adir, store, version_id)
    # C11b (opt-in): re-materialize the model from Postgres so Phase 2+ consume the STORED
    # model rather than whatever Phase 1 happened to leave on disk. This is what makes the
    # database authoritative — and it is exactly the round-trip tools/verify_model_parity.py
    # checks, so any field the store drops shows up as changed document content immediately.
    # Off by default until that check is clean on a real database (it already caught global
    # descriptions being dropped).
    if model_from_db and store.hydrate_model(version_id, model_dir):
        from core.logging_setup import get_logger as _gl
        _gl("incremental").info(
            f"C11b: model re-materialized from the database for {version_id}")
    rc = subprocess.run(base_cmd + ["--from-phase", "2", repo_dir],
                        cwd=project_root, shell=(os.name == "nt")).returncode
    if rc != 0:
        _fail_full(rc)

    # 4. capture artifacts (model/output/documents) + hashes/edges snapshots
    output_dir = _paths().output_dir
    # Structured model (+ hashes + edges) -> the store, keyed by the real ver id. This is what
    # the NEXT run reads as its baseline (store.read_hashes/functions), replacing the on-disk
    # HashStore/EdgeStore. Postgres under PgStore; versions/<ver…>/model under FileStore.
    store.write_model(version_id, model_dir)
    # Run identity (basePath/projectName/parseFingerprint) -> the store: the `versions` columns
    # under PgStore. Replaces the API reading model/metadata.json off disk (doc 07 §3).
    _meta_path = os.path.join(model_dir, "metadata.json")
    if os.path.isfile(_meta_path):
        import json as _json
        with open(_meta_path, encoding="utf-8") as _fh:
            store.write_run_metadata(version_id, _json.load(_fh))
    # Rendered output -> versions/<ver id>/ (what every reader resolves) + the .docx list.
    documents = store.capture_output(version_id, output_dir)
    import json
    hashes = json.load(open(os.path.join(model_dir, "hashes.json"), encoding="utf-8"))
    edges = json.load(open(os.path.join(model_dir, "edges.json"), encoding="utf-8"))
    functions = json.load(open(os.path.join(model_dir, "functions.json"), encoding="utf-8"))

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
    vstore.write_manifest(commit_key, manifest)
    # AND to the store, which is what reaches Postgres (doc 09, C1). These are two different
    # stores keyed two different ways: `vstore` is the file VersionStore keyed by COMMIT,
    # `store` is the artifact store keyed by the real VERSION id. Writing only the first
    # leaves versions.pipeline_status at its last in-progress phase, and
    # pg_stores.list_versions then refuses the version as a baseline forever - so every
    # later run falls back to a full generation and reuses nothing.
    store.write_manifest(version_id, manifest)

    # End-of-run report (M3.4): a full generation regenerates everything (it becomes
    # the baseline future incrementals diff against).
    globals_ = json.load(open(os.path.join(model_dir, "globalVariables.json"), encoding="utf-8")) \
        if os.path.isfile(os.path.join(model_dir, "globalVariables.json")) else {}
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
    })
    emit_report(_report_lines, version_dir=vdir)
    # ...and to the store, so the report is readable from any node (versions.report existed
    # but was never written).
    try:
        store.write_report(version_id, "\n".join(_report_lines))
    except Exception:
        pass                           # already logged + on disk
    # C11c — last thing, so nothing downstream can still need the files.
    prune_model_files(store, version_id, model_dir, enabled=prune_model_files_after)
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
    ap.add_argument("--prune-model-files", action="store_true",
                    help="C11c: delete this version's model/*.json once the database is "
                         "confirmed to hold them. Off by default — those files are what "
                         "tools/verify_model_parity.py compares against.")
    ap.add_argument("--model-from-db", action="store_true",
                    help="C11b (opt-in): after Phase 1, re-materialize the model from Postgres "
                         "so Phase 2+ consume the STORED model. Off by default.")
    ap.add_argument("--config", default=None, help="per-project config.json to use as-is")
    ap.add_argument("--repo-url", default=None, help="clone URL (else resolved from the project record)")
    args = ap.parse_args()
    m = generate_full(args.project_id, args.branch, args.commit, _parse_scope(args.scope),
                      data_dict_id=args.data_dict_id, no_llm=args.no_llm, force=args.force,
                      version_id=args.version_id, config_path=args.config, repo_url=args.repo_url,
                      model_from_db=args.model_from_db,
                      prune_model_files_after=args.prune_model_files)
    print(f"\nversion {m['versionId']} ({m['status']}): commit {m['commit'][:10]}, "
          f"decision={m['decision']}, regenerated={m['regenerated']}, "
          f"documents={m.get('documents')}")


if __name__ == "__main__":
    main()
