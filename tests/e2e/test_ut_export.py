"""UT export on the real pipeline output: output/<component>/ut_export.json per
component, and ONE project-level output/ut/ folder in the target format.

The per-rule tests live in tests/unit/test_ut_paths.py, test_ut_target.py and
test_ut_export.py; these assert what a real SampleCppProject run produces:
our format per component, one hierarchy for the whole project, target files that
pass tools/check_ut_json.py, the two formats agreeing on their cases, and every
case solved -- with two values checked by hand against the C++ source pinned so a
regression cannot pass as "still solved".
"""
import json
import os
import sys

import pytest

from tests.e2e_paths import COMPONENTS, OUTPUT_DIR, PROJECT_ROOT, output_for

pytestmark = pytest.mark.e2e

_TOOLS = os.path.join(PROJECT_ROOT, "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
import check_ut_json  # noqa: E402

UT_DIR = os.path.join(OUTPUT_DIR, "ut")


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def ut_outputs(run_pipeline):
    """[(component, our ut_export.json)]."""
    out = [(c, _load(os.path.join(output_for(c), "ut_export.json")))
           for c in COMPONENTS if os.path.isfile(os.path.join(output_for(c), "ut_export.json"))]
    if not out:
        raise AssertionError("no ut_export.json under any component output")
    return out


@pytest.fixture(scope="session")
def target(run_pipeline):
    """{file name: payload} for the project-level output/ut/ folder."""
    if not os.path.isdir(UT_DIR):
        raise AssertionError(f"no target-format folder at {UT_DIR}")
    return {n: _load(os.path.join(UT_DIR, n)) for n in sorted(os.listdir(UT_DIR))}


def _cases(ut_outputs):
    return [c for _, ours in ut_outputs for c in ours["cases"]]


def test_one_hierarchy_lists_every_component(ut_outputs, target):
    assert "hierarchy.json" in target
    for comp in COMPONENTS:
        assert not os.path.isdir(os.path.join(output_for(comp), "ut")), comp
    envs = sorted(env for lay in target["hierarchy.json"]["LayerMapping"].values()
                  for sec in lay["Sections"].values() for env in sec["TestEnvironments"])
    units = {uk for comp, _ in ut_outputs
             for uk, unit in _load(os.path.join(output_for(comp), "test_specs.json")).items()
             if isinstance(unit, dict) and unit.get("functions")}
    assert len(envs) == len(units) >= len(COMPONENTS)
    # Each environment's test-case file is beside the hierarchy, and nothing else is.
    assert sorted(f"{e}.json" for e in envs) == sorted(n for n in target if n != "hierarchy.json")


def test_every_target_file_matches_its_template(target):
    for name, payload in target.items():
        kind = check_ut_json.pick_template(payload)
        found = check_ut_json.run(
            payload, check_ut_json.load(check_ut_json.template_path(kind)))
        assert found.count("ERROR") == 0 and found.count("WARN") == 0, (
            check_ut_json.render(found, name, kind))


def test_the_two_formats_carry_the_same_cases(ut_outputs, target):
    target_ids = sorted(c["id"] for n, p in target.items() if n != "hierarchy.json"
                        for c in p["cases"])
    assert target_ids == sorted(c["id"] for c in _cases(ut_outputs))


def test_every_case_has_a_verdict_and_none_is_unsolved(ut_outputs):
    cases = _cases(ut_outputs)
    assert cases and all("solve" in c for c in cases)
    assert not [c["id"] for c in cases if c["solve"]["status"] == "unsolved"]


def _case(ut_outputs, function, step):
    for c in _cases(ut_outputs):
        if c["target"]["FunctionName"] == function and c["expected"].get("atStep") == step:
            return c
    raise AssertionError(f"no case for {function} at step {step}")


def test_a_return_through_two_nested_helpers_is_computed(ut_outputs):
    """coreEarlyReturn(10001): x > 10000 -> coreValidate(10000) -> v > 100 ->
    coreTransform(100) -> 100 * 2 + 1 = 201. Both helpers run for real, so the
    value only exists because they were executed."""
    c = _case(ut_outputs, "coreEarlyReturn", "2.b.1.b.1.a")
    assert {i["name"]: i["value"] for i in c["inputs"]} == {"x": "10001"}
    assert c["expected"]["value"] == "201"


def test_nested_branches_get_one_input_set_per_path(ut_outputs):
    got = {c["expected"]["atStep"]: {i["name"]: i["value"] for i in c["inputs"]
                                     if i["kind"] == "parameter"}
           for c in _cases(ut_outputs) if c["target"]["FunctionName"] == "coreNestedBranch"}
    assert got == {"2.a.1.a": {"a": "1", "b": "1"}, "2.a.1.b": {"a": "1", "b": "0"},
                   "2.b.1.a": {"a": "0", "b": "1"}, "2.b.1.b": {"a": "0", "b": "0"}}
