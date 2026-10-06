"""A job's scope is checked when the job is requested, against the project's own layers.

The sample project's architecture has two layers that both define a group `My Sample` holding a
component `Sample Core` -- the twin that tests layer-qualified identity. A job scoped to the bare
name was accepted (202) and stopped in Phase 1:

    Component 'Sample-Core' is ambiguous - 2 layers use that name: Layer1.Sample-Core, ...

after its version tag had been taken, so a retry with the same tag answered 409 VERSION_EXISTS.
Now the request itself is refused, 400 INVALID_SCOPE naming the candidates, and nothing is
reserved. The names are resolved by the engine's own resolvers, over the layers the job's config
is written from, so the API and the run cannot disagree about a name.
"""
import datetime
import json
import os
import uuid
from unittest.mock import patch

import pytest

from api.models.domain import Project, ProjectMember

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
with open(os.path.join(ROOT, "engine", "config",
                       "api_create_project.sample_full.example.json"), encoding="utf-8") as _fh:
    SAMPLE_LAYERS = json.load(_fh)["architecture_layers"]


def _project(db):
    """The sample project, alice its admin -- created in the database directly, as
    test_start_job_needs_architecture does: POST /projects would clone a repository."""
    pid = "psc" + uuid.uuid4().hex[:6]
    now = datetime.datetime.now(datetime.timezone.utc)
    db.projects.create(Project(
        id=pid, org_id="org1", name=pid, client="c", compliance_standard="ASPICE_L2",
        repo_url="https://example.invalid/r.git", repo_provider="github",
        default_branch="main", build_config={}, architecture_layers=SAMPLE_LAYERS,
        status="not_run", created_by="u1", created_at=now, updated_at=now))
    db.members.add_member(ProjectMember(
        id="m" + uuid.uuid4().hex[:8], project_id=pid, user_id="u1", role="admin",
        status="active", invited_by="u1", invited_at=now, joined_at=now))
    return pid


def _start(client, auth_header, pid, scope, tag="v1"):
    body = {"commit_sha": "8b3e313f892f2b3baea252d98f0b083015622e98", "version_tag": tag,
            "mode": "full", "scope": scope}
    with patch("api.services.pipeline_runner.start") as start:
        r = client.post(f"/api/v1/projects/{pid}/jobs", headers=auth_header, json=body)
    return r, start


class TestABareNameTwoLayersShareIsRefused:
    """The two bodies the user sent."""

    @pytest.mark.parametrize("scope,kind,candidates", [
        ({"type": "component", "names": ["Sample Core"]}, "Component",
         ["Layer1.Sample Core", "Layer2.Sample Core"]),
        ({"type": "group", "names": ["My Sample"]}, "Group",
         ["Layer1.My Sample", "Layer2.My Sample"]),
    ], ids=["component", "group"])
    def test_400_naming_the_candidates(self, client, db, auth_header, scope, kind, candidates):
        pid = _project(db)
        r, start = _start(client, auth_header, pid, scope)
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        assert detail["code"] == "INVALID_SCOPE"
        assert detail["message"].startswith("%s %r is ambiguous" % (kind, scope["names"][0]))
        assert detail["candidates"] == candidates
        start.assert_not_called()

    def test_nothing_is_reserved_so_the_tag_stays_free(self, client, db, auth_header):
        pid = _project(db)
        _start(client, auth_header, pid, {"type": "group", "names": ["My Sample"]})
        assert client.get(f"/api/v1/projects/{pid}/versions",
                          headers=auth_header).json()["versions"] == []
        assert client.get(f"/api/v1/projects/{pid}/jobs/current",
                          headers=auth_header).json() == {"job": None}
        r, start = _start(client, auth_header, pid,
                          {"type": "group", "names": ["Layer1.My Sample"]})
        assert r.status_code == 202, r.text
        start.assert_called_once()


class TestWhatTheEngineAcceptsIsAccepted:
    @pytest.mark.parametrize("scope", [
        {"type": "component", "names": ["Layer1.Sample Core"]},
        {"type": "component", "names": ["Layer1.Sample-Core"]},       # the id's other spelling
        {"type": "group", "names": ["Layer1.My Sample"]},
        {"type": "group", "names": ["layer1.my sample"]},             # case and spaces never decide
        {"type": "group", "names": ["Full"]},                         # unique: no layer needed
        {"type": "group", "names": ["Layer1.My Sample", "Layer1.Full"]},
        {"type": "layer", "names": ["Layer1"]},
        {"type": "project"},
        None,
    ], ids=lambda s: json.dumps(s))
    def test_202(self, client, db, auth_header, scope):
        pid = _project(db)
        r, start = _start(client, auth_header, pid, scope)
        assert r.status_code == 202, r.text
        start.assert_called_once()


class TestOtherMistakes:
    @pytest.mark.parametrize("scope,says", [
        ({"type": "group", "names": ["Nope"]}, "No group 'Nope' in this project"),
        ({"type": "component", "names": ["Nope"]}, "No component 'Nope' in this project"),
        ({"type": "layer", "names": ["layer1"]}, "No layer 'layer1' in this project"),
        ({"type": "module", "names": ["Lib"]}, "scope type 'module' is not one of"),
        ({"type": "component", "names": ["Layer1.My Sample"]}, "is a group: use"),
        ({"type": "group", "names": ["Layer1.Lib"]}, "is a component: use"),
        ({"type": "group", "names": ["Layer1.Full", "Nope"]}, "No group 'Nope'"),
    ], ids=["unknown-group", "unknown-component", "layer-case", "type", "group-as-component",
            "component-as-group", "one-of-several"])
    def test_400(self, client, db, auth_header, scope, says):
        pid = _project(db)
        r, start = _start(client, auth_header, pid, scope)
        assert r.status_code == 400, r.text
        assert r.json()["detail"]["code"] == "INVALID_SCOPE"
        assert says in r.json()["detail"]["message"]
        start.assert_not_called()

    def test_an_unknown_name_lists_what_there_is(self, client, db, auth_header):
        pid = _project(db)
        r, _ = _start(client, auth_header, pid, {"type": "group", "names": ["Nope"]})
        assert "Layer1.My Sample" in r.json()["detail"]["candidates"]


class TestTheLayerFilterIsCheckedToo:
    """`layer_filter` is what a run selects when the scope names nothing. An unknown one was
    accepted with 202, the tag reserved, and the run stopped in Phase 1."""

    def _start(self, client, auth_header, pid, layer_filter, scope=None):
        body = {"commit_sha": "8b3e313f892f2b3baea252d98f0b083015622e98", "version_tag": "v1",
                "mode": "full", "scope": scope, "layer_filter": layer_filter}
        with patch("api.services.pipeline_runner.start") as start:
            r = client.post(f"/api/v1/projects/{pid}/jobs", headers=auth_header, json=body)
        return r, start

    @pytest.mark.parametrize("scope", [None, {"type": "project"}, {"type": "group", "names": []}],
                             ids=["none", "project", "empty-names"])
    def test_an_unknown_layer_is_refused(self, client, db, auth_header, scope):
        pid = _project(db)
        r, start = self._start(client, auth_header, pid, "Nope", scope)
        assert r.status_code == 400, r.text
        assert r.json()["detail"]["code"] == "INVALID_SCOPE"
        assert "No layer 'Nope'" in r.json()["detail"]["message"]
        start.assert_not_called()

    def test_a_known_layer_is_accepted(self, client, db, auth_header):
        pid = _project(db)
        r, start = self._start(client, auth_header, pid, "Layer1")
        assert r.status_code == 202, r.text
        start.assert_called_once()

    def test_a_scope_with_names_wins_and_the_filter_is_not_read(self, client, db, auth_header):
        pid = _project(db)
        r, _ = self._start(client, auth_header, pid, "Nope",
                           {"type": "group", "names": ["Layer1.My Sample"]})
        assert r.status_code == 202, r.text


def test_the_check_is_the_engines(monkeypatch):
    """The API asks the engine's resolvers, so it agrees with the run by construction --
    a resolver that answered differently would be seen here."""
    from api.services import pipeline_runner
    import core.config as cfg
    calls = []
    real = cfg.resolve_group_id

    def spy(groups, name):
        calls.append(name)
        return real(groups, name)
    monkeypatch.setattr(cfg, "resolve_group_id", spy)
    assert pipeline_runner.scope_problem(SAMPLE_LAYERS,
                                         {"type": "group", "names": ["Layer1.Full"]}) is None
    assert calls == ["Layer1.Full"]
