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


# ---------------------------------------------------------------------------
# doc 09 B1 — rendered output goes straight into the version dir
# ---------------------------------------------------------------------------

def test_capture_output_when_run_rendered_into_the_version_dir(tmp_path):
    """The run now renders into versions/<ver>/output directly (--output-root), so
    capture's source and destination are the SAME directory.

    Without a guard, copytree onto itself either raises or duplicates the tree. The .docx
    collection into documents/ must still happen — that is what the API serves.
    """
    for store in _both_stores(tmp_path, ["v1"]):
        store.create_version("v1")
        out = os.path.join(store.artifact_dir("v1"), "output")
        os.makedirs(os.path.join(out, "App"), exist_ok=True)
        with open(os.path.join(out, "App", "software_detailed_design_App.docx"), "w") as fh:
            fh.write("x")
        with open(os.path.join(out, "App", "interface_tables.json"), "w") as fh:
            fh.write("{}")

        captured = store.capture_output("v1", out)

        assert captured == ["software_detailed_design_App.docx"]
        # the source tree is intact and NOT nested inside itself
        assert os.path.isfile(os.path.join(out, "App", "interface_tables.json"))
        assert not os.path.exists(os.path.join(out, "output"))


def test_capture_output_still_copies_from_a_separate_dir(tmp_path):
    """The pre-B1 shape (render elsewhere, then copy in) must keep working — a CLI run
    with no --output-root still writes the default output dir."""
    for store in _both_stores(tmp_path, ["v1"]):
        store.create_version("v1")
        src = tmp_path / f"elsewhere-{id(store)}" / "output" / "App"
        src.mkdir(parents=True)
        (src / "software_detailed_design_App.docx").write_text("x")

        captured = store.capture_output("v1", str(src.parent))

        assert captured == ["software_detailed_design_App.docx"]
        assert os.path.isfile(os.path.join(
            store.artifact_dir("v1"), "output", "App", "software_detailed_design_App.docx"))


def test_set_output_dir_relocates_only_output(monkeypatch, tmp_path):
    """Output relocates per run; logs and the render cache must NOT follow it.

    Relocating the whole data root would give every run a private .flowchart_cache — the
    caches are content-addressed and shared across runs on purpose, so per-version would
    mean a 0% hit rate and re-rendering every diagram.
    """
    # NB: `import core.paths as cp` does NOT work — core/__init__.py re-exports the `paths`
    # FUNCTION, which shadows the submodule attribute. Import the names directly.
    from core.paths import paths as _paths, set_data_root, set_output_dir

    set_data_root(str(tmp_path))                 # clears the cache too
    before = _paths()
    target = tmp_path / "versions" / "ver1" / "output"

    set_output_dir(str(target))
    after = _paths()

    assert after.output_dir == os.path.abspath(str(target))   # moved
    assert after.logs_dir == before.logs_dir                  # NOT moved
    assert after.cache_dir == before.cache_dir                # NOT moved
    assert after.model_dir == before.model_dir                # NOT moved (C11 handles it)
    # In-process only: no environment variable is set. Subprocesses are told via
    # `run.py --output-root`, so a run's own command line records where its output went.
    assert "ANALYZER_OUTPUT_DIR" not in os.environ
