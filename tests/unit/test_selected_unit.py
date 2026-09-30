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


def test_out_of_scope_is_not_reported_as_unknown(capsys):
    """`--unit Dispatch --scope "component:Lib"` is the combination that reads wrong.

    Dispatch is not unknown -- it is in Other. Calling it unknown sends the caller
    looking for a typo in a name they can see in their own source, when the fix is
    in --scope. The two failures need different fixes, so they need different words.
    """
    with pytest.raises(SystemExit):
        run_views._resolve_units(MODEL, ["Dispatch"], IN_GROUP)
    out = capsys.readouterr().out
    assert "unknown" not in out.lower()
    assert "not in this run's scope" in out
    assert "It is in Other" in out
    assert '--scope "component:Other"' in out


def test_a_real_typo_still_reads_as_a_typo(capsys):
    """The other half: narrowing the out-of-scope wording must not swallow this one."""
    with pytest.raises(SystemExit):
        run_views._resolve_units(MODEL, ["Dispatc"], IN_GROUP)
    out = capsys.readouterr().out
    assert "unknown --selected-unit" in out


def test_unit_home_finds_every_component_a_name_lives_in():
    model = {UNITS: {"A|Shared": {}, "B|Shared": {}, "C|Solo": {}}}
    assert run_views._unit_home(model, "Shared") == ["A", "B"]
    assert run_views._unit_home(model, "shared") == ["A", "B"]
    assert run_views._unit_home(model, "Nope") == []


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



# --- when run.py may check the unit, before any phase runs ----------------

from core.group_planner import unit_check_can_run_early  # noqa: E402


class TestWhenTheEarlyCheckMayRun:
    """`--selected-unit` is consumed by Phase 3 alone, so run.py may validate it at startup only
    when the units it would read ARE the units Phase 3 will use.

    `generate` starts run.py twice -- Phase 1 alone, then Phases 2-4 -- passing the flag to both.
    The check used to run whenever a units model existed, so on a version left with units by an
    earlier attempt, the Phase-1 process exited with "Units in scope: (none)" before parsing
    anything: blaming the unit name for a model that was about to be replaced. Reproduced on a
    real run, same message, same traceback lines as the report.
    """

    # (from_phase, to_phase, use_model)  ->  may check early?
    CASES = [
        ((1, 1, False), False, "generate, process A: Phase 1 only -- Phase 3 never runs here"),
        ((2, None, False), False, "generate, process B: Phase 2 rebuilds the units first"),
        ((1, None, False), False, "a plain full run: Phases 1-2 rebuild the model"),
        ((1, 2, False), False, "parse + derive only: Phase 3 never runs"),
        ((3, None, False), True, "reexport --from-phase 3: the stored model is final"),
        ((3, None, True), True, "reexport --from-phase 3 with --use-model"),
        ((1, None, True), True, "--use-model: Phases 1-2 are skipped, the model is final"),
        ((4, None, True), False, "export only: Phase 3 does not run, the flag is unused"),
        ((3, 3, False), True, "exactly Phase 3"),
        ((3, 2, False), False, "an empty range: nothing runs"),
    ]

    @pytest.mark.parametrize("args,expected,why", CASES, ids=[c[2] for c in CASES])
    def test_the_decision(self, args, expected, why):
        assert unit_check_can_run_early(*args) is expected, why

    def test_it_is_never_true_when_the_model_is_about_to_be_rebuilt(self):
        """THE BUG, stated as a property rather than as one case."""
        for from_phase in (1, 2):
            for to_phase in (None, 1, 2, 3, 4):
                assert not unit_check_can_run_early(from_phase, to_phase, use_model=False)

    def test_it_is_never_true_when_phase_3_does_not_run(self):
        """The flag is consumed by Phase 3 alone; a process without Phase 3 has nothing to check."""
        for to_phase in (1, 2):
            for use_model in (False, True):
                assert not unit_check_can_run_early(1, to_phase, use_model)
        assert not unit_check_can_run_early(4, None, True)


class TestRunPyUsesTheDecision:
    """run.py cannot be imported in a test -- it runs on import -- so its wiring is read."""

    SRC = open(os.path.join(os.path.dirname(ENGINE), "engine", "run.py"), encoding="utf-8").read()

    def test_the_startup_check_is_gated(self):
        import re
        assert re.search(r"^if selected_units_arg and not _unit_check_early\(from_phase, "
                         r"to_phase, use_model\):", self.SRC, re.M), (
            "run.py validates --selected-unit at startup without asking whether the stored "
            "units are the ones Phase 3 will use")

    def test_the_matcher_cannot_match_a_definition(self):
        """A wiring test whose matcher also matches a `def` line passes however the code
        behaves -- a mistake made twice already on this branch."""
        import re
        pat = re.compile(r"^if selected_units_arg and not _unit_check_early\(", re.M)
        assert not pat.search("def unit_check_can_run_early(from_phase, to_phase, use_model):")

    def test_the_gate_comes_before_the_stored_units_are_read(self):
        """Gating AFTER the read would still check against the leftover model."""
        gate = self.SRC.index("if selected_units_arg and not _unit_check_early(")
        read = self.SRC.index("_units_data = _rmf(UNITS")
        assert gate < read

    def test_run_views_is_not_imported_at_the_top_of_run_py(self):
        """run_views rewrites sys.argv and snapshots paths on import. It is imported only in the
        branch that resolves units against a stored model, as it always was."""
        import re
        assert not re.search(r"^import run_views", self.SRC, re.M)

    def test_a_run_without_the_flag_says_nothing_about_it(self):
        """The old `else` was paired with `if selected_units_arg:`, so every run WITHOUT the
        flag announced "--selected-unit will be validated in Phase 3"."""
        import re
        block = self.SRC[self.SRC.index("from core.group_planner import unit_check_can_run_early"):
                         self.SRC.index("plans = plan_runs(")]
        assert not re.search(r"^else:", block, re.M), (
            "a top-level else after the --selected-unit block logs on runs that have no flag")
