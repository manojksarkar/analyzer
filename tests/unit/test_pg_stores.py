"""Postgres-backed engine stores (docs/production-redesign/07, PG-4).

Exercised against FK-enforcing SQLite (Postgres-strict). Covers the ReuseIndex
first-writer-wins + save/reload semantics, and the DB-backed project/version reads that
replace project_db's JSON files.
"""
import datetime
import os
import sys

import pytest
from sqlalchemy import create_engine, event, insert, select
from sqlalchemy.pool import StaticPool

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from api.db.postgres import schema as s
from incremental import pg_stores

UTC = datetime.timezone.utc
PID = "proj-1"


def _engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(eng, "connect")
    def _fk(dbapi_conn, _rec):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    s.metadata.create_all(eng)
    with eng.begin() as cx:
        cx.execute(insert(s.projects), {
            "id": PID, "name": "P", "repo_url": "https://git/x.git", "default_branch": "main",
            "build_config": {"repo_access_token": "tok"},
            "architecture_layers": [{"name": "L1"}],
            "created_at": datetime.datetime.now(UTC)})
    return eng


def _version(cx, vid, commit, *, pipeline_status="complete", branch="main"):
    cx.execute(insert(s.versions), {
        "id": vid, "project_id": PID, "version": vid, "commit_sha": commit, "branch": branch,
        "pipeline_status": pipeline_status, "created_at": datetime.datetime.now(UTC)})


class TestReuseIndex:
    def test_put_get_persist_across_instances(self):
        eng = _engine()
        idx = pg_stores.PgReuseIndex(eng, PID)
        assert idx.get("fp1") is None
        assert idx.put("fp1", "v1", "E|U|f|") is True
        idx.save()
        # a fresh instance (new connection) still sees it -> it hit the DB, not memory
        idx2 = pg_stores.PgReuseIndex(eng, PID)
        assert idx2.get("fp1") == {"versionId": "v1", "entityKey": "E|U|f|"}
        assert len(idx2) == 1

    def test_first_writer_wins(self):
        eng = _engine()
        a = pg_stores.PgReuseIndex(eng, PID)
        a.put("fp", "v1", "k1"); a.save()
        b = pg_stores.PgReuseIndex(eng, PID)
        assert b.put("fp", "v2", "k2") is False        # already present -> not re-pointed
        b.save()
        assert pg_stores.PgReuseIndex(eng, PID).get("fp")["versionId"] == "v1"

    def test_concurrent_save_does_not_clobber(self):
        """Two indexes buffering the same fingerprint: ON CONFLICT DO NOTHING keeps the
        first to land, no IntegrityError."""
        eng = _engine()
        a = pg_stores.PgReuseIndex(eng, PID); a.put("fp", "v1", "k1")
        b = pg_stores.PgReuseIndex(eng, PID)
        # b didn't see fp yet (a hasn't saved), so it buffers its own
        assert b.put("fp", "v2", "k2") is True
        a.save(); b.save()                              # b's row is ignored on conflict
        assert pg_stores.PgReuseIndex(eng, PID).get("fp")["versionId"] == "v1"


def _count_connects(eng):
    """Count connection acquisitions on `eng`. Returns a one-element list used as a
    counter, plus the listener so a test can stop counting."""
    calls = []

    @event.listens_for(eng, "engine_connect")
    def _on(_conn):
        calls.append(1)

    return calls


class TestReuseIndexBatching:
    """doc 09 B5a — the batched forms must not scale connection acquisitions with entity
    count.

    This is the guarantee, not an optimisation detail: `PgReuseIndex.get` opens its own
    connection, and both hot paths called it once per entity — the end-of-run seeding loop
    does so for EVERY function and global in the project. At ~20k functions that is ~20k
    acquisitions per run. It is nearly free against a pooled connection, which is why it
    survived unnoticed, and ruinous under the NullPool profile B5b introduces, where each
    one becomes a real connect + auth. If a future edit reintroduces the per-entity call,
    these tests fail rather than the regression showing up as a slow run on a big repo.
    """

    def test_get_many_is_one_acquisition_for_many_fingerprints(self):
        eng = _engine()
        seed = pg_stores.PgReuseIndex(eng, PID)
        seed.put_many((f"fp{i}", "v1", f"k{i}") for i in range(50))
        seed.save()

        idx = pg_stores.PgReuseIndex(eng, PID)
        calls = _count_connects(eng)
        hits = idx.get_many([f"fp{i}" for i in range(50)])
        assert len(hits) == 50
        assert hits["fp7"] == {"versionId": "v1", "entityKey": "k7"}
        assert len(calls) == 1, f"expected 1 connection acquisition, got {len(calls)}"

    def test_put_many_is_one_acquisition_for_many_entries(self):
        eng = _engine()
        idx = pg_stores.PgReuseIndex(eng, PID)
        calls = _count_connects(eng)
        added = idx.put_many((f"fp{i}", "v1", f"k{i}") for i in range(50))
        assert added == 50
        # One existence query for the whole batch (save() adds its own, after we stop counting).
        assert len(calls) == 1, f"expected 1 connection acquisition, got {len(calls)}"

    def test_batched_semantics_match_single(self):
        """First-writer-wins and the pending buffer behave identically batched."""
        eng = _engine()
        a = pg_stores.PgReuseIndex(eng, PID)
        a.put_many([("fp", "v1", "k1")]); a.save()

        b = pg_stores.PgReuseIndex(eng, PID)
        # already present -> not re-pointed, exactly as put() would report
        assert b.put_many([("fp", "v2", "k2")]) == 0
        b.save()
        assert pg_stores.PgReuseIndex(eng, PID).get("fp")["versionId"] == "v1"

    def test_get_many_merges_unsaved_pending_and_skips_misses(self):
        eng = _engine()
        idx = pg_stores.PgReuseIndex(eng, PID)
        idx.put("buffered", "v9", "kb")                 # buffered, not yet saved
        got = idx.get_many(["buffered", "absent"])
        assert got["buffered"] == {"versionId": "v9", "entityKey": "kb"}
        assert "absent" not in got                       # a miss is an absent key, not None

    def test_get_many_handles_more_than_one_chunk(self):
        """Exceeding the IN-clause bound must still be one connection, and lose nothing."""
        eng = _engine()
        seed = pg_stores.PgReuseIndex(eng, PID)
        n = pg_stores._MAX_IN_PARAMS + 25
        seed.put_many((f"f{i}", "v1", f"k{i}") for i in range(n))
        seed.save()

        idx = pg_stores.PgReuseIndex(eng, PID)
        calls = _count_connects(eng)
        hits = idx.get_many([f"f{i}" for i in range(n)])
        assert len(hits) == n                            # nothing dropped at the boundary
        assert len(calls) == 1, "chunking must reuse ONE connection"


class TestRunOutcome:
    """doc 09 C1 — the run's accounting lives on the version row, not in manifest.json.

    Every field already had a column; the file was only the transport the API read them from.
    Putting them on the row removes an engine->API file and makes the accounting readable from
    any node, not just the one that happened to run the job.
    """

    def _v(self, eng, vid="v1"):
        from incremental import model_store
        with eng.begin() as cx:
            _version(cx, vid, "abcdef123456")
        return model_store

    def test_round_trip_in_manifest_shape(self):
        eng = _engine()
        ms = self._v(eng)
        with eng.begin() as cx:
            ms.persist_run_outcome(cx, "v1", {
                "decision": "incremental", "baselineVersionId": None,
                "regenerated": 5, "reused": 9})
        with eng.connect() as cx:
            got = ms.load_run_outcome(cx, "v1")
        # keyed exactly as manifest.json was, so callers need no reshaping
        assert got["decision"] == "incremental"
        assert got["regenerated"] == 5
        assert got["reused"] == 9

    def test_partial_manifest_does_not_blank_existing_columns(self):
        """A manifest missing a key must leave that column alone — a later partial write
        must not erase accounting an earlier complete one recorded."""
        eng = _engine()
        ms = self._v(eng)
        with eng.begin() as cx:
            ms.persist_run_outcome(cx, "v1", {"decision": "full", "regenerated": 14, "reused": 0})
        with eng.begin() as cx:
            ms.persist_run_outcome(cx, "v1", {"reused": 3})          # partial
        with eng.connect() as cx:
            got = ms.load_run_outcome(cx, "v1")
        assert got["reused"] == 3                                     # updated
        assert got["decision"] == "full"                              # NOT blanked
        assert got["regenerated"] == 14                               # NOT blanked

    def test_missing_version_returns_empty(self):
        eng = _engine()
        from incremental import model_store
        with eng.connect() as cx:
            assert model_store.load_run_outcome(cx, "nope") == {}


class TestPipelineStatus:
    """doc 09 C1 — `versions.pipeline_status` gives the UI real progress instead of scraping
    `=== Phase N ===` out of the log stream.

    The writes must be best-effort: a plain CLI run has no version id, and the DB-less
    `tools/verify_incremental.py` gate runs the entire pipeline with no database at all.
    Neither is an error, and progress reporting must never be what kills a run.
    """

    def test_writes_status_to_the_version_row(self, monkeypatch):
        eng = _engine()
        with eng.begin() as cx:
            _version(cx, "v1", "abcdef123456", pipeline_status=None)
        import core.db as coredb
        coredb.reset_engine()
        monkeypatch.setattr(coredb, "get_engine", lambda *a, **k: eng)
        coredb.set_pipeline_status("parsing", version_id="v1")
        with eng.connect() as cx:
            row = cx.execute(select(s.versions.c.pipeline_status)
                             .where(s.versions.c.id == "v1")).first()
        assert row.pipeline_status == "parsing"

    def test_no_version_id_is_a_silent_no_op(self, monkeypatch):
        """A CLI run sets no ANALYZER_VERSION_ID — it must not touch the DB or raise."""
        import core.db as coredb
        monkeypatch.delenv("ANALYZER_VERSION_ID", raising=False)

        def _boom(*a, **k):
            raise AssertionError("must not reach the database without a version id")

        monkeypatch.setattr(coredb, "get_engine", _boom)
        coredb.set_pipeline_status("parsing")                   # must not raise

    def test_unreachable_database_is_swallowed(self, monkeypatch):
        """The DB-less gate runs the whole pipeline; a progress marker cannot break it."""
        import core.db as coredb

        def _boom(*a, **k):
            raise RuntimeError("no database here")

        monkeypatch.setattr(coredb, "get_engine", _boom)
        coredb.set_pipeline_status("parsing", version_id="v1")  # must not raise


class TestProjectReads:
    def test_read_project_and_repo(self):
        eng = _engine()
        p = pg_stores.read_project(eng, PID)
        assert p["name"] == "P" and p["repo_url"] == "https://git/x.git"
        assert p["build_config"] == {"repo_access_token": "tok"}      # JSON round-trips
        assert pg_stores.resolve_project_repo(eng, PID) == ("https://git/x.git", "main", "tok")

    def test_read_missing_project_is_empty(self):
        assert pg_stores.read_project(_engine(), "nope") == {}

    def test_read_baseline_model_by_commit(self):
        """The engine reads its baseline (hashes/functions/globals) from the DB by commit."""
        import json as _json
        model_dir = os.path.join(PROJECT_ROOT, "model")
        if not os.path.isfile(os.path.join(model_dir, "functions.json")):
            pytest.skip("needs a parsed model/")
        from incremental import model_store
        eng = _engine()
        with eng.begin() as cx:
            _version(cx, "base", "cafebabe0000")
            model_store.persist_model_from_dir(cx, PID, "base", model_dir)

        got = pg_stores.read_baseline_model(eng, PID, "cafebabe0000")
        assert got is not None
        assert got["hashes"] == _json.load(open(os.path.join(model_dir, "hashes.json"), encoding="utf-8"))
        assert set(got["functions"]) == set(
            _json.load(open(os.path.join(model_dir, "functions.json"), encoding="utf-8")))
        assert pg_stores.read_baseline_model(eng, PID, "no-such-commit") is None

    def test_list_versions_only_completed(self):
        eng = _engine()
        with eng.begin() as cx:
            _version(cx, "v1", "aaaaaaaa1111")
            _version(cx, "v2", "bbbbbbbb2222", pipeline_status=None)     # legacy -> treated complete
            _version(cx, "v3", "cccccccc3333", pipeline_status="parsing")  # in-flight -> excluded
            _version(cx, "v4", "")                                       # no commit -> excluded
        # versionId is the real DB id now (08), not commit[:16]; commit is carried alongside
        got = {v["commit"]: v["versionId"] for v in pg_stores.list_versions(eng, PID)}
        assert set(got) == {"aaaaaaaa1111", "bbbbbbbb2222"}    # v3 in-flight, v4 no-commit excluded
        assert got["aaaaaaaa1111"] == "v1"


class TestProjectDbDbAware:
    """project_db reads Postgres when DATABASE_URL is set, else the JSON files."""

    def test_get_project_and_list_versions_via_database_url(self, tmp_path, monkeypatch):
        import core.db as coredb
        import incremental.project_db as project_db
        dbfile = tmp_path / "pd.db"
        url = f"sqlite:///{dbfile}"
        # seed the file DB directly (schema + a project + a completed version)
        seed = coredb.get_engine(url)
        s.metadata.create_all(seed)
        with seed.begin() as cx:
            cx.execute(insert(s.projects), {
                "id": PID, "name": "P", "repo_url": "https://git/x.git", "default_branch": "main",
                "build_config": {"repo_access_token": "tok"},
                "created_at": datetime.datetime.now(UTC)})
            _version(cx, "v1", "abcdef123456")

        monkeypatch.setenv("DATABASE_URL", url)
        coredb.reset_engine()
        try:
            assert project_db.get_project(PID)["repo_url"] == "https://git/x.git"
            assert project_db.resolve_project_repo(PID) == ("https://git/x.git", "main", "tok")
            vs = project_db.list_versions(PID)
            assert vs and vs[0]["commit"] == "abcdef123456"
            assert vs[0]["versionId"] == "v1"                    # the real DB id (08)
        finally:
            coredb.reset_engine()
