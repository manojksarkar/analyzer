"""
API smoke tests — verify the HTTP layer end-to-end against an in-memory DB.

These tests do NOT run the real pipeline.  Jobs are started with
pipeline_runner.start patched to a no-op so the HTTP 202 response is
validated without touching git or subprocesses.

Mark: unit (fast, no I/O beyond the in-memory DB)
"""
import pytest
from unittest.mock import patch


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Meta / health
# ---------------------------------------------------------------------------

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_root(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "docs" in r.json()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def test_signin_success(client):
    r = client.post(
        "/api/v1/auth/signin",
        json={"email": "alice@aspice.dev", "password": "secret"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["user"]["email"] == "alice@aspice.dev"


def test_signin_wrong_password(client):
    r = client.post(
        "/api/v1/auth/signin",
        json={"email": "alice@aspice.dev", "password": "wrong"},
    )
    assert r.status_code == 401


def test_signin_unknown_user(client):
    r = client.post(
        "/api/v1/auth/signin",
        json={"email": "nobody@example.com", "password": "secret"},
    )
    assert r.status_code == 401


def test_me(client, auth_header):
    r = client.get("/api/v1/auth/me", headers=auth_header)
    assert r.status_code == 200
    assert r.json()["user"]["email"] == "alice@aspice.dev"


def test_me_no_token(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401


def test_refresh_token(client):
    r = client.post(
        "/api/v1/auth/signin",
        json={"email": "bob@aspice.dev", "password": "secret"},
    )
    refresh = r.json()["refresh_token"]
    r2 = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh},
    )
    assert r2.status_code == 200
    assert "access_token" in r2.json()


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

def test_list_projects(client, auth_header):
    r = client.get("/api/v1/projects", headers=auth_header)
    assert r.status_code == 200
    data = r.json()
    assert "projects" in data
    assert len(data["projects"]) >= 1


def test_get_project(client, auth_header):
    r = client.get("/api/v1/projects/p1", headers=auth_header)
    assert r.status_code == 200
    data = r.json()["project"]
    assert data["id"] == "p1"
    assert "build_config" in data
    # Token must never be echoed
    assert "repo_access_token" not in str(data.get("build_config", {}))


def test_get_project_not_found(client, auth_header):
    r = client.get("/api/v1/projects/nonexistent", headers=auth_header)
    assert r.status_code == 404


def test_search_projects(client, auth_header):
    r = client.get("/api/v1/projects/search?q=VCU", headers=auth_header)
    assert r.status_code == 200


def test_create_project(client, auth_header):
    r = client.post(
        "/api/v1/projects",
        json={
            "name": "Test ECU",
            "client": "TestCo",
            "compliance_standard": "ASPICE_L2",
            "repo_url": "https://github.com/test/ecu",
            "repo_provider": "github",
        },
        headers=auth_header,
    )
    assert r.status_code == 200
    data = r.json()["project"]
    assert data["name"] == "Test ECU"


# ---------------------------------------------------------------------------
# Commits & Versions
# ---------------------------------------------------------------------------

def test_list_versions(client, auth_header):
    r = client.get("/api/v1/projects/p1/versions", headers=auth_header)
    assert r.status_code == 200
    data = r.json()
    assert "versions" in data
    assert len(data["versions"]) >= 1


def test_list_commits(client, auth_header):
    r = client.get("/api/v1/projects/p1/commits", headers=auth_header)
    assert r.status_code == 200
    data = r.json()
    assert "commits" in data


def test_get_version(client, auth_header):
    # Get the first version from the list
    r = client.get("/api/v1/projects/p1/versions", headers=auth_header)
    versions = r.json()["versions"]
    assert versions, "no seeded versions for p1"
    ver_id = versions[0]["id"]

    r2 = client.get(f"/api/v1/projects/p1/versions/{ver_id}", headers=auth_header)
    assert r2.status_code == 200
    assert r2.json()["version"]["id"] == ver_id


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

def test_list_documents(client, auth_header):
    r = client.get("/api/v1/projects/p1/documents", headers=auth_header)
    assert r.status_code == 200
    data = r.json()
    assert "documents" in data
    assert data["pagination"]["total"] >= 0


def test_document_stats(client, auth_header):
    r = client.get("/api/v1/projects/p1/documents/stats", headers=auth_header)
    assert r.status_code == 200
    assert "stats" in r.json()
    assert "total" in r.json()["stats"]


def test_get_document(client, auth_header):
    r = client.get("/api/v1/projects/p1/documents", headers=auth_header)
    docs = r.json()["documents"]
    if not docs:
        pytest.skip("no documents seeded for p1")
    doc_id = docs[0]["id"]

    r2 = client.get(f"/api/v1/projects/p1/documents/{doc_id}", headers=auth_header)
    assert r2.status_code == 200
    assert r2.json()["document"]["id"] == doc_id


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def test_get_current_job(client, auth_header):
    r = client.get("/api/v1/projects/p1/jobs/current", headers=auth_header)
    # p1 has a seeded job — may be 200 or 404 depending on status filter
    assert r.status_code in (200, 404)


def test_start_job_mocked(client, auth_header):
    """Start a job with the real pipeline stubbed out."""
    with patch("api.services.pipeline_runner.start") as mock_start:
        # Use a seeded commit SHA from p1
        r = client.get("/api/v1/projects/p1/commits", headers=auth_header)
        commits = r.json().get("commits", [])
        sha = commits[0]["sha"] if commits else "abc123def456789012345678"

        r2 = client.post(
            "/api/v1/projects/p1/jobs",
            json={"commit_sha": sha},
            headers=auth_header,
        )
        # Either 202 (new job) or 409 (job already active)
        assert r2.status_code in (202, 409)
        if r2.status_code == 202:
            assert mock_start.called
            assert "job_id" in r2.json()


def test_start_job_requires_admin(client, dev_header):
    """Developer role cannot start a job."""
    with patch("api.services.pipeline_runner.start"):
        r = client.post(
            "/api/v1/projects/p1/jobs",
            json={"commit_sha": "abc123def456789012345678"},
            headers=dev_header,
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------

def test_get_job_functions(client, auth_header):
    # Get the current/latest job for p1
    r = client.get("/api/v1/projects/p1/jobs/current", headers=auth_header)
    if r.status_code != 200:
        pytest.skip("no active job for p1")
    job = r.json().get("job")
    if not job:
        pytest.skip("no active job for p1")
    job_id = job["id"]

    r2 = client.get(
        f"/api/v1/projects/p1/jobs/{job_id}/functions", headers=auth_header
    )
    assert r2.status_code == 200
    assert "functions" in r2.json()


# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------

def test_list_members(client, auth_header):
    r = client.get("/api/v1/projects/p1/members", headers=auth_header)
    assert r.status_code == 200
    data = r.json()
    assert "members" in data
    assert len(data["members"]) >= 1


def test_list_pending_members(client, auth_header):
    r = client.get("/api/v1/projects/p1/members/pending", headers=auth_header)
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------

def test_compare_requires_refs(client, auth_header):
    # Missing query params → 422
    r = client.get("/api/v1/projects/p1/compare", headers=auth_header)
    assert r.status_code == 422


def test_compare_with_refs(client, auth_header):
    r = client.get(
        "/api/v1/projects/p1/compare?current=ver1&baseline=ver2",
        headers=auth_header,
    )
    # 200 (seeded or empty diff) or 404 (refs not found)
    assert r.status_code in (200, 404)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def test_get_notifications(client, auth_header):
    r = client.get("/api/v1/notifications", headers=auth_header)
    assert r.status_code == 200
    assert "notifications" in r.json()


# ---------------------------------------------------------------------------
# Users search
# ---------------------------------------------------------------------------

def test_search_users(client, auth_header):
    r = client.get("/api/v1/users/search?q=alice", headers=auth_header)
    assert r.status_code == 200
    data = r.json()
    assert "users" in data


def test_search_users_no_query(client, auth_header):
    r = client.get("/api/v1/users/search", headers=auth_header)
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Access requests
# ---------------------------------------------------------------------------

def test_list_access_requests(client, auth_header):
    r = client.get("/api/v1/projects/p1/access-requests", headers=auth_header)
    assert r.status_code == 200
