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


def _slot_kind_enum():
    """`slot.ALL_KINDS` as an Enum, so Swagger offers a dropdown instead of a blank box.

    Built FROM the canonical tuple rather than retyped: a hand-written copy here would be a
    second list of the editable kinds, and the first one to gain an eighth would be wrong.

    It also moves "that is not a slot kind" from a 404 out of the service to a 422 from
    validation, naming every value that IS allowed — which is the answer to the question
    somebody staring at an empty query field is actually asking.
    """
    import enum
    from review import slot as _slot
    return enum.Enum("SlotKind", {k: k for k in _slot.ALL_KINDS}, type=str)


SlotKind = _slot_kind_enum()


# ---------------------------------------------------------------------------
# bodies
# ---------------------------------------------------------------------------
class UpdateSlotRequest(BaseModel):
    slot_kind: SlotKind = Field(
        ..., description="which kind of text this is. nodeLabel -> R8, behaviourDescription -> R6")
    slot_key: str = Field(..., description="from review.slot; never built by hand")
    text: str


class UpdateFlowchartRequest(BaseModel):
    labels: Dict[str, str] = Field(
        ..., description="{nodeId: new text} — ONLY the labels the reviewer changed. "
                         "Node ids come from R7's `labels[].nodeId`.")

    # Without this Swagger renders a Dict[str, str] as {"additionalProp1": "string", ...},
    # which reads as three required fields with meaningless names.
    model_config = {"json_schema_extra": {"examples": [
        {"labels": {"N2": "Verify the checksum", "N5": "Retry the write"}}]}}


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


def _key(slot_kind: str, slot_key: str) -> str:
    """The canonical key for what the caller sent, or 400 saying what the key should be.

    Accepts the key as any JSON viewer DISPLAYS it -- Swagger shows the U+0001 separator as the
    six characters `\\u0001`, and nobody can type the real character into a text field -- and
    rejects a malformed key by name rather than answering `200 []`, `404` or `409` for a
    correction that exists. See `slot.from_request`.
    """
    from review import slot as slot_mod
    try:
        return slot_mod.from_request(slot_kind, slot_key)
    except slot_mod.SlotKeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _version(project_id: str, version_id: str) -> None:
    """404 unless `version_id` is a version OF `project_id`.

    Every route here is addressed /projects/{p}/versions/{v}, but the reads and writes beneath
    are by version alone. Without this check:

      * an id that does not exist answered as if the version were empty -- which is exactly what
        a version's TAG looks like, because a run started from the web app is stored under a
        generated id (`ver1a2b3c4d`), not the tag it was given (`v1`);
      * a version of ANOTHER project answered with that project's text, and took writes to it,
        from anyone who is a member of the project in the path.

    Read through `_connection()`, the database every route here reads its data from.
    """
    from sqlalchemy import select
    from ..db.postgres import schema as s
    with _connection().connect() as cx:
        row = cx.execute(select(s.versions.c.project_id)
                         .where(s.versions.c.id == version_id)).first()
        if row is not None and row.project_id == project_id:
            return
        tagged = cx.execute(select(s.versions.c.id)
                            .where(s.versions.c.project_id == project_id,
                                   s.versions.c.version == version_id)).first()
    hint = ""
    if tagged is not None:
        hint = (f" '{version_id}' is this project's version TAG; its id is '{tagged.id}'. These "
                f"endpoints take the id -- GET /api/v1/projects/{project_id}/versions lists both.")
    raise HTTPException(status_code=404,
                        detail=f"no version '{version_id}' in project '{project_id}'.{hint}")


def _latest_reexport(cx, version_id: str) -> Optional[Dict[str, Any]]:
    """The newest re-export job of a version, shaped for R9, or None when it was never
    re-exported. Read from `analysis_jobs` directly, on the connection R9 already holds."""
    from sqlalchemy import select
    from ..db.postgres import schema as s
    from ..models.domain import REEXPORT_MODE
    j = s.analysis_jobs
    r = cx.execute(select(j.c.id, j.c.status, j.c.started_at, j.c.completed_at,
                          j.c.error_message)
                   .where(j.c.version_id == version_id, j.c.mode == REEXPORT_MODE)
                   .order_by(j.c.started_at.desc()).limit(1)).first()
    if r is None:
        return None
    return {"jobId": r.id, "status": r.status,
            "startedAt": r.started_at.isoformat() if r.started_at else None,
            "completedAt": r.completed_at.isoformat() if r.completed_at else None,
            "errorMessage": r.error_message}


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
@router.get(
    "/projects/{project_id}/versions/{version_id}/overrides",
    summary="R1 - the corrections in a version")
def list_overrides(
    project_id: str,
    version_id: str,
    slot_kind: Optional[SlotKind] = Query(
        None, description="filter to one kind; omit for every correction in the version"),
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
    _version(project_id, version_id)
    svc = _service()
    with _connection().connect() as cx:
        try:
            kind = slot_kind.value if slot_kind else None
            rows = svc.list_overrides(cx, version_id, slot_kind=kind,
                                      limit=limit, offset=offset)
            total = svc.count_overrides(cx, version_id, slot_kind=kind)
        except Exception as exc:
            raise _as_http(exc)
    return {"overrides": [_row(r) for r in rows], "total": total,
            "limit": limit, "offset": offset}


@router.get(
    "/projects/{project_id}/versions/{version_id}/slots",
    summary="R11 - what can be edited")
def list_slots(
    project_id: str,
    version_id: str,
    slot_kind: SlotKind = Query(..., description="which kind of slot to list"),
    unit: Optional[str] = Query(None, description="narrow to one unit (its name, e.g. `OpsTable`)"),
    component: Optional[str] = Query(
        None, description="narrow to one component, by its layer-qualified id (`Layer1.Cross`) "
                          "- a document's `group`"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """`REQ-API-01`'s other half: the slots that CAN be edited, with their text and key.

    R1 lists what has been corrected, which is empty until somebody corrects something. This
    lists what is there to correct — so a `slot_key`, which a caller may never invent
    (`REQ-ID-01`), can be read from a response instead of dug out of stored view output.

    `nodeLabel` is listed per FLOWCHART, not per node: a version has ~42,000 node labels, and a
    flowchart is one function's graph. Each row carries the token R7 takes.

    `structDescription` lists the structs, classes and unions whose description the unit header
    table can show. The key names the type, not a unit, so each row says where it is shown
    (`shownIn`, unit keys), and `unit` / `component` filter on that.
    """
    require_project_member(project_id, current_user, db)
    _version(project_id, version_id)
    kind = slot_kind.value
    from review import catalog, resolver as _resolver
    # Only the model-backed kinds read the model. Building a repository for a flowchart listing
    # would pay for a model read nobody asked for.
    models = (_service().ModelAccess(version_id=version_id, project_id=project_id)
              if kind in _resolver.MODEL_BACKED_KINDS else None)
    with _connection().connect() as cx:
        try:
            page = catalog.list_slots(cx, version_id, kind, models=models, unit=unit,
                                      component=component, limit=limit, offset=offset)
        except Exception as exc:
            raise _as_http(exc)
    return {"slotKind": kind, "slots": page.items, "total": page.total,
            "limit": limit, "offset": offset}


@router.get(
    "/projects/{project_id}/versions/{version_id}/overrides/slot",
    summary="R2 - read one slot")
def get_slot(
    project_id: str,
    version_id: str,
    slot_kind: SlotKind = Query(...),
    slot_key: str = Query(..., description="from an R1/R2/R7 response; never built by hand"),
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """`REQ-API-02`. A query parameter, not a path segment: a slot key contains `|`, `:`, `,`,
    `*`, spaces and a control character."""
    require_project_member(project_id, current_user, db)
    _version(project_id, version_id)
    key = _key(slot_kind.value, slot_key)
    with _connection().connect() as cx:
        row = _service().get_override(cx, version_id, slot_kind.value, key)
    if row is None:
        raise HTTPException(status_code=404, detail="no override on that slot")
    return _row(row)


@router.get(
    "/projects/{project_id}/versions/{version_id}/flowcharts/{flowchart_token}/labels",
    summary="R7 - read a flowchart's labels")
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
    _version(project_id, version_id)
    from review import rerender, slot as slot_mod
    try:
        flowchart_id = slot_mod.decode(flowchart_token)
    except Exception as exc:
        raise _as_http(exc)

    import json
    from review.catalog import _state
    with _connection().connect() as cx:
        found = rerender.find_flowchart_row(cx, version_id, flowchart_id)
        if not found:
            raise HTTPException(status_code=404, detail="no flowchart %s" % flowchart_id)
        entry = next((e for e in json.loads(found[2])
                      if e.get("functionKey") == flowchart_id), None)
        if entry is None:
            raise HTTPException(status_code=404, detail="no flowchart %s" % flowchart_id)
        nodes = [n for n in (entry.get("cfg") or {}).get("nodes") or []
                 if isinstance(n, dict) and n.get("id")]
        # Only THIS flowchart's keys. Paging the whole version (newest 1,000) dropped older
        # corrections on the flowchart being opened, and reported their nodes as uncorrected.
        overrides = _service().overrides_by_key(
            cx, version_id, slot_mod.NODE_LABEL,
            [slot_mod.for_node(flowchart_id, str(n["id"])) for n in nodes])

    labels = []
    for node in nodes:
        nid = str(node.get("id"))
        key = slot_mod.for_node(flowchart_id, nid)
        labels.append({"nodeId": nid,
                       # The key for THIS node, so undo (R4) and history (R5) work on a single
                       # label without the caller assembling one. A node key is
                       # `flowchartId + U+0001 + nodeId`, and `REQ-ID-01` says a key is built by
                       # the server and never by hand -- so not returning it here left the UI
                       # with a rule it could not follow.
                       "slotKey": key,
                       # `text` is the stored label: what the picture and the SWE.4 step carry.
                       # The same rule as R11 decides the rest -- an orphan is not in force.
                       **_state(overrides.get(key), node.get("label") or "")})
    # An empty list here is ambiguous on its own: it reads as "this flowchart has no nodes".
    # `cfg` has only been stored since 2026-09-01, so a version generated before that has the
    # picture and the DOT but not the graph -- and its labels cannot be corrected until it is
    # re-derived. Say which it is rather than leaving the caller to guess.
    body = {"flowchartId": flowchart_id, "flowchartToken": flowchart_token,
            "functionName": entry.get("name"), "labels": labels,
            "graphAvailable": bool(labels),
            # The Graphviz DOT, read from the DATABASE -- rebuilt by R8 in the same request that
            # saves a label. A UI draws it with @viz-js/viz, the library the pipeline itself uses
            # to turn DOT into the SVG it screenshots for the Word file, so the editor shows the
            # corrected flowchart the moment it is saved. The PNG beside the document is a
            # file on disk and is only redrawn by the next re-export.
            "dot": entry.get("flowchart") or ""}
    if not labels:
        body["note"] = (
            "This flowchart has no stored graph, so its labels cannot be listed or corrected. "
            "Its output predates the CFG being stored; re-derive the version "
            "(reexport --from-phase 3) and this will fill in."
            if not entry.get("error") else
            "This flowchart failed to build: %s" % entry.get("error"))
    return body


# ---------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------
@router.put(
    "/projects/{project_id}/versions/{version_id}/overrides/slot",
    summary="R3 - correct one slot")
def update_slot(
    project_id: str,
    version_id: str,
    body: UpdateSlotRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """`REQ-API-03`. One slot per call, for the six kinds that are not a flowchart."""
    require_project_member(project_id, current_user, db)
    _version(project_id, version_id)
    svc = _service()
    with _connection().begin() as cx:          # one transaction, REQ-AP-02
        try:
            # The repository is built from (version, project): an API process has no
            # "current run", so there is none installed, and `model_repo.repository()` would
            # raise. The model write then joins THIS transaction (REQ-AP-02).
            models = svc.ModelAccess(version_id=version_id, project_id=project_id)
            out = svc.apply_override(cx, version_id, body.slot_kind.value,
                                     _key(body.slot_kind.value, body.slot_key), body.text,
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


@router.put(
    "/projects/{project_id}/versions/{version_id}/flowcharts/{flowchart_token}/labels",
    summary="R8 - correct a flowchart, in one call")
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
    _version(project_id, version_id)
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
            # True while the picture is owed. The service decides it from the JOBS, not from
            # whether the stored DOT was rebuilt -- those are different facts, and conflating
            # them told the caller "no render pending" while the export blocked on one.
            "renderPending": out.render_pending,
            "renderJobs": list(out.render_jobs),
            "viewsDerived": list(out.views_derived)}


@router.put(
    "/projects/{project_id}/versions/{version_id}/overrides/behaviour",
    summary="R6 - correct one Dynamic Behaviour row")
def update_behaviour(
    project_id: str,
    version_id: str,
    body: UpdateBehaviourRequest,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """`REQ-ED-02`. The bullet list is accepted and returned as a unit."""
    require_project_member(project_id, current_user, db)
    _version(project_id, version_id)
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


@router.delete(
    "/projects/{project_id}/versions/{version_id}/overrides/slot",
    summary="R4 - undo one slot")
def undo_slot(
    project_id: str,
    version_id: str,
    slot_kind: SlotKind = Query(...),
    slot_key: str = Query(..., description="from an R1/R2/R7 response; never built by hand"),
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """`REQ-API-04`. Restores the LLM's original wording. **The record survives** — undo is an
    ordinary edit whose text happens to be the original, so both texts and the history remain."""
    require_project_member(project_id, current_user, db)
    _version(project_id, version_id)
    key = _key(slot_kind.value, slot_key)
    svc = _service()
    with _connection().begin() as cx:
        try:
            svc.undo_override(cx, version_id, slot_kind.value, key,
                              models=svc.ModelAccess(version_id=version_id,
                                                     project_id=project_id),
                              user_id=current_user.id)
            row = svc.get_override(cx, version_id, slot_kind.value, key)
            payload = _row(row) if row else None
        except Exception as exc:
            raise _as_http(exc)
    return {"undone": True, "override": payload}


@router.get(
    "/projects/{project_id}/versions/{version_id}/overrides/history",
    summary="R5 - one slot's history")
def slot_history(
    project_id: str,
    version_id: str,
    slot_kind: SlotKind = Query(...),
    slot_key: str = Query(..., description="from an R1/R2/R7 response; never built by hand"),
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """Every retained edit for one slot, oldest first — bounded by `llm.overrideHistoryDepth`
    (`REQ-ST-04`). The LLM original is not in here; it is on the override itself, which is what
    makes "the original is never evicted" structural."""
    require_project_member(project_id, current_user, db)
    _version(project_id, version_id)
    key = _key(slot_kind.value, slot_key)
    with _connection().connect() as cx:
        rows = _service().history_for(cx, version_id, slot_kind.value, key)
    return {"history": [{"seq": r.seq, "humanText": r.human_text, "updatedBy": r.updated_by,
                         "updatedAt": r.updated_at.isoformat() if r.updated_at else None}
                        for r in rows]}


@router.get(
    "/projects/{project_id}/versions/{version_id}/regeneration-queue",
    summary="R10 - the regeneration queue")
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
    _version(project_id, version_id)
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
@router.get(
    "/projects/{project_id}/versions/{version_id}/export-readiness",
    summary="R9 - export readiness")
def export_readiness(
    project_id: str,
    version_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """`REQ-AP-04`. Whether exporting now would ship text a correction has already replaced, so
    the UI can say so before someone downloads a document that is quietly out of date."""
    require_project_member(project_id, current_user, db)
    _version(project_id, version_id)
    from review.export_guard import staleness
    with _connection().connect() as cx:
        st = staleness(cx, version_id)
        reexport = _latest_reexport(cx, version_id)
    return {"stale": st.is_stale, "reason": st.reason, "explanation": st.explain(),
            # The version's latest re-export job, or null. How a page that was reloaded -- or
            # opened by someone else -- learns a re-export is already running, and follows that
            # job instead of offering to start a second one.
            "reexport": reexport,
            "overrideCount": st.override_count,
            # REQ-IM-02/03: a picture still being drawn blocks the export; one that failed does
            # not, but the UI must be able to say the image is out of date.
            "pendingRenders": st.pending_renders, "failedRenders": st.failed_renders,
            "newestOverrideAt": st.newest_override_at.isoformat()
            if st.newest_override_at else None,
            "oldestDerivationAt": st.oldest_derivation_at.isoformat()
            if st.oldest_derivation_at else None}
