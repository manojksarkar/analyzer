"""Renaming a project: `PATCH /projects/{id}` with `name`, by the project's admins.

The name is trimmed, and never blank or longer than 120 characters -- a name of spaces was taken
as it was. Creating a project takes its name the same way. The same route set `status` to any
text; only the states the app knows are taken now. Documents already made keep the name they
were made with (the render reads the version's recorded name); that is not changed here.
"""
import pytest

pytestmark = pytest.mark.unit

REPO = "https://github.com/test/ecu"


def _new_project(client, auth_header, name="Rename Me"):
    r = client.post("/api/v1/projects", json={"name": name, "client": "T", "compliance_standard": "ASPICE_L2", "repo_url": REPO},
                    headers=auth_header)
    assert r.status_code == 200, r.text
    body = r.json()
    return (body.get("project") or body)["id"]


def _name(client, auth_header, pid):
    return client.get(f"/api/v1/projects/{pid}", headers=auth_header).json()["project"]["name"]


def test_an_admin_renames_the_name_trimmed(client, auth_header):
    pid = _new_project(client, auth_header)
    r = client.patch(f"/api/v1/projects/{pid}", json={"name": "  Brake ECU v2  "}, headers=auth_header)
    assert r.status_code == 200, r.text
    assert r.json()["project"]["name"] == "Brake ECU v2"
    assert _name(client, auth_header, pid) == "Brake ECU v2"
    listed = {p["id"]: p["name"] for p in client.get("/api/v1/projects", headers=auth_header).json()["projects"]}
    assert listed[pid] == "Brake ECU v2"


@pytest.mark.parametrize("name, message", [
    ("", "A project needs a name."),
    ("    ", "A project needs a name."),
    ("x" * 121, "A project name is at most 120 characters."),
])
def test_a_blank_or_too_long_name_is_refused_and_the_name_kept(client, auth_header, name, message):
    pid = _new_project(client, auth_header, "Keep Me")
    r = client.patch(f"/api/v1/projects/{pid}", json={"name": name}, headers=auth_header)
    assert r.status_code == 400 and r.json()["detail"]["message"] == message
    assert _name(client, auth_header, pid) == "Keep Me"


def test_only_what_is_sent_changes(client, auth_header):
    pid = _new_project(client, auth_header, "Only Client")
    r = client.patch(f"/api/v1/projects/{pid}", json={"client": "Acme"}, headers=auth_header)
    assert r.status_code == 200 and r.json()["project"]["name"] == "Only Client"


def test_someone_not_an_admin_of_it_cannot_rename_it(client, auth_header, dev_token):
    pid = _new_project(client, auth_header, "Not Yours")
    r = client.patch(f"/api/v1/projects/{pid}", json={"name": "Taken"},
                     headers={"Authorization": f"Bearer {dev_token}"})
    assert r.status_code == 403
    assert _name(client, auth_header, pid) == "Not Yours"


def test_status_takes_only_a_state_the_app_knows(client, auth_header):
    pid = _new_project(client, auth_header, "Status")
    r = client.patch(f"/api/v1/projects/{pid}", json={"status": "banana"}, headers=auth_header)
    assert r.status_code == 400 and "Unknown project status" in r.json()["detail"]["message"]
    r = client.patch(f"/api/v1/projects/{pid}", json={"status": "stale"}, headers=auth_header)
    assert r.status_code == 200 and r.json()["project"]["status"] == "stale"


def test_creating_takes_the_name_the_same_way(client, auth_header):
    assert _name(client, auth_header, _new_project(client, auth_header, "  Spaced  ")) == "Spaced"
    r = client.post("/api/v1/projects", json={"name": "   ", "client": "T", "compliance_standard": "ASPICE_L2", "repo_url": REPO},
                    headers=auth_header)
    assert r.status_code == 400 and r.json()["detail"]["message"] == "A project needs a name."
