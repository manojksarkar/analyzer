"""
Call-name labelling rules — deterministic, no LLM.

The flowchart label rule: a label is descriptive prose that names EVERY function
the node calls, each written ``Name()`` with no arguments. The prompt asks the
LLM for that shape; ``enforce_call_names`` guarantees it afterwards, so these
tests cover the guarantee rather than the prompt.
"""

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _p in (_PROJECT_ROOT / "engine" / "flowchart", _PROJECT_ROOT / "engine"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from cpp_tokens import extract_call_names, render_call, short_name  # noqa: E402
from llm.generator import enforce_call_names  # noqa: E402
from models import CfgNode, ControlFlowGraph, NodeType  # noqa: E402

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _node(node_id, raw_code, label, call_names=None,
          node_type=NodeType.ACTION):
    node = CfgNode(
        node_id=node_id,
        node_type=node_type,
        raw_code=raw_code,
        start_line=1,
        end_line=1,
    )
    node.label = label
    if call_names is None:
        call_names = extract_call_names(raw_code)
    if call_names:
        node.enriched_context = {"call_names": call_names}
    return node


def _cfg(*nodes):
    return ControlFlowGraph(
        function_key="src|f|doWork|void",
        qualified_name="doWork",
        source_file="src/f.cpp",
        start_line=1,
        end_line=10,
        nodes={n.node_id: n for n in nodes},
        entry_node_id=nodes[0].node_id if nodes else "",
    )


# ---------------------------------------------------------------------------
# extract_call_names
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code, expected", [
    ("ServerReplicate(part, id);",        ["ServerReplicate"]),
    ("sz = functionJ();",                 ["functionJ"]),
    ("functionX()->timeSlot = False;",    ["functionX"]),
    ("sa = &functionA()->sa;",            ["functionA"]),
    ("doc.AddMember(\"initiator\", id);", ["doc.AddMember"]),
    ("buf->reset();",                     ["buf->reset"]),
    ("v = Ns::helper(x);",                ["Ns::helper"]),
    ("memcpy(dst, src, n);",              ["memcpy"]),
    # Nested calls: both are named, in source order.
    ("a = f(g(x));",                      ["f", "g"]),
    # Two calls in one statement.
    ("ok = Validate(r) && Persist(r);",   ["Validate", "Persist"]),
])
def test_extract_call_names_finds_real_calls(code, expected):
    assert extract_call_names(code) == expected


@pytest.mark.parametrize("code", [
    "if (x > 0)",
    "while (i < n)",
    "switch (op)",
    "return result;",
    "int result = 0;",
    "sizeof(T)",
    "y = static_cast<int>(x);",
    "TRACE_DEBUG(\"Item {} active\", ldu);",
    "ASSERT(ptr != nullptr);",
    "SYS_ASSERT(ok);",
    "assert(ok);",
    "static_assert(sizeof(T) == 4);",
    "n = MAX(a, b);",
])
def test_extract_call_names_skips_non_calls(code):
    assert extract_call_names(code) == []


def test_extract_call_names_dedupes_and_keeps_order():
    code = "doc.AddMember(a); doc.SetObject(); doc.AddMember(b);"
    assert extract_call_names(code) == ["doc.AddMember", "doc.SetObject"]


def test_extract_call_names_excludes_known_types():
    """Constructors are the same shape as calls; only type knowledge separates them."""
    code = "Point p = Point(1, 2); process(p);"
    assert extract_call_names(code) == ["Point", "process"]
    assert extract_call_names(code, exclude={"Point"}) == ["process"]


def test_render_and_short_name():
    assert render_call("ServerReplicate") == "ServerReplicate()"
    assert render_call("doc.AddMember") == "doc.AddMember()"
    assert render_call("already()") == "already()"
    assert short_name("Ops::Replicate") == "Replicate"
    assert short_name("doc.AddMember") == "AddMember"


# ---------------------------------------------------------------------------
# enforce_call_names — appending what the LLM omitted
# ---------------------------------------------------------------------------

def test_missing_names_are_appended():
    node = _node(
        "N1",
        "ok = Validate(r) && Persist(r) && Audit(r);",
        "Validate the request with Validate()",
    )
    cfg = _cfg(node)

    assert enforce_call_names(cfg) == 1
    assert node.label == (
        "Validate the request with Validate()<br/>Calls: Persist(), Audit()"
    )


def test_label_already_naming_every_call_is_untouched():
    label = "Validate the request with Validate(), then store it with Persist()"
    node = _node("N1", "ok = Validate(r) && Persist(r);", label)
    cfg = _cfg(node)

    assert enforce_call_names(cfg) == 0
    assert node.label == label


def test_node_without_calls_is_untouched():
    label = "Set the result to zero"
    node = _node("N1", "int result = 0;", label)
    cfg = _cfg(node)

    assert enforce_call_names(cfg) == 0
    assert node.label == label


def test_short_form_counts_as_present():
    """A qualified call named by its leaf is not re-appended."""
    node = _node(
        "N1",
        "v = Ops::Replicate(x);",
        "Replicate the partition with Replicate()",
        call_names=["Ops::Replicate"],
    )
    cfg = _cfg(node)

    assert enforce_call_names(cfg) == 0
    assert node.label == "Replicate the partition with Replicate()"


def test_start_and_end_nodes_are_skipped():
    start = _node("N0", "", "Start: doWork", call_names=["doWork"],
                  node_type=NodeType.START)
    end = _node("N9", "", "End", call_names=["doWork"], node_type=NodeType.END)
    cfg = _cfg(start, end)

    assert enforce_call_names(cfg) == 0
    assert start.label == "Start: doWork"
    assert end.label == "End"


# ---------------------------------------------------------------------------
# enforce_call_names — normalising to the Name() form
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label, expected", [
    # Bare name gains parens.
    ("Replicate partition state via ServerReplicate",
     "Replicate partition state via ServerReplicate()"),
    # Arguments are stripped.
    ("Replicate partition state with ServerReplicate(part, id)",
     "Replicate partition state with ServerReplicate()"),
    # Empty parens are already correct.
    ("Replicate partition state with ServerReplicate()",
     "Replicate partition state with ServerReplicate()"),
])
def test_mentions_are_normalised_to_empty_parens(label, expected):
    node = _node("N1", "ServerReplicate(part, id);", label)
    cfg = _cfg(node)

    assert enforce_call_names(cfg) == 0
    assert node.label == expected


def test_prose_word_matching_a_call_name_is_not_parenthesised():
    """`Validate the request` is a sentence, not a mention of Validate().

    A bare word that happens to match a call name must be left alone —
    "Validate() the request" would be mangled output.
    """
    node = _node(
        "N1",
        "ok = Validate(r);",
        "Validate the request with Validate()",
    )
    cfg = _cfg(node)

    assert enforce_call_names(cfg) == 0
    assert node.label == "Validate the request with Validate()"


def test_ambiguous_bare_word_is_appended_not_edited():
    """With no parenthesised mention, an ambiguous word does not count as
    naming the call — the name is appended instead of editing the prose."""
    node = _node("N1", "ok = Validate(r);", "Validate the request")
    cfg = _cfg(node)

    assert enforce_call_names(cfg) == 1
    assert node.label == "Validate the request<br/>Calls: Validate()"


def test_unambiguous_bare_identifier_is_parenthesised():
    """An internal capital means it cannot be prose, so it is safe to convert."""
    node = _node(
        "N1",
        "ServerReplicate(part, id);",
        "Replicate partition state via ServerReplicate",
    )
    cfg = _cfg(node)

    assert enforce_call_names(cfg) == 0
    assert node.label == "Replicate partition state via ServerReplicate()"


def test_surrounding_prose_is_not_rewritten():
    node = _node(
        "N1",
        "functionX()->timeSlot = False;",
        "Set the time slot in functionX(part) to False",
    )
    cfg = _cfg(node)

    enforce_call_names(cfg)
    assert node.label == "Set the time slot in functionX() to False"


def test_fallback_raw_code_label_is_normalised():
    """A rule-based fallback carries the call with its arguments; it still ends
    up in the Name() form rather than looking like a different style."""
    node = _node("N1", "result = add(result, a);", "result = add(result, a)")
    cfg = _cfg(node)

    assert enforce_call_names(cfg) == 0
    assert node.label == "result = add()"


def test_decision_node_call_is_enforced():
    node = _node(
        "N1",
        "if (IsLimitExceeded(id))",
        "Is the limit exceeded?",
        node_type=NodeType.DECISION,
    )
    cfg = _cfg(node)

    assert enforce_call_names(cfg) == 1
    assert node.label == "Is the limit exceeded?<br/>Calls: IsLimitExceeded()"


def test_overlong_label_is_not_grown_further():
    long_label = "x" * 395
    node = _node("N1", "doWork(a);", long_label)
    cfg = _cfg(node)

    assert enforce_call_names(cfg) == 0
    assert node.label == long_label
