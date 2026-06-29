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

from core.paths import paths as _paths
from core.config import load_config
from incremental import git_ops
from incremental.stores import Workspace, VersionStore, HashStore, EdgeStore, ReuseIndex, _rmtree_force
from incremental.clone import ensure_commit_checkout, resolve_project_repo
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


def snapshot_parse_model(model_dir: str, version_dir: str) -> None:
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


def _resolved_config(project: Dict[str, Any], project_root: str) -> Dict[str, Any]:
    """Global config (merged with local) + the project's layers injected."""
    cfg = copy.deepcopy(load_config(project_root))
    cfg["layers"] = project.get("layers") or {}
    return cfg


def resolve_run_config(config_path: Optional[str], project: Dict[str, Any],
                       project_root: str, *, no_llm: bool = False) -> Dict[str, Any]:
    """The resolved per-run config. Use `config_path` if given (the API server's
    per-project config.json, carrying its architecture_layers + build_config overrides);
    otherwise build the default from the global config + the project's own layers. Applies
    the no_llm kill switch last."""
    if config_path and os.path.isfile(config_path):
        with open(config_path, "r", encoding="utf-8") as fh:
            import json as _json
            cfg = _json.load(fh)
    else:
        cfg = _resolved_config(project, project_root)
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
    project = ws.project()
    vstore = VersionStore(ws)
    hstore, estore = HashStore(vstore), EdgeStore(vstore)
    ridx = ReuseIndex(ws)

    data_dict_id = data_dict_id or project.get("currentDataDictId")

    # 1. ensure the per-commit checkout. The repo for a commit IS its version dir,
    #    workspaces/<pid>/<commit[:16]>/. The API pre-clones it for a Job; the CLI clones
    #    on demand (repo_url/token from the project record when not passed explicitly).
    repo_dir = ws.commit_dir(commit)
    if not repo_url and not os.path.isdir(os.path.join(repo_dir, ".git")):
        repo_url, _rb, repo_token = resolve_project_repo(project_id)
    ensure_commit_checkout(repo_dir, repo_url or "", branch, commit, token=(repo_token or ""))
    actual_commit = git_ops.current_commit(repo_dir)
    version_id = actual_commit[:16]          # the commit IS the version id (== dir name)

    # 2. resolved config -> <commit[:16]>/config.json + a "running" manifest so the
    #    version is queryable immediately (status flips to complete/failed below).
    vdir = vstore.create_dir(version_id)     # == repo_dir; ensured, never wiped
    cfg = resolve_run_config(config_path, project, project_root, no_llm=no_llm)
    vstore.write_config(version_id, cfg)
    vcfg_path = os.path.join(vdir, "config.json")
    vstore.write_manifest(version_id, _manifest(
        version_id, branch, actual_commit, scope, data_dict_id,
        decision="full", regenerated=0, reused=0, status="running", warnings=[]))

    # 3. run the analyzer (full) against the workspace repo (stdout/stderr inherited).
    # Clean output/ first so the version captures only its own documents.
    _rmtree_force(os.path.join(project_root, "output"))
    base_cmd = [sys.executable, "run.py", "--config", vcfg_path]
    base_cmd += scope_to_args(scope)
    if no_llm:
        base_cmd += ["--no-llm-summarize"]
    if data_dict_id:
        dd = ws.datadict_path(data_dict_id)
        if os.path.isfile(dd):
            base_cmd += ["--data-dictionary", dd]

    model_dir = os.path.join(project_root, "model")

    def _fail_full(rc):
        vstore.write_manifest(version_id, _manifest(
            version_id, branch, actual_commit, scope, data_dict_id,
            decision="full", regenerated=0, reused=0, status="failed",
            warnings=[f"analyzer exited {rc}"]))
        raise RuntimeError(f"analyzer run failed (exit {rc})")

    # Phase-split (M4.4): Phase 1 (parse) -> snapshot the blank-skeleton model into the
    # version (the baseline a future narrowed parse merges against) -> Phase 2+.
    rc = subprocess.run(base_cmd + ["--to-phase", "1", repo_dir],
                        cwd=project_root, shell=(os.name == "nt")).returncode
    if rc != 0:
        _fail_full(rc)
    snapshot_parse_model(model_dir, vdir)
    rc = subprocess.run(base_cmd + ["--from-phase", "2", repo_dir],
                        cwd=project_root, shell=(os.name == "nt")).returncode
    if rc != 0:
        _fail_full(rc)

    # 4. capture artifacts (model/output/documents) + hashes/edges snapshots
    output_dir = os.path.join(project_root, "output")
    documents = vstore.capture_artifacts(version_id, model_dir=model_dir, output_dir=output_dir)
    import json
    hashes = json.load(open(os.path.join(model_dir, "hashes.json"), encoding="utf-8"))
    edges = json.load(open(os.path.join(model_dir, "edges.json"), encoding="utf-8"))
    functions = json.load(open(os.path.join(model_dir, "functions.json"), encoding="utf-8"))
    hstore.write(version_id, hashes)
    estore.write(version_id, edges)

    # 5. fingerprints -> seed reuse index (content-only key; recipe is intentionally
    #    not folded in — an approved doc is reused regardless of model/prompt).
    llm = cfg.get("llm") or {}
    fps = compute_fingerprints(hashes, functions, edges)
    for entity_key, fp in fps.items():
        ridx.put(fp, version_id, entity_key)  # first version that produced a fp keeps it
    ridx.save()

    # 6. manifest + index
    manifest = _manifest(version_id, branch, actual_commit, scope, data_dict_id,
                         decision="full",
                         regenerated=len(fps), reused=0, status="complete", warnings=[])
    manifest["documents"] = documents
    vstore.write_manifest(version_id, manifest)

    # End-of-run report (M3.4): a full generation regenerates everything (it becomes
    # the baseline future incrementals diff against).
    globals_ = json.load(open(os.path.join(model_dir, "globalVariables.json"), encoding="utf-8")) \
        if os.path.isfile(os.path.join(model_dir, "globalVariables.json")) else {}
    files_total = len({(f.get("location") or {}).get("file") for f in functions.values()} - {None})
    stype = (scope or {}).get("type", "project")
    names = (scope or {}).get("names") or []
    from incremental.report import build_report, emit_report
    emit_report(build_report({
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
    }), version_dir=vstore.version_dir(version_id))
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
    ap.add_argument("--config", default=None, help="per-project config.json to use as-is")
    ap.add_argument("--repo-url", default=None, help="clone URL (else resolved from the project record)")
    args = ap.parse_args()
    m = generate_full(args.project_id, args.branch, args.commit, _parse_scope(args.scope),
                      data_dict_id=args.data_dict_id, no_llm=args.no_llm, force=args.force,
                      version_id=args.version_id, config_path=args.config, repo_url=args.repo_url)
    print(f"\nversion {m['versionId']} ({m['status']}): commit {m['commit'][:10]}, "
          f"decision={m['decision']}, regenerated={m['regenerated']}, "
          f"documents={m.get('documents')}")


if __name__ == "__main__":
    main()
