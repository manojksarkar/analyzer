"""What else a correction invalidates (REQ-CS-01/02/03).

Some LLM text is generated FROM other LLM text. Correcting a function's description leaves its
callers' descriptions, and its unit's, describing wording the human has already rejected.

Two properties matter more than the mechanics, and both are load-bearing:

  **the cascade stops at one level** -- a transitive one is unbounded in a deep call graph, and one
  edit could mean hundreds of LLM calls;

  **node labels are not dependents of anything** -- the summary chain that produces them starts at
  the SOURCE, never at a description. Without that, one correction would invalidate ~42,000 labels
  and the cascade would be the whole document.
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
from review import cascade, override_service as svc, slot

CALLEE = "Comp|UnitA|ns::doThing|void"
CALLER1 = "Comp|UnitA|ns::first|void"
CALLER2 = "Comp|UnitB|ns::second|void"
GLOBAL = "Comp|UnitA|gCounter"
UNIT = "Comp|UnitA"
REL_BD = "Sample/behaviour_diagrams/_behaviour_pngs.json"


@pytest.fixture
def conn():
    eng = sa.create_engine("sqlite://")
    s.metadata.create_all(eng)
    with eng.begin() as cx:
        now = datetime.datetime.now(datetime.timezone.utc)
        cx.execute(sa.insert(s.projects).values(id="p", name="p", created_at=now))
        cx.execute(sa.insert(s.versions).values(id="v1", project_id="p", version="v1",
                                                created_at=now))
        # first() and second() both call doThing().
        for src in (CALLER1, CALLER2):
            cx.execute(sa.insert(s.model_edges).values(
                version_id="v1", kind="call", src_key=src, dst_key=CALLEE, mode=None))
        cx.execute(sa.insert(s.version_output_files).values(
            version_id="v1", rel_path=REL_BD, group_name="Sample",
            content=json.dumps({"_docxRows": {"Comp": {"UnitA": [
                {"currentFunctionId": CALLEE, "externalCallerId": CALLER2,
                 "externalUnitFunction": "UnitB - second",
                 "behaviorDescription": ["second calls doThing"]}]}}})))
        yield cx


def _deps(conn, key=CALLEE, kind=slot.DESCRIPTION, artifact="functions"):
    return cascade.dependents_of(conn, "v1", kind,
                                 slot.for_entity(kind, key) if kind == slot.DESCRIPTION else key,
                                 artifact=artifact)


class TestWhatAFunctionDescriptionInvalidates:
    def test_its_unit_description(self, conn):
        keys = {(d.slot_kind, d.slot_key) for d in _deps(conn)}
        assert (slot.UNIT_DESCRIPTION, slot.for_unit(UNIT)) in keys

    def test_its_direct_callers(self, conn):
        """One indexed lookup on ix_edges_reverse -- the index the schema comments 'who depends
        on X (impact)'."""
        keys = {d.slot_key for d in _deps(conn) if d.slot_kind == slot.DESCRIPTION}
        assert keys == {slot.for_entity(slot.DESCRIPTION, CALLER1),
                        slot.for_entity(slot.DESCRIPTION, CALLER2)}

    def test_behaviour_rows_at_either_end(self, conn):
        keys = {d.slot_key for d in _deps(conn) if d.slot_kind == slot.BEHAVIOUR_DESCRIPTION}
        assert keys == {slot.for_behaviour_row(CALLEE, CALLER2)}

    def test_it_does_not_invalidate_node_labels(self, conn):
        """The bound on the whole cascade. `_summarize_function_batch` builds its prompt from the
        signature and body and never reads `description`, so a correction cannot reach the
        ~42,000 node labels."""
        assert not any(d.slot_kind == slot.NODE_LABEL for d in _deps(conn))

    def test_it_stops_at_one_level(self, conn):
        """CALLER1's own callers are NOT included. A transitive cascade is unbounded in a deep
        call graph -- one edit, hundreds of LLM calls (REQ-CS-02)."""
        conn.execute(sa.insert(s.model_edges).values(
            version_id="v1", kind="call", src_key="Comp|UnitA|ns::grandparent|void",
            dst_key=CALLER1, mode=None))
        keys = {d.slot_key for d in _deps(conn)}
        assert slot.for_entity(slot.DESCRIPTION, "Comp|UnitA|ns::grandparent|void") not in keys

    def test_recursion_is_not_its_own_dependent(self, conn):
        conn.execute(sa.insert(s.model_edges).values(
            version_id="v1", kind="call", src_key=CALLEE, dst_key=CALLEE, mode=None))
        assert slot.for_entity(slot.DESCRIPTION, CALLEE) not in {d.slot_key for d in _deps(conn)}

    def test_two_call_sites_yield_one_dependent(self, conn):
        conn.execute(sa.insert(s.model_edges).values(
            version_id="v1", kind="call", src_key=CALLER1, dst_key=CALLEE, mode=None))
        callers = [d for d in _deps(conn)
                   if d.slot_key == slot.for_entity(slot.DESCRIPTION, CALLER1)]
        assert len(callers) == 1


class TestWhatDoesNotCascade:
    def test_a_global_description_reaches_only_its_unit(self, conn):
        deps = _deps(conn, key=GLOBAL, artifact="globalVariables")
        assert [(d.slot_kind, d.slot_key) for d in deps] == \
            [(slot.UNIT_DESCRIPTION, slot.for_unit(UNIT))]

    @pytest.mark.parametrize("kind", [slot.UNIT_DESCRIPTION, slot.STRUCT_DESCRIPTION,
                                      slot.BEHAVIOUR_INPUT_NAME, slot.BEHAVIOUR_OUTPUT_NAME,
                                      slot.BEHAVIOUR_DESCRIPTION, slot.NODE_LABEL])
    def test_every_other_kind_cascades_to_nothing(self, conn, kind):
        assert cascade.dependents_of(conn, "v1", kind, "anything") == []


class TestAHumansTextIsNeverOverwritten:
    def test_a_dependent_with_its_own_override_is_skipped(self, conn):
        """REQ-CS-03. Regenerating over a correction would undo somebody's work as a side effect
        of somebody else's."""
        conn.execute(sa.insert(s.text_overrides).values(
            version_id="v1", slot_kind=slot.DESCRIPTION,
            slot_key=slot.for_entity(slot.DESCRIPTION, CALLER1),
            llm_text="llm", human_text="already corrected", is_orphaned=False,
            updated_at=datetime.datetime.now(datetime.timezone.utc)))
        keys = {d.slot_key for d in _deps(conn)}
        assert slot.for_entity(slot.DESCRIPTION, CALLER1) not in keys
        assert slot.for_entity(slot.DESCRIPTION, CALLER2) in keys


class TestTheQueue:
    def test_dependents_are_recorded(self, conn):
        cascade.enqueue(conn, "v1", _deps(conn), source_kind=slot.DESCRIPTION,
                        source_key=CALLEE)
        rows = cascade.pending(conn, "v1")
        assert len(rows) == 4          # unit + 2 callers + 1 behaviour row
        assert all(r.source_slot_key == CALLEE for r in rows)

    def test_the_reason_is_recorded(self, conn):
        """So a reviewer can be told why their edit changed something they did not touch."""
        cascade.enqueue(conn, "v1", _deps(conn))
        assert all((r.reason or "").strip() for r in cascade.pending(conn, "v1"))

    def test_the_same_slot_twice_is_one_entry(self, conn):
        """Two corrections that both invalidate one caller need it regenerated once. Twice would
        be two LLM calls to reach the same place."""
        cascade.enqueue(conn, "v1", _deps(conn))
        cascade.enqueue(conn, "v1", _deps(conn))
        assert len(cascade.pending(conn, "v1")) == 4

    def test_an_entry_is_cleared_only_when_named(self, conn):
        """Not "clear the version": an entry must survive until the thing it names has actually
        been rebuilt, or a half-finished run leaves the document stale with an empty queue saying
        everything is fine."""
        cascade.enqueue(conn, "v1", _deps(conn))
        assert cascade.clear(conn, "v1", slot.UNIT_DESCRIPTION, slot.for_unit(UNIT))
        assert len(cascade.pending(conn, "v1")) == 3
        assert not cascade.clear(conn, "v1", slot.UNIT_DESCRIPTION, slot.for_unit(UNIT))

    def test_nothing_to_enqueue_is_not_an_error(self, conn):
        assert cascade.enqueue(conn, "v1", []) == 0
        assert cascade.pending(conn, "v1") == []


class TestThroughTheOverrideService:
    def _model(self):
        return {"functions": {CALLEE: {"qualifiedName": "ns::doThing",
                                       "description": "Does the thing."},
                              CALLER1: {"qualifiedName": "ns::first", "description": "First."},
                              CALLER2: {"qualifiedName": "ns::second", "description": "Second."}},
                "globalVariables": {GLOBAL: {"qualifiedName": "gCounter",
                                             "description": "Counts."}},
                "units": {UNIT: {"name": "UnitA", "description": "A unit."}},
                "dataDictionary": {}}

    def test_correcting_a_description_queues_its_dependents(self, conn):
        out = svc.apply_override(conn, "v1", slot.DESCRIPTION,
                                 slot.for_entity(slot.DESCRIPTION, CALLEE), "Corrected.",
                                 models=svc.ModelAccess(artifacts=self._model()))
        assert len(out.queued_for_regeneration) == 4
        assert len(cascade.pending(conn, "v1")) == 4

    def test_the_corrected_slot_is_not_queued_against_itself(self, conn):
        svc.apply_override(conn, "v1", slot.DESCRIPTION,
                           slot.for_entity(slot.DESCRIPTION, CALLEE), "Corrected.",
                           models=svc.ModelAccess(artifacts=self._model()))
        keys = {(r.slot_kind, r.slot_key) for r in cascade.pending(conn, "v1")}
        assert (slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, CALLEE)) not in keys

    def test_correcting_a_unit_description_queues_nothing(self, conn):
        out = svc.apply_override(conn, "v1", slot.UNIT_DESCRIPTION, slot.for_unit(UNIT),
                                 "Corrected.",
                                 models=svc.ModelAccess(artifacts=self._model()))
        assert list(out.queued_for_regeneration) == []
        assert cascade.pending(conn, "v1") == []

    def test_correcting_a_caller_afterwards_removes_it_from_the_queue_next_time(self, conn):
        """The human's own text wins: once CALLER1 is corrected, a later correction of the callee
        no longer asks for it to be regenerated."""
        models = svc.ModelAccess(artifacts=self._model())
        svc.apply_override(conn, "v1", slot.DESCRIPTION,
                           slot.for_entity(slot.DESCRIPTION, CALLER1), "Mine.", models=models)
        out = svc.apply_override(conn, "v1", slot.DESCRIPTION,
                                 slot.for_entity(slot.DESCRIPTION, CALLEE), "Corrected.",
                                 models=models)
        assert slot.for_entity(slot.DESCRIPTION, CALLER1) not in \
            {k for _kind, k in out.queued_for_regeneration}
