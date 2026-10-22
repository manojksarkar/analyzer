"""Analysis Jobs routes — /api/v1/projects/:id/jobs/*"""
from __future__ import annotations
import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sse_starlette.sse import EventSourceResponse

from ..db.session import get_db
from ..db.in_memory import InMemoryDatabase
from ..middleware.auth import get_current_user, require_project_admin, require_project_member
from ..models.domain import (User, AnalysisJob, AnalysisPhase, REEXPORT_MODE, EXPORT_MODE,
                             RENDER_MODES, ACTIVE_JOB_STATUSES)
from ..services.errors import not_found, conflict, bad_request
from ..services import job_queue, pipeline_runner
from ..schemas import (
    StartJobResponse, JobResponse, CurrentJobResponse,
    FunctionListResponse, ReexportResponse, ReexportVersionResponse,
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
    # {"type": "project|layer|group|component", "names": [...]} — maps to run.py's
    # --selected-layer / --selected-group / --selected-component (mutually exclusive with
    # layer_filter). Checked against the project's architecture before anything is reserved.
    scope: Optional[dict] = Field(
        None, description=(
            '{"type": "project|layer|group|component", "names": [...]}. Name a group or a '
            'component by its LAYER-QUALIFIED id, "Layer1.My Sample" / "Layer1.Sample Core": '
            'a bare name that two layers both use is ambiguous, and is refused with 400 '
            'INVALID_SCOPE naming the candidates. A layer by its name, "Layer1". Omit for the '
            'whole project.'))
    no_llm: bool = False                       # disable LLM descriptions/behaviour/summaries
    data_dict_id: Optional[str] = None         # resolved to workspaces/<pid>/datadict/<id>.csv
    # M4.4 opt-in: in an incremental run, re-parse only the affected TUs and merge into the
    # baseline parser snapshot instead of a full Phase-1 parse (pays off on large repos).
    narrowed_parse: bool = True         # opt-OUT: send false to force a full re-parse
    # Its order in the project's generation lane: high | normal | low. A super admin's to set
    # (docs/spec/JOB_SCHEDULING_SPEC.md REQ-JS-11); anyone else sends normal or nothing.
    priority: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _started_by(job: AnalysisJob, db) -> Optional[dict]:
    """Who started the job, as a user ref -- or None (a generation, or a job from before 0018)."""
    uid = getattr(job, "started_by", None)
    u = db.users.get_by_id(uid) if (uid and db is not None) else None
    return {"user_id": u.id, "name": u.name, "initials": u.initials} if u is not None else None


def _job_dict(job: AnalysisJob, db=None) -> dict:
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
        "narrowed_parse": getattr(job, "narrowed_parse", True),
        # When it started RUNNING -- null while it waits in its lane.
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "error_message": job.error_message,
        # Who started it and why (docs/design/WORD_FILE_UPDATES.md §4.1): an update's
        # `update` | `rebuild` | `submit`, an export's `export` | `resume`; null for a generation.
        "started_by": _started_by(job, db),
        "reason": getattr(job, "reason", None),
        # The queue (docs/spec/JOB_SCHEDULING_SPEC.md REQ-JS-30): lane, priority, place,
        # position and estimated start while it waits, where it runs, its alive signal, flags.
        **_queue_fields(job, db),
    }


def _queue_fields(job: AnalysisJob, db) -> dict:
    try:
        return job_queue.job_queue_fields(db, job) if db is not None else {}
    except Exception:                                   # noqa: BLE001 - the job still shows
        return {"lane": job_queue.lane_of(job)}


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
    request_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """Submit a generation. 202 with the answer (docs/spec/JOB_SCHEDULING_SPEC.md REQ-JS-06,
    REQ-JS-35): `status` running | queued | held, `position`, `estimated_start`, `ahead`, and a
    `message` -- or 409 `LANE_FULL` / `DUPLICATE_JOB` naming the jobs in the way. A request sent
    again with the same `Idempotency-Key` answers the job it made the first time (REQ-JS-09)."""
    project = db.projects.get(project_id)
    if not project:
        raise not_found("Project", project_id)
    require_project_admin(project_id, current_user, db)
    request_key = (request_key or "").strip()[:200] or None
    if request_key:
        first = db.jobs.find_by_request_key(project_id, request_key)
        if first is not None:
            answer = job_queue.answer_for(db, first)
            return {"job_id": first.id, "status": first.status, **answer.as_dict(),
                    "job": _job_dict(first, db)}
    # A project onboarded with `analyzer.py onboard` has no architecture in the database: its
    # layers are in workspaces/<pid>/config.json, which onboarding wrote. A run from here builds
    # that file from the database instead, so it would REPLACE the project's config with the
    # built-in sample project's layers; and `_make_documents` creates documents only for the
    # components declared here, so the run would produce none. Refused before anything is
    # reserved or written.
    if not (project.architecture_layers or []):
        raise conflict(
            "NO_ARCHITECTURE",
            f"Project '{project_id}' has no architecture in the database — it was onboarded with "
            f"`analyzer.py onboard`, so its layers are in workspaces/{project_id}/config.json. A run "
            f"started here would replace that file and create no documents. Generate it with "
            f"`python analyzer.py generate --project-id {project_id} --version-id <id> "
            f"--commit <sha>`, or create the project in the web app with its architecture.")
    # Version identity (D-3): the version is REQUIRED and UNIQUE within the project.
    # No auto-generated name, no silent "-1" rename — a duplicate is rejected. Checked
    # before the active-job guard so a malformed request fails as 400, deterministically.
    version_name = (body.version_tag or "").strip()
    if not version_name:
        raise bad_request("A version name is required.")
    if (body.mode or "").strip() == EXPORT_MODE:
        raise bad_request("Components are added to a version with POST "
                          "/projects/{project_id}/versions/{version_id}/documents/generate, "
                          "not as a new job.")
    if (body.mode or "").strip() == REEXPORT_MODE:
        raise bad_request("A re-export is started with POST "
                          "/projects/{project_id}/versions/{version_id}/reexport, not as a new job.")
    # The scope, resolved now as the run will resolve it -- an unknown or ambiguous name used to
    # be accepted and to stop the run in Phase 1, after the version tag had been taken.
    problem = pipeline_runner.scope_problem(project.architecture_layers, body.scope)
    # `layer_filter` is what the run selects when the scope names nothing (no scope, a project
    # scope, empty names -- `_build_cmd`): checked the same way, before the tag is taken.
    named = body.scope.get("names") if isinstance(body.scope, dict) else None
    stype = (body.scope.get("type") if isinstance(body.scope, dict) else None) or "project"
    layer_filter = (body.layer_filter or "").strip()
    if not problem and layer_filter and (stype == "project" or not named):
        problem = pipeline_runner.scope_problem(project.architecture_layers,
                                                {"type": "layer", "names": [layer_filter]})
    if problem:
        message, candidates = problem
        raise HTTPException(status_code=400, detail={
            "code": "INVALID_SCOPE", "message": message, "status": 400,
            "candidates": candidates})
    if db.versions.get_by_tag(project_id, version_name):
        raise conflict("VERSION_EXISTS",
                       f"Version '{version_name}' already exists in this project.")
    # The baseline is one of THIS project's versions -- 976ee0f's rule, "resolved inside its
    # project, never another project's". Found by id, else by this project's version name (the
    # CLI's --base-version takes either), and stored as the id. It used to be passed on
    # unchecked: the engine refused a foreign id and chose a baseline itself, but
    # `_load_and_register_functions` read that version's functions to mark which ones are new
    # -- another project's model.
    reference_version_id = None
    if (body.reference_version_id or "").strip():
        ref = body.reference_version_id.strip()
        base = db.versions.get(ref)
        if base is None or base.project_id != project_id:
            base = db.versions.get_by_tag(project_id, ref)
        if base is None:
            raise not_found("Version", f"'{ref}' in project '{project_id}'")
        reference_version_id = base.id
    # A job's own data dictionary applies to every layer (`--data-dict`). The project's
    # dictionaries reach the run through its cores - each layer takes its core's - so a job that
    # names none adds none (services/project_cores.py; a project from before cores is one core).
    data_dict_id = (body.data_dict_id or "").strip() or None
    # Another generation of the project running or waiting is no refusal any more: this one waits
    # its turn in the project's generation lane (docs/spec/JOB_SCHEDULING_SPEC.md REQ-JS-06).
    priority = (body.priority or "normal").strip().lower()
    if priority not in job_queue.PRIORITY:
        raise bad_request("priority is high, normal or low.")
    if priority != "normal" and not getattr(current_user, "is_superuser", False):
        raise HTTPException(status_code=403, detail={
            "code": "FORBIDDEN", "status": 403,
            "message": "Only a super admin sets a job's priority (REQ-JS-11)."})
    # Checked now, and again when the job starts (REQ-JS-07): a job that waits hours must not fail
    # on a mistyped commit, or on a configuration that does not build.
    if not pipeline_runner.commit_known(db, project, body.commit_sha):
        raise HTTPException(status_code=422, detail={
            "code": "UNKNOWN_COMMIT", "status": 422,
            "message": f"Commit '{body.commit_sha}' is not one of project '{project_id}''s "
                       f"commits. Pick it from the project's commit list — synced from its "
                       f"repository — or check the SHA."})
    problem = pipeline_runner.config_problem(project, no_llm=bool(body.no_llm))
    if problem:
        raise conflict("CONFIG_INVALID", f"The project's configuration does not build: {problem}")
    # Version identity (D-3 / PG-3): claim the real `ver…` id NOW so it is the engine's version
    # identity (`--version`) for the whole run.
    version_id = f"ver{uuid.uuid4().hex[:8]}"
    # The branch comes from the chosen commit (falls back to the project default).
    commit = db.commits.get(project_id, body.commit_sha)
    branch = commit.branch if commit else (project.default_branch or "main")
    now = datetime.now(UTC)
    job = AnalysisJob(
        id=f"job{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        commit_sha=body.commit_sha,
        version_id=version_id,
        reference_version_id=reference_version_id,
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
        branch=branch, version_tag=version_name,
        mode=(body.mode or "auto"),
        scope=body.scope, no_llm=bool(body.no_llm), data_dict_id=data_dict_id,
        narrowed_parse=bool(body.narrowed_parse),
    )
    job.started_by = current_user.id
    # Reserve the version row (status 'draft') BEFORE inserting the job: analysis_jobs.version_id
    # is a FK to versions.id, so the job may only reference a version that already exists. The
    # name is taken while the job waits (REQ-JS-08). The engine writes its per-version rows under
    # this same id, _make_version finalizes it at completion, and a removed, failed or cancelled
    # job deletes its draft (_release_draft_version) — so it leaves no orphan.
    try:
        pipeline_runner._reserve_version(db, job, project)
    except IntegrityError:
        # The name was taken since it was checked: the same request sent twice at once (a double
        # click). The first one's answer when it carries the same key (REQ-JS-09), else the name's
        # refusal -- not a server error.
        first = db.jobs.find_by_request_key(project_id, request_key) if request_key else None
        if first is not None:
            answer = job_queue.answer_for(db, first)
            return {"job_id": first.id, "status": first.status, **answer.as_dict(),
                    "job": _job_dict(first, db)}
        raise conflict("VERSION_EXISTS",
                       f"Version '{version_name}' already exists in this project.")
    try:
        answer = job_queue.enqueue(db, job, actor_id=current_user.id, request_key=request_key,
                                   priority=priority)
    except BaseException as exc:
        # Refused, or the insert failed: the just-reserved draft goes, so its name is free.
        _v = db.versions.get(version_id)
        if _v is not None and getattr(_v, "status", None) == "draft":
            try:
                pipeline_runner.delete_version(db, version_id, only_draft=True)
            except Exception:                              # best-effort cleanup
                pass
        if isinstance(exc, job_queue.JobRefused):
            raise HTTPException(status_code=exc.status, detail=exc.detail())
        raise
    pipeline_runner.note_request_job(answer.job)
    return {"job_id": answer.job.id, "status": answer.job.status, **answer.as_dict(),
            "job": _job_dict(answer.job, db)}


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
    return {"job": _job_dict(job, db)}


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
    return {"job": _job_dict(job, db)}


def _project_job(db, project_id: str, job_id: str) -> AnalysisJob:
    job = db.jobs.get(job_id)
    if not job or job.project_id != project_id:
        raise not_found("AnalysisJob", job_id)
    return job


def _refused(exc: "job_queue.JobRefused") -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.detail())


@router.post("/projects/{project_id}/jobs/{job_id}/cancel",
             responses={200: {"model": JobResponse}})
def cancel_job(
    project_id: str,
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """Cancel a running or paused job, or remove a waiting one (REQ-JS-25, 26): the submitter
    their own, a project admin any of the project's, a super admin any. A CLI run is the
    developer's to stop (409 `CLI_RUN`)."""
    require_project_member(project_id, current_user, db)
    job = _project_job(db, project_id, job_id)
    if not job_queue.may_act(db, current_user, job):
        raise HTTPException(status_code=403, detail={
            "code": "FORBIDDEN", "status": 403,
            "message": "You cancel or remove the jobs you submitted; a project admin any of "
                       "the project's."})
    if job.status in job_queue.ENDED:
        # A page's view of the job can be seconds old: cancelling a run that has just stopped
        # -- its work kept for `resume` -- would have deleted that work.
        raise conflict("JOB_FINISHED", f"Job {job_id} has already ended ({job.status}).")
    try:
        job = job_queue.cancel(db, job, current_user)
    except job_queue.JobRefused as exc:
        raise _refused(exc)
    return {"job": _job_dict(job, db)}


@router.post("/projects/{project_id}/jobs/{job_id}/pause",
             responses={200: {"model": JobResponse}})
def pause_job(
    project_id: str,
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """Pause a running generation at its next safe point (REQ-JS-22). 409 `NOT_PAUSABLE` for an
    update or a waiting job, `CLI_RUN` for a command-line run."""
    require_project_admin(project_id, current_user, db)
    try:
        job = job_queue.request_pause(db, _project_job(db, project_id, job_id), current_user.id)
    except job_queue.JobRefused as exc:
        raise _refused(exc)
    return {"job": _job_dict(job, db)}


@router.post("/projects/{project_id}/jobs/{job_id}/resume",
             responses={200: {"model": JobResponse}})
def resume_job(
    project_id: str,
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """Resume a paused job: it takes the next free server slot, before waiting generations
    (REQ-JS-24). 409 `NOT_PAUSED`."""
    require_project_admin(project_id, current_user, db)
    try:
        job = job_queue.request_resume(db, _project_job(db, project_id, job_id), current_user.id)
    except job_queue.JobRefused as exc:
        raise _refused(exc)
    return {"job": _job_dict(job, db)}


class JobChangeRequest(BaseModel):
    priority: str = Field(..., description="high | normal | low")


@router.patch("/projects/{project_id}/jobs/{job_id}", responses={200: {"model": JobResponse}})
def change_job(
    project_id: str,
    job_id: str,
    body: JobChangeRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """A waiting generation's priority (REQ-JS-11) -- a super admin's."""
    if not getattr(current_user, "is_superuser", False):
        raise HTTPException(status_code=403, detail={
            "code": "FORBIDDEN", "status": 403,
            "message": "Only a super admin sets a job's priority."})
    try:
        job = job_queue.set_priority(db, _project_job(db, project_id, job_id),
                                     (body.priority or "").strip().lower(), current_user.id)
    except job_queue.JobRefused as exc:
        raise _refused(exc)
    return {"job": _job_dict(job, db)}


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
                "class_name": f.class_name,
            }
            for f in functions
        ],
        "summary": {"total": total, "hidden": hidden, "new_since_last": new_count},
    }


def _start_reexport(db, version, components=None, *, started_by=None):
    """`pipeline_runner.start_reexport`, with its refusals as HTTP errors. A refusal caused by
    another job names it (`job_id`), so a client can follow that job instead of guessing."""
    try:
        return pipeline_runner.start_reexport(db, version, components, started_by=started_by,
                                              reason="rebuild")
    except pipeline_runner.ReexportRefused as exc:
        detail = {"code": exc.code, "message": str(exc), "status": exc.status, **exc.extra}
        if exc.job_id:
            detail["job_id"] = exc.job_id
        raise HTTPException(status_code=exc.status, detail=detail)


class ReexportComponentsRequest(BaseModel):
    """docs/design/WORD_FILE_UPDATES.md §4.1. Every field optional."""
    # `out_of_date`: the components whose Word files are out of date (the server's own rule);
    # `all`: every component with documents (Rebuild all, admins). Absent: `all`, as before.
    scope: Optional[str] = None
    components: Optional[list[str]] = None
    # The document the caller has open: a developer may update its component too.
    document_id: Optional[str] = None


@router.post("/projects/{project_id}/versions/{version_id}/reexport", status_code=202,
             responses={202: {"model": ReexportVersionResponse},
                        200: {"model": ReexportVersionResponse}})
def reexport_version(
    project_id: str,
    version_id: str,
    body: Optional[ReexportComponentsRequest] = None,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
    request_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """Update ONE version's Word files -- any version with documents, not only the newest,
    whether the web app or the command line made it (docs/design/WORD_FILE_UPDATES.md §4.1).

    Body `{"scope": "out_of_date" | "all", "components": [...], "document_id": "..."}`, every
    field optional. `out_of_date`: the components whose Word files are out of date (of
    `components`, when given) -- any member: an admin all of them, a developer those of the
    documents they review plus `document_id`'s (403 `NOT_YOUR_DOCUMENTS` beyond). `all` (the
    default): every component with documents, or exactly `components` -- admins only.

    202 with a new job (`mode: "reexport"`); 200 `joined: true` when a running update covers the
    request (follow its `job_id`); 200 `{"job_id": null, "status": "up_to_date"}` when nothing
    asked for is out of date. 409 `REEXPORT_RUNNING` (`job_id`, `scope`, `components`) while
    another update or export of the version runs; 409 `VERSION_BUSY` (`writer`) while a
    generation or a command-line run holds it; 409 `NO_DOCUMENTS` / `VERSION_NOT_READY`; 422
    `INVALID_COMPONENTS`. Follow the job with `GET /jobs/{job_id}` or its `/events` stream.
    """
    require_project_member(project_id, current_user, db)
    version = db.versions.get(version_id)
    if not version or version.project_id != project_id:
        raise not_found("Version", version_id)
    from ..services import word_files
    status, out = word_files.start_update(
        db, version, current_user, scope=(body.scope if body else None),
        components=(body.components if body else None) or None,
        document_id=(body.document_id if body else None) or None,
        request_key=(request_key or "").strip()[:200] or None)
    return JSONResponse(status_code=status, content=out)


@router.post("/projects/{project_id}/jobs/{job_id}/reexport",
             responses={200: {"model": ReexportResponse}})
def reexport(
    project_id: str,
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """Re-export the version this job produced. Kept for existing callers;
    `POST /projects/{project_id}/versions/{version_id}/reexport` is the same thing addressed by
    version. `job_id` in the answer is the NEW re-export job -- the one to follow."""
    require_project_admin(project_id, current_user, db)
    job = db.jobs.get(job_id)
    if not job or job.project_id != project_id:
        raise not_found("AnalysisJob", job_id)
    version = db.versions.get(job.version_id) if job.version_id else None
    if not version:
        raise not_found("Version", job.version_id or "(none)")
    started = _start_reexport(db, version, started_by=current_user.id)
    return {"message": "Re-export queued.", "job_id": started.id}
