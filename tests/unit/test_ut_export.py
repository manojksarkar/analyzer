"""utExport view: test_specs.json -> the unit-test automation JSON.

Rules under test come from docs/spec/UT_EXPORT_SPEC.md.
"""
import os
import sys

import pytest

ENGINE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "engine")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from views.ut_export import (  # noqa: E402
    _cases_for, _environment, _iter_specs, _review, _split_qualified, LEVEL_UT,
)


def _spec(**over):
    spec = {
        "testCaseId": "TC_IF_01",
        "name": "f",
        "qualifiedName": "f",
        "precondition": {"mocks": [{"name": "dep", "returnType": "int",
                                    "parameters": [], "declaredIn": "D.h"}],
                         "globals": []},
        "input": {"entries": [{"kind": "parameter", "name": "a", "type": "int"}]},
        "expected": {"returns": [{"step": "2.1", "expression": "0"},
                                 {"step": "2.2", "expression": "a"}]},
    }
    spec.update(over)
    return spec


def _cases(**over):
    return _cases_for(_spec(**over), {}, {"author": "", "reviewer": ""})


# --- one case per path (REQ-UE-04) -----------------------------------------

def test_each_return_becomes_its_own_case():
    """A spec covers every exit in one row because that is what the document
    renders; the export is per test case, so the paths split back out."""
    cases = _cases()
    assert [c["id"] for c in cases] == ["TC_IF_01_01", "TC_IF_01_02"]


def test_each_case_expects_the_return_of_its_own_path():
    cases = _cases()
    assert [(c["expected"]["return"], c["expected"]["atStep"]) for c in cases] == [
        ("0", "2.1"), ("a", "2.2")]


def test_a_spec_with_no_return_still_yields_one_case():
    """A void function has nothing to assert a return against, but skipping it
    would leave the function untested rather than trivially tested."""
    cases = _cases(expected={"returns": []})
    assert len(cases) == 1
    assert cases[0]["expected"]["return"] is None


def test_every_case_id_carries_a_path_suffix():
    """Interface ids already end in `_NN`, so a bare id on a no-return spec is
    indistinguishable from a path index: `TC_IF_LAYER1_CORE_02` could be spec 02
    with one path, or spec CORE path 02. Suffixing uniformly removes the guess."""
    assert _cases(expected={"returns": []})[0]["id"] == "TC_IF_01_01"
    assert [c["id"] for c in _cases()] == ["TC_IF_01_01", "TC_IF_01_02"]


def test_expected_asserts_no_called_mocks():
    """The mock list is the union over every path, so on any one path most of it
    did not run. Asserting it would fail on every path but one."""
    for case in _cases():
        assert "calls" not in case["expected"]


# --- case content ----------------------------------------------------------

def test_every_case_is_a_unit_test():
    assert {c["level"] for c in _cases()} == {LEVEL_UT}


def test_trace_is_present_but_empty():
    """No requirements source exists yet. Emitted empty rather than omitted, so a
    missing field is never read as 'traced, link unknown'."""
    assert all(c["trace"] == "" for c in _cases())


def test_free_function_has_no_class_name():
    assert _split_qualified("coreNestedBranch") == ("", "coreNestedBranch")


def test_member_function_splits_into_class_and_method():
    assert _split_qualified("SignalProcessor::normalize") == (
        "SignalProcessor", "normalize")


def test_stubs_carry_the_signature():
    stub = _cases()[0]["stubs"][0]
    assert stub["returnType"] == "int" and stub["declaredIn"] == "D.h"


def test_inputs_carry_a_range_and_an_unsolved_value():
    """Values need the branch predicates, which are not structural yet — so the
    shape is emitted with the value missing rather than guessed."""
    entry = _cases()[0]["inputs"][0]
    assert entry["value"] is None
    assert entry["range"] == "-0x80000000-0x7FFFFFFF"


def test_global_initial_value_reaches_preconditions():
    spec = _spec(precondition={"mocks": [], "globals": [
        {"name": "gFlag", "type": "int", "value": "7"}]})
    pre = _cases_for(spec, {}, {"author": "", "reviewer": ""})[0]["preconditions"]
    assert pre["globals"] == [{"name": "gFlag", "type": "int", "initialValue": "7"}]


# --- configuration, not derivation (REQ-UE-05) -----------------------------

def test_environment_is_carried_from_config_verbatim():
    cfg = {"views": {"utExport": {"environment": {
        "flags": ["-std=c++14"], "probepoint": ["p"], "usercode": ["init();"]}}}}
    assert _environment(cfg) == {"flags": ["-std=c++14"], "probepoint": ["p"],
                                 "usercode": ["init();"]}


def test_environment_is_empty_when_unconfigured():
    """Nothing here is derivable from source; an absent config means empty, never
    a synthesised value."""
    assert _environment({}) == {"flags": [], "probepoint": [], "usercode": []}


def test_review_comes_from_config():
    cfg = {"views": {"utExport": {"review": {"author": "A", "reviewer": "B"}}}}
    assert _review(cfg) == {"author": "A", "reviewer": "B"}


# --- both spec kinds are unit tests (REQ-UE-01) ----------------------------

def test_dynamic_behaviour_specs_are_exported_too():
    """Both SWE.4 spec kinds are unit-test specifications, so both become cases."""
    test_specs = {
        "unitNames": {"C|U": "U"},
        "C|U": {"name": "U", "functions": [_spec()]},
        "dynamicSpecs": {"C": [_spec(testCaseId="TC_DYN_01")]},
    }
    assert [s["testCaseId"] for s in _iter_specs(test_specs)] == ["TC_IF_01", "TC_DYN_01"]
