"""Deleting a project leaves nothing of it behind, and never pulls it from under a running job.

The rows went (they cascade from `projects`), but `job_functions` has no foreign key and kept
every function of every run, and `workspaces/<project_id>/` -- a checkout per commit plus every
version's documents and diagrams -- stayed on disk.
"""
import datetime
import types
import uuid
from unittest.mock import patch

import pytest

from api.models.domain import AnalysisJob, AnalysisPhase, Project, ProjectMember


def _project(db):
    pid = "pdel" + uuid.uuid4().hex[:6]
    now = datetime.datetime.now(datetime.timezone.utc)
    db.projects.create(Project(
        id=pid, org_id="org1", name=pid, client="c", compliance_standard="ASPICE_L2",
        repo_url="https://example.invalid/r.git", repo_provider="github", default_branch="main",
        build_config={}, architecture_layers=[], status="not_run", created_by="u1",
        created_at=now, updated_at=now))
    db.members.add_member(ProjectMember(
        id="m" + uuid.uuid4().hex[:8], project_id=pid, user_id="u1", role="admin",
        status="active", invited_by="u1", invited_at=now, joined_at=now))
    return pid


def _settings(root):
    return types.SimpleNamespace(workspaces=root)


def test_the_workspace_folder_goes_with_the_project(db, client, auth_header, tmp_path):
    pid = _project(db)
    ws = tmp_path / pid
    (ws / "0123456789abcdef" / ".git").mkdir(parents=True)
    pack = ws / "0123456789abcdef" / ".git" / "pack"
    pack.write_bytes(b"x")
    pack.chmod(0o444)                                  # git keeps its packs read-only
    (tmp_path / "another-project").mkdir()

    with patch("api.services.settings.get_settings", return_value=_settings(tmp_path)):
        r = client.delete(f"/api/v1/projects/{pid}", headers=auth_header)

    assert r.status_code == 204, r.text
    assert not ws.exists()
    assert (tmp_path / "another-project").is_dir(), "only that project's folder is removed"


def test_its_job_functions_rows_go_too(db, client, auth_header, tmp_path):
    if not hasattr(db, "_engine"):
        pytest.skip("job_functions is a SQL table")
    from sqlalchemy import insert, select, func
    from api.db.postgres import schema as s
    pid = _project(db)
    with db._engine.begin() as cx:
        cx.execute(insert(s.job_functions), [{"id": "f" + uuid.uuid4().hex[:8], "job_id": "jobx",
                                              "project_id": pid, "name": "fn", "is_visible": True}])

    with patch("api.services.settings.get_settings", return_value=_settings(tmp_path)):
        r = client.delete(f"/api/v1/projects/{pid}", headers=auth_header)

    assert r.status_code == 204, r.text
    with db._engine.connect() as cx:
        left = cx.execute(select(func.count()).select_from(s.job_functions)
                          .where(s.job_functions.c.project_id == pid)).scalar()
    assert left == 0


def test_a_project_with_a_live_run_is_not_deleted(db, client, auth_header, tmp_path):
    pid = _project(db)
    now = datetime.datetime.now(datetime.timezone.utc)
    db.jobs.create(AnalysisJob(
        id="job" + uuid.uuid4().hex[:8], project_id=pid, commit_sha="0" * 40, version_id=None,
        reference_version_id=None, status="running", pause_after_phase1=False, layer_filter=None,
        phase=2, phase_pct=0, current_activity="", activity_detail="", elapsed_seconds=0,
        eta_seconds=None, phases=[AnalysisPhase(2, "Derive Model", "running", None)],
        started_at=now, completed_at=None, error_message=None))

    with patch("api.services.pipeline_runner.job_alive", return_value=True):
        r = client.delete(f"/api/v1/projects/{pid}", headers=auth_header)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "JOB_RUNNING"
    assert db.projects.get(pid) is not None

    # The same row left behind by a server that stopped mid-run blocks nothing.
    with patch("api.services.settings.get_settings", return_value=_settings(tmp_path)):
        r = client.delete(f"/api/v1/projects/{pid}", headers=auth_header)
    assert r.status_code == 204, r.text
