"""What else a correction invalidates (REQ-CS-01/02/03, FAST_WORD_FILE_UPDATES §4.1).

Some LLM text is generated FROM other LLM text: every text whose prompt contains a corrected text
is queued, and the update of its component rewrites it (decided with the user, 2026-10-06). Only a
description is read by other prompts. Read from the prompt builders, a function's description is in
the prompts of its callers', callees' and same-file functions' descriptions, of the globals it
reaches, its unit's description, the behaviour rows it is in -- their incoming call or their call
tree -- and the labels of its own chart, its callees' charts and every chart within four calls
above it. A global's is in the
prompts of its unit's description and of the descriptions, input and output names and chart
labels of every function that reaches it.

**One level**: a text is queued because its prompt holds the CORRECTED text -- never because it
was written from a text that is itself queued (REQ-CS-02). A chart four calls up is one level: its
label prompt lists the callee hierarchy, descriptions included.
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


def _pairs(deps):
    return {(d.slot_kind, d.slot_key) for d in deps}


def _call(conn, src, dst):
    conn.execute(sa.insert(s.model_edges).values(
        version_id="v1", kind="call", src_key=src, dst_key=dst, mode=None))


def _reads(conn, fid, gid):
    conn.execute(sa.insert(s.model_edges).values(
        version_id="v1", kind="global_access", src_key=fid, dst_key=gid, mode="read"))


def _in_file(conn, fid, path):
    eid = conn.execute(sa.insert(s.entities).values(
        project_id="p", entity_key=fid, kind="function")).inserted_primary_key[0]
    conn.execute(sa.insert(s.entity_versions).values(version_id="v1", entity_id=eid, file=path))


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

    def test_its_callees_and_its_file_s_other_functions(self, conn):
        """A rich description's prompt lists the CALLERS of a function too, and its file's other
        functions (`_build_function_context`)."""
        callee = "Comp|UnitA|ns::helper|void"
        _call(conn, CALLEE, callee)
        _in_file(conn, CALLEE, "UnitA.cpp")
        _in_file(conn, "Comp|UnitA|ns::sibling|void", "UnitA.cpp")
        _in_file(conn, "Comp|UnitB|ns::elsewhere|void", "UnitB.cpp")
        keys = {d.slot_key for d in _deps(conn) if d.slot_kind == slot.DESCRIPTION}
        assert {slot.for_entity(slot.DESCRIPTION, callee),
                slot.for_entity(slot.DESCRIPTION, "Comp|UnitA|ns::sibling|void")} <= keys
        assert slot.for_entity(slot.DESCRIPTION, "Comp|UnitB|ns::elsewhere|void") not in keys

    def test_the_globals_it_reaches(self, conn):
        """A global's rich description lists its readers and writers, through calls."""
        callee = "Comp|UnitA|ns::helper|void"
        _call(conn, CALLEE, callee)
        _reads(conn, callee, GLOBAL)
        assert (slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, GLOBAL)) in _pairs(_deps(conn))

    def test_the_behaviour_rows_it_is_in(self, conn):
        """A row's bullets describe its incoming call -- from the caller the view drew it for --
        and its function's calls, each from both ends' descriptions (`build_diagram_for_caller`).
        So the row of the function itself, the rows of whoever reaches it, and the rows of what it
        reaches: it may be the row's caller, as CALLER2 is here."""
        row = slot.for_behaviour_row(CALLEE, CALLER2)
        for key in (CALLEE, CALLER2):
            rows = {d.slot_key for d in _deps(conn, key=key)
                    if d.slot_kind == slot.BEHAVIOUR_DESCRIPTION}
            assert rows == {row}, key
        stranger = "Comp|UnitB|ns::stranger|void"
        _call(conn, stranger, "Comp|UnitB|ns::other|void")
        assert not any(d.slot_kind == slot.BEHAVIOUR_DESCRIPTION
                       for d in _deps(conn, key=stranger))

    def test_its_chart_its_callees_charts_and_the_charts_four_calls_up(self, conn):
        """A label prompt names the function's purpose (its description), its callers' and its
        callees' descriptions down to four levels -- so these charts, and not a fifth level."""
        chain = ["Comp|UnitA|ns::up%d|void" % i for i in range(1, 6)]
        _call(conn, chain[0], CALLER1)
        for a, b in zip(chain[1:], chain):
            _call(conn, a, b)
        callee = "Comp|UnitA|ns::helper|void"
        _call(conn, CALLEE, callee)
        charts = {d.slot_key for d in _deps(conn) if d.slot_kind == cascade.FLOWCHART_LABELS}
        assert {CALLEE, callee, CALLER1, CALLER2, chain[0], chain[1], chain[2]} == charts
        assert not any(d.slot_kind == slot.NODE_LABEL for d in _deps(conn))

    def test_it_stops_at_one_level(self, conn):
        """CALLER1's own callers are NOT queued for their DESCRIPTIONS: their prompts hold
        CALLER1's description, not the corrected one (REQ-CS-02). Their chart is: its label prompt
        lists the callee hierarchy, the corrected description included."""
        gp = "Comp|UnitA|ns::grandparent|void"
        _call(conn, gp, CALLER1)
        pairs = _pairs(_deps(conn))
        assert (slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, gp)) not in pairs
        assert (cascade.FLOWCHART_LABELS, gp) in pairs

    def test_recursion_is_not_its_own_dependent(self, conn):
        _call(conn, CALLEE, CALLEE)
        assert (slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, CALLEE)) \
            not in _pairs(_deps(conn))

    def test_two_call_sites_yield_one_dependent(self, conn):
        _call(conn, CALLER1, CALLEE)
        callers = [d for d in _deps(conn) if d.slot_kind == slot.DESCRIPTION
                   and d.slot_key == slot.for_entity(slot.DESCRIPTION, CALLER1)]
        assert len(callers) == 1


class TestWhatAGlobalDescriptionInvalidates:
    def test_with_nobody_reading_it_only_its_unit(self, conn):
        deps = _deps(conn, key=GLOBAL, artifact="globalVariables")
        assert [(d.slot_kind, d.slot_key) for d in deps] == \
            [(slot.UNIT_DESCRIPTION, slot.for_unit(UNIT))]

    def test_the_texts_of_every_function_that_reaches_it(self, conn):
        """The knowledge base's read and write sets are transitive: a function that calls a reader
        has the global in its description's, its names' and its labels' prompts too."""
        _reads(conn, CALLEE, GLOBAL)               # CALLER1 and CALLER2 call CALLEE
        pairs = _pairs(_deps(conn, key=GLOBAL, artifact="globalVariables"))
        for fid in (CALLEE, CALLER1, CALLER2):
            assert {(slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, fid)),
                    (slot.INPUT_NAME, slot.for_entity(slot.INPUT_NAME, fid)),
                    (cascade.FLOWCHART_LABELS, fid)} <= pairs


class TestWhatDoesNotCascade:

    @pytest.mark.parametrize("kind", [slot.UNIT_DESCRIPTION, slot.STRUCT_DESCRIPTION,
                                      slot.INPUT_NAME, slot.OUTPUT_NAME,
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
        pairs = _pairs(_deps(conn))
        assert (slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, CALLER1)) not in pairs
        assert (slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, CALLER2)) in pairs

    def test_the_names_stay_queued_while_one_of_them_is_the_llm_s(self, conn):
        """An `inputName` entry stands for both names: it goes when BOTH are corrected."""
        _reads(conn, CALLEE, GLOBAL)
        now = datetime.datetime.now(datetime.timezone.utc)
        conn.execute(sa.insert(s.text_overrides).values(
            version_id="v1", slot_kind=slot.INPUT_NAME, slot_key=CALLEE, llm_text="x",
            human_text="Mine", is_orphaned=False, updated_at=now))
        names = (slot.INPUT_NAME, CALLEE)
        assert names in _pairs(_deps(conn, key=GLOBAL, artifact="globalVariables"))
        conn.execute(sa.insert(s.text_overrides).values(
            version_id="v1", slot_kind=slot.OUTPUT_NAME, slot_key=CALLEE, llm_text="y",
            human_text="Mine too", is_orphaned=False, updated_at=now))
        assert names not in _pairs(_deps(conn, key=GLOBAL, artifact="globalVariables"))


class TestTheQueue:
    def test_dependents_are_recorded(self, conn):
        cascade.enqueue(conn, "v1", _deps(conn), source_kind=slot.DESCRIPTION,
                        source_key=CALLEE)
        rows = cascade.pending(conn, "v1")
        assert len(rows) == 7          # unit + 2 callers + 1 behaviour row + 3 charts
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
        assert len(cascade.pending(conn, "v1")) == 7

    def test_an_entry_is_cleared_only_when_named(self, conn):
        """Not "clear the version": an entry must survive until the thing it names has actually
        been rebuilt, or a half-finished run leaves the document stale with an empty queue saying
        everything is fine."""
        cascade.enqueue(conn, "v1", _deps(conn))
        assert cascade.clear(conn, "v1", slot.UNIT_DESCRIPTION, slot.for_unit(UNIT))
        assert len(cascade.pending(conn, "v1")) == 6
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
        assert len(out.queued_for_regeneration) == 7
        assert len(cascade.pending(conn, "v1")) == 7

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
        assert (slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, CALLER1)) not in \
            set(out.queued_for_regeneration)
