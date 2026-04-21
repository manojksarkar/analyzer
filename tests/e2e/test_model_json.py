"""Validates model/ JSON files produced by Phase 1+2.

Checks structure and invariants for:
  model/functions.json
  model/globalVariables.json
  model/units.json
  model/modules.json
"""
import json
import os

import pytest

pytestmark = pytest.mark.e2e

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODEL_DIR = os.path.join(PROJECT_ROOT, "model")

SAMPLE_MODULES = {"Core", "Lib", "Util"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def functions(run_pipeline):
    path = os.path.join(MODEL_DIR, "functions.json")
    if not os.path.isfile(path):
        pytest.fail(f"Missing: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def global_variables(run_pipeline):
    path = os.path.join(MODEL_DIR, "globalVariables.json")
    if not os.path.isfile(path):
        pytest.fail(f"Missing: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def units(run_pipeline):
    path = os.path.join(MODEL_DIR, "units.json")
    if not os.path.isfile(path):
        pytest.fail(f"Missing: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def modules(run_pipeline):
    path = os.path.join(MODEL_DIR, "modules.json")
    if not os.path.isfile(path):
        pytest.fail(f"Missing: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def sample_functions(functions):
    return {fid: f for fid, f in functions.items() if fid.split("|")[0] in SAMPLE_MODULES}


# ---------------------------------------------------------------------------
# functions.json
# ---------------------------------------------------------------------------

def test_functions_json_not_empty(functions):
    assert functions, "functions.json is empty"


def test_function_key_format(functions):
    """Keys must be module|unit|qualifiedName|paramTypes."""
    for fid in functions:
        parts = fid.split("|")
        assert len(parts) == 4, f"Function key should have 4 parts: {fid!r}"


def test_function_required_fields(sample_functions):
    required = {"qualifiedName", "location", "returnType", "visibility"}
    for fid, f in sample_functions.items():
        missing = required - set(f.keys())
        assert not missing, f"{fid} missing fields: {missing}"


def test_function_location_has_file_and_line(sample_functions):
    for fid, f in sample_functions.items():
        loc = f.get("location") or {}
        assert loc.get("file"), f"{fid}: location.file is missing"
        assert isinstance(loc.get("line"), int), f"{fid}: location.line should be int"


def test_phase2_enrichment_present(sample_functions):
    """Phase 2 must have set interfaceId and direction on all Sample functions."""
    for fid, f in sample_functions.items():
        assert f.get("interfaceId", "").startswith("IF_"), f"{fid}: bad interfaceId"
        assert f.get("direction") in ("In", "Out"), f"{fid}: invalid direction {f.get('direction')!r}"


def test_interface_ids_unique(sample_functions):
    ids = [f["interfaceId"] for f in sample_functions.values() if f.get("interfaceId")]
    assert len(ids) == len(set(ids)), "Duplicate interfaceIds found in Sample functions"


def test_behaviour_names_set(sample_functions):
    for fid, f in sample_functions.items():
        if (f.get("visibility") or "").lower() == "private":
            continue
        assert (f.get("behaviourInputName") or "").strip(), f"{fid}: behaviourInputName empty"
        assert (f.get("behaviourOutputName") or "").strip(), f"{fid}: behaviourOutputName empty"


# ---------------------------------------------------------------------------
# globalVariables.json
# ---------------------------------------------------------------------------

def test_global_variables_json_not_empty(global_variables):
    assert global_variables, "globalVariables.json is empty"


def test_global_variable_key_format(global_variables):
    """Keys must be module|unit|qualifiedName."""
    for vid in global_variables:
        parts = vid.split("|")
        assert len(parts) == 3, f"Global key should have 3 parts: {vid!r}"


def test_global_variable_required_fields(global_variables):
    required = {"qualifiedName", "location", "type", "visibility"}
    for vid, g in global_variables.items():
        if vid.split("|")[0] not in SAMPLE_MODULES:
            continue
        missing = required - set(g.keys())
        assert not missing, f"{vid} missing fields: {missing}"


# ---------------------------------------------------------------------------
# units.json
# ---------------------------------------------------------------------------

def test_units_json_not_empty(units):
    assert units, "units.json is empty"


def test_sample_units_present(units):
    for expected in ("Core|Core", "Lib|Lib", "Util|Util"):
        assert expected in units, f"Expected unit {expected!r} missing from units.json"


def test_unit_required_fields(units):
    required = {"name", "functionIds", "globalVariableIds", "callerUnits", "calleesUnits"}
    for uk, u in units.items():
        if uk.split("|")[0] not in SAMPLE_MODULES:
            continue
        missing = required - set(u.keys())
        assert not missing, f"Unit {uk!r} missing fields: {missing}"


def test_unit_function_ids_are_strings(units):
    for uk, u in units.items():
        for fid in u.get("functionIds", []):
            assert isinstance(fid, str), f"Unit {uk!r}: functionId {fid!r} is not a string"


def test_core_calls_lib_and_util(units):
    """Core unit must list Lib and Util as callees."""
    core = units.get("Core|Core", {})
    callees = set(core.get("calleesUnits", []))
    assert "Lib|Lib" in callees, "Core|Core should call Lib|Lib"
    assert "Util|Util" in callees, "Core|Core should call Util|Util"


def test_util_has_no_callees(units):
    """Util calls nobody — calleesUnits must be empty."""
    util = units.get("Util|Util", {})
    assert not util.get("calleesUnits"), "Util|Util should have no callees"


# ---------------------------------------------------------------------------
# modules.json
# ---------------------------------------------------------------------------

def test_modules_json_not_empty(modules):
    assert modules, "modules.json is empty"


def test_sample_modules_present(modules):
    for m in SAMPLE_MODULES:
        assert m in modules, f"Module {m!r} missing from modules.json"


def test_module_has_units_list(modules):
    for m, data in modules.items():
        if m not in SAMPLE_MODULES:
            continue
        assert "units" in data, f"Module {m!r} missing 'units' key"
        assert isinstance(data["units"], list), f"Module {m!r}: 'units' should be a list"
        assert data["units"], f"Module {m!r}: 'units' list is empty"
