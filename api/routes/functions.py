"""Function visibility routes — /api/v1/projects/:id/functions/*"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional

from ..db.session import get_db
from ..db.in_memory import InMemoryDatabase
from ..middleware.auth import get_current_user, require_project_admin
from ..models.domain import User
from ..services.errors import not_found

router = APIRouter(tags=["functions"])


class UpdateVisibilityRequest(BaseModel):
    is_visible: bool


class BulkVisibilityRequest(BaseModel):
    function_ids: list[str]
    is_visible: bool


@router.patch("/projects/{project_id}/functions/{fn_id}")
def update_function_visibility(
    project_id: str,
    fn_id: str,
    body: UpdateVisibilityRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    require_project_admin(project_id, current_user, db)
    fn = db.functions.get(fn_id)
    if not fn or fn.project_id != project_id:
        raise not_found("Function", fn_id)
    fn.is_visible = body.is_visible
    db.functions.update(fn)
    return {"function": {"id": fn.id, "name": fn.name, "is_visible": fn.is_visible}}


@router.patch("/projects/{project_id}/functions")
def bulk_update_visibility(
    project_id: str,
    body: BulkVisibilityRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    require_project_admin(project_id, current_user, db)
    db.functions.bulk_update_visibility(body.function_ids, body.is_visible)
    return {"updated_count": len(body.function_ids)}
