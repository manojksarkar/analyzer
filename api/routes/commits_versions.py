"""Commits & Versions routes — /api/v1/projects/:id/commits and /versions"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel

from ..db.session import get_db
from ..db.in_memory import InMemoryDatabase
from ..middleware.auth import get_current_user, require_project_admin, require_project_member
from ..models.domain import User, Version, Commit, Project
from ..services import repo_git, review_workflow
from ..services.errors import bad_request, not_found, conflict
from ..schemas import CommitListResponse, VersionResponse, VersionListResponse

router = APIRouter(tags=["commits-versions"])
UTC = timezone.utc

# Min seconds between repo commit syncs for a single project. list_commits runs
# the sync on every page-1 view, so this stops rapid refreshes from re-scanning
# the repo on every call.
_COMMIT_SYNC_THROTTLE_SECONDS = 60


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
    background_tasks: BackgroundTasks,
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
    # Sync new commits from the connected repo on every page-1 view (so pushes
    # show up without re-creating the project), throttled per project and
    # insert-only — see _backfill_commits_from_repo. The throttle clock is
    # advanced synchronously so concurrent/rapid requests don't each schedule a
    # scan and last_synced_at reflects this attempt.
    if page == 1 and _should_sync(project):
        first_sync = project.last_commit_sync_at is None
        project.last_commit_sync_at = datetime.now(UTC)
        db.projects.update(project)
        if first_sync:
            # First-ever view (e.g. a fresh wizard project): fetch inline so the
            # commits show up immediately. This is the only sync that blocks the
            # response, and it happens at most once per project.
            _backfill_commits_from_repo(project_id, db)
            commits, total = db.commits.list_for_project(project_id, page, per_page)
        else:
            # Steady state: pull new commits after the response is sent so the
            # API is never slowed by the git round-trip; they appear on the next
            # refetch.
            background_tasks.add_task(_backfill_commits_from_repo, project_id, db)
    all_versions = sorted(db.versions.list_for_project(project_id),
                          key=lambda v: review_workflow._aware(v.created_at))
    versions = {v.commit_sha: v.tag for v in all_versions}
    # A commit's document status is its newest finished version's: in_review or approved (derived
    # from the documents, review_workflow.roll_up). `commits.doc_status` was written once, as
    # "never", and nothing kept it current.
    reviewed = {v.commit_sha: v.status for v in all_versions if v.status in ("in_review", "approved")}
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
                "doc_status": reviewed.get(c.sha) or c.doc_status,
                "version": versions.get(c.sha),
                "is_current": c.sha == current_sha,
            }
            for c in commits
        ],
        "pagination": {"page": page, "per_page": per_page, "total": total},
        "last_synced_at": (
            project.last_commit_sync_at.isoformat()
            if project.last_commit_sync_at else None
        ),
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
    return {"versions": [_version_dict(v, db) for v in versions]}


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
    return {"version": _version_dict(version, db)}


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
    return {"version": _version_dict(version, db)}


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
    if body.status is not None:
        # A version is approved when every one of its documents is (REVIEW_APPROVE_API_SPEC
        # A14): derived, never set. Setting it by hand recorded nothing and agreed with nothing.
        raise bad_request("A version's status follows its documents: approve the documents.")
    if body.description is not None:
        version.description = body.description
    db.versions.update(version)
    return {"version": _version_dict(version, db)}


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
    # How a stopped run's kept version is thrown away (its job ended, so Cancel no longer
    # applies). Three things pointed at a version without ON DELETE CASCADE -- its jobs, another
    # version's baseline, a cached comparison -- and the delete failed with a 500.
    from ..services import pipeline_runner
    busy = pipeline_runner.version_writer_busy(db, version_id)
    if busy:
        raise conflict("VERSION_BUSY", f"Version '{version.tag or version_id}' is being written by "
                                       f"{busy}. Stop that run first.")
    jobs = db.jobs.list_for_version(version_id)
    if any(j.status in ("queued", "running", "paused") for j in jobs):
        raise conflict("RUN_ACTIVE", f"A job is at work on version '{version.tag or version_id}'. "
                                     f"Cancel it first.")
    if any(getattr(v, "baseline_version_id", None) == version_id
           for v in db.versions.list_for_project(project_id)):
        raise conflict("VERSION_IS_BASELINE", f"Version '{version.tag or version_id}' is the "
                                              f"baseline of a later version, which reuses its work.")
    for job in jobs:                         # the job's record stays; it no longer points here
        job.version_id = None
        db.jobs.update(job)
    engine = getattr(db, "_engine", None)
    if engine is not None:
        from sqlalchemy import delete, or_
        from ..db.postgres import schema as s
        with engine.begin() as cx:
            cx.execute(delete(s.compare_results).where(or_(
                s.compare_results.c.current_version_id == version_id,
                s.compare_results.c.baseline_version_id == version_id)))
    db.versions.delete(version_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _should_sync(project: Project) -> bool:
    """True when the project's commits are due for a repo sync (throttle gate).

    Syncs on the first-ever view (no timestamp) and at most once per
    _COMMIT_SYNC_THROTTLE_SECONDS thereafter. Projects with no repo connected
    never sync — there is nothing to pull.
    """
    if not project.repo_url or not project.default_branch:
        return False
    last = project.last_commit_sync_at
    if last is None:
        return True
    if last.tzinfo is None:        # tolerate naive timestamps from storage
        last = last.replace(tzinfo=UTC)
    return (datetime.now(UTC) - last).total_seconds() >= _COMMIT_SYNC_THROTTLE_SECONDS


def _backfill_commits_from_repo(project_id: str, db: InMemoryDatabase) -> None:
    """Sync recent commits from the project's connected repo (insert-only).

    Inserts commits that aren't already stored; existing commits are left
    untouched so their doc_status / version links are never overwritten. The
    caller gates this behind _should_sync and owns advancing the throttle clock
    (Project.last_commit_sync_at); this function only touches commits.

    Takes a project_id (not the object) and re-reads the project, because it may
    run as a BackgroundTask after the response is sent. Safe to reuse `db`: the
    in-memory / json backends are process-global singletons, not per-request
    sessions.

    Best-effort: any git/network failure leaves the stored commits as-is. The
    repo access token (stored in build_config, never exposed) is used for
    private repos.
    """
    project = db.projects.get(project_id)
    # _should_sync already guarantees repo_url/default_branch, but re-check since
    # state may have changed between scheduling and running.
    if not project or not project.repo_url or not project.default_branch:
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
        if db.commits.get(project.id, sha):
            continue  # insert-only — keep the existing doc_status / version link
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


def _version_dict(v: Version, db=None) -> dict:
    """A version; with `db`, its status derived from its documents and their review counts."""
    review = None
    status = v.status
    if db is not None:
        docs = review_workflow.version_docs(db, v)
        status = review_workflow.derived_status(v, docs)
        review = review_workflow.version_review(db, v, docs)
    return {
        "id": v.id,
        "tag": v.tag,
        "commit_sha": v.commit_sha,
        # A version the CLI made (`--create-version`) has no branch, description or author; the
        # contract's types are strings, and the web app refused the WHOLE version list on a null.
        "branch": v.branch or "",
        "description": v.description or "",
        "status": status,
        "review": review,
        "docs_count": v.docs_count,
        "created_by": v.created_by or "",
        "created_at": v.created_at.isoformat(),
        "baseline_version_id": getattr(v, "baseline_version_id", None),
        "decision": getattr(v, "decision", None),
        "regenerated": getattr(v, "regenerated", None),
        "reused": getattr(v, "reused", None),
        # What the run warned about (engine manifest, `versions.run_report.warnings`).
        "warnings": list(getattr(v, "warnings", None) or []),
    }
