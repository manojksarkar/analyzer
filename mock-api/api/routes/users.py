"""Users routes — /api/v1/users/*

Currently exposes org member search, used by the new-project wizard's team step
to find existing users to invite.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..db.session import get_db
from ..db.in_memory import InMemoryDatabase
from ..middleware.auth import get_current_user
from ..models.domain import User
from ..schemas import UserSearchResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/search", responses={200: {"model": UserSearchResponse}})
def search_users(
    q: str = Query("", description="Name or email substring"),
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """Search the organisation directory, excluding the caller themselves."""
    matches = [u for u in db.users.search(q, limit + 1) if u.id != current_user.id]
    return {
        "users": [
            {"id": u.id, "name": u.name, "email": u.email, "initials": u.initials}
            for u in matches[:limit]
        ]
    }
