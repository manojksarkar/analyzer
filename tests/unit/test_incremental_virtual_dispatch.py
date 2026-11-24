"""Unit tests for the links of a virtual call.

spread_virtual_calls (review SWE3-028): a call reaches the method it names and every
override below it; a call naming the class (`Base::f()`) that one only.
spread_virtual_families (D7), kept for a baseline that did not record its virtual calls,
links every caller of a family member to ALL members."""
import os
import sys
from collections import defaultdict

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from incremental.parse_merge import merge_model
from incremental.virtual_dispatch import (overrides_below, spread_virtual_calls,
                                          spread_virtual_families)


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


# ---------------------------------------------------------------- spread_virtual_calls (SWE3-028)

_PAIRS = [("Nand::read", "Device::read"), ("Nor::read", "Device::read"), ("Slc::read", "Nand::read")]
_KEYS = {"any", "nand", "Device::read", "Nand::read", "Nor::read", "Slc::read"}


class TestSpreadVirtualCalls:
    def test_overrides_below_are_transitive(self):
        below = overrides_below(_PAIRS)
        assert below["Device::read"] == {"Nand::read", "Nor::read", "Slc::read"}
        assert below["Nand::read"] == {"Slc::read"}
        assert "Nor::read" not in below

    def test_a_base_call_reaches_every_override(self):
        cg = defaultdict(list, {"any": ["Device::read"]})
        rev = defaultdict(list, {"Device::read": ["any"]})
        spread_virtual_calls(cg, rev, _PAIRS, [("any", "Device::read")], _KEYS)
        assert set(cg["any"]) == {"Device::read", "Nand::read", "Nor::read", "Slc::read"}

    def test_a_derived_call_reaches_only_below_it(self):
        cg = defaultdict(list, {"nand": ["Nand::read"]})
        rev = defaultdict(list, {"Nand::read": ["nand"]})
        spread_virtual_calls(cg, rev, _PAIRS, [("nand", "Nand::read")], _KEYS)
        assert set(cg["nand"]) == {"Nand::read", "Slc::read"}     # not the base, not Nor
        assert "nand" not in rev.get("Nor::read", [])

    def test_a_call_not_recorded_does_not_spread(self):
        # `Device::read(lba)` names the class: the parser does not record it
        cg = defaultdict(list, {"Nand::read": ["Device::read"]})
        rev = defaultdict(list, {"Device::read": ["Nand::read"]})
        assert spread_virtual_calls(cg, rev, _PAIRS, [], _KEYS) == (0, 0)
        assert cg["Nand::read"] == ["Device::read"]

    def test_a_pure_base_reaches_its_defined_overrides(self):
        pairs = [("Uart::send", "Port::send"), ("Spi::send", "Port::send")]
        cg, rev = defaultdict(list), defaultdict(list)
        spread_virtual_calls(cg, rev, pairs, [("c", "Port::send")], {"c", "Uart::send", "Spi::send"})
        assert set(cg["c"]) == {"Uart::send", "Spi::send"}


# ---------------------------------------------------------------- the parser (libclang)

@pytest.fixture(scope="module")
def parser_mod():
    old_argv = sys.argv
    sys.argv = ["parser.py", PROJECT_ROOT]
    try:
        import parser as P
    except Exception as e:  # libclang missing / load failure
        pytest.skip(f"parser/libclang unavailable: {e}")
    finally:
        sys.argv = old_argv
    yield P


def _call_graph(P, tmp_path, source):
    """Parse a snippet; run Phase 1's call visitor and the virtual link on it; return
    {caller: sorted callees}, by qualified name. The parser's module state is restored."""
    from clang import cindex

    src = tmp_path / "t.cpp"
    src.write_text(source, encoding="utf-8")
    tu = cindex.Index.create().parse(str(src), args=["-x", "c++", "-std=c++20"])
    assert not [d for d in tu.diagnostics if d.severity >= 3], [d.spelling for d in tu.diagnostics]

    saved = {n: getattr(P, n) for n in ("functions", "call_graph", "reverse_call_graph",
                                         "_visited_call_keys", "_virtual_calls",
                                         "is_project_file", "MODULE_BASE_PATH")}
    try:
        P.functions, P._visited_call_keys, P._virtual_calls = {}, set(), set()
        P.call_graph, P.reverse_call_graph = defaultdict(list), defaultdict(list)
        P.MODULE_BASE_PATH = str(tmp_path)
        P.is_project_file = lambda _p: True
        names, pairs = {}, []

        def collect(c):
            if (c.kind in (cindex.CursorKind.FUNCTION_DECL, cindex.CursorKind.CXX_METHOD)
                    and c.is_definition()):
                key = P.get_function_key(c)
                P.functions[key] = {"functionName": c.spelling}
                names[key] = P.get_qualified_name(c)
                if c.kind == cindex.CursorKind.CXX_METHOD:
                    pairs.extend((key, P.get_function_key(b)) for b in P._clang_overridden(c))
            for ch in c.get_children():
                collect(ch)

        collect(tu.cursor)
        P.visit_calls(tu.cursor)
        spread_virtual_calls(P.call_graph, P.reverse_call_graph, pairs, P._virtual_calls,
                             set(P.functions))
        return {names[k]: sorted(names[c] for c in v) for k, v in P.call_graph.items() if v}
    finally:
        for n, v in saved.items():
            setattr(P, n, v)


_DEVICES = """
class Device { public: virtual ~Device() = default; virtual int read(int lba); };
class NandDevice : public Device { public: int read(int lba) override; };
class NorDevice : public Device { public: int read(int lba) override; };
int Device::read(int lba) { return lba; }
int NandDevice::read(int lba) { return Device::read(lba) + 1; }
int NorDevice::read(int lba) { return lba * 2; }
int devReadAny(Device* d, int lba) { return d->read(lba); }
int devReadNand(NandDevice& n, int lba) { return n.read(lba); }

struct Port { virtual ~Port() = default; virtual int send(int x) = 0; };
struct UartPort : Port { int send(int x) override { return x; } };
struct SpiPort : Port { int send(int x) override { return x + 1; } };
int send(int x) { return x; }                 // a free function of the same name
int portSend(Port* p, int x) { return p->send(x); }
"""


class TestParserVirtualCalls:
    def test_each_call_reaches_what_it_can(self, parser_mod, tmp_path):
        g = _call_graph(parser_mod, tmp_path, _DEVICES)
        assert g["devReadAny"] == ["Device::read", "NandDevice::read", "NorDevice::read"]
        assert g["devReadNand"] == ["NandDevice::read"]          # not the base, not NorDevice
        assert g["NandDevice::read"] == ["Device::read"]         # `Device::read(lba)` names the class

    def test_a_pure_virtual_call_is_never_matched_by_name(self, parser_mod, tmp_path):
        g = _call_graph(parser_mod, tmp_path, _DEVICES)
        assert g["portSend"] == ["SpiPort::send", "UartPort::send"]   # not the free `send`


# ---------------------------------------------------------------- the narrowed-parse merge

def _fn(name, calls=()):
    return {"functionName": name, "callsIds": list(calls), "calledByIds": []}


def _model(functions, pairs, virtual=None):
    pc = {"stores": [], "calls": [], "edges": []}
    if virtual is not None:
        pc["virtual"] = virtual
    return {"functions": functions, "entity_files": {k: k.split(":")[0] for k in functions},
            "override_pairs": pairs, "pointer_calls": pc}


class TestMergeVirtualCalls:
    def test_a_new_override_reaches_the_callers_above_it(self):
        # user.cpp calls through a Device* and through a NandDevice&; a re-parse of slc.cpp
        # adds Slc::read below NandDevice. Both callers reach it; neither reaches more.
        pairs = [["nand.cpp:1", "dev.cpp:1"], ["nor.cpp:1", "dev.cpp:1"]]
        base_fns = {"dev.cpp:1": _fn("dev"), "nand.cpp:1": _fn("nand"), "nor.cpp:1": _fn("nor"),
                    "user.cpp:1": _fn("any", ["dev.cpp:1", "nand.cpp:1", "nor.cpp:1"]),
                    "user.cpp:2": _fn("nand_only", ["nand.cpp:1"])}
        baseline = _model(base_fns, pairs, [["user.cpp:1", "dev.cpp:1"], ["user.cpp:2", "nand.cpp:1"]])
        fresh = _model({"slc.cpp:1": _fn("slc")}, [["slc.cpp:1", "nand.cpp:1"]], [])
        merged = merge_model(baseline, fresh, ["slc.cpp"])
        f = merged["functions"]
        assert "slc.cpp:1" in f["user.cpp:1"]["callsIds"]
        assert f["user.cpp:2"]["callsIds"] == ["nand.cpp:1", "slc.cpp:1"]   # never Nor or the base
        assert merged["pointer_calls"]["virtual"] == [["user.cpp:1", "dev.cpp:1"],
                                                      ["user.cpp:2", "nand.cpp:1"]]

    def test_an_old_baseline_spreads_by_family(self):
        pairs = [["nand.cpp:1", "dev.cpp:1"], ["nor.cpp:1", "dev.cpp:1"]]
        base_fns = {"dev.cpp:1": _fn("dev"), "nand.cpp:1": _fn("nand"), "nor.cpp:1": _fn("nor"),
                    "user.cpp:2": _fn("nand_only", ["nand.cpp:1"])}
        merged = merge_model(_model(base_fns, pairs), _model({}, []), [])
        assert set(merged["functions"]["user.cpp:2"]["callsIds"]) == {"nand.cpp:1", "nor.cpp:1",
                                                                      "dev.cpp:1"}
