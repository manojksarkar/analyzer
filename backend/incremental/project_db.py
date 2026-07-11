"""Read-only accessor for the API server's JSON DB (``api/db/data/*.json``).

This is the SINGLE source of truth for project + version metadata, shared by the API and
the CLI engine so both refer to the same data (no ``workspaces/<pid>/project.json``, no
separate ``workspaces/<pid>/versions.json``). The CLI only READS here — the JSON DB is held
in memory + write-through by the running server, so writing it from a separate process would
race; recording versions/documents in the DB stays the API's job.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from core.paths import paths as _paths


def _data_dir(project_root: Optional[str]) -> str:
    return os.path.join(project_root or _paths().project_root, "api", "db", "data")


def _load(name: str, project_root: Optional[str]) -> Any:
    p = os.path.join(_data_dir(project_root), name)
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _records(store: Any) -> List[dict]:
    """A DB store is either a list of dicts or a {id: dict} map."""
    if isinstance(store, dict):
        return [v for v in store.values() if isinstance(v, dict)]
    if isinstance(store, list):
        return [v for v in store if isinstance(v, dict)]
    return []


def get_project(project_id: str, *, project_root: Optional[str] = None) -> Dict[str, Any]:
    """The project's DB record (repo_url, default_branch, build_config, architecture_layers),
    or {} if not found. Replaces the old workspaces/<pid>/project.json."""
    for p in _records(_load("projects.json", project_root)):
        if p.get("id") == project_id:
            return p
    return {}


def resolve_project_repo(project_id: str, *, project_root: Optional[str] = None) -> Tuple[str, str, str]:
    """``(repo_url, default_branch, token)`` for cloning a commit on demand.
    ``("", "main", "")`` when the project/record is absent."""
    p = get_project(project_id, project_root=project_root)
    bc = p.get("build_config") or {}
    token = bc.get("repo_access_token") or bc.get("access_token") or ""
    return (p.get("repo_url") or "", p.get("default_branch") or "main", token)


def project_data_dict_id(project_id: str, *, project_root: Optional[str] = None) -> Optional[str]:
    """The project's current data-dictionary id, if the record carries one (best-effort —
    data dictionaries are optional)."""
    p = get_project(project_id, project_root=project_root)
    bc = p.get("build_config") or {}
    return p.get("currentDataDictId") or bc.get("data_dict_id") or bc.get("currentDataDictId")


def list_versions(project_id: str, *, project_root: Optional[str] = None) -> List[Dict[str, Any]]:
    """Completed versions for the project, shaped for ``baseline.select_baseline``:
    ``[{versionId: commit[:16], commit: <full sha>, branch, status: "complete"}]``.

    Reads ``api/db/data/versions.json`` — the SAME list the API uses for baselines. A DB
    Version exists only once a generation finished, so every record is a 'complete' candidate
    (its review status draft/in_review/approved is a separate concern, mapped to 'complete')."""
    out: List[Dict[str, Any]] = []
    for v in _records(_load("versions.json", project_root)):
        if v.get("project_id") != project_id:
            continue
        commit = v.get("commit_sha") or ""
        if not commit:
            continue
        out.append({"versionId": commit[:16], "commit": commit,
                    "branch": v.get("branch") or "", "status": "complete"})
    return out
