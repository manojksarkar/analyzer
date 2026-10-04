"""
Real analysis-job runner.

Replaces the mock's job_runner.py simulation with actual subprocess calls to
run.py. A daemon thread per job handles the full lifecycle:

  1. Clone / check out the project commit into workspaces/<project_id>/<sha16>/.
  2. Write a per-project config.json (base config + build_config overrides +
     architecture_layers → layers schema) and pass it via --config.
  3. Invoke run.py as a subprocess (shell=False, cwd=repo_root), capturing
     combined stdout+stderr so all phase-script output flows through.
  4. Tail subprocess output: detect phase transitions, update job record for SSE.
  5. On completion: register a real Version + Documents from output/ dirs.
  6. On failure: mark job failed with the tail of subprocess output.
  7. On cancel: terminate the subprocess immediately.

Public surface used by routes/jobs.py:
  start(db, job_id)            — kick off on a daemon thread
  cancel_subprocess(job_id)    — kill the running subprocess
  signal_resume(job_id)        — unblock a paused thread
  reexport(db, job_id)         — run Phase 4 only on a daemon thread
  get_log_lines(job_id, after) — (lines, new_cursor) for SSE streaming
"""
from __future__ import annotations

import copy
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Set

from ..models.domain import (Version, Document, AnalysisJob, AnalysisPhase, REEXPORT_MODE,
                             EXPORT_MODE, RENDER_MODES)
from . import git_cli
from . import doc_render
from .model_reader import ModelReader
from .settings import get_settings

UTC = timezone.utc

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-job state (thread-safe via _LOCK)
# ---------------------------------------------------------------------------
_LOCK = threading.Lock()
_job_logs: dict[str, deque] = {}        # recent log lines (ring buffer)
_job_log_totals: dict[str, int] = {}    # monotonic line count (for SSE cursor)
_job_procs: dict[str, subprocess.Popen] = {}
_job_resume_events: dict[str, threading.Event] = {}
_job_threads: dict[str, threading.Thread] = {}   # see job_alive
_LOG_MAX = 500

# Concurrency semaphore — lazily initialised from JOB_MAX_CONCURRENCY setting.
_SEMAPHORE: Optional[threading.BoundedSemaphore] = None
_SEM_LOCK = threading.Lock()


def _get_semaphore() -> threading.BoundedSemaphore:
    global _SEMAPHORE
    with _SEM_LOCK:
        if _SEMAPHORE is None:
            _SEMAPHORE = threading.BoundedSemaphore(get_settings().job_max_concurrency)
        return _SEMAPHORE


_PHASES = [(1, "Parse C++"), (2, "Derive Model"), (3, "Run Views"), (4, "Export DOCX")]
_ACTIVITY = {
    1: "Parsing C++ sources with libclang…",
    2: "Deriving model + enriching with LLM…",
    3: "Rendering views, diagrams and flowcharts…",
    4: "Exporting Software Detailed Design DOCX…",
}

# Phase name fragments that appear in PhaseRunner log lines
# e.g.: "INFO orchestration: [1/4] === Phase 1: Parse C++ source ==="
_PHASE_MARKERS = {
    1: "Phase 1:",
    2: "Phase 2:",
    3: "Phase 3:",
    4: "Phase 4:",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _elapsed_since(started_at: Optional[datetime], now: Optional[datetime] = None) -> int:
    """Whole seconds since `started_at`, whichever backend handed it back.

    `started_at` is written timezone-aware (`_now()` is UTC), and PostgreSQL returns it that way.
    SQLite stores no zone and returns it NAIVE, and aware-minus-naive raises TypeError -- which,
    raised from the per-line progress update, hung every job the API started on SQLite (see
    `_progress`). Naive is read as UTC, because UTC is what was written.
    """
    if started_at is None:
        return 0
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    return max(0, int(((now or _now()) - started_at).total_seconds()))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start(db: Any, job_id: str) -> None:
    """Kick off the real pipeline on a daemon thread (returns immediately)."""
    t = threading.Thread(target=_run, args=(db, job_id), daemon=True, name=f"job-{job_id}")
    with _LOCK:
        _job_threads[job_id] = t
    t.start()


def job_alive(job_id: str) -> bool:
    """Whether THIS process is running that job. A row left `running` by a server that stopped
    mid-run is not: no thread here will ever finish it, or clean up after it."""
    with _LOCK:
        t = _job_threads.get(job_id)
    return t is not None and t.is_alive()


def cancel_subprocess(job_id: str) -> None:
    """Stop the subprocess for the given job (if still alive), and what it started -- or the
    background run it follows (on a thread: stopping a process tree can take seconds)."""
    with _LOCK:
        proc = _job_procs.get(job_id)
        run = _job_runs.get(job_id)
    if proc is not None:
        _stop_tree(proc)
    fr = _frozen_run_module() if run is not None else None
    if fr is not None:
        threading.Thread(target=fr.stop, args=(run.get("pid"), run.get("create_time")),
                         daemon=True, name=f"stop-{job_id}").start()


def _stop_tree(proc: subprocess.Popen) -> None:
    """Stop a job's subprocess AND everything it started.

    `proc.terminate()` alone stops only the direct child. That child is `analyzer.py`, which runs
    each phase as its own `run.py` (through cmd.exe on Windows), so the phase carried on without
    its parent: still writing to the database, and blocked for ever on the output pipe once
    nobody read it. Descendants first, so none is re-parented and missed. psutil when present --
    a requirement, but optional at runtime as in engine/core/subprocess_util.py -- otherwise
    `taskkill /T` on Windows.
    """
    if proc.poll() is not None:
        return
    try:
        import psutil
    except ImportError:
        psutil = None
    if psutil is not None:
        try:
            family = psutil.Process(proc.pid).children(recursive=True)
        except psutil.Error:
            family = []
        for p in family:
            try:
                p.terminate()
            except psutil.Error:
                pass
    elif os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True, shell=True)
    try:
        proc.terminate()
    except OSError:
        pass


def signal_resume(job_id: str) -> None:
    """Unblock a thread that is holding at the pause point."""
    with _LOCK:
        ev = _job_resume_events.get(job_id)
    if ev is not None:
        ev.set()


class ReexportRefused(Exception):
    """Why a re-export cannot start now. `status` and `code` are the HTTP answer; `job_id` names
    the job that is in the way, so a client can follow it instead of starting another."""

    def __init__(self, status: int, code: str, message: str, job_id: Optional[str] = None):
        super().__init__(message)
        self.status, self.code, self.job_id = status, code, job_id


_REEXPORT_ACTIVE = ("queued", "running")
_REEXPORT_LOCK = threading.Lock()          # guard + create, so two requests cannot both pass
_reexport_threads: dict[str, threading.Thread] = {}


def _reexport_alive(job_id: str) -> bool:
    """Whether THIS process is still running that re-export. A row left `running` by a server
    that stopped mid-run is not: nothing will ever finish it."""
    t = _reexport_threads.get(job_id)
    return t is not None and t.is_alive()


def start_reexport(db: Any, version: Any) -> AnalysisJob:
    """Re-export `version` as a job of its own, and return that job.

    A re-export used to reuse the version's GENERATION job and never change its status, which
    stayed `complete`: polling it, or its live stream, said "finished" before anything ran, and
    a failure was not recorded at all. Nothing stopped a second one starting on the same folder.
    And it was addressed by job id, which a client could find only for the project's newest job.

    Now it has its own row -- `mode: "reexport"`, phases 3 and 4 -- whose status goes
    queued -> running -> complete | failed like any job's, so `GET /jobs/{id}` and
    `GET /jobs/{id}/events` follow it unchanged. It is addressed by VERSION, so any version with
    a finished generation can be re-exported. One at a time per version: a second request while
    one runs is refused with the running job's id.

    Raises ReexportRefused. The version must belong to the project; the caller checks that.
    """
    with _REEXPORT_LOCK:
        jobs = db.jobs.list_for_version(version.id)
        generation = next((j for j in jobs if getattr(j, "mode", None) not in RENDER_MODES), None)
        if generation is None:
            raise ReexportRefused(
                409, "NO_GENERATION_JOB",
                f"Version '{version.id}' was not generated through the web app, so there is no "
                f"run to repeat its export from. Re-export it with `python analyzer.py reexport "
                f"--project-id {version.project_id} --version-id {version.id}`.")
        if generation.status != "complete":
            raise ReexportRefused(
                409, "VERSION_NOT_READY",
                f"Version '{version.id}' has no finished generation to re-export: its job "
                f"{generation.id} is '{generation.status}'.", generation.id)
        busy = version_writer_busy(db, version.id)
        if busy:
            raise ReexportRefused(
                409, "VERSION_BUSY",
                f"Version '{version.id}' is being written by {busy}. Wait for it to finish, "
                f"then re-export.")
        # An export renders the version too: whichever of the two took the lock second would
        # fail on it, so one waits for the other here.
        running = next((j for j in jobs if getattr(j, "mode", None) in RENDER_MODES
                        and j.status in _REEXPORT_ACTIVE), None)
        if running is not None:
            if _reexport_alive(running.id):
                raise ReexportRefused(
                    409, "REEXPORT_RUNNING",
                    f"Version '{version.id}' is already being re-exported by job {running.id}. "
                    f"Follow that job rather than starting another on the same folder.",
                    running.id)
            _mark_failed(db, running.id, "Interrupted: the API server stopped while this "
                                         "re-export was running. Start it again.")
        job = AnalysisJob(
            id=f"job{uuid.uuid4().hex[:8]}", project_id=version.project_id,
            commit_sha=generation.commit_sha, version_id=version.id,
            reference_version_id=None, status="queued", pause_after_phase1=False,
            layer_filter=generation.layer_filter, phase=3, phase_pct=0,
            current_activity="Queued — waiting for worker…", activity_detail="",
            elapsed_seconds=0, eta_seconds=None,
            phases=[AnalysisPhase(3, "Run Views", "pending", None),
                    AnalysisPhase(4, "Export DOCX", "pending", None)],
            started_at=_now(), completed_at=None, error_message=None,
            branch=generation.branch, version_tag=generation.version_tag,
            # How the version was generated is how it is re-rendered: same LLM switch, same
            # data dictionary, same document title -- and every document it HAS, which since
            # `export` can be more than its generation's scope (`_reexport_scope`).
            mode=REEXPORT_MODE, scope=_reexport_scope(db, version, generation.scope),
            no_llm=generation.no_llm,
            data_dict_id=generation.data_dict_id, narrowed_parse=generation.narrowed_parse)
        db.jobs.create(job)
        t = threading.Thread(target=_run_reexport, args=(db, job.id), daemon=True,
                             name=f"reexport-{job.id}")
        _reexport_threads[job.id] = t
        t.start()
    return job


def get_log_lines(job_id: str, after_idx: int) -> tuple[list[str], int]:
    """Return (new_lines, updated_cursor) for SSE streaming. Thread-safe."""
    with _LOCK:
        buf = _job_logs.get(job_id)
        total = _job_log_totals.get(job_id, 0)
    if buf is None:
        return [], after_idx
    lines = list(buf)
    buf_start = max(0, total - len(lines))
    start = max(0, after_idx - buf_start)
    return lines[start:], total


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _append_log(job_id: str, line: str) -> None:
    with _LOCK:
        buf = _job_logs.get(job_id)
        if buf is None:
            return
        buf.append(line)
        _job_log_totals[job_id] = _job_log_totals.get(job_id, 0) + 1


def _init_state(job_id: str) -> None:
    with _LOCK:
        _job_logs[job_id] = deque(maxlen=_LOG_MAX)
        _job_log_totals[job_id] = 0
        _job_resume_events[job_id] = threading.Event()


def _cleanup_state(job_id: str) -> None:
    with _LOCK:
        _job_procs.pop(job_id, None)
        _job_resume_events.pop(job_id, None)
        _progress_warned.difference_update({k for k in _progress_warned if k[0] == job_id})
        _step_clocks.pop(job_id, None)
        # Only this thread's own entry: a job reopened by `start_resume` has a new thread, which
        # the old one ending must not unregister (the job would look unfollowed).
        if _job_threads.get(job_id) is threading.current_thread():
            _job_threads.pop(job_id, None)
        # Keep logs so SSE can drain remaining lines after completion


def _reserve_version(db: Any, job: Any, project: Any) -> None:
    """Create the version row (status 'draft') for a job. Called at **job creation** (jobs route,
    before the job INSERT — ``analysis_jobs.version_id`` is a FK to ``versions.id``) and again at
    run start as an **idempotent safety net** (so the engine — writing to Postgres via PgStore —
    can insert its per-version rows under the ``versions`` FK *during* the run, PG-3/08).
    ``_make_version`` finalizes it at completion; ``_mark_failed`` deletes it on failure so the
    name is free to retry. No-op if there's no reserved id or the row already exists."""
    vid = getattr(job, "version_id", None)
    if not vid or db.versions.get(vid):
        return
    db.versions.create(Version(
        id=vid, project_id=job.project_id,
        tag=(getattr(job, "version_tag", None) or "").strip(),
        commit_sha=job.commit_sha, branch=job.branch,
        description="Generating…", status="draft", docs_count=0,
        created_by=(project.created_by if project else "system"), created_at=_now()))


def _materialise_data_dictionary(db: Any, job: Any) -> Optional[Path]:
    """Put the uploaded data dictionary where the engine expects it, and persist it.

    The engine resolves it as `workspaces/<pid>/datadict/<id>.csv` — and nothing ever created
    that file. `POST /uploads` kept the bytes in a module-level `_UPLOADS` dict and returned an
    id; the wizard stored the id in `build_config`; the runner then checked for a file that was
    never written, found nothing, and silently omitted `--data-dictionary`. The CSV therefore
    never reached the parser, never merged into `dataDictionary`, and never appeared in the
    database. No error at any step.

    Two destinations, because they answer different questions:
      * the FILE is what `parser.py` reads (it takes a path);
      * `data_dictionaries` + `data_dictionary_entries` make it survive an API restart and be
        visible from another node — the in-memory dict does neither.

    Returns the path, or None when the job has no dictionary or the content cannot be found.
    """
    ddid = getattr(job, "data_dict_id", None)
    if not ddid:
        return None
    dd_path = (get_settings().repo_root / "workspaces" / job.project_id
               / "datadict" / f"{ddid}.csv")
    if dd_path.is_file():
        return dd_path                       # already materialised by an earlier run

    data = _upload_bytes(ddid) or _stored_dictionary_bytes(db, job.project_id, ddid)
    if not data:
        _append_log(job.id, f"WARNING: data dictionary {ddid} has no content on this node — "
                            f"the run will proceed WITHOUT it")
        return None

    try:
        dd_path.parent.mkdir(parents=True, exist_ok=True)
        dd_path.write_bytes(data)
    except OSError as exc:
        _append_log(job.id, f"WARNING: could not write the data dictionary: {exc}")
        return None
    _persist_dictionary(db, job.project_id, ddid, data)
    _append_log(job.id, f"Data dictionary {ddid} ready ({len(data)} bytes).")
    return dd_path


def _upload_bytes(upload_id: str) -> Optional[bytes]:
    """The uploaded bytes, read from where the upload route stores them.

    Uploads live on disk (`routes/repositories.py`, `_upload_dir`); `_UPLOADS` holds only their
    metadata. This used to read a `data` key that is never set, so every data dictionary was
    reported to have "no content on this node" and the run went on without it.
    """
    try:
        from ..routes.repositories import resolve_upload
        path = resolve_upload(upload_id)
        return path.read_bytes() if path is not None else None
    except Exception:
        return None


def _stored_dictionary_bytes(db: Any, project_id: str, ddid: str) -> Optional[bytes]:
    """Rebuild the CSV from `data_dictionary_entries` — the copy that survives a restart."""
    try:
        import sqlalchemy as sa
        from ..db.postgres import schema as s
        eng = getattr(db, "_engine", None)
        if eng is None:
            return None
        with eng.connect() as cx:
            rows = cx.execute(
                sa.select(s.data_dictionary_entries.c.payload)
                .where(s.data_dictionary_entries.c.data_dictionary_id == ddid)
                .order_by(s.data_dictionary_entries.c.id)).all()
        if not rows:
            return None
        lines = [r[0].get("_raw", "") for r in rows if isinstance(r[0], dict)]
        if not any(lines):
            return None
        return ("\n".join(lines) + "\n").encode("utf-8")
    except Exception:
        return None


def _persist_dictionary(db: Any, project_id: str, ddid: str, data: bytes) -> None:
    """Store the CSV so a restart or another node can still find it. Best-effort."""
    try:
        import sqlalchemy as sa
        from ..db.postgres import schema as s
        eng = getattr(db, "_engine", None)
        if eng is None:
            return
        text = data.decode("utf-8", errors="replace")
        rows = [{"data_dictionary_id": ddid, "payload": {"_raw": ln}}
                for ln in text.splitlines()]
        with eng.begin() as cx:
            if not cx.execute(sa.select(s.data_dictionaries.c.id)
                              .where(s.data_dictionaries.c.id == ddid)).first():
                cx.execute(sa.insert(s.data_dictionaries), {
                    "id": ddid, "project_id": project_id, "name": f"{ddid}.csv",
                    "uploaded_at": _now()})
            cx.execute(sa.delete(s.data_dictionary_entries)
                       .where(s.data_dictionary_entries.c.data_dictionary_id == ddid))
            if rows:
                cx.execute(sa.insert(s.data_dictionary_entries), rows)
    except Exception as exc:
        _log.warning("could not persist the data dictionary %s: %s", ddid, exc)


def _store_resolved_config(db: Any, job: Any, cfg: dict) -> None:
    """Persist the per-version NON-SECRET analysis config onto the reserved version row
    (versions.resolved_config). Best-effort: a storage hiccup must not fail the run — the
    config is also materialized to the workspace file the engine actually reads."""
    vid = getattr(job, "version_id", None)
    if not vid:
        return
    try:
        v = db.versions.get(vid)
        if v is not None:
            v.resolved_config = cfg
            db.versions.update(v)
    except Exception as exc:                         # best-effort: don't fail the run on this
        # But say so. This column is the record of what settings a version was built with, and
        # losing it without a trace makes a later "why does this version look like that?"
        # unanswerable — the workspace config.json is per PROJECT and shared, so it has already
        # moved on by the time anyone asks.
        _append_log(getattr(job, "id", ""), f"WARNING: could not store resolved_config: {exc}")


def _mark_failed(db: Any, job_id: str, message: str) -> None:
    # Also to the server log (doc 09, A0). The job record alone is not enough: it is
    # only visible to someone who thinks to query that job, it is lost if the DB write
    # itself is what failed, and an operator tailing the API sees nothing at all.
    _log.error("job %s failed: %s", job_id, message)
    job = db.jobs.get(job_id)
    if job and job.status not in ("cancelled", "complete", "failed"):
        job.status = "failed"
        job.error_message = message[:4000]
        job.completed_at = _now()
        db.jobs.update(job)
        # drop the reserved (still-draft) version so its name is free for a retry
        _release_draft_version(db, job)


def _release_draft_version(db: Any, job: Any) -> None:
    """Delete the draft version a job reserved and did not finish, so its name is free again.

    `analysis_jobs.version_id` is a foreign key to `versions.id` with no ON DELETE, so PostgreSQL
    refused to delete the version while its own job still pointed at it -- and the refusal was
    swallowed as best-effort cleanup. Every failed or cancelled run left an empty draft behind as
    the project's newest version: the Subbar showed it by default instead of the last good one,
    the Versions page listed it, and its name could not be used for the retry. The job is
    detached first; its `version_tag` still names what it was generating. The engine's
    per-version rows go with the version (ON DELETE CASCADE).
    """
    vid = getattr(job, "version_id", None)
    if not vid:
        return
    v = db.versions.get(vid)
    if v is None or getattr(v, "status", None) != "draft":
        return
    try:
        if delete_version(db, vid, only_draft=True):
            job.version_id = None
    except Exception as exc:                                  # noqa: BLE001 - logged, not fatal
        _log.warning("job %s: could not delete its unfinished draft version %s: %s: %s",
                     job.id, vid, type(exc).__name__, exc)


def delete_version(db: Any, version_id: str, *, only_draft: bool = False) -> bool:
    """Delete a version, and first what points at it without ON DELETE CASCADE -- its jobs'
    `version_id` (the jobs stay, naming no version) and cached comparisons -- in ONE transaction.
    In two, a reader between them saw the job detached while the version was still there (the web
    app took a cancelled run's draft for gone, and showed it again); and a job created between
    them made the delete fail on its foreign key. `only_draft`: only while it is still a draft.
    True when it was deleted."""
    eng = getattr(db, "_engine", None)
    if eng is None:                       # the in-memory backend: one process, no transactions
        v = db.versions.get(version_id)
        if v is None or (only_draft and getattr(v, "status", None) != "draft"):
            return False
        for j in db.jobs.list_for_version(version_id):
            j.version_id = None
            db.jobs.update(j)
        db.versions.delete(version_id)
        return True
    import sqlalchemy as sa
    from ..db.postgres import schema as s
    cond = s.versions.c.id == version_id
    if only_draft:
        cond = cond & (s.versions.c.status == "draft")
    with eng.begin() as cx:
        if cx.execute(sa.select(s.versions.c.id).where(cond).with_for_update()).first() is None:
            return False
        cx.execute(sa.update(s.analysis_jobs).where(s.analysis_jobs.c.version_id == version_id)
                   .values(version_id=None))
        cx.execute(sa.delete(s.compare_results).where(sa.or_(
            s.compare_results.c.current_version_id == version_id,
            s.compare_results.c.baseline_version_id == version_id)))
        cx.execute(sa.delete(s.versions).where(cond))
    return True


#: What a job a stopped server left behind says, on the job and in the Overview's banner.
INTERRUPTED_MESSAGE = ("Interrupted: the API server stopped while this ran, so it never "
                       "finished. Start it again.")

#: The advisory lock an API process holds while it runs jobs (`claim_job_runner`): the two-key
#: form, whose key space is not the one-key form's that a review save locks a version with.
_RUNNER_LOCK = (0x41524658, 1)          # "ARFX"
_runner_conn = None                     # the connection holding it, open for the process's life


def runner_still_held(engine: Any) -> bool:
    """Whether this process still holds the job-runner lock (`claim_job_runner`). A database
    restart or a dropped idle connection frees it in silence; then another server may sweep, and
    two sweeping at once would follow (and fail) each other's jobs. A lost claim is dropped, not
    taken again: the server that holds it now does the sweeping. True on a database without
    advisory locks (one process by construction)."""
    global _runner_conn
    if getattr(getattr(engine, "dialect", None), "name", "") != "postgresql":
        return True
    if _runner_conn is None:
        return False
    from sqlalchemy import text
    try:
        held = _runner_conn.execute(text(
            "SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND granted "
            "AND classid::bigint = :a AND objid::bigint = :b AND pid = pg_backend_pid()"),
            {"a": _RUNNER_LOCK[0], "b": _RUNNER_LOCK[1]}).first() is not None
        _runner_conn.commit()
    except Exception:                                    # noqa: BLE001 - the session is gone
        held = False
    if not held:
        try:
            _runner_conn.invalidate()
            _runner_conn.close()
        except Exception:                                # noqa: BLE001
            pass
        _runner_conn = None
    return held


def claim_job_runner(engine: Any) -> bool:
    """Whether this process is the only API server running jobs on its database.

    Takes the session-level advisory lock `_RUNNER_LOCK` on a connection kept open for the life
    of the process; PostgreSQL releases it when the process ends, however it ends. True when no
    other server holds it -- then every job the database calls active was left by a server that
    stopped (`fail_interrupted_jobs`). False when another server runs on this database: its jobs
    are alive there, and failing them would delete the draft versions it is still generating.
    That is why `web-app/PLAN.md` once ruled a stale-job sweep out. A database without advisory
    locks (SQLite: local runs and tests) serves one process by construction.
    """
    global _runner_conn
    if _runner_conn is not None:
        return True
    if getattr(getattr(engine, "dialect", None), "name", "") != "postgresql":
        return True
    from sqlalchemy import text
    conn = engine.connect()
    try:
        got = bool(conn.execute(text("SELECT pg_try_advisory_lock(:a, :b)"),
                                {"a": _RUNNER_LOCK[0], "b": _RUNNER_LOCK[1]}).scalar())
        conn.commit()                   # a session lock outlives the transaction
    except Exception:
        conn.close()
        raise
    if not got:
        conn.close()
        return False
    _runner_conn = conn
    return True


#: When this process started: a job that started before it cannot be one of its own.
PROCESS_STARTED = datetime.now(UTC)


def fail_interrupted_jobs(db: Any, *, before: Optional[datetime] = None,
                          reattach_only: bool = False) -> int:
    """At start-up: fail every job a stopped server left queued, running or paused.

    A job runs on a thread of the API process that started it (`job_alive`), and a process that
    has just started runs none -- so, when no other server runs on the database
    (`claim_job_runner`, which the caller asks first), a job the database still calls active
    belongs to a server that stopped mid-run, and no thread will ever finish it. Left alone it
    said "running" for ever: the Overview showed it, and every new run of its project was refused
    as JOB_ALREADY_RUNNING until someone pressed Cancel Job (2026-09-30: two such jobs, one from
    June). Each is marked failed with what happened, and its unfinished draft version is freed,
    as a cancel of a dead job does. Returns how many.

    Except a job whose run is in the BACKGROUND (`_execute_detached`): that run did not stop with
    the server, so it is followed again (`_reattach_detached`) and its job ends when it does.

    `before` (the API passes `PROCESS_STARTED`): only jobs started before then. The check may run
    late -- tried again while the database does not answer -- and a job started meanwhile is this
    process's own, between its row being written and its thread being registered.
    """
    failed = 0
    for job in db.jobs.list_active():
        if job_alive(job.id) or _reexport_alive(job.id):
            continue
        started = job.started_at
        if before is not None and started is not None:
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            if started >= before:
                continue
        if _reattach_detached(db, job):
            continue
        if reattach_only:
            # The periodic pass: only background runs nobody follows. A job with no run.json
            # may be queued, checking out or starting -- the start-up check decides those.
            continue
        job.status = "failed"
        job.error_message = INTERRUPTED_MESSAGE
        job.completed_at = _now()
        db.jobs.update(job)
        _release_draft_version(db, job)
        failed += 1
    return failed


# ---------------------------------------------------------------------------
# Main thread entry
# ---------------------------------------------------------------------------

def _run(db: Any, job_id: str) -> None:
    try:
        _init_state(job_id)
        _inner_run(db, job_id)
    except Exception as exc:
        # Kept when there is work in it: a database error at the end of a long run must not
        # delete the version it made. If even this fails, the job stays active with nothing
        # following it, and the periodic check follows its run again (main._watch_jobs).
        try:
            _fail_keeping_work(db, job_id, f"Runner error: {exc}")
        except Exception as exc2:                             # noqa: BLE001 - see above
            _log.error("job %s: could not record the runner error (%s)", job_id, exc2)
    finally:
        # A cancelled run's draft goes too -- here, once the subprocess has exited, not in the
        # cancel route while the engine may still be writing rows under that version.
        try:
            job = db.jobs.get(job_id)
            if job is not None and job.status == "cancelled":
                _release_draft_version(db, job)
                _finish_if_it_finished(db, job)
        except Exception as exc:                              # noqa: BLE001 - cleanup only
            _log.warning("job %s: draft cleanup after cancel failed: %s", job_id, exc)
        _cleanup_state(job_id)


def _finish_if_it_finished(db: Any, job: Any) -> None:
    """A cancel that came too late: the run had finished and recorded its documents, so its
    version is no longer a draft and was kept. Finalise it as a finished run (`_complete`) --
    left as it was, it said "Generating…" for ever, with no functions registered -- and the job
    says complete: the run did.

    A background run says whether it finished (its exit code): a resume of a version that had
    documents already starts out of draft, and stopping it half-way is a cancel, not a finish."""
    vid = getattr(job, "version_id", None)
    v = db.versions.get(vid) if vid else None
    if v is None or getattr(v, "status", None) == "draft":
        return
    fr = _frozen_run_module()
    run = fr.find_job_run(_data_root(), vid, job.id) if fr is not None else None
    if run is not None and fr.read_exit(run["run_dir"]) not in (0, 3):
        return
    _append_log(job.id, "The run had finished before the cancel; its version is kept.")
    _complete(db, job.id, force=True)


def _inner_run(db: Any, job_id: str) -> None:
    job = db.jobs.get(job_id)
    if not job:
        return
    project = db.projects.get(job.project_id)
    if not project:
        _mark_failed(db, job_id, "Project not found.")
        return

    # Respect JOB_MAX_CONCURRENCY — block until a slot is free (or job cancelled).
    sem = _get_semaphore()
    while not sem.acquire(timeout=2.0):
        if _is_cancelled(db, job_id):
            return

    try:
        # NOT under the version's writer lock: the run is `analyzer.py generate`, which takes it
        # itself, in its own process -- holding it here as well refused that process, and every
        # run started from the web app failed at once. (A re-export, which runs the engine
        # directly, does hold it here: `_run_reexport`.)
        _inner_run_locked(db, job_id, project)
    finally:
        sem.release()


def _version_run_module():
    """core.version_run, with the engine on the path (it is added lazily, as elsewhere here);
    None when it cannot be imported."""
    try:
        eng_dir = os.path.join(str(get_settings().repo_root), "engine")
        if eng_dir not in sys.path:
            sys.path.insert(0, eng_dir)
        from core import version_run
        return version_run
    except ImportError:
        return None


def _version_busy(exc: BaseException) -> bool:
    return type(exc).__name__ == "VersionBusy"


def _version_writer(db: Any, version_id: Optional[str], command: str):
    """Hold the version's writer lock and record the run, on the API's OWN database (the one
    its versions are in). A no-op for the in-memory database and without a version id."""
    import contextlib
    eng = getattr(db, "_engine", None)
    vr = _version_run_module() if (eng is not None and version_id) else None
    if vr is None:
        return contextlib.nullcontext()
    return vr.writing(version_id, command=command, engine=eng)


def version_writer_busy(db: Any, version_id: str) -> Optional[str]:
    """Who is writing the version now, in words -- or None. For refusing a re-export up front."""
    eng = getattr(db, "_engine", None)
    vr = _version_run_module() if eng is not None else None
    if vr is None:
        return None
    try:
        describe, holder = vr.describe, vr.holder
        h = holder(version_id, engine=eng)
        return describe(h) if h else None
    except Exception:                                # noqa: BLE001 - the job checks again
        return None


def _scope_to_cli(scope: Any) -> str:
    """Map a scope dict {type, names} to the engine's --scope string
    (project | layer:L | group:G | component:C1,C2)."""
    if not isinstance(scope, dict):
        return "project"
    stype = scope.get("type") or "project"
    names = scope.get("names") or []
    if stype == "project" or not names:
        return "project"
    return f"{stype}:{','.join(str(n) for n in names)}"


def _inner_run_locked(db: Any, job_id: str, project: Any) -> None:
    job = db.jobs.get(job_id)
    if not job:
        return

    job.status = "running"
    job.current_activity = "Preparing workspace…"
    db.jobs.update(job)
    _reserve_version(db, job, project)     # version row must exist before the engine (PgStore FK)
    _append_log(job_id, "Starting analysis pipeline…")

    root = get_settings().repo_root

    # 1. Checkout commit
    checkout_dir = root / "workspaces" / job.project_id / job.commit_sha[:16]
    try:
        _checkout(project, job.commit_sha, checkout_dir, job_id)
    except Exception as exc:
        _mark_failed(db, job_id, f"Checkout failed: {exc}")
        return

    _append_log(job_id, f"Checked out commit {job.commit_sha[:8]} → {checkout_dir.name}")

    # 2. Write per-project config
    workspace_dir = root / "workspaces" / job.project_id
    try:
        config_path, analysis_cfg = _write_project_config(
            project, workspace_dir, no_llm=bool(getattr(job, "no_llm", False)))
    except Exception as exc:
        _mark_failed(db, job_id, f"Config generation failed: {exc}")
        return
    _store_resolved_config(db, job, analysis_cfg)   # per-version config → versions.resolved_config
    _append_log(job_id, f"Config written to {config_path.name}")

    if _is_cancelled(db, job_id):
        return

    job = db.jobs.get(job_id)
    job.current_activity = _ACTIVITY[1]
    db.jobs.update(job)

    # 3. Produce the version through `analyzer.py generate` -- see `_generate_cmd`. The engine
    #    reuses the checkout we just made, writes model/output + manifest into the version's own
    #    directory, and seeds the reuse index. The job lifecycle (SSE phase tailing, cancel)
    #    wraps the subprocess as before.
    job = db.jobs.get(job_id)
    if not getattr(job, "version_id", None):
        # Every job reserves one at creation; the CLI requires it. Say so rather than hand the
        # subprocess a None.
        _mark_failed(db, job_id, "This job has no version id, so there is nothing to generate "
                                 "into. Start a new job.")
        return
    if getattr(job, "data_dict_id", None):
        # Materialise it FIRST — the engine resolves the id to a file, and nothing else
        # creates that file.
        _materialise_data_dictionary(db, job)
    mode = (getattr(job, "mode", "auto") or "auto")
    config_path = _freeze_version_config(job, config_path)
    cmd = _generate_cmd(job, root, config_path)
    _append_log(job_id, f"Generating ({'full' if mode == 'full' else 'auto'}) via analyzer.py generate…")

    # In the background when the API has a database: the run outlives this server
    # (`_execute_detached`), and a restarted server follows it again.
    ok = _run_engine_command(db, job_id, cmd, phase_start=1, extra_env=_engine_db_env(db))
    if ok:
        _when_db_answers(job_id, "finishing the job", _complete, db, job_id)


def _freeze_version_config(job: Any, config_path: Path) -> Path:
    """The version's own copy of the config the run starts with, and its path.

    `export`, `resume` and `reexport` read `<version dir>/config.json` first
    (analyzer._render_version), else the project's `config.json` -- which every later run
    rewrites. A run stopped on day 3 and resumed after another run (LLM off, other layers) would
    have carried on with that run's settings. The paths in the config are absolute, so the copy
    reads the same files."""
    vid = getattr(job, "version_id", None)
    if not vid:
        return config_path
    try:
        vdir = doc_render.workspaces_root() / job.project_id / "versions" / vid
        vdir.mkdir(parents=True, exist_ok=True)
        with open(config_path, encoding="utf-8") as fh:
            cfg = json.loads(_strip_jsonc(fh.read()))
        # A core's typed macros are a file of the PROJECT (cores/<core>/macros.json), rewritten
        # by every run: the version keeps its own. (Uploaded files are kept by upload id.)
        for name, core in (cfg.get("cores") or {}).items():
            src = core.get("macros") if isinstance(core, dict) else None
            if src and os.path.isfile(src):
                dst = vdir / "cores" / re.sub(r"[^A-Za-z0-9._-]+", "_", str(name)) / Path(src).name
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)
                core["macros"] = str(dst)
        dest = vdir / "config.json"
        with open(dest, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
        return dest
    except (OSError, ValueError) as exc:
        _append_log(getattr(job, "id", ""), f"note: the version's own copy of the config could "
                                            f"not be written ({exc}); using the project's")
        return config_path


#: Database errors the end of a run waits out rather than turns into a failed job.
_DB_RETRY_SECONDS = 30.0
_DB_RETRY_FOR = 6 * 3600.0


def _db_unavailable(exc: BaseException) -> bool:
    """Whether `exc` says the database did not answer (connection refused or lost, pool
    exhausted) -- what waiting fixes. A constraint violation or a missing column does not go away:
    those raise at once, or a job would sit "running" for six hours over a bug."""
    try:
        from sqlalchemy import exc as sa_exc
    except ImportError:                                      # pragma: no cover
        return False
    if isinstance(exc, (sa_exc.OperationalError, sa_exc.InterfaceError,
                        sa_exc.DisconnectionError, sa_exc.TimeoutError)):
        return True
    return isinstance(exc, sa_exc.DBAPIError) and bool(getattr(exc, "connection_invalidated", False))


def _when_db_answers(job_id: str, what: str, fn, *args):
    """`fn(*args)`, tried again every 30 s while the database does not answer (up to six hours).

    The end of a run -- its outcome judged, the version finalised -- is a handful of writes after
    days of work. A database restart at that moment raised out of the runner: the job failed
    ("Runner error") or stayed "running" with nothing following it. The run's outcome is on disk
    (exit.json), so waiting for the database loses nothing. Other errors raise at once."""
    end = time.monotonic() + _DB_RETRY_FOR
    warned = False
    while True:
        try:
            return fn(*args)
        except Exception as exc:
            if not _db_unavailable(exc) or time.monotonic() >= end:
                raise
            if not warned:
                warned = True
                _log.warning("job %s: %s: the database did not answer (%s); trying again every "
                             "%.0f s", job_id, what, type(exc).__name__, _DB_RETRY_SECONDS)
                _append_log(job_id, f"The database did not answer while {what}; trying again "
                                    f"every {_DB_RETRY_SECONDS:.0f} s.")
            time.sleep(_DB_RETRY_SECONDS)


def _generate_cmd(job: Any, root: Path, config_path: Path) -> list[str]:
    """The command that produces a job's version: `analyzer.py generate`.

    This spawned `engine/incremental/generate.py` (mode "full") or `engine.py` (otherwise) until
    e0f5aef made `analyzer.py` the only front door. Both scripts' `main()` now print "This is not
    a command any more" and exit 2, so every run started from the web app failed before parsing
    anything. `analyzer.py generate` calls the same two functions with the same options under the
    CLI's names, so this is a translation, not a change of behaviour:

        mode "full"               --full                 generate_full
        anything else             (default)              generate_incremental, which falls back
                                                         to full when there is no usable baseline
        reference_version_id      --base-version         incremental only; the real `ver…` id
        narrowed_parse is False   --no-narrowed-parse    incremental only
        data_dict_id              --data-dict
        no_llm                    --no-llm

    `--doc-type all`, always: a run that makes a component's Detailed Design (SWE.3) makes its
    Unit Test Specification (SWE.4) too (docs/ui-mockups/documents.html). The engine derives
    SWE.4 from the same model with no LLM, so the second document costs little.
    """
    mode = (getattr(job, "mode", "auto") or "auto")
    scope = getattr(job, "scope", None) or {"type": "project"}
    cmd = [sys.executable, str(root / "analyzer.py"), "generate",
           "--project-id", job.project_id,
           # The real `ver…` id reserved at job start (08), so the engine's identity, reuse index
           # and DB records all match the API/DB.
           "--version-id", job.version_id,
           "--branch", job.branch, "--commit", job.commit_sha,
           "--scope", _scope_to_cli(scope),
           "--config", str(config_path),
           "--doc-type", "all"]
    # No `--no-register`: the run records its documents for review itself, as well as `_complete`
    # does (both idempotent), so a 4-day run whose server restarted under it -- the job then
    # marked failed, `_complete` never reached -- still has its documents listed.
    if mode == "full":
        cmd.append("--full")
    else:
        if getattr(job, "reference_version_id", None):
            cmd += ["--base-version", job.reference_version_id]
        # Narrowed parse is ON by default in the engine, so a job opts OUT rather than in. A full
        # generation has no baseline to merge against, and the engine falls back to a full parse
        # by itself whenever it cannot prove the merge safe.
        if getattr(job, "narrowed_parse", True) is False:
            cmd.append("--no-narrowed-parse")
    if getattr(job, "data_dict_id", None):
        cmd += ["--data-dict", job.data_dict_id]
    if getattr(job, "no_llm", False):
        cmd.append("--no-llm")
    return cmd


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------

def _checkout(project: Any, commit_sha: str, checkout_dir: Path, job_id: str) -> None:
    """Clone (or reuse) the project repo and check out commit_sha."""
    if checkout_dir.is_dir() and (checkout_dir / ".git").is_dir():
        _append_log(job_id, "Reusing existing checkout.")
        return

    bc = project.build_config or {}
    token = bc.get("repo_access_token") or bc.get("access_token") or ""
    token = (token or "").strip()
    username = token  # PAT goes in username position for GitHub/GitLab
    password = ""

    checkout_dir.mkdir(parents=True, exist_ok=True)

    # Shallow clone — enough depth to reach the target commit
    git_cli.shallow_clone(
        project.repo_url, username, password, str(checkout_dir),
        ref=project.default_branch or "main",
        depth=50,
    )

    # Check out the specific commit
    git_exe = shutil.which("git") or "git"
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    r = subprocess.run(
        [git_exe, "-C", str(checkout_dir), "checkout", commit_sha],
        capture_output=True, text=True, env=env, shell=False,
    )
    if r.returncode != 0:
        raise RuntimeError(f"git checkout {commit_sha[:8]} failed: {r.stderr.strip()}")


# ---------------------------------------------------------------------------
# Config generation
# ---------------------------------------------------------------------------

def _strip_json_comments(text: str) -> str:
    """Strip // and /* */ comments, skipping the contents of "..." string literals
    (so values like "http://host" or a Windows path are never corrupted).

    Self-contained port of the analyzer's stripper — the API does not import from
    src/. Kept char-by-char (not regex) precisely so a `//` inside a string value
    is preserved.
    """
    result = []
    i = 0
    in_string = False
    escape = False
    while i < len(text):
        c = text[i]
        if escape:
            result.append(c)
            escape = False
            i += 1
            continue
        if c == "\\" and in_string:
            escape = True
            result.append(c)
            i += 1
            continue
        if c == '"' and not escape:
            in_string = not in_string
            result.append(c)
            i += 1
            continue
        if in_string:
            result.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < len(text):
            if text[i + 1] == "/":
                i += 2
                while i < len(text) and text[i] != "\n":
                    i += 1
                continue
            if text[i + 1] == "*":
                i += 2
                while i + 1 < len(text) and (text[i] != "*" or text[i + 1] != "/"):
                    i += 1
                i += 2
                continue
        result.append(c)
        i += 1
    return "".join(result)


def _strip_trailing_commas(text: str) -> str:
    """Remove trailing commas before } or ] (JSON5-style), outside strings."""
    out = []
    i = 0
    in_string = False
    escape = False
    n = len(text)
    while i < n:
        c = text[i]
        if escape:
            out.append(c)
            escape = False
            i += 1
            continue
        if c == "\\" and in_string:
            escape = True
            out.append(c)
            i += 1
            continue
        if c == '"':
            in_string = not in_string
            out.append(c)
            i += 1
            continue
        if not in_string and c == ",":
            j = i + 1
            while j < n and text[j] in (" ", "\t", "\r", "\n"):
                j += 1
            if j < n and text[j] in ("}", "]"):
                i += 1
                continue
        out.append(c)
        i += 1
    return "".join(out)


def _strip_jsonc(text: str) -> str:
    """Strip JSONC comments + trailing commas (string-aware) so config.json may use
    // and /* */ comments without breaking the parse."""
    return _strip_trailing_commas(_strip_json_comments(text))


def _load_base_config(base_path: Path) -> dict:
    """Parse the base config/config.defaults.json as JSONC (comments + trailing commas allowed).
    Returns {} on any read/parse failure, matching the prior json.load fallback."""
    try:
        with open(base_path, "r", encoding="utf-8") as f:
            return json.loads(_strip_jsonc(f.read()))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_project_config(project: Any, workspace_dir: Path, *, no_llm: bool = False) -> tuple[Path, dict]:
    """Materialize the workspace config.json the engine runs with, and return it alongside the
    NON-SECRET analysis config that is stored per version (versions.resolved_config).

    Two configs come out of here, by design:

      * ``analysis_cfg`` — config.defaults.json + this project's build_config + layers (+ no_llm).
        No secrets. This is the reproducible, self-describing per-version config → resolved_config.
      * the workspace file — ``analysis_cfg`` overlaid with engine/config/config.local.json's
        secrets (llm baseUrl/credentials, any machine-specific override) so the engine can reach
        the LLM. The ``db`` section is deliberately NOT written to this on-disk file: the engine
        talks to Postgres via the DATABASE_URL env, so the DB password has no business in it.
    """
    from core.config import _deep_merge
    base_path = get_settings().repo_root / "engine" / "config" / "config.defaults.json"
    cfg = _load_base_config(base_path)
    # The defaults' `project` block names the sample project, for the wizard's Import config; the
    # engine ignores it, and left in, every version's stored config would carry the sample's name.
    cfg.pop("project", None)

    # Apply explicit section overrides from build_config (per-project, from onboarding)
    bc = project.build_config or {}
    for key in ("clang", "llm", "views", "docx"):
        if key in bc and isinstance(bc[key], dict):
            cfg.setdefault(key, {})
            cfg[key].update(bc[key])

    # Convert architecture_layers to the layers schema. Names have to be unambiguous
    # BEFORE the engine sees them: the wizard hands over lists, the config is dicts keyed
    # by name, and every collision - a name reused in one scope, or a group/component name
    # reused across layers - used to resolve itself by silently dropping or merging one
    # side. The result was a document quietly missing a group, or one component holding two
    # layers' files and parsed with a single layer's -D set. Fail the job instead.
    layers = _convert_layers(project.architecture_layers or [])
    if layers:
        cfg["layers"] = layers
        # The defaults' `cores` belong to their own (sample) layers, which these replace. A web
        # project names no core - its definitions reach Clang as clang.macrosFile - so every run
        # warned "cores.Core1 is listed by no layer", and the web app shows a run's warnings.
        cfg.pop("cores", None)
    from core.config import validate_layer_names
    name_problems = (_duplicate_wizard_names(project.architecture_layers or [])
                     + validate_layer_names({"layers": layers}))
    if name_problems:
        raise ValueError("ambiguous architecture layer names - "
                         + "; ".join(name_problems))

    # Cores: each one's macros, data dictionary and compile commands as files the engine reads
    # (cores.<Core>), and the core each layer is built for (layers.<Layer>.cores) - so a layer's
    # files parse with its own core's -D set and include paths. A project from before cores (one
    # definitions file and one dictionary) is one core, Core1, used by every layer.
    from .project_cores import project_cores
    cores, layer_core = project_cores(bc, project.architecture_layers or [])
    if cores:
        cfg["cores"] = {c["name"]: _materialize_core(c, workspace_dir) for c in cores}
        for lname, core in layer_core.items():
            if core and lname in (cfg.get("layers") or {}):
                cfg["layers"][lname]["cores"] = [core]

    # noLlm — disable per-entity LLM (descriptions + behaviour names), mirroring
    # apply_no_llm. Phase summarization is disabled via --no-llm-summarize in _build_cmd.
    if no_llm:
        cfg.setdefault("llm", {})
        cfg["llm"]["descriptions"] = False
        cfg["llm"]["behaviourNames"] = False

    # Snapshot the non-secret analysis config BEFORE overlaying secrets — this is what gets
    # persisted per version. deepcopy so the secret overlay below can't leak back into it.
    analysis_cfg = copy.deepcopy(cfg)

    # Overlay secrets from config.local.json (gitignored) into the RUNTIME file only: llm creds/URL
    # (and any machine-specific override) reach the engine, but never enter resolved_config. Drop
    # `db` so the DB password is not written to a workspace file. Deep-merged per nested key, so a
    # partial `llm` block (e.g. just customHeaders) overrides without restating the whole block.
    local_path = base_path.parent / "config.local.json"
    if local_path.is_file():
        try:
            local = _load_base_config(local_path)
            local.pop("db", None)
            local.pop("auth", None)        # the API server's own setting; no engine reads it
            _deep_merge(cfg, local)
        except Exception:                            # best-effort: run with the non-secret config
            pass

    workspace_dir.mkdir(parents=True, exist_ok=True)
    out_path = workspace_dir / "config.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    return out_path, analysis_cfg


def _materialize_core(core: dict, workspace_dir: Path) -> dict:
    """One core's inputs as the paths the engine reads: `{macros, dataDictionary,
    compileCommands}`, each only when the core has it. Typed macros are written to
    `cores/<core>/macros.json`; an uploaded file is read where the upload route stored it."""
    from ..routes.repositories import resolve_upload
    out: dict = {}
    folder = workspace_dir / "cores" / re.sub(r"[^A-Za-z0-9._-]+", "_", core["name"])
    macros = _materialize_macros(core.get("macros"), folder)
    if macros:
        out["macros"] = str(macros)
    for key, field in (("dataDictionary", "data_dictionary"), ("compileCommands", "compile_commands")):
        ref = core.get(field)
        path = resolve_upload(ref["file_id"]) if ref else None
        if path is not None:
            out[key] = str(path)
    return out


def _materialize_macros(defs: Any, workspace_dir: Path) -> Optional[Path]:
    """Resolve build_config.preprocessor_definitions to a file on disk, or None.

    `mode: "manual"` writes the wizard's ``["NAME=VALUE", ...]`` list next to the
    per-project config; `mode: "upload"` returns the stored upload (CSV or any of
    the JSON shapes engine/core/macro_input.py reads) as-is.
    """
    if not isinstance(defs, dict):
        return None

    mode = str(defs.get("mode") or "manual").lower()
    if mode == "upload":
        from ..routes.repositories import resolve_upload
        return resolve_upload(str(defs.get("file_id") or ""))

    entries = [str(d).strip() for d in (defs.get("defines") or []) if str(d).strip()]
    if not entries:
        return None
    workspace_dir.mkdir(parents=True, exist_ok=True)
    out_path = workspace_dir / "macros.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)
    return out_path


def _convert_layers(arch_layers: list) -> dict:
    """Convert API architecture_layers list to config.json layers dict.

    API shape (from NewProjectPage):
      [{"name": "L1", "path": "Layer1", "lib_paths": [...],
        "groups": [{"name": "G1", "components": [{"name": "C1", "files": [...]}]}]}]
    Config shape (component value is the selection relative to the layer path —
    a string for a single path, a list for several):
      {"L1": {"path": "Layer1", "groups": {
          "G1": {"Single": "Sample/Core",
                 "Multi": ["Flow/Flowcharts.cpp", "Math/Utils.cpp"]}}}}

    Component paths preserve the wizard selection verbatim (files stay files,
    folders stay folders), each stripped of the layer path prefix. See
    _component_paths_from_files.
    """
    result: dict = {}
    for layer in arch_layers:
        if not isinstance(layer, dict):
            continue
        lname = str(layer.get("name") or "").strip()
        lpath = str(layer.get("path") or lname).strip()
        if not lname:
            continue
        groups: dict = {}
        for g in (layer.get("groups") or []):
            if isinstance(g, str):
                gname, comps = g.strip(), {}
            elif isinstance(g, dict):
                gname = str(g.get("name") or "").strip()
                comps = {}
                for c in (g.get("components") or []):
                    if isinstance(c, str):
                        cname = c.strip()
                        if cname:
                            comps[cname] = cname
                    elif isinstance(c, dict):
                        cname = str(c.get("name") or "").strip()
                        files = [str(f) for f in (c.get("files") or []) if f]
                        if cname:
                            rels = _component_paths_from_files(files, lpath)
                            if not rels:
                                # No usable selection — fall back to the component
                                # name (parity with the bare-string component case).
                                comps[cname] = cname
                            else:
                                comps[cname] = rels[0] if len(rels) == 1 else rels
            else:
                continue
            if gname:
                groups[gname] = comps
        result[lname] = {"path": lpath, "groups": groups}
    return result


def _duplicate_wizard_names(arch_layers: list) -> list:
    """Names the list -> dict conversion in _convert_layers would silently swallow.

    `architecture_layers` arrives as LISTS, and _convert_layers writes each entry
    into a dict keyed by name: two layers, two groups in one layer, or two
    components in one group sharing a name means the second one REPLACES the
    first, and the wizard's selection is lost with no error anywhere.

    Only same-scope duplicates are reported here, because those are the ones that
    disappear before `layers` exists. Cross-layer collisions survive the
    conversion and are reported by core.config.validate_layer_names instead.
    """
    from core.config import name_ident

    problems: list = []
    seen_layers: dict = {}
    for layer in arch_layers or []:
        if not isinstance(layer, dict):
            continue
        lname = str(layer.get("name") or "").strip()
        if not lname:
            continue
        if name_ident(lname) in seen_layers:
            problems.append(f"two layers are named {lname!r}")
            continue
        seen_layers[name_ident(lname)] = lname

        seen_groups: dict = {}
        for g in (layer.get("groups") or []):
            if isinstance(g, str):
                gname, comps = g.strip(), []
            elif isinstance(g, dict):
                gname, comps = str(g.get("name") or "").strip(), (g.get("components") or [])
            else:
                continue
            if not gname:
                continue
            if name_ident(gname) in seen_groups:
                problems.append(f"layer {lname!r} has two groups named {gname!r}")
                continue
            seen_groups[name_ident(gname)] = gname

            seen_comps: dict = {}
            for c in comps:
                cname = c.strip() if isinstance(c, str) else (
                    str(c.get("name") or "").strip() if isinstance(c, dict) else "")
                if not cname:
                    continue
                if name_ident(cname) in seen_comps:
                    problems.append(
                        f"group {lname}/{gname} has two components named {cname!r}")
                    continue
                seen_comps[name_ident(cname)] = cname
    return problems


def _norm_rel(path: str) -> str:
    """Normalize a repo-relative path: backslashes -> '/', drop leading './' and
    surrounding slashes."""
    p = (path or "").replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    return p.strip("/")


def _component_paths_from_files(files: list, layer_path: str) -> list:
    """Return the wizard selection relative to ``layer_path``, order-preserving.

    Each entry in ``files`` (a file or a folder, expressed from the repo root) is
    normalized and stripped of the ``layer_path`` prefix so it becomes relative to
    the layer root. The selection is preserved verbatim — files stay files and
    folders stay folders — rather than being collapsed to a common-ancestor
    directory, which over-selects and degenerates to the layer root whenever the
    selection spans sibling directories.

    An entry equal to the layer path itself (a whole-layer selection) becomes ``""``,
    the config's own spelling of "the whole layer" (``core.config._resolve_layer_paths``).
    It used to be dropped, and ``_convert_layers`` then fell back to the component NAME
    as its path: a config whose component took its whole layer came back from the web
    app pointing at a folder that does not exist, and the run stopped on it. An
    entry that is not under the layer is kept as-is (defensive; the wizard only picks
    within the layer). Duplicates are removed.

    Both the ``str`` (single path) and ``list`` (multiple paths) result forms are
    accepted downstream by ``core.config._resolve_layer_paths`` and
    ``parser._build_file_component_map``.
    """
    layer_norm = _norm_rel(layer_path)
    prefix = layer_norm + "/" if layer_norm else ""
    out: list = []
    seen: set = set()
    for f in files:
        p = _norm_rel(str(f) if f is not None else "")
        if not p:
            continue
        if layer_norm and p == layer_norm:
            p = ""                              # the whole layer
        elif prefix and p.startswith(prefix):
            p = p[len(prefix):]
        if p not in seen:                       # "" only for the whole layer
            seen.add(p)
            out.append(p)
    return out


# ---------------------------------------------------------------------------
# Command building
# ---------------------------------------------------------------------------

def _build_cmd(
    job: Any,
    checkout_dir: Path,
    config_path: Path,
    *,
    from_phase: int = 1,
    to_phase: Optional[int] = None,
    use_model: bool = False,
    arch_layers: list = (),
    model_root=None,
    output_root=None,
    version_id=None,
    doc_type: Optional[str] = None,
) -> list[str]:
    cmd = [sys.executable, str(get_settings().repo_root / "engine" / "run.py")]
    cmd += ["--config", str(config_path)]
    # Which documents Phase 4 writes (`export_doc_type`): run.py's default is swe3 alone.
    if doc_type:
        cmd += ["--doc-type", doc_type]
    # Run against THIS version's own model/ and output/ instead of the shared <repo>/model
    # and <repo>/output (doc 09, B1 + C11b). Without these the caller has to stage the
    # version's trees into the repo root first — which means rmtree-ing a directory another
    # concurrent job may be using.
    if model_root is not None:
        cmd += ["--model-root", str(model_root)]
    if output_root is not None:
        cmd += ["--output-root", str(output_root)]
    # Where the model lives, and which version's (doc 10, step 8). Re-export runs
    # `--use-model --from-phase 4`, which now asks the REPOSITORY whether the model exists —
    # so a version whose model is in the database must say so, or Phase 4 looks for files that
    # were never written and the job fails with "model is missing".
    if version_id:
        cmd += ["--version-id", version_id]
    if use_model:
        cmd.append("--use-model")
    if from_phase > 1:
        cmd += ["--from-phase", str(from_phase)]
    if to_phase is not None:
        cmd += ["--to-phase", str(to_phase)]
    # Scope -> run.py selection flags (mutually exclusive with --selected-layer). A
    # first-class scope wins over layer_filter; project scope selects nothing (full).
    #
    # One flag PER NAME: run.py takes each of these repeatedly, as `--scope group:A,B` does
    # for a generation. Passing only the first name re-exported a version generated for
    # several groups as if it had one -- the other groups' views were never re-derived, so
    # their corrections never reached the Word file (found by tools/review_api_test).
    scope = getattr(job, "scope", None)
    stype = (scope.get("type") if isinstance(scope, dict) else None) or "project"
    names = (scope.get("names") if isinstance(scope, dict) else None) or []
    flag = {"group": "--selected-group", "component": "--selected-component",
            "layer": "--selected-layer"}.get(stype)
    if flag and names:
        for name in names:
            cmd += [flag, str(name)]
    elif job.layer_filter:
        cmd += ["--selected-layer", job.layer_filter]
    # One DOCX per component, for every scope -- as a generation makes them
    # (`per_component_docx_args`). It used to be left out of a component scope, from when run.py
    # refused the two together; it no longer does, and without it a version of several
    # components was re-exported as ONE bundled document while each component's own document
    # kept its old text.
    cmd.append("--component-per-docx")
    if getattr(job, "no_llm", False):
        cmd.append("--no-llm-summarize")     # descriptions/behaviourNames disabled via config
    ddid = getattr(job, "data_dict_id", None)
    if ddid:
        dd_path = (get_settings().repo_root / "workspaces" / job.project_id
                   / "datadict" / f"{ddid}.csv")
        if dd_path.is_file():
            cmd += ["--data-dictionary", str(dd_path)]
    # The DOCX project name is the job's VERSION TAG, not the project name. This reverses the
    # earlier D-3 decision deliberately: re-exporting v1 and v2 now yields documents titled
    # "v1.0" and "v2.1" rather than both carrying the project name.
    if getattr(job, "version_tag", None):
        cmd += ["--project-name", job.version_tag]
    # Extra include paths from architecture_layers.lib_paths (--include-path-layer <layer> <abs_dir>)
    for layer in arch_layers:
        if not isinstance(layer, dict):
            continue
        lname = str(layer.get("name") or "").strip()
        if not lname:
            continue
        for lp in (layer.get("lib_paths") or []):
            lp = str(lp).strip()
            if lp:
                cmd += ["--include-path-layer", lname, str(checkout_dir / lp)]
    cmd.append(str(checkout_dir))
    return cmd


# ---------------------------------------------------------------------------
# Incremental helpers
# ---------------------------------------------------------------------------


def _find_project_repo(project_id: str) -> Optional[Path]:
    """Newest existing per-commit checkout (a git repo) for the project, for read-only git
    queries (baseline preview). None when the project has never been generated."""
    base = get_settings().repo_root / "workspaces" / project_id
    if not base.is_dir():
        return None
    repos = [d for d in base.iterdir() if d.is_dir() and (d / ".git").is_dir()]
    return max(repos, key=lambda d: d.stat().st_mtime) if repos else None


def preview_baseline(db: Any, project_id: str, commit: str,
                     base_version_id: Optional[str] = None) -> dict:
    """Read-only baseline decision for `commit` (what an auto-mode job WOULD pick), using an
    existing project checkout for git ancestry. No checkout/clone, changes nothing — mirrors
    the standalone /generate/preview. Returns the select_baseline result, or a full-decision
    stub with a warning when no local history is available yet."""
    def _stub(warning: str) -> dict:
        return {"targetCommit": commit, "decision": "full",
                "chosenBaseVersionId": None, "chosenBaseCommit": None,
                "chosenIsAncestor": False, "chosenIsNearest": False,
                "changedFiles": None, "warnings": [warning]}

    import sys as _sys
    src_dir = str(get_settings().repo_root / "engine")
    if src_dir not in _sys.path:
        _sys.path.insert(0, src_dir)
    try:
        from incremental import git_ops                      # type: ignore[import]
        from incremental.baseline import select_baseline     # type: ignore[import]
        from incremental.project_db import list_versions     # type: ignore[import]
    except Exception as exc:
        return _stub(f"incremental engine unavailable ({exc})")

    repo = _find_project_repo(project_id)
    if not repo:
        return _stub("no local checkout yet — run one generation to enable incremental previews")
    target = git_ops.resolve(str(repo), commit)
    if not target:
        return _stub(f"commit {commit!r} not found in the local checkout")
    # Same version list the engine uses (api/db/data/versions.json), commit-addressed.
    # base_version_id from the UI is an API Version.id; translate to the engine's
    # commit[:16] namespace (pass through unknown values so a real versionId still works).
    _resolved = _resolve_ref_commit(db, base_version_id)
    base_arg = _resolved[:16] if _resolved else base_version_id
    return select_baseline(str(repo), list_versions(project_id), target, base_arg)


# ---------------------------------------------------------------------------
# Run strategies
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Subprocess execution + output tailing
# ---------------------------------------------------------------------------

def _engine_db_env(db: Any) -> dict:
    """DATABASE_URL for the engine subprocess when the API is on the SQL backend, so the
    engine reads its project/version/baseline metadata from the same DB (project_db and
    the incremental baseline read gate on DATABASE_URL). Empty otherwise, so file-based
    dev is unchanged. Resolves the DSN via core.db so it matches the default when unset."""
    if getattr(db, "_engine", None) is None:
        return {}
    try:
        import sys
        eng_dir = os.path.join(str(get_settings().repo_root), "engine")
        if eng_dir not in sys.path:
            sys.path.insert(0, eng_dir)
        from core.db import database_url
        return {"DATABASE_URL": database_url()}
    except Exception:
        return {}


def _execute_subprocess(
    db: Any,
    job_id: str,
    cmd: list[str],
    phase_start: int = 1,
    extra_env: Optional[dict] = None,
    partial_ok: bool = True,
) -> bool:
    """Run cmd, tail its output, update job progress. Returns True on success.

    Exit 3 (`partial_ok`): some components' documents failed and the run went on with the
    others (engine/run.py). That is a success with failures in it -- the version keeps what was
    made, and its Components panel names the failed ones -- not a failed job, whose draft
    version would be deleted with everything the run made."""
    cfg = get_settings()
    env = _subprocess_env(db, job_id, extra_env)

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cfg.repo_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    except Exception as exc:
        _mark_failed(db, job_id, f"Failed to start run.py: {exc}")
        return False

    with _LOCK:
        _job_procs[job_id] = proc

    tracker = _LineTracker(db, job_id, phase_start)
    recent_lines = tracker.recent_lines
    _timeout = get_settings().subprocess_timeout or None
    _timed_out = False

    # This loop is the only thing reading the child's output. Every way out of it before the end
    # of that output -- a cancel, or anything raising -- leaves a child writing into a pipe nobody
    # drains: it blocks when the pipe fills, and `wait()` below then waits for ever with the job
    # stuck at "running". So an early exit stops the whole tree first.
    abandoned = True
    try:
        for raw_line in proc.stdout:
            if tracker.feed(raw_line):
                return False
        abandoned = False

    finally:
        if abandoned:
            _stop_tree(proc)
        try:
            proc.wait(timeout=_timeout)
        except subprocess.TimeoutExpired:
            _timed_out = True
            _stop_tree(proc)
            proc.wait()

    if _timed_out:
        # Carry the tail here too (doc 09, A0). A timeout is precisely when you need
        # to know what the run was doing when it stalled — the non-zero-exit path
        # below already did this; this one silently dropped it.
        tail = "\n".join(recent_lines[-20:])
        _append_log(job_id, f"Job failed after timing out after {_timeout}s")
        _mark_failed(db, job_id, f"Subprocess timed out after {_timeout}s.\n{tail}")
        return False

    with _LOCK:
        _job_procs.pop(job_id, None)

    rc = proc.returncode
    if _is_cancelled(db, job_id):
        return False

    if rc == 3 and partial_ok:
        _append_log(job_id, "Some components' documents failed (see above); the others were "
                            "made. Their state is on the Documents page's Components panel.")
    elif rc != 0:
        tail = "\n".join(recent_lines[-20:])
        _append_log(job_id, f"Job failed with code {rc}")
        _mark_failed(db, job_id, _failure_message(rc, recent_lines, tail))
        return False

    tracker.finish()
    return True


def _subprocess_env(db: Any, job_id: str, extra_env: Optional[dict] = None) -> dict:
    """The environment a job's analyzer process runs in."""
    cfg = get_settings()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    if cfg.libclang_path:
        env["LIBCLANG_PATH"] = cfg.libclang_path
    # Tag this run's metrics records (doc 09, D2a). Concurrent jobs append to one
    # metrics file, so without an id their phase timings and peak-RSS numbers cannot
    # be told apart — which is the whole point of measuring before raising B4.
    # A background run also records it in its run.json: how a restarted API finds it.
    env["ANALYZER_JOB_ID"] = job_id
    _job = db.jobs.get(job_id)
    _vid = getattr(_job, "version_id", None) if _job else None
    if _vid:
        env["ANALYZER_VERSION_ID"] = str(_vid)
    env.update(extra_env or {})
    return env


class _LineTracker:
    """What a job learns from its run's output, a line at a time: the live log, the phase, the
    activity and the progress -- whether the lines come from a pipe (`_execute_subprocess`) or
    from a background run's log file (`_follow_detached`)."""

    def __init__(self, db: Any, job_id: str, phase_start: int):
        self.db, self.job_id = db, job_id
        self.current_phase = phase_start
        self.phase_start_time = _now()
        self.recent_lines: list[str] = []
        self.line_count = 0
        # Mark the first phase of this run as "running" immediately. Without this, phase_start
        # stays "pending" until the *next* phase fires _transition_phase — meaning phase 1 (and
        # phase 3 on a resume) would skip "running" entirely and jump from "pending" to "done".
        job = db.jobs.get(job_id)
        if job:
            for p in job.phases:
                if p.number == phase_start and p.status != "done":
                    p.status = "running"
            job.phase = phase_start
            db.jobs.update(job)

    def _keep(self, line: str) -> None:
        _append_log(self.job_id, line)
        self.recent_lines.append(line)
        if len(self.recent_lines) > 80:
            self.recent_lines.pop(0)
        self.line_count += 1

    def feed(self, raw_line: str) -> bool:
        """Take one line of output; True when the job has been cancelled."""
        db, job_id = self.db, self.job_id
        line = raw_line.rstrip("\n\r")
        if not line:
            return False
        self._keep(line)

        # Cancel check (every 20 lines to keep overhead low)
        if self.line_count % 20 == 0 and _progress(job_id, _is_cancelled, db, job_id):
            return True

        # Phase transition detection
        new_phase = _detect_phase(line, self.current_phase)
        if new_phase != self.current_phase:
            _progress(job_id, _transition_phase, db, job_id, self.current_phase, new_phase,
                      self.phase_start_time)
            self.current_phase = new_phase
            self.phase_start_time = _now()

        # The ACTIVITY label follows the marker regardless of direction, so a later
        # component's Phase 3 is not still announced as "Exporting".
        _marker = _marker_phase(line)
        if _marker:
            _progress(job_id, _set_activity, db, job_id, _ACTIVITY[_marker])

        # Update activity detail from log content (strip log prefix)
        detail = _strip_log_prefix(line)
        if detail and len(detail) > 10:
            _progress(job_id, _update_activity, db, job_id, detail[:120])
        return False

    def replay(self, lines: list) -> None:
        """Catch up on output written while nobody followed it (an API that restarted): the
        live log and the phase, with one database write instead of one per line."""
        phase, activity, detail = self.current_phase, None, None
        for raw in lines:
            line = raw.rstrip("\n\r")
            if not line:
                continue
            self._keep(line)
            phase = _detect_phase(line, phase)
            marker = _marker_phase(line)
            if marker:
                activity = _ACTIVITY[marker]
            d = _strip_log_prefix(line)
            if d and len(d) > 10:
                detail = d[:120]
        job = self.db.jobs.get(self.job_id)
        if job is None:
            return
        for p in job.phases:
            if p.number < phase and p.status in ("pending", "running"):
                p.status = "done"
            elif p.number == phase and p.status != "done":
                p.status = "running"
        job.phase = phase
        if activity:
            job.current_activity = activity
        if detail:
            job.activity_detail = detail
        job.elapsed_seconds = _elapsed_since(job.started_at)
        _progress(self.job_id, self.db.jobs.update, job)
        self.current_phase = phase

    def finish(self) -> None:
        """Mark the final phase done."""
        job = self.db.jobs.get(self.job_id)
        if job:
            for p in job.phases:
                if p.number == self.current_phase and p.status != "done":
                    p.status = "done"
                    p.duration_seconds = max(
                        1, int((_now() - self.phase_start_time).total_seconds()))
            self.db.jobs.update(job)


# ---------------------------------------------------------------------------
# Background runs: a web run that outlives the API (staged generation, C4)
# ---------------------------------------------------------------------------
#
# A run started as a child of this process died with it: a restart of the API on day 3 of a
# 5-day run stopped the run, the next start failed the job, and failing it deleted the draft
# version with everything in it. So with a database behind the API, a run is started as the
# CLI's `--detach` starts one -- a process of its own, on a frozen copy of the code, its output
# in a log file -- and the job only FOLLOWS it: the log for the live output and the phase, the
# run's process and the version's writer lock for whether it lives, `exit.json` for how it
# ended (core/frozen_run.py). A restarted API follows it again (`fail_interrupted_jobs`).

#: Seconds between two looks at a background run (its log, its process, the job's cancel flag).
DETACHED_POLL_SECONDS = 2.0
_CANCEL_CHECK_SECONDS = 5.0
_LAUNCH_TIMEOUT = 600

_job_runs: dict[str, dict] = {}     # job id -> the background run it follows (run.json's fields)

STOPPED_MESSAGE = ("Stopped: the run's process ended before it finished -- the machine "
                   "restarted, or the process was killed.")


def _resume_hint(job: Any) -> str:
    from ..models.domain import REEXPORT_MODE
    if getattr(job, "mode", None) == REEXPORT_MODE:
        # The version's documents stand as they were; a re-export is started again, not resumed.
        return "The version's documents are as they were before this re-export."
    return (f"What the run made is kept. To carry it on from where it stopped, on the server: "
            f"python analyzer.py resume --project-id {job.project_id} --version-id "
            f"{job.version_id} --detach")


def _frozen_run_module():
    """core.frozen_run, with the engine on the path; None when it cannot be imported."""
    try:
        eng_dir = os.path.join(str(get_settings().repo_root), "engine")
        if eng_dir not in sys.path:
            sys.path.insert(0, eng_dir)
        from core import frozen_run
        return frozen_run
    except ImportError:
        return None


def _data_root() -> str:
    """Where `--detach` puts its runs (`<data root>/runs`), as the analyzer resolves it."""
    try:
        _frozen_run_module()
        from core.paths import paths
        return paths().data_root
    except Exception:                                    # noqa: BLE001
        return str(get_settings().repo_root)


def _detach_enabled(db: Any) -> bool:
    """Runs go to the background when the API has a database (the run, its lock and its record
    are there) and `JOB_DETACH` is not off. The in-memory database keeps the child process."""
    return (getattr(db, "_engine", None) is not None
            and bool(getattr(get_settings(), "job_detach", True))
            and _frozen_run_module() is not None)


def _run_engine_command(db: Any, job_id: str, cmd: list, *, phase_start: int,
                        extra_env: Optional[dict] = None) -> bool:
    """A job's `analyzer.py` command, in the background when it can be (`_execute_detached`),
    else as a child of this process (`_execute_subprocess`). Same answer either way."""
    if _detach_enabled(db):
        return _execute_detached(db, job_id, cmd, phase_start=phase_start, extra_env=extra_env)
    return _execute_subprocess(db, job_id, cmd, phase_start=phase_start, extra_env=extra_env)


class _LaunchFailed(Exception):
    pass


def _launch_detached(cmd: list, env: dict) -> dict:
    """Run `cmd --detach` and return the background run it started: {pid, log_path, run_dir}.

    The launcher is a process of its own that exits once the run has started, so the run is not
    a child of this server: stopping the server's process tree (tools/start_app.py) does not
    reach it. Its output goes to a file, not a pipe -- a pipe is read until every process holding
    it has closed it, and a run that inherited it by accident would hold it for days."""
    import tempfile
    kw: dict = {}
    if os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with tempfile.TemporaryFile() as out:
        try:
            proc = subprocess.run([*cmd, "--detach"], cwd=str(get_settings().repo_root), env=env,
                                  stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                  timeout=_LAUNCH_TIMEOUT, **kw)
        except subprocess.TimeoutExpired:
            raise _LaunchFailed(f"starting the run took more than {_LAUNCH_TIMEOUT} s")
        out.seek(0)
        text = out.read().decode("utf-8", "replace")
    pid = re.search(r"started in the background: pid (\d+)", text)
    log = re.search(r"^\s*log\s+(\S.*?)\s*$", text, re.M)
    if proc.returncode != 0 or not pid or not log:
        raise _LaunchFailed(text.strip() or f"the launcher exited with code {proc.returncode}")
    log_path = log.group(1)
    run = {"pid": int(pid.group(1)), "log_path": log_path, "run_dir": os.path.dirname(log_path)}
    try:                                    # run.json has the process's start time (identity)
        with open(os.path.join(run["run_dir"], "run.json"), encoding="utf-8") as fh:
            run["create_time"] = json.load(fh).get("create_time")
    except (OSError, ValueError):
        pass
    return run


class _LogFollower:
    """A growing log file, read a whole line at a time from where the last read stopped."""

    def __init__(self, path: str):
        self.path, self.offset, self.rest = path, 0, b""

    def read(self) -> list:
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self.offset)
                data = fh.read()
        except OSError:
            return []
        if not data:
            return []
        self.offset += len(data)
        parts = (self.rest + data).split(b"\n")
        self.rest = parts.pop()
        return [p.decode("utf-8", "replace") for p in parts]

    def flush(self) -> list:
        """Everything left, the last line too even without its line break."""
        lines = self.read()
        if self.rest:
            lines.append(self.rest.decode("utf-8", "replace"))
            self.rest = b""
        return lines


def _lock_held(vr: Any, version_id: Optional[str], eng: Any) -> Optional[bool]:
    if vr is None or eng is None or not version_id:
        return None
    return vr.alive(version_id, engine=eng)


def _execute_detached(db: Any, job_id: str, cmd: list, phase_start: int = 1,
                      extra_env: Optional[dict] = None) -> bool:
    """`_execute_subprocess` for a run that must outlive this server: start `cmd` in the
    background and follow it (`_follow_detached`). Same answer: True when it succeeded."""
    env = _subprocess_env(db, job_id, extra_env)
    _append_log(job_id, "Starting the run in the background: it carries on if this server "
                        "stops, and is followed again when the server starts.")
    try:
        run = _launch_detached(cmd, env)
    except _LaunchFailed as exc:
        for line in str(exc).splitlines()[-40:]:
            _append_log(job_id, line)
        # Kept when there is work in it: a resume of a stopped run that cannot start (the
        # version busy for a moment, the code copy failing) must not delete days of work.
        _fail_keeping_work(db, job_id, f"The run could not be started:\n{str(exc)[-3000:]}")
        return False
    _append_log(job_id, f"Background run: process {run['pid']}, log {run['log_path']}")
    return _follow_detached(db, job_id, run, phase_start=phase_start)


def _wait_gone(fr: Any, pid: Optional[int], seconds: float = 30.0,
               create_time: Optional[float] = None) -> None:
    """A run writes its exit code just before it exits: wait for the process to be gone, so the
    last lines it wrote are in the log."""
    end = time.monotonic() + seconds
    while fr.process_alive(pid, create_time) and time.monotonic() < end:
        time.sleep(0.25)


def _follow_detached(db: Any, job_id: str, run: dict, *, phase_start: int,
                     replay: bool = False) -> bool:
    """Follow background run `run` to its end as `_execute_subprocess` follows a child, with the
    same answer: True when it succeeded (exit 0, or 3: some components failed and the others
    were made), False when it failed -- recorded on the job -- or was cancelled (the run is
    stopped then).

    It has ended when it recorded its exit code (`frozen_run.record_exit`). Its process gone with
    no exit code, and the version's lock free, means it died -- the machine restarted, someone
    killed it. Either way the job fails, and what the run made is kept for `resume` once Phase 1
    stored anything (`_fail_keeping_work`). `replay`: catch up on the whole log first (an API that
    restarted while the run went on)."""
    fr = _frozen_run_module()
    vr = _version_run_module()
    eng = getattr(db, "_engine", None)
    job = db.jobs.get(job_id)
    vid = getattr(job, "version_id", None) if job else None
    pid, born = run.get("pid"), run.get("create_time")
    run_dir = run.get("run_dir") or os.path.dirname(run["log_path"])
    with _LOCK:
        _job_runs[job_id] = run
    rc: Optional[int] = None
    try:
        tracker = _LineTracker(db, job_id, phase_start)
        log = _LogFollower(run["log_path"])
        if replay:
            tracker.replay(log.read())
        held_once, next_cancel_check = False, 0.0
        while True:
            for line in log.read():
                if tracker.feed(line):
                    fr.stop(pid, born)
                    return False
            now = time.monotonic()
            if now >= next_cancel_check:
                if _progress(job_id, _is_cancelled, db, job_id):
                    fr.stop(pid, born)
                    return False
                next_cancel_check = now + _CANCEL_CHECK_SECONDS
            rc = fr.read_exit(run_dir)
            if rc is None:
                alive = fr.process_alive(pid, born)
                if alive:
                    time.sleep(DETACHED_POLL_SECONDS)
                    continue
                held = _progress(job_id, _lock_held, vr, vid, eng)
                held_once = held_once or bool(held)
                # Without psutil the process cannot be asked: then the lock decides, once the
                # run has been seen holding it (it takes it a few seconds after it starts).
                if held or (alive is None and not held_once):
                    time.sleep(DETACHED_POLL_SECONDS)
                    continue
                rc = fr.read_exit(run_dir)          # it may have ended between the two looks
            else:
                _wait_gone(fr, pid, create_time=born)
            for line in log.flush():
                tracker.feed(line)
            break
    finally:
        with _LOCK:
            _job_runs.pop(job_id, None)

    def conclude() -> bool:
        if _is_cancelled(db, job_id):
            return False
        code = rc
        if (code is None and getattr(job, "mode", None) not in RENDER_MODES
                and _version_completed(db, vid)):
            # The version's own run: its process is gone with no exit code, yet the version is
            # complete -- a `resume` from the command line finished it while this run's record
            # still said running. (An export's version may have been complete before it started,
            # so for an export this says nothing.)
            _append_log(job_id, "The version was completed by another run (a resume).")
            code = 0
        if code in (0, 3):
            if code == 3:
                _append_log(job_id, "Some components' documents failed (see above); the others "
                                    "were made. Their state is on the Documents page's Components "
                                    "panel.")
            tracker.finish()
            return True
        if code is None:
            _append_log(job_id, "The run's process ended before it finished.")
            _fail_keeping_work(db, job_id, STOPPED_MESSAGE)
        else:
            tail = "\n".join(tracker.recent_lines[-20:])
            _append_log(job_id, f"Job failed with code {code}")
            _fail_keeping_work(db, job_id, _failure_message(code, tracker.recent_lines, tail))
        return False

    return _when_db_answers(job_id, "recording the run's end", conclude)


def _version_completed(db: Any, version_id: Optional[str]) -> bool:
    """Whether the version's pipeline is complete (`versions.pipeline_status`)."""
    eng = getattr(db, "_engine", None)
    if eng is None or not version_id:
        return False
    import sqlalchemy as sa
    from ..db.postgres import schema as s
    with eng.connect() as cx:
        return cx.execute(sa.select(s.versions.c.pipeline_status)
                          .where(s.versions.c.id == version_id)).scalar() == "complete"


def stop_background_run(job: Any) -> bool:
    """Stop the background run of `job` that no thread of this server follows (a server that
    stopped mid-run, before its run is followed again) -- before its version is removed, so the
    run does not go on writing into a deleted version. True when one was stopped."""
    fr = _frozen_run_module()
    vid = getattr(job, "version_id", None)
    if fr is None or not vid:
        return False
    run = fr.find_job_run(_data_root(), vid, job.id)
    if not run or fr.process_alive(run.get("pid"), run.get("create_time")) is False:
        return False
    fr.stop(run.get("pid"), run.get("create_time"))
    return True


def _version_has_work(db: Any, version_id: Optional[str]) -> bool:
    """Whether the version holds something a `resume` carries on from: a stored parse, or a
    pipeline that got past the parse. A run that stopped before that is started again instead."""
    eng = getattr(db, "_engine", None)
    if eng is None or not version_id:
        return False
    try:
        import sqlalchemy as sa
        from ..db.postgres import schema as s
        with eng.connect() as cx:
            if cx.execute(sa.select(sa.func.count()).select_from(s.parse_snapshots)
                          .where(s.parse_snapshots.c.version_id == version_id)).scalar():
                return True
            status = cx.execute(sa.select(s.versions.c.pipeline_status)
                                .where(s.versions.c.id == version_id)).scalar()
        return status in ("deriving", "viewing", "exporting", "complete")
    except Exception:                                    # noqa: BLE001 - see below
        # Cannot tell (the database did not answer): keep the version. Deleting a draft that
        # holds days of work is the one mistake that cannot be undone; keeping an empty one is.
        return True


def _fail_keeping_work(db: Any, job_id: str, message: str) -> None:
    """Fail the job; keep its version when there is work in it to resume (`_version_has_work`),
    else free it as `_mark_failed` does. Days of LLM work are not thrown away because the
    machine restarted."""
    job = db.jobs.get(job_id)
    if job is None:
        return
    if not _version_has_work(db, getattr(job, "version_id", None)):
        _mark_failed(db, job_id, message)
        return
    _log.error("job %s stopped: %s", job_id, message)
    if job.status not in ("cancelled", "complete", "failed"):
        job.status = "failed"
        job.error_message = f"{message}\n\n{_resume_hint(job)}"[:4000]
        job.completed_at = _now()
        db.jobs.update(job)


def _reattach_detached(db: Any, job: Any) -> bool:
    """At start-up: follow again the background run a stopped server was following for `job`
    (its run.json names the job). False when the job has none -- it ran as a child, or never got
    as far as starting one."""
    fr = _frozen_run_module()
    vid = getattr(job, "version_id", None)
    if fr is None or not vid:
        return False
    run = fr.find_job_run(_data_root(), vid, job.id)
    if run is None:
        return False
    render = getattr(job, "mode", None) in RENDER_MODES
    t = threading.Thread(target=_refollow, args=(db, job.id, run, render), daemon=True,
                         name=f"follow-{job.id}")
    if render:
        with _REEXPORT_LOCK:
            _reexport_threads[job.id] = t
    else:
        with _LOCK:
            _job_threads[job.id] = t
    print(f"[api] job {job.id}: its run goes on in the background (process {run.get('pid')}); "
          f"following it again", file=sys.stderr)
    t.start()
    return True


def _refollow(db: Any, job_id: str, run: dict, render: bool) -> None:
    """The thread of a job followed again after a restart: to the run's end, then the job's."""
    sem = _get_semaphore()
    slot = sem.acquire(blocking=False)      # the run goes on whether or not a slot is free
    try:
        _init_state(job_id)
        _append_log(job_id, "The API server restarted while this ran; following the "
                            "background run again.")
        job = db.jobs.get(job_id)
        phase = getattr(job, "phase", None) or (3 if render else 1)
        if _follow_detached(db, job_id, run, phase_start=phase, replay=True) \
                and not _is_cancelled(db, job_id):
            _when_db_answers(job_id, "finishing the job",
                             _complete_render if render else _complete, db, job_id)
    except Exception as exc:                             # noqa: BLE001 - recorded on the job
        _fail_keeping_work(db, job_id, f"Runner error: {exc}")
    finally:
        if slot:
            sem.release()
        try:
            job = db.jobs.get(job_id)
            if job is not None and job.status == "cancelled" and not render:
                _release_draft_version(db, job)
                _finish_if_it_finished(db, job)
        except Exception as exc:                         # noqa: BLE001 - cleanup only
            _log.warning("job %s: draft cleanup after cancel failed: %s", job_id, exc)
        _cleanup_state(job_id)
        if render:
            with _REEXPORT_LOCK:
                _reexport_threads.pop(job_id, None)


def _marker_phase(line: str) -> int:
    """The phase a `=== Phase N: ... ===` marker names, or 0 when the line is not a marker."""
    if "===" not in line:
        return 0
    for n in range(1, 5):
        if _PHASE_MARKERS[n] in line:
            return n
    return 0


def _detect_phase(line: str, current_phase: int) -> int:
    """Detect a phase start marker. Advances forward only — see `_marker_phase` for why.

    A run is one PLAN PER COMPONENT (`--component-per-docx`), and every plan emits its own
    Phase 3 and Phase 4 markers. The phase list shown in the UI is per RUN, not per plan, so
    letting it walk backwards would flip completed phases back to running on every component.

    The cost of that is a wrong LABEL: once plan 1 reaches Phase 4, plan 2's Phase-3 work —
    flowcharts, the most expensive thing in the pipeline — is reported as "Exporting". A run
    spending four minutes per component on flowchart LLM labels looked like four minutes of
    DOCX export. `_execute_subprocess` now takes the activity text from `_marker_phase`, which
    does not care about direction, so the label follows the real work.
    """
    n = _marker_phase(line)
    return n if n > current_phase else current_phase


def _stop_reasons(lines: list) -> list:
    """What the engine said it must stop for, before the parse - the `STOPPING BEFORE THE PARSE`
    block of its run summary (engine/incremental/report.py) - or [] when it did not stop there."""
    out: list = []
    inside = False
    for raw in lines:
        msg = _strip_log_prefix(raw)
        if msg.startswith("STOPPING BEFORE THE PARSE"):
            inside, out = True, []
        elif inside:
            if not msg.startswith("- "):
                break                               # the rule that closes the block
            out.append(msg[2:])
    return out


def _failure_message(rc: int, lines: list, tail: str) -> str:
    """The job's error: the engine's own reasons first when it stopped before the parse - the
    web app shows the first line as the headline, and "run.py exited with code 2" said nothing
    about a component path the checkout does not have."""
    reasons = _stop_reasons(lines)
    if not reasons:
        return f"run.py exited with code {rc}.\n{tail}"
    more = "".join(f"- {r}\n" for r in reasons[1:])
    return f"Stopped before the parse: {reasons[0]}\n{more}\n{tail}"


def _strip_log_prefix(line: str) -> str:
    """Strip [HH:MM:SS] LEVEL name: prefix, return the message part."""
    import re
    m = re.match(r"^\[[\d:]+\]\s+\w+\s+\S+:\s+(.*)", line)
    return m.group(1).strip() if m else line.strip()


def _transition_phase(db: Any, job_id: str, old_phase: int, new_phase: int,
                       old_phase_start: datetime) -> None:
    job = db.jobs.get(job_id)
    if not job:
        return
    elapsed = max(1, int((_now() - old_phase_start).total_seconds()))
    for p in job.phases:
        if p.number == old_phase:
            p.status = "done"
            p.duration_seconds = elapsed
        elif p.number == new_phase:
            p.status = "running"
    job.phase = new_phase
    job.phase_pct = 0
    job.current_activity = _ACTIVITY.get(new_phase, f"Phase {new_phase}…")
    job.elapsed_seconds = _elapsed_since(job.started_at)
    job.eta_seconds = max(0, (4 - new_phase) * 120)
    db.jobs.update(job)
    _append_log(job_id, f"→ Phase {new_phase}: {_ACTIVITY.get(new_phase, '')}")


def _set_activity(db: Any, job_id: str, activity: str) -> None:
    """Set the headline activity. Separate from `_update_activity`, which sets the DETAIL line."""
    job = db.jobs.get(job_id)
    if job and job.current_activity != activity:
        job.current_activity = activity
        db.jobs.update(job)


def _update_activity(db: Any, job_id: str, detail: str) -> None:
    job = db.jobs.get(job_id)
    if job:
        job.activity_detail = detail
        job.elapsed_seconds = _elapsed_since(job.started_at)
        _count_progress(job, detail)
        db.jobs.update(job)


# "[45/159] coreDoWhileClamp" -- a ProgressReporter step (engine/core/progress.py), logged every
# few items. The phase runner's own "[2/4] === Derive Model ===" and "[2/4] Derive Model — 12.3s"
# lines count phases, not items, and are skipped.
_ITEM_COUNTER = re.compile(r"^\[(\d+)/(\d+)\](?:\s+(.*))?$")
_step_clocks: dict = {}    # job_id -> (total, monotonic time first seen, done first seen)


def _count_progress(job: Any, detail: str) -> None:
    """Set the phase percentage and the time left from the engine's item counter.

    Nothing set `phase_pct`, so the web app's progress bar sat at 0% for a whole phase, and
    `eta_seconds` was only ever the transition guess of two minutes per remaining phase: "~4m
    remaining" for an LLM phase that takes an hour. The estimate is the rate seen so far in this
    counted step, plus that same guess for the phases still to come.
    """
    m = _ITEM_COUNTER.match(detail or "")
    if not m:
        return
    rest = m.group(3) or ""
    if rest.startswith("===") or " — " in rest:
        return
    done, total = int(m.group(1)), int(m.group(2))
    if total <= 0 or done > total:
        return
    now = time.monotonic()
    with _LOCK:
        clock = _step_clocks.get(job.id)
        if clock is None or clock[0] != total or done < clock[2]:     # a new counted step
            clock = (total, now, done)
            _step_clocks[job.id] = clock
    job.phase_pct = done * 100 // total
    _, t0, done0 = clock
    later = max(0, (4 - (job.phase or 4)) * 120)
    if done > done0:
        job.eta_seconds = int((now - t0) / (done - done0) * (total - done)) + later


_progress_warned: set = set()      # (job_id, function) pairs already logged -- see _progress


def _progress(job_id: str, fn, *args):
    """One bookkeeping call from the output loop -- it never stops the job.

    These run once per output line, and that loop is the only thing draining the child's pipe.
    An exception from one used to end the loop, after which `wait()` waited for a child blocked
    writing into the undrained pipe: the job hung at "running" for ever. That is how every job the
    API started on SQLite hung at its first line (`_elapsed_since` has the trigger). A lost
    progress line is cosmetic; a lost run is not.

    Returns what `fn` returned, or None when it raised -- which `_is_cancelled` reads as "not
    cancelled", the right default when the question could not be answered. Logged once per
    function per job, so a database that stays down cannot flood the log a line at a time.
    """
    try:
        return fn(*args)
    except Exception as exc:                                  # noqa: BLE001 - see docstring
        key = (job_id, getattr(fn, "__name__", repr(fn)))
        with _LOCK:
            first = key not in _progress_warned
            _progress_warned.add(key)
        if first:
            _log.warning("job %s: progress update %s failed (the run continues; further "
                         "failures of it are not logged): %s: %s",
                         job_id, key[1], type(exc).__name__, exc)
        return None


def _is_cancelled(db: Any, job_id: str) -> bool:
    job = db.jobs.get(job_id)
    return not job or job.status == "cancelled"


# ---------------------------------------------------------------------------
# Version snapshot — capture model/ + output/ for the compare engine (M3)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Completion — register Version + Documents
# ---------------------------------------------------------------------------

def _commit_dir(project_id: str, commit_sha: str) -> Path:
    """The per-commit dir workspaces/<pid>/<commit[:16]> — the git checkout, plus the manifest
    the incremental engine writes for that commit."""
    return get_settings().repo_root / "workspaces" / project_id / (commit_sha or "")[:16]


def _version_dir(project_id: str, version_id: Optional[str]) -> Optional[Path]:
    """workspaces/<pid>/versions/<ver…> — where the run captures its artifacts (08 step 3)."""
    if not version_id:
        return None
    return get_settings().repo_root / "workspaces" / project_id / "versions" / version_id


def _version_model_dir(project_id: str, commit_sha: str, version_id: Optional[str]) -> Optional[Path]:
    """The dir holding a version's model/*.json — the DISK fallback for ModelReader when the model
    isn't in Postgres. Prefers versions/<ver…>/model (what FileStore.write_model writes), falling
    back to the commit dir for versions produced under the older layout. None when neither exists."""
    vdir = _version_dir(project_id, version_id)
    if vdir is not None and (vdir / "model").is_dir():
        return vdir / "model"
    d = _commit_dir(project_id, commit_sha) / "model"
    return d if d.is_dir() else None


def _read_engine_manifest(project_id: str, commit_sha: str,
                          version_id: Optional[str] = None) -> dict:
    """The engine's run accounting — decision / baselineVersionId / regenerated / reused.

    From the `versions` row (doc 09, C1), so it is readable from any node rather than only the
    one that ran the job.

    There was a disk fallback here for versions written before that, reading the commit-dir
    manifest.json. Nothing writes that file any more, and the merge had the file OVERRIDE the
    database — so on a version that somehow had both, the stale copy won. Gone with the rest
    of the JSON persistence.
    """
    from_db: dict = {}
    if version_id:
        try:
            from incremental.model_store import load_run_outcome
            from core.db import get_engine
            with get_engine().connect() as cx:
                from_db = load_run_outcome(cx, version_id) or {}
        except Exception:                       # no DB / not migrated -> the file below
            from_db = {}

    return dict(from_db)


# _read_run_metadata was removed: the engine now writes the run's identity metadata straight onto
# the version row (store.write_run_metadata -> versions.base_path/project_name/parse_fingerprint),
# so the API no longer hunts for model/metadata.json on disk. _make_version just carries the
# columns through finalize.


# _sync_model_to_db was removed in the PG-7b cutover: it re-persisted the completed run's
# model/ dir into Postgres from the API side, but the engine already writes the model to the DB
# during the run (`PgStore.write_model`, engine.py/generate.py). Both were gated on the same
# condition — `_engine_db_env` only hands the engine a DATABASE_URL when the API is on the SQL
# backend — so the API-side sync was always a redundant second write of data already stored.


def _complete(db: Any, job_id: str, *, force: bool = False) -> None:
    """Finalise a finished run's job and version. `force`: a failed job too -- a version a
    `resume` from the command line finished (analyzer._finish_web_job)."""
    job = db.jobs.get(job_id)
    if not job or (job.status in ("cancelled", "failed") and not force):
        return

    now = _now()
    project = db.projects.get(job.project_id)
    # The engine wrote model/output + manifest INTO the commit dir and seeded the reuse index
    # itself — read the manifest for the incremental accounting; no separate capture/seed.
    manifest = _read_engine_manifest(job.project_id, job.commit_sha,
                                     getattr(job, "version_id", None))

    version = _make_version(db, project, job, now, manifest)
    docs = _make_documents(db, project, version, now)
    # Section seeding reads this version's rendered output — the version-keyed dir when the run
    # captured one, else the legacy commit dir (doc_render.commit_output_root resolves both).
    _out_root = doc_render.commit_output_root(job.project_id, job.commit_sha, version.id)
    _make_sections(db, docs, now, _out_root or (_commit_dir(job.project_id, job.commit_sha) / "output"))
    # Every document of the version: a run that registered some before (a CLI run inside the job,
    # a retried completion) has only the rest to add.
    from .review_workflow import version_docs as _version_docs
    version.docs_count = len(_version_docs(db, version))
    db.versions.update(version)

    # The engine already persisted the model to Postgres during the run (PgStore.write_model), so
    # this reads it straight back (falling back to the run's model/ dir when there is no DB).
    _load_and_register_functions(db, job, version.id)

    job.status = "complete"
    job.phase = 4
    job.phase_pct = 100
    job.current_activity = "Done"
    job.activity_detail = f"{version.docs_count} document(s) generated"
    job.eta_seconds = 0
    job.completed_at = now
    job.version_id = version.id
    job.elapsed_seconds = _elapsed_since(job.started_at, now)
    for p in job.phases:
        p.status = "done"
    db.jobs.update(job)

    if project:
        project.status = "in_review"
        project.updated_at = now
        db.projects.update(project)

    # Review and approval (REVIEW_APPROVE_API_SPEC §4): a document unchanged since the baseline
    # keeps its approval; the others start In review with the baseline's reviewer, who is told.
    # It never fails the run -- a document it could not judge stays In review, which is where
    # every document started before. The run itself has usually recorded and opened them already
    # (`analyzer.py generate` does at its end), so `docs` is empty here; the version's and the
    # project's status are derived again either way, as `_make_version` rewrote the row.
    if project:
        try:
            from .review_workflow import roll_up, start_review
            if docs:
                got = start_review(db, project, version, docs)
                if got["carried"]:
                    _append_log(job_id, f"{got['carried']} document(s) unchanged since the "
                                        f"baseline keep their approval.")
            roll_up(db, version)
        except Exception:                                   # noqa: BLE001 - see above
            _log.exception("opening the review of version %s failed", version.id)

    _append_log(job_id, f"Complete. Version {version.tag}, {version.docs_count} document(s).")


def _make_sections(db: Any, docs: list, now: datetime, output_dir: Path) -> None:
    """Seed DocumentSection records for every document created by _make_documents.
    `output_dir` is the version's commit-dir output (workspaces/<pid>/<commit[:16]>/output)."""
    from ..models.domain import DocumentSection


    for doc in docs:
        existing = db.documents.list_sections(doc.id)
        if existing:
            continue  # already has sections (e.g. re-export of an existing doc)

        if doc.process in ("SYS.2", "SWE.1"):
            sections = [
                DocumentSection(
                    id=f"sec{uuid.uuid4().hex[:8]}", document_id=doc.id,
                    section_key="intro", title="1. Introduction", order=1,
                    content=f"This document captures the {doc.subtitle} for {doc.name}.",
                    review_state=None, reviewed_by=None, reviewed_at=None,
                ),
            ]
        elif doc.process == "SWE.4":
            # The three numbered chapters of the SWE.4 DOCX (engine/swe4_exporter.py). The keys
            # are the ids the page gives those chapters, so the review tracker can jump to them.
            sections = [
                DocumentSection(
                    id=f"sec{uuid.uuid4().hex[:8]}", document_id=doc.id,
                    section_key=key, title=title, order=order, content=content,
                    review_state=None, reviewed_by=None, reviewed_at=None,
                )
                for order, (key, title, content) in enumerate((
                    ("intro", "1. Introduction",
                     f"Purpose and scope of the unit tests of '{doc.name}', and the terms used."),
                    ("test_spec", "2. Unit Test Specification",
                     "Per function: precondition, inputs, test steps along its control flow and "
                     "the expected results, with the test case metadata."),
                    ("metrics", "3. Code Metric, Coding Rule, Test Coverage",
                     "Code metrics, coding-rule compliance and test-coverage results."),
                ), start=1)
            ]
        else:
            # SWE.2 / SWE.3 — read unit count from interface_tables.json
            n_units, n_comps = 0, 1
            group_dir = output_dir / doc.group if doc.group else None
            if group_dir and group_dir.is_dir():
                itf_path = group_dir / "interface_tables.json"
                if itf_path.exists():
                    try:
                        itf = json.loads(itf_path.read_text(encoding="utf-8"))
                        unit_names = itf.get("unitNames", {}) or {}
                        n_units = len(unit_names)
                        comps: dict = {}
                        for uk in unit_names:
                            comps.setdefault(uk.split("|", 1)[0], []).append(uk)
                        n_comps = max(len(comps), 1)
                    except Exception:
                        pass

            sections = [
                DocumentSection(
                    id=f"sec{uuid.uuid4().hex[:8]}", document_id=doc.id,
                    section_key="intro", title="1. Introduction", order=1,
                    content=(
                        f"This {doc.subtitle} describes the '{doc.name}' software component, "
                        f"covering {n_units} unit(s) across {n_comps} component(s). "
                        f"Interfaces, static structure and control-flow are derived from "
                        f"the Clang AST analysis."
                    ),
                    review_state=None, reviewed_by=None, reviewed_at=None,
                ),
                DocumentSection(
                    id=f"sec{uuid.uuid4().hex[:8]}", document_id=doc.id,
                    section_key="interfaces", title="2. Interfaces", order=2,
                    content="Interface table derived from the pipeline analysis.",
                    review_state=None, reviewed_by=None, reviewed_at=None,
                ),
                DocumentSection(
                    id=f"sec{uuid.uuid4().hex[:8]}", document_id=doc.id,
                    section_key="static_design", title="3. Static Design", order=3,
                    content="Component structure and include-dependency graph derived from Clang AST.",
                    review_state=None, reviewed_by=None, reviewed_at=None,
                ),
                DocumentSection(
                    id=f"sec{uuid.uuid4().hex[:8]}", document_id=doc.id,
                    section_key="dynamic_design", title="4. Dynamic Design", order=4,
                    content="Control-flow graphs (CFGs) for each function, derived from the Clang AST.",
                    review_state=None, reviewed_by=None, reviewed_at=None,
                ),
            ]

        for sec in sections:
            db.documents.update_section(sec)


def _make_version(db: Any, project: Any, job: Any, now: datetime, manifest: dict = None) -> Version:
    manifest = manifest or {}
    # Version identity (D-3): use the caller-supplied version verbatim. It was validated
    # required + unique at job start (400/409), so there is no fallback name and no
    # silent "-1" rename here.
    tag = (getattr(job, "version_tag", None) or "").strip()
    # Use the id reserved at job start (PG-3) so the row matches the identity the engine ran
    # under; fall back to a fresh id only for callers that didn't reserve one.
    vid = getattr(job, "version_id", None) or f"ver{uuid.uuid4().hex[:8]}"
    reserved = db.versions.get(vid) if getattr(job, "version_id", None) else None
    version = Version(
        id=vid,
        project_id=project.id,
        tag=tag,
        commit_sha=job.commit_sha,
        branch=job.branch,
        description="Generated by analysis run",
        status="in_review",
        docs_count=0,
        created_by=(project.created_by if project else "system"),
        created_at=(reserved.created_at if reserved else now),
        # Incremental accounting comes from the engine's manifest (baselineVersionId is now the
        # baseline's real ver id — 08 step 2b).
        baseline_version_id=manifest.get("baselineVersionId"),
        decision=manifest.get("decision") or getattr(job, "decision", None),
        regenerated=manifest.get("regenerated"),
        reused=manifest.get("reused"),
        # Carry the per-version config stored at job start through finalize — _put replaces the
        # whole row, so rebuilding the Version without it would null versions.resolved_config.
        resolved_config=(reserved.resolved_config if reserved else None),
        # Run metadata (was model/metadata.json) is written straight onto the version row by the
        # engine via store.write_run_metadata, so carry it through finalize — _put replaces the
        # whole row and would otherwise null the columns the engine just filled.
        base_path=(reserved.base_path if reserved else None),
        project_name=(reserved.project_name if reserved else None),
        parse_fingerprint=(reserved.parse_fingerprint if reserved else None),
    )
    # Finalize the row reserved at job start; create it if this flow didn't reserve one.
    if reserved is not None:
        db.versions.update(version)
    else:
        db.versions.create(version)
    return version


def _make_documents(db: Any, project: Any, version: Version, now: datetime) -> list[Document]:
    """Create one Document per *real* generated DOCX in this version's output/ that is not
    recorded yet, and return the new ones.

    Runs are generated **per component**, so the pipeline writes
    ``output/<id>/software_detailed_design_<id>.docx`` (and the SWE.4 beside it), where ``<id>``
    is the component's layer-qualified id (``Layer1.Sample-Core``). Which component a dir is, and
    the idempotence that lets a CLI run, a re-export and `analyzer.py register` all call this,
    live in `services/document_registry.py` (`new_documents`)."""
    from .document_registry import new_documents
    return new_documents(db, project, version, now)


# ---------------------------------------------------------------------------
# Functions loader — reads model/functions.json and registers under the job
# ---------------------------------------------------------------------------

def _resolve_ref_commit(db: Any, version_id: Optional[str]) -> Optional[str]:
    """Translate an API Version.id ('ver…') to its commit sha.

    The incremental engine's version namespace is commit[:16] (see
    incremental/project_db.list_versions), not the API's 'ver…' ids, so callers
    must translate before passing --base-version-id or resolving a per-commit dir.
    Returns None if unset/unknown (→ auto baseline)."""
    if not version_id:
        return None
    v = db.versions.get(version_id)
    return v.commit_sha if v else None


def _baseline_fn_keys(db: Any, project_id: str, reference_commit: Optional[str],
                      reference_version_id: Optional[str] = None) -> Optional[Set[str]]:
    """The set of function dict-keys from the baseline's model — Postgres-first (by version id),
    falling back to the baseline's model/functions.json on disk. None when neither has it."""
    model_dir = _version_model_dir(project_id, reference_commit or "", reference_version_id)
    raw = ModelReader(db, reference_version_id, model_dir).load("functions")
    return set(raw.keys()) if isinstance(raw, dict) and raw else None


def _load_and_register_functions(db: Any, job: Any, version_id: str) -> None:
    """Register this version's functions in the DB under the job's id.

    The model is read Postgres-first for `version_id` (the run persisted it via PgStore /
    PgStore.write_model during the run), falling back to this version's model/functions.json."""
    from ..models.domain import Function

    model_dir = _version_model_dir(job.project_id, job.commit_sha, version_id)
    raw = ModelReader(db, version_id, model_dir).load("functions")
    if not isinstance(raw, dict) or not raw:
        return

    ref_keys: Optional[Set[str]] = None
    if getattr(job, "reference_version_id", None):
        # reference_version_id is an API Version.id; the disk fallback keys by commit sha, so
        # translate for it while the DB path uses the version id directly.
        ref_commit = _resolve_ref_commit(db, job.reference_version_id)
        ref_keys = _baseline_fn_keys(db, job.project_id, ref_commit, job.reference_version_id)

    functions: list[Function] = []
    for fn_key, fn_data in raw.items():
        if not isinstance(fn_data, dict):
            continue
        fn_name = fn_data.get("name") or fn_key.split("::")[-1]
        file_path = fn_data.get("file", fn_data.get("filePath", ""))
        layer = fn_data.get("layer", fn_data.get("layerName", ""))
        group = fn_data.get("componentName", fn_data.get("group", ""))
        description = fn_data.get("description", "")
        is_visible = bool(fn_data.get("isVisible", fn_data.get("is_visible", True)))
        fn_id = fn_data.get("id") or str(uuid.uuid4())
        is_new = (fn_key not in ref_keys) if ref_keys is not None else False

        functions.append(Function(
            id=fn_id,
            project_id=job.project_id,
            version_id=version_id,
            name=fn_name,
            file_path=file_path,
            layer=layer,
            group=group,
            is_visible=is_visible,
            is_new=is_new,
            description=description,
        ))

    if hasattr(db.functions, "load_from_pipeline"):
        db.functions.load_from_pipeline({job.id: functions})


# ---------------------------------------------------------------------------
# Re-export
# ---------------------------------------------------------------------------

def _capture_reexport_output(db: Any, job: Any, adir) -> None:
    """Persist a re-export's freshly rendered output back into the store.

    Generation reaches this through the incremental orchestrator's `store.capture_output`;
    re-export bypasses that orchestrator entirely, so without this the run rewrites files and
    nothing else. That is invisible while documents render from disk, and wrong the moment
    they render from Postgres (C0) — the stored views stay at the previous render and the
    re-export looks like it did nothing.

    Best-effort: the .docx has already been produced on disk at this point, so a store hiccup
    must not fail an otherwise successful job.
    """
    version_id = getattr(job, "version_id", None)
    if not version_id:
        return                       # legacy commit-keyed run: nothing version-scoped to update
    try:
        import sys as _sys
        engine_dir = str(get_settings().repo_root / "engine")
        if engine_dir not in _sys.path:
            _sys.path.insert(0, engine_dir)
        from incremental.store import make_store          # type: ignore[import]
        store = make_store(job.project_id,
                           workspaces_root=str(get_settings().repo_root / "workspaces"))
        store.capture_output(version_id, str(adir / "output"))
    except Exception as exc:                              # pragma: no cover - never fail here
        _log.warning("re-export: could not persist rendered output for %s: %s", version_id, exc)


def export_doc_type(db: Any, project_id: str, version_id: Optional[str]) -> str:
    """What exporting this version writes: `all` when a run made its SWE.4 documents, else `swe3`.

    A web run makes both (`--doc-type all`, `_generate_cmd`). A version generated before that
    has SWE.3 alone, and asking run.py for SWE.4 there would export specs that were never built.
    The re-export (`_do_reexport`) and R9 (`text_overrides.export_readiness`) ask the same
    question, so this answers both.
    """
    if not version_id:
        return "swe3"
    try:
        _docs, total = db.documents.list_for_project(project_id, version_id=version_id,
                                                     process="SWE.4", per_page=1)
    except Exception:                                  # noqa: BLE001 - SWE.3 alone, as before
        return "swe3"
    return "all" if total else "swe3"


def _reexport_from_phase(version_id: Optional[str], doc_type: str = "swe3") -> int:
    """4 normally; 3 when a reviewer's correction is newer than the last derivation.

    `REQ-AP-04` says an export must verify rather than assume. The CLI answers by refusing and
    printing how to re-derive. A refusal is the wrong answer HERE: the person at the other end is
    a reviewer who pressed "re-export" seconds after correcting a sentence, and "phase 3" is not
    a thing they should have to know. So the remedy is applied instead of being recommended.

    Phase 3 is not an approximation of the fix — it IS the fix the guard's message names. It
    re-derives the view rows from the model with the corrections applied, and `capture_output`
    draws the flowchart pictures that were owed on the way through. It costs seconds on a small
    project and minutes on a large one; shipping a document whose text and diagrams disagree
    costs more than that.

    Falls back to 4 whenever the question cannot be asked — no version, no database, the feature
    absent, or the guard itself failing. An unavailable guard must not turn into a changed
    pipeline: that would be a second, silent behaviour nobody asked for.
    """
    if not version_id:
        return 4
    try:
        engine_dir = str(get_settings().repo_root / "engine")
        if engine_dir not in sys.path:
            sys.path.insert(0, engine_dir)
        from core.db import get_engine, is_database_configured     # type: ignore[import]
        if not is_database_configured():
            return 4
        from review.export_guard import staleness                  # type: ignore[import]
        with get_engine().connect() as cx:
            # Asked about what this re-export writes (`export_doc_type`): SWE.3, and SWE.4 when
            # the version has it -- a node-label correction re-derives the SWE.4 specs at save
            # time, so that document is behind as well.
            st = staleness(cx, version_id, doc_type)
    except Exception as exc:                                       # noqa: BLE001 - see docstring
        _log.warning("re-export: could not check whether %s is up to date (%s); "
                     "exporting without re-deriving", version_id, exc)
        return 4
    if not st.is_stale:
        return 4
    _log.info("re-export: %s has corrections newer than its last derivation (%s), so this run "
              "re-derives the views first (phase 3) instead of exporting the previous text",
              version_id, st.explain())
    return 3


def _do_reexport(db: Any, job_id: str) -> bool:
    """Re-render and re-export one version, as re-export job `job_id`. True when it succeeded.

    Every failure is recorded on the job (`_mark_failed`) before False comes back; the caller
    marks success.
    """
    job = db.jobs.get(job_id)
    if not job:
        return False
    project = db.projects.get(job.project_id)
    if not project:
        _mark_failed(db, job_id, f"Project {job.project_id} not found.")
        return False
    if _detach_enabled(db):
        # In the background, as `analyzer.py reexport`: it restores the source, takes the
        # version's writer lock, and stores and records what it makes. Re-exporting every
        # document of a large version takes hours, and as a child of this server it died with
        # every restart.
        doc_type = export_doc_type(db, job.project_id, job.version_id)
        return _reexport_detached(db, job_id, _reexport_from_phase(job.version_id, doc_type),
                                  doc_type)

    root = get_settings().repo_root
    version_id = getattr(job, "version_id", None)
    cdir = _commit_dir(job.project_id, job.commit_sha)   # the git CHECKOUT (run.py's project dir)
    if version_id:
        # Found wherever it actually is, and restored from the project's repository when it is
        # nowhere -- the same resolver `analyzer.py reexport` uses, so the two front doors
        # cannot disagree about whether a version can be re-exported. Phase 3 reads the SOURCE
        # (flowcharts, line numbers), so without this a re-export failed on any host that had
        # not generated the version itself: a second working copy, a cleaned workspace, a
        # short-SHA folder name.
        try:
            engine_dir = str(root / "engine")
            if engine_dir not in sys.path:
                sys.path.insert(0, engine_dir)
            from incremental.source_checkout import SourceUnavailable, locate_or_restore
            cdir = Path(locate_or_restore(job.project_id, version_id).path)
        except SourceUnavailable as exc:
            _mark_failed(db, job_id, str(exc))
            return False
    # This version's ARTIFACTS (model/output) — the version-keyed dir when the run captured one,
    # else the legacy commit dir. Kept distinct from the checkout above: run.py parses source from
    # the checkout, while model/output are per-version.
    #
    # The model itself is ROWS. This used to refuse unless `<adir>/model/` existed on disk --
    # the same filesystem check run.py dropped because it "refused a perfectly good stored
    # model". A host that did not generate the version has no such folder and every re-export
    # failed as "generate this version first". run.py's `--use-model` asks the repository and
    # exits 2 with a clear message when the model really is missing.
    adir = _version_dir(job.project_id, version_id)
    if adir is None:
        adir = cdir
    # THIS version's own folders -- created if a host that did not generate it has none. Never
    # the shared <repo>/model or <repo>/output, and nothing is deleted or copied: that staging
    # step is what test_reexport_isolation guards against, and this is not it.
    (adir / "model").mkdir(parents=True, exist_ok=True)
    (adir / "output").mkdir(parents=True, exist_ok=True)

    workspace_dir = root / "workspaces" / job.project_id
    config_path = workspace_dir / "config.json"
    if not config_path.is_file():
        try:
            config_path, _ = _write_project_config(project, workspace_dir)
        except Exception as exc:
            _mark_failed(db, job_id, f"Config generation failed: {exc}")
            return False

    # Re-export = run.py Phase 4 (--use-model), run IN PLACE against this version's own
    # model/ and output/.
    #
    # It used to stage them into the SHARED <repo>/model and <repo>/output, rmtree-ing those
    # first — the exact concurrency hazard B1 removed from the generation path, still alive
    # here: two jobs re-exporting at once would wipe each other's staged trees mid-run, and a
    # re-export would wipe a *generation* that was using the shared dirs. Running in place
    # also drops two full copies of the model and output per re-export.
    # REQ-AP-04. Phase 4 alone would ship whatever Phase 3 produced last time. When a reviewer
    # has corrected something since, the honest choices are to refuse or to re-derive — and the
    # guard's own message already names re-deriving as the remedy, so do that instead of handing
    # a reviewer a failed job and an explanation of pipeline phases.
    #
    # Phase 3 is exactly that remedy: it rebuilds the view rows from the model with the
    # corrections applied, and draws the flowchart pictures that were owed on the way through.
    #
    # Both documents of a version that has both: a web run writes SWE.4 beside SWE.3, and a
    # re-export that rewrote only SWE.3 left the SWE.4 Word file with the old labels.
    doc_type = export_doc_type(db, job.project_id, getattr(job, "version_id", None))
    from_phase = _reexport_from_phase(getattr(job, "version_id", None), doc_type)

    arch_layers = project.architecture_layers or []
    # The model is rows, so Phase 4 needs the version id to find it. This used to ASK whether
    # the model was persisted and pass the id only if so, because a version generated before
    # the DB-native work had files instead. There is no file model any more: a version whose
    # rows are missing cannot be re-exported at all, and saying so beats re-exporting nothing.
    cmd = _build_cmd(job, cdir, config_path, from_phase=from_phase, use_model=True,
                     arch_layers=arch_layers,
                     model_root=adir / "model", output_root=adir / "output",
                     version_id=getattr(job, "version_id", None), doc_type=doc_type)
    if from_phase > 3:
        # Nothing to re-derive: say so on the job rather than leave phase 3 "pending" for ever.
        job = db.jobs.get(job_id)
        for p in job.phases:
            if p.number < from_phase and p.status == "pending":
                p.status = "skipped"
        db.jobs.update(job)
    if not _execute_subprocess(db, job_id, cmd, phase_start=from_phase):
        return False
    # Re-persist the re-rendered views (C0). The document render now reads interface
    # tables / flowcharts / behaviour rows from Postgres when they are there, so a
    # re-export that only rewrote FILES would leave the stored copies stale and appear to
    # have had no effect. capture_output also re-collects the .docx into documents/.
    _capture_reexport_output(db, job, adir)
    return True


def _reexport_detached(db: Any, job_id: str, first_phase: int, doc_type: str) -> bool:
    """A web re-export as `analyzer.py reexport --detach`, followed like a run: the documents of
    the job's scope, from `first_phase` (3 when a correction is newer than the views, else 4 --
    `_reexport_from_phase`), of `doc_type`. Same answer as `_do_reexport`."""
    job = db.jobs.get(job_id)
    scope = job.scope or {}
    # Export only was judged when the job was made; a correction saved while it waited for its
    # turn would make the process refuse. `auto` makes the views again instead.
    cmd = [sys.executable, str(get_settings().repo_root / "analyzer.py"), "reexport",
           "--project-id", job.project_id, "--version-id", job.version_id,
           "--from-phase", "auto" if first_phase >= 4 else str(first_phase),
           "--doc-type", doc_type]
    names = scope.get("names") or []
    if scope.get("type") == "component" and names:
        cmd += ["--components", ",".join(names)]
    elif scope.get("type") not in (None, "project"):
        cmd += ["--scope", _scope_to_cli(scope)]
    if first_phase > 3:
        # Nothing to re-derive: say so on the job rather than leave phase 3 "pending" for ever.
        for p in job.phases:
            if p.number < first_phase and p.status == "pending":
                p.status = "skipped"
        db.jobs.update(job)
    return _execute_detached(db, job_id, cmd, phase_start=first_phase,
                             extra_env=_engine_db_env(db))


def _reexport_scope(db: Any, version: Any, generation_scope: Optional[dict]) -> Optional[dict]:
    """Every component the version has documents for, whichever run made them -- `analyzer.py
    reexport`'s default too. The generation's scope when its documents are not per component (an
    old group-scoped run) or the view cannot be read."""
    try:
        from .version_components import components_view, default_reexport
        names = default_reexport(components_view(db, version))
        if names:
            return {"type": "component", "names": names}
    except Exception as exc:                          # noqa: BLE001 - the old scope still works
        _log.warning("re-export of %s: its components could not be read (%s); using the "
                     "generation's scope", getattr(version, "id", "?"), exc)
    return generation_scope


def start_export(db: Any, version: Any, components: list, *,
                 added_layers: Optional[list] = None) -> AnalysisJob:
    """Make the documents of `components` -- not generated yet -- into `version`, as a job of its
    own (`mode: "export"`, phases 3 and 4), and return it.

    The job runs `analyzer.py export`, the same command as the CLI: Phases 3-4 from the version's
    stored model, the output stored, the documents recorded for review. `added_layers`: layers
    the model lacks that some of `components` are of -- the same command adds them first (the
    parse again with them, the model derived again keeping its descriptions), so the job's
    phases are 1-4 and it says so in its activity. That process takes the
    version's writer lock itself, so this thread does not. One at a time per version, like a
    re-export; refused while any other process writes the version. The caller has checked the
    components (`version_components`): each is of the version's model and has no documents yet.

    Raises ReexportRefused.
    """
    with _REEXPORT_LOCK:
        busy = version_writer_busy(db, version.id)
        if busy:
            raise ReexportRefused(
                409, "VERSION_BUSY",
                f"Version '{version.id}' is being written by {busy}. Wait for it to finish.")
        jobs = db.jobs.list_for_version(version.id)
        running = next((j for j in jobs if getattr(j, "mode", None) in RENDER_MODES
                        and j.status in _REEXPORT_ACTIVE), None)
        if running is not None and _reexport_alive(running.id):
            raise ReexportRefused(
                409, "EXPORT_RUNNING",
                f"Version '{version.id}' is already being rendered by job {running.id}. Follow "
                f"that job, then add these.", running.id)
        # The version's own run, alive in this server: on SQLite there is no lock to say so, and
        # a resumed run holds none for the moment before it starts. Whichever stored last would
        # replace the other's documents.
        own = next((j for j in jobs if j.status in ("queued", "running", "paused")
                    and job_alive(j.id)), None)
        if own is not None:
            raise ReexportRefused(
                409, "RUN_ACTIVE",
                f"Job {own.id} is at work on version '{version.id}'. Follow that job, then add "
                f"these.", own.id)
        generation = next((j for j in jobs if getattr(j, "mode", None) not in RENDER_MODES), None)
        added = list(added_layers or [])
        first = 1 if added else 3
        scope: dict = {"type": "component", "names": list(components)}
        if added:
            scope["added_layers"] = added
        job = AnalysisJob(
            id=f"job{uuid.uuid4().hex[:8]}", project_id=version.project_id,
            commit_sha=version.commit_sha or (generation.commit_sha if generation else ""),
            version_id=version.id, reference_version_id=None, status="queued",
            pause_after_phase1=False, layer_filter=None, phase=first, phase_pct=0,
            current_activity="Queued — waiting for worker…", activity_detail="",
            elapsed_seconds=0, eta_seconds=None,
            phases=[AnalysisPhase(n, name, "pending", None) for n, name in _PHASES if n >= first],
            started_at=_now(), completed_at=None, error_message=None,
            branch=(generation.branch if generation else None) or version.branch or "main",
            version_tag=version.tag, mode=EXPORT_MODE, scope=scope)
        db.jobs.create(job)
        t = threading.Thread(target=_run_export, args=(db, job.id), daemon=True,
                             name=f"export-{job.id}")
        _reexport_threads[job.id] = t
        t.start()
    return job


def _run_export(db: Any, job_id: str) -> None:
    """The export job's thread: `analyzer.py export` as its subprocess, followed like a run."""
    try:
        _init_state(job_id)
        job = db.jobs.get(job_id)
        if not job or job.status == "cancelled":
            return
        job.status = "running"
        added = (job.scope or {}).get("added_layers") or []
        job.current_activity = _export_activity(added)
        db.jobs.update(job)
        names = (job.scope or {}).get("names") or []
        cmd = [sys.executable, str(get_settings().repo_root / "analyzer.py"), "export",
               "--project-id", job.project_id, "--version-id", job.version_id,
               "--components", ",".join(names)]
        # In the background when it can be: making 33 components' documents takes a day too.
        # A layer to add: `export` parses and derives it first (Phases 1-2), then the documents.
        if (_run_engine_command(db, job_id, cmd, phase_start=1 if added else 3,
                                extra_env=_engine_db_env(db))
                and not _is_cancelled(db, job_id)):
            _when_db_answers(job_id, "finishing the job", _complete_render, db, job_id)
    except Exception as exc:                  # noqa: BLE001 - recorded on the job, not lost
        _fail_keeping_work(db, job_id, f"Export error: {exc}")
    finally:
        _cleanup_state(job_id)
        with _REEXPORT_LOCK:
            _reexport_threads.pop(job_id, None)


def _export_activity(added_layers: list) -> str:
    """An export job's headline while it runs: what it does first."""
    if not added_layers:
        return "Making the documents…"
    s = "s" if len(added_layers) > 1 else ""
    return (f"Adding layer{s} {', '.join(added_layers)} (parse + model), then making the "
            f"documents…")


def _complete_render(db: Any, job_id: str) -> None:
    """The end of an export, resume or re-export job: complete, saying what it made."""
    _complete_reexport(db, job_id)
    done = db.jobs.get(job_id)
    if getattr(done, "mode", None) == REEXPORT_MODE:
        return                                           # "Re-exported", as _complete_reexport says
    names = (done.scope or {}).get("names") or []
    added = (done.scope or {}).get("added_layers") or []
    done.activity_detail = (f"Generated {len(names)} component(s)" if names
                            else "Resumed: the version is complete")
    if names and added:
        done.activity_detail += (f"; added layer{'s' if len(added) > 1 else ''} "
                                 f"{', '.join(added)}")
    db.jobs.update(done)


class ResumeRefused(ReexportRefused):
    """Why a version cannot be resumed now (HTTP status, code, message)."""


def start_resume(db: Any, version: Any) -> AnalysisJob:
    """Carry on a version whose run stopped before it finished, from the web app: `analyzer.py
    resume`, in the background, followed as a job (staged generation, C4).

    The version's own generation job is reopened when it did not finish -- a web run that
    stopped -- so its end finalises the version as a run's end does (`_complete`). Otherwise
    (a version made from the command line, or one complete apart from some components) the
    resume is a job of its own, like an export. What it does is `resume`'s to decide: the parse
    again, Phase 2 from the stored parse, the unfinished components, or only the closing steps.

    Raises ResumeRefused: VERSION_BUSY (a writer holds the version), RUN_ACTIVE (a job of this
    server is at work on it), NOTHING_TO_RESUME, NO_BACKGROUND_RUNS (no database behind the API).
    """
    if not _detach_enabled(db):
        raise ResumeRefused(409, "NO_BACKGROUND_RUNS",
                            "Resuming needs the API on a database. Resume on the server: "
                            f"python analyzer.py resume --project-id {version.project_id} "
                            f"--version-id {version.id} --detach")
    with _REEXPORT_LOCK:
        busy = version_writer_busy(db, version.id)
        if busy:
            raise ResumeRefused(409, "VERSION_BUSY",
                                f"Version '{version.id}' is being written by {busy}: it has not "
                                f"stopped. Follow it on the Components panel.")
        jobs = db.jobs.list_for_version(version.id)
        active = next((j for j in jobs if j.status in ("queued", "running", "paused")
                       and (job_alive(j.id) or _reexport_alive(j.id))), None)
        if active is not None:
            raise ResumeRefused(409, "RUN_ACTIVE",
                                f"Job {active.id} is at work on version '{version.id}'. Follow "
                                f"that job.", active.id)
        from .version_components import resume_action
        action = resume_action(db, version)
        if action == "busy":
            raise ResumeRefused(409, "VERSION_BUSY",
                                f"Version '{version.id}' is being written: it has not stopped.")
        if action == "nothing":
            raise ResumeRefused(409, "NOTHING_TO_RESUME",
                                f"Version '{version.id}' is complete: nothing was cut short. "
                                f"Components it has not generated are added with Generate.")
        generation = next((j for j in jobs if getattr(j, "mode", None) not in RENDER_MODES), None)
        first = {"regenerate": 1, "derive": 2}.get(action, 3)
        if generation is not None and generation.status != "complete":
            job, render = generation, False
            job.status = "queued"
            job.error_message = None
            job.completed_at = None
            # Started again: the checks for unfollowed jobs leave a job alone for its first
            # minutes, and they read this (and "the project's run" is the newest).
            job.started_at = _now()
            job.current_activity = "Resuming…"
            for p in job.phases:
                if p.number >= first and p.status != "done":
                    p.status = "pending"
            db.jobs.update(job)
        else:
            render = True
            job = AnalysisJob(
                id=f"job{uuid.uuid4().hex[:8]}", project_id=version.project_id,
                commit_sha=version.commit_sha or (generation.commit_sha if generation else ""),
                version_id=version.id, reference_version_id=None, status="queued",
                pause_after_phase1=False, layer_filter=None, phase=first, phase_pct=0,
                current_activity="Resuming…", activity_detail="",
                elapsed_seconds=0, eta_seconds=None,
                phases=[AnalysisPhase(n, name, "pending", None) for n, name in _PHASES
                        if n >= first],
                started_at=_now(), completed_at=None, error_message=None,
                branch=(generation.branch if generation else None) or version.branch or "main",
                version_tag=version.tag, mode=EXPORT_MODE, scope=None)
            db.jobs.create(job)
        t = threading.Thread(target=_run_resume, args=(db, job.id, render, first), daemon=True,
                             name=f"resume-{job.id}")
        if render:
            _reexport_threads[job.id] = t
        else:
            with _LOCK:
                _job_threads[job.id] = t
        t.start()
    return job


def _run_resume(db: Any, job_id: str, render: bool, first_phase: int) -> None:
    """The resume job's thread: `analyzer.py resume` in the background, followed to its end."""
    try:
        _init_state(job_id)
        job = db.jobs.get(job_id)
        if not job or job.status == "cancelled":
            return
        job.status = "running"
        db.jobs.update(job)
        cmd = [sys.executable, str(get_settings().repo_root / "analyzer.py"), "resume",
               "--project-id", job.project_id, "--version-id", job.version_id]
        if (_execute_detached(db, job_id, cmd, phase_start=first_phase,
                              extra_env=_engine_db_env(db))
                and not _is_cancelled(db, job_id)):
            _when_db_answers(job_id, "finishing the job",
                             _complete_render if render else _complete, db, job_id)
    except Exception as exc:                  # noqa: BLE001 - recorded on the job, not lost
        _fail_keeping_work(db, job_id, f"Resume error: {exc}")
    finally:
        try:
            job = db.jobs.get(job_id)
            if job is not None and job.status == "cancelled" and not render:
                _release_draft_version(db, job)
                _finish_if_it_finished(db, job)
        except Exception as exc:              # noqa: BLE001 - cleanup only
            _log.warning("job %s: draft cleanup after cancel failed: %s", job_id, exc)
        _cleanup_state(job_id)
        if render:
            with _REEXPORT_LOCK:
                _reexport_threads.pop(job_id, None)


def _run_reexport(db: Any, job_id: str) -> None:
    """The re-export job's thread: queued -> running -> complete | failed, as a generation does."""
    try:
        _init_state(job_id)                  # the log buffer the live stream reads
        job = db.jobs.get(job_id)
        if not job or job.status == "cancelled":
            return
        job.status = "running"
        job.current_activity = "Preparing re-export…"
        db.jobs.update(job)
        # In the background the re-export's own process takes the version's writer lock, as a web
        # run's generate does: holding it here as well would refuse that process.
        import contextlib
        writer = (contextlib.nullcontext() if _detach_enabled(db)
                  else _version_writer(db, job.version_id, "web reexport"))
        with writer:
            if _do_reexport(db, job_id) and not _is_cancelled(db, job_id):
                _register_missing_documents(db, job_id)
                _when_db_answers(job_id, "finishing the job", _complete_reexport, db, job_id)
    except Exception as exc:                  # noqa: BLE001 - recorded on the job, not lost
        _mark_failed(db, job_id, f"Re-export error: {exc}")
    finally:
        _cleanup_state(job_id)
        with _REEXPORT_LOCK:
            _reexport_threads.pop(job_id, None)


def _register_missing_documents(db: Any, job_id: str) -> int:
    """Register the documents of a re-exported version that are not recorded yet, and open their
    review. Returns how many.

    A version generated from the CLI, or while `_make_documents` matched output dirs by the bare
    component name, has its DOCX files on disk and no `documents` rows; re-exporting it is one way
    it gets its document list. Registration is idempotent (`document_registry`), so a version
    whose documents are all recorded is left exactly as it is.

    Best-effort: the re-export has succeeded by now, and its job must not fail over this.
    """
    try:
        job = db.jobs.get(job_id)
        version_id = getattr(job, "version_id", None) if job else None
        version = db.versions.get(version_id) if version_id else None
        project = db.projects.get(job.project_id) if version else None
        if version is None or project is None:
            return 0
        from .document_registry import register_documents
        docs = register_documents(db, project, version, now=_now())
        if docs:
            _append_log(job_id, f"Registered {len(docs)} document(s) this version was missing.")
        return len(docs)
    except Exception as exc:                  # noqa: BLE001 - see docstring
        _log.warning("re-export %s: could not register the version's documents: %s", job_id, exc)
        return 0


def _complete_reexport(db: Any, job_id: str) -> None:
    now = _now()
    job = db.jobs.get(job_id)
    job.status = "complete"
    job.phase = 4
    job.phase_pct = 100
    job.current_activity = "Done"
    job.activity_detail = "Re-exported"
    job.eta_seconds = 0
    job.completed_at = now
    job.elapsed_seconds = _elapsed_since(job.started_at, now)
    for p in job.phases:
        if p.status in ("pending", "running"):
            p.status = "done"
    db.jobs.update(job)
