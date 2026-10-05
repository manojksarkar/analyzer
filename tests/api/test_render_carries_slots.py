"""The SWE.3 web render tells the reader which of its texts a reviewer can correct.

Every LLM-written text carries its `slot`: the address the review routes take (built on the
server by `review.slot`, so the client never builds a key) and its state in the one shape every
review route answers with (`review.catalog.slot_view`). Without it the page could only guess
which function a sentence belongs to -- by name, which two overloads share.
"""
import datetime
import json
from types import SimpleNamespace

import pytest

from api.services import doc_render as dr

pytestmark = pytest.mark.unit

UNIT = "Layer1.Lib|Lib"
FID = "Layer1.Lib|Lib|libAdd|int"
GID = "Layer1.Lib|Lib|g_total"
CALLER = "Layer1.App|App|main|"
ENTRIES = [
    {"interfaceId": "IF_1", "interfaceName": "libAdd", "name": "libAdd", "type": "Function",
     "functionId": FID, "qualifiedName": "libAdd", "description": "Adds.",
     "parameters": [{"type": "int", "name": "a", "range": "R"}], "returnType": "int"},
    {"interfaceId": "IF_2", "interfaceName": "g_total", "name": "g_total",
     "type": "Global Variable", "globalId": GID, "variableType": "int", "description": ""},
]
DOT = 'digraph G {\n  n0 [label="Start"];\n  n1 [label="add a"];\n  n0 -> n1;\n}'


class _Model:
    def __init__(self, **parts):
        self._parts = {"units": {}, "functions": {}, "globalVariables": {},
                       "dataDictionary": {}, "metadata": {"projectName": "P"}, **parts}

    def load(self, name):
        return self._parts.get(name, {})


def _render(tmp_path, *, overrides=None, model=None, headers=None, behaviour=None,
            flowchart=True):
    group = tmp_path / "Layer1.Lib"
    (group / "flowcharts").mkdir(parents=True)
    (group / "interface_tables.json").write_text(json.dumps({
        "unitNames": {UNIT: "Lib"}, UNIT: {"entries": ENTRIES}}), encoding="utf-8")
    if flowchart:
        (group / "flowcharts" / "Lib.json").write_text(json.dumps([
            {"name": "libAdd", "functionKey": FID, "flowchart": DOT,
             "cfg": {"nodes": [{"id": "n0"}, {"id": "n1"}], "edges": []}}]), encoding="utf-8")
    if headers is not None:
        (group / "unit_headers.json").write_text(json.dumps({UNIT: headers}), encoding="utf-8")
    if behaviour is not None:
        (group / "behaviour_diagrams").mkdir()
        (group / "behaviour_diagrams" / "_behaviour_pngs.json").write_text(
            json.dumps({"_docxRows": {"Layer1.Lib": {"Lib": behaviour}}}), encoding="utf-8")
    now = datetime.datetime(2026, 9, 30, tzinfo=datetime.timezone.utc)
    doc = SimpleNamespace(id="d1", group="Layer1.Lib", layer="Layer1", subtitle=None,
                          process="SWE.3", updated_at=now, version_id="v1")
    project = SimpleNamespace(name="P", compliance_standard="ISO_26262")
    version = SimpleNamespace(id="v1", tag="v1", resolved_config=None)
    return dr.build_render(doc, project, version, group, "p1", model_reader=model or _Model(),
                           output_reader=None, overrides=overrides or {})


def _sections(render):
    stack, out = list(render["sections"]), []
    while stack:
        s = stack.pop()
        out.append(s)
        stack.extend(s.get("children") or [])
    return out


def _section(render, pred):
    return next(s for s in _sections(render) if pred(s))


def _row(slot_kind, slot_key, human, llm, orphaned=False):
    return {(slot_kind, slot_key): SimpleNamespace(
        slot_kind=slot_kind, slot_key=slot_key, human_text=human, llm_text=llm,
        is_orphaned=orphaned, updated_by="u1",
        updated_at=datetime.datetime(2026, 9, 30, 21, 0, tzinfo=datetime.timezone.utc))}


class TestTheInterfaceTable:
    def test_the_information_cell_is_the_description_slot(self, tmp_path):
        table = _section(_render(tmp_path), lambda s: s["id"] == f"{UNIT}-iface")["table"]
        fn_slots, gv_slots = table["cell_slots"]
        assert [i for i, c in enumerate(fn_slots) if c] == [2]
        assert fn_slots[2]["slotKind"] == "description"
        assert fn_slots[2]["slotKey"] == FID
        assert fn_slots[2]["text"] == "Adds."
        assert gv_slots[2]["slotKey"] == GID

    def test_an_empty_description_is_an_empty_slot_not_the_dash(self, tmp_path):
        table = _section(_render(tmp_path), lambda s: s["id"] == f"{UNIT}-iface")["table"]
        assert table["rows"][1][2] == "-"
        assert table["cell_slots"][1][2]["text"] == ""


class TestAFunctionSection:
    def test_its_texts_carry_their_slots(self, tmp_path):
        model = _Model(functions={FID: {"inputName": "Operand",
                                        "outputName": ""}})
        ft = _section(_render(tmp_path, model=model),
                      lambda s: s["type"] == "flowchart_table")["flowchart_table"]
        assert ft["description_slot"]["slotKey"] == FID
        assert ft["input_name_slot"]["slotKind"] == "inputName"
        assert ft["input_name_slot"]["text"] == "Operand"
        # the page prints a stand-in; the slot is honestly empty
        assert ft["output_name"].endswith(" result")
        assert ft["output_name_slot"]["text"] == ""

    def test_its_flowchart_is_named_for_the_label_editor(self, tmp_path):
        ft = _section(_render(tmp_path), lambda s: s["type"] == "flowchart_table")["flowchart_table"]
        (fc,) = ft["flowcharts"]
        assert fc["flowchart_id"] == FID
        assert fc["editable"] is True

    def test_without_a_flowchart_the_content_carries_the_slot(self, tmp_path):
        sec = _section(_render(tmp_path, flowchart=False), lambda s: s["id"].startswith(f"{UNIT}-fn-"))
        assert sec["type"] == "richtext"
        assert sec["content_slot"]["slotKey"] == FID


class TestTheSlotState:
    def test_a_correction_in_force(self, tmp_path):
        rows = _row("description", FID, "Adds a to the total.", "Adds.")
        table = _section(_render(tmp_path, overrides=rows),
                         lambda s: s["id"] == f"{UNIT}-iface")["table"]
        slot = table["cell_slots"][0][2]
        assert slot["isOverridden"] is True and slot["canUndo"] is True
        assert slot["llmText"] == "Adds."
        assert slot["updatedBy"] == "u1"

    def test_an_orphan_is_not_in_force(self, tmp_path):
        rows = _row("description", FID, "Old words.", "Old LLM.", orphaned=True)
        table = _section(_render(tmp_path, overrides=rows),
                         lambda s: s["id"] == f"{UNIT}-iface")["table"]
        slot = table["cell_slots"][0][2]
        assert slot["isOrphaned"] is True and slot["isOverridden"] is False
        assert slot["canUndo"] is False


class TestUnitAndStructDescriptions:
    def test_the_unit_table_cell_is_the_unit_description(self, tmp_path):
        model = _Model(units={UNIT: {"name": "Lib", "description": "Maths helpers."}})
        table = _section(_render(tmp_path, model=model),
                         lambda s: s["title"] == "Component/Unit Table")["table"]
        slot = table["cell_slots"][0][2]
        assert (slot["slotKind"], slot["slotKey"], slot["text"]) == (
            "unitDescription", UNIT, "Maths helpers.")

    def test_a_record_row_shows_the_models_description(self, tmp_path):
        """A save writes the model; the row's copy is Phase 3's, stale until a re-export."""
        headers = [{"declaration": "struct Acc { int t; };", "information": "Old words.",
                    "typeKey": "Acc"},
                   {"declaration": "#define N 3", "information": "3", "typeKey": None}]
        model = _Model(dataDictionary={"Acc": {"kind": "struct", "description": "New words."}})
        table = _section(_render(tmp_path, model=model, headers=headers),
                         lambda s: s["id"] == f"{UNIT}-header")["table"]
        assert table["rows"][0][1] == "New words."
        assert table["cell_slots"][0][1]["slotKind"] == "structDescription"
        assert table["cell_slots"][0][1]["slotKey"] == "Acc"
        assert table["cell_slots"][1][1] is None


class TestABehaviourRow:
    def test_the_bullets_are_one_slot(self, tmp_path):
        rows = [{"currentFunctionName": "libAdd", "currentFunctionId": FID,
                 "externalCallerId": CALLER, "externalUnitFunction": "App - main",
                 "behaviorDescription": ["main calls libAdd.", "libAdd adds."]}]
        model = _Model(functions={FID: {"inputName": "Operand"}})
        bt = _section(_render(tmp_path, behaviour=rows, model=model),
                      lambda s: s["type"] == "behavior_table")["behavior_table"]
        slot = bt["description_slot"]
        assert slot["slotKind"] == "behaviourDescription"
        assert slot["bullets"] == ["main calls libAdd.", "libAdd adds."]
        assert slot["functionId"] == FID and slot["externalCallerId"] == CALLER
        assert bt["input_name_slot"]["slotKey"] == FID
        assert bt["input_name_slot"]["text"] == "Operand"

    def test_a_row_without_its_caller_id_has_none(self, tmp_path):
        rows = [{"currentFunctionName": "libAdd", "currentFunctionId": FID,
                 "behaviorDescription": ["x"]}]
        bt = _section(_render(tmp_path, behaviour=rows),
                      lambda s: s["type"] == "behavior_table")["behavior_table"]
        assert bt["description_slot"] is None
