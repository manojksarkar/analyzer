"""Unit tests for the pure helpers in src/incremental/engine.py (M2.3)."""
import os
import sys
import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from incremental.engine import plan_incremental, carry_forward_descriptions


# target model:  a -> b -> c  (calledByIds carry reverse edges)
def _target_fns():
    return {
        "a": {"callsIds": ["b"], "calledByIds": []},
        "b": {"callsIds": ["c"], "calledByIds": ["a"]},
        "c": {"callsIds": [], "calledByIds": ["b"]},
    }


class TestPlanIncremental:
    def test_changed_leaf_impacts_callers_reuses_rest(self):
        base_h = {"a": "1", "b": "1", "c": "1"}
        targ_h = {"a": "1", "b": "1", "c": "2"}     # c changed
        plan = plan_incremental(base_h, targ_h, _target_fns(), {}, {})
        assert plan["impact"] == {"a", "b", "c"}    # c + its transitive callers
        assert plan["reused"] == set()              # everything depends on c here

    def test_independent_change_reuses_others(self):
        fns = {"a": {"calledByIds": []}, "b": {"calledByIds": []}}
        plan = plan_incremental({"a": "1", "b": "1"}, {"a": "2", "b": "1"}, fns, {}, {})
        assert plan["impact"] == {"a"} and plan["reused"] == {"b"}

    def test_new_function_is_impact_not_reuse(self):
        base_h = {"a": "1"}
        targ_h = {"a": "1", "b": "1"}                # b is new
        fns = {"a": {"calledByIds": []}, "b": {"calledByIds": []}}
        plan = plan_incremental(base_h, targ_h, fns, {}, {})
        assert "b" in plan["impact"] and plan["reused"] == {"a"}

    def test_deleted_function_callers_regenerate(self):
        # baseline had x called by a; x deleted in target -> a must regenerate
        base_h = {"a": "1", "x": "1"}
        targ_h = {"a": "1"}
        base_fns = {"a": {"calledByIds": []}, "x": {"calledByIds": ["a"]}}
        targ_fns = {"a": {"calledByIds": []}}
        plan = plan_incremental(base_h, targ_h, targ_fns, {}, base_fns)
        assert plan["classify"]["deleted"] == {"x"}
        assert "a" in plan["impact"]

    def test_type_change_impacts_users(self):
        base_h = {"a": "1", "T": "1"}
        targ_h = {"a": "1", "T": "2"}                # type T changed
        fns = {"a": {"calledByIds": []}}
        edges = {"typeUsers": {"T": ["a"]}, "macroUsers": {}}
        plan = plan_incremental(base_h, targ_h, fns, edges, {})
        assert plan["impact"] == {"a"}


class TestCarryForward:
    def test_copies_outputs_for_reused_only(self):
        base = {"a": {"description": "good A", "behaviourInputName": "in"},
                "b": {"description": "good B"}}
        targ = {"a": {"description": ""}, "b": {"description": ""}}
        n = carry_forward_descriptions({"a"}, targ, base)      # reuse only a
        assert n == 1
        assert targ["a"]["description"] == "good A"
        assert targ["a"]["behaviourInputName"] == "in"
        assert targ["b"]["description"] == ""                 # b not reused -> untouched

    def test_missing_baseline_entry_skipped(self):
        targ = {"a": {"description": ""}}
        assert carry_forward_descriptions({"a"}, targ, {}) == 0
        assert targ["a"]["description"] == ""

    def test_missing_target_entry_skipped(self):
        assert carry_forward_descriptions({"z"}, {}, {"z": {"description": "x"}}) == 0
