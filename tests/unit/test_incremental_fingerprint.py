"""Unit tests for src/incremental/fingerprint.py — content-only reuse fingerprints.

The fingerprint folds in an entity's own source hash + its dependencies' source
hashes, but NOT the LLM recipe (recipe-fingerprint invalidation was dropped — an
approved output is reused regardless of which model/prompt produced it)."""
import os
import re
import sys
import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from incremental.fingerprint import compute_fingerprints


class TestComputeFingerprints:
    def _model(self):
        hashes = {
            "C|U|a|": "ha", "C|U|b|": "hb",          # functions
            "C|U|g_x": "hg",                          # global (2 pipes)
            "Point": "ht",                            # type
            "MAX@h.h": "hm",                          # macro
        }
        functions = {
            "C|U|a|": {"callsIds": ["C|U|b|"], "readsGlobalIds": ["C|U|g_x"]},
            "C|U|b|": {},
        }
        edges = {"typeUsers": {"Point": ["C|U|a|"]}, "macroUsers": {"MAX@h.h": ["C|U|a|"]}}
        return hashes, functions, edges

    def test_covers_functions_and_globals(self):
        h, f, e = self._model()
        fps = compute_fingerprints(h, f, e)
        assert set(fps) == {"C|U|a|", "C|U|b|", "C|U|g_x"}        # 2 funcs + 1 global
        assert all(re.fullmatch(r"[0-9a-f]{64}", v) for v in fps.values())

    def test_deterministic(self):
        h, f, e = self._model()
        assert compute_fingerprints(h, f, e) == compute_fingerprints(h, f, e)

    def test_dependency_change_changes_dependent_fingerprint(self):
        h, f, e = self._model()
        base = compute_fingerprints(h, f, e)
        # change callee b's source hash -> a's fingerprint must change, b's too
        h2 = dict(h); h2["C|U|b|"] = "hb_v2"
        after = compute_fingerprints(h2, f, e)
        assert after["C|U|b|"] != base["C|U|b|"]                  # b changed (own source)
        assert after["C|U|a|"] != base["C|U|a|"]                  # a changed (callee dep)
        assert after["C|U|g_x"] == base["C|U|g_x"]               # global unaffected

    def test_type_and_macro_deps_propagate(self):
        h, f, e = self._model()
        base = compute_fingerprints(h, f, e)
        h_t = dict(h); h_t["Point"] = "ht_v2"
        assert compute_fingerprints(h_t, f, e)["C|U|a|"] != base["C|U|a|"]   # type dep
        h_m = dict(h); h_m["MAX@h.h"] = "hm_v2"
        assert compute_fingerprints(h_m, f, e)["C|U|a|"] != base["C|U|a|"]   # macro dep

    def test_revert_reproduces_fingerprint(self):
        h, f, e = self._model()
        base = compute_fingerprints(h, f, e)
        h2 = dict(h); h2["C|U|b|"] = "hb_v2"
        compute_fingerprints(h2, f, e)
        # revert b back -> a's fingerprint returns to the original (content-addressed reuse)
        assert compute_fingerprints(h, f, e)["C|U|a|"] == base["C|U|a|"]

    def test_recipe_not_part_of_key(self):
        # compute_fingerprints takes no recipe arg; identical content -> identical key
        # no matter the (hypothetical) model/prompt. Guards against re-introducing it.
        h, f, e = self._model()
        assert compute_fingerprints(h, f, e)["C|U|a|"] == compute_fingerprints(h, f, e)["C|U|a|"]
