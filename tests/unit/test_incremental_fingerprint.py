"""Unit tests for src/incremental/fingerprint.py — reuse fingerprints (M1.3)."""
import os
import re
import sys
import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from incremental.fingerprint import recipe_fingerprint, compute_fingerprints


class TestRecipeFingerprint:
    def test_hex_and_deterministic(self):
        a = recipe_fingerprint("m", cache_version=1)
        b = recipe_fingerprint("m", cache_version=1)
        assert a == b and re.fullmatch(r"[0-9a-f]{64}", a)

    def test_model_and_cache_version_matter(self):
        base = recipe_fingerprint("m1", cache_version=1)
        assert base != recipe_fingerprint("m2", cache_version=1)   # model change
        assert base != recipe_fingerprint("m1", cache_version=2)   # cacheVersion bump


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
        fps = compute_fingerprints(h, f, e, "rfp")
        assert set(fps) == {"C|U|a|", "C|U|b|", "C|U|g_x"}        # 2 funcs + 1 global
        assert all(re.fullmatch(r"[0-9a-f]{64}", v) for v in fps.values())

    def test_dependency_change_changes_dependent_fingerprint(self):
        h, f, e = self._model()
        base = compute_fingerprints(h, f, e, "rfp")
        # change callee b's source hash -> a's fingerprint must change, b's too
        h2 = dict(h); h2["C|U|b|"] = "hb_v2"
        after = compute_fingerprints(h2, f, e, "rfp")
        assert after["C|U|b|"] != base["C|U|b|"]                  # b changed (own source)
        assert after["C|U|a|"] != base["C|U|a|"]                  # a changed (callee dep)
        assert after["C|U|g_x"] == base["C|U|g_x"]               # global unaffected

    def test_type_and_macro_deps_propagate(self):
        h, f, e = self._model()
        base = compute_fingerprints(h, f, e, "rfp")
        h_t = dict(h); h_t["Point"] = "ht_v2"
        assert compute_fingerprints(h_t, f, e, "rfp")["C|U|a|"] != base["C|U|a|"]   # type dep
        h_m = dict(h); h_m["MAX@h.h"] = "hm_v2"
        assert compute_fingerprints(h_m, f, e, "rfp")["C|U|a|"] != base["C|U|a|"]   # macro dep

    def test_recipe_change_changes_all(self):
        h, f, e = self._model()
        base = compute_fingerprints(h, f, e, "rfp1")
        after = compute_fingerprints(h, f, e, "rfp2")
        assert all(after[k] != base[k] for k in base)

    def test_revert_reproduces_fingerprint(self):
        h, f, e = self._model()
        base = compute_fingerprints(h, f, e, "rfp")
        h2 = dict(h); h2["C|U|b|"] = "hb_v2"
        compute_fingerprints(h2, f, e, "rfp")
        # revert b back -> a's fingerprint returns to the original (content-addressed reuse)
        assert compute_fingerprints(h, f, e, "rfp")["C|U|a|"] == base["C|U|a|"]
