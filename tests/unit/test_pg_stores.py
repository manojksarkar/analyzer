"""Postgres-backed engine stores (docs/production-redesign/07, PG-4).

Exercised against FK-enforcing SQLite (Postgres-strict). Covers the ReuseIndex
first-writer-wins + save/reload semantics, and the DB-backed project/version reads that
replace project_db's JSON files.
"""
import datetime
import os
import sys

import pytest
from sqlalchemy import create_engine, event, insert
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
