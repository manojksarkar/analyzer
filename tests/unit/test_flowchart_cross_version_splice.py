"""A cross-version flowchart splice must land BOTH halves: the graph and the images.

Measured on a real project (v5 baseline, v7 correct, v8 second incremental off v5):

    GCM_SetGcStartTime   DOT came from v5, PNG came from v7
    GCM_SetGcEndTime     DOT came from v5, PNG came from v5   (split into 2 parts)

Two independent defects, both silent:

  * the merge read `fresh` straight out of out_dir, but _carry_forward_flowcharts has
    already copied every BASELINE json there. For a unit whose changed functions were all
    diverted to cross-version reuse the engine writes nothing, so those baseline entries
    were treated as freshly generated and beat the x-ver entry in `fresh > x-ver >
    baseline`. A cross-version DOT could never win.

  * the image copy handled one filename, <stem>_<qn>.png. A flowchart too tall for a
    single image is written as _part_1_of_N.png ... and no plain .png exists, so nothing
    was copied and the carried baseline images stayed.

Together they produced a stored graph and a document picture from different versions.
"""
import json
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from views.flowcharts import _merge_incremental_flowcharts, _splice_function_pngs


def _write_json(path, entries):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f)


def _entries(path):
    with open(path, encoding="utf-8") as f:
        return {e["name"]: e["flowchart"] for e in json.load(f)}


class TestCrossVersionDotWins:
    """x-ver must beat a carried baseline entry; only real engine output outranks it."""

    def _setup(self, tmp_path, *, engine_regenerated):
        base_fc = str(tmp_path / "base")
        out_dir = str(tmp_path / "out")
        unit = "MGCM_Completion"
        baseline = [{"name": "GCM_SetGcEndTime", "flowchart": "BASELINE_v5"}]
        _write_json(os.path.join(base_fc, unit + ".json"), baseline)
        # What carry-forward does before the engine runs: the baseline json is in out_dir.
        _write_json(os.path.join(out_dir, unit + ".json"), baseline)
        return {
            "mode": "function",
            "base_fc": base_fc,
            "changed_units": {unit},
            "current_by_unit": {unit: {"GCM_SetGcEndTime"}},
            # The engine was handed this function only when it actually regenerated it.
            "fresh_pairs": {(unit, "GCM_SetGcEndTime")} if engine_regenerated else set(),
            "xver_by_unit": {unit: {"GCM_SetGcEndTime": {"name": "GCM_SetGcEndTime",
                                                         "flowchart": "XVER_v7"}}},
        }, out_dir, unit

    def test_xver_beats_a_carried_baseline_entry(self, tmp_path):
        inc, out_dir, unit = self._setup(tmp_path, engine_regenerated=False)
        _merge_incremental_flowcharts(inc, out_dir)
        got = _entries(os.path.join(out_dir, unit + ".json"))
        assert got["GCM_SetGcEndTime"] == "XVER_v7", (
            "the baseline json sitting in out_dir is carry-forward, not engine output")

    def test_real_engine_output_still_beats_xver(self, tmp_path):
        inc, out_dir, unit = self._setup(tmp_path, engine_regenerated=True)
        # The engine really did rewrite the unit json for this function.
        _write_json(os.path.join(out_dir, unit + ".json"),
                    [{"name": "GCM_SetGcEndTime", "flowchart": "FRESH"}])
        _merge_incremental_flowcharts(inc, out_dir)
        got = _entries(os.path.join(out_dir, unit + ".json"))
        assert got["GCM_SetGcEndTime"] == "FRESH", "fresh > x-ver must still hold"

    def test_unchanged_function_keeps_the_baseline(self, tmp_path):
        inc, out_dir, unit = self._setup(tmp_path, engine_regenerated=False)
        inc["xver_by_unit"] = {}                      # nothing spliced
        _merge_incremental_flowcharts(inc, out_dir)
        got = _entries(os.path.join(out_dir, unit + ".json"))
        assert got["GCM_SetGcEndTime"] == "BASELINE_v5"


class TestSplitPngsAreSpliced:
    """The image copy must take every part of a split flowchart, not just <stem>_<qn>.png."""

    def _run_copy(self, out_dir, src_dir, stem, qn):
        return _splice_function_pngs(src_dir, out_dir, stem, qn)

    def _dirs(self, tmp_path, carried, source):
        out_dir, src_dir = str(tmp_path / "out"), str(tmp_path / "src")
        for d in (out_dir, src_dir):
            os.makedirs(d, exist_ok=True)
        for name, body in carried.items():
            open(os.path.join(out_dir, name), "wb").write(body)
        for name, body in source.items():
            open(os.path.join(src_dir, name), "wb").write(body)
        return out_dir, src_dir

    def test_every_part_is_copied(self, tmp_path):
        stem, qn = "MGCM_Completion", "GCM_SetGcEndTime"
        out_dir, src_dir = self._dirs(
            tmp_path,
            {f"{stem}_{qn}_part_1_of_2.png": b"old1", f"{stem}_{qn}_part_2_of_2.png": b"old2"},
            {f"{stem}_{qn}_part_1_of_2.png": b"new1", f"{stem}_{qn}_part_2_of_2.png": b"new2"})
        self._run_copy(out_dir, src_dir, stem, qn)
        assert open(os.path.join(out_dir, f"{stem}_{qn}_part_1_of_2.png"), "rb").read() == b"new1"
        assert open(os.path.join(out_dir, f"{stem}_{qn}_part_2_of_2.png"), "rb").read() == b"new2"

    def test_single_png_still_works(self, tmp_path):
        stem, qn = "MGCM_Completion", "GCM_SetGcStartTime"
        out_dir, src_dir = self._dirs(tmp_path, {f"{stem}_{qn}.png": b"old"},
                                      {f"{stem}_{qn}.png": b"new"})
        self._run_copy(out_dir, src_dir, stem, qn)
        assert open(os.path.join(out_dir, f"{stem}_{qn}.png"), "rb").read() == b"new"

    def test_a_shrunken_part_count_leaves_no_orphan(self, tmp_path):
        stem, qn = "MGCM_Completion", "GCM_SetGcEndTime"
        out_dir, src_dir = self._dirs(
            tmp_path,
            {f"{stem}_{qn}_part_1_of_3.png": b"o1", f"{stem}_{qn}_part_2_of_3.png": b"o2",
             f"{stem}_{qn}_part_3_of_3.png": b"o3"},
            {f"{stem}_{qn}_part_1_of_2.png": b"n1", f"{stem}_{qn}_part_2_of_2.png": b"n2"})
        self._run_copy(out_dir, src_dir, stem, qn)
        left = sorted(f for f in os.listdir(out_dir) if f.endswith(".png"))
        assert left == [f"{stem}_{qn}_part_1_of_2.png", f"{stem}_{qn}_part_2_of_2.png"]

    def test_a_similarly_named_function_is_untouched(self, tmp_path):
        stem, qn = "MGCM_Completion", "GCM_Set"
        other = f"{stem}_GCM_SetGcEndTime.png"
        out_dir, src_dir = self._dirs(tmp_path,
                                      {f"{stem}_{qn}.png": b"old", other: b"keep"},
                                      {f"{stem}_{qn}.png": b"new"})
        self._run_copy(out_dir, src_dir, stem, qn)
        assert open(os.path.join(out_dir, other), "rb").read() == b"keep", (
            "a prefix match must not consume a longer function name's images")
