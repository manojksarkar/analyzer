"""Pictures waiting to be redrawn, and the export refusing to go out ahead of them.

REQ-IM-01/02/03. Correcting a flowchart node label changes the picture, not only the text. The
failure this guards is narrow and quiet: export a second after an edit and the document carries the
new wording with the old image -- the split-origin shape that once left a stored graph and a
document picture coming from different versions.

Two judgement calls are pinned here because both could reasonably have gone the other way:

  a PENDING render blocks the export; a FAILED one does not. Blocking on a failure would make one
  unrenderable flowchart permanently unexportable;

  two corrections to one flowchart make TWO jobs. Collapsing them would let a render that started
  before the second edit satisfy it.
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
from review import export_guard as guard, override_service as svc, render_queue as rq, slot

FID = "Comp|UnitA|ns::doThing|void"
REL = "Sample/flowcharts/UnitA.json"
T0 = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


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
        cx.execute(sa.insert(s.version_output_files).values(
            version_id="v1", rel_path=REL, group_name="Sample",
            content=json.dumps([{"name": "ns::doThing", "functionKey": FID,
                                 "cfg": _cfg("n0", "n1"),
                                 "flowchart": "digraph G { n0 -> n1; }"}])))
        yield cx


class TestTheQueue:
    def test_a_job_is_recorded_and_counted(self, conn):
        rq.enqueue(conn, "v1", FID, "UnitA_doThing.png")
        assert rq.counts(conn, "v1") == rq.Counts(pending=1, failed=0)

    def test_completing_clears_it(self, conn):
        job = rq.enqueue(conn, "v1", FID)
        rq.complete(conn, job)
        assert rq.counts(conn, "v1") == rq.Counts(pending=0, failed=0)

    def test_a_failure_is_kept_with_its_reason(self, conn):
        job = rq.enqueue(conn, "v1", FID)
        rq.complete(conn, job, error="graphviz not found")
        assert rq.counts(conn, "v1") == rq.Counts(pending=0, failed=1)
        row = conn.execute(sa.select(s.render_jobs)).first()
        assert row.error == "graphviz not found" and row.finished_at is not None

    def test_two_corrections_make_two_jobs(self, conn):
        """Not collapsed. A render that began before the second edit would otherwise satisfy it,
        leaving the picture one edit behind with nothing pending to say so."""
        rq.enqueue(conn, "v1", FID)
        rq.enqueue(conn, "v1", FID)
        assert rq.counts(conn, "v1").pending == 2

    def test_another_version_is_not_counted(self, conn):
        conn.execute(sa.insert(s.versions).values(
            id="v2", project_id="p", version="v2",
            created_at=datetime.datetime.now(datetime.timezone.utc)))
        rq.enqueue(conn, "v2", FID)
        assert rq.counts(conn, "v1").pending == 0

    def test_a_version_with_no_jobs_costs_one_query(self, conn):
        assert rq.counts(conn, "v1") == rq.Counts(0, 0)
        assert rq.pending_jobs(conn, "v1") == []


class TestTheExportGuard:
    def _correct(self, conn):
        conn.execute(sa.insert(s.text_overrides).values(
            version_id="v1", slot_kind=slot.DESCRIPTION, slot_key="k", llm_text="a",
            human_text="b", is_orphaned=False, updated_at=T0))
        guard.stamp_pipeline_derivation(conn, "v1", now=T0 + datetime.timedelta(days=1))

    def test_a_pending_render_blocks_the_export(self, conn):
        """REQ-IM-02. The text is fresh -- the derivation is newer than the correction -- and the
        export must still refuse, because the picture is not."""
        self._correct(conn)
        assert not guard.staleness(conn, "v1").is_stale
        rq.enqueue(conn, "v1", FID)
        st = guard.staleness(conn, "v1")
        assert st.is_stale and st.pending_renders == 1
        assert "still being drawn" in st.reason

    def test_finishing_the_render_unblocks_it(self, conn):
        self._correct(conn)
        job = rq.enqueue(conn, "v1", FID)
        assert guard.staleness(conn, "v1").is_stale
        rq.complete(conn, job)
        assert not guard.staleness(conn, "v1").is_stale

    def test_a_failed_render_does_not_block_for_ever(self, conn):
        """Blocking on a failure would make one unrenderable flowchart permanently
        unexportable -- worse than the problem. It is reported instead."""
        self._correct(conn)
        job = rq.enqueue(conn, "v1", FID)
        rq.complete(conn, job, error="graphviz not found")
        st = guard.staleness(conn, "v1")
        assert st.is_stale is False
        assert st.failed_renders == 1
        assert "could not be drawn" in st.explain()

    def test_a_version_nobody_corrected_is_unaffected(self, conn):
        rq.enqueue(conn, "v1", FID)
        assert guard.staleness(conn, "v1").is_stale is False

    def test_assert_exportable_refuses_while_a_render_is_pending(self, conn):
        self._correct(conn)
        rq.enqueue(conn, "v1", FID)
        with pytest.raises(guard.StaleExport):
            guard.assert_exportable(conn, "v1")


class TestTheWorker:
    def test_it_draws_and_completes(self, conn, tmp_path, monkeypatch):
        drawn = {}

        def _fake_render(project_root, fc_dir, item):
            drawn["png"] = item.png_name
            drawn["dot"] = item.dot
            return True

        from review import rerender
        monkeypatch.setattr(rerender, "render_png", _fake_render)
        job = rq.enqueue(conn, "v1", FID, "UnitA_doThing.png")
        assert rq.run_pending(conn, "v1", output_dir=str(tmp_path),
                              project_root=str(tmp_path)) == [job]
        assert rq.counts(conn, "v1") == rq.Counts(0, 0)
        assert drawn["png"] == "UnitA_doThing.png"

    def test_it_draws_the_CURRENT_graph_not_the_one_at_queue_time(self, conn, tmp_path,
                                                                 monkeypatch):
        """By the time a job runs the flowchart may have been corrected again. The picture must
        match what the document will show, not what was true when the job was made."""
        seen = {}
        from review import rerender
        monkeypatch.setattr(rerender, "render_png",
                            lambda pr, d, item: seen.setdefault("dot", item.dot) or True)
        rq.enqueue(conn, "v1", FID)
        conn.execute(sa.update(s.version_output_files).values(
            content=json.dumps([{"name": "ns::doThing", "functionKey": FID,
                                 "cfg": _cfg("n0", "n1"),
                                 "flowchart": "digraph G { CORRECTED }"}])))
        rq.run_pending(conn, "v1", output_dir=str(tmp_path), project_root=str(tmp_path))
        assert "CORRECTED" in seen["dot"]

    def test_one_bad_job_does_not_strand_the_others(self, conn, tmp_path, monkeypatch):
        from review import rerender
        monkeypatch.setattr(rerender, "render_png", lambda *a, **k: True)
        bad = rq.enqueue(conn, "v1", "Comp|UnitZ|gone|")
        good = rq.enqueue(conn, "v1", FID)
        assert sorted(rq.run_pending(conn, "v1", output_dir=str(tmp_path),
                                     project_root=str(tmp_path))) == sorted([bad, good])
        assert rq.counts(conn, "v1") == rq.Counts(pending=0, failed=1)

    def test_a_render_that_raises_is_recorded_not_swallowed(self, conn, tmp_path, monkeypatch):
        from review import rerender
        monkeypatch.setattr(rerender, "render_png",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        rq.enqueue(conn, "v1", FID)
        rq.run_pending(conn, "v1", output_dir=str(tmp_path), project_root=str(tmp_path))
        row = conn.execute(sa.select(s.render_jobs)).first()
        assert row.status == rq.FAILED and "boom" in row.error

    def test_a_render_that_produces_nothing_is_a_failure(self, conn, tmp_path, monkeypatch):
        from review import rerender
        monkeypatch.setattr(rerender, "render_png", lambda *a, **k: False)
        rq.enqueue(conn, "v1", FID)
        rq.run_pending(conn, "v1", output_dir=str(tmp_path), project_root=str(tmp_path))
        assert rq.counts(conn, "v1") == rq.Counts(pending=0, failed=1)


class TestThroughTheSave:
    def test_a_save_raises_a_job(self, conn):
        out = svc.apply_flowchart_overrides(conn, "v1", FID, {"n1": "Corrected"})
        assert len(out.render_jobs) == 1

    def test_a_save_with_no_output_tree_leaves_it_pending(self, conn):
        """The API host has no output dir. The text is stored and correct everywhere it is read
        from the database; the picture is owed, and the export knows it."""
        svc.apply_flowchart_overrides(conn, "v1", FID, {"n1": "Corrected"})
        assert rq.counts(conn, "v1").pending == 1
        assert guard.staleness(conn, "v1").is_stale

    def test_a_save_that_drew_the_picture_marks_it_done(self, conn, tmp_path, monkeypatch):
        from review import rerender
        monkeypatch.setattr(rerender, "render_png", lambda *a, **k: True)
        svc.apply_flowchart_overrides(conn, "v1", FID, {"n1": "Corrected"},
                                      output_dir=str(tmp_path), project_root=str(tmp_path))
        assert rq.counts(conn, "v1") == rq.Counts(pending=0, failed=0)

    def test_twelve_labels_raise_one_job(self, conn):
        """One picture, one job -- the same saving the one-call API buys everywhere else."""
        out = svc.apply_flowchart_overrides(conn, "v1", FID, {"n0": "A", "n1": "B"})
        assert len(out.render_jobs) == 1
