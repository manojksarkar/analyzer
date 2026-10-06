"""Review and approval — the rules (docs/spec/REVIEW_APPROVE_API_SPEC.md; why: docs/design/
REVIEW_APPROVE_DESIGN.md).

A document moves In review -> (its reviewer submits) Ready for approval -> (an admin) Approved, or
back as Changes requested; an admin reopens an approved one. Each step here checks the state it
starts from, records a `ReviewEvent` (who, when, why: the review evidence), writes the
notifications, and rolls the version's and the project's status up from the documents.

Who may call each step is the route's check (role, membership). What state a document may be in,
and what follows from a step, is here -- so every route, and the run that carries approvals into a
new version, obeys the same rules.
"""
from __future__ import annotations

import hashlib
import shutil
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from fastapi import HTTPException, status as http_status

from ..models.domain import DOC_STATUSES, DocumentAssignment, Notification, ReviewEvent
from . import doc_render
from .errors import conflict, forbidden, not_found

UTC = timezone.utc
MAX_COMMENT = 2000
ALL = 1_000_000          # "every document of the version" for a paged repository call

# notification types (contract A16)
N_ASSIGNED, N_UNASSIGNED, N_CLAIMED = "review_assigned", "review_unassigned", "review_claimed"
N_SUBMITTED, N_APPROVED = "review_submitted", "review_approved"
N_CHANGES, N_REOPENED, N_BACK = "review_changes_requested", "review_reopened", "review_back_in_review"


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
_stamp_lock = threading.Lock()
_last_stamp: Optional[datetime] = None


def _stamp() -> datetime:
    """Now -- but strictly after the previous event, so `at` alone orders the record even when
    one request records two steps inside the clock's resolution (15 ms on Windows)."""
    global _last_stamp
    with _stamp_lock:
        now = datetime.now(UTC)
        if _last_stamp is not None and now <= _last_stamp:
            now = _last_stamp + timedelta(microseconds=1)
        _last_stamp = now
        return now


def unprocessable(code: str, msg: str) -> HTTPException:
    return HTTPException(status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                         detail={"code": code, "message": msg, "status": 422})


def clean_text(value: Optional[str], what: str, required: bool) -> Optional[str]:
    """A comment, reason or note: stripped; required ones not empty; none over MAX_COMMENT."""
    text = (value or "").strip()
    if required and not text:
        raise unprocessable("VALIDATION_ERROR", "%s is required." % what)
    if len(text) > MAX_COMMENT:
        raise unprocessable("VALIDATION_ERROR", "%s is longer than %d characters." % (what, MAX_COMMENT))
    return text or None


def label(doc: Any) -> str:
    return "%s (%s)" % (doc.name, doc.process)


def active_member(db: Any, project_id: str, user_id: str):
    m = db.members.get_member(project_id, user_id)
    return m if m is not None and m.status == "active" else None


def is_admin(db: Any, project_id: str, user: Any) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    m = active_member(db, project_id, user.id)
    return m is not None and m.role == "admin"


def admin_ids(db: Any, project_id: str) -> list[str]:
    return [m.user_id for m in db.members.list_members(project_id)
            if m.role == "admin" and m.status == "active"]


def reviewer_id(db: Any, doc: Any) -> Optional[str]:
    return db.assignments.reviewers([doc.id]).get(doc.id)


def record(db: Any, doc: Any, kind: str, actor_id: Optional[str], comment: Optional[str] = None,
           payload: Optional[dict] = None) -> ReviewEvent:
    ev = ReviewEvent(id="rev" + uuid.uuid4().hex[:12], document_id=doc.id,
                     project_id=doc.project_id, version_id=doc.version_id, kind=kind,
                     actor_id=actor_id, at=_stamp(), comment=comment, payload=payload or {})
    db.review_events.add(ev)
    return ev


def notify(db: Any, user_ids: Iterable[Optional[str]], project_id: str, doc: Any, kind: str,
           message: str, *, skip: Optional[str] = None) -> None:
    """One notification per user (each once), never to `skip` -- whoever did it."""
    now = datetime.now(UTC)
    for uid in dict.fromkeys(u for u in user_ids if u and u != skip):
        db.notifications.create(Notification(
            id="ntf" + uuid.uuid4().hex[:10], user_id=uid, project_id=project_id, type=kind,
            message=message, read_at=None, created_at=now,
            document_id=getattr(doc, "id", None)))


def _save(db: Any, doc: Any) -> None:
    doc.updated_at = datetime.now(UTC)
    db.documents.update(doc)


def _version_tag(db: Any, doc: Any) -> str:
    v = db.versions.get(doc.version_id) if doc.version_id else None
    return (v.tag if v else "") or ""


def _in(doc: Any, db: Any) -> str:
    tag = _version_tag(db, doc)
    return "%s%s" % (label(doc), " in %s" % tag if tag else "")


# ---------------------------------------------------------------------------
# views (contract §2)
# ---------------------------------------------------------------------------
def user_ref(u: Any) -> Optional[dict]:
    return {"user_id": u.id, "name": u.name, "initials": u.initials} if u is not None else None


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _aware(dt: Optional[datetime]) -> datetime:
    """For ordering: SQLite hands back naive datetimes where Postgres hands back aware ones."""
    if dt is None:
        return datetime.min.replace(tzinfo=UTC)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def event_view(ev: ReviewEvent, users: dict, document: Optional[Any] = None) -> dict:
    out = {"id": ev.id, "document_id": ev.document_id, "version_id": ev.version_id,
           "kind": ev.kind, "actor": user_ref(users.get(ev.actor_id)) if ev.actor_id else None,
           "at": _iso(ev.at), "comment": ev.comment, "payload": dict(ev.payload or {})}
    if document is not None:
        out["document"] = {"id": document.id, "name": document.name, "process": document.process}
    return out


def event_views(db: Any, events: list, with_documents: bool = False) -> list[dict]:
    users = {u.id: u for u in db.users.list_by_ids(
        list({e.actor_id for e in events if e.actor_id}))}
    docs: dict = {}
    if with_documents:
        for e in events:
            if e.document_id not in docs:
                docs[e.document_id] = db.documents.get(e.document_id)
    return [event_view(e, users, docs.get(e.document_id) if with_documents else None)
            for e in events]


def document_views(db: Any, docs: list) -> list[dict]:
    """The contract's Document for each of `docs`, with three repository reads in all."""
    ids = [d.id for d in docs]
    reviewers = db.assignments.reviewers(ids)
    last = db.review_events.last_for_documents(ids)
    wanted = set(reviewers.values()) | {d.approved_by for d in docs if d.approved_by} \
        | {e.actor_id for e in last.values() if e.actor_id}
    users = {u.id: u for u in db.users.list_by_ids(list(wanted))}
    tags: dict = {}
    out = []
    for d in docs:
        rv = user_ref(users.get(reviewers.get(d.id)))
        carried = None
        if d.carried_from:
            if d.carried_from not in tags:
                v = db.versions.get(d.carried_from)
                tags[d.carried_from] = v.tag if v else None
            carried = {"version_id": d.carried_from, "tag": tags[d.carried_from]}
        approved = d.status == "approved"
        out.append({
            "id": d.id, "name": d.name, "subtitle": d.subtitle, "process": d.process,
            "layer": d.layer, "group": d.group, "status": d.status, "version_id": d.version_id,
            "due_date": d.due_date.isoformat() if d.due_date else None,
            "assignees": [rv] if rv else [],
            "reviewer": rv,
            "review": {
                "comment": d.review_comment,
                "changes_comment": d.changes_comment if d.status == "changes_requested" else None,
                "approved_by": user_ref(users.get(d.approved_by)) if approved and d.approved_by else None,
                "approved_at": _iso(d.approved_at) if approved else None,
                "approval_comment": d.approval_comment if approved else None,
                "docx_sha256": d.docx_sha256 if approved else None,
                "carried_from": carried if approved else None,
                "last_event": event_view(last[d.id], users) if d.id in last else None,
            },
            "created_at": _iso(d.created_at),
            "updated_at": _iso(d.updated_at),
        })
    return out


def document_view(db: Any, doc: Any, sections: Optional[list] = None) -> dict:
    d = document_views(db, [doc])[0]
    if sections is not None:
        d["sections"] = [
            {"key": s.section_key, "title": s.title, "order": s.order, "content": s.content}
            for s in sections
        ]
    return d


# ---------------------------------------------------------------------------
# the Word file, the content fingerprint, the export guard
# ---------------------------------------------------------------------------
def freeze_docx(project: Any, version: Any, doc: Any) -> tuple[Optional[Path], Optional[str]]:
    """Keep a copy of the Word file being approved, and its SHA-256. A later re-export rewrites
    the working file; downloads of an approved document serve this copy (contract §4)."""
    out_root = (doc_render.commit_output_root(project.id, version.commit_sha, version.id)
                if version is not None else None)
    src = doc_render.find_docx(doc.group, out_root, doc.process)
    if src is None:
        return None, None
    dest = out_root.parent / "approved" / doc.id / src.name     # keeps the file's own name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest, hashlib.sha256(dest.read_bytes()).hexdigest()


def approved_docx(doc: Any) -> Optional[Path]:
    """The copy of an approved document's Word file, when there is one on this machine."""
    if doc.status != "approved" or not doc.approved_docx_path:
        return None
    p = Path(doc.approved_docx_path)
    return p if p.is_file() else None


def fingerprint(db: Any, project: Any, doc: Any) -> Optional[str]:
    """A hash of the document's rendered content -- the same build the page shows. None when it
    cannot be built here; then no approval is carried forward by it."""
    from .compare_render import render_fingerprint
    from .document_payload import build_document_render
    try:
        render = build_document_render(db, project, doc)
    except Exception:                                   # noqa: BLE001 -- no render, no carry
        return None
    text = render_fingerprint(render) if render else ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None


def word_file_state(db: Any, doc: Any):
    """`(FileState or None, updating, job id)` for the document's Word file -- the rule of
    docs/design/WORD_FILE_UPDATES.md §4.3 (A15's), and whether an update is writing its component
    now. The state is None when it cannot be asked here (no engine database: the in-memory test
    seam, where no correction exists either)."""
    from .word_files import approval_state
    return approval_state(db, doc)


# ---------------------------------------------------------------------------
# the steps
# ---------------------------------------------------------------------------
def _not_approved(doc: Any, doing: str) -> None:
    if doc.status == "approved":
        raise conflict("DOCUMENT_APPROVED", "%s is approved: reopen it before %s." % (label(doc), doing))


def assign(db: Any, doc: Any, user_id: str, actor: Any, *, tell: bool = True) -> bool:
    """Make `user_id` the reviewer, replacing any. False when they already were."""
    _not_approved(doc, "changing its reviewer")
    user = db.users.get_by_id(user_id)
    if user is None:
        raise not_found("User", user_id)
    if active_member(db, doc.project_id, user_id) is None:
        raise unprocessable("NOT_A_MEMBER", "%s is not an active member of this project." % user.name)
    before = reviewer_id(db, doc)
    if before == user_id:
        return False
    db.assignments.set_reviewer(DocumentAssignment(
        id="asgn" + uuid.uuid4().hex[:8], document_id=doc.id, user_id=user_id,
        assigned_by=actor.id, assigned_at=datetime.now(UTC)))
    record(db, doc, "assigned", actor.id, payload={"from_user_id": before, "to_user_id": user_id})
    _save(db, doc)
    if tell:
        notify(db, [user_id], doc.project_id, doc, N_ASSIGNED,
               "%s assigned you to review %s." % (actor.name, _in(doc, db)), skip=actor.id)
    if before:
        notify(db, [before], doc.project_id, doc, N_UNASSIGNED,
               "%s gave the review of %s to %s." % (actor.name, _in(doc, db), user.name),
               skip=actor.id)
    return True


def unassign(db: Any, doc: Any, user_id: str, actor: Any) -> None:
    _not_approved(doc, "removing its reviewer")
    if reviewer_id(db, doc) != user_id:
        return
    db.assignments.remove(doc.id, user_id)
    record(db, doc, "unassigned", actor.id, payload={"user_id": user_id})
    _save(db, doc)
    notify(db, [user_id], doc.project_id, doc, N_UNASSIGNED,
           "%s removed you as the reviewer of %s." % (actor.name, _in(doc, db)), skip=actor.id)


CLAIMING_ROLES = ("developer", "reviewer")     # an active member who is not an admin


def claim(db: Any, doc: Any, user: Any) -> None:
    _not_approved(doc, "claiming it")
    if reviewer_id(db, doc):
        raise conflict("HAS_REVIEWER", "%s already has a reviewer." % label(doc))
    db.assignments.set_reviewer(DocumentAssignment(
        id="asgn" + uuid.uuid4().hex[:8], document_id=doc.id, user_id=user.id,
        assigned_by=user.id, assigned_at=datetime.now(UTC)))
    record(db, doc, "claimed", user.id)
    _save(db, doc)
    notify(db, admin_ids(db, doc.project_id), doc.project_id, doc, N_CLAIMED,
           "%s claimed %s." % (user.name, _in(doc, db)), skip=user.id)


def submit(db: Any, doc: Any, actor: Any, comment: str) -> None:
    if doc.status not in ("in_review", "changes_requested"):
        raise conflict("WRONG_STATE", "%s is %s, so it cannot be submitted for approval."
                       % (label(doc), _state(doc)))
    rid = reviewer_id(db, doc)
    if not rid:
        raise conflict("NO_REVIEWER", "%s has no reviewer: assign or claim it first." % label(doc))
    if rid != actor.id and not is_admin(db, doc.project_id, actor):
        raise forbidden("Only the reviewer of %s, or an admin, submits it." % label(doc))
    again = doc.status == "changes_requested"
    doc.status, doc.review_comment, doc.changes_comment = "submitted", comment, None
    _save(db, doc)
    record(db, doc, "submitted", actor.id, comment=comment, payload={"again": again})
    notify(db, admin_ids(db, doc.project_id), doc.project_id, doc, N_SUBMITTED,
           "%s submitted %s for approval." % (actor.name, _in(doc, db)), skip=actor.id)


def approve(db: Any, project: Any, doc: Any, actor: Any, comment: Optional[str], *,
            only_ready: bool = False) -> None:
    """`only_ready`: a bulk approval takes Ready-for-approval documents only (A9)."""
    allowed = ("submitted",) if only_ready else ("submitted", "in_review")
    if doc.status not in allowed:
        raise conflict("WRONG_STATE", "%s is %s, not %s." % (
            label(doc), _state(doc),
            "ready for approval" if only_ready else "ready for approval or in review"))
    # The approval records the Word file (its hash, a kept copy): it must be the current one.
    # Approve turns on in the web app once the update is done (WORD_FILE_UPDATES §4.5).
    st, updating, job_id = word_file_state(db, doc)
    if updating:
        raise HTTPException(status_code=409, detail={
            "code": "WORD_FILE_UPDATING", "status": 409, "job_id": job_id,
            "message": "The Word file of %s is being updated now; approve it when that is done."
                       % label(doc)})
    if st is not None and st.out_of_date:
        raise HTTPException(status_code=409, detail={
            "code": "STALE_EXPORT", "status": 409, "why": list(st.why),
            "corrections": st.corrections, "pictures": st.pictures, "layer": st.layer,
            "message": "The Word file of %s is out of date (%s). Update it, then approve."
                       % (label(doc), _why_text(st))})
    version = db.versions.get(doc.version_id)
    path, sha = freeze_docx(project, version, doc)
    direct = doc.status == "in_review"
    doc.status = "approved"
    doc.approved_by, doc.approved_at, doc.approval_comment = actor.id, _stamp(), comment
    doc.docx_sha256, doc.approved_docx_path = sha, (str(path) if path else None)
    doc.content_fingerprint = fingerprint(db, project, doc)
    doc.carried_from = None
    _save(db, doc)
    record(db, doc, "approved", actor.id, comment=comment,
           payload={"docx_sha256": sha, "direct": direct})
    notify(db, [reviewer_id(db, doc)], doc.project_id, doc, N_APPROVED,
           "%s approved %s." % (actor.name, _in(doc, db)), skip=actor.id)
    roll_up(db, version)


def _why_text(st: Any) -> str:
    """`2 corrections not in it, HAL_LAYER added since` -- the mockup's words."""
    bits = []
    if st.corrections:
        bits.append("%d correction%s not in it" % (st.corrections, "" if st.corrections == 1 else "s"))
    if "layerAdded" in st.why:
        bits.append("%s added since" % (st.layer or "a layer"))
    if st.pictures:
        bits.append("%d flowchart picture%s still being drawn"
                    % (st.pictures, "" if st.pictures == 1 else "s"))
    return ", ".join(bits) or "out of date"


def request_changes(db: Any, doc: Any, actor: Any, comment: str) -> None:
    if doc.status != "submitted":
        raise conflict("WRONG_STATE", "%s is %s; changes are requested of a document ready for "
                       "approval." % (label(doc), _state(doc)))
    doc.status, doc.changes_comment = "changes_requested", comment
    _save(db, doc)
    record(db, doc, "changes_requested", actor.id, comment=comment)
    notify(db, [reviewer_id(db, doc)], doc.project_id, doc, N_CHANGES,
           "%s requested changes to %s." % (actor.name, _in(doc, db)), skip=actor.id)


def reopen(db: Any, doc: Any, actor: Any, reason: str) -> None:
    if doc.status != "approved":
        raise conflict("WRONG_STATE", "%s is %s; only an approved document is reopened."
                       % (label(doc), _state(doc)))
    sha = doc.docx_sha256
    doc.status = "in_review"
    doc.approved_by = doc.approved_at = doc.approval_comment = None
    doc.docx_sha256 = doc.approved_docx_path = doc.content_fingerprint = doc.carried_from = None
    doc.changes_comment = None
    _save(db, doc)
    record(db, doc, "reopened", actor.id, comment=reason, payload={"docx_sha256": sha})
    notify(db, [reviewer_id(db, doc)], doc.project_id, doc, N_REOPENED,
           "%s reopened %s: %s" % (actor.name, _in(doc, db), reason), skip=actor.id)
    roll_up(db, db.versions.get(doc.version_id))


def _state(doc: Any) -> str:
    return {"in_review": "in review", "submitted": "ready for approval",
            "changes_requested": "back with changes requested", "approved": "approved"}.get(
                doc.status, doc.status or "in no state")


# ---------------------------------------------------------------------------
# version and project status, derived
# ---------------------------------------------------------------------------
def version_docs(db: Any, version: Any) -> list:
    docs, _ = db.documents.list_for_project(version.project_id, version_id=version.id, per_page=ALL)
    return docs


def derived_status(version: Any, docs: list) -> str:
    """Approved when it has documents and every one is; in review while any is not. A version
    with none keeps what it was (a draft being generated)."""
    if not docs:
        return version.status
    return "approved" if all(d.status == "approved" for d in docs) else "in_review"


def latest_version(db: Any, project_id: str) -> Optional[Any]:
    """The project's newest version that is not a draft being generated."""
    return max((v for v in db.versions.list_for_project(project_id) if v.status != "draft"),
               key=lambda v: _aware(v.created_at), default=None)


def open_reviews(db: Any, project_id: str) -> dict:
    """`{user id: documents they review that are not approved}` in the project's latest version
    -- the review load an Assign dialog or the team list shows."""
    latest = latest_version(db, project_id)
    if latest is None:
        return {}
    docs = [d for d in version_docs(db, latest) if d.status != "approved"]
    out: dict = {}
    for uid in db.assignments.reviewers([d.id for d in docs]).values():
        out[uid] = out.get(uid, 0) + 1
    return out


def release_reviews(db: Any, project_id: str, user_id: str, actor: Any) -> int:
    """A member who leaves the project stops being anyone's reviewer: each document of theirs that
    is not approved goes back to Needs a reviewer, on the record, and the admins are told. An
    approved one keeps its reviewer -- it is history."""
    docs, _ = db.documents.list_for_project(project_id, assignee_id=user_id, per_page=ALL)
    left = [d for d in docs if d.status != "approved"]
    for d in left:
        db.assignments.remove(d.id, user_id)
        record(db, d, "unassigned", actor.id, comment="No longer a member of the project.",
               payload={"user_id": user_id, "left_project": True})
        _save(db, d)
    if left:
        gone = db.users.get_by_id(user_id)
        notify(db, admin_ids(db, project_id), project_id, left[0] if len(left) == 1 else None,
               N_UNASSIGNED, "%s left the project: %d document(s) need a reviewer."
               % (gone.name if gone else user_id, len(left)), skip=actor.id)
    return len(left)


def version_review(db: Any, version: Any, docs: Optional[list] = None) -> dict:
    docs = version_docs(db, version) if docs is None else docs
    counts = {k: sum(1 for d in docs if d.status == k) for k in DOC_STATUSES}
    sources = sorted({d.carried_from for d in docs if d.status == "approved" and d.carried_from})
    carried_from = []
    for vid in sources:
        v = db.versions.get(vid)
        carried_from.append({"version_id": vid, "tag": v.tag if v else None})
    approved_by = approved_at = None
    if docs and counts["approved"] == len(docs):
        last = max(docs, key=lambda d: _aware(d.approved_at))
        approved_at = last.approved_at
        u = db.users.get_by_id(last.approved_by) if last.approved_by else None
        approved_by = user_ref(u)
    return {"documents": len(docs), **counts,
            "carried": sum(1 for d in docs if d.status == "approved" and d.carried_from),
            "carried_from": carried_from,
            "approved_by": approved_by, "approved_at": _iso(approved_at)}


def roll_up(db: Any, version: Any) -> None:
    """Write the version's derived status, and the project's when this is its latest version."""
    if version is None or version.status == "draft":
        return
    new = derived_status(version, version_docs(db, version))
    if new != version.status:
        version.status = new
        db.versions.update(version)
    project = db.projects.get(version.project_id)
    if project is None or project.status not in ("in_review", "complete"):
        return
    latest = latest_version(db, version.project_id)
    if latest is None or latest.id != version.id:
        return
    want = "complete" if new == "approved" else "in_review"
    if project.status != want:
        project.status = want
        project.updated_at = datetime.now(UTC)
        db.projects.update(project)


# ---------------------------------------------------------------------------
# a run: carry approvals of unchanged documents forward, keep reviewers (contract §4)
# ---------------------------------------------------------------------------
def baseline_of(db: Any, version: Any) -> Optional[Any]:
    """The run's baseline, else the project's previous finished version."""
    if getattr(version, "baseline_version_id", None):
        b = db.versions.get(version.baseline_version_id)
        if b is not None and b.id != version.id:
            return b
    earlier = [v for v in db.versions.list_for_project(version.project_id)
               if v.id != version.id and v.status in ("in_review", "approved")
               and _aware(v.created_at) < _aware(version.created_at)]
    return max(earlier, key=lambda v: _aware(v.created_at), default=None)


def start_review(db: Any, project: Any, version: Any, docs: list, *,
                 fingerprint_fn: Callable = fingerprint,
                 freeze_fn: Callable = freeze_docx) -> dict:
    """Open the review of a run's new documents.

    A document whose baseline twin (same process, same component) was approved and whose
    rendered content is the same keeps the approval (`carried`). Every other one is In review,
    with the baseline's reviewer kept when they are still an active member, who is told once.
    """
    base = baseline_of(db, version)
    twins: dict = {}
    reviewers: dict = {}
    if base is not None:
        for b in version_docs(db, base):
            twins[(b.process, b.group)] = b
        reviewers = db.assignments.reviewers([b.id for b in twins.values()])
    back: dict = {}
    carried = 0
    for doc in docs:
        twin = twins.get((doc.process, doc.group))
        rid = reviewers.get(twin.id) if twin is not None else None
        if rid and active_member(db, doc.project_id, rid) is None:
            rid = None
        if rid:
            db.assignments.set_reviewer(DocumentAssignment(
                id="asgn" + uuid.uuid4().hex[:8], document_id=doc.id, user_id=rid,
                assigned_by=None, assigned_at=datetime.now(UTC)))
        if twin is not None and twin.status == "approved":
            fp = fingerprint_fn(db, project, doc)
            # The stored fingerprint first; when it differs -- or there is none -- the twin is
            # fingerprinted again with THIS code. An approved document cannot change (corrections
            # are refused), so its render today is what was approved, and a change to how pages
            # are built cannot then stop an unchanged document from carrying its approval.
            same = bool(fp) and (fp == twin.content_fingerprint
                                 or fp == fingerprint_fn(db, project, twin))
            if same:
                path, sha = freeze_fn(project, version, doc)
                doc.status = "approved"
                doc.approved_by, doc.approved_at = twin.approved_by, twin.approved_at
                doc.approval_comment = twin.approval_comment
                doc.docx_sha256, doc.approved_docx_path = sha, (str(path) if path else None)
                doc.content_fingerprint, doc.carried_from = fp, base.id
                _save(db, doc)
                record(db, doc, "carried", None, payload={
                    "from_version_id": base.id, "from_tag": base.tag, "docx_sha256": sha})
                carried += 1
                continue
        record(db, doc, "generated", None,
               payload={"kept_reviewer_from": base.tag} if rid else {})
        if rid:
            back.setdefault(rid, []).append(doc)
    for rid, ds in back.items():
        if len(ds) == 1:
            msg = "%s changed in %s and needs your review again." % (label(ds[0]), version.tag)
        else:
            msg = "%d of your documents changed in %s and need your review again." % (len(ds), version.tag)
        notify(db, [rid], version.project_id, ds[0] if len(ds) == 1 else None, N_BACK, msg)
    roll_up(db, version)
    return {"carried": carried, "in_review": len(docs) - carried}


# ---------------------------------------------------------------------------
# corrections on approved documents (contract: "Corrections on an approved document")
# ---------------------------------------------------------------------------
def approved_printing(db: Any, project_id: str, version_id: str, slot_kind: str,
                      slot_key: str) -> list:
    """The approved documents of this version that print the text of `slot_kind`/`slot_key`:
    the SWE.3 and SWE.4 of its component; for a key that names no component, any."""
    docs, _ = db.documents.list_for_project(project_id, version_id=version_id, status="approved",
                                            per_page=ALL)
    if not docs:
        return []
    try:
        from review.derive import component_of
        from review.export_guard import _component_of, component_id
        comp = _component_of(slot_kind, slot_key, component_of)
    except Exception:                                   # noqa: BLE001 -- cannot place: any
        return docs
    if comp is None:
        return docs
    return [d for d in docs if component_id(d.group) == comp]


def approved_of_component(db: Any, project_id: str, version_id: str,
                          component: Optional[str]) -> list:
    """The approved documents of this version for `component` (any, when it is None)."""
    docs, _ = db.documents.list_for_project(project_id, version_id=version_id, status="approved",
                                            per_page=ALL)
    if not docs or not component:
        return docs
    from review.export_guard import component_id
    want = component_id(component)
    return [d for d in docs if component_id(d.group) == want]


def refuse_if_approved(db: Any, project_id: str, version_id: str, slot_kind: Optional[str] = None,
                       slot_key: Optional[str] = None, *, function_id: Optional[str] = None) -> None:
    """409 DOCUMENT_APPROVED when an approved document prints the text being corrected: named by
    its slot, or -- a flowchart's labels, a behaviour row -- by the function it belongs to."""
    if function_id is not None:
        comp = function_id.split("|")[0] if "|" in function_id else None
        hits = approved_of_component(db, project_id, version_id, comp)
    else:
        hits = approved_printing(db, project_id, version_id, slot_kind, slot_key)
    if hits:
        raise conflict("DOCUMENT_APPROVED", "%s %s approved, and this text is printed there: "
                       "reopen it before correcting the text."
                       % (" and ".join(label(d) for d in hits[:2]), "is" if len(hits) == 1 else "are"))
