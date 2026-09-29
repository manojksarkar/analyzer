"""The data dictionary uploaded in the New Project wizard reaches the run.

Two links were missing. A job started from the web app never named a dictionary -- the Run
modal sends none, and the route did not fall back to the project's own -- and when a job did
name one, the runner read its bytes from a `data` key of the in-memory upload record that is
never set (uploads are stored on disk), logged "no content on this node" and ran without it.
"""
import datetime
import types
import uuid
from unittest.mock import patch

import pytest

from api.models.domain import Project, ProjectMember
from api.routes import repositories
from api.services import pipeline_runner as pr

CSV = b"Name,Type,Min,Max\nsig_a,uint8,0,255\n"
LAYERS = [{"name": "Layer1", "path": "Layer1", "groups": [{"name": "G", "components": [
    {"name": "C", "files": ["Layer1/C/c.cpp"]}]}]}]


@pytest.fixture
def uploads_root(tmp_path, monkeypatch):
    """The upload store in a tmp dir, so the test never writes into the real workspaces/."""
    monkeypatch.setattr(repositories, "_upload_dir", lambda upload_id: tmp_path / "uploads" / upload_id)
    repositories._UPLOADS.clear()
    return tmp_path


def _project(db, build_config):
    pid = "pdd" + uuid.uuid4().hex[:6]
    now = datetime.datetime.now(datetime.timezone.utc)
    db.projects.create(Project(
        id=pid, org_id="org1", name=pid, client="c", compliance_standard="ASPICE_L2",
        repo_url="https://example.invalid/r.git", repo_provider="github", default_branch="main",
        build_config=build_config, architecture_layers=LAYERS, status="not_run",
        created_by="u1", created_at=now, updated_at=now))
    db.members.add_member(ProjectMember(
        id="m" + uuid.uuid4().hex[:8], project_id=pid, user_id="u1", role="admin",
        status="active", invited_by="u1", invited_at=now, joined_at=now))
    return pid


def _start(client, auth_header, pid, **body):
    with patch("api.services.pipeline_runner.start"):            # no real run
        r = client.post(f"/api/v1/projects/{pid}/jobs", headers=auth_header,
                        json={"commit_sha": "0" * 40, "version_tag": "v-" + uuid.uuid4().hex[:6], **body})
    assert r.status_code == 202, r.text
    return r.json()["job_id"]


def test_the_runner_reads_an_upload_from_disk(client, auth_header, uploads_root):
    r = client.post("/api/v1/repositories/uploads", headers=auth_header,
                    files={"file": ("dd.csv", CSV, "text/csv")}, data={"kind": "data_dictionary"})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]

    assert pr._upload_bytes(uid) == CSV
    repositories._UPLOADS.clear()                  # an API restart: only the disk copy is left
    assert pr._upload_bytes(uid) == CSV


def test_the_project_dictionary_reaches_the_run_through_its_core(db, client, auth_header, tmp_path,
                                                                  uploads_root, monkeypatch):
    # The project's dictionary is its core's (a project from before cores is Core1, used by every
    # layer), so a job that names none adds no second, project-wide copy of it.
    up = uploads_root / "uploads" / "up_wizard"
    up.mkdir(parents=True)
    (up / "dd.csv").write_bytes(CSV)
    pid = _project(db, {"data_dictionary": {"file_name": "dd.csv", "file_id": "up_wizard"}})
    with patch("api.services.settings.get_settings",
               return_value=types.SimpleNamespace(workspaces=tmp_path, repo_root=tmp_path)):
        job_id = _start(client, auth_header, pid)
    assert db.jobs.get(job_id).data_dict_id is None
    monkeypatch.setattr(pr, "get_settings", lambda: types.SimpleNamespace(repo_root=tmp_path))
    (tmp_path / "engine" / "config").mkdir(parents=True)
    (tmp_path / "engine" / "config" / "config.defaults.json").write_text("{}", encoding="utf-8")
    _, cfg = pr._write_project_config(db.projects.get(pid), tmp_path / "ws")
    assert cfg["cores"]["Core1"]["dataDictionary"].endswith("dd.csv")
    assert cfg["layers"]["Layer1"]["cores"] == ["Core1"]


def test_a_job_that_names_a_dictionary_keeps_it(db, client, auth_header):
    pid = _project(db, {"data_dictionary": {"file_name": "dd.csv", "file_id": "up_wizard"}})
    job_id = _start(client, auth_header, pid, data_dict_id="up_other")
    assert db.jobs.get(job_id).data_dict_id == "up_other"


def test_a_project_without_a_dictionary_runs_without_one(db, client, auth_header):
    pid = _project(db, {"data_dictionary": None})
    job_id = _start(client, auth_header, pid)
    assert db.jobs.get(job_id).data_dict_id is None
