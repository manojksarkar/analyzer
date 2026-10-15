"""Tests for the flowcharts view (output/<component>/flowcharts/).

The flowchart generator writes one JSON file per unit, in the folder of the unit's component.
For the Sample units Core, Lib and Util:
  output/Layer1.Sample-Core/flowcharts/Core.json
  output/Layer1.Lib/flowcharts/Lib.json
  output/Layer1.Util/flowcharts/Util.json

Each file is a JSON array of { "name", "functionKey", "flowchart": <Graphviz DOT>, "cfg" } items.

These tests check structure and function coverage, not diagram content: the node labels come
from the LLM. The structural contract is that each chart is a non-empty Graphviz digraph.
"""
import json
import os
import sys
import re

import pytest

pytestmark = pytest.mark.e2e

_DOT_HEADER = re.compile(r"^\s*(strict\s+)?digraph\b")


def is_valid_dot(text: str) -> bool:
    """True if text is a Graphviz digraph (flowcharts are DOT since 2026-07-27, not Mermaid)."""
    return bool(_DOT_HEADER.match(text or ""))

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from tests.e2e_paths import COMPONENTS, output_for   # noqa: E402
# One flowcharts directory per component, where a group-scoped run once had one.
FC_DIRS = [_os.path.join(output_for(c), "flowcharts") for c in COMPONENTS]


def _unit_file(unit):
    """`<unit>.json` in whichever component's flowcharts folder holds it, else None."""
    for d in FC_DIRS:
        path = os.path.join(d, f"{unit}.json")
        if os.path.isfile(path):
            return path
    return None

# Skip entire module when flowcharts are disabled in config
_cfg_path = os.path.join(PROJECT_ROOT, "engine", "config", "config.defaults.json")
if os.path.isfile(_cfg_path):
    import json as _json
    # The defaults file is JSONC -- comments and trailing commas. Parse it the
    # way the engine does, not with a strict loader.
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))
    from core.config import _strip_json_comments, _strip_trailing_commas
    with open(_cfg_path, encoding="utf-8") as _f:
        _cfg = _json.loads(_strip_trailing_commas(_strip_json_comments(_f.read())))
    if not _cfg.get("views", {}).get("flowcharts"):
        pytest.skip("flowcharts disabled in config", allow_module_level=True)

UNITS = ["Core", "Lib", "Util"]

# Public functions that must appear in each unit's flowchart
EXPECTED_FUNCTIONS = {
    "Core": {"coreAdd", "coreCompute", "coreLoopSum", "coreCheck", "coreSumPoint",
             "coreSetResult", "coreProcess", "coreOrchestrate", "coreSetMode"},
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
        path = _unit_file(unit)
        if path:
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
    assert any(os.path.isdir(d) for d in FC_DIRS), f"No flowcharts directory in: {FC_DIRS}"


@pytest.mark.parametrize("unit", UNITS)
def test_flowchart_file_exists(run_pipeline, unit):
    assert _unit_file(unit), f"Missing flowchart file: {unit}.json"


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
def test_flowchart_strings_are_dot(fc_data, unit):
    """Every chart is a Graphviz digraph -- what the DOCX renders and the web reader's SVG is drawn from."""
    for entry in fc_data[unit]:
        fc = entry.get("flowchart") or ""
        assert is_valid_dot(fc), (
            f"{unit}.json entry '{entry.get('name')}' has an invalid or empty DOT chart: {fc[:60]!r}"
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
