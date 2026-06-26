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

import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Set

from ..models.domain import Version, Document
from . import git_cli
from .settings import get_settings

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Per-job state (thread-safe via _LOCK)
# ---------------------------------------------------------------------------
_LOCK = threading.Lock()
_job_logs: dict[str, deque] = {}        # recent log lines (ring buffer)
_job_log_totals: dict[str, int] = {}    # monotonic line count (for SSE cursor)
_job_procs: dict[str, subprocess.Popen] = {}
_job_resume_events: dict[str, threading.Event] = {}
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start(db: Any, job_id: str) -> None:
    """Kick off the real pipeline on a daemon thread (returns immediately)."""
    t = threading.Thread(target=_run, args=(db, job_id), daemon=True, name=f"job-{job_id}")
    t.start()


def cancel_subprocess(job_id: str) -> None:
    """Terminate the subprocess for the given job (if still alive)."""
    with _LOCK:
        proc = _job_procs.get(job_id)
    if proc is not None and proc.poll() is None:
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


def reexport(db: Any, job_id: str) -> None:
    """Run Phase 4 only (re-export DOCX) on a daemon thread."""
    t = threading.Thread(target=_do_reexport, args=(db, job_id), daemon=True,
                         name=f"reexport-{job_id}")
    t.start()


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
        # Keep logs so SSE can drain remaining lines after completion


def _mark_failed(db: Any, job_id: str, message: str) -> None:
    job = db.jobs.get(job_id)
    if job and job.status not in ("cancelled", "complete", "failed"):
        job.status = "failed"
        job.error_message = message[:4000]
        job.completed_at = _now()
        db.jobs.update(job)


# ---------------------------------------------------------------------------
# Main thread entry
# ---------------------------------------------------------------------------

def _run(db: Any, job_id: str) -> None:
    try:
        _init_state(job_id)
        _inner_run(db, job_id)
    except Exception as exc:
        _mark_failed(db, job_id, f"Runner error: {exc}")
    finally:
        _cleanup_state(job_id)


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
        _inner_run_locked(db, job_id, project)
    finally:
        sem.release()


def _inner_run_locked(db: Any, job_id: str, project: Any) -> None:
    job = db.jobs.get(job_id)
    if not job:
        return

    job.status = "running"
    job.current_activity = "Preparing workspace…"
    db.jobs.update(job)
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
        config_path = _write_project_config(project, workspace_dir)
    except Exception as exc:
        _mark_failed(db, job_id, f"Config generation failed: {exc}")
        return
    _append_log(job_id, f"Config written to {config_path.name}")

    if _is_cancelled(db, job_id):
        return

    job = db.jobs.get(job_id)
    job.current_activity = _ACTIVITY[1]
    db.jobs.update(job)

    arch_layers = project.architecture_layers or []

    # 3. Run pipeline
    if job.pause_after_phase1:
        _run_with_pause(db, job_id, checkout_dir, config_path, arch_layers=arch_layers)
    else:
        _run_full(db, job_id, checkout_dir, config_path, arch_layers=arch_layers)


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

def _write_project_config(project: Any, workspace_dir: Path) -> Path:
    """Write a per-project config.json by merging the base config with project settings."""
    base_path = get_settings().repo_root / "config" / "config.json"
    try:
        with open(base_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError):
        cfg = {}

    # Apply explicit section overrides from build_config
    bc = project.build_config or {}
    for key in ("clang", "llm", "views", "docx"):
        if key in bc and isinstance(bc[key], dict):
            cfg.setdefault(key, {})
            cfg[key].update(bc[key])

    # Convert architecture_layers to the layers schema
    layers = _convert_layers(project.architecture_layers or [])
    if layers:
        cfg["layers"] = layers

    workspace_dir.mkdir(parents=True, exist_ok=True)
    out_path = workspace_dir / "config.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    return out_path


def _convert_layers(arch_layers: list) -> dict:
    """Convert API architecture_layers list to config.json layers dict.

    API shape (from NewProjectPage):
      [{"name": "L1", "path": "Layer1", "lib_paths": [...],
        "groups": [{"name": "G1", "components": [{"name": "C1", "files": [...]}]}]}]
    Config shape:
      {"L1": {"path": "Layer1", "groups": {"G1": {"C1": "Sample/C1"}}}}

    Component paths are derived from the files list: the common ancestor directory
    of all selected files, stripped of the layer path prefix.
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
                            comp_path = _derive_component_path(files, lpath) or cname
                            comps[cname] = comp_path
            else:
                continue
            if gname:
                groups[gname] = comps
        result[lname] = {"path": lpath, "groups": groups}
    return result


def _derive_component_path(files: list, layer_path: str) -> str:
    """Return the component directory path relative to layer_path.

    Finds the common ancestor directory of all file paths, then strips the
    layer_path prefix so the result is relative to the layer root.
    """
    import posixpath
    dirs = [posixpath.dirname(f.replace("\\", "/")) for f in files if f]
    dirs = [d for d in dirs if d]
    if not dirs:
        return ""
    common = dirs[0]
    for d in dirs[1:]:
        while common and not (d == common or d.startswith(common + "/")):
            common = posixpath.dirname(common)
    if not common:
        return ""
    layer_norm = layer_path.rstrip("/").replace("\\", "/")
    if common == layer_norm:
        return ""
    if layer_norm and common.startswith(layer_norm + "/"):
        return common[len(layer_norm) + 1:]
    return common


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
) -> list[str]:
    cmd = [sys.executable, str(get_settings().repo_root / "run.py")]
    cmd += ["--config", str(config_path)]
    if use_model:
        cmd.append("--use-model")
    if from_phase > 1:
        cmd += ["--from-phase", str(from_phase)]
    if to_phase is not None:
        cmd += ["--to-phase", str(to_phase)]
    if job.layer_filter:
        cmd += ["--selected-layer", job.layer_filter]
    if getattr(job, "version_tag", None):
        cmd += ["--project-name", job.version_tag]
    # Extra include paths from architecture_layers.lib_paths (--include-path <layer> <abs_dir>)
    for layer in arch_layers:
        if not isinstance(layer, dict):
            continue
        lname = str(layer.get("name") or "").strip()
        if not lname:
            continue
        for lp in (layer.get("lib_paths") or []):
            lp = str(lp).strip()
            if lp:
                cmd += ["--include-path", lname, str(checkout_dir / lp)]
    cmd.append(str(checkout_dir))
    return cmd


# ---------------------------------------------------------------------------
# Run strategies
# ---------------------------------------------------------------------------

def _run_full(db: Any, job_id: str, checkout_dir: Path, config_path: Path,
              arch_layers: list = ()) -> None:
    job = db.jobs.get(job_id)
    cmd = _build_cmd(job, checkout_dir, config_path, arch_layers=arch_layers)
    ok = _execute_subprocess(db, job_id, cmd, phase_start=1)
    if ok:
        _complete(db, job_id)


def _run_with_pause(db: Any, job_id: str, checkout_dir: Path, config_path: Path,
                    arch_layers: list = ()) -> None:
    job = db.jobs.get(job_id)
    # Phase 1+2 only
    cmd = _build_cmd(job, checkout_dir, config_path, to_phase=2, arch_layers=arch_layers)
    ok = _execute_subprocess(db, job_id, cmd, phase_start=1, phase_end=2)
    if not ok or _is_cancelled(db, job_id):
        return

    # Pause
    job = db.jobs.get(job_id)
    job.status = "paused"
    job.current_activity = "Paused after Phase 2 — review functions, then resume."
    db.jobs.update(job)
    _append_log(job_id, "Paused. Resume to run Phases 3–4.")

    # Wait for resume signal or cancel
    ev = None
    with _LOCK:
        ev = _job_resume_events.get(job_id)
    while ev and not ev.is_set():
        ev.wait(timeout=2.0)
        if _is_cancelled(db, job_id):
            return

    if _is_cancelled(db, job_id):
        return

    # Phase 3+4
    job = db.jobs.get(job_id)
    if not job or job.status == "cancelled":
        return
    job.status = "running"
    job.current_activity = _ACTIVITY[3]
    db.jobs.update(job)
    _append_log(job_id, "Resuming from Phase 3…")

    job = db.jobs.get(job_id)
    cmd = _build_cmd(job, checkout_dir, config_path, from_phase=3, use_model=True,
                     arch_layers=arch_layers)
    ok = _execute_subprocess(db, job_id, cmd, phase_start=3)
    if ok:
        _complete(db, job_id)


# ---------------------------------------------------------------------------
# Subprocess execution + output tailing
# ---------------------------------------------------------------------------

def _execute_subprocess(
    db: Any,
    job_id: str,
    cmd: list[str],
    phase_start: int = 1,
    phase_end: int = 4,
) -> bool:
    """Run cmd, tail its output, update job progress. Returns True on success."""
    cfg = get_settings()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    if cfg.libclang_path:
        env["LIBCLANG_PATH"] = cfg.libclang_path

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

    current_phase = phase_start
    phase_start_time = _now()
    recent_lines: list[str] = []
    line_count = 0
    _timeout = get_settings().subprocess_timeout or None
    _timed_out = False

    try:
        for raw_line in proc.stdout:
            line = raw_line.rstrip("\n\r")
            if not line:
                continue

            _append_log(job_id, line)
            recent_lines.append(line)
            if len(recent_lines) > 80:
                recent_lines.pop(0)
            line_count += 1

            # Cancel check (every 20 lines to keep overhead low)
            if line_count % 20 == 0 and _is_cancelled(db, job_id):
                try:
                    proc.terminate()
                except OSError:
                    pass
                return False

            # Phase transition detection
            new_phase = _detect_phase(line, current_phase)
            if new_phase != current_phase:
                _transition_phase(db, job_id, current_phase, new_phase, phase_start_time)
                current_phase = new_phase
                phase_start_time = _now()

            # Update activity detail from log content (strip log prefix)
            detail = _strip_log_prefix(line)
            if detail and len(detail) > 10:
                _update_activity(db, job_id, detail[:120])

    finally:
        try:
            proc.wait(timeout=_timeout)
        except subprocess.TimeoutExpired:
            _timed_out = True
            try:
                proc.terminate()
            except OSError:
                pass
            proc.wait()

    if _timed_out:
        _mark_failed(db, job_id, f"Subprocess timed out after {_timeout}s.")
        return False

    with _LOCK:
        _job_procs.pop(job_id, None)

    rc = proc.returncode
    if _is_cancelled(db, job_id):
        return False

    if rc != 0:
        tail = "\n".join(recent_lines[-20:])
        _mark_failed(db, job_id, f"run.py exited with code {rc}.\n{tail}")
        return False

    # Mark the final phase done
    job = db.jobs.get(job_id)
    if job:
        for p in job.phases:
            if p.number == current_phase and p.status != "done":
                p.status = "done"
                p.duration_seconds = max(1, int((_now() - phase_start_time).total_seconds()))
        db.jobs.update(job)

    return True


def _detect_phase(line: str, current_phase: int) -> int:
    """Detect a phase start marker in a log line. Only advances forward."""
    if "===" not in line:
        return current_phase
    for n in range(current_phase + 1, 5):
        if _PHASE_MARKERS[n] in line:
            return n
    return current_phase


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
    job.elapsed_seconds = int((_now() - job.started_at).total_seconds())
    job.eta_seconds = max(0, (4 - new_phase) * 120)
    db.jobs.update(job)
    _append_log(job_id, f"→ Phase {new_phase}: {_ACTIVITY.get(new_phase, '')}")


def _update_activity(db: Any, job_id: str, detail: str) -> None:
    job = db.jobs.get(job_id)
    if job:
        job.activity_detail = detail
        job.elapsed_seconds = int((_now() - job.started_at).total_seconds())
        db.jobs.update(job)


def _is_cancelled(db: Any, job_id: str) -> bool:
    job = db.jobs.get(job_id)
    return not job or job.status == "cancelled"


# ---------------------------------------------------------------------------
# Version snapshot — capture model/ + output/ for the compare engine (M3)
# ---------------------------------------------------------------------------

def _capture_version_snapshot(project_id: str, version_id: str) -> None:
    """Copy current model/ and output/ into workspaces/<project_id>/versions/<version_id>/
    so the compare engine can diff two versions without re-running the pipeline."""
    root = get_settings().repo_root
    vdir = root / "workspaces" / project_id / "versions" / version_id
    try:
        vdir.mkdir(parents=True, exist_ok=True)
        for dirname in ("model", "output"):
            src = root / dirname
            dst = vdir / dirname
            if src.is_dir():
                shutil.copytree(str(src), str(dst), dirs_exist_ok=True)
    except Exception:
        pass  # snapshot is best-effort; failures must not break the job


# ---------------------------------------------------------------------------
# Completion — register Version + Documents
# ---------------------------------------------------------------------------

def _complete(db: Any, job_id: str) -> None:
    job = db.jobs.get(job_id)
    if not job or job.status in ("cancelled", "failed"):
        return

    now = _now()
    project = db.projects.get(job.project_id)

    version = _make_version(db, project, job, now)
    docs = _make_documents(db, project, version, now)
    _make_sections(db, docs, now)
    version.docs_count = len(docs)
    db.versions.update(version)

    _load_and_register_functions(db, job, version.id)
    _capture_version_snapshot(job.project_id, version.id)

    job.status = "complete"
    job.phase = 4
    job.phase_pct = 100
    job.current_activity = "Done"
    job.activity_detail = f"{len(docs)} document(s) generated"
    job.eta_seconds = 0
    job.completed_at = now
    job.version_id = version.id
    job.elapsed_seconds = int((now - job.started_at).total_seconds())
    for p in job.phases:
        p.status = "done"
    db.jobs.update(job)

    if project:
        project.status = "in_review"
        project.updated_at = now
        db.projects.update(project)

    _append_log(job_id, f"Complete. Version {version.tag}, {len(docs)} document(s).")


def _make_sections(db: Any, docs: list, now: datetime) -> None:
    """Seed DocumentSection records for every document created by _make_documents."""
    from ..models.domain import DocumentSection

    output_dir = get_settings().repo_root / "output"

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


def _make_version(db: Any, project: Any, job: Any, now: datetime) -> Version:
    existing = db.versions.list_for_project(project.id) if project else []
    taken = {v.tag for v in existing}
    tag = (getattr(job, "version_tag", None) or "").strip() or f"v0.{len(existing) + 1}.0"
    base, i = tag, 1
    while tag in taken:
        tag = f"{base}-{i}"
        i += 1
    version = Version(
        id=f"ver{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        tag=tag,
        commit_sha=job.commit_sha,
        branch=job.branch,
        description="Generated by analysis run",
        status="in_review",
        docs_count=0,
        created_by=(project.created_by if project else "system"),
        created_at=now,
    )
    db.versions.create(version)
    return version


def _make_documents(db: Any, project: Any, version: Version, now: datetime) -> list[Document]:
    """Create Documents by scanning real output/ dirs, falling back to architecture walk."""
    docs: list[Document] = []

    def add(process: str, name: str, subtitle: str, layer: str, group: str) -> None:
        doc = Document(
            id=f"doc{uuid.uuid4().hex[:8]}",
            project_id=project.id,
            version_id=version.id,
            process=process, name=name, subtitle=subtitle,
            layer=layer, group=group, status="in_review",
            due_date=None, created_at=now, updated_at=now,
        )
        db.documents.update(doc)
        docs.append(doc)

    add("SYS.2", "System Requirements", "SyRS", "", "Global")
    add("SWE.1", "Software Requirements", "SRS", "", "Global")

    # Real output/ dirs — add one SWE.2 per group directory found
    output_dir = get_settings().repo_root / "output"
    groups_found: list[str] = []
    if output_dir.is_dir():
        groups_found = [d.name for d in sorted(output_dir.iterdir()) if d.is_dir()]
        for gname in groups_found:
            add("SWE.2", gname, "Component Design", "", gname)

    # Walk architecture_layers: add SWE.2 only when no output dirs found (fallback),
    # but always add SWE.3 unit design docs for every component.
    unit_count = 0
    for layer in (project.architecture_layers or []):
        if not isinstance(layer, dict):
            continue
        lname = str(layer.get("name") or "")
        for g in (layer.get("groups") or []):
            gname = g if isinstance(g, str) else (str(g.get("name") or "") if isinstance(g, dict) else "")
            if not gname:
                continue
            if not groups_found:
                add("SWE.2", gname, "Component Design", lname, gname)
            comps = [] if isinstance(g, str) else (g.get("components", []) or [])
            for c in comps:
                cname = c if isinstance(c, str) else (c.get("name", "") if isinstance(c, dict) else "")
                if cname and unit_count < 24:
                    add("SWE.3", str(cname), "Unit Design", lname, gname)
                    unit_count += 1

    if unit_count == 0 and len(docs) <= 2:
        add("SWE.3", "Main Module", "Unit Design", "", "Global")
    return docs


# ---------------------------------------------------------------------------
# Functions loader — reads model/functions.json and registers under the job
# ---------------------------------------------------------------------------

def _baseline_fn_keys(reference_version_id: str) -> Optional[Set[str]]:
    """Return the set of function dict-keys from the baseline version's model, or None."""
    versions_dir = get_settings().repo_root / "versions" / reference_version_id / "model"
    path = versions_dir / "functions.json"
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as f:
            raw = json.load(f)
        return set(raw.keys()) if isinstance(raw, dict) else None
    except Exception:
        return None


def _load_and_register_functions(db: Any, job: Any, version_id: str) -> None:
    """Read model/functions.json and register functions in the DB under the job's id."""
    from ..models.domain import Function

    path = get_settings().repo_root / "model" / "functions.json"
    if not path.exists():
        return
    try:
        with path.open(encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return
    if not isinstance(raw, dict):
        return

    ref_keys: Optional[Set[str]] = None
    if getattr(job, "reference_version_id", None):
        ref_keys = _baseline_fn_keys(job.reference_version_id)

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

def _do_reexport(db: Any, job_id: str) -> None:
    job = db.jobs.get(job_id)
    if not job:
        return
    project = db.projects.get(job.project_id)
    if not project:
        return

    root = get_settings().repo_root
    checkout_dir = root / "workspaces" / job.project_id / job.commit_sha[:16]
    if not checkout_dir.is_dir():
        _mark_failed(db, job_id, "Checkout not found — run the full analysis first.")
        return

    workspace_dir = root / "workspaces" / job.project_id
    config_path = workspace_dir / "config.json"
    if not config_path.is_file():
        try:
            config_path = _write_project_config(project, workspace_dir)
        except Exception as exc:
            _mark_failed(db, job_id, f"Config generation failed: {exc}")
            return

    arch_layers = project.architecture_layers or []
    cmd = _build_cmd(job, checkout_dir, config_path, from_phase=4, use_model=True,
                     arch_layers=arch_layers)
    _execute_subprocess(db, job_id, cmd, phase_start=4, phase_end=4)
