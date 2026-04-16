"""Tests for the flowcharts view (output/flowcharts/).

The flowchart generator writes one JSON file per unit (named by unit name only).
For the Sample group (Core, Lib, Util units), it produces:
  output/flowcharts/Core.json
  output/flowcharts/Lib.json
  output/flowcharts/Util.json

Each file is a JSON array of { "name": <funcName>, "flowchart": <mermaid> } items.
The view passes only functions within the selected group, so only Sample functions appear.

These tests are intentionally generator-agnostic: they check structure and function
coverage, not diagram content. Real LLM output is non-deterministic; the only
structural contract is that the content is a non-empty, valid Mermaid diagram.
"""
import json
import os
import re

import pytest

pytestmark = pytest.mark.e2e

# Valid Mermaid diagram opening keywords (LLM may produce any of these)
_MERMAID_HEADERS = re.compile(
    r"^(%%\{|flowchart|graph|sequenceDiagram|classDiagram|stateDiagram|erDiagram|gantt|pie|gitGraph)",
    re.MULTILINE,
)


def _strip_fences(text: str) -> str:
    """Strip ```mermaid ... ``` or ``` ... ``` code fences if present."""
    text = text.strip()
    m = re.match(r"^```(?:mermaid)?\s*\n?(.*?)```\s*$", text, re.DOTALL)
    return m.group(1).strip() if m else text


def is_valid_mermaid(text: str) -> bool:
    """True if text (after stripping code fences) starts with a Mermaid keyword."""
    return bool(_MERMAID_HEADERS.search(_strip_fences(text)))

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FC_DIR = os.path.join(PROJECT_ROOT, "output", "flowcharts")

UNITS = ["Core", "Lib", "Util"]

# Public functions that must appear in each unit's flowchart
EXPECTED_FUNCTIONS = {
    "Core": {"coreAdd", "coreCompute", "coreLoopSum", "coreCheck", "coreSumPoint",
             "coreSetResult", "coreProcess", "coreOrchestrate", "coreSetMode", "coreGetCount"},
    "Lib":  {"libAdd", "libNormalize"},
    "Util": {"utilCompute", "utilScale"},
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def fc_data(run_pipeline):
    """Dict of unit name → parsed JSON array."""
    result = {}
    missing = []
    for unit in UNITS:
        path = os.path.join(FC_DIR, f"{unit}.json")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                result[unit] = json.load(f)
        else:
            missing.append(f"{unit}.json")
    if missing:
        pytest.fail(f"Missing flowchart file(s): {missing}")
    return result


# ---------------------------------------------------------------------------
# File presence
# ---------------------------------------------------------------------------

def test_flowcharts_dir_exists(run_pipeline):
    assert os.path.isdir(FC_DIR), f"Missing directory: {FC_DIR}"


@pytest.mark.parametrize("unit", UNITS)
def test_flowchart_file_exists(run_pipeline, unit):
    path = os.path.join(FC_DIR, f"{unit}.json")
    assert os.path.isfile(path), f"Missing flowchart file: {unit}.json"


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("unit", UNITS)
def test_flowchart_file_is_list(fc_data, unit):
    assert isinstance(fc_data[unit], list), f"{unit}.json should be a JSON array"


@pytest.mark.parametrize("unit", UNITS)
def test_flowchart_file_not_empty(fc_data, unit):
    assert fc_data[unit], f"{unit}.json is empty"


@pytest.mark.parametrize("unit", UNITS)
def test_entries_have_name_and_flowchart(fc_data, unit):
    for entry in fc_data[unit]:
        assert "name" in entry, f"{unit}.json entry missing 'name': {entry}"
        assert "flowchart" in entry, f"{unit}.json entry missing 'flowchart': {entry}"


@pytest.mark.parametrize("unit", UNITS)
def test_flowchart_strings_are_valid_mermaid(fc_data, unit):
    """Diagram content must be a valid Mermaid diagram regardless of diagram type.
    Code fences (```mermaid ... ```) are accepted — the generator or post-processing
    is expected to strip them, but we validate the inner content here.
    """
    for entry in fc_data[unit]:
        fc = entry.get("flowchart") or ""
        assert is_valid_mermaid(fc), (
            f"{unit}.json entry '{entry.get('name')}' has invalid or empty Mermaid diagram: {fc[:60]!r}"
        )


@pytest.mark.parametrize("unit", UNITS)
def test_function_names_are_nonempty(fc_data, unit):
    for entry in fc_data[unit]:
        assert (entry.get("name") or "").strip(), (
            f"{unit}.json has entry with blank name: {entry}"
        )


# ---------------------------------------------------------------------------
# Expected functions present
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("unit", UNITS)
def test_expected_functions_present(fc_data, unit):
    names = {e["name"] for e in fc_data[unit]}
    missing = EXPECTED_FUNCTIONS[unit] - names
    assert not missing, f"{unit}.json missing expected functions: {missing}"
