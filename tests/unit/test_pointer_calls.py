"""Calls through a function pointer reach what the pointer can hold (review SWE3-V5-02).

    something->somesome = d.k;     // one place
    something->somesome(7);        // another place: a call to the function d.k holds

libclang resolves such a call to the FIELD (or variable, or parameter), not to a function, so
it had no call edge -- and a field named like a function (`o->add(1)`) was matched by NAME to
the first function anywhere called `add`. Phase 1 now records what every slot can hold and
links each call through it (incremental/pointer_calls.py); the narrowed-parse merge links
again with the stores of the files it did not re-parse (parse_merge).

Parser tests need libclang, so those skip without it (see test_address_taken.py).
"""
import os
import sys
from collections import defaultdict

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ENGINE = os.path.join(PROJECT_ROOT, "engine")
if _ENGINE not in sys.path:
    sys.path.insert(0, _ENGINE)

from incremental.pointer_calls import link_pointer_calls, slot_contents, strip_edges  # noqa: E402
from incremental.parse_merge import merge_model  # noqa: E402


# ---------------------------------------------------------------- the resolver (pure)

def test_a_slot_holds_what_is_stored_and_what_is_copied_into_it():
    stores = [("a.c", "f:read", "fn:fA"),
              ("b.c", "f:k", "fn:fB"),
              ("c.c", "f:somesome", "slot:f:k"),          # o->somesome = d.k
              ("c.c", "f:twice", "slot:f:somesome")]      # copied again, in a chain
    holds = slot_contents(stores)
    assert holds["f:read"] == {"fA"}
    assert holds["f:somesome"] == {"fB"}
    assert holds["f:twice"] == {"fB"}


def test_slot_copies_in_a_cycle_terminate():
    stores = [("a.c", "v:x", "slot:v:y"), ("a.c", "v:y", "slot:v:x"), ("a.c", "v:x", "fn:f")]
    holds = slot_contents(stores)
    assert holds["v:x"] == holds["v:y"] == {"f"}


def test_link_adds_only_new_edges_and_skips_self_and_unknown_functions():
    cg = defaultdict(list, {"caller": ["fA"]})            # already calls fA directly
    rev = defaultdict(list, {"fA": ["caller"]})
    stores = [("a.c", "f:read", "fn:fA"), ("a.c", "f:read", "fn:fB"),
              ("a.c", "f:read", "fn:caller"), ("a.c", "f:read", "fn:libc_memcpy")]
    added = link_pointer_calls(cg, rev, stores, [("caller", "f:read")],
                               {"caller", "fA", "fB"})
    assert added == [("caller", "fB")]                   # fA was direct; self and libc skipped
    assert cg["caller"] == ["fA", "fB"]
    assert rev["fB"] == ["caller"]
    strip_edges(cg, added)
    assert cg["caller"] == ["fA"]                        # the direct call stays


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


def _call_graph(P, tmp_path, source, lang="c++"):
    """Parse a snippet; run Phase 1's call visitor and pointer link on it; return
    {caller name: sorted callee names}. The parser's module state is saved and restored."""
    from clang import cindex

    src = tmp_path / ("t.cpp" if lang == "c++" else "t.c")
    src.write_text(source, encoding="utf-8")
    args = ["-x", lang] + (["-std=c++20"] if lang == "c++" else [])
    tu = cindex.Index.create().parse(str(src), args=args)
    assert not [d for d in tu.diagnostics if d.severity >= 3], [d.spelling for d in tu.diagnostics]

    saved = {n: getattr(P, n) for n in ("functions", "call_graph", "reverse_call_graph",
                                         "_visited_call_keys", "_ptr_stores", "_ptr_calls",
                                         "is_project_file")}
    try:
        P.functions = {}
        P.call_graph = defaultdict(list)
        P.reverse_call_graph = defaultdict(list)
        P._visited_call_keys = set()
        P._ptr_stores = set()
        P._ptr_calls = set()
        P.is_project_file = lambda _p: True
        names = {}

        def collect(c):
            if (c.kind in (cindex.CursorKind.FUNCTION_DECL, cindex.CursorKind.CXX_METHOD)
                    and c.is_definition()):
                key = P.get_function_key(c)
                P.functions[key] = {"functionName": c.spelling}
                names[key] = c.spelling
                P._walk_ptr_stores(c, "t", lambda s, sl, v: P._ptr_stores.add((s, sl, v)))
            elif c.kind == cindex.CursorKind.VAR_DECL and c.semantic_parent.kind == cindex.CursorKind.TRANSLATION_UNIT:
                P._walk_ptr_stores(c, "t", lambda s, sl, v: P._ptr_stores.add((s, sl, v)))
            for ch in c.get_children():
                collect(ch)

        collect(tu.cursor)
        P.visit_calls(tu.cursor)
        link_pointer_calls(P.call_graph, P.reverse_call_graph, P._ptr_stores, P._ptr_calls,
                           set(P.functions))
        return {names[k]: sorted(names[c] for c in v) for k, v in P.call_graph.items() if v}
    finally:
        for n, v in saved.items():
            setattr(P, n, v)


_CPP = """
typedef int (*Fn)(int);
struct Ops { int id; Fn read; Fn add; };      // a field named like the function below
int add(int a) { return a; }
int fA(int x) { return x; }
int fB(int x) { return x; }
int fC(int x) { return x; }
int fD(int x) { return x; }
static Ops g_pos = { 1, fA, fB };             // positional: read = fA, add = fB
static Ops g_des = { .read = fC };            // designated
Fn g_tbl[] = { fA, &fD };                     // a table, one entry through &
struct Holder { Fn cb; };
Holder g_h;
void reg(Fn cb) { g_h.cb = cb; }              // a parameter stored in a field
void setup() { reg(fD); }                     // ...and what is passed for it
struct D { Fn k; };
D g_d = { fB };
struct S { Fn somesome; };
void store(S* s) { s->somesome = g_d.k; }     // a field copied from another field
int callRead(Ops* o) { return o->read(1); }
int callAdd(Ops* o) { return o->add(1); }
int callTbl(int i) { return g_tbl[i](2); }
int callCb() { return g_h.cb(3); }
int callSome(S* s) { return s->somesome(4); }
int callLocal() { Fn fp = fC; return fp(5); }
int callDeref() { Fn fp = fA; return (*fp)(6); }
int callTernary(int c) { Fn fp = c ? fA : fB; return fp(7); }
int callDirect() { return add(8); }
"""


def test_each_call_through_a_pointer_reaches_what_it_can_hold(parser_mod, tmp_path):
    g = _call_graph(parser_mod, tmp_path, _CPP)
    assert g["callRead"] == ["fA", "fC"]          # positional + designated stores
    assert g["callTbl"] == ["fA", "fD"]           # every table entry
    assert g["callCb"] == ["fD"]                  # through the parameter of reg()
    assert g["callSome"] == ["fB"]                # o->somesome = d.k, then o->somesome()
    assert g["callLocal"] == ["fC"]
    assert g["callDeref"] == ["fA"]               # (*fp)(x)
    assert g["callTernary"] == ["fA", "fB"]       # both arms of ?:
    assert g["setup"] == ["reg"]                  # an ordinary call is untouched
    assert g["callDirect"] == ["add"]


def test_a_field_named_like_a_function_is_not_a_call_to_that_function(parser_mod, tmp_path):
    g = _call_graph(parser_mod, tmp_path, _CPP)
    # `o->add(1)` calls what the field holds (fB), never the function that happens to be
    # called `add` -- the name match used to link it there.
    assert g["callAdd"] == ["fB"]
    assert "store" not in g                       # a store is not a call


def test_c_designated_initializer_and_deref_through_a_field(parser_mod, tmp_path):
    g = _call_graph(parser_mod, tmp_path, """
typedef int (*Fn)(int);
struct Ops { Fn read; Fn write; };
int fA(int x) { return x; }
int fB(int x) { return x; }
struct Ops g_ops = { .write = fB, .read = fA };
int callC(struct Ops *o) { return (*o->read)(1) + o->write(2); }
""", lang="c")
    assert g["callC"] == ["fA", "fB"]


def test_a_pointer_nothing_is_stored_in_links_to_nothing(parser_mod, tmp_path):
    g = _call_graph(parser_mod, tmp_path, """
typedef int (*Fn)(int);
struct Ops { Fn read; };
int read(int x) { return x; }
int callEmpty(Ops* o) { return o->read(1); }
""")
    assert "callEmpty" not in g                   # and not to the function `read`


# ---------------------------------------------------------------- the narrowed-parse merge

def _fn(calls=()):
    return {"callsIds": list(calls), "calledByIds": []}


def test_merge_links_again_with_the_stores_of_files_not_reparsed():
    # caller.c calls through f:read; the only store is in table.c. A narrowed parse
    # re-parses caller.c alone: its partial parse cannot see the store, the baseline can.
    baseline = {
        "functions": {"caller": _fn(["fA"]), "fA": _fn(), "fB": _fn()},
        "entity_files": {"caller": "caller.c", "fA": "table.c", "fB": "table.c"},
        "pointer_calls": {"stores": [["table.c", "f:read", "fn:fA"]],
                          "calls": [["caller", "f:read"]], "edges": [["caller", "fA"]]},
    }
    fresh = {
        "functions": {"caller": _fn([])},           # its own parse found no store
        "entity_files": {"caller": "caller.c"},
        "pointer_calls": {"stores": [], "calls": [["caller", "f:read"]], "edges": []},
    }
    merged = merge_model(baseline, fresh, ["caller.c"])
    assert merged["functions"]["caller"]["callsIds"] == ["fA"]
    assert merged["functions"]["fA"]["calledByIds"] == ["caller"]
    assert merged["pointer_calls"]["edges"] == [["caller", "fA"]]


def test_merge_drops_an_edge_whose_store_was_removed():
    # table.c is re-parsed and now stores fB, not fA; caller.c is not re-parsed, so its
    # callsIds come from the baseline and still carry the old pointer edge to fA.
    baseline = {
        "functions": {"caller": _fn(["fA"]), "fA": _fn(), "fB": _fn()},
        "entity_files": {"caller": "caller.c", "fA": "table.c", "fB": "table.c"},
        "pointer_calls": {"stores": [["table.c", "f:read", "fn:fA"]],
                          "calls": [["caller", "f:read"]], "edges": [["caller", "fA"]]},
    }
    fresh = {
        "functions": {"fA": _fn(), "fB": _fn()},
        "entity_files": {"fA": "table.c", "fB": "table.c"},
        "pointer_calls": {"stores": [["table.c", "f:read", "fn:fB"]], "calls": [], "edges": []},
    }
    merged = merge_model(baseline, fresh, ["table.c"])
    assert merged["functions"]["caller"]["callsIds"] == ["fB"]
    assert merged["functions"]["fA"]["calledByIds"] == []


def test_merge_keeps_a_direct_call_to_a_function_the_pointer_also_reaches():
    baseline = {
        "functions": {"caller": _fn(["fA"]), "fA": _fn()},
        "entity_files": {"caller": "caller.c", "fA": "table.c"},
        # fA is called directly AND stored; the pointer added no edge (it was already there)
        "pointer_calls": {"stores": [["table.c", "f:read", "fn:fA"]],
                          "calls": [["caller", "f:read"]], "edges": []},
    }
    fresh = {
        "functions": {"fA": _fn()}, "entity_files": {"fA": "table.c"},
        "pointer_calls": {"stores": [], "calls": [], "edges": []},   # the store is gone
    }
    merged = merge_model(baseline, fresh, ["table.c"])
    assert merged["functions"]["caller"]["callsIds"] == ["fA"]     # the direct call stays
