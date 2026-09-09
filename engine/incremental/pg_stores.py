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
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import func, select

# Bound on parameters in one IN (...) clause. Postgres caps a statement at 65535 bind
# parameters; 5000 keeps a wide margin and keeps each statement small enough to plan
# quickly. Only matters on projects big enough for the batching to be the point.
_MAX_IN_PARAMS = 5000

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from api.db.postgres import schema as s   # noqa: E402


# One implementation, in core/ so core.model_store can use it too (doc 10, step 4). Kept as a
# module-level name because tests and callers here already reference it.
from core.db_util import insert_ignore as _insert_ignore   # noqa: E402,F401


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
        """Single lookup. Prefer `get_many` in a loop — see its note on the N+1."""
        if fingerprint in self._pending:
            return self._pending[fingerprint]
        ri = s.reuse_index
        with self._engine.connect() as cx:
            r = cx.execute(select(ri.c.version_id, ri.c.entity_key)
                           .where((ri.c.project_id == self._project_id)
                                  & (ri.c.fingerprint == fingerprint))).first()
        return {"versionId": r.version_id, "entityKey": r.entity_key} if r else None

    def get_many(self, fingerprints: Iterable[str]) -> Dict[str, Dict[str, str]]:
        """Resolve many fingerprints in ONE round-trip (doc 09, B5a).

        `get` opens its own connection, and both hot paths called it once per entity:
        `carry_forward_from_index` per impact-set entity, and the end-of-run seeding
        loop — via `put` — for *every* fingerprinted entity in the project. On a 20k
        function codebase that is ~20k connection acquisitions per run. Cheap against a
        pooled connection, which is why it went unnoticed; ruinous under the `NullPool`
        profile B5b introduces, where each one becomes a real connect + auth.

        Returns only the fingerprints that were found, so a caller can treat a missing
        key as a miss exactly as it treated `None` before.
        """
        # dict.fromkeys dedupes while preserving order (deterministic chunking).
        fps = [f for f in dict.fromkeys(fingerprints) if f]
        found: Dict[str, Dict[str, str]] = {}
        remaining: List[str] = []
        for f in fps:
            pend = self._pending.get(f)
            if pend is not None:
                found[f] = pend
            else:
                remaining.append(f)
        if not remaining:
            return found
        ri = s.reuse_index
        with self._engine.connect() as cx:          # one connection for every chunk
            for i in range(0, len(remaining), _MAX_IN_PARAMS):
                chunk = remaining[i:i + _MAX_IN_PARAMS]
                rows = cx.execute(
                    select(ri.c.fingerprint, ri.c.version_id, ri.c.entity_key)
                    .where((ri.c.project_id == self._project_id)
                           & (ri.c.fingerprint.in_(chunk)))).all()
                for r in rows:
                    found[r.fingerprint] = {"versionId": r.version_id,
                                            "entityKey": r.entity_key}
        return found

    def put(self, fingerprint: str, version_id: str, entity_key: str, *, overwrite: bool = False) -> bool:
        """Record a pointer. First writer wins (unless overwrite). Returns True if buffered
        as a new entry. Flushed by save()."""
        if not overwrite and (fingerprint in self._pending or self.get(fingerprint) is not None):
            return False
        self._pending[fingerprint] = {"versionId": version_id, "entityKey": entity_key}
        return True

    def put_many(self, entries: Iterable[tuple], *, overwrite: bool = False) -> int:
        """Buffer many pointers using ONE existence query instead of one per entry.

        `entries` is an iterable of ``(fingerprint, version_id, entity_key)``. Returns the
        number newly buffered. Semantics match `put` exactly — first writer wins — the
        only difference is how many times the database is asked.
        """
        rows = [(fp, vid, key) for fp, vid, key in entries if fp]
        if not rows:
            return 0
        existing = {} if overwrite else self.get_many(fp for fp, _v, _k in rows)
        added = 0
        for fp, vid, key in rows:
            if not overwrite and (fp in existing or fp in self._pending):
                continue
            self._pending[fp] = {"versionId": vid, "entityKey": key}
            added += 1
        return added

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

    `versionId` is the **real DB version id** (08): the engine runs under it and the store keys
    artifacts by it; `commit` is carried alongside for resolving the checkout dir. A version
    qualifies as a baseline once its generation finished (pipeline_status 'complete'); rows
    written before the lifecycle change have a null pipeline_status and are treated so.

    Rows still in review-status 'draft' are EXCLUDED. The API reserves the version row at job
    start (so the job + entity FKs resolve during the run) and only flips it to 'in_review' on
    completion, while pipeline_status is never written — so without this filter a running job's
    OWN row is a baseline candidate at its own commit (the nearest possible match), producing a
    0-changed-file diff that regenerates nothing."""
    v = s.versions
    out: List[Dict[str, Any]] = []
    with engine.connect() as cx:
        for r in cx.execute(select(v.c.id, v.c.commit_sha, v.c.branch, v.c.pipeline_status, v.c.status)
                            .where(v.c.project_id == project_id)):
            if not r.commit_sha:
                continue
            if r.status == "draft":                  # reserved at job start; not yet generated
                continue
            if r.pipeline_status not in (None, "complete"):
                continue
            out.append({"versionId": r.id, "commit": r.commit_sha,
                        "branch": r.branch or "", "status": "complete"})
    return out
