"""Unit tests for src/incremental/edges.py — slim usage index assembly (M1.2b)."""
import os
import sys
import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from incremental.edges import build_edges

# Common fixtures
_F2FID = {"fkA": "Comp|U|a|", "fkB": "Comp|U|b|int", "fkC": "Comp|U|c|"}


class TestTypeUsers:
    def test_inversion_and_fid_remap(self):
        out = build_edges(
            type_users={"Core::Config": {"fkA", "fkB"}},
            function_tokens={},
            type_keys={"Core::Config"},
            macro_keys=set(),
            func_key_to_fid=_F2FID,
        )
        assert out["typeUsers"] == {"Core::Config": ["Comp|U|a|", "Comp|U|b|int"]}  # sorted

    def test_unhashed_type_is_dropped(self):
        # A referenced type with no hash (not in type_keys) must not appear.
        out = build_edges({"Ghost": {"fkA"}}, {}, set(), set(), _F2FID)
        assert out["typeUsers"] == {}

    def test_unknown_func_key_skipped(self):
        out = build_edges({"T": {"fkZ"}}, {}, {"T"}, set(), _F2FID)
        assert out["typeUsers"] == {}  # fkZ has no fid -> no users -> key omitted


class TestMacroUsers:
    def test_token_match_creates_edge(self):
        out = build_edges(
            type_users={},
            function_tokens={"fkA": {"MAX_RETRIES", "i", "x"}},
            type_keys=set(),
            macro_keys={"MAX_RETRIES@Core/Core.h"},
            func_key_to_fid=_F2FID,
        )
        assert out["macroUsers"] == {"MAX_RETRIES@Core/Core.h": ["Comp|U|a|"]}

    def test_no_match_no_edge(self):
        out = build_edges({}, {"fkA": {"i", "x"}}, set(), {"MAX@f.h"}, _F2FID)
        assert out["macroUsers"] == {}

    def test_same_name_in_two_files_both_edged(self):
        # Over-approximate: a name #defined in two files -> edge to both keys.
        out = build_edges(
            type_users={},
            function_tokens={"fkA": {"DBG"}},
            type_keys=set(),
            macro_keys={"DBG@a.h", "DBG@b.h"},
            func_key_to_fid=_F2FID,
        )
        assert out["macroUsers"] == {"DBG@a.h": ["Comp|U|a|"], "DBG@b.h": ["Comp|U|a|"]}


class TestDeterminismShape:
    def test_keys_and_values_sorted(self):
        out = build_edges(
            type_users={"Zeta": {"fkB", "fkA"}, "Alpha": {"fkC"}},
            function_tokens={},
            type_keys={"Zeta", "Alpha"},
            macro_keys=set(),
            func_key_to_fid=_F2FID,
        )
        assert list(out["typeUsers"].keys()) == ["Alpha", "Zeta"]              # keys sorted
        assert out["typeUsers"]["Zeta"] == ["Comp|U|a|", "Comp|U|b|int"]       # values sorted

    def test_always_has_both_sections(self):
        out = build_edges({}, {}, set(), set(), {})
        assert out == {"typeUsers": {}, "macroUsers": {}}
