"""Unit tests for the virtual-dispatch over-approximation (D7).

spread_virtual_families links every caller of a virtual-family member to ALL members,
so a call that may dynamically dispatch to any override impacts the whole family."""
import os
import sys
from collections import defaultdict

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from incremental.virtual_dispatch import spread_virtual_families


class TestSpreadVirtualFamilies:
    def test_links_dispatcher_to_all_overrides(self):
        # caller resolved (by name fallback) to only AddOp::apply; MultOp::apply orphaned.
        call_graph = defaultdict(list, {"dispatch": ["AddOp::apply"]})
        reverse = defaultdict(list, {"AddOp::apply": ["dispatch"]})
        pairs = [("AddOp::apply", "Base::apply"), ("MultOp::apply", "Base::apply")]
        fkeys = {"dispatch", "AddOp::apply", "MultOp::apply"}  # Base::apply is pure-virtual, absent
        edges, fams = spread_virtual_families(call_graph, reverse, pairs, fkeys)
        assert fams == 1 and edges == 1
        assert set(call_graph["dispatch"]) == {"AddOp::apply", "MultOp::apply"}
        assert reverse["MultOp::apply"] == ["dispatch"]   # the previously-orphaned override

    def test_transitive_override_chain_is_one_family(self):
        call_graph = defaultdict(list, {"c": ["D2::m"]})
        reverse = defaultdict(list, {"D2::m": ["c"]})
        pairs = [("D2::m", "D1::m"), ("D1::m", "B::m")]   # D2 -> D1 -> B
        fkeys = {"c", "D2::m", "D1::m", "B::m"}            # base B::m also defined here
        edges, fams = spread_virtual_families(call_graph, reverse, pairs, fkeys)
        assert fams == 1
        assert set(call_graph["c"]) == {"D2::m", "D1::m", "B::m"}

    def test_no_pairs_is_noop(self):
        cg = defaultdict(list, {"a": ["b"]})
        rev = defaultdict(list, {"b": ["a"]})
        assert spread_virtual_families(cg, rev, [], {"a", "b"}) == (0, 0)
        assert cg["a"] == ["b"]

    def test_lone_override_not_spread(self):
        # only one family member is in the model -> nothing to spread to
        cg = defaultdict(list, {"c": ["D::m"]})
        rev = defaultdict(list, {"D::m": ["c"]})
        edges, fams = spread_virtual_families(cg, rev, [("D::m", "B::m")], {"c", "D::m"})
        assert (edges, fams) == (0, 0)

    def test_idempotent(self):
        cg = defaultdict(list, {"dispatch": ["AddOp::apply"]})
        rev = defaultdict(list, {"AddOp::apply": ["dispatch"]})
        pairs = [("AddOp::apply", "B::apply"), ("MultOp::apply", "B::apply")]
        fkeys = {"dispatch", "AddOp::apply", "MultOp::apply"}
        spread_virtual_families(cg, rev, pairs, fkeys)
        edges2, _ = spread_virtual_families(cg, rev, pairs, fkeys)   # second run adds nothing
        assert edges2 == 0
        assert set(cg["dispatch"]) == {"AddOp::apply", "MultOp::apply"}

    def test_caller_via_any_member_reaches_all(self):
        # caller linked only to the BASE; spread must still reach the overrides
        cg = defaultdict(list, {"c": ["B::m"]})
        rev = defaultdict(list, {"B::m": ["c"]})
        pairs = [("D1::m", "B::m"), ("D2::m", "B::m")]
        fkeys = {"c", "B::m", "D1::m", "D2::m"}
        spread_virtual_families(cg, rev, pairs, fkeys)
        assert set(cg["c"]) == {"B::m", "D1::m", "D2::m"}
