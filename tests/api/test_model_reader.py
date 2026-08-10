"""PG-7a — ModelReader reads the model Postgres-first, with a disk fallback.

The model lives in the manifest-of-pointers tables (entities / entity_versions / content_blobs),
so the reader delegates to the engine's model_store loaders and falls back to model/*.json.
SQLite stands in for Postgres (shared schema), as in the other PG parity tests.
"""
import json
import os
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from api.services.model_reader import ModelReader
from api.db.postgres import schema as s

_ENGINE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "engine")
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)
from incremental import model_store as ms          # noqa: E402

pytestmark = pytest.mark.unit


def _sql_db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    s.metadata.create_all(eng)
    return SimpleNamespace(_engine=eng)


_FN = {
    "L1|Core|doWork": {
        "qualifiedName": "Core::doWork", "location": {"file": "a.cpp", "line": 1, "endLine": 9},
        "returnType": "void", "description": "does work", "parameters": [],
        "callsIds": [], "readsGlobalIds": [], "writesGlobalIds": [],
    }
}


def _seed_project_version(db, project_id="p1", version_id="ver1"):
    """versions/projects rows so the entity FKs resolve."""
    import datetime
    with db._engine.begin() as cx:
        cx.execute(s.projects.insert().values(id=project_id, name="P", created_at=datetime.datetime.now()))
        cx.execute(s.versions.insert().values(id=version_id, project_id=project_id, version="v1",
                                              created_at=datetime.datetime.now()))


def test_reads_model_from_postgres():
    db = _sql_db()
    _seed_project_version(db)
    with db._engine.begin() as cx:
        ms.persist_functions(cx, "p1", "ver1", _FN)

    r = ModelReader(db, "ver1", None)             # no disk dir → PG is the only source
    fns = r.load("functions")
    assert "L1|Core|doWork" in fns
    assert fns["L1|Core|doWork"]["qualifiedName"] == "Core::doWork"
    assert fns["L1|Core|doWork"]["description"] == "does work"
    assert r.has_pg() is True


def test_is_visible_false_becomes_hidden():
    """The DB carries isVisible; renderers filter on `hidden` — the reader translates."""
    db = _sql_db()
    _seed_project_version(db)
    hidden_fn = {"L1|Core|secret": {**_FN["L1|Core|doWork"], "isVisible": False}}
    with db._engine.begin() as cx:
        ms.persist_functions(cx, "p1", "ver1", {**_FN, **hidden_fn})

    fns = ModelReader(db, "ver1", None).load("functions")
    assert fns["L1|Core|secret"].get("hidden") is True
    assert fns["L1|Core|doWork"].get("hidden") is not True     # visible stays unhidden


def test_falls_back_to_disk_when_pg_empty(tmp_path):
    db = _sql_db()                                 # SQL backend, nothing stored for this version
    (tmp_path / "functions.json").write_text(json.dumps(_FN), encoding="utf-8")
    r = ModelReader(db, "verX", tmp_path)
    assert r.load("functions")["L1|Core|doWork"]["qualifiedName"] == "Core::doWork"
    assert r.has_pg() is False


def test_no_sql_engine_uses_disk(tmp_path):
    db = SimpleNamespace()                         # in-memory/json backend
    (tmp_path / "units.json").write_text('{"L1|Core": {"name": "Core"}}', encoding="utf-8")
    r = ModelReader(db, "ver1", tmp_path)
    assert r.load("units")["L1|Core"]["name"] == "Core"
    assert r.load("missing-name") == {}


def test_metadata_is_disk_only(tmp_path):
    """metadata has no DB equivalent — always read from disk, even with a live PG model."""
    db = _sql_db()
    _seed_project_version(db)
    with db._engine.begin() as cx:
        ms.persist_functions(cx, "p1", "ver1", _FN)
    (tmp_path / "metadata.json").write_text('{"projectName": "FromDisk"}', encoding="utf-8")
    r = ModelReader(db, "ver1", tmp_path)
    assert r.load("metadata")["projectName"] == "FromDisk"
    assert r.load("functions")                      # PG still serves the model
