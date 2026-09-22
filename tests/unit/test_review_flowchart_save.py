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
