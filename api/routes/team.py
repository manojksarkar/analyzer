"""Team routes — /api/v1/projects/:id/members/*"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..db.session import get_db
from ..db.in_memory import InMemoryDatabase
from ..middleware.auth import get_current_user, require_project_admin, require_project_member
from ..models.domain import User, ProjectMember
from ..services import review_workflow
from ..services.errors import conflict, not_found

#: The roles a member can hold. "reviewer" is a developer by another name for review: it reviews,
#: claims and submits; only an admin assigns and approves (REVIEW_APPROVE_API_SPEC).
ROLES = ("admin", "developer", "reviewer")

router = APIRouter(tags=["team"])
UTC = timezone.utc


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class InviteRequest(BaseModel):
    email: str
    role: str = "developer"
    name: Optional[str] = None      # for an address with no account yet: the account's name


class UpdateRoleRequest(BaseModel):
    role: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _member_view(member: ProjectMember, user: Optional[User], open_reviews: int = 0) -> dict:
    return {
        "id": member.id,
        "user_id": member.user_id,
        "name": user.name if user else "Unknown",
        "email": user.email if user else "",
        "initials": user.initials if user else "??",
        "role": member.role,
        "status": member.status,
        "joined_at": member.joined_at.isoformat() if member.joined_at else None,
        # documents of the latest version they review that are not approved yet
        "open_reviews": open_reviews,
    }


def _role(role: str) -> str:
    if role not in ROLES:
        raise HTTPException(status_code=422, detail={
            "code": "VALIDATION_ERROR", "status": 422,
            "message": "role must be one of: %s." % ", ".join(ROLES)})
    return role


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/members")
def list_members(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_member(project_id, current_user, db)
    members = db.members.list_members(project_id)
    users = {u.id: u for u in db.users.list_by_ids([m.user_id for m in members])}
    load = review_workflow.open_reviews(db, project_id)
    return {"members": [_member_view(m, users.get(m.user_id), load.get(m.user_id, 0))
                        for m in members]}


@router.get("/projects/{project_id}/members/pending")
def list_pending(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_admin(project_id, current_user, db)
    pending = db.members.list_pending(project_id)
    users = {u.id: u for u in db.users.list_by_ids([m.user_id for m in pending])}
    return {"pending": [_member_view(m, users.get(m.user_id)) for m in pending]}


@router.post("/projects/{project_id}/members/invite", status_code=201)
def invite_member(
    project_id: str,
    body: InviteRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """Add a person to the project: an ACTIVE member at once, who can review straight away.

    An address with no account gets one, with a temporary password answered ONCE in
    `account.temporary_password` for the admin to pass on (the person changes it with
    `POST /auth/change-password`). Before this an invite made a `pending` membership that nothing
    ever activated -- there was no accept step -- and an unknown address was refused, as nothing
    created accounts; so a new person could not be added at all.
    """
    from ..services import accounts

    project = db.projects.get(project_id)
    if not project:
        raise not_found("Project", project_id)
    require_project_admin(project_id, current_user, db)
    role = _role(body.role)
    try:
        email = accounts.normalise_email(body.email)
    except accounts.AccountError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc), "status": 422})
    invited_user = accounts.find_user(db, body.email)
    temporary = None
    if invited_user is None:
        try:
            invited_user, temporary = accounts.create_user(db, email, body.name)
        except accounts.AccountError as exc:
            raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc),
                                                         "status": 422})
    now = datetime.now(UTC)
    member = db.members.get_member(project_id, invited_user.id)
    if member is not None and member.status == "active":
        raise conflict("ALREADY_MEMBER",
                       f"{invited_user.name} ({invited_user.email}) is already a member of this project.")
    if member is not None:
        # An invite from before (pending, never activated): it becomes the active membership.
        # (project, user) is unique, so adding a second row was a 500.
        member.role, member.status = role, "active"
        member.invited_by, member.invited_at, member.joined_at = current_user.id, now, now
        db.members.update_member(member)
    else:
        member = ProjectMember(
            id=f"m{uuid.uuid4().hex[:8]}",
            project_id=project_id,
            user_id=invited_user.id,
            role=role,
            status="active",
            invited_by=current_user.id,
            invited_at=now,
            joined_at=now,
        )
        db.members.add_member(member)
    review_workflow.notify(db, [invited_user.id], project_id, None, "member_added",
                           f"{current_user.name} added you to {project.name} as {role}.",
                           skip=current_user.id)
    return {
        "invite": {"id": member.id, "email": invited_user.email, "role": member.role,
                   "status": "active"},
        "member": _member_view(member, invited_user),
        # Shown once: the only time the temporary password exists outside its hash.
        "account": {"created": temporary is not None, "temporary_password": temporary},
    }


@router.patch("/projects/{project_id}/members/{user_id}/role")
def update_role(
    project_id: str,
    user_id: str,
    body: UpdateRoleRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_admin(project_id, current_user, db)
    member = db.members.get_member(project_id, user_id)
    if not member:
        raise not_found("Member", user_id)
    member.role = _role(body.role)
    db.members.update_member(member)
    user = db.users.get_by_id(user_id)
    return {"member": _member_view(member, user)}


@router.delete("/projects/{project_id}/members/{user_id}", status_code=204)
def remove_member(
    project_id: str,
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_admin(project_id, current_user, db)
    db.members.remove_member(project_id, user_id)
    # Their documents that are not approved go back to Needs a reviewer, on the record: a
    # document must not wait on someone who can no longer act on it.
    review_workflow.release_reviews(db, project_id, user_id, current_user)


@router.delete("/projects/{project_id}/members/pending/{invite_id}", status_code=204)
def cancel_invite(
    project_id: str,
    invite_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_admin(project_id, current_user, db)
    db.members.cancel_invite(project_id, invite_id)
