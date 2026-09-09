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
        # reuse_index.version_id became a foreign key in 0006 — a pointer to a deleted version
        # kept occupying its (project_id, fingerprint) slot and, since the index is
        # first-writer-wins, permanently blocked a live version from claiming it. The reuse
        # tests point at "v1", so it has to exist.
        cx.execute(insert(s.versions), {
            "id": "v1", "project_id": PID, "version": "v1", "commit_sha": "a" * 40,
            "created_at": datetime.datetime.now(UTC)})
    return eng


def _version(cx, vid, commit, *, pipeline_status="complete", branch="main"):
    """Create or UPDATE the version row.

    Idempotent because `_engine()` pre-creates "v1" to satisfy reuse_index's foreign key (added
    in 0006), and several tests then want that same id with their own commit and status.
    """
    row = {"id": vid, "project_id": PID, "version": vid, "commit_sha": commit, "branch": branch,
           "pipeline_status": pipeline_status, "created_at": datetime.datetime.now(UTC)}
    if cx.execute(select(s.versions.c.id).where(s.versions.c.id == vid)).first():
        cx.execute(s.versions.update().where(s.versions.c.id == vid)
                   .values({k: v for k, v in row.items() if k != "id"}))
        return
    cx.execute(insert(s.versions), row)


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


class TestDatabaseConfiguredDetection:
    """Backend selection must honour config.local.json, not just DATABASE_URL.

    The `db` section of `engine/config/config.local.json` is the configured home for the
    connection (root PROJECT_CONTEXT §6). Every backend selector used to test
    `os.environ.get("DATABASE_URL")` directly, which made the env var the ONLY way to turn
    Postgres on inside the engine: a standalone `run.py` / tools invocation fell back to the
    file store and silently persisted nothing, even with a valid `db` section. API-driven runs
    masked it, because the API resolves the DSN itself and injects DATABASE_URL into the
    subprocess — so the same deployment behaved differently depending on who started the run.
    """

    def test_env_var_alone_is_enough(self, monkeypatch):
        import core.db as coredb
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/d")
        assert coredb.is_database_configured() is True

    def test_config_db_section_alone_is_enough(self, monkeypatch):
        """The case that was broken: no env var, but config.local.json has a db section."""
        import core.db as coredb
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setattr(coredb, "_dsn_from_config",
                            lambda: "postgresql+psycopg://u:p@h:5432/d")
        assert coredb.is_database_configured() is True

    def test_nothing_configured_is_false(self, monkeypatch):
        """The compose default must NOT count — `database_url()` falls back to localhost so
        `docker compose up -d` needs no config, but 'nothing configured' must not read as
        'Postgres is on', or a DB-less dev run would try to use it."""
        import core.db as coredb
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setattr(coredb, "_dsn_from_config", lambda: None)
        assert coredb.is_database_configured() is False

    def test_unreadable_config_is_false_not_an_exception(self, monkeypatch):
        import core.db as coredb
        monkeypatch.delenv("DATABASE_URL", raising=False)

        def _boom():
            raise RuntimeError("config is malformed")

        monkeypatch.setattr(coredb, "_dsn_from_config", _boom)
        assert coredb.is_database_configured() is False

    def test_make_store_uses_the_config_section(self, monkeypatch, tmp_path):
        """The end-to-end consequence: a standalone run with only config.local.json gets a
        store, and one with no database at all is refused rather than quietly given a
        DB-less FileStore that no reader would ever look at."""
        import core.db as coredb
        from incremental.store import make_store, PgStore
        monkeypatch.delenv("DATABASE_URL", raising=False)
        coredb.reset_engine()
        try:
            monkeypatch.setattr(coredb, "_dsn_from_config", lambda: "sqlite://")
            assert isinstance(make_store("p1", workspaces_root=str(tmp_path / "a")), PgStore)
            monkeypatch.setattr(coredb, "_dsn_from_config", lambda: None)
            coredb.reset_engine()
            with pytest.raises(RuntimeError, match="no database is configured"):
                make_store("p1", workspaces_root=str(tmp_path / "b"))
        finally:
            coredb.reset_engine()


class TestPipelineLifecycleAndBaseline:
    """A finished run must remain eligible as a baseline (doc 09, C1 regression).

    `list_versions` only offers a baseline whose pipeline_status is NULL or 'complete'. That
    filter was written when the column was never written at all, so NULL meant "finished".
    Once PhaseRunner started writing progress (parsing/deriving/viewing/exporting) and nothing
    wrote a terminal state, every finished version sat at 'exporting' and was silently
    disqualified — so the next run found NO baseline, fell back to a full generation and
    reused 0%. It looks like the incremental feature is broken; it is one unwritten column.
    """

    def _finish(self, eng, vid, *, status="complete"):
        from incremental import model_store
        with eng.begin() as cx:
            model_store.persist_run_outcome(cx, vid, {
                "status": status, "decision": "full", "regenerated": 3, "reused": 0})

    def test_completing_a_run_marks_the_version_complete(self):
        eng = _engine()
        with eng.begin() as cx:
            _version(cx, "v1", "aaaaaaaaaaaa", pipeline_status="exporting")
        self._finish(eng, "v1")
        with eng.connect() as cx:
            row = cx.execute(select(s.versions.c.pipeline_status)
                             .where(s.versions.c.id == "v1")).first()
        assert row.pipeline_status == "complete"

    def test_a_finished_version_is_offered_as_a_baseline(self):
        """The end-to-end consequence — this is what actually broke."""
        eng = _engine()
        with eng.begin() as cx:
            _version(cx, "v1", "aaaaaaaaaaaa", pipeline_status="exporting")
            cx.execute(s.versions.update().where(s.versions.c.id == "v1")
                       .values(status="in_review"))
        # mid-run state: NOT a candidate
        assert pg_stores.list_versions(eng, PID) == []
        self._finish(eng, "v1")
        got = pg_stores.list_versions(eng, PID)
        assert [v["versionId"] for v in got] == ["v1"], \
            "a completed run must be selectable as the next run's baseline"

    def test_a_failed_run_is_not_a_baseline(self):
        eng = _engine()
        with eng.begin() as cx:
            _version(cx, "v1", "aaaaaaaaaaaa", pipeline_status="deriving")
            cx.execute(s.versions.update().where(s.versions.c.id == "v1")
                       .values(status="in_review"))
        self._finish(eng, "v1", status="failed")
        assert pg_stores.list_versions(eng, PID) == [], \
            "a failed run must never become a baseline"

    def test_running_status_does_not_clobber_the_phase(self):
        """The early 'running' manifest must not overwrite PhaseRunner's finer state."""
        from incremental import model_store
        eng = _engine()
        with eng.begin() as cx:
            _version(cx, "v1", "aaaaaaaaaaaa", pipeline_status="parsing")
        with eng.begin() as cx:
            model_store.persist_run_outcome(cx, "v1", {"status": "running"})
        with eng.connect() as cx:
            row = cx.execute(select(s.versions.c.pipeline_status)
                             .where(s.versions.c.id == "v1")).first()
        assert row.pipeline_status == "parsing"


class TestGlobalDescriptionSurvives:
    """A global's description must round-trip (found by verify_model_parity on a real run).

    It is LLM-generated and renders in the DOCX unit-header table, so dropping it costs real
    document content — and it was missing from _GLOBAL_PAYLOAD_FIELDS, so every global lost
    its description on the way into the database.
    """

    def test_description_is_persisted_and_loaded(self):
        from incremental import model_store
        eng = _engine()
        with eng.begin() as cx:
            _version(cx, "v1", "aaaaaaaaaaaa")
        globals_data = {
            "App|Main|g_globalResult": {
                "qualifiedName": "g_globalResult", "type": "int", "value": "0",
                "description": "Accumulated result shared across the App unit.",
                "location": {"file": "App/Main.cpp", "line": 7},
            },
        }
        with eng.begin() as cx:
            model_store.persist_globals(cx, PID, "v1", globals_data, {})
        with eng.connect() as cx:
            loaded = model_store.load_globals(cx, "v1")
        assert loaded["App|Main|g_globalResult"]["description"] == \
            "Accumulated result shared across the App unit."


class TestTheGatesRunOnADatabase:
    """The two end-to-end gates must exercise the path production takes.

    They used to set `ANALYZER_NO_DB=1` — an opt-out that existed ONLY for them — and run
    against the file store. Once the database became the default (doc 10 step 9) that tested
    code nobody runs, which is worse than no gate at all: these are the project's best
    end-to-end checks and they were green on a dead path.

    They now build a throwaway SQLite database, so the isolation that mattered (never writing a
    fake project into a real Postgres) is kept while the real path is what runs. `ANALYZER_NO_DB`
    itself is gone with step 11b — with files no longer a working backing, an opt-out that
    selects them only produces a version that looks generated and is not there.

    The move paid for itself immediately: an empty `globalVariables` read as missing and failed
    Phase 2 on every project with no global variables. See TestEmptyIsNotMissing in
    test_model_repo.py.
    """

    @pytest.mark.parametrize("tool", ["verify_incremental.py", "verify_incremental_parity.py"])
    def test_the_gate_uses_a_throwaway_database(self, tool):
        import os as _os
        root = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        src = open(_os.path.join(root, "tools", tool), encoding="utf-8").read()
        assert 'os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"' in src
        assert "_s.metadata.create_all(_eng)" in src, f"{tool} does not create its schema"
        assert "def _reserve(" in src,             (f"{tool} must reserve the versions row the API owns — without it the run cannot "
             f"reach the database and the gate tests nothing")

    def test_the_opt_out_is_gone(self):
        """ANALYZER_NO_DB must not come back by habit: it selects a backing that no longer
        works, and it is an environment variable deciding product behaviour."""
        import os as _os
        root = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        for rel in ("engine/core/db.py", "tools/verify_incremental.py",
                    "tools/verify_incremental_parity.py"):
            src = open(_os.path.join(root, rel), encoding="utf-8").read()
            assert "ANALYZER_NO_DB" not in src, f"{rel} still references the removed opt-out"


class TestRunReportAndReportText:
    """doc 09 C1 follow-up — the manifest and the end-of-run report reach the database.

    C1 put the queryable accounting on the version row, but the manifest also carries
    `warnings`, `carriedForward`, `crossVersionReused` and `documents`, which no column
    covered — so versions/<ver>/manifest.json was genuinely load-bearing, not redundant, and
    an operator on another node could not see why a run warned. `versions.report` had the
    same shape as pipeline_status did: the column existed and nothing ever wrote it.
    """

    def test_manifest_fields_without_a_column_survive(self):
        from incremental import model_store
        eng = _engine()
        with eng.begin() as cx:
            _version(cx, "v1", "aaaaaaaaaaaa")
        manifest = {"status": "complete", "decision": "incremental", "regenerated": 3,
                    "reused": 12, "warnings": ["narrowed parse fell back: new TU"],
                    "carriedForward": 12, "crossVersionReused": 2, "documents": ["a.docx"]}
        with eng.begin() as cx:
            model_store.persist_run_outcome(cx, "v1", manifest)
        with eng.connect() as cx:
            got = model_store.load_run_outcome(cx, "v1")
        assert got["warnings"] == ["narrowed parse fell back: new TU"]
        assert got["carriedForward"] == 12
        assert got["crossVersionReused"] == 2
        assert got["documents"] == ["a.docx"]

    def test_typed_columns_win_over_the_stored_manifest(self):
        """The columns can be corrected after the run; the stored blob cannot."""
        from incremental import model_store
        from sqlalchemy import update
        eng = _engine()
        with eng.begin() as cx:
            _version(cx, "v1", "aaaaaaaaaaaa")
            model_store.persist_run_outcome(cx, "v1", {"decision": "full", "reused": 0,
                                                       "warnings": ["w"]})
        with eng.begin() as cx:
            cx.execute(update(s.versions).where(s.versions.c.id == "v1").values(reused=99))
        with eng.connect() as cx:
            got = model_store.load_run_outcome(cx, "v1")
        assert got["reused"] == 99            # the column, not the blob's 0
        assert got["warnings"] == ["w"]       # and the blob still supplies the rest

    def test_report_text_is_stored(self):
        from incremental.store import PgStore
        eng = _engine()
        with eng.begin() as cx:
            _version(cx, "v1", "aaaaaaaaaaaa")
        store = PgStore(PID, eng, workspaces_root="unused")
        assert store.write_report("v1", "Functions : reused 12 (80%)") is True
        with eng.connect() as cx:
            row = cx.execute(select(s.versions.c.report)
                             .where(s.versions.c.id == "v1")).first()
        assert row.report == "Functions : reused 12 (80%)"
