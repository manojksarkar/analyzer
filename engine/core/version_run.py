"""A version's writer: one at a time, what it is doing, and each component's documents.

Three things a run that lasts days needs and a short one could ignore (staged generation,
2026-10-01):

* **One writer per version.** `generate`, `export`, `reexport`, `resume` and a web job all end by
  storing the version's output, and storing REPLACES what was stored
  (`model_store.persist_output_files`): two at once and the second wipes the first's documents.
  `writing()` takes a Postgres advisory lock for the version and holds it, on a connection of its
  own, for the whole run. The lock goes with the process, so a run killed on day 4 does not leave
  the version locked. SQLite (tests, local runs) has no such lock: there `writing()` records the
  run and locks nothing.
* **What the run is doing.** `version_runs` holds the latest run's command line, process, log and
  progress; the phases' `ProgressReporter` publishes into it (`progress`, at most every 20 s).
  Whether the run is ALIVE is the lock (`holder`), never that row: a killed run cannot update it.
* **Each component's documents.** `version_components`: waiting -> generating -> generated |
  failed, written by run.py around each component's Phases 3-4 (`mark_components`).

Nothing here may fail a run. Every write is best-effort and says so on stderr when it fails; the
one deliberate refusal is `VersionBusy`, raised before a run starts.
"""
from __future__ import annotations

import datetime
import os
import socket
import sys
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterable, Optional

# The advisory lock's first key, "the analyzer's version writer"; the second is the version id's
# hash. Two-key form, so pg_locks shows them as classid/objid and `holder` can find the process.
LOCK_NAMESPACE = 72157
_KEY2 = "(hashtext(:v) & 2147483647)"

STATES = ("waiting", "generating", "generated", "failed")
_PUBLISH_EVERY = 20.0          # seconds between progress writes from one process
_last_publish = 0.0
_warned: set = set()


class VersionBusy(RuntimeError):
    """Another process holds the version's writer lock."""

    def __init__(self, version_id: str, holder: Optional[dict]):
        self.version_id, self.holder = version_id, holder
        super().__init__(f"version {version_id} is being written by {describe(holder)}. Wait for "
                         f"it to finish (`python analyzer.py progress ...` shows how far it is), "
                         f"or stop that process first.")


def describe(holder: Optional[dict]) -> str:
    if not holder:
        return "another process"
    since = holder.get("since")
    when = since.strftime("%Y-%m-%d %H:%M") if hasattr(since, "strftime") else str(since or "?")
    return f"{holder.get('application') or 'another process'} (since {when})"


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _schema():
    """api/db/postgres/schema.py, with the repo root on the path -- a phase process (run.py and
    what it starts) has only engine/ there, so the import fails without it (as core/model_store
    arranges for itself)."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if root not in sys.path:
        sys.path.insert(0, root)
    from api.db.postgres import schema
    return schema


def _engine():
    from .db import get_engine, is_database_configured
    if not is_database_configured():
        return None
    return get_engine()


def _is_pg(eng) -> bool:
    return eng is not None and eng.dialect.name == "postgresql"


def _note(what: str, exc: BaseException) -> None:
    """Say once per kind that a best-effort write failed, and carry on."""
    if what in _warned:
        return
    _warned.add(what)
    print(f"note: {what} ({type(exc).__name__}: {exc})", file=sys.stderr)


# ---------------------------------------------------------------------------
# The writer lock
# ---------------------------------------------------------------------------

def holder(version_id: str, *, engine=None) -> Optional[dict]:
    """Who holds the version's writer lock: {backend_pid, application, since, client}, or None
    when nobody does -- or when the database cannot tell (SQLite). `engine`: the caller's own
    (the API's), instead of the engine's configured database."""
    eng = engine if engine is not None else _engine()
    if not _is_pg(eng) or not version_id:
        return None
    from sqlalchemy import text
    with eng.connect() as cx:
        r = cx.execute(text(
            "SELECT a.pid, a.application_name, a.backend_start, host(a.client_addr) "
            "  FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid "
            " WHERE l.locktype = 'advisory' AND l.granted AND l.objsubid = 2 "
            f"  AND l.classid::bigint = :ns AND l.objid::bigint = {_KEY2}"),
            {"ns": LOCK_NAMESPACE, "v": version_id}).first()
    if r is None:
        return None
    return {"backend_pid": r[0], "application": r[1], "since": r[2], "client": r[3]}


def alive(version_id: str, *, engine=None) -> Optional[bool]:
    """True: a writer holds the version. False: none does. None: this database cannot tell."""
    eng = engine if engine is not None else _engine()
    if not _is_pg(eng):
        return None
    return holder(version_id, engine=eng) is not None


class _Run:
    """What `writing()` yields: tell it how the command ended (`ok(rc)`)."""

    def __init__(self) -> None:
        self.outcome: Optional[str] = None

    def ok(self, rc: int = 0) -> int:
        self.outcome = "complete" if not rc else "failed"
        return rc


@contextmanager
def writing(version_id: str, *, command: str, argv: Optional[list] = None,
            log_path: Optional[str] = None, code_dir: Optional[str] = None, engine=None):
    """Hold the version's writer lock and record the run for its duration.

    Raises `VersionBusy` -- before anything is written -- when another process holds it.
    `engine`: the caller's own (the API passes its database's, so a job is locked and recorded
    where the API keeps its versions). The lock lives on a session of its own (`_LockSession`)."""
    eng = engine if engine is not None else _engine()
    lock = None
    if _is_pg(eng) and version_id:
        lock = _LockSession(eng, version_id, command)
        if not lock.acquire():
            lock.close()
            raise VersionBusy(version_id, holder(version_id, engine=eng))
        lock.start_heartbeat()
    record_start(version_id, command=command, argv=argv, log_path=log_path, code_dir=code_dir,
                 engine=eng)
    run = _Run()
    try:
        yield run
        if run.outcome is None:
            run.outcome = "complete"
    except SystemExit as exc:
        run.outcome = "complete" if exc.code in (None, 0) else "failed"
        raise
    except BaseException:
        run.outcome = "failed"
        raise
    finally:
        record_end(version_id, run.outcome or "failed", engine=eng)
        if lock is not None:
            lock.close()


HEARTBEAT_SECONDS = 120.0


class _LockSession:
    """The writer lock's own database session, for a run that holds it for days.

    * Its own connection, AUTOCOMMIT: an open transaction held for days would pin the database's
      oldest snapshot and stop VACUUM.
    * Not from the pool, and discarded at the end: a pooled session that still held the lock would
      keep the version locked for as long as this process lives.
    * TCP keepalives, and a heartbeat (`SELECT 1` every two minutes): an idle session can be cut by
      a firewall or an idle timeout, which releases the lock in silence -- and then a second writer
      may start. The heartbeat notices a lost session and takes the lock again on a new one, and
      keeps trying on every beat until it has it (the server may hold the dead session's lock for a
      while). It says so each time; a lock another process has taken meanwhile it says loudly.
    """

    _KEEPALIVE = {"keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10,
                  "keepalives_count": 6, "connect_timeout": 10}

    def __init__(self, engine, version_id: str, command: str):
        import threading
        from sqlalchemy import create_engine
        from sqlalchemy.pool import NullPool
        self.version_id = version_id
        self.app = f"analyzer {command} pid {os.getpid()} on {socket.gethostname()}"[:63]
        args = dict(self._KEEPALIVE) if engine.dialect.driver.startswith("psycopg") else {}
        self._engine = create_engine(engine.url, poolclass=NullPool, connect_args=args)
        if self._engine.dialect.name == "postgresql":
            # A busy server's refused or timed-out connection is tried again, not the run failed
            # at its start or its lock left untaken (a heartbeat tries again anyway).
            from core.db import retry_connects
            retry_connects(self._engine)
        self._cx = None
        self._held = False
        self._stop = threading.Event()
        self._thread = None
        self._mutex = threading.Lock()

    def _connect(self):
        from sqlalchemy import text
        cx = self._engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        cx.execute(text("SELECT set_config('application_name', :a, false)"), {"a": self.app})
        return cx

    def _try_lock(self) -> bool:
        from sqlalchemy import text
        return bool(self._cx.execute(text(f"SELECT pg_try_advisory_lock(:ns, {_KEY2})"),
                                     {"ns": LOCK_NAMESPACE, "v": self.version_id}).scalar())

    def acquire(self) -> bool:
        with self._mutex:
            self._cx = self._connect()
            self._held = self._try_lock()
            return self._held

    def start_heartbeat(self) -> None:
        import threading
        self._thread = threading.Thread(target=self._beat, daemon=True,
                                        name=f"version-lock-{self.version_id}")
        self._thread.start()

    def _discard(self) -> None:
        if self._cx is not None:
            try:
                self._cx.invalidate()
                self._cx.close()
            except Exception:                             # noqa: BLE001
                pass
            self._cx = None

    def _beat(self) -> None:
        from sqlalchemy import text
        while not self._stop.wait(HEARTBEAT_SECONDS):
            with self._mutex:
                if self._stop.is_set():                   # close() is under way: never re-take
                    return
                try:
                    if self._cx is None:
                        raise RuntimeError("no session")
                    self._cx.execute(text("SELECT 1"))
                    if self._held:
                        continue
                except Exception as exc:                  # noqa: BLE001 - the session is gone
                    print(f"warning: the database session holding the lock on version "
                          f"{self.version_id} was lost ({type(exc).__name__}); taking the lock "
                          f"again", file=sys.stderr)
                    self._discard()
                    self._held = False
                try:
                    if self._cx is None:
                        self._cx = self._connect()
                    self._held = self._try_lock()
                    if self._held:
                        print(f"note: the lock on version {self.version_id} is held again",
                              file=sys.stderr)
                    else:
                        h = holder(self.version_id, engine=self._engine)
                        print(f"WARNING: the lock on version {self.version_id} is held by "
                              f"{describe(h)}, not this run -- if that is not this run's lost "
                              f"session, two writers are at work: let one finish before trusting "
                              f"the result. Retrying.", file=sys.stderr)
                except Exception as exc:                  # noqa: BLE001 - try again next beat
                    self._discard()
                    print(f"warning: could not take the lock on version {self.version_id} again "
                          f"({type(exc).__name__}: {exc}); retrying", file=sys.stderr)

    def close(self) -> None:
        from sqlalchemy import text
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=30)
        with self._mutex:
            if self._cx is not None and self._held:
                try:
                    self._cx.execute(text(f"SELECT pg_advisory_unlock(:ns, {_KEY2})"),
                                     {"ns": LOCK_NAMESPACE, "v": self.version_id})
                except Exception:                         # noqa: BLE001 - closing releases it
                    pass
            self._discard()
            self._held = False
        self._engine.dispose()


# ---------------------------------------------------------------------------
# version_runs
# ---------------------------------------------------------------------------

def _upsert(cx, table, key: Dict[str, Any], values: Dict[str, Any]) -> None:
    from sqlalchemy import and_, insert, update
    cond = and_(*[table.c[k] == v for k, v in key.items()])
    if cx.execute(update(table).where(cond).values(**values)).rowcount == 0:
        cx.execute(insert(table).values(**key, **values))


def record_start(version_id: str, *, command: str, argv: Optional[list] = None,
                 log_path: Optional[str] = None, code_dir: Optional[str] = None,
                 engine=None) -> None:
    eng = engine if engine is not None else _engine()
    if eng is None or not version_id:
        return
    try:
        s = _schema()
        with eng.begin() as cx:
            _upsert(cx, s.version_runs, {"version_id": version_id}, {
                "command": command, "argv": list(argv or []), "pid": os.getpid(),
                "host": socket.gethostname(), "code_dir": code_dir, "log_path": log_path,
                "started_at": _now(), "finished_at": None, "outcome": "running",
                "stage": None, "done": None, "total": None, "stage_started_at": None,
                "progress_at": None})
    except Exception as exc:                     # noqa: BLE001 - see the module docstring
        _note("the run could not be recorded (no versions row yet?)", exc)


def record_end(version_id: str, outcome: str, *, engine=None) -> None:
    eng = engine if engine is not None else _engine()
    if eng is None or not version_id:
        return
    try:
        from sqlalchemy import update
        s = _schema()
        t = s.version_runs
        with eng.begin() as cx:
            cx.execute(update(t).where(t.c.version_id == version_id)
                       .values(outcome=outcome, finished_at=_now()))
    except Exception as exc:                     # noqa: BLE001
        _note("the run's end could not be recorded", exc)


def run_row(version_id: str, *, engine=None) -> Optional[Dict[str, Any]]:
    eng = engine if engine is not None else _engine()
    if eng is None:
        return None
    from sqlalchemy import select
    s = _schema()
    t = s.version_runs
    with eng.connect() as cx:
        r = cx.execute(select(t).where(t.c.version_id == version_id)).first()
    return dict(r._mapping) if r is not None else None


def progress(stage: str, done: int, total: int, stage_started: Optional[float] = None, *,
             force: bool = False, version_id: Optional[str] = None) -> None:
    """Publish a phase's progress onto the version's run row, at most every 20 s per process
    (`force` for a stage's start and end). Called by `ProgressReporter`, and by the flowchart
    engine (its own process: it passes `version_id`); a no-op without a version or a database, and
    for the narrowed parse's scratch model."""
    global _last_publish
    try:
        from . import run_context
        vid = version_id or run_context.version_id()
        if not vid or (not version_id and run_context.scratch_model()):
            return
        now = time.monotonic()
        if not force and now - _last_publish < _PUBLISH_EVERY:
            return
        _last_publish = now
        eng = _engine()
        if eng is None:
            return
        s = _schema()
        started = (datetime.datetime.fromtimestamp(stage_started, datetime.timezone.utc)
                   if stage_started else None)
        with eng.begin() as cx:
            _upsert(cx, s.version_runs, {"version_id": vid}, {
                "stage": stage, "done": int(done), "total": int(total),
                "stage_started_at": started, "progress_at": _now()})
    except Exception as exc:                     # noqa: BLE001
        _note("progress could not be recorded", exc)


# ---------------------------------------------------------------------------
# version_components
# ---------------------------------------------------------------------------

def mark_components(version_id: Optional[str], components: Iterable[str], state: str, *,
                    error: Optional[str] = None) -> None:
    """Move components to `state` (waiting | generating | generated | failed)."""
    comps = [c for c in dict.fromkeys(components or ()) if c]
    if not version_id or not comps or state not in STATES:
        return
    eng = _engine()
    if eng is None:
        return
    now = _now()
    stamps = {
        "waiting": {"requested_at": now, "started_at": None, "finished_at": None, "error": None},
        "generating": {"started_at": now, "finished_at": None, "error": None},
        "generated": {"finished_at": now, "error": None},
        "failed": {"finished_at": now, "error": (error or "")[:2000] or None},
    }[state]
    try:
        from sqlalchemy import and_, insert, select, update
        s = _schema()
        t = s.version_components
        with eng.begin() as cx:
            for c in comps:
                key = and_(t.c.version_id == version_id, t.c.component == c)
                current = cx.execute(select(t.c.state).where(key)).scalar()
                if current is None:
                    cx.execute(insert(t).values(version_id=version_id, component=c,
                                                **{"requested_at": now, "state": state,
                                                   **stamps}))
                elif not (state == "waiting" and current == "waiting"):
                    # Asked for again while still waiting (the incremental engine starts run.py
                    # twice): keep when it was first asked for.
                    cx.execute(update(t).where(key).values(state=state, **stamps))
    except Exception as exc:                     # noqa: BLE001
        _note("component states could not be recorded", exc)


def generated_components(version_id: str) -> list:
    """Components the version has documents for (by any run), as their output folder names."""
    eng = _engine()
    if eng is None or not version_id:
        return []
    from sqlalchemy import select
    s = _schema()
    d, t = s.documents, s.version_components
    with eng.connect() as cx:
        names = {r[0] for r in cx.execute(select(d.c.component).where(d.c.version_id == version_id))}
        names |= {r[0] for r in cx.execute(select(t.c.component).where(
            (t.c.version_id == version_id) & (t.c.state == "generated")))}
    return sorted(n for n in names if n)


def component_rows(version_id: str) -> Dict[str, Dict[str, Any]]:
    eng = _engine()
    if eng is None:
        return {}
    from sqlalchemy import select
    s = _schema()
    t = s.version_components
    with eng.connect() as cx:
        return {r.component: dict(r._mapping)
                for r in cx.execute(select(t).where(t.c.version_id == version_id))}
