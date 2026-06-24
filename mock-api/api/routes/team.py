"""Team routes — /api/v1/projects/:id/members/*"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..db.session import get_db
from ..db.in_memory import InMemoryDatabase
from ..middleware.auth import get_current_user, require_project_admin, require_project_member
from ..models.domain import User, ProjectMember
from ..services.errors import not_found
from ..schemas import (
    MemberListResponse, PendingListResponse, InviteResponse, MemberResponse,
)

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

@router.get("/projects/{project_id}/members",
            responses={200: {"model": MemberListResponse}})
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


@router.get("/projects/{project_id}/members/pending",
            responses={200: {"model": PendingListResponse}})
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


@router.post("/projects/{project_id}/members/invite", status_code=201,
             responses={201: {"model": InviteResponse}})
def invite_member(
    project_id: str,
    body: InviteRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_admin(project_id, current_user, db)
    invited_user = db.users.get_by_email(body.email)
    now = datetime.now(UTC)
    member = ProjectMember(
        id=f"m{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        user_id=invited_user.id if invited_user else f"pending_{body.email}",
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
            "email": body.email,
            "role": body.role,
            "status": "pending",
        }
    }


@router.patch("/projects/{project_id}/members/{user_id}/role",
              responses={200: {"model": MemberResponse}})
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
