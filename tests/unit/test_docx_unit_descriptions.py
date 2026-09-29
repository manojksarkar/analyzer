"""The Component/Unit table's descriptions leave the exporter as data, not only as DOCX text.

With AI on, each unit's description is an LLM summary made while the DOCX is written, so the
web app's document (api/services/doc_render.py) had no way to show it and guessed from the
unit's functions instead. `_add_component_unit_table` now returns what it wrote per unit, and
export_docx saves that as unit_descriptions.json next to the views.
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for path in (os.path.join(_ROOT, "engine"),):
    if path not in sys.path:
        sys.path.insert(0, path)

docx = pytest.importorskip("docx", reason="python-docx is needed by docx_exporter")

import docx_exporter as dx                                        # noqa: E402

pytestmark = pytest.mark.unit

NO_LLM = {"llm": {"descriptions": False}}


def _rows():
    return [
        ("Layer1.Lib|Lib", "Lib", [
            {"type": "Function", "interfaceName": "libAdd", "description": "Adds two numbers."},
            {"type": "Global Variable", "interfaceName": "g_count", "description": "Counts calls."}]),
        ("Layer1.Lib|Empty", "Empty", [{"type": "Function", "interfaceName": "noop", "description": "-"}]),
    ]


def test_each_units_description_is_returned_as_the_table_shows_it():
    doc = docx.Document()
    written = dx._add_component_unit_table(doc, "Lib", _rows(), docx.shared.Pt(8), NO_LLM, {})
    table = doc.tables[0]
    assert written == {
        "Layer1.Lib|Lib": table.rows[1].cells[2].text,
        "Layer1.Lib|Empty": table.rows[2].cells[2].text,
    }
    assert written["Layer1.Lib|Lib"] == "Adds two numbers.; Counts calls."
    assert written["Layer1.Lib|Empty"] == "N/A"


def test_no_units_no_table_nothing_returned():
    doc = docx.Document()
    assert dx._add_component_unit_table(doc, "Lib", [], docx.shared.Pt(8), NO_LLM, {}) == {}
    assert not doc.tables
