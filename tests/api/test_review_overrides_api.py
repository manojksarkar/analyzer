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
from sqlalchemy import create_engine, insert
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


def _token():
    from review import slot
    return slot.encode(FID)


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

    def test_an_unknown_slot_is_404(self, client, review_db, auth_header):
        r = client.put(BASE + "/overrides/slot", headers=auth_header,
                       json={"slot_kind": "description", "slot_key": "Nope|Nope|gone|",
                             "text": "Words."})
        assert r.status_code == 404

    def test_a_node_label_through_this_route_is_501(self, client, review_db, auth_header):
        """It has no model field; R8 is its route. A 501 says so instead of pretending."""
        from review import slot
        r = client.put(BASE + "/overrides/slot", headers=auth_header,
                       json={"slot_kind": slot.NODE_LABEL,
                             "slot_key": slot.for_node(FID, "n1"), "text": "Words."})
        assert r.status_code == 501

    def test_reading_a_slot_nobody_corrected_is_404(self, client, review_db, auth_header):
        r = client.get(BASE + "/overrides/slot", headers=auth_header,
                       params={"slot_kind": "description", "slot_key": FID})
        assert r.status_code == 404


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
        r = client.get(BASE + "/flowcharts/%s/labels" % _token(), headers=auth_header)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["flowchartId"] == FID
        assert [l["nodeId"] for l in body["labels"]] == ["n0", "n1", "n2"]
        assert all(l["isOverridden"] is False for l in body["labels"])

    def test_a_save_applies_and_shows_up(self, client, review_db, auth_header):
        r = client.put(BASE + "/flowcharts/%s/labels" % _token(), headers=auth_header,
                       json={"labels": {"n1": "Check the write-protect flag"}})
        assert r.status_code == 200, r.text
        assert r.json()["applied"] == ["n1"]
        assert r.json()["slotShape"]

        body = client.get(BASE + "/flowcharts/%s/labels" % _token(),
                          headers=auth_header).json()
        n1 = next(l for l in body["labels"] if l["nodeId"] == "n1")
        assert n1["text"] == "Check the write-protect flag"
        assert n1["isOverridden"] is True
        assert n1["llmText"] == "llm n1"

    def test_several_labels_in_one_call(self, client, review_db, auth_header):
        r = client.put(BASE + "/flowcharts/%s/labels" % _token(), headers=auth_header,
                       json={"labels": {"n0": "Begin", "n2": "Finish"}})
        assert r.status_code == 200
        assert sorted(r.json()["applied"]) == ["n0", "n2"]

    def test_a_node_that_does_not_exist_fails_the_whole_call(self, client, review_db,
                                                             auth_header):
        r = client.put(BASE + "/flowcharts/%s/labels" % _token(), headers=auth_header,
                       json={"labels": {"n1": "Good", "n99": "Nowhere"}})
        assert r.status_code == 404
        assert "n99" in r.json()["detail"]
        assert client.get(BASE + "/overrides", headers=auth_header).json()["total"] == 0

    def test_empty_label_text_is_422(self, client, review_db, auth_header):
        r = client.put(BASE + "/flowcharts/%s/labels" % _token(), headers=auth_header,
                       json={"labels": {"n1": "  "}})
        assert r.status_code == 422

    def test_a_malformed_token_is_not_a_500(self, client, review_db, auth_header):
        r = client.get(BASE + "/flowcharts/!!!not-base64!!!/labels", headers=auth_header)
        assert r.status_code in (400, 404)

    def test_an_unknown_flowchart_is_404(self, client, review_db, auth_header):
        from review import slot
        r = client.get(BASE + "/flowcharts/%s/labels" % slot.encode("No|Such|fn|"),
                       headers=auth_header)
        assert r.status_code == 404


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

    def test_an_unknown_caller_is_404(self, client, review_db, auth_header):
        r = client.put(BASE + "/overrides/behaviour", headers=auth_header,
                       json={"function_id": FID, "external_caller_id": "No|Such|caller|",
                             "bullets": ["x"]})
        assert r.status_code == 404

    def test_an_empty_list_is_422(self, client, review_db, auth_header):
        r = client.put(BASE + "/overrides/behaviour", headers=auth_header,
                       json={"function_id": FID, "external_caller_id": CALLER, "bullets": []})
        assert r.status_code == 422


class TestUndoAndHistory:
    def test_undo_restores_the_original_and_keeps_the_record(self, client, review_db,
                                                             auth_header):
        client.put(BASE + "/overrides/slot", headers=auth_header,
                   json={"slot_kind": "description", "slot_key": FID, "text": "Corrected."})
        r = client.delete(BASE + "/overrides/slot", headers=auth_header,
                          params={"slot_kind": "description", "slot_key": FID})
        assert r.status_code == 200, r.text
        assert r.json()["undone"] is True
        assert r.json()["override"]["humanText"] == "Does the thing."

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
        r = client.get(BASE + "/flowcharts/%s/labels" % _token(), headers=auth_header)
        assert r.status_code == 200, r.text
        labels = r.json()["labels"]
        assert labels, "the fixture must have nodes"
        for n in labels:
            assert n.get("slotKey"), "node %s has no slotKey" % n["nodeId"]

    def test_the_key_is_the_one_the_server_would_build(self, client, review_db, auth_header):
        from review import slot as slot_mod
        body = client.get(BASE + "/flowcharts/%s/labels" % _token(), headers=auth_header).json()
        for n in body["labels"]:
            assert n["slotKey"] == slot_mod.for_node(body["flowchartId"], n["nodeId"])

    def test_that_key_works_for_undo_and_history(self, client, review_db, auth_header):
        """The point of returning it. Round-trip it through R8 -> R5 -> R4 untouched."""
        body = client.get(BASE + "/flowcharts/%s/labels" % _token(), headers=auth_header).json()
        node = body["labels"][0]
        assert client.put(BASE + "/flowcharts/%s/labels" % _token(), headers=auth_header,
                          json={"labels": {node["nodeId"]: "Corrected here."}}).status_code == 200

        h = client.get(BASE + "/overrides/history", headers=auth_header,
                       params={"slot_kind": "nodeLabel", "slot_key": node["slotKey"]})
        assert h.status_code == 200 and len(h.json()["history"]) == 1

        u = client.delete(BASE + "/overrides/slot", headers=auth_header,
                          params={"slot_kind": "nodeLabel", "slot_key": node["slotKey"]})
        assert u.status_code == 200 and u.json()["undone"] is True


class TestRenderPendingTellsTheTruth:
    def test_a_save_with_no_output_tree_reports_the_picture_as_owed(self, client, review_db,
                                                                    auth_header):
        """The API host has no output tree, so the text is corrected and the PNG is not. Saying
        otherwise made the UI show "image up to date" while the export blocked on that job."""
        r = client.put(BASE + "/flowcharts/%s/labels" % _token(), headers=auth_header,
                       json={"labels": {"n1": "Check the write-protect flag"}})
        assert r.status_code == 200, r.text
        assert r.json()["renderPending"] is True
        assert r.json()["renderJobs"]

    def test_it_agrees_with_export_readiness(self, client, review_db, auth_header):
        """Two answers to "is the picture current" that disagree is worse than either alone."""
        put = client.put(BASE + "/flowcharts/%s/labels" % _token(), headers=auth_header,
                         json={"labels": {"n1": "Corrected."}}).json()
        ready = client.get(BASE + "/export-readiness", headers=auth_header).json()
        assert put["renderPending"] is (ready["pendingRenders"] > 0)
