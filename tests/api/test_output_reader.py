"""PG-5b — OutputReader reads view outputs Postgres-first, with a disk fallback.

Validates the seam compare_engine (and later doc_render) uses: when the version's view files are
in version_output_files (PG-5a), they win; otherwise the on-disk snapshot is read; a backend with
no SQL engine (in-memory/json) uses disk only. SQLite stands in for Postgres (shared schema).
"""
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.pool import StaticPool

from api.services.output_reader import OutputReader
from api.db.postgres import schema as s

pytestmark = pytest.mark.unit


def _sql_db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    s.metadata.create_all(eng)
    return SimpleNamespace(_engine=eng)


def _put(db, version_id, rel, content, group=None):
    with db._engine.begin() as cx:
        cx.execute(insert(s.version_output_files).values(
            version_id=version_id, rel_path=rel, content=content, group_name=group))


def test_reads_from_postgres_when_present():
    db = _sql_db()
    _put(db, "ver1", "G/interface_tables.json", '{"unitNames": {}}', "G")
    _put(db, "ver1", "G/flowcharts/Core.json", "{}", "G")
    r = OutputReader(db, "ver1", None)          # no disk dir at all → PG is the only source
    assert r.has_pg() is True
    assert r.groups() == {"G"}
    assert r.read_text("G/interface_tables.json") == '{"unitNames": {}}'
    assert r.read_text("missing.json") is None


def test_falls_back_to_disk_when_pg_empty(tmp_path):
    db = _sql_db()                               # SQL backend, but no rows for this version
    out = tmp_path / "output" / "G"
    out.mkdir(parents=True)
    (out / "interface_tables.json").write_text('{"disk": true}', encoding="utf-8")
    r = OutputReader(db, "verX", tmp_path)
    assert r.has_pg() is False
    assert r.groups() == {"G"}
    assert json.loads(r.read_text("G/interface_tables.json"))["disk"] is True


def test_no_sql_engine_uses_disk(tmp_path):
    db = SimpleNamespace()                        # in-memory/json backend: no _engine
    out = tmp_path / "output" / "G"
    out.mkdir(parents=True)
    (out / "interface_tables.json").write_text("{}", encoding="utf-8")
    r = OutputReader(db, "ver1", tmp_path)
    assert r.groups() == {"G"}
    assert r.read_text("G/interface_tables.json") == "{}"
    assert r.read_text("G/nope.json") is None
