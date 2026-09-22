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
        rows = re.findall(r"^\| \*\*R\d+\*\* \| (GET|PUT|DELETE) \| `([^`]+)` \|", section, re.M)
        assert rows, "no R-numbered endpoints found in the spec's endpoint index"
        return {(m, self._shape("/api/v1" + p)) for m, p in rows}

    def test_every_documented_endpoint_is_registered(self):
        registered = self._registered()
        missing = sorted(self._documented() - registered)
        assert not missing, (
            "documented in the API spec but not served: %s" % ", ".join("%s %s" % x for x in missing))

    def test_the_spec_documents_eleven_endpoints(self):
        """Was `== 9`, with an `R\\d` matcher that silently stopped at R9 -- "R10" matched "R1"
        and then failed on the literal `**`. So the newest endpoint was the one nobody compared."""
        assert len(self._documented()) == 11

    def test_every_r_number_in_the_index_is_matched(self):
        """Guards the class of bug above: if a row is in the table but the matcher cannot read
        it, the comparison quietly shrinks instead of failing.

        The section boundary is the next heading, not `---` -- a markdown table's separator row
        is `|---|---|`, so splitting on `---` stops inside the table being counted.
        """
        text = open(self.SPEC, encoding="utf-8").read()
        section = text.split("## 3. Endpoint index", 1)[1].split("\n## ", 1)[0]
        assert len(re.findall(r"^\| \*\*R\d+\*\*", section, re.M)) == len(self._documented())

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


class TestTheSpecDocumentsTheRealWireFormat:
    """The spec is what a UI engineer builds against, so a field name in it is a promise.

    It documented camelCase request bodies (`{"slotKind": …}`) and camelCase query parameters
    (`?slotKind=`). The server takes neither: the request models are plain pydantic, so the wire
    names are the Python field names, and every one of those calls would have returned 422. The
    whole platform API is snake_case in and camelCase out; the review routes were never the
    exception, only the documentation was.

    Nothing could catch that -- the route comparison beside this checks methods and paths, and the
    HTTP tests send the correct snake_case because they were written from the code.
    """

    SPEC = TestTheDocumentedContractExists.SPEC

    @staticmethod
    def _request_models():
        from api.routes import text_overrides as t
        return {"UpdateSlotRequest": t.UpdateSlotRequest,
                "UpdateFlowchartRequest": t.UpdateFlowchartRequest,
                "UpdateBehaviourRequest": t.UpdateBehaviourRequest}

    def _spec(self):
        return open(self.SPEC, encoding="utf-8").read()

    def test_every_request_field_is_documented_by_its_wire_name(self):
        text = self._spec()
        missing = []
        for name, model in self._request_models().items():
            for field in model.model_fields:
                if ("`%s`" % field) not in text:
                    missing.append("%s.%s" % (name, field))
        assert not missing, (
            "these request-body fields are not in the API spec under the name the server "
            "actually accepts: %s" % ", ".join(missing))

    def _request_examples(self):
        """Every JSON block that follows a `**Request body**` heading, parsed.

        Searching the whole document for camelCase would be wrong: RESPONSE examples are
        camelCase and correct. Only the request examples make a promise the server can break.
        """
        text = self._spec()
        out = []
        for chunk in text.split("**Request body**")[1:]:
            block = re.search(r"```json\n(.*?)```", chunk, re.S)
            if block:
                out.append(json.loads(block.group(1)))
        return out

    def test_every_request_example_parses_and_matches_a_real_model(self):
        """THE MISTAKE THIS CLASS EXISTS FOR. The spec showed `{"slotKind": …, "slotKey": …}`
        and `{"functionId": …, "externalCallerId": …}`. The server accepts neither, so every
        write a UI built from this document would have returned 422."""
        examples = self._request_examples()
        assert len(examples) == 3, (
            "expected one request example each for R3, R6 and R8; found %d" % len(examples))

        shapes = {name: set(m.model_fields) for name, m in self._request_models().items()}
        for body in examples:
            keys = set(body)
            assert keys in shapes.values(), (
                "this request example matches no request model: %s.\n"
                "The server accepts one of: %s"
                % (sorted(keys), " | ".join(sorted(str(sorted(v)) for v in shapes.values()))))

    def test_each_model_is_shown_exactly_once(self):
        """So a model cannot go undocumented while another is shown twice and the count passes."""
        shapes = {name: frozenset(m.model_fields) for name, m in self._request_models().items()}
        shown = [frozenset(b) for b in self._request_examples()]
        assert sorted(shown, key=sorted) == sorted(shapes.values(), key=sorted)

    def test_the_query_parameters_are_documented_in_snake_case(self):
        text = self._spec()
        assert "?slot_kind=" in text or "`slot_kind`" in text
        assert "?slotKind=" not in text and "?slotKey=" not in text

    def test_the_response_fields_stay_camel_case(self):
        """The other half of the same promise -- responses are hand-built camelCase, and a spec
        that 'corrected' them to snake_case would break every reader instead."""
        text = self._spec()
        for expected in ("`slotKind`", "`slotKey`", "`humanText`", "`llmText`", "`isOrphaned`"):
            assert expected in text

    def test_the_check_would_notice_a_new_field(self):
        """Not vacuous: a field nobody documented must fail, so add a fake one and confirm."""
        text = self._spec()
        assert "`definitely_not_a_real_field`" not in text


class TestSwaggerNamesTheEndpointsTheWayTheSpecDoes:
    """A tester works from the spec (or a checklist) that says "R3", and then looks at Swagger.

    FastAPI's default summary is the function name prettified -- "Update Slot", "Get Slot" --
    which gives no way to tell which row of the list is which R-number. Three of the ten sit on
    the same path and differ only by method, so the path does not disambiguate them either.
    """

    SPEC = TestTheDocumentedContractExists.SPEC

    def _operations(self):
        from api.main import app
        spec = app.openapi()
        out = {}
        for path, ops in spec["paths"].items():
            for method, op in ops.items():
                if "review" in (op.get("tags") or []):
                    out[(method.upper(), path)] = op
        return out

    def test_all_eleven_are_published(self):
        assert len(self._operations()) == 11

    def test_every_one_is_named_by_its_r_number(self):
        bad = {k: op.get("summary") for k, op in self._operations().items()
               if not re.match(r"^R\d+ - ", op.get("summary") or "")}
        assert not bad, "these operations do not name their R-number in Swagger: %s" % bad

    def test_the_r_numbers_match_the_spec_exactly(self):
        """Not just well-formed -- the same set the spec's endpoint index lists, so a new
        endpoint cannot be published under a number the spec does not have, or vice versa."""
        from_swagger = {re.match(r"^(R\d+) - ", op["summary"]).group(1)
                        for op in self._operations().values()}
        index = open(self.SPEC, encoding="utf-8").read().split("## 3. Endpoint index", 1)[1]
        from_spec = set(re.findall(r"^\| \*\*(R\d+)\*\* \|", index, re.M))
        assert from_swagger == from_spec, (
            "Swagger and the spec disagree: only in Swagger %s, only in the spec %s"
            % (sorted(from_swagger - from_spec), sorted(from_spec - from_swagger)))

    def test_each_number_is_used_once(self):
        summaries = [op["summary"].split(" - ")[0] for op in self._operations().values()]
        assert len(set(summaries)) == len(summaries), "an R-number is reused: %s" % summaries

    def test_they_carry_the_bearer_scheme(self):
        """Without it Swagger shows no Authorize button, and every Try-it-out returns 401."""
        for key, op in self._operations().items():
            assert op.get("security"), "%s %s has no security scheme, so Swagger cannot send a token" % key


class TestSwaggerOffersTheValidSlotKinds:
    """`slot_kind` was a free-text box, and "what do I put here?" is not a question a reference
    document should have to answer.

    It is an Enum built FROM `slot.ALL_KINDS`, so Swagger renders a dropdown and an eighth kind
    appears there the moment it is added -- a hand-written copy in the router would be a second
    list of the editable kinds, and the first one to fall behind would be this one.
    """

    def _spec(self):
        from api.main import app
        return app.openapi()

    def test_the_dropdown_is_exactly_the_canonical_list(self):
        published = self._spec()["components"]["schemas"]["SlotKind"]["enum"]
        assert published == list(slot.ALL_KINDS), (
            "Swagger offers %s but the editable kinds are %s" % (published, list(slot.ALL_KINDS)))

    def test_every_endpoint_that_takes_a_kind_uses_it(self):
        """A single endpoint left as a free string is the one somebody will mistype into."""
        spec = self._spec()
        loose = []
        for path, ops in spec["paths"].items():
            for method, op in ops.items():
                if "review" not in (op.get("tags") or []):
                    continue
                for prm in op.get("parameters", []):
                    if prm["name"] != "slot_kind":
                        continue
                    if "SlotKind" not in json.dumps(prm.get("schema", {})):
                        loose.append("%s %s" % (method.upper(), path))
        assert not loose, "slot_kind is still a free string on: %s" % loose

    def test_the_request_body_uses_it_too(self):
        body = self._spec()["components"]["schemas"]["UpdateSlotRequest"]["properties"]["slot_kind"]
        assert "SlotKind" in json.dumps(body)

    def test_an_invalid_kind_is_refused_by_validation(self, client=None):
        """422 naming the allowed values, rather than a 404 from deep in the service."""
        from fastapi.testclient import TestClient
        from api.main import app
        with TestClient(app) as c:
            r = c.get("/api/v1/projects/p1/versions/v1/overrides?slot_kind=notAKind")
        assert r.status_code in (401, 422), r.status_code
