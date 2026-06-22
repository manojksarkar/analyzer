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
from incremental.fingerprint import recipe_fingerprint, compute_fingerprints
from incremental.edges import build_edges  # noqa: F401  (kept for symmetry / future use)


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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

    version_id = version_id or vstore.next_version_id()
    data_dict_id = data_dict_id or project.get("currentDataDictId")

    # 1. checkout
    git_ops.checkout(ws.repo_dir, commit)
    actual_commit = git_ops.current_commit(ws.repo_dir)

    # 2. resolved config -> versions/<id>/config.json + a "running" manifest so the
    #    version is queryable immediately (status flips to complete/failed below).
    vdir = vstore.create_dir(version_id, force=force)
    cfg = _resolved_config(project, project_root)
    vstore.write_config(version_id, cfg)
    vcfg_path = os.path.join(vdir, "config.json")
    vstore.write_manifest(version_id, _manifest(
        version_id, branch, actual_commit, scope, data_dict_id, recipe_fp="",
        decision="full", regenerated=0, reused=0, status="running", warnings=[]))

    # 3. run the analyzer (full) against the workspace repo (stdout/stderr inherited).
    # Clean output/ first so the version captures only its own documents.
    _rmtree_force(os.path.join(project_root, "output"))
    cmd = [sys.executable, "run.py", "--config", vcfg_path]
    cmd += scope_to_args(scope)
    if no_llm:
        cmd += ["--no-llm-summarize"]
    if data_dict_id:
        dd = ws.datadict_path(data_dict_id)
        if os.path.isfile(dd):
            cmd += ["--data-dictionary", dd]
    cmd += [ws.repo_dir]

    proc = subprocess.run(cmd, cwd=project_root, shell=(os.name == "nt"))
    if proc.returncode != 0:
        vstore.write_manifest(version_id, _manifest(
            version_id, branch, actual_commit, scope, data_dict_id, recipe_fp="",
            decision="full", regenerated=0, reused=0, status="failed",
            warnings=[f"analyzer exited {proc.returncode}"]))
        raise RuntimeError(f"analyzer run failed (exit {proc.returncode})")

    # 4. capture artifacts (model/output/documents) + hashes/edges snapshots
    model_dir = os.path.join(project_root, "model")
    output_dir = os.path.join(project_root, "output")
    documents = vstore.capture_artifacts(version_id, model_dir=model_dir, output_dir=output_dir)
    import json
    hashes = json.load(open(os.path.join(model_dir, "hashes.json"), encoding="utf-8"))
    edges = json.load(open(os.path.join(model_dir, "edges.json"), encoding="utf-8"))
    functions = json.load(open(os.path.join(model_dir, "functions.json"), encoding="utf-8"))
    hstore.write(version_id, hashes)
    estore.write(version_id, edges)

    # 5. fingerprints -> seed reuse index
    llm = cfg.get("llm") or {}
    recipe_fp = recipe_fingerprint(llm.get("defaultModel", ""),
                                   cache_version=llm.get("cacheVersion", 1))
    fps = compute_fingerprints(hashes, functions, edges, recipe_fp)
    for entity_key, fp in fps.items():
        ridx.put(fp, version_id, entity_key)  # first version that produced a fp keeps it
    ridx.save()

    # 6. manifest + index
    manifest = _manifest(version_id, branch, actual_commit, scope, data_dict_id,
                         recipe_fp=recipe_fp, decision="full",
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
        "dataDictId": data_dict_id, "recipeFingerprint": recipe_fp,
        "llmModel": llm.get("defaultModel"), "elapsedSeconds": time.perf_counter() - _t0,
        "functions": {"total": len(functions), "regenerated": len(functions), "reused": 0},
        "globals": {"total": len(globals_), "regenerated": len(globals_), "reused": 0},
        "files": {"total": files_total, "regenerated": files_total, "carried": 0},
        "documents": documents, "warnings": [],
    }), version_dir=vstore.version_dir(version_id))
    return manifest


def _manifest(version_id, branch, commit, scope, data_dict_id, *, recipe_fp,
              decision, regenerated, reused, status, warnings) -> Dict[str, Any]:
    return {
        "versionId": version_id, "branch": branch, "commit": commit,
        "scope": scope, "dataDictId": data_dict_id, "baselineVersionId": None,
        "recipeFingerprint": recipe_fp, "decision": decision,
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
    ap.add_argument("--version-id", default=None, help="use this (pre-allocated) version id")
    ap.add_argument("--no-llm", action="store_true", help="skip LLM hierarchy summarization")
    ap.add_argument("--force", action="store_true", help="overwrite the version dir if it exists")
    args = ap.parse_args()
    m = generate_full(args.project_id, args.branch, args.commit, _parse_scope(args.scope),
                      data_dict_id=args.data_dict_id, no_llm=args.no_llm, force=args.force,
                      version_id=args.version_id)
    print(f"\nversion {m['versionId']} ({m['status']}): commit {m['commit'][:10]}, "
          f"decision={m['decision']}, regenerated={m['regenerated']}, "
          f"documents={m.get('documents')}")


if __name__ == "__main__":
    main()
