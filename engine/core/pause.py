"""A run's pause: it stops at a safe point when its job asks (docs/design/JOB_SCHEDULING_DESIGN.md §8;
docs/spec/JOB_SCHEDULING_SPEC.md REQ-JS-22, 23).

The API sets the job's `pause_requested_at` (`POST …/jobs/{j}/pause`). Each process of the run asks
for it at its pause points -- between phases, between components, per translation unit, before each
item the LLM is asked about -- from the database at most every 15 s, and once asked it stops:
`check()` raises `PauseRequested`, a BaseException, so the pipeline's `except Exception` blocks let it
through to the step script's entry, which exits 75 (`exits_paused`, `EXIT_PAUSED`). The process's
exit hooks then save every cache's buffer, so a pause keeps every LLM answer received.

Resume redoes the step it stopped in, not the exact item (the user, 2026-10-19): `analyzer.py
resume` runs the parse again, Phase 2 again from the stored parse, or the components not finished,
and the answers already saved come back from the cache.

The job is the run's `ANALYZER_JOB_ID` -- `--job-id`, or the command line's own record. Without one,
or without a database, nothing is ever asked: `requested()` is False and `check()` does nothing.
"""
from __future__ import annotations

import functools
import os
import sys
import threading
import time
from typing import Callable, Optional

#: The exit code of a run that paused at a safe point.
EXIT_PAUSED = 75

#: Seconds between two reads of the job's request, per process.
ASK_EVERY = 15.0

_lock = threading.Lock()
_asked_at: Optional[float] = None
_asked = False


class PauseRequested(BaseException):
    """The run's job asked it to pause: raised at a pause point. A BaseException, as
    KeyboardInterrupt is, so a stage's `except Exception` does not swallow it."""


def job_id() -> Optional[str]:
    return os.environ.get("ANALYZER_JOB_ID") or None


def _read(jid: str) -> bool:
    """Whether job `jid` is running and asked to pause, in the database. False when it cannot be
    read: a pause is a convenience, never a reason for a run to fail."""
    try:
        from .db import get_engine, is_database_configured
        if not is_database_configured():
            return False
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if root not in sys.path:
            sys.path.insert(0, root)
        from sqlalchemy import select
        from api.db.postgres import schema as s
        j = s.analysis_jobs
        with get_engine().connect() as cx:
            row = cx.execute(select(j.c.status, j.c.pause_requested_at)
                             .where(j.c.id == jid)).first()
        return row is not None and row.status == "running" and row.pause_requested_at is not None
    except Exception:                                   # noqa: BLE001 - see docstring
        return False


def requested(*, read: Optional[Callable[[str], bool]] = None) -> bool:
    """Whether the run's job asks it to pause -- read at most every `ASK_EVERY` seconds, and once
    asked, asked for the rest of the process. False without a job."""
    global _asked_at, _asked
    jid = job_id()
    if not jid:
        return False
    now = time.monotonic()
    with _lock:
        if _asked or (_asked_at is not None and now - _asked_at < ASK_EVERY):
            return _asked
        _asked_at = now
    got = (read or _read)(jid)
    with _lock:
        _asked = _asked or got
        return _asked


def check(where: str = "") -> None:
    """A pause point: stop here when the run's job asks. On the main thread only -- raised in a
    worker thread it would end that thread, not the run; a pool's items are checked by the loop
    that hands them out."""
    if threading.current_thread() is not threading.main_thread():
        return
    if requested():
        raise PauseRequested(where)


def exits_paused(fn):
    """A step script's entry: a pause that reaches it exits `EXIT_PAUSED`, after the exit hooks
    that save the caches' buffers."""
    @functools.wraps(fn)
    def run(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except PauseRequested as exc:
            where = str(exc)
            print("paused at a safe point" + (": " + where if where else "")
                  + " -- `analyzer.py resume` carries it on", file=sys.stderr, flush=True)
            sys.exit(EXIT_PAUSED)
    return run


def reset() -> None:
    """Forget what was read (tests)."""
    global _asked_at, _asked
    with _lock:
        _asked_at, _asked = None, False
