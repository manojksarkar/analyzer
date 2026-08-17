"""doc 10 step 10 — the LLM description cache lives in the database.

`.flowchart_cache/{llm,aux}_descriptions/**.json` was one JSON file per entity on whichever
machine ran the job. On the container deployment that cache dies with the container and is
invisible to every other node, so N nodes share roughly a 1/N hit rate.

The miss is expensive in a way an ordinary cache miss is not: the gateway admits about one call
every three seconds, and the FULL generation path has no other protection — the reuse index
carries descriptions forward on the incremental path only.

What has to hold, and what each check is really defending:

  * hits and misses key on CONTENT, so changed code re-describes and unchanged code does not;
  * reads are ONE query, not one per entity — 20k round trips would cost more than the LLM
    calls being avoided (doc 09 B5a);
  * a cache failure is never a run failure — an unreachable database costs money, not output;
  * without a database it still dedupes WITHIN a run, which the disk version did for free and
    is easy to lose when moving to rows.
"""
import datetime
import os
import sys

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "engine"))

from llm_core.cache import EntityCache          # noqa: E402


class TestKeying:
    def test_hash_is_content_addressed(self):
        a = EntityCache.compute_hash("int f(){}")
        assert a == EntityCache.compute_hash("int f(){}")
        assert a != EntityCache.compute_hash("int f(){return 1;}")

    def test_dependency_hashes_are_order_independent(self):
        """Callee order is an artefact of the model, not a difference in meaning — if it keyed
        the hash, every run would miss on functions whose callee list merely reordered."""
        assert (EntityCache.compute_hash("s", ["a", "b"])
                == EntityCache.compute_hash("s", ["b", "a"]))

    def test_a_changed_dependency_changes_the_key(self):
        """The whole point of the composite hash: F misses when its callee C changes, without
        anyone maintaining a dependency graph."""
        assert (EntityCache.compute_hash("s", ["a", "b"])
                != EntityCache.compute_hash("s", ["a", "c"]))


class TestWithoutADatabase:
    """No project id -> no database. It must still behave like a cache in-process."""

    def test_it_dedupes_within_a_run(self):
        c = EntityCache("", "aux_descriptions", 1)
        assert c.get("e1", "h1") is None
        c.put("e1", "h1", "described")
        assert c.get("e1", "h1") == "described"

    def test_a_different_hash_misses(self):
        c = EntityCache("", "aux_descriptions", 1)
        c.put("e1", "h1", "described")
        assert c.get("e1", "h2") is None

    def test_empty_values_are_never_cached(self):
        """Caching a failed generation would make the failure permanent."""
        c = EntityCache("", "aux_descriptions", 1)
        c.put("e1", "h1", "")
        assert c.get("e1", "h1") is None

    def test_flush_is_safe(self):
        c = EntityCache("", "aux_descriptions", 1)
        c.put("e1", "h1", "v")
        c.flush()                                # nothing buffered for the DB; must not raise
        assert c.get("e1", "h1") == "v"

    def test_stats_say_where_it_lives(self):
        c = EntityCache("", "aux_descriptions", 1)
        c.put("e1", "h1", "v")
        c.get("e1", "h1")
        c.get("e2", "h9")
        s = c.stats()
        assert "1 hits" in s and "1 misses" in s and "in-memory only" in s


class TestFailureIsNotFatal:
    def test_an_unreachable_database_does_not_raise(self, monkeypatch):
        def _boom(*a, **k):
            raise RuntimeError("connection refused")
        monkeypatch.setattr("core.db.get_engine", _boom)
        monkeypatch.setattr("core.db.is_database_configured", lambda: True)
        c = EntityCache("p1", "llm_descriptions", 1)         # load fails -> disabled
        c.put("e1", "h1", "v")
        c.flush()
        assert c.get("e1", "h1") == "v"                      # still memoised in-process

    def test_a_failed_write_does_not_raise(self, monkeypatch):
        monkeypatch.setattr("core.db.is_database_configured", lambda: True)
        monkeypatch.setattr("core.db.get_engine", lambda: _FakeEngine({}))
        c = EntityCache("p1", "llm_descriptions", 1)
        assert c._enabled

        def _boom():
            raise RuntimeError("disk full")
        monkeypatch.setattr("core.db.get_engine", _boom)
        c.put("e1", "h1", "v")
        c.flush()                                            # write fails, silently
        assert c.get("e1", "h1") == "v"


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows
        self.statements = 0

    def execute(self, *a, **k):
        self.statements += 1
        return _FakeResult(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeEngine:
    def __init__(self, rows, sink=None):
        self._rows = list(rows.items()) if isinstance(rows, dict) else rows
        self.conn = None
        self.sink = sink

    def connect(self):
        self.conn = _FakeConn(self._rows)
        return self.conn


class _Row:
    def __init__(self, entity_id, content_hash, value):
        self.entity_id, self.content_hash, self.value = entity_id, content_hash, value


class TestReadsAreBatched:
    """One query for the whole scope, then dict lookups.

    A per-entity SELECT is ~20k connection acquisitions on a 20k-function project — slower than
    the LLM calls it is trying to save. This asserts the shape, not a timing.
    """

    def test_the_whole_scope_loads_in_one_statement(self, monkeypatch):
        rows = [_Row("e1", "h1", "one"), _Row("e2", "h2", "two")]
        eng = _FakeEngine(rows)
        monkeypatch.setattr("core.db.is_database_configured", lambda: True)
        monkeypatch.setattr("core.db.get_engine", lambda: eng)

        c = EntityCache("p1", "llm_descriptions", 1)
        assert eng.conn.statements == 1

        for _ in range(50):                                  # every read after that is free
            assert c.get("e1", "h1") == "one"
            assert c.get("e2", "h2") == "two"
            assert c.get("e3", "h3") is None
        assert eng.conn.statements == 1, "get() issued a query — reads must not hit the database"


class TestSchema:
    def test_the_table_name_marks_it_as_cache_data(self):
        """Named so it can move to a cache server later: it is the only data here that can be
        discarded without loss, since every row is recomputable."""
        from api.db.postgres import schema as s
        assert s.llm_description_cache.name.endswith("cache")

    def test_scoped_per_project_not_per_version(self):
        """Per-version rows would defeat the point — the hit that matters is the NEXT version
        finding a description an earlier one already paid for."""
        from api.db.postgres import schema as s
        cols = set(s.llm_description_cache.c.keys())
        assert "project_id" in cols
        assert "version_id" not in cols

    def test_cache_version_is_part_of_the_key(self):
        """Bumping llm.cacheVersion must invalidate by construction, leaving the old rows
        unreferenced rather than needing a delete."""
        from api.db.postgres import schema as s
        uq = [c for c in s.llm_description_cache.constraints
              if c.__class__.__name__ == "UniqueConstraint"]
        assert uq, "no unique constraint"
        assert "cache_version" in {c.name for c in uq[0].columns}

    def test_migration_0005_follows_0004(self):
        path = os.path.join(ROOT, "alembic", "versions", "0005_llm_description_cache.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        assert 'down_revision = "0004_kb_and_plans"' in src


class TestTheDiskCacheIsGone:
    def test_the_module_touches_no_files_at_all(self):
        """Asserted on code, not prose — the docstring names the old path deliberately."""
        with open(os.path.join(ROOT, "engine", "llm_core", "cache.py"), encoding="utf-8") as fh:
            body = "".join(ln for ln in fh if not ln.lstrip().startswith("#"))
        for marker in ("json.dump(", "json.load(", "os.makedirs(", "os.replace(", "open("):
            assert marker not in body, f"cache.py still does file I/O: {marker}"

    def test_enrichment_builds_it_from_the_project_id(self):
        with open(os.path.join(ROOT, "engine", "llm_enrichment.py"), encoding="utf-8") as fh:
            src = fh.read()
        assert '".flowchart_cache", "llm_descriptions"' not in src
        assert '".flowchart_cache", "aux_descriptions"' not in src
        assert 'EntityCache(_project_id() or "", "llm_descriptions"' in src

    def test_buffered_writes_are_flushed(self):
        """put() buffers; without a flush at the end of enrichment the run finishes having
        paid for descriptions it never stored — the bill arrives again next run."""
        with open(os.path.join(ROOT, "engine", "llm_enrichment.py"), encoding="utf-8") as fh:
            src = fh.read()
        assert src.count("entity_cache.flush()") >= 2, "pass 1 and pass 2 must both flush"
        assert "atexit.register(_AUX_DESC_CACHE.flush)" in src


class TestPkbDiskCacheIsGone:
    """`.flowchart_cache/pkb_*.json` mirrored data the model already holds (doc 04 §13.2)."""

    def test_the_module_is_deleted(self):
        assert not os.path.isfile(os.path.join(ROOT, "engine", "flowchart", "pkb", "cache.py"))

    def test_the_engine_builds_it_every_run(self):
        with open(os.path.join(ROOT, "engine", "flowchart", "flowchart_engine.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        assert "PkbCache(" not in src
        assert 'p.add_argument("--no-cache"' not in src
        assert 'p.add_argument("--cache-dir"' not in src

    def test_the_serializers_went_with_it(self):
        """to_dict/from_dict existed only to write that file."""
        with open(os.path.join(ROOT, "engine", "flowchart", "pkb", "builder.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        assert "def to_dict" not in src and "def from_dict" not in src
