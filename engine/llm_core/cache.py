"""Entity-level LLM result cache with composite-hash dependency tracking.

Keyed per entity on a composite hash of
  (entity source + sorted callee content hashes + cache_version)

When a function F changes, its content hash changes → F misses. When F's callee C changes, C's
content hash changes, so F's composite hash (which includes C's) changes too → F misses. But
siblings of F that do not depend on C still hit. That is implicit dependency tracking: no
separate dependency graph to maintain.

**Storage is the database** (doc 04 §13, doc 10 step 10). It used to be one JSON file per entity
under `.flowchart_cache/`, which is close to worthless on the container deployment: the
filesystem is ephemeral, so the cache dies on restart, and node A's cache is invisible to node B,
so N nodes give a ~1/N hit rate.

Losing those hits is not cheap. The gateway admits roughly one call every three seconds, so a
cold run on a 20k-function project is measured in hours — and the FULL generation path has no
other protection, since the reuse index carries descriptions forward only on the incremental
path.

Two properties the file version did not have to think about and this one does:

* **Reads are batched.** The whole (project, namespace, cache_version) scope is loaded in ONE
  query at construction, and `get()` is a dict lookup. Per-entity SELECTs would be ~20k round
  trips on a 20k-function project (doc 09 B5a) — more expensive than the LLM calls being
  avoided.
* **Writes are buffered** and flushed in chunks with ON CONFLICT DO NOTHING, so concurrent jobs
  describing the same entity cannot collide. First writer wins; the value is content-addressed,
  so they would agree anyway.

Bump ``llm.cacheVersion`` in config to invalidate everything: it is part of the key, so old rows
simply stop being referenced.

With no database configured it degrades to an in-process memo: still deduplicates within a run,
just does not survive it. That costs LLM calls on the next run and nothing else.
"""

from __future__ import annotations

import datetime
import hashlib
import logging
import threading
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# One statement per this many buffered rows on flush (mirrors core.db_util).
_FLUSH_CHUNK = 1000


class EntityCache:
    """Per-entity LLM cache with composite hash keys, stored in the database."""

    def __init__(self, project_id: str, namespace: str, cache_version: int = 1) -> None:
        self._project = project_id or ""
        self._namespace = namespace
        self._version = int(cache_version)
        self._hits = 0
        self._misses = 0
        self._writes = 0
        self._lock = threading.Lock()
        self._pending: Dict[Tuple[str, str], str] = {}
        self._loaded: Dict[Tuple[str, str], str] = {}
        self._enabled = False
        self._load()

    # ------------------------------------------------------------------
    # Key derivation
    # ------------------------------------------------------------------

    @staticmethod
    def compute_hash(entity_source: str, dependency_hashes: Optional[list] = None) -> str:
        """Compute a 16-char composite hash for an entity.

        Parameters
        ----------
        entity_source : str
            The source text (or any canonical representation) of this entity.
        dependency_hashes : list[str], optional
            Sorted list of content hashes of dependencies (e.g. callees).
        """
        h = hashlib.sha256()
        h.update((entity_source or "").encode("utf-8", errors="replace"))
        if dependency_hashes:
            for dh in sorted(dependency_hashes):
                h.update(b"|")
                h.update(dh.encode("ascii", errors="replace"))
        return h.hexdigest()[:16]

    # ------------------------------------------------------------------
    # Get/Put
    # ------------------------------------------------------------------

    def get(self, entity_id: str, content_hash: str) -> Optional[str]:
        """The cached value for *entity_id* at *content_hash*, or None.

        A dict lookup against the scope loaded once at construction — never a query.
        """
        val = self._loaded.get((entity_id, content_hash))
        with self._lock:
            if val is None:
                self._misses += 1
            else:
                self._hits += 1
        return val

    def put(self, entity_id: str, content_hash: str, value: str,
            metadata: Optional[Dict] = None) -> None:
        """Record *value* under *entity_id* keyed on *content_hash*.

        Always kept in memory, and additionally buffered for the database when one is usable.
        The in-memory half matters on its own: export-time descriptions ask for the same struct
        from several call sites in a single run, and without it a machine with no database would
        pay the LLM for each — worse than the disk cache this replaced, not merely less durable.

        `metadata` is accepted and ignored — callers pass which pass produced the value, which
        was only ever written for debugging and is not worth a column.
        """
        if not value:
            return                                          # never cache empty results
        key = (entity_id, content_hash)
        batch = None
        with self._lock:
            self._loaded[key] = value
            if self._enabled:
                self._pending[key] = value
                if len(self._pending) >= _FLUSH_CHUNK:
                    batch, self._pending = self._pending, {}    # hand it off, keep buffering
        if batch:
            self._write(batch)

    def flush(self) -> None:
        """Persist buffered entries. Safe to call repeatedly and when empty."""
        with self._lock:
            pending, self._pending = self._pending, {}
        if pending:
            self._write(pending)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> str:
        with self._lock:
            total = self._hits + self._misses
            rate = (self._hits / total * 100) if total else 0.0
            where = "db" if self._enabled else "in-memory only"
            return (f"{self._hits} hits, {self._misses} misses, "
                    f"{self._writes} writes, {rate:.0f}% hit rate [{where}]")

    def hit_count(self) -> int:
        with self._lock:
            return self._hits

    def miss_count(self) -> int:
        with self._lock:
            return self._misses

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load this scope in one query. Any failure disables the cache, never the run."""
        if not self._project:
            logger.info("LLM cache disabled: no project id in this run context.")
            return
        try:
            import sqlalchemy as sa
            from api.db.postgres import schema as s
            from core.db import get_engine, is_database_configured
            if not is_database_configured():
                logger.info("LLM cache disabled: no database configured.")
                return
            t = s.llm_description_cache
            with get_engine().connect() as cx:
                rows = cx.execute(
                    sa.select(t.c.entity_id, t.c.content_hash, t.c.value).where(
                        sa.and_(t.c.project_id == self._project,
                                t.c.namespace == self._namespace,
                                t.c.cache_version == self._version))).fetchall()
            self._loaded = {(r.entity_id, r.content_hash): r.value for r in rows}
            self._enabled = True
            logger.info("LLM cache: %d entr(y/ies) loaded for %s/%s v%d",
                        len(self._loaded), self._project, self._namespace, self._version)
        except Exception as exc:                            # unreachable DB, table not migrated
            logger.warning("LLM cache unavailable (%s); descriptions will not be cached.", exc)
            self._enabled = False

    def _write(self, pending: Dict[Tuple[str, str], str]) -> None:
        """Insert buffered rows, ignoring conflicts. A cache write must never fail a run."""
        if not pending:
            return
        try:
            from api.db.postgres import schema as s
            from core.db import get_engine
            from core.db_util import insert_ignore
            now = datetime.datetime.now(datetime.timezone.utc)
            rows: List[dict] = [
                {"project_id": self._project, "namespace": self._namespace,
                 "cache_version": self._version, "entity_id": eid, "content_hash": ch,
                 "value": val, "created_at": now}
                for (eid, ch), val in pending.items()]
            with get_engine().begin() as cx:
                insert_ignore(cx, s.llm_description_cache, rows)
            with self._lock:
                self._writes += len(rows)
            self._loaded.update(pending)                    # visible to this run immediately
        except Exception as exc:
            logger.warning("LLM cache write failed (%s); continuing without it.", exc)
