"""A project onboarded by the CLI must be reachable over HTTP.

There are two front doors and they wrote different rows.

`POST /api/v1/projects` knows who is calling, so it adds the caller to `project_members`.
`analyzer.py onboard` has no caller, so it wrote the `projects` row and stopped. The result was a
project that generated documents perfectly from the CLI and was invisible over HTTP:

    GET /projects                 -> {"projects": []}
    GET /projects/{id}            -> 403 "Project membership required."
    GET /projects/{id}/versions/{v}/overrides -> 403     <- the whole review feature

Signing in as "the admin" did not help, and the membership check was not at fault. There is no
global role in this system: `User` has no role field, and `admin@aspice.dev` is a seeded LOGIN.
Authorisation is per project, so a project nobody was added to has nobody who can read it.

`GET /projects/search` answered for those projects throughout, because it does not filter by
membership -- which is how they were findable at all while the row was missing.

The second defect only appeared once the first was fixed: the CLI never wrote `projects.updated_at`
either, and the project view called `.isoformat()` on it unconditionally, so one such row made the
whole LIST answer 500.
"""
import datetime
import os
import sys
import uuid

import pytest
import sqlalchemy as sa

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "tools"))

from api.db.postgres import schema as s
from api.db.postgres.database import SqlDatabase
from grant_access import grant

NOW = datetime.datetime.now(datetime.timezone.utc)


def _engine_of(db):
    """The SQL backend's engine, or skip: these tests are about rows, so the in-memory
    backend has nothing to say about them."""
    eng = getattr(db, "engine", None) or getattr(db, "_engine", None)
    if eng is None or not isinstance(db, SqlDatabase):
        pytest.skip("row-level test; only meaningful on the SQL backend")
    return eng


@pytest.fixture
def cli_project(db):
    """Exactly what `analyzer.py onboard` used to write: a projects row and nothing else.

    No membership, and no `updated_at` -- both omissions are the point.
    """
    eng = _engine_of(db)
    pid = "cli-" + uuid.uuid4().hex[:6]
    with eng.begin() as cx:
        cx.execute(sa.insert(s.projects), {"id": pid, "name": pid, "status": "active",
                                           "created_at": NOW})
    yield pid
    with eng.begin() as cx:
        cx.execute(sa.delete(s.project_members).where(s.project_members.c.project_id == pid))
        cx.execute(sa.delete(s.projects).where(s.projects.c.id == pid))


def _uid(db, email="alice@aspice.dev"):
    """Resolve the user id BEFORE opening a transaction.

    The SQL test backend uses StaticPool, so every `connect()` hands back the same DBAPI
    connection. Calling this inside an open `eng.begin()` block therefore runs a second
    Connection over the same physical one and discards the pending write on close -- which
    looked exactly like `grant` not being idempotent.
    """
    return db.users.get_by_email(email).id


class TestTheSymptom:
    def test_it_is_not_listed(self, client, auth_header, cli_project):
        r = client.get("/api/v1/projects", headers=auth_header)
        assert r.status_code == 200
        assert cli_project not in [p["id"] for p in r.json()["projects"]]

    def test_but_search_finds_it(self, client, auth_header, cli_project):
        """Which is why it looks like a listing bug rather than an access one."""
        r = client.get("/api/v1/projects/search?q=", headers=auth_header)
        assert cli_project in [p["id"] for p in r.json()["projects"]]

    @pytest.mark.parametrize("suffix", ["", "/commits", "/versions/v1/overrides"])
    def test_every_project_route_is_403(self, client, auth_header, cli_project, suffix):
        r = client.get(f"/api/v1/projects/{cli_project}{suffix}", headers=auth_header)
        assert r.status_code == 403
        assert r.json()["detail"]["message"] == "Project membership required."


class TestGrantFixesIt:
    def test_the_project_is_listed_afterwards(self, client, auth_header, cli_project, db):
        uid = _uid(db)
        with _engine_of(db).begin() as cx:
            assert grant(cx, cli_project, uid) == "created"
        r = client.get("/api/v1/projects", headers=auth_header)
        listed = {p["id"]: p for p in r.json()["projects"]}
        assert cli_project in listed
        assert listed[cli_project]["my_role"] == "admin"

    @pytest.mark.parametrize("suffix", ["", "/commits", "/versions/v1/overrides"])
    def test_the_routes_answer(self, client, auth_header, cli_project, db, suffix):
        uid = _uid(db)
        with _engine_of(db).begin() as cx:
            grant(cx, cli_project, uid)
        r = client.get(f"/api/v1/projects/{cli_project}{suffix}", headers=auth_header)
        if "/versions/" in suffix:
            # Through the membership gate: this project has no version 'v1', and saying so is
            # the route's own answer, not the 403 the grant removes. (It answered 200 with an
            # empty list before the review routes checked that a version is the project's own.)
            assert r.status_code == 404 and "no version" in r.text, r.text
        else:
            assert r.status_code == 200, r.text

    def test_it_is_idempotent(self, client, cli_project, db):
        """The obvious response to a lingering 403 is to run it again, and a second row for the
        same pair would make `get_member` ambiguous."""
        eng = _engine_of(db)
        uid = _uid(db)
        with eng.begin() as cx:
            assert grant(cx, cli_project, uid) == "created"
            assert grant(cx, cli_project, uid) == "unchanged"
        with eng.connect() as cx:
            n = cx.execute(sa.select(sa.func.count()).select_from(s.project_members)
                           .where(s.project_members.c.project_id == cli_project)).scalar()
        assert n == 1

    def test_an_inactive_membership_is_reactivated(self, client, auth_header, cli_project, db):
        """A row that exists but is not active fails the check exactly like a missing one, and
        "it says I am a member but I get 403" is worse to debug than "I am not a member"."""
        eng, uid = _engine_of(db), _uid(db)
        with eng.begin() as cx:
            cx.execute(sa.insert(s.project_members), {
                "id": "m" + uuid.uuid4().hex[:8], "project_id": cli_project,
                "user_id": uid, "role": "developer", "status": "invited",
                "invited_at": NOW})
        assert client.get(f"/api/v1/projects/{cli_project}",
                          headers=auth_header).status_code == 403
        uid = _uid(db)
        with eng.begin() as cx:
            assert grant(cx, cli_project, uid) == "updated"
        assert client.get(f"/api/v1/projects/{cli_project}",
                          headers=auth_header).status_code == 200


class TestANullTimestampDoesNotBreakTheList:
    """The second defect, which only surfaces once the first is fixed.

    `_project_view` called `project.updated_at.isoformat()` unconditionally, so ONE row written
    without it made `GET /projects` answer 500 for every project the caller can see -- not just
    that one.
    """

    def test_the_list_survives_a_project_with_no_updated_at(self, client, auth_header,
                                                            cli_project, db):
        uid = _uid(db)
        with _engine_of(db).begin() as cx:
            grant(cx, cli_project, uid)
        r = client.get("/api/v1/projects", headers=auth_header)
        assert r.status_code == 200, r.text
        row = next(p for p in r.json()["projects"] if p["id"] == cli_project)
        assert row["updated_at"] is None

    def test_the_single_project_view_survives_it_too(self, client, auth_header, cli_project, db):
        uid = _uid(db)
        with _engine_of(db).begin() as cx:
            grant(cx, cli_project, uid)
        r = client.get(f"/api/v1/projects/{cli_project}", headers=auth_header)
        assert r.status_code == 200, r.text
        assert r.json()["project"]["updated_at"] is None


class TestOnboardingWritesACompleteRow:
    """The reader is null-safe now, but new rows should not need that safety net."""

    def test_new_project_sets_updated_at(self):
        src = open(os.path.join(PROJECT_ROOT, "tools", "new_project.py"),
                   encoding="utf-8").read()
        insert = src[src.index("cx.execute(sa.insert(s.projects)"):]
        assert '"updated_at": now' in insert[:800], (
            "onboarding writes a projects row with no updated_at again")

    def test_onboard_can_grant_access(self):
        """Otherwise every new CLI project repeats this whole diagnosis."""
        src = open(os.path.join(PROJECT_ROOT, "analyzer.py"), encoding="utf-8").read()
        assert "--owner" in src and "_grant_after_onboard" in src

    def test_onboard_says_so_when_it_does_not(self):
        """Silence here is what made the 403 a mystery rather than a message."""
        src = open(os.path.join(PROJECT_ROOT, "analyzer.py"), encoding="utf-8").read()
        body = src[src.index("def _grant_after_onboard"):src.index("def cmd_grant")]
        assert "403" in body and "analyzer.py grant" in body
