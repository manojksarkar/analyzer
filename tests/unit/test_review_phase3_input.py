"""A correction survives a regeneration (REQ-AP-05).

The failure this prevents is the whole reason node labels are not stored in the view's output:

    Monday   a reviewer fixes n7. The flowchart JSON now says the corrected thing.
    Tuesday  someone regenerates. Phase 3 rebuilds that JSON from the CFG and asks the LLM
             for labels again. n7 is back to the LLM's wording, with no error anywhere.

So the corrections are an INPUT to Phase 3, applied after the engine has written its JSON and
before any PNG is drawn. The picture is then right the first time -- no second write, no
re-render.
"""
import json
import os
import re
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine", "flowchart"))

from review import redraw
from views import flowcharts

FID = "Comp|UnitA|doThing|"
OTHER = "Comp|UnitB|other|"


def _cfg_overrides(by_flowchart):
    """A run config carrying node-label corrections, in the shape `phase3_overrides.from_config`
    defines -- keyed by kind, so both Phase-3 views read one shape."""
    from review.phase3_overrides import CONFIG_KEY, NODE_LABEL_KIND
    return {CONFIG_KEY: {NODE_LABEL_KIND: by_flowchart}}


def _cfg(*ids):
    return {"entry": ids[0], "exits": [ids[-1]],
            "nodes": [{"id": i, "type": "ACTION", "label": "llm " + i, "rawCode": "c",
                       "line": 1, "endLine": 1} for i in ids],
            "edges": [{"source": a, "target": b, "label": None} for a, b in zip(ids, ids[1:])]}


def _unit_file(tmp_path, name, fid, *node_ids):
    entries = [{"name": "ns::" + name, "functionKey": fid, "cfg": _cfg(*node_ids),
                "flowchart": "digraph G { generated }"}]
    p = tmp_path / (name + ".json")
    p.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    return p


class TestApplyingAcrossAnOutputDirectory:
    def test_a_correction_lands_in_the_regenerated_json(self, tmp_path):
        f = _unit_file(tmp_path, "UnitA", FID, "n0", "n1", "n2")
        done = redraw.apply_to_output_dir(str(tmp_path), {FID: {"n1": "Check the flag"}})
        assert done == [FID]
        entry = json.loads(f.read_text(encoding="utf-8"))[0]
        assert {n["id"]: n["label"] for n in entry["cfg"]["nodes"]}["n1"] == "Check the flag"

    def test_the_dot_is_rebuilt_so_the_picture_is_right_first_time(self, tmp_path):
        """If only the CFG moved, the PNG would be drawn from the generated DOT and the
        picture would still show the LLM's words."""
        f = _unit_file(tmp_path, "UnitA", FID, "n0", "n1")
        redraw.apply_to_output_dir(str(tmp_path), {FID: {"n1": "Check the flag"}})
        entry = json.loads(f.read_text(encoding="utf-8"))[0]
        assert entry["flowchart"] != "digraph G { generated }"
        assert "Check the flag" in entry["flowchart"]

    def test_units_with_no_corrections_are_untouched(self, tmp_path):
        a = _unit_file(tmp_path, "UnitA", FID, "n0", "n1")
        b = _unit_file(tmp_path, "UnitB", OTHER, "n0", "n1")
        before = b.read_text(encoding="utf-8")
        redraw.apply_to_output_dir(str(tmp_path), {FID: {"n1": "Corrected"}})
        assert b.read_text(encoding="utf-8") == before
        assert "Corrected" in a.read_text(encoding="utf-8")

    def test_the_summary_file_is_skipped(self, tmp_path):
        (tmp_path / "_summary.json").write_text(
            json.dumps([{"functionKey": FID, "cfg": _cfg("n0")}]), encoding="utf-8")
        assert redraw.apply_to_output_dir(str(tmp_path), {FID: {"n0": "x"}}) == []

    def test_an_unreadable_unit_does_not_stop_the_others(self, tmp_path):
        """A generation that has already paid for the parse and the LLM must not be lost to one
        bad file."""
        (tmp_path / "Broken.json").write_text("{not json", encoding="utf-8")
        _unit_file(tmp_path, "UnitA", FID, "n0", "n1")
        assert redraw.apply_to_output_dir(str(tmp_path), {FID: {"n1": "Corrected"}}) == [FID]

    def test_no_corrections_touches_nothing(self, tmp_path):
        f = _unit_file(tmp_path, "UnitA", FID, "n0", "n1")
        before = f.read_text(encoding="utf-8")
        assert redraw.apply_to_output_dir(str(tmp_path), {}) == []
        assert f.read_text(encoding="utf-8") == before

    def test_a_missing_directory_is_not_an_error(self):
        assert redraw.apply_to_output_dir("/no/such/dir", {FID: {"n0": "x"}}) == []


class TestTheViewHook:
    """The view reads corrections from config, the same way it reads component scoping, so it
    stays a pure function of the model plus config and never touches a database."""

    def test_corrections_arrive_through_config(self, tmp_path):
        _unit_file(tmp_path, "UnitA", FID, "n0", "n1")
        n = flowcharts._apply_text_overrides(
            str(tmp_path), _cfg_overrides({FID: {"n1": "Corrected"}}))
        assert n == 1
        assert "Corrected" in (tmp_path / "UnitA.json").read_text(encoding="utf-8")

    def test_an_ordinary_run_with_no_corrections_does_nothing(self, tmp_path):
        f = _unit_file(tmp_path, "UnitA", FID, "n0", "n1")
        before = f.read_text(encoding="utf-8")
        assert flowcharts._apply_text_overrides(str(tmp_path), {}) == 0
        assert flowcharts._apply_text_overrides(str(tmp_path), None) == 0
        assert f.read_text(encoding="utf-8") == before

    def test_a_failure_does_not_fail_the_run(self, tmp_path, monkeypatch):
        """Losing a whole generation because one correction could not be applied would cost far
        more than the correction is worth."""
        _unit_file(tmp_path, "UnitA", FID, "n0", "n1")

        def _boom(*a, **k):
            raise RuntimeError("no")

        monkeypatch.setattr(redraw, "apply_to_output_dir", _boom)
        assert flowcharts._apply_text_overrides(
            str(tmp_path), _cfg_overrides({FID: {"n1": "x"}})) == 0


class TestItIsActuallyWiredIn:
    """A helper that works and is never called is worse than no helper: everything passes and
    the corrections silently stop reaching the document. This codebase has had exactly that --
    a guard whose import moved, so it quietly stopped running and nothing failed.

    `run()` cannot be invoked here (it needs a model, a subprocess and Node), so the call site is
    checked in the source, the same way the exporter is checked for LLM calls it must not make.
    """

    @staticmethod
    def _source():
        return open(os.path.join(PROJECT_ROOT, "engine", "views", "flowcharts.py"),
                    encoding="utf-8").read()

    #: The indented CALL. Matching the bare name would also match `def _apply_text_overrides(
    #: out_dir, config)`, which made the first version of this test unable to fail at all.
    CALL = re.compile(r"^[ 	]+_apply_text_overrides\(out_dir, config\)", re.M)

    def test_the_view_calls_it(self):
        assert self.CALL.search(self._source()), (
            "the flowcharts view no longer applies text overrides, so every correction to a node "
            "label is silently dropped by the next regeneration (REQ-AP-05)")

    def test_the_check_above_can_actually_fail(self):
        """The first version of it matched the function DEFINITION as well as the call, so it
        passed whatever the view did. A guard that cannot fail is worse than none -- it reports
        safety it is not providing."""
        assert not self.CALL.search("def _apply_text_overrides(out_dir, config) -> int:")
        assert self.CALL.search("    _apply_text_overrides(out_dir, config)")

    def test_it_is_called_before_anything_is_rendered(self):
        """Applying after the PNGs are drawn would leave the picture showing the LLM's wording
        while the JSON showed the human's -- and would need a second render to fix."""
        src = self._source()
        call = self.CALL.search(src)
        assert call, "no call site to order"
        assert call.start() < src.index("if render_dot_cached("), (
            "corrections are applied after the pictures are drawn; the flowchart image would "
            "carry the old label")


class TestOneImplementationNotTwo:
    def test_the_save_path_and_the_run_path_produce_the_same_dot(self, tmp_path):
        """A save redraws a flowchart and so does a regeneration. Two implementations of "apply
        a correction" would drift, and the document would depend on which route last touched it.
        Both go through `patch_unit_flowcharts`, so this is structural -- the test says so."""
        entries = [{"name": "ns::doThing", "functionKey": FID, "cfg": _cfg("n0", "n1", "n2"),
                    "flowchart": "digraph G { generated }"}]
        content = json.dumps(entries, indent=2)
        labels = {"n1": "Check the write-protect flag"}

        # the save route
        saved = redraw.patch_unit_flowcharts(content, "UnitA", {FID: labels})

        # the Phase-3 route
        f = tmp_path / "UnitA.json"
        f.write_text(content, encoding="utf-8")
        redraw.apply_to_output_dir(str(tmp_path), {FID: labels})
        regenerated = f.read_text(encoding="utf-8")

        assert saved.content == regenerated
        assert json.loads(regenerated)[0]["flowchart"] == saved.redrawn[0].dot
