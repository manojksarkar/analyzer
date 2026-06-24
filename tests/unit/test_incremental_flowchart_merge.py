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

from views.flowcharts import _merge_incremental_flowcharts, _prune_orphan_flowcharts


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


class TestCrossVersionSplice:
    """M3.7b: a reverted (index-reused) function's flowchart comes from a prior version
    (X-VER), winning over the now-wrong baseline entry; fresh still wins over X-VER."""

    def test_three_source_priority(self, tmp_path):
        base_fc = tmp_path / "baseline"; out = tmp_path / "out"
        base_fc.mkdir(); out.mkdir()
        # baseline = target's parent: subtract holds the (revert-stale) changed flowchart
        _write(str(base_fc / "U.json"),
               [_entry("add", "a"), _entry("subtract", "BASE-sub"), _entry("multiply", "BASE-mul")])
        # engine fresh output for U: only 'multiply' was regenerated
        _write(str(out / "U.json"), [_entry("multiply", "FRESH-mul")])
        inc = {"base_fc": str(base_fc), "changed_units": {"U"},
               "current_by_unit": {"U": {"add", "subtract", "multiply"}},
               "xver_by_unit": {"U": {"subtract": _entry("subtract", "XVER-sub")}}}
        _merge_incremental_flowcharts(inc, str(out))
        merged = _read(str(out / "U.json"))
        by = {e["name"]: e["flowchart"] for e in merged}
        assert [e["name"] for e in merged] == ["add", "subtract", "multiply"]
        assert "a" in by["add"]                 # unchanged -> baseline
        assert "XVER-sub" in by["subtract"]     # reverted -> cross-version (NOT BASE-sub)
        assert "FRESH-mul" in by["multiply"]    # changed -> fresh

    def test_xver_new_function_appended(self, tmp_path):
        base_fc = tmp_path / "baseline"; out = tmp_path / "out"
        base_fc.mkdir(); out.mkdir()
        _write(str(base_fc / "U.json"), [_entry("add", "a")])
        _write(str(out / "U.json"), [])  # engine regenerated nothing
        inc = {"base_fc": str(base_fc), "changed_units": {"U"},
               "current_by_unit": {"U": {"add", "brandNew"}},
               "xver_by_unit": {"U": {"brandNew": _entry("brandNew", "XVER-new")}}}
        _merge_incremental_flowcharts(inc, str(out))
        merged = _read(str(out / "U.json"))
        assert [e["name"] for e in merged] == ["add", "brandNew"]
        assert "XVER-new" in {e["name"]: e["flowchart"] for e in merged}["brandNew"]


class TestPruneOrphanFlowcharts:
    """Move/rename cleanup: carried artifacts for files no longer in the model are dropped."""

    def _seed(self, d, units):
        for u in units:
            (d / f"{u}.json").write_text("[]", encoding="utf-8")
            (d / f"{u}_someFunc.png").write_bytes(b"png")

    def test_drops_orphan_unit_json_and_png(self, tmp_path):
        d = tmp_path / "out"; d.mkdir()
        self._seed(d, ["Kept", "Renamed"])  # Renamed no longer in the model
        removed = _prune_orphan_flowcharts(str(d), {"Kept"})
        files = set(os.listdir(str(d)))
        assert removed == 2  # Renamed.json + Renamed_someFunc.png
        assert "Kept.json" in files and "Kept_someFunc.png" in files
        assert "Renamed.json" not in files and "Renamed_someFunc.png" not in files

    def test_no_orphans_keeps_everything(self, tmp_path):
        d = tmp_path / "out"; d.mkdir()
        self._seed(d, ["A", "B"])
        assert _prune_orphan_flowcharts(str(d), {"A", "B"}) == 0
        assert len(os.listdir(str(d))) == 4

    def test_empty_valid_stems_is_a_noop(self, tmp_path):
        # guard: a load glitch (no valid stems) must NOT nuke the carried output
        d = tmp_path / "out"; d.mkdir()
        self._seed(d, ["A"])
        assert _prune_orphan_flowcharts(str(d), set()) == 0
        assert len(os.listdir(str(d))) == 2

    def test_prefix_collision_not_pruned(self, tmp_path):
        # 'Foo' orphan must not drop 'Foobar' artifacts (separator guards the prefix)
        d = tmp_path / "out"; d.mkdir()
        self._seed(d, ["Foo", "Foobar"])
        _prune_orphan_flowcharts(str(d), {"Foobar"})
        files = set(os.listdir(str(d)))
        assert "Foobar.json" in files and "Foobar_someFunc.png" in files
        assert "Foo.json" not in files
