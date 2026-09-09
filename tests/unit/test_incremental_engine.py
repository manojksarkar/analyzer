"""Unit tests for the pure helpers in src/incremental/engine.py (M2.3)."""
import os
import sys
import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from incremental.engine import plan_incremental, carry_forward_descriptions, carry_forward_globals


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


class TestCarryForwardGlobals:
    def test_copies_description_for_reused(self):
        base = {"C|U|g_a": {"description": "good A"}, "C|U|g_b": {"description": "good B"}}
        targ = {"C|U|g_a": {"description": ""}, "C|U|g_b": {"description": ""}}
        n = carry_forward_globals({"C|U|g_a"}, targ, base)
        assert n == 1
        assert targ["C|U|g_a"]["description"] == "good A"
        assert targ["C|U|g_b"]["description"] == ""   # not reused -> untouched

    def test_missing_entries_skipped(self):
        assert carry_forward_globals({"x"}, {}, {"x": {"description": "d"}}) == 0
        assert carry_forward_globals({"x"}, {"x": {"description": ""}}, {}) == 0


class TestTerminalManifestReachesTheStore:
    """The orchestrators must write the manifest to the STORE, not only to the file store.

    This is the wiring, and it is what actually broke. `persist_run_outcome` was implemented
    and unit-tested, but nothing called it: every orchestrator wrote its manifest through
    `vstore` (the file VersionStore, keyed by COMMIT) while only `store` (the artifact store,
    keyed by the real VERSION id) reaches Postgres. So versions.pipeline_status was never
    closed out, `pg_stores.list_versions` refused every finished version as a baseline, and
    every run silently fell back to a FULL generation with 0% reuse.

    Testing the function passed. Testing the wiring is what catches it, so these assert on
    the source: both terminal paths and both failure paths must reach `store.write_manifest`.
    """

    def _source(self, name):
        import os
        here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        with open(os.path.join(here, "engine", "incremental", name), encoding="utf-8") as fh:
            return fh.read()

    def test_generate_full_writes_the_manifest_to_the_store(self):
        src = self._source("generate.py")
        assert "store.write_manifest(version_id, manifest)" in src, \
            "generate_full must persist its terminal manifest to the store (-> Postgres)"

    def test_generate_incremental_writes_the_manifest_to_the_store(self):
        src = self._source("engine.py")
        assert "store.write_manifest(version_id, manifest)" in src, \
            "generate_incremental must persist its terminal manifest to the store"

    def test_failure_paths_close_the_lifecycle_too(self):
        """A failed run left mid-phase would also be permanently baseline-ineligible."""
        for name in ("generate.py", "engine.py"):
            src = self._source(name)
            assert "store.write_manifest(version_id, m)" in src, \
                f"{name}: the failure path must close the pipeline lifecycle"

    def test_every_vstore_manifest_write_has_a_store_counterpart(self):
        """Counts, so a NEW manifest write added later cannot quietly skip the store."""
        for name in ("generate.py", "engine.py"):
            src = self._source(name)
            v = src.count("vstore.write_manifest(")
            st = src.count("store.write_manifest(") - v      # 'vstore.' contains 'store.'
            # the early 'running' manifest is deliberately file-only (it must not clobber
            # the finer-grained phase status), so the store gets one fewer write
            assert st >= v - 1, (
                f"{name}: {v} vstore manifest write(s) but only {st} store write(s) - "
                f"a terminal manifest is not reaching Postgres")
