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
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

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


class TestGlobalsFoldInTheirAccessors:
    """A global's fingerprint must move when a function that reads or writes it changes.

    `enrich_globals_rich` builds a global's description from the DESCRIPTIONS of its readers and
    writers, so a changed reader changes the global's input. The fingerprint was
    `_fingerprint(own_source_hash, [])` — no dependencies — so it did not move, the reuse index
    scored a hit, and the global kept a description written against the reader's old behaviour.

    Observed in a real run: 4 functions regenerated, both globals "reused 100%" via the content
    index. The report even claimed globals get regenerated when a reader does; the fingerprint
    made that false.

    Functions already folded in their callees. Globals were the gap.
    """

    def _model(self, reader_hash):
        functions = {
            "App|U|reader|void": {"qualifiedName": "reader", "callsIds": [],
                                  "readsGlobalIds": ["App|U|g_flag"], "writesGlobalIds": []},
        }
        hashes = {"App|U|reader|void": reader_hash, "App|U|g_flag": "GLOBAL-SRC-1"}
        return hashes, functions, {"typeUsers": {}, "macroUsers": {}}

    def test_a_changed_reader_changes_the_global_fingerprint(self):
        h1, f1, e1 = self._model("READER-V1")
        h2, f2, e2 = self._model("READER-V2")      # the global's own source is identical
        fp1 = compute_fingerprints(h1, f1, e1)["App|U|g_flag"]
        fp2 = compute_fingerprints(h2, f2, e2)["App|U|g_flag"]
        assert fp1 != fp2, ("the global's fingerprint ignored its reader, so a stale description "
                            "would be reused")

    def test_an_unchanged_reader_keeps_it_stable(self):
        """Reuse must still happen when nothing relevant moved — the point is precision, not
        regenerating everything."""
        h1, f1, e1 = self._model("READER-V1")
        h2, f2, e2 = self._model("READER-V1")
        assert (compute_fingerprints(h1, f1, e1)["App|U|g_flag"]
                == compute_fingerprints(h2, f2, e2)["App|U|g_flag"])

    def test_a_writer_counts_too(self):
        base = {"App|U|w|void": {"qualifiedName": "w", "callsIds": [],
                                 "readsGlobalIds": [], "writesGlobalIds": ["App|U|g_flag"]}}
        edges = {"typeUsers": {}, "macroUsers": {}}
        a = compute_fingerprints({"App|U|w|void": "W1", "App|U|g_flag": "G"}, base, edges)
        b = compute_fingerprints({"App|U|w|void": "W2", "App|U|g_flag": "G"}, base, edges)
        assert a["App|U|g_flag"] != b["App|U|g_flag"]

    def test_accessor_order_does_not_matter(self):
        """Two readers listed in either order must fingerprint the same — `_fingerprint` sorts
        its dependency hashes, and a set is unordered anyway."""
        edges = {"typeUsers": {}, "macroUsers": {}}
        fns = {
            "App|U|a|void": {"qualifiedName": "a", "callsIds": [],
                             "readsGlobalIds": ["App|U|g"], "writesGlobalIds": []},
            "App|U|b|void": {"qualifiedName": "b", "callsIds": [],
                             "writesGlobalIds": ["App|U|g"], "readsGlobalIds": []},
        }
        h = {"App|U|a|void": "A", "App|U|b|void": "B", "App|U|g": "G"}
        first = compute_fingerprints(h, fns, edges)["App|U|g"]
        second = compute_fingerprints(dict(reversed(list(h.items()))), fns, edges)["App|U|g"]
        assert first == second

    def test_a_global_with_no_accessors_still_gets_one(self):
        edges = {"typeUsers": {}, "macroUsers": {}}
        out = compute_fingerprints({"App|U|orphan": "G"}, {}, edges)
        assert out.get("App|U|orphan")
