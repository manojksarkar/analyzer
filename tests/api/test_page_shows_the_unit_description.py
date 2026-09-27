"""The document page shows a unit's STORED description in its Component/Unit table.

The Word exporter prints the stored description (REQ-PRE-01): what Phase 2 generated, or a
reviewer's `unitDescription` correction. The page joined the unit's interface descriptions
instead, so it showed one sentence where the Word file showed another -- and a unit correction
never appeared on the page at all.
"""
import json
from types import SimpleNamespace

import pytest

from api.services import doc_render

pytestmark = pytest.mark.unit

UNIT = "Layer1.Core|Core"


class _Model:
    """Stands in for the version's model reader."""

    def __init__(self, units):
        self._parts = {"units": units, "functions": {}, "globalVariables": {},
                       "dataDictionary": {}, "metadata": {"projectName": "P"}}

    def load(self, name):
        return self._parts.get(name, {})


def _render(tmp_path, units):
    group_dir = tmp_path / "output" / "Layer1.Core"
    group_dir.mkdir(parents=True)
    (group_dir / "interface_tables.json").write_text(json.dumps({
        "unitNames": {UNIT: "Core"},
        UNIT: {"name": "Core", "entries": [
            {"type": "Function", "interfaceName": "coreAdd", "name": "coreAdd",
             "functionId": "Layer1.Core|Core|coreAdd|int,int",
             "description": "Adds two numbers."}]}}), encoding="utf-8")
    import datetime
    doc = SimpleNamespace(id="d1", group="Layer1.Core", name="Core", subtitle="Detailed Design",
                          version_id="v1", layer="Layer1", process="SWE.3",
                          updated_at=datetime.datetime(2026, 9, 27))
    project = SimpleNamespace(id="p1", name="P", compliance_standard="ASPICE_L2")
    return doc_render.build_render(doc, project, None, group_dir, "p1",
                                   model_reader=_Model(units))


def _unit_table_rows(payload):
    stack = list(payload.get("sections") or [])
    while stack:
        section = stack.pop()
        if section.get("title") == "Component/Unit Table":
            return section["table"]["rows"]
        stack.extend(section.get("children") or [])
    raise AssertionError("the page has no Component/Unit Table")


def test_the_stored_description_is_what_the_page_shows(tmp_path):
    rows = _unit_table_rows(_render(tmp_path, {UNIT: {"name": "Core",
                                                      "description": "Coordinates the pump."}}))
    assert rows[0][1:3] == ["Core", "Coordinates the pump."]


def test_without_one_the_interface_descriptions_stand_in(tmp_path):
    """A version generated before the description was stored, or with the LLM off -- the same
    fallback the Word exporter uses."""
    rows = _unit_table_rows(_render(tmp_path, {UNIT: {"name": "Core"}}))
    assert rows[0][2] == "Adds two numbers."
