"""The job queues: what waits and runs, the limits, the held jobs, the record
(docs/spec/JOB_SCHEDULING_SPEC.md REQ-JS-04, 18, 30-35; docs/design/JOB_SCHEDULING_DESIGN.md §13).

Submitting, pausing, resuming and cancelling a job are the job routes' (`routes/jobs.py`,
`routes/version_components.py`); these are the views and the queue-wide actions. Every refusal is
`detail: {code, message, status, ...}`, as the web app reads it (REQ-JS-35).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..db.in_memory import InMemoryDatabase
from ..db.session import get_db
from ..middleware.auth import (get_current_user, require_project_admin, require_project_member,
                               require_superuser)
from ..models.domain import User
from ..services import job_queue
from ..services.errors import not_found

router = APIRouter(tags=["queues"])


def _project(db: Any, project_id: str) -> Any:
    project = db.projects.get(project_id)
    if project is None:
        raise not_found("Project", project_id)
    return project


def _refused(exc: job_queue.JobRefused) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.detail())


@router.get("/projects/{project_id}/queues")
def project_queues(project_id: str, current_user: User = Depends(get_current_user),
                   db: InMemoryDatabase = Depends(get_db)) -> Dict[str, Any]:
    """The project's two lanes (REQ-JS-30): `lanes.generation` and `lanes.update`, each with its
    `limit`, the job holding it (`active`: running or paused) and the waiting ones in their order
    (`position`, `estimated_start`, `current_activity`, `flags`); `held`; the server's `cap`."""
    _project(db, project_id)
    require_project_member(project_id, current_user, db)
    return job_queue.queues(db, project_id)


@router.get("/projects/{project_id}/queues/preview")
def preview(project_id: str, lane: str = Query("generation", description="generation | update"),
            current_user: User = Depends(get_current_user),
            db: InMemoryDatabase = Depends(get_db)) -> Dict[str, Any]:
    """What a submit to `lane` would get now (REQ-JS-31): `answer` start | wait | refuse, with
    `message` -- "Starts now", "Waits as #2 — about 3 h", "Refused: ..." -- and, waiting,
    `position` and `estimated_start`; refused, the jobs in the way."""
    _project(db, project_id)
    require_project_member(project_id, current_user, db)
    try:
        return job_queue.preview(db, project_id, lane)
    except job_queue.JobRefused as exc:
        raise _refused(exc)


@router.get("/projects/{project_id}/queues/events")
def queue_events(project_id: str, limit: int = Query(100, ge=1, le=500),
                 current_user: User = Depends(get_current_user),
                 db: InMemoryDatabase = Depends(get_db)) -> Dict[str, Any]:
    """The record (REQ-JS-33), newest first: who submitted, started, paused, resumed, cancelled or
    removed which job, changed a priority or the limits, held or released jobs -- and when."""
    _project(db, project_id)
    require_project_admin(project_id, current_user, db)
    return {"events": [{"id": e.id, "job_id": e.job_id, "kind": e.kind, "actor_id": e.actor_id,
                        "at": e.at.isoformat() if e.at else None, "detail": e.detail or {}}
                       for e in db.job_events.list_for_project(project_id, limit=limit)]}


class LimitsRequest(BaseModel):
    generation_limit: Optional[int] = Field(None, description="1-50: running or paused + waiting")
    update_limit: Optional[int] = Field(None, description="1-50: running + waiting")


@router.patch("/projects/{project_id}/job-limits")
def change_limits(project_id: str, body: LimitsRequest,
                  current_user: User = Depends(get_current_user),
                  db: InMemoryDatabase = Depends(get_db)) -> Dict[str, Any]:
    """A project's two limits (REQ-JS-04) -- its admins' and a super admin's. Lowering one removes
    nothing already accepted. 422 `INVALID_LIMIT`."""
    project = _project(db, project_id)
    require_project_admin(project_id, current_user, db)
    try:
        project = job_queue.set_limits(db, project, current_user.id,
                                       generation_limit=body.generation_limit,
                                       update_limit=body.update_limit)
    except job_queue.JobRefused as exc:
        raise _refused(exc)
    return {"project_id": project.id,
            "generation_limit": job_queue.limit_of(project, job_queue.GENERATION),
            "update_limit": job_queue.limit_of(project, job_queue.UPDATE)}


@router.get("/queues")
def every_queue(current_user: User = Depends(require_superuser),
                db: InMemoryDatabase = Depends(get_db)) -> Dict[str, Any]:
    """Every project with a job in a lane (REQ-JS-30), the server's cap and how many are held --
    a super admin's view."""
    return job_queue.all_queues(db)


class HeldRequest(BaseModel):
    project_id: Optional[str] = Field(None, description="one project's held jobs; absent: all")
    remove: Union[List[str], str] = Field(
        default_factory=list,
        description='the held jobs to clear (ids), or "all"; the rest start, in their order')


@router.post("/queues/held")
def release_held(body: HeldRequest, current_user: User = Depends(require_superuser),
                 db: InMemoryDatabase = Depends(get_db)) -> Dict[str, Any]:
    """After a restart (REQ-JS-18): start all held jobs (`remove: []`), clear all
    (`remove: "all"`), or clear some and start the rest (`remove: [ids]`) -- of one project or of
    all. 422 `NOT_HELD` for an id that is not a held job."""
    if isinstance(body.remove, str) and body.remove != "all":
        raise HTTPException(status_code=422, detail={
            "code": "VALIDATION_ERROR", "status": 422,
            "message": 'remove is a list of job ids, or "all".'})
    if body.project_id:
        _project(db, body.project_id)
    try:
        return job_queue.release_held(db, current_user.id, project_id=body.project_id,
                                      remove=body.remove)
    except job_queue.JobRefused as exc:
        raise _refused(exc)
