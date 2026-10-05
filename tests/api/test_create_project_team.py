"""Creating a project with a team: every member needs an account, and is added once.

An unknown address was stored under a made-up user id that the `users` foreign key refused --
AFTER the project row was written, so the 500 left a half-created project behind. A person listed
twice, or the creator listing themselves, hit the (project, user) unique key the same way.
"""
import types
import uuid
from unittest.mock import patch

import pytest


@pytest.fixture
def ws(tmp_path):
    """Creation writes workspaces/<pid>/config.json; keep it out of the real workspaces/."""
    with patch("api.services.settings.get_settings",
               return_value=types.SimpleNamespace(workspaces=tmp_path, repo_root=tmp_path)):
        yield tmp_path


def _body(name, team):
    return {"name": name, "client": "", "compliance_standard": "ISO_26262",
            "repo_url": "https://example.invalid/r.git", "team": team}


def test_an_unknown_address_is_refused_before_anything_is_written(db, client, auth_header, ws):
    name = "team-" + uuid.uuid4().hex[:6]
    r = client.post("/api/v1/projects", headers=auth_header,
                    json=_body(name, [{"email": "bob@aspice.dev", "role": "developer"},
                                      {"email": "nobody.here@aspice.dev", "role": "developer"}]))
    assert r.status_code == 404, r.text
    assert r.json()["detail"]["code"] == "USER_NOT_FOUND"
    assert "nobody.here@aspice.dev" in r.json()["detail"]["message"]
    assert not [p for p in db.projects.search(name)], "no half-created project"


def test_each_member_is_added_once(db, client, auth_header, ws):
    r = client.post("/api/v1/projects", headers=auth_header,
                    json=_body("team-" + uuid.uuid4().hex[:6],
                               [{"email": "bob@aspice.dev", "role": "developer"},
                                {"email": "bob@aspice.dev", "role": "admin"},
                                {"email": "alice@aspice.dev", "role": "developer"}]))
    assert r.status_code == 200, r.text
    pid = r.json()["project"]["id"]
    members = client.get(f"/api/v1/projects/{pid}/members", headers=auth_header).json()["members"]
    by_email = sorted((m["email"], m["role"]) for m in members)
    assert by_email == [("alice@aspice.dev", "admin"), ("bob@aspice.dev", "developer")]
