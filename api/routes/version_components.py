"""A version's components and the state of their documents (staged generation).

A version's model covers every component of the layers its run parsed; its documents are made per
component, by any number of runs. These routes are the web app's view of that, the same one as
`analyzer.py components` / `progress` / `export`:

    GET  /projects/{pid}/versions/{vid}/components            every component, its state, its
                                                              documents; and the latest run
    POST /projects/{pid}/versions/{vid}/documents/generate    make the documents of components
                                                              not generated yet (a job)
    POST /projects/{pid}/versions/{vid}/resume                carry on a run that stopped
                                                              before it finished (a job)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..db.in_memory import InMemoryDatabase
from ..db.session import get_db
from ..middleware.auth import get_current_user, require_project_admin, require_project_member
from ..models.domain import User
from ..services import pipeline_runner
from ..services.errors import conflict, not_found
from ..services.review_workflow import unprocessable
from ..services import version_components as vc

router = APIRouter(tags=["versions"])


def _version(db, project_id: str, version_id: str):
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    version = db.versions.get(version_id)
    if version is None or version.project_id != project_id:
        raise not_found("Version", version_id)
    return version


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def _run_view(db, version_id: str) -> tuple:
    """(the latest run of the version, whether a writer holds it now) -- (None, None) on a
    database that keeps neither (in-memory)."""
    engine = getattr(db, "_engine", None)
    vr = pipeline_runner._version_run_module() if engine is not None else None
    if vr is None:
        return None, None
    alive = vr.alive(version_id, engine=engine)
    row = vr.run_row(version_id, engine=engine)
    if row is None:
        return None, alive
    out = {k: _iso(row.get(k)) for k in (
        "command", "pid", "host", "outcome", "log_path", "started_at", "finished_at",
        "stage", "done", "total", "stage_started_at", "progress_at")}
    out["alive"] = alive
    # A run recorded as running whose process holds nothing any more was cut short.
    out["stopped"] = bool(row.get("outcome") == "running" and alive is False)
    return out, alive


@router.get("/projects/{project_id}/versions/{version_id}/components")
def list_components(project_id: str, version_id: str,
                    current_user: User = Depends(get_current_user),
                    db: InMemoryDatabase = Depends(get_db)) -> Dict[str, Any]:
    """Every component of the layers the version parsed: `state` (generated | generating |
    waiting | stopped | failed | not_requested), its documents with their review status, and
    the version's latest run (`run`: command, running or stopped, the current stage's progress).
    """
    require_project_member(project_id, current_user, db)
    version = _version(db, project_id, version_id)
    run, alive = _run_view(db, version.id)
    view = vc.components_view(db, version, alive=alive)
    try:
        resume = vc.resume_action(db, version, view=view, alive=alive)
    except Exception:                                   # noqa: BLE001 - the list still answers
        resume = "nothing"
    # The web job at work on the version now, newest first: what the panel's Stop cancels
    # (`POST /jobs/{id}/cancel`). A Components -> Generate job is never "the project's run"
    # (`jobs/current`), so the Overview's Cancel does not reach it.
    active = next((j for j in db.jobs.list_for_version(version.id)
                   if j.status in ("queued", "running", "paused")), None)
    return {
        "version_id": version.id,
        "components": [{**c, **{k: _iso(c[k]) for k in ("requested_at", "started_at", "finished_at")}}
                       for c in view],
        "counts": vc.counts(view),
        "run": run,
        # What Resume would do now (`POST .../resume`): regenerate | derive | export | close when
        # a run stopped before it finished; busy while one is at work; nothing otherwise.
        "resume_action": resume,
        "job": ({"id": active.id, "mode": getattr(active, "mode", None) or "auto",
                 "status": active.status} if active is not None else None),
    }


@router.post("/projects/{project_id}/versions/{version_id}/resume", status_code=202)
def resume_version(project_id: str, version_id: str,
                   current_user: User = Depends(get_current_user),
                   db: InMemoryDatabase = Depends(get_db)) -> Dict[str, Any]:
    """Carry on a version whose run stopped before it finished (the machine restarted, the
    process was killed, some components failed): `analyzer.py resume` in the background, as a
    job -- the version's own generation job when that one did not finish, else a job of its own.
    Follow it with `GET /jobs/{job_id}`. 409: VERSION_BUSY (a run is at work on it), RUN_ACTIVE
    (one of this server's jobs is), NOTHING_TO_RESUME, NO_BACKGROUND_RUNS (no database).
    """
    require_project_admin(project_id, current_user, db)
    version = _version(db, project_id, version_id)
    try:
        job = pipeline_runner.start_resume(db, version)
    except pipeline_runner.ReexportRefused as exc:
        detail = {"code": exc.code, "message": str(exc), "status": exc.status}
        if exc.job_id:
            detail["job_id"] = exc.job_id
        raise HTTPException(status_code=exc.status, detail=detail)
    return {"job_id": job.id, "status": job.status, "version_id": version.id}


class GenerateComponentsRequest(BaseModel):
    components: List[str]


@router.post("/projects/{project_id}/versions/{version_id}/documents/generate",
             status_code=202)
def generate_components(project_id: str, version_id: str, body: GenerateComponentsRequest,
                        current_user: User = Depends(get_current_user),
                        db: InMemoryDatabase = Depends(get_db)) -> Dict[str, Any]:
    """Make the documents of components the version has not generated yet: Phases 3-4 from its
    stored model, into this version, as a job (`mode: "export"`; follow it with
    `GET /jobs/{job_id}`). A component already generated is skipped (`skipped`); one outside the
    layers the version parsed is 422; nothing left to make is 409.
    """
    require_project_admin(project_id, current_user, db)
    version = _version(db, project_id, version_id)
    _, alive = _run_view(db, version.id)
    view = vc.components_view(db, version, alive=alive)
    if not any(c["in_model"] for c in view):
        raise conflict("NO_MODEL", f"Version '{version.id}' has no model to make documents from: "
                                   f"its run did not finish Phase 2.")
    found, problems = vc.resolve(view, body.components)
    if problems:
        raise unprocessable("INVALID_COMPONENTS", "; ".join(problems))
    todo, skipped = vc.export_targets(view, found)
    if not todo:
        raise conflict("NOTHING_TO_GENERATE",
                       f"Every component asked for has its documents already: "
                       f"{', '.join(skipped) or 'none'}. A re-export makes them again.")
    try:
        job = pipeline_runner.start_export(db, version, todo)
    except pipeline_runner.ReexportRefused as exc:
        detail = {"code": exc.code, "message": str(exc), "status": exc.status}
        if exc.job_id:
            detail["job_id"] = exc.job_id
        raise HTTPException(status_code=exc.status, detail=detail)
    return {"job_id": job.id, "status": job.status, "version_id": version.id,
            "components": todo, "skipped": skipped}
