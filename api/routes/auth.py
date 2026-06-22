"""Auth routes — /api/v1/auth/*"""
from __future__ import annotations
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from ..db.session import get_db
from ..db.in_memory import InMemoryDatabase
from ..middleware.auth import (
    verify_password, hash_password,
    create_access_token, create_refresh_token, decode_token,
    get_current_user,
)
from ..models.domain import User
from ..services.errors import not_found, bad_request

router = APIRouter(prefix="/auth", tags=["auth"])
UTC = timezone.utc


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class SignInRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class UpdateMeRequest(BaseModel):
    name: str | None = None
    avatar_url: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user_to_dict(user: User, role_in_project: str | None = None) -> dict:
    d = {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "initials": user.initials,
        "avatar_url": user.avatar_url,
        "created_at": user.created_at.isoformat(),
    }
    if role_in_project:
        d["role_in_project"] = role_in_project
    return d


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/signin")
def signin(body: SignInRequest, db: InMemoryDatabase = Depends(get_db)):
    user = db.users.get_by_email(body.email)
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHENTICATED", "message": "Invalid credentials.", "status": 401},
        )
    return {
        "access_token": create_access_token(user.id),
        "refresh_token": create_refresh_token(user.id),
        "user": _user_to_dict(user),
    }


@router.post("/refresh")
def refresh_token(body: RefreshRequest, db: InMemoryDatabase = Depends(get_db)):
    payload = decode_token(body.refresh_token)
    if payload.get("type") != "refresh":
        raise bad_request("Token is not a refresh token.")
    user = db.users.get_by_id(payload["sub"])
    if not user:
        raise HTTPException(status_code=401, detail={"code": "UNAUTHENTICATED", "status": 401})
    return {"access_token": create_access_token(user.id)}


@router.post("/signout")
def signout(current_user: User = Depends(get_current_user)):
    # Stateless — client discards tokens.  Real impl would blacklist the JTI.
    return {"message": "Signed out."}


@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {"user": _user_to_dict(current_user)}


@router.patch("/me")
def update_me(
    body: UpdateMeRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    if body.name:
        current_user.name = body.name
    if body.avatar_url is not None:
        current_user.avatar_url = body.avatar_url
    updated = db.users.update(current_user)
    return {"user": _user_to_dict(updated)}
