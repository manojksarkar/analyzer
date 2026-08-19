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
    """Store one output file, creating the parent rows the foreign key needs.

    version_output_files.version_id references versions.id. SQLite ignored foreign keys until
    core.db turned the pragma on, so these rows used to be inserted for a version that did not
    exist — which Postgres would have rejected outright. Creating the parent keeps the fixture
    describing a state the product can actually reach.
    """
    import datetime
    from sqlalchemy import select
    with db._engine.begin() as cx:
        if not cx.execute(select(s.projects.c.id).where(s.projects.c.id == "p1")).first():
            cx.execute(insert(s.projects).values(
                id="p1", name="P", created_at=datetime.datetime.now(datetime.timezone.utc)))
        if not cx.execute(select(s.versions.c.id).where(s.versions.c.id == version_id)).first():
            cx.execute(insert(s.versions).values(
                id=version_id, project_id="p1", version=version_id,
                created_at=datetime.datetime.now(datetime.timezone.utc)))
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


# ---------------------------------------------------------------------------
# doc 09 C0 — doc_render reads the VIEW outputs through the reader
# ---------------------------------------------------------------------------

class TestDocRenderReadsViewsFromPostgres:
    """The rendered document is the main product surface, and it still read interface
    tables / flowcharts / behaviour rows off local disk even though PG-5a had been storing
    them since the migration. That made the document depend on the machine that produced it.

    These assert the reader is genuinely preferred — a value present ONLY in Postgres has to
    come through — and that omitting the reader still reads disk exactly as before.
    """

    def _group_dir(self, tmp_path):
        d = tmp_path / "output" / "App"
        (d / "flowcharts").mkdir(parents=True)
        (d / "behaviour_diagrams").mkdir(parents=True)
        return d

    def test_interface_tables_come_from_postgres(self, tmp_path):
        from api.services import doc_render
        db = _sql_db()
        gd = self._group_dir(tmp_path)
        (gd / "interface_tables.json").write_text(json.dumps({"unitNames": {"X|onDisk": "onDisk"}}),
                                                  encoding="utf-8")
        _put(db, "v1", "App/interface_tables.json",
             json.dumps({"unitNames": {"X|fromDb": "fromDb"}}), group="App")

        rdr = OutputReader(db, "v1", tmp_path)
        got = doc_render._view_json(rdr, gd, "interface_tables.json")
        assert got["unitNames"] == {"X|fromDb": "fromDb"}, "Postgres must win over the disk copy"

    def test_falls_back_to_disk_when_not_stored(self, tmp_path):
        from api.services import doc_render
        db = _sql_db()
        gd = self._group_dir(tmp_path)
        (gd / "interface_tables.json").write_text(json.dumps({"unitNames": {"X|onDisk": "d"}}),
                                                  encoding="utf-8")
        rdr = OutputReader(db, "v1", tmp_path)          # nothing stored for v1
        got = doc_render._view_json(rdr, gd, "interface_tables.json")
        assert got["unitNames"] == {"X|onDisk": "d"}

    def test_no_reader_is_the_unchanged_disk_path(self, tmp_path):
        from api.services import doc_render
        gd = self._group_dir(tmp_path)
        (gd / "interface_tables.json").write_text(json.dumps({"unitNames": {"a": "b"}}),
                                                  encoding="utf-8")
        assert doc_render._view_json(None, gd, "interface_tables.json")["unitNames"] == {"a": "b"}
        assert doc_render._view_json(None, gd, "missing.json") is None

    def test_flowcharts_come_from_postgres(self, tmp_path):
        from api.services import doc_render
        db = _sql_db()
        gd = self._group_dir(tmp_path)
        _put(db, "v1", "App/flowcharts/Main.json",
             json.dumps([{"name": "calc", "flowchart": "digraph {a->b}"}]), group="App")
        _put(db, "v1", "App/flowcharts/_summary.json", json.dumps({"x": 1}), group="App")

        rdr = OutputReader(db, "v1", tmp_path)
        got = doc_render._load_flowcharts(gd / "flowcharts", rdr, gd)
        assert got == {"Main": {"calc": "digraph {a->b}"}}
        assert "_summary" not in got            # the summary file is not a unit

    def test_behaviour_rows_come_from_postgres(self, tmp_path):
        from api.services import doc_render
        db = _sql_db()
        gd = self._group_dir(tmp_path)
        _put(db, "v1", "App/behaviour_diagrams/_behaviour_pngs.json",
             json.dumps({"_docxRows": {"App": {"Main": [{"currentFunctionName": "calc"}]}}}),
             group="App")
        rdr = OutputReader(db, "v1", tmp_path)
        rows = doc_render._load_behavior_diagrams(gd, rdr)
        assert rows["App"]["Main"][0]["currentFunctionName"] == "calc"
