"""Every field Phase 1 produces must survive the hand-off to Phase 2.

In database mode the phases talk through the database, not through model/*.json, so a
field the store does not carry is a field Phase 2 never sees. Two bugs of exactly that
shape shipped together and between them wrecked every interface table:

  * `_FN_PAYLOAD_FIELDS` listed `parameters` but Phase 1 emits `params` (parser.py:2072);
    Phase 2 normalises `params` -> `parameters` and pops it (model_deriver.py:449,1180).
    The store dropped the only spelling that existed at hand-off time, so Phase 2 computed
    an empty list and 112 of 140 functions rendered as VOID.
  * `className` and `addressTakenByUnits` have no column and no edge, so the payload was
    their only route through, and they were not listed either.

These are cheap structural checks. The behavioural proof is a round-trip through a real
database in tests/unit/test_model_store.py.
"""

import os
import re
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (_ROOT, os.path.join(_ROOT, "engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _src(rel):
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


@pytest.mark.parametrize("field", ["params", "parameters", "className", "addressTakenByUnits",
                                   "returnExpr", "syntheticFromVarDecl"])
def test_field_is_carried_by_the_store(field):
    """Each of these reaches Phase 2 only through the payload allow-list."""
    from core.model_store import _FN_PAYLOAD_FIELDS
    assert field in _FN_PAYLOAD_FIELDS


def test_both_parameter_spellings_are_carried():
    """`params` is Phase 1's name, `parameters` is Phase 2's. The hand-off needs both:
    keeping only Phase 2's name stores a field that does not exist yet."""
    from core.model_store import _FN_PAYLOAD_FIELDS
    assert {"params", "parameters"} <= set(_FN_PAYLOAD_FIELDS)


def test_the_second_parse_walks_globals_as_well_as_calls():
    """parse_calls_and_globals() promises both walks -- and for a while did only one.

    visit_global_access is the sole producer of readsGlobalIds/writesGlobalIds AND of
    function_return_expr (parser.py:1765, on RETURN_STMT). With the call missing, the
    model had no global access at all: every function's direction came out
    "Out: accesses no globals", the transitive sets were empty, and returnExpr went to
    zero across the board. Nothing failed -- the pipeline reported success.
    """
    src = _src(os.path.join("engine", "parser.py"))
    body = src.split("def parse_calls_and_globals(", 1)[1].split("\ndef ", 1)[0]
    assert "visit_calls(tu.cursor)" in body
    assert "visit_global_access(tu.cursor)" in body


def test_global_access_has_exactly_one_top_level_entry_point():
    """The bug was a dead entry point: the two passes were merged, the old
    parse_global_access() was left behind uncalled, and the merged function forgot the
    walk. A second uncalled entry point is how that hid -- the code looked present."""
    src = _src(os.path.join("engine", "parser.py"))
    # Calls of the form `visit_global_access(tu.cursor)` -- the top-level walk of a
    # translation unit, as opposed to the visitor's own recursion into children.
    tops = re.findall(r"visit_global_access\(tu\.cursor\)", src)
    assert len(tops) == 1, f"expected exactly one top-level global-access walk, found {len(tops)}"
