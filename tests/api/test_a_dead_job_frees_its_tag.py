"""A job that will never finish -- failed or cancelled -- gives its version tag back.

A job reserves its version (status `draft`) before it starts, and the job row points at it:
`analysis_jobs.version_id` is a foreign key with no ON DELETE. On failure the runner deleted the
draft so the tag was free for a retry -- but the job still pointed at it, so the database refused
the delete, and the refusal was swallowed. Every failed job kept its tag, and the retry answered
409 VERSION_EXISTS. Found running `{"scope": {"type": "group", "names": ["My Sample"]}, "version_tag":
"v1"}` after a failed `v1`.

The SQL backend runs with foreign keys on, as PostgreSQL does; that is where these failed. The
in-memory backend has no foreign keys and always let the delete through.

`DELETE /versions/{id}` had the same cause: every version a job had produced was undeletable.
"""
import datetime
import uuid
from unittest.mock import patch

import pytest

from api.models.domain import Project, ProjectMember

SHA = "8b3e313f892f2b3baea252d98f0b083015622e98"


def _project(db):
    pid = "ptg" + uuid.uuid4().hex[:6]
    now = datetime.datetime.now(datetime.timezone.utc)
    db.projects.create(Project(
        id=pid, org_id="org1", name=pid, client="c", compliance_standard="ASPICE_L2",
        repo_url="https://example.invalid/r.git", repo_provider="github",
        default_branch="main", build_config={},
        architecture_layers=[{"name": "L1", "groups": ["G1"]}],
        status="not_run", created_by="u1", created_at=now, updated_at=now))
    db.members.add_member(ProjectMember(
        id="m" + uuid.uuid4().hex[:8], project_id=pid, user_id="u1", role="admin",
        status="active", invited_by="u1", invited_at=now, joined_at=now))
    return pid


def _start(client, auth_header, pid, tag="v1"):
    with patch("api.services.pipeline_runner.start"):
        return client.post(f"/api/v1/projects/{pid}/jobs", headers=auth_header,
                           json={"commit_sha": SHA, "version_tag": tag, "mode": "full"})


@pytest.fixture
def started(client, db, auth_header):
    """A project with one queued job and the draft version it reserved."""
    pid = _project(db)
    r = _start(client, auth_header, pid)
    assert r.status_code == 202, r.text
    job = db.jobs.get(r.json()["job_id"])
    assert db.versions.get(job.version_id).status == "draft"
    return pid, job.id, job.version_id


class TestAFailedJob:
    def test_its_draft_is_deleted_and_the_tag_is_free(self, client, db, auth_header, started):
        from api.services.pipeline_runner import _mark_failed
        pid, job_id, vid = started
        _mark_failed(db, job_id, "run.py exited with code 2.")
        assert db.versions.get(vid) is None
        r = _start(client, auth_header, pid)          # the same tag, "v1"
        assert r.status_code == 202, r.text

    def test_the_job_is_kept_with_what_was_attempted(self, db, started):
        from api.services.pipeline_runner import _mark_failed
        _pid, job_id, _vid = started
        _mark_failed(db, job_id, "run.py exited with code 2.")
        job = db.jobs.get(job_id)
        assert (job.status, job.version_id, job.version_tag) == ("failed", None, "v1")
        assert job.error_message == "run.py exited with code 2."

    def test_a_failed_re_export_keeps_its_finished_version(self, db, started):
        """A re-export's job points at a version that was finished before it started."""
        from api.services.pipeline_runner import _mark_failed
        _pid, job_id, vid = started
        version = db.versions.get(vid)
        version.status = "complete"
        db.versions.update(version)
        _mark_failed(db, job_id, "re-export failed")
        assert db.versions.get(vid) is not None
        assert db.jobs.get(job_id).version_id == vid


class TestACancelledJob:
    def test_its_tag_is_free(self, client, db, auth_header, started):
        pid, job_id, vid = started
        r = client.post(f"/api/v1/projects/{pid}/jobs/{job_id}/cancel", headers=auth_header)
        assert r.status_code == 200, r.text
        assert r.json()["job"]["status"] == "cancelled"
        assert db.versions.get(vid) is None
        assert _start(client, auth_header, pid).status_code == 202


class TestDeletingAVersion:
    def test_a_version_a_job_produced_can_be_deleted(self, client, db, auth_header, started):
        pid, job_id, vid = started
        job = db.jobs.get(job_id)
        job.status = "complete"
        db.jobs.update(job)
        version = db.versions.get(vid)
        version.status = "complete"
        db.versions.update(version)
        r = client.delete(f"/api/v1/projects/{pid}/versions/{vid}", headers=auth_header)
        assert r.status_code == 204, r.text
        assert db.versions.get(vid) is None
        assert db.jobs.get(job_id).version_id is None, "the job is kept, without the version"
        assert _start(client, auth_header, pid).status_code == 202, "and its tag is free"

    def test_not_while_a_job_is_working_on_it(self, client, db, auth_header, started):
        pid, job_id, vid = started                    # queued
        r = client.delete(f"/api/v1/projects/{pid}/versions/{vid}", headers=auth_header)
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["code"] == "JOB_ACTIVE"
        assert job_id in r.json()["detail"]["message"]
        assert db.versions.get(vid) is not None
