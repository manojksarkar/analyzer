"""Unit tests for engine/swe4_exporter.py — cell rendering + table structure."""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

import swe4_exporter as se

pytest.importorskip("docx")


class TestCellRendering:
    def test_precondition_lists_mocks_params_globals(self):
        pre = {
            "mockFunctions": ["helper()"],
            "parameters": [{"name": "n", "type": "int"}],
            "globals": [{"name": "g_count", "type": "int", "direction": "read/write", "value": "0"}],
        }
        txt = se._precondition_text(pre)
        assert "Mock functions: helper()" in txt
        assert "int n" in txt
        assert "g_count" in txt and "read/write" in txt and "= 0" in txt

    def test_precondition_empty_is_none(self):
        assert se._precondition_text({}) == "None"

    def test_input_void(self):
        assert se._input_text({"isVoid": True}) == "VOID"

    def test_input_lists_params_when_not_void(self):
        txt = se._input_text({"isVoid": False,
                              "parameters": [{"name": "n", "type": "int", "range": "0-9"}]})
        assert "int n" in txt and "0-9" in txt
        assert "[To be specified]" not in txt  # deterministic domain, no placeholder

    def test_input_renders_llm_sets_when_present(self):
        txt = se._input_text({"isVoid": False, "parameters": [{"name": "n", "type": "int"}],
                              "sets": ["n = 1", "n = 9"]})
        assert "Set 1: n = 1" in txt and "Set 2: n = 9" in txt

    def test_expected_return_and_globals(self):
        txt = se._expected_text({"returnType": "int",
                                 "writesGlobals": [{"name": "g_count"}]})
        assert "int" in txt and "tester to confirm" in txt and "g_count" in txt
        assert "[To be specified]" not in txt

    def test_expected_void_no_return_line(self):
        txt = se._expected_text({"returnType": "void", "writesGlobals": []})
        assert "Return value" not in txt and "[To be specified]" not in txt


class TestTableStructure:
    def _doc(self):
        from docx import Document
        return Document()

    def _spec(self):
        return {
            "testCaseId": "TC_IF_01", "name": "f", "generationMethod": "Analysis of Requirements",
            "returnType": "int",
            "precondition": {"mockFunctions": [], "parameters": [], "globals": []},
            "input": {"isVoid": True, "parameters": [], "sets": []},
            "expected": {"returnType": "int", "writesGlobals": [], "sets": []},
            "testSteps": [],
        }

    def test_table_a_is_horizontal_six_cols_one_data_row(self):
        from docx.shared import Pt
        doc = self._doc()
        se._add_table_a(doc, self._spec(), {}, Pt(8))
        t = doc.tables[0]
        assert len(t.columns) == 6 and len(t.rows) == 2
        assert [c.text for c in t.rows[0].cells] == list(se.TABLE_A_COLS)

    def test_table_b_is_vertical_eight_fields(self):
        from docx.shared import Pt
        doc = self._doc()
        se._add_table_b(doc, self._spec(), {"priorityDefault": "Medium"}, Pt(8))
        t = doc.tables[0]
        assert len(t.columns) == 2 and len(t.rows) == 8
        labels = [r.cells[0].text for r in t.rows]
        assert labels[0] == "Test Case ID"
        assert "Test Case Generation Method" in labels
        gen_row = next(r for r in t.rows if r.cells[0].text == "Test Case Generation Method")
        assert gen_row.cells[1].text == "Analysis of Requirements"

    def test_table_a_env_defaults(self):
        from docx.shared import Pt
        doc = self._doc()
        se._add_table_a(doc, self._spec(),
                        {"evalEquipmentName": "Rig", "testPlatform": "HW"}, Pt(8))
        row = doc.tables[0].rows[1].cells
        assert row[0].text == "Rig" and row[5].text == "HW"
