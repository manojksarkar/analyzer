"""The live log for superusers (docs/spec/LIVE_LOGS_SPEC.md): API and engine lines in one stream.

    GET  /admin/logs          the last N records                      (REQ-LL-05, -06)
    POST /admin/logs/ticket   a 60-second, single-use stream ticket    (REQ-LL-10)
    GET  /admin/logs/stream   SSE: one `log` event per record          (REQ-LL-08)

The page reads the tail, then opens the stream with `after=<cursor>`. The stream takes a ticket
rather than the bearer token because a browser `EventSource` cannot send a header; a reconnect
needs a new ticket, and `after=` the last `seq` it saw.
"""
from __future__ import annotations

import asyncio
import enum
import json
import secrets
import threading
import time
from typing import Dict, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse

from ..db.session import _engine_on_path
from ..middleware.auth import require_superuser
from ..models.domain import User
from ..services import live_logs

_engine_on_path()
from core.config import logs_config  # noqa: E402

router = APIRouter(tags=["admin"])

TICKET_SECONDS = 60
STREAM_POLL_SECONDS = 0.5
HEARTBEAT_SECONDS = 15
#: Passes a stream makes before it ends; None = until the client goes. Tests set a number: a
#: test client cannot leave a stream half way.
STREAM_PASSES: Optional[int] = None


class Level(str, enum.Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Source(str, enum.Enum):
    server = "server"
    engine = "engine"


class Step(str, enum.Enum):
    parse = "Parse"
    derive = "Derive"
    views = "Views"
    export_swe3 = "Export SWE.3"
    export_swe4 = "Export SWE.4"


# ---------------------------------------------------------------------------
# Stream tickets -- in memory: one API process (LIVE_LOGS_SPEC, Limitations)
# ---------------------------------------------------------------------------
_tickets: Dict[str, Tuple[str, float]] = {}
_tickets_lock = threading.Lock()


def issue_ticket(user_id: str) -> str:
    now = time.monotonic()
    ticket = secrets.token_urlsafe(24)
    with _tickets_lock:
        for t in [t for t, (_, exp) in _tickets.items() if exp <= now]:
            del _tickets[t]
        _tickets[ticket] = (user_id, now + TICKET_SECONDS)
    return ticket


def redeem_ticket(ticket: Optional[str]) -> Optional[str]:
    """The user a ticket was issued to, or None. A ticket is gone once used."""
    if not ticket:
        return None
    with _tickets_lock:
        held = _tickets.pop(ticket, None)
    if held is None or held[1] <= time.monotonic():
        return None
    return held[0]


# ---------------------------------------------------------------------------
def _level(level: Optional[Level], cfg: dict) -> str:
    if level is not None:
        return level.value
    configured = str(cfg.get("level") or "INFO").upper()
    return configured if configured in live_logs.LEVELS else "INFO"


def _filters(source, project, version, job, step) -> Dict[str, Optional[str]]:
    return {"source": source.value if source else None, "project": project, "version": version,
            "job": job, "step": step.value if step else None}


@router.get("/admin/logs")
def read_logs(
    lines: Optional[int] = Query(None, ge=1, description="how many records; default "
                                 "`logs.liveLines` (500), at most `logs.maxLines` (2000)"),
    level: Optional[Level] = Query(None, description="lowest level; default `logs.level`"),
    source: Optional[Source] = Query(None),
    project: Optional[str] = Query(None),
    version: Optional[str] = Query(None),
    job: Optional[str] = Query(None),
    step: Optional[Step] = Query(None),
    current_user: User = Depends(require_superuser),
):
    """The last N log records of the API and every engine run, oldest first, and `cursor`:
    open the stream with `after=<cursor>` to continue from them. Superusers only."""
    cfg = logs_config()
    n = min(int(lines or cfg["liveLines"]), int(cfg["maxLines"]))
    lvl = _level(level, cfg)
    records, cursor = live_logs.get_reader().tail(
        n, lvl, _filters(source, project, version, job, step))
    return {"records": records, "cursor": cursor, "lines": n, "level": lvl}


@router.post("/admin/logs/ticket")
def stream_ticket(current_user: User = Depends(require_superuser)):
    """A ticket that opens one log stream within 60 seconds (a browser `EventSource` cannot
    send the bearer token). Superusers only."""
    return {"ticket": issue_ticket(current_user.id), "expiresIn": TICKET_SECONDS}


@router.get("/admin/logs/stream")
async def stream_logs(
    request: Request,
    ticket: Optional[str] = Query(None, description="from POST /admin/logs/ticket; used once"),
    after: Optional[int] = Query(None, ge=0, description="the last `seq` seen; default: "
                                 "only records written from now"),
    level: Optional[Level] = Query(None),
    source: Optional[Source] = Query(None),
    project: Optional[str] = Query(None),
    version: Optional[str] = Query(None),
    job: Optional[str] = Query(None),
    step: Optional[Step] = Query(None),
):
    """Server-Sent Events: `log` (one record, `id` = its `seq`), and `gap` when records between
    `after` and what is still kept were lost -- reload the tail then. A heartbeat comment every
    15 s. `Last-Event-ID` works as `after`."""
    if redeem_ticket(ticket) is None:
        raise HTTPException(status_code=401, detail={
            "code": "UNAUTHENTICATED", "status": 401,
            "message": "A stream ticket is needed: POST /api/v1/admin/logs/ticket, then open "
                       "the stream within 60 seconds. A ticket opens one stream."})
    reader = live_logs.get_reader()
    lvl = _level(level, logs_config())
    filters = _filters(source, project, version, job, step)
    last_id = request.headers.get("last-event-id", "")
    cursor = after if after is not None else (int(last_id) if last_id.isdigit() else None)

    async def events():
        nonlocal cursor
        gap = False
        if cursor is None:
            cursor = reader.last_seq()
        elif cursor > reader.last_seq():
            # Numbered by an earlier API process: what follows cannot be placed after it.
            gap, cursor = True, reader.last_seq()
        passes = 0
        while True:
            records, cursor, lost = reader.after(cursor, lvl, filters)
            if passes == 0 and (gap or lost):
                yield {"event": "gap", "data": json.dumps({"cursor": cursor})}
            for rec in records:
                yield {"event": "log", "id": str(rec["seq"]),
                       "data": json.dumps(rec, ensure_ascii=False, default=str)}
            passes += 1
            if (STREAM_PASSES is not None and passes >= STREAM_PASSES) \
                    or await request.is_disconnected():
                break
            await asyncio.sleep(STREAM_POLL_SECONDS)

    return EventSourceResponse(events(), ping=HEARTBEAT_SECONDS)
