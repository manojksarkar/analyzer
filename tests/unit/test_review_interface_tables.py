"""A corrected description reaches the document, not only the model.

The audit finding this closes. The document does NOT read a function's description from the model:
the interface-tables view writes a **copy** into its own output, and both the DOCX exporter and the
HTML view read that copy. So the model write alone left the page showing the LLM's old words while
the model held the human's -- the two-copies failure this feature exists to remove, arriving from
the other direction.

It also removes an inconsistency a user could not have guessed: a corrected flowchart label reached
the document immediately (the flowchart JSON row is patched) while a corrected description did not.
"""
import datetime
import json
import os
import sys

import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from api.db.postgres import schema as s
from review import override_service as svc, rerender, slot

FN = "Comp|UnitA|ns::doThing|void"
GLOBAL = "Comp|UnitA|gCounter"
UNIT = "Comp|UnitA"
REL = "Sample/interface_tables.json"
NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


def _tables(fn_desc="LLM words.", global_desc="LLM global words."):
    return {
        UNIT: {"name": "UnitA", "entries": [
            {"interfaceId": "I1", "functionId": FN, "type": "Function",
             "name": "doThing", "description": fn_desc},
            {"interfaceId": "I2", "globalId": GLOBAL, "type": "Global Variable",
             "name": "gCounter", "description": global_desc},
        ]},
        "unitNames": {UNIT: "UnitA"},
    }


@pytest.fixture
def conn():
    eng = sa.create_engine("sqlite://")
    s.metadata.create_all(eng)
    with eng.begin() as cx:
        cx.execute(sa.insert(s.projects).values(id="p", name="p", created_at=NOW))
        cx.execute(sa.insert(s.versions).values(id="v1", project_id="p", version="v1",
                                                created_at=NOW))
        cx.execute(sa.insert(s.version_output_files).values(
            version_id="v1", rel_path=REL, group_name="Sample",
            content=json.dumps(_tables())))
        yield cx


def _stored(conn, rel=REL):
    return json.loads(conn.execute(
        sa.select(s.version_output_files.c.content)
        .where(s.version_output_files.c.rel_path == rel)).scalar())


def _model():
    return {"functions": {FN: {"qualifiedName": "ns::doThing", "description": "LLM words."}},
            "globalVariables": {GLOBAL: {"qualifiedName": "gCounter",
                                         "description": "LLM global words."}},
            "units": {UNIT: {"name": "UnitA", "description": "Unit text."}},
            "dataDictionary": {}}


class TestThePatcher:
    def test_a_function_description_is_brought_into_step(self, conn):
        assert rerender.patch_interface_tables(conn, "v1", FN, "Human words.") == 1
        entries = _stored(conn)[UNIT]["entries"]
        assert entries[0]["description"] == "Human words."

    def test_a_global_description_too(self, conn):
        assert rerender.patch_interface_tables(conn, "v1", GLOBAL, "Human global.") == 1
        assert _stored(conn)[UNIT]["entries"][1]["description"] == "Human global."

    def test_only_the_named_entry_changes(self, conn):
        rerender.patch_interface_tables(conn, "v1", FN, "Human words.")
        assert _stored(conn)[UNIT]["entries"][1]["description"] == "LLM global words."

    def test_every_group_that_holds_it_is_patched(self, conn):
        """A function lives in one unit but can appear in several groups' files when scopes
        overlap. Patching only the first would leave one document right and another wrong."""
        conn.execute(sa.insert(s.version_output_files).values(
            version_id="v1", rel_path="Other/interface_tables.json", group_name="Other",
            content=json.dumps(_tables())))
        assert rerender.patch_interface_tables(conn, "v1", FN, "Human words.") == 2
        for rel in (REL, "Other/interface_tables.json"):
            assert _stored(conn, rel)[UNIT]["entries"][0]["description"] == "Human words."

    def test_an_entity_not_in_the_tables_changes_nothing(self, conn):
        before = _stored(conn)
        assert rerender.patch_interface_tables(conn, "v1", "Gone|Gone|x|", "Words.") == 0
        assert _stored(conn) == before

    def test_the_unitnames_key_is_not_mistaken_for_a_unit(self, conn):
        """`unitNames` sits beside the units in the same dict; walking it as one would raise."""
        assert rerender.patch_interface_tables(conn, "v1", FN, "Human words.") == 1
        assert _stored(conn)["unitNames"] == {UNIT: "UnitA"}

    def test_an_unreadable_group_does_not_stop_the_others(self, conn):
        conn.execute(sa.insert(s.version_output_files).values(
            version_id="v1", rel_path="Broken/interface_tables.json", group_name="Broken",
            content="{not json"))
        assert rerender.patch_interface_tables(conn, "v1", FN, "Human words.") == 1

    def test_another_versions_tables_are_untouched(self, conn):
        conn.execute(sa.insert(s.versions).values(id="v2", project_id="p", version="v2",
                                                  created_at=NOW))
        conn.execute(sa.insert(s.version_output_files).values(
            version_id="v2", rel_path=REL, group_name="Sample",
            content=json.dumps(_tables())))
        rerender.patch_interface_tables(conn, "v1", FN, "Human words.")
        other = json.loads(conn.execute(
            sa.select(s.version_output_files.c.content)
            .where(s.version_output_files.c.version_id == "v2")).scalar())
        assert other[UNIT]["entries"][0]["description"] == "LLM words."


class TestThroughTheSave:
    def test_correcting_a_description_updates_the_document_copy(self, conn):
        """The whole point. Before this, the model moved and the page did not."""
        out = svc.apply_override(conn, "v1", slot.DESCRIPTION,
                                 slot.for_entity(slot.DESCRIPTION, FN), "Human words.",
                                 models=svc.ModelAccess(artifacts=_model()))
        assert out.tables_patched == 1
        assert _stored(conn)[UNIT]["entries"][0]["description"] == "Human words."

    def test_correcting_a_global_updates_it_too(self, conn):
        out = svc.apply_override(conn, "v1", slot.DESCRIPTION,
                                 slot.for_entity(slot.DESCRIPTION, GLOBAL), "Human global.",
                                 models=svc.ModelAccess(artifacts=_model()))
        assert out.tables_patched == 1
        assert _stored(conn)[UNIT]["entries"][1]["description"] == "Human global."

    def test_a_unit_description_patches_nothing(self, conn):
        """Unit and struct descriptions are read from the MODEL by the exporter
        (`_load_model_json`), so they were never stale and need no copy kept in step."""
        out = svc.apply_override(conn, "v1", slot.UNIT_DESCRIPTION, slot.for_unit(UNIT),
                                 "Human unit text.",
                                 models=svc.ModelAccess(artifacts=_model()))
        assert out.tables_patched == 0

    def test_a_behaviour_name_patches_nothing(self, conn):
        """Also read from the model, and not present in the interface tables at all."""
        out = svc.apply_override(conn, "v1", slot.BEHAVIOUR_INPUT_NAME,
                                 slot.for_entity(slot.BEHAVIOUR_INPUT_NAME, FN), "Timer value",
                                 models=svc.ModelAccess(artifacts=_model()))
        assert out.tables_patched == 0

    def test_an_undo_puts_the_original_back_in_the_document(self, conn):
        models = svc.ModelAccess(artifacts=_model())
        key = slot.for_entity(slot.DESCRIPTION, FN)
        svc.apply_override(conn, "v1", slot.DESCRIPTION, key, "Human words.", models=models)
        svc.undo_override(conn, "v1", slot.DESCRIPTION, key, models=models)
        assert _stored(conn)[UNIT]["entries"][0]["description"] == "LLM words."

    def test_a_version_with_no_tables_is_not_an_error(self, conn):
        """An API host correcting a version whose output has not been captured yet."""
        conn.execute(sa.delete(s.version_output_files))
        out = svc.apply_override(conn, "v1", slot.DESCRIPTION,
                                 slot.for_entity(slot.DESCRIPTION, FN), "Human words.",
                                 models=svc.ModelAccess(artifacts=_model()))
        assert out.tables_patched == 0
