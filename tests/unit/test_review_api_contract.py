"""Undo, the overlay list, and the API contract actually matching the spec.

Two separate things are checked here.

**Undo (REQ-API-04)** is not a special state -- it is an ordinary edit whose text happens to be the
LLM's original. That is what makes "the override record survives" true without a second code path,
and what makes the after-state consistent everywhere else: re-applying it during a Phase-3 run
writes the LLM's own words back, which is a no-op.

**The contract** is written down in `docs/spec/REVIEW_UPDATE_API_SPEC.md`, and the UI is built
against it. A documented route that does not exist is a bug report from someone else's sprint,
so the two are compared directly.
"""
import datetime
import json
import os
import re
import sys

import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine", "flowchart"))

from api.db.postgres import schema as s
from review import override_service as svc, slot

FID = "Comp|UnitA|ns::doThing|void"
CALLER = "CompX|UnitB|ns::apply|int"
REL_FC = "Sample/flowcharts/UnitA.json"
REL_BD = "Sample/behaviour_diagrams/_behaviour_pngs.json"


def _model():
    return {"functions": {FID: {"qualifiedName": "ns::doThing",
                                "description": "Does the thing."}},
            "globalVariables": {}, "units": {}, "dataDictionary": {}}


def _cfg(*ids):
    return {"entry": ids[0], "exits": [ids[-1]],
            "nodes": [{"id": i, "type": "ACTION", "label": "llm " + i, "rawCode": "c",
                       "line": 1, "endLine": 1} for i in ids],
            "edges": [{"source": a, "target": b, "label": None} for a, b in zip(ids, ids[1:])]}


@pytest.fixture
def conn():
    eng = sa.create_engine("sqlite://")
    s.metadata.create_all(eng)
    with eng.begin() as cx:
        now = datetime.datetime.now(datetime.timezone.utc)
        cx.execute(sa.insert(s.projects).values(id="p", name="p", created_at=now))
        cx.execute(sa.insert(s.versions).values(id="v1", project_id="p", version="v1",
                                                created_at=now))
        cx.execute(sa.insert(s.version_output_files).values(
            version_id="v1", rel_path=REL_FC, group_name="Sample",
            content=json.dumps([{"name": "ns::doThing", "functionKey": FID,
                                 "cfg": _cfg("n0", "n1"), "flowchart": "digraph G {}"}])))
        cx.execute(sa.insert(s.version_output_files).values(
            version_id="v1", rel_path=REL_BD, group_name="Sample",
            content=json.dumps({"_docxRows": {"Comp": {"UnitA": [
                {"currentFunctionId": FID, "externalCallerId": CALLER,
                 "externalUnitFunction": "UnitB - apply", "pngPath": "x.png",
                 "behaviorDescription": ["apply calls doThing"]}]}}})))
        yield cx


class TestUndoRestoresTheOriginal:
    def test_a_description_goes_back(self, conn):
        m = svc.ModelAccess(artifacts=_model())
        key = slot.for_entity(slot.DESCRIPTION, FID)
        svc.apply_override(conn, "v1", slot.DESCRIPTION, key, "Corrected.", models=m)
        svc.undo_override(conn, "v1", slot.DESCRIPTION, key, models=m)
        assert m.artifact("functions")[FID]["description"] == "Does the thing."

    def test_the_record_survives(self, conn):
        """REQ-API-04 says the record survives. Deleting it would destroy the user's work and the
        training pair to express "put it back"."""
        m = svc.ModelAccess(artifacts=_model())
        key = slot.for_entity(slot.DESCRIPTION, FID)
        svc.apply_override(conn, "v1", slot.DESCRIPTION, key, "Corrected.", models=m)
        svc.undo_override(conn, "v1", slot.DESCRIPTION, key, models=m)
        row = svc.get_override(conn, "v1", slot.DESCRIPTION, key)
        assert row is not None
        assert row.llm_text == "Does the thing."
        assert row.human_text == "Does the thing."

    def test_the_undo_is_in_the_history(self, conn):
        m = svc.ModelAccess(artifacts=_model())
        key = slot.for_entity(slot.DESCRIPTION, FID)
        svc.apply_override(conn, "v1", slot.DESCRIPTION, key, "Corrected.", models=m)
        svc.undo_override(conn, "v1", slot.DESCRIPTION, key, models=m)
        assert [r.human_text for r in svc.history_for(conn, "v1", slot.DESCRIPTION, key)] == \
            ["Corrected.", "Does the thing."]

    def test_a_node_label_undo_goes_through_the_flowchart_path(self, conn):
        svc.apply_flowchart_overrides(conn, "v1", FID, {"n1": "Corrected"})
        key = slot.for_node(FID, "n1")
        svc.undo_override(conn, "v1", slot.NODE_LABEL, key)
        stored = json.loads(conn.execute(
            sa.select(s.version_output_files.c.content)
            .where(s.version_output_files.c.rel_path == REL_FC)).scalar())
        labels = {n["id"]: n["label"] for n in stored[0]["cfg"]["nodes"]}
        assert labels["n1"] == "llm n1", "the picture still carries the human's words"

    def test_a_behaviour_undo_restores_the_bullet_list(self, conn):
        svc.apply_behaviour_override(conn, "v1", FID, CALLER, ["Corrected bullet"])
        key = slot.for_behaviour_row(FID, CALLER)
        svc.undo_override(conn, "v1", slot.BEHAVIOUR_DESCRIPTION, key)
        stored = json.loads(conn.execute(
            sa.select(s.version_output_files.c.content)
            .where(s.version_output_files.c.rel_path == REL_BD)).scalar())
        row = stored["_docxRows"]["Comp"]["UnitA"][0]
        assert row["behaviorDescription"] == ["apply calls doThing"]

    def test_undo_with_nothing_to_undo_is_refused(self, conn):
        m = svc.ModelAccess(artifacts=_model())
        with pytest.raises(svc.NothingToUndo):
            svc.undo_override(conn, "v1", slot.DESCRIPTION,
                              slot.for_entity(slot.DESCRIPTION, FID), models=m)

    def test_undo_is_refused_when_there_was_no_original(self, conn):
        """The slot was empty before the first correction, and REQ-ST-06 forbids writing empty
        text. Guessing -- by deleting the row -- would destroy the history to express "there was
        nothing here", so it is an explicit error instead."""
        model = _model()
        model["functions"][FID]["description"] = ""
        m = svc.ModelAccess(artifacts=model)
        key = slot.for_entity(slot.DESCRIPTION, FID)
        svc.apply_override(conn, "v1", slot.DESCRIPTION, key, "First words.", models=m)
        with pytest.raises(svc.NothingToUndo) as exc:
            svc.undo_override(conn, "v1", slot.DESCRIPTION, key, models=m)
        assert "no LLM original" in str(exc.value)
        assert svc.get_override(conn, "v1", slot.DESCRIPTION, key) is not None

    def test_it_can_be_re_corrected_after_an_undo(self, conn):
        m = svc.ModelAccess(artifacts=_model())
        key = slot.for_entity(slot.DESCRIPTION, FID)
        svc.apply_override(conn, "v1", slot.DESCRIPTION, key, "First.", models=m)
        svc.undo_override(conn, "v1", slot.DESCRIPTION, key, models=m)
        svc.apply_override(conn, "v1", slot.DESCRIPTION, key, "Second.", models=m)
        row = svc.get_override(conn, "v1", slot.DESCRIPTION, key)
        assert row.human_text == "Second."
        assert row.llm_text == "Does the thing.", "the original survived an undo and a re-edit"


class TestTheOverlayList:
    def test_a_version_with_no_corrections_is_empty(self, conn):
        assert svc.list_overrides(conn, "v1") == []
        assert svc.count_overrides(conn, "v1") == 0

    def test_it_lists_what_was_corrected(self, conn):
        m = svc.ModelAccess(artifacts=_model())
        svc.apply_override(conn, "v1", slot.DESCRIPTION,
                           slot.for_entity(slot.DESCRIPTION, FID), "Corrected.", models=m)
        svc.apply_flowchart_overrides(conn, "v1", FID, {"n1": "Also corrected"})
        assert svc.count_overrides(conn, "v1") == 2
        assert len(svc.list_overrides(conn, "v1")) == 2

    def test_it_filters_by_kind(self, conn):
        m = svc.ModelAccess(artifacts=_model())
        svc.apply_override(conn, "v1", slot.DESCRIPTION,
                           slot.for_entity(slot.DESCRIPTION, FID), "Corrected.", models=m)
        svc.apply_flowchart_overrides(conn, "v1", FID, {"n1": "Also"})
        rows = svc.list_overrides(conn, "v1", slot_kind=slot.NODE_LABEL)
        assert [r.slot_kind for r in rows] == [slot.NODE_LABEL]
        assert svc.count_overrides(conn, "v1", slot_kind=slot.NODE_LABEL) == 1

    def test_an_unknown_kind_is_refused(self, conn):
        with pytest.raises(svc.SlotUnknown):
            svc.list_overrides(conn, "v1", slot_kind="somethingElse")

    def test_the_page_size_is_capped(self, conn):
        """A version holds ~57,000 slots. An uncapped limit is a way to ask the API to build one
        response out of all of them."""
        m = svc.ModelAccess(artifacts=_model())
        svc.apply_override(conn, "v1", slot.DESCRIPTION,
                           slot.for_entity(slot.DESCRIPTION, FID), "x", models=m)
        assert len(svc.list_overrides(conn, "v1", limit=10 ** 6)) == 1   # does not raise


class TestTheDocumentedContractExists:
    """The UI is built against REVIEW_UPDATE_API_SPEC. A documented route that does not exist
    becomes a bug report from someone else's sprint."""

    SPEC = os.path.join(PROJECT_ROOT, "docs", "spec", "REVIEW_UPDATE_API_SPEC.md")

    @staticmethod
    def _shape(path):
        """Path parameter NAMES are not part of the URL contract, and the two sides spell them
        differently by long-standing convention: the spec uses `{projectId}` throughout, FastAPI
        uses `{project_id}`. Compare the shape."""
        return re.sub(r"\{[^}]*\}", "{}", path)

    def _registered(self):
        from api.main import app
        return {(m, self._shape(r.path))
                for r in app.routes for m in getattr(r, "methods", set())}

    def _documented(self):
        text = open(self.SPEC, encoding="utf-8").read()
        section = text.split("## 3. Endpoint index", 1)[1]
        rows = re.findall(r"^\| \*\*R\d\*\* \| (GET|PUT|DELETE) \| `([^`]+)` \|", section, re.M)
        assert rows, "no R-numbered endpoints found in the spec's endpoint index"
        return {(m, self._shape("/api/v1" + p)) for m, p in rows}

    def test_every_documented_endpoint_is_registered(self):
        registered = self._registered()
        missing = sorted(self._documented() - registered)
        assert not missing, (
            "documented in the API spec but not served: %s" % ", ".join("%s %s" % x for x in missing))

    def test_the_spec_documents_nine_endpoints(self):
        assert len(self._documented()) == 9

    def test_the_comparison_is_not_vacuous(self):
        """If the heading or the table format changed, `_documented()` would silently return
        nothing and the test above would pass against an empty set."""
        assert len(self._registered()) > 9


class TestKeysStayOutOfPaths:
    def test_no_route_puts_a_raw_slot_key_in_the_path(self):
        """A slot key contains `|`, `:`, `,`, `*`, spaces and a 0x01 separator. The flowchart
        routes use the base64url token instead, whose alphabet needs no escaping."""
        from api.main import app
        review = [r.path for r in app.routes
                  if "/overrides" in r.path or "/flowcharts/" in r.path]
        assert review
        for path in review:
            for param in re.findall(r"\{(\w+)\}", path):
                assert param in ("project_id", "version_id", "flowchart_token"), (
                    "%s puts %r in a path segment" % (path, param))
