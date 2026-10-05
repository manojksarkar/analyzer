"""A whole flowchart saved in one call (REQ-API-08).

The API is per flowchart; the storage is per label. Both halves are tested here, because the
value of the split is exactly that they differ: one request, N rows, one rebuild, one picture.

This is also the only path that writes `slot_shape`, so REQ-ID-02's guard finally has a producer
as well as a consumer.
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
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine", "flowchart"))

from api.db.postgres import schema as s
from review import override_service as svc, slot

FID = "Comp|UnitA|doThing|"
OTHER = "Comp|UnitA|other|"
REL = "Sample/flowcharts/UnitA.json"
NODES = ("n0", "n1", "n2")


def _cfg(*ids):
    return {"entry": ids[0], "exits": [ids[-1]],
            "nodes": [{"id": i, "type": "ACTION", "label": "llm " + i, "rawCode": "c",
                       "line": 1, "endLine": 1} for i in ids],
            "edges": [{"source": a, "target": b, "label": None} for a, b in zip(ids, ids[1:])]}


@pytest.fixture
def conn():
    eng = sa.create_engine("sqlite://")
    s.metadata.create_all(eng)
    with eng.begin() as cx:
        now = datetime.datetime.now(datetime.timezone.utc)
        cx.execute(sa.insert(s.projects).values(id="p", name="p", created_at=now))
        cx.execute(sa.insert(s.versions).values(id="v1", project_id="p", version="v1",
                                                created_at=now))
        entries = [{"name": "ns::doThing", "functionKey": FID, "cfg": _cfg(*NODES),
                    "flowchart": "digraph G { stale }"},
                   {"name": "ns::other", "functionKey": OTHER, "cfg": _cfg("n0", "n1"),
                    "flowchart": "digraph G { other }"}]
        cx.execute(sa.insert(s.version_output_files).values(
            version_id="v1", rel_path=REL, content=json.dumps(entries), group_name="Sample"))
        yield cx


def _save(conn, labels, **kw):
    return svc.apply_flowchart_overrides(conn, "v1", FID, labels, **kw)


class TestTheWebPictureIsRedrawnAtOnce:
    """The web reader shows a flowchart only when its SVG was drawn from the stored DOT. A save
    rebuilds the DOT, so the page read "not drawn for this run" until a re-export."""

    @staticmethod
    def _fake_renderer(drawn):
        from core.flowchart_svg import svg_content_key

        def render(_project_root, jobs, **_kw):
            for dot, path in jobs:
                drawn.append((os.path.basename(path), dot))
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write('<!-- dot-key: %s -->\n<svg width="10pt" height="10pt"></svg>'
                             % svg_content_key(dot))
            return {}
        return render

    def _redraw(self, conn, tmp_path, monkeypatch):
        import views.flowcharts as fc
        from review import rerender
        drawn = []
        monkeypatch.setattr(fc, "render_dot_svgs", self._fake_renderer(drawn))
        counts = rerender.draw_web_svgs(conn, "v1", FID, str(tmp_path), PROJECT_ROOT)
        return counts, drawn

    def test_the_corrected_chart_is_drawn_from_the_stored_dot(self, conn, tmp_path, monkeypatch):
        from core.flowchart_svg import svg_content_key, svg_file_key, svg_file_name
        from review import rerender
        (tmp_path / "Sample" / "flowcharts").mkdir(parents=True)
        self._redraw(conn, tmp_path, monkeypatch)                  # the pictures before the save
        _save(conn, {"n1": "Check the flag"})
        counts, drawn = self._redraw(conn, tmp_path, monkeypatch)
        stored = rerender.find_flowchart_row(conn, "v1", FID)[2]
        dot = next(e for e in json.loads(stored) if e["functionKey"] == FID)["flowchart"]
        assert "Check the flag" in dot
        assert [name for name, _ in drawn] == [svg_file_name("UnitA", "ns::doThing")], \
            "only the corrected chart is drawn; its neighbour is still current"
        svg = tmp_path / "Sample" / "flowcharts" / svg_file_name("UnitA", "ns::doThing")
        assert svg_file_key(str(svg)) == svg_content_key(dot.strip())
        assert counts["drawn"] == 1 and counts["current"] == 1

    def test_the_disk_copy_follows_the_database(self, conn, tmp_path, monkeypatch):
        """The SVG pass and the backfill tool read disk: an old copy there redraws old labels."""
        from review import rerender
        (tmp_path / "Sample" / "flowcharts").mkdir(parents=True)
        _save(conn, {"n1": "Check the flag"})
        self._redraw(conn, tmp_path, monkeypatch)
        on_disk = (tmp_path / "Sample" / "flowcharts" / "UnitA.json").read_text(encoding="utf-8")
        assert on_disk == rerender.find_flowchart_row(conn, "v1", FID)[2]

    def test_no_output_tree_here_draws_nothing(self, conn, tmp_path, monkeypatch):
        """An API host without the version's output: the next re-export draws it instead."""
        counts, drawn = self._redraw(conn, tmp_path, monkeypatch)
        assert counts == {} and drawn == []


class TestOneCallManyLabels:
    def test_three_labels_write_three_rows(self, conn):
        out = _save(conn, {"n0": "Start here", "n1": "Check the flag", "n2": "Return"})
        assert list(out.applied) == ["n0", "n1", "n2"]
        rows = conn.execute(sa.select(s.text_overrides)).fetchall()
        assert len(rows) == 3
        assert {r.human_text for r in rows} == {"Start here", "Check the flag", "Return"}

    def test_each_row_keeps_its_own_llm_original(self, conn):
        """The per-label storage earning its keep: one sentence against one sentence, which is
        what REQ-TD-01 wants and what a whole-flowchart blob could not give."""
        _save(conn, {"n1": "Check the flag"})
        row = svc.get_override(conn, "v1", slot.NODE_LABEL, slot.for_node(FID, "n1"))
        assert row.llm_text == "llm n1"
        assert row.human_text == "Check the flag"

    def test_the_picture_is_rebuilt_once_for_the_whole_call(self, conn):
        out = _save(conn, {"n0": "A", "n1": "B", "n2": "C"})
        assert len(out.redrawn) == 1, "twelve labels must not mean twelve Graphviz runs"
        assert all(x in out.redrawn[0].dot for x in ("A", "B", "C"))

    def test_untouched_labels_keep_the_llm_text(self, conn):
        _save(conn, {"n1": "Only this one"})
        stored = json.loads(conn.execute(
            sa.select(s.version_output_files.c.content)).scalar())
        cfg = next(e for e in stored if e["functionKey"] == FID)["cfg"]
        assert {n["id"]: n["label"] for n in cfg["nodes"]} == {
            "n0": "llm n0", "n1": "Only this one", "n2": "llm n2"}


class TestTheShape:
    def test_every_row_of_one_flowchart_carries_the_same_shape(self, conn):
        """Read once per save, stamped on each row, so they cannot disagree about which graph
        they were written against (REQ-ID-02)."""
        out = _save(conn, {"n0": "A", "n2": "C"})
        shapes = {r.slot_shape for r in conn.execute(sa.select(s.text_overrides)).fetchall()}
        assert shapes == {out.slot_shape}
        assert out.slot_shape == slot.cfg_shape(NODES)

    def test_the_shape_describes_the_graph_not_the_edited_nodes(self, conn):
        """Editing one node must produce the same shape as editing three -- it is the graph's
        identity, not a record of the edit."""
        one = _save(conn, {"n1": "A"})
        three = _save(conn, {"n0": "X", "n1": "Y", "n2": "Z"})
        assert one.slot_shape == three.slot_shape

    def test_a_shape_is_actually_written(self, conn):
        """Until this entry point existed, slot_shape had a consumer and no producer."""
        _save(conn, {"n1": "A"})
        assert conn.execute(sa.select(s.text_overrides.c.slot_shape)).scalar()


class TestAllOrNothing:
    def test_a_node_that_does_not_exist_fails_the_whole_call(self, conn):
        with pytest.raises(svc.SlotUnknown) as exc:
            _save(conn, {"n1": "Good", "n99": "Nowhere"})
        assert "n99" in str(exc.value), "the response must name the offending node"
        assert conn.execute(sa.select(sa.func.count())
                            .select_from(s.text_overrides)).scalar() == 0

    def test_a_failed_call_leaves_the_picture_alone(self, conn):
        before = conn.execute(sa.select(s.version_output_files.c.content)).scalar()
        with pytest.raises(svc.SlotUnknown):
            _save(conn, {"n1": "Good", "n99": "Nowhere"})
        assert conn.execute(sa.select(s.version_output_files.c.content)).scalar() == before

    def test_one_empty_text_fails_the_whole_call(self, conn):
        with pytest.raises(svc.EmptyText) as exc:
            _save(conn, {"n0": "Fine", "n1": "   "})
        assert "n1" in str(exc.value)
        assert conn.execute(sa.select(sa.func.count())
                            .select_from(s.text_overrides)).scalar() == 0

    def test_an_unknown_flowchart_is_refused(self, conn):
        with pytest.raises(svc.SlotUnknown):
            svc.apply_flowchart_overrides(conn, "v1", "Comp|UnitZ|gone|", {"n0": "x"})

    def test_no_labels_is_refused(self, conn):
        with pytest.raises(svc.OverrideError):
            _save(conn, {})


class TestHistory:
    def test_history_is_per_label_not_per_save(self, conn):
        """REQ-ST-04. A call changing one label of three appends one history row, not three."""
        _save(conn, {"n1": "First"})
        _save(conn, {"n1": "Second"})
        n1 = svc.history_for(conn, "v1", slot.NODE_LABEL, slot.for_node(FID, "n1"))
        n0 = svc.history_for(conn, "v1", slot.NODE_LABEL, slot.for_node(FID, "n0"))
        assert [r.human_text for r in n1] == ["First", "Second"]
        assert n0 == []

    def test_the_llm_original_survives_repeated_saves(self, conn):
        for text in ("First", "Second", "Third"):
            _save(conn, {"n1": text})
        row = svc.get_override(conn, "v1", slot.NODE_LABEL, slot.for_node(FID, "n1"))
        assert row.llm_text == "llm n1", (
            "by the second save the stored CFG holds the HUMAN's text, so re-reading it would "
            "destroy the original and leave a human-vs-human pair")
        assert row.human_text == "Third"

    def test_first_edits_are_reported(self, conn):
        first = _save(conn, {"n0": "A", "n1": "B"})
        second = _save(conn, {"n1": "B2", "n2": "C"})
        assert set(first.first_edits) == {"n0", "n1"}
        assert set(second.first_edits) == {"n2"}

    def test_an_orphaned_label_starts_a_new_correction(self, conn):
        """The orphan was written for a graph that has since changed and is never applied, so
        the stored label is fresh LLM text -- the slot's original now. Keeping the orphan's
        `llm_text` would make an undo put back a label for a statement that is gone."""
        key = slot.for_node(FID, "n1")
        conn.execute(sa.insert(s.text_overrides).values(
            version_id="v1", slot_kind=slot.NODE_LABEL, slot_key=key,
            llm_text="label of the old graph", human_text="corrected, old graph",
            is_orphaned=True, updated_at=datetime.datetime.now(datetime.timezone.utc)))
        out = _save(conn, {"n1": "corrected, new graph"})
        assert set(out.first_edits) == {"n1"}
        row = svc.get_override(conn, "v1", slot.NODE_LABEL, key)
        assert (row.llm_text, row.human_text) == ("llm n1", "corrected, new graph")
        assert not row.is_orphaned


class TestACorrectionWrittenForAnotherNumbering:
    """A node-label row whose shape is not this graph's -- carried from a version whose builder
    numbered the nodes differently. Phase 3 drops it; a save on its flowchart holds the graph, so
    it orphans it there, and an undo refuses rather than write the old graph's LLM label onto the
    box that now holds its id (REQ-ID-02)."""

    OLD = slot.cfg_shape(["n0", "n1"])

    def _carried(self, conn, node, fid=FID, shape=None):
        conn.execute(sa.insert(s.text_overrides).values(
            version_id="v1", slot_kind=slot.NODE_LABEL, slot_key=slot.for_node(fid, node),
            llm_text="the old graph's llm " + node, human_text="Written for the old " + node,
            is_orphaned=False, slot_shape=shape or self.OLD,
            updated_at=datetime.datetime.now(datetime.timezone.utc)))

    def _row(self, conn, node, fid=FID):
        return svc.get_override(conn, "v1", slot.NODE_LABEL, slot.for_node(fid, node))

    def _stored(self, conn):
        return conn.execute(sa.select(s.version_output_files.c.content)).scalar()

    def test_a_save_on_its_flowchart_orphans_it(self, conn):
        self._carried(conn, "n1")
        _save(conn, {"n2": "Written for this n2"})
        assert self._row(conn, "n1").is_orphaned
        assert not self._row(conn, "n2").is_orphaned

    def test_then_it_reads_as_no_correction_in_force(self, conn):
        from review import catalog
        self._carried(conn, "n1")
        _save(conn, {"n2": "Written for this n2"})
        view = catalog.slot_view(slot.NODE_LABEL, slot.for_node(FID, "n1"), "llm n1",
                                 self._row(conn, "n1"))
        assert (view["isOverridden"], view["canUndo"], view["isOrphaned"]) == (False, False,
                                                                                True)

    def test_other_flowcharts_are_not_judged_by_this_graph(self, conn):
        self._carried(conn, "n1", fid=OTHER, shape=slot.cfg_shape(["n0", "n1"]))
        _save(conn, {"n2": "x"})
        assert not self._row(conn, "n1", fid=OTHER).is_orphaned

    def test_saving_that_node_starts_a_new_correction(self, conn):
        """Its original is THIS graph's LLM label, not the old graph's."""
        self._carried(conn, "n1")
        out = _save(conn, {"n1": "Written for this n1"})
        assert "n1" in out.first_edits
        row = self._row(conn, "n1")
        assert (row.llm_text, row.slot_shape, bool(row.is_orphaned)) == (
            "llm n1", slot.cfg_shape(NODES), False)

    def test_undoing_it_does_not_touch_the_new_graph(self, conn):
        self._carried(conn, "n1")
        before = self._stored(conn)
        with pytest.raises(svc.NothingToUndo) as exc:
            svc.undo_override(conn, "v1", slot.NODE_LABEL, slot.for_node(FID, "n1"))
        assert "numbering" in str(exc.value)
        assert self._stored(conn) == before
        assert conn.execute(sa.select(sa.func.count())
                            .select_from(s.text_override_history)).scalar() == 0

    def test_a_correction_written_for_this_graph_still_undoes(self, conn):
        _save(conn, {"n1": "Mine"})
        svc.undo_override(conn, "v1", slot.NODE_LABEL, slot.for_node(FID, "n1"))
        cfg = next(e for e in json.loads(self._stored(conn)) if e["functionKey"] == FID)["cfg"]
        assert {n["id"]: n["label"] for n in cfg["nodes"]}["n1"] == "llm n1"


class TestDerivation:
    def test_one_derivation_for_the_whole_call(self, conn):
        calls = []

        def _derive(*, version_id, slot_kind, flowchart_id):
            calls.append(flowchart_id)
            return ["flowcharts", "testSpecs"]

        out = _save(conn, {"n0": "A", "n1": "B", "n2": "C"}, derive=_derive)
        assert calls == [FID], "one call, one derivation, however many labels"
        assert list(out.views_derived) == ["flowcharts", "testSpecs"]

    def test_the_derivations_are_stamped(self, conn):
        _save(conn, {"n1": "A"}, derive=lambda **kw: ["flowcharts", "testSpecs"])
        names = {r.view_name for r in conn.execute(sa.select(s.view_derivations)).fetchall()}
        assert names == {"flowcharts", "testSpecs"}


class TestRenderPendingMeansThePictureIsOwed:
    """`redrawn` and "the image exists" are different facts, and conflating them misinforms
    the caller about the one thing this flag is for.

    `redraw_flowchart` rebuilds the stored JSON and DOT whether or not it has an output tree --
    the text is corrected everywhere it is READ from the database. Drawing the PNG needs
    somewhere to put it. An API host usually has no output tree, so it patches the text, leaves
    the picture owed, and the export blocks on that job (`REQ-IM-02`).

    The flag used to be `render_jobs and not redrawn`, which was therefore False on every save
    the API made: the caller was told no render was pending while the export blocked on one, and
    R9 said `pendingRenders: 1` at the same moment. Found by walking the UI flow end to end, not
    by a test -- every test here passed throughout.
    """

    def test_no_output_tree_leaves_the_picture_owed(self, conn):
        out = _save(conn, {"n1": "Corrected"})
        assert out.redrawn, "the stored DOT must still be rebuilt"
        assert out.render_jobs, "a job must be raised for the picture"
        assert out.render_pending is True

    def test_the_job_really_is_pending(self, conn):
        """The flag must agree with the row the EXPORT consults, or one of them is lying."""
        from review import render_queue
        out = _save(conn, {"n1": "Corrected"})
        assert render_queue.counts(conn, "v1").pending == len(out.render_jobs)
        assert out.render_pending is True

    def test_it_is_not_derived_from_redrawn(self, conn):
        """The specific mistake: `redrawn` is non-empty here, and the picture is still owed."""
        out = _save(conn, {"n1": "Corrected"})
        assert bool(out.redrawn) and out.render_pending is True

    def test_an_empty_save_is_refused_rather_than_owing_a_picture(self, conn):
        """Not "nothing happened" -- a save with no labels is a caller mistake, and answering it
        with a successful no-op would raise a render job for a picture nobody changed."""
        with pytest.raises(svc.OverrideError):
            _save(conn, {})


class TestAFlowchartWithNoStoredGraph:
    """`cfg` has only been written since 2026-09-01 (`3355930`). A version generated before that
    has the picture and the DOT but not the graph they were built from.

    Found on a real project: every flowchart reported `nodeCount: 0`, R7 returned an empty label
    list, and R8 answered "has no node(s) N2" — which blames the caller's node id for the absence
    of the whole graph. Three different ways of not saying the one useful thing.

    This is not a failure to repair automatically: the CFG comes back by re-deriving the version,
    which the message says.
    """

    def _no_graph(self, conn):
        """A stored flowchart exactly as an older build wrote it: key, name, DOT — no cfg."""
        conn.execute(sa.update(s.version_output_files)
                     .where(s.version_output_files.c.version_id == "v1")
                     .values(content=json.dumps([{ "functionKey": FID, "name": "doThing",
                                                   "flowchart": "digraph {}"}])))

    def test_a_save_says_what_is_actually_wrong(self, conn):
        self._no_graph(conn)
        with pytest.raises(svc.NoStoredGraph) as exc:
            _save(conn, {"n1": "Corrected"})
        msg = str(exc.value)
        assert "no stored graph" in msg and "reexport" in msg

    def test_it_is_409_not_404(self, conn):
        """404 would say the flowchart is not there. It is there; its graph is not, and that is
        a different thing to fix."""
        self._no_graph(conn)
        with pytest.raises(svc.OverrideError) as exc:
            _save(conn, {"n1": "Corrected"})
        assert getattr(exc.value, "status", None) == 409

    def test_it_does_not_blame_the_node(self, conn):
        self._no_graph(conn)
        with pytest.raises(svc.NoStoredGraph) as exc:
            _save(conn, {"n1": "Corrected"})
        assert "no node" not in str(exc.value).lower()

    def test_nothing_is_written(self, conn):
        """It must refuse before touching the override table, or a correction would be stored
        against a graph that cannot carry it."""
        self._no_graph(conn)
        with pytest.raises(svc.NoStoredGraph):
            _save(conn, {"n1": "Corrected"})
        n = conn.execute(sa.select(sa.func.count())
                         .select_from(s.text_overrides)).scalar()
        assert n == 0
