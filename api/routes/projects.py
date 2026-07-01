"""Projects routes — /api/v1/projects/*"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import Any, Optional

from ..db.session import get_db
from ..db.in_memory import InMemoryDatabase
from ..middleware.auth import get_current_user, require_project_admin, require_project_member
from ..models.domain import User, Project, ProjectMember, AccessRequest
from ..services.errors import not_found, forbidden, conflict
from ..schemas import (
    ProjectResponse, ProjectListResponse, ProjectSearchResponse,
    AccessRequestResponse, AccessRequestListResponse,
)

router = APIRouter(prefix="/projects", tags=["projects"])
UTC = timezone.utc


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CreateProjectRequest(BaseModel):
    name: str
    client: str
    compliance_standard: str
    repo_url: str
    repo_provider: str = "github"
    default_branch: str = "main"
    access_token: Optional[str] = None
    build_config: dict[str, Any] = {}
    architecture_layers: list[dict[str, Any]] = []
    team: list[dict[str, str]] = []


class UpdateProjectRequest(BaseModel):
    name: Optional[str] = None
    client: Optional[str] = None
    status: Optional[str] = None


class AccessRequestAction(BaseModel):
    action: str   # "approve" | "deny"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _project_view(project: Project, db: InMemoryDatabase, user_id: str) -> dict:
    member = db.members.get_member(project.id, user_id)
    versions = db.versions.list_for_project(project.id)
    latest = max(versions, key=lambda v: v.created_at, default=None)
    docs, total = db.documents.list_for_project(project.id)
    # Scope the dashboard doc counts to the version actually on display (latest),
    # not the sum across every run. latest is None for a project with no versions.
    stats = db.documents.get_stats(project.id, version_id=latest.id if latest else None)
    job = db.jobs.get_current(project.id)
    return {
        "id": project.id,
        "name": project.name,
        "client": project.client,
        "compliance_standard": project.compliance_standard,
        "status": project.status,
        "last_run_at": job.started_at.isoformat() if job else None,
        "current_version": latest.tag if latest else None,
        "doc_counts": stats,
        "team_count": len(db.members.list_members(project.id)),
        "my_role": member.role if member else None,
        "repo_url": project.repo_url,
        "default_branch": project.default_branch,
        # Surface the captured build config so the overview can show it even
        # before analysis runs — minus the access token (never exposed).
        "build_config": {k: v for k, v in (project.build_config or {}).items()
                         if k != "repo_access_token"},
        "architecture_layers": project.architecture_layers,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", responses={200: {"model": ProjectListResponse}})
def list_projects(
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    projects = db.projects.list_for_user(current_user.id)
    return {"projects": [_project_view(p, db, current_user.id) for p in projects]}


@router.get("/search", responses={200: {"model": ProjectSearchResponse}})
def search_projects(
    q: str = Query(""),
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    results = db.projects.search(q)
    return {"projects": [{"id": p.id, "name": p.name, "client": p.client} for p in results]}


@router.post("", responses={200: {"model": ProjectResponse}})
def create_project(
    body: CreateProjectRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    now = datetime.now(UTC)
    # Stash the repo access token inside build_config; _project_view never echoes
    # build_config, so the token is not exposed in any API response.
    build_config = dict(body.build_config)
    if body.access_token:
        build_config["repo_access_token"] = body.access_token
    project = Project(
        id=f"p{uuid.uuid4().hex[:8]}",
        org_id="org1",
        name=body.name, client=body.client,
        compliance_standard=body.compliance_standard,
        repo_url=body.repo_url, repo_provider=body.repo_provider,
        default_branch=body.default_branch,
        build_config=build_config,
        architecture_layers=body.architecture_layers,
        status="not_run",
        created_by=current_user.id,
        created_at=now, updated_at=now,
    )
    db.projects.create(project)
    # Materialize the per-project workspace config (workspaces/<pid>/config.json) at
    # onboarding — from architecture_layers + build_config — so the analyzer engine, the
    # standalone CLI, and jobs can all use it immediately (reuses the job-time builder; a
    # job re-writes it too). Best-effort: never fail onboarding on a config-write hiccup.
    try:
        from ..services import pipeline_runner
        from ..services.settings import get_settings
        pipeline_runner._write_project_config(
            project, get_settings().repo_root / "workspaces" / project.id)
    except Exception:
        pass
    # Add creator as admin
    db.members.add_member(ProjectMember(
        id=f"m{uuid.uuid4().hex[:8]}", project_id=project.id,
        user_id=current_user.id, role="admin", status="active",
        invited_by=current_user.id, invited_at=now, joined_at=now,
    ))
    # Add selected developers as active members
    for invite in body.team:
        email = (invite.get("email") or "").strip()
        if not email:
            continue
        user = db.users.get_by_email(email)
        db.members.add_member(ProjectMember(
            id=f"m{uuid.uuid4().hex[:8]}", project_id=project.id,
            user_id=user.id if user else f"pending_{email}",
            role=invite.get("role", "developer"),
            status="active", invited_by=current_user.id,
            invited_at=now, joined_at=now,
        ))
    return {"project": _project_view(project, db, current_user.id)}


@router.get("/{project_id}", responses={200: {"model": ProjectResponse}})
def get_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    project = db.projects.get(project_id)
    if not project:
        raise not_found("Project", project_id)
    require_project_member(project_id, current_user, db)
    return {"project": _project_view(project, db, current_user.id)}


@router.patch("/{project_id}", responses={200: {"model": ProjectResponse}})
def update_project(
    project_id: str,
    body: UpdateProjectRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    project = db.projects.get(project_id)
    if not project:
        raise not_found("Project", project_id)
    require_project_admin(project_id, current_user, db)
    if body.name:
        project.name = body.name
    if body.client:
        project.client = body.client
    if body.status:
        project.status = body.status
    project.updated_at = datetime.now(UTC)
    db.projects.update(project)
    return {"project": _project_view(project, db, current_user.id)}


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    project = db.projects.get(project_id)
    if not project:
        raise not_found("Project", project_id)
    require_project_admin(project_id, current_user, db)
    db.projects.delete(project_id)


# ---------------------------------------------------------------------------
# Access requests
# ---------------------------------------------------------------------------

@router.post("/{project_id}/access-requests", status_code=201,
             responses={201: {"model": AccessRequestResponse}})
def request_access(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    req = AccessRequest(
        id=f"req{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        user_id=current_user.id,
        requested_at=datetime.now(UTC),
        status="pending",
        resolved_by=None, resolved_at=None,
    )
    db.access_reqs.create(req)
    return {"request": {"id": req.id, "status": req.status}}


@router.get("/{project_id}/access-requests",
            responses={200: {"model": AccessRequestListResponse}})
def list_access_requests(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    require_project_admin(project_id, current_user, db)
    reqs = db.access_reqs.list_pending(project_id)
    return {"requests": [
        {"id": r.id, "user_id": r.user_id, "requested_at": r.requested_at.isoformat()}
        for r in reqs
    ]}


@router.patch("/{project_id}/access-requests/{req_id}",
              responses={200: {"model": AccessRequestResponse}})
def resolve_access_request(
    project_id: str,
    req_id: str,
    body: AccessRequestAction,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    require_project_admin(project_id, current_user, db)
    req = db.access_reqs.get(req_id)
    if not req:
        raise not_found("AccessRequest", req_id)
    now = datetime.now(UTC)
    req.status = "approved" if body.action == "approve" else "denied"
    req.resolved_by = current_user.id
    req.resolved_at = now
    db.access_reqs.update(req)
    if req.status == "approved":
        db.members.add_member(ProjectMember(
            id=f"m{uuid.uuid4().hex[:8]}", project_id=project_id,
            user_id=req.user_id, role="developer", status="active",
            invited_by=current_user.id, invited_at=now, joined_at=now,
        ))
    return {"request": {"id": req.id, "status": req.status}}
