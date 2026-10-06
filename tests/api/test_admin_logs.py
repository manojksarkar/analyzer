"""The live log over HTTP (api/routes/admin_logs.py, api/middleware/request_log.py;
docs/spec/LIVE_LOGS_SPEC.md REQ-LL-03, -05 … -10).

The reader is pointed at a temporary folder written the way the processes write it.
"""
import datetime as dt
import json
import logging
import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (PROJECT_ROOT, os.path.join(PROJECT_ROOT, "engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from api.middleware import request_log  # noqa: E402
from api.routes import admin_logs  # noqa: E402
from api.services import live_logs as ll  # noqa: E402
from core import logging_setup as ls  # noqa: E402

LOGS = "/api/v1/admin/logs"
TODAY = dt.date.today().isoformat()


def _ts(i):
    start = dt.datetime.combine(dt.date.today(), dt.time(8, 0)).astimezone()
    return (start + dt.timedelta(milliseconds=i)).isoformat(timespec="milliseconds")


def _write(root, name, records):
    folder = root / TODAY
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / name, "a", encoding="utf-8", newline="\n") as fh:
        for rec in records:
            fh.write(json.dumps({"level": "INFO", "source": "engine", "logger": "t", **rec}) + "\n")


@pytest.fixture
def reader(tmp_path, monkeypatch):
    r = ll.LiveLogReader(str(tmp_path))
    monkeypatch.setattr(ll, "READER", r)
    monkeypatch.setattr(admin_logs, "STREAM_PASSES", 1)
    r.root_path = tmp_path
    return r


def _fill(reader, n, **extra):
    _write(reader.root_path, "engine-1.jsonl",
           [{"ts": _ts(i), "message": "line %d" % i, **extra} for i in range(n)])
    reader.poll()


@pytest.fixture
def superuser(db):
    """alice made a superuser for one test, on either backend."""
    user = db.users.get_by_email("alice@aspice.dev")
    engine = getattr(db, "_engine", None)
    if engine is None:                                  # the in-memory store hands out copies
        before, user.is_superuser = user.is_superuser, True
        db.users.update(user)
        yield user.id
        user.is_superuser = before
        db.users.update(user)
        return
    import sqlalchemy as sa
    from api.db.postgres import schema as s
    with engine.begin() as cx:
        cx.execute(sa.update(s.users).where(s.users.c.id == user.id).values(is_superuser=True))
    yield user.id
    with engine.begin() as cx:
        cx.execute(sa.update(s.users).where(s.users.c.id == user.id).values(is_superuser=False))


class TestOnlySuperusers:
    def test_no_sign_in_is_401(self, client, reader):
        assert client.get(LOGS).status_code == 401
        assert client.post(LOGS + "/ticket").status_code == 401

    def test_a_project_admin_is_not_enough(self, client, reader, auth_header, dev_header):
        """alice is admin of p1 and p2, bob a developer: neither sees every project's logs."""
        for header in (auth_header, dev_header):
            assert client.get(LOGS, headers=header).status_code == 403
            assert client.post(LOGS + "/ticket", headers=header).status_code == 403

    def test_a_superuser_reads_them(self, client, reader, auth_header, superuser):
        _fill(reader, 3)
        body = client.get(LOGS, headers=auth_header).json()
        assert [r["message"] for r in body["records"]] == ["line 0", "line 1", "line 2"]
        assert body["cursor"] == 3 and body["level"] == "INFO"


class TestTheTail:
    def test_500_by_default_and_never_more_than_2000(self, client, reader, auth_header, superuser):
        _fill(reader, 2500)
        assert len(client.get(LOGS, headers=auth_header).json()["records"]) == 500
        capped = client.get(LOGS, headers=auth_header, params={"lines": 5000}).json()
        assert capped["lines"] == 2000 and len(capped["records"]) == 2000
        assert capped["records"][-1]["message"] == "line 2499"

    def test_lines_level_and_filters(self, client, reader, auth_header, superuser):
        _write(reader.root_path, "engine-1.jsonl", [
            {"ts": _ts(1), "message": "d", "level": "DEBUG"},
            {"ts": _ts(2), "message": "w", "level": "WARNING", "job": "j1"},
            {"ts": _ts(3), "message": "s", "source": "server"}])
        reader.poll()

        def get(**params):
            body = client.get(LOGS, headers=auth_header, params=params).json()
            return [r["message"] for r in body["records"]]
        assert get() == ["w", "s"]
        assert get(level="DEBUG") == ["d", "w", "s"]
        assert get(lines=1) == ["s"]
        assert get(source="server") == ["s"]
        assert get(job="j1") == ["w"]

    def test_the_configured_level_is_the_default(self, client, reader, auth_header, superuser,
                                                 monkeypatch):
        monkeypatch.setattr(admin_logs, "logs_config", lambda: {
            "liveLines": 500, "maxLines": 2000, "level": "DEBUG", "keepDays": 30})
        _fill(reader, 1, level="DEBUG")
        body = client.get(LOGS, headers=auth_header).json()
        assert body["level"] == "DEBUG" and len(body["records"]) == 1

    def test_an_unknown_level_is_422(self, client, reader, auth_header, superuser):
        assert client.get(LOGS, headers=auth_header, params={"level": "LOUD"}).status_code == 422


def _events(text):
    """[(event, id, data)] from an SSE body."""
    out = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line)
        if "event" in fields:
            out.append((fields["event"], fields.get("id"), fields.get("data")))
    return out


class TestTheStream:
    def _ticket(self, client, header):
        r = client.post(LOGS + "/ticket", headers=header)
        assert r.status_code == 200 and r.json()["expiresIn"] == 60
        return r.json()["ticket"]

    def test_it_needs_a_ticket(self, client, reader):
        assert client.get(LOGS + "/stream").status_code == 401
        assert client.get(LOGS + "/stream", params={"ticket": "made-up"}).status_code == 401

    def test_a_ticket_opens_one_stream(self, client, reader, auth_header, superuser):
        ticket = self._ticket(client, auth_header)
        assert client.get(LOGS + "/stream", params={"ticket": ticket}).status_code == 200
        assert client.get(LOGS + "/stream", params={"ticket": ticket}).status_code == 401

    def test_a_ticket_lasts_60_seconds(self, client, reader, auth_header, superuser, monkeypatch):
        ticket = self._ticket(client, auth_header)
        later = admin_logs.time.monotonic() + 61
        monkeypatch.setattr(admin_logs.time, "monotonic", lambda: later)
        assert client.get(LOGS + "/stream", params={"ticket": ticket}).status_code == 401

    def test_records_after_the_cursor_one_event_each(self, client, reader, auth_header, superuser):
        _fill(reader, 4)
        r = client.get(LOGS + "/stream",
                       params={"ticket": self._ticket(client, auth_header), "after": 2})
        events = _events(r.text)
        assert [(e, i) for e, i, _ in events] == [("log", "3"), ("log", "4")]
        assert json.loads(events[0][2])["message"] == "line 2"

    def test_last_event_id_resumes_too(self, client, reader, auth_header, superuser):
        _fill(reader, 4)
        r = client.get(LOGS + "/stream", params={"ticket": self._ticket(client, auth_header)},
                       headers={"Last-Event-ID": "3"})
        assert [i for _, i, _ in _events(r.text)] == ["4"]

    def test_a_cursor_from_before_a_restart_is_a_gap(self, client, reader, auth_header, superuser):
        _fill(reader, 2)
        r = client.get(LOGS + "/stream",
                       params={"ticket": self._ticket(client, auth_header), "after": 900})
        assert [e for e, _, _ in _events(r.text)] == ["gap"]


# ---------------------------------------------------------------------------
# Request lines (REQ-LL-03)
# ---------------------------------------------------------------------------
class _Capture(logging.Handler):
    """Each record with the request context it was logged under."""
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.seen = []

    def emit(self, record):
        self.seen.append((record.levelname, record.getMessage(),
                          dict(ls.REQUEST_CONTEXT.get() or {}), record.exc_info is not None))


@pytest.fixture
def lines():
    capture = _Capture()
    log = logging.getLogger("api.request")
    log.addHandler(capture)
    yield capture.seen
    log.removeHandler(capture)


class TestRequestLines:
    def test_a_change_is_logged_with_its_ids_and_its_user(self, client, reader, auth_header,
                                                          superuser, lines):
        client.post(LOGS + "/ticket", headers=auth_header)
        level, text, ctx, _ = lines[-1]
        assert level == "INFO" and text.startswith("POST /api/v1/admin/logs/ticket -> 200 (")
        assert text.endswith("user=%s" % superuser)

    def test_the_ids_in_the_path(self, client, auth_header, lines):
        client.post("/api/v1/projects/p1/jobs", headers=auth_header, json={})
        assert lines[-1][2] == {"project": "p1"}
        assert request_log.path_ids("/api/v1/projects/p1/versions/vera072/jobs/jobab17") == \
            {"project": "p1", "version": "vera072", "job": "jobab17"}
        assert request_log.path_ids("/api/v1/projects/p1/jobs/current") == {"project": "p1"}

    def test_a_get_is_not_logged_unless_it_fails(self, client, auth_header, lines):
        client.get("/api/v1/projects", headers=auth_header)
        assert lines == []
        client.get("/api/v1/projects/no-such-project", headers=auth_header)
        assert lines and lines[-1][0] == "WARNING" and "-> 404" in lines[-1][1]

    def test_the_query_string_is_never_logged(self, client, auth_header, lines):
        client.delete("/api/v1/projects/p9?access_token=SECRET", headers=auth_header)
        assert lines and "SECRET" not in lines[-1][1]


def _app():
    """A bare app behind the middleware: a sync route (run in the thread pool) and a failure."""
    app = FastAPI()
    seen = logging.getLogger("test.request_context")

    @app.post("/projects/{pid}/versions/{vid}/thing")
    def thing(pid: str, vid: str):
        seen.info("inside the route")
        return {"ok": True}

    @app.post("/boom")
    def boom():
        raise RuntimeError("broken")

    @app.post("/projects/{pid}/jobs")
    def create_job(pid: str):
        from types import SimpleNamespace
        from api.services.pipeline_runner import note_request_job
        note_request_job(SimpleNamespace(id="jobnew1", version_id="vernew1"))
        return {"ok": True}

    app.add_middleware(request_log.RequestLogMiddleware)
    return app


class TestTheMiddlewareOnItsOwn:
    def test_lines_logged_inside_a_sync_route_carry_the_request_ids(self):
        capture = _Capture()
        log = logging.getLogger("test.request_context")
        log.addHandler(capture)
        try:
            TestClient(_app()).post("/projects/pX/versions/vY/thing")
        finally:
            log.removeHandler(capture)
        assert capture.seen[0][2] == {"project": "pX", "version": "vY"}

    def test_the_line_of_a_request_that_creates_a_job_names_it(self, lines):
        """`POST .../jobs -> 202` is the line that links an API call to its run's engine lines:
        it carries the job and version the run's lines carry, though its path names neither."""
        TestClient(_app()).post("/projects/p7/jobs")
        assert lines[-1][2] == {"project": "p7", "job": "jobnew1", "version": "vernew1"}

    def test_an_exception_is_logged_with_its_traceback(self, lines):
        TestClient(_app(), raise_server_exceptions=False).post("/boom")
        level, text, _, has_exc = lines[-1]
        assert level == "ERROR" and text.startswith("POST /boom -> 500") and has_exc
