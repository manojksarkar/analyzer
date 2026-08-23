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


# --- validation ------------------------------------------------------------
#
# A mistyped unit filters the function set to nothing, so the run would report
# success having generated no flowcharts. It has to be a hard error.

import run_views  # noqa: E402
from core.model_io import UNITS  # noqa: E402

MODEL = {UNITS: {"Sample-Core|Core": {}, "Lib|Lib": {}, "Util|Util": {},
                 "Other|Dispatch": {}}}
IN_GROUP = ["Sample-Core", "Lib", "Util"]


def test_known_unit_resolves():
    assert run_views._resolve_units(MODEL, ["Core"], IN_GROUP) == ["Core"]


def test_unit_name_is_case_insensitive_and_normalised():
    assert run_views._resolve_units(MODEL, ["core"], IN_GROUP) == ["Core"]
    assert run_views._resolve_units(MODEL, ["CORE"], IN_GROUP) == ["Core"]


def test_unknown_unit_exits_rather_than_running_empty():
    with pytest.raises(SystemExit) as e:
        run_views._resolve_units(MODEL, ["Bogus"], IN_GROUP)
    assert e.value.code == 1


def test_a_unit_outside_the_component_scope_is_rejected():
    """`Dispatch` exists in the model but not in this run's components, so it
    would contribute no functions — the filter requires both to match."""
    with pytest.raises(SystemExit):
        run_views._resolve_units(MODEL, ["Dispatch"], IN_GROUP)


def test_the_listing_names_only_units_the_run_visits(capsys):
    with pytest.raises(SystemExit):
        run_views._resolve_units(MODEL, ["Bogus"], IN_GROUP)
    out = capsys.readouterr().out
    assert "Core, Lib, Util" in out
    assert "Dispatch" not in out


def test_a_near_miss_gets_a_suggestion(capsys):
    with pytest.raises(SystemExit):
        run_views._resolve_units(MODEL, ["cor"], IN_GROUP)
    assert "Did you mean 'Core'?" in capsys.readouterr().out


def test_one_bad_name_fails_the_whole_run(capsys):
    with pytest.raises(SystemExit):
        run_views._resolve_units(MODEL, ["Core", "Bogus"], IN_GROUP)
