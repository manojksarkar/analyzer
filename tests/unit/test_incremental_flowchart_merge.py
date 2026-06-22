"""Unit tests for the function-level flowchart splice (M3.6).

_merge_incremental_flowcharts rebuilds a changed file's flowchart JSON from the
baseline (all functions) with the freshly generated changed functions spliced in:
unchanged kept, changed replaced, deleted dropped, new appended. Join key = the
entry 'name' (== functions.json qualifiedName)."""
import json
import os
import sys
import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from views.flowcharts import _merge_incremental_flowcharts


def _entry(name, body):
    return {"name": name, "flowchart": f"flowchart TD\n  A[{body}]"}


def _write(path, entries):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f)


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _setup(tmp_path, baseline_entries, fresh_entries, current_names, unit="Utils"):
    base_fc = tmp_path / "baseline"
    out_dir = tmp_path / "out"
    base_fc.mkdir()
    out_dir.mkdir()
    if baseline_entries is not None:
        _write(str(base_fc / f"{unit}.json"), baseline_entries)
    _write(str(out_dir / f"{unit}.json"), fresh_entries)  # engine output: changed only
    inc = {"base_fc": str(base_fc), "changed_units": {unit},
           "current_by_unit": {unit: set(current_names)}}
    _merge_incremental_flowcharts(inc, str(out_dir))
    return _read(str(out_dir / f"{unit}.json"))


class TestSplice:
    def test_replaces_changed_keeps_unchanged_in_order(self, tmp_path):
        baseline = [_entry("add", "old-add"), _entry("subtract", "old-sub"),
                    _entry("computeBoth", "old-both")]
        fresh = [_entry("subtract", "NEW-sub")]
        merged = _setup(tmp_path, baseline, fresh, {"add", "subtract", "computeBoth"})
        names = [e["name"] for e in merged]
        assert names == ["add", "subtract", "computeBoth"]            # baseline order kept
        by = {e["name"]: e["flowchart"] for e in merged}
        assert "NEW-sub" in by["subtract"]                           # changed -> fresh
        assert "old-add" in by["add"] and "old-both" in by["computeBoth"]  # unchanged carried

    def test_drops_deleted(self, tmp_path):
        baseline = [_entry("add", "a"), _entry("subtract", "s"), _entry("computeBoth", "b")]
        fresh = [_entry("subtract", "NEW")]
        # computeBoth deleted in the target -> not in current
        merged = _setup(tmp_path, baseline, fresh, {"add", "subtract"})
        names = [e["name"] for e in merged]
        assert names == ["add", "subtract"]
        assert "computeBoth" not in names

    def test_drops_deleted_even_when_present_in_carried_fresh(self, tmp_path):
        # Deletion-only file: the engine produced no fresh output, so out_dir holds the
        # CARRIED baseline (deleted fn still present). The merge must still drop it.
        baseline = [_entry("add", "a"), _entry("subtract", "s"), _entry("computeBoth", "b")]
        fresh = [_entry("add", "a"), _entry("subtract", "s"), _entry("computeBoth", "b")]  # carried
        merged = _setup(tmp_path, baseline, fresh, {"add", "subtract"})  # computeBoth deleted
        assert [e["name"] for e in merged] == ["add", "subtract"]

    def test_appends_new(self, tmp_path):
        baseline = [_entry("add", "a"), _entry("subtract", "s")]
        fresh = [_entry("subtract", "NEW"), _entry("brandNew", "NN")]
        merged = _setup(tmp_path, baseline, fresh, {"add", "subtract", "brandNew"})
        names = [e["name"] for e in merged]
        assert names == ["add", "subtract", "brandNew"]              # new appended last
        by = {e["name"]: e["flowchart"] for e in merged}
        assert "NEW" in by["subtract"] and "NN" in by["brandNew"]

    def test_new_file_no_baseline_json(self, tmp_path):
        # baseline dir exists but has no JSON for this unit (brand-new source file)
        fresh = [_entry("brandNew", "NN")]
        merged = _setup(tmp_path, None, fresh, {"brandNew"})
        assert [e["name"] for e in merged] == ["brandNew"]

    def test_empty_current_falls_back_to_keep_all_baseline(self, tmp_path):
        # if current is empty (mapping unavailable) we must NOT drop everything
        baseline = [_entry("add", "a"), _entry("subtract", "s")]
        fresh = [_entry("subtract", "NEW")]
        merged = _setup(tmp_path, baseline, fresh, set())
        names = [e["name"] for e in merged]
        assert names == ["add", "subtract"]                          # nothing dropped
        by = {e["name"]: e["flowchart"] for e in merged}
        assert "NEW" in by["subtract"]                               # still replaced
