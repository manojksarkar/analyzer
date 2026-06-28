"""Analysis Jobs routes — /api/v1/projects/:id/jobs/*"""
from __future__ import annotations
import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ..db.session import get_db
from ..db.in_memory import InMemoryDatabase
from ..middleware.auth import get_current_user, require_project_admin, require_project_member
from ..models.domain import User, AnalysisJob, AnalysisPhase
from ..services.errors import not_found, conflict
from ..services import pipeline_runner
from ..schemas import (
    StartJobResponse, JobResponse, CurrentJobResponse,
    FunctionListResponse, ReexportResponse,
)

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
    # "auto" = pick the nearest-ancestor completed version as the incremental baseline
    # (mirrors the standalone /generate decision); "full" = force a full generation.
    # An explicit reference_version_id still wins under "auto".
    mode: str = "auto"
    # {"type": "project|group|component", "names": [...]} — maps to run.py's
    # --selected-group / --selected-component (mutually exclusive with layer_filter).
    scope: Optional[dict] = None
    no_llm: bool = False                       # disable LLM descriptions/behaviour/summaries
    data_dict_id: Optional[str] = None         # resolved to workspaces/<pid>/datadict/<id>.csv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
        "version_tag": job.version_tag,
        "reference_version_id": job.reference_version_id,
        "mode": getattr(job, "mode", "auto"),
        "decision": getattr(job, "decision", None),
        "baseline_commit": getattr(job, "baseline_commit", None),
        "scope": getattr(job, "scope", None),
        "no_llm": getattr(job, "no_llm", False),
        "data_dict_id": getattr(job, "data_dict_id", None),
        "started_at": job.started_at.isoformat(),
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "error_message": job.error_message,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/jobs", status_code=202,
             responses={202: {"model": StartJobResponse}})
def start_job(
    project_id: str,
    body: StartJobRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    project = db.projects.get(project_id)
    if not project:
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
    # The branch comes from the chosen commit (falls back to the project default).
    commit = db.commits.get(project_id, body.commit_sha)
    branch = commit.branch if commit else (project.default_branch or "main")
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
        phase=1, phase_pct=0,
        current_activity="Queued — waiting for worker…",
        activity_detail="",
        elapsed_seconds=0, eta_seconds=None,
        phases=[
            AnalysisPhase(1, "Parse C++",    "pending", None),
            AnalysisPhase(2, "Derive Model", "pending", None),
            AnalysisPhase(3, "Run Views",    "pending", None),
            AnalysisPhase(4, "Export DOCX",  "pending", None),
        ],
        started_at=now, completed_at=None, error_message=None,
        branch=branch, version_tag=(body.version_tag or None),
        mode=(body.mode or "auto"),
        scope=body.scope, no_llm=bool(body.no_llm), data_dict_id=body.data_dict_id,
    )
    db.jobs.create(job)
    pipeline_runner.start(db, job.id)
    return {"job_id": job.id, "status": job.status}


@router.get("/projects/{project_id}/baseline-preview")
def baseline_preview(
    project_id: str,
    commit: str,
    base_version_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """Preview the incremental baseline decision for `commit` before starting a job
    (read-only — no checkout/clone). Mirrors the standalone /generate/preview: returns
    the auto/chosen baseline, ancestor/nearest flags, changed-file count, decision, warnings."""
    project = db.projects.get(project_id)
    if not project:
        raise not_found("Project", project_id)
    require_project_member(project_id, current_user, db)
    return pipeline_runner.preview_baseline(db, project_id, commit, base_version_id)


@router.get("/projects/{project_id}/jobs/current",
            responses={200: {"model": CurrentJobResponse}})
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


@router.get("/projects/{project_id}/jobs/{job_id}",
            responses={200: {"model": JobResponse}})
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


@router.post("/projects/{project_id}/jobs/{job_id}/cancel",
             responses={200: {"model": JobResponse}})
def cancel_job(
    project_id: str,
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    require_project_admin(project_id, current_user, db)
    job = db.jobs.get(job_id)
    if not job or job.project_id != project_id:
        raise not_found("AnalysisJob", job_id)
    job.status = "cancelled"
    job.completed_at = datetime.now(UTC)
    db.jobs.update(job)
    pipeline_runner.cancel_subprocess(job_id)
    return {"job": _job_dict(job)}


@router.post("/projects/{project_id}/jobs/{job_id}/resume",
             responses={200: {"model": JobResponse}})
def resume_job(
    project_id: str,
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    require_project_admin(project_id, current_user, db)
    job = db.jobs.get(job_id)
    if not job or job.project_id != project_id:
        raise not_found("AnalysisJob", job_id)
    if job.status != "paused":
        raise HTTPException(400, detail={"code": "VALIDATION_ERROR",
                                         "message": "Job is not paused.", "status": 400})
    job.status = "running"
    db.jobs.update(job)
    pipeline_runner.signal_resume(job_id)
    return {"job": _job_dict(job)}


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
    Emits: phase_update, activity_update, log_line, job_complete, job_failed.
    """
    async def generator() -> AsyncIterator[dict]:
        job = db.jobs.get(job_id)
        if not job:
            yield {"event": "error", "data": json.dumps({"message": "Job not found"})}
            return
        log_cursor = 0
        while True:
            if await request.is_disconnected():
                break
            job = db.jobs.get(job_id)
            if not job:
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
                }),
            }
            # Drain real log lines from the pipeline runner
            new_lines, log_cursor = pipeline_runner.get_log_lines(job_id, log_cursor)
            for text in new_lines:
                yield {
                    "event": "log_line",
                    "data": json.dumps({
                        "timestamp": datetime.now(UTC).isoformat(),
                        "text": text,
                        "color": "green",
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
            await asyncio.sleep(2)

    return EventSourceResponse(generator())


# ---------------------------------------------------------------------------
# Functions (visibility) — nested under jobs
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/jobs/{job_id}/functions",
            responses={200: {"model": FunctionListResponse}})
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


@router.post("/projects/{project_id}/jobs/{job_id}/reexport",
             responses={200: {"model": ReexportResponse}})
def reexport(
    project_id: str,
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    require_project_admin(project_id, current_user, db)
    job = db.jobs.get(job_id)
    if not job or job.project_id != project_id:
        raise not_found("AnalysisJob", job_id)
    pipeline_runner.reexport(db, job_id)
    return {"message": "Re-export queued.", "job_id": job_id}
