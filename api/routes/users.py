"""
User management routes — /api/v1/users/*

Covers:
  POST   /auth/register             — create a new account (open)
  POST   /auth/me/change-password   — change own password (authenticated)
  GET    /users                     — list all users (admin-only platform op)
  GET    /users/{user_id}           — get any user by id (admin)
  DELETE /users/{user_id}           — remove a user account (admin)
  GET    /users/search              — search users by name/email (for invite autocomplete)
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr

from ..db.session import get_db
from ..db.in_memory import InMemoryDatabase
from ..middleware.auth import get_current_user, hash_password, verify_password
from ..models.domain import User
from ..services.errors import not_found, conflict, forbidden, bad_request

router = APIRouter(tags=["users"])
UTC = timezone.utc


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user_view(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "initials": user.initials,
        "avatar_url": user.avatar_url,
        "created_at": user.created_at.isoformat(),
    }


def _make_initials(name: str) -> str:
    parts = name.strip().split()
    if not parts:
        return "??"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _is_platform_admin(user: User, db: InMemoryDatabase) -> bool:
    """
    Platform-level admin check.
    A user is considered a platform admin if they are an admin on at least
    one project.  In production this would be a separate platform_role field.
    """
    for project in db.projects.list_all():
        member = db.members.get_member(project.id, user.id)
        if member and member.role == "admin":
            return True
    return False


# ---------------------------------------------------------------------------
# Registration (open endpoint — no auth required)
# ---------------------------------------------------------------------------

@router.post("/auth/register", status_code=201)
def register(
    body: RegisterRequest,
    db: InMemoryDatabase = Depends(get_db),
):
    """
    Create a new user account.

    - Email must be unique.
    - Password is bcrypt-hashed (SHA-256 pre-hash for length safety).
    - New users are not added to any project automatically; a project admin
      must invite them or approve their access request.
    """
    if not body.email or "@" not in body.email:
        raise bad_request("VALIDATION_ERROR", "A valid email address is required.")
    if not body.password or len(body.password) < 8:
        raise bad_request("VALIDATION_ERROR", "Password must be at least 8 characters.")
    if not body.name or not body.name.strip():
        raise bad_request("VALIDATION_ERROR", "Name is required.")
    existing = db.users.get_by_email(body.email.lower().strip())
    if existing:
        raise conflict("EMAIL_IN_USE", f"An account with email '{body.email}' already exists.")
    now = datetime.now(UTC)
    user = User(
        id=f"u{uuid.uuid4().hex[:8]}",
        email=body.email.lower().strip(),
        name=body.name.strip(),
        initials=_make_initials(body.name),
        avatar_url=None,
        hashed_password=hash_password(body.password),
        created_at=now,
    )
    db.users.create(user)
    return {"user": _user_view(user), "message": "Account created successfully."}


# ---------------------------------------------------------------------------
# Change own password (authenticated)
# ---------------------------------------------------------------------------

@router.post("/auth/me/change-password")
def change_password(
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """
    Change the authenticated user's password.

    Requires the current password to confirm identity.
    """
    if not verify_password(body.current_password, current_user.hashed_password):
        raise bad_request("WRONG_PASSWORD", "Current password is incorrect.")
    if not body.new_password or len(body.new_password) < 8:
        raise bad_request("VALIDATION_ERROR", "New password must be at least 8 characters.")
    if body.new_password == body.current_password:
        raise bad_request("SAME_PASSWORD", "New password must differ from the current password.")
    current_user.hashed_password = hash_password(body.new_password)
    db.users.update(current_user)
    return {"message": "Password changed successfully."}


# ---------------------------------------------------------------------------
# User search — for invite autocomplete (any authenticated user)
# ---------------------------------------------------------------------------

@router.get("/users/search")
def search_users(
    q: str = Query("", min_length=0),
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """
    Search users by name or email fragment.  Returns lightweight objects
    suitable for invite drop-downs.  Excludes the calling user.
    """
    q_lower = q.lower()
    users = db.users.list_all()
    results = [
        u for u in users
        if u.id != current_user.id
        and (not q_lower or q_lower in u.email.lower() or q_lower in u.name.lower())
    ]
    return {
        "users": [
            {"id": u.id, "name": u.name, "email": u.email, "initials": u.initials}
            for u in results[:20]   # cap at 20 for autocomplete
        ]
    }


# ---------------------------------------------------------------------------
# Platform-admin user listing and management
# ---------------------------------------------------------------------------

@router.get("/users")
def list_users(
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """
    List all platform users.  Restricted to platform admins.
    """
    if not _is_platform_admin(current_user, db):
        raise forbidden("Platform admin role required.")
    users = db.users.list_all()
    return {"users": [_user_view(u) for u in users], "total": len(users)}


@router.get("/users/{user_id}")
def get_user(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """
    Retrieve a user by id.  Admins can look up any user; others can only
    look up themselves.
    """
    if user_id != current_user.id and not _is_platform_admin(current_user, db):
        raise forbidden("You may only view your own profile.")
    user = db.users.get_by_id(user_id)
    if not user:
        raise not_found("User", user_id)
    return {"user": _user_view(user)}


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """
    Delete a user account.  Platform admins only.  Cannot delete yourself.
    """
    if not _is_platform_admin(current_user, db):
        raise forbidden("Platform admin role required.")
    if user_id == current_user.id:
        raise bad_request("SELF_DELETE", "You cannot delete your own account.")
    user = db.users.get_by_id(user_id)
    if not user:
        raise not_found("User", user_id)
    db.users.delete(user_id)
