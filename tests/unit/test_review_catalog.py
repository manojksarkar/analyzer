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
        "dataDictionary": {"Buffer_t": {"kind": "struct", "description": "A buffer."}},
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
        assert _keys(page) == ["Buffer_t"]
        assert page.items[0]["text"] == "A buffer."


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

    def test_an_uncorrected_slot_has_no_llm_text(self, conn, models):
        """`llmText` is the captured ORIGINAL, which only exists once someone has edited."""
        row = next(i for i in catalog.list_slots(conn, "v1", slot.DESCRIPTION,
                                                 models=models).items
                   if i["slotKey"] == FN)
        assert row["llmText"] is None and row["isOverridden"] is False

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
        body = src[src.index("def _model_backed("):src.index("def _structs(")]
        assert "_overridden(conn" in body and body.count("conn.execute") == 0


class TestNarrowing:
    def test_by_unit(self, conn, models):
        page = catalog.list_slots(conn, "v1", slot.DESCRIPTION, models=models, unit="UnitA")
        assert set(_keys(page)) == {FN, GLOBAL}

    def test_by_component(self, conn, models):
        assert catalog.list_slots(conn, "v1", slot.DESCRIPTION, models=models,
                                  component="Comp").total == 3
        assert catalog.list_slots(conn, "v1", slot.DESCRIPTION, models=models,
                                  component="Nope").total == 0

    def test_a_struct_filter_is_refused_not_ignored(self, conn, models):
        """A filter that silently does nothing is worse than one that is rejected: the caller
        reads the unfiltered result as the filtered one."""
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

    def test_it_carries_the_token_r7_takes(self, conn):
        self._store(conn)
        row = catalog.list_slots(conn, "v1", slot.NODE_LABEL).items[0]
        assert slot.decode(row["flowchartToken"]) == row["flowchartId"]

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
        fix above would have made an orphan's work disappear from the listing entirely."""
        self._orphan(conn)
        row = self._row(conn, models)
        assert row["humanText"] == "Stale words for the OLD code."
        assert row["llmText"] == "Old LLM text."

    def test_an_uncorrected_slot_has_no_human_text(self, conn, models):
        row = self._row(conn, models)
        assert row["humanText"] is None and row["llmText"] is None



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
