"""The export refuses to ship text a correction has already replaced (REQ-AP-04).

`reexport --from-phase 4` is "export only" and skips Phase 3, the step that rebuilds the view rows
the document is built from. Correct a description and export a second later and the DOCX carries
the previous wording, silently. That is the failure this guard exists for, and it is a query over
stored facts rather than a flag, so a future write path that forgets to re-derive still cannot slip
past it.

The facts are per (view, component): which view was last rebuilt for which component, from the
corrections that existed then. A single "the version was derived" stamp could not tell a SWE.3
re-derive from a SWE.4 one -- reproduced on the real pipeline: a label corrected, a SWE.3 re-export,
then an export-only run shipped the SWE.4 document with the old label and no warning.
"""
import datetime
import json
import os
import re
import sys

import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from api.db.postgres import schema as s
from review import export_guard as g

T0 = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
T1 = datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)
T2 = datetime.datetime(2026, 1, 3, tzinfo=datetime.timezone.utc)
T3 = datetime.datetime(2026, 1, 4, tzinfo=datetime.timezone.utc)

#: What a description correction reaches (`derive.views_for`): the interface table (SWE.3) and the
#: SWE.4 spec that copies it.
DESCRIPTION_VIEWS = ("interfaceTables", "testSpecs")


@pytest.fixture
def conn():
    eng = sa.create_engine("sqlite://")
    s.metadata.create_all(eng)
    with eng.begin() as cx:
        now = datetime.datetime.now(datetime.timezone.utc)
        cx.execute(sa.insert(s.projects).values(id="p", name="p", created_at=now))
        cx.execute(sa.insert(s.versions).values(id="v1", project_id="p", version="v1",
                                                created_at=now))
        yield cx


def _override(conn, when, key="Comp|UnitA|f|", kind="description"):
    conn.execute(sa.insert(s.text_overrides).values(
        version_id="v1", slot_kind=kind, slot_key=key,
        llm_text="llm", human_text="human", is_orphaned=False, updated_at=when))


def _derived(conn, when, views=DESCRIPTION_VIEWS, component="Comp"):
    g.stamp_view_derivations(conn, "v1", [(v, component) for v in views], when)


class TestTheOrdinaryCase:
    def test_a_version_nobody_corrected_is_never_stale(self, conn):
        """Every project today. It must also be cheap -- one indexed lookup that returns nothing
        and stops, with no join and no scan."""
        st = g.staleness(conn, "v1")
        assert not st.is_stale
        assert st.override_count == 0

    def test_a_correction_older_than_the_derivation_is_fine(self, conn):
        _override(conn, T0)
        _derived(conn, T1)
        assert not g.staleness(conn, "v1").is_stale

    def test_a_correction_newer_than_the_derivation_is_stale(self, conn):
        """The whole point: the model and the override table moved, the view rows did not."""
        _derived(conn, T0)
        _override(conn, T1)
        st = g.staleness(conn, "v1")
        assert st.is_stale
        assert "newer than the derived output" in st.reason


class TestAbsenceOfEvidence:
    def test_corrections_with_no_recorded_derivation_are_stale(self, conn):
        """Not evidence of freshness -- the absence of evidence. A guard that reads "no data" as
        "fine" is the guard that does not guard."""
        _override(conn, T1)
        st = g.staleness(conn, "v1")
        assert st.is_stale
        assert "ever recorded" in st.reason

    def test_one_fresh_view_does_not_vouch_for_another(self, conn):
        """The interface table re-derived after the correction; the SWE.4 spec that copies the
        same description was not."""
        _derived(conn, T0)
        _override(conn, T1)
        _derived(conn, T2, views=("interfaceTables",))
        assert g.staleness(conn, "v1").is_stale

    def test_re_deriving_everything_clears_it(self, conn):
        _derived(conn, T0)
        _override(conn, T1)
        assert g.staleness(conn, "v1").is_stale
        _derived(conn, T2)
        assert not g.staleness(conn, "v1").is_stale


class TestDocumentTypes:
    """An export is judged on the views its documents are built from."""

    def test_a_swe3_re_derive_does_not_vouch_for_swe4(self, conn):
        """THE REPRODUCED BUG. A SWE.3 re-export rebuilt the interface table after the
        correction; the SWE.4 spec still carries the old wording."""
        _derived(conn, T0)
        _override(conn, T1)
        _derived(conn, T2, views=("interfaceTables",))
        assert not g.staleness(conn, "v1", "swe3").is_stale
        assert g.staleness(conn, "v1", "swe4").is_stale
        assert g.staleness(conn, "v1", "all").is_stale
        assert g.staleness(conn, "v1").is_stale, "no document type named = every view"

    def test_a_swe3_export_is_not_held_up_by_specs_it_does_not_print(self, conn):
        """A web-app version has no SWE.4 at all; its SWE.3 must still be exportable."""
        _override(conn, T1)
        _derived(conn, T2, views=("interfaceTables",))
        assert not g.staleness(conn, "v1", "swe3").is_stale

    def test_a_swe4_export_asks_only_about_swe4_views(self, conn):
        _override(conn, T1)
        _derived(conn, T2, views=("testSpecs",))
        assert not g.staleness(conn, "v1", "swe4").is_stale
        assert g.staleness(conn, "v1", "swe3").is_stale

    def test_a_label_reaches_swe4_through_the_specs_and_the_ut_export(self, conn):
        _override(conn, T1, key="Comp|UnitA|f|\x01n3", kind="nodeLabel")
        _derived(conn, T2, views=("testSpecs",))
        assert g.staleness(conn, "v1", "swe4").is_stale, "the UT export was not re-derived"
        _derived(conn, T2, views=("utExport",))
        assert not g.staleness(conn, "v1", "swe4").is_stale

    def test_a_rebuilt_flowchart_does_not_vouch_for_the_specs_transcribing_it(self, conn):
        """A SWE.3 re-derive redraws the flowchart with the corrected label; the Test Steps are
        still the old ones until the specs are rebuilt from it."""
        _override(conn, T1, key="Comp|UnitA|f|\x01n3", kind="nodeLabel")
        _derived(conn, T2, views=("flowcharts",))
        assert not g.staleness(conn, "v1", "swe3").is_stale
        assert g.staleness(conn, "v1", "swe4").is_stale

    def test_a_picture_being_drawn_holds_up_swe3_only(self, conn):
        """SWE.4 prints no flowchart, so it has no picture to wait for."""
        from review import render_queue
        _override(conn, T1, key="Comp|UnitA|f|\x01n3", kind="nodeLabel")
        _derived(conn, T2, views=("flowcharts", "testSpecs", "utExport"))
        render_queue.enqueue(conn, "v1", "Comp|UnitA|f|", "f.png", user_id="u1", now=T1)
        assert "being drawn" in g.staleness(conn, "v1", "swe3").reason
        assert g.staleness(conn, "v1").is_stale, "no document type named = the cautious answer"
        assert not g.staleness(conn, "v1", "swe4").is_stale

    def test_the_names(self):
        assert g.doc_types_of("all") == ("swe3", "swe4")
        assert g.doc_types_of(("swe4", "swe3", "swe4")) == ("swe4", "swe3")
        assert g.doc_types_of(None) is None
        with pytest.raises(ValueError):
            g.doc_types_of("swe9")

    def test_the_swe4_views_are_the_registrys(self):
        """Kept as a constant so asking the guard imports no view; this keeps it honest. A SWE.4
        run also runs `flowcharts`, as the specs' input -- the one view it runs and does not
        read."""
        import views  # noqa: F401 - importing the package registers the views
        from views.registry import DOC_TYPE_SWE4, DOC_TYPE_VIEWS
        assert g.SWE4_VIEWS <= set(DOC_TYPE_VIEWS[DOC_TYPE_SWE4])
        assert set(DOC_TYPE_VIEWS[DOC_TYPE_SWE4]) - g.SWE4_VIEWS == {"flowcharts"}


class TestWhatSwe3Prints:
    """SWE.3 embeds the flowcharts only where `views.flowcharts` is on -- off by default, and then
    only a SWE.4 run draws them. A label correction must not hold up such a SWE.3 export: no
    SWE.3 re-derive could ever clear it. The stored records say which document types' runs built
    each view."""

    LABEL = dict(key="Layer1.Lib|Lib|libAbs|int\x01N3", kind="nodeLabel")

    def _record(self, conn, flowcharts_by):
        views = {"interfaceTables": {"at": T2.isoformat(), "components": ["layer1.lib"],
                                     "docTypes": ["swe3"]},
                 "flowcharts": {"at": T0.isoformat(), "components": ["layer1.lib"],
                                "docTypes": flowcharts_by}}
        _stored_record(conn, "Layer1.Lib/_derivations.json", {"views": views})
        g.stamp_view_derivations(conn, "v1", [("interfaceTables", "Layer1.Lib")], T2)
        g.stamp_view_derivations(conn, "v1", [("flowcharts", "Layer1.Lib")], T0)

    def test_flowcharts_only_swe4_draws_do_not_hold_up_swe3(self, conn):
        self._record(conn, ["swe4"])
        _override(conn, T1, **self.LABEL)
        assert not g.staleness(conn, "v1", "swe3").is_stale
        assert g.staleness(conn, "v1").is_stale, "no document type named = every view"

    def test_flowcharts_swe3_draws_do(self, conn):
        self._record(conn, ["swe3", "swe4"])
        _override(conn, T1, **self.LABEL)
        assert g.staleness(conn, "v1", "swe3").is_stale

    def test_nor_does_their_picture(self, conn):
        from review import render_queue
        self._record(conn, ["swe4"])
        _override(conn, T1, **self.LABEL)
        render_queue.enqueue(conn, "v1", "Layer1.Lib|Lib|libAbs|int", "f.png", user_id="u",
                             now=T1)
        assert not g.staleness(conn, "v1", "swe3").is_stale

    def test_without_records_every_view_counts(self, conn):
        """Output from before the records: nobody can say what SWE.3 prints."""
        g.stamp_view_derivations(conn, "v1", [("flowcharts", "Layer1.Lib")], T0)
        _override(conn, T1, **self.LABEL)
        assert g.staleness(conn, "v1", "swe3").is_stale

    def test_a_record_that_does_not_say_counts_every_view(self, conn):
        _stored_record(conn, "G/_derivations.json", {"views": {"flowcharts": {
            "at": T0.isoformat(), "components": ["layer1.lib"]}}})
        g.stamp_view_derivations(conn, "v1", [("flowcharts", "Layer1.Lib")], T0)
        _override(conn, T1, **self.LABEL)
        assert g.staleness(conn, "v1", "swe3").is_stale

    def test_the_record_accumulates_who_built_a_view(self, tmp_path):
        """Sticky: once a SWE.3 run drew the flowcharts, SWE.3 prints them."""
        out = str(tmp_path / "G")
        g.record_derivation(out, ["flowcharts"], ["Comp"], T0,
                            doc_types={"flowcharts": ["swe3"]})
        g.record_derivation(out, ["flowcharts", "testSpecs"], ["Comp"], T1,
                            doc_types={"flowcharts": ["swe4"], "testSpecs": ["swe4"]})
        rec = g.read_record(os.path.join(out, g.DERIVATION_RECORD))
        assert rec["views"]["flowcharts"]["docTypes"] == ["swe3", "swe4"]
        assert rec["views"]["testSpecs"]["docTypes"] == ["swe4"]

    def test_an_all_run_builds_the_flowcharts_for_swe4_alone_when_swe3_has_none(self):
        """One `--doc-type all` Phase 3 builds every view both documents need; what each view
        was built for comes from the rule that chose it (`views.views_to_run`)."""
        from views import views_to_run
        off = {"views": {"flowcharts": False}}
        assert "flowcharts" in views_to_run("swe4", off)
        assert "flowcharts" not in views_to_run("swe3", off)
        assert "flowcharts" in views_to_run("swe3", {"views": {"flowcharts": True}})
        assert "flowcharts" in views_to_run("all", off)

    def test_phase_3_records_it(self):
        """The call site: `run_views` hands the record what each view was built for."""
        src = open(os.path.join(PROJECT_ROOT, "engine", "run_views.py"), encoding="utf-8").read()
        assert "doc_types=built_for" in src
        assert "views_to_run(t, config)" in src


class TestComponents:
    def test_another_components_derivation_does_not_cover_this_one(self, conn):
        """A run scoped to one group rebuilt that group's components only."""
        _derived(conn, T0)
        _override(conn, T1)
        _derived(conn, T2, component="Other")
        assert g.staleness(conn, "v1").is_stale

    def test_components_meet_in_one_form(self, conn):
        """Config spells a component with spaces, unit keys with hyphens."""
        _override(conn, T1, key="Layer1.Sample-Core|Core|f|")
        _derived(conn, T2, component="Layer1.Sample Core")
        assert not g.staleness(conn, "v1").is_stale

    def test_a_struct_description_needs_every_component(self, conn):
        """Its key is the type's own name -- which unit's table prints it is not in the key."""
        _override(conn, T1, key="Point", kind="structDescription")
        _derived(conn, T2, views=("unitHeaders",), component="A")
        _derived(conn, T0, views=("unitHeaders",), component="B")
        assert g.staleness(conn, "v1").is_stale
        _derived(conn, T2, views=("unitHeaders",), component="B")
        assert not g.staleness(conn, "v1").is_stale


class TestLegacyStamps:
    def test_a_whole_version_wildcard_vouches_for_nothing(self, conn):
        """What was written before this fix: one row, whatever Phase 3 had done."""
        conn.execute(sa.insert(s.view_derivations).values(
            version_id="v1", view_name=g.PIPELINE_ALL, group_name="", derived_at=T2))
        _override(conn, T1)
        assert g.staleness(conn, "v1").is_stale

    def test_a_stamp_that_names_no_component_vouches_for_nothing(self, conn):
        conn.execute(sa.insert(s.view_derivations).values(
            version_id="v1", view_name="interfaceTables", group_name="", derived_at=T2))
        _override(conn, T1)
        assert g.staleness(conn, "v1", "swe3").is_stale


class TestScope:
    def test_another_version_does_not_make_this_one_stale(self, conn):
        conn.execute(sa.insert(s.versions).values(
            id="v2", project_id="p", version="v2",
            created_at=datetime.datetime.now(datetime.timezone.utc)))
        _derived(conn, T1)
        conn.execute(sa.insert(s.text_overrides).values(
            version_id="v2", slot_kind="description", slot_key="Comp|UnitA|f|",
            llm_text="a", human_text="b", is_orphaned=False, updated_at=T2))
        assert not g.staleness(conn, "v1").is_stale
        assert g.staleness(conn, "v2").is_stale


class TestTheStamp:
    def test_it_is_idempotent_and_moves_forward(self, conn):
        _derived(conn, T0, views=("testSpecs",))
        _derived(conn, T2, views=("testSpecs",))
        rows = conn.execute(sa.select(s.view_derivations)).fetchall()
        assert len(rows) == 1, "a second run appended instead of moving the row forward"
        assert g._aware(rows[0].derived_at) == T2

    def test_it_never_moves_backwards(self, conn):
        """Two saves in one component must not undo each other. Moving a stamp back is the
        capture's alone, by replacing the rows -- see TestTheRecord."""
        _derived(conn, T2, views=("testSpecs",))
        _derived(conn, T0, views=("testSpecs",))
        row = conn.execute(sa.select(s.view_derivations)).first()
        assert g._aware(row.derived_at) == T2

    def test_one_row_per_view_and_component(self, conn):
        _derived(conn, T0, component="A")
        _derived(conn, T0, component="B")
        assert len(conn.execute(sa.select(s.view_derivations)).fetchall()) == 4

    def test_a_component_is_stored_in_one_form(self, conn):
        _derived(conn, T0, views=("testSpecs",), component="Layer1.Sample Core")
        _derived(conn, T1, views=("testSpecs",), component="layer1.sample-core")
        rows = conn.execute(sa.select(s.view_derivations)).fetchall()
        assert [r.group_name for r in rows] == ["layer1.sample-core"]


class TestTheRecord:
    """Phase 3 records what it rebuilt; the capture turns the records into stamps."""

    def test_a_view_not_rebuilt_keeps_its_earlier_entry(self, tmp_path):
        g.record_derivation(str(tmp_path), ["interfaceTables", "testSpecs"], ["Comp"], T0)
        g.record_derivation(str(tmp_path), ["interfaceTables"], ["Comp"], T2)
        rec = g.read_record(str(tmp_path / g.DERIVATION_RECORD))
        assert rec["views"]["interfaceTables"]["at"].startswith("2026-01-03")
        assert rec["views"]["testSpecs"]["at"].startswith("2026-01-01")

    def test_the_context_travels_with_the_swe4_views_only(self, tmp_path):
        ctx = {"allowedComponents": ["Comp"], "views": {}, "layers": {}}
        g.record_derivation(str(tmp_path), ["interfaceTables", "testSpecs", "utExport"],
                            ["Comp"], T0, context=ctx)
        rec = g.read_record(str(tmp_path / g.DERIVATION_RECORD))
        assert "context" not in rec["views"]["interfaceTables"]
        assert rec["views"]["testSpecs"]["context"] == ctx
        assert rec["views"]["utExport"]["context"] == ctx

    def test_every_record_in_the_tree_is_stamped(self, conn, tmp_path):
        g.record_derivation(str(tmp_path / "Layer1.A"), ["interfaceTables"], ["Layer1.A"], T0)
        g.record_derivation(str(tmp_path / "Layer1.B"), ["interfaceTables"], ["Layer1.B"], T1)
        assert g.stamp_recorded_derivations(conn, "v1", str(tmp_path)) == 2
        rows = {r.group_name: g._aware(r.derived_at)
                for r in conn.execute(sa.select(s.view_derivations))}
        assert rows == {"layer1.a": T0, "layer1.b": T1}

    def test_an_unchanged_record_moves_nothing(self, conn, tmp_path):
        """An export-only run rebuilds nothing, so its capture must vouch for nothing new."""
        g.record_derivation(str(tmp_path / "G"), ["interfaceTables"], ["Comp"], T0)
        g.stamp_recorded_derivations(conn, "v1", str(tmp_path))
        _override(conn, T1)
        g.stamp_recorded_derivations(conn, "v1", str(tmp_path))      # the export-only capture
        assert g.staleness(conn, "v1", "swe3").is_stale

    def test_the_reproduced_sequence(self, conn, tmp_path):
        """generate --doc-type all, correct, re-export SWE.3 only, then ask about SWE.4."""
        out = str(tmp_path / "Layer1.Lib")
        g.record_derivation(out, ["interfaceTables", "flowcharts", "testSpecs", "utExport"],
                            ["Layer1.Lib"], T0)
        g.stamp_recorded_derivations(conn, "v1", str(tmp_path))
        _override(conn, T1, key="Layer1.Lib|Lib|libAbs|int\x01N3", kind="nodeLabel")
        g.record_derivation(out, ["interfaceTables", "flowcharts"], ["Layer1.Lib"], T2)
        g.stamp_recorded_derivations(conn, "v1", str(tmp_path))
        assert not g.staleness(conn, "v1", "swe3").is_stale
        st = g.staleness(conn, "v1", "swe4")
        assert st.is_stale and "testSpecs" in st.reason

    def test_an_unreadable_record_is_skipped(self, conn, tmp_path):
        (tmp_path / "G").mkdir()
        (tmp_path / "G" / g.DERIVATION_RECORD).write_text("{not json", encoding="utf-8")
        assert g.stamp_recorded_derivations(conn, "v1", str(tmp_path)) == 0

    def test_the_capture_replaces_the_stamps(self, conn, tmp_path):
        """The capture replaced every output row with these files, so a stamp for rows it
        overwrote vouches for text that is no longer stored."""
        g.record_derivation(str(tmp_path / "G"), ["interfaceTables"], ["Comp"], T0)
        _derived(conn, T2, views=("interfaceTables",))           # a stamp no record backs
        _override(conn, T1)
        assert not g.staleness(conn, "v1", "swe3").is_stale
        g.stamp_recorded_derivations(conn, "v1", str(tmp_path))
        assert g.staleness(conn, "v1", "swe3").is_stale


def _stored_record(conn, rel_path, record):
    """A record as the capture stores it: an output row beside the files it describes."""
    conn.execute(sa.insert(s.version_output_files).values(
        version_id="v1", rel_path=rel_path, content=g.record_text(record),
        group_name=rel_path.split("/", 1)[0]))


def _row(conn, rel_path):
    return conn.execute(sa.select(s.version_output_files.c.content)
                        .where(s.version_output_files.c.rel_path == rel_path)).scalar()


class TestASaveThatReDerives:
    """`stamp_saved`: the stamp a save writes lives exactly as long as the rows it rebuilt."""

    RECORD = {"views": {"testSpecs": {"at": T0.isoformat(), "components": ["comp"]},
                        "utExport": {"at": T0.isoformat(), "components": ["comp"]}}}

    def test_it_marks_the_record_and_moves_the_stamp(self, conn):
        _stored_record(conn, "G/_derivations.json", self.RECORD)
        g.stamp_view_derivations(conn, "v1", [("testSpecs", "Comp")], T0)
        assert g.stamp_saved(conn, "v1", [("testSpecs", "Comp")], T2) == 1
        rec = json.loads(_row(conn, "G/_derivations.json"))
        assert rec["views"]["testSpecs"]["saved"] == {"comp": T2.isoformat()}
        assert "saved" not in rec["views"]["utExport"], "only the pair the save rebuilt"
        row = conn.execute(sa.select(s.view_derivations)).first()
        assert g._aware(row.derived_at) == T2

    def test_its_mark_survives_the_next_capture(self, conn, tmp_path):
        """Any later run restores the rows -- the marked record among them -- before it
        captures. Without the mark, the next re-export of anything would call this correction
        stale again."""
        _stored_record(conn, "G/_derivations.json", self.RECORD)
        _override(conn, T2, key="Comp|UnitA|f|\x01n3", kind="nodeLabel")
        g.stamp_saved(conn, "v1", [("testSpecs", "Comp"), ("utExport", "Comp")], T2)
        (tmp_path / "G").mkdir()
        (tmp_path / "G" / g.DERIVATION_RECORD).write_text(_row(conn, "G/_derivations.json"),
                                                          encoding="utf-8")
        g.stamp_recorded_derivations(conn, "v1", str(tmp_path))
        assert not g.staleness(conn, "v1", "swe4").is_stale

    def test_a_save_made_while_a_run_was_building_is_not_vouched_for(self, conn, tmp_path):
        """The run restored the rows before the save and stores its own after it: the save's
        rows and its mark are overwritten together, so the correction is stale again -- the
        truth, since the rows no longer carry it."""
        (tmp_path / "G").mkdir()
        (tmp_path / "G" / g.DERIVATION_RECORD).write_text(g.record_text(self.RECORD),
                                                          encoding="utf-8")   # restored at T0
        _stored_record(conn, "G/_derivations.json", self.RECORD)
        _override(conn, T2, key="Comp|UnitA|f|\x01n3", kind="nodeLabel")
        g.stamp_saved(conn, "v1", [("testSpecs", "Comp"), ("utExport", "Comp")], T2)
        assert not g.staleness(conn, "v1", "swe4").is_stale
        g.stamp_recorded_derivations(conn, "v1", str(tmp_path))    # the run's capture
        assert g.staleness(conn, "v1", "swe4").is_stale

    def test_a_run_that_rebuilds_the_view_drops_the_marks(self, tmp_path):
        """Its rows replace the ones the save wrote; its own time is what they carry now."""
        out = str(tmp_path / "G")
        g.record_derivation(out, ["testSpecs", "interfaceTables"], ["Comp"], T0)
        path = os.path.join(out, g.DERIVATION_RECORD)
        rec = g.read_record(path)
        for view in ("testSpecs", "interfaceTables"):
            g.mark_saved(rec, view, "Comp", T1)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(g.record_text(rec))
        g.record_derivation(out, ["testSpecs"], ["Comp"], T2)
        rec = g.read_record(path)
        assert "saved" not in rec["views"]["testSpecs"]
        assert rec["views"]["interfaceTables"]["saved"] == {"comp": T1.isoformat()}

    def test_a_record_that_does_not_cover_the_pair_is_left_alone(self, conn):
        _stored_record(conn, "G/_derivations.json", self.RECORD)
        g.stamp_saved(conn, "v1", [("testSpecs", "Other")], T2)
        assert _row(conn, "G/_derivations.json") == g.record_text(self.RECORD)

    def test_a_mark_never_moves_backwards(self):
        rec = json.loads(json.dumps(self.RECORD))
        assert g.mark_saved(rec, "testSpecs", "Comp", T2)
        assert not g.mark_saved(rec, "testSpecs", "Comp", T1)
        assert rec["views"]["testSpecs"]["saved"] == {"comp": T2.isoformat()}

    def test_what_the_records_vouch_for(self):
        """Per record, the later of the run and a save; across records, the latest -- one row
        per (view, component), as always."""
        a = {"views": {"testSpecs": {"at": T0.isoformat(), "components": ["comp", "other"],
                                     "saved": {"comp": T2.isoformat()}}}}
        b = {"views": {"testSpecs": {"at": T1.isoformat(), "components": ["other"]}}}
        assert g.stamps_from_records([a, b]) == {("testSpecs", "comp"): T2,
                                                 ("testSpecs", "other"): T1}


class TestAssertExportable:
    def test_it_passes_when_fresh(self, conn):
        _derived(conn, T1)
        assert g.assert_exportable(conn, "v1").is_stale is False

    def test_it_raises_when_stale_and_says_what_to_run(self, conn):
        _derived(conn, T0)
        _override(conn, T1)
        with pytest.raises(g.StaleExport) as exc:
            g.assert_exportable(conn, "v1")
        msg = str(exc.value)
        assert "--from-phase 3" in msg, "the error must say how to fix it, not just that it failed"
        assert "v1" in msg

    def test_it_asks_about_the_documents_it_is_given(self, conn):
        _override(conn, T1)
        _derived(conn, T2, views=("interfaceTables",))
        assert g.assert_exportable(conn, "v1", "swe3").is_stale is False
        with pytest.raises(g.StaleExport):
            g.assert_exportable(conn, "v1", "swe4")


class TestNaiveTimestamps:
    def test_a_naive_timestamp_does_not_crash_the_export(self, conn):
        """SQLite returns naive datetimes where Postgres returns aware ones. Comparing the two
        raises TypeError, which inside an export path reads as a crash rather than as the
        stale-or-not answer the caller asked for."""
        for view in DESCRIPTION_VIEWS:
            conn.execute(sa.insert(s.view_derivations).values(
                version_id="v1", view_name=view, group_name="comp",
                derived_at=datetime.datetime(2026, 1, 1)))          # naive
        _override(conn, T1)
        st = g.staleness(conn, "v1")
        assert st.is_stale is True


class TestItIsWiredIntoReexport:
    """The guard existing and never being called is the failure mode -- everything passes and
    `--from-phase 4` still ships stale text. `cmd_reexport` cannot be invoked here (it needs a
    workspace, a checkout and a subprocess), so the call site is checked in the source, the same
    way the flowcharts view's hook is."""

    @staticmethod
    def _source():
        return open(os.path.join(PROJECT_ROOT, "analyzer.py"), encoding="utf-8").read()

    CALL = re.compile(r"^[ 	]+rc = _refuse_stale_export\(a\.version_id, doc_type\)", re.M)

    def test_reexport_calls_the_guard(self):
        assert self.CALL.search(self._source()), (
            "reexport no longer checks staleness, so --from-phase 4 can ship superseded text")

    def test_the_matcher_rejects_the_definition(self):
        """A matcher that also matches `def _refuse_stale_export(...)` could never fail. That
        exact mistake was made once already in this feature's tests."""
        assert not self.CALL.search(
            "def _refuse_stale_export(version_id: str, doc_type: str = None) -> int:")

    def test_the_check_runs_before_the_pipeline_is_launched(self):
        src = self._source()
        call = self.CALL.search(src)
        assert call and call.start() < src.index('_script(os.path.join(_ROOT, "engine", "run.py")'), (
            "the guard runs after the export; it must refuse before any work is done")

    def test_it_asks_about_the_documents_the_export_writes(self):
        """The document type is resolved BEFORE the question -- the answer depends on it."""
        src = self._source()
        body = src[src.index("def cmd_reexport("):]
        assert body.index("doc_type = a.doc_type or") < self.CALL.search(body).start()

    def test_only_phase_4_is_gated(self):
        """Phases 2 and 3 re-derive on their way through, so gating them would refuse a command
        that is itself the fix."""
        assert "if a.from_phase >= 4 and not forced:" in self._source()

    def test_there_is_an_escape_hatch(self):
        """A guard with no override becomes something people work around by other means."""
        assert '"--force"' in self._source()


class TestTheApiRederivesRatherThanRefusing:
    """The same question, answered differently because the asker is different.

    The CLI refuses and prints `--from-phase 3`. A reviewer who pressed "re-export" in the UI
    seconds after fixing a sentence should not have to learn what a phase is, so the API applies
    that remedy instead of recommending it.

    These drive the real function with a real database, because the wiring tests beside them only
    read the source -- and a decision that is computed correctly and then ignored looks identical
    to source.
    """

    @staticmethod
    def _decide(conn, monkeypatch, version_id="v1"):
        """Run `_reexport_from_phase` against this test's SQLite connection."""
        import api.services.pipeline_runner as pr
        from core import db as core_db

        class _Eng:
            def connect(self):
                class _Cx:
                    def __enter__(_s):
                        return conn

                    def __exit__(_s, *a):
                        return False
                return _Cx()

        monkeypatch.setattr(core_db, "is_database_configured", lambda: True)
        monkeypatch.setattr(core_db, "get_engine", lambda *a, **k: _Eng())
        return pr._reexport_from_phase(version_id)

    def test_a_clean_version_exports_only(self, conn, monkeypatch):
        """Nothing has been corrected since the views were built, so Phase 3 would be waste."""
        _derived(conn, T1)
        assert self._decide(conn, monkeypatch) == 4

    def test_a_correction_newer_than_the_views_re_derives(self, conn, monkeypatch):
        """THE CASE THIS EXISTS FOR. Phase 4 alone would ship what Phase 3 wrote last time."""
        _derived(conn, T1)
        _override(conn, T2)
        assert self._decide(conn, monkeypatch) == 3

    def test_it_asks_about_swe3_the_only_document_it_writes(self, conn, monkeypatch):
        """SWE.4 specs the web app never re-derives must not send every re-export through
        Phase 3 for ever."""
        _derived(conn, T1)
        _override(conn, T2)
        _derived(conn, T3, views=("interfaceTables",))
        assert self._decide(conn, monkeypatch) == 4

    def test_a_version_never_derived_re_derives(self, conn, monkeypatch):
        """Absence of evidence is not evidence of freshness -- the same rule the guard uses."""
        _override(conn, T2)
        assert self._decide(conn, monkeypatch) == 3

    def test_a_pending_picture_re_derives(self, conn, monkeypatch):
        """A correction saved where no output tree existed leaves the text right and the PNG
        owed. Exporting now yields a document whose words and picture disagree, which is worse
        than one that is uniformly out of date."""
        _derived(conn, T2)
        _override(conn, T1)
        from review import render_queue
        render_queue.enqueue(conn, "v1", "Comp|UnitA|f|", "f.png", user_id="u1", now=T1)
        assert self._decide(conn, monkeypatch) == 3

    def test_no_version_id_exports_only(self, conn, monkeypatch):
        """A legacy commit-keyed job. There is nothing to be stale against."""
        assert self._decide(conn, monkeypatch, version_id=None) == 4

    def test_no_database_exports_only(self, monkeypatch):
        """An unavailable guard must not quietly change what the pipeline does."""
        import api.services.pipeline_runner as pr
        from core import db as core_db
        monkeypatch.setattr(core_db, "is_database_configured", lambda: False)
        assert pr._reexport_from_phase("v1") == 4

    def test_a_failing_guard_exports_only(self, monkeypatch):
        """Same rule, arrived at the hard way: if asking raises, the answer is the old
        behaviour, not a new one."""
        import api.services.pipeline_runner as pr
        from core import db as core_db

        def _boom():
            raise RuntimeError("database is down")

        monkeypatch.setattr(core_db, "is_database_configured", _boom)
        assert pr._reexport_from_phase("v1") == 4
