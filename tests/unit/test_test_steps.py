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
    steps, returns = build_steps(cfg, SPEC)
    assert _numbers(steps) == ["1", "2", "3"]
    assert _texts(steps)["1"] == "Issue function fn with inputs x."
    assert [r["step"] for r in returns] == ["3"]


def test_entry_step_says_void_when_there_are_no_parameters():
    cfg = _cfg([("N1", "START", "Start: fn", ""), ("NE", "END", "End", "")],
               [("N1", "NE", None)])
    steps, _ = build_steps(cfg, {"name": "fn", "precondition": {"parameters": []}})
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
    steps, _ = build_steps(if_else, SPEC)
    t = _texts(steps)
    assert t["2"] == "Check whether x < 0."
    assert t["2.1"].startswith("True:")
    assert t["2.2"].startswith("False:")


def test_single_step_leg_is_inlined_after_the_label(if_else):
    t = _texts(build_steps(if_else, SPEC)[0])
    assert t["2.1"] == "True: Return -1."


def test_every_return_gets_an_entry_naming_its_step(if_else):
    _, returns = build_steps(if_else, SPEC)
    assert {r["step"] for r in returns} == {"2.1", "2.2"}
    assert {r["text"] for r in returns} == {"Successfully returned -1",
                                            "Successfully returned 1"}


def test_nested_decision_nests_deeper():
    cfg = _cfg([("N1", "START", "Start: fn", ""), ("N2", "DECISION", "Check: x < 0?", ""),
                ("N3", "RETURN", "Return -1", ""), ("N4", "DECISION", "Check: x == 0?", ""),
                ("N5", "RETURN", "Return 0", ""), ("N6", "RETURN", "Return 1", ""),
                ("NE", "END", "End", "")],
               [("N1", "N2", None), ("N2", "N3", "Yes"), ("N2", "N4", "No"),
                ("N4", "N5", "Yes"), ("N4", "N6", "No"),
                ("N3", "NE", None), ("N5", "NE", None), ("N6", "NE", None)])
    steps, returns = build_steps(cfg, SPEC)
    nums = _numbers(steps)
    assert "2.2.1" in nums and "2.2.1.1" in nums and "2.2.1.2" in nums
    assert {r["step"] for r in returns} == {"2.1", "2.2.1.1", "2.2.1.2"}


# --- loop ------------------------------------------------------------------

def test_loop_body_nests_and_continuation_does_not():
    cfg = _cfg([("N1", "START", "Start: fn", ""), ("N2", "LOOP_HEAD", "Loop: i < n?", ""),
                ("N3", "ACTION", "sum += i", ""), ("N4", "RETURN", "Return sum", ""),
                ("NE", "END", "End", "")],
               [("N1", "N2", None), ("N2", "N3", "Yes"), ("N3", "N2", None),
                ("N2", "N4", "No"), ("N4", "NE", None)])
    steps, _ = build_steps(cfg, SPEC)
    t = _texts(steps)
    assert t["2"].startswith("Repeat ")
    assert "2.1" in t                      # body nests
    assert t["3"] == "Return sum."         # continuation resumes at top level


def test_back_edge_does_not_loop_forever():
    cfg = _cfg([("N1", "START", "Start: fn", ""), ("N2", "LOOP_HEAD", "Loop: forever?", ""),
                ("N3", "ACTION", "tick()", ""), ("N4", "RETURN", "Return 0", ""),
                ("NE", "END", "End", "")],
               [("N1", "N2", None), ("N2", "N3", "Yes"), ("N3", "N2", None),
                ("N2", "N4", "No"), ("N4", "NE", None)])
    steps, _ = build_steps(cfg, SPEC)
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
    assert t["2.1"].startswith("case 1:") and t["2.2"].startswith("default:")


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
    assert text.startswith("Expect mock function helper;")


# --- graph helpers ---------------------------------------------------------

def test_immediate_post_dominator_is_the_nearest_join(if_else):
    nodes, succ = _index(if_else)
    pdom = _post_dominators(nodes, succ, {"NE"})
    assert _ipdom("N2", pdom) == "NE"


def test_missing_cfg_yields_no_steps():
    assert build_steps(None, SPEC) == ([], [])
    assert build_steps({}, SPEC) == ([], [])
