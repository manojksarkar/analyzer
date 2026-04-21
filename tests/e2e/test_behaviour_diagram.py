"""Tests for the behaviourDiagram view (output/behaviour_diagrams/).

These tests are intentionally generator-agnostic: they check structure, caller
filtering, and file naming — not diagram content. Real LLM output is
non-deterministic; only structural Mermaid validity is asserted.

"External caller" means a caller from OUTSIDE the selected group (Sample).
The Sample group contains Core, Lib, Util — calls among them are internal.

External callers in the SampleCppProject:
  App/Main   → Core  (runSampleTests calls coreAdd, coreSetResult, etc.)
  Cross/Hub  → Core  (hubCompute calls coreAdd)

Expected docxRows:
  - Core has rows (called by App/Main and Cross/Hub, both outside Sample)
  - Lib  has NO rows (only called by Core, which is internal to Sample)
  - Util has NO rows (only called by Core/Lib, both internal to Sample)
"""
import json
import os
import re

import pytest

pytestmark = pytest.mark.e2e

_MERMAID_HEADERS = re.compile(
    r"^(%%\{|flowchart|graph|sequenceDiagram|classDiagram|stateDiagram|erDiagram|gantt|pie|gitGraph)",
    re.MULTILINE,
)


def _strip_fences(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:mermaid)?\s*\n?(.*?)```\s*$", text, re.DOTALL)
    return m.group(1).strip() if m else text


def is_valid_mermaid(text: str) -> bool:
    return bool(_MERMAID_HEADERS.search(_strip_fences(text)))

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BD_DIR = os.path.join(PROJECT_ROOT, "output", "behaviour_diagrams")
BD_JSON = os.path.join(BD_DIR, "_behaviour_pngs.json")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def bd_json(run_pipeline):
    if not os.path.isfile(BD_JSON):
        pytest.fail(f"Missing: {BD_JSON}")
    with open(BD_JSON, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def docx_rows(bd_json):
    return bd_json.get("_docxRows", {})


@pytest.fixture(scope="module")
def mmd_filenames(run_pipeline):
    if not os.path.isdir(BD_DIR):
        pytest.fail(f"Missing directory: {BD_DIR}")
    return [f for f in os.listdir(BD_DIR) if f.endswith(".mmd")]


# ---------------------------------------------------------------------------
# File presence
# ---------------------------------------------------------------------------

def test_behaviour_diagrams_dir_exists(run_pipeline):
    assert os.path.isdir(BD_DIR), f"Missing directory: {BD_DIR}"


def test_behaviour_pngs_json_exists(run_pipeline):
    assert os.path.isfile(BD_JSON), f"Missing: {BD_JSON}"


def test_mmd_files_exist(mmd_filenames):
    assert mmd_filenames, "No .mmd files found in behaviour_diagrams/"


# ---------------------------------------------------------------------------
# JSON structure
# ---------------------------------------------------------------------------

def test_docx_rows_key_present(bd_json):
    assert "_docxRows" in bd_json, "_behaviour_pngs.json missing '_docxRows' key"


def test_core_has_docx_rows(docx_rows):
    """Core is called by App/Main and Cross/Hub (external to Sample group) — must have rows."""
    assert "Core" in docx_rows, "Core module missing from _docxRows (expected: called by App/Main, Cross/Hub)"
    core_units = docx_rows["Core"]
    assert "Core" in core_units, "Core unit missing from _docxRows['Core']"
    assert core_units["Core"], "Core unit has no behaviour diagram rows"


def test_lib_has_no_docx_rows(docx_rows):
    """Lib is only called by Core (internal to Sample) — must have no behaviour diagram rows."""
    lib_rows = docx_rows.get("Lib", {})
    all_lib = [row for unit_rows in lib_rows.values() for row in unit_rows]
    assert not all_lib, f"Lib should have no behaviour rows (callers are internal), found: {all_lib}"


def test_util_has_no_docx_rows(docx_rows):
    """Util is only called by Core/Lib (internal to Sample) — must have no behaviour diagram rows."""
    util_rows = docx_rows.get("Util", {})
    all_util = [row for unit_rows in util_rows.values() for row in unit_rows]
    assert not all_util, f"Util should have no behaviour rows (callers are internal), found: {all_util}"


# ---------------------------------------------------------------------------
# Row structure
# ---------------------------------------------------------------------------

def test_docx_row_fields(docx_rows):
    required = {"currentFunctionName", "externalUnitFunction", "pngPath"}
    for module, units in docx_rows.items():
        for unit, rows in units.items():
            for row in rows:
                missing = required - set(row.keys())
                assert not missing, (
                    f"Row in {module}/{unit} missing fields: {missing}\n  Row: {row}"
                )


def test_external_unit_function_format(docx_rows):
    """externalUnitFunction should be 'UnitName - funcName' format."""
    for module, units in docx_rows.items():
        for unit, rows in units.items():
            for row in rows:
                val = row.get("externalUnitFunction", "")
                assert " - " in val, (
                    f"externalUnitFunction should contain ' - ', got: {val!r}"
                )


def test_core_external_callers_are_outside_sample(docx_rows):
    """All external callers for Core must come from outside the Sample group."""
    sample_units = {"Core", "Lib", "Util"}  # units within Sample group
    for row in docx_rows.get("Core", {}).get("Core", []):
        ext = row.get("externalUnitFunction", "")
        unit_name = ext.split(" - ")[0] if " - " in ext else ext
        assert unit_name not in sample_units, (
            f"Core behaviour diagram has internal caller: {ext!r}"
        )


# ---------------------------------------------------------------------------
# .mmd file content
# ---------------------------------------------------------------------------

def test_mmd_files_use_double_underscore_separator(mmd_filenames):
    """Naming convention: current_key__caller_key.mmd."""
    for fname in mmd_filenames:
        assert "__" in fname, f".mmd file missing '__' separator: {fname}"


def test_mmd_files_contain_valid_mermaid(mmd_filenames):
    """Each .mmd must contain a valid Mermaid diagram (any supported type).
    Code fences are accepted — the content inside them is validated.
    """
    for fname in mmd_filenames:
        path = os.path.join(BD_DIR, fname)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert is_valid_mermaid(content), (
            f"{fname} does not contain a valid Mermaid diagram: {content[:60]!r}"
        )
