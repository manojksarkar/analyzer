"""Analysis Jobs routes — /api/v1/projects/:id/jobs/*

Changes vs original stub
-------------------------
* ``POST /jobs``            — now actually spawns ``run.py`` via ``PipelineExecutor``
* ``POST /jobs/{id}/cancel`` — kills the real subprocess (was just a DB mutation)
* ``GET  /jobs/{id}/logs``  — new endpoint: tail the job's captured log file
* ``GET  /jobs/{id}/events`` — SSE stream now polls real DB state (no change to shape)
* ``POST /jobs/{id}/reexport`` — re-runs Phase 4 only (``--from-phase 4``)
"""
from __future__ import annotations
import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ..db.session import get_db
from ..db.in_memory import InMemoryDatabase
from ..middleware.auth import get_current_user, require_project_admin, require_project_member
from ..models.domain import User, AnalysisJob, AnalysisPhase
from ..services.errors import not_found, conflict, bad_request
from ..services.pipeline_executor import executor

router = APIRouter(tags=["jobs"])
UTC = timezone.utc


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class StartJobRequest(BaseModel):
    commit_sha: str
    version_tag: Optional[str] = None
    reference_version_id: Optional[str] = None
    pause_after_phase1: bool = False
    layer_filter: Optional[str] = None
    # Pipeline execution options
    project_path: Optional[str] = None        # abs path to C++ source tree
    selected_group: Optional[str] = None      # --selected-group
    selected_layer: Optional[str] = None      # --selected-layer
    selected_components: Optional[list[str]] = None  # --selected-component (repeatable)
    from_phase: int = 1                        # --from-phase N
    to_phase: Optional[int] = None             # --to-phase N
    clean: bool = False                        # --clean
    no_llm_summarize: bool = False             # --no-llm-summarize
    use_model: bool = False                    # --use-model (skip Phase 1/2)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_root() -> Path:
    here = Path(__file__).resolve().parent
    for candidate in [here, here.parent, here.parent.parent, here.parent.parent.parent]:
        if (candidate / "run.py").exists():
            return candidate
    return here.parent.parent


def _default_project_path(project, root: Path) -> str:
    """
    Resolve the C++ source path for a project.

    Priority:
    1. ``project.build_config["project_path"]`` if set
    2. ``repo_url`` last segment as a subdirectory of the repo root
    3. ``<root>/SampleCppProject`` (bundled test corpus)
    """
    cfg_path = (project.build_config or {}).get("project_path", "")
    if cfg_path and Path(cfg_path).is_dir():
        return cfg_path
    # Try to derive from repo name
    repo_name = (project.repo_url or "").rstrip("/").split("/")[-1].replace(".git", "")
    if repo_name:
        candidate = root / repo_name
        if candidate.is_dir():
            return str(candidate)
    # Fall back to bundled corpus
    fallback = root / "SampleCppProject"
    if fallback.is_dir():
        return str(fallback)
    return str(root)


def _build_run_args(body: StartJobRequest) -> list[str]:
    """Build the extra CLI args for run.py from the job request."""
    args: list[str] = []
    if body.clean:
        args.append("--clean")
    if body.use_model:
        args.append("--use-model")
    if body.no_llm_summarize:
        args.append("--no-llm-summarize")
    if body.from_phase and body.from_phase > 1:
        args += ["--from-phase", str(body.from_phase)]
    if body.to_phase:
        args += ["--to-phase", str(body.to_phase)]
    if body.layer_filter:
        args += ["--selected-layer", body.layer_filter]
    elif body.selected_layer:
        args += ["--selected-layer", body.selected_layer]
    if body.selected_group:
        args += ["--selected-group", body.selected_group]
    if body.selected_components:
        for comp in body.selected_components:
            args += ["--selected-component", comp]
    return args


def _job_dict(job: AnalysisJob) -> dict:
    return {
        "id": job.id,
        "status": job.status,
        "phase": job.phase,
        "phase_pct": job.phase_pct,
        "current_activity": job.current_activity,
        "activity_detail": job.activity_detail,
        "elapsed_seconds": job.elapsed_seconds,
        "eta_seconds": job.eta_seconds,
        "phases": [
            {
                "number": p.number,
                "name": p.name,
                "status": p.status,
                "duration_seconds": p.duration_seconds,
            }
            for p in job.phases
        ],
        "commit_sha": job.commit_sha,
        "branch": job.branch,
        "version_id": job.version_id,
        "started_at": job.started_at.isoformat(),
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "error_message": job.error_message,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/jobs", status_code=202)
def start_job(
    project_id: str,
    body: StartJobRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """
    Start a new analysis job.

    Creates the ``AnalysisJob`` DB record and immediately spawns ``run.py``
    as a subprocess.  Progress is tracked by tailing the log file and pushing
    updates to the DB every second.

    The job stays in ``running`` state until ``run.py`` exits.  Use
    ``GET /jobs/{id}`` or the SSE ``/jobs/{id}/events`` endpoint to poll
    or stream progress.
    """
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_admin(project_id, current_user, db)

    # Prevent duplicate active jobs
    existing = db.jobs.get_current(project_id)
    if existing and existing.status in ("queued", "running", "paused"):
        raise conflict("JOB_ALREADY_RUNNING", "An analysis job is already active for this project.")

    # Resolve version_id if tag provided
    version_id = None
    if body.version_tag:
        ver = db.versions.get_by_tag(project_id, body.version_tag)
        version_id = ver.id if ver else None

    now = datetime.now(UTC)
    job = AnalysisJob(
        id=f"job{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        commit_sha=body.commit_sha,
        version_id=version_id,
        reference_version_id=body.reference_version_id,
        status="queued",
        pause_after_phase1=body.pause_after_phase1,
        layer_filter=body.layer_filter,
        phase=body.from_phase, phase_pct=0,
        current_activity="Queued — launching pipeline…",
        activity_detail="",
        elapsed_seconds=0, eta_seconds=None,
        phases=[
            AnalysisPhase(1, "Parse C++",    "pending", None),
            AnalysisPhase(2, "Derive Model", "pending", None),
            AnalysisPhase(3, "Run Views",    "pending", None),
            AnalysisPhase(4, "Export DOCX",  "pending", None),
        ],
        started_at=now, completed_at=None, error_message=None,
    )
    db.jobs.create(job)

    # Resolve the C++ source tree path
    project = db.projects.get(project_id)
    root = _find_root()
    cpp_path = body.project_path or _default_project_path(project, root)

    extra_args = _build_run_args(body)

    # Launch — non-blocking; watcher thread updates DB in background
    try:
        executor.start(job.id, db, cpp_path, extra_args=extra_args)
    except Exception as exc:
        # If spawn fails, mark job as failed immediately
        job.status = "failed"
        job.error_message = str(exc)
        job.completed_at = datetime.now(UTC)
        db.jobs.update(job)
        raise HTTPException(500, detail={
            "code": "SPAWN_FAILED",
            "message": f"Failed to launch pipeline: {exc}",
            "status": 500,
        })

    return {
        "job_id": job.id,
        "status": job.status,
        "log_url": f"/api/v1/projects/{project_id}/jobs/{job.id}/logs",
    }


@router.get("/projects/{project_id}/jobs/current")
def get_current_job(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_member(project_id, current_user, db)
    job = db.jobs.get_current(project_id)
    if not job:
        return {"job": None}
    return {"job": _job_dict(job)}


@router.get("/projects/{project_id}/jobs/{job_id}")
def get_job(
    project_id: str,
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_member(project_id, current_user, db)
    job = db.jobs.get(job_id)
    if not job or job.project_id != project_id:
        raise not_found("AnalysisJob", job_id)
    return {"job": _job_dict(job)}


@router.get("/projects/{project_id}/jobs/{job_id}/logs")
def get_job_logs(
    project_id: str,
    job_id: str,
    lines: int = Query(60, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """
    Return the tail of the captured ``run.py`` output for this job.

    Returns plain text (newline-separated).  The ``lines`` query parameter
    controls how many tail lines to return (default 60, max 500).

    While the job is running this reflects live output; after it completes
    the full log remains available.
    """
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_member(project_id, current_user, db)
    job = db.jobs.get(job_id)
    if not job or job.project_id != project_id:
        raise not_found("AnalysisJob", job_id)

    log_lines = executor.get_log_tail(job_id, lines=lines)
    return PlainTextResponse("\n".join(log_lines))


@router.post("/projects/{project_id}/jobs/{job_id}/cancel")
def cancel_job(
    project_id: str,
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """
    Cancel a running job.

    Sends SIGKILL to the ``run.py`` process tree.  The watcher thread detects
    the exit and finalises the DB record as ``cancelled``.
    """
    require_project_admin(project_id, current_user, db)
    job = db.jobs.get(job_id)
    if not job or job.project_id != project_id:
        raise not_found("AnalysisJob", job_id)
    if job.status not in ("queued", "running", "paused"):
        # Job already in a terminal state — still try to kill any stray process
        executor.cancel(job_id)
        return {"job": _job_dict(job)}

    # Kill the real subprocess if it's tracked
    killed = executor.cancel(job_id)

    if not killed:
        # Process not found in executor (e.g. seed data job) — just mutate the DB
        job.status = "cancelled"
        job.completed_at = datetime.now(UTC)
        job.error_message = "Cancelled by user."
        db.jobs.update(job)

    # Reload and return (watcher may have already finalised)
    job = db.jobs.get(job_id)
    return {"job": _job_dict(job)}


@router.post("/projects/{project_id}/jobs/{job_id}/resume")
def resume_job(
    project_id: str,
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """
    Resume a paused job from its last completed phase.

    Re-launches ``run.py --from-phase <next_phase>`` using the same project
    path that was used originally.
    """
    require_project_admin(project_id, current_user, db)
    job = db.jobs.get(job_id)
    if not job or job.project_id != project_id:
        raise not_found("AnalysisJob", job_id)
    if job.status != "paused":
        raise HTTPException(400, detail={
            "code": "VALIDATION_ERROR",
            "message": "Job is not paused.",
            "status": 400,
        })

    # Determine which phase to resume from
    next_phase = max(
        (p.number for p in job.phases if p.status == "done"),
        default=0
    ) + 1
    next_phase = min(next_phase, 4)

    project = db.projects.get(project_id)
    root = _find_root()
    cpp_path = _default_project_path(project, root)
    extra_args = ["--from-phase", str(next_phase)]
    if job.layer_filter:
        extra_args += ["--selected-layer", job.layer_filter]

    job.status = "running"
    job.phase = next_phase
    job.phase_pct = 0
    job.current_activity = "Resuming pipeline…"
    db.jobs.update(job)

    try:
        executor.start(job.id, db, cpp_path, extra_args=extra_args)
    except Exception as exc:
        job.status = "failed"
        job.error_message = str(exc)
        job.completed_at = datetime.now(UTC)
        db.jobs.update(job)
        raise HTTPException(500, detail={
            "code": "SPAWN_FAILED",
            "message": str(exc),
            "status": 500,
        })

    return {"job": _job_dict(db.jobs.get(job_id))}


@router.post("/projects/{project_id}/jobs/{job_id}/reexport")
def reexport(
    project_id: str,
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """
    Re-run Phase 4 only (DOCX export) using the existing ``model/`` + ``output/``
    artifacts from this job.

    Useful when document settings or config have changed but the model is still
    current.  Spawns ``run.py --from-phase 4`` and returns immediately.
    """
    require_project_admin(project_id, current_user, db)
    job = db.jobs.get(job_id)
    if not job or job.project_id != project_id:
        raise not_found("AnalysisJob", job_id)
    if job.status not in ("complete", "failed"):
        raise bad_request("JOB_NOT_EXPORTABLE",
                          "Re-export is only allowed after a completed or failed job.")

    project = db.projects.get(project_id)
    root = _find_root()
    cpp_path = _default_project_path(project, root)

    # Create a new job record for the re-export
    now = datetime.now(UTC)
    new_job = AnalysisJob(
        id=f"job{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        commit_sha=job.commit_sha,
        version_id=job.version_id,
        reference_version_id=None,
        status="queued",
        pause_after_phase1=False,
        layer_filter=job.layer_filter,
        phase=4, phase_pct=0,
        current_activity="Queued — re-exporting DOCX…",
        activity_detail="",
        elapsed_seconds=0, eta_seconds=None,
        phases=[
            AnalysisPhase(1, "Parse C++",    "done", None),
            AnalysisPhase(2, "Derive Model", "done", None),
            AnalysisPhase(3, "Run Views",    "done", None),
            AnalysisPhase(4, "Export DOCX",  "pending", None),
        ],
        started_at=now, completed_at=None, error_message=None,
    )
    db.jobs.create(new_job)

    extra_args = ["--from-phase", "4"]
    if job.layer_filter:
        extra_args += ["--selected-layer", job.layer_filter]

    try:
        executor.start(new_job.id, db, cpp_path, extra_args=extra_args)
    except Exception as exc:
        new_job.status = "failed"
        new_job.error_message = str(exc)
        new_job.completed_at = datetime.now(UTC)
        db.jobs.update(new_job)

    return {
        "message": "Re-export started.",
        "job_id": new_job.id,
        "log_url": f"/api/v1/projects/{project_id}/jobs/{new_job.id}/logs",
    }


# ---------------------------------------------------------------------------
# SSE — live job events
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/jobs/{job_id}/events")
async def job_events(
    project_id: str,
    job_id: str,
    request: Request,
    db: InMemoryDatabase = Depends(get_db),
):
    """
    Server-Sent Events stream for live job progress.

    Polls the DB every 2 seconds (the executor watcher updates the DB every
    second, so clients always see near-real-time state).

    Events emitted: ``phase_update``, ``activity_update``, ``log_line``,
    ``job_complete``, ``job_failed``.
    """
    async def generator() -> AsyncIterator[dict]:
        tick = 0
        while True:
            if await request.is_disconnected():
                break
            job = db.jobs.get(job_id)
            if not job:
                yield {"event": "error", "data": json.dumps({"message": "Job not found"})}
                break

            yield {
                "event": "phase_update",
                "data": json.dumps({
                    "phase": job.phase,
                    "status": job.status,
                    "percent": job.phase_pct,
                }),
            }
            yield {
                "event": "activity_update",
                "data": json.dumps({
                    "activity": job.current_activity,
                    "detail": job.activity_detail,
                    "elapsed_seconds": job.elapsed_seconds,
                    "eta_seconds": job.eta_seconds,
                }),
            }
            # Tail a few log lines as log_line events
            if executor.is_running(job_id):
                for line in executor.get_log_tail(job_id, lines=3):
                    yield {
                        "event": "log_line",
                        "data": json.dumps({
                            "timestamp": datetime.now(UTC).isoformat(),
                            "text": line,
                            "color": "red" if " ERROR " in line else "green",
                        }),
                    }

            if job.status in ("complete", "failed", "cancelled"):
                event = "job_complete" if job.status == "complete" else "job_failed"
                yield {
                    "event": event,
                    "data": json.dumps({
                        "status": job.status,
                        "error_message": job.error_message,
                    }),
                }
                break

            tick += 1
            await asyncio.sleep(2)

    return EventSourceResponse(generator())


# ---------------------------------------------------------------------------
# Functions (visibility) — nested under jobs
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/jobs/{job_id}/functions")
def list_functions(
    project_id: str,
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_member(project_id, current_user, db)
    functions = db.functions.list_for_job(job_id)
    total = len(functions)
    hidden = sum(1 for f in functions if not f.is_visible)
    new_count = sum(1 for f in functions if f.is_new)
    return {
        "functions": [
            {
                "id": f.id, "name": f.name, "file_path": f.file_path,
                "layer": f.layer, "group": f.group,
                "is_visible": f.is_visible, "is_new": f.is_new,
                "description": f.description,
            }
            for f in functions
        ],
        "summary": {"total": total, "hidden": hidden, "new_since_last": new_count},
    }

