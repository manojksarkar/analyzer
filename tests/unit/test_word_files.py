"""Word file updates — the engine side (docs/design/WORD_FILE_UPDATES.md).

* **The rule** (§4.3, `review/word_files.states`): a document's Word file is out of date when a
  correction it prints was saved after the file was written, a layer added since made its
  component stale, or a corrected picture of its component is still being drawn. Not the
  derivation stamps: a save re-derives and stamps SWE.4 rows, and the stamps then called an old
  SWE.4 file current -- Approve froze it.
* **When a file was written** (`record_word_files`): the run's start, for the .docx it wrote.
* **A run stores only what it rebuilt** (S4a): a save made while a re-export of another component
  ran was reverted by the capture, in every component.
* **One picture is one component's** (S0b), the stale layer is recorded (0017), the .docx is
  written whole (SD), and migration 0017 applies.
"""
import datetime
import json
import os
import sys

import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from api.db.postgres import schema as s
from review import export_guard as g, slot
from review import word_files as wf

UTC = datetime.timezone.utc
T0 = datetime.datetime(2026, 1, 1, tzinfo=UTC)
T1 = datetime.datetime(2026, 1, 2, tzinfo=UTC)
T2 = datetime.datetime(2026, 1, 3, tzinfo=UTC)
A, B = "Layer1.Comp-A", "Layer1.Comp-B"


@pytest.fixture
def engine():
    eng = sa.create_engine("sqlite://")
    s.metadata.create_all(eng)
    with eng.begin() as cx:
        now = datetime.datetime.now(UTC)
        cx.execute(sa.insert(s.projects).values(id="p", name="p", created_at=now))
        cx.execute(sa.insert(s.versions).values(id="v1", project_id="p", version="v1",
                                                created_at=now))
    return eng


@pytest.fixture
def conn(engine):
    with engine.begin() as cx:
        yield cx


def _correct(conn, when, key, kind="description", orphaned=False):
    conn.execute(sa.insert(s.text_overrides).values(
        version_id="v1", slot_kind=kind, slot_key=key, llm_text="llm", human_text="human",
        is_orphaned=orphaned, updated_at=when))


def _fid(comp, name="f"):
    return "%s|Unit|%s|" % (comp, name)


def _record(conn, comp, views, doc_types):
    """A stored derivation record for `comp`'s output directory, saying which documents print
    which views (what `_swe3_built` reads)."""
    rec = {"views": {v: {"at": T0.isoformat(), "components": [g.component_id(comp)],
                         "docTypes": list(doc_types)} for v in views}}
    conn.execute(sa.insert(s.version_output_files).values(
        version_id="v1", rel_path="%s/%s" % (comp, g.DERIVATION_RECORD), group_name=comp,
        content=json.dumps(rec)))


def _files(*specs):
    return [wf.WordFile("%s-%s" % (c, p), c, p, w) for c, p, w in specs]


def _state(conn, *specs, stale=None):
    return wf.states(conn, "v1", _files(*specs), stale_layers=stale)


class TestCorrections:
    def test_a_correction_saved_after_the_file_puts_it_out_of_date(self, conn):
        _correct(conn, T1, _fid(A))
        st = _state(conn, (A, "SWE.3", T0), (A, "SWE.4", T2))
        assert st[A + "-SWE.3"] == wf.FileState(True, ("corrections",), 1, 0, None)
        assert not st[A + "-SWE.4"].out_of_date, "written after the correction: it has it"

    def test_the_stamps_do_not_vouch_for_a_file(self, conn):
        """THE bug: a save re-derives its component's SWE.4 rows and stamps them, so the guard
        said the SWE.4 document was current -- while its .docx was written before the save."""
        _correct(conn, T1, _fid(A))
        g.stamp_view_derivations(conn, "v1", [("testSpecs", A), ("utExport", A)], T2)
        assert not g.staleness(conn, "v1", "swe4", component=A).is_stale    # the old answer
        assert _state(conn, (A, "SWE.4", T0))[A + "-SWE.4"].out_of_date     # the file's

    def test_an_orphan_or_another_component_does_not_count(self, conn):
        _correct(conn, T1, _fid(A), orphaned=True)
        _correct(conn, T1, _fid(B))
        assert not _state(conn, (A, "SWE.3", T0))[A + "-SWE.3"].out_of_date

    def test_each_correction_is_counted(self, conn):
        _correct(conn, T1, _fid(A, "f"))
        _correct(conn, T1, _fid(A, "g"))
        _correct(conn, T1, _fid(A, "f"), kind="inputName")
        assert _state(conn, (A, "SWE.3", T0))[A + "-SWE.3"].corrections == 3

    def test_a_label_reaches_swe3_only_where_it_prints_flowcharts(self, conn):
        _correct(conn, T1, slot.for_node(_fid(A), "n1"), kind="nodeLabel")
        _record(conn, A, ("interfaceTables", "flowcharts"), ("swe4",))      # flowcharts: SWE.4's
        st = _state(conn, (A, "SWE.3", T0), (A, "SWE.4", T0))
        assert not st[A + "-SWE.3"].out_of_date
        assert st[A + "-SWE.4"].why == ("corrections",)

    def test_a_label_reaches_swe3_too_where_it_does(self, conn):
        _correct(conn, T1, slot.for_node(_fid(A), "n1"), kind="nodeLabel")
        _record(conn, A, ("interfaceTables", "flowcharts"), ("swe3", "swe4"))
        assert _state(conn, (A, "SWE.3", T0))[A + "-SWE.3"].out_of_date

    def test_a_struct_description_is_its_showing_components(self, conn):
        """Keyed by its type, it named no component -- and put every one out of date."""
        _correct(conn, T1, "Pump", kind="structDescription")
        conn.execute(sa.insert(s.version_output_files).values(
            version_id="v1", rel_path="%s/unit_headers.json" % A, group_name=A,
            content=json.dumps({"%s|Core" % A: [{"declaration": "class Pump", "typeKey": "Pump"}],
                                "%s|Io" % B: [{"declaration": "int x", "typeKey": None}]})))
        st = _state(conn, (A, "SWE.3", T0), (B, "SWE.3", T0), (A, "SWE.4", T0))
        assert st[A + "-SWE.3"].out_of_date and not st[B + "-SWE.3"].out_of_date
        assert not st[A + "-SWE.4"].out_of_date, "SWE.4 prints no unit header table"

    def test_a_struct_description_no_table_can_place_counts_everywhere(self, conn):
        _correct(conn, T1, "Pump", kind="structDescription")
        st = _state(conn, (A, "SWE.3", T0), (B, "SWE.3", T0))
        assert st[A + "-SWE.3"].out_of_date and st[B + "-SWE.3"].out_of_date

    def test_a_file_with_no_time_falls_back_to_the_stamps(self, conn):
        _correct(conn, T1, _fid(A))
        assert _state(conn, (A, "SWE.3", None))[A + "-SWE.3"].out_of_date   # never derived
        g.stamp_view_derivations(conn, "v1", [("interfaceTables", A)], T2)
        assert not _state(conn, (A, "SWE.3", None))[A + "-SWE.3"].out_of_date


class TestTheOtherReasons:
    def test_a_layer_added_since(self, conn):
        st = _state(conn, (A, "SWE.3", T2), (B, "SWE.3", T2), stale={A: ["HAL_LAYER"]})
        assert st[A + "-SWE.3"] == wf.FileState(True, ("layerAdded",), 0, 0, "HAL_LAYER")
        assert not st[B + "-SWE.3"].out_of_date

    def test_a_layer_not_recorded_still_counts(self, conn):
        st = _state(conn, (A, "SWE.4", T2), stale={A: []})
        assert st[A + "-SWE.4"].why == ("layerAdded",) and st[A + "-SWE.4"].layer is None

    def test_a_picture_being_drawn_is_its_own_component_s(self, conn):
        """S0b: one pending picture put every component behind."""
        from review import render_queue
        render_queue.enqueue(conn, "v1", _fid(A), "f.png", now=T1)
        _record(conn, A, ("flowcharts",), ("swe3", "swe4"))
        st = _state(conn, (A, "SWE.3", T2), (B, "SWE.3", T2), (A, "SWE.4", T2))
        assert st[A + "-SWE.3"] == wf.FileState(True, ("pictures",), 0, 1, None)
        assert not st[B + "-SWE.3"].out_of_date
        assert not st[A + "-SWE.4"].out_of_date, "SWE.4 prints no flowchart picture"
        assert render_queue.counts(conn, "v1", A).pending == 1
        assert render_queue.counts(conn, "v1", B).pending == 0
        assert render_queue.counts(conn, "v1").pending == 1

    def test_the_guard_counts_a_component_s_pictures_only(self, conn):
        from review import render_queue
        render_queue.enqueue(conn, "v1", _fid(A), "f.png", now=T1)
        _correct(conn, T0, _fid(B))
        g.stamp_view_derivations(conn, "v1", [(v, B) for v in ("interfaceTables", "testSpecs")], T1)
        assert not g.staleness(conn, "v1", component=B).is_stale
        assert g.stale_components(conn, "v1", None, [A, B]) == []      # A has no correction

    def test_reasons_add_up(self, conn):
        _correct(conn, T1, _fid(A))
        st = _state(conn, (A, "SWE.3", T0), stale={A: ["L2"]})
        assert st[A + "-SWE.3"].why == ("corrections", "layerAdded")


class TestWhenAFileWasWritten:
    def _docx(self, out, comp, process, mtime):
        prefix = wf.DOCX_PREFIX[process]
        p = out / comp / ("%s_%s.docx" % (prefix, comp))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"PK")
        os.utime(p, (mtime.timestamp(), mtime.timestamp()))
        return p

    def _doc(self, conn, did, comp, process):
        conn.execute(sa.insert(s.documents).values(id=did, project_id="p", version_id="v1",
                                                   process=process, name=comp, component=comp,
                                                   status="in_review"))

    def test_the_run_s_files_get_its_start(self, conn, tmp_path):
        self._docx(tmp_path, A, "SWE.3", T2)
        self._docx(tmp_path, A, "SWE.4", T2)
        self._docx(tmp_path, B, "SWE.3", T0)        # not written by this run
        for did, comp, proc in (("a3", A, "SWE.3"), ("a4", A, "SWE.4"), ("b3", B, "SWE.3")):
            self._doc(conn, did, comp, proc)
        assert wf.record_word_files(conn, "v1", str(tmp_path), T1) == 2
        at = {r.id: r.word_file_at for r in conn.execute(sa.select(s.documents))}
        assert g._aware(at["a3"]) == T1 and g._aware(at["a4"]) == T1 and at["b3"] is None

    def test_only_the_components_it_rebuilt(self, conn, tmp_path):
        self._docx(tmp_path, A, "SWE.3", T2)
        self._docx(tmp_path, B, "SWE.3", T2)
        assert wf.written_by(str(tmp_path), T1, [B]) == [(B, "SWE.3")]

    def test_the_file_time_stands_in(self, tmp_path):
        self._docx(tmp_path, A, "SWE.4", T1)
        assert wf.file_written_at(str(tmp_path), A, "SWE.4") == T1
        assert wf.file_written_at(str(tmp_path), A, "SWE.3") is None


class TestARunStoresOnlyWhatItRebuilt:
    """S4a. A re-export restores every stored row to disk at its start; its capture REPLACED every
    row of the version at its end -- so a correction saved meanwhile in another component was
    reverted, in its page and its stamps alike."""

    def _put(self, conn, rel, content):
        from review.rerender import write_output_row
        write_output_row(conn, "v1", rel, content)

    def _disk(self, out, rel, content):
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def test_a_save_in_another_component_survives(self, engine, tmp_path, monkeypatch):
        from incremental.store import PgStore
        monkeypatch.setattr("incremental.store._draw_pending_pictures", lambda *a, **k: None)
        out = tmp_path / "out"
        rec = lambda at: json.dumps({"views": {"interfaceTables": {
            "at": at.isoformat(), "components": [], "docTypes": ["swe3"]}}})
        with engine.begin() as cx:
            for comp in (A, B):
                self._put(cx, "%s/interface_tables.json" % comp, '"old %s"' % comp)
            for did, comp in (("a3", A), ("b3", B)):
                cx.execute(sa.insert(s.documents).values(
                    id=did, project_id="p", version_id="v1", process="SWE.3", name=comp,
                    component=comp, status="in_review", word_file_at=T0))
        # The run of A: what it restored for B at its start, and A rebuilt.
        self._disk(out, "%s/interface_tables.json" % A, '"rebuilt A"')
        self._disk(out, "%s/interface_tables.json" % B, '"old %s"' % B)
        docx = out / A / ("software_detailed_design_%s.docx" % A)
        docx.write_bytes(b"PK")
        since = datetime.datetime.now(UTC) - datetime.timedelta(seconds=5)
        # Meanwhile: a correction in B (patched row) and one in A, after the run started.
        with engine.begin() as cx:
            self._put(cx, "%s/interface_tables.json" % B, '"corrected B"')
            _correct(cx, datetime.datetime.now(UTC), _fid(B))
            _correct(cx, datetime.datetime.now(UTC), _fid(A))
        PgStore("p", engine, workspaces_root=str(tmp_path / "ws")).capture_output(
            "v1", str(out), components=[A], since=since)
        with engine.connect() as cx:
            rows = {r.rel_path: r.content for r in cx.execute(sa.select(s.version_output_files))}
            at = {r.id: g._aware(r.word_file_at) for r in cx.execute(sa.select(s.documents))}
            st = wf.states(cx, "v1", [wf.WordFile("a3", A, "SWE.3", at["a3"]),
                                      wf.WordFile("b3", B, "SWE.3", at["b3"])])
        assert rows["%s/interface_tables.json" % B] == '"corrected B"', "the save was reverted"
        assert rows["%s/interface_tables.json" % A] == '"rebuilt A"'
        assert at["a3"] == since and at["b3"] == T0
        assert st["a3"].out_of_date, "saved while A was rebuilt: not in A's file"
        assert st["b3"].out_of_date, "B's file was never rewritten"

    def test_the_stamps_come_from_the_stored_records(self, engine, tmp_path, monkeypatch):
        """B's record, with the mark of a save made while A was rebuilt, keeps its stamp."""
        from incremental.store import PgStore
        monkeypatch.setattr("incremental.store._draw_pending_pictures", lambda *a, **k: None)
        out = tmp_path / "out"
        with engine.begin() as cx:
            for comp in (A, B):
                self._put(cx, "%s/%s" % (comp, g.DERIVATION_RECORD), g.record_text({"views": {
                    "testSpecs": {"at": T0.isoformat(), "components": [g.component_id(comp)],
                                  "docTypes": ["swe4"]}}}))
            g.stamp_saved(cx, "v1", [("testSpecs", B)], T2)      # a save in B, mid-run
        g.record_derivation(str(out / A), ["testSpecs"], [A], T1, doc_types={"testSpecs": ["swe4"]})
        PgStore("p", engine, workspaces_root=str(tmp_path / "ws")).capture_output(
            "v1", str(out), components=[A], since=T1)
        with engine.connect() as cx:
            stamps = g._derivation_stamps(cx, "v1")
        assert stamps[("testSpecs", g.component_id(A))] == T1
        assert stamps[("testSpecs", g.component_id(B))] == T2

    def test_reexport_export_and_resume_say_what_they_rebuilt(self):
        """`_render_version` is what all three run; by component, the capture is told which."""
        src = open(os.path.join(PROJECT_ROOT, "analyzer.py"), encoding="utf-8").read()
        body = src[src.index("def _render_version("):src.index("def _with_current_secrets(")]
        assert "components=rebuilt, since=since" in body
        assert body.index("since = ") < body.index('_script(os.path.join(_ROOT, "engine", "run.py")')

    def test_a_generation_still_stores_everything(self, engine, tmp_path):
        from core.model_store import persist_output_files
        out = tmp_path / "out"
        self._disk(out, "%s/x.json" % A, "1")
        with engine.begin() as cx:
            self._put(cx, "%s/y.json" % B, "2")
            assert persist_output_files(cx, "v1", str(out)) == 1
            assert [r.rel_path for r in cx.execute(sa.select(s.version_output_files))] == \
                ["%s/x.json" % A]


class TestTheStaleLayerIsRecorded:
    def test_stale_carries_its_layers(self, engine, monkeypatch):
        from core import version_run as vr
        monkeypatch.setattr(vr, "_engine", lambda: engine)
        vr.mark_components("v1", [A], "stale", layers=["HAL_LAYER"])
        vr.mark_components("v1", [B], "generated")
        with engine.connect() as cx:
            rows = {r.component: r for r in cx.execute(sa.select(s.version_components))}
        assert rows[A].state == "stale" and rows[A].stale_layers == ["HAL_LAYER"]
        assert rows[B].state == "generated" and rows[B].stale_layers is None

    def test_a_database_without_the_column_still_records_the_state(self, monkeypatch):
        """`setup` not run yet after the pull: the stale mark goes in without its layers."""
        from core import version_run as vr
        eng = sa.create_engine("sqlite://")
        md = sa.MetaData()
        for t in s.metadata.sorted_tables:
            sa.Table(t.name, md, *[c._copy() for c in t.columns
                                   if not (t.name == "version_components" and c.name == "stale_layers")])
        md.create_all(eng)
        monkeypatch.setattr(vr, "_engine", lambda: eng)
        with eng.begin() as cx:
            cx.execute(sa.text("INSERT INTO projects (id, name, created_at) VALUES ('p','p','2026-01-01')"))
            cx.execute(sa.text("INSERT INTO versions (id, project_id, version, created_at) "
                               "VALUES ('v1','p','v1','2026-01-01')"))
        vr.mark_components("v1", [A], "stale", layers=["HAL_LAYER"])
        with eng.connect() as cx:
            assert cx.execute(sa.text("SELECT state FROM version_components")).scalar() == "stale"


class TestAWordFileIsWrittenWhole:
    def test_it_replaces_the_file(self, tmp_path):
        import docx
        from docx_common import save_docx
        target = tmp_path / "out" / "software_detailed_design_X.docx"
        d = docx.Document()
        d.add_paragraph("one")
        save_docx(d, str(target))
        assert docx.Document(str(target)).paragraphs[0].text == "one"
        assert [p.name for p in target.parent.iterdir()] == [target.name], "no temp file left"

    def test_a_failed_write_leaves_the_previous_file(self, tmp_path):
        from docx_common import save_docx
        target = tmp_path / "software_detailed_design_X.docx"
        target.write_bytes(b"PK-previous")

        class Broken:
            def save(self, path):
                with open(path, "wb") as fh:
                    fh.write(b"half")
                raise OSError("disk full")
        with pytest.raises(OSError):
            save_docx(Broken(), str(target))
        assert target.read_bytes() == b"PK-previous"
        assert [p.name for p in tmp_path.iterdir()] == [target.name]

    def test_both_exporters_use_it(self):
        for name in ("docx_exporter.py", "swe4_exporter.py"):
            src = open(os.path.join(PROJECT_ROOT, "engine", name), encoding="utf-8").read()
            assert "save_docx(doc, docx_path)" in src and "doc.save(docx_path)" not in src, name


class TestMigration0017:
    def test_it_adds_the_columns_and_takes_them_away(self, tmp_path):
        import importlib.util
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        eng = sa.create_engine("sqlite:///" + str(tmp_path / "m.db").replace("\\", "/"))
        new = {("documents", "word_file_at"), ("analysis_jobs", "started_by"),
               ("analysis_jobs", "reason"), ("version_components", "stale_layers")}
        md = sa.MetaData()
        for t in s.metadata.sorted_tables:
            sa.Table(t.name, md, *[c._copy() for c in t.columns if (t.name, c.name) not in new])
        md.create_all(eng)
        path = os.path.join(PROJECT_ROOT, "alembic", "versions", "0018_word_file_updates.py")
        spec = importlib.util.spec_from_file_location("m0017", path)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        assert (m.revision, m.down_revision) == ("0018_word_file_updates", "0017_input_output_names")

        def cols():
            insp = sa.inspect(eng)
            return {(t, c["name"]) for t in ("documents", "analysis_jobs", "version_components")
                    for c in insp.get_columns(t)}
        with eng.begin() as cx:
            with Operations.context(MigrationContext.configure(cx)):
                m.upgrade()
        assert new <= cols()
        with eng.begin() as cx:
            with Operations.context(MigrationContext.configure(cx)):
                m.downgrade()
        assert not (new & cols())


# ---------------------------------------------------------------------------
# The review of 2026-10-06 (findings 1-8), one class each
# ---------------------------------------------------------------------------
class TestAResumeStoresWhatTheDeadRunMade:
    """Finding 1. A generation stores its output once, at its end. Cut short after making X, its
    `resume` makes Y -- and stored only Y: X's page, corrections and stamps had no rows."""

    def test_directories_never_stored_are_stored_too(self, engine, tmp_path, monkeypatch):
        from incremental.store import PgStore
        from review.rerender import write_output_row
        monkeypatch.setattr("incremental.store._draw_pending_pictures", lambda *a, **k: None)
        out = tmp_path / "out"
        for comp in ("Layer1.X", "Layer1.Y", "Layer1.Z"):
            (out / comp).mkdir(parents=True)
            (out / comp / "interface_tables.json").write_text('"%s on disk"' % comp)
        with engine.begin() as cx:        # Z was stored by an earlier run, then corrected
            write_output_row(cx, "v1", "Layer1.Z/interface_tables.json", '"Z corrected"')
        PgStore("p", engine, workspaces_root=str(tmp_path / "ws")).capture_output(
            "v1", str(out), components=["Layer1.Y"], since=T0)
        with engine.connect() as cx:
            rows = {r.rel_path: r.content for r in cx.execute(sa.select(s.version_output_files))}
        assert rows == {"Layer1.X/interface_tables.json": '"Layer1.X on disk"',
                        "Layer1.Y/interface_tables.json": '"Layer1.Y on disk"',
                        "Layer1.Z/interface_tables.json": '"Z corrected"'}

    def test_unstored_dirs(self, conn, tmp_path):
        from review.rerender import write_output_row
        for comp in (A, B):
            (tmp_path / comp).mkdir()
        (tmp_path / "loose.json").write_text("{}")
        write_output_row(conn, "v1", "%s/x.json" % A, "{}")
        assert wf.unstored_dirs(conn, "v1", str(tmp_path)) == [B]


class TestALayerAddedIsRememberedUntilMadeAgain:
    """Finding 2. run.py marks a component waiting, then generating, at an update's start: the
    `stale` state went, and with it "layer added" -- a failed, cancelled or killed update left a
    pre-layer file reading up to date, Approve froze it, and Try again ran Phase 4 alone."""

    def _rows(self, engine):
        from api.services.version_components import state_rows
        return state_rows(engine, "v1")

    def test_through_waiting_generating_and_failed(self, engine, monkeypatch):
        from core import version_run as vr
        from api.services import word_files as api_wf
        monkeypatch.setattr(vr, "_engine", lambda: engine)
        vr.mark_components("v1", [A], "stale", layers=["HAL_LAYER"])
        for state in ("waiting", "generating", "failed"):
            vr.mark_components("v1", [A], state, error="x")
            assert api_wf.stale_layers(None, "v1", self._rows(engine)) == {A: ["HAL_LAYER"]}, state
        vr.mark_components("v1", [A], "stale", layers=["L3"])          # a second layer added
        assert self._rows(engine)[A]["stale_layers"] == ["HAL_LAYER", "L3"]
        vr.mark_components("v1", [A], "generated")                     # made again: cleared
        assert api_wf.stale_layers(None, "v1", self._rows(engine)) == {}

    def test_a_layer_not_named_is_still_a_layer(self, engine, monkeypatch):
        from core import version_run as vr
        monkeypatch.setattr(vr, "_engine", lambda: engine)
        vr.mark_components("v1", [A], "stale")
        vr.mark_components("v1", [A], "waiting")
        assert vr.layer_added(self._rows(engine)[A]) == []
        assert vr.layer_added({"state": "stale", "stale_layers": None}) == []   # before 0017
        assert vr.layer_added({"state": "failed", "stale_layers": None}) is None

    def test_the_cli_and_the_in_process_reexport_ask_the_same(self):
        src = open(os.path.join(PROJECT_ROOT, "analyzer.py"), encoding="utf-8").read()
        body = src[src.index("def cmd_reexport("):src.index("def _layers_adder(")]
        assert "layer_added(rows.get(c[\"component\"])) is not None" in body
        pr = open(os.path.join(PROJECT_ROOT, "api", "services", "pipeline_runner.py"),
                  encoding="utf-8").read()
        body = pr[pr.index("def _stale_in_scope("):pr.index("def _reexport_detached(")]
        assert "vr.layer_added(r) is not None" in body and "return True" in body


class TestASaveUnderWayIsInOrOut:
    """Finding 3. A save stamps its time, then commits after its SWE.4 re-derive. An update whose
    `since` was taken between the two read the rows without it -- and the save's earlier time said
    "in the file". `since` is now taken holding the version's save lock."""

    def test_the_lock_is_taken_before_the_time(self):
        seen = []

        class Cx:
            dialect = type("D", (), {"name": "postgresql"})()

            def execute(self, stmt, params=None):
                seen.append(str(stmt))

        class Eng:
            def begin(self):
                import contextlib
                return contextlib.nullcontext(Cx())

        before = datetime.datetime.now(UTC)
        at = wf.wait_for_saves(Eng(), "v1")
        assert seen == ["SELECT pg_advisory_xact_lock(:k)"]
        assert at >= before

    def test_both_front_doors_take_it(self):
        src = open(os.path.join(PROJECT_ROOT, "analyzer.py"), encoding="utf-8").read()
        body = src[src.index("def _render_version("):src.index("def _with_current_secrets(")]
        assert body.index("with writing(") < body.index("since = _run_since(") \
            < body.index('_script(os.path.join(_ROOT, "engine", "run.py")')
        pr = open(os.path.join(PROJECT_ROOT, "api", "services", "pipeline_runner.py"),
                  encoding="utf-8").read()
        body = pr[pr.index("def _do_reexport("):pr.index("def _update_since(")]
        assert "since = _update_since(job.version_id)" in body


class TestAStructIsPlacedPerComponent:
    """Finding 4. One version-wide "the tables name their types" flag let a component updated by
    new code vouch for another whose stored rows predate `typeKey`."""

    def _headers(self, conn, comp, rows):
        conn.execute(sa.insert(s.version_output_files).values(
            version_id="v1", rel_path="%s/unit_headers.json" % comp, group_name=comp,
            content=json.dumps({"%s|U" % comp: rows})))

    def test_an_old_table_counts_as_showing_every_struct(self, conn):
        _correct(conn, T1, "Pump", kind="structDescription")
        self._headers(conn, A, [{"declaration": "int x", "typeKey": None}])
        self._headers(conn, B, [{"declaration": "struct Pump", "information": "llm"}])
        st = _state(conn, (A, "SWE.3", T0), (B, "SWE.3", T0))
        assert not st[A + "-SWE.3"].out_of_date, "A's table names its types: no Pump there"
        assert st[B + "-SWE.3"].out_of_date, "B's rows predate typeKey: it may print Pump"

    def test_the_placement(self, conn):
        self._headers(conn, A, [{"typeKey": "Pump"}, {"typeKey": None}])
        self._headers(conn, B, [{"declaration": "x"}])
        p = wf.struct_placement(conn, "v1")
        assert p.prints("Pump", A) and not p.prints("Valve", A)
        assert p.prints("Valve", B), "no typeKey: cannot say"
        assert p.prints("Valve", "Layer1.No-Table"), "no stored table: cannot say"


class TestAWordFileWaitsForItsReader:
    """Finding 5. Python opens files without FILE_SHARE_DELETE, so on Windows `os.replace` failed
    while a download or an approval's copy held the file -- where `doc.save(path)` had worked."""

    class Doc:
        def __init__(self, body):
            self.body = body

        def save(self, path):
            with open(path, "wb") as fh:
                fh.write(self.body)

    def test_a_held_file_is_replaced_once_let_go(self, tmp_path, monkeypatch):
        import os as _os
        import docx_common
        target = tmp_path / "software_detailed_design_X.docx"
        target.write_bytes(b"old")
        real, tries = _os.replace, []

        def busy_twice(src, dst):
            tries.append(dst)
            if len(tries) < 3:
                raise PermissionError(13, "held by a reader", dst)
            return real(src, dst)
        monkeypatch.setattr(docx_common.os, "replace", busy_twice)
        docx_common.save_docx(self.Doc(b"new"), str(target))
        assert target.read_bytes() == b"new" and len(tries) == 3
        assert [p.name for p in tmp_path.iterdir()] == [target.name]

    def test_a_real_reader_on_this_machine(self, tmp_path):
        import threading
        import docx_common
        target = tmp_path / "software_detailed_design_X.docx"
        target.write_bytes(b"old")
        reader = open(target, "rb")
        threading.Timer(0.4, reader.close).start()
        docx_common.save_docx(self.Doc(b"new"), str(target))
        assert target.read_bytes() == b"new"

    def test_a_reader_that_never_lets_go_fails_it_cleanly(self, tmp_path, monkeypatch):
        import docx_common
        target = tmp_path / "software_detailed_design_X.docx"
        target.write_bytes(b"old")
        monkeypatch.setattr(docx_common, "REPLACE_WAIT_SECONDS", 0.2)
        monkeypatch.setattr(docx_common.os, "replace",
                            lambda s_, d: (_ for _ in ()).throw(PermissionError(13, "held", d)))
        with pytest.raises(PermissionError) as exc:
            docx_common.save_docx(self.Doc(b"new"), str(target))
        assert "held open by a reader" in str(exc.value)
        assert target.read_bytes() == b"old"
        assert [p.name for p in tmp_path.iterdir()] == [target.name]

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
    def test_it_keeps_the_file_s_permissions(self, tmp_path):
        import docx_common
        target = tmp_path / "software_detailed_design_X.docx"
        target.write_bytes(b"old")
        os.chmod(target, 0o644)
        docx_common.save_docx(self.Doc(b"new"), str(target))
        assert (os.stat(target).st_mode & 0o777) == 0o644
        first = tmp_path / "software_unit_test_specification_X.docx"
        mask = os.umask(0)
        os.umask(mask)
        docx_common.save_docx(self.Doc(b"new"), str(first))
        assert (os.stat(first).st_mode & 0o777) == (0o666 & ~mask)


class TestAGroupOrLayerRunStoresItsComponents:
    """Finding 6. `reexport --scope group:/layer:` stored the whole version but held only its own
    components: a save in another layer during it was reverted."""

    def test_the_components_it_asked_for(self, engine, monkeypatch):
        from core import version_run as vr
        monkeypatch.setattr(vr, "_engine", lambda: engine)
        vr.mark_components("v1", [B], "generated")                       # an earlier run
        since = datetime.datetime.now(UTC)
        vr.mark_components("v1", [A], "waiting")                         # this run's plan
        with engine.connect() as cx:
            assert wf.components_touched_since(cx, "v1", since) == [A]

    def test_the_cli_passes_them(self):
        src = open(os.path.join(PROJECT_ROOT, "analyzer.py"), encoding="utf-8").read()
        body = src[src.index("def _render_version("):src.index("def _with_current_secrets(")]
        assert "rebuilt = _touched_since(a.version_id, since)" in body


class TestEveryRunStampsItsStart:
    """Finding 8. A generation and resume's "close" passed no `since`, so their files took their
    own time -- later than the run read, and a correction saved meanwhile counted as in them."""

    def test_the_capture_takes_the_running_run_s_start(self, engine, tmp_path, monkeypatch):
        from incremental.store import PgStore
        monkeypatch.setattr("incremental.store._draw_pending_pictures", lambda *a, **k: None)
        start = datetime.datetime.now(UTC) - datetime.timedelta(minutes=5)
        out = tmp_path / "out"
        docx = out / A / ("software_detailed_design_%s.docx" % A)
        docx.parent.mkdir(parents=True)
        docx.write_bytes(b"PK")
        with engine.begin() as cx:
            cx.execute(sa.insert(s.version_runs).values(version_id="v1", command="generate",
                                                        started_at=start, outcome="running"))
            cx.execute(sa.insert(s.documents).values(id="a3", project_id="p", version_id="v1",
                                                     process="SWE.3", name=A, component=A,
                                                     status="in_review"))
        PgStore("p", engine, workspaces_root=str(tmp_path / "ws")).capture_output("v1", str(out))
        with engine.connect() as cx:
            at = cx.execute(sa.select(s.documents.c.word_file_at)).scalar()
        assert g._aware(at) == start

    def test_a_recorded_document_takes_its_run_s_start(self, tmp_path):
        from api.services.document_registry import _word_file_time
        comp = tmp_path / A
        comp.mkdir()
        docx = comp / ("software_detailed_design_%s.docx" % A)
        docx.write_bytes(b"PK")
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(docx), UTC)
        run = {"started_at": mtime - datetime.timedelta(hours=2), "finished_at": None}
        assert _word_file_time(run, comp, docx) == run["started_at"]       # the run wrote it
        old_run = {"started_at": mtime + datetime.timedelta(hours=1), "finished_at": None}
        assert _word_file_time(old_run, comp, docx) == mtime               # nothing known
        g.record_derivation(str(comp), ["interfaceTables"], [A], mtime - datetime.timedelta(hours=3))
        os.utime(docx, (mtime.timestamp(), mtime.timestamp()))
        assert _word_file_time(old_run, comp, docx) == mtime - datetime.timedelta(hours=3)
