"""Listing what CAN be edited, not just what has been (`REQ-API-01`).

`list_overrides` answers "what has been corrected here?" and is empty until somebody corrects
something. That left the other half unanswered: *what is there to correct, and what is its key?*
A slot key may never be invented by a caller (`REQ-ID-01`), so without this the only way to obtain
one was to dig through stored view output by hand.

The rule these guard is the one that makes the listing trustworthy: **the text shown is read
through `resolver`, the same way `apply_override` writes it.** A listing that read `comment` while
a save wrote `description` would show one sentence and replace a different one, and both would
look right in isolation.
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
from review import catalog, override_service as svc, slot

NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)

FN = "Comp|UnitA|doThing|int"
FN2 = "Comp|UnitB|other|"
GLOBAL = "Comp|UnitA|g_count"


def _model():
    return {
        "functions": {
            FN: {"name": "doThing", "description": "Does the thing.",
                 "behaviourInputName": "in", "behaviourOutputName": "out"},
            FN2: {"name": "other", "description": "Other.",
                  "behaviourInputName": "", "behaviourOutputName": ""},
        },
        "globalVariables": {GLOBAL: {"name": "g_count", "description": "A counter."}},
        "units": {"Comp|UnitA": {"name": "UnitA", "description": "Unit A."},
                  "Comp|UnitB": {"name": "UnitB", "description": ""}},
        "dataDictionary": {
            "Buffer_t": {"kind": "struct", "name": "Buffer_t", "description": "A buffer."},
            # Stored with a description field like any entry, and shown by no document -- so
            # never offered as a slot (a correction would save and never be seen).
            "UINT8": {"kind": "typedef", "name": "UINT8", "underlyingType": "unsigned char"},
            "MAX_LEN": {"kind": "define", "name": "MAX_LEN", "value": "64"},
            "Mode_t": {"kind": "enum", "name": "Mode_t", "enumerators": []},
            "int": {"kind": "primitive", "name": "int"},
            "Outer": {"kind": "class", "name": "Outer", "description": "Holds things."},
            "Outer::Inner": {"kind": "struct", "name": "Inner", "nestedIn": "Outer"},
        },
    }


@pytest.fixture
def conn():
    eng = sa.create_engine("sqlite://")
    s.metadata.create_all(eng)
    with eng.begin() as cx:
        cx.execute(sa.insert(s.projects).values(id="p", name="p", created_at=NOW))
        cx.execute(sa.insert(s.versions).values(id="v1", project_id="p", version="v1",
                                                created_at=NOW))
        yield cx


@pytest.fixture
def models():
    return svc.ModelAccess(artifacts=_model())


def _override(conn, kind, key, human="Corrected.", llm="Original.", orphaned=False):
    conn.execute(sa.insert(s.text_overrides).values(
        version_id="v1", slot_kind=kind, slot_key=key, llm_text=llm, human_text=human,
        is_orphaned=orphaned, updated_by="u1", updated_at=NOW))


def _keys(page):
    return [i.get("slotKey") or i.get("flowchartId") for i in page.items]


class TestTheModelBackedKinds:
    def test_descriptions_cover_functions_and_globals(self, conn, models):
        page = catalog.list_slots(conn, "v1", slot.DESCRIPTION, models=models)
        assert page.total == 3
        assert set(_keys(page)) == {FN, FN2, GLOBAL}

    def test_behaviour_names_are_functions_only(self, conn, models):
        """A global has no behaviour row, so offering one would be a slot that cannot be saved."""
        page = catalog.list_slots(conn, "v1", slot.BEHAVIOUR_INPUT_NAME, models=models)
        assert set(_keys(page)) == {FN, FN2}

    def test_the_text_is_the_one_a_save_would_replace(self, conn, models):
        """THE RULE. Read through `resolver`, exactly as `apply_override` writes it."""
        page = catalog.list_slots(conn, "v1", slot.DESCRIPTION, models=models)
        row = next(i for i in page.items if i["slotKey"] == FN)
        assert row["text"] == "Does the thing."

        page = catalog.list_slots(conn, "v1", slot.BEHAVIOUR_INPUT_NAME, models=models)
        row = next(i for i in page.items if i["slotKey"] == FN)
        assert row["text"] == "in", "the same key must read a DIFFERENT field per kind"

    def test_an_empty_slot_is_still_listed(self, conn, models):
        """`behaviourOutputName` is legitimately blank on a function that writes nothing, and a
        reviewer may be filling it in for the first time -- hiding it would hide the edit."""
        page = catalog.list_slots(conn, "v1", slot.BEHAVIOUR_OUTPUT_NAME, models=models)
        row = next(i for i in page.items if i["slotKey"] == FN2)
        assert row["text"] == "" and row["isOverridden"] is False

    def test_the_scope_comes_from_the_key(self, conn, models):
        """Function entries carry no `unit`/`component` fields; the scope is in the key."""
        page = catalog.list_slots(conn, "v1", slot.DESCRIPTION, models=models)
        row = next(i for i in page.items if i["slotKey"] == FN)
        assert (row["component"], row["unit"]) == ("Comp", "UnitA")

    def test_units_are_listed_by_their_own_key(self, conn, models):
        page = catalog.list_slots(conn, "v1", slot.UNIT_DESCRIPTION, models=models)
        assert set(_keys(page)) == {"Comp|UnitA", "Comp|UnitB"}

    def test_structs_are_listed(self, conn, models):
        page = catalog.list_slots(conn, "v1", slot.STRUCT_DESCRIPTION, models=models)
        row = next(i for i in page.items if i["slotKey"] == "Buffer_t")
        assert row["text"] == "A buffer." and row["kindOfType"] == "struct"

    def test_only_records_a_document_describes_are_offered(self, conn, models):
        """The data dictionary holds typedefs, defines, enums, primitives and nested records,
        each with a `description` field the model would store -- and no row that prints it."""
        page = catalog.list_slots(conn, "v1", slot.STRUCT_DESCRIPTION, models=models)
        assert sorted(_keys(page)) == ["Buffer_t", "Outer"]


def _unit_headers(conn, by_unit, rel_path="G/unit_headers.json"):
    conn.execute(sa.insert(s.version_output_files).values(
        version_id="v1", rel_path=rel_path, content=json.dumps(by_unit), group_name="G"))


def _hrow(decl, info, type_key=None, *, legacy=False):
    row = {"declaration": decl, "information": info}
    if not legacy:
        row["typeKey"] = type_key
    return row


class TestWhereAStructDescriptionIsShown:
    """The key names a type, not a unit -- but the unit header table shows the description
    under particular units, which is where a reviewer meets it. The stored rows say which."""

    def test_each_row_says_which_units_show_it(self, conn, models):
        _unit_headers(conn, {
            "Comp|UnitA": [_hrow("struct Buffer_t {...}", "A buffer.", "Buffer_t"),
                           _hrow("#define MAX_LEN 64", "64")],
            "Comp|UnitB": [_hrow("typedef struct Buffer_t Buf;", "A buffer.", "Buffer_t")]})
        page = catalog.list_slots(conn, "v1", slot.STRUCT_DESCRIPTION, models=models)
        row = next(i for i in page.items if i["slotKey"] == "Buffer_t")
        assert row["shownIn"] == ["Comp|UnitA", "Comp|UnitB"]
        assert (row["component"], row["unit"]) == ("Comp", "UnitA")
        outer = next(i for i in page.items if i["slotKey"] == "Outer")
        assert outer["shownIn"] == [] and outer["unit"] is None, "shown by no document here"

    def test_a_unit_filter_keeps_what_that_unit_shows(self, conn, models):
        _unit_headers(conn, {"Comp|UnitA": [_hrow("struct Buffer_t {...}", "A buffer.", "Buffer_t")],
                             "Comp|UnitB": [_hrow("class Outer {...}", "Holds things.", "Outer")]})
        assert _keys(catalog.list_slots(conn, "v1", slot.STRUCT_DESCRIPTION, models=models,
                                        unit="UnitB")) == ["Outer"]
        assert _keys(catalog.list_slots(conn, "v1", slot.STRUCT_DESCRIPTION, models=models,
                                        component="Comp")) == ["Buffer_t", "Outer"]
        assert catalog.list_slots(conn, "v1", slot.STRUCT_DESCRIPTION, models=models,
                                  component="Other").total == 0

    def test_output_that_cannot_say_refuses_a_filter(self, conn, models):
        """Rows derived before `typeKey` existed cannot say where anything is shown. An empty
        answer would read as "this unit shows none"; refused instead, with the remedy."""
        _unit_headers(conn, {"Comp|UnitA": [_hrow("struct Buffer_t {...}", "A buffer.",
                                                  legacy=True)]})
        with pytest.raises(catalog.NotScoped, match="Re-export"):
            catalog.list_slots(conn, "v1", slot.STRUCT_DESCRIPTION, models=models, unit="UnitA")
        # ...while the unfiltered list still answers.
        assert "Buffer_t" in _keys(catalog.list_slots(conn, "v1", slot.STRUCT_DESCRIPTION,
                                                      models=models))


def _store(conn, rel_path, content):
    conn.execute(sa.insert(s.version_output_files).values(
        version_id="v1", rel_path=rel_path, content=json.dumps(content), group_name="G"))


class TestEveryRowSaysWhereItsTextIsShown:
    """A slot exists for every function in the model, but a document shows only some: a function
    gets an interface row -- and with it a flowchart table and behaviour names -- only when another
    unit in the parsed scope calls it (develop 470d15c). In a run scoped to one group most are
    shown nowhere, and a correction to one of those saves and is never seen. `shownIn` says which,
    read from the stored views -- what the documents actually print."""

    def _documents(self, conn, *, drawn=True):
        # UnitA is documented: doThing and g_count are published. UnitB has a section too,
        # but `other` is private -- listed nowhere.
        _store(conn, "G/interface_tables.json", {
            "unitNames": {"Comp|UnitA": "UnitA", "Comp|UnitB": "UnitB"},
            "Comp|UnitA": {"name": "UnitA", "entries": [{"functionId": FN}, {"globalId": GLOBAL}]},
            "Comp|UnitB": {"name": "UnitB", "entries": []}})
        if drawn:
            _store(conn, "G/flowcharts/UnitA.json", [{"name": "doThing", "functionKey": FN,
                                                      "cfg": {"nodes": [], "edges": []}}])

    def _shown(self, conn, models, kind):
        return {i["slotKey"]: i["shownIn"]
                for i in catalog.list_slots(conn, "v1", kind, models=models).items}

    def test_a_description_is_shown_where_its_interface_row_is(self, conn, models):
        self._documents(conn)
        assert self._shown(conn, models, slot.DESCRIPTION) == {
            FN: ["Comp|UnitA"], GLOBAL: ["Comp|UnitA"], FN2: []}

    def test_behaviour_names_need_the_flowchart_table_or_a_behaviour_row(self, conn, models):
        self._documents(conn)
        _store(conn, "G/behaviour_diagrams/_behaviour_pngs.json", {"_docxRows": {"Comp": {
            "UnitB": [{"currentFunctionId": FN2, "externalCallerId": "X|Y|z|"}]}}})
        assert self._shown(conn, models, slot.BEHAVIOUR_INPUT_NAME) == {
            FN: ["Comp|UnitA"], FN2: ["Comp|UnitB"]}

    def test_without_a_drawn_flowchart_behaviour_names_are_not_shown(self, conn, models):
        """Flowcharts off: a published function's section is its description paragraph only."""
        self._documents(conn, drawn=False)
        assert self._shown(conn, models, slot.BEHAVIOUR_OUTPUT_NAME)[FN] == []

    def test_a_unit_is_shown_when_it_has_a_section(self, conn, models):
        self._documents(conn)
        assert self._shown(conn, models, slot.UNIT_DESCRIPTION) == {
            "Comp|UnitA": ["Comp|UnitA"], "Comp|UnitB": ["Comp|UnitB"]}

    def test_nothing_derived_means_nothing_shown(self, conn, models):
        assert set(map(tuple, self._shown(conn, models, slot.DESCRIPTION).values())) == {()}

    def test_a_hidden_function_is_shown_nowhere(self, conn):
        """The exporter drops a hidden function from the document entirely."""
        self._documents(conn)
        model = _model()
        model["functions"][FN]["hidden"] = True
        page = catalog.list_slots(conn, "v1", slot.DESCRIPTION,
                                  models=svc.ModelAccess(artifacts=model))
        assert next(i for i in page.items if i["slotKey"] == FN)["shownIn"] == []

    def test_a_flowchart_is_shown_where_its_function_is_published(self, conn):
        self._documents(conn)
        _store(conn, "G/flowcharts/UnitB.json", [{"name": "other", "functionKey": FN2,
                                                  "cfg": {"nodes": [], "edges": []}}])
        rows = {i["flowchartId"]: i["shownIn"]
                for i in catalog.list_slots(conn, "v1", slot.NODE_LABEL).items}
        assert rows == {FN: ["Comp|UnitA"], FN2: []}

    def test_a_behaviour_row_is_shown_where_it_sits(self, conn):
        _store(conn, "G/behaviour_diagrams/_behaviour_pngs.json", {"_docxRows": {"Comp": {
            "UnitA": [{"currentFunctionId": FN, "externalCallerId": "X|Y|z|"}]}}})
        page = catalog.list_slots(conn, "v1", slot.BEHAVIOUR_DESCRIPTION)
        assert page.items[0]["shownIn"] == ["Comp|UnitA"]


class TestOverrideState:
    def test_a_corrected_slot_shows_the_human_text(self, conn, models):
        """Through the REAL save, not a hand-inserted row.

        An earlier version of this inserted an override row without touching the model -- a
        state `apply_override` can never produce, since it writes both. The test then asserted
        the row's text, which is how the listing came to read `text` from the row at all, and
        so showed an ORPHAN's stale words as the current wording. Going through the real save
        means the fixture cannot drift from what production does.
        """
        svc.apply_override(conn, "v1", slot.DESCRIPTION, FN, "Corrected.", models=models)
        row = next(i for i in catalog.list_slots(conn, "v1", slot.DESCRIPTION,
                                                 models=models).items
                   if i["slotKey"] == FN)
        assert row["isOverridden"] is True and row["isOrphaned"] is False
        assert row["text"] == "Corrected."
        assert row["humanText"] == "Corrected."
        assert row["llmText"] == "Does the thing."

    def test_an_uncorrected_slot_carries_its_llm_text(self, conn, models):
        """`llmText` means one thing everywhere: what the LLM wrote for this slot. Nobody has
        corrected it, so that is what the document prints (`REQ-API-09`). It used to be null
        until a first edit here, and filled in R3's answer."""
        row = next(i for i in catalog.list_slots(conn, "v1", slot.DESCRIPTION,
                                                 models=models).items
                   if i["slotKey"] == FN)
        assert row["llmText"] == row["text"] == "Does the thing."
        assert row["isOverridden"] is False and row["humanText"] is None
        assert row["canUndo"] is False and row["updatedAt"] is None

    def test_an_orphan_is_shown_as_one(self, conn, models):
        _override(conn, slot.DESCRIPTION, FN, orphaned=True)
        row = next(i for i in catalog.list_slots(conn, "v1", slot.DESCRIPTION,
                                                 models=models).items
                   if i["slotKey"] == FN)
        assert row["isOrphaned"] is True

    def test_one_query_not_one_per_slot(self, conn, models):
        """A lookup per slot would be 57,000 round trips on a real version."""
        src = open(os.path.join(PROJECT_ROOT, "engine", "review", "catalog.py"),
                   encoding="utf-8").read()
        start = src.index("def _model_backed(")
        body = src[start:src.index("\ndef ", start + 1)]          # that function alone
        assert "_overridden(conn" in body and body.count("conn.execute") == 0

    def test_structs_read_their_placement_in_one_query_too(self, conn, models):
        src = open(os.path.join(PROJECT_ROOT, "engine", "review", "catalog.py"),
                   encoding="utf-8").read()
        start = src.index("def _structs(")
        body = src[start:src.index("\ndef ", start + 1)]
        assert "_shown_in(conn" in body and body.count("conn.execute") == 0


class TestNarrowing:
    def test_by_unit(self, conn, models):
        page = catalog.list_slots(conn, "v1", slot.DESCRIPTION, models=models, unit="UnitA")
        assert set(_keys(page)) == {FN, GLOBAL}

    def test_by_component(self, conn, models):
        assert catalog.list_slots(conn, "v1", slot.DESCRIPTION, models=models,
                                  component="Comp").total == 3
        assert catalog.list_slots(conn, "v1", slot.DESCRIPTION, models=models,
                                  component="Nope").total == 0

    @pytest.mark.parametrize("asked", ["Layer1.My Sample", "layer1.my-sample",
                                       "Layer1.My-Sample"])
    def test_a_component_is_matched_however_it_is_spelled(self, conn, asked):
        """A key spells a component with hyphens, the config and the CLI with spaces. The
        spaced spelling used to match nothing -- an empty list, read as "no slots here"."""
        fn = "Layer1.My-Sample|Core|ns::f|void"
        m = svc.ModelAccess(artifacts={"functions": {fn: {"name": "f", "description": "F."}},
                                       "globalVariables": {}, "units": {},
                                       "dataDictionary": {}})
        page = catalog.list_slots(conn, "v1", slot.DESCRIPTION, models=m, component=asked)
        assert _keys(page) == [fn]
        conn.execute(sa.insert(s.version_output_files).values(
            version_id="v1", rel_path="G/flowcharts/Core.json", group_name="G",
            content=json.dumps([{"name": "f", "functionKey": fn,
                                 "cfg": {"nodes": [{"id": "n0"}], "edges": []}}])))
        assert catalog.list_slots(conn, "v1", slot.NODE_LABEL, component=asked).total == 1

    def test_a_struct_filter_nothing_can_answer_is_refused_not_ignored(self, conn, models):
        """No stored unit header rows at all: nothing says where a struct is shown. A filter
        that silently does nothing is worse than one that is rejected -- the caller reads the
        unfiltered result as the filtered one."""
        with pytest.raises(catalog.NotScoped):
            catalog.list_slots(conn, "v1", slot.STRUCT_DESCRIPTION, models=models, unit="UnitA")

    def test_paging_reports_the_total_before_paging(self, conn, models):
        page = catalog.list_slots(conn, "v1", slot.DESCRIPTION, models=models, limit=1)
        assert len(page.items) == 1 and page.total == 3

    def test_offset_walks_without_repeating(self, conn, models):
        seen = []
        for off in range(3):
            seen += _keys(catalog.list_slots(conn, "v1", slot.DESCRIPTION, models=models,
                                             limit=1, offset=off))
        assert sorted(seen) == sorted([FN, FN2, GLOBAL])

    def test_an_unknown_kind_is_refused(self, conn, models):
        with pytest.raises(slot.SlotKeyError):
            catalog.list_slots(conn, "v1", "notAKind", models=models)


class TestFlowchartsAreListedPerGraph:
    """~42,000 node labels in a version. One row per node would be hundreds of pages of
    something nobody reads linearly, so this lists the graphs and R7 lists their nodes."""

    def _store(self, conn, fid="Comp|UnitA|doThing|int", nodes=3):
        content = json.dumps([{ "name": "doThing", "functionKey": fid,
                                "cfg": {"nodes": [{"id": "n%d" % i, "label": "L%d" % i}
                                                  for i in range(nodes)], "edges": []}}])
        conn.execute(sa.insert(s.version_output_files).values(
            version_id="v1", rel_path="G/flowcharts/UnitA.json", content=content,
            group_name="G"))

    def test_one_row_per_flowchart(self, conn):
        self._store(conn)
        page = catalog.list_slots(conn, "v1", slot.NODE_LABEL)
        assert page.total == 1
        assert page.items[0]["nodeCount"] == 3

    def test_it_carries_the_id_r7_takes(self, conn):
        """The function's id, as it is -- no second spelling of the same fact."""
        self._store(conn)
        row = catalog.list_slots(conn, "v1", slot.NODE_LABEL).items[0]
        assert slot.flowchart_id_from_request(row["flowchartId"]) == row["flowchartId"]
        assert "flowchartToken" not in row

    def test_it_counts_the_corrections_on_that_graph(self, conn):
        self._store(conn)
        _override(conn, slot.NODE_LABEL, slot.for_node("Comp|UnitA|doThing|int", "n1"))
        assert catalog.list_slots(conn, "v1", slot.NODE_LABEL).items[0]["overriddenCount"] == 1

    def test_an_orphaned_correction_is_not_counted(self, conn):
        """It is kept in the table but not applied, so counting it would promise an edit the
        document does not carry."""
        self._store(conn)
        _override(conn, slot.NODE_LABEL, slot.for_node("Comp|UnitA|doThing|int", "n1"),
                  orphaned=True)
        assert catalog.list_slots(conn, "v1", slot.NODE_LABEL).items[0]["overriddenCount"] == 0

    def test_a_summary_file_is_not_a_flowchart(self, conn):
        conn.execute(sa.insert(s.version_output_files).values(
            version_id="v1", rel_path="G/flowcharts/_summary.json",
            content=json.dumps([{"functionKey": "x", "cfg": {"nodes": []}}]), group_name="G"))
        assert catalog.list_slots(conn, "v1", slot.NODE_LABEL).total == 0

    def test_it_needs_no_model(self, conn):
        """Flowcharts are Phase-3 output. Building a repository for this listing would pay for
        a model read nobody asked for."""
        self._store(conn)
        assert catalog.list_slots(conn, "v1", slot.NODE_LABEL, models=None).total == 1


class TestBehaviourRows:
    def _store(self, conn, caller="CompX|UnitB|apply|int"):
        payload = {"_docxRows": {"Comp": {"UnitA": [
            {"currentFunctionId": FN, "externalCallerId": caller,
             "externalUnitFunction": "UnitB - apply",
             # The REAL field. This fixture once used `behaviorDescriptionList` -- the same wrong
             # name the reader used -- so the test passed while real data listed no bullets.
             "behaviorDescription": ["calls it", "returns"]}]}}}
        conn.execute(sa.insert(s.version_output_files).values(
            version_id="v1", rel_path="G/behaviour_diagrams/_behaviour_pngs.json",
            content=json.dumps(payload), group_name="G"))

    def test_a_row_is_listed_with_its_bullets(self, conn):
        self._store(conn)
        page = catalog.list_slots(conn, "v1", slot.BEHAVIOUR_DESCRIPTION)
        assert page.total == 1
        assert page.items[0]["bullets"] == ["calls it", "returns"]

    def test_it_is_keyed_by_both_entity_ids(self, conn):
        self._store(conn)
        row = catalog.list_slots(conn, "v1", slot.BEHAVIOUR_DESCRIPTION).items[0]
        assert row["slotKey"] == slot.for_behaviour_row(FN, "CompX|UnitB|apply|int")

    def test_a_row_with_no_caller_id_is_not_offered(self, conn):
        """Written before `externalCallerId` existed: it cannot be addressed unambiguously, so
        it must not be presented as editable."""
        self._store(conn, caller="")
        assert catalog.list_slots(conn, "v1", slot.BEHAVIOUR_DESCRIPTION).total == 0

    def test_a_corrected_row_shows_the_human_bullets(self, conn):
        """Through the real save, for the same reason as the description test above: R6
        patches the stored row as well as writing the override, and only a real save does both."""
        self._store(conn)
        svc.apply_behaviour_override(conn, "v1", FN, "CompX|UnitB|apply|int", ["one", "two"])
        row = catalog.list_slots(conn, "v1", slot.BEHAVIOUR_DESCRIPTION).items[0]
        assert row["bullets"] == ["one", "two"] and row["isOverridden"] is True
        assert row["humanText"] == "one\ntwo"


class TestOneShapeForASlot:
    """`slot_view` (`REQ-API-09`): the fields every route gives a slot, whatever its kind."""

    FIELDS = {"slotKind", "slotKey", "text", "llmText", "humanText", "isOverridden",
              "isOrphaned", "canUndo", "updatedBy", "updatedAt"}

    class _Row:
        def __init__(self, llm, human, orphaned=False):
            import datetime
            self.llm_text, self.human_text, self.is_orphaned = llm, human, orphaned
            self.updated_by = "u1"
            self.updated_at = datetime.datetime(2026, 1, 1)

    def test_every_kind_has_the_same_fields(self):
        for kind in slot.ALL_KINDS:
            parts = {n: "Comp|UnitA|f|" if n != "node_id" else "n1" for n in slot.parts_for(kind)}
            key = slot.make(kind, **parts)
            assert self.FIELDS <= set(catalog.slot_view(kind, key, "t", None)), kind

    def test_a_node_label_says_where_it_is(self):
        v = catalog.slot_view(slot.NODE_LABEL, slot.for_node("C|U|f|", "n7"), "Check", None)
        assert (v["flowchartId"], v["nodeId"]) == ("C|U|f|", "n7")

    def test_a_behaviour_row_says_where_it_is_and_lists_its_bullets(self):
        key = slot.for_behaviour_row("C|U|f|", "D|V|g|")
        v = catalog.slot_view(slot.BEHAVIOUR_DESCRIPTION, key, "one\ntwo", None)
        assert (v["functionId"], v["externalCallerId"]) == ("C|U|f|", "D|V|g|")
        assert v["bullets"] == ["one", "two"]

    def test_undo_is_offered_only_where_it_would_change_the_text(self):
        view = catalog.slot_view
        assert view(slot.DESCRIPTION, FN, "Human.", self._Row("LLM.", "Human."))["canUndo"]
        assert not view(slot.DESCRIPTION, FN, "LLM.", None)["canUndo"]               # none
        assert not view(slot.DESCRIPTION, FN, "LLM.", self._Row("LLM.", "LLM."))["canUndo"]
        assert not view(slot.DESCRIPTION, FN, "Human.", self._Row(None, "Human."))["canUndo"]
        assert not view(slot.DESCRIPTION, FN, "New.", self._Row("Old.", "H.", True))["canUndo"]

    def test_an_empty_slot_has_no_llm_text(self):
        """The one case `llmText` is null: the LLM wrote nothing -- which is also why an undo of
        the first correction there is refused."""
        assert catalog.slot_view(slot.DESCRIPTION, FN, "", None)["llmText"] is None
        assert catalog.slot_view(slot.DESCRIPTION, FN, "Human.",
                                 self._Row("", "Human."))["llmText"] is None


class TestReadingAnySlot:
    """`slot_views` / `texts_in_force`: what R1 and R2 read -- the text from where the document
    reads it, for any slot, corrected or not."""

    def test_a_description_reads_from_the_model(self, conn, models):
        (v,) = catalog.slot_views(conn, "v1", [(slot.DESCRIPTION, FN)], models)
        assert v["text"] == "Does the thing." and v["isOverridden"] is False

    def test_a_slot_that_is_not_there_is_none(self, conn, models):
        assert catalog.slot_views(conn, "v1", [(slot.DESCRIPTION, "C|U|gone|")], models) == [None]

    def test_an_orphan_of_a_slot_that_left_is_still_shown(self, conn, models):
        """Its record is the reviewer's work: shown, with nothing printed."""
        _override(conn, slot.DESCRIPTION, "C|U|gone|", orphaned=True)
        (v,) = catalog.slot_views(conn, "v1", [(slot.DESCRIPTION, "C|U|gone|")], models)
        assert v["text"] == "" and v["isOrphaned"] is True and v["humanText"] == "Corrected."

    def test_node_labels_read_from_the_stored_flowchart(self, conn):
        """More than a few flowcharts are found in one pass; a few, one by one -- same answer."""
        fids = ["Comp|U%d|f|" % i for i in range(5)]
        for i, fid in enumerate(fids):
            conn.execute(sa.insert(s.version_output_files).values(
                version_id="v1", rel_path="G/flowcharts/U%d.json" % i, group_name="G",
                content=json.dumps([{"functionKey": fid, "cfg": {"nodes": [
                    {"id": "n0", "label": "label %d" % i}]}}])))
        many = catalog.slot_views(conn, "v1", [(slot.NODE_LABEL, slot.for_node(f, "n0"))
                                               for f in fids])
        few = catalog.slot_views(conn, "v1", [(slot.NODE_LABEL, slot.for_node(fids[3], "n0"))])
        assert [v["text"] for v in many] == ["label %d" % i for i in range(5)]
        assert few[0]["text"] == "label 3"
        assert catalog.slot_views(conn, "v1", [(slot.NODE_LABEL,
                                                slot.for_node(fids[0], "n9"))]) == [None]


class TestEveryKindIsListable:
    def test_no_kind_raises(self, conn, models):
        """An eighth kind added without a branch here would be silently unlistable -- the
        feature would look complete and one kind would have no way in."""
        for kind in slot.ALL_KINDS:
            catalog.list_slots(conn, "v1", kind, models=models)



class TestAnOrphanIsNotInForce:
    """An orphan is KEPT (`REQ-ID-03`) and NOT applied. The listing has to say both.

    The case that exposed it: a function's code changed, so the carry-forward orphaned the
    reviewer's description. The document now carries fresh LLM text for the new code -- and the
    listing reported the reviewer's stale words as `text`, with `isOverridden: true`. A UI built on
    that shows a correction as current wording when the document prints something else.
    """

    def _orphan(self, conn):
        _override(conn, slot.DESCRIPTION, FN, human="Stale words for the OLD code.",
                  llm="Old LLM text.", orphaned=True)

    def _row(self, conn, models):
        return next(i for i in catalog.list_slots(conn, "v1", slot.DESCRIPTION,
                                                  models=models).items
                    if i["slotKey"] == FN)

    def test_text_is_what_the_document_prints(self, conn, models):
        self._orphan(conn)
        assert self._row(conn, models)["text"] == "Does the thing."

    def test_it_is_not_reported_as_overridden(self, conn, models):
        """`isOverridden` means a correction is IN FORCE. An orphan is not one."""
        self._orphan(conn)
        row = self._row(conn, models)
        assert row["isOverridden"] is False and row["isOrphaned"] is True

    def test_the_reviewers_words_stay_visible(self, conn, models):
        """Kept means visible -- as what it is, not as what is printed. Without `humanText` the
        fix above would have made an orphan's work disappear from the listing entirely.

        `llmText` is the LLM's wording for the slot as it stands -- the fresh text for the new
        code, which a new edit would capture as its original -- not the old code's original the
        orphan was written against."""
        self._orphan(conn)
        row = self._row(conn, models)
        assert row["humanText"] == "Stale words for the OLD code."
        assert row["llmText"] == row["text"] == "Does the thing."
        assert row["canUndo"] is False

    def test_an_uncorrected_slot_has_no_human_text(self, conn, models):
        row = self._row(conn, models)
        assert row["humanText"] is None and row["llmText"] == "Does the thing."



class TestTheFixtureMatchesWhatTheViewWrites:
    """A test whose fixture shares the reader's mistake passes whatever the reader does.

    That is how R11 listed every real behaviour row with no bullets: the reader looked for
    `behaviorDescriptionList`, the fixture stored `behaviorDescriptionList`, and neither matched
    the `behaviorDescription` the behaviour view actually writes. So the field name is checked
    against the WRITER, not against another test.
    """

    def test_the_view_writes_the_field_the_listing_reads(self):
        view = open(os.path.join(PROJECT_ROOT, "engine", "views", "behaviour_diagram.py"),
                    encoding="utf-8").read()
        listing = open(os.path.join(PROJECT_ROOT, "engine", "review", "catalog.py"),
                       encoding="utf-8").read()
        assert '"behaviorDescription":' in view, "the behaviour view no longer writes this field"
        assert 'row.get("behaviorDescription")' in listing

    def test_the_exporter_reads_the_same_field(self):
        exporter = open(os.path.join(PROJECT_ROOT, "engine", "docx_exporter.py"),
                        encoding="utf-8").read()
        assert 'row.get("behaviorDescription"' in exporter

    def test_nothing_reads_the_parameter_name_as_a_field(self):
        listing = open(os.path.join(PROJECT_ROOT, "engine", "review", "catalog.py"),
                       encoding="utf-8").read()
        code = " ".join(l for l in listing.splitlines() if not l.strip().startswith("#"))
        assert 'get("behaviorDescriptionList")' not in code
