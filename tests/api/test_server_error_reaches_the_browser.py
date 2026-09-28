"""A 500 carries the CORS headers, so the web app can read its message.

Starlette answers an unhandled exception from ServerErrorMiddleware, outside CORSMiddleware. The
response had no `Access-Control-Allow-Origin`, so the browser blocked it as a CORS failure and the
web app showed "Failed to fetch" -- for a database timeout, a constraint violation, anything.
"""
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.db.session import get_db
from api.main import app

ORIGIN = "http://localhost:5173"


def test_an_unhandled_error_is_readable_cross_origin(db, auth_header):
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app, raise_server_exceptions=False) as c, \
                patch.object(type(db.projects), "list_for_user", side_effect=RuntimeError("boom")):
            r = c.get("/api/v1/projects", headers={**auth_header, "Origin": ORIGIN})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 500
    assert r.headers.get("access-control-allow-origin") == ORIGIN
    assert r.json()["error"] == {"code": "INTERNAL_ERROR", "message": "boom", "status": 500}
