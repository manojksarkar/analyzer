"""A run that fails or is cancelled deletes the draft version it reserved.

`analysis_jobs.version_id` is a foreign key to `versions.id` with no ON DELETE, so deleting the
draft while its own job still pointed at it was refused on a SQL database -- silently, as
best-effort cleanup. Every failed or cancelled run left an empty draft behind as the project's
newest version: the web app's Subbar showed it instead of the last good version, the Versions
page listed it, and its name could not be used for the retry.
"""
import datetime
import uuid
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
