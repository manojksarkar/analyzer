"""Commits & Versions routes — /api/v1/projects/:id/commits and /versions"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ..db.session import get_db
from ..db.in_memory import InMemoryDatabase
from ..middleware.auth import get_current_user, require_project_admin, require_project_member
from ..models.domain import User, Version, Commit, Project
from ..services import repo_git
from ..services.errors import not_found, conflict
from ..schemas import CommitListResponse, VersionResponse, VersionListResponse

router = APIRouter(tags=["commits-versions"])
UTC = timezone.utc


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CreateVersionRequest(BaseModel):
    tag: str
    commit_sha: str
    branch: str = "main"
    description: str = ""


class UpdateVersionRequest(BaseModel):
    status: Optional[str] = None
    description: Optional[str] = None


# ---------------------------------------------------------------------------
# Commits
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/commits",
            responses={200: {"model": CommitListResponse}})
def list_commits(
    project_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    project = db.projects.get(project_id)
    if not project:
        raise not_found("Project", project_id)
    require_project_member(project_id, current_user, db)
    commits, total = db.commits.list_for_project(project_id, page, per_page)
    # A wizard-created project starts with no commits — fetch the real history
    # from the connected repo on first view, persist it, then re-read.
    if not commits and page == 1:
        _backfill_commits_from_repo(project, db)
        commits, total = db.commits.list_for_project(project_id, page, per_page)
    versions = {v.commit_sha: v.tag for v in db.versions.list_for_project(project_id)}
    # Mark the most recent commit as "current"
    current_job = db.jobs.get_current(project_id)
    current_sha = current_job.commit_sha if current_job else None
    return {
        "commits": [
            {
                "sha": c.sha,
                "message": c.message,
                "author": c.author_name,
                "committed_at": c.committed_at.isoformat(),
                "branch": c.branch,
                "doc_status": c.doc_status,
                "version": versions.get(c.sha),
                "is_current": c.sha == current_sha,
            }
            for c in commits
        ],
        "pagination": {"page": page, "per_page": per_page, "total": total},
    }


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/versions",
            responses={200: {"model": VersionListResponse}})
def list_versions(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_member(project_id, current_user, db)
    versions = db.versions.list_for_project(project_id)
    versions.sort(key=lambda v: v.created_at, reverse=True)
    return {"versions": [_version_dict(v) for v in versions]}


@router.post("/projects/{project_id}/versions", status_code=201,
             responses={201: {"model": VersionResponse}})
def create_version(
    project_id: str,
    body: CreateVersionRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_admin(project_id, current_user, db)
    if db.versions.get_by_tag(project_id, body.tag):
        raise conflict("VERSION_TAG_EXISTS", f"Version tag '{body.tag}' already exists.")
    version = Version(
        id=f"ver{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        tag=body.tag,
        commit_sha=body.commit_sha,
        branch=body.branch,
        description=body.description,
        status="draft",
        docs_count=0,
        created_by=current_user.id,
        created_at=datetime.now(UTC),
    )
    db.versions.create(version)
    return {"version": _version_dict(version)}


@router.get("/projects/{project_id}/versions/{version_id}",
            responses={200: {"model": VersionResponse}})
def get_version(
    project_id: str,
    version_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_member(project_id, current_user, db)
    version = db.versions.get(version_id)
    if not version or version.project_id != project_id:
        raise not_found("Version", version_id)
    return {"version": _version_dict(version)}


@router.patch("/projects/{project_id}/versions/{version_id}",
              responses={200: {"model": VersionResponse}})
def update_version(
    project_id: str,
    version_id: str,
    body: UpdateVersionRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_admin(project_id, current_user, db)
    version = db.versions.get(version_id)
    if not version or version.project_id != project_id:
        raise not_found("Version", version_id)
    if body.status:
        version.status = body.status
    if body.description is not None:
        version.description = body.description
    db.versions.update(version)
    return {"version": _version_dict(version)}


@router.delete("/projects/{project_id}/versions/{version_id}", status_code=204)
def delete_version(
    project_id: str,
    version_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_admin(project_id, current_user, db)
    version = db.versions.get(version_id)
    if not version or version.project_id != project_id:
        raise not_found("Version", version_id)
    db.versions.delete(version_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _backfill_commits_from_repo(project: Project, db: InMemoryDatabase) -> None:
    """Fetch recent commits from the project's connected repo and persist them.

    Best-effort: any git/network failure leaves the commit list empty (the same
    state as before), so the overview just keeps showing "no commit to analyze".
    The repo access token (stored in build_config, never exposed) is used for
    private repos.
    """
    if not project.repo_url or not project.default_branch:
        return
    token = (project.build_config or {}).get("repo_access_token")
    try:
        raw = repo_git.list_commits(project.repo_url, project.default_branch, token, limit=50)
    except Exception:
        return
    for rc in raw:
        sha = rc.get("sha")
        if not sha:
            continue
        date_str = rc.get("date") or ""
        try:
            committed = datetime.fromisoformat(date_str) if date_str else datetime.now(UTC)
        except ValueError:
            committed = datetime.now(UTC)
        db.commits.upsert(Commit(
            sha=sha, project_id=project.id, branch=project.default_branch,
            message=rc.get("message", ""), author_name=rc.get("author", ""),
            author_email=rc.get("authorEmail", ""), committed_at=committed,
            has_version=False, version_id=None, doc_status="never",
        ))


def _version_dict(v: Version) -> dict:
    return {
        "id": v.id,
        "tag": v.tag,
        "commit_sha": v.commit_sha,
        "branch": v.branch,
        "description": v.description,
        "status": v.status,
        "docs_count": v.docs_count,
        "created_by": v.created_by,
        "created_at": v.created_at.isoformat(),
        "baseline_version_id": getattr(v, "baseline_version_id", None),
        "decision": getattr(v, "decision", None),
        "regenerated": getattr(v, "regenerated", None),
        "reused": getattr(v, "reused", None),
    }
