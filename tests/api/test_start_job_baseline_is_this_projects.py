"""A job's baseline (`reference_version_id`) is one of THIS project's versions.

976ee0f's rule for version ids: resolved inside their project, never another project's. The
web API's start-job route passed the baseline on unchecked. The engine refused a foreign id and
picked a baseline itself -- `--base-version` resolves inside the project -- but the runner's
`_load_and_register_functions` read that version's function list to mark which functions are
new: another project's model.
"""
import datetime
import uuid
from unittest.mock import patch

from api.models.domain import Project, ProjectMember, Version

LAYERS = [{"name": "L1", "groups": [{"name": "G1", "components": [{"name": "C1"}]}]}]


def _project(db, name):
    pid = name + uuid.uuid4().hex[:6]
    now = datetime.datetime.now(datetime.timezone.utc)
    db.projects.create(Project(
        id=pid, org_id="org1", name=pid, client="c", compliance_standard="ASPICE_L2",
        repo_url="https://example.invalid/r.git", repo_provider="github",
        default_branch="main", build_config={}, architecture_layers=LAYERS,
        status="in_review", created_by="u1", created_at=now, updated_at=now))
    db.members.add_member(ProjectMember(
        id="m" + uuid.uuid4().hex[:8], project_id=pid, user_id="u1", role="admin",
        status="active", invited_by="u1", invited_at=now, joined_at=now))
    vid = "ver" + uuid.uuid4().hex[:8]
    db.versions.create(Version(
        id=vid, project_id=pid, tag="v1", commit_sha="a" * 40, branch="main", description="",
        status="in_review", docs_count=0, created_by="u1", created_at=now))
    return pid, vid


def _start(client, auth_header, pid, reference):
    body = {"commit_sha": "b" * 40, "version_tag": "v2", "mode": "auto"}
    if reference is not None:
        body["reference_version_id"] = reference
    with patch("api.services.pipeline_runner.start"):        # queue it, run nothing
        return client.post(f"/api/v1/projects/{pid}/jobs", headers=auth_header, json=body)


def _stored_reference(client, auth_header, pid, response):
    job = client.get(f"/api/v1/projects/{pid}/jobs/{response.json()['job_id']}",
                     headers=auth_header).json()["job"]
    return job["reference_version_id"]


class TestTheBaselineIsThisProjects:
    def test_another_projects_version_is_refused(self, client, db, auth_header):
        mine, _my_v1 = _project(db, "pa")
        _other, their_v1 = _project(db, "pb")
        r = _start(client, auth_header, mine, their_v1)
        assert r.status_code == 404, r.text
        assert their_v1 in r.text and mine in r.text
        assert client.get(f"/api/v1/projects/{mine}/jobs/current",
                          headers=auth_header).json() == {"job": None}, "nothing was queued"

    def test_its_own_version_id_is_kept(self, client, db, auth_header):
        mine, my_v1 = _project(db, "pa")
        r = _start(client, auth_header, mine, my_v1)
        assert r.status_code == 202, r.text
        assert _stored_reference(client, auth_header, mine, r) == my_v1

    def test_its_own_version_name_is_resolved_to_the_id(self, client, db, auth_header):
        """Both projects have a `v1`; the name resolves to THIS project's."""
        mine, my_v1 = _project(db, "pa")
        _project(db, "pb")
        r = _start(client, auth_header, mine, "v1")
        assert r.status_code == 202, r.text
        assert _stored_reference(client, auth_header, mine, r) == my_v1

    def test_no_baseline_is_still_no_baseline(self, client, db, auth_header):
        mine, _ = _project(db, "pa")
        r = _start(client, auth_header, mine, None)
        assert r.status_code == 202, r.text
        assert _stored_reference(client, auth_header, mine, r) is None
