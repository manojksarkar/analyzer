"""CFG -> Test Steps (SWE.4).

Graphs are hand-built so the shapes under test are explicit: straight line,
if/else, nested if, loop, switch, and a function whose branches return.
"""
import os
import sys

import pytest

ENGINE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "engine")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from views.test_steps import build_steps, _ipdom, _post_dominators, _index  # noqa: E402


def _cfg(nodes, edges, entry="N1", exits=("NE",)):
    return {"entry": entry, "exits": list(exits),
            "nodes": [{"id": i, "type": t, "label": l, "rawCode": r or l,
                       "line": n + 1, "endLine": n + 1}
                      for n, (i, t, l, r) in enumerate(nodes)],
            "edges": [{"source": s, "target": t, "label": lab}
                      for s, t, lab in edges]}


SPEC = {"name": "fn", "precondition": {"parameters": [{"name": "x"}]}}


def _numbers(steps):
    return [s["number"] for s in steps]


def _texts(steps):
    return {s["number"]: s["text"] for s in steps}


# --- straight line ---------------------------------------------------------

def test_linear_flow_is_numbered_flat():
    cfg = _cfg([("N1", "START", "Start: fn", ""), ("N2", "ACTION", "int a = 1;", ""),
                ("N3", "RETURN", "Return a", ""), ("NE", "END", "End", "")],
               [("N1", "N2", None), ("N2", "N3", None), ("N3", "NE", None)])
    steps, returns, _ = build_steps(cfg, SPEC)
    assert _numbers(steps) == ["1", "2", "3"]
    assert _texts(steps)["1"] == "Issue function fn with inputs x."
    assert [r["step"] for r in returns] == ["3"]


def test_entry_step_says_void_when_there_are_no_parameters():
    cfg = _cfg([("N1", "START", "Start: fn", ""), ("NE", "END", "End", "")],
               [("N1", "NE", None)])
    steps, _, _ = build_steps(cfg, {"name": "fn", "precondition": {"parameters": []}})
    assert steps[0]["text"] == "Issue function fn with input VOID."


# --- decision --------------------------------------------------------------

@pytest.fixture
def if_else():
    return _cfg([("N1", "START", "Start: fn", ""), ("N2", "DECISION", "Check: x < 0?", ""),
                 ("N3", "RETURN", "Return -1", ""), ("N4", "RETURN", "Return 1", ""),
                 ("NE", "END", "End", "")],
                [("N1", "N2", None), ("N2", "N3", "Yes"), ("N2", "N4", "No"),
                 ("N3", "NE", None), ("N4", "NE", None)])


def test_decision_legs_are_sub_numbered_true_then_false(if_else):
    steps, _, _ = build_steps(if_else, SPEC)
    t = _texts(steps)
    assert t["2"] == "Check whether x < 0."
    assert t["2.a"].startswith("True:")
    assert t["2.b"].startswith("False:")


def test_single_step_leg_is_inlined_after_the_label(if_else):
    t = _texts(build_steps(if_else, SPEC)[0])
    assert t["2.a"] == "True: Return -1."


def test_every_return_gets_an_entry_naming_its_step(if_else):
    _, returns, _ = build_steps(if_else, SPEC)
    assert {r["step"] for r in returns} == {"2.a", "2.b"}
    assert {r["text"] for r in returns} == {"Successfully returned -1",
                                            "Successfully returned 1"}


def test_return_carries_the_source_expression_beside_the_wording():
    """The wording paraphrases; the bracket gives the tester something exact.
    Two branches can share wording while returning different expressions."""
    cfg = _cfg([("N1", "START", "Start: fn", ""), ("N2", "DECISION", "Check: x < 0?", ""),
                ("N3", "RETURN", "Return validated value", "return validate(10000);"),
                ("N4", "RETURN", "Return validated value", "return validate(x);"),
                ("NE", "END", "End", "")],
               [("N1", "N2", None), ("N2", "N3", "Yes"), ("N2", "N4", "No"),
                ("N3", "NE", None), ("N4", "NE", None)])
    _, returns, _ = build_steps(cfg, SPEC)
    texts = {r["text"] for r in returns}
    assert "Successfully returned validated value [validate(10000)]" in texts
    assert "Successfully returned validated value [validate(x)]" in texts


def test_return_omits_the_bracket_when_wording_is_already_the_source():
    cfg = _cfg([("N1", "START", "Start: fn", ""),
                ("N2", "RETURN", "Return 0", "return 0;"), ("NE", "END", "End", "")],
               [("N1", "N2", None), ("N2", "NE", None)])
    _, returns, _ = build_steps(cfg, SPEC)
    assert returns[0]["text"] == "Successfully returned 0"


def test_nested_decision_nests_deeper():
    cfg = _cfg([("N1", "START", "Start: fn", ""), ("N2", "DECISION", "Check: x < 0?", ""),
                ("N3", "RETURN", "Return -1", ""), ("N4", "DECISION", "Check: x == 0?", ""),
                ("N5", "RETURN", "Return 0", ""), ("N6", "RETURN", "Return 1", ""),
                ("NE", "END", "End", "")],
               [("N1", "N2", None), ("N2", "N3", "Yes"), ("N2", "N4", "No"),
                ("N4", "N5", "Yes"), ("N4", "N6", "No"),
                ("N3", "NE", None), ("N5", "NE", None), ("N6", "NE", None)])
    steps, returns, _ = build_steps(cfg, SPEC)
    nums = _numbers(steps)
    assert "2.b.1" in nums and "2.b.1.a" in nums and "2.b.1.b" in nums
    assert {r["step"] for r in returns} == {"2.a", "2.b.1.a", "2.b.1.b"}


# --- loop ------------------------------------------------------------------

def test_loop_body_nests_and_continuation_does_not():
    cfg = _cfg([("N1", "START", "Start: fn", ""), ("N2", "LOOP_HEAD", "Loop: i < n?", ""),
                ("N3", "ACTION", "sum += i", ""), ("N4", "RETURN", "Return sum", ""),
                ("NE", "END", "End", "")],
               [("N1", "N2", None), ("N2", "N3", "Yes"), ("N3", "N2", None),
                ("N2", "N4", "No"), ("N4", "NE", None)])
    steps, _, _ = build_steps(cfg, SPEC)
    t = _texts(steps)
    assert t["2"].startswith("Repeat ")
    assert "2.a" in t                      # body nests
    assert t["3"] == "Return sum."         # continuation resumes at top level


def test_back_edge_does_not_loop_forever():
    cfg = _cfg([("N1", "START", "Start: fn", ""), ("N2", "LOOP_HEAD", "Loop: forever?", ""),
                ("N3", "ACTION", "tick()", ""), ("N4", "RETURN", "Return 0", ""),
                ("NE", "END", "End", "")],
               [("N1", "N2", None), ("N2", "N3", "Yes"), ("N3", "N2", None),
                ("N2", "N4", "No"), ("N4", "NE", None)])
    steps, _, _ = build_steps(cfg, SPEC)
    assert len(steps) < 20


# --- switch ----------------------------------------------------------------

@pytest.fixture
def switch():
    return _cfg([("N1", "START", "Start: fn", ""), ("N2", "SWITCH_HEAD", "Switch on: op?", ""),
                 ("N3", "ACTION", "r = 1", ""), ("N4", "BREAK", "Exit loop", ""),
                 ("N5", "ACTION", "r = 2", ""), ("N6", "BREAK", "Exit loop", ""),
                 ("N7", "RETURN", "Return r", ""), ("NE", "END", "End", "")],
                [("N1", "N2", None), ("N2", "N3", "case 1"), ("N2", "N5", "default"),
                 ("N3", "N4", None), ("N4", "N7", None),
                 ("N5", "N6", None), ("N6", "N7", None), ("N7", "NE", None)])


def test_switch_cases_keep_their_labels(switch):
    t = _texts(build_steps(switch, SPEC)[0])
    assert t["2"] == "Select on op."
    assert t["2.a"].startswith("case 1:") and t["2.b"].startswith("default:")


def test_break_inside_a_switch_says_switch_not_loop(switch):
    texts = " ".join(_texts(build_steps(switch, SPEC)[0]).values())
    assert "Exit the switch." in texts and "Exit the loop." not in texts


# --- label hygiene ---------------------------------------------------------

def test_graphviz_markup_is_stripped_from_step_text():
    cfg = _cfg([("N1", "START", "Start: fn", ""),
                ("N2", "ACTION", "int a = f();<br/>Calls: f(), g()", ""),
                ("N3", "RETURN", "Return a", ""), ("NE", "END", "End", "")],
               [("N1", "N2", None), ("N2", "N3", None), ("N3", "NE", None)])
    text = _texts(build_steps(cfg, SPEC)[0])["2"]
    assert "<br" not in text and "Calls:" not in text and ";." not in text


def test_a_mocked_callee_is_named_at_the_point_it_is_reached():
    cfg = _cfg([("N1", "START", "Start: fn", ""), ("N2", "ACTION", "int a = helper();", ""),
                ("N3", "RETURN", "Return a", ""), ("NE", "END", "End", "")],
               [("N1", "N2", None), ("N2", "N3", None), ("N3", "NE", None)])
    text = _texts(build_steps(cfg, SPEC, ["helper()"])[0])["2"]
    # The node is nothing but the mocked call, so the mock clause IS the step --
    # it no longer repeats `int a = helper()` after it.
    assert text == "Update a by mocking function helper()."


# --- graph helpers ---------------------------------------------------------

def test_immediate_post_dominator_is_the_nearest_join(if_else):
    nodes, succ = _index(if_else)
    pdom = _post_dominators(nodes, succ, {"NE"})
    assert _ipdom("N2", pdom) == "NE"


# --- plain statements read as English (not copied source) -------------------

@pytest.mark.parametrize("stmt,expected", [
    ("int status = 0", "Set status to 0"),
    ("gLastLba = lba", "Set gLastLba to lba"),
    ("gErrCount++", "Increment gErrCount by one"),
    ("--count", "Decrement count by one"),
    ("gErrCount += 2", "Increment gErrCount by 2"),
    ("total -= n", "Decrement total by n"),
    ("mask |= FLAG", "Set mask to mask | FLAG"),
    ("*ppnOut = e.ppn", "Set ppnOut to e.ppn"),
    ("int clipped = utilClip(v, -max, max)",
     "Call function utilClip() with v, -max, max, storing the result in clipped"),
    ("logReset()", "Call function logReset()"),
])
def test_a_statement_reads_as_a_sentence(stmt, expected):
    from views.test_steps import _describe
    assert _describe(stmt) == expected


def test_an_unreadable_statement_falls_back_to_the_flowchart_label():
    """`_describe` returning None is the signal to keep the label, rather than
    invent wording for a shape it does not understand."""
    from views.test_steps import _describe
    assert _describe("for (int i = 0; i < n; ++i)") is None


def test_statements_split_on_top_level_semicolons_only():
    """A `for` header holds two semicolons inside its parentheses; splitting on
    them would hand `_describe` three fragments of one statement."""
    from views.test_steps import _statements
    assert _statements("a = 1; b = 2;") == ["a = 1", "b = 2"]
    assert _statements("for (i = 0; i < n; i++)") == ["for (i = 0; i < n; i++)"]


# --- mocked callees: four shapes --------------------------------------------

def _mock_spec(**sigs):
    return {"name": "fn", "precondition": {
        "parameters": [{"name": "x", "type": "int"}],
        "mocks": [{"name": n, "parameters": p} for n, p in sigs.items()]}}


GROUPED_RAW = """int sum = libAdd(a, b);
int product = libMultiply(sum, c);"""

OUT_SIG = {"FilReadPage": [{"name": "idx", "type": "uint16_t"},
                           {"name": "e", "type": "MapEntry *"}]}


def test_an_assigned_mock_leads_with_the_variable():
    from views.test_steps import _mock_sentence
    assert (_mock_sentence("int sum = libAdd(a, b);", ["libAdd"], {})
            == "Update sum by mocking function libAdd()")


def test_several_assigned_mocks_pair_positionally():
    """Two statements, ONE CFG node. The lists pair by position, so they must
    stay in source order."""
    from views.test_steps import _mock_sentence
    assert (_mock_sentence(GROUPED_RAW, ["libAdd", "libMultiply"], {})
            == "Update sum, product by mocking function libAdd(), libMultiply()")


def test_an_assigned_mock_that_also_writes_through_names_both():
    from views.test_steps import _mock_sentence
    sig = {"Foo": [{"name": "a", "type": "int"}, {"name": "b", "type": "int *"}]}
    assert (_mock_sentence("int r = Foo(a, &b);", ["Foo"], sig)
            == "Update r, b by mocking function Foo()")


def test_a_mock_whose_value_is_the_return():
    from views.test_steps import _mock_sentence
    assert (_mock_sentence("return libAdd(x, y);", ["libAdd"], {}, kind="return")
            == "Expect return value from the return of mock function libAdd() with x, y inputs")


def test_a_mock_whose_value_picks_a_branch():
    from views.test_steps import _mock_sentence
    assert (_mock_sentence("if (FilReadPage(i, &e) != 0)", ["FilReadPage"], OUT_SIG,
                           kind="branch", condition="is not equal to 0")
            == "Derive value to return of mock function FilReadPage() with i, "
               "setting e and check it is not equal to 0")


def test_a_mock_whose_value_is_discarded():
    from views.test_steps import _mock_sentence
    assert (_mock_sentence("FilReadPage(i, &e);", ["FilReadPage"], OUT_SIG)
            == "Mock function FilReadPage() with i, setting e")
    assert (_mock_sentence("HilNotify(ERR_RANGE);", ["HilNotify"], {})
            == "Mock function HilNotify() with ERR_RANGE")


def test_with_is_inputs_and_setting_is_outputs():
    """`&e` is the slot the stub fills, not a value the tester supplies, so it
    must never appear beside `i` after `with`. The side comes from the callee's
    signature, never from the call text."""
    from views.test_steps import _mock_facts
    facts = _mock_facts("FilReadPage(i, &e);", "FilReadPage", OUT_SIG)
    assert facts["inputs"] == ["i"] and facts["outputs"] == ["e"]


def test_a_const_pointer_argument_is_an_input():
    from views.test_steps import _mock_sentence
    sigs = {"Send": [{"name": "buf", "type": "const char *"}]}
    assert (_mock_sentence("Send(msg);", ["Send"], sigs)
            == "Mock function Send() with msg")


def test_nested_call_arguments_do_not_shift_the_out_parameter_position():
    """`Foo(a, Bar(b, c), &out)` has THREE arguments -- splitting on commas would
    read `&out` as the fourth and name the wrong thing."""
    from views.test_steps import _call_args
    assert _call_args("int r = Foo(a, Bar(b, c), &out);", "Foo") == ["a", "Bar(b, c)", "&out"]


def test_a_mixed_node_gives_each_mock_its_own_clause():
    """One assigned, one not: the parallel lists would differ in length and pair
    silently wrong, so they are not used."""
    from views.test_steps import _mock_sentence
    raw = """int sum = libAdd(a, b);
HilNotify(ERR);"""
    assert (_mock_sentence(raw, ["libAdd", "HilNotify"], {})
            == "Update sum by mocking function libAdd(); mock function HilNotify() with ERR")


@pytest.mark.parametrize("cond,expected", [
    ("FilReadPage(i, &e) != 0", "is not equal to 0"),
    ("FilReadPage(i, &e) == 0", "is equal to 0"),
    ("FilReadPage(i, &e) >= LIMIT", "is greater than or equal to LIMIT"),
    ("FilReadPage(i, &e)", "is true"),
])
def test_a_check_mirrors_the_source_operator(cond, expected):
    """Never a friendlier inversion: `!= 0` inverted to "returned zero" would put
    the error path on the True leg and send the tester down the wrong branch."""
    from views.test_steps import _comparison
    assert _comparison(cond, "FilReadPage") == expected


# --- the shapes end to end, through a real walk ------------------------------

def test_a_statement_that_is_only_a_mock_call_is_the_whole_step():
    """Echoing `HilNotify(ERR_RANGE)` would tell the tester to perform the one
    call they never make."""
    cfg = _cfg([("N1", "START", "Start: fn", ""),
                ("N2", "ACTION", "HilNotify(ERR_RANGE)", "HilNotify(ERR_RANGE);"),
                ("N3", "RETURN", "Return 0", ""), ("NE", "END", "End", "")],
               [("N1", "N2", None), ("N2", "N3", None), ("N3", "NE", None)])
    text = _texts(build_steps(cfg, _mock_spec(HilNotify=[]), ["HilNotify()"])[0])["2"]
    assert text == "Mock function HilNotify() with ERR_RANGE."


def test_a_decision_folds_its_check_into_the_mock_clause():
    cfg = _cfg([("N1", "START", "Start: fn", ""),
                ("N2", "DECISION", "Check: read(x) != 0?", "if (read(x) != 0)"),
                ("N3", "RETURN", "Return 0", ""), ("N4", "RETURN", "Return 1", ""),
                ("NE", "END", "End", "")],
               [("N1", "N2", None), ("N2", "N3", "Yes"), ("N2", "N4", "No"),
                ("N3", "NE", None), ("N4", "NE", None)])
    text = _texts(build_steps(cfg, _mock_spec(read=[]), ["read()"])[0])["2"]
    assert text == ("Derive value to return of mock function read() with x "
                    "and check it is not equal to 0.")


def test_a_plain_statement_and_a_mock_keep_source_order():
    cfg = _cfg([("N1", "START", "Start: fn", ""),
                ("N2", "ACTION", "gErrCount++;", "gErrCount++;\nHilNotify(ERR);"),
                ("N3", "RETURN", "Return 0", ""), ("NE", "END", "End", "")],
               [("N1", "N2", None), ("N2", "N3", None), ("N3", "NE", None)])
    text = _texts(build_steps(cfg, _mock_spec(HilNotify=[]), ["HilNotify()"])[0])["2"]
    assert text == "Increment gErrCount by one; mock function HilNotify() with ERR."


def test_step_levels_alternate_numeric_and_alphabetic():
    """`4.a.3.b`, not `4.1.3.2` -- depth is readable at a glance."""
    from views.test_steps import _number
    assert _number([4]) == "4"
    assert _number([4, 1]) == "4.a"
    assert _number([4, 1, 3]) == "4.a.3"
    assert _number([4, 1, 3, 2]) == "4.a.3.b"
    assert _number([1, 27]) == "1.aa"           # past z, spreadsheet-style


def test_missing_cfg_yields_no_steps():
    assert build_steps(None, SPEC) == ([], [], {})
    assert build_steps({}, SPEC) == ([], [], {})
