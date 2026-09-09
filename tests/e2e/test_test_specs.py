"""SWE.4 test-spec view output (output/<group>/test_specs.json).

Covers docs/spec/SWE4_WIKI.md at the output level; the per-rule unit tests live in
tests/unit/test_test_specs_view.py.

The snapshot here is the acceptance test for the DB migration. SWE.4 derivation is
deterministic and LLM-free, so a rerun on unchanged input must be byte-identical —
any field silently dropped on the way through the database shows up as a snapshot
diff. Captured before the model backing changes; see engine/PLAN.md.
"""
import copy

import pytest

pytestmark = pytest.mark.e2e


def _specs(data):
    """Every per-function spec, across units."""
    out = []
    for unit_key, unit in data.items():
        if unit_key in ("unitNames", "dynamicSpecs") or not isinstance(unit, dict):
            continue
        out.extend(unit.get("functions", []))
    return out


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------

def test_units_carrying_specs_are_named(test_specs):
    names = test_specs.get("unitNames", {})
    for key, unit in test_specs.items():
        if key in ("unitNames", "dynamicSpecs") or not isinstance(unit, dict):
            continue
        assert key in names, f"unit {key} has specs but no unitNames entry"


def test_every_spec_has_a_test_case_id(test_specs, function_test_specs_on):
    specs = _specs(test_specs)
    assert specs, "no per-function specs emitted for the Sample group"
    for spec in specs:
        assert spec.get("testCaseId"), f"{spec.get('qualifiedName')} has no testCaseId"


def test_returns_name_a_step_that_exists(test_specs, function_test_specs_on):
    """expected.returns[].step is the path bridge the UT export builds on."""
    for spec in _specs(test_specs):
        returns = (spec.get("expected") or {}).get("returns") or []
        if not returns:
            continue
        numbers = {s.get("number") for s in spec.get("testSteps", [])}
        for r in returns:
            assert r.get("step") in numbers, (
                f"{spec.get('qualifiedName')}: return claims step {r.get('step')!r}, "
                "which is not in testSteps"
            )


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------

def _normalize(data):
    """Path separators are not part of the contract."""
    out = copy.deepcopy(data)
    for key, unit in out.items():
        if key in ("unitNames", "dynamicSpecs") or not isinstance(unit, dict):
            continue
        for spec in unit.get("functions", []):
            loc = spec.get("location", {})
            if "file" in loc:
                loc["file"] = loc["file"].replace("\\", "/")
    dynamic = out.get("dynamicSpecs")
    for spec in (dynamic if isinstance(dynamic, list) else []):
        loc = spec.get("location", {})
        if "file" in loc:
            loc["file"] = loc["file"].replace("\\", "/")
    return out


def test_snapshot(test_specs, assert_snapshot, llm_descriptions_off, llm_summarize_off):
    assert_snapshot(_normalize(test_specs), "Sample/test_specs.json")
