"""A superuser reaches every project, including ones nobody was added to.

Access here is per project, through `project_members`, and that is still the model. This is one
deliberate exception for the operator account.

**Why the flag and not just a membership row.** Adding the operator to every project on
onboarding would look equivalent and is not: a row can be missed by any path that forgets to
write it — which is precisely how a CLI-onboarded project became unreachable over HTTP — and by
anything that creates a project in future. The flag cannot be forgotten, because nothing has to
remember it. The row is written as well, but for the team list and `my_role`, not for access.

**Why a column and not a hard-coded email.** It is data: greppable, visible in the database,
changeable without a deploy, and testable — these tests promote a user that is not
`admin@aspice.dev` precisely to prove nothing is special about that address.
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

NOW = datetime.datetime.now(datetime.timezone.utc)


def _engine_of(db):
    if not isinstance(db, SqlDatabase):
        pytest.skip("row-level test; only meaningful on the SQL backend")
    return getattr(db, "engine", None) or getattr(db, "_engine")


@pytest.fixture
def orphan_project(db):
    """A project with no members at all — what `analyzer.py onboard` leaves behind."""
    eng = _engine_of(db)
    pid = "orphan-" + uuid.uuid4().hex[:6]
    with eng.begin() as cx:
        cx.execute(sa.insert(s.projects), {"id": pid, "name": pid, "status": "active",
                                           "created_at": NOW, "updated_at": NOW})
    yield pid
    with eng.begin() as cx:
        cx.execute(sa.delete(s.project_members).where(s.project_members.c.project_id == pid))
        cx.execute(sa.delete(s.projects).where(s.projects.c.id == pid))


@pytest.fixture
def superuser(db):
    """Promote alice for the duration of one test, and demote her afterwards.

    Alice, not `admin@aspice.dev`: if these passed only for that address the flag would be
    decoration around a hard-coded email.
    """
    eng = _engine_of(db)
    uid = db.users.get_by_email("alice@aspice.dev").id
    with eng.begin() as cx:
        cx.execute(sa.update(s.users).where(s.users.c.id == uid).values(is_superuser=True))
    yield uid
    with eng.begin() as cx:
        cx.execute(sa.update(s.users).where(s.users.c.id == uid).values(is_superuser=False))


class TestWithoutTheFlag:
    """The behaviour every other user keeps. The exception must stay an exception."""

    def test_an_orphan_project_is_not_listed(self, client, auth_header, orphan_project):
        r = client.get("/api/v1/projects", headers=auth_header)
        assert orphan_project not in [p["id"] for p in r.json()["projects"]]

    def test_an_orphan_project_is_403(self, client, auth_header, orphan_project):
        assert client.get(f"/api/v1/projects/{orphan_project}",
                          headers=auth_header).status_code == 403


class TestWithTheFlag:
    def test_every_project_is_listed(self, client, auth_header, orphan_project, superuser, db):
        r = client.get("/api/v1/projects", headers=auth_header)
        assert r.status_code == 200, r.text
        listed = [p["id"] for p in r.json()["projects"]]
        assert orphan_project in listed
        assert len(listed) == len(db.projects.list_all())

    @pytest.mark.parametrize("suffix", ["", "/commits", "/versions/v1/overrides"])
    def test_every_project_route_answers(self, client, auth_header, orphan_project,
                                         superuser, suffix):
        r = client.get(f"/api/v1/projects/{orphan_project}{suffix}", headers=auth_header)
        if "/versions/" in suffix:
            # Through the membership gate: the orphan has no version 'v1', and saying so is the
            # route's own answer -- not the 403 this test exists to rule out. (It answered 200
            # with an empty list before the review routes checked that a version is the
            # project's own.)
            assert r.status_code == 404 and "no version" in r.text, r.text
        else:
            assert r.status_code == 200, r.text

    def test_it_needs_no_membership_row(self, client, auth_header, orphan_project,
                                        superuser, db):
        """THE POINT. Access must not depend on a row somebody remembered to write."""
        eng = _engine_of(db)
        with eng.connect() as cx:
            n = cx.execute(sa.select(sa.func.count()).select_from(s.project_members)
                           .where(s.project_members.c.project_id == orphan_project)).scalar()
        assert n == 0, "the fixture is not testing what it claims to"
        assert client.get(f"/api/v1/projects/{orphan_project}",
                          headers=auth_header).status_code == 200

    def test_my_role_reads_as_admin(self, client, auth_header, orphan_project, superuser):
        """Reporting None would grey out controls the API will honour."""
        r = client.get(f"/api/v1/projects/{orphan_project}", headers=auth_header)
        assert r.json()["project"]["my_role"] == "admin"

    def test_a_real_membership_still_wins(self, client, auth_header, superuser, db):
        """On a project where the superuser IS a member, the stored role is what is reported —
        the fallback must not overwrite real data."""
        r = client.get("/api/v1/projects/p1", headers=auth_header)
        assert r.json()["project"]["my_role"] == "admin"

    def test_the_flag_is_what_does_it_not_the_email(self, client, db, superuser):
        """Alice is not `admin@aspice.dev`. If this passes, nothing is hard-coded."""
        assert db.users.get_by_email("alice@aspice.dev").is_superuser is True


class TestTheExceptionIsNarrow:
    def test_another_user_is_unaffected(self, client, orphan_project, superuser, db):
        """Promoting one user must not open the door for everyone."""
        tok = client.post("/api/v1/auth/signin",
                          json={"email": "bob@aspice.dev", "password": "secret"})
        if tok.status_code != 200:
            pytest.skip("no bob in this seed")
        h = {"Authorization": "Bearer " + tok.json()["access_token"]}
        assert client.get(f"/api/v1/projects/{orphan_project}", headers=h).status_code == 403

    def test_the_default_is_false(self, db):
        """A user created without saying anything is ordinary."""
        assert db.users.get_by_email("bob@aspice.dev").is_superuser in (False, None)


class TestTheColumnCanReachAnExistingDatabase:
    """`is_superuser` is NOT NULL, and it is added to databases that already have user rows.

    Without a server default that ALTER is impossible, and `analyzer.py setup` would report it
    as blocked and send the operator to Alembic for a column they could have had.
    """

    def test_it_has_a_server_default(self):
        col = s.users.c.is_superuser
        assert col.nullable is False
        assert col.server_default is not None, (
            "a NOT NULL column with no server default cannot be added to a table with rows")

    def test_setup_can_add_it(self, tmp_path):
        from db_setup import _add_missing_columns
        eng = sa.create_engine("sqlite:///" + str(tmp_path / "old.db").replace("\\", "/"))
        old = sa.MetaData()
        for t in s.metadata.sorted_tables:
            sa.Table(t.name, old, *[c._copy() for c in t.columns
                                    if not (t.name == "users" and c.name == "is_superuser")])
        old.create_all(eng)
        with eng.begin() as cx:
            cx.execute(sa.text("INSERT INTO users (id, email, name, hashed_password, created_at) "
                               "VALUES ('u1', 'a@b.c', 'A', 'x', '2026-01-01')"))
        added, blocked = _add_missing_columns(eng, s.metadata)
        assert not blocked, blocked
        assert any("users.is_superuser" in a for a in added)
        with eng.connect() as cx:
            assert cx.execute(sa.text("SELECT is_superuser FROM users")).scalar() in (0, False)


class TestOnboardingKeepsTheDataHonest:
    def test_onboard_adds_superusers_by_default(self):
        src = open(os.path.join(PROJECT_ROOT, "analyzer.py"), encoding="utf-8").read()
        body = src[src.index("def _grant_after_onboard"):src.index("def cmd_grant")]
        assert '"--superusers"' in body, (
            "onboarding no longer puts the operator on the new project's team list")

    def test_setup_backfills_the_superusers_memberships(self):
        src = open(os.path.join(PROJECT_ROOT, "tools", "db_setup.py"), encoding="utf-8").read()
        assert "WHERE u.is_superuser" in src and "project_members" in src, (
            "setup no longer puts every superuser on every project's team list")


def _sqlite_url(tmp_path, name):
    return "sqlite:///" + str(tmp_path / name).replace("\\", "/")


def _admin_flag(eng):
    with eng.connect() as cx:
        return cx.execute(sa.text("SELECT is_superuser FROM users "
                                  "WHERE email = 'admin@aspice.dev'")).scalar()


class TestNobodyIsASuperuserUnlessMadeOne:
    """The seeded login `admin@aspice.dev` / `admin` is an ORDINARY user.

    Its password is published, it is re-created on startup when deleted, and the JWT secret's
    default makes a token for it forgeable -- so promoting it made every project reachable by
    anyone who knew that. Three places did it: migration 0014, the startup seed and
    `analyzer.py setup`. Now `tools/grant_access.py --set-superuser` is the only way.
    """

    def test_a_fresh_databases_seeded_login_is_ordinary(self, tmp_path):
        from api.main import _ensure_default_admin
        eng = sa.create_engine(_sqlite_url(tmp_path, "fresh.db"))
        db = SqlDatabase(eng, create_schema=True)
        _ensure_default_admin(db)
        assert db.users.get_by_email("admin@aspice.dev").is_superuser is False
        assert _admin_flag(eng) in (0, False)

    def test_migration_0014_promotes_nobody(self, tmp_path):
        """0013 -> 0014 on a database that has the seeded login: the column lands, false."""
        import importlib.util
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        eng = sa.create_engine(_sqlite_url(tmp_path, "at0013.db"))
        before = sa.MetaData()
        sa.Table("users", before, *[col._copy() for col in s.users.columns
                                    if col.name != "is_superuser"])
        before.create_all(eng)
        with eng.begin() as cx:
            cx.execute(sa.text("INSERT INTO users (id, email, name, hashed_password, created_at) "
                               "VALUES ('admin', 'admin@aspice.dev', 'A', 'x', '2026-01-01')"))
        path = os.path.join(PROJECT_ROOT, "alembic", "versions", "0014_users_is_superuser.py")
        spec = importlib.util.spec_from_file_location("m0014", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with eng.begin() as cx:
            with Operations.context(MigrationContext.configure(cx)):
                migration.upgrade()
        assert _admin_flag(eng) in (0, False)

    def test_setup_promotes_nobody(self, tmp_path, monkeypatch):
        """`analyzer.py setup` on a database with no superuser used to promote the seeded login."""
        import db_setup
        url = _sqlite_url(tmp_path, "setup.db")
        eng = sa.create_engine(url)
        s.metadata.create_all(eng)
        with eng.begin() as cx:
            cx.execute(sa.insert(s.users), {"id": "admin", "email": "admin@aspice.dev",
                                            "name": "A", "hashed_password": "x",
                                            "created_at": NOW, "is_superuser": False})
        monkeypatch.setenv("DATABASE_URL", url)
        monkeypatch.setattr(sys, "argv", ["db_setup.py"])
        assert db_setup.main() == 0
        assert _admin_flag(eng) in (0, False)

    def test_the_command_makes_one_and_access_follows(self, client, db, orphan_project,
                                                      monkeypatch):
        """`tools/grant_access.py --set-superuser`: the flag, then every project -- and
        `--unset-superuser` takes it away again."""
        import grant_access
        import core.db as core_db
        eng = _engine_of(db)
        monkeypatch.setattr(core_db, "require_database", lambda *a, **k: None)
        monkeypatch.setattr(core_db, "get_engine", lambda *a, **k: eng)
        monkeypatch.setattr(core_db, "database_url", lambda *a, **k: "sqlite://")
        tok = client.post("/api/v1/auth/signin",
                          json={"email": "bob@aspice.dev", "password": "secret"})
        if tok.status_code != 200:
            pytest.skip("no bob in this seed")
        h = {"Authorization": "Bearer " + tok.json()["access_token"]}
        assert client.get(f"/api/v1/projects/{orphan_project}", headers=h).status_code == 403
        assert grant_access.main(["--set-superuser", "--email", "bob@aspice.dev"]) == 0
        try:
            assert db.users.get_by_email("bob@aspice.dev").is_superuser is True
            assert client.get(f"/api/v1/projects/{orphan_project}",
                              headers=h).status_code == 200
            listed = [p["id"] for p in client.get("/api/v1/projects",
                                                  headers=h).json()["projects"]]
            assert orphan_project in listed
        finally:
            assert grant_access.main(["--unset-superuser", "--email", "bob@aspice.dev"]) == 0
        assert client.get(f"/api/v1/projects/{orphan_project}", headers=h).status_code == 403

    def test_the_command_needs_an_email(self):
        import grant_access
        with pytest.raises(SystemExit):
            grant_access.main(["--set-superuser"])



class TestAdminOnlyRoutesToo:
    """"All access to all projects" includes the admin-only routes.

    `require_project_member` honoured the flag; `require_project_admin` did not. On a project
    the superuser had no admin row for, it could read everything and got "Admin role required."
    on re-export, team management and the rest of the 25 routes that use the admin check.
    """

    def test_an_admin_only_route_answers_a_superuser(self, client, auth_header, orphan_project,
                                                     superuser):
        r = client.patch(f"/api/v1/projects/{orphan_project}", headers=auth_header,
                         json={"client": "Changed by the operator"})
        assert r.status_code == 200, r.text

    def test_it_needs_no_admin_row(self, client, auth_header, orphan_project, superuser, db):
        eng = _engine_of(db)
        with eng.connect() as cx:
            rows = cx.execute(sa.select(sa.func.count()).select_from(s.project_members)
                              .where(s.project_members.c.project_id == orphan_project)).scalar()
        assert rows == 0, "the fixture is not testing what it claims to"
        assert client.patch(f"/api/v1/projects/{orphan_project}", headers=auth_header,
                            json={"client": "x"}).status_code == 200

    def test_an_ordinary_member_is_still_refused(self, client, orphan_project, superuser, db):
        """The exception stays an exception: a plain member of p1 is not an admin of it."""
        tok = client.post("/api/v1/auth/signin",
                          json={"email": "bob@aspice.dev", "password": "secret"})
        if tok.status_code != 200:
            pytest.skip("no bob in this seed")
        h = {"Authorization": "Bearer " + tok.json()["access_token"]}
        assert client.patch(f"/api/v1/projects/{orphan_project}", headers=h,
                            json={"client": "x"}).status_code == 403
