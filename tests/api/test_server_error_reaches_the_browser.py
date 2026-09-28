"""A 500 carries the CORS headers, so the web app can read its message.

Starlette answers an unhandled exception from ServerErrorMiddleware, outside CORSMiddleware. The
response had no `Access-Control-Allow-Origin`, so the browser blocked it as a CORS failure and the
web app showed "Failed to fetch" -- for a database timeout, a constraint violation, anything.
"""
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app

ORIGIN = "http://localhost:5173"


def test_an_unhandled_error_is_readable_cross_origin(db, client, auth_header):
    # A second client on the same app, so the session `client` fixture's database override
    # stays exactly as it is (clearing it would point every later test at the configured
    # database), and not entered as a context manager, so no second startup runs.
    raw = TestClient(app, raise_server_exceptions=False)
    with patch.object(type(db.projects), "list_for_user", side_effect=RuntimeError("boom")):
        r = raw.get("/api/v1/projects", headers={**auth_header, "Origin": ORIGIN})
    assert r.status_code == 500
    assert r.headers.get("access-control-allow-origin") == ORIGIN
    assert r.json()["error"] == {"code": "INTERNAL_ERROR", "message": "boom", "status": 500}
