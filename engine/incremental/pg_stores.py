"""Postgres-backed engine metadata stores (docs/production-redesign/07, PG-4).

Drop-in replacements for the file-based `stores.ReuseIndex` and the JSON-file
`project_db` reads, so the incremental engine can read/write its metadata in the DB.
Additive groundwork: nothing here is wired into the pipeline yet (that flip needs the
office Postgres); each piece is exercised against SQLite by tests/unit/test_pg_stores.py.

Engine-agnostic: given any SQLAlchemy engine (Postgres in production, SQLite in tests).
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

from sqlalchemy import func, insert, select

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from api.db.postgres import schema as s   # noqa: E402


def _insert_ignore(conn, table, rows: list) -> None:
    """Bulk insert, skipping rows that collide on the PK (first-writer-wins). Portable
    across Postgres and SQLite (both support ON CONFLICT DO NOTHING in SQLAlchemy 2.0)."""
    if not rows:
        return
    name = conn.engine.dialect.name
    if name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as _ins
        conn.execute(_ins(table).on_conflict_do_nothing(), rows)
    elif name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as _ins
        conn.execute(_ins(table).on_conflict_do_nothing(), rows)
    else:                                            # pragma: no cover
        conn.execute(insert(table), rows)


class PgReuseIndex:
    """Cross-version content-addressed pointer index (D3), same surface as
    `stores.ReuseIndex`: get / put / save / len. First writer of a fingerprint keeps it.

    Unlike the file index it does NOT load everything into memory: `get` queries the DB,
    `put` buffers, `save` bulk-inserts with ON CONFLICT DO NOTHING (so concurrent engine
    processes can't clobber each other's pointer)."""

    def __init__(self, engine, project_id: str):
        self._engine = engine
        self._project_id = project_id
        self._pending: Dict[str, Dict[str, str]] = {}

    def get(self, fingerprint: str) -> Optional[Dict[str, str]]:
        if fingerprint in self._pending:
            return self._pending[fingerprint]
        ri = s.reuse_index
        with self._engine.connect() as cx:
            r = cx.execute(select(ri.c.version_id, ri.c.entity_key)
                           .where((ri.c.project_id == self._project_id)
                                  & (ri.c.fingerprint == fingerprint))).first()
        return {"versionId": r.version_id, "entityKey": r.entity_key} if r else None

    def put(self, fingerprint: str, version_id: str, entity_key: str, *, overwrite: bool = False) -> bool:
        """Record a pointer. First writer wins (unless overwrite). Returns True if buffered
        as a new entry. Flushed by save()."""
        if not overwrite and (fingerprint in self._pending or self.get(fingerprint) is not None):
            return False
        self._pending[fingerprint] = {"versionId": version_id, "entityKey": entity_key}
        return True

    def save(self) -> None:
        if not self._pending:
            return
        rows = [{"project_id": self._project_id, "fingerprint": fp,
                 "version_id": v["versionId"], "entity_key": v["entityKey"]}
                for fp, v in self._pending.items()]
        with self._engine.begin() as cx:
            _insert_ignore(cx, s.reuse_index, rows)
        self._pending.clear()

    def __len__(self) -> int:
        ri = s.reuse_index
        with self._engine.connect() as cx:
            return cx.execute(select(func.count()).select_from(ri)
                              .where(ri.c.project_id == self._project_id)).scalar_one()


# ---------------------------------------------------------------------------
# project_db reads, from the DB instead of api/db/data/*.json
# ---------------------------------------------------------------------------
def read_project(engine, project_id: str) -> Dict[str, Any]:
    """The project's DB record (repo_url, default_branch, build_config, architecture_layers,
    name, ...), or {} if absent. Replaces project_db.get_project's JSON read."""
    with engine.connect() as cx:
        r = cx.execute(select(s.projects).where(s.projects.c.id == project_id)).first()
    return dict(r._mapping) if r else {}


def resolve_project_repo(engine, project_id: str) -> tuple[str, str, str]:
    """(repo_url, default_branch, token) for cloning a commit on demand."""
    p = read_project(engine, project_id)
    bc = p.get("build_config") or {}
    token = bc.get("repo_access_token") or bc.get("access_token") or ""
    return (p.get("repo_url") or "", p.get("default_branch") or "main", token)


def read_baseline_model(engine, project_id: str, base_commit: str) -> Optional[Dict[str, Any]]:
    """The baseline parts the incremental engine needs (hashes/functions/globals), read
    from the DB by the baseline's commit. None when the baseline isn't in the DB yet -
    the engine then falls back to the captured files. (PG-4 Path B.)"""
    from . import model_store
    with engine.connect() as cx:
        r = cx.execute(select(s.versions.c.id).where(
            (s.versions.c.project_id == project_id) & (s.versions.c.commit_sha == base_commit))).first()
        if not r:
            return None
        vid = r.id
        return {"hashes": model_store.load_hashes(cx, vid),
                "functions": model_store.load_functions(cx, vid),
                "globals": model_store.load_globals(cx, vid)}


def list_versions(engine, project_id: str) -> List[Dict[str, Any]]:
    """Completed versions for baseline selection: [{versionId, commit, branch, status}].

    Uses the real version id (D-3), not commit[:16]. A version qualifies as a baseline
    once its generation finished (pipeline_status 'complete'); rows written before the
    lifecycle change have a null pipeline_status and are treated as complete."""
    v = s.versions
    out: List[Dict[str, Any]] = []
    with engine.connect() as cx:
        for r in cx.execute(select(v.c.id, v.c.commit_sha, v.c.branch, v.c.pipeline_status)
                            .where(v.c.project_id == project_id)):
            if not r.commit_sha:
                continue
            if r.pipeline_status not in (None, "complete"):
                continue
            out.append({"versionId": r.id, "commit": r.commit_sha,
                        "branch": r.branch or "", "status": "complete"})
    return out
