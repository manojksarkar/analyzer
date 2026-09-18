"""Review & Update routes — correcting the LLM's wording in a generated document.

Contract: `docs/spec/REVIEW_UPDATE_API_SPEC.md` · requirements:
`docs/spec/REVIEW_UPDATE_SPEC.md` (`REQ-API-*`).

Thin on purpose. Every rule — what may be empty, what the LLM original is, how history is
trimmed, which views must be re-derived — lives in `engine/review/override_service`, which is
also what the CLI and the tests use. A second copy of those rules behind HTTP is how the API and
the pipeline would start disagreeing about what a correction means.

**The transaction is opened here** and closed here. `apply_override` deliberately neither begins
nor commits, so the handler owns the unit of work: an edit either lands with its re-derivation or
does not land at all (`REQ-AP-02`).

Keys travel in the **body or a query parameter, never in a path segment** — a slot key contains
`|`, `:`, `,`, `*`, spaces and a 0x01 separator. The flowchart routes are the exception and use
`slot.encode()`'s base64url form, which has no character needing escaping.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..db.in_memory import InMemoryDatabase
from ..db.session import get_db
from ..middleware.auth import get_current_user, require_project_member
from ..models.domain import User

_ENGINE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "engine")
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

router = APIRouter(tags=["review"])


# ---------------------------------------------------------------------------
# bodies
# ---------------------------------------------------------------------------
class UpdateSlotRequest(BaseModel):
    slot_kind: str = Field(..., description="one of review.slot.ALL_KINDS")
    slot_key: str = Field(..., description="from review.slot; never built by hand")
    text: str


class UpdateFlowchartRequest(BaseModel):
    labels: Dict[str, str] = Field(
        ..., description="{node_id: text} — ONLY the labels the reviewer changed")


class UpdateBehaviourRequest(BaseModel):
    function_id: str
    external_caller_id: str
    bullets: List[str]


# ---------------------------------------------------------------------------
# plumbing
# ---------------------------------------------------------------------------
def _service():
    from review import override_service
    return override_service


def _connection():
    """A Postgres connection, or 503 if this deployment has no database.

    The corrections live nowhere else, so a missing database is not something to degrade around —
    silently accepting an edit that cannot be stored is worse than refusing it.
    """
    try:
        from core.db import get_engine, is_database_configured
        if not is_database_configured():
            raise RuntimeError("no database is configured")
        return get_engine()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


def _as_http(exc: Exception) -> HTTPException:
    """An `OverrideError` carries the status the API should return, so the mapping is one line
    rather than a table here that could drift from the service's own view of it."""
    return HTTPException(status_code=getattr(exc, "status", 400), detail=str(exc))


def _row(r) -> Dict[str, Any]:
    return {
        "slotKind": r.slot_kind,
        "slotKey": r.slot_key,
        "llmText": r.llm_text,
        "humanText": r.human_text,
        "isOrphaned": bool(r.is_orphaned),
        "updatedBy": r.updated_by,
        "updatedAt": r.updated_at.isoformat() if r.updated_at else None,
    }


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------
@router.get("/projects/{project_id}/versions/{version_id}/overrides")
def list_overrides(
    project_id: str,
    version_id: str,
    slot_kind: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """`REQ-API-01`. The corrections in a version — an **overlay**, not a slot enumeration.

    A version holds ~57,000 slots; listing them here would rebuild the document the UI already
    has. It merges these by `slotKey` instead.
    """
    require_project_member(project_id, current_user, db)
    svc = _service()
    with _connection().connect() as cx:
        try:
            rows = svc.list_overrides(cx, version_id, slot_kind=slot_kind,
                                      limit=limit, offset=offset)
            total = svc.count_overrides(cx, version_id, slot_kind=slot_kind)
        except Exception as exc:
            raise _as_http(exc)
    return {"overrides": [_row(r) for r in rows], "total": total,
            "limit": limit, "offset": offset}


@router.get("/projects/{project_id}/versions/{version_id}/overrides/slot")
def get_slot(
    project_id: str,
    version_id: str,
    slot_kind: str = Query(...),
    slot_key: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """`REQ-API-02`. A query parameter, not a path segment: a slot key contains `|`, `:`, `,`,
    `*`, spaces and a control character."""
    require_project_member(project_id, current_user, db)
    with _connection().connect() as cx:
        row = _service().get_override(cx, version_id, slot_kind, slot_key)
    if row is None:
        raise HTTPException(status_code=404, detail="no override on that slot")
    return _row(row)


@router.get("/projects/{project_id}/versions/{version_id}/flowcharts/{flowchart_token}/labels")
def get_flowchart_labels(
    project_id: str,
    version_id: str,
    flowchart_token: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """`REQ-API-02` / `REQ-ID-04`. Every node label of one flowchart, so the editor opens with one
    request and saves with one."""
    require_project_member(project_id, current_user, db)
    from review import rerender, slot as slot_mod
    try:
        flowchart_id = slot_mod.decode(flowchart_token)
    except Exception as exc:
        raise _as_http(exc)

    with _connection().connect() as cx:
        found = rerender.find_flowchart_row(cx, version_id, flowchart_id)
        if not found:
            raise HTTPException(status_code=404, detail="no flowchart %s" % flowchart_id)
        overrides = {r.slot_key: r for r in _service().list_overrides(
            cx, version_id, slot_kind=slot_mod.NODE_LABEL, limit=1000)}

    import json
    entry = next((e for e in json.loads(found[2]) if e.get("functionKey") == flowchart_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="no flowchart %s" % flowchart_id)

    labels = []
    for node in (entry.get("cfg") or {}).get("nodes") or []:
        nid = str(node.get("id") or "")
        if not nid:
            continue
        row = overrides.get(slot_mod.for_node(flowchart_id, nid))
        labels.append({"nodeId": nid, "text": node.get("label") or "",
                       "llmText": row.llm_text if row else None,
                       "isOverridden": row is not None})
    return {"flowchartId": flowchart_id, "flowchartToken": flowchart_token,
            "functionName": entry.get("name"), "labels": labels}


# ---------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------
@router.put("/projects/{project_id}/versions/{version_id}/overrides/slot")
def update_slot(
    project_id: str,
    version_id: str,
    body: UpdateSlotRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """`REQ-API-03`. One slot per call, for the six kinds that are not a flowchart."""
    require_project_member(project_id, current_user, db)
    svc = _service()
    with _connection().begin() as cx:          # one transaction, REQ-AP-02
        try:
            # The repository is built from (version, project): an API process has no
            # "current run", so there is none installed, and `model_repo.repository()` would
            # raise. The model write then joins THIS transaction (REQ-AP-02).
            models = svc.ModelAccess(version_id=version_id, project_id=project_id)
            out = svc.apply_override(cx, version_id, body.slot_kind, body.slot_key, body.text,
                                     models=models, user_id=current_user.id)
        except Exception as exc:
            raise _as_http(exc)
    return {"slotKind": out.slot_kind, "slotKey": out.slot_key, "humanText": out.human_text,
            "llmText": out.llm_text, "previousText": out.previous_text,
            "firstEdit": out.first_edit, "viewsDerived": list(out.views_derived),
            # What this correction invalidated. Returned so the UI can say that an edit changed
            # something the reviewer did not touch, rather than letting it appear unannounced.
            "queuedForRegeneration": [{"slotKind": k, "slotKey": v}
                                      for k, v in out.queued_for_regeneration]}


@router.put("/projects/{project_id}/versions/{version_id}/flowcharts/{flowchart_token}/labels")
def update_flowchart_labels(
    project_id: str,
    version_id: str,
    flowchart_token: str,
    body: UpdateFlowchartRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """`REQ-API-08`. A whole flowchart in one call, carrying **only the labels that changed**.

    All or nothing: one bad node fails the call and names itself, so the picture is never rebuilt
    from a half-applied edit.
    """
    require_project_member(project_id, current_user, db)
    from review import slot as slot_mod
    try:
        flowchart_id = slot_mod.decode(flowchart_token)
    except Exception as exc:
        raise _as_http(exc)

    svc = _service()
    with _connection().begin() as cx:
        try:
            out = svc.apply_flowchart_overrides(cx, version_id, flowchart_id, dict(body.labels),
                                                user_id=current_user.id)
        except Exception as exc:
            raise _as_http(exc)
    return {"flowchartId": out.flowchart_id, "applied": list(out.applied),
            "firstEdits": list(out.first_edits), "slotShape": out.slot_shape,
            "renderPending": bool(out.redrawn), "viewsDerived": list(out.views_derived)}


@router.put("/projects/{project_id}/versions/{version_id}/overrides/behaviour")
def update_behaviour(
    project_id: str,
    version_id: str,
    body: UpdateBehaviourRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """`REQ-ED-02`. The bullet list is accepted and returned as a unit."""
    require_project_member(project_id, current_user, db)
    svc = _service()
    with _connection().begin() as cx:
        try:
            out = svc.apply_behaviour_override(cx, version_id, body.function_id,
                                               body.external_caller_id, list(body.bullets),
                                               user_id=current_user.id)
        except Exception as exc:
            raise _as_http(exc)
    return {"slotKey": out.slot_key, "bullets": list(out.bullets), "llmText": out.llm_text,
            "firstEdit": out.first_edit, "viewsDerived": list(out.views_derived)}


@router.delete("/projects/{project_id}/versions/{version_id}/overrides/slot")
def undo_slot(
    project_id: str,
    version_id: str,
    slot_kind: str = Query(...),
    slot_key: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """`REQ-API-04`. Restores the LLM's original wording. **The record survives** — undo is an
    ordinary edit whose text happens to be the original, so both texts and the history remain."""
    require_project_member(project_id, current_user, db)
    svc = _service()
    with _connection().begin() as cx:
        try:
            svc.undo_override(cx, version_id, slot_kind, slot_key,
                              models=svc.ModelAccess(version_id=version_id,
                                                     project_id=project_id),
                              user_id=current_user.id)
            row = svc.get_override(cx, version_id, slot_kind, slot_key)
            payload = _row(row) if row else None
        except Exception as exc:
            raise _as_http(exc)
    return {"undone": True, "override": payload}


@router.get("/projects/{project_id}/versions/{version_id}/overrides/history")
def slot_history(
    project_id: str,
    version_id: str,
    slot_kind: str = Query(...),
    slot_key: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """Every retained edit for one slot, oldest first — bounded by `llm.overrideHistoryDepth`
    (`REQ-ST-04`). The LLM original is not in here; it is on the override itself, which is what
    makes "the original is never evicted" structural."""
    require_project_member(project_id, current_user, db)
    with _connection().connect() as cx:
        rows = _service().history_for(cx, version_id, slot_kind, slot_key)
    return {"history": [{"seq": r.seq, "humanText": r.human_text, "updatedBy": r.updated_by,
                         "updatedAt": r.updated_at.isoformat() if r.updated_at else None}
                        for r in rows]}


@router.get("/projects/{project_id}/versions/{version_id}/regeneration-queue")
def regeneration_queue(
    project_id: str,
    version_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """`REQ-CS-01`. Slots whose text was built from wording a human has since corrected, and
    which therefore need regenerating.

    Recorded rather than regenerated when the correction was saved: regenerating needs the
    function's source, which is in the git checkout and not in the model, and an LLM call. A run
    with both consumes this.
    """
    require_project_member(project_id, current_user, db)
    from review.cascade import pending
    with _connection().connect() as cx:
        rows = pending(cx, version_id)
    return {"pending": [{"slotKind": r.slot_kind, "slotKey": r.slot_key, "reason": r.reason,
                         "causedBy": {"slotKind": r.source_slot_kind,
                                      "slotKey": r.source_slot_key},
                         "requestedAt": r.requested_at.isoformat() if r.requested_at else None}
                        for r in rows],
            "total": len(rows)}


# ---------------------------------------------------------------------------
# export readiness
# ---------------------------------------------------------------------------
@router.get("/projects/{project_id}/versions/{version_id}/export-readiness")
def export_readiness(
    project_id: str,
    version_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """`REQ-AP-04`. Whether exporting now would ship text a correction has already replaced, so
    the UI can say so before someone downloads a document that is quietly out of date."""
    require_project_member(project_id, current_user, db)
    from review.export_guard import staleness
    with _connection().connect() as cx:
        st = staleness(cx, version_id)
    return {"stale": st.is_stale, "reason": st.reason, "explanation": st.explain(),
            "overrideCount": st.override_count,
            "newestOverrideAt": st.newest_override_at.isoformat()
            if st.newest_override_at else None,
            "oldestDerivationAt": st.oldest_derivation_at.isoformat()
            if st.oldest_derivation_at else None}
