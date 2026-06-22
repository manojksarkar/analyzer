"""Documents routes — /api/v1/projects/:id/documents/*"""
from __future__ import annotations
import io
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel

from ..db.session import get_db
from ..db.in_memory import InMemoryDatabase
from ..middleware.auth import get_current_user, require_project_admin, require_project_member
from ..models.domain import User, DocumentAssignment
from ..services.errors import not_found, forbidden

router = APIRouter(tags=["documents"])
UTC = timezone.utc


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class UpdateDocumentRequest(BaseModel):
    status: Optional[str] = None
    due_date: Optional[str] = None


class UpdateSectionRequest(BaseModel):
    review_state: str                  # "accepted" | "declined" | "edited"
    edited_content: Optional[str] = None


class AssignRequest(BaseModel):
    user_ids: list[str]


class BatchAssignRequest(BaseModel):
    document_ids: list[str]
    user_ids: list[str]


class ApproveAllRequest(BaseModel):
    version_id: str
    process_filter: Optional[list[str]] = None


class ExportAllRequest(BaseModel):
    version_id: str
    process_filter: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _doc_dict(doc, assignees: list, sections=None) -> dict:
    d = {
        "id": doc.id,
        "name": doc.name,
        "subtitle": doc.subtitle,
        "process": doc.process,
        "layer": doc.layer,
        "group": doc.group,
        "status": doc.status,
        "version_id": doc.version_id,
        "due_date": doc.due_date.isoformat() if doc.due_date else None,
        "assignees": assignees,
        "created_at": doc.created_at.isoformat(),
        "updated_at": doc.updated_at.isoformat(),
    }
    if sections is not None:
        resolved = sum(1 for s in sections if s.review_state in ("accepted", "declined", "edited"))
        d["sections"] = [
            {
                "key": s.section_key,
                "title": s.title,
                "order": s.order,
                "content": s.content,
                "review_state": s.review_state,
                "reviewed_by": s.reviewed_by,
                "reviewed_at": s.reviewed_at.isoformat() if s.reviewed_at else None,
            }
            for s in sections
        ]
        d["review_progress"] = {"resolved": resolved, "total": len(sections)}
    return d


def _assignee_views(document_id: str, db: InMemoryDatabase) -> list[dict]:
    assignments = db.assignments.list_for_document(document_id)
    user_ids = [a.user_id for a in assignments]
    users = {u.id: u for u in db.users.list_by_ids(user_ids)}
    return [
        {"user_id": uid, "name": users[uid].name, "initials": users[uid].initials}
        for uid in user_ids if uid in users
    ]


# ---------------------------------------------------------------------------
# Routes — document list & detail
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/documents/stats")
def document_stats(
    project_id: str,
    version_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_member(project_id, current_user, db)
    return {"stats": db.documents.get_stats(project_id, version_id)}


@router.get("/projects/{project_id}/documents")
def list_documents(
    project_id: str,
    version_id: Optional[str] = Query(None),
    process: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    assignee_id: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_member(project_id, current_user, db)
    docs, total = db.documents.list_for_project(
        project_id, version_id=version_id, process=process,
        status=status, assignee_id=assignee_id, query=q,
        page=page, per_page=per_page,
    )
    return {
        "documents": [_doc_dict(d, _assignee_views(d.id, db)) for d in docs],
        "pagination": {"page": page, "per_page": per_page, "total": total},
    }


@router.get("/projects/{project_id}/documents/{doc_id}")
def get_document(
    project_id: str,
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_member(project_id, current_user, db)
    doc = db.documents.get(doc_id)
    if not doc or doc.project_id != project_id:
        raise not_found("Document", doc_id)
    sections = db.documents.list_sections(doc_id)
    return {"document": _doc_dict(doc, _assignee_views(doc_id, db), sections)}


@router.patch("/projects/{project_id}/documents/{doc_id}")
def update_document(
    project_id: str,
    doc_id: str,
    body: UpdateDocumentRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    require_project_admin(project_id, current_user, db)
    doc = db.documents.get(doc_id)
    if not doc or doc.project_id != project_id:
        raise not_found("Document", doc_id)
    if body.status:
        doc.status = body.status
    doc.updated_at = datetime.now(UTC)
    db.documents.update(doc)
    return {"document": _doc_dict(doc, _assignee_views(doc_id, db))}


# ---------------------------------------------------------------------------
# Download (stub — returns minimal DOCX bytes)
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/documents/{doc_id}/download")
def download_document(
    project_id: str,
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_member(project_id, current_user, db)
    doc = db.documents.get(doc_id)
    if not doc or doc.project_id != project_id:
        raise not_found("Document", doc_id)
    # Return a 1-byte placeholder so the endpoint is exercisable
    return Response(
        content=b"PK\x03\x04",   # DOCX/ZIP magic bytes
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{doc.name}.docx"'},
    )


# ---------------------------------------------------------------------------
# Assignments
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/documents/{doc_id}/assignments", status_code=201)
def assign_reviewers(
    project_id: str,
    doc_id: str,
    body: AssignRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    require_project_admin(project_id, current_user, db)
    doc = db.documents.get(doc_id)
    if not doc or doc.project_id != project_id:
        raise not_found("Document", doc_id)
    now = datetime.now(UTC)
    for uid in body.user_ids:
        db.assignments.assign(DocumentAssignment(
            id=f"asgn{uuid.uuid4().hex[:8]}",
            document_id=doc_id, user_id=uid,
            assigned_by=current_user.id, assigned_at=now,
        ))
    return {"assignees": _assignee_views(doc_id, db)}


@router.delete("/projects/{project_id}/documents/{doc_id}/assignments/{user_id}", status_code=204)
def remove_assignee(
    project_id: str,
    doc_id: str,
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    require_project_admin(project_id, current_user, db)
    db.assignments.remove(doc_id, user_id)


@router.post("/projects/{project_id}/documents/assignments/batch", status_code=201)
def batch_assign(
    project_id: str,
    body: BatchAssignRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    require_project_admin(project_id, current_user, db)
    now = datetime.now(UTC)
    for doc_id in body.document_ids:
        for uid in body.user_ids:
            db.assignments.assign(DocumentAssignment(
                id=f"asgn{uuid.uuid4().hex[:8]}",
                document_id=doc_id, user_id=uid,
                assigned_by=current_user.id, assigned_at=now,
            ))
    return {"message": "Batch assignment complete."}


@router.post("/projects/{project_id}/documents/{doc_id}/assignments/self", status_code=201)
def self_assign(
    project_id: str,
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    member = db.members.get_member(project_id, current_user.id)
    if not member or member.role != "developer":
        raise forbidden("Only developers may self-assign.")
    db.assignments.assign(DocumentAssignment(
        id=f"asgn{uuid.uuid4().hex[:8]}",
        document_id=doc_id, user_id=current_user.id,
        assigned_by=current_user.id, assigned_at=datetime.now(UTC),
    ))
    return {"assignees": _assignee_views(doc_id, db)}


# ---------------------------------------------------------------------------
# Section-level review
# ---------------------------------------------------------------------------

@router.patch("/projects/{project_id}/documents/{doc_id}/sections/{section_key}")
def review_section(
    project_id: str,
    doc_id: str,
    section_key: str,
    body: UpdateSectionRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    require_project_member(project_id, current_user, db)
    section = db.documents.get_section(doc_id, section_key)
    if not section:
        raise not_found("Section", section_key)
    section.review_state = body.review_state
    if body.review_state == "edited" and body.edited_content:
        section.content = body.edited_content
    section.reviewed_by = current_user.id
    section.reviewed_at = datetime.now(UTC)
    db.documents.update_section(section)
    return {
        "section": {
            "key": section.section_key,
            "review_state": section.review_state,
            "reviewed_by": section.reviewed_by,
        }
    }


@router.post("/projects/{project_id}/documents/{doc_id}/submit-review")
def submit_review(
    project_id: str,
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    require_project_member(project_id, current_user, db)
    doc = db.documents.get(doc_id)
    if not doc or doc.project_id != project_id:
        raise not_found("Document", doc_id)
    doc.status = "in_review"
    doc.updated_at = datetime.now(UTC)
    db.documents.update(doc)
    return {"message": "Review submitted.", "document_id": doc_id}


@router.post("/projects/{project_id}/documents/{doc_id}/approve")
def approve_document(
    project_id: str,
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    require_project_admin(project_id, current_user, db)
    doc = db.documents.get(doc_id)
    if not doc or doc.project_id != project_id:
        raise not_found("Document", doc_id)
    doc.status = "approved"
    doc.updated_at = datetime.now(UTC)
    db.documents.update(doc)
    return {"document_id": doc_id, "status": "approved"}


@router.post("/projects/{project_id}/documents/{doc_id}/request-changes")
def request_changes(
    project_id: str,
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    require_project_admin(project_id, current_user, db)
    doc = db.documents.get(doc_id)
    if not doc or doc.project_id != project_id:
        raise not_found("Document", doc_id)
    doc.status = "in_review"
    doc.updated_at = datetime.now(UTC)
    db.documents.update(doc)
    return {"document_id": doc_id, "status": "in_review"}


@router.post("/projects/{project_id}/documents/approve-all")
def approve_all(
    project_id: str,
    body: ApproveAllRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    require_project_admin(project_id, current_user, db)
    docs, _ = db.documents.list_for_project(
        project_id, version_id=body.version_id, per_page=1000,
    )
    now = datetime.now(UTC)
    approved_ids = []
    for doc in docs:
        if body.process_filter and doc.process not in body.process_filter:
            continue
        doc.status = "approved"
        doc.updated_at = now
        db.documents.update(doc)
        approved_ids.append(doc.id)
    return {"approved_count": len(approved_ids), "document_ids": approved_ids}


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/documents/{doc_id}/export")
def export_document(
    project_id: str,
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_member(project_id, current_user, db)
    doc = db.documents.get(doc_id)
    if not doc or doc.project_id != project_id:
        raise not_found("Document", doc_id)
    return Response(
        content=b"PK\x03\x04",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{doc.name}.docx"'},
    )


@router.post("/projects/{project_id}/documents/export-all")
def export_all(
    project_id: str,
    body: ExportAllRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    require_project_member(project_id, current_user, db)
    # Return a signed URL stub
    return {
        "download_url": f"/api/v1/projects/{project_id}/documents/export-all/download?version_id={body.version_id}",
        "expires_at": "2026-06-22T12:15:00Z",
    }
