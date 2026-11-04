"""Function visibility routes — /api/v1/projects/:id/functions/*"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import Optional

from ..db.session import get_db
from ..db.in_memory import InMemoryDatabase
from ..middleware.auth import get_current_user, require_project_admin, require_project_member
from ..models.domain import User
from ..services.errors import conflict, not_found

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
    # Only this project's functions: the admin check is on the project in the path.
    updated = db.functions.bulk_update_visibility(body.function_ids, body.is_visible,
                                                  project_id=project_id)
    return {"updated_count": updated}


@router.get("/projects/{project_id}/versions/{version_id}/functions/source")
def get_function_source(
    project_id: str,
    version_id: str,
    function_id: str = Query(..., description="the function's id, as the render payload gives it"),
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """The function's own lines of code in this version, for the reader beside its flowchart
    (BACKLOG NW-7). Any member: they read the documents made from this code. 409 SOURCE_NOT_HERE
    when the version's code is not on this machine."""
    from ..services import function_source as fs
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_member(project_id, current_user, db)
    version = db.versions.get(version_id)
    if not version or version.project_id != project_id:
        raise not_found("Version", version_id)
    try:
        return fs.function_source(db, project_id, version_id, function_id)
    except LookupError:
        raise not_found("Function", function_id)
    except fs.SourceNotHere:
        raise conflict("SOURCE_NOT_HERE", "The code of this version is not on this server. "
                                          "A run or a re-export of the version puts it back.")

