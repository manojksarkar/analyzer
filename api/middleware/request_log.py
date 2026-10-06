"""One live-log line per API call that changes something or fails (docs/spec/LIVE_LOGS_SPEC.md
REQ-LL-03), and the ids of the request on every line logged while it is handled.

Plain ASGI rather than Starlette's `BaseHTTPMiddleware`, which buffers and re-tasks responses:
the SSE streams (job events, the live log itself) pass through untouched.

    POST /api/v1/projects/p1/jobs -> 202 (184 ms) user=u1

A GET that succeeds is not logged -- the web app polls, and those lines would push everything
else out of the last 500. The query string is never logged: some routes take a token in it.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Dict, Optional
from urllib.parse import unquote

from ..db.session import _engine_on_path

_engine_on_path()
from core import logging_setup  # noqa: E402

_log = logging.getLogger("api.request")
#: To the live log only: the console and logs/run_<date>.log stay as they were (REQ-LL-15).
_log.propagate = False

#: Methods whose every call is logged; any other is logged only when it fails.
CHANGING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_IDS = re.compile(r"/(projects|versions|jobs)/([^/?#]+)")
_KEY = {"projects": "project", "versions": "version", "jobs": "job"}


def path_ids(path: str) -> Dict[str, str]:
    """`{"project": .., "version": .., "job": ..}` named in an API path. `jobs/current` names no
    job: a job id starts with `job`."""
    out: Dict[str, str] = {}
    for kind, value in _IDS.findall(path or ""):
        value = unquote(value)
        if kind == "jobs" and not value.startswith("job"):
            continue
        out[_KEY[kind]] = value
    return out


def _user_id(scope) -> Optional[str]:
    """Who called, from the bearer token -- without failing the request over it."""
    for name, value in scope.get("headers") or []:
        if name == b"authorization" and value[:7].lower() == b"bearer ":
            try:
                from .auth import decode_token
                return decode_token(value[7:].decode("latin-1")).get("sub")
            except Exception:                           # noqa: BLE001 - a bad token is a 401 anyway
                return None
    return None


class RequestLogMiddleware:
    def __init__(self, app):
        self.app = app
        handler = logging_setup.live_handler()
        if handler is not None and handler not in _log.handlers:
            _log.addHandler(handler)

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        # A dict even when the path names nothing: a route that creates a job adds its ids
        # (`logging_setup.note_request_ids`).
        token = logging_setup.REQUEST_CONTEXT.set(path_ids(scope.get("path", "")))
        status = {"code": 500}
        start = time.perf_counter()

        async def send_wrapper(message):
            if message.get("type") == "http.response.start":
                status["code"] = message.get("status", 500)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            self._line(scope, 500, start, failed=True)
            raise
        else:
            self._line(scope, status["code"], start)
        finally:
            logging_setup.REQUEST_CONTEXT.reset(token)

    @staticmethod
    def _line(scope, code: int, start: float, failed: bool = False) -> None:
        method = scope.get("method", "")
        if method not in CHANGING and code < 400 and not failed:
            return
        ms = int((time.perf_counter() - start) * 1000)
        text = "%s %s -> %d (%d ms) user=%s" % (method, scope.get("path", ""), code, ms,
                                               _user_id(scope) or "-")
        if failed:
            _log.exception(text)
        elif code >= 500:
            _log.error(text)
        elif code >= 400:
            _log.warning(text)
        else:
            _log.info(text)
