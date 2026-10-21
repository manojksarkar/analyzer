"""
API test fixtures.

Provides:
  client      — TestClient wired to an InMemoryDatabase (no pipeline, no disk I/O)
  auth_header — Authorization header for alice (admin)
  admin_token — raw JWT for alice

And, for every test, whether it asks or not: no API test reaches the database this machine is
configured for (`DATABASE_URL`, or the `db` section of `engine/config/config.local.json`).
"""
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from api.main import app
from api.db.in_memory import InMemoryDatabase
from api.db.postgres import schema as s
from api.db.postgres.database import SqlDatabase
from api.db.session import get_db


class _Turn:
    """One thread at a time on the shared connection; the thread that has it may check it out
    again, nested (the engine's helpers do). Given back from any thread. A turn not given back
    within `LIMIT` seconds is taken over, said loudly -- never a suite that hangs."""

    LIMIT = 60.0

    def __init__(self):
        self._cv = threading.Condition()
        self._owner, self._count = None, 0

    def take(self):
        me = threading.get_ident()
        with self._cv:
            if not self._cv.wait_for(lambda: self._owner in (None, me), timeout=self.LIMIT):
                import warnings
                warnings.warn("the test database's connection was not given back within %ds; "
                              "taken over" % self.LIMIT)
                self._owner, self._count = None, 0
            self._owner = me
            self._count += 1

    def give(self):
        with self._cv:
            self._count = max(0, self._count - 1)
            if not self._count:
                self._owner = None
                self._cv.notify_all()


def _sqlite_engine():
    # StaticPool + one shared connection: an in-memory SQLite DB is otherwise
    # per-connection, so TestClient's threadpool would each see an empty database.
    # No rollback by the pool when a connection comes back: each Connection ends its own
    # transaction, and on the one shared connection the pool's rollback could undo another
    # thread's -- or the open transaction of the connection a nested one was opened inside.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, pool_reset_on_return=None)

    # SQLite leaves FK enforcement OFF by default; Postgres does not. Turn it ON so a
    # seed/insert-ordering bug fails HERE instead of on the review Postgres box.
    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _rec):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    # That one connection serves every thread: a request's, a job's, its alive signal's. They take
    # turns with it, as a pool's connections would let them; at the same time SQLite answered "bad
    # parameter or other API misuse", or handed back a wrong row. Given back on `reset`, which the
    # pool sends for every connection it gets back: `checkin` is sent once for two connections
    # out at once, as StaticPool's share one record.
    turn = _Turn()

    @event.listens_for(engine, "checkout")
    def _take_turn(_dbapi_conn, _rec, _proxy):
        turn.take()

    @event.listens_for(engine, "reset")
    def _give_turn(_dbapi_conn, _rec, _state):
        turn.give()

    return engine


def _sqlite_backed() -> SqlDatabase:
    return SqlDatabase(_sqlite_engine(), create_schema=True).seed()


def record_commit(db, project_id: str, sha: str, branch: str = "main") -> str:
    """`sha` as one of the project's commits -- a row of what the web app's commit list shows --
    so a submit of it passes the commit check (docs/spec/JOB_SCHEDULING_SPEC.md REQ-JS-07)."""
    from datetime import datetime, timezone
    from api.models.domain import Commit
    db.commits.upsert(Commit(sha=sha, project_id=project_id, branch=branch, message="test",
                             author_name="Test", author_email="test@aspice.dev",
                             committed_at=datetime.now(timezone.utc), has_version=False,
                             version_id=None, doc_status="never"))
    return sha


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
def _job_scheduler(request, monkeypatch):
    """Every API test has the scheduler a server has, without its thread
    (docs/design/JOB_SCHEDULING_DESIGN.md §5): a submit starts its job at once when it may -- the
    real launch, the job's own thread -- and a job's end starts the next one. The `jobs` settings
    are the defaults with the server cap out of the way: the session's database keeps the running
    jobs of every earlier test. This machine's config.local.json is not read."""
    from api.services import job_queue as q, job_scheduler
    monkeypatch.setattr(q, "_SETTINGS", {"maxGenerations": 10000,
                                         "startQueuedAfterRestart": False, "pausedDays": 7,
                                         "interruptedAfterMinutes": 10, "keepFinishedDays": 90})
    monkeypatch.setattr(q, "_kick", q._kick)            # put back after the test
    monkeypatch.setattr(q, "_try_start", q._try_start)
    monkeypatch.setattr(job_scheduler, "_SCHEDULER", job_scheduler._SCHEDULER)
    if "db" not in request.fixturenames:
        return
    db = request.getfixturevalue("db")
    # No job an earlier test left waiting: this test's scheduler would start it for real -- a
    # clone of its project's repository, over the network for a seeded one.
    for job in db.jobs.in_status(q.WAITING):
        db.jobs.transition(job.id, (job.status,), "removed")
    sched = job_scheduler.install(db)
    monkeypatch.setattr(q, "_kick", lambda: sched.round(sweep=False))


#: The threads of a job (api/services/pipeline_runner.py): its body, a run followed again, its
#: alive signal.
_JOB_THREADS = ("job-", "export-", "reexport-", "resume-", "follow-", "beat-")


@pytest.fixture(autouse=True)
def _job_threads_end_with_their_test():
    """A job thread a test starts ends within that test. Left running, it ended its job during a
    later test -- and a job's end starts the next job (`job_queue.after_end`), so it started that
    test's jobs from outside it, at any moment."""
    import threading
    before = set(threading.enumerate())
    yield
    for t in threading.enumerate():
        if t not in before and t.name.startswith(_JOB_THREADS):
            t.join(timeout=15)


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
