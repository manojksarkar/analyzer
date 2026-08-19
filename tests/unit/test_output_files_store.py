"""PG-5a — model_store.persist_output_files / load_output_files round-trip.

The Phase-3 view outputs (interface tables, flowchart + unit-diagram mermaid, behaviour rows)
are stored in the version_output_files table so the API can read the views from Postgres instead
of an on-disk snapshot. Text/JSON files are stored; PNG/DOCX binaries are skipped (they stay as
files, D-14). Validated on SQLite — the shared schema builds there, same as the API parity tests.
"""
import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

# engine/ on path so `incremental.model_store` and `api.db.postgres.schema` resolve.
_ENGINE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "engine")
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from incremental import model_store as ms          # noqa: E402
from api.db.postgres import schema as s            # noqa: E402

pytestmark = pytest.mark.unit


def _fresh_engine():
    """An engine with the PARENT rows these tests' foreign keys need.

    version_output_files.version_id is a FK to versions.id. SQLite ignored foreign keys until
    core.db turned the pragma on, so these tests inserted output rows for a version that did not
    exist — a state Postgres would already have rejected. Creating the parents makes the fixture
    describe something that can actually happen.
    """
    import datetime
    from sqlalchemy import insert
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    s.metadata.create_all(eng)
    now = datetime.datetime.now(datetime.timezone.utc)
    with eng.begin() as cx:
        cx.execute(insert(s.projects), {"id": "proj-1", "name": "P", "created_at": now})
    return eng


def _ensure_version(eng, vid: str, project_id: str = "proj-1") -> None:
    """Create the parent versions row if it is not already there.

    Tolerant because some tests insert their own with specific fields; this only has to satisfy
    the foreign key for the ones that do not.
    """
    import datetime
    from sqlalchemy import insert, select
    with eng.begin() as cx:
        if cx.execute(select(s.versions.c.id).where(s.versions.c.id == vid)).first():
            return
        cx.execute(insert(s.versions), {
            "id": vid, "project_id": project_id, "version": vid,
            "created_at": datetime.datetime.now(datetime.timezone.utc)})


def _write(base: str, rel: str, content) -> None:
    p = os.path.join(base, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb" if isinstance(content, bytes) else "w",
              **({} if isinstance(content, bytes) else {"encoding": "utf-8"})) as f:
        f.write(content)


def test_persist_and_load_round_trip(tmp_path):
    out = str(tmp_path / "output")
    _write(out, "My-Sample/interface_tables.json", '{"unitNames": ["Core"]}')
    _write(out, "My-Sample/flowcharts/Core.json", '{"mermaid": "flowchart TD"}')
    _write(out, "My-Sample/unit_diagrams/Core.mmd", "sequenceDiagram")
    _write(out, "My-Sample/flowcharts/Core.png", b"\x89PNG\r\n\x1a\n")   # binary → skipped

    eng = _fresh_engine()
    _ensure_version(eng, "ver1")
    _ensure_version(eng, "v1")
    with eng.begin() as cx:
        n = ms.persist_output_files(cx, "ver1", out)
    assert n == 3                                              # 3 text files; the PNG is skipped

    with eng.connect() as cx:
        files = ms.load_output_files(cx, "ver1")
        assert set(files) == {
            "My-Sample/interface_tables.json",
            "My-Sample/flowcharts/Core.json",
            "My-Sample/unit_diagrams/Core.mmd",
        }
        assert "unitNames" in files["My-Sample/interface_tables.json"]
        assert ms.load_output_file(cx, "ver1", "My-Sample/unit_diagrams/Core.mmd") == "sequenceDiagram"
        assert ms.load_output_file(cx, "ver1", "does/not/exist.json") is None


def test_persist_is_idempotent_and_replaces(tmp_path):
    out = str(tmp_path / "output")
    _write(out, "G/interface_tables.json", '{"v": 1}')
    eng = _fresh_engine()
    _ensure_version(eng, "ver1")
    _ensure_version(eng, "v1")
    with eng.begin() as cx:
        ms.persist_output_files(cx, "ver1", out)

    # Re-persist with changed content + an added file: the prior rows for this version are replaced.
    _write(out, "G/interface_tables.json", '{"v": 2}')
    _write(out, "G/extra.json", "{}")
    with eng.begin() as cx:
        n = ms.persist_output_files(cx, "ver1", out)
    assert n == 2

    with eng.connect() as cx:
        files = ms.load_output_files(cx, "ver1")
        assert files["G/interface_tables.json"] == '{"v": 2}'
        assert "G/extra.json" in files


def test_run_metadata_round_trips_on_the_version_row():
    """metadata.json's fields live on the versions row (doc 07 §3) — the engine writes them via
    store.write_run_metadata, and the narrowed-parse guard reads parseFingerprint back."""
    import datetime
    eng = _fresh_engine()          # this test creates its own version row below
    now = datetime.datetime(2026, 8, 12, tzinfo=datetime.timezone.utc)
    with eng.begin() as cx:
        cx.execute(s.projects.insert().values(id="p1", name="P", created_at=now))
        cx.execute(s.versions.insert().values(id="ver1", project_id="p1", version="v1",
                                              created_at=now))
        ms.persist_run_metadata(cx, "ver1", {
            "basePath": "C:/repo/SampleCppProject", "projectName": "SampleCppProject",
            "parseFingerprint": "abc123", "generatedAt": "ignored"})
    with eng.connect() as cx:
        meta = ms.load_run_metadata(cx, "ver1")
    assert meta == {"basePath": "C:/repo/SampleCppProject",
                    "projectName": "SampleCppProject", "parseFingerprint": "abc123"}


def test_run_metadata_absent_version_is_empty():
    eng = _fresh_engine()
    _ensure_version(eng, "ver1")
    _ensure_version(eng, "v1")
    with eng.connect() as cx:
        assert ms.load_run_metadata(cx, "nope") == {}


def test_missing_output_dir_is_noop(tmp_path):
    eng = _fresh_engine()
    _ensure_version(eng, "ver1")
    _ensure_version(eng, "v1")
    with eng.begin() as cx:
        assert ms.persist_output_files(cx, "ver1", str(tmp_path / "nope")) == 0
    with eng.connect() as cx:
        assert ms.load_output_files(cx, "ver1") == {}
