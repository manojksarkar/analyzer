"""Unit tests for the narrowed-parse model merge (M4.3)."""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from incremental.parse_merge import merge_model, diff_models


def _fn(file, callsIds=None, h="h"):
    return {"location": {"file": file}, "callsIds": list(callsIds or []), "calledByIds": []}


def _model(functions, hashes=None, edges=None, entity_files=None, override_pairs=None,
           dataDictionary=None, tu_includes=None, globalVariables=None):
    return {
        "functions": functions, "globalVariables": globalVariables or {},
        "dataDictionary": dataDictionary or {}, "hashes": hashes or {},
        "edges": edges or {"typeUsers": {}, "macroUsers": {}},
        "tu_includes": tu_includes or {}, "entity_files": entity_files or {},
        "override_pairs": override_pairs or [], "metadata": {"basePath": "x"},
    }


class TestMergeModel:
    def test_modified_function_replaced_callers_preserved(self):
        # B/f2 (unchanged) calls A/f1; A/f1 modified. Re-parse A -> fresh has f1 only.
        baseline = _model(
            {"A|U|f1|": _fn("A.cpp"), "B|U|f2|": _fn("B.cpp", ["A|U|f1|"])},
            hashes={"A|U|f1|": "h1", "B|U|f2|": "h2"},
            entity_files={"A|U|f1|": "A.cpp", "B|U|f2|": "B.cpp"})
        fresh = _model({"A|U|f1|": _fn("A.cpp")}, hashes={"A|U|f1|": "h1_v2"},
                       entity_files={"A|U|f1|": "A.cpp"})
        m = merge_model(baseline, fresh, drop_files={"A.cpp"})
        assert set(m["functions"]) == {"A|U|f1|", "B|U|f2|"}            # f2 kept
        assert m["hashes"]["A|U|f1|"] == "h1_v2"                        # fresh hash
        assert m["functions"]["A|U|f1|"]["calledByIds"] == ["B|U|f2|"]  # baseline caller preserved
        assert m["functions"]["B|U|f2|"]["callsIds"] == ["A|U|f1|"]

    def test_new_function_added(self):
        baseline = _model({"A|U|f1|": _fn("A.cpp")}, entity_files={"A|U|f1|": "A.cpp"})
        fresh = _model({"A|U|f1|": _fn("A.cpp"), "A|U|f3|": _fn("A.cpp")},
                       entity_files={"A|U|f1|": "A.cpp", "A|U|f3|": "A.cpp"})
        m = merge_model(baseline, fresh, drop_files={"A.cpp"})
        assert set(m["functions"]) == {"A|U|f1|", "A|U|f3|"}

    def test_deleted_function_dropped_and_edges_cleaned(self):
        # A/f1 called B/f2; the edit deletes f2 from B (B re-parsed, fresh has no f2).
        baseline = _model(
            {"A|U|f1|": _fn("A.cpp", ["B|U|f2|"]), "B|U|f2|": _fn("B.cpp")},
            entity_files={"A|U|f1|": "A.cpp", "B|U|f2|": "B.cpp"})
        fresh = _model({}, entity_files={})           # B re-parsed -> empty
        m = merge_model(baseline, fresh, drop_files={"B.cpp"})
        assert set(m["functions"]) == {"A|U|f1|"}                       # f2 gone
        assert m["functions"]["A|U|f1|"]["callsIds"] == []              # stale edge cleaned

    def test_deleted_file_dropped(self):
        baseline = _model(
            {"A|U|f1|": _fn("A.cpp"), "Gone|U|g|": _fn("Gone.cpp")},
            entity_files={"A|U|f1|": "A.cpp", "Gone|U|g|": "Gone.cpp"})
        fresh = _model({}, entity_files={})
        m = merge_model(baseline, fresh, drop_files={"Gone.cpp"})       # deleted file
        assert set(m["functions"]) == {"A|U|f1|"}

    def test_edges_typeusers_merged_and_filtered(self):
        baseline = _model(
            {"A|U|f1|": _fn("A.cpp"), "B|U|f2|": _fn("B.cpp")},
            edges={"typeUsers": {"T": ["A|U|f1|", "B|U|f2|"]}, "macroUsers": {}},
            entity_files={"A|U|f1|": "A.cpp", "B|U|f2|": "B.cpp"})
        fresh = _model({"A|U|f1|": _fn("A.cpp")},
                       edges={"typeUsers": {"T": ["A|U|f1|"]}, "macroUsers": {}},
                       entity_files={"A|U|f1|": "A.cpp"})
        m = merge_model(baseline, fresh, drop_files={"A.cpp"})
        assert sorted(m["edges"]["typeUsers"]["T"]) == ["A|U|f1|", "B|U|f2|"]

    def test_virtual_family_respread_on_merge(self):
        # dispatcher (unchanged) calls AddOp::apply; MultOp::apply re-parsed.
        baseline = _model(
            {"C|D|disp|": _fn("D.cpp", ["C|D|AddOp::apply|i"]),
             "C|D|AddOp::apply|i": _fn("D.cpp"),
             "C|D|MultOp::apply|i": _fn("M.cpp")},
            override_pairs=[["C|D|AddOp::apply|i", "C|D|Op::apply|i"],
                            ["C|D|MultOp::apply|i", "C|D|Op::apply|i"]],
            entity_files={"C|D|disp|": "D.cpp", "C|D|AddOp::apply|i": "D.cpp",
                          "C|D|MultOp::apply|i": "M.cpp"})
        fresh = _model({"C|D|MultOp::apply|i": _fn("M.cpp")},
                       override_pairs=[["C|D|MultOp::apply|i", "C|D|Op::apply|i"]],
                       entity_files={"C|D|MultOp::apply|i": "M.cpp"})
        m = merge_model(baseline, fresh, drop_files={"M.cpp"})
        # dispatcher must now call BOTH overrides (virtual family re-spread)
        assert set(m["functions"]["C|D|disp|"]["callsIds"]) == {
            "C|D|AddOp::apply|i", "C|D|MultOp::apply|i"}
        assert m["functions"]["C|D|MultOp::apply|i"]["calledByIds"] == ["C|D|disp|"]

    def test_tu_includes_merged_by_tu(self):
        baseline = _model({}, tu_includes={"A.cpp": ["X.h"], "B.cpp": ["Y.h"]})
        fresh = _model({}, tu_includes={"A.cpp": ["X.h", "Z.h"]})
        m = merge_model(baseline, fresh, drop_files={"A.cpp"})
        assert m["tu_includes"] == {"A.cpp": ["X.h", "Z.h"], "B.cpp": ["Y.h"]}


class TestDiffModels:
    """M4.5 --verify-parse self-check: diff a narrowed model against a full one."""

    def test_identical_models_no_diff(self):
        m = _model({"A|U|f|": _fn("A.cpp", ["B|U|g|"])},
                   hashes={"A|U|f|": "h"}, edges={"typeUsers": {"T": ["A|U|f|"]}, "macroUsers": {}})
        assert diff_models(m, m) == []

    def test_edge_order_is_not_a_diff(self):
        a = _model({"A|U|f|": _fn("A.cpp", ["x", "y"])})
        b = _model({"A|U|f|": _fn("A.cpp", ["y", "x"])})   # same set, different order
        assert diff_models(a, b) == []

    def test_missing_function_reported(self):
        a = _model({"A|U|f|": _fn("A.cpp")})
        b = _model({"A|U|f|": _fn("A.cpp"), "A|U|g|": _fn("A.cpp")})
        d = diff_models(a, b)
        assert any("MISSING A|U|g|" in s for s in d)

    def test_callsids_difference_reported(self):
        a = _model({"A|U|f|": _fn("A.cpp", ["x"])})
        b = _model({"A|U|f|": _fn("A.cpp", ["x", "y"])})   # y missing in narrowed
        d = diff_models(a, b)
        assert any("callsIds" in s for s in d)

    def test_hash_difference_reported(self):
        a = _model({"A|U|f|": _fn("A.cpp")}, hashes={"A|U|f|": "h1"})
        b = _model({"A|U|f|": _fn("A.cpp")}, hashes={"A|U|f|": "h2"})
        assert any("hashes[A|U|f|]" in s for s in diff_models(a, b))
