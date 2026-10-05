"""
API test fixtures.

Provides:
  client      — TestClient wired to an InMemoryDatabase (no pipeline, no disk I/O)
  auth_header — Authorization header for alice (admin)
  admin_token — raw JWT for alice

And, for every test, whether it asks or not: no API test reaches the database this machine is
configured for (`DATABASE_URL`, or the `db` section of `engine/config/config.local.json`).
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from api.main import app
from api.db.in_memory import InMemoryDatabase
from api.db.postgres import schema as s
from api.db.postgres.database import SqlDatabase
from api.db.session import get_db


def _sqlite_engine():
    # StaticPool + one shared connection: an in-memory SQLite DB is otherwise
    # per-connection, so TestClient's threadpool would each see an empty database.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)

    # SQLite leaves FK enforcement OFF by default; Postgres does not. Turn it ON so a
    # seed/insert-ordering bug fails HERE instead of on the office Postgres box.
    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _rec):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


def _sqlite_backed() -> SqlDatabase:
    return SqlDatabase(_sqlite_engine(), create_schema=True).seed()


@pytest.fixture(scope="session", params=["memory", "sql"])
def db(request):
    """The full API suite runs against BOTH backends (the PG-2 parity guarantee):
    in-memory, and the SQL backend over SQLite with identical seed data."""
    return InMemoryDatabase() if request.param == "memory" else _sqlite_backed()


@pytest.fixture(scope="session")
def _spare_engine():
    """An empty database with the schema: what `core.db` hands a test on the in-memory backend."""
    engine = _sqlite_engine()
    s.metadata.create_all(engine)
    return engine


@pytest.fixture(autouse=True)
def _no_test_reaches_the_configured_database(request, monkeypatch, _spare_engine):
    """`core.db` hands every API test the test's own engine, on a machine that looks unconfigured.

    The review routes -- and the runner's re-export check, and `DbRepository` -- open
    `core.db.get_engine()`, which is `DATABASE_URL` or the `db` section of `config.local.json`,
    not the API's `get_db`. A test that called one without patching it failed with 503 on a
    clean checkout, and read the real database on a machine that has one.

    Now: no `DATABASE_URL` and no `db` section, as on a clean checkout, and `get_engine()` is the
    SQL backend's engine when the test runs on it -- the same database `get_db` serves -- else
    an empty one. An explicit DSN still gets its own engine. A test that wants a database of its
    own (`review_db`) patches over this; its patches are undone first.
    """
    import core.db as core_db
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(core_db, "_db_section", lambda: {})
    engine = _spare_engine
    if "db" in request.fixturenames:
        engine = getattr(request.getfixturevalue("db"), "_engine", None) or engine
    real_get_engine = core_db.get_engine
    monkeypatch.setattr(core_db, "get_engine",
                        lambda dsn=None: engine if dsn is None else real_get_engine(dsn))
    monkeypatch.setattr(core_db, "is_database_configured", lambda: True)


@pytest.fixture(autouse=True)
def _no_commit_sync_over_the_network(monkeypatch):
    """`GET /projects/{id}/commits` syncs the project's repository on its first view -- a real
    `git clone` of the seeded `https://github.com/org/vcu-firmware`, which does not exist. It hung
    the suite for an hour once (2026-10-04, `test_smoke.py::test_list_commits`). No test here is
    about the sync; each reads the commits the database has."""
    from api.routes import commits_versions
    monkeypatch.setattr(commits_versions, "_backfill_commits_from_repo", lambda *a, **k: None)


@pytest.fixture(scope="session", autouse=True)
def _startup_meets_no_database():
    """`with TestClient(app)` runs the app's startup hook, which connects to -- and seeds a login
    into -- the database `api/db/session.py` chose at import: the configured one. The routes get
    the test's database through `get_db`; the hook gets an in-memory one, and says so."""
    import api.db.session as session
    mp = pytest.MonkeyPatch()
    mp.setattr(session, "_db", InMemoryDatabase())
    yield
    mp.undo()


@pytest.fixture(scope="session")
def client(db):
    """TestClient that injects the shared in-memory DB and skips the real pipeline."""
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="session")
def admin_token(client):
    """JWT for alice (admin on p1 and p2)."""
    r = client.post(
        "/api/v1/auth/signin",
        json={"email": "alice@aspice.dev", "password": "secret"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def auth_header(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="session")
def dev_token(client):
    """JWT for bob (developer on p1)."""
    r = client.post(
        "/api/v1/auth/signin",
        json={"email": "bob@aspice.dev", "password": "secret"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def dev_header(dev_token):
    return {"Authorization": f"Bearer {dev_token}"}
