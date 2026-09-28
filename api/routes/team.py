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
from ..services.errors import conflict, not_found

router = APIRouter(tags=["team"])
UTC = timezone.utc


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class InviteRequest(BaseModel):
    email: str
    role: str = "developer"


class UpdateRoleRequest(BaseModel):
    role: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _member_view(member: ProjectMember, user: Optional[User]) -> dict:
    return {
        "id": member.id,
        "user_id": member.user_id,
        "name": user.name if user else "Unknown",
        "email": user.email if user else "",
        "initials": user.initials if user else "??",
        "role": member.role,
        "status": member.status,
        "joined_at": member.joined_at.isoformat() if member.joined_at else None,
    }


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
    return {"members": [_member_view(m, users.get(m.user_id)) for m in members]}


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
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_admin(project_id, current_user, db)
    email = body.email.strip()
    invited_user = db.users.get_by_email(email)
    if invited_user is None:
        # A membership row references users.id, and nothing creates an account for an address.
        # An unknown address used to be stored under a made-up id ("pending_<email>"), which the
        # in-memory seam accepted and the database refused: a 500 for every such invite.
        raise HTTPException(status_code=404, detail={
            "code": "USER_NOT_FOUND",
            "message": f"No user account uses {email}. Only people who already have an "
                       f"account can be invited to a project.",
            "status": 404})
    now = datetime.now(UTC)
    member = db.members.get_member(project_id, invited_user.id)
    if member is not None and member.status == "active":
        raise conflict("ALREADY_MEMBER",
                       f"{invited_user.name} ({email}) is already a member of this project.")
    if member is not None:
        # Invited again ("Resend"): refresh the one pending row. (project, user) is unique, so
        # adding a second row was a 500 too.
        member.role = body.role
        member.invited_by = current_user.id
        member.invited_at = now
        db.members.update_member(member)
    else:
        member = ProjectMember(
            id=f"m{uuid.uuid4().hex[:8]}",
            project_id=project_id,
            user_id=invited_user.id,
            role=body.role,
            status="pending",
            invited_by=current_user.id,
            invited_at=now,
            joined_at=None,
        )
        db.members.add_member(member)
    return {
        "invite": {
            "id": member.id,
            "email": email,
            "role": member.role,
            "status": "pending",
        }
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
    member.role = body.role
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
