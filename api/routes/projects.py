"""Projects routes — /api/v1/projects/*"""
from __future__ import annotations
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from typing import Any, Optional

from ..db.session import get_db
from ..db.in_memory import InMemoryDatabase
from ..middleware.auth import get_current_user, require_project_admin, require_project_member
from ..models.domain import User, Project, ProjectMember, AccessRequest
from ..services.errors import bad_request, not_found, forbidden, conflict
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

def _is_superuser(db, user_id: str) -> bool:
    """`my_role` is computed from a user id, not a User, so the flag is looked up here.

    Best-effort: a failure to answer must not turn a project listing into a 500. Reporting a
    superuser as an ordinary member is a cosmetic loss; the API still honours them.
    """
    try:
        u = db.users.get_by_id(user_id)
        return bool(getattr(u, "is_superuser", False)) if u else False
    except Exception:                                  # noqa: BLE001 - see docstring
        return False


def _project_view(project: Project, db: InMemoryDatabase, user_id: str) -> dict:
    member = db.members.get_member(project.id, user_id)
    # The version on display: the newest that is not a draft being generated. A run's draft
    # (days, for a long run) has no documents yet, so the counts and the current version read
    # 0 and the draft's name for the whole run. None for a project with no finished version.
    from ..services.review_workflow import latest_version
    latest = latest_version(db, project.id)
    # Scope the dashboard doc counts to that version, not the sum across every run. With no
    # finished version there is nothing to count: a version id no document has gives zeros in
    # the usual shape (None would count every document, the running draft's too).
    stats = db.documents.get_stats(project.id, version_id=latest.id if latest else "-")
    job = db.jobs.get_current(project.id)
    return {
        "id": project.id,
        "name": project.name,
        # A project onboarded from the CLI leaves these empty; the contract's types are strings
        # and a list, and the web app refuses the whole project on a null.
        "client": project.client or "",
        "compliance_standard": project.compliance_standard or "",
        "status": project.status,
        "last_run_at": job.started_at.isoformat() if job else None,
        "current_version": latest.tag if latest else None,
        "doc_counts": stats,
        "team_count": len(db.members.list_members(project.id)),
        # A superuser with no membership row is still an admin of this project as far as the
        # UI is concerned -- reporting None would grey out controls the API will honour.
        "my_role": member.role if member else ("admin" if _is_superuser(db, user_id) else None),
        "repo_url": project.repo_url,
        "default_branch": project.default_branch,
        # Surface the captured build config so the overview can show it even
        # before analysis runs — minus the access token (never exposed).
        "build_config": {k: v for k, v in (project.build_config or {}).items()
                         if k != "repo_access_token"},
        "architecture_layers": project.architecture_layers or [],
        **_cores_view(project),
        # Null-safe. A row written by `analyzer.py onboard` has no `updated_at` -- the CLI
        # has no notion of "modified" -- and an unconditional .isoformat() turned the whole
        # project LIST into a 500 for every project, not just that one.
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
    }


def _cores_view(project: Project) -> dict:
    """The project's cores - each with its inputs' file names and the layers it builds - and the
    core of every layer. A project from before cores reads as one core, Core1, that every layer
    uses (services/project_cores.py), so the web app never has to know the older shape."""
    from ..services.project_cores import describe, project_cores
    cores, layer_core = project_cores(project.build_config, project.architecture_layers)
    return {
        "cores": [{"name": c["name"], **describe(c),
                   "layers": [l for l, k in layer_core.items() if k == c["name"]]} for c in cores],
        "layer_cores": layer_core,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", responses={200: {"model": ProjectListResponse}})
def list_projects(
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    # A superuser sees everything. Without this the bypass in `require_project_member` would
    # be half a feature: every project would OPEN but none would be LISTED, which reads as the
    # projects having vanished.
    projects = (db.projects.list_all() if getattr(current_user, "is_superuser", False)
                else db.projects.list_for_user(current_user.id))
    # Most recently changed first, and the same order on every load: the database answered in
    # its own order, so rows swapped places between refreshes.
    projects = sorted(projects, key=lambda p: (_when(p.updated_at or p.created_at), p.id),
                      reverse=True)
    return {"projects": [_project_view(p, db, current_user.id) for p in projects]}


def _when(dt) -> datetime:
    """A row's time as an aware UTC datetime (SQLite hands it back naive), or the epoch."""
    if dt is None:
        return datetime.min.replace(tzinfo=UTC)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class ConfigPreviewRequest(BaseModel):
    text: str                                   # the config file's contents
    repo_url: Optional[str] = None              # when the wizard has connected the repository
    branch: Optional[str] = None
    access_token: Optional[str] = None


@router.post("/config/preview")
def preview_config(
    body: ConfigPreviewRequest,
    current_user: User = Depends(get_current_user),
):
    """Read a config file and fill the New Project wizard from it: `{draft, expected_uploads,
    report, repository_checked}`. With a repository, every layer and component path is checked
    against it. A core's files are the user's own inputs, never read from the repository: step 2
    asks for them. Nothing is written; the project is created by `POST /projects` as before."""
    from ..services import git_cli, project_config, repo_git
    if len(body.text or "") > 2 * 1024 * 1024:
        raise bad_request("The config file is larger than 2 MB.")
    try:
        cfg = project_config.parse(body.text)
    except project_config.ConfigError as exc:
        raise bad_request(str(exc))

    tree = None
    note = None
    url = (body.repo_url or "").strip()
    from ..services import local_repos
    if url and local_repos.is_local(url):
        # A local repository: read as git reads it, and only when it may be one.
        why = local_repos.problem(url)
        if why:
            note, url = f"The repository could not be read ({why}), so paths were not checked.", ""
        else:
            url = local_repos.clean(url)
    if url:
        try:
            # The branch as it is now: a reused clone is refreshed, and read at the fetched tip.
            branch = (body.branch or "").strip() or None
            clone = repo_git._clone_or_reuse(url, branch, body.access_token, blobless=True,
                                             refresh=True)
            tree = git_cli.list_tree(str(clone), repo_git.tree_ref(clone, branch))
        except git_cli.GitError as exc:
            note = (f"The repository could not be read ({repo_git._friendly(str(exc))}), so "
                    f"paths were not checked.")
    result = project_config.preview(cfg, tree_nodes=tree)
    if note:
        result["report"].insert(0, {"level": "check", "text": note, "topic": "repository"})
    return result


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
    # Every team member needs an account, checked BEFORE anything is written: a membership row
    # references users.id, and an unknown address (stored as "pending_<email>") failed that
    # foreign key after the project row existed -- a 500 that left a half-created project.
    from ..services.accounts import find_user
    unknown = [e for e in ((t.get("email") or "").strip() for t in body.team)
               if e and not find_user(db, e)]
    if unknown:
        raise HTTPException(status_code=404, detail={
            "code": "USER_NOT_FOUND",
            "message": f"No user account uses {', '.join(unknown)}. Add the project without them, "
                       f"then invite them from the Team page: an invite creates the account.",
            "status": 404})
    # Stash the repo access token inside build_config; _project_view never echoes
    # build_config, so the token is not exposed in any API response.
    # Cores the run would refuse or read wrongly are refused here, before anything is written.
    from ..services.project_cores import core_problems
    problems = core_problems(body.build_config, body.architecture_layers)
    if problems:
        raise bad_request(" ".join(problems))
    # A local repository (a git repository's folder on the server) is checked as Test Connection
    # checks it -- the wizard cannot be relied on to have -- and stored as git will read it.
    from ..services import local_repos
    repo_url, repo_provider = body.repo_url, body.repo_provider
    if (repo_url or "").strip() and local_repos.is_local(repo_url):
        why = local_repos.problem(repo_url)
        if why:
            raise bad_request(why)
        repo_url, repo_provider = local_repos.clean(repo_url), "local"
    build_config = dict(body.build_config)
    if body.access_token and repo_provider != "local":
        build_config["repo_access_token"] = body.access_token
    project = Project(
        id=f"p{uuid.uuid4().hex[:8]}",
        org_id="org1",
        name=body.name, client=body.client,
        compliance_standard=body.compliance_standard,
        repo_url=repo_url, repo_provider=repo_provider,
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
    # Add selected developers as active members -- once each: (project, user) is unique, so the
    # creator listing themselves, or one person listed twice, was a 500 on the second row.
    added = {current_user.id}
    for invite in body.team:
        email = (invite.get("email") or "").strip()
        if not email:
            continue
        user = find_user(db, email)
        if user.id in added:
            continue
        added.add(user.id)
        db.members.add_member(ProjectMember(
            id=f"m{uuid.uuid4().hex[:8]}", project_id=project.id,
            user_id=user.id,
            role=invite.get("role", "developer"),
            status="active", invited_by=current_user.id,
            invited_at=now, joined_at=now,
        ))
    return {"project": _project_view(project, db, current_user.id)}


@router.get("/{project_id}/config")
def download_config(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """The project as a config file -- what `analyzer.py onboard --config` reads and the New
    Project wizard imports. Never the access token."""
    from ..services import project_config
    project = db.projects.get(project_id)
    if not project:
        raise not_found("Project", project_id)
    require_project_member(project_id, current_user, db)
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", project.name or "").strip("-") or project_id
    return Response(project_config.to_config_text(project), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}.config.json"'})


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
    from ..services import pipeline_runner
    job = db.jobs.get_current(project_id)
    if job and job.status in ("queued", "running", "paused") and pipeline_runner.job_alive(job.id):
        # Its thread would go on writing versions, documents and files for a project that is gone.
        raise conflict("JOB_RUNNING", "An analysis is running for this project. "
                                      "Cancel it before deleting the project.")
    db.projects.delete(project_id)
    _remove_workspace(project_id)


def _remove_workspace(project_id: str) -> None:
    """Delete `workspaces/<project_id>/` -- the git checkout and every version's output.

    Nothing refers to it once the project row is gone, and a real project's folder holds a
    checkout per commit plus every version's documents and diagrams: leaving it behind was a
    silent disk leak on every delete. Best effort -- a failure is logged, the deletion stands.
    """
    import logging
    import os
    import shutil
    import stat
    import sys
    from ..services.settings import get_settings

    root = get_settings().workspaces.resolve()
    target = (root / project_id).resolve()
    if target.parent != root or not target.is_dir():       # never outside the workspaces root
        return

    def _retry(func, path, _exc):                           # git pack files are read-only
        os.chmod(path, stat.S_IWRITE)
        func(path)

    kwargs = {"onexc": _retry} if sys.version_info >= (3, 12) else {"onerror": _retry}
    try:
        shutil.rmtree(target, **kwargs)
    except Exception as exc:                                # noqa: BLE001 - logged, not fatal
        logging.getLogger(__name__).warning(
            "project %s deleted, but its workspace %s was not: %s", project_id, target, exc)


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
    # The request must be for THIS project: the admin check is on the project in the path, so a
    # request for another project was resolved by someone who does not administer it -- and on
    # approval its requester was added to the path's project instead.
    if not req or req.project_id != project_id:
        raise not_found("AccessRequest", req_id)
    if req.status != "pending":
        # Approving twice added the membership twice: a 500 on the (project, user) unique key.
        raise conflict("ACCESS_REQUEST_RESOLVED", f"Access request {req_id} is already {req.status}.")
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
