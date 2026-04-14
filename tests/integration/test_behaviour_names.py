"""Tests for static behaviour name enrichment (LLM off).

model_deriver._enrich_behaviour_names() always runs — it produces
behaviourInputName and behaviourOutputName from static heuristics:

  Input priority:  param name → first written global → first read global
                   → fallback "<FuncName> input"
  Output priority: returnExpr first token → non-primitive returnType last word
                   → first written global → first read global
                   → fallback "<FuncName> result"

LLM improvement is skipped in tests because config.llm.descriptions
and config.llm.behaviourNames are both false by default.

These tests check:
  1. Every public function has non-empty behaviour names after Phase 2
  2. The description field is always a string (empty when LLM off)
  3. Specific functions with known derivation produce expected values
  4. The returnExpr heuristic fires for functions with a return expression
  5. The global-read heuristic fires for getter functions
"""
import json
import os

import pytest

pytestmark = pytest.mark.integration

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODEL_DIR = os.path.join(PROJECT_ROOT, "model")
FUNCTIONS_JSON = os.path.join(MODEL_DIR, "functions.json")

# Modules belonging to the Sample group
SAMPLE_MODULES = {"Core", "Lib", "Util"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def functions(run_pipeline):
    if not os.path.isfile(FUNCTIONS_JSON):
        pytest.fail(f"Missing: {FUNCTIONS_JSON}")
    with open(FUNCTIONS_JSON, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def sample_public_functions(functions):
    """All non-private functions from the Sample group modules."""
    result = {}
    for fid, f in functions.items():
        parts = fid.split("|")
        if len(parts) < 2:
            continue
        module = parts[0]
        if module not in SAMPLE_MODULES:
            continue
        if (f.get("visibility") or "").lower() == "private":
            continue
        result[fid] = f
    return result


def _find(sample_public_functions, func_name):
    """Return the first function dict whose base name matches func_name."""
    return next(
        (f for fid, f in sample_public_functions.items()
         if fid.split("|")[2].split("::")[-1] == func_name),
        None,
    )


# ---------------------------------------------------------------------------
# Phase 2 ran: fields must be present and non-empty
# ---------------------------------------------------------------------------

def test_functions_json_has_phase2_fields(sample_public_functions):
    """Verify that Phase 2 ran: at least some functions have behaviourInputName set."""
    with_names = [
        fid for fid, f in sample_public_functions.items()
        if (f.get("behaviourInputName") or "").strip()
    ]
    assert with_names, (
        "No Sample function has behaviourInputName set — Phase 2 may not have run. "
        "Run the full pipeline without --skip-pipeline."
    )


def test_all_public_functions_have_behaviour_input_name(sample_public_functions):
    missing = [
        fid for fid, f in sample_public_functions.items()
        if not (f.get("behaviourInputName") or "").strip()
    ]
    assert not missing, (
        f"{len(missing)} public function(s) missing behaviourInputName: {missing[:5]}"
    )


def test_all_public_functions_have_behaviour_output_name(sample_public_functions):
    missing = [
        fid for fid, f in sample_public_functions.items()
        if not (f.get("behaviourOutputName") or "").strip()
    ]
    assert not missing, (
        f"{len(missing)} public function(s) missing behaviourOutputName: {missing[:5]}"
    )


def test_behaviour_names_are_strings(sample_public_functions):
    for fid, f in sample_public_functions.items():
        assert isinstance(f.get("behaviourInputName", ""), str), (
            f"{fid}: behaviourInputName is not a string"
        )
        assert isinstance(f.get("behaviourOutputName", ""), str), (
            f"{fid}: behaviourOutputName is not a string"
        )


def test_description_field_is_string_when_llm_off(sample_public_functions):
    """With LLM off, description is absent or an empty string — never a non-string."""
    for fid, f in sample_public_functions.items():
        if "description" in f:
            assert isinstance(f["description"], str), (
                f"{fid}: description is not a string: {f['description']!r}"
            )


# ---------------------------------------------------------------------------
# Static derivation: known expected values
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("func_name,field,expected_substr", [
    # coreGetCount(): no params, reads g_count →
    #   Input:  _readable_label("g_count") = "Count" (strips g_ prefix)
    #   Output: returnExpr="g_count" → first token → "Count"
    ("coreGetCount",  "behaviourInputName",  "Count"),
    ("coreGetCount",  "behaviourOutputName", "Count"),

    # coreLoopSum(int n): param "n" is 1 char → skipped; no globals
    #   Output: returnExpr="sum" → first token → "Sum"
    ("coreLoopSum",   "behaviourOutputName", "Sum"),

    # coreOrchestrate: returnExpr = "sum + norm + comp + scale"
    #   operators stripped → first token "sum" → "Sum"
    ("coreOrchestrate", "behaviourOutputName", "Sum"),
])
def test_static_behaviour_name_derivation(sample_public_functions, func_name, field, expected_substr):
    match = _find(sample_public_functions, func_name)
    assert match is not None, f"Function '{func_name}' not found in Sample public functions"
    value = match.get(field, "")
    assert expected_substr.lower() in value.lower(), (
        f"'{func_name}'.{field} = {value!r}, expected to contain {expected_substr!r}"
    )


# ---------------------------------------------------------------------------
# Heuristic coverage: returnExpr path fires for known functions
# ---------------------------------------------------------------------------

def test_return_expr_heuristic_produces_non_generic_output(sample_public_functions):
    """Functions whose returnExpr starts with a word should get a non-generic output name.
    coreLoopSum (returnExpr='sum') and coreOrchestrate (returnExpr='sum+...') are
    known to trigger this path — their outputs should NOT end with ' result'.
    """
    candidates = ("coreLoopSum", "coreOrchestrate")
    for name in candidates:
        f = _find(sample_public_functions, name)
        if f is None:
            continue
        out = (f.get("behaviourOutputName") or "").strip()
        assert not out.endswith(" result"), (
            f"'{name}' has returnExpr but behaviourOutputName = {out!r} (generic fallback). "
            "The returnExpr heuristic may be broken."
        )


# ---------------------------------------------------------------------------
# Heuristic coverage: global-read path fires for getter functions
# ---------------------------------------------------------------------------

def test_global_read_heuristic_for_getter_function(sample_public_functions):
    """coreGetCount() has no params and reads g_count.
    Its input name should come from the global name ('Count'), not the generic fallback.
    """
    f = _find(sample_public_functions, "coreGetCount")
    if f is None:
        pytest.skip("coreGetCount not found in Sample public functions")
    inp = (f.get("behaviourInputName") or "").strip()
    assert not inp.endswith(" input"), (
        f"coreGetCount.behaviourInputName = {inp!r}: expected global-derived name, got generic fallback. "
        "The global-read heuristic may be broken."
    )
