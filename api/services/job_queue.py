"""The job queue -- what a submit gets, the order jobs wait in, and what each job says about it.

docs/spec/JOB_SCHEDULING_SPEC.md; docs/design/JOB_SCHEDULING_DESIGN.md §3-§4, §9-§10, §13, §15.

Every job is a row of `analysis_jobs`: its lane, its state, its place. A submit is answered here --
it starts now, it waits with its place, or it is refused -- and every waiting job's
`current_activity` says why it waits, in the field the web app already shows (REQ-JS-35). Starting
a job is the scheduler's (`job_scheduler`): its claim checks again, under a lock of its own.
"""
from __future__ import annotations

import logging
import os
import statistics
import sys
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional

from ..models.domain import AnalysisJob, JobEvent


def _engine_on_path() -> None:
    eng = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(
        __file__)))), "engine")
    if eng not in sys.path:
        sys.path.insert(0, eng)


_engine_on_path()
# The lanes, written once for the API and the command line.
from core.job_lanes import (ENDED, GENERATION, HOLDING, IN_LANE, LANES, UPDATE,  # noqa: E402
                            WAITING, cli_refusal, lane_of_mode)

UTC = timezone.utc
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_log = logging.getLogger(__name__)

PRIORITY = {"high": 0, "normal": 1, "low": 2}
PRIORITY_NAME = {v: k for k, v in PRIORITY.items()}
NORMAL = PRIORITY["normal"]

#: The default limits, as the columns' (migration 0019).
DEFAULT_LIMITS = {GENERATION: 3, UPDATE: 10}
LIMIT_RANGE = (1, 50)

#: The scheduler, reached without importing it (it imports this module). `job_scheduler` sets
#: these when it starts: `_kick()` asks for a round now; `_try_start(db, job)` starts the job at
#: once when it can -- on the server that runs jobs -- and says whether it did.
_kick: Callable[[], None] = lambda: None
_try_start: Callable[[Any, Any], bool] = lambda db, job: False


def now() -> datetime:
    return datetime.now(UTC)


_last_place: Optional[datetime] = None
_PLACE_LOCK = threading.Lock()


def next_place() -> datetime:
    """The time a job takes its place in its lane, or a step of the record happens: now, and always
    after the last one this process gave. On Windows the clock moves in steps of about 15 ms, so two
    submits in a row -- or a CLI run's `submitted` and `started` -- got the same time, and a tie is
    ordered by the id, which is random, not by which came first."""
    global _last_place
    with _PLACE_LOCK:
        t = now()
        if _last_place is not None and t <= _last_place:
            t = _last_place + timedelta(microseconds=1)
        _last_place = t
        return t


def aware(t: Optional[datetime]) -> Optional[datetime]:
    """A stored time as UTC-aware: SQLite hands back naive ones, written as UTC."""
    if t is None:
        return None
    return t if t.tzinfo is not None else t.replace(tzinfo=UTC)


def lane_of(job: Any) -> str:
    return lane_of_mode(getattr(job, "mode", None))


def place_of(job: Any) -> datetime:
    """When the job took its place in its lane."""
    return aware(getattr(job, "submitted_at", None) or getattr(job, "started_at", None)) or _EPOCH


def order_key(job: Any) -> tuple:
    """A lane's order: the generation lane by priority, then the oldest place; the update lane by
    the oldest place alone (REQ-JS-11, 12). The id breaks a tie the same way every time."""
    pr = getattr(job, "priority", NORMAL) if lane_of(job) == GENERATION else NORMAL
    return (NORMAL if pr is None else pr, place_of(job), job.id)


def kick() -> None:
    try:
        _kick()
    except Exception:                                   # noqa: BLE001 - the next round comes
        pass


class JobRefused(Exception):
    """A submit or an action refused: its HTTP status, a code, a message for the person
    (REQ-JS-35), and more fields for the answer -- the jobs in the way."""

    def __init__(self, status: int, code: str, message: str, **extra: Any):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra

    def detail(self) -> dict:
        return {"code": self.code, "message": self.message, "status": self.status, **self.extra}


# ---------------------------------------------------------------------------
# settings -- config.local.json's `jobs` block (engine/core/config.py `jobs_settings`)
# ---------------------------------------------------------------------------
_SETTINGS: Optional[dict] = None
_SETTINGS_LOCK = threading.Lock()


def settings(refresh: bool = False) -> dict:
    """This server's `jobs` settings, read once (restart the API after a change, as for `auth`)."""
    global _SETTINGS
    with _SETTINGS_LOCK:
        if _SETTINGS is None or refresh:
            from core.config import jobs_settings
            _SETTINGS = jobs_settings()
        return dict(_SETTINGS)


# ---------------------------------------------------------------------------
# what a job is, in words
# ---------------------------------------------------------------------------
def kind_of(job: Any) -> str:
    """generation | export | resume | update | rebuild -- `word_files.job_kind`, with a reopened
    web generation (reason `resume`) called a resume."""
    from .word_files import job_kind
    kind = job_kind(job)
    if kind == "generation" and getattr(job, "reason", None) == "resume":
        return "resume"
    return kind


def describe(job: Any) -> str:
    """'generate v4.1', 'export of Lib into v4', 'update of v4' -- a job in a sentence."""
    tag = getattr(job, "version_tag", None) or getattr(job, "version_id", None) or "?"
    kind = kind_of(job)
    names = ((getattr(job, "scope", None) or {}).get("names") or []) if kind in (
        "export", "update", "rebuild") else []
    which = (" (%s)" % ", ".join(names[:3]) + ("…" if len(names) > 3 else "")) if names else ""
    return {"generation": "generate %s" % tag, "export": "export into %s%s" % (tag, which),
            "resume": "resume %s" % tag, "update": "update of %s%s" % (tag, which),
            "rebuild": "rebuild of %s%s" % (tag, which)}.get(kind, "%s %s" % (kind, tag))


def brief(job: Any) -> dict:
    """A job as the queue views and a refusal name it."""
    return {"job_id": job.id, "kind": kind_of(job), "what": describe(job), "status": job.status,
            "version_id": job.version_id, "version_tag": getattr(job, "version_tag", None),
            "priority": PRIORITY_NAME.get(getattr(job, "priority", NORMAL), "normal"),
            "submitted_at": _iso(place_of(job)), "started_by": getattr(job, "started_by", None),
            "origin": getattr(job, "origin", "web"), "runner": getattr(job, "runner", None)}


def _iso(t: Optional[datetime]) -> Optional[str]:
    t = aware(t)
    return None if t is None or t == _EPOCH else t.isoformat()


def _clock(t: Optional[datetime]) -> str:
    t = aware(t)
    return t.astimezone().strftime("%a %H:%M") if t else "?"


def _duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return ""
    minutes = max(1, int(round(seconds / 60.0)))
    if minutes < 90:
        return "%d min" % minutes
    hours = minutes / 60.0
    return "%.0f h" % hours if hours < 48 else "%.0f days" % (hours / 24.0)


# ---------------------------------------------------------------------------
# the record and the notices (REQ-JS-32, 33)
# ---------------------------------------------------------------------------
def record(db: Any, project_id: str, kind: str, *, job_id: Optional[str] = None,
           actor_id: Optional[str] = None, **detail: Any) -> None:
    """One `job_events` row: who did what to which job, when. Never fails the action."""
    try:
        db.job_events.add(JobEvent(id="jev" + uuid.uuid4().hex[:12], job_id=job_id,
                                   project_id=project_id, kind=kind, actor_id=actor_id,
                                   at=next_place(),
                                   detail={k: v for k, v in detail.items() if v is not None}))
    except Exception as exc:                            # noqa: BLE001 - the record, not the job
        _log.warning("job event %s of %s not recorded: %s", kind, job_id or project_id, exc)


def admins_of(db: Any, project_id: str) -> List[str]:
    """The project's active admins -- super admins too: `setup` makes them admins of every project."""
    try:
        return [m.user_id for m in db.members.list_members(project_id)
                if getattr(m, "role", None) == "admin" and getattr(m, "status", None) == "active"]
    except Exception:                                   # noqa: BLE001
        return []


def tell(db: Any, job: Any, kind: str, message: str, *, submitter: bool = True,
         skip: Optional[str] = None) -> None:
    """A notice to the job's submitter and the project's admins (REQ-JS-32). Never fails."""
    try:
        from .review_workflow import notify
        users = ([getattr(job, "started_by", None)] if submitter else []) + admins_of(
            db, job.project_id)
        notify(db, users, job.project_id, None, kind, message, skip=skip)
    except Exception as exc:                            # noqa: BLE001 - a notice, not the job
        _log.warning("job %s: notice %s not sent: %s", getattr(job, "id", "?"), kind, exc)


# ---------------------------------------------------------------------------
# how long things take -- for "about 3 h" (REQ-JS-30, 34)
# ---------------------------------------------------------------------------
def run_seconds(job: Any) -> Optional[float]:
    """How long an ended job ran: its start to its end, less the time it was paused."""
    s, e = aware(getattr(job, "started_at", None)), aware(getattr(job, "completed_at", None))
    if s is None or e is None or e < s:
        return None
    return max(0.0, (e - s).total_seconds() - float(getattr(job, "paused_seconds", 0) or 0))


def typical_seconds(db: Any, project_id: str, kind: str) -> Optional[float]:
    """The median run time of the project's last five completed jobs of `kind`."""
    try:
        done = [j for j in db.jobs.recent_ended(project_id, limit=60)
                if j.status == "complete" and kind_of(j) == kind]
    except Exception:                                   # noqa: BLE001 - no estimate then
        return None
    times = [t for t in (run_seconds(j) for j in done[:5]) if t]
    return statistics.median(times) if times else None


def remaining_seconds(db: Any, job: Any, at: datetime) -> Optional[float]:
    """What is left of a running job: its own estimate, else its kind's typical time less what it
    has run."""
    if getattr(job, "eta_seconds", None):
        return float(job.eta_seconds)
    typical = typical_seconds(db, job.project_id, kind_of(job))
    started = aware(getattr(job, "started_at", None))
    if typical is None or started is None:
        return None
    ran = (at - started).total_seconds() - float(getattr(job, "paused_seconds", 0) or 0)
    return max(60.0, typical - ran)


# ---------------------------------------------------------------------------
# a lane, as it stands
# ---------------------------------------------------------------------------
@dataclass
class Lane:
    """A project lane at one moment: the job holding it (running or paused), the waiting ones in
    their order, and whether the project's queue is held."""
    project_id: str
    name: str
    holding: List[Any] = field(default_factory=list)
    waiting: List[Any] = field(default_factory=list)
    held: bool = False

    def position(self, job_id: str) -> Optional[int]:
        for i, j in enumerate(self.waiting):
            if j.id == job_id:
                return i + 1
        return None


def lanes_of(db: Any, project_id: str) -> Dict[str, Lane]:
    jobs = db.jobs.lane_jobs(project_id, IN_LANE)
    held = any(j.status == "held" for j in jobs)
    out = {}
    for name in LANES:
        mine = [j for j in jobs if lane_of(j) == name]
        out[name] = Lane(project_id, name,
                         holding=[j for j in mine if j.status in HOLDING],
                         waiting=sorted((j for j in mine if j.status in WAITING), key=order_key),
                         held=held)
    return out


def estimated_start(db: Any, lane: Lane, job: Any, at: datetime) -> Optional[datetime]:
    """When `job` should start: what is left of the job holding its lane, plus the typical time of
    each job ahead of it. None when it cannot be told -- a paused job ahead, a held queue, or a
    kind never run before."""
    if lane.held:
        return None
    total = 0.0
    for h in lane.holding:
        if h.status == "paused":
            return None
        left = remaining_seconds(db, h, at)
        if left is None:
            return None
        total += left
    for w in lane.waiting:
        if w.id == job.id:
            return at + timedelta(seconds=total)
        typical = typical_seconds(db, w.project_id, kind_of(w))
        if typical is None:
            return None
        total += typical
    return None


# ---------------------------------------------------------------------------
# messages -- in the fields the web app already shows (REQ-JS-35)
# ---------------------------------------------------------------------------
def version_writer(db: Any, job: Any, holding: Iterable[Any]) -> Optional[Any]:
    """The other job running or paused on `job`'s version, if any (REQ-JS-03)."""
    vid = getattr(job, "version_id", None)
    if not vid:
        return None
    return next((h for h in holding if h.id != job.id and h.version_id == vid), None)


def waiting_message(db: Any, lane: Lane, job: Any, *, at: Optional[datetime] = None,
                    running_generations: Optional[int] = None) -> tuple:
    """(`current_activity`, `activity_detail`) of a waiting job: where it is and why it waits."""
    at = at or now()
    if job.status == "held":
        return ("Held after a restart",
                "A super admin starts the held jobs, or clears them.")
    pos = lane.position(job.id) or 1
    ahead = lane.waiting[:pos - 1]
    when = estimated_start(db, lane, job, at)
    about = " — about %s" % _duration((when - at).total_seconds()) if when and when > at else ""
    if pos > 1:
        return ("Waiting as #%d%s" % (pos, about),
                "After: " + "; ".join(describe(j) for j in ahead[:3])
                + ("…" if len(ahead) > 3 else ""))
    if lane.holding:
        h = lane.holding[0]
        if h.status == "paused":
            return ("Waiting as #1", "After %s, paused since %s" % (describe(h), _clock(h.paused_at)))
        return ("Waiting as #1%s" % about,
                "After %s, running since %s" % (describe(h), _clock(h.started_at)))
    try:
        all_holding = db.jobs.in_status(HOLDING)
    except Exception:                                   # noqa: BLE001
        all_holding = []
    writer = version_writer(db, job, all_holding)
    tag = getattr(job, "version_tag", None) or job.version_id
    if writer is not None:
        what = describe(writer)
        return ("Waiting for %s" % tag,
                "%s is %s it" % (what[:1].upper() + what[1:],
                                 "writing" if writer.status == "running" else "paused on"))
    if getattr(job, "version_id", None):
        # A process with no job here holding the version's writer lock: what the scheduler waits
        # for too (`job_scheduler._claims`).
        from .pipeline_runner import version_writer_busy
        who = version_writer_busy(db, job.version_id)
        if who:
            return ("Waiting for %s" % tag, "%s is writing it" % who)
    if lane.name == GENERATION:
        cap = settings().get("maxGenerations", 2)
        n = running_generations
        if n is None:
            n = sum(1 for j in all_holding if lane_of(j) == GENERATION and j.status == "running")
        if n >= cap:
            return ("Waiting for a free server slot",
                    "%d of %d generations are running on this server" % (n, cap))
    return ("Starting…", "")


def refresh_messages(db: Any, project_id: str) -> None:
    """Say again, on each waiting job of the project, where it is and why it waits -- after anything
    that moves the queue. Writes only what changed. Never fails."""
    try:
        at = now()
        for lane in lanes_of(db, project_id).values():
            for job in lane.waiting:
                head, detail = waiting_message(db, lane, job, at=at)
                if (job.current_activity, job.activity_detail) != (head, detail):
                    job.current_activity, job.activity_detail = head, detail
                    db.jobs.update(job)
    except Exception as exc:                            # noqa: BLE001 - words, not the queue
        _log.warning("project %s: waiting messages not refreshed: %s", project_id, exc)


# ---------------------------------------------------------------------------
# submit (REQ-JS-04, 06-09, 18)
# ---------------------------------------------------------------------------
@dataclass
class Answer:
    """What a submit got: the job, and `status` -- running | queued | held, or joined |
    already_queued when an update already covers it -- with its place and a message (REQ-JS-35)."""
    job: Any
    status: str
    position: Optional[int] = None
    estimated_start: Optional[datetime] = None
    ahead: List[dict] = field(default_factory=list)
    message: str = ""

    def as_dict(self) -> dict:
        return {"status": self.status, "position": self.position,
                "estimated_start": _iso(self.estimated_start), "ahead": self.ahead,
                "message": self.message}


def limit_of(project: Any, lane: str) -> int:
    value = getattr(project, "%s_limit" % lane, None)
    return int(value) if value else DEFAULT_LIMITS[lane]


def _same_generation(a: Any, b: Any) -> bool:
    """Two generations that would make the same version: commit, mode, scope, baseline and
    settings (REQ-JS-08)."""
    keys = ("commit_sha", "mode", "scope", "reference_version_id", "layer_filter", "no_llm",
            "data_dict_id", "narrowed_parse")
    return all(getattr(a, k, None) == getattr(b, k, None) for k in keys)


def _lane_full(project: Any, lane: str, jobs: List[Any]) -> JobRefused:
    held = [j for j in jobs if j.status in HOLDING]
    waiting = sorted((j for j in jobs if j.status in WAITING), key=order_key)
    limit = limit_of(project, lane)
    names = "; ".join([describe(j) + " (%s)" % j.status for j in held + waiting][:5])
    return JobRefused(
        409, "LANE_FULL",
        "Refused: the %s queue of this project is full — %d of %d places are taken (%s). Try "
        "again when one ends, or remove a waiting job." % (lane, len(jobs), limit, names),
        lane=lane, limit=limit, running=[brief(j) for j in held],
        waiting=[brief(j) for j in waiting])


def answer_for(db: Any, job: Any, status: Optional[str] = None) -> Answer:
    """The answer for `job` as its lane stands now."""
    job = db.jobs.get(job.id) or job
    status = status or job.status
    at = now()
    if job.status in HOLDING:
        return Answer(job, status, message="Starts now" if job.status == "running" else "Paused")
    lane = lanes_of(db, job.project_id)[lane_of(job)]
    pos = lane.position(job.id)
    when = estimated_start(db, lane, job, at) if job.status == "queued" else None
    head, _detail = waiting_message(db, lane, job, at=at) if job.status in WAITING else ("", "")
    ahead = [brief(j) for j in lane.holding] + [brief(j) for j in lane.waiting[:(pos or 1) - 1]]
    if job.status == "held":
        message = "Held: the queue is held after a restart; a super admin starts it"
    elif head in ("", "Starting…"):
        message = "Starts now"
    else:
        message = head.replace("Waiting", "Waits", 1)     # "Waits as #2 — about 3 h"
    return Answer(job, status, position=pos, estimated_start=when, ahead=ahead, message=message)


def enqueue(db: Any, job: AnalysisJob, *, actor_id: Optional[str],
            request_key: Optional[str] = None, priority: str = "normal",
            covers: Optional[Callable[[List[Any]], Optional[tuple]]] = None) -> Answer:
    """Put `job` -- made by the caller, its version reserved for a generation -- into its lane.

    Under the project's lock (`jobs.add_to_lane`): a retried request answers its first job
    (REQ-JS-09); `covers(jobs)` may answer an existing job instead (`("joined", job)` for a running
    update that covers it, `("already_queued", job)` for a waiting one); a generation identical to
    a waiting one is refused (REQ-JS-08); a full lane refuses (REQ-JS-04, 06). Otherwise the job
    joins its lane, held while the project's queue is held (REQ-JS-18), and starts at once when it
    can. Raises JobRefused."""
    project = db.projects.get(job.project_id)
    if project is None:
        raise JobRefused(404, "NOT_FOUND", "Project %s not found." % job.project_id)
    if request_key:
        first = db.jobs.find_by_request_key(job.project_id, request_key)
        if first is not None:
            return answer_for(db, first)
    lane = lane_of(job)
    job.lane = lane
    job.priority = PRIORITY.get(priority, NORMAL) if lane == GENERATION else NORMAL
    job.submitted_at, job.started_at, job.completed_at = next_place(), None, None
    job.request_key, job.origin, job.forced = request_key or None, "web", False
    job.started_by = job.started_by or actor_id
    job.error_message = None

    def decide(jobs: List[Any]) -> Optional[tuple]:
        mine = [j for j in jobs if lane_of(j) == lane]
        if covers is not None:
            hit = covers(mine)
            if hit:
                return hit
        if lane == GENERATION:
            # Only what `jobs` holds: a read of the repository here would be a second
            # transaction inside this one.
            waiting = sorted((j for j in mine if j.status in WAITING), key=order_key)
            twin = next((j for j in waiting if _same_generation(j, job)), None)
            if twin is not None:
                raise JobRefused(
                    409, "DUPLICATE_JOB",
                    "Refused: the same generation is already waiting — %s, as #%d. Remove it "
                    "first to submit it again." % (describe(twin), waiting.index(twin) + 1),
                    job_id=twin.id, waiting=[brief(twin)])
        if len(mine) >= limit_of(project, lane):
            raise _lane_full(project, lane, mine)
        job.status = "held" if any(j.status == "held" for j in jobs) else "queued"
        job.current_activity, job.activity_detail = (
            ("Held after a restart", "A super admin starts the held jobs, or clears them.")
            if job.status == "held" else ("Waiting…", ""))
        return None

    hit = db.jobs.add_to_lane(job, decide)
    if hit:
        how, existing = hit
        return answer_for(db, existing, status=how)
    record(db, job.project_id, "submitted", job_id=job.id, actor_id=actor_id,
           lane=lane, what=describe(job), priority=PRIORITY_NAME[job.priority],
           status=job.status)
    started = False
    if job.status == "queued":
        try:
            started = _try_start(db, job)
        except Exception as exc:                        # noqa: BLE001 - the scheduler retries
            _log.warning("job %s: could not start at once: %s", job.id, exc)
    refresh_messages(db, job.project_id)
    if not started:
        kick()
    return answer_for(db, job)


def requeue(db: Any, job: Any, *, actor_id: Optional[str], phases: Optional[list] = None) -> Answer:
    """A job that ended without finishing -- a web generation that failed or was interrupted --
    submitted again to be resumed: the back of its lane, Normal priority, a new place
    (REQ-JS-20). The lane's limit counts it as a new job. Raises JobRefused."""
    project = db.projects.get(job.project_id)
    lane = lanes_of(db, job.project_id)[lane_of(job)]
    if len(lane.holding) + len(lane.waiting) >= limit_of(project, lane.name):
        raise _lane_full(project, lane.name, lane.holding + lane.waiting)
    status = "held" if lane.held else "queued"
    values = dict(error_message=None, completed_at=None, started_at=None,
                  submitted_at=next_place(),
                  priority=NORMAL, reason="resume", heartbeat_at=None, paused_at=None,
                  pause_requested_at=None, resume_requested_at=None, runner=None,
                  current_activity="Waiting…", activity_detail="")
    if phases is not None:
        values["phases"] = phases
    if not db.jobs.transition(job.id, ("failed", "interrupted", "cancelled"), status, **values):
        raise JobRefused(409, "RUN_ACTIVE", "Job %s changed meanwhile; look at it again, then "
                                            "resume." % job.id, job_id=job.id)
    fresh = db.jobs.get(job.id) or job
    record(db, job.project_id, "submitted", job_id=job.id, actor_id=actor_id, lane=lane.name,
           what=describe(fresh), status=status, again=True)
    started = False
    if status == "queued":
        try:
            started = _try_start(db, fresh)
        except Exception as exc:                        # noqa: BLE001 - the scheduler retries
            _log.warning("job %s: could not start at once: %s", job.id, exc)
    refresh_messages(db, job.project_id)
    if not started:
        kick()
    return answer_for(db, fresh)


# ---------------------------------------------------------------------------
# the alive signal (REQ-JS-20)
# ---------------------------------------------------------------------------
#: Seconds between two alive signals of a running job: silent `jobs.interruptedAfterMinutes`
#: (10) and it is interrupted.
HEARTBEAT_SECONDS = 60.0


class Heartbeat:
    """A running job's alive signal (`heartbeat_at`), every `HEARTBEAT_SECONDS` while this process
    works on it: an API thread preparing, running or following a job (`pipeline_runner`), and the
    `analyzer.py` process of a run -- the web's, or one from the command line. The first after an
    interval: the claim, or the command line's record, wrote one as the job started."""

    def __init__(self, db: Any, job_id: str):
        self.db, self.job_id = db, job_id
        self._stop = threading.Event()

    def start(self) -> "Heartbeat":
        threading.Thread(target=self._beat, daemon=True, name="beat-%s" % self.job_id).start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _beat(self) -> None:
        while not self._stop.wait(HEARTBEAT_SECONDS):
            try:
                self.db.jobs.transition(self.job_id, ("running",), "running", heartbeat_at=now())
            except Exception:                           # noqa: BLE001 - the next beat
                pass


# ---------------------------------------------------------------------------
# the command line (REQ-JS-27..29; JOB_SCHEDULING_DESIGN §11)
# ---------------------------------------------------------------------------
#: An `analyzer.py` command -> its job's (mode, reason): it reads as the web job of its kind.
CLI_MODES = {"generate": ("auto", None), "export": ("export", "export"),
             "resume": ("auto", "resume"), "reexport": ("reexport", "rebuild")}
#: A refusal's reason (`core.job_lanes.cli_refusal`) -> its code.
CLI_REFUSALS = {"busy": "LANE_BUSY", "waiting": "JOBS_WAITING", "cap": "SERVER_FULL"}


def cli_runner() -> str:
    """'cli <user>@<host> pid N' -- who runs a command-line job, and where."""
    import getpass
    import socket
    try:
        user = getpass.getuser()
    except Exception:                                   # noqa: BLE001 - no login name here
        user = "?"
    return ("cli %s@%s pid %d" % (user, socket.gethostname(), os.getpid()))[:120]


def _by_whom(job: Any) -> str:
    if getattr(job, "origin", "web") == "cli":
        return "from the command line, %s" % (getattr(job, "runner", None) or "?")
    return "in the web app"


def _cli_refused(project_id: str, lane: str, why: str, jobs: List[Any], cap: int,
                 running: int) -> JobRefused:
    head = {"busy": "Refused: the %s lane of project %s is taken." % (lane, project_id),
            "waiting": "Refused: jobs wait in the %s lane of project %s, and a run started now "
                       "would go before them." % (lane, project_id),
            "cap": "Refused: %d of %d generations run on this server (jobs.maxGenerations)."
                   % (running, cap)}[why]
    lines = ["%s: %s, %s %s" % (j.id, describe(j), j.status, _by_whom(j)) for j in jobs[:8]]
    if len(jobs) > 8:
        lines.append("and %d more" % (len(jobs) - 8))
    lines.append("Run it when they have ended — or now, past the queue: --ignore-queue (the "
                 "super admin's choice).")
    return JobRefused(409, CLI_REFUSALS[why], ended_message(head, *lines), lane=lane,
                      jobs=[brief(j) for j in jobs])


def record_cli_run(db: Any, command: str, *, project_id: str, version_id: Optional[str],
                   version_tag: Optional[str] = None, commit_sha: Optional[str] = None,
                   branch: Optional[str] = None, scope: Optional[dict] = None, full: bool = False,
                   ignore_queue: bool = False) -> AnalysisJob:
    """A command-line run of `command` -- generate, export, resume, reexport -- recorded as a
    running job of its lane (REQ-JS-29), once the checks allow it (REQ-JS-28): no job runs, is
    paused or waits in the project's lane, and, for a generation, the server runs fewer than
    `jobs.maxGenerations`. Checked and recorded in one transaction under the queue's lock.
    `ignore_queue`: no checks, and the job is `forced` -- it runs beside the lane's job.
    Raises JobRefused (409 LANE_BUSY | JOBS_WAITING | SERVER_FULL) naming the jobs in the way."""
    mode, reason = CLI_MODES[command]
    if command == "generate" and full:
        mode = "full"
    at = next_place()
    job = AnalysisJob(
        id="job" + uuid.uuid4().hex[:8], project_id=project_id, commit_sha=commit_sha or "",
        version_id=version_id, reference_version_id=None, status="running",
        pause_after_phase1=False, layer_filter=None,
        phase=1 if command in ("generate", "resume") else 3, phase_pct=0,
        current_activity="Running from the command line",
        activity_detail="analyzer.py %s on %s" % (command, cli_runner().split("@", 1)[-1]),
        elapsed_seconds=0, eta_seconds=None, phases=[], started_at=at, completed_at=None,
        error_message=None, branch=branch or "main", version_tag=version_tag, mode=mode,
        scope=scope, reason=reason, submitted_at=at, heartbeat_at=at, origin="cli",
        runner=cli_runner(), forced=bool(ignore_queue))
    job.lane = lane_of(job)
    cap = int(settings().get("maxGenerations", 2))
    counted = {}

    def decide(lane_jobs: List[Any], running: int):
        counted["running"] = running
        if ignore_queue:
            return None
        return cli_refusal(job.lane, lane_jobs, running, cap)

    verdict = db.jobs.record_run(job, decide)
    if verdict is not None:
        why, jobs = verdict
        if why == "no_project":
            raise JobRefused(404, "NO_PROJECT", ended_message(
                "Refused: there is no project %s in the database." % project_id,
                "Onboard it first: python analyzer.py onboard --project-id %s ..." % project_id))
        if why == "busy" and not jobs:              # a claim took the lane meanwhile
            jobs = db.jobs.lane_jobs(project_id, HOLDING)
            jobs = [j for j in jobs if lane_of(j) == job.lane]
        raise _cli_refused(project_id, job.lane, why, jobs, cap, counted.get("running", 0))
    record(db, project_id, "submitted", job_id=job.id, lane=job.lane, what=describe(job),
           origin="cli", runner=job.runner, forced=bool(ignore_queue) or None)
    record(db, project_id, "started", job_id=job.id, waited_seconds=0)
    tell(db, job, "job_started", "Started from the command line: %s (%s)." % (
        describe(job), job.runner), submitter=False)
    refresh_messages(db, project_id)
    return job


def end_cli_run(db: Any, job_id: str, outcome: str, message: Optional[str] = None) -> bool:
    """A command-line run's end, recorded by the run itself (JOB_SCHEDULING_DESIGN §11):
    complete | failed | cancelled (Ctrl+C). Its lane is free for the scheduler's next round.
    An `interrupted` job -- silent too long: the machine slept, say -- takes the outcome the run
    really had. False when it had ended otherwise."""
    words = {"complete": "Done", "failed": "Failed", "cancelled": "Cancelled"}
    if not db.jobs.transition(job_id, ("running", "interrupted"), outcome, completed_at=now(),
                              error_message=message, current_activity=words[outcome],
                              activity_detail=""):
        return False
    after_end(db, job_id)
    return True


# ---------------------------------------------------------------------------
# actions on a job (REQ-JS-11, 22-26)
# ---------------------------------------------------------------------------
def may_act(db: Any, user: Any, job: Any) -> bool:
    """Cancel or remove: the submitter their own, a project admin any of the project's, a super
    admin any (REQ-JS who-may-do-what)."""
    if getattr(user, "is_superuser", False):
        return True
    member = db.members.get_member(job.project_id, user.id)
    if member is not None and member.role == "admin" and member.status == "active":
        return True
    return bool(getattr(job, "started_by", None)) and job.started_by == user.id


def request_pause(db: Any, job: Any, actor_id: Optional[str]) -> Any:
    """Ask a running web generation to stop at its next safe point (REQ-JS-22). A second ask
    changes nothing."""
    if lane_of(job) != GENERATION:
        raise JobRefused(409, "NOT_PAUSABLE",
                         "Refused: a Word-file update is not paused — it takes minutes; cancel "
                         "it instead.")
    if getattr(job, "origin", "web") == "cli":
        raise JobRefused(409, "CLI_RUN", cli_run_message(job))
    if job.status in WAITING:
        raise JobRefused(409, "NOT_PAUSABLE",
                         "Refused: a waiting job is not paused — remove it instead.")
    if job.status != "running":
        raise JobRefused(409, "NOT_PAUSABLE", "Refused: the job is %s." % job.status)
    if getattr(job, "pause_requested_at", None):
        return job
    if db.jobs.transition(job.id, ("running",), "running", pause_requested_at=now(),
                          current_activity="Pausing at the next safe point…"):
        record(db, job.project_id, "pause_requested", job_id=job.id, actor_id=actor_id)
    return db.jobs.get(job.id) or job


def request_resume(db: Any, job: Any, actor_id: Optional[str]) -> Any:
    """Resume a paused job: it takes the next free server slot, before waiting generations
    (REQ-JS-24)."""
    if job.status != "paused":
        raise JobRefused(409, "NOT_PAUSED", "Refused: the job is %s, not paused." % job.status)
    if getattr(job, "resume_requested_at", None):
        return job
    if db.jobs.transition(job.id, ("paused",), "paused", resume_requested_at=now(),
                          current_activity="Resuming — waiting for a free server slot",
                          activity_detail=""):
        record(db, job.project_id, "resume_requested", job_id=job.id, actor_id=actor_id)
    started = False
    try:
        started = _try_start(db, db.jobs.get(job.id) or job)
    except Exception as exc:                            # noqa: BLE001 - the scheduler retries
        _log.warning("job %s: could not resume at once: %s", job.id, exc)
    if not started:
        kick()
    return db.jobs.get(job.id) or job


def cli_run_message(job: Any) -> str:
    runner = getattr(job, "runner", None) or "the command line"
    return ("Refused: this run was started from the command line (%s); stop it there." % runner)


def set_priority(db: Any, job: Any, priority: str, actor_id: Optional[str]) -> Any:
    """A waiting generation's priority (REQ-JS-11). Super admin only -- the route checks."""
    if priority not in PRIORITY:
        raise JobRefused(422, "INVALID_PRIORITY", "Priority is high, normal or low.")
    if lane_of(job) != GENERATION or job.status not in WAITING:
        raise JobRefused(409, "NOT_WAITING",
                         "Refused: only a waiting generation has a priority to change.")
    before = PRIORITY_NAME.get(job.priority, "normal")
    if db.jobs.transition(job.id, WAITING, job.status, priority=PRIORITY[priority]):
        record(db, job.project_id, "priority_changed", job_id=job.id, actor_id=actor_id,
               before=before, after=priority)
    refresh_messages(db, job.project_id)
    kick()
    return db.jobs.get(job.id) or job


def set_limits(db: Any, project: Any, actor_id: Optional[str], *,
               generation_limit: Optional[int] = None, update_limit: Optional[int] = None) -> Any:
    """A project's two limits (REQ-JS-04): lowering one removes nothing already accepted."""
    lo, hi = LIMIT_RANGE
    before = {GENERATION: limit_of(project, GENERATION), UPDATE: limit_of(project, UPDATE)}
    for name, value in ((GENERATION, generation_limit), (UPDATE, update_limit)):
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
            raise JobRefused(422, "INVALID_LIMIT",
                             "The %s limit is a whole number from %d to %d." % (name, lo, hi))
        setattr(project, "%s_limit" % name, value)
    project.updated_at = now()
    db.projects.update(project)
    record(db, project.id, "limits_changed", actor_id=actor_id, before=before,
           after={GENERATION: limit_of(project, GENERATION), UPDATE: limit_of(project, UPDATE)})
    return project


# ---------------------------------------------------------------------------
# held queues -- a restart (REQ-JS-18)
# ---------------------------------------------------------------------------
def hold_waiting(db: Any) -> Dict[str, int]:
    """At start-up: every waiting job is held until a super admin starts or clears it -- unless
    `jobs.startQueuedAfterRestart`. Returns {project_id: how many}."""
    held: Dict[str, int] = {}
    for job in db.jobs.in_status(("queued",)):
        if db.jobs.transition(job.id, ("queued",), "held",
                              current_activity="Held after a restart",
                              activity_detail="A super admin starts the held jobs, or clears them."):
            held[job.project_id] = held.get(job.project_id, 0) + 1
            record(db, job.project_id, "held", job_id=job.id, reason="restart")
    for project_id, n in held.items():
        try:
            from .review_workflow import notify
            notify(db, admins_of(db, project_id), project_id, None, "jobs_held",
                   "%d job(s) of this project are held after a server restart: a super admin "
                   "starts them, or clears them." % n)
        except Exception as exc:                        # noqa: BLE001 - a notice
            _log.warning("held-jobs notice for %s not sent: %s", project_id, exc)
    return held


def release_held(db: Any, actor_id: Optional[str], *, project_id: Optional[str] = None,
                 remove: Any = ()) -> dict:
    """Start all, clear all, or clear some and start the rest -- of one project or of all
    (REQ-JS-18). `remove`: job ids, or "all". The rest go back to waiting with their places, so in
    their order."""
    held = [j for j in db.jobs.in_status(("held",))
            if project_id is None or j.project_id == project_id]
    clear_all = remove == "all"
    wanted = set() if clear_all else set(remove or ())
    unknown = sorted(wanted - {j.id for j in held})
    if unknown:
        raise JobRefused(422, "NOT_HELD", "Not held jobs%s: %s." % (
            " of this project" if project_id else "", ", ".join(unknown)))
    removed, released = [], []
    for job in held:
        if clear_all or job.id in wanted:
            if _remove(db, job, actor_id, why="Removed from the held queue."):
                removed.append(job.id)
        elif db.jobs.transition(job.id, ("held",), "queued", current_activity="Waiting…",
                                activity_detail=""):
            released.append(job.id)
            record(db, job.project_id, "released", job_id=job.id, actor_id=actor_id)
    for pid in {j.project_id for j in held}:
        refresh_messages(db, pid)
    kick()
    return {"removed": removed, "released": released}


# ---------------------------------------------------------------------------
# remove, cancel, interrupt (REQ-JS-20, 24-26)
# ---------------------------------------------------------------------------
def _remove(db: Any, job: Any, actor_id: Optional[str], *, why: str) -> bool:
    """A waiting job leaves its lane; a generation's reserved version goes, its name freed."""
    if not db.jobs.transition(job.id, WAITING, "removed", completed_at=now(),
                              error_message=why, current_activity="Removed",
                              activity_detail=""):
        return False
    record(db, job.project_id, "removed", job_id=job.id, actor_id=actor_id)
    if kind_of(job) == "generation" and getattr(job, "reason", None) != "resume":
        from .pipeline_runner import _release_draft_version
        _release_draft_version(db, job)
    return True


def ended_message(headline: str, *reasons: str) -> str:
    """`error_message` as the web app reads it: a headline, then `- ` lines (lib/failure.ts)."""
    return "\n".join([headline] + ["- " + r for r in reasons if r])[:4000]


def after_end(db: Any, job_id: str) -> None:
    """Once a job has ended, however it ended: its record, its notices, the next job. Called by
    the job's thread as it finishes and by whatever ended it from outside; idempotent per end."""
    job = db.jobs.get(job_id)
    if job is None or job.status not in ENDED:
        return
    kind = {"complete": "completed"}.get(job.status, job.status)
    try:
        seen = any(e.kind == kind for e in db.job_events.list_for_job(job_id))
    except Exception:                                   # noqa: BLE001
        seen = False
    if not seen:
        record(db, job.project_id, kind, job_id=job.id, what=describe(job),
               ran_seconds=run_seconds(job))
        if job.status != "removed":
            first = (job.error_message or "").split("\n", 1)[0]
            text = {"complete": "Finished: %s." % describe(job),
                    "failed": "Failed: %s. %s" % (describe(job), first),
                    "interrupted": "Interrupted: %s. %s" % (describe(job), first),
                    "cancelled": "Cancelled: %s. %s" % (describe(job), first)}.get(job.status, "")
            # An update's starter is told by `word_files.tell_update_end`, in its own words.
            tell(db, job, "job_%s" % kind, text.strip(), submitter=lane_of(job) != UPDATE)
    refresh_messages(db, job.project_id)
    kick()


def _keeps_its_version(job: Any) -> bool:
    """A job whose version is not its own to delete: an export, an update, a resume -- or a CLI
    run, whose version the developer manages."""
    return kind_of(job) != "generation" or getattr(job, "origin", "web") == "cli"


def interrupt(db: Any, job: Any, message: str) -> bool:
    """A running job that stopped answering (REQ-JS-20): its place freed, its version kept when it
    holds work to resume and deleted otherwise, as a run that died (`_fail_keeping_work`), the
    submitter and the admins told, the next job started. False when it had ended meanwhile."""
    if not db.jobs.transition(job.id, ("running",), "interrupted", completed_at=now(),
                              error_message=message, current_activity="Interrupted",
                              activity_detail=""):
        return False
    if not _keeps_its_version(job):
        from .pipeline_runner import _release_draft_version, _version_has_work
        if not _version_has_work(db, job.version_id):
            _release_draft_version(db, job)
    after_end(db, job.id)
    return True


def cancel_paused_too_long(db: Any, job: Any, days: float) -> bool:
    """Paused for `jobs.pausedDays` (REQ-JS-24): cancelled as any cancel -- a version that never
    finished is deleted, one with Word files keeps them (REQ-JS-25)."""
    if not db.jobs.transition(job.id, ("paused",), "cancelled", completed_at=now(),
                              current_activity="Cancelled", activity_detail="",
                              error_message=ended_message(
                                  "Cancelled: paused for %g days and not resumed." % days,
                                  "A server sets longer with jobs.pausedDays in "
                                  "config.local.json.")):
        return False
    if not _keeps_its_version(job):
        from .pipeline_runner import _release_draft_version
        _release_draft_version(db, job)
    after_end(db, job.id)
    return True


def cancel(db: Any, job: Any, actor: Any) -> Any:
    """Cancel a running or paused job, or remove a waiting one (REQ-JS-25, 26). A CLI run is the
    developer's to stop. Raises JobRefused; returns the job as it is now."""
    if getattr(job, "origin", "web") == "cli" and job.status in HOLDING:
        raise JobRefused(409, "CLI_RUN", cli_run_message(job))
    actor_id = getattr(actor, "id", None)
    if job.status in WAITING:
        if not _remove(db, job, actor_id, why=ended_message(
                "Removed before it started.", "Its place is free; submit it again to run it.")):
            raise _finished(db, job)
        refresh_messages(db, job.project_id)
        after_end(db, job.id)
        return db.jobs.get(job.id) or job
    by = getattr(actor, "name", None) or actor_id or "someone"
    if not db.jobs.transition(job.id, HOLDING, "cancelled", completed_at=now(),
                              current_activity="Cancelled", activity_detail="",
                              error_message=ended_message("Cancelled by %s." % by)):
        raise _finished(db, job)
    from . import pipeline_runner as pr
    from ..models.domain import RENDER_MODES
    if job.status == "paused":
        # No process to stop: its version goes now, as a run's thread does after a cancel.
        if not _keeps_its_version(job):
            pr._release_draft_version(db, job)
            pr._finish_if_it_finished(db, job)
    else:
        pr.cancel_subprocess(job.id)
        if not (pr.job_alive(job.id) or pr._reexport_alive(job.id)):
            # Nothing here follows it: its run is stopped here before anything else, or it would
            # go on writing into a version being removed.
            pr.stop_background_run(job)
            if getattr(job, "mode", None) not in RENDER_MODES and not _keeps_its_version(job):
                pr._release_draft_version(db, job)
                pr._finish_if_it_finished(db, job)
    record(db, job.project_id, "cancelled", job_id=job.id, actor_id=actor_id)
    after_end(db, job.id)
    return db.jobs.get(job.id) or job


def _finished(db: Any, job: Any) -> JobRefused:
    now_is = db.jobs.get(job.id)
    return JobRefused(409, "JOB_FINISHED", "Job %s has already ended (%s)." % (
        job.id, getattr(now_is, "status", "gone")))


def delete_refusal(db: Any, project_id: str, version: Any) -> Optional[JobRefused]:
    """Why a version may not be deleted now, by the jobs (design §16); None when they allow it.

    - A job of the project running or paused: it may build on the version -- named by its job, or
      picked by the engine, and recorded only at its end -- and deleting it would take the model
      and reuse rows the run reads (`RUN_ACTIVE`, as before the queue).
    - A waiting job that needs the version: its own (an update, an export, a generation's draft)
      or the baseline it was submitted with (`VERSION_NEEDED`). Other waiting jobs do not stop
      it: a baseline left to the engine is picked when the job starts, from what exists then.
    """
    name = getattr(version, "tag", None) or version.id
    holding = db.jobs.lane_jobs(project_id, HOLDING)
    if holding:
        return JobRefused(409, "RUN_ACTIVE", ended_message(
            "Version '%s' can't be deleted while a run of this project is at work or paused: "
            "it may build on it." % name,
            *("%s: %s, %s" % (j.id, describe(j), j.status) for j in holding),
            "Delete it once the run has ended or is cancelled."),
            jobs=[brief(j) for j in holding])
    needing = [j for j in db.jobs.lane_jobs(project_id, WAITING)
               if version.id in (j.version_id, getattr(j, "reference_version_id", None))]
    if needing:
        return JobRefused(409, "VERSION_NEEDED", ended_message(
            "Version '%s' can't be deleted: waiting jobs need it." % name,
            *("%s: %s%s" % (j.id, describe(j),
                            ", which builds on it" if j.version_id != version.id else "")
              for j in needing),
            "Remove them first, or delete it once they have run."),
            jobs=[brief(j) for j in needing])
    return None


# ---------------------------------------------------------------------------
# views -- the queues as the web app and the CLI read them (REQ-JS-30, 31, 34)
# ---------------------------------------------------------------------------
#: A job waiting longer than this, or running with no progress for longer than that, is flagged.
LONG_WAIT = timedelta(days=1)
STUCK = timedelta(minutes=30)


def flags(db: Any, job: Any, at: datetime) -> List[str]:
    """`long_wait` and `stuck` -- shown, never acted on (REQ-JS-34)."""
    out = []
    if job.status in WAITING and at - place_of(job) > LONG_WAIT:
        out.append("long_wait")
    if job.status == "running" and getattr(job, "version_id", None):
        try:
            from .pipeline_runner import _version_run_module
            vr = _version_run_module()
            eng = getattr(db, "_engine", None)
            row = vr.run_row(job.version_id, engine=eng) if (vr and eng is not None) else None
            last = aware((row or {}).get("progress_at")) or aware(job.started_at)
            if last is not None and at - last > STUCK:
                out.append("stuck")
        except Exception:                               # noqa: BLE001 - a flag, not a must
            pass
    return out


def job_queue_fields(db: Any, job: Any, lane: Optional[Lane] = None,
                     at: Optional[datetime] = None) -> dict:
    """The fields a job's view carries for the queue (design §13)."""
    at = at or now()
    out = {"lane": lane_of(job),
           "priority": PRIORITY_NAME.get(getattr(job, "priority", NORMAL), "normal"),
           "submitted_at": _iso(place_of(job)), "origin": getattr(job, "origin", "web"),
           "runner": getattr(job, "runner", None),
           "heartbeat_at": _iso(getattr(job, "heartbeat_at", None)),
           "pause_requested": bool(getattr(job, "pause_requested_at", None))
           and job.status == "running",
           "resume_requested": bool(getattr(job, "resume_requested_at", None)),
           "paused_at": _iso(getattr(job, "paused_at", None)),
           "position": None, "estimated_start": None, "flags": []}
    if job.status in WAITING:
        lane = lane or lanes_of(db, job.project_id)[lane_of(job)]
        out["position"] = lane.position(job.id)
        if job.status == "queued":
            out["estimated_start"] = _iso(estimated_start(db, lane, job, at))
    if job.status in IN_LANE:
        out["flags"] = flags(db, job, at)
    return out


def queues(db: Any, project_id: str) -> dict:
    """A project's two lanes: the job holding each, the waiting ones in order, the limits."""
    project = db.projects.get(project_id)
    at = now()
    lanes = lanes_of(db, project_id)
    s = settings()
    holding_all = db.jobs.in_status(HOLDING)
    out = {"project_id": project_id, "held": any(l.held for l in lanes.values()),
           "cap": {"max_generations": s.get("maxGenerations", 2),
                   "running_generations": sum(1 for j in holding_all if j.status == "running"
                                              and lane_of(j) == GENERATION)},
           "lanes": {}}
    for name, lane in lanes.items():
        out["lanes"][name] = {
            "limit": limit_of(project, name) if project else DEFAULT_LIMITS[name],
            "active": [dict(brief(j), current_activity=j.current_activity,
                            **job_queue_fields(db, j, lane, at)) for j in lane.holding],
            "waiting": [dict(brief(j), current_activity=j.current_activity,
                             activity_detail=j.activity_detail,
                             **job_queue_fields(db, j, lane, at)) for j in lane.waiting]}
    return out


def all_queues(db: Any) -> dict:
    """Every project with a job in a lane (REQ-JS-30, super admin)."""
    jobs = db.jobs.in_status(IN_LANE)
    s = settings()
    return {"cap": {"max_generations": s.get("maxGenerations", 2),
                    "running_generations": sum(1 for j in jobs if j.status == "running"
                                               and lane_of(j) == GENERATION)},
            "held": sum(1 for j in jobs if j.status == "held"),
            "projects": [queues(db, pid) for pid in sorted({j.project_id for j in jobs})]}


def preview(db: Any, project_id: str, lane: str) -> dict:
    """What a submit to `lane` would get now (REQ-JS-31): start | wait (position, estimate) |
    refuse (the jobs in the way) -- with its message."""
    if lane not in LANES:
        raise JobRefused(422, "INVALID_LANE", "The lane is generation or update.")
    project = db.projects.get(project_id)
    here = lanes_of(db, project_id)[lane]
    limit = limit_of(project, lane) if project else DEFAULT_LIMITS[lane]
    if len(here.holding) + len(here.waiting) >= limit:
        refused = _lane_full(project, lane, here.holding + here.waiting)
        return {"answer": "refuse", "code": refused.code, "message": refused.message,
                "running": refused.extra["running"], "waiting": refused.extra["waiting"]}
    if here.held:
        return {"answer": "wait", "position": len(here.waiting) + 1, "estimated_start": None,
                "message": "Held: the queue is held after a restart; a super admin starts it"}
    at = now()
    if not here.holding and not here.waiting:
        if lane == GENERATION:
            cap = settings().get("maxGenerations", 2)
            n = sum(1 for j in db.jobs.in_status(("running",)) if lane_of(j) == GENERATION)
            if n >= cap:
                return {"answer": "wait", "position": 1, "estimated_start": None,
                        "message": "Waits for a free server slot: %d of %d generations are "
                                   "running" % (n, cap)}
        return {"answer": "start", "position": None, "estimated_start": None,
                "message": "Starts now"}
    pos = len(here.waiting) + 1
    total: Optional[float] = 0.0
    for h in here.holding:
        left = None if h.status == "paused" else remaining_seconds(db, h, at)
        total = None if (total is None or left is None) else total + left
    for w in here.waiting:
        typical = typical_seconds(db, w.project_id, kind_of(w))
        total = None if (total is None or typical is None) else total + typical
    about = (" — about %s" % _duration(total)) if total else ""
    when = at + timedelta(seconds=total) if total else None
    return {"answer": "wait", "position": pos, "estimated_start": _iso(when),
            "message": "Waits as #%d%s" % (pos, about)}
