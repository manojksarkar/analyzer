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
from ..models.domain import User, Version, Commit
from ..services.errors import not_found, conflict, bad_request

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


class IngestCommitRequest(BaseModel):
    sha: str
    message: str
    author_name: str
    author_email: str
    branch: str = "main"
    committed_at: Optional[str] = None   # ISO 8601; defaults to now


# ---------------------------------------------------------------------------
# Commits
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/commits")
def list_commits(
    project_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_member(project_id, current_user, db)
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

@router.get("/projects/{project_id}/versions")
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


@router.post("/projects/{project_id}/versions", status_code=201)
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


@router.get("/projects/{project_id}/versions/{version_id}")
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


@router.patch("/projects/{project_id}/versions/{version_id}")
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


@router.post("/projects/{project_id}/versions/{version_id}/approve")
def approve_version(
    project_id: str,
    version_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """
    Approve a version (transition from ``in_review`` → ``approved``).
    Admin only.  Marks all documents belonging to this version as ``approved``
    and updates the project status to ``complete``.
    """
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_admin(project_id, current_user, db)
    version = db.versions.get(version_id)
    if not version or version.project_id != project_id:
        raise not_found("Version", version_id)
    if version.status == "approved":
        return {"version": _version_dict(version), "message": "Already approved."}
    version.status = "approved"
    db.versions.update(version)
    # Mark all documents for this version as approved
    docs, _ = db.documents.list_for_project(project_id, version_id=version_id, per_page=1000)
    now = datetime.now(UTC)
    for doc in docs:
        if doc.status != "approved":
            doc.status = "approved"
            doc.updated_at = now
            db.documents.update(doc)
    # Update project status
    project = db.projects.get(project_id)
    if project:
        project.status = "complete"
        project.updated_at = now
        db.projects.update(project)
    return {"version": _version_dict(version), "approved_docs": len(docs)}


@router.post("/projects/{project_id}/versions/{version_id}/submit-for-review")
def submit_version_for_review(
    project_id: str,
    version_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """
    Submit a draft version for review (``draft`` → ``in_review``).
    Any active project member can trigger this.
    """
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_member(project_id, current_user, db)
    version = db.versions.get(version_id)
    if not version or version.project_id != project_id:
        raise not_found("Version", version_id)
    if version.status not in ("draft",):
        raise bad_request("INVALID_STATUS", f"Version is already '{version.status}' — cannot submit for review.")
    version.status = "in_review"
    db.versions.update(version)
    # Update project status to reflect review in progress
    project = db.projects.get(project_id)
    if project and project.status not in ("in_review", "complete"):
        project.status = "in_review"
        project.updated_at = datetime.now(UTC)
        db.projects.update(project)
    return {"version": _version_dict(version)}


# ---------------------------------------------------------------------------
# Commit ingestion
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/commits", status_code=201)
def ingest_commit(
    project_id: str,
    body: IngestCommitRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """
    Ingest a commit record for a project.

    This is called by a CI/CD webhook or manually to register a new commit
    in the platform so it appears in the commit list and can be used to
    trigger an analysis job.

    If a commit with the same SHA already exists for this project it is
    returned as-is (idempotent).
    """
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_member(project_id, current_user, db)
    # Idempotent — return existing commit if already recorded
    existing = db.commits.get(project_id, body.sha)
    if existing:
        return {"commit": _commit_dict(existing), "created": False}
    # Parse committed_at
    committed_at: datetime
    if body.committed_at:
        try:
            committed_at = datetime.fromisoformat(body.committed_at)
            if committed_at.tzinfo is None:
                committed_at = committed_at.replace(tzinfo=UTC)
        except ValueError:
            raise bad_request("VALIDATION_ERROR", f"Invalid committed_at format: '{body.committed_at}'. Use ISO 8601.")
    else:
        committed_at = datetime.now(UTC)
    commit = Commit(
        sha=body.sha,
        project_id=project_id,
        branch=body.branch,
        message=body.message,
        author_name=body.author_name,
        author_email=body.author_email,
        committed_at=committed_at,
        has_version=False,
        version_id=None,
        doc_status="never",
    )
    db.commits.upsert(commit)
    return {"commit": _commit_dict(commit), "created": True}


@router.get("/projects/{project_id}/commits/{sha}")
def get_commit(
    project_id: str,
    sha: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """Retrieve a single commit by SHA."""
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_member(project_id, current_user, db)
    commit = db.commits.get(project_id, sha)
    if not commit:
        raise not_found("Commit", sha)
    return {"commit": _commit_dict(commit)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    }


def _commit_dict(c: Commit) -> dict:
    return {
        "sha": c.sha,
        "project_id": c.project_id,
        "branch": c.branch,
        "message": c.message,
        "author_name": c.author_name,
        "author_email": c.author_email,
        "committed_at": c.committed_at.isoformat(),
        "has_version": c.has_version,
        "version_id": c.version_id,
        "doc_status": c.doc_status,
    }
