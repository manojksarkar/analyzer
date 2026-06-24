"""Compare routes — /api/v1/projects/:id/compare/*"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from typing import Optional

from ..db.session import get_db
from ..db.in_memory import InMemoryDatabase
from ..middleware.auth import get_current_user, require_project_member
from ..models.domain import User
from ..services.errors import not_found
from ..schemas import (
    CompareResponse, CompareDocumentsResponse, CompareDocumentDetailResponse,
)

router = APIRouter(tags=["compare"])


@router.get("/projects/{project_id}/compare",
            responses={200: {"model": CompareResponse}})
def compare(
    project_id: str,
    current: str = Query(...),
    baseline: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_member(project_id, current_user, db)
    cr = db.compare.get_or_create(project_id, current, baseline)
    diffs = db.compare.list_diffs(cr.id)
    # Resolve version labels
    def _resolve_ref(ref: str):
        for v in db.versions.list_for_project(project_id):
            if v.commit_sha == ref or v.tag == ref or v.id == ref:
                return {"ref": ref, "version": v.tag, "branch": v.branch}
        return {"ref": ref, "version": None, "branch": "main"}

    changed_docs = []
    for d in diffs:
        doc = db.documents.get(d.document_id)
        if doc:
            changed_docs.append({
                "document_id": d.document_id,
                "name": doc.name,
                "process": doc.process,
                "diff_type": d.diff_type,
                "sections_changed": d.sections_changed,
            })

    return {
        "current": _resolve_ref(current),
        "baseline": _resolve_ref(baseline),
        "summary": cr.diff_summary,
        "changed_documents": changed_docs,
    }


@router.get("/projects/{project_id}/compare/documents",
            responses={200: {"model": CompareDocumentsResponse}})
def compare_documents(
    project_id: str,
    current: str = Query(...),
    baseline: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_member(project_id, current_user, db)
    cr = db.compare.get_or_create(project_id, current, baseline)
    diffs = db.compare.list_diffs(cr.id)
    result = []
    for d in diffs:
        doc = db.documents.get(d.document_id)
        if doc:
            result.append({
                "document_id": d.document_id,
                "name": doc.name,
                "process": doc.process,
                "diff_type": d.diff_type,
                "sections_changed": d.sections_changed,
            })
    return {"documents": result, "summary": cr.diff_summary}


@router.get("/projects/{project_id}/compare/documents/{doc_id}",
            responses={200: {"model": CompareDocumentDetailResponse}})
def compare_document_detail(
    project_id: str,
    doc_id: str,
    current: str = Query(...),
    baseline: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_member(project_id, current_user, db)
    doc = db.documents.get(doc_id)
    if not doc or doc.project_id != project_id:
        raise not_found("Document", doc_id)
    cr = db.compare.get_or_create(project_id, current, baseline)
    diff = db.compare.get_document_diff(cr.id, doc_id)
    sections = db.documents.list_sections(doc_id)
    changed_keys = set(diff.sections_changed) if diff else set()
    section_diffs = []
    for s in sections:
        dt = "changed" if s.section_key in changed_keys else "unchanged"
        section_diffs.append({
            "key": s.section_key,
            "title": s.title,
            "diff_type": dt,
            "current_content": s.content,
            "baseline_content": s.content if dt == "unchanged" else "[previous version content]",
        })
    return {"document_name": doc.name, "sections": section_diffs}
