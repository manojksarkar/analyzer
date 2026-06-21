"""Unit tests for src/incremental/impact.py — classify + impact BFS (M2.2)."""
import os
import sys
import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from incremental.impact import classify, impact_set


class TestClassify:
    def test_all_four_buckets(self):
        base = {"a": "1", "b": "1", "c": "1"}      # c will be deleted
        targ = {"a": "1", "b": "2", "d": "1"}      # b changed, d new
        r = classify(base, targ)
        assert r["unchanged"] == {"a"}
        assert r["changed"] == {"b"}
        assert r["new"] == {"d"}
        assert r["deleted"] == {"c"}

    def test_empty_baseline_is_all_new(self):
        r = classify({}, {"a": "1", "b": "2"})
        assert r["new"] == {"a", "b"} and not r["changed"] and not r["deleted"]


# A small graph:  a -> b -> c   (a calls b, b calls c);  d is independent.
#   functions.json carries calledByIds (reverse call edges).
def _functions():
    return {
        "a": {"callsIds": ["b"], "calledByIds": []},
        "b": {"callsIds": ["c"], "calledByIds": ["a"]},
        "c": {"callsIds": [], "calledByIds": ["b"], "readsGlobalIds": ["G"]},
        "d": {"callsIds": [], "calledByIds": []},
    }


_EDGES = {"typeUsers": {"T": ["b"]}, "macroUsers": {"M@f.h": ["d"]}}


class TestImpactBFS:
    def test_changed_leaf_propagates_to_all_callers(self):
        # c changed -> c, and its callers transitively: b (calls c), a (calls b)
        assert impact_set({"c"}, _functions(), _EDGES) == {"a", "b", "c"}

    def test_changed_mid_propagates_up_not_down(self):
        # b changed -> b + its caller a; NOT c (c doesn't depend on b)
        assert impact_set({"b"}, _functions(), _EDGES) == {"a", "b"}

    def test_independent_function_isolated(self):
        assert impact_set({"d"}, _functions(), _EDGES) == {"d"}

    def test_changed_global_pulls_users_and_their_callers(self):
        # G changed -> users {c} -> + callers b, a
        assert impact_set({"G"}, _functions(), _EDGES) == {"a", "b", "c"}

    def test_changed_type_pulls_users(self):
        # T changed -> typeUsers {b} -> + caller a
        assert impact_set({"T"}, _functions(), _EDGES) == {"a", "b"}

    def test_changed_macro_pulls_users(self):
        assert impact_set({"M@f.h"}, _functions(), _EDGES) == {"d"}

    def test_non_function_unknown_key_is_noop(self):
        assert impact_set({"ghost_type"}, _functions(), _EDGES) == set()

    def test_extra_seed_functions_for_deleted_callers(self):
        # a deleted entity's baseline callers are injected directly
        assert impact_set(set(), _functions(), _EDGES, extra_seed_functions=["b"]) == {"a", "b"}

    def test_cycle_terminates(self):
        # a <-> b mutually recursive
        fns = {"a": {"calledByIds": ["b"]}, "b": {"calledByIds": ["a"]}}
        assert impact_set({"a"}, fns, {}) == {"a", "b"}

    def test_seed_function_not_in_model_ignored(self):
        assert impact_set({"missing"}, _functions(), _EDGES) == set()
