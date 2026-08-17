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
    """make_store -> PgStore when a database is CONFIGURED (create_engine is lazy, no
    connect), else FileStore. This is how the engine picks its store at runtime (08 step 4).

    Both signals must be neutralised to test the FileStore branch, not just the env var:
    since the C-fix, `config.local.json`'s `db` section also counts as configured. Clearing
    only DATABASE_URL left this test reading the DEVELOPER'S OWN config — so it passed on a
    machine with no config.local.json and failed on one set up to reach a real Postgres,
    which is precisely backwards for a unit test.
    """
    from incremental.store import make_store
    import core.db as coredb
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(coredb, "_dsn_from_config", lambda: None)   # ignore any real db section
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


# ---------------------------------------------------------------------------
# doc 09 C11b — hydrate the model FROM the store
# ---------------------------------------------------------------------------

def test_hydrate_model_writes_the_stored_model_to_disk(tmp_path):
    """PgStore materializes its stored model; FileStore is a no-op (the files ARE the store)."""
    fs, ps = _both_stores(tmp_path, ["v1"])
    hashes = {"App|Main|calc|int": "aaa"}
    md = _model_dir(tmp_path, "src", hashes)

    ps.write_model("v1", md)
    target = tmp_path / "hydrated"; target.mkdir()
    assert ps.hydrate_model("v1", str(target)) is True
    assert json.loads((target / "hashes.json").read_text(encoding="utf-8")) == hashes

    # FileStore: nothing to materialize, and it must not claim it did.
    assert fs.hydrate_model("v1", str(target)) is False


def test_hydrate_model_leaves_files_the_store_does_not_back(tmp_path):
    """Only the 8 store-backed files are overwritten.

    metadata.json, tu_includes/entity_files/func_keys/override_pairs (narrowed parse, C2),
    clang_include_paths.json (machine-specific, C3) and knowledge_base.json (C4) are NOT in
    the database yet. A wipe-then-write would delete them and break the next phase, so
    hydration must overwrite in place.
    """
    _fs, ps = _both_stores(tmp_path, ["v1"])
    md = _model_dir(tmp_path, "src2", {"k": "h"})
    ps.write_model("v1", md)

    target = tmp_path / "hydrated2"; target.mkdir()
    (target / "metadata.json").write_text('{"projectName": "keep me"}', encoding="utf-8")
    (target / "tu_includes.json").write_text('{"a.cpp": []}', encoding="utf-8")

    ps.hydrate_model("v1", str(target))

    assert json.loads((target / "metadata.json").read_text(encoding="utf-8"))["projectName"] == "keep me"
    assert (target / "tu_includes.json").is_file()
    assert (target / "hashes.json").is_file()          # and the stored ones did land


# ---------------------------------------------------------------------------
# doc 09 C2 — the post-Phase-1 skeleton lives in the database
# ---------------------------------------------------------------------------

_SNAP_NAMES = ("functions.json", "hashes.json", "tu_includes.json", "entity_files.json")


def _parse_dir(tmp_path, name):
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "functions.json").write_text(json.dumps({"App|Main|calc|int": {"qualifiedName": "calc"}}),
                                      encoding="utf-8")
    (d / "hashes.json").write_text(json.dumps({"App|Main|calc|int": "aaa"}), encoding="utf-8")
    (d / "tu_includes.json").write_text(json.dumps({"App/Main.cpp": ["App/Main.h"]}),
                                        encoding="utf-8")
    # entity_files.json deliberately absent — not every run produces every artifact
    return str(d)


def test_parse_snapshot_roundtrip(tmp_path):
    _fs, ps = _both_stores(tmp_path, ["v1"])
    src = _parse_dir(tmp_path, "parse-src")

    n = ps.write_parse_snapshot("v1", src, _SNAP_NAMES)
    assert n == 3                                     # the absent file is skipped, not an error

    snap = ps.read_parse_snapshot("v1")
    assert snap["hashes.json"] == {"App|Main|calc|int": "aaa"}
    assert snap["tu_includes.json"] == {"App/Main.cpp": ["App/Main.h"]}
    assert "entity_files.json" not in snap


def test_parse_snapshot_is_idempotent(tmp_path):
    """Re-running Phase 1 (or --from-phase 1) must replace, not accumulate."""
    _fs, ps = _both_stores(tmp_path, ["v1"])
    src = _parse_dir(tmp_path, "parse-src2")
    ps.write_parse_snapshot("v1", src, _SNAP_NAMES)
    ps.write_parse_snapshot("v1", src, _SNAP_NAMES)
    snap = ps.read_parse_snapshot("v1")
    assert len(snap) == 3                             # not 6


def test_parse_snapshot_is_per_version(tmp_path):
    _fs, ps = _both_stores(tmp_path, ["v1", "v2"])
    a = _parse_dir(tmp_path, "pa")
    b = tmp_path / "pb"; b.mkdir()
    (b / "hashes.json").write_text(json.dumps({"App|Main|calc|int": "bbb"}), encoding="utf-8")

    ps.write_parse_snapshot("v1", a, _SNAP_NAMES)
    ps.write_parse_snapshot("v2", str(b), _SNAP_NAMES)

    assert ps.read_parse_snapshot("v1")["hashes.json"]["App|Main|calc|int"] == "aaa"
    assert ps.read_parse_snapshot("v2")["hashes.json"]["App|Main|calc|int"] == "bbb"


def test_file_store_has_no_parse_snapshot(tmp_path):
    """DB-less: the parse/ directory IS the snapshot, so the store reports nothing and the
    caller falls back to disk."""
    fs, _ps = _both_stores(tmp_path, ["v1"])
    assert fs.write_parse_snapshot("v1", _parse_dir(tmp_path, "pc"), _SNAP_NAMES) == 0
    assert fs.read_parse_snapshot("v1") == {}


def test_parse_snapshot_is_registered_for_deletion(tmp_path):
    """A new per-version table needs a retention story, or a deleted version leaks rows."""
    from api.db.postgres.schema import PER_VERSION_TABLES
    assert "parse_snapshots" in PER_VERSION_TABLES


def test_hydrate_parse_snapshot_restores_the_skeleton(tmp_path):
    """--from-phase 2 must be resumable from the database on any machine.

    Round-trip: store the skeleton, wipe the directory, restore it, and confirm the files
    Phase 2 reads are back with their original contents.
    """
    _fs, ps = _both_stores(tmp_path, ["v1"])
    src = _parse_dir(tmp_path, "skel-src")
    ps.write_parse_snapshot("v1", src, _SNAP_NAMES)

    target = tmp_path / "restored"            # deliberately does not exist yet
    n = ps.hydrate_parse_snapshot("v1", str(target))

    assert n == 3
    funcs = json.loads((target / "functions.json").read_text(encoding="utf-8"))
    assert funcs["App|Main|calc|int"]["qualifiedName"] == "calc"
    assert "description" not in funcs["App|Main|calc|int"]      # a SKELETON: no LLM text
    assert json.loads((target / "hashes.json").read_text(encoding="utf-8")) \
        == {"App|Main|calc|int": "aaa"}


def test_hydrate_parse_snapshot_is_a_no_op_without_one(tmp_path):
    fs, ps = _both_stores(tmp_path, ["v1"])
    assert ps.hydrate_parse_snapshot("v1", str(tmp_path / "none")) == 0   # nothing stored
    assert fs.hydrate_parse_snapshot("v1", str(tmp_path / "none2")) == 0  # DB-less store


# ---------------------------------------------------------------------------
# doc 09 — constructing a store must not touch the filesystem
# ---------------------------------------------------------------------------

def test_constructing_a_store_creates_no_directory(tmp_path):
    """A store used only for a probe — or by a run.py that turns out to have nothing to
    persist — used to leave an empty workspaces/<pid>/ behind, for a project that may not
    even exist. That is where the stray `verify-inc` directory came from."""
    root = tmp_path / "ws"
    FileStore("ghost-project", workspaces_root=str(root))
    assert not (root / "ghost-project").exists(), \
        "constructing a FileStore must have no filesystem side effect"

    PgStore("ghost-project", _pg_engine([]), workspaces_root=str(root))
    assert not (root / "ghost-project").exists(), \
        "constructing a PgStore must have no filesystem side effect"


def test_the_directory_still_appears_when_actually_used(tmp_path):
    """Laziness must not break the write paths — they create what they need."""
    root = tmp_path / "ws2"
    fs = FileStore("p", workspaces_root=str(root))
    fs.create_version("v1")
    assert (root / "p" / "versions" / "v1").is_dir()

    fs2 = FileStore("p2", workspaces_root=str(root))
    fs2.reuse_put("fp", "v1", "k"); fs2.reuse_save()      # writes cache/index.json
    assert (root / "p2" / "cache" / "index.json").is_file()


def test_default_workspaces_root_follows_the_data_root(tmp_path, monkeypatch):
    """Workspaces are generated DATA, so ANALYZER_DATA_ROOT must relocate them.

    Anchored on the code root, an isolated run still created directories inside the repo and
    left them there — which is how a temp-isolated gate littered the working tree.
    """
    import importlib
    cp = importlib.import_module("core.paths")
    from incremental.stores import default_workspaces_root
    before = cp._OVERRIDE_DATA_ROOT
    try:
        cp.set_data_root(str(tmp_path / "elsewhere"))
        assert default_workspaces_root() == os.path.join(
            str(tmp_path / "elsewhere"), "workspaces")
    finally:
        cp._OVERRIDE_DATA_ROOT = before
        cp._CACHED = None


# ---------------------------------------------------------------------------
# doc 09 IN-3 — a baseline's view outputs can be restored on another machine
# ---------------------------------------------------------------------------

def test_hydrate_output_restores_the_baseline_view_files(tmp_path):
    """Incremental flowchart carry-forward copies the baseline's <unit>.json files, and those
    are a genuine INPUT: the flowchart engine writes the DOT text into them in one process and
    the view reads them back in another to render each PNG. On a node that did not produce the
    baseline they are absent — carry-forward finds nothing, every flowchart re-renders, and
    the run still 'succeeds' with 0% flowchart reuse and no error."""
    from sqlalchemy import insert as _insert
    _fs, ps = _both_stores(tmp_path, ["v1"])
    with ps.engine.begin() as cx:
        for rel, content in (
            ("App/flowcharts/Math.json",
             json.dumps([{"name": "add", "flowchart": "digraph { A -> B }"}])),
            ("App/interface_tables.json", json.dumps({"unitNames": {"App|Math": "Math"}})),
            ("App/unit_diagrams/Math.mmd", "flowchart LR; A-->B"),
        ):
            cx.execute(_insert(s.version_output_files), {
                "version_id": "v1", "rel_path": rel, "content": content, "group_name": "App"})

    out = tmp_path / "restored-output"          # nothing on disk yet, as on a fresh node
    n = ps.hydrate_output("v1", str(out))

    assert n == 3
    fc = json.loads((out / "App" / "flowcharts" / "Math.json").read_text(encoding="utf-8"))
    assert fc[0]["flowchart"] == "digraph { A -> B }", \
        "the DOT text must survive — it is what the PNG is rendered from"
    assert (out / "App" / "unit_diagrams" / "Math.mmd").read_text(encoding="utf-8") \
        == "flowchart LR; A-->B"


def test_hydrate_output_is_a_no_op_without_stored_files(tmp_path):
    fs, ps = _both_stores(tmp_path, ["v1"])
    assert ps.hydrate_output("v1", str(tmp_path / "a")) == 0    # nothing stored
    assert fs.hydrate_output("v1", str(tmp_path / "b")) == 0    # DB-less store


def test_engine_restores_baseline_output_before_planning():
    """The wiring: the orchestrator must restore the baseline output BEFORE writing the plan
    that points at it, or the plan names a directory that does not exist."""
    import os as _os
    root = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    with open(_os.path.join(root, "engine", "incremental", "engine.py"), encoding="utf-8") as fh:
        src = fh.read()
    assert "store.hydrate_output(base_vid, _base_out)" in src
    assert src.index("hydrate_output") < src.index('"baselineVersionDir": _base_dir'), \
        "the restore must happen before the plan is written"


# ---------------------------------------------------------------------------
# doc 09 C11c — prune the model FILES once the database holds them
# ---------------------------------------------------------------------------

def test_model_is_persisted_reports_the_truth(tmp_path):
    fs, ps = _both_stores(tmp_path, ["v1"])
    assert ps.model_is_persisted("v1") is False        # nothing written yet
    ps.write_model("v1", _model_dir(tmp_path, "mp", {"App|Main|calc|int": "aaa"}))
    assert ps.model_is_persisted("v1") is True
    # A DB-less store can never confirm, so its files are never pruned — they are the
    # only copy.
    assert fs.model_is_persisted("v1") is False


def test_prune_deletes_only_when_the_database_confirms(tmp_path):
    from incremental.generate import prune_model_files
    _fs, ps = _both_stores(tmp_path, ["v1"])
    md = _model_dir(tmp_path, "prune-me", {"App|Main|calc|int": "aaa"})

    # not confirmed yet -> kept
    assert prune_model_files(ps, "v1", md, enabled=True) is False
    assert os.path.isdir(md), "files must survive when the DB cannot confirm them"

    ps.write_model("v1", md)
    assert prune_model_files(ps, "v1", md, enabled=True) is True
    assert not os.path.isdir(md)


def test_prune_is_off_by_default(tmp_path):
    """Opt-in: these files are what verify_model_parity compares against."""
    from incremental.generate import prune_model_files
    _fs, ps = _both_stores(tmp_path, ["v1"])
    md = _model_dir(tmp_path, "keep-me", {"k": "h"})
    ps.write_model("v1", md)
    assert prune_model_files(ps, "v1", md, enabled=False) is False
    assert os.path.isdir(md)


def test_prune_never_raises(tmp_path):
    from incremental.generate import prune_model_files
    _fs, ps = _both_stores(tmp_path, ["v1"])
    # absent dir, empty ids — all must be quiet no-ops, never an exception at the end of a
    # run that has already produced its documents.
    assert prune_model_files(ps, "v1", str(tmp_path / "nope"), enabled=True) is False
    assert prune_model_files(ps, "", str(tmp_path), enabled=True) is False
    assert prune_model_files(ps, "v1", "", enabled=True) is False
