"""Documents routes — /api/v1/projects/:id/documents/*"""
from __future__ import annotations
import zipfile
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..db.session import get_db
from ..db.in_memory import InMemoryDatabase
from ..middleware.auth import get_current_user, require_project_admin, require_project_member
from ..models.domain import User
from ..services.errors import bad_request, not_found, forbidden
from ..services import doc_render, review_workflow as rw
from ..services.document_payload import build_document_render
from ..schemas import RenderResponse, ExportAllResponse

router = APIRouter(tags=["documents"])
UTC = timezone.utc


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class UpdateDocumentRequest(BaseModel):
    status: Optional[str] = None
    due_date: Optional[str] = None


# Review and approval (docs/spec/REVIEW_APPROVE_API_SPEC.md §3). Comments are checked by
# review_workflow.clean_text, so a blank one and a missing one get the same 422.
class AssignRequest(BaseModel):
    user_id: Optional[str] = None
    user_ids: Optional[list[str]] = None     # the older shape: exactly one


class BatchAssignRequest(BaseModel):
    document_ids: list[str] = Field(..., min_length=1, max_length=500)
    user_id: Optional[str] = None
    user_ids: Optional[list[str]] = None


class CommentRequest(BaseModel):
    comment: Optional[str] = None


class ReopenRequest(BaseModel):
    reason: Optional[str] = None


class ApproveAllRequest(BaseModel):
    document_ids: list[str] = Field(..., min_length=1, max_length=500)
    comment: Optional[str] = None


class ExportAllRequest(BaseModel):
    version_id: str
    process_filter: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _document(db, project_id: str, doc_id: str):
    """The document `doc_id` of `project_id` -- 404 when it belongs to another project. Every
    route that takes a document id asks this: an id alone named any project's document."""
    doc = db.documents.get(doc_id)
    if not doc or doc.project_id != project_id:
        raise not_found("Document", doc_id)
    return doc


def _project(db, project_id: str):
    project = db.projects.get(project_id)
    if not project:
        raise not_found("Project", project_id)
    return project


class ApprovedFileMissing(Exception):
    """An approved document whose kept Word file is not here, and whose working file is not the
    approved one."""


def _docx_for(db, project_id: str, doc):
    """The Word file a download serves: the copy kept at approval for an approved document
    (a later update cannot change what was approved), else the version's own.

    An approved document whose kept copy is missing gets the working file only when it IS the
    approved file (its SHA-256 is `docx_sha256`); otherwise `ApprovedFileMissing` -- never a file
    that may differ from what was approved (WORD_FILE_UPDATES §4.8)."""
    kept = rw.approved_docx(doc)
    if kept is not None:
        return kept
    version = db.versions.get(doc.version_id) if doc.version_id else None
    out_root = doc_render.commit_output_root(project_id, version.commit_sha, version.id) if version else None
    working = doc_render.find_docx(doc.group, out_root, doc.process)
    if doc.status == "approved":
        if working is None or not doc.docx_sha256 or _sha256(working) != doc.docx_sha256:
            raise ApprovedFileMissing(doc.id)
    return working


def _sha256(path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _approved_missing(docs) -> HTTPException:
    names = ", ".join(rw.label(d) for d in docs[:5]) + (" and %d more" % (len(docs) - 5)
                                                      if len(docs) > 5 else "")
    return HTTPException(status_code=409, detail={
        "code": "APPROVED_FILE_MISSING", "status": 409,
        "document_ids": [d.id for d in docs],
        "message": "The approved Word file of %s is not on this server, and the current file is "
                   "not the one that was approved. Restore the kept copy, or reopen and approve "
                   "again." % names})


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
        "documents": rw.document_views(db, docs),
        "pagination": {"page": page, "per_page": per_page, "total": total},
    }


# ---------------------------------------------------------------------------
# Synthesized render fallback helpers
# ---------------------------------------------------------------------------

def _parse_md_table(content: str) -> Optional[dict]:
    lines = [l.strip() for l in content.strip().splitlines() if l.strip().startswith("|")]
    if len(lines) < 2:
        return None
    def cells(line: str) -> list[str]:
        return [c.strip() for c in line.strip().strip("|").split("|")]
    return {"headers": cells(lines[0]), "rows": [cells(l) for l in lines[2:]]}


def _arch_summary(project) -> tuple[list[str], list[str]]:
    layers: list[str] = []
    components: list[str] = []
    for layer in (project.architecture_layers or []):
        if not isinstance(layer, dict):
            continue
        if layer.get("name"):
            layers.append(layer["name"])
        for grp in layer.get("groups", []) or []:
            if isinstance(grp, str):
                components.append(grp)
            elif isinstance(grp, dict):
                comps = grp.get("components") or []
                if comps:
                    for c in comps:
                        name = c.get("name") if isinstance(c, dict) else c
                        if name:
                            components.append(name)
                elif grp.get("name"):
                    components.append(grp["name"])
    return layers, components


def _render_section(s) -> dict:
    table = _parse_md_table(s.content)
    node: dict = {
        "id": s.section_key, "number": str(s.order), "title": s.title, "level": 1,
        "type": "table" if table else "richtext",
        "content": None if table else s.content,
        "table": table, "children": [],
    }
    if s.section_key == "dynamic_design":
        node["children"] = [
            {"id": "dyn_cfg", "number": f"{s.order}.1", "title": "Control Flow Graphs",
             "level": 2, "type": "diagram", "content": "Per-function CFGs from Clang AST.",
             "table": None, "children": []},
            {"id": "dyn_state", "number": f"{s.order}.2", "title": "State Machine",
             "level": 2, "type": "diagram", "content": "Unit lifecycle states and transitions.",
             "table": None, "children": []},
        ]
    elif s.section_key == "static_design":
        node["children"] = [
            {"id": "static_diagram", "number": f"{s.order}.1", "title": "Include Dependencies",
             "level": 2, "type": "diagram", "content": "Include-dependency graph from Clang AST.",
             "table": None, "children": []},
        ]
    return node


def _flatten_toc(sections: list[dict]) -> list[dict]:
    out: list[dict] = []
    for s in sections:
        out.append({"id": s["id"], "number": s["number"], "title": s["title"], "level": s["level"]})
        out.extend(_flatten_toc(s["children"]))
    return out


def _render_doc_dict(doc, sections, project, version) -> dict:
    rich_sections = [_render_section(s) for s in sections]
    layers, components = _arch_summary(project)
    if not layers:
        layers = [doc.layer] if doc.layer else []
    if not components:
        components = [doc.group] if doc.group else []

    # Prepend the Introduction (Purpose / Scope / Terms) so the synthesized
    # fallback render matches the exported DOCX even without live pipeline output.
    intro_comps = components or ([doc.group] if doc.group else [])
    if not any(s.get("id") == "intro" for s in rich_sections):
        rich_sections = [doc_render.intro_section_from_config(intro_comps, project.name, version),
                         *rich_sections]
    units_total = max(len(components), 1) * 2
    return {
        "cover": {
            "project_name": project.name,
            "subtitle": doc.subtitle or "Software Detailed Design Specification",
            "version": version.tag if version else doc.version_id,
            "layer": doc.layer,
            "group": doc.group,
            "standard": project.compliance_standard,
            "process": doc.process,
            "generated_at": doc.updated_at.isoformat(),
        },
        "toc": _flatten_toc(rich_sections),
        "sections": rich_sections,
        "meta": {
            "pipeline_data_available": False,
            "model_data_available": True,
            "source": "model",
            "layers": layers,
            "components": components,
            "units_total": units_total,
            "functions_total": units_total * 4,
            "globals_total": units_total * 2,
        },
    }


# ---------------------------------------------------------------------------
# Render + Assets
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/documents/{doc_id}/render",
            responses={200: {"model": RenderResponse}})
def render_document(
    project_id: str,
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """Rich render payload (cover / toc / typed-nested sections / meta).

    Uses live pipeline output from ``output/<group>/`` when available;
    falls back to a synthesized payload from stored section bodies."""
    project = db.projects.get(project_id)
    if not project:
        raise not_found("Project", project_id)
    require_project_member(project_id, current_user, db)
    doc = db.documents.get(doc_id)
    if not doc or doc.project_id != project_id:
        raise not_found("Document", doc_id)
    version = db.versions.get(doc.version_id) if doc.version_id else None
    # The same build an approval fingerprints (services/document_payload.py).
    render = build_document_render(db, project, doc)
    if render is not None:
        return {"document": render}

    sections = db.documents.list_sections(doc_id)
    return {"document": _render_doc_dict(doc, sections, project, version)}


@router.get("/projects/{project_id}/documents/{doc_id}/assets/{asset_path:path}")
def document_asset(
    project_id: str,
    doc_id: str,
    asset_path: str,
    db: InMemoryDatabase = Depends(get_db),
):
    """Stream a diagram file (PNG/SVG/MMD) from the document's live pipeline output.

    Intentionally unauthenticated so ``<img>`` tags can load diagrams directly."""
    doc = db.documents.get(doc_id)
    if not doc or doc.project_id != project_id:
        raise not_found("Document", doc_id)
    version = db.versions.get(doc.version_id) if doc.version_id else None
    out_root = doc_render.commit_output_root(project_id, version.commit_sha, version.id) if version else None
    target = doc_render.resolve_asset(doc.group, asset_path, out_root)
    if target is None:
        raise not_found("Asset", asset_path)
    if target.suffix.lower() == ".svg":
        # Named explicitly: an <img> shows an SVG only as image/svg+xml, and the guess comes
        # from the OS registry on Windows. And an SVG is a document too: opened on its own tab
        # it could run script from this origin. Graphviz writes none; the policy keeps it so.
        # no-cache: a label correction redraws the file under the same name, so the browser
        # must ask again (the ETag answers 304 when nothing changed) instead of showing its copy.
        return FileResponse(target, media_type="image/svg+xml", headers={
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-cache",
        })
    return FileResponse(target)


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
    doc = _document(db, project_id, doc_id)
    sections = db.documents.list_sections(doc_id)
    return {"document": rw.document_view(db, doc, sections)}


@router.patch("/projects/{project_id}/documents/{doc_id}")
def update_document(
    project_id: str,
    doc_id: str,
    body: UpdateDocumentRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    require_project_admin(project_id, current_user, db)
    doc = _document(db, project_id, doc_id)
    if body.status is not None:
        # Retired (REVIEW_APPROVE_API_SPEC §3): any string was accepted, and approval had no
        # record. A state moves only through submit, approve, request changes and reopen.
        raise bad_request("A document's status moves only through submit-review, approve, "
                          "request-changes and reopen.")
    if "due_date" in body.model_fields_set:
        # Stored now (it was accepted and dropped): a review deadline, `YYYY-MM-DD`, or null to clear.
        try:
            doc.due_date = date.fromisoformat(body.due_date) if body.due_date else None
        except ValueError:
            raise rw.unprocessable("VALIDATION_ERROR", "due_date must be a date, YYYY-MM-DD.")
    doc.updated_at = datetime.now(UTC)
    db.documents.update(doc)
    return {"document": rw.document_view(db, doc)}


# ---------------------------------------------------------------------------
# Export-all download — must be registered BEFORE /{doc_id}/download so the
# literal segment "export-all" wins over the {doc_id} parameter.
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/documents/export-all/download")
def download_export_all(
    project_id: str,
    version_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """Stream a ZIP of all available DOCX files for the version."""
    if not db.projects.get(project_id):
        raise not_found("Project", project_id)
    require_project_member(project_id, current_user, db)
    docs, _ = db.documents.list_for_project(project_id, version_id=version_id, per_page=1000)
    # An approved document whose approved file is not here fails the archive by name, before
    # anything is written (WORD_FILE_UPDATES §4.8).
    missing = []
    for doc in docs:
        try:
            _docx_for(db, project_id, doc)
        except ApprovedFileMissing:
            missing.append(doc)
    if missing:
        raise _approved_missing(missing)

    # Built in a temporary file, not in memory, with the files STORED: a version of a large
    # project holds dozens of Word files of tens of MB each (every flowchart is a picture), so the
    # archive held in memory reached gigabytes for one click; and a DOCX is already a ZIP, so
    # compressing it again only cost CPU. The file is deleted once it has been sent.
    import os
    import tempfile
    from starlette.background import BackgroundTask
    fd, path = tempfile.mkstemp(prefix="export-", suffix=".zip")
    added = 0
    try:
        with os.fdopen(fd, "wb") as fh, zipfile.ZipFile(fh, "w", zipfile.ZIP_STORED) as zf:
            seen = set()
            for doc in docs:
                docx = _docx_for(db, project_id, doc)
                # The DOCX's own name carries the layer-qualified component id, so it is unique.
                # `doc.name` is not: two layers with a component of the same name wrote two
                # entries with one name, and unzipping kept only one of them.
                if docx is not None and docx.name not in seen:
                    zf.write(docx, arcname=docx.name)
                    seen.add(docx.name)
                    added += 1
    except Exception:
        os.unlink(path)
        raise

    # An archive with nothing in it is still a valid (empty) ZIP, as before.
    return FileResponse(path, media_type="application/zip", filename="export.zip",
                        background=BackgroundTask(os.unlink, path))


# ---------------------------------------------------------------------------
# Download — real DOCX when available, stub otherwise
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
    doc = _document(db, project_id, doc_id)
    try:
        docx = _docx_for(db, project_id, doc)
    except ApprovedFileMissing:
        raise _approved_missing([doc])
    if docx is not None:
        # The file's own name: `doc.name` is the component, which its SWE.3 and SWE.4
        # documents share. (An approved copy keeps it: approved/<doc id>/<file name>.)
        return FileResponse(
            docx,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{docx.name}"'},
        )
    return Response(
        content=b"PK\x03\x04",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{doc.name}.docx"'},
    )


# ---------------------------------------------------------------------------
# Review and approval — docs/spec/REVIEW_APPROVE_API_SPEC.md §3 (A1–A11)
#
# The rules -- what state a document may be in, what each step records and who hears of it --
# are services/review_workflow.py. Here: who may call, and that the document is this project's.
# ---------------------------------------------------------------------------

def _one_user(user_id: Optional[str], user_ids: Optional[list[str]]) -> str:
    ids = [u for u in ([user_id] if user_id else []) + list(user_ids or []) if u]
    ids = list(dict.fromkeys(ids))
    if len(ids) != 1:
        raise rw.unprocessable("VALIDATION_ERROR",
                               "Name exactly one reviewer: a document has one reviewer.")
    return ids[0]


@router.post("/projects/{project_id}/documents/{doc_id}/assignments")
def assign_reviewer(
    project_id: str,
    doc_id: str,
    body: AssignRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """A1 — make one user the document's reviewer, replacing any."""
    require_project_admin(project_id, current_user, db)
    doc = _document(db, project_id, doc_id)
    rw.assign(db, doc, _one_user(body.user_id, body.user_ids), current_user)
    return {"document": rw.document_view(db, doc)}


@router.delete("/projects/{project_id}/documents/{doc_id}/assignments/{user_id}", status_code=204)
def remove_reviewer(
    project_id: str,
    doc_id: str,
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """A3."""
    require_project_admin(project_id, current_user, db)
    rw.unassign(db, _document(db, project_id, doc_id), user_id, current_user)


@router.post("/projects/{project_id}/documents/assignments/batch")
def batch_assign(
    project_id: str,
    body: BatchAssignRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """A2 — one reviewer for several documents; those that cannot take one are reported."""
    require_project_admin(project_id, current_user, db)
    user_id = _one_user(body.user_id, body.user_ids)
    assigned, skipped, first = [], [], None
    for doc_id in dict.fromkeys(body.document_ids):
        doc = db.documents.get(doc_id)
        if not doc or doc.project_id != project_id:
            skipped.append({"document_id": doc_id, "code": "NOT_FOUND",
                            "message": "Document %s does not exist." % doc_id})
            continue
        try:
            if rw.assign(db, doc, user_id, current_user, tell=False):
                assigned.append(doc_id)
                first = first or doc
        except HTTPException as exc:
            if exc.status_code == 422:       # the reviewer is not a member: no document can take them
                raise
            detail = exc.detail if isinstance(exc.detail, dict) else {"code": "ERROR", "message": str(exc.detail)}
            skipped.append({"document_id": doc_id, "code": detail.get("code"), "message": detail.get("message")})
    if assigned:
        msg = ("%s assigned you to review %s." % (current_user.name, rw.label(first))
               if len(assigned) == 1 else
               "%s assigned you %d documents to review." % (current_user.name, len(assigned)))
        rw.notify(db, [user_id], project_id, first if len(assigned) == 1 else None,
                  rw.N_ASSIGNED, msg, skip=current_user.id)
    return {"assigned": assigned, "skipped": skipped}


@router.post("/projects/{project_id}/documents/{doc_id}/assignments/self")
def claim_document(
    project_id: str,
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """A4 — an active developer becomes the reviewer of a document that has none."""
    _project(db, project_id)
    member = rw.active_member(db, project_id, current_user.id)
    if member is None or member.role not in rw.CLAIMING_ROLES:
        raise forbidden("Only an active developer or reviewer of this project claims a document; "
                        "an admin assigns one.")
    doc = _document(db, project_id, doc_id)
    rw.claim(db, doc, current_user)
    return {"document": rw.document_view(db, doc)}


@router.post("/projects/{project_id}/documents/{doc_id}/submit-review")
def submit_review(
    project_id: str,
    doc_id: str,
    body: CommentRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """A5 — its reviewer (or an admin) submits it for approval, saying what was checked.

    When its Word file is out of date the update of its component starts too, for the approval
    (`word_file`; docs/design/WORD_FILE_UPDATES.md §4.4). A refusal there -- another update, a
    generation holding the version -- is reported in `word_file`, and the submit stands."""
    require_project_member(project_id, current_user, db)
    doc = _document(db, project_id, doc_id)
    rw.submit(db, doc, current_user, rw.clean_text(body.comment, "A comment", required=True))
    from ..services.word_files import submit_word_file
    view = rw.document_view(db, doc)            # read before the update's thread starts
    return {"document": view, "word_file": submit_word_file(db, doc, current_user)}


@router.post("/projects/{project_id}/documents/{doc_id}/approve")
def approve_document(
    project_id: str,
    doc_id: str,
    body: Optional[CommentRequest] = None,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """A6 — approve, keeping the Word file and its hash; refused while the file lacks corrections."""
    require_project_admin(project_id, current_user, db)
    project = _project(db, project_id)
    doc = _document(db, project_id, doc_id)
    comment = rw.clean_text(body.comment if body else None, "A comment", required=False)
    rw.approve(db, project, doc, current_user, comment)
    return {"document": rw.document_view(db, doc)}


@router.post("/projects/{project_id}/documents/{doc_id}/request-changes")
def request_changes(
    project_id: str,
    doc_id: str,
    body: CommentRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """A7 — send it back to its reviewer, saying what needs to change."""
    require_project_admin(project_id, current_user, db)
    doc = _document(db, project_id, doc_id)
    rw.request_changes(db, doc, current_user, rw.clean_text(body.comment, "A comment", required=True))
    return {"document": rw.document_view(db, doc)}


@router.post("/projects/{project_id}/documents/{doc_id}/reopen")
def reopen_document(
    project_id: str,
    doc_id: str,
    body: ReopenRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """A8 — an approved document back to In review, on the record."""
    require_project_admin(project_id, current_user, db)
    doc = _document(db, project_id, doc_id)
    rw.reopen(db, doc, current_user, rw.clean_text(body.reason, "A reason", required=True))
    return {"document": rw.document_view(db, doc)}


@router.post("/projects/{project_id}/documents/approve-all")
def approve_several(
    project_id: str,
    body: ApproveAllRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """A9 — approve the listed documents that are ready for approval, each on its own record.

    It used to take a version and approve all of it -- every version's documents when the
    version was empty -- with no record. Now it takes the documents, by id, of this project.
    """
    require_project_admin(project_id, current_user, db)
    project = _project(db, project_id)
    comment = rw.clean_text(body.comment, "A comment", required=False)
    approved, skipped = [], []
    for doc_id in dict.fromkeys(body.document_ids):
        doc = db.documents.get(doc_id)
        if not doc or doc.project_id != project_id:
            skipped.append({"document_id": doc_id, "code": "NOT_FOUND",
                            "message": "Document %s does not exist." % doc_id})
            continue
        try:
            rw.approve(db, project, doc, current_user, comment, only_ready=True)
            approved.append(doc_id)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"code": "ERROR", "message": str(exc.detail)}
            # A6's refusal as it is: STALE_EXPORT's why / corrections / pictures / layer,
            # WORD_FILE_UPDATING's job_id (WORD_FILE_UPDATES §4.5).
            extra = {k: v for k, v in detail.items() if k not in ("code", "message", "status")}
            skipped.append({"document_id": doc_id, "code": detail.get("code"),
                            "message": detail.get("message"), **extra})
    return {"approved": approved, "skipped": skipped}


@router.post("/projects/{project_id}/versions/{version_id}/documents/register")
def register_version_documents(
    project_id: str,
    version_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """A17 — record the version's Word files that have no document yet, and open their review.

    For a version generated from the command line, or before review and approval existed: its
    documents are on disk and nothing lists them. Idempotent; regenerates nothing.
    """
    require_project_admin(project_id, current_user, db)
    project = _project(db, project_id)
    version = db.versions.get(version_id)
    if not version or version.project_id != project_id:
        raise not_found("Version", version_id)
    from ..services.document_registry import register_documents
    docs = register_documents(db, project, version)
    return {"registered": rw.document_views(db, docs),
            "carried": sum(1 for d in docs if d.status == "approved")}


@router.get("/reviews/mine")
def my_reviews(
    include_approved: bool = Query(False),
    limit: int = Query(200, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """A18 — the documents the caller reviews, across every project they are an active member of:
    each with its project and version, newest version first; approved ones only on request."""
    projects = (db.projects.list_all() if getattr(current_user, "is_superuser", False)
                else db.projects.list_for_user(current_user.id))
    out = []
    for project in projects:
        docs, _ = db.documents.list_for_project(project.id, assignee_id=current_user.id,
                                                per_page=rw.ALL)
        docs = [d for d in docs if include_approved or d.status != "approved"]
        if not docs:
            continue
        tags = {}
        for view in rw.document_views(db, docs):
            vid = view["version_id"]
            if vid not in tags:
                v = db.versions.get(vid)
                tags[vid] = (v.tag if v else None, v.created_at if v else None)
            out.append({**view, "project": {"id": project.id, "name": project.name},
                        "version": {"id": vid, "tag": tags[vid][0]},
                        "_order": rw._aware(tags[vid][1])})
    out.sort(key=lambda d: (d["name"], d["process"]))          # then, stably: newest version first
    out.sort(key=lambda d: d["_order"], reverse=True)
    for d in out:
        d.pop("_order")
    return {"documents": out[:limit], "total": len(out)}


@router.get("/projects/{project_id}/documents/{doc_id}/events")
def document_events(
    project_id: str,
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """A10 — the document's review record, newest first."""
    _project(db, project_id)
    require_project_member(project_id, current_user, db)
    doc = _document(db, project_id, doc_id)
    return {"events": rw.event_views(db, db.review_events.list_for_document(doc.id))}


@router.get("/projects/{project_id}/review-events")
def project_review_events(
    project_id: str,
    version_id: Optional[str] = Query(None),
    document_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """A11 — the project's review record, newest first, each with its document."""
    _project(db, project_id)
    require_project_member(project_id, current_user, db)
    events = db.review_events.list_for_project(project_id, version_id=version_id,
                                               document_id=document_id, limit=limit)
    return {"events": rw.event_views(db, events, with_documents=True)}


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
    doc = _document(db, project_id, doc_id)
    try:
        docx = _docx_for(db, project_id, doc)
    except ApprovedFileMissing:
        raise _approved_missing([doc])
    if docx is not None:
        return FileResponse(
            docx,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{doc.name}.docx"'},
        )
    return Response(
        content=b"PK\x03\x04",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{doc.name}.docx"'},
    )


@router.post("/projects/{project_id}/documents/export-all",
             responses={200: {"model": ExportAllResponse}})
def export_all(
    project_id: str,
    body: ExportAllRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    require_project_member(project_id, current_user, db)
    return {
        "download_url": f"/api/v1/projects/{project_id}/documents/export-all/download?version_id={body.version_id}",
        "expires_at": "2099-12-31T23:59:59Z",
    }
