"""The scheduler -- starts the next job when it may run (docs/design/JOB_SCHEDULING_DESIGN.md §5,
§7, §8, §10; docs/spec/JOB_SCHEDULING_SPEC.md REQ-JS-11..20, 24).

One thread, in the server that holds the job-runner lock (`pipeline_runner.claim_job_runner`). A
round every 10 s, and at once when kicked -- a submit, a job's end, a release, a resume:

1. sweeps, at most once a minute: running jobs nobody follows (followed again, or interrupted when
   silent too long), paused jobs past `jobs.pausedDays` (cancelled), and once a day the records
   past `jobs.keepFinishedDays`;
2. claims: resume requests first, then each project's generation head -- the longest waiting
   first, under `jobs.maxGenerations` -- then each project's oldest update whose version is free;
3. each job claimed is launched (`pipeline_runner.launch_job`).

A claim is one transaction that checks again (`jobs.claim`): the lane, the version, the cap.
"""
from __future__ import annotations

import logging
import os
import socket
import threading
import time
from datetime import timedelta
from typing import Any, Callable, List, Optional

from . import job_queue as q

_log = logging.getLogger(__name__)

ROUND_SECONDS = 10.0
SWEEP_SECONDS = 60.0
RETENTION_SECONDS = 24 * 3600.0
#: After the database comes back, runs get this long to send their alive signal again before
#: anyone is called silent: an outage stops every signal at once (REQ-JS-17).
DB_STEADY_SECONDS = 120.0

RUNNER = ("api %s pid %d" % (socket.gethostname(), os.getpid()))[:120]


class Scheduler:
    def __init__(self, db: Any, launch: Callable[[Any, Any, bool], None]):
        self.db = db
        self.launch = launch
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._db_up_since: Optional[float] = None
        #: When the last sweep and the last clean-up of old records ran (`time.monotonic()`); None
        #: until the first, which the first round makes.
        self._last_sweep: Optional[float] = None
        self._last_retention: Optional[float] = None
        self._thread: Optional[threading.Thread] = None
        #: Hold the waiting jobs in the first round (a restart, `start_up`).
        self.hold_first = False

    # -- the thread -------------------------------------------------------
    def start(self) -> "Scheduler":
        self._thread = threading.Thread(target=self._loop, daemon=True, name="job-scheduler")
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def kick(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(ROUND_SECONDS)
            self._wake.clear()
            if self._stop.is_set():
                return
            try:
                self.round()
            except Exception as exc:                    # noqa: BLE001 - the next round comes
                self._db_up_since = None
                _log.warning("job scheduler round failed: %s: %s", type(exc).__name__, exc)

    # -- a round ----------------------------------------------------------
    def runs_jobs(self) -> bool:
        """Whether this server schedules: it holds the job-runner lock -- claimed again when a
        database restart dropped it -- or has a database with none to hold (one process)."""
        engine = getattr(self.db, "_engine", None)
        if engine is None or getattr(getattr(engine, "dialect", None), "name", "") != "postgresql":
            return True
        from . import pipeline_runner as pr
        try:
            return pr.runner_still_held(engine) or pr.claim_job_runner(engine)
        except Exception:                               # noqa: BLE001 - not now
            return False

    def round(self, *, sweep: bool = True) -> List[Any]:
        """One round: sweeps when due, then every claim that may be made now; the jobs started."""
        if not self.runs_jobs():
            return []
        with self._lock:
            self._db_answers()
            if self.hold_first:
                self.hold_first = False
                held = q.hold_waiting(self.db)
                if held:
                    _log.warning("%d waiting job(s) held after the restart, in %d project(s): a "
                                 "super admin starts or clears them", sum(held.values()),
                                 len(held))
            t = time.monotonic()
            if sweep and (self._last_sweep is None or t - self._last_sweep >= SWEEP_SECONDS):
                self._last_sweep = t
                self.sweep()
            started = self._claims()
            # Launched before another round may begin: a job claimed here is running, and a
            # round that came meanwhile -- a submit's own, say -- must find its thread there,
            # not claimed and not yet started. A launch only starts a thread.
            for job, resumed in started:
                self._launch(job, resumed)
        for pid in {j.project_id for j, _ in started}:
            q.refresh_messages(self.db, pid)
        return [j for j, _ in started]

    def try_start(self, db: Any, job: Any) -> bool:
        """A claim round now, in the request: whether `job` is running -- started by this round, or
        by one that came first (REQ-JS-06)."""
        if any(j.id == job.id for j in self.round(sweep=False)):
            return True
        now_is = db.jobs.get(job.id)
        return now_is is not None and now_is.status == "running"

    def _db_answers(self) -> None:
        self.db.jobs.in_status(("running",))           # raises when the database does not answer
        if self._db_up_since is None:
            self._db_up_since = time.monotonic()

    # -- claims (§5) ---------------------------------------------------------
    def _claims(self) -> List[tuple]:
        db = self.db
        cap = int(q.settings().get("maxGenerations", 2))
        at = q.now()
        holding = db.jobs.in_status(q.HOLDING)
        held_projects = {j.project_id for j in db.jobs.in_status(("held",))}
        busy_lanes = {(h.project_id, q.lane_of(h)) for h in holding}
        running_gen = sum(1 for h in holding
                          if h.status == "running" and q.lane_of(h) == q.GENERATION)
        started: List[tuple] = []

        def version_busy(job: Any) -> bool:
            if q.version_writer(db, job, holding) is not None:
                return True
            vid = getattr(job, "version_id", None)
            if not vid:
                return False
            from .pipeline_runner import version_writer_busy
            return bool(version_writer_busy(db, vid))

        # 1. resume requests: a paused job holds its lane already, so only the cap and its
        #    version decide (REQ-JS-24).
        asked = sorted((h for h in holding if h.status == "paused" and h.resume_requested_at),
                       key=lambda j: (q.aware(j.resume_requested_at), j.id))
        for job in asked:
            if running_gen >= cap:
                break
            if not version_busy(job) and self._claim(job, "paused", cap, at):
                started.append((job, True))
                running_gen += 1

        waiting = db.jobs.in_status(("queued",))
        # 2. generations: each free lane offers its head; the longest waiting starts (REQ-JS-13).
        heads = {}
        for job in sorted((w for w in waiting if q.lane_of(w) == q.GENERATION), key=q.order_key):
            pid = job.project_id
            if pid in heads or pid in held_projects or (pid, q.GENERATION) in busy_lanes:
                continue
            heads[pid] = job
        for job in sorted(heads.values(), key=lambda j: (q.place_of(j), j.id)):
            if running_gen >= cap:
                break
            if version_busy(job):
                continue                               # the head waits: its lane is not skipped
            if self._claim(job, "queued", cap, at):
                started.append((job, False))
                running_gen += 1

        # 3. updates: each free lane starts its oldest update whose version is free; one held by
        #    its version is passed and keeps its place (REQ-JS-12).
        by_project: dict = {}
        for job in sorted((w for w in waiting if q.lane_of(w) == q.UPDATE), key=q.order_key):
            by_project.setdefault(job.project_id, []).append(job)
        for pid, jobs in by_project.items():
            if pid in held_projects or (pid, q.UPDATE) in busy_lanes:
                continue
            for job in jobs:
                if version_busy(job):
                    continue
                if self._claim(job, "queued", None, at):
                    started.append((job, False))
                    break
        return started

    def _claim(self, job: Any, from_status: str, cap: Optional[int], at) -> bool:
        values = {"current_activity": "Starting…", "activity_detail": ""}
        if from_status == "paused":
            paused = q.aware(getattr(job, "paused_at", None))
            more = (at - paused).total_seconds() if paused else 0.0
            values.update(paused_seconds=int((job.paused_seconds or 0) + max(0.0, more)),
                          paused_at=None, pause_requested_at=None, resume_requested_at=None,
                          current_activity="Resuming…")
        try:
            ok = self.db.jobs.claim(job.id, from_status,
                                    cap=cap if q.lane_of(job) == q.GENERATION else None,
                                    runner=RUNNER, now=at, **values)
        except Exception as exc:                        # noqa: BLE001 - not this round
            _log.warning("job %s: claim failed: %s", job.id, exc)
            return False
        if ok:
            kind = "resumed" if from_status == "paused" else "started"
            q.record(self.db, job.project_id, kind, job_id=job.id,
                     waited_seconds=(None if from_status == "paused" else
                                     int((at - q.place_of(job)).total_seconds())))
            q.tell(self.db, job, "job_started",
                   "%s: %s." % ("Resumed" if from_status == "paused" else "Started",
                                q.describe(job)))
        return ok

    def _launch(self, job: Any, resumed: bool) -> None:
        fresh = self.db.jobs.get(job.id) or job
        try:
            self.launch(self.db, fresh, resumed)
        except Exception as exc:                        # noqa: BLE001 - recorded on the job
            _log.error("job %s could not be launched: %s", job.id, exc)
            from .pipeline_runner import _mark_failed
            _mark_failed(self.db, job.id, q.ended_message(
                "Failed: the job could not be started (%s: %s)." % (type(exc).__name__, exc)))
            q.after_end(self.db, job.id)

    # -- sweeps (§7, §8, §15) --------------------------------------------------
    def sweep(self) -> None:
        db = self.db
        s = q.settings()
        at = q.now()
        from . import pipeline_runner as pr
        # A background run nobody follows any more is followed again (what `_watch_jobs` did).
        try:
            pr.fail_interrupted_jobs(db, before=at - timedelta(seconds=120), reattach_only=True)
        except Exception as exc:                        # noqa: BLE001
            _log.warning("job sweep: following runs again failed: %s", exc)
        # Silent too long (REQ-JS-20) -- never in the first minutes after an outage.
        steady = (self._db_up_since is not None
                  and time.monotonic() - self._db_up_since >= DB_STEADY_SECONDS)
        if steady:
            limit = timedelta(minutes=float(s.get("interruptedAfterMinutes", 10)))
            for job in db.jobs.in_status(("running",)):
                if not self._silent(job, at, limit):
                    continue
                q.interrupt(db, job, q.ended_message(
                    "Interrupted: no sign of life for %d minutes — its process stopped, or its "
                    "machine did." % int(limit.total_seconds() // 60),
                    "Start it again: it joins the back of its lane."))
        # Paused too long (REQ-JS-24).
        days = float(s.get("pausedDays", 7))
        for job in db.jobs.in_status(("paused",)):
            paused = q.aware(getattr(job, "paused_at", None))
            if paused is not None and at - paused >= timedelta(days=days):
                q.cancel_paused_too_long(db, job, days)
        # The records (REQ-JS-34), once a day.
        if (self._last_retention is None
                or time.monotonic() - self._last_retention >= RETENTION_SECONDS):
            self._last_retention = time.monotonic()
            try:
                n = db.jobs.prune_ended(at - timedelta(days=float(s.get("keepFinishedDays", 90))))
                if n:
                    _log.info("job records: %d ended job(s) older than %s day(s) removed", n,
                              s.get("keepFinishedDays", 90))
            except Exception as exc:                    # noqa: BLE001
                _log.warning("job records not pruned: %s", exc)

    def _silent(self, job: Any, at, limit) -> bool:
        """A running job is silent when nothing here follows it, its alive signal is older than
        `limit`, and -- where the database can tell -- nobody holds its version's writer lock."""
        from . import pipeline_runner as pr
        if pr.job_alive(job.id) or pr._reexport_alive(job.id):
            return False
        beat = q.aware(getattr(job, "heartbeat_at", None)) or q.aware(job.started_at)
        if beat is None or at - beat < limit:
            return False
        vid = getattr(job, "version_id", None)
        if vid and pr.version_writer_alive(self.db, vid):
            return False
        return True


# ---------------------------------------------------------------------------
# the one scheduler of this process
# ---------------------------------------------------------------------------
_SCHEDULER: Optional[Scheduler] = None


def install(db: Any, launch: Optional[Callable[[Any, Any, bool], None]] = None) -> Scheduler:
    """The scheduler of this process, wired into the queue (`job_queue._kick`, `_try_start`) -- not
    yet started. Tests use it without its thread."""
    global _SCHEDULER
    if launch is None:
        from .pipeline_runner import launch_job as launch
    _SCHEDULER = Scheduler(db, launch)
    q._kick = _SCHEDULER.kick
    q._try_start = _SCHEDULER.try_start
    return _SCHEDULER


def start_up(db: Any) -> Scheduler:
    """At start-up (§10), after the start-up check has followed again or interrupted the running
    web jobs (`api.main._fail_interrupted_jobs`): the thread, whose first round -- once the
    database answers, on the server that runs jobs -- holds the jobs left waiting, unless
    `jobs.startQueuedAfterRestart` (REQ-JS-18)."""
    sched = install(db)
    sched.hold_first = not q.settings().get("startQueuedAfterRestart", False)
    return sched.start()


def kick() -> None:
    if _SCHEDULER is not None:
        _SCHEDULER.kick()
