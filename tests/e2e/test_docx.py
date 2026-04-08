"""E2E tests — verifies the final output/software_detailed_design_Sample.docx.

Column index map for interface tables (COLS in docx_exporter.py):
  0  Interface ID
  1  Interface Name
  2  Information
  3  Data Type
  4  Data Range
  5  Direction(In/Out)
  6  Source/Destination
  7  Interface Type
"""
import os

import pytest

try:
    from docx import Document
except ImportError:
    pytest.skip("python-docx not installed", allow_module_level=True)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCX_PATH = os.path.join(PROJECT_ROOT, "output", "software_detailed_design_Sample.docx")

COL_IF_ID    = 0
COL_IF_NAME  = 1
COL_DIRECTION = 5
COL_IF_TYPE  = 7

PRIVATE_NAMES = {"coreHelper", "coreSwitch", "libClamp", "utilClip", "g_count"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def docx(run_pipeline):
    if not os.path.isfile(DOCX_PATH):
        pytest.fail(f"DOCX not found: {DOCX_PATH}")
    return Document(DOCX_PATH)


@pytest.fixture(scope="module")
def interface_tables_in_docx(docx):
    return [
        t for t in docx.tables
        if t.rows and t.rows[0].cells[COL_IF_ID].text.strip() == "Interface ID"
    ]


@pytest.fixture(scope="module")
def all_interface_rows(interface_tables_in_docx):
    return [row for t in interface_tables_in_docx for row in t.rows[1:]]


@pytest.fixture(scope="module")
def all_cell_text(all_interface_rows):
    return {cell.text.strip() for row in all_interface_rows for cell in row.cells}


# ---------------------------------------------------------------------------
# Basic document sanity
# ---------------------------------------------------------------------------

def test_docx_exists(run_pipeline):
    assert os.path.isfile(DOCX_PATH), f"DOCX not found: {DOCX_PATH}"


def test_docx_non_empty(docx):
    text = "\n".join(p.text for p in docx.paragraphs)
    assert len(text.strip()) > 100, "DOCX appears empty or near-empty"


# ---------------------------------------------------------------------------
# Interface tables present
# ---------------------------------------------------------------------------

def test_interface_tables_found_in_docx(interface_tables_in_docx):
    assert len(interface_tables_in_docx) > 0, (
        "No interface tables found in DOCX (expected header 'Interface ID')"
    )


def test_interface_table_has_data_rows(all_interface_rows):
    assert len(all_interface_rows) > 0, "Interface tables have no data rows"


def test_interface_ids_start_with_IF(all_interface_rows):
    for row in all_interface_rows:
        iface_id = row.cells[COL_IF_ID].text.strip()
        assert iface_id.startswith("IF_"), f"Interface ID does not start with IF_: '{iface_id}'"


def test_interface_type_values_valid(all_interface_rows):
    valid = {"Function", "Global Variable"}
    for row in all_interface_rows:
        itype = row.cells[COL_IF_TYPE].text.strip()
        assert itype in valid, f"Unexpected Interface Type in DOCX: '{itype}'"


# ---------------------------------------------------------------------------
# Private items absent, public items present
# ---------------------------------------------------------------------------

def test_private_names_absent_from_docx(all_cell_text):
    for name in PRIVATE_NAMES:
        assert name not in all_cell_text, f"Private name '{name}' found in DOCX interface table"


@pytest.mark.parametrize("name,unit", [
    ("coreAdd",        "Core"), ("coreCompute",    "Core"), ("coreLoopSum",  "Core"),
    ("coreCheck",      "Core"), ("coreSumPoint",   "Core"), ("coreSetResult","Core"),
    ("coreProcess",    "Core"), ("coreOrchestrate","Core"), ("coreSetMode",  "Core"),
    ("coreGetCount",   "Core"), ("libAdd",         "Lib"),  ("libNormalize", "Lib"),
    ("utilCompute",    "Util"), ("utilScale",      "Util"),
    ("g_result",       "Core"), ("g_utilBase",     "Util"),
])
def test_public_name_in_docx(all_cell_text, name, unit):
    assert name in all_cell_text, f"'{name}' ({unit}) missing from DOCX interface table"


# ---------------------------------------------------------------------------
# Direction values in correct column
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,expected_direction", [
    ("coreGetCount",  "Out"),
    ("coreSetResult", "In"),
    ("g_result",      "In/Out"),
])
def test_direction_in_docx(all_interface_rows, name, expected_direction):
    row = next((r for r in all_interface_rows if r.cells[COL_IF_NAME].text.strip() == name), None)
    assert row is not None, f"'{name}' row not found in DOCX interface table"
    actual = row.cells[COL_DIRECTION].text.strip()
    assert actual == expected_direction, (
        f"'{name}' direction should be {expected_direction}, got '{actual}'"
    )


# ---------------------------------------------------------------------------
# Images and headings
# ---------------------------------------------------------------------------

def test_docx_has_embedded_images(docx):
    assert len(docx.inline_shapes) > 0, (
        "No embedded images in DOCX — unit/behaviour/flowchart/module-static diagrams missing"
    )


@pytest.mark.parametrize("heading", ["Dynamic Behaviour", "Static"])
def test_heading_present(docx, heading):
    headings = {p.text.strip() for p in docx.paragraphs if p.style.name.startswith("Heading")}
    assert any(heading in h for h in headings), (
        f"'{heading}' heading not found. Headings: {sorted(headings)[:10]}"
    )
