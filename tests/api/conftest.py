"""
API test fixtures.

Provides:
  client      — TestClient wired to an InMemoryDatabase (no pipeline, no disk I/O)
  auth_header — Authorization header for alice (admin)
  admin_token — raw JWT for alice
"""
import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.db.in_memory import InMemoryDatabase
from api.db.session import get_db


@pytest.fixture(scope="session")
def db():
    """Fresh in-memory DB shared for the whole session (seed data only)."""
    return InMemoryDatabase()


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
