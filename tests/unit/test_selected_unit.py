"""`--selected-unit`: narrow the expensive per-function view work to one unit.

A development aid. Two properties matter: the flag reaches Phase 3, and leaving
it off changes nothing.
"""
import os
import sys

import pytest

ENGINE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "engine")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from core.group_planner import plan_runs  # noqa: E402
from utils import KEY_SEP  # noqa: E402

CFG = {"layers": {"L1": {"groups": {"G": {"CompA": {}}}}}}


def _views_args(plans):
    for pl in plans:
        for ph in pl.phases:
            if ph.script == "run_views.py":
                return [str(a) for a in ph.args]
    raise AssertionError("no views phase planned")


def _plan(**kw):
    base = dict(project_path="proj", selected_group=None, use_model=True,
                no_llm_summarize=True, filter_mode=None)
    base.update(kw)
    return plan_runs(CFG, **base)


# --- plumbing --------------------------------------------------------------

def test_unit_is_forwarded_to_phase_3():
    assert "--selected-unit" in _views_args(_plan(selected_units=["Core"]))


def test_each_unit_is_forwarded_separately():
    args = _views_args(_plan(selected_units=["Core", "Lib"]))
    pairs = [(args[i], args[i + 1]) for i in range(len(args) - 1)
             if args[i] == "--selected-unit"]
    assert pairs == [("--selected-unit", "Core"), ("--selected-unit", "Lib")]


@pytest.mark.parametrize("units", [None, []])
def test_omitting_the_flag_plans_exactly_as_before(units):
    """The regression that matters: an ordinary run must be untouched."""
    before = _views_args(_plan())
    after = _views_args(_plan(selected_units=units))
    assert before == after
    assert "--selected-unit" not in after


def test_the_flag_does_not_disturb_the_export_phase():
    plans = _plan(selected_units=["Core"])
    exports = [ph for pl in plans for ph in pl.phases if ph.script != "run_views.py"]
    assert all("--selected-unit" not in [str(a) for a in ph.args] for ph in exports)


# --- the scope predicate ---------------------------------------------------

def _in_scope(fid, comps, units):
    """Mirror of the filter in views/flowcharts.py, kept here so the selection
    rule itself is covered without spawning the flowchart subprocess."""
    if not isinstance(fid, str) or KEY_SEP not in fid:
        return False
    parts = fid.split(KEY_SEP)
    if comps and parts[0].lower() not in comps:
        return False
    if units:
        unit = parts[1].lower() if len(parts) > 1 else ""
        if unit not in units:
            return False
    return True


FIDS = ["CompA|Core|fnOne|int", "CompA|Core|fnTwo|", "CompA|Lib|fnThree|int",
        "CompB|Util|fnFour|", "malformed"]


def test_no_units_keeps_everything_in_the_components():
    kept = [f for f in FIDS if _in_scope(f, ["compa"], [])]
    assert kept == FIDS[:3]


def test_one_unit_keeps_only_that_unit():
    kept = [f for f in FIDS if _in_scope(f, ["compa"], ["core"])]
    assert kept == ["CompA|Core|fnOne|int", "CompA|Core|fnTwo|"]


def test_units_are_matched_case_insensitively():
    assert _in_scope("CompA|Core|fn|int", ["compa"], ["core"])


def test_unit_narrowing_works_without_a_component_filter():
    kept = [f for f in FIDS if _in_scope(f, [], ["util"])]
    assert kept == ["CompB|Util|fnFour|"]


def test_malformed_keys_are_dropped_not_crashed():
    assert not _in_scope("malformed", [], ["core"])
    assert not _in_scope(None, [], ["core"])
