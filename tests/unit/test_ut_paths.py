"""ut_paths: solving input values per path for the UT export (UT_EXPORT_SPEC REQ-UE-10).

Each test builds a small CFG by hand -- the shape the flowchart engine emits:
START -> DECISION/LOOP_HEAD/SWITCH_HEAD/ACTION ... -> RETURN -> END, edges labelled
Yes/No or `case N` / `default` -- and asserts the values chosen for one return, or
the note saying why a value could not be chosen.
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

ENGINE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "engine")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from views.ut_paths import (  # noqa: E402
    Context, NONNULL, Unsupported, constants_from_macros, display, parse, solve, statements,
)


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------

def _cfg(nodes, edges):
    """nodes: [(id, type, rawCode)]; edges: [(src, dst, label)]. Entry = first node."""
    return {"entry": nodes[0][0],
            "exits": [n[0] for n in nodes if n[1] == "END"],
            "nodes": [{"id": i, "type": t, "rawCode": r, "label": r} for i, t, r in nodes],
            "edges": [{"source": s, "target": d, "label": lab} for s, d, lab in edges]}


def _spec(params=(), globals_=(), mocks=(), writebacks=(), written=(), ret_type="int",
          returns=()):
    """A spec whose return steps are named after their CFG node ids."""
    entries = ([{"kind": "parameter", "name": n, "type": t} for n, t in params]
               + [{"kind": "global", "name": n, "type": t} for n, t in globals_]
               + [{"kind": "mockReturn", "name": f"{n}()", "type": rt}
                  for n, rt, _ in mocks if rt and rt != "void"]
               + [{"kind": "mockWriteback", "name": label, "type": t} for label, t in writebacks])
    return {
        "name": "f", "qualifiedName": "f", "functionId": "L.C|U|f|", "unitKey": "L.C|U",
        "returnType": ret_type,
        "precondition": {
            "mocks": [{"functionId": f"L.D|D|{n}|", "name": n, "qualifiedName": n,
                       "returnType": rt, "parameters": [{"name": pn, "type": pt} for pn, pt in ps]}
                      for n, rt, ps in mocks],
            "parameters": [{"name": n, "type": t} for n, t in params],
            "globals": [{"name": n, "type": t} for n, t in list(globals_) + list(written)]},
        "input": {"entries": entries},
        "expected": {"returns": [{"step": r} for r in returns],
                     "globals": [{"name": n, "type": t} for n, t in written]},
        "testSteps": [{"number": r, "nodeId": r} for r in returns],
    }


def _solve(spec, cfg, dd=None, consts=None):
    ctx = Context(spec, dd or {}, consts or {})
    return solve(spec, cfg, ctx), ctx


def _vals(result, ctx):
    return {k: display(v, s, (ctx.variables.get(k) or {}).get("type", ""))
            for k, (v, s) in result["values"].items()}


def _branch(cond, yes="return 1", no="return 0"):
    """if (cond) <yes> else <no>."""
    return _cfg([("S", "START", "f()"), ("D", "DECISION", cond),
                 ("R1", "RETURN", yes), ("R2", "RETURN", no), ("E", "END", "")],
                [("S", "D", None), ("D", "R1", "Yes"), ("D", "R2", "No"),
                 ("R1", "E", None), ("R2", "E", None)])


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------

def test_parse_follows_c_precedence():
    assert parse("a || b && c") == ("or", ("name", "a"), ("and", ("name", "b"), ("name", "c")))
    assert parse("a + 2 * b > 3")[0] == "cmp"
    assert parse("x & M == 0") == ("bin", "&", ("name", "x"), ("cmp", "==", ("name", "M"), ("num", 0)))


def test_parse_reads_members_calls_casts_and_hex():
    assert parse("p->lba") == ("member", "p.lba")
    assert parse("Foo(a, b)") == ("call", "Foo", "a , b")
    assert parse("(uint8_t)x") == ("name", "x")
    assert parse("0x1F") == ("num", 31)
    assert parse("(a) - b")[0] == "bin"          # a grouping, not a cast


@pytest.mark.parametrize("text", ["a[1] > 0", "&x", "sizeof(int)", "*p > 0", "\"s\""])
def test_parse_rejects_shapes_it_cannot_solve(text):
    with pytest.raises(Unsupported):
        parse(text)


def test_statements_split_on_semicolons_and_on_bare_newlines():
    """The flowchart engine drops semicolons and puts one statement per line."""
    assert statements("result = f(result, limit)\nlimit  = limit / 2") == [
        "result = f(result, limit)", "limit  = limit / 2"]
    assert statements("int a = 1; int b = 2;") == ["int a = 1", "int b = 2"]
    assert statements("x = a +\n    b") == ["x = a +\n    b"]      # continues


# ---------------------------------------------------------------------------
# single conditions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cond, yes, no", [
    ("a > 0", "1", "0"),
    ("a >= 5", "5", "0"),
    ("a < -3", "-4", "0"),
    ("a <= 10", "0", "11"),
    ("a == 7", "7", "0"),
    ("a != 0", "1", "0"),
    ("0 < a", "1", "0"),                   # constant on the left
    ("a + 2 > 5", "4", "0"),               # offset folded into the bound
])
def test_one_comparison_each_edge(cond, yes, no):
    spec = _spec(params=[("a", "int")], returns=["R1", "R2"])
    res, ctx = _solve(spec, _branch(cond))
    assert _vals(res["R1"], ctx)["a"] == yes
    assert _vals(res["R2"], ctx)["a"] == no
    assert res["R1"]["status"] == res["R2"]["status"] == "solved"


def test_the_type_range_bounds_the_value():
    """`x < 0` on a uint8_t cannot hold: the Yes path is infeasible."""
    spec = _spec(params=[("x", "uint8_t")], returns=["R1", "R2"])
    res, _ = _solve(spec, _branch("x < 0"))
    assert res["R1"]["status"] == "unsolved"
    assert "contradict" in res["R1"]["notes"][0]
    assert res["R2"]["status"] == "solved"


def test_and_or_pick_a_consistent_alternative():
    spec = _spec(params=[("a", "int"), ("b", "int")], returns=["R1", "R2"])
    res, ctx = _solve(spec, _branch("a > 0 && b < 0"))
    assert _vals(res["R1"], ctx) == {"a": "1", "b": "-1"}
    assert _vals(res["R2"], ctx)["a"] == "0"                  # !(a > 0) suffices
    res, ctx = _solve(spec, _branch("a < -100 || a > 100"))
    assert _vals(res["R1"], ctx)["a"] == "-101"
    assert _vals(res["R2"], ctx)["a"] == "0"


def test_a_comparison_between_two_inputs():
    spec = _spec(params=[("a", "int"), ("b", "int")], returns=["R1", "R2"])
    res, ctx = _solve(spec, _branch("a > b", "return a", "return b"))
    v = _vals(res["R1"], ctx)
    assert int(v["a"]) > int(v["b"])
    assert res["R1"]["return"] == v["a"]
    v = _vals(res["R2"], ctx)
    assert int(v["a"]) <= int(v["b"])


def test_bool_parameter_is_a_json_bool_and_a_truth_test():
    spec = _spec(params=[("ready", "bool")], returns=["R1", "R2"])
    res, ctx = _solve(spec, _branch("ready"))
    assert _vals(res["R1"], ctx)["ready"] is True
    assert _vals(res["R2"], ctx)["ready"] is False


def test_negation():
    spec = _spec(params=[("a", "int")], returns=["R1", "R2"])
    res, ctx = _solve(spec, _branch("!(a == 3)"))
    assert _vals(res["R1"], ctx)["a"] == "0"
    assert _vals(res["R2"], ctx)["a"] == "3"


# ---------------------------------------------------------------------------
# symbols, pointers, bits
# ---------------------------------------------------------------------------

def test_enum_constants_resolve_and_keep_their_names():
    dd = {"Level": {"kind": "enum", "name": "Level", "enumerators": [
        {"name": "LEVEL_LOW", "value": 0}, {"name": "LEVEL_HIGH", "value": 2}]}}
    spec = _spec(params=[("lvl", "Level")], returns=["R1", "R2"])
    res, ctx = _solve(spec, _branch("lvl == LEVEL_HIGH"), dd=dd)
    assert _vals(res["R1"], ctx)["lvl"] == "LEVEL_HIGH"
    assert _vals(res["R2"], ctx)["lvl"] == "LEVEL_LOW"          # another enumerator


def test_macro_constants_come_from_the_layer_defines():
    consts = constants_from_macros(["-DMAX_LUN=8", "-DNEG=-1", "-DSUM=(MAX_LUN + 1)",
                                    "-DFLAG", "-DSTR=\"x\"", "-DUNK=(OTHER + 1)"])
    assert consts == {"MAX_LUN": 8, "NEG": -1, "SUM": 9}
    spec = _spec(params=[("lun", "int")], returns=["R1", "R2"])
    res, ctx = _solve(spec, _branch("lun >= MAX_LUN"), consts=consts)
    assert _vals(res["R1"], ctx)["lun"] == "8"


def test_source_defines_from_the_data_dictionary_are_constants():
    """`#define` entries (kind "define") resolve -- the layer's own wins, a define
    built from another resolves in any order, and a name with two values in other
    layers is left out rather than guessed."""
    dd = {"A@a.h:1": {"kind": "define", "name": "SHARED_SCALE", "value": "8", "layer": "L1"},
          "B@b.h:1": {"kind": "define", "name": "SHARED_SCALE", "value": "4", "layer": "L2"},
          "C@c.h:1": {"kind": "define", "name": "BIG", "value": "(SMALL * 2)", "layer": "L1"},
          "D@d.h:1": {"kind": "define", "name": "SMALL", "value": "5", "layer": "L1"},
          "E@e.h:1": {"kind": "define", "name": "TWO", "value": "1", "layer": "L2"},
          "F@f.h:1": {"kind": "define", "name": "TWO", "value": "2", "layer": "L3"}}
    spec = _spec(params=[("s", "int")], returns=["R1", "R2"])
    ctx = Context(spec, dd, {}, layer="L1")
    assert ctx.constants["SHARED_SCALE"] == 8
    assert ctx.constants["BIG"] == 10
    assert "TWO" not in ctx.constants
    res = solve(spec, _branch("s > BIG"), ctx)
    assert _vals(res["R1"], ctx)["s"] == "11"


def test_cxx_casts_are_their_operand():
    assert parse("static_cast<int>(x) > 3") == ("cmp", ">", ("name", "x"), ("num", 3))
    assert parse("reinterpret_cast<const Foo *>(p)") == ("name", "p")


def test_an_unknown_symbol_is_used_by_name_and_its_negation_is_a_note():
    spec = _spec(params=[("s", "int")], returns=["R1", "R2"])
    res, ctx = _solve(spec, _branch("s == STATUS_OK"))
    assert _vals(res["R1"], ctx)["s"] == "STATUS_OK"
    assert res["R1"]["status"] == "solved"
    assert res["R2"]["inputs"] == "partial"
    assert "STATUS_OK" in res["R2"]["notes"][0]


def test_pointer_null_and_non_null():
    spec = _spec(params=[("p", "const Cfg *")], returns=["R1", "R2"])
    res, ctx = _solve(spec, _branch("p == NULL"))
    assert _vals(res["R1"], ctx)["p"] is None
    assert res["R1"]["status"] == "solved"
    assert res["R2"]["values"]["p"][0] == NONNULL
    assert res["R2"]["inputs"] == "partial"
    assert "valid pointer" in res["R2"]["notes"][0]


@pytest.mark.parametrize("cond, yes, no", [
    ("flags & 0x4", "4", "0"),
    ("(flags & 0x6) == 0x2", "2", "0"),
    ("(flags & 0x1) != 0", "1", "0"),
])
def test_bit_tests(cond, yes, no):
    spec = _spec(params=[("flags", "uint8_t")], returns=["R1", "R2"])
    res, ctx = _solve(spec, _branch(cond))
    assert _vals(res["R1"], ctx)["flags"] == yes
    assert _vals(res["R2"], ctx)["flags"] == no


def test_struct_parameter_field():
    dd = {"Cfg": {"kind": "struct", "fields": [{"name": "mode", "type": "uint8_t"}]}}
    spec = _spec(params=[("cfg", "const Cfg *")], returns=["R1", "R2"])
    res, ctx = _solve(spec, _branch("cfg->mode == 3"), dd=dd)
    assert res["R1"]["values"]["cfg.mode"] == (3, None)


# ---------------------------------------------------------------------------
# mocks and assignments along the path
# ---------------------------------------------------------------------------

def test_a_mock_call_in_the_condition_sets_the_stub_return():
    spec = _spec(params=[("i", "int")], mocks=[("FilRead", "int", [("idx", "int")])],
                 returns=["R1", "R2"])
    res, ctx = _solve(spec, _branch("FilRead(i) != 0"))
    assert _vals(res["R1"], ctx)["FilRead()"] == "1"
    assert _vals(res["R2"], ctx)["FilRead()"] == "0"


def test_a_local_holding_a_mock_result_lands_on_the_mock():
    cfg = _cfg([("S", "START", "f()"), ("A", "ACTION", "int status = HilSend(cmd);"),
                ("D", "DECISION", "status == 0"), ("R1", "RETURN", "return status"),
                ("R2", "RETURN", "return -1"), ("E", "END", "")],
               [("S", "A", None), ("A", "D", None), ("D", "R1", "Yes"), ("D", "R2", "No"),
                ("R1", "E", None), ("R2", "E", None)])
    spec = _spec(params=[("cmd", "int")], mocks=[("HilSend", "int", [("c", "int")])],
                 returns=["R1", "R2"])
    res, ctx = _solve(spec, cfg)
    assert _vals(res["R1"], ctx)["HilSend()"] == "0"
    assert res["R1"]["return"] == "0"
    assert _vals(res["R2"], ctx)["HilSend()"] == "1"
    assert res["R2"]["return"] == "-1"


def test_a_field_the_mock_writes_back_compared_with_a_parameter():
    cfg = _cfg([("S", "START", "f()"), ("A", "ACTION", "FilReadPage(idx, &e)"),
                ("D", "DECISION", "e.lba == lba"), ("R1", "RETURN", "return 0"),
                ("R2", "RETURN", "return -4"), ("E", "END", "")],
               [("S", "A", None), ("A", "D", None), ("D", "R1", "Yes"), ("D", "R2", "No"),
                ("R1", "E", None), ("R2", "E", None)])
    spec = _spec(params=[("lba", "uint32_t"), ("idx", "uint16_t")],
                 mocks=[("FilReadPage", "int", [("i", "uint16_t"), ("e", "MapEntry *")])],
                 writebacks=[("e.lba", "uint32_t")], returns=["R1", "R2"])
    res, ctx = _solve(spec, cfg)
    v = _vals(res["R1"], ctx)
    assert v["e.lba"] == v["lba"]
    v = _vals(res["R2"], ctx)
    assert v["e.lba"] != v["lba"]


def test_self_assignment_does_not_loop_and_a_non_linear_condition_is_searched():
    """`x = x / 2` refers to the OLD x (no cycle). `x / 2 + 1 > 3` cannot be
    inverted, but it can be CHECKED: a bounded search over small values and the
    function's literals finds an x that takes the path."""
    cfg = _cfg([("S", "START", "f()"), ("A", "ACTION", "x = x / 2\ny = x + 1"),
                ("D", "DECISION", "y > 3"), ("R1", "RETURN", "return y"),
                ("R2", "RETURN", "return 0"), ("E", "END", "")],
               [("S", "A", None), ("A", "D", None), ("D", "R1", "Yes"), ("D", "R2", "No"),
                ("R1", "E", None), ("R2", "E", None)])
    spec = _spec(params=[("x", "int")], returns=["R1", "R2"])
    res, ctx = _solve(spec, cfg)
    x = int(_vals(res["R1"], ctx)["x"])
    assert x // 2 + 1 > 3                          # the path really is taken
    assert res["R1"]["status"] == "solved"
    assert res["R1"]["return"] == str(x // 2 + 1)
    assert int(_vals(res["R2"], ctx)["x"]) // 2 + 1 <= 3


def test_a_search_that_finds_nothing_says_so():
    cfg = _cfg([("S", "START", "f()"), ("A", "ACTION", "y = x * x"),
                ("D", "DECISION", "y == 2"), ("R1", "RETURN", "return 1"),
                ("R2", "RETURN", "return 0"), ("E", "END", "")],
               [("S", "A", None), ("A", "D", None), ("D", "R1", "Yes"), ("D", "R2", "No"),
                ("R1", "E", None), ("R2", "E", None)])
    spec = _spec(params=[("x", "int")], returns=["R1", "R2"])
    res, _ = _solve(spec, cfg)
    assert res["R1"]["inputs"] == "partial"          # no integer squares to 2
    assert "cannot invert" in res["R1"]["notes"][0]
    assert res["R2"]["status"] == "solved"


def test_a_function_that_runs_for_real_is_not_an_input():
    spec = _spec(params=[("x", "int")], returns=["R1", "R2"])
    res, _ = _solve(spec, _branch("isValid(x)"))
    assert res["R1"]["inputs"] == "partial"
    assert "runs for real" in res["R1"]["notes"][0]


def test_a_local_the_path_never_assigns_is_reported():
    spec = _spec(params=[("x", "int")], returns=["R1", "R2"])
    res, _ = _solve(spec, _branch("tmp > 0"))
    assert "never assigns" in res["R1"]["notes"][0]


# ---------------------------------------------------------------------------
# loops and switches
# ---------------------------------------------------------------------------

def _loop(head):
    return _cfg([("S", "START", "f()"), ("A", "ACTION", "int count = 0;"),
                 ("L", "LOOP_HEAD", head), ("B", "ACTION", "count++;"),
                 ("R", "RETURN", "return count"), ("E", "END", "")],
                [("S", "A", None), ("A", "L", None), ("L", "B", "Yes"), ("B", "L", None),
                 ("L", "R", "No"), ("R", "E", None)])


def test_for_loop_init_is_applied_before_the_condition():
    cfg = _cfg([("S", "START", "f()"), ("L", "LOOP_HEAD", "for (int i = 0; i < n; ++i)"),
                ("R1", "RETURN", "return i"), ("R2", "RETURN", "return -1"), ("E", "END", "")],
               [("S", "L", None), ("L", "R1", "Yes"), ("L", "R2", "No"),
                ("R1", "E", None), ("R2", "E", None)])
    spec = _spec(params=[("n", "int")], returns=["R1", "R2"])
    res, ctx = _solve(spec, cfg)
    assert _vals(res["R1"], ctx)["n"] == "1"            # enters the body: n > 0
    assert res["R1"]["return"] == "0"
    assert _vals(res["R2"], ctx)["n"] == "0"            # skips it: n <= 0


def test_while_loop_over_a_local_counter():
    spec = _spec(params=[("limit", "int")], returns=["R"])
    res, ctx = _solve(spec, _loop("count < limit"))
    assert _vals(res["R"], ctx)["limit"] == "0"         # first check fails
    assert res["R"]["return"] == "0"


def test_do_while_prefix_is_stripped():
    spec = _spec(params=[("limit", "int")], returns=["R"])
    res, ctx = _solve(spec, _loop("do-while: count < limit"))
    assert res["R"]["status"] == "solved"


def test_switch_case_and_default():
    cfg = _cfg([("S", "START", "f()"), ("W", "SWITCH_HEAD", "op"),
                ("R1", "RETURN", "return 10"), ("R2", "RETURN", "return 20"),
                ("R3", "RETURN", "return -1"), ("E", "END", "")],
               [("S", "W", None), ("W", "R1", "case 1"), ("W", "R2", "case 2"),
                ("W", "R3", "default"), ("R1", "E", None), ("R2", "E", None), ("R3", "E", None)])
    spec = _spec(params=[("op", "int")], returns=["R1", "R2", "R3"])
    res, ctx = _solve(spec, cfg)
    assert [_vals(res[r], ctx)["op"] for r in ("R1", "R2", "R3")] == ["1", "2", "0"]
    assert [res[r]["return"] for r in ("R1", "R2", "R3")] == ["10", "20", "-1"]


# ---------------------------------------------------------------------------
# what a path returns, writes and calls
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ret, expected", [
    ("return -1", "-1"),
    ("return a * 2 + 1", "7"),
    ("return a > 2 ? A_BIG : A_SMALL", "A_BIG"),
    ("return STATUS_OK", "STATUS_OK"),
    ("return a & 0x2", "2"),
])
def test_return_value_is_evaluated_with_the_chosen_inputs(ret, expected):
    spec = _spec(params=[("a", "int")], returns=["R1", "R2"])
    res, _ = _solve(spec, _branch("a == 3", yes=ret))
    assert res["R1"]["return"] == expected
    assert res["R1"]["expected"] == "known"


def test_bool_function_returns_true_false():
    spec = _spec(params=[("a", "int")], ret_type="bool", returns=["R1", "R2"])
    res, _ = _solve(spec, _branch("a > 0", yes="return true", no="return a > 5"))
    assert res["R1"]["return"] == "true"
    assert res["R2"]["return"] == "false"


def test_a_return_through_a_real_call_is_open():
    spec = _spec(params=[("a", "int")], returns=["R1", "R2"])
    res, _ = _solve(spec, _branch("a > 0", yes="return clip(a, 0, 9)"))
    assert res["R1"]["inputs"] == "solved"
    assert res["R1"]["expected"] == "open"
    assert res["R1"]["return"] is None


# ---------------------------------------------------------------------------
# helpers that run for real are executed
# ---------------------------------------------------------------------------

def _helper(name, sig, nodes, edges):
    from views.ut_paths import helpers_from_cfgs
    return helpers_from_cfgs({f"L.C|U|{name}|x": dict(_cfg([("HS", "START", sig)] + nodes,
                                                           edges))})


CLIP = ("clip", "clip(int v, int lo, int hi)",
        [("C1", "DECISION", "v < lo"), ("CR1", "RETURN", "return lo"),
         ("C2", "DECISION", "v > hi"), ("CR2", "RETURN", "return hi"),
         ("CR3", "RETURN", "return v"), ("CE", "END", "")],
        [("HS", "C1", None), ("C1", "CR1", "Yes"), ("C1", "C2", "No"), ("C2", "CR2", "Yes"),
         ("C2", "CR3", "No"), ("CR1", "CE", None), ("CR2", "CE", None), ("CR3", "CE", None)])


def test_helper_parameters_are_read_from_its_start_node():
    helpers = _helper(*CLIP)
    assert helpers["clip"]["params"] == ["v", "lo", "hi"]


def test_a_return_through_a_helper_is_computed_by_executing_it():
    spec = _spec(params=[("a", "int")], returns=["R1", "R2"])
    ctx = Context(spec, {}, {})
    ctx.helpers = _helper(*CLIP)
    res = solve(spec, _branch("a > 20", yes="return clip(a, 0, 9)", no="return clip(a, 0, 9)"),
                ctx)
    assert res["R1"]["return"] == "9"                 # a = 21, clipped to 9
    assert res["R2"]["return"] == "0"                 # a = 0
    assert res["R1"]["status"] == res["R2"]["status"] == "solved"


def test_a_condition_on_a_helper_result_is_met_by_search():
    cfg = _cfg([("S", "START", "f()"), ("A", "ACTION", "int h = clip(x, 0, 100);"),
                ("D", "DECISION", "h > 50"), ("R1", "RETURN", "return 1"),
                ("R2", "RETURN", "return 0"), ("E", "END", "")],
               [("S", "A", None), ("A", "D", None), ("D", "R1", "Yes"), ("D", "R2", "No"),
                ("R1", "E", None), ("R2", "E", None)])
    spec = _spec(params=[("x", "int")], returns=["R1", "R2"])
    ctx = Context(spec, {}, {})
    ctx.helpers = _helper(*CLIP)
    res = solve(spec, cfg, ctx)
    x = int(_vals(res["R1"], ctx)["x"])
    assert min(max(x, 0), 100) > 50
    assert res["R1"]["status"] == "solved"
    assert res["R2"]["status"] == "solved"            # x = 0 already takes No


def test_a_helper_loop_really_iterates():
    helpers = _helper("sumTo", "sumTo(int n)",
                      [("A", "ACTION", "int s = 0;"),
                       ("L", "LOOP_HEAD", "for (int i = 1; i <= n; i++)"),
                       ("B", "ACTION", "s += i;"), ("R", "RETURN", "return s"), ("E", "END", "")],
                      [("HS", "A", None), ("A", "L", None), ("L", "B", "Yes"), ("B", "L", None),
                       ("L", "R", "No"), ("R", "E", None)])
    spec = _spec(params=[("n", "int")], returns=["R1", "R2"])
    ctx = Context(spec, {}, {})
    ctx.helpers = helpers
    res = solve(spec, _branch("n == 4", yes="return sumTo(n)"), ctx)
    assert res["R1"]["return"] == "10"                # 1 + 2 + 3 + 4


def test_a_write_through_a_pointer_is_skipped_safely():
    """`*out = v` cannot feed a wrong value into a result: reading it back
    (`return *out`) is itself unsupported. So the write is skipped, not refused."""
    helpers = _helper("fill", "fill(int *out, int v)",
                      [("A", "ACTION", "*out = v;"), ("R", "RETURN", "return 0"), ("E", "END", "")],
                      [("HS", "A", None), ("A", "R", None), ("R", "E", None)])
    spec = _spec(params=[("a", "int")], returns=["R1", "R2"])
    ctx = Context(spec, {}, {})
    ctx.helpers = helpers
    res = solve(spec, _branch("a > 0", yes="return fill(0, a)"), ctx)
    assert res["R1"]["return"] == "0"


def test_reading_back_through_a_pointer_stays_open():
    helpers = _helper("fill", "fill(int *out, int v)",
                      [("A", "ACTION", "*out = v;"), ("R", "RETURN", "return *out"),
                       ("E", "END", "")],
                      [("HS", "A", None), ("A", "R", None), ("R", "E", None)])
    spec = _spec(params=[("a", "int")], returns=["R1", "R2"])
    ctx = Context(spec, {}, {})
    ctx.helpers = helpers
    res = solve(spec, _branch("a > 0", yes="return fill(0, a)"), ctx)
    assert res["R1"]["expected"] == "open"
    assert res["R1"]["return"] is None


def test_a_helper_that_never_returns_hits_the_step_limit():
    helpers = _helper("spin", "spin(int v)",
                      [("L", "LOOP_HEAD", "while (1)"), ("B", "ACTION", "v++;"),
                       ("R", "RETURN", "return v"), ("E", "END", "")],
                      [("HS", "L", None), ("L", "B", "Yes"), ("B", "L", None), ("L", "R", "No"),
                       ("R", "E", None)])
    spec = _spec(params=[("a", "int")], returns=["R1", "R2"])
    ctx = Context(spec, {}, {})
    ctx.helpers = helpers
    res = solve(spec, _branch("a > 0", yes="return spin(a)"), ctx)
    assert res["R1"]["expected"] == "open"
    assert "step limit" in res["R1"]["notes"][-1]


def test_a_helper_does_not_see_the_callers_parameters():
    """Inside `leak`, `a` is not its own name: it must not resolve to the caller's
    parameter `a`, or the helper would compute with a value it never received."""
    helpers = _helper("leak", "leak(int v)",
                      [("R", "RETURN", "return v + a"), ("E", "END", "")],
                      [("HS", "R", None), ("R", "E", None)])
    spec = _spec(params=[("a", "int")], returns=["R1", "R2"])
    ctx = Context(spec, {}, {})
    ctx.helpers = helpers
    res = solve(spec, _branch("a > 0", yes="return leak(a)"), ctx)
    assert res["R1"]["expected"] == "open"


# ---------------------------------------------------------------------------
# the function itself is executed when its conditions cannot be solved
# ---------------------------------------------------------------------------

def test_a_loop_with_a_fixed_bound_is_solved_by_executing_the_function():
    """`for (i = 0; i < 10; i++)` always runs ten times: the exit edge is not
    reachable on the first iteration, which is all the symbolic walk sees. Running
    the function reaches the return -- and the run gives the expected value."""
    cfg = _cfg([("S", "START", "f(int a)"), ("A", "ACTION", "int qw = 0;"),
                ("L", "LOOP_HEAD", "for (int i = 0; i < 10; i++)"),
                ("B", "ACTION", "qw = qw + 1\na = a + qw"), ("R", "RETURN", "return a * qw"),
                ("E", "END", "")],
               [("S", "A", None), ("A", "L", None), ("L", "B", "Yes"), ("B", "L", None),
                ("L", "R", "No"), ("R", "E", None)])
    spec = _spec(params=[("a", "int")], returns=["R"])
    res, ctx = _solve(spec, cfg)
    assert res["R"]["status"] == "solved"
    assert res["R"]["return"] == "550"                 # a = 0: (1+2+..+10) * 10
    assert "executing the function" in res["R"]["notes"][0]


def test_a_null_check_on_an_out_parameter():
    """`Operation *op` is an output to the document, but `if (!op)` is a condition
    on it -- and the call must pass something for it."""
    spec = _spec(params=[("a", "int")], returns=["R1", "R2"])
    spec["precondition"]["parameters"].append({"name": "op", "type": "Operation *"})
    res, ctx = _solve(spec, _branch("!op", yes="return 0", no="return a"))
    assert res["R1"]["values"]["op"] == (None, None)            # NULL takes the Yes edge
    assert res["R1"]["status"] == "solved"
    assert res["R2"]["values"]["op"][0] == NONNULL


def test_a_method_call_on_a_mocked_method_is_the_stub_value():
    spec = _spec(params=[("a", "int")], mocks=[("apply", "int", [("x", "int")])],
                 returns=["R1", "R2"])
    res, ctx = _solve(spec, _branch("a > 0", yes="return op->apply(a, 1)"))
    assert res["R1"]["return"] == "1"                            # the stub's default


def test_a_return_spliced_in_from_a_callee_says_so():
    spec = _spec(params=[("a", "int")], returns=["R1"])
    spec["testSteps"] = [{"number": "R1", "nodeId": "N99"}]
    res, _ = _solve(spec, _branch("a > 0"))
    assert res["R1"]["status"] == "unsolved"
    assert "spliced" in res["R1"]["notes"][0]


def test_void_cast_statement_is_ignored():
    cfg = _cfg([("S", "START", "f(int a)"), ("A", "ACTION", "(void)a;\nint b = a + 1;"),
                ("D", "DECISION", "b > 5"), ("R1", "RETURN", "return b"),
                ("R2", "RETURN", "return 0"), ("E", "END", "")],
               [("S", "A", None), ("A", "D", None), ("D", "R1", "Yes"), ("D", "R2", "No"),
                ("R1", "E", None), ("R2", "E", None)])
    spec = _spec(params=[("a", "int")], returns=["R1", "R2"])
    res, ctx = _solve(spec, cfg)
    assert _vals(res["R1"], ctx)["a"] == "5" and res["R1"]["return"] == "6"


def test_an_out_parameter_the_function_writes_gets_a_format_note():
    spec = _spec(params=[("a", "int")], returns=["R1", "R2"])
    spec["precondition"]["parameters"].append({"name": "out", "type": "int *"})
    spec["expected"]["outParameters"] = [{"name": "out", "type": "int *"}]
    res, _ = _solve(spec, _branch("a > 0"))
    assert res["R1"]["status"] == "solved"              # informational, not a verdict
    assert any("`out` must point at a buffer" in n for n in res["R1"]["notes"])


def test_written_globals_after_the_path():
    cfg = _cfg([("S", "START", "f()"), ("D", "DECISION", "a < 0"),
                ("A", "ACTION", "gErr++;\ngLast = a;"), ("R1", "RETURN", "return -1"),
                ("R2", "RETURN", "return 0"), ("E", "END", "")],
               [("S", "D", None), ("D", "A", "Yes"), ("A", "R1", None), ("D", "R2", "No"),
                ("R1", "E", None), ("R2", "E", None)])
    spec = _spec(params=[("a", "int")], globals_=[("gErr", "int")],
                 written=[("gErr", "int"), ("gLast", "int")], returns=["R1", "R2"])
    res, _ = _solve(spec, cfg)
    assert res["R1"]["globals"] == {"gErr": "1", "gLast": "-1"}
    assert res["R2"]["globals"]["gErr"] == "0"            # unchanged: its precondition


def test_stub_calls_keep_known_arguments_and_skip_out_parameters():
    cfg = _cfg([("S", "START", "f()"), ("A", "ACTION", "HilNotify(ERR_RANGE, &st)"),
                ("R", "RETURN", "return 0"), ("E", "END", "")],
               [("S", "A", None), ("A", "R", None), ("R", "E", None)])
    spec = _spec(mocks=[("HilNotify", "void", [("code", "int"), ("out", "Status *")])],
                 returns=["R"])
    res, _ = _solve(spec, cfg)
    assert res["R"]["stubCalls"] == [("HilNotify", {"code": "ERR_RANGE"})]


def test_a_void_function_gets_one_result_for_its_exit():
    cfg = _cfg([("S", "START", "f()"), ("A", "ACTION", "g = 1;"), ("E", "END", "")],
               [("S", "A", None), ("A", "E", None)])
    spec = _spec(written=[("g", "int")], ret_type="void")
    res, _ = _solve(spec, cfg)
    assert list(res) == [""]
    assert res[""]["globals"] == {"g": "1"}


def test_no_cfg_is_unsolved_with_a_reason():
    spec = _spec(params=[("a", "int")], returns=["R1"])
    res, _ = _solve(spec, None)
    assert res["R1"]["status"] == "unsolved"
    assert "control-flow graph" in res["R1"]["notes"][0]


def test_same_input_same_output():
    spec = _spec(params=[("a", "int"), ("b", "int")], returns=["R1", "R2"])
    first, _ = _solve(spec, _branch("a > b && a != 5"))
    second, _ = _solve(spec, _branch("a > b && a != 5"))
    assert first == second
