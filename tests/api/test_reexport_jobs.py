"""A re-export is a job of its own, addressed by version.

Two defects this replaces, both found testing the review feature's export step:

  * a re-export reused the version's GENERATION job and never changed its status, which stayed
    `complete` -- so polling it, or its live stream, said "finished" before anything ran, a
    failure was never recorded, and nothing stopped a second one starting on the same folder;
  * it was addressed by job id, and a client could find only the project's NEWEST job, so older
    versions could not be re-exported at all.

The engine step (`_do_reexport`) is replaced by a stand-in the test controls: what is under test
is the job's lifecycle, the one-at-a-time guard and the addressing, not the pipeline.
"""
import datetime
import threading
import uuid

import pytest

from api.models.domain import (AnalysisJob, AnalysisPhase, Project, ProjectMember, Version,
                               REEXPORT_MODE)
from api.services import pipeline_runner as pr

UTC = datetime.timezone.utc


def _uid(prefix):
    return prefix + uuid.uuid4().hex[:6]


def _project(db):
    pid = _uid("prx")
    now = datetime.datetime.now(UTC)
    db.projects.create(Project(
        id=pid, org_id="org1", name=pid, client="c", compliance_standard="ASPICE_L2",
        repo_url="C:/repo", repo_provider="github", default_branch="main", build_config={},
        architecture_layers=[{"name": "L1", "groups": ["G1"]}], status="in_review",
        created_by="u1", created_at=now, updated_at=now))
    db.members.add_member(ProjectMember(
        id=_uid("m"), project_id=pid, user_id="u1", role="admin", status="active",
        invited_by="u1", invited_at=now, joined_at=now))
    db.members.add_member(ProjectMember(
        id=_uid("m"), project_id=pid, user_id="u2", role="developer", status="active",
        invited_by="u1", invited_at=now, joined_at=now))
    return pid


def _version(db, pid, tag="v1", *, generation="complete", minutes_ago=0):
    """A version and, unless `generation` is None, the web-app job that generated it."""
    now = datetime.datetime.now(UTC) - datetime.timedelta(minutes=minutes_ago)
    vid = _uid("ver")
    db.versions.create(Version(
        id=vid, project_id=pid, tag=tag, commit_sha="a" * 40, branch="main",
        description="", status="in_review", docs_count=1, created_by="u1", created_at=now))
    if generation is not None:
        db.jobs.create(AnalysisJob(
            id=_uid("jobgen"), project_id=pid, commit_sha="a" * 40, version_id=vid,
            reference_version_id=None, status=generation, pause_after_phase1=False,
            layer_filter=None, phase=4, phase_pct=100, current_activity="Done",
            activity_detail="", elapsed_seconds=60, eta_seconds=0,
            phases=[AnalysisPhase(n, "p%d" % n, "done", 1) for n in (1, 2, 3, 4)],
            started_at=now, completed_at=now, error_message=None, branch="main",
            version_tag=tag, mode="full", scope={"type": "group", "names": ["G1"]},
            no_llm=True, data_dict_id=None, narrowed_parse=True))
    return vid


class _Engine:
    """Stands in for `_do_reexport`: holds until released, then succeeds, fails or raises."""

    def __init__(self, monkeypatch, outcome="ok"):
        self.release = threading.Event()
        self.entered = threading.Event()
        self.outcome = outcome

        def fake(db, job_id):
            self.entered.set()
            self.release.wait(20)
            if self.outcome == "raise":
                raise RuntimeError("engine blew up")
            if self.outcome == "fail":
                pr._mark_failed(db, job_id, "run.py exited with code 2.")
                return False
            return True
        monkeypatch.setattr(pr, "_do_reexport", fake)

    def finish(self, job_id):
        t = pr._reexport_threads.get(job_id)
        self.release.set()
        if t is not None:
            t.join(20)
            assert not t.is_alive(), "the re-export thread did not finish"


def _start(client, auth_header, pid, vid):
    return client.post(f"/api/v1/projects/{pid}/versions/{vid}/reexport", headers=auth_header)


def _job(client, auth_header, pid, job_id):
    return client.get(f"/api/v1/projects/{pid}/jobs/{job_id}", headers=auth_header).json()["job"]


class TestItIsAJobOfItsOwn:
    def test_it_answers_at_once_with_a_new_job(self, client, db, auth_header, monkeypatch):
        pid = _project(db)
        vid = _version(db, pid)
        engine = _Engine(monkeypatch)
        r = _start(client, auth_header, pid, vid)
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["version_id"] == vid and body["status"] == "queued"
        generation = [j for j in db.jobs.list_for_version(vid) if j.mode != REEXPORT_MODE][0]
        assert body["job_id"] != generation.id
        job = _job(client, auth_header, pid, body["job_id"])
        assert job["mode"] == REEXPORT_MODE and job["version_id"] == vid
        assert [p["number"] for p in job["phases"]] == [3, 4]
        engine.finish(body["job_id"])

    def test_its_status_moves_the_way_a_client_already_follows(self, client, db, auth_header,
                                                               monkeypatch):
        """THE POINT of #1: queued/running while it works, complete when it is done -- the
        states the web app's polling and live stream wait for."""
        pid = _project(db)
        vid = _version(db, pid)
        engine = _Engine(monkeypatch)
        job_id = _start(client, auth_header, pid, vid).json()["job_id"]
        assert engine.entered.wait(10)
        assert _job(client, auth_header, pid, job_id)["status"] == "running"
        engine.finish(job_id)
        job = _job(client, auth_header, pid, job_id)
        assert job["status"] == "complete" and job["completed_at"]
        assert all(p["status"] == "done" for p in job["phases"])

    def test_a_failure_is_recorded_with_its_reason(self, client, db, auth_header, monkeypatch):
        """It used to be lost: the failure path skipped a job that was already `complete`."""
        pid = _project(db)
        vid = _version(db, pid)
        engine = _Engine(monkeypatch, outcome="fail")
        job_id = _start(client, auth_header, pid, vid).json()["job_id"]
        engine.finish(job_id)
        job = _job(client, auth_header, pid, job_id)
        assert job["status"] == "failed" and "exited with code 2" in job["error_message"]

    def test_an_unexpected_error_is_recorded_too(self, client, db, auth_header, monkeypatch):
        pid = _project(db)
        vid = _version(db, pid)
        engine = _Engine(monkeypatch, outcome="raise")
        job_id = _start(client, auth_header, pid, vid).json()["job_id"]
        engine.finish(job_id)
        job = _job(client, auth_header, pid, job_id)
        assert job["status"] == "failed" and "engine blew up" in job["error_message"]

    def test_the_generation_job_is_left_alone(self, client, db, auth_header, monkeypatch):
        pid = _project(db)
        vid = _version(db, pid)
        engine = _Engine(monkeypatch, outcome="fail")
        job_id = _start(client, auth_header, pid, vid).json()["job_id"]
        engine.finish(job_id)
        generation = [j for j in db.jobs.list_for_version(vid) if j.mode != REEXPORT_MODE][0]
        assert generation.status == "complete" and generation.error_message is None

    def test_it_is_never_the_projects_current_job(self, client, db, auth_header, monkeypatch):
        """`GET /jobs/current` is the project's latest RUN; the project page reads it.

        The generation is minutes older on purpose: the re-export must be the NEWER job, or
        "latest wins" would return the generation for the wrong reason. Windows clocks can hand
        two jobs created milliseconds apart the same timestamp."""
        pid = _project(db)
        vid = _version(db, pid, minutes_ago=5)
        engine = _Engine(monkeypatch)
        job_id = _start(client, auth_header, pid, vid).json()["job_id"]
        current = client.get(f"/api/v1/projects/{pid}/jobs/current",
                             headers=auth_header).json()["job"]
        assert current["id"] != job_id and current["mode"] != REEXPORT_MODE
        engine.finish(job_id)

    def test_a_cancel_is_not_overwritten_by_the_finish(self, client, db, auth_header,
                                                       monkeypatch):
        pid = _project(db)
        vid = _version(db, pid)
        engine = _Engine(monkeypatch)
        job_id = _start(client, auth_header, pid, vid).json()["job_id"]
        assert engine.entered.wait(10)
        assert client.post(f"/api/v1/projects/{pid}/jobs/{job_id}/cancel",
                           headers=auth_header).status_code == 200
        engine.finish(job_id)
        assert _job(client, auth_header, pid, job_id)["status"] == "cancelled"


class TestOneAtATime:
    def test_a_second_request_is_refused_naming_the_running_job(self, client, db, auth_header,
                                                                monkeypatch):
        pid = _project(db)
        vid = _version(db, pid)
        engine = _Engine(monkeypatch)
        first = _start(client, auth_header, pid, vid).json()["job_id"]
        assert engine.entered.wait(10)
        r = _start(client, auth_header, pid, vid)
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["code"] == "REEXPORT_RUNNING"
        assert r.json()["detail"]["job_id"] == first
        engine.finish(first)

    def test_once_it_has_finished_another_may_start(self, client, db, auth_header, monkeypatch):
        pid = _project(db)
        vid = _version(db, pid)
        engine = _Engine(monkeypatch)
        engine.release.set()
        first = _start(client, auth_header, pid, vid).json()["job_id"]
        engine.finish(first)
        r = _start(client, auth_header, pid, vid)
        assert r.status_code == 202, r.text
        engine.finish(r.json()["job_id"])

    def test_a_row_left_running_by_a_stopped_server_does_not_block(self, client, db,
                                                                   auth_header, monkeypatch):
        """Nothing in this process is running it, so nothing will ever finish it."""
        pid = _project(db)
        vid = _version(db, pid)
        stale = _uid("jobstale")
        db.jobs.create(AnalysisJob(
            id=stale, project_id=pid, commit_sha="a" * 40, version_id=vid,
            reference_version_id=None, status="running", pause_after_phase1=False,
            layer_filter=None, phase=3, phase_pct=0, current_activity="", activity_detail="",
            elapsed_seconds=0, eta_seconds=None,
            phases=[AnalysisPhase(3, "Run Views", "running", None),
                    AnalysisPhase(4, "Export DOCX", "pending", None)],
            started_at=datetime.datetime.now(UTC), completed_at=None, error_message=None,
            branch="main", version_tag="v1", mode=REEXPORT_MODE))
        engine = _Engine(monkeypatch)
        r = _start(client, auth_header, pid, vid)
        assert r.status_code == 202, r.text
        old = db.jobs.get(stale)
        assert old.status == "failed" and "Interrupted" in old.error_message
        engine.finish(r.json()["job_id"])


class TestAnyVersion:
    def test_an_older_version_can_be_re_exported(self, client, db, auth_header, monkeypatch):
        """THE POINT of #2. v1 is not the project's newest version, nor its current job's."""
        pid = _project(db)
        older = _version(db, pid, "v1", minutes_ago=30)
        _version(db, pid, "v2")
        engine = _Engine(monkeypatch)
        r = _start(client, auth_header, pid, older)
        assert r.status_code == 202, r.text
        assert _job(client, auth_header, pid, r.json()["job_id"])["version_id"] == older
        engine.finish(r.json()["job_id"])

    def test_the_job_addressed_endpoint_starts_the_same_kind_of_job(self, client, db,
                                                                    auth_header, monkeypatch):
        """Kept for existing callers. Its `job_id` is now the NEW job, the one to follow."""
        pid = _project(db)
        vid = _version(db, pid)
        generation = db.jobs.list_for_version(vid)[0].id
        engine = _Engine(monkeypatch)
        r = client.post(f"/api/v1/projects/{pid}/jobs/{generation}/reexport",
                        headers=auth_header)
        assert r.status_code == 200, r.text
        new = r.json()["job_id"]
        assert new != generation
        assert _job(client, auth_header, pid, new)["mode"] == REEXPORT_MODE
        engine.finish(new)


class TestRefusals:
    def test_a_version_still_being_generated(self, client, db, auth_header, monkeypatch):
        _Engine(monkeypatch)
        pid = _project(db)
        vid = _version(db, pid, generation="running")
        r = _start(client, auth_header, pid, vid)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "VERSION_NOT_READY"

    def test_a_version_generated_with_the_cli(self, client, db, auth_header, monkeypatch):
        _Engine(monkeypatch)
        pid = _project(db)
        vid = _version(db, pid, generation=None)
        r = _start(client, auth_header, pid, vid)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "NO_GENERATION_JOB"
        assert "analyzer.py reexport" in r.json()["detail"]["message"]

    def test_another_projects_version(self, client, db, auth_header, monkeypatch):
        _Engine(monkeypatch)
        pid, other = _project(db), _project(db)
        vid = _version(db, other)
        assert _start(client, auth_header, pid, vid).status_code == 404

    def test_a_member_who_is_not_an_admin(self, client, db, dev_header, monkeypatch):
        _Engine(monkeypatch)
        pid = _project(db)
        vid = _version(db, pid)
        assert _start(client, dev_header, pid, vid).status_code == 403

    def test_a_generation_cannot_be_asked_to_be_a_reexport(self, client, db, auth_header):
        pid = _project(db)
        r = client.post(f"/api/v1/projects/{pid}/jobs", headers=auth_header,
                        json={"commit_sha": "a" * 40, "version_tag": "vx", "mode": REEXPORT_MODE})
        assert r.status_code == 400


class TestAReexportRegistersMissingDocuments:
    """A version generated while `_make_documents` matched output dirs by the bare component
    name has its DOCX files on disk and no `documents` rows -- since 1df3016 every web-app run.
    Re-exporting it is how it gets its document list back."""

    LAYERS = [{"name": "L1", "groups": [{"name": "G1", "components": [{"name": "Comp A"}]}]}]

    def _setup(self, db, monkeypatch, tmp_path):
        pid = _project(db)
        project = db.projects.get(pid)
        project.architecture_layers = self.LAYERS
        db.projects.update(project)
        vid = _version(db, pid)
        comp_dir = tmp_path / "output" / "L1.Comp-A"
        comp_dir.mkdir(parents=True)
        (comp_dir / "software_detailed_design_L1.Comp-A.docx").write_bytes(b"PK")
        monkeypatch.setattr(pr.doc_render, "commit_output_root",
                            lambda *a, **k: tmp_path / "output")
        return pid, vid

    def _reexport(self, client, auth_header, monkeypatch, pid, vid):
        engine = _Engine(monkeypatch)
        engine.release.set()
        r = _start(client, auth_header, pid, vid)
        assert r.status_code == 202, r.text
        engine.finish(r.json()["job_id"])
        return _job(client, auth_header, pid, r.json()["job_id"])

    def test_they_are_registered(self, client, db, auth_header, monkeypatch, tmp_path):
        pid, vid = self._setup(db, monkeypatch, tmp_path)
        job = self._reexport(client, auth_header, monkeypatch, pid, vid)
        assert job["status"] == "complete"
        docs, total = db.documents.list_for_project(pid, version_id=vid, per_page=50)
        assert total == 1
        assert (docs[0].name, docs[0].layer, docs[0].group) == ("Comp A", "L1", "L1.Comp-A")
        assert db.versions.get(vid).docs_count == 1

    def test_a_second_reexport_registers_nothing_twice(self, client, db, auth_header,
                                                       monkeypatch, tmp_path):
        pid, vid = self._setup(db, monkeypatch, tmp_path)
        self._reexport(client, auth_header, monkeypatch, pid, vid)
        self._reexport(client, auth_header, monkeypatch, pid, vid)
        assert db.documents.list_for_project(pid, version_id=vid, per_page=50)[1] == 1

    def test_a_failed_reexport_registers_nothing(self, client, db, auth_header, monkeypatch,
                                                 tmp_path):
        pid, vid = self._setup(db, monkeypatch, tmp_path)
        engine = _Engine(monkeypatch, outcome="fail")
        engine.release.set()
        r = _start(client, auth_header, pid, vid)
        engine.finish(r.json()["job_id"])
        assert db.documents.list_for_project(pid, version_id=vid, per_page=50)[1] == 0
