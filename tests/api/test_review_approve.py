"""Review and approval over HTTP — docs/spec/REVIEW_APPROVE_API_SPEC.md.

Each test works in a project of its own (`proj`), so the session's shared database -- seed data
other tests read -- is not disturbed, and the two backends (memory, SQL) see the same steps.
"""
from __future__ import annotations

import dataclasses
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from api.models.domain import Document, DocumentAssignment, ProjectMember, Version
from api.services import review_workflow as rw

UTC = timezone.utc
NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def _token(client, email):
    r = client.post("/api/v1/auth/signin", json={"email": email, "password": "secret"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


@pytest.fixture(scope="session")
def h(client):
    """Headers per seed user: alice (admin), bob and carol (developers), dave, eve."""
    return {name: _token(client, "%s@aspice.dev" % name) for name in ("alice", "bob", "carol", "dave", "eve")}


class Proj:
    def __init__(self, db, pid, vid):
        self.db, self.id, self.vid = db, pid, vid

    @property
    def base(self):
        return "/api/v1/projects/%s/documents" % self.id

    def doc(self, status="in_review", reviewer=None, process="SWE.3", group=None, vid=None, **kw):
        did = "d" + uuid.uuid4().hex[:10]
        d = Document(id=did, project_id=self.id, version_id=vid or self.vid, process=process,
                     name="Comp-" + did, subtitle="Detailed Design", layer="L1",
                     group=group or ("L1.Comp-" + did), status=status, due_date=None,
                     created_at=NOW, updated_at=NOW, **kw)
        self.db.documents.update(d)
        if reviewer:
            self.db.assignments.set_reviewer(DocumentAssignment("a" + did, did, reviewer, "u1", NOW))
        return d

    def version(self, tag, status="in_review", created=None, baseline=None):
        vid = "ver" + uuid.uuid4().hex[:8]
        self.db.versions.create(Version(vid, self.id, tag, "c" + vid, "main", "", status, 0, "u1",
                                        created or NOW, baseline_version_id=baseline))
        return vid

    def member(self, user_id, role="developer", status="active"):
        self.db.members.add_member(ProjectMember("m" + uuid.uuid4().hex[:8], self.id, user_id, role,
                                                 status, "u1", NOW, NOW if status == "active" else None))

    def get(self, doc):
        return self.db.documents.get(doc.id)

    def kinds(self, doc):
        return [e.kind for e in self.db.review_events.list_for_document(doc.id)]


@pytest.fixture
def proj(db):
    """A fresh project: alice admin; bob and carol developers; dave invited (pending)."""
    base = db.projects.get("p1")
    pid = "pr" + uuid.uuid4().hex[:8]
    db.projects.create(dataclasses.replace(base, id=pid, name="Review " + pid, status="in_review"))
    p = Proj(db, pid, None)
    p.vid = p.version("v1.0")
    p.member("u1", "admin")
    p.member("u2")
    p.member("u3")
    p.member("u4", status="pending")
    return p


def _code(r):
    return (r.json().get("detail") or {}).get("code")


# ---------------------------------------------------------------------------
# A1-A4: one reviewer, assigned or claimed
# ---------------------------------------------------------------------------
class TestAssign:
    def test_assigning_replaces_the_reviewer_and_tells_both(self, client, h, proj, db):
        d = proj.doc(reviewer="u2")
        r = client.post("%s/%s/assignments" % (proj.base, d.id), json={"user_id": "u3"}, headers=h["alice"])
        assert r.status_code == 200, r.text
        body = r.json()["document"]
        assert body["reviewer"]["user_id"] == "u3"
        assert [a["user_id"] for a in body["assignees"]] == ["u3"]
        assert db.assignments.reviewers([d.id]) == {d.id: "u3"}
        ev = db.review_events.list_for_document(d.id)[0]
        assert (ev.kind, ev.actor_id, ev.payload) == ("assigned", "u1", {"from_user_id": "u2", "to_user_id": "u3"})
        assert any(n.document_id == d.id and n.type == "review_assigned" for n in db.notifications.list_unread("u3"))
        assert any(n.document_id == d.id and n.type == "review_unassigned" for n in db.notifications.list_unread("u2"))

    def test_the_older_list_shape_takes_exactly_one(self, client, h, proj):
        d = proj.doc()
        r = client.post("%s/%s/assignments" % (proj.base, d.id), json={"user_ids": ["u2", "u3"]}, headers=h["alice"])
        assert r.status_code == 422
        r = client.post("%s/%s/assignments" % (proj.base, d.id), json={"user_ids": ["u2"]}, headers=h["alice"])
        assert r.status_code == 200 and r.json()["document"]["reviewer"]["user_id"] == "u2"

    def test_only_an_active_member_can_be_the_reviewer(self, client, h, proj):
        d = proj.doc()
        for uid in ("u4", "u5"):        # invited, not accepted; and not a member at all
            r = client.post("%s/%s/assignments" % (proj.base, d.id), json={"user_id": uid}, headers=h["alice"])
            assert r.status_code == 422 and _code(r) == "NOT_A_MEMBER", r.text

    def test_an_approved_document_keeps_its_reviewer(self, client, h, proj):
        d = proj.doc(status="approved", reviewer="u2")
        r = client.post("%s/%s/assignments" % (proj.base, d.id), json={"user_id": "u3"}, headers=h["alice"])
        assert r.status_code == 409 and _code(r) == "DOCUMENT_APPROVED"
        r = client.delete("%s/%s/assignments/u2" % (proj.base, d.id), headers=h["alice"])
        assert r.status_code == 409

    def test_a_developer_does_not_assign(self, client, h, proj):
        d = proj.doc()
        r = client.post("%s/%s/assignments" % (proj.base, d.id), json={"user_id": "u2"}, headers=h["bob"])
        assert r.status_code == 403

    def test_remove(self, client, h, proj, db):
        d = proj.doc(reviewer="u2")
        r = client.delete("%s/%s/assignments/u2" % (proj.base, d.id), headers=h["alice"])
        assert r.status_code == 204
        assert db.assignments.reviewers([d.id]) == {}
        assert proj.kinds(d)[0] == "unassigned"

    def test_batch_assigns_what_it_can_and_names_the_rest(self, client, h, proj, db):
        a, b, done = proj.doc(), proj.doc(), proj.doc(status="approved")
        r = client.post(proj.base + "/assignments/batch", headers=h["alice"],
                        json={"document_ids": [a.id, b.id, done.id, "nope"], "user_id": "u3"})
        assert r.status_code == 200, r.text
        assert r.json()["assigned"] == [a.id, b.id]
        assert {s["document_id"]: s["code"] for s in r.json()["skipped"]} == {
            done.id: "DOCUMENT_APPROVED", "nope": "NOT_FOUND"}
        told = [n for n in db.notifications.list_unread("u3") if "2 documents" in n.message]
        assert len(told) == 1          # one notification for the batch, not one per document


class TestClaim:
    def test_a_developer_claims_a_document_without_a_reviewer(self, client, h, proj, db):
        d = proj.doc()
        r = client.post("%s/%s/assignments/self" % (proj.base, d.id), headers=h["bob"])
        assert r.status_code == 200, r.text
        assert r.json()["document"]["reviewer"]["user_id"] == "u2"
        assert proj.kinds(d)[0] == "claimed"
        assert any(n.type == "review_claimed" and n.document_id == d.id for n in db.notifications.list_unread("u1"))
        r = client.post("%s/%s/assignments/self" % (proj.base, d.id), headers=h["carol"])
        assert r.status_code == 409 and _code(r) == "HAS_REVIEWER"

    def test_an_admin_or_an_invited_developer_does_not_claim(self, client, h, proj):
        d = proj.doc()
        assert client.post("%s/%s/assignments/self" % (proj.base, d.id), headers=h["alice"]).status_code == 403
        assert client.post("%s/%s/assignments/self" % (proj.base, d.id), headers=h["dave"]).status_code == 403

    def test_an_approved_document_is_not_claimed(self, client, h, proj):
        d = proj.doc(status="approved")
        r = client.post("%s/%s/assignments/self" % (proj.base, d.id), headers=h["bob"])
        assert r.status_code == 409 and _code(r) == "DOCUMENT_APPROVED"


# ---------------------------------------------------------------------------
# A5-A9: submit, approve, request changes, reopen, approve several
# ---------------------------------------------------------------------------
class TestFlow:
    def test_submit_then_changes_then_submit_again_then_approve(self, client, h, proj, db):
        d = proj.doc(reviewer="u2")
        url = "%s/%s/" % (proj.base, d.id)

        r = client.post(url + "submit-review", json={"comment": "  "}, headers=h["bob"])
        assert r.status_code == 422                      # a comment is required
        r = client.post(url + "submit-review", json={"comment": "Checked every function."}, headers=h["bob"])
        assert r.status_code == 200, r.text
        doc = r.json()["document"]
        assert doc["status"] == "submitted" and doc["review"]["comment"] == "Checked every function."
        assert any(n.type == "review_submitted" for n in db.notifications.list_unread("u1"))

        r = client.post(url + "request-changes", json={}, headers=h["alice"])
        assert r.status_code == 422                      # so is the admin's
        r = client.post(url + "request-changes", json={"comment": "Names are vague."}, headers=h["alice"])
        assert r.status_code == 200
        doc = r.json()["document"]
        assert doc["status"] == "changes_requested" and doc["review"]["changes_comment"] == "Names are vague."
        assert any(n.type == "review_changes_requested" for n in db.notifications.list_unread("u2"))

        r = client.post(url + "submit-review", json={"comment": "Renamed both."}, headers=h["bob"])
        assert r.status_code == 200
        assert r.json()["document"]["review"]["changes_comment"] is None
        assert db.review_events.list_for_document(d.id)[0].payload == {"again": True}

        r = client.post(url + "approve", json={"comment": "Reads well."}, headers=h["alice"])
        assert r.status_code == 200, r.text
        doc = r.json()["document"]
        assert doc["status"] == "approved"
        assert doc["review"]["approved_by"]["user_id"] == "u1"
        assert doc["review"]["approval_comment"] == "Reads well."
        ev = db.review_events.list_for_document(d.id)[0]
        assert ev.kind == "approved" and ev.payload["direct"] is False
        assert proj.kinds(d) == ["approved", "submitted", "changes_requested", "submitted"]
        assert any(n.type == "review_approved" for n in db.notifications.list_unread("u2"))

    def test_who_submits(self, client, h, proj):
        d = proj.doc(reviewer="u2")
        r = client.post("%s/%s/submit-review" % (proj.base, d.id), json={"comment": "x"}, headers=h["carol"])
        assert r.status_code == 403                      # not its reviewer
        lone = proj.doc()
        r = client.post("%s/%s/submit-review" % (proj.base, lone.id), json={"comment": "x"}, headers=h["alice"])
        assert r.status_code == 409 and _code(r) == "NO_REVIEWER"
        r = client.post("%s/%s/submit-review" % (proj.base, d.id), json={"comment": "x"}, headers=h["alice"])
        assert r.status_code == 200                      # an admin may submit for the reviewer

    def test_states_are_checked(self, client, h, proj):
        ready, done, open_ = proj.doc("submitted", "u2"), proj.doc("approved", "u2"), proj.doc("in_review", "u2")
        assert _code(client.post("%s/%s/submit-review" % (proj.base, ready.id), json={"comment": "x"},
                                 headers=h["bob"])) == "WRONG_STATE"
        assert _code(client.post("%s/%s/approve" % (proj.base, done.id), headers=h["alice"])) == "WRONG_STATE"
        assert _code(client.post("%s/%s/request-changes" % (proj.base, open_.id), json={"comment": "x"},
                                 headers=h["alice"])) == "WRONG_STATE"
        assert _code(client.post("%s/%s/reopen" % (proj.base, open_.id), json={"reason": "x"},
                                 headers=h["alice"])) == "WRONG_STATE"

    def test_approving_from_in_review_is_direct_and_needs_no_body(self, client, h, proj, db):
        d = proj.doc(reviewer="u2")
        r = client.post("%s/%s/approve" % (proj.base, d.id), headers=h["alice"])
        assert r.status_code == 200, r.text
        assert db.review_events.list_for_document(d.id)[0].payload["direct"] is True

    def test_only_an_active_admin_approves(self, client, h, proj):
        d = proj.doc("submitted", "u2")
        assert client.post("%s/%s/approve" % (proj.base, d.id), headers=h["bob"]).status_code == 403
        proj.member("u5", "admin", status="pending")     # invited as admin, not accepted (B14)
        assert client.post("%s/%s/approve" % (proj.base, d.id), headers=h["eve"]).status_code == 403

    def test_a_word_file_without_every_correction_is_not_approved(self, client, h, proj, monkeypatch):
        """WORD_FILE_UPDATES §4.5: out of date by the Word file's own rule, saying why."""
        from review.word_files import FileState
        d = proj.doc("submitted", "u2")
        monkeypatch.setattr(rw, "word_file_state", lambda db, doc: (
            FileState(True, ("corrections", "layerAdded"), 2, 0, "HAL_LAYER"), False, None))
        r = client.post("%s/%s/approve" % (proj.base, d.id), headers=h["alice"])
        assert r.status_code == 409 and _code(r) == "STALE_EXPORT"
        detail = r.json()["detail"]
        assert (detail["why"], detail["corrections"], detail["layer"]) == \
            (["corrections", "layerAdded"], 2, "HAL_LAYER")
        assert "2 corrections not in it, HAL_LAYER added since" in detail["message"]
        assert proj.get(d).status == "submitted"

    def test_nor_one_being_updated(self, client, h, proj, monkeypatch):
        d = proj.doc("submitted", "u2")
        monkeypatch.setattr(rw, "word_file_state", lambda db, doc: (None, True, "jobupd1"))
        r = client.post("%s/%s/approve" % (proj.base, d.id), headers=h["alice"])
        assert r.status_code == 409 and _code(r) == "WORD_FILE_UPDATING"
        assert r.json()["detail"]["job_id"] == "jobupd1"

    def test_approve_several_says_why_a_file_was_skipped(self, client, h, proj, monkeypatch):
        from review.word_files import FileState
        ready, behind = proj.doc("submitted", "u2"), proj.doc("submitted", "u3")
        monkeypatch.setattr(rw, "word_file_state", lambda db, doc: (
            (FileState(True, ("corrections",), 1, 0, None) if doc.id == behind.id else None),
            False, None))
        r = client.post(proj.base + "/approve-all", headers=h["alice"],
                        json={"document_ids": [ready.id, behind.id]})
        assert r.json()["approved"] == [ready.id]
        skipped = r.json()["skipped"][0]
        assert (skipped["document_id"], skipped["code"], skipped["why"], skipped["corrections"]) == \
            (behind.id, "STALE_EXPORT", ["corrections"], 1)

    def test_reopen_needs_a_reason_and_keeps_the_reviewer(self, client, h, proj, db):
        d = proj.doc("approved", "u2", approved_by="u1", approved_at=NOW, docx_sha256="ab" * 32)
        r = client.post("%s/%s/reopen" % (proj.base, d.id), json={"reason": ""}, headers=h["alice"])
        assert r.status_code == 422
        r = client.post("%s/%s/reopen" % (proj.base, d.id), json={"reason": "Pump table changed."},
                        headers=h["alice"])
        assert r.status_code == 200, r.text
        doc = r.json()["document"]
        assert doc["status"] == "in_review" and doc["reviewer"]["user_id"] == "u2"
        assert doc["review"]["approved_by"] is None and doc["review"]["docx_sha256"] is None
        ev = db.review_events.list_for_document(d.id)[0]
        assert (ev.kind, ev.comment, ev.payload) == ("reopened", "Pump table changed.", {"docx_sha256": "ab" * 32})
        assert any(n.type == "review_reopened" for n in db.notifications.list_unread("u2"))

    def test_approve_several_takes_ready_ones_of_this_project_only(self, client, h, proj, db):
        ready, open_ = proj.doc("submitted", "u2"), proj.doc("in_review", "u2")
        foreign = db.documents.get("doc8")                      # project p2
        r = client.post(proj.base + "/approve-all", headers=h["alice"],
                        json={"document_ids": [ready.id, open_.id, foreign.id]})
        assert r.status_code == 200, r.text
        assert r.json()["approved"] == [ready.id]
        assert {s["document_id"]: s["code"] for s in r.json()["skipped"]} == {
            open_.id: "WRONG_STATE", foreign.id: "NOT_FOUND"}

    def test_approve_all_by_version_is_retired(self, client, h, proj):
        # It approved every document of every version when the version was empty (B7).
        r = client.post(proj.base + "/approve-all", json={"version_id": ""}, headers=h["alice"])
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# A5: submit updates the document's Word file (docs/design/WORD_FILE_UPDATES.md §4.4)
# ---------------------------------------------------------------------------
class TestSubmitUpdatesTheWordFile:
    def _out_of_date(self, monkeypatch, doc):
        from review.word_files import FileState, UP_TO_DATE
        from api.services import word_files
        monkeypatch.setattr(word_files, "file_states", lambda db, v, docs=None, **k: {
            d.id: (FileState(True, ("corrections",), 1, 0, None) if d.id == doc.id else UP_TO_DATE)
            for d in (docs if docs is not None else word_files.version_documents(db, v))})

    def _submit(self, client, h, proj, d):
        r = client.post("%s/%s/submit-review" % (proj.base, d.id), json={"comment": "Checked."},
                        headers=h["bob"])
        assert r.status_code == 200, r.text
        assert r.json()["document"]["status"] == "submitted"
        return r.json()["word_file"]

    def test_an_up_to_date_file_starts_nothing(self, client, h, proj):
        d = proj.doc(reviewer="u2")
        assert self._submit(client, h, proj, d) == {"state": "up_to_date", "job_id": None,
                                                     "blocked_by": None}

    def test_an_out_of_date_one_is_updated_by_the_submitter(self, client, h, proj, monkeypatch):
        from api.services import pipeline_runner as pr
        d = proj.doc(reviewer="u2", group="L1.Brake")
        self._out_of_date(monkeypatch, d)
        asked = {}

        def start(db, version, comps, **kw):
            asked.update(comps=comps, **kw)
            return type("J", (), {"id": "jobsub1", "status": "queued", "mode": "reexport",
                                  "reason": "submit"})(), False, comps
        monkeypatch.setattr(pr, "start_update", start)
        assert self._submit(client, h, proj, d) == {"state": "updating", "job_id": "jobsub1",
                                                    "blocked_by": None}
        assert asked == {"comps": ["L1.Brake"], "started_by": "u2", "reason": "submit",
                         "document_id": d.id}

    def test_a_refusal_never_fails_the_submit(self, client, h, proj, monkeypatch):
        """D8: another update (that does not cover it) holds the version -- the submit stands,
        and its answer says what to wait for."""
        from api.services import pipeline_runner as pr
        d = proj.doc(reviewer="u2", group="L1.Brake")
        self._out_of_date(monkeypatch, d)

        def busy(db, version, comps, **kw):
            raise pr.ReexportRefused(409, "REEXPORT_RUNNING", "being updated by job jobx", "jobx",
                                     extra={"kind": "update", "scope": "out_of_date",
                                            "components": ["L1.Other"]})
        monkeypatch.setattr(pr, "start_update", busy)
        wf = self._submit(client, h, proj, d)
        assert wf["state"] == "out_of_date" and wf["job_id"] is None
        assert (wf["blocked_by"]["kind"], wf["blocked_by"]["job_id"],
                wf["blocked_by"]["components"]) == ("update", "jobx", ["L1.Other"])
        assert proj.get(d).status == "submitted"


# ---------------------------------------------------------------------------
# version and project status, derived
# ---------------------------------------------------------------------------
class TestRollUp:
    def test_the_version_is_approved_when_every_document_is(self, client, h, proj, db):
        a, b = proj.doc("submitted", "u2"), proj.doc("submitted", "u3")
        vurl = "/api/v1/projects/%s/versions/%s" % (proj.id, proj.vid)
        client.post("%s/%s/approve" % (proj.base, a.id), headers=h["alice"])
        v = client.get(vurl, headers=h["alice"]).json()["version"]
        assert v["status"] == "in_review"
        assert (v["review"]["documents"], v["review"]["approved"]) == (2, 1)
        assert db.projects.get(proj.id).status == "in_review"

        client.post("%s/%s/approve" % (proj.base, b.id), headers=h["alice"])
        v = client.get(vurl, headers=h["alice"]).json()["version"]
        assert v["status"] == "approved"
        assert v["review"]["approved_by"]["user_id"] == "u1" and v["review"]["approved_at"]
        assert db.versions.get(proj.vid).status == "approved"
        assert db.projects.get(proj.id).status == "complete"    # its latest version

        client.post("%s/%s/reopen" % (proj.base, b.id), json={"reason": "again"}, headers=h["alice"])
        assert client.get(vurl, headers=h["alice"]).json()["version"]["status"] == "in_review"
        assert db.projects.get(proj.id).status == "in_review"

    def test_a_version_status_is_not_set_by_hand(self, client, h, proj):
        r = client.patch("/api/v1/projects/%s/versions/%s" % (proj.id, proj.vid),
                         json={"status": "approved"}, headers=h["alice"])
        assert r.status_code == 400
        r = client.patch("/api/v1/projects/%s/versions/%s" % (proj.id, proj.vid),
                         json={"description": "Release candidate"}, headers=h["alice"])
        assert r.status_code == 200

    def test_stats_count_each_state(self, client, h, proj):
        proj.doc("in_review"), proj.doc("submitted", "u2"), proj.doc("approved", "u2", carried_from=proj.vid)
        r = client.get(proj.base + "/stats", params={"version_id": proj.vid}, headers=h["alice"])
        s = r.json()["stats"]
        assert (s["total"], s["in_review"], s["submitted"], s["approved"]) == (3, 1, 1, 1)
        assert (s["needs_reviewer"], s["carried"]) == (1, 1)

    def test_the_list_filters_by_reviewer_and_by_none(self, client, h, proj):
        mine, none = proj.doc(reviewer="u2"), proj.doc()
        ids = lambda q: {d["id"] for d in client.get(proj.base, params={**q, "per_page": 100},
                                                     headers=h["alice"]).json()["documents"]}
        assert ids({"assignee_id": "u2"}) == {mine.id}
        assert ids({"assignee_id": "none"}) == {none.id}


# ---------------------------------------------------------------------------
# retired routes, the record, notifications
# ---------------------------------------------------------------------------
class TestRetiredAndRecord:
    def test_status_and_sections_are_not_written_directly(self, client, h, proj):
        d = proj.doc()
        r = client.patch("%s/%s" % (proj.base, d.id), json={"status": "approved"}, headers=h["alice"])
        assert r.status_code == 400
        r = client.patch("%s/%s/sections/intro" % (proj.base, d.id), json={"review_state": "accepted"},
                         headers=h["alice"])
        assert r.status_code in (404, 405)

    def test_events_newest_first_and_the_project_feed_names_documents(self, client, h, proj):
        d = proj.doc(reviewer="u2")
        client.post("%s/%s/submit-review" % (proj.base, d.id), json={"comment": "ok"}, headers=h["bob"])
        client.post("%s/%s/approve" % (proj.base, d.id), headers=h["alice"])
        ev = client.get("%s/%s/events" % (proj.base, d.id), headers=h["bob"]).json()["events"]
        assert [e["kind"] for e in ev] == ["approved", "submitted"]
        assert ev[1]["actor"]["user_id"] == "u2" and ev[1]["comment"] == "ok"
        feed = client.get("/api/v1/projects/%s/review-events" % proj.id, headers=h["bob"]).json()["events"]
        assert feed[0]["document"] == {"id": d.id, "name": d.name, "process": "SWE.3"}
        listed = client.get(proj.base, params={"per_page": 100}, headers=h["bob"]).json()["documents"]
        assert [x["review"]["last_event"]["kind"] for x in listed if x["id"] == d.id] == ["approved"]

    def test_a_document_of_another_project_is_not_found(self, client, h, proj, db):
        # B1/B2: routes named the project in the path and acted on any project's document.
        foreign = db.documents.get("doc8")                      # project p2
        for method, path, body in (
                ("post", "/assignments", {"user_id": "u2"}),
                ("post", "/assignments/self", None),
                ("delete", "/assignments/u2", None),
                ("post", "/submit-review", {"comment": "x"}),
                ("post", "/approve", None),
                ("post", "/request-changes", {"comment": "x"}),
                ("post", "/reopen", {"reason": "x"}),
                ("get", "/events", None)):
            who = h["bob"] if path == "/assignments/self" else h["alice"]
            kw = {"json": body} if body is not None else {}
            r = getattr(client, method)("%s/%s%s" % (proj.base, foreign.id, path), headers=who, **kw)
            assert r.status_code == 404, (method, path, r.status_code, r.text)
        assert db.documents.get("doc8").status == "approved"

    def test_notifications_are_the_callers_own(self, client, h, proj, db):
        d = proj.doc()
        client.post("%s/%s/assignments" % (proj.base, d.id), json={"user_id": "u3"}, headers=h["alice"])
        note = next(n for n in db.notifications.list_unread("u3") if n.document_id == d.id)
        r = client.patch("/api/v1/notifications/%s/read" % note.id, headers=h["bob"])
        assert r.status_code == 404                              # B13
        assert client.patch("/api/v1/notifications/%s/read" % note.id, headers=h["carol"]).status_code == 200
        unread = client.get("/api/v1/notifications", headers=h["carol"]).json()["notifications"]
        assert note.id not in {n["id"] for n in unread}
        every = client.get("/api/v1/notifications", params={"all": "true"}, headers=h["carol"]).json()["notifications"]
        mine = [n for n in every if n["id"] == note.id]
        assert mine and mine[0]["read_at"] and mine[0]["document_id"] == d.id


# ---------------------------------------------------------------------------
# an approved document is locked; its Word file is kept
# ---------------------------------------------------------------------------
class TestLocked:
    def test_a_correction_to_an_approved_component_is_refused(self, client, h, proj, db):
        if not hasattr(db, "_engine"):
            pytest.skip("the correction routes find the version in the engine database, which "
                        "the in-memory backend leaves empty; test_which_documents_lock_a_text "
                        "covers the rule on both")
        proj.doc("approved", "u2", group="Layer1.Util")
        url = "/api/v1/projects/%s/versions/%s/overrides/behaviour" % (proj.id, proj.vid)
        r = client.put(url, headers=h["bob"], json={"function_id": "Layer1.Util|util|utilCompute",
                                                    "external_caller_id": "x", "bullets": ["a"]})
        assert r.status_code == 409 and _code(r) == "DOCUMENT_APPROVED", r.text

    def test_which_documents_lock_a_text(self, proj):
        swe4 = proj.doc("approved", process="SWE.4", group="Layer1.Lib")
        proj.doc("in_review", group="Layer1.Util")
        hit = lambda fid: [d.id for d in rw.approved_of_component(
            proj.db, proj.id, proj.vid, fid.split("|")[0])]
        assert hit("Layer1.Lib|lib|libAdd") == [swe4.id]      # SWE.4 approved locks the labels too
        assert hit("Layer1.Util|util|utilCompute") == []
        with pytest.raises(Exception) as exc:
            rw.refuse_if_approved(proj.db, proj.id, proj.vid, function_id="Layer1.Lib|lib|libAdd")
        assert exc.value.status_code == 409

    def test_a_missing_kept_copy_is_an_error_not_the_working_file(self, client, h, proj, tmp_path,
                                                                    monkeypatch):
        """WORD_FILE_UPDATES §4.8: the working file may be one an update wrote after approval."""
        import hashlib
        from api.services import doc_render
        out = tmp_path / "out"
        working = out / "L1.W" / "software_detailed_design_L1.W.docx"
        working.parent.mkdir(parents=True)
        working.write_bytes(b"PK-rewritten-since")
        monkeypatch.setattr(doc_render, "commit_output_root", lambda *a, **k: out)
        d = proj.doc("approved", "u2", group="L1.W", approved_docx_path=str(tmp_path / "gone.docx"),
                     docx_sha256=hashlib.sha256(b"PK-the-approved-bytes").hexdigest())
        r = client.get("%s/%s/download" % (proj.base, d.id), headers=h["bob"])
        assert r.status_code == 409 and _code(r) == "APPROVED_FILE_MISSING", r.text
        r = client.get(proj.base + "/export-all/download", params={"version_id": proj.vid},
                       headers=h["bob"])
        assert r.status_code == 409 and r.json()["detail"]["document_ids"] == [d.id]
        # The working file IS the approved one: its hash says so, and it is served.
        working.write_bytes(b"PK-the-approved-bytes")
        r = client.get("%s/%s/download" % (proj.base, d.id), headers=h["bob"])
        assert r.status_code == 200 and r.content == b"PK-the-approved-bytes"

    def test_downloads_of_an_approved_document_serve_the_copy_kept(self, client, h, proj, tmp_path):
        kept = tmp_path / proj.id / "software_detailed_design_L1.Kept.docx"
        kept.parent.mkdir(parents=True)
        kept.write_bytes(b"PK-the-approved-bytes")
        d = proj.doc("approved", "u2", approved_docx_path=str(kept), docx_sha256="0" * 64)
        r = client.get("%s/%s/download" % (proj.base, d.id), headers=h["bob"])
        assert r.status_code == 200 and r.content == b"PK-the-approved-bytes"
        assert kept.name in r.headers["content-disposition"]


# ---------------------------------------------------------------------------
# a run: approvals of unchanged documents carry forward (contract §4)
# ---------------------------------------------------------------------------
class TestStartReview:
    def test_unchanged_keeps_its_approval_and_changed_goes_back_to_its_reviewer(self, proj, db):
        project = db.projects.get(proj.id)
        same = proj.doc("approved", "u2", group="L1.Same", approved_by="u1", approved_at=NOW,
                        content_fingerprint="fp-same")
        moved = proj.doc("approved", "u3", group="L1.Moved", approved_by="u1", approved_at=NOW,
                         content_fingerprint="fp-old")
        v2 = proj.version("v1.1", created=NOW + timedelta(days=1), baseline=proj.vid)
        new_same = proj.doc(group="L1.Same", vid=v2)
        new_moved = proj.doc(group="L1.Moved", vid=v2)
        new_comp = proj.doc(group="L1.New", vid=v2)
        fps = {new_same.id: "fp-same", new_moved.id: "fp-new", new_comp.id: "fp-x"}

        got = rw.start_review(db, project, db.versions.get(v2), [new_same, new_moved, new_comp],
                              fingerprint_fn=lambda _db, _p, d: fps.get(d.id),
                              freeze_fn=lambda _p, _v, _d: (None, "f" * 64))
        assert got == {"carried": 1, "in_review": 2}

        s = proj.get(new_same)
        assert (s.status, s.carried_from, s.approved_by, s.docx_sha256) == ("approved", proj.vid, "u1", "f" * 64)
        assert proj.kinds(new_same) == ["carried"]
        assert db.assignments.reviewers([new_same.id]) == {new_same.id: "u2"}

        m = proj.get(new_moved)
        assert m.status == "in_review" and m.carried_from is None
        assert db.assignments.reviewers([new_moved.id]) == {new_moved.id: "u3"}
        ev = db.review_events.list_for_document(new_moved.id)[0]
        assert (ev.kind, ev.payload) == ("generated", {"kept_reviewer_from": "v1.0"})
        assert any(n.type == "review_back_in_review" for n in db.notifications.list_unread("u3"))

        assert proj.get(new_comp).status == "in_review"
        assert db.assignments.reviewers([new_comp.id]) == {}
        assert db.versions.get(v2).status == "in_review"
        assert same.id and moved.id

    def test_an_approval_without_a_stored_fingerprint_carries_when_the_twin_renders_the_same(self, proj, db):
        # The 81 approvals made before the record have no fingerprint; and a change to how pages
        # are built must not stop an unchanged document from carrying: the twin is fingerprinted
        # again, with the code of today.
        project = db.projects.get(proj.id)
        old = proj.doc("approved", "u2", group="L1.Old", approved_by="u1", approved_at=NOW,
                       content_fingerprint=None)
        v2 = proj.version("v1.1", created=NOW + timedelta(days=1), baseline=proj.vid)
        new = proj.doc(group="L1.Old", vid=v2)
        got = rw.start_review(db, project, db.versions.get(v2), [new],
                              fingerprint_fn=lambda _db, _p, d: "same",
                              freeze_fn=lambda *_: (None, None))
        assert got["carried"] == 1 and proj.get(new).carried_from == proj.vid
        assert old.id

    def test_a_reviewer_who_left_is_not_kept(self, proj, db):
        project = db.projects.get(proj.id)
        proj.member("u5", status="pending")          # never accepted: not active
        proj.doc("in_review", "u5", group="L1.Gone")
        v2 = proj.version("v1.1", created=NOW + timedelta(days=1))   # no baseline: the previous version
        new = proj.doc(group="L1.Gone", vid=v2)
        rw.start_review(db, project, db.versions.get(v2), [new],
                        fingerprint_fn=lambda *_: None, freeze_fn=lambda *_: (None, None))
        assert db.assignments.reviewers([new.id]) == {}
        assert db.review_events.list_for_document(new.id)[0].payload == {}


# ---------------------------------------------------------------------------
# the database brought to the rules (migration 0015 and `analyzer.py setup`)
# ---------------------------------------------------------------------------
class TestRepair:
    def test_statuses_one_reviewer_and_a_record_idempotently(self):
        from sqlalchemy import create_engine, insert, select, text
        from api.db.postgres import schema as s
        from api.db.postgres.review_repair import repair_review

        eng = create_engine("sqlite://")
        s.metadata.create_all(eng)
        with eng.begin() as cx:
            cx.execute(text("DROP INDEX IF EXISTS uq_document_assignments_document"))
        # an older database: the table without its unique key (create_all made it with one)
        with eng.begin() as cx:
            cx.execute(text("CREATE TABLE da_old AS SELECT * FROM document_assignments"))
            cx.execute(text("DROP TABLE document_assignments"))
            cx.execute(text("ALTER TABLE da_old RENAME TO document_assignments"))
            cx.execute(insert(s.users).values(id="u1", email="a@x", name="A", initials="A",
                                              hashed_password="x", created_at=NOW))
            cx.execute(insert(s.projects).values(id="p", org_id="o", name="P", created_at=NOW,
                                                 updated_at=NOW))
            cx.execute(insert(s.versions).values(id="v", project_id="p", version="v1", created_at=NOW))
            for did, st in (("d1", "never"), ("d2", "unchanged"), ("d3", "approved"), ("d4", None),
                            ("d5", "submitted")):
                cx.execute(insert(s.documents).values(id=did, project_id="p", version_id="v",
                                                      status=st, updated_at=NOW))
            for aid, at in (("a1", NOW), ("a2", NOW + timedelta(hours=1)), ("a3", NOW - timedelta(hours=1))):
                cx.execute(insert(s.document_assignments).values(
                    id=aid, document_id="d1", user_id="u1", assigned_at=at))

        with eng.begin() as cx:
            first = repair_review(cx)
        with eng.begin() as cx:
            again = repair_review(cx)
        assert first == {"statuses": 3, "assignments": 2, "events": 1}
        assert again == {"statuses": 0, "assignments": 0, "events": 0}
        with eng.connect() as cx:
            st = dict(cx.execute(select(s.documents.c.id, s.documents.c.status)).fetchall())
            assert st == {"d1": "in_review", "d2": "in_review", "d3": "approved", "d4": "in_review",
                          "d5": "submitted"}
            assert [r.id for r in cx.execute(select(s.document_assignments))] == ["a2"]
            ev = cx.execute(select(s.document_review_events)).fetchall()
            assert [(e.document_id, e.kind, e.payload) for e in ev] == [("d3", "approved", {"before_record": True})]
        with pytest.raises(Exception):                       # one reviewer is now the rule
            with eng.begin() as cx:
                cx.execute(insert(s.document_assignments).values(
                    id="a9", document_id="d1", user_id="u1", assigned_at=NOW))


# ---------------------------------------------------------------------------
# registering a version's documents, however it was generated (contract §4, A17)
# ---------------------------------------------------------------------------
class TestRegister:
    @staticmethod
    def _output(tmp_path, monkeypatch, dirs):
        from api.services import doc_render
        out = tmp_path / "versions" / "v" / "output"
        for name, processes in dirs.items():
            (out / name).mkdir(parents=True)
            for proc in processes:
                prefix = doc_render.DOCX_PREFIX[proc]
                (out / name / ("%s_%s.docx" % (prefix, name))).write_bytes(b"PK")
        monkeypatch.setattr(doc_render, "commit_output_root", lambda *a, **k: out)
        return out

    def test_every_word_file_gets_one_document_named_from_the_config(self, proj, db, tmp_path, monkeypatch):
        from api.services.document_registry import register_documents
        self._output(tmp_path, monkeypatch, {"Layer1.Sample-Core": ("SWE.3", "SWE.4"),
                                             "Layer1.Util": ("SWE.3",), "Layer2.Odd-One": ("SWE.3",)})
        version = db.versions.get(proj.vid)
        version.resolved_config = {"layers": {"Layer1": {"groups": {"Main": {
            "Sample Core": ["core"], "Util": ["util"]}}}}}
        db.versions.update(version)
        project = db.projects.get(proj.id)
        new = register_documents(db, project, db.versions.get(proj.vid))
        got = sorted((d.process, d.group, d.name, d.layer) for d in new)
        assert got == [("SWE.3", "Layer1.Sample-Core", "Sample Core", "Layer1"),   # Layer2.Odd-One:
                       ("SWE.3", "Layer1.Util", "Util", "Layer1"),                 # no component
                       ("SWE.4", "Layer1.Sample-Core", "Sample Core", "Layer1")]   # declares it
        assert all(proj.kinds(d) == ["generated"] for d in new)               # their review is open
        assert db.versions.get(proj.vid).docs_count == 3
        # again: nothing new, nothing twice
        assert register_documents(db, project, db.versions.get(proj.vid)) == []
        listed, total = db.documents.list_for_project(proj.id, version_id=proj.vid, per_page=100)
        assert total == 3

    def test_with_no_configuration_anywhere_the_dirs_themselves_are_taken(self, proj, db, tmp_path, monkeypatch):
        from api.services.document_registry import register_documents
        self._output(tmp_path, monkeypatch, {"Layer1.Sample-Core": ("SWE.3",)})
        project = db.projects.get(proj.id)
        project.architecture_layers = []
        db.projects.update(project)
        new = register_documents(db, project, db.versions.get(proj.vid))
        assert [(d.group, d.name, d.layer) for d in new] == [("Layer1.Sample-Core", "Sample-Core", "Layer1")]

    def test_the_route_registers_and_says_what(self, client, h, proj, db, tmp_path, monkeypatch):
        self._output(tmp_path, monkeypatch, {"Layer1.Util": ("SWE.3", "SWE.4")})
        url = "/api/v1/projects/%s/versions/%s/documents/register" % (proj.id, proj.vid)
        assert client.post(url, headers=h["bob"]).status_code == 403
        r = client.post(url, headers=h["alice"])
        assert r.status_code == 200, r.text
        assert sorted(d["process"] for d in r.json()["registered"]) == ["SWE.3", "SWE.4"]
        assert r.json()["carried"] == 0
        assert client.post(url, headers=h["alice"]).json()["registered"] == []

    def test_a_reviewer_role_member_claims(self, client, h, proj):
        proj.member("u5", role="reviewer")
        d = proj.doc()
        r = client.post("%s/%s/assignments/self" % (proj.base, d.id), headers=h["eve"])
        assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# the team, the version's sources, "my reviews" (A14, A18, members)
# ---------------------------------------------------------------------------
class TestTeamAndMine:
    def test_members_show_their_open_reviews_in_the_latest_version(self, client, h, proj):
        proj.doc(reviewer="u2"), proj.doc("submitted", "u2"), proj.doc("approved", "u2"), proj.doc(reviewer="u3")
        r = client.get("/api/v1/projects/%s/members" % proj.id, headers=h["alice"])
        load = {m["user_id"]: m["open_reviews"] for m in r.json()["members"]}
        assert (load["u2"], load["u3"], load["u1"]) == (2, 1, 0)

    def test_a_role_is_one_of_three(self, client, h, proj):
        url = "/api/v1/projects/%s/members/u2/role" % proj.id
        assert client.patch(url, json={"role": "banana"}, headers=h["alice"]).status_code == 422
        assert client.patch(url, json={"role": "reviewer"}, headers=h["alice"]).status_code == 200
        r = client.post("/api/v1/projects/%s/members/invite" % proj.id, headers=h["alice"],
                        json={"email": "eve@aspice.dev", "role": "owner"})
        assert r.status_code == 422

    def test_a_member_who_leaves_stops_being_a_reviewer(self, client, h, proj, db):
        open_, done = proj.doc(reviewer="u2"), proj.doc("approved", "u2")
        r = client.delete("/api/v1/projects/%s/members/u2" % proj.id, headers=h["alice"])
        assert r.status_code == 204
        assert db.assignments.reviewers([open_.id, done.id]) == {done.id: "u2"}   # approved keeps it
        ev = db.review_events.list_for_document(open_.id)[0]
        assert ev.kind == "unassigned" and ev.payload["left_project"] is True

    def test_the_version_names_where_carried_approvals_came_from(self, client, h, proj):
        proj.doc("approved", "u2", carried_from=proj.vid)
        r = client.get("/api/v1/projects/%s/versions/%s" % (proj.id, proj.vid), headers=h["alice"])
        assert r.json()["version"]["review"]["carried_from"] == [{"version_id": proj.vid, "tag": "v1.0"}]

    def test_my_reviews_across_projects(self, client, h, proj, db):
        mine, done = proj.doc(reviewer="u3"), proj.doc("approved", "u3")
        r = client.get("/api/v1/reviews/mine", headers=h["carol"])
        assert r.status_code == 200
        got = {d["id"]: d for d in r.json()["documents"]}
        assert mine.id in got and done.id not in got
        assert got[mine.id]["project"] == {"id": proj.id, "name": db.projects.get(proj.id).name}
        assert got[mine.id]["version"] == {"id": proj.vid, "tag": "v1.0"}
        r = client.get("/api/v1/reviews/mine", params={"include_approved": "true"}, headers=h["carol"])
        assert done.id in {d["id"] for d in r.json()["documents"]}


class TestDueDate:
    def test_a_due_date_is_stored_and_cleared(self, client, h, proj, db):
        d = proj.doc()
        url = "%s/%s" % (proj.base, d.id)
        r = client.patch(url, json={"due_date": "2026-11-30"}, headers=h["alice"])
        assert r.status_code == 200 and r.json()["document"]["due_date"] == "2026-11-30"
        assert str(db.documents.get(d.id).due_date) == "2026-11-30"
        assert client.patch(url, json={"due_date": "soon"}, headers=h["alice"]).status_code == 422
        r = client.patch(url, json={"due_date": None}, headers=h["alice"])
        assert r.json()["document"]["due_date"] is None
