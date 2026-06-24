"""
Pipeline executor — spawns ``run.py`` as a subprocess and tracks progress
by tailing its log output.

Architecture
------------
``PipelineExecutor`` is a module-level singleton.  When a route calls
``executor.start(job_id, ...)``, the executor:

1. Builds the ``run.py`` argv list from the job parameters.
2. Spawns the process with stdout+stderr merged into a per-job log file
   under ``api/db/jobs/<job_id>.log``.
3. Starts a background daemon thread (``_watcher``) that polls the process
   exit code and parses the growing log file every second to update the
   ``AnalysisJob`` record in the database.

Progress parsing
----------------
The log lines written by ``run.py`` / ``core.orchestration`` follow
consistent patterns:

    [HH:MM:SS] INFO orchestration: [1/4] === Phase 1: Parse C++ source ===
    [HH:MM:SS] INFO orchestration: [1/4] Phase 1: Parse C++ source — 192.3s
    [HH:MM:SS] INFO orchestration: [2/4] === Phase 2: Derive Model ===
    ...
    [HH:MM:SS] INFO run: Done. Total: 1234.56s

We derive ``phase`` (1-4), ``phase_pct`` (heuristic per-phase progress),
``current_activity``, and ``elapsed_seconds`` from these patterns.  This
avoids any changes to ``run.py`` or the pipeline scripts.

Thread safety
-------------
All reads/writes of ``_active`` go through ``_lock``.  The DB update
(``db.jobs.update``) delegates thread-safety to the repository.

Cancellation
------------
``executor.cancel(job_id)`` sends SIGKILL to the process group (POSIX) or
uses ``taskkill /F /T`` on Windows, exactly like the backend's ``_kill_process_tree``.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Regexes for log parsing
# ---------------------------------------------------------------------------

# Phase start line: "[1/4] === Phase 1: Parse C++ source ==="
_RE_PHASE_START = re.compile(r"\[(\d+)/(\d+)\]\s+===\s+(.+?)\s+===")

# Phase done line:  "[1/4] Phase 1: Parse C++ source — 192.3s"
_RE_PHASE_DONE  = re.compile(r"\[(\d+)/(\d+)\]\s+(.+?)\s+—\s+([\d.]+)s")

# LLM enrichment progress: "312 of 842 functions"
_RE_LLM_PROGRESS = re.compile(r"(\d+)\s+of\s+(\d+)\s+functions")

# Final done: "Done. Total: 1234.56s"
_RE_DONE = re.compile(r"Done\.\s+Total:\s+([\d.]+)s")

# Error: any ERROR line
_RE_ERROR = re.compile(r"\]\s+ERROR\s+")

# Phase-number label → internal phase number
_PHASE_NAMES = {
    "Parse C++":    1,
    "Derive Model": 2,
    "Run Views":    3,
    "Export DOCX":  4,
}

# Per-phase activity descriptions shown in the UI
_PHASE_ACTIVITIES = {
    1: "Parsing C++ source with libclang…",
    2: "Deriving model, running LLM enrichment…",
    3: "Generating views, flowcharts, interface tables…",
    4: "Exporting DOCX document…",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_root() -> Path:
    here = Path(__file__).resolve().parent
    for candidate in [here, here.parent, here.parent.parent, here.parent.parent.parent]:
        if (candidate / "run.py").exists():
            return candidate
    return here.parent.parent


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Kill the process and all its children."""
    if proc.poll() is not None:
        return
    pid = proc.pid
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=False, timeout=10,
            )
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            proc.terminate()
        except OSError:
            pass
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
            return
        except OSError:
            pass
        try:
            proc.kill()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Per-job state tracker (internal)
# ---------------------------------------------------------------------------

class _JobState:
    def __init__(self, job_id: str, log_path: Path, proc: subprocess.Popen):
        self.job_id   = job_id
        self.log_path = log_path
        self.proc     = proc
        self.cancelled = False

        # Parsed progress (updated by watcher thread)
        self.phase          = 1
        self.phase_pct      = 0
        self.current_activity = _PHASE_ACTIVITIES[1]
        self.activity_detail  = ""
        self.elapsed_seconds  = 0
        self.eta_seconds: Optional[int] = None
        self.error_message: Optional[str] = None

        # Phase timing
        self._phase_start: Dict[int, float] = {}   # phase_num → wall-clock start
        self._phase_done:  Dict[int, float] = {}   # phase_num → duration_seconds
        self._log_offset   = 0   # byte offset for incremental reads
        self._start_wall   = time.monotonic()

    # -----------------------------------------------------------------------
    # Log parsing
    # -----------------------------------------------------------------------

    def parse_new_log_lines(self) -> None:
        """Read any new bytes from the log file and update progress fields."""
        try:
            size = self.log_path.stat().st_size
        except OSError:
            return
        if size <= self._log_offset:
            return
        try:
            with self.log_path.open("rb") as f:
                f.seek(self._log_offset)
                chunk = f.read(size - self._log_offset)
            self._log_offset = size
        except OSError:
            return

        for raw_line in chunk.split(b"\n"):
            try:
                line = raw_line.decode("utf-8", errors="replace").rstrip()
            except Exception:
                continue
            self._process_line(line)

        self.elapsed_seconds = int(time.monotonic() - self._start_wall)

    def _process_line(self, line: str) -> None:
        # Phase start
        m = _RE_PHASE_START.search(line)
        if m:
            idx, total, name = int(m.group(1)), int(m.group(2)), m.group(3)
            phase_num = _PHASE_NAMES.get(name.split(":")[0].strip(), idx)
            self.phase = phase_num
            self.phase_pct = 0
            self.current_activity = _PHASE_ACTIVITIES.get(phase_num, name)
            self.activity_detail = ""
            self._phase_start[phase_num] = time.monotonic()
            return

        # Phase done
        m = _RE_PHASE_DONE.search(line)
        if m:
            idx, total, name, secs = int(m.group(1)), int(m.group(2)), m.group(3), float(m.group(4))
            phase_num = _PHASE_NAMES.get(name.split(":")[0].strip(), idx)
            self._phase_done[phase_num] = secs
            self.phase_pct = 100
            return

        # LLM enrichment progress ("312 of 842 functions")
        m = _RE_LLM_PROGRESS.search(line)
        if m:
            done, total = int(m.group(1)), int(m.group(2))
            if total > 0:
                self.phase_pct = min(99, int(done * 100 / total))
                self.activity_detail = f"{done} of {total} functions"
                # ETA heuristic: if we know when phase 2 started, extrapolate
                p2_start = self._phase_start.get(2)
                if p2_start and done > 0:
                    elapsed_p2 = time.monotonic() - p2_start
                    rate = done / elapsed_p2  # functions/sec
                    if rate > 0:
                        remaining = (total - done) / rate
                        self.eta_seconds = int(remaining)
            return

        # Final done
        m = _RE_DONE.search(line)
        if m:
            self.phase = 4
            self.phase_pct = 100
            self.current_activity = "Complete"
            self.activity_detail = f"Total: {m.group(1)}s"
            self.eta_seconds = 0
            return

        # Error line — capture message
        if _RE_ERROR.search(line):
            # Strip log prefix, keep the message part
            parts = line.split("ERROR", 1)
            msg = parts[-1].strip().lstrip(": ").strip() if len(parts) > 1 else line
            if msg:
                self.error_message = msg[:300]


# ---------------------------------------------------------------------------
# Singleton executor
# ---------------------------------------------------------------------------

class PipelineExecutor:
    """
    Manages spawning and monitoring of ``run.py`` subprocesses.

    Usage (from a route handler)::

        from api.services.pipeline_executor import executor
        executor.start(job_id, db, project_path, extra_args=[...])
    """

    def __init__(self) -> None:
        self._lock: threading.Lock = threading.Lock()
        self._active: Dict[str, _JobState] = {}  # job_id → state
        self._root: Path = _find_root()
        self._log_dir: Path = self._root / "api" / "db" / "jobs"
        self._log_dir.mkdir(parents=True, exist_ok=True)

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def start(
        self,
        job_id: str,
        db: Any,
        project_path: str,
        extra_args: Optional[list] = None,
    ) -> None:
        """
        Spawn ``run.py`` for ``job_id`` and start progress tracking.

        Parameters
        ----------
        job_id
            The ``AnalysisJob.id`` already persisted in *db*.
        db
            Database adapter (to call ``db.jobs.update``).
        project_path
            Absolute path to the C++ source tree to analyse.
        extra_args
            Additional CLI arguments for ``run.py`` (e.g. ``["--selected-group", "Sample"]``).
        """
        log_path = self._log_dir / f"{job_id}.log"
        cmd = [sys.executable, str(self._root / "run.py"), project_path]
        if extra_args:
            cmd.extend(extra_args)

        log_path.parent.mkdir(parents=True, exist_ok=True)
        out_fh = log_path.open("w", encoding="utf-8", buffering=1)

        popen_kw: Dict[str, Any] = dict(
            cwd=str(self._root),
            stdout=out_fh,
            stderr=subprocess.STDOUT,
        )
        if sys.platform == "win32":
            popen_kw["shell"] = True
            popen_kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kw["start_new_session"] = True

        proc = subprocess.Popen(cmd, **popen_kw)
        proc._spawn_output_fh = out_fh  # type: ignore[attr-defined]

        state = _JobState(job_id, log_path, proc)

        with self._lock:
            self._active[job_id] = state

        # Update DB: running
        job = db.jobs.get(job_id)
        if job:
            job.status = "running"
            job.phases[0].status = "running"
            db.jobs.update(job)

        # Background watcher thread
        t = threading.Thread(
            target=self._watcher,
            args=(job_id, db),
            daemon=True,
            name=f"pipeline-watcher-{job_id}",
        )
        t.start()

    def cancel(self, job_id: str) -> bool:
        """Kill the running process for *job_id*. Returns True if found."""
        with self._lock:
            state = self._active.get(job_id)
        if state is None:
            return False
        state.cancelled = True
        _kill_process_tree(state.proc)
        return True

    def is_running(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._active

    def get_log_tail(self, job_id: str, lines: int = 60) -> list[str]:
        """Return the last *lines* lines from the job log file."""
        with self._lock:
            state = self._active.get(job_id)
        if state is None:
            # Job may have finished — try reading the log from disk
            log_path = self._log_dir / f"{job_id}.log"
        else:
            log_path = state.log_path
        if not log_path.exists():
            return []
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
            all_lines = text.splitlines()
            return all_lines[-lines:]
        except OSError:
            return []

    # -----------------------------------------------------------------------
    # Background watcher
    # -----------------------------------------------------------------------

    def _watcher(self, job_id: str, db: Any) -> None:
        """Poll the subprocess and update DB progress until it exits."""
        with self._lock:
            state = self._active.get(job_id)
        if state is None:
            return

        try:
            while True:
                rc = state.proc.poll()
                # Parse any new log output
                state.parse_new_log_lines()
                # Push progress to DB
                self._push_progress(state, db, rc)
                if rc is not None:
                    break
                time.sleep(1.0)
        finally:
            # Close log file handle
            fh = getattr(state.proc, "_spawn_output_fh", None)
            if fh is not None:
                try:
                    fh.close()
                except OSError:
                    pass
            with self._lock:
                self._active.pop(job_id, None)

    def _push_progress(
        self,
        state: _JobState,
        db: Any,
        rc: Optional[int],
    ) -> None:
        """Write the current progress snapshot back to the DB job record."""
        job = db.jobs.get(state.job_id)
        if not job:
            return

        now = datetime.now(UTC)

        # Build updated phases list
        for p in job.phases:
            if p.number < state.phase:
                p.status = "done"
                duration = state._phase_done.get(p.number)
                if duration is not None:
                    p.duration_seconds = int(duration)
            elif p.number == state.phase:
                if rc is not None:
                    p.status = "done" if rc == 0 else "failed"
                    duration = state._phase_done.get(p.number)
                    if duration is not None:
                        p.duration_seconds = int(duration)
                else:
                    p.status = "running"
            else:
                p.status = "pending"

        job.phase             = state.phase
        job.phase_pct         = state.phase_pct
        job.current_activity  = state.current_activity
        job.activity_detail   = state.activity_detail
        job.elapsed_seconds   = state.elapsed_seconds
        job.eta_seconds       = state.eta_seconds

        if rc is not None:
            if state.cancelled and rc != 0:
                job.status = "cancelled"
                job.error_message = "Cancelled by user."
            elif rc == 0:
                job.status = "complete"
                job.phase_pct = 100
                job.current_activity = "Complete"
                job.eta_seconds = 0
            else:
                job.status = "failed"
                job.error_message = state.error_message or f"run.py exited with code {rc}"
            job.completed_at = now
        else:
            job.status = "running"

        db.jobs.update(job)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

executor = PipelineExecutor()
