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
`|`, `:`, `,`, `*`, spaces and a 0x01 separator. Flowcharts too: R7 and R8 take the flowchart's
function id as `flowchart_id`, in the query and the body. Which kind of text a key names is never
read from the key — each route is told its kind, or is one kind (R6, R7, R8).
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AfterValidator, BaseModel, Field

from ..db.in_memory import InMemoryDatabase
from ..db.session import get_db
from ..middleware.auth import get_current_user, require_project_member
from ..models.domain import User

_ENGINE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "engine")
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

router = APIRouter(tags=["review"])
_log = logging.getLogger(__name__)


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
def _no_nul(value: str) -> str:
    """Refuse U+0000 in anything a save stores.

    PostgreSQL cannot store it in text or JSONB, so a save carrying one died there as a 500. SQLite
    stores it, so on SQLite -- every unit test -- it reached the model and the DOCX. Refused here,
    before anything is written, as a 422 whose `loc` names the field.
    """
    if "\x00" in value:
        raise ValueError("must not contain the NUL character (\\u0000)")
    return value


#: Every text, label, bullet and id a save (R3, R6, R8) takes.
NoNulStr = Annotated[str, AfterValidator(_no_nul)]


class UpdateSlotRequest(BaseModel):
    slot_kind: SlotKind = Field(
        ..., description="which kind of text this is. nodeLabel -> R8, behaviourDescription -> R6")
    slot_key: NoNulStr = Field(..., description="from review.slot; never built by hand")
    text: NoNulStr


class UpdateFlowchartRequest(BaseModel):
    flowchart_id: NoNulStr = Field(
        ..., description="the flowchart's function id — `flowchartId` from R11 or R7; never "
                         "built by hand")
    labels: Dict[NoNulStr, NoNulStr] = Field(
        ..., description="{nodeId: new text} — ONLY the labels the reviewer changed. "
                         "Node ids come from R7's `labels[].nodeId`.")

    # Without this Swagger renders a Dict[str, str] as {"additionalProp1": "string", ...},
    # which reads as three required fields with meaningless names.
    model_config = {"json_schema_extra": {"examples": [
        {"flowchart_id": "Layer1.Lib|Lib|libAbs|int",
         "labels": {"N2": "Verify the checksum", "N5": "Retry the write"}}]}}


class UpdateBehaviourRequest(BaseModel):
    function_id: NoNulStr
    external_caller_id: NoNulStr
    bullets: List[NoNulStr]


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


def _swe4_deriver(cx, models):
    """`derive=` for a save: the saved component's SWE.4 specs, and the UT export built from
    them, re-derived from the stored rows in this transaction (`REQ-CS-04`) -- when the version
    has SWE.4 output. One query of row paths when it has none, which is every version the web app
    generates. See `review.swe4_rederive`."""
    from review.swe4_rederive import make_save_deriver
    return make_save_deriver(cx, models)


def _as_http(exc: Exception) -> HTTPException:
    """The HTTP answer for what a review call raised.

    A refusal the service chose carries its own status (`OverrideError`, `catalog.NotScoped`),
    so that mapping is one line rather than a table here that could drift from the service's own
    view of it. An `HTTPException` raised inside the block -- `_key` rejecting a malformed key --
    passes through as it is. A key the service could not take apart is the caller's mistake
    (400); stored output that cannot be read, or a save that lost the race for its slot, is a
    conflict (409).

    Anything else is a fault on this side, not the caller's: a 500 that says so, with the detail
    in the server log. Answering it as a 400, as this used to, told the client to fix a request
    that was fine -- and handed it an internal message (a SQL error, a Python `KeyError`) as the
    reason.
    """
    from sqlalchemy.exc import IntegrityError
    from review import catalog, slot as slot_mod
    from review.override_service import OverrideError
    from review.redraw import RedrawError

    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, (OverrideError, catalog.NotScoped)):
        return HTTPException(status_code=exc.status, detail=str(exc))
    if isinstance(exc, slot_mod.SlotKeyError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, RedrawError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, IntegrityError):
        return HTTPException(status_code=409, detail=(
            "another save of this text finished first; nothing was saved -- reload it and "
            "save again"))
    _log.exception("review route failed")
    return HTTPException(status_code=500, detail=(
        "the request failed because of an error on the server (%s); nothing was changed, and "
        "the server log has the detail" % type(exc).__name__))


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


def _saved_by_another_route(project_id: str, version_id: str, slot_kind: str,
                            slot_key: str) -> Optional[str]:
    """The 501 detail for a kind R3 does not save -- naming the route that does, and what to send
    it -- or None for the five kinds R3 saves.

    A Dynamic Behaviour row (R6) and a flowchart label (R8) are made in Phase 3 and live in the
    stored view output, not in the model R3 writes (`resolver.VIEW_ONLY_KINDS`). R3 still offers
    them: its `slot_kind` is the one list of seven that R2, R4 and R5 take, where all seven are
    valid. The refusal used to come from the service, after the save lock and a model read, and
    explained only why: "... its text lives in Phase-3 view output, not the model". A reviewer who
    sent a behaviour row here was left to find R6 in the spec. Now the answer says which route,
    its path for this version, and the ids it takes, read from the slot key the caller sent.
    """
    from review import slot as slot_mod
    if slot_kind not in (slot_mod.BEHAVIOUR_DESCRIPTION, slot_mod.NODE_LABEL):
        return None
    base = "/api/v1/projects/%s/versions/%s" % (project_id, version_id)
    try:
        parts = slot_mod.parse(slot_kind, slot_mod.from_request(slot_kind, slot_key))
    except slot_mod.SlotKeyError:
        parts = {}                                 # still say which route; the ids come from R11
    also = (" Reading it (R2), undoing it (R4) and its history (R5) do take slot_kind %s and %s."
            % (slot_kind, "this slot_key" if parts else "the slot's slotKey from R11"))
    if slot_kind == slot_mod.BEHAVIOUR_DESCRIPTION:
        ids = ("function_id %r, external_caller_id %r"
               % (parts["function_id"], parts["external_caller_id"]) if parts else
               "function_id and external_caller_id -- the row's functionId and externalCallerId "
               "from R11 (GET %s/slots?slot_kind=behaviourDescription)" % base)
        return ("A Dynamic Behaviour row is not saved with this route. Save it with R6: PUT "
                "%s/overrides/behaviour, with %s, and bullets: the row's lines, as a list of "
                "strings.%s" % (base, ids, also))
    target = ("flowchart_id %r and labels mapping node %r to its new text"
              % (parts["entity_key"], parts["node_id"]) if parts else
              "flowchart_id (flowchartId from R11 or R7) and labels mapping each node id to its "
              "new text")
    return ("A flowchart label is not saved with this route. Save it with R8: PUT "
            "%s/flowcharts/labels, with %s -- only the labels you change, several in one call."
            "%s" % (base, target, also))


def _flowchart_id(value: str) -> str:
    """The flowchart id the caller sent, or 400 naming the mistake -- above all one node's key
    sent for the whole flowchart. See `slot.flowchart_id_from_request`."""
    from review import slot as slot_mod
    try:
        return slot_mod.flowchart_id_from_request(value)
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


def _models_for(version_id: str, project_id: str, kinds):
    """A `ModelAccess` when one of `kinds` lives in the model, else None -- a listing of node
    labels or behaviour rows must not pay for a model read nobody asked for."""
    from review import resolver as _resolver
    if any(k in _resolver.MODEL_BACKED_KINDS for k in kinds):
        return _service().ModelAccess(version_id=version_id, project_id=project_id)
    return None


def _saved(res, slot_kind: str, slot_key: str) -> Dict[str, Any]:
    """What a save did, beside the slot as it now is -- the same four fields from R3, R4, R6 and
    each node of R8 (`REQ-API-09`).

    `previousText` is what the document printed before this save (`None` when it printed
    nothing); `firstEdit` is true when the save started a correction rather than changing one in
    force; `queuedForRegeneration` is what the save made out of date -- `[]` for the kinds that
    cascade to nothing (`REQ-CS-01`).
    """
    from review import slot as slot_mod
    svc = _service()
    if isinstance(res, svc.FlowchartApplied):
        node = slot_mod.parse(slot_mod.NODE_LABEL, slot_key)["node_id"]
        previous, first, queued = (res.previous or {}).get(node), node in res.first_edits, ()
    elif isinstance(res, svc.BehaviourApplied):
        previous, first, queued = res.previous_text, res.first_edit, ()
    else:
        previous, first, queued = res.previous_text, res.first_edit, res.queued_for_regeneration
    return {"previousText": previous or None, "firstEdit": bool(first),
            "viewsDerived": list(res.views_derived or ()),
            # What this correction invalidated. Returned so the UI can say that an edit changed
            # something the reviewer did not touch, rather than letting it appear unannounced.
            "queuedForRegeneration": [{"slotKind": k, "slotKey": v} for k, v in queued]}


def _flowchart_entry(cx, version_id: str, flowchart_id: str):
    """The stored flowchart entry of `flowchart_id` -- its CFG and its DOT -- or None."""
    import json
    from review import rerender
    found = rerender.find_flowchart_row(cx, version_id, flowchart_id)
    if not found:
        return None
    try:
        entries = json.loads(found[2] or "[]")
    except ValueError:
        return None
    return next((e for e in entries if isinstance(entries, list) and isinstance(e, dict)
                 and e.get("functionKey") == flowchart_id), None)


def _node_slots(cx, version_id: str, flowchart_id: str, entry, node_ids=None):
    """The `Slot` of each node of a stored flowchart -- every node, or `node_ids` in that order.

    `text` is the stored label: what the picture and the SWE.4 step carry. Only THIS flowchart's
    corrections are read: paging the whole version (newest 1,000) dropped older corrections on the
    flowchart being opened, and reported their nodes as uncorrected.
    """
    from review import catalog, slot as slot_mod
    nodes = [n for n in ((entry or {}).get("cfg") or {}).get("nodes") or []
             if isinstance(n, dict) and n.get("id")]
    if node_ids is not None:
        by_id = {str(n["id"]): n for n in nodes}
        nodes = [by_id[n] for n in node_ids if n in by_id]
    keys = [slot_mod.for_node(flowchart_id, str(n["id"])) for n in nodes]
    rows = _service().overrides_by_key(cx, version_id, slot_mod.NODE_LABEL, keys)
    return [catalog.slot_view(slot_mod.NODE_LABEL, k, n.get("label") or "", rows.get(k))
            for k, n in zip(keys, nodes)]


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
    from review import catalog
    with _connection().connect() as cx:
        try:
            kind = slot_kind.value if slot_kind else None
            rows = svc.list_overrides(cx, version_id, slot_kind=kind,
                                      limit=limit, offset=offset)
            total = svc.count_overrides(cx, version_id, slot_kind=kind)
            pairs = [(r.slot_kind, r.slot_key) for r in rows]
            slots = catalog.slot_views(
                cx, version_id, pairs,
                _models_for(version_id, project_id, {k for k, _key in pairs}),
                rows={(r.slot_kind, r.slot_key): r for r in rows})
        except Exception as exc:
            raise _as_http(exc)
    return {"overrides": [x for x in slots if x is not None], "total": total,
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
    flowchart is one function's graph. Each row carries the `flowchartId` R7 and R8 take.

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
    """`REQ-API-02`. Any slot of the version, corrected or not, in the one `Slot` shape
    (`REQ-API-09`) -- `isOverridden` says which. A query parameter, not a path segment: a slot key
    contains `|`, `:`, `,`, `*`, spaces and a control character."""
    require_project_member(project_id, current_user, db)
    _version(project_id, version_id)
    kind = slot_kind.value
    key = _key(kind, slot_key)
    from review import catalog
    with _connection().connect() as cx:
        try:
            got = catalog.slot_views(cx, version_id, [(kind, key)],
                                     _models_for(version_id, project_id, {kind}))[0]
        except Exception as exc:
            raise _as_http(exc)
    if got is None:
        raise HTTPException(status_code=404, detail=(
            "no %s slot %r in version %s -- take the key from R11 (or R7 for a node label)"
            % (kind, key, version_id)))
    return got


@router.get(
    "/projects/{project_id}/versions/{version_id}/flowcharts/labels",
    summary="R7 - read a flowchart's labels")
def get_flowchart_labels(
    project_id: str,
    version_id: str,
    flowchart_id: str = Query(..., description="the flowchart's function id — `flowchartId` "
                                                "from R11; never built by hand"),
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """`REQ-API-02` / `REQ-ID-04`. Every node label of one flowchart, so the editor opens with one
    request and saves with one."""
    require_project_member(project_id, current_user, db)
    _version(project_id, version_id)
    flowchart_id = _flowchart_id(flowchart_id)
    with _connection().connect() as cx:
        entry = _flowchart_entry(cx, version_id, flowchart_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="no flowchart %s" % flowchart_id)
        # Each node as a `Slot` -- with its own `slotKey`, so undo (R4) and history (R5) work on a
        # single label without the caller assembling one: a node key is
        # `flowchartId + U+0001 + nodeId`, and `REQ-ID-01` says a key is built by the server and
        # never by hand.
        labels = _node_slots(cx, version_id, flowchart_id, entry)
    # An empty list here is ambiguous on its own: it reads as "this flowchart has no nodes".
    # `cfg` has only been stored since 2026-09-01, so a version generated before that has the
    # picture and the DOT but not the graph -- and its labels cannot be corrected until it is
    # re-derived. Say which it is rather than leaving the caller to guess.
    body = {"flowchartId": flowchart_id,
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
    """`REQ-API-03`. One slot per call: `description`, `behaviourInputName`,
    `behaviourOutputName`, `unitDescription` and `structDescription`. A Dynamic Behaviour row
    (`behaviourDescription`) is saved with R6 and a flowchart label (`nodeLabel`) with R8: sent
    here, either answers 501 naming that route and what to send it. Answers the slot as it now is
    (`REQ-API-09`) and what the save did."""
    require_project_member(project_id, current_user, db)
    _version(project_id, version_id)
    elsewhere = _saved_by_another_route(project_id, version_id, body.slot_kind.value,
                                        body.slot_key)
    if elsewhere:
        raise HTTPException(status_code=501, detail=elsewhere)
    svc = _service()
    from review import catalog
    with _connection().begin() as cx:          # one transaction, REQ-AP-02
        try:
            # The repository is built from (version, project): an API process has no
            # "current run", so there is none installed, and `model_repo.repository()` would
            # raise. The model write then joins THIS transaction (REQ-AP-02).
            models = svc.ModelAccess(version_id=version_id, project_id=project_id)
            out = svc.apply_override(cx, version_id, body.slot_kind.value,
                                     _key(body.slot_kind.value, body.slot_key), body.text,
                                     models=models, user_id=current_user.id,
                                     derive=_swe4_deriver(cx, models))
            # Read back through the save's own model and connection: what the document prints now.
            now = catalog.slot_views(cx, version_id, [(out.slot_kind, out.slot_key)], models)[0]
        except Exception as exc:
            raise _as_http(exc)
    return {**now, **_saved(out, out.slot_kind, out.slot_key)}


@router.put(
    "/projects/{project_id}/versions/{version_id}/flowcharts/labels",
    summary="R8 - correct a flowchart, in one call")
def update_flowchart_labels(
    project_id: str,
    version_id: str,
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
    flowchart_id = _flowchart_id(body.flowchart_id)

    svc = _service()
    with _connection().begin() as cx:
        try:
            # Read only if the version has SWE.4 specs to re-derive: a label is not a model field.
            models = svc.ModelAccess(version_id=version_id, project_id=project_id)
            out = svc.apply_flowchart_overrides(cx, version_id, flowchart_id, dict(body.labels),
                                                user_id=current_user.id,
                                                derive=_swe4_deriver(cx, models))
            # The saved nodes as they now are, read back from the flowchart the save rewrote --
            # with the DOT it rebuilt, so the editor redraws without a second request.
            entry = _flowchart_entry(cx, version_id, out.flowchart_id)
            nodes = _node_slots(cx, version_id, out.flowchart_id, entry, list(out.applied))
        except Exception as exc:
            raise _as_http(exc)
    return {"flowchartId": out.flowchart_id,
            "labels": [{**n, **_saved(out, n["slotKind"], n["slotKey"])} for n in nodes],
            "viewsDerived": list(out.views_derived),
            "queuedForRegeneration": [],
            # True while the picture is owed. The service decides it from the JOBS, not from
            # whether the stored DOT was rebuilt -- those are different facts, and conflating
            # them told the caller "no render pending" while the export blocked on one.
            "renderPending": out.render_pending,
            "renderJobs": list(out.render_jobs),
            "dot": (entry or {}).get("flowchart") or ""}


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
    """`REQ-ED-02`. The bullet list is accepted as a unit; the answer is the row as a `Slot`
    (`REQ-API-09`) -- its bullets one per line in `text`, and as a list in `bullets`."""
    require_project_member(project_id, current_user, db)
    _version(project_id, version_id)
    svc = _service()
    from review import catalog, slot as slot_mod
    with _connection().begin() as cx:
        try:
            out = svc.apply_behaviour_override(cx, version_id, body.function_id,
                                               body.external_caller_id, list(body.bullets),
                                               user_id=current_user.id)
            now = catalog.slot_views(cx, version_id,
                                     [(slot_mod.BEHAVIOUR_DESCRIPTION, out.slot_key)])[0]
        except Exception as exc:
            raise _as_http(exc)
    return {**now, **_saved(out, slot_mod.BEHAVIOUR_DESCRIPTION, out.slot_key)}


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
    ordinary edit whose text happens to be the original, so both texts and the history remain.
    Answers like a save (`REQ-API-09`): the slot as it now is, and what the undo did -- for a node
    label also the picture's state and the rebuilt DOT, as R8 does."""
    require_project_member(project_id, current_user, db)
    _version(project_id, version_id)
    kind = slot_kind.value
    key = _key(kind, slot_key)
    svc = _service()
    from review import catalog, slot as slot_mod
    with _connection().begin() as cx:
        try:
            models = svc.ModelAccess(version_id=version_id, project_id=project_id)
            out = svc.undo_override(cx, version_id, kind, key, models=models,
                                    user_id=current_user.id, derive=_swe4_deriver(cx, models))
            now = catalog.slot_views(cx, version_id, [(kind, key)], models)[0]
            entry = (_flowchart_entry(cx, version_id, now["flowchartId"])
                     if kind == slot_mod.NODE_LABEL else None)
        except Exception as exc:
            raise _as_http(exc)
    body = {**now, **_saved(out, kind, key)}
    if kind == slot_mod.NODE_LABEL:
        body.update({"renderPending": out.render_pending, "renderJobs": list(out.render_jobs),
                     "dot": (entry or {}).get("flowchart") or ""})
    return body


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
    the UI can say so before someone downloads a document that is quietly out of date.

    About the documents the web app exports -- SWE.3. A SWE.4 document of a CLI-generated version
    is exported from the CLI, which asks its own question (`analyzer.py reexport`)."""
    require_project_member(project_id, current_user, db)
    _version(project_id, version_id)
    from review.export_guard import staleness
    with _connection().connect() as cx:
        st = staleness(cx, version_id, "swe3")
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
