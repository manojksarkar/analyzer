"""A run that fails or is cancelled deletes the draft version it reserved.

`analysis_jobs.version_id` is a foreign key to `versions.id` with no ON DELETE, so deleting the
draft while its own job still pointed at it was refused on a SQL database -- silently, as
best-effort cleanup. Every failed or cancelled run left an empty draft behind as the project's
newest version: the web app's Subbar showed it instead of the last good version, the Versions
page listed it, and its name could not be used for the retry.
"""
import datetime
import uuid

import pytest
from unittest.mock import patch

from api.models.domain import AnalysisJob, AnalysisPhase, Project, ProjectMember, Version
from api.services import pipeline_runner as pr

LAYERS = [{"name": "Layer1", "path": "Layer1", "groups": [{"name": "My Sample", "components": [
    {"name": "Sample Core", "files": ["Layer1/Sample/Core"]}]}]}]


def _project(db):
    pid = "pfr" + uuid.uuid4().hex[:6]
    now = datetime.datetime.now(datetime.timezone.utc)
    project = Project(
        id=pid, org_id="org1", name=pid, client="c", compliance_standard="ASPICE_L2",
        repo_url="https://example.invalid/r.git", repo_provider="github",
        default_branch="main", build_config={}, architecture_layers=LAYERS,
        status="not_run", created_by="u1", created_at=now, updated_at=now)
    db.projects.create(project)
    return project


def _job(db, project, tag):
    """A job as `POST /jobs` creates it: the draft version first, then the job pointing at it."""
    now = datetime.datetime.now(datetime.timezone.utc)
    job = AnalysisJob(
        id="job" + uuid.uuid4().hex[:8], project_id=project.id, commit_sha="0" * 40,
        version_id="ver" + uuid.uuid4().hex[:8], reference_version_id=None, status="running",
        pause_after_phase1=False, layer_filter=None, phase=1, phase_pct=0,
        current_activity="", activity_detail="", elapsed_seconds=0, eta_seconds=None,
        phases=[AnalysisPhase(1, "Parse C++", "running", None)],
        started_at=now, completed_at=None, error_message=None, version_tag=tag)
    pr._reserve_version(db, job, project)
    db.jobs.create(job)
    return job


class TestAnUnfinishedRunFreesItsVersion:
    def test_a_failed_run_deletes_its_draft(self, db):
        project = _project(db)
        job = _job(db, project, "v1.0.0")
        vid = job.version_id
        assert db.versions.get(vid) is not None

        pr._mark_failed(db, job.id, "run.py exited with code 2.")

        assert db.versions.get(vid) is None
        assert db.versions.get_by_tag(project.id, "v1.0.0") is None, "the name is free to retry"
        failed = db.jobs.get(job.id)
        assert failed.status == "failed"
        assert failed.error_message == "run.py exited with code 2."
        assert failed.version_id is None
        assert failed.version_tag == "v1.0.0", "the job still says what it was generating"

    def test_a_cancelled_run_deletes_its_draft_once_the_runner_stops(self, db):
        project = _project(db)
        job = _job(db, project, "v2.0.0")
        vid = job.version_id
        job.status = "cancelled"          # what the cancel route writes
        db.jobs.update(job)

        with patch.object(pr, "_inner_run"):
            pr._run(db, job.id)

        assert db.versions.get(vid) is None
        assert db.jobs.get(job.id).status == "cancelled"

    def test_a_finished_version_is_never_deleted(self, db):
        project = _project(db)
        job = _job(db, project, "v3.0.0")
        vid = job.version_id
        version = db.versions.get(vid)
        version.status = "in_review"      # what _make_version writes at completion
        db.versions.update(version)

        pr._release_draft_version(db, db.jobs.get(job.id))

        assert db.versions.get(vid) is not None
        assert db.jobs.get(job.id).version_id == vid

    def test_a_run_that_completes_keeps_its_version(self, db):
        project = _project(db)
        job = _job(db, project, "v4.0.0")
        vid = job.version_id
        job.status = "complete"
        db.jobs.update(job)

        with patch.object(pr, "_inner_run"):
            pr._run(db, job.id)

        assert isinstance(db.versions.get(vid), Version)

    def test_cancelling_a_job_no_thread_runs_deletes_its_draft(self, db, client, auth_header):
        """A job left `running` by a server that stopped mid-run has no runner thread, so the
        runner's own cleanup never comes: the cancel does it."""
        project = _project(db)
        now = datetime.datetime.now(datetime.timezone.utc)
        db.members.add_member(ProjectMember(
            id="m" + uuid.uuid4().hex[:8], project_id=project.id, user_id="u1", role="admin",
            status="active", invited_by="u1", invited_at=now, joined_at=now))
        job = _job(db, project, "v5.0.0")
        vid = job.version_id
        assert not pr.job_alive(job.id)

        r = client.post(f"/api/v1/projects/{project.id}/jobs/{job.id}/cancel", headers=auth_header)

        assert r.status_code == 200, r.text
        assert db.versions.get(vid) is None
        assert db.jobs.get(job.id).status == "cancelled"


class TestAJobAStoppedServerLeftRunning:
    """At start-up every job still marked queued, running or paused belongs to a server that
    stopped mid-run: no thread of the new process runs it (`fail_interrupted_jobs`). It used to say
    "running" for ever, and every new run of its project was refused as JOB_ALREADY_RUNNING."""

    def test_it_is_failed_with_the_reason_and_frees_its_draft(self, db, monkeypatch):
        project = _project(db)
        job = _job(db, project, "v9.0.0")
        vid = job.version_id
        assert job.id in [j.id for j in db.jobs.list_active()]
        # Every other job in this session's database is left as it is.
        monkeypatch.setattr(pr, "job_alive", lambda job_id: job_id != job.id)

        assert pr.fail_interrupted_jobs(db) == 1

        failed = db.jobs.get(job.id)
        assert failed.status == "failed" and failed.error_message == pr.INTERRUPTED_MESSAGE
        assert failed.completed_at is not None
        assert db.versions.get(vid) is None, "the draft is freed, as a cancel of a dead job does"
        assert job.id not in [j.id for j in db.jobs.list_active()]

    def test_a_job_this_process_runs_is_left_alone(self, db, monkeypatch):
        project = _project(db)
        job = _job(db, project, "v9.1.0")
        monkeypatch.setattr(pr, "job_alive", lambda job_id: True)
        assert pr.fail_interrupted_jobs(db) == 0
        assert db.jobs.get(job.id).status == "running"

    def test_a_reexport_left_running_keeps_its_version(self, db, monkeypatch):
        """A re-export runs on a finished version; failing it must not delete the version."""
        project = _project(db)
        job = _job(db, project, "v9.2.0")
        version = db.versions.get(job.version_id)
        version.status = "in_review"
        db.versions.update(version)
        monkeypatch.setattr(pr, "job_alive", lambda job_id: job_id != job.id)

        pr.fail_interrupted_jobs(db)

        assert db.jobs.get(job.id).status == "failed"
        assert db.versions.get(job.version_id) is not None

    def test_the_api_does_it_at_start_up(self):
        import inspect
        from api import main
        assert "_fail_interrupted_jobs(_db)" in inspect.getsource(main._db_startup_check)

    def test_a_job_started_after_this_process_is_its_own(self, db, monkeypatch):
        """The check may run late -- tried again while the database does not answer -- and a job
        started meanwhile is this process's own, between its row and its thread."""
        import datetime
        project = _project(db)
        job = _job(db, project, "v9.3.0")
        monkeypatch.setattr(pr, "job_alive", lambda job_id: job_id != job.id)
        an_hour_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
        assert pr.fail_interrupted_jobs(db, before=an_hour_ago) == 0
        assert db.jobs.get(job.id).status == "running"

    def test_a_check_that_could_not_run_is_tried_again(self, monkeypatch):
        """Only this check follows a background run again after a restart: one missed try (the
        database slow to answer) left the job "running" for ever with nothing following it."""
        import threading
        from api import main
        calls, done = [], threading.Event()

        def sweep(db, before=None):
            calls.append(before)
            if len(calls) < 3:
                raise RuntimeError("connection timeout expired")
            done.set()
            return 0
        monkeypatch.setattr(pr, "fail_interrupted_jobs", sweep)
        monkeypatch.setattr(main, "JOB_SWEEP_RETRY_SECONDS", 0.05)
        db = type("Db", (), {"_engine": None})()
        assert main._fail_interrupted_jobs(db) is False
        main._sweep_until_done(db)
        assert done.wait(10) and len(calls) == 3
        assert calls[-1] == pr.PROCESS_STARTED


class TestOnlyTheOnlyServerSweeps:
    """A second API server on the same database runs jobs of its own; failing them would delete
    the draft versions it is still generating. Start-up sweeps only when this process holds the
    runner lock (`claim_job_runner`), which PostgreSQL frees when a server ends, however it ends."""

    class _Conn:
        def __init__(self, got):
            self.got, self.closed, self.sql = got, False, []

        def execute(self, stmt, params=None):
            self.sql.append((str(stmt), params))
            return type("R", (), {"scalar": lambda _self: self.got})()

        def commit(self):
            pass

        def close(self):
            self.closed = True

    def _engine(self, got):
        conn = self._Conn(got)
        engine = type("E", (), {"dialect": type("D", (), {"name": "postgresql"})(),
                                "connect": lambda _self: conn})()
        return engine, conn

    def test_the_only_server_takes_the_lock_and_keeps_it(self, monkeypatch):
        monkeypatch.setattr(pr, "_runner_conn", None)
        engine, conn = self._engine(True)
        assert pr.claim_job_runner(engine) is True
        assert "pg_try_advisory_lock" in conn.sql[0][0] and not conn.closed
        assert pr._runner_conn is conn, "held for the life of the process"

    def test_a_second_server_does_not_sweep(self, monkeypatch):
        monkeypatch.setattr(pr, "_runner_conn", None)
        engine, conn = self._engine(False)
        assert pr.claim_job_runner(engine) is False
        assert conn.closed and pr._runner_conn is None

    def test_start_up_leaves_the_jobs_alone_then(self, monkeypatch):
        from api import main
        engine, _conn = self._engine(False)
        monkeypatch.setattr(pr, "_runner_conn", None)
        monkeypatch.setattr(pr, "fail_interrupted_jobs", lambda db: pytest.fail("swept"))
        main._fail_interrupted_jobs(type("Db", (), {"_engine": engine})())

    def test_sqlite_serves_one_process(self, monkeypatch):
        monkeypatch.setattr(pr, "_runner_conn", None)
        engine = type("E", (), {"dialect": type("D", (), {"name": "sqlite"})()})()
        assert pr.claim_job_runner(engine) is True


class TestCancelAfterTheReview:
    """Cancel had three gaps (review, 2026-10-04)."""

    def _admin(self, db, project):
        now = datetime.datetime.now(datetime.timezone.utc)
        db.members.add_member(ProjectMember(
            id="m" + uuid.uuid4().hex[:8], project_id=project.id, user_id="u1", role="admin",
            status="active", invited_by="u1", invited_at=now, joined_at=now))

    def test_a_job_that_has_ended_is_not_cancelled(self, db, client, auth_header):
        project = _project(db)
        self._admin(db, project)
        job = _job(db, project, "v9.4.0")
        job.status = "failed"                     # stopped, its work kept for `resume`
        db.jobs.update(job)
        r = client.post(f"/api/v1/projects/{project.id}/jobs/{job.id}/cancel", headers=auth_header)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "JOB_FINISHED"
        assert db.versions.get(job.version_id) is not None

    def test_an_unfollowed_run_is_stopped_before_its_draft_goes(self, db, client, auth_header,
                                                               monkeypatch):
        project = _project(db)
        self._admin(db, project)
        job = _job(db, project, "v9.5.0")
        order = []
        monkeypatch.setattr(pr, "stop_background_run", lambda j: order.append("stop") or True)
        real = pr._release_draft_version
        monkeypatch.setattr(pr, "_release_draft_version",
                            lambda d, j: order.append("release") or real(d, j))
        r = client.post(f"/api/v1/projects/{project.id}/jobs/{job.id}/cancel", headers=auth_header)
        assert r.status_code == 200 and order == ["stop", "release"]


class TestTheJobWatch:
    def test_it_looks_again_every_few_minutes_at_jobs_older_than_two(self, monkeypatch):
        """A follower thread that died left its job "running" until the next restart."""
        import datetime
        import threading
        from api import main
        seen, done = [], threading.Event()

        stop = threading.Event()

        def sweep(db, before=None, reattach_only=False):
            seen.append((before, reattach_only))
            stop.set()                   # ends the watch thread: nothing outlives this test
            done.set()
            return 0
        monkeypatch.setattr(pr, "fail_interrupted_jobs", sweep)
        monkeypatch.setattr(main, "JOB_WATCH_SECONDS", 0.05)
        main._watch_jobs(type("Db", (), {"_engine": None})(), stop=stop)
        assert done.wait(10)
        before, reattach_only = seen[0]
        assert reattach_only, "the periodic pass only follows runs again; start-up decides the rest"
        age = datetime.datetime.now(datetime.timezone.utc) - before
        assert datetime.timedelta(seconds=110) < age < datetime.timedelta(seconds=180)


class TestDiscardingAStoppedRun:
    """A stopped run's version is kept for `resume`; when nobody wants it, deleting it is how it
    goes. The delete failed with a 500: the job still pointed at the version (no ON DELETE)."""

    def _admin(self, db, project):
        now = datetime.datetime.now(datetime.timezone.utc)
        db.members.add_member(ProjectMember(
            id="m" + uuid.uuid4().hex[:8], project_id=project.id, user_id="u1", role="admin",
            status="active", invited_by="u1", invited_at=now, joined_at=now))

    def test_a_stopped_run_s_version_can_be_deleted(self, db, client, auth_header):
        project = _project(db)
        self._admin(db, project)
        job = _job(db, project, "v9.6.0")
        job.status = "failed"                          # stopped, its work kept
        db.jobs.update(job)
        vid = job.version_id
        r = client.delete(f"/api/v1/projects/{project.id}/versions/{vid}", headers=auth_header)
        assert r.status_code == 204, r.text
        assert db.versions.get(vid) is None
        assert db.jobs.get(job.id).version_id is None and db.jobs.get(job.id).version_tag == "v9.6.0"

    def test_not_while_its_run_is_at_work(self, db, client, auth_header):
        project = _project(db)
        self._admin(db, project)
        job = _job(db, project, "v9.7.0")               # running
        r = client.delete(f"/api/v1/projects/{project.id}/versions/{job.version_id}",
                          headers=auth_header)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "RUN_ACTIVE"
        assert db.versions.get(job.version_id) is not None

    def test_not_while_a_later_version_builds_on_it(self, db, client, auth_header):
        project = _project(db)
        self._admin(db, project)
        base = _job(db, project, "v9.8.0")
        base.status = "complete"
        db.jobs.update(base)
        later = _job(db, project, "v9.9.0")
        later.status = "complete"
        db.jobs.update(later)
        v = db.versions.get(later.version_id)
        v.baseline_version_id = base.version_id
        db.versions.update(v)
        r = client.delete(f"/api/v1/projects/{project.id}/versions/{base.version_id}",
                          headers=auth_header)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "VERSION_IS_BASELINE"
