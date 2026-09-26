"""Redrawing one flowchart after a correction (REQ-AP-06).

The save path never runs the pipeline: it reads the stored CFG, patches the label, regenerates the
DOT and re-renders the picture. Everything here is about that staying honest -- the graph and the
DOT moving together, an untouched unit not being rewritten, and the picture being rebuilt rather
than string-patched.
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
from review import rerender

FID = "Comp|UnitA|doThing|"
OTHER = "Comp|UnitA|other|"
REL = "Sample/flowcharts/UnitA.json"


def _cfg(*ids):
    return {"entry": ids[0],
            "exits": [ids[-1]],
            "nodes": [{"id": i, "type": "ACTION", "label": "llm " + i, "rawCode": "code " + i,
                       "line": 1, "endLine": 1} for i in ids],
            "edges": [{"source": a, "target": b, "label": None}
                      for a, b in zip(ids, ids[1:])]}


def _entries():
    return [{"name": "ns::doThing", "functionKey": FID, "cfg": _cfg("n0", "n1", "n2"),
             "flowchart": "digraph G { stale }"},
            {"name": "ns::other", "functionKey": OTHER, "cfg": _cfg("n0", "n1"),
             "flowchart": "digraph G { other }"}]


def _content():
    return json.dumps(_entries(), indent=2)


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
            version_id="v1", rel_path=REL, content=_content(), group_name="Sample"))
        yield cx


class TestPatchingAUnitFile:
    def test_the_label_and_the_dot_move_together(self):
        """The stored DOT is what the PNG render reads. If the CFG moves and the DOT does not,
        the picture and the graph disagree -- the two-copies failure in miniature."""
        out = rerender.patch_unit_flowcharts(_content(), "UnitA", {FID: {"n1": "Corrected"}})
        entries = json.loads(out.content)
        entry = next(e for e in entries if e["functionKey"] == FID)
        labels = {n["id"]: n["label"] for n in entry["cfg"]["nodes"]}
        assert labels["n1"] == "Corrected"
        assert entry["flowchart"] != "digraph G { stale }"
        assert "Corrected" in entry["flowchart"]

    def test_the_dot_is_rebuilt_not_string_patched(self):
        """A long correction must be re-wrapped by the builder. If it appears verbatim, someone
        pasted it into the DOT text and the wrapping rules now live in two places."""
        long_text = ("Check whether the write-protect flag is set on the currently selected "
                     "flash die before issuing the erase")
        out = rerender.patch_unit_flowcharts(_content(), "UnitA", {FID: {"n1": long_text}})
        dot = next(e for e in json.loads(out.content)
                   if e["functionKey"] == FID)["flowchart"]
        assert long_text not in dot
        assert "write-protect" in dot

    def test_an_untouched_flowchart_is_left_alone(self):
        out = rerender.patch_unit_flowcharts(_content(), "UnitA", {FID: {"n1": "Corrected"}})
        other = next(e for e in json.loads(out.content) if e["functionKey"] == OTHER)
        assert other["flowchart"] == "digraph G { other }", (
            "an unedited flowchart's DOT was regenerated, so its picture would re-render too")

    def test_a_unit_with_no_corrections_is_byte_identical(self):
        """Not merely equivalent. Re-serialising JSON nobody edited rewrites the row on every
        save and makes the table useless for seeing what actually changed."""
        original = _content()
        assert rerender.patch_unit_flowcharts(original, "UnitA", {}).content is original
        out = rerender.patch_unit_flowcharts(original, "UnitA",
                                             {"Comp|UnitZ|nothere|": {"n0": "x"}})
        assert out.content == original and out.redrawn == ()

    def test_what_was_redrawn_is_reported(self):
        out = rerender.patch_unit_flowcharts(_content(), "UnitA", {FID: {"n1": "Corrected"}})
        assert [r.flowchart_id for r in out.redrawn] == [FID]
        assert out.redrawn[0].function_name == "ns::doThing"
        assert out.redrawn[0].png_name.startswith("UnitA_")
        assert out.redrawn[0].png_name.endswith(".png")

    def test_several_labels_in_one_call_redraw_once(self):
        """REQ-API-08: a flowchart is saved in one call, so twelve labels must not mean twelve
        rebuilds of the same graph."""
        out = rerender.patch_unit_flowcharts(
            _content(), "UnitA", {FID: {"n0": "A", "n1": "B", "n2": "C"}})
        assert len(out.redrawn) == 1
        dot = out.redrawn[0].dot
        assert all(x in dot for x in ("A", "B", "C"))

    def test_unreadable_json_is_an_error_not_a_silent_skip(self):
        with pytest.raises(rerender.RerenderError):
            rerender.patch_unit_flowcharts("{not json", "UnitA", {FID: {"n1": "x"}})
        with pytest.raises(rerender.RerenderError):
            rerender.patch_unit_flowcharts('{"a": 1}', "UnitA", {FID: {"n1": "x"}})


class TestThePngName:
    def test_it_matches_the_view_spelling(self):
        """flowcharts.py builds `<unit>_<safe_filename(func)>.png`. Two spellings of one filename
        is how a re-render writes a picture the document never looks at."""
        sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))
        from utils import safe_filename
        assert rerender.png_name_for("UnitA", "ns::doThing") == \
            "UnitA_%s.png" % safe_filename("ns::doThing")


class TestFindingTheRow:
    def test_the_unit_file_holding_a_flowchart_is_found(self, conn):
        rel, unit, content = rerender.find_flowchart_row(conn, "v1", FID)
        assert (rel, unit) == (REL, "UnitA")
        assert FID in content

    def test_an_unknown_flowchart_is_not_found(self, conn):
        assert rerender.find_flowchart_row(conn, "v1", "Comp|UnitZ|gone|") is None

    def test_the_summary_file_is_not_mistaken_for_a_unit(self, conn):
        conn.execute(sa.insert(s.version_output_files).values(
            version_id="v1", rel_path="Sample/flowcharts/_summary.json",
            content=json.dumps([{"functionKey": "Comp|UnitZ|x|"}]), group_name="Sample"))
        assert rerender.find_flowchart_row(conn, "v1", "Comp|UnitZ|x|") is None

    def test_a_non_flowchart_row_is_ignored(self, conn):
        conn.execute(sa.insert(s.version_output_files).values(
            version_id="v1", rel_path="Sample/interface_tables.json",
            content=json.dumps([{"functionKey": "Comp|UnitQ|q|"}]), group_name="Sample"))
        assert rerender.find_flowchart_row(conn, "v1", "Comp|UnitQ|q|") is None


class TestTheWholeRedraw:
    def test_the_stored_row_is_updated(self, conn):
        done = rerender.redraw_flowchart(conn, "v1", FID, {"n1": "Corrected"})
        assert [r.flowchart_id for r in done] == [FID]
        stored = json.loads(rerender.read_output_row(conn, "v1", REL))
        entry = next(e for e in stored if e["functionKey"] == FID)
        assert {n["id"]: n["label"] for n in entry["cfg"]["nodes"]}["n1"] == "Corrected"

    def test_no_output_dir_means_no_image_but_the_text_still_lands(self, conn):
        """An API host with no output tree: the correction is in the database, so every reader
        shows it, and the picture is regenerated by the next run. The caller still gets the list
        and can queue a render, so nothing is silent."""
        done = rerender.redraw_flowchart(conn, "v1", FID, {"n1": "Corrected"})
        assert done
        assert "Corrected" in rerender.read_output_row(conn, "v1", REL)

    def test_a_correction_for_a_node_that_is_gone_changes_nothing(self, conn):
        before = rerender.read_output_row(conn, "v1", REL)
        assert rerender.redraw_flowchart(conn, "v1", FID, {"n99": "Nowhere"}) == ()
        assert rerender.read_output_row(conn, "v1", REL) == before

    def test_an_unknown_flowchart_raises(self, conn):
        with pytest.raises(rerender.RerenderError):
            rerender.redraw_flowchart(conn, "v1", "Comp|UnitZ|gone|", {"n0": "x"})

    def test_only_the_named_flowchart_changes(self, conn):
        rerender.redraw_flowchart(conn, "v1", FID, {"n1": "Corrected"})
        stored = json.loads(rerender.read_output_row(conn, "v1", REL))
        other = next(e for e in stored if e["functionKey"] == OTHER)
        assert other["flowchart"] == "digraph G { other }"
        assert all(n["label"].startswith("llm ") for n in other["cfg"]["nodes"])


class TestTheRowWriter:
    def test_an_existing_row_is_replaced_not_duplicated(self, conn):
        rerender.write_output_row(conn, "v1", REL, "first")
        rerender.write_output_row(conn, "v1", REL, "second")
        rows = conn.execute(sa.select(s.version_output_files)
                            .where(s.version_output_files.c.rel_path == REL)).fetchall()
        assert len(rows) == 1 and rows[0].content == "second"

    def test_a_missing_row_is_created_with_its_group(self, conn):
        rerender.write_output_row(conn, "v1", "Sample/flowcharts/UnitB.json", "[]")
        row = conn.execute(sa.select(s.version_output_files)
                           .where(s.version_output_files.c.rel_path ==
                                  "Sample/flowcharts/UnitB.json")).first()
        assert row.content == "[]" and row.group_name == "Sample"
