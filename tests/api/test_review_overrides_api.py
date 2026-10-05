"""The Review & Update endpoints, driven over HTTP.

Everything beneath these routes is covered by `tests/unit/test_review_*`; what those cannot see is
the part that only exists at request time — auth, status codes, payload shapes, and whether the
handler can actually reach a model repository.

That last one is not hypothetical. Writing these tests is what found two defects the unit tests
could not:

  * the handler built a `ModelAccess` with no repository, and an API process has no "current run",
    so `model_repo.repository()` raised and every slot update was a 500;
  * `ModelAccess.save()` wrote through `DbRepository.write`, which only BUFFERS — nothing reached
    the database until a `flush` that never came, so a save returned 200 and stored nothing.

Contract: `docs/spec/REVIEW_UPDATE_API_SPEC.md`.
"""
import datetime
import json
import os
import sys

import pytest
from sqlalchemy import create_engine, insert, select
from sqlalchemy.pool import StaticPool

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (PROJECT_ROOT, os.path.join(PROJECT_ROOT, "engine"),
           os.path.join(PROJECT_ROOT, "engine", "flowchart")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from api.db.postgres import schema as s

PROJECT = "p1"                    # alice is admin, bob a developer — both active members
VERSION = "rv-1"
FID = "Sample-Core|Core|ns::doThing|void"
CALLER = "App|AppMain|ns::start|void"
BASE = "/api/v1/projects/%s/versions/%s" % (PROJECT, VERSION)


def _cfg(*ids):
    return {"entry": ids[0], "exits": [ids[-1]],
            "nodes": [{"id": i, "type": "ACTION", "label": "llm " + i, "rawCode": "code",
                       "line": 1, "endLine": 1} for i in ids],
            "edges": [{"source": a, "target": b, "label": None} for a, b in zip(ids, ids[1:])]}


@pytest.fixture
def review_db(monkeypatch):
    """A SQLite database standing in for Postgres, with a version, a model and Phase-3 output.

    `core.db.get_engine` is patched rather than the route's own helper, because the handler is not
    the only thing that reaches for it: `DbRepository` does too, and a test that patched only the
    route would have missed the repository defect entirely.
    """
    from core import model_store

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    s.metadata.create_all(engine)
    now = datetime.datetime.now(datetime.timezone.utc)
    with engine.begin() as cx:
        cx.execute(insert(s.projects).values(id=PROJECT, name="p1", created_at=now))
        cx.execute(insert(s.versions).values(id=VERSION, project_id=PROJECT, version="v1",
                                             created_at=now))
        model_store.persist_model(
            cx, PROJECT, VERSION,
            functions={FID: {"qualifiedName": "ns::doThing", "description": "Does the thing.",
                             "behaviourInputName": "Input", "behaviourOutputName": "Output"}},
            globals={}, datadict={}, edges={"typeUsers": {}, "macroUsers": {}},
            hashes={}, units={}, components={}, summaries={})
        cx.execute(insert(s.version_output_files).values(
            version_id=VERSION, rel_path="Sample/flowcharts/Core.json", group_name="Sample",
            content=json.dumps([{"name": "ns::doThing", "functionKey": FID,
                                 "cfg": _cfg("n0", "n1", "n2"),
                                 "flowchart": "digraph G { generated }"}])))
        cx.execute(insert(s.version_output_files).values(
            version_id=VERSION, rel_path="Sample/behaviour_diagrams/_behaviour_pngs.json",
            group_name="Sample",
            content=json.dumps({"_docxRows": {"Sample-Core": {"Core": [
                {"currentFunctionId": FID, "externalCallerId": CALLER,
                 "externalUnitFunction": "AppMain - start", "pngPath": "x.png",
                 "behaviorDescription": ["start calls doThing"]}]}}})))

    import core.db as core_db
    monkeypatch.setattr(core_db, "get_engine", lambda *a, **k: engine)
    monkeypatch.setattr(core_db, "is_database_configured", lambda *a, **k: True)
    return engine


def _key(kind, entity=FID):
    from review import slot
    return slot.for_entity(kind, entity)


LABELS = "/flowcharts/labels"


def _read_labels(client, headers, flowchart_id=FID):
    """R7: a flowchart is named by its function id, in the query."""
    return client.get(BASE + LABELS, headers=headers, params={"flowchart_id": flowchart_id})


def _save_labels(client, headers, labels, flowchart_id=FID):
    """R8: the flowchart id travels in the body, beside the labels."""
    return client.put(BASE + LABELS, headers=headers,
                      json={"flowchart_id": flowchart_id, "labels": labels})


# ---------------------------------------------------------------------------
class TestAuth:
    def test_no_token_is_rejected(self, client, review_db):
        assert client.get(BASE + "/overrides").status_code == 401

    def test_a_member_may_read(self, client, review_db, dev_header):
        assert client.get(BASE + "/overrides", headers=dev_header).status_code == 200

    def test_a_member_may_write(self, client, review_db, dev_header):
        """`REQ-API-05`: members edit, not only admins."""
        r = client.put(BASE + "/overrides/slot", headers=dev_header,
                       json={"slot_kind": "description", "slot_key": FID, "text": "By bob."})
        assert r.status_code == 200, r.text

    def test_a_non_member_is_refused(self, client, review_db, dev_header):
        """bob (u2) is a member of p1 only. alice is an admin on BOTH p1 and p2, so she is the
        wrong user to prove this with -- the first version of this test used her and passed a
        200 as a 403."""
        r = client.get("/api/v1/projects/p2/versions/%s/overrides" % VERSION, headers=dev_header)
        assert r.status_code == 403

    def test_a_non_member_cannot_write_either(self, client, review_db, dev_header):
        r = client.put("/api/v1/projects/p2/versions/%s/overrides/slot" % VERSION,
                       headers=dev_header,
                       json={"slot_kind": "description", "slot_key": FID, "text": "Words."})
        assert r.status_code == 403


class TestUpdatingASlot:
    def test_a_description_is_saved_and_read_back(self, client, review_db, auth_header):
        r = client.put(BASE + "/overrides/slot", headers=auth_header,
                       json={"slot_kind": "description", "slot_key": FID,
                             "text": "Starts the pump and clears the fault flag."})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["humanText"] == "Starts the pump and clears the fault flag."
        assert body["llmText"] == "Does the thing."
        assert body["firstEdit"] is True

        got = client.get(BASE + "/overrides/slot", headers=auth_header,
                         params={"slot_kind": "description", "slot_key": FID})
        assert got.status_code == 200
        assert got.json()["humanText"] == "Starts the pump and clears the fault flag."

    def test_the_model_really_moved(self, client, review_db, auth_header):
        """The defect this test exists for: `DbRepository.write` only buffers, so without a
        flush the request returned 200 and the model still held the LLM's words."""
        client.put(BASE + "/overrides/slot", headers=auth_header,
                   json={"slot_kind": "description", "slot_key": FID, "text": "Persisted."})
        from core import model_store
        with review_db.connect() as cx:
            functions = model_store.load_functions(cx, VERSION)
        assert functions[FID]["description"] == "Persisted."

    def test_empty_text_is_422(self, client, review_db, auth_header):
        r = client.put(BASE + "/overrides/slot", headers=auth_header,
                       json={"slot_kind": "description", "slot_key": FID, "text": "   "})
        assert r.status_code == 422

    def test_a_text_longer_than_a_correction_can_be_is_422(self, client, review_db, auth_header):
        """A 5 MB "correction" was accepted (RF-10). The page caps one at 2,000 characters."""
        from api.routes.text_overrides import MAX_TEXT
        r = client.put(BASE + "/overrides/slot", headers=auth_header,
                       json={"slot_kind": "description", "slot_key": FID,
                             "text": "x" * (MAX_TEXT + 1)})
        assert r.status_code == 422 and "text" in str(r.json())
        r = client.put(BASE + "/overrides/slot", headers=auth_header,
                       json={"slot_kind": "description", "slot_key": FID,
                             "text": "Within the limit. " * 100})
        assert r.status_code == 200, r.text

    def test_an_unreachable_database_does_not_say_why_to_the_caller(self, monkeypatch):
        """The driver's own message is for the server log (RF-9)."""
        import pytest as _pytest
        from fastapi import HTTPException
        from api.routes import text_overrides as to
        import core.db as core_db
        monkeypatch.setattr(core_db, "is_database_configured", lambda: True)

        def down():
            raise RuntimeError("connection to server at 10.0.0.5 port 5432 failed: password for "
                               "user analyzer")
        monkeypatch.setattr(core_db, "get_engine", down)
        with _pytest.raises(HTTPException) as exc:
            to._connection()
        assert exc.value.status_code == 503 and "10.0.0.5" not in exc.value.detail

    def test_a_connection_refused_at_connect_does_not_say_why_either(
            self, review_db, auth_header, monkeypatch):
        """The engine is made without a connection; the server is reached at `.connect()`,
        outside `_connection()`'s guard. The driver's text (host, port, user) went to the caller
        through the 500 handler's `str(exc)` (RF-9, second half)."""
        from fastapi.testclient import TestClient
        from sqlalchemy import exc as sa_exc
        from api.main import app
        from api.routes import text_overrides as to

        class Down:
            def connect(self):
                raise sa_exc.OperationalError(
                    "SELECT 1", {}, Exception("connection to server at 10.0.0.5 port 5432 "
                                              "failed: timeout expired"))
            begin = connect

        monkeypatch.setattr(to, "_connection", lambda: Down())
        raw = TestClient(app, raise_server_exceptions=False)
        r = raw.get(BASE + "/overrides/slot", headers=auth_header,
                    params={"slot_kind": "description", "slot_key": FID})
        assert r.status_code == 503, r.text
        assert "10.0.0.5" not in r.text and "SELECT" not in r.text
        assert r.json()["error"]["code"] == "DATABASE_UNAVAILABLE"

    def test_any_other_database_error_is_a_500_without_its_sql(
            self, review_db, auth_header, monkeypatch):
        from fastapi.testclient import TestClient
        from sqlalchemy import exc as sa_exc
        from api.main import app
        from api.routes import text_overrides as to

        class Broken:
            def connect(self):
                raise sa_exc.ProgrammingError(
                    "SELECT secret_column FROM versions", {"id": "ver1"},
                    Exception("column secret_column does not exist"))
            begin = connect

        monkeypatch.setattr(to, "_connection", lambda: Broken())
        raw = TestClient(app, raise_server_exceptions=False)
        r = raw.get(BASE + "/overrides/slot", headers=auth_header,
                    params={"slot_kind": "description", "slot_key": FID})
        assert r.status_code == 500, r.text
        assert "secret_column" not in r.text

    def test_an_unknown_slot_is_404(self, client, review_db, auth_header):
        r = client.put(BASE + "/overrides/slot", headers=auth_header,
                       json={"slot_kind": "description", "slot_key": "Nope|Nope|gone|",
                             "text": "Words."})
        assert r.status_code == 404

    def test_a_node_label_through_this_route_is_501(self, client, review_db, auth_header):
        """It has no model field; R8 is its route. A 501 says so instead of pretending -- and
        names R8, its path and what to send it, read from the key."""
        from review import slot
        r = client.put(BASE + "/overrides/slot", headers=auth_header,
                       json={"slot_kind": slot.NODE_LABEL,
                             "slot_key": slot.for_node(FID, "n1"), "text": "Words."})
        assert r.status_code == 501
        detail = r.json()["detail"]
        assert "R8: PUT " + BASE + "/flowcharts/labels" in detail
        assert "flowchart_id %r" % FID in detail and "node 'n1'" in detail


class TestR3NamesTheRouteThatSavesABehaviourRow:
    """What a reviewer tried: R3 with `slot_kind: behaviourDescription`. R3 offers the kind --
    its `slot_kind` is the one list of seven that R2, R4 and R5 take -- but a Dynamic Behaviour
    row is saved with R6. The 501 used to explain only why ("its text lives in Phase-3 view
    output, not the model"); it now says which route, its path and the two ids R6 takes."""

    def _put(self, client, auth_header, key):
        from review import slot
        return client.put(BASE + "/overrides/slot", headers=auth_header,
                          json={"slot_kind": slot.BEHAVIOUR_DESCRIPTION, "slot_key": key,
                                "text": "start calls doThing\ndoThing returns"})

    def test_501_naming_r6_with_the_ids_from_the_key(self, client, review_db, auth_header):
        from review import slot
        r = self._put(client, auth_header, slot.for_behaviour_row(FID, CALLER))
        assert r.status_code == 501, r.text
        detail = r.json()["detail"]
        assert "R6: PUT " + BASE + "/overrides/behaviour" in detail
        assert "function_id %r" % FID in detail
        assert "external_caller_id %r" % CALLER in detail
        assert "bullets" in detail

    def test_nothing_is_saved(self, client, review_db, auth_header):
        from review import slot
        self._put(client, auth_header, slot.for_behaviour_row(FID, CALLER))
        assert client.get(BASE + "/overrides", headers=auth_header).json()["total"] == 0

    def test_the_key_as_swagger_shows_it_is_read_too(self, client, review_db, auth_header):
        r = self._put(client, auth_header, FID + "\\u0001" + CALLER)
        assert r.status_code == 501
        assert "external_caller_id %r" % CALLER in r.json()["detail"]

    def test_a_malformed_key_still_names_the_route(self, client, review_db, auth_header):
        """The route is the answer whatever the key; the ids then come from R11."""
        r = self._put(client, auth_header, "not a behaviour key")
        assert r.status_code == 501
        detail = r.json()["detail"]
        assert "R6: PUT " + BASE + "/overrides/behaviour" in detail
        assert "from R11" in detail

    def test_r6_then_saves_it(self, client, review_db, auth_header):
        """The body the message describes is one R6 takes."""
        r = client.put(BASE + "/overrides/behaviour", headers=auth_header,
                       json={"function_id": FID, "external_caller_id": CALLER,
                             "bullets": ["start calls doThing", "doThing returns"]})
        assert r.status_code == 200, r.text

    def test_the_route_says_so_in_swagger(self):
        from api.routes.text_overrides import update_slot
        assert "saved with R6" in update_slot.__doc__ and "with R8" in update_slot.__doc__

    def test_a_slot_nobody_corrected_reads_as_uncorrected(self, client, review_db, auth_header):
        """R2 reads a SLOT, not a correction (`REQ-API-02`): a 404 here used to mean "not
        corrected yet", which a client had to treat as success."""
        r = client.get(BASE + "/overrides/slot", headers=auth_header,
                       params={"slot_kind": "description", "slot_key": FID})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["text"] == body["llmText"] == "Does the thing."
        assert body["isOverridden"] is False and body["humanText"] is None
        assert body["canUndo"] is False

    def test_a_slot_not_in_the_version_is_404(self, client, review_db, auth_header):
        r = client.get(BASE + "/overrides/slot", headers=auth_header,
                       params={"slot_kind": "description", "slot_key": "No|Such|fn|"})
        assert r.status_code == 404 and "R11" in r.json()["detail"]


class TestTheOverlayList:
    def test_it_is_empty_before_anything_is_corrected(self, client, review_db, auth_header):
        body = client.get(BASE + "/overrides", headers=auth_header).json()
        assert body == {"overrides": [], "total": 0, "limit": 200, "offset": 0}

    def test_it_lists_a_correction(self, client, review_db, auth_header):
        client.put(BASE + "/overrides/slot", headers=auth_header,
                   json={"slot_kind": "description", "slot_key": FID, "text": "Corrected."})
        body = client.get(BASE + "/overrides", headers=auth_header).json()
        assert body["total"] == 1
        assert body["overrides"][0]["slotKey"] == FID

    def test_it_filters_by_kind(self, client, review_db, auth_header):
        client.put(BASE + "/overrides/slot", headers=auth_header,
                   json={"slot_kind": "description", "slot_key": FID, "text": "Corrected."})
        body = client.get(BASE + "/overrides", headers=auth_header,
                          params={"slot_kind": "nodeLabel"}).json()
        assert body["overrides"] == []

    def test_an_oversized_page_is_rejected_by_validation(self, client, review_db, auth_header):
        r = client.get(BASE + "/overrides", headers=auth_header, params={"limit": 10 ** 6})
        assert r.status_code == 422


class TestFlowchartLabels:
    def test_the_labels_come_back(self, client, review_db, auth_header):
        r = _read_labels(client, auth_header)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["flowchartId"] == FID
        assert [l["nodeId"] for l in body["labels"]] == ["n0", "n1", "n2"]
        assert all(l["isOverridden"] is False for l in body["labels"])

    def test_a_save_applies_and_shows_up(self, client, review_db, auth_header):
        """R8 answers with each saved node as it now is -- it used to name the nodes and say
        nothing about their text."""
        r = _save_labels(client, auth_header, {"n1": "Check the write-protect flag"})
        assert r.status_code == 200, r.text
        (saved,) = r.json()["labels"]
        assert saved["nodeId"] == "n1" and saved["slotKind"] == "nodeLabel"
        assert saved["text"] == saved["humanText"] == "Check the write-protect flag"
        assert saved["previousText"] == saved["llmText"] == "llm n1"
        assert saved["firstEdit"] is True and saved["isOverridden"] is True
        assert "slotShape" not in r.json() and "applied" not in r.json()

        body = _read_labels(client, auth_header).json()
        n1 = next(l for l in body["labels"] if l["nodeId"] == "n1")
        assert n1["text"] == "Check the write-protect flag"
        assert n1["isOverridden"] is True
        assert n1["llmText"] == "llm n1"

    def test_several_labels_in_one_call(self, client, review_db, auth_header):
        r = _save_labels(client, auth_header, {"n0": "Begin", "n2": "Finish"})
        assert r.status_code == 200
        assert [(n["nodeId"], n["text"]) for n in r.json()["labels"]] == [("n0", "Begin"),
                                                                         ("n2", "Finish")]

    def test_a_node_that_does_not_exist_fails_the_whole_call(self, client, review_db,
                                                             auth_header):
        r = _save_labels(client, auth_header, {"n1": "Good", "n99": "Nowhere"})
        assert r.status_code == 404
        assert "n99" in r.json()["detail"]
        assert client.get(BASE + "/overrides", headers=auth_header).json()["total"] == 0

    def test_empty_label_text_is_422(self, client, review_db, auth_header):
        r = _save_labels(client, auth_header, {"n1": "  "})
        assert r.status_code == 422

    def test_the_flowchart_id_is_required(self, client, review_db, auth_header):
        assert client.get(BASE + LABELS, headers=auth_header).status_code == 422
        assert client.put(BASE + LABELS, headers=auth_header,
                          json={"labels": {"n1": "x"}}).status_code == 422

    def test_an_unknown_flowchart_is_404(self, client, review_db, auth_header):
        assert _read_labels(client, auth_header, "No|Such|fn|").status_code == 404
        assert _save_labels(client, auth_header, {"n1": "x"}, "No|Such|fn|").status_code == 404


class TestALabelSaveRedrawsTheWebPicture:
    """The web page shows a flowchart only when its SVG was drawn from the stored DOT, so R8 and a
    label's R4 redraw it once the save has committed (`review.rerender.draw_web_svgs`)."""

    @pytest.fixture
    def redraws(self, monkeypatch, tmp_path):
        import review.rerender as rerender
        from api.services import doc_render
        calls = []
        monkeypatch.setattr(doc_render, "commit_output_root", lambda *_a, **_k: tmp_path)
        monkeypatch.setattr(rerender, "draw_web_svgs", lambda _cx, vid, fid, out, _root: (
            calls.append((vid, fid, out)) or {}))
        return calls

    def test_r8_redraws_the_corrected_chart(self, client, review_db, auth_header, redraws,
                                            tmp_path):
        assert _save_labels(client, auth_header, {"n1": "Checked."}).status_code == 200
        assert redraws == [(VERSION, FID, str(tmp_path))]

    def test_undoing_a_label_redraws_it_too(self, client, review_db, auth_header, redraws):
        _save_labels(client, auth_header, {"n1": "Checked."})
        n1 = next(l for l in _read_labels(client, auth_header).json()["labels"]
                  if l["nodeId"] == "n1")
        r = client.delete(BASE + "/overrides/slot", headers=auth_header,
                          params={"slot_kind": "nodeLabel", "slot_key": n1["slotKey"]})
        assert r.status_code == 200, r.text
        assert [fid for _vid, fid, _out in redraws] == [FID, FID]

    def test_a_refused_save_draws_nothing(self, client, review_db, auth_header, redraws):
        assert _save_labels(client, auth_header, {"n99": "Nowhere"}).status_code == 404
        assert redraws == []

    def test_a_picture_that_cannot_be_drawn_does_not_fail_the_save(
            self, client, review_db, auth_header, monkeypatch, tmp_path):
        """The correction is stored either way; the next re-export draws the picture."""
        import review.rerender as rerender
        from api.services import doc_render
        monkeypatch.setattr(doc_render, "commit_output_root", lambda *_a, **_k: tmp_path)

        def no_node(*_a, **_k):
            raise RuntimeError("node not found")
        monkeypatch.setattr(rerender, "draw_web_svgs", no_node)
        r = _save_labels(client, auth_header, {"n1": "Checked."})
        assert r.status_code == 200, r.text
        assert r.json()["labels"][0]["text"] == "Checked."


class TestASaveReDerivesTheSwe4Specs:
    """REQ-CS-04 over HTTP. A version with SWE.4 output -- one generated from the CLI -- has the
    saved component's specs and UT export rebuilt from the stored rows, in the save's request.
    `review_db` has none, which is every web-app version: there the save re-derives nothing and
    `viewsDerived` stays empty (the tests above)."""

    CFG = {"entry": "n0", "exits": ["n4"],
           "nodes": [{"id": i, "type": t, "label": lab, "rawCode": raw, "line": 1, "endLine": 1}
                     for i, t, lab, raw in (
                         ("n0", "START", "Start: doThing", ""),
                         ("n1", "DECISION", "Check: ready?", "if (ready)"),
                         ("n2", "RETURN", "Return 1", "return 1;"),
                         ("n3", "RETURN", "Return 0", "return 0;"),
                         ("n4", "END", "End", ""))],
           "edges": [{"source": a, "target": b, "label": lab} for a, b, lab in (
               ("n0", "n1", None), ("n1", "n2", "Yes"), ("n1", "n3", "No"),
               ("n2", "n4", None), ("n3", "n4", None))]}

    @pytest.fixture
    def swe4_db(self, review_db):
        from sqlalchemy import update
        from core import model_store
        from review import export_guard as g
        from views import ut_export
        from views.test_specs import build
        from views.test_steps import cfgs_from_entries

        fn = {"qualifiedName": "ns::doThing", "visibility": "public", "returnType": "int",
              "location": {"file": "Core.cpp", "line": 1}, "parameters": [], "callsIds": [],
              "calledByIds": [], "interfaceId": "IF_CORE_01", "description": "Does the thing."}
        units = {"Sample-Core|Core": {"name": "Core", "fileName": "Core.cpp",
                                      "functionIds": [FID]}}
        components = {"Sample-Core": {"units": ["Sample-Core|Core"]}}
        entry = {"name": "ns::doThing", "functionKey": FID, "cfg": self.CFG,
                 "flowchart": "digraph G { generated }"}
        context = {"allowedComponents": ["Sample-Core"], "layerComponents": None,
                   "views": {"functionTestSpecs": True, "dynamicBehaviourSpecs": True},
                   "layers": {}}
        config = {"views": context["views"], "layers": {},
                  "_analyzerAllowedComponents": ["Sample-Core"]}
        specs = build({"functions": {FID: fn}, "globalVariables": {}, "units": units,
                       "components": components, "dataDictionary": {}},
                      config, cfgs_from_entries([[entry]]), verbose=False)
        at = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        with review_db.begin() as cx:
            model_store.clear_version(cx, VERSION)
            model_store.persist_model(cx, PROJECT, VERSION, functions={FID: fn}, globals={},
                                      datadict={}, edges={"typeUsers": {}, "macroUsers": {}},
                                      hashes={}, units=units, components=components,
                                      summaries={})
            cx.execute(update(s.version_output_files)
                       .where(s.version_output_files.c.rel_path == "Sample/flowcharts/Core.json")
                       .values(content=json.dumps([entry])))
            for path, content in {
                    "Sample/test_specs.json": json.dumps(specs, indent=2),
                    "Sample/ut_export.json": json.dumps(ut_export.build(specs, {}, config),
                                                        indent=2),
                    "Sample/_derivations.json": g.record_text({"views": {
                        view: {"at": at.isoformat(), "components": ["sample-core"],
                               "context": context}
                        for view in ("testSpecs", "utExport")}})}.items():
                cx.execute(insert(s.version_output_files).values(
                    version_id=VERSION, rel_path=path, content=content, group_name="Sample"))
        return review_db

    @staticmethod
    def _spec(db):
        with db.connect() as cx:
            doc = json.loads(cx.execute(
                select(s.version_output_files.c.content)
                .where(s.version_output_files.c.rel_path == "Sample/test_specs.json")).scalar())
        return doc["Sample-Core|Core"]["functions"][0]

    def test_the_fixture_transcribes_the_decision(self, swe4_db):
        assert "Check whether ready." in [st["text"] for st in self._spec(swe4_db)["testSteps"]]

    def test_a_label_save_rebuilds_the_test_steps(self, client, swe4_db, auth_header):
        r = _save_labels(client, auth_header, {"n1": "Check: the device is ready?"})
        assert r.status_code == 200, r.text
        assert r.json()["viewsDerived"] == ["testSpecs", "utExport"]
        steps = [st["text"] for st in self._spec(swe4_db)["testSteps"]]
        assert "Check whether the device is ready." in steps

    def test_a_description_save_rebuilds_the_copy_in_the_spec(self, client, swe4_db,
                                                              auth_header):
        r = client.put(BASE + "/overrides/slot", headers=auth_header,
                       json={"slot_kind": "description", "slot_key": FID,
                             "text": "Reports whether the device is ready."})
        assert r.status_code == 200, r.text
        assert r.json()["viewsDerived"] == ["testSpecs", "utExport"]
        assert self._spec(swe4_db)["description"] == "Reports whether the device is ready."

    def test_an_undo_rebuilds_them_too(self, client, swe4_db, auth_header):
        _save_labels(client, auth_header, {"n1": "Check: the device is ready?"})
        from review import slot
        r = client.delete(BASE + "/overrides/slot", headers=auth_header,
                          params={"slot_kind": "nodeLabel",
                                  "slot_key": slot.for_node(FID, "n1")})
        assert r.status_code == 200, r.text
        assert "Check whether ready." in [st["text"] for st in self._spec(swe4_db)["testSteps"]]


class TestBehaviourRow:
    def test_the_bullet_list_round_trips(self, client, review_db, auth_header):
        r = client.put(BASE + "/overrides/behaviour", headers=auth_header,
                       json={"function_id": FID, "external_caller_id": CALLER,
                             "bullets": ["start calls doThing to prime the pump",
                                         "doThing returns the pump state"]})
        assert r.status_code == 200, r.text
        assert r.json()["bullets"] == ["start calls doThing to prime the pump",
                                       "doThing returns the pump state"]
        assert r.json()["llmText"] == "start calls doThing"

    def test_the_bullets_together_are_one_text_and_have_its_limit(
            self, client, review_db, auth_header):
        """Each bullet within the limit, 500 of them a 5 MB cell (RF-10)."""
        from api.routes.text_overrides import MAX_TEXT
        r = client.put(BASE + "/overrides/behaviour", headers=auth_header,
                       json={"function_id": FID, "external_caller_id": CALLER,
                             "bullets": ["x" * (MAX_TEXT // 2)] * 3})
        assert r.status_code == 422 and "bullets" in r.text
        r = client.put(BASE + "/overrides/behaviour", headers=auth_header,
                       json={"function_id": FID, "external_caller_id": CALLER,
                             "bullets": ["x" * 100] * 10})
        assert r.status_code == 200, r.text

    def test_an_unknown_caller_is_404(self, client, review_db, auth_header):
        r = client.put(BASE + "/overrides/behaviour", headers=auth_header,
                       json={"function_id": FID, "external_caller_id": "No|Such|caller|",
                             "bullets": ["x"]})
        assert r.status_code == 404

    def test_an_empty_list_is_422(self, client, review_db, auth_header):
        r = client.put(BASE + "/overrides/behaviour", headers=auth_header,
                       json={"function_id": FID, "external_caller_id": CALLER, "bullets": []})
        assert r.status_code == 422


class TestANulCharacterIsRefused:
    """PostgreSQL cannot store U+0000 in text or JSONB: a save carrying one died there as a 500.
    SQLite -- every test here -- stored it, and the model and the DOCX carried it. Each save
    refuses it at the request, with a 422 whose `loc` names the field, and stores nothing."""

    CASES = {
        "r3 text": ("/overrides/slot", {"slot_kind": "description", "slot_key": FID,
                                        "text": "Starts the pump\u0000."}, ["body", "text"]),
        "r3 key": ("/overrides/slot", {"slot_kind": "description", "slot_key": FID + "\u0000",
                                       "text": "Words."}, ["body", "slot_key"]),
        "r6 bullet": ("/overrides/behaviour",
                      {"function_id": FID, "external_caller_id": CALLER,
                       "bullets": ["start calls doThing", "\u0000"]}, ["body", "bullets", 1]),
        "r6 function": ("/overrides/behaviour",
                        {"function_id": FID + "\u0000", "external_caller_id": CALLER,
                         "bullets": ["x"]}, ["body", "function_id"]),
        "r6 caller": ("/overrides/behaviour",
                      {"function_id": FID, "external_caller_id": "\u0000" + CALLER,
                       "bullets": ["x"]}, ["body", "external_caller_id"]),
        "r8 label": (LABELS, {"flowchart_id": FID, "labels": {"n1": "Check\u0000 it"}},
                     ["body", "labels", "n1"]),
        "r8 node id": (LABELS, {"flowchart_id": FID, "labels": {"n1\u0000": "Check it"}},
                       ["body", "labels", "n1\u0000", "[key]"]),
        "r8 flowchart": (LABELS, {"flowchart_id": FID + "\u0000", "labels": {"n1": "Check it"}},
                         ["body", "flowchart_id"]),
    }

    @staticmethod
    def _stored(engine):
        from core import model_store
        with engine.connect() as cx:
            return (cx.execute(select(s.text_overrides.c.slot_key)).fetchall(),
                    model_store.load_functions(cx, VERSION),
                    sorted(cx.execute(select(s.version_output_files.c.rel_path,
                                             s.version_output_files.c.content)).fetchall()))

    @pytest.mark.parametrize("case", sorted(CASES))
    def test_it_is_422_naming_the_field_and_nothing_is_stored(self, client, review_db,
                                                              auth_header, case):
        path, body, loc = self.CASES[case]
        before = self._stored(review_db)
        r = client.put(BASE + path, headers=auth_header, json=body)
        assert r.status_code == 422, r.text
        assert [e["loc"] for e in r.json()["detail"]] == [loc]
        assert "NUL" in r.json()["detail"][0]["msg"]
        after = self._stored(review_db)
        assert after == before
        assert after[0] == [], "a text_overrides row was written"

    def test_the_same_save_without_it_lands(self, client, review_db, auth_header):
        """The refusal is the character, not the field: the case above minus the NUL saves."""
        r = client.put(BASE + "/overrides/slot", headers=auth_header,
                       json={"slot_kind": "description", "slot_key": FID,
                             "text": "Starts the pump."})
        assert r.status_code == 200, r.text


class TestUndoAndHistory:
    def test_undo_restores_the_original_and_keeps_the_record(self, client, review_db,
                                                             auth_header):
        client.put(BASE + "/overrides/slot", headers=auth_header,
                   json={"slot_kind": "description", "slot_key": FID, "text": "Corrected."})
        r = client.delete(BASE + "/overrides/slot", headers=auth_header,
                          params={"slot_kind": "description", "slot_key": FID})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["text"] == body["humanText"] == body["llmText"] == "Does the thing."
        assert body["previousText"] == "Corrected."
        assert body["isOverridden"] is True and body["canUndo"] is False    # the record survives

        from core import model_store
        with review_db.connect() as cx:
            assert model_store.load_functions(cx, VERSION)[FID]["description"] == \
                "Does the thing."

    def test_undo_with_no_correction_is_409(self, client, review_db, auth_header):
        r = client.delete(BASE + "/overrides/slot", headers=auth_header,
                          params={"slot_kind": "description", "slot_key": FID})
        assert r.status_code == 409

    def test_history_lists_every_retained_edit(self, client, review_db, auth_header):
        for text in ("First.", "Second."):
            client.put(BASE + "/overrides/slot", headers=auth_header,
                       json={"slot_kind": "description", "slot_key": FID, "text": text})
        r = client.get(BASE + "/overrides/history", headers=auth_header,
                       params={"slot_kind": "description", "slot_key": FID})
        assert r.status_code == 200
        assert [h["humanText"] for h in r.json()["history"]] == ["First.", "Second."]


class TestExportReadiness:
    def test_a_version_nobody_corrected_is_not_stale(self, client, review_db, auth_header):
        r = client.get(BASE + "/export-readiness", headers=auth_header)
        assert r.status_code == 200
        assert r.json()["stale"] is False

    def test_a_correction_makes_it_stale(self, client, review_db, auth_header):
        """No derivation has been recorded for this version, and corrections exist -- absence of
        evidence counts as stale."""
        client.put(BASE + "/overrides/slot", headers=auth_header,
                   json={"slot_kind": "description", "slot_key": FID, "text": "Corrected."})
        body = client.get(BASE + "/export-readiness", headers=auth_header).json()
        assert body["stale"] is True
        assert body["overrideCount"] == 1

    def test_it_asks_about_every_document_the_version_has(self, client, review_db, auth_header,
                                                           monkeypatch):
        """A web run writes SWE.4 beside SWE.3, so R9 asks what the re-export writes
        (`pipeline_runner.export_doc_type`), not SWE.3 alone."""
        import review.export_guard as guard
        from api.services import pipeline_runner
        asked, real = [], guard.staleness
        monkeypatch.setattr(pipeline_runner, "export_doc_type", lambda db, pid, vid: "all")
        monkeypatch.setattr(guard, "staleness", lambda cx, vid, doc_types=None, component=None: (
            asked.append(doc_types) or real(cx, vid, doc_types, component=component)))
        r = client.get(BASE + "/export-readiness", headers=auth_header)
        assert r.status_code == 200
        assert asked == ["all"]

    def test_it_names_the_components_whose_documents_are_behind(self, client, review_db,
                                                                 auth_header, db, monkeypatch):
        """One version-wide `stale` marked every row "previous Word file" for one correction in
        one component."""
        from types import SimpleNamespace
        client.put(BASE + "/overrides/slot", headers=auth_header,
                   json={"slot_kind": "description", "slot_key": FID, "text": "Corrected."})
        docs = [SimpleNamespace(group="Sample-Core"), SimpleNamespace(group="Other")]
        monkeypatch.setattr(type(db.documents), "list_for_project",
                            lambda self, pid, version_id=None, per_page=20, **k: (docs, 2))
        body = client.get(BASE + "/export-readiness", headers=auth_header).json()
        assert body["stale"] is True and body["staleComponents"] == ["Sample-Core"]

    def test_nothing_is_behind_when_the_version_is_not_stale(self, client, review_db,
                                                             auth_header):
        body = client.get(BASE + "/export-readiness", headers=auth_header).json()
        assert body["staleComponents"] == []


class TestNoDatabase:
    def test_a_write_is_refused_rather_than_dropped(self, client, auth_header, monkeypatch):
        """Corrections live nowhere else. Accepting an edit that cannot be stored would be worse
        than refusing it."""
        import core.db as core_db
        monkeypatch.setattr(core_db, "is_database_configured", lambda *a, **k: False)
        r = client.put(BASE + "/overrides/slot", headers=auth_header,
                       json={"slot_kind": "description", "slot_key": FID, "text": "Words."})
        assert r.status_code == 503


class TestTheFlowchartEditorHasWhatItNeeds:
    """R7 is what a flowchart editor opens with, so anything the editor must send back has to
    come FROM it. A node's `slotKey` is `flowchartId + U+0001 + nodeId`, and `REQ-ID-01` says a
    key is built by the server and never by hand -- so omitting it left the UI with a rule it
    could not follow, and undo (R4) or history (R5) on a single label impossible.
    """

    def test_every_node_carries_its_own_slot_key(self, client, review_db, auth_header):
        r = _read_labels(client, auth_header)
        assert r.status_code == 200, r.text
        labels = r.json()["labels"]
        assert labels, "the fixture must have nodes"
        for n in labels:
            assert n.get("slotKey"), "node %s has no slotKey" % n["nodeId"]

    def test_the_key_is_the_one_the_server_would_build(self, client, review_db, auth_header):
        from review import slot as slot_mod
        body = _read_labels(client, auth_header).json()
        for n in body["labels"]:
            assert n["slotKey"] == slot_mod.for_node(body["flowchartId"], n["nodeId"])

    def test_that_key_works_for_undo_and_history(self, client, review_db, auth_header):
        """The point of returning it. Round-trip it through R8 -> R5 -> R4 untouched."""
        body = _read_labels(client, auth_header).json()
        node = body["labels"][0]
        assert _save_labels(client, auth_header, {node["nodeId"]: "Corrected here."}).status_code == 200

        h = client.get(BASE + "/overrides/history", headers=auth_header,
                       params={"slot_kind": "nodeLabel", "slot_key": node["slotKey"]})
        assert h.status_code == 200 and len(h.json()["history"]) == 1

        u = client.delete(BASE + "/overrides/slot", headers=auth_header,
                          params={"slot_kind": "nodeLabel", "slot_key": node["slotKey"]})
        assert u.status_code == 200 and u.json()["text"] == node["text"]


class TestTheEditorCanDrawTheCorrectedDiagram:
    """R7 carries the Graphviz DOT from the database. The PNG beside the document is a file on
    disk, redrawn only by the next re-export (`renderPending`), so a UI showing the PNG shows the
    OLD label after a save and after a reload. The DOT is rebuilt by R8 in the same request, so a
    UI that draws it shows the correction at once."""

    LABEL = "WP-flag-checked"      # one token: never wrapped onto two lines in the DOT

    def _dot(self, client, auth_header):
        r = _read_labels(client, auth_header)
        assert r.status_code == 200, r.text
        return r.json()["dot"]

    def test_the_diagram_comes_with_the_labels(self, client, review_db, auth_header):
        assert self._dot(client, auth_header) == "digraph G { generated }"

    def test_a_save_redraws_the_diagram_in_the_same_request(self, client, review_db,
                                                            auth_header):
        put = _save_labels(client, auth_header, {"n1": self.LABEL})
        assert put.status_code == 200, put.text
        assert put.json()["renderPending"] is True      # the PNG is still the old picture ...
        dot = self._dot(client, auth_header)
        assert self.LABEL in dot                        # ... but the diagram is already right
        assert dot.lstrip().startswith("digraph")

    def test_an_undo_takes_the_correction_back_out(self, client, review_db, auth_header):
        body = _read_labels(client, auth_header).json()
        key = next(n["slotKey"] for n in body["labels"] if n["nodeId"] == "n1")
        _save_labels(client, auth_header, {"n1": self.LABEL})
        assert client.delete(BASE + "/overrides/slot", headers=auth_header,
                             params={"slot_kind": "nodeLabel", "slot_key": key}).status_code == 200
        dot = self._dot(client, auth_header)
        assert self.LABEL not in dot
        assert "llm n1" in dot


class TestRenderPendingTellsTheTruth:
    def test_a_save_with_no_output_tree_reports_the_picture_as_owed(self, client, review_db,
                                                                    auth_header):
        """The API host has no output tree, so the text is corrected and the PNG is not. Saying
        otherwise made the UI show "image up to date" while the export blocked on that job."""
        r = _save_labels(client, auth_header, {"n1": "Check the write-protect flag"})
        assert r.status_code == 200, r.text
        assert r.json()["renderPending"] is True
        assert r.json()["renderJobs"]

    def test_it_agrees_with_export_readiness(self, client, review_db, auth_header):
        """Two answers to "is the picture current" that disagree is worse than either alone."""
        put = _save_labels(client, auth_header, {"n1": "Corrected."}).json()
        ready = client.get(BASE + "/export-readiness", headers=auth_header).json()
        assert put["renderPending"] is (ready["pendingRenders"] > 0)



class TestR7ReportsWhatIsInForce:
    """R7 follows the same rule as R11: `text` is what the picture carries, and `isOverridden`
    means a correction is IN FORCE. An orphan is kept but not applied, so it is not one."""

    def _get(self, client, auth_header, node="n1"):
        body = _read_labels(client, auth_header).json()
        return next(n for n in body["labels"] if n["nodeId"] == node)

    def test_a_live_correction_carries_its_human_text(self, client, review_db, auth_header):
        _save_labels(client, auth_header, {"n1": "Check the write-protect flag"})
        n = self._get(client, auth_header)
        assert n["isOverridden"] is True and n["isOrphaned"] is False
        assert n["text"] == n["humanText"] == "Check the write-protect flag"

    def test_an_orphan_is_not_in_force(self, client, review_db, auth_header):
        from review import slot
        with review_db.begin() as cx:
            cx.execute(insert(s.text_overrides).values(
                version_id=VERSION, slot_kind="nodeLabel", slot_key=slot.for_node(FID, "n1"),
                llm_text="old", human_text="Words for a graph that changed.", is_orphaned=True,
                updated_by="u1", updated_at=datetime.datetime.now(datetime.timezone.utc)))
        n = self._get(client, auth_header)
        assert n["isOverridden"] is False and n["isOrphaned"] is True
        assert n["humanText"] == "Words for a graph that changed.", "kept means visible"
        assert n["text"] != n["humanText"], "text is what the picture carries, not the orphan"


class TestR7SeesEveryCorrectionOnItsOwnFlowchart:
    """R7 used to page the WHOLE version's node corrections, newest 1,000 first, and then look
    this flowchart's nodes up in that page. On a version with more than a thousand node
    corrections, an older one on the flowchart being opened fell off the page, and its node was
    reported as never corrected -- `isOverridden: false`, `llmText: null` -- while the picture
    carried the correction.
    """

    def test_an_older_correction_survives_a_thousand_newer_ones(self, client, review_db,
                                                              auth_header):
        from review import slot
        assert _save_labels(client, auth_header, {"n1": "The oldest correction."}).status_code == 200

        later = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)
        with review_db.begin() as cx:
            cx.execute(insert(s.text_overrides), [
                {"version_id": VERSION, "slot_kind": "nodeLabel",
                 "slot_key": slot.for_node("Other|Unit|f%d|" % i, "n0"),
                 "llm_text": "x", "human_text": "y", "is_orphaned": False,
                 "updated_by": "u1", "updated_at": later}
                for i in range(1001)])

        body = _read_labels(client, auth_header).json()
        n1 = next(n for n in body["labels"] if n["nodeId"] == "n1")
        assert n1["isOverridden"] is True, (
            "a correction on THIS flowchart was lost behind 1,001 newer ones elsewhere")
        assert n1["humanText"] == "The oldest correction."



class TestKeysCopiedFromSwaggerWork:
    """The key exactly as a JSON viewer displays it -- `\\u0001` as six characters.

    Before: R4 answered 409 "has no override", R5 `200 []`, R2 404, all for a correction that
    existed, because the pasted key carried a backslash instead of the separator. Found by the
    first manual undo of a flowchart label in Swagger.
    """

    def _shown(self, client, auth_header, node="n1"):
        from review import slot as slot_mod
        r = _read_labels(client, auth_header)
        real = next(n["slotKey"] for n in r.json()["labels"] if n["nodeId"] == node)
        return real.replace(slot_mod.SEP, slot_mod.ESCAPED_SEP)

    def _correct(self, client, auth_header, node="n1"):
        assert _save_labels(client, auth_header, {node: "Corrected in Swagger."}).status_code == 200

    def test_r2_reads_it(self, client, review_db, auth_header):
        self._correct(client, auth_header)
        r = client.get(BASE + "/overrides/slot", headers=auth_header,
                       params={"slot_kind": "nodeLabel", "slot_key": self._shown(client, auth_header)})
        assert r.status_code == 200 and r.json()["humanText"] == "Corrected in Swagger."

    def test_r5_reads_its_history(self, client, review_db, auth_header):
        self._correct(client, auth_header)
        r = client.get(BASE + "/overrides/history", headers=auth_header,
                       params={"slot_kind": "nodeLabel", "slot_key": self._shown(client, auth_header)})
        assert r.status_code == 200 and len(r.json()["history"]) == 1

    def test_r4_undoes_it(self, client, review_db, auth_header):
        self._correct(client, auth_header)
        r = client.delete(BASE + "/overrides/slot", headers=auth_header,
                          params={"slot_kind": "nodeLabel", "slot_key": self._shown(client, auth_header)})
        assert r.status_code == 200 and r.json()["text"] == "llm n1"
        labels = _read_labels(client, auth_header).json()["labels"]
        assert next(n["text"] for n in labels if n["nodeId"] == "n1") == "llm n1"


class TestAFlowchartIdIsNotANodeKey:
    """Three endpoints used to report the same mistake three different wrong ways."""

    @pytest.mark.parametrize("method,path", [("get", "/overrides/slot"),
                                             ("get", "/overrides/history"),
                                             ("delete", "/overrides/slot")])
    def test_it_is_a_400_that_says_so(self, client, review_db, auth_header, method, path):
        r = getattr(client, method)(BASE + path, headers=auth_header,
                                    params={"slot_kind": "nodeLabel", "slot_key": FID})
        assert r.status_code == 400, r.text
        assert "flowchart id" in r.json()["detail"] and "R7" in r.json()["detail"]


class TestANodeKeyIsNotAFlowchartId:
    """The same mistake the other way round: one node's key sent where R7 and R8 want the whole
    flowchart. It carries the separator -- really, or as the `\\u0001` a JSON viewer displays."""

    @pytest.mark.parametrize("sep", ["\x01", "\\u0001"], ids=["real", "displayed"])
    def test_r7_says_so(self, client, review_db, auth_header, sep):
        r = _read_labels(client, auth_header, FID + sep + "n1")
        assert r.status_code == 400, r.text
        assert "one node's key" in r.json()["detail"] and FID in r.json()["detail"]

    @pytest.mark.parametrize("sep", ["\x01", "\\u0001"], ids=["real", "displayed"])
    def test_r8_says_so_and_saves_nothing(self, client, review_db, auth_header, sep):
        r = _save_labels(client, auth_header, {"n1": "x"}, FID + sep + "n1")
        assert r.status_code == 400, r.text
        assert "one node's key" in r.json()["detail"]
        assert client.get(BASE + "/overrides", headers=auth_header).json()["total"] == 0


class TestAFlowchartIdTravelsAsItIs:
    """A flowchart is named by its function id -- no second spelling of it. An id carries what a
    C++ signature carries: `::`, `+`, `&`, `*`, commas and spaces. A client encodes the query as
    it encodes any other (R2, R4 and R5 already carry keys that way), and R8's is JSON."""

    OP = "Sample-Core|Core|Vec::operator+=|const Vec &, int *"

    @pytest.fixture
    def op_db(self, review_db):
        with review_db.begin() as cx:
            cx.execute(insert(s.version_output_files).values(
                version_id=VERSION, rel_path="Sample/flowcharts/Vec.json", group_name="Sample",
                content=json.dumps([{"name": "Vec::operator+=", "functionKey": self.OP,
                                     "cfg": _cfg("m0", "m1"),
                                     "flowchart": "digraph G { generated }"}])))
        return review_db

    def test_r11_lists_it_as_it_is(self, client, op_db, auth_header):
        rows = client.get(BASE + "/slots", headers=auth_header,
                          params={"slot_kind": "nodeLabel"}).json()["slots"]
        assert self.OP in {r["flowchartId"] for r in rows}
        assert all("flowchartToken" not in r for r in rows)

    def test_r7_and_r8_take_it(self, client, op_db, auth_header):
        body = _read_labels(client, auth_header, self.OP).json()
        assert body["flowchartId"] == self.OP and "flowchartToken" not in body
        assert _save_labels(client, auth_header, {"m1": "Add the other vector"},
                            self.OP).status_code == 200
        m1 = next(n for n in _read_labels(client, auth_header, self.OP).json()["labels"]
                  if n["nodeId"] == "m1")
        assert m1["text"] == "Add the other vector" and m1["isOverridden"] is True

    def test_a_query_encoded_by_hand_works(self, client, op_db, auth_header):
        """What Swagger and a browser send: every reserved character percent-encoded."""
        from urllib.parse import quote
        r = client.get(BASE + LABELS + "?flowchart_id=" + quote(self.OP, safe=""),
                       headers=auth_header)
        assert r.status_code == 200, r.text
        assert r.json()["flowchartId"] == self.OP

    def test_undo_and_history_take_the_node_key_r7_returns(self, client, op_db, auth_header):
        _save_labels(client, auth_header, {"m1": "Add the other vector"}, self.OP)
        key = next(n["slotKey"] for n in _read_labels(client, auth_header, self.OP).json()["labels"]
                   if n["nodeId"] == "m1")
        q = {"slot_kind": "nodeLabel", "slot_key": key}
        hist = client.get(BASE + "/overrides/history", headers=auth_header, params=q).json()
        assert [h["humanText"] for h in hist["history"]] == ["Add the other vector"]
        assert client.delete(BASE + "/overrides/slot", headers=auth_header,
                             params=q).status_code == 200
        m1 = next(n for n in _read_labels(client, auth_header, self.OP).json()["labels"]
                  if n["nodeId"] == "m1")
        assert m1["text"] == "llm m1"


# ---------------------------------------------------------------------------
# The version in the path must be one of the project's own
# ---------------------------------------------------------------------------
def _every_route():
    """(label, method, path-after-the-version, request kwargs) -- R1 to R11, each with a minimal
    request it would otherwise accept."""
    q = {"slot_kind": "description", "slot_key": FID}
    return [
        ("R1", "get", "/overrides", {}),
        ("R2", "get", "/overrides/slot", {"params": q}),
        ("R3", "put", "/overrides/slot", {"json": {**q, "text": "x"}}),
        ("R4", "delete", "/overrides/slot", {"params": q}),
        ("R5", "get", "/overrides/history", {"params": q}),
        ("R6", "put", "/overrides/behaviour", {"json": {"function_id": FID,
                                                        "external_caller_id": CALLER,
                                                        "bullets": ["x"]}}),
        ("R7", "get", LABELS, {"params": {"flowchart_id": FID}}),
        ("R8", "put", LABELS, {"json": {"flowchart_id": FID, "labels": {"n1": "x"}}}),
        ("R9", "get", "/export-readiness", {}),
        ("R10", "get", "/regeneration-queue", {}),
        ("R11", "get", "/slots", {"params": {"slot_kind": "description"}}),
    ]


ROUTES = [pytest.param(m, p, kw, id=label) for label, m, p, kw in _every_route()]


class TestTheVersionMustBeTheProjectsOwn:
    """Every route is addressed /projects/{p}/versions/{v}, but reads and writes by version alone.

    Reported from a web-app run: R11 answered `total: 0` for every kind because the caller sent
    the version's TAG (`v1`) -- a run started from the web app is stored under a generated id --
    and an unknown id looked exactly like an empty version. Reproducing it showed the worse half:
    where some OTHER project had a version with that id, R11 answered with that project's slots.
    """

    @pytest.mark.parametrize("method,path,kw", ROUTES)
    def test_an_unknown_version_is_404(self, client, review_db, auth_header, method, path, kw):
        url = "/api/v1/projects/%s/versions/no-such-version%s" % (PROJECT, path)
        r = getattr(client, method)(url, headers=auth_header, **kw)
        assert r.status_code == 404, r.text
        assert "no version 'no-such-version'" in r.json()["detail"]

    @pytest.mark.parametrize("method,path,kw", ROUTES)
    def test_another_projects_version_is_404(self, client, review_db, auth_header,
                                             method, path, kw):
        """alice is an admin of p1 AND p2; the path decides which project is being read."""
        now = datetime.datetime.now(datetime.timezone.utc)
        with review_db.begin() as cx:
            cx.execute(insert(s.projects).values(id="p2", name="p2", created_at=now))
            cx.execute(insert(s.versions).values(id="rv-other", project_id="p2", version="v1",
                                                 created_at=now))
        url = "/api/v1/projects/%s/versions/rv-other%s" % (PROJECT, path)
        r = getattr(client, method)(url, headers=auth_header, **kw)
        assert r.status_code == 404, r.text

    def test_a_write_never_reaches_the_other_project(self, client, review_db, auth_header):
        now = datetime.datetime.now(datetime.timezone.utc)
        with review_db.begin() as cx:
            cx.execute(insert(s.projects).values(id="p2", name="p2", created_at=now))
            cx.execute(insert(s.versions).values(id="rv-other", project_id="p2", version="v9",
                                                 created_at=now))
        client.put("/api/v1/projects/%s/versions/rv-other/overrides/slot" % PROJECT,
                   headers=auth_header,
                   json={"slot_kind": "description", "slot_key": FID, "text": "sneaky"})
        with review_db.connect() as cx:
            assert cx.execute(select(s.text_overrides)
                              .where(s.text_overrides.c.version_id == "rv-other")).first() is None

    def test_the_tag_is_answered_with_the_id(self, client, review_db, auth_header):
        """The fixture's version is id `rv-1`, tag `v1` -- the shape a web-app run has."""
        r = client.get("/api/v1/projects/%s/versions/v1/slots" % PROJECT, headers=auth_header,
                       params={"slot_kind": "description"})
        assert r.status_code == 404
        assert "TAG" in r.json()["detail"] and "'%s'" % VERSION in r.json()["detail"]

    def test_the_id_still_works(self, client, review_db, auth_header):
        r = client.get(BASE + "/slots", headers=auth_header, params={"slot_kind": "description"})
        assert r.status_code == 200 and r.json()["total"] >= 1


class TestExportReadinessReportsTheReexport:
    """R9 is what a page calls on load for its banner. It also says whether a re-export is
    running, so a reloaded page -- or someone else's -- follows that job instead of offering to
    start another."""

    def _job(self, review_db, job_id, mode, status, minutes_ago=0, error=None):
        started = (datetime.datetime.now(datetime.timezone.utc)
                   - datetime.timedelta(minutes=minutes_ago))
        with review_db.begin() as cx:
            cx.execute(insert(s.analysis_jobs).values(
                id=job_id, project_id=PROJECT, version_id=VERSION, status=status, mode=mode,
                started_at=started, error_message=error))

    def test_never_re_exported_is_null(self, client, review_db, auth_header):
        self._job(review_db, "jobgen1", "full", "complete", minutes_ago=60)
        r = client.get(BASE + "/export-readiness", headers=auth_header)
        assert r.status_code == 200 and r.json()["reexport"] is None

    def test_the_newest_reexport_is_reported(self, client, review_db, auth_header):
        self._job(review_db, "jobgen1", "full", "complete", minutes_ago=60)
        self._job(review_db, "jobrx1", "reexport", "failed", minutes_ago=30, error="boom")
        self._job(review_db, "jobrx2", "reexport", "running", minutes_ago=1)
        rx = client.get(BASE + "/export-readiness", headers=auth_header).json()["reexport"]
        assert rx["jobId"] == "jobrx2" and rx["status"] == "running"
        assert rx["startedAt"] and rx["completedAt"] is None and rx["errorMessage"] is None


class TestStructDescriptionsEndToEnd:
    """Develop's unit header table describes structs, classes and unions. The review flow for
    that text: R11 lists the records a unit shows (`unit` filter, `shownIn`), R3 corrects one by
    its type key, and a type no document describes is refused rather than saved for nothing."""

    TYPES = {
        "Pump": {"kind": "class", "name": "Pump", "qualifiedName": "Pump",
                 "description": "Drives the pump."},
        "MAX_LEN": {"kind": "define", "name": "MAX_LEN", "qualifiedName": "MAX_LEN",
                    "value": "64"},
    }

    @pytest.fixture
    def with_types(self, review_db):
        from core import model_store
        with review_db.begin() as cx:
            model_store.persist_types(cx, PROJECT, VERSION, self.TYPES)
            cx.execute(insert(s.version_output_files).values(
                version_id=VERSION, rel_path="Sample/unit_headers.json", group_name="Sample",
                content=json.dumps({"Sample-Core|Core": [
                    {"declaration": "class Pump {...}", "information": "Drives the pump.",
                     "typeKey": "Pump"},
                    {"declaration": "#define MAX_LEN 64", "information": "64",
                     "typeKey": None}]})))
        return review_db

    def test_r11_lists_what_a_unit_shows(self, client, with_types, auth_header):
        r = client.get(BASE + "/slots", headers=auth_header,
                       params={"slot_kind": "structDescription", "unit": "Core"})
        assert r.status_code == 200, r.text
        slots = r.json()["slots"]
        assert [x["slotKey"] for x in slots] == ["Pump"]
        assert slots[0]["shownIn"] == ["Sample-Core|Core"]
        assert (slots[0]["component"], slots[0]["unit"]) == ("Sample-Core", "Core")
        assert slots[0]["kindOfType"] == "class" and slots[0]["text"] == "Drives the pump."

    def test_r3_corrects_it_by_its_type_key(self, client, with_types, auth_header):
        r = client.put(BASE + "/overrides/slot", headers=auth_header,
                       json={"slot_kind": "structDescription", "slot_key": "Pump",
                             "text": "Moves coolant."})
        assert r.status_code == 200, r.text
        assert r.json()["llmText"] == "Drives the pump."
        from core import model_store
        with with_types.connect() as cx:
            assert model_store.load_types(cx, VERSION)["Pump"]["description"] == "Moves coolant."

    def test_a_define_is_refused_with_the_reason(self, client, with_types, auth_header):
        r = client.put(BASE + "/overrides/slot", headers=auth_header,
                       json={"slot_kind": "structDescription", "slot_key": "MAX_LEN",
                             "text": "Words."})
        assert r.status_code == 404
        assert "is a define" in r.text


class TestR11SaysWhereATextIsShown:
    """`shownIn` on every row: the units whose document shows the text. `[]` is a slot that
    saves but is printed nowhere in this version -- e.g. a private function in a group run."""

    def _slots(self, client, auth_header, kind):
        r = client.get(BASE + "/slots", headers=auth_header, params={"slot_kind": kind})
        assert r.status_code == 200, r.text
        return r.json()["slots"]

    def test_a_function_no_document_lists_is_shown_nowhere(self, client, review_db, auth_header):
        row = next(x for x in self._slots(client, auth_header, "description")
                   if x["slotKey"] == FID)
        assert row["shownIn"] == []

    def test_once_its_interface_row_is_stored_it_is_shown_there(self, client, review_db,
                                                                auth_header):
        with review_db.begin() as cx:
            cx.execute(insert(s.version_output_files).values(
                version_id=VERSION, rel_path="Sample/interface_tables.json", group_name="Sample",
                content=json.dumps({"unitNames": {"Sample-Core|Core": "Core"},
                                    "Sample-Core|Core": {"name": "Core",
                                                         "entries": [{"functionId": FID}]}})))
        row = next(x for x in self._slots(client, auth_header, "description")
                   if x["slotKey"] == FID)
        assert row["shownIn"] == ["Sample-Core|Core"]
        flow = self._slots(client, auth_header, "nodeLabel")[0]
        assert flow["shownIn"] == ["Sample-Core|Core"]


class TestAnErrorSaysWhoseFaultItIs:
    """`_as_http`. A refusal the service chose keeps its own status; everything else was a 400,
    which told the client to fix a request that was fine -- and handed it an internal message
    (a SQL error, a Python `KeyError`) as the reason."""

    def _put(self, client, auth_header, key=FID, text="Words."):
        return client.put(BASE + "/overrides/slot", headers=auth_header,
                          json={"slot_kind": "description", "slot_key": key, "text": text})

    def test_an_unexpected_error_is_a_500_that_leaks_nothing(self, client, review_db,
                                                             auth_header, monkeypatch):
        from review import override_service

        def _boom(*a, **k):
            raise KeyError("internal_detail_nobody_outside_should_see")
        monkeypatch.setattr(override_service, "apply_override", _boom)
        r = self._put(client, auth_header)
        assert r.status_code == 500
        assert "internal_detail" not in r.text
        assert "server log" in r.json()["detail"]

    def test_a_malformed_key_keeps_its_own_400(self, client, review_db, auth_header):
        """Raised by the route itself, inside the block: passed through, not re-wrapped as
        "400: 400: ..."."""
        r = self._put(client, auth_header, key="one\x01two")
        assert r.status_code == 400
        assert not r.json()["detail"].startswith("400")

    def test_a_lost_race_for_the_slot_is_a_409(self, client, review_db, auth_header,
                                               monkeypatch):
        from sqlalchemy.exc import IntegrityError
        from review import override_service

        def _race(*a, **k):
            raise IntegrityError("INSERT INTO text_overrides", {}, Exception("UNIQUE"))
        monkeypatch.setattr(override_service, "apply_override", _race)
        r = self._put(client, auth_header)
        assert r.status_code == 409 and "save again" in r.json()["detail"]

    def test_a_model_replaced_under_the_save_is_a_409_and_saves_nothing(
            self, client, review_db, auth_header, monkeypatch):
        """A run regenerating the version replaced the row between the save's read and its
        write. The one-row write finds nothing to update and says so."""
        from core import model_store

        def _gone(*a, **k):
            raise model_store.ModelRowMissing("replaced while it was being written")
        monkeypatch.setattr(model_store, "set_entity_field", _gone)
        r = self._put(client, auth_header)
        detail = r.json()["detail"]
        assert r.status_code == 409 and "regenerating" in detail["message"]
        # A code of its own: the web app says "save again once the run has finished" for it
        assert detail["code"] == "VERSION_REGENERATING" and detail["status"] == 409
        got = client.get(BASE + "/overrides/slot", headers=auth_header,
                         params={"slot_kind": "description", "slot_key": FID})
        assert got.json()["isOverridden"] is False, "nothing was saved"


class TestAnOrphanOverHttp:
    def test_undoing_it_is_a_409_that_says_why(self, client, review_db, auth_header):
        with review_db.begin() as cx:
            cx.execute(insert(s.text_overrides).values(
                version_id=VERSION, slot_kind="description", slot_key=FID,
                llm_text="About the old code.", human_text="Corrected, old code.",
                is_orphaned=True, updated_at=datetime.datetime.now(datetime.timezone.utc)))
        r = client.delete(BASE + "/overrides/slot", headers=auth_header,
                          params={"slot_kind": "description", "slot_key": FID})
        assert r.status_code == 409 and "orphaned" in r.json()["detail"]

    def test_a_new_edit_is_a_first_edit(self, client, review_db, auth_header):
        with review_db.begin() as cx:
            cx.execute(insert(s.text_overrides).values(
                version_id=VERSION, slot_kind="description", slot_key=FID,
                llm_text="About the old code.", human_text="Corrected, old code.",
                is_orphaned=True, updated_at=datetime.datetime.now(datetime.timezone.utc)))
        r = client.put(BASE + "/overrides/slot", headers=auth_header,
                       json={"slot_kind": "description", "slot_key": FID,
                             "text": "Corrected, new code."})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["firstEdit"] is True and body["llmText"] == "Does the thing."


class TestDiscardingOrphans:
    """R12: orphans piled up version after version with no way to clean them up."""

    def _seed(self, review_db):
        now = datetime.datetime.now(datetime.timezone.utc)
        with review_db.begin() as cx:
            cx.execute(insert(s.text_overrides), [
                {"version_id": VERSION, "slot_kind": "description", "slot_key": FID,
                 "llm_text": "old", "human_text": "Corrected, old code.", "is_orphaned": True,
                 "updated_at": now},
                {"version_id": VERSION, "slot_kind": "behaviourInputName", "slot_key": FID,
                 "llm_text": "in", "human_text": "Pump input", "is_orphaned": False,
                 "updated_at": now}])
            cx.execute(insert(s.text_override_history).values(
                version_id=VERSION, slot_kind="description", slot_key=FID,
                human_text="Corrected, old code.", updated_at=now, seq=1))

    def test_an_admin_discards_them_and_corrections_in_force_stay(self, client, review_db,
                                                                   auth_header):
        self._seed(review_db)
        r = client.delete(BASE + "/overrides/orphans", headers=auth_header)
        assert r.status_code == 200, r.text
        assert r.json() == {"discarded": 1}
        with review_db.connect() as cx:
            left = cx.execute(select(s.text_overrides.c.slot_kind)
                              .where(s.text_overrides.c.version_id == VERSION)).fetchall()
            hist = cx.execute(select(s.text_override_history.c.slot_kind)
                              .where(s.text_override_history.c.version_id == VERSION)).fetchall()
        assert [r.slot_kind for r in left] == ["behaviourInputName"] and hist == []

    def test_one_slot_only(self, client, review_db, auth_header):
        self._seed(review_db)
        r = client.delete(BASE + "/overrides/orphans", headers=auth_header,
                          params={"slot_kind": "behaviourInputName", "slot_key": FID})
        assert r.status_code == 200 and r.json() == {"discarded": 0}, "in force: untouched"
        r = client.delete(BASE + "/overrides/orphans", headers=auth_header,
                          params={"slot_kind": "description", "slot_key": FID})
        assert r.json() == {"discarded": 1}

    def test_a_developer_may_not(self, client, review_db, dev_header):
        self._seed(review_db)
        r = client.delete(BASE + "/overrides/orphans", headers=dev_header)
        assert r.status_code == 403


class TestR11MatchesAComponentHoweverItIsSpelled:
    @pytest.mark.parametrize("asked", ["Sample Core", "Sample-Core", "sample-core"])
    def test_the_config_spelling_finds_it(self, client, review_db, auth_header, asked):
        r = client.get(BASE + "/slots", headers=auth_header,
                       params={"slot_kind": "description", "component": asked})
        assert r.status_code == 200, r.text
        assert [x["slotKey"] for x in r.json()["slots"]] == [FID]


class TestEveryRouteGivesASlotInOneShape:
    """`REQ-API-09`. One set of fields for a slot, whichever route returns it, so a client reads
    the same names for a description, a node label and a behaviour row. Before it, R3 had
    `previousText` and no `isOverridden`, R2 no `text`, R6 no `humanText`, and R8 no text at all.
    """

    SLOT = {"slotKind", "slotKey", "text", "llmText", "humanText", "isOverridden",
            "isOrphaned", "canUndo", "updatedBy", "updatedAt"}
    SAVE = {"previousText", "firstEdit", "viewsDerived", "queuedForRegeneration"}
    NODE = "Sample-Core|Core|ns::doThing|void\x01n1"

    def _saves(self, client, auth_header):
        r3 = client.put(BASE + "/overrides/slot", headers=auth_header,
                        json={"slot_kind": "description", "slot_key": FID, "text": "Human words."})
        r6 = client.put(BASE + "/overrides/behaviour", headers=auth_header,
                        json={"function_id": FID, "external_caller_id": CALLER,
                              "bullets": ["one", "two"]})
        r8 = _save_labels(client, auth_header, {"n1": "Checked label"})
        assert (r3.status_code, r6.status_code, r8.status_code) == (200, 200, 200), \
            (r3.text, r6.text, r8.text)
        return r3.json(), r6.json(), r8.json()["labels"][0]

    def test_every_save_answers_the_slot_and_what_it_did(self, client, review_db, auth_header):
        for body in self._saves(client, auth_header):
            assert self.SLOT | self.SAVE <= set(body), sorted(self.SLOT | self.SAVE - set(body))

    def test_every_read_answers_the_same_slot(self, client, review_db, auth_header):
        """R1, R2, R7 and R11 agree field for field with what the save answered."""
        r3, r6, r8 = self._saves(client, auth_header)
        slots = {(b["slotKind"], b["slotKey"]): {k: b[k] for k in self.SLOT}
                 for b in (r3, r6, r8)}
        r1 = client.get(BASE + "/overrides", headers=auth_header).json()["overrides"]
        assert {(x["slotKind"], x["slotKey"]): {k: x[k] for k in self.SLOT} for x in r1} == slots
        for (kind, key), want in slots.items():
            r2 = client.get(BASE + "/overrides/slot", headers=auth_header,
                            params={"slot_kind": kind, "slot_key": key}).json()
            assert {k: r2[k] for k in self.SLOT} == want, kind
            listed = client.get(BASE + "/slots", headers=auth_header,
                                params={"slot_kind": kind}).json()["slots"]
            if kind != "nodeLabel":                         # R11 lists flowcharts, not nodes
                row = next(x for x in listed if x["slotKey"] == key)
                assert {k: row[k] for k in self.SLOT} == want, kind
        n1 = next(n for n in _read_labels(client, auth_header).json()["labels"]
                  if n["nodeId"] == "n1")
        assert {k: n1[k] for k in self.SLOT} == slots[("nodeLabel", r8["slotKey"])]

    def test_a_behaviour_row_reads_as_text_and_as_bullets(self, client, review_db, auth_header):
        _r3, r6, _r8 = self._saves(client, auth_header)
        assert r6["text"] == r6["humanText"] == "one\ntwo" and r6["bullets"] == ["one", "two"]
        assert r6["previousText"] == r6["llmText"] == "start calls doThing"
        assert (r6["functionId"], r6["externalCallerId"]) == (FID, CALLER)
        assert r6["queuedForRegeneration"] == []

    def test_r8_carries_the_rebuilt_diagram(self, client, review_db, auth_header):
        """So the editor redraws from the save's answer, without asking R7 again."""
        r = _save_labels(client, auth_header, {"n1": "Checked-label"})
        assert "Checked-label" in r.json()["dot"]

    def test_an_undo_answers_like_a_save(self, client, review_db, auth_header):
        self._saves(client, auth_header)
        for kind, key in (("description", FID), ("nodeLabel", self.NODE)):
            u = client.delete(BASE + "/overrides/slot", headers=auth_header,
                              params={"slot_kind": kind, "slot_key": key})
            assert u.status_code == 200, u.text
            assert self.SLOT | self.SAVE <= set(u.json()), kind
            assert u.json()["text"] == u.json()["llmText"] and u.json()["canUndo"] is False
        assert "llm n1" in u.json()["dot"] and "renderPending" in u.json()


class TestQueuedTextsCarryAName:
    """A save's `queuedForRegeneration` carries `label` -- the function's or the unit's name --
    so the web app can say WHICH texts will be rewritten without taking a key apart."""

    def test_a_function_and_a_unit(self):
        from api.routes.text_overrides import _readable
        assert _readable("description", "Layer1.Lib|Lib|libAdd|int,int") == "libAdd"
        assert _readable("unitDescription", "Layer1.Lib|Lib") == "Lib"

    def test_a_key_it_cannot_read_is_its_own_label(self):
        from api.routes.text_overrides import _readable
        assert _readable("description", "nonsense") == "nonsense"
