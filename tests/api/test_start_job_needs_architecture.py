"""A run cannot start from the web app on a project with no architecture in the database.

That is every project onboarded with `analyzer.py onboard`: its layers are in
workspaces/<pid>/config.json, which onboarding wrote, and its database row has none. The runner
builds the config from the database, so a run REPLACED that file with the built-in sample
project's layers -- before failing -- and `_make_documents` creates documents only for components
declared in the database, so even a run that worked would have produced none.

Refused up front instead: no job, no reserved version, nothing written.
"""
import datetime
import uuid
from unittest.mock import patch

import pytest

from api.models.domain import Project, ProjectMember

BODY = {"commit_sha": "8b3e313f892f2b3baea252d98f0b083015622e98", "version_tag": "t-arch"}


def _project(db, layers):
    """A project alice administers, created in the database directly -- `POST /projects` would
    also write a real workspaces/<pid>/ folder, which a test has no business leaving behind."""
    pid = "pna" + uuid.uuid4().hex[:6]
    now = datetime.datetime.now(datetime.timezone.utc)
    db.projects.create(Project(
        id=pid, org_id="org1", name=pid, client="c", compliance_standard="ASPICE_L2",
        repo_url="https://example.invalid/r.git", repo_provider="github",
        default_branch="main", build_config={}, architecture_layers=layers,
        status="not_run", created_by="u1", created_at=now, updated_at=now))
    db.members.add_member(ProjectMember(
        id="m" + uuid.uuid4().hex[:8], project_id=pid, user_id="u1", role="admin",
        status="active", invited_by="u1", invited_at=now, joined_at=now))
    return pid


@pytest.mark.parametrize("layers", [None, []], ids=["null", "empty"])
class TestAProjectWithNoArchitectureIsRefused:
    def test_409_naming_the_cli(self, client, db, auth_header, layers):
        pid = _project(db, layers)
        with patch("api.services.pipeline_runner.start") as start:
            r = client.post(f"/api/v1/projects/{pid}/jobs", headers=auth_header, json=BODY)
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["code"] == "NO_ARCHITECTURE"
        assert "analyzer.py generate" in r.json()["detail"]["message"]
        start.assert_not_called()

    def test_nothing_is_created(self, client, db, auth_header, layers):
        pid = _project(db, layers)
        with patch("api.services.pipeline_runner.start"), \
                patch("api.services.pipeline_runner._reserve_version") as reserve:
            client.post(f"/api/v1/projects/{pid}/jobs", headers=auth_header, json=BODY)
        reserve.assert_not_called()
        assert client.get(f"/api/v1/projects/{pid}/jobs/current",
                          headers=auth_header).json() == {"job": None}
        assert client.get(f"/api/v1/projects/{pid}/versions",
                          headers=auth_header).json()["versions"] == []


def test_a_project_with_an_architecture_still_starts(client, db, auth_header):
    """The guard is about the missing architecture, not about starting runs."""
    pid = _project(db, [{"name": "L1", "groups": ["G1"]}])
    with patch("api.services.pipeline_runner.start") as start:
        r = client.post(f"/api/v1/projects/{pid}/jobs", headers=auth_header, json=BODY)
    assert r.status_code == 202, r.text
    start.assert_called_once()
