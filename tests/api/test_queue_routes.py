"""The queue over HTTP: submits answered with a place, the views, the limits, held jobs, and who may
do what (docs/spec/JOB_SCHEDULING_SPEC.md REQ-JS-04, 06, 09, 18, 22, 25, 26, 30-35).

Both backends. No scheduler runs here: a submit waits unless a test starts it, so each answer is
the queue's own. Each test makes its own project.
"""
import dataclasses
import datetime
import uuid

import pytest

from api.models.domain import (AnalysisJob, AnalysisPhase, JOB_STATUSES, Project, ProjectMember,
                               REEXPORT_MODE)
from api.services import job_queue as q
from api.services import pipeline_runner as pr
from tests.api.conftest import record_commit

UTC = datetime.timezone.utc
LAYERS = [{"name": "Layer1", "path": "Layer1", "groups": [{"name": "My Sample", "components": [
    {"name": "Sample Core", "files": ["Layer1/Sample/Core"]}]}]}]


def _now():
    return datetime.datetime.now(UTC)


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setattr(q, "_SETTINGS", {"maxGenerations": 10000,
                                         "startQueuedAfterRestart": False, "pausedDays": 7,
                                         "interruptedAfterMinutes": 10, "keepFinishedDays": 90})
    monkeypatch.setattr(q, "_try_start", lambda db, job: False)     # nothing starts by itself
    monkeypatch.setattr(q, "_kick", lambda: None)


@pytest.fixture
def superuser(db):
    """Alice a super admin for one test."""
    user = db.users.get_by_id("u1")
    db.users.update(dataclasses.replace(user, is_superuser=True))
    yield user.id
    db.users.update(dataclasses.replace(db.users.get_by_id("u1"), is_superuser=False))


@pytest.fixture
def project(db):
    """A project with layers; alice (u1) its admin, bob (u2) a developer. Its jobs end with the
    test: the session's database outlives it, and a later test's scheduler would start them."""
    pid = "pqr" + uuid.uuid4().hex[:6]
    db.projects.create(Project(
        id=pid, org_id="org1", name=pid, client="c", compliance_standard="ASPICE_L2",
        repo_url="https://example.invalid/r.git", repo_provider="github", default_branch="main",
        build_config={}, architecture_layers=LAYERS, status="not_run", created_by="u1",
        created_at=_now(), updated_at=_now()))
    for uid, role in (("u1", "admin"), ("u2", "developer")):
        db.members.add_member(ProjectMember(
            id="m" + uuid.uuid4().hex[:8], project_id=pid, user_id=uid, role=role,
            status="active", invited_by="u1", invited_at=_now(), joined_at=_now()))
    for sha in ("c" * 40, "d" * 40, "e" * 40):
        record_commit(db, pid, sha)
    yield db.projects.get(pid)
    for job in db.jobs.lane_jobs(pid, q.IN_LANE):
        db.jobs.transition(job.id, (job.status,), "removed")


@pytest.fixture
def dev_header(dev_token):
    return {"Authorization": f"Bearer {dev_token}"}


def _job(db, project, *, status="queued", mode="auto", started_by="u1", tag=None):
    job = AnalysisJob(
        id="job" + uuid.uuid4().hex[:8], project_id=project.id,
        commit_sha=uuid.uuid4().hex + "00000000", version_id="ver" + uuid.uuid4().hex[:8],
        reference_version_id=None, status="queued", pause_after_phase1=False, layer_filter=None,
        phase=1, phase_pct=0, current_activity="", activity_detail="", elapsed_seconds=0,
        eta_seconds=None, phases=[AnalysisPhase(1, "Parse C++", "pending", None)],
        started_at=None, completed_at=None, error_message=None,
        version_tag=tag or "v" + uuid.uuid4().hex[:4], mode=mode, started_by=started_by,
        submitted_at=_now())
    pr._reserve_version(db, job, project)
    db.jobs.create(job)
    if status != "queued":
        assert db.jobs.transition(job.id, JOB_STATUSES, status, started_at=_now())
    return db.jobs.get(job.id)


def _url(project, rest=""):
    return f"/api/v1/projects/{project.id}{rest}"


class TestSubmit:
    def test_a_generation_waits_with_its_place_and_a_message(self, client, auth_header, db,
                                                            project):
        running = _job(db, project, status="running")
        r = client.post(_url(project, "/jobs"), headers=auth_header,
                        json={"commit_sha": "c" * 40, "version_tag": "v-wait"})
        assert r.status_code == 202, r.text
        body = r.json()
        assert (body["status"], body["position"]) == ("queued", 1)
        assert body["message"].startswith("Waits as #1")
        assert [a["job_id"] for a in body["ahead"]] == [running.id]
        assert body["job"]["started_at"] is None and body["job"]["lane"] == "generation"

    def test_a_full_lane_is_refused_naming_the_jobs(self, client, auth_header, db, project):
        q.set_limits(db, project, "u1", generation_limit=1)
        running = _job(db, project, status="running")
        r = client.post(_url(project, "/jobs"), headers=auth_header,
                        json={"commit_sha": "c" * 40, "version_tag": "v-full"})
        assert r.status_code == 409, r.text
        detail = r.json()["detail"]
        assert detail["code"] == "LANE_FULL" and detail["running"][0]["job_id"] == running.id
        assert db.versions.get_by_tag(project.id, "v-full") is None, "its name is not taken"

    def test_a_retried_request_answers_its_first_job(self, client, auth_header, db, project):
        _job(db, project, status="running")
        key = {"Idempotency-Key": uuid.uuid4().hex}
        first = client.post(_url(project, "/jobs"), headers={**auth_header, **key},
                            json={"commit_sha": "d" * 40, "version_tag": "v-once"})
        again = client.post(_url(project, "/jobs"), headers={**auth_header, **key},
                            json={"commit_sha": "d" * 40, "version_tag": "v-once"})
        assert first.status_code == 202 and again.status_code == 202, again.text
        assert again.json()["job_id"] == first.json()["job_id"]

    def test_an_unknown_commit_is_refused_and_its_name_stays_free(self, client, auth_header, db,
                                                                   project):
        """REQ-JS-07: refused at submit, not hours later when the job starts."""
        r = client.post(_url(project, "/jobs"), headers=auth_header,
                        json={"commit_sha": "f" * 40, "version_tag": "v-typo"})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "UNKNOWN_COMMIT"
        assert db.versions.get_by_tag(project.id, "v-typo") is None

    def test_a_configuration_that_does_not_build_is_refused(self, client, auth_header, db,
                                                             project):
        twin = LAYERS[0]
        stored = db.projects.get(project.id)
        stored.architecture_layers = [twin, dict(twin)]          # one layer name, twice
        db.projects.update(stored)
        r = client.post(_url(project, "/jobs"), headers=auth_header,
                        json={"commit_sha": "c" * 40, "version_tag": "v-cfg"})
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["code"] == "CONFIG_INVALID"
        assert db.versions.get_by_tag(project.id, "v-cfg") is None

    def test_priority_is_a_super_admins(self, client, auth_header, project):
        r = client.post(_url(project, "/jobs"), headers=auth_header,
                        json={"commit_sha": "e" * 40, "version_tag": "v-pr", "priority": "high"})
        assert r.status_code == 403


class TestViews:
    def test_a_projects_queues(self, client, auth_header, db, project):
        running = _job(db, project, status="running")
        waiting = _job(db, project)
        r = client.get(_url(project, "/queues"), headers=auth_header)
        assert r.status_code == 200, r.text
        gen = r.json()["lanes"]["generation"]
        assert gen["limit"] == 3 and r.json()["lanes"]["update"]["limit"] == 10
        assert [j["job_id"] for j in gen["active"]] == [running.id]
        assert [(j["job_id"], j["position"]) for j in gen["waiting"]] == [(waiting.id, 1)]

    def test_the_preview_says_start_wait_or_refuse(self, client, auth_header, db, project):
        def preview():
            r = client.get(_url(project, "/queues/preview?lane=generation"), headers=auth_header)
            assert r.status_code == 200, r.text
            return r.json()
        assert preview()["answer"] == "start" and preview()["message"] == "Starts now"
        _job(db, project, status="running")
        assert (preview()["answer"], preview()["position"]) == ("wait", 1)
        _job(db, project)
        _job(db, project)
        got = preview()
        assert got["answer"] == "refuse" and got["code"] == "LANE_FULL"

    def test_every_queue_is_a_super_admins(self, client, auth_header, db, project, superuser):
        _job(db, project, status="running")
        r = client.get("/api/v1/queues", headers=auth_header)
        assert r.status_code == 200, r.text
        assert project.id in [p["project_id"] for p in r.json()["projects"]]

    def test_every_queue_is_403_to_others(self, client, auth_header):
        assert client.get("/api/v1/queues", headers=auth_header).status_code == 403

    def test_the_record(self, client, auth_header, db, project):
        q.set_limits(db, project, "u1", update_limit=4)
        r = client.get(_url(project, "/queues/events"), headers=auth_header)
        assert r.status_code == 200, r.text
        assert r.json()["events"][0]["kind"] == "limits_changed"


class TestLimits:
    def test_an_admin_changes_them(self, client, auth_header, db, project):
        r = client.patch(_url(project, "/job-limits"), headers=auth_header,
                         json={"generation_limit": 5, "update_limit": 20})
        assert r.status_code == 200, r.text
        assert (r.json()["generation_limit"], r.json()["update_limit"]) == (5, 20)
        assert db.projects.get(project.id).generation_limit == 5

    @pytest.mark.parametrize("value", [0, 51])
    def test_out_of_range_is_422(self, client, auth_header, project, value):
        r = client.patch(_url(project, "/job-limits"), headers=auth_header,
                         json={"generation_limit": value})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_LIMIT"

    def test_a_developer_does_not(self, client, dev_header, project):
        r = client.patch(_url(project, "/job-limits"), headers=dev_header,
                         json={"generation_limit": 5})
        assert r.status_code == 403


class TestActions:
    def test_a_developer_removes_their_own_waiting_job_and_not_anothers(
            self, client, dev_header, db, project):
        _job(db, project, status="running")
        mine = _job(db, project, started_by="u2")
        theirs = _job(db, project, started_by="u1")
        r = client.post(_url(project, f"/jobs/{theirs.id}/cancel"), headers=dev_header)
        assert r.status_code == 403
        r = client.post(_url(project, f"/jobs/{mine.id}/cancel"), headers=dev_header)
        assert r.status_code == 200, r.text
        assert r.json()["job"]["status"] == "removed"

    def test_an_update_is_not_paused(self, client, auth_header, db, project):
        update = _job(db, project, status="running", mode=REEXPORT_MODE)
        r = client.post(_url(project, f"/jobs/{update.id}/pause"), headers=auth_header)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "NOT_PAUSABLE"

    def test_a_running_generation_is_asked_to_pause(self, client, auth_header, db, project):
        gen = _job(db, project, status="running")
        r = client.post(_url(project, f"/jobs/{gen.id}/pause"), headers=auth_header)
        assert r.status_code == 200, r.text
        assert r.json()["job"]["pause_requested"] is True
        assert r.json()["job"]["current_activity"].startswith("Pausing")

    def test_priority_by_a_super_admin(self, client, auth_header, db, project, superuser):
        _job(db, project, status="running")
        waiting = _job(db, project)
        r = client.patch(_url(project, f"/jobs/{waiting.id}"), headers=auth_header,
                         json={"priority": "high"})
        assert r.status_code == 200, r.text
        assert r.json()["job"]["priority"] == "high"

    def test_priority_by_anyone_else_is_403(self, client, auth_header, db, project):
        waiting = _job(db, project)
        r = client.patch(_url(project, f"/jobs/{waiting.id}"), headers=auth_header,
                         json={"priority": "high"})
        assert r.status_code == 403


class TestDeletingAVersion:
    """Design §16: a waiting job stops a version's delete only when it needs that version."""

    def _delete(self, client, auth_header, project, version_id):
        return client.delete(_url(project, f"/versions/{version_id}"), headers=auth_header)

    def test_a_waiting_update_of_it_stops_it_naming_the_job(self, client, auth_header, db,
                                                           project):
        done = _job(db, project, status="complete")
        update = _job(db, project, mode=REEXPORT_MODE)
        assert db.jobs.transition(update.id, ("queued",), "queued", version_id=done.version_id)
        r = self._delete(client, auth_header, project, done.version_id)
        assert r.status_code == 409, r.text
        detail = r.json()["detail"]
        assert detail["code"] == "VERSION_NEEDED"
        assert [j["job_id"] for j in detail["jobs"]] == [update.id]
        assert update.id in detail["message"]

    def test_a_waiting_generation_built_on_it_stops_it(self, client, auth_header, db, project):
        done = _job(db, project, status="complete")
        later = _job(db, project)
        assert db.jobs.transition(later.id, ("queued",), "queued",
                                  reference_version_id=done.version_id)
        r = self._delete(client, auth_header, project, done.version_id)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "VERSION_NEEDED"
        assert "builds on it" in r.json()["detail"]["message"]

    def test_other_waiting_jobs_do_not(self, client, auth_header, db, project):
        done = _job(db, project, status="complete")
        _job(db, project)                     # waits, its baseline left to the engine
        r = self._delete(client, auth_header, project, done.version_id)
        assert r.status_code == 204, r.text
        assert db.versions.get(done.version_id) is None

    def test_a_run_at_work_in_the_project_stops_it(self, client, auth_header, db, project):
        done = _job(db, project, status="complete")
        running = _job(db, project, status="running")
        r = self._delete(client, auth_header, project, done.version_id)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "RUN_ACTIVE"
        assert [j["job_id"] for j in r.json()["detail"]["jobs"]] == [running.id]


class TestHeld:
    def test_a_super_admin_clears_some_and_starts_the_rest(self, client, auth_header, db,
                                                           project, superuser):
        _job(db, project, status="running")
        a, b = _job(db, project, status="held"), _job(db, project, status="held")
        r = client.post("/api/v1/queues/held", headers=auth_header,
                        json={"project_id": project.id, "remove": [a.id]})
        assert r.status_code == 200, r.text
        assert r.json() == {"removed": [a.id], "released": [b.id]}
        assert db.jobs.get(b.id).status == "queued"

    def test_nobody_else_does(self, client, auth_header, project):
        r = client.post("/api/v1/queues/held", headers=auth_header,
                        json={"project_id": project.id, "remove": "all"})
        assert r.status_code == 403
