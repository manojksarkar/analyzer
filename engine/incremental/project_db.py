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
    # The JSON DB is generated/instance data -> the DATA root (== project_root in production,
    # a scratch dir under ANALYZER_DATA_ROOT for an isolated run).
    return os.path.join(project_root or _paths().data_root, "api", "db", "data")


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


def _db_engine():
    """The Postgres engine when a database is configured, else None. On a Postgres
    deployment there are no api/db/data/*.json files, so the engine reads project/version
    metadata from the DB; with nothing configured it reads the JSON as before.

    "Configured" = `DATABASE_URL` **or** the `db` section of `config.local.json`
    (`core.db.is_database_configured`) — the env var alone would leave a standalone run
    reading stale JSON while the API read Postgres."""
    from core.db import is_database_configured
    if not is_database_configured():
        return None
    try:
        from core.db import get_engine
        return get_engine()
    except Exception:
        return None


def get_project(project_id: str, *, project_root: Optional[str] = None) -> Dict[str, Any]:
    """The project's DB record (repo_url, default_branch, build_config, architecture_layers),
    or {} if not found. Reads Postgres when DATABASE_URL is set, else api/db/data/projects.json."""
    eng = _db_engine()
    if eng is not None:
        from incremental.pg_stores import read_project
        return read_project(eng, project_id)
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

    Reads Postgres when DATABASE_URL is set (real version ids, only completed versions),
    else api/db/data/versions.json. A DB Version exists once a generation finished, so every
    record is a 'complete' baseline candidate."""
    eng = _db_engine()
    if eng is not None:
        from incremental.pg_stores import list_versions as _pg_list_versions
        return _pg_list_versions(eng, project_id)
    out: List[Dict[str, Any]] = []
    for v in _records(_load("versions.json", project_root)):
        if v.get("project_id") != project_id:
            continue
        commit = v.get("commit_sha") or ""
        if not commit:
            continue
        out.append({"versionId": v.get("id") or commit[:16], "commit": commit,
                    "branch": v.get("branch") or "", "status": "complete"})
    return out
