"""
API test fixtures.

Provides:
  client      — TestClient wired to an InMemoryDatabase (no pipeline, no disk I/O)
  auth_header — Authorization header for alice (admin)
  admin_token — raw JWT for alice
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from api.main import app
from api.db.in_memory import InMemoryDatabase
from api.db.postgres.database import SqlDatabase
from api.db.session import get_db


def _sqlite_backed() -> SqlDatabase:
    # StaticPool + one shared connection: an in-memory SQLite DB is otherwise
    # per-connection, so TestClient's threadpool would each see an empty database.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    return SqlDatabase(engine, create_schema=True).seed()


@pytest.fixture(scope="session", params=["memory", "sql"])
def db(request):
    """The full API suite runs against BOTH backends (the PG-2 parity guarantee):
    in-memory, and the SQL backend over SQLite with identical seed data."""
    return InMemoryDatabase() if request.param == "memory" else _sqlite_backed()


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
