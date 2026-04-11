"""Entity-level LLM result cache with composite-hash dependency tracking.

Problem with the previous cache: the whole PKB cache was invalidated on any
change to any function, which made re-runs nearly as expensive as clean runs.

Solution: per-entity cache keyed on a composite hash of
  (entity source + sorted callee content hashes + cache_version)

When a function F changes, its content hash changes → F misses.
When F's callee C changes, C's content hash changes, so F's composite hash
(which includes C's hash) also changes → F misses.  But siblings of F that
don't depend on C continue to hit.  This is implicit dependency tracking:
no need to maintain a dependency graph separately.

Storage: one JSON file per entity at ``cache_dir/<prefix>/<entity_id>.json``
with a two-character prefix directory (like git object storage) to keep any
single directory manageable.  Each cache entry stores:
  - content_hash  : the composite hash used as the key
  - value         : the cached LLM result
  - metadata      : optional metadata (timestamp, model, token count)

Bump ``llm.cacheVersion`` in config to invalidate everything.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class EntityCache:
    """Per-entity cache with composite hash keys."""

    def __init__(self, cache_dir: str, cache_version: int = 1) -> None:
        self._base = cache_dir
        self._version = int(cache_version)
        self._hits = 0
        self._misses = 0
        self._writes = 0
        self._lock = threading.Lock()
        os.makedirs(self._base, exist_ok=True)

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

        Returns
        -------
        str
            A 16-char hex digest suitable for use as a cache key.
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
        """Return the cached value for *entity_id* if hash matches, else None."""
        path = self._path_for(entity_id)
        if not os.path.isfile(path):
            with self._lock:
                self._misses += 1
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            with self._lock:
                self._misses += 1
            return None

        if data.get("version") != self._version:
            with self._lock:
                self._misses += 1
            return None
        if data.get("content_hash") != content_hash:
            with self._lock:
                self._misses += 1
            return None

        with self._lock:
            self._hits += 1
        return data.get("value")

    def put(
        self,
        entity_id: str,
        content_hash: str,
        value: str,
        metadata: Optional[Dict] = None,
    ) -> None:
        """Store *value* under *entity_id* keyed on *content_hash*."""
        if not value:
            return  # never cache empty results
        path = self._path_for(entity_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = {
            "version": self._version,
            "entity_id": entity_id,
            "content_hash": content_hash,
            "value": value,
            "metadata": metadata or {},
            "ts": time.time(),
        }
        try:
            # Atomic write: tmp + replace
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, path)
            with self._lock:
                self._writes += 1
        except OSError as exc:
            logger.warning("Failed to write cache %s: %s", path, exc)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> str:
        """Return a human-readable stats string."""
        with self._lock:
            total = self._hits + self._misses
            rate = (self._hits / total * 100) if total else 0.0
            return (
                f"{self._hits} hits, {self._misses} misses, "
                f"{self._writes} writes, {rate:.0f}% hit rate"
            )

    def hit_count(self) -> int:
        with self._lock:
            return self._hits

    def miss_count(self) -> int:
        with self._lock:
            return self._misses

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _path_for(self, entity_id: str) -> str:
        """Compute filesystem path for an entity_id.

        Uses a 2-char prefix directory (like git's object storage) to keep
        any single directory from growing unbounded.
        """
        # Sanitize entity_id — replace filesystem-hostile chars
        safe = "".join(c if c.isalnum() or c in "_-." else "_" for c in entity_id)
        if len(safe) < 2:
            safe = safe + "_" * (2 - len(safe))
        prefix = safe[:2]
        return os.path.join(self._base, prefix, f"{safe}.json")
