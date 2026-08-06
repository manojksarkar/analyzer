"""ArtifactStore — FileStore/PgStore round-trip, parity, and the correctness fix (doc 08).

The store keys artifacts by the real `ver…` id, not `commit[:16]`. The headline test is
`test_same_commit_two_versions_distinct`: two versions that would share one commit dir today
get INDEPENDENT artifacts — the collision bug (08 §1) is gone. FileStore runs on a temp dir;
PgStore on a FK-enforcing SQLite engine (Postgres-strict), so both back-ends prove the same
behaviour without Docker.
"""
import datetime
import json
import os
import sys

import pytest
from sqlalchemy import create_engine, event, insert
from sqlalchemy.pool import StaticPool

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "engine"))

from api.db.postgres import schema as s          # noqa: E402
from incremental.store import FileStore, PgStore  # noqa: E402

PID = "proj-store"
MODEL_DIR = os.path.join(ROOT, "model")
HAS_MODEL = os.path.isfile(os.path.join(MODEL_DIR, "functions.json"))
_UTC = datetime.timezone.utc


def _pg_engine(version_ids):
    """FK-enforcing SQLite engine with the project + version rows the store writes under."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _rec):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    s.metadata.create_all(engine)
    now = datetime.datetime.now(_UTC)
    with engine.begin() as cx:
        cx.execute(insert(s.projects), {"id": PID, "name": "T", "created_at": now})
        for v in version_ids:
            cx.execute(insert(s.versions),
                       {"id": v, "project_id": PID, "version": v, "created_at": now})
    return engine


def _both_stores(tmp_path, version_ids):
    """A FileStore and a PgStore, each isolated, both set up for `version_ids`."""
    fs = FileStore(PID, workspaces_root=str(tmp_path / "fs"))
    ps = PgStore(PID, _pg_engine(version_ids), workspaces_root=str(tmp_path / "pg"))
    return [fs, ps]


def _model_dir(tmp_path, name, hashes):
    """A minimal model/ dir carrying just hashes.json (persist treats the rest as empty)."""
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "hashes.json").write_text(json.dumps(hashes), encoding="utf-8")
    return str(d)


# ---------------------------------------------------------------------------
# File-area: config / manifest / reuse index (no model needed)
# ---------------------------------------------------------------------------

def test_config_and_manifest_roundtrip(tmp_path):
    for store in _both_stores(tmp_path, ["v1"]):
        store.create_version("v1")
        assert store.read_manifest("v1") is None          # absent -> None
        store.write_config("v1", {"llm": {"enabled": False}})
        store.write_manifest("v1", {"versionId": "v1", "status": "complete"})
        assert store.read_config("v1") == {"llm": {"enabled": False}}
        assert store.read_manifest("v1")["status"] == "complete"


def test_reuse_index_first_writer_wins_and_persists(tmp_path):
    for store in _both_stores(tmp_path, ["v1", "v2"]):
        assert store.reuse_get("fp1") is None
        assert store.reuse_put("fp1", "v1", "E|u|f|") is True
        assert store.reuse_put("fp1", "v2", "E|u|f|") is False   # first writer keeps it
        store.reuse_save()
        assert store.reuse_get("fp1") == {"versionId": "v1", "entityKey": "E|u|f|"}


def test_reuse_index_survives_a_fresh_store(tmp_path):
    # FileStore reloads cache/index.json; PgStore re-queries the reuse_index table.
    fs = FileStore(PID, workspaces_root=str(tmp_path / "fs"))
    fs.reuse_put("fp", "v1", "E|u|f|"); fs.reuse_save()
    assert FileStore(PID, workspaces_root=str(tmp_path / "fs")).reuse_get("fp") \
        == {"versionId": "v1", "entityKey": "E|u|f|"}

    engine = _pg_engine(["v1"])
    ps = PgStore(PID, engine, workspaces_root=str(tmp_path / "pg"))
    ps.reuse_put("fp", "v1", "E|u|f|"); ps.reuse_save()
    assert PgStore(PID, engine, workspaces_root=str(tmp_path / "pg")).reuse_get("fp") \
        == {"versionId": "v1", "entityKey": "E|u|f|"}


# ---------------------------------------------------------------------------
# THE correctness fix: same commit, two versions -> independent artifacts
# ---------------------------------------------------------------------------

def test_same_commit_two_versions_distinct(tmp_path):
    """Two versions that today would share one commit[:16] dir/id must NOT collide."""
    a = {"f|unitA|calc|int()": "aaa", "MAX@cfg.h": "bbb"}   # exercise function + macro keys
    b = {"f|unitA|calc|int()": "ccc", "MAX@cfg.h": "ddd"}
    for store in _both_stores(tmp_path, ["ver_a", "ver_b"]):
        store.write_model("ver_a", _model_dir(tmp_path, f"{id(store)}_a", a))
        store.write_model("ver_b", _model_dir(tmp_path, f"{id(store)}_b", b))
        assert store.read_hashes("ver_a") == a
        assert store.read_hashes("ver_b") == b               # ver_a did NOT overwrite ver_b


# ---------------------------------------------------------------------------
# Real-model round-trip + FileStore/PgStore parity
# ---------------------------------------------------------------------------

def test_make_store_selects_backend(tmp_path, monkeypatch):
    """make_store -> PgStore when DATABASE_URL is set (create_engine is lazy, no connect), else
    FileStore. This is how the engine picks its store at runtime (08 step 4)."""
    from incremental.store import make_store
    import core.db as coredb
    monkeypatch.delenv("DATABASE_URL", raising=False)
    coredb.reset_engine()
    assert isinstance(make_store(PID, workspaces_root=str(tmp_path / "fs")), FileStore)
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    coredb.reset_engine()
    try:
        assert isinstance(make_store(PID, workspaces_root=str(tmp_path / "pg")), PgStore)
    finally:
        coredb.reset_engine()


@pytest.mark.skipif(not HAS_MODEL, reason="needs model/ (run the pipeline once)")
def test_real_model_roundtrip_and_parity(tmp_path):
    orig_hashes = json.load(open(os.path.join(MODEL_DIR, "hashes.json"), encoding="utf-8"))
    orig_funcs = json.load(open(os.path.join(MODEL_DIR, "functions.json"), encoding="utf-8"))

    fs, ps = _both_stores(tmp_path, ["v1"])
    for store in (fs, ps):
        store.write_model("v1", MODEL_DIR)
        assert store.read_hashes("v1") == orig_hashes                 # exact
        assert set(store.read_functions("v1")) == set(orig_funcs)     # same function set

    # parity: the two back-ends return identical data for the same input
    assert fs.read_hashes("v1") == ps.read_hashes("v1")
    assert set(fs.read_functions("v1")) == set(ps.read_functions("v1"))
