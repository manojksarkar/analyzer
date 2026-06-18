"""Onboarding stub — seed a workspace fixture for incremental testing (P1).

A stand-in for the *real* onboarding workstream (a separate engineer). It creates
the **onboarding-owned** parts of a project workspace so the incremental engine
(M1+) has something to consume, without a real registration/clone UI flow.

Creates ONLY what onboarding owns (doc 04 §4):

    workspaces/<projectId>/
      project.json          name, layers, repo ref, currentDataDictId
      repo/                 a real git clone (full — so checkout/diff/ancestry work)
      datadict/<id>.csv     seeded from config/data_dictionary.csv

It does NOT create ``cache/`` or ``versions/`` — those are owned by INCREMENTAL
and are written by the generation engine.

Usage:
    python backend/seed_workspace.py [--project-id samplecpp]
                                     [--repo-url <https url>] [--branch main] [--force]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import shutil
import sys

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_ANALYZER_ROOT = os.path.dirname(_BACKEND_DIR)
sys.path.insert(0, _BACKEND_DIR)                          # git_service
sys.path.insert(0, os.path.join(_ANALYZER_ROOT, "src"))  # core.config

import git_service                       # noqa: E402  (sibling module in backend/)
from core.config import load_config      # noqa: E402

_DEFAULT_PROJECT_ID = "samplecpp"
_DEFAULT_REPO_URL = "https://github.com/vishal9359/SampleCppProject.git"
_DEFAULT_BRANCH = "main"
_DATADICT_ID = "dd-001"


def _project_layers() -> dict:
    """The project's ``layers`` config (drops layers that define no groups, e.g.
    a placeholder Layer3) so the stored record matches the repo's real content."""
    cfg = load_config(_ANALYZER_ROOT)
    layers = cfg.get("layers") or {}
    return {name: spec for name, spec in layers.items() if (spec.get("groups") or {})}


def seed(project_id: str, repo_url: str, branch: str, force: bool) -> str:
    ws = os.path.join(_ANALYZER_ROOT, "workspaces", project_id)
    if os.path.isdir(ws):
        if not force:
            raise SystemExit(
                f"workspace already exists: {ws}\n  re-run with --force to recreate."
            )
        shutil.rmtree(ws)
    os.makedirs(ws)

    # repo/ — real full clone via the onboarding primitive (public repo: no creds).
    repo_dir = os.path.join(ws, "repo")
    print(f"cloning {repo_url} (branch {branch}) -> {repo_dir} ...")
    git_service.clone_repo(repo_url, "", "", repo_dir, branch=branch)
    head = git_service.current_commit(repo_dir)
    branches = [b["name"] for b in git_service.list_branches(repo_dir)]

    # datadict/<id>.csv — seed from the analyzer's sample data dictionary.
    datadict_dir = os.path.join(ws, "datadict")
    os.makedirs(datadict_dir)
    src_dd = os.path.join(_ANALYZER_ROOT, "config", "data_dictionary.csv")
    dst_dd = os.path.join(datadict_dir, f"{_DATADICT_ID}.csv")
    if os.path.isfile(src_dd):
        shutil.copyfile(src_dd, dst_dd)
    else:
        open(dst_dd, "w").close()  # empty placeholder

    # project.json — the onboarding record the incremental feature consumes.
    project = {
        "projectId": project_id,
        "name": "SampleCppProject",
        "repo": {"url": repo_url, "defaultBranch": branch},
        "layers": _project_layers(),
        "currentDataDictId": _DATADICT_ID,
        "createdAt": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with open(os.path.join(ws, "project.json"), "w", encoding="utf-8") as fh:
        json.dump(project, fh, indent=2)

    print(f"\nworkspace seeded: {ws}")
    print(f"  repo HEAD ({branch}): {head[:10]}")
    print(f"  branches available : {', '.join(branches)}")
    print(f"  layers             : {', '.join(project['layers'])}")
    print(f"  dataDict           : datadict/{_DATADICT_ID}.csv")
    print("  (cache/ and versions/ are created later by the incremental engine)")
    return ws


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed an onboarding workspace fixture (P1 stub).")
    ap.add_argument("--project-id", default=_DEFAULT_PROJECT_ID)
    ap.add_argument("--repo-url", default=_DEFAULT_REPO_URL)
    ap.add_argument("--branch", default=_DEFAULT_BRANCH)
    ap.add_argument("--force", action="store_true", help="recreate if it already exists")
    args = ap.parse_args()
    seed(args.project_id, args.repo_url, args.branch, args.force)


if __name__ == "__main__":
    main()
