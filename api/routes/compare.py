"""Compare routes — /api/v1/projects/:id/compare/*"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..db.session import get_db
from ..middleware.auth import get_current_user, require_project_member
from ..models.domain import User
from ..services.errors import not_found
from ..services import compare_engine

router = APIRouter(tags=["compare"])


@router.get("/projects/{project_id}/compare")
def compare(
    project_id: str,
    current: str = Query(...),
    baseline: str = Query(...),
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_member(project_id, current_user, db)
    result = compare_engine.compute_compare(db, project_id, current, baseline)
    return result


@router.get("/projects/{project_id}/compare/documents")
def compare_documents(
    project_id: str,
    current: str = Query(...),
    baseline: str = Query(...),
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_member(project_id, current_user, db)
    result = compare_engine.compute_compare(db, project_id, current, baseline)
    return {
        "documents": result["changed_documents"],
        "summary": result["summary"],
    }


@router.get("/projects/{project_id}/compare/documents/{doc_id}")
def compare_document_detail(
    project_id: str,
    doc_id: str,
    current: str = Query(...),
    baseline: str = Query(...),
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_member(project_id, current_user, db)
    result = compare_engine.compute_document_sections_diff(
        db, project_id, doc_id, current, baseline
    )
    if result is None:
        raise not_found("Document", doc_id)
    return result
