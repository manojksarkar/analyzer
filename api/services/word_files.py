"""Word file updates -- the server side of docs/design/WORD_FILE_UPDATES.md (the contract is its §4).

One rule says whether a document's Word file is out of date (`engine/review/word_files.py`); this
module gathers what it needs from the API's database and answers, with it, every place that asks:

* R9 / A15 -- `readiness`: the out-of-date documents, the approved ones kept, what holds the version;
* the update route -- `start_update`: the out-of-date components (a developer's within their
  documents), one update at a time per version, joined when a running one covers the request;
* Submit -- `submit_word_file`: the update of the submitted document's component, never failing it;
* Approve -- `approval_state`: out of date, or being updated;
* the save routes -- `refuse_if_updating`: 409 `WORD_FILE_UPDATING` in a component being written;
* an update's end -- `tell_update_end`: the notifications.

Components are compared in `export_guard.component_id` form (`Layer1.Sample Core` is
`layer1.sample-core`): documents, job scopes, component states and slot keys spell them apart.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import HTTPException

from ..models.domain import EXPORT_MODE, REEXPORT_MODE, RENDER_MODES

_log = logging.getLogger(__name__)
UTC = timezone.utc
ALL = 1_000_000
ACTIVE = ("queued", "running")

# notification types (REVIEW_APPROVE_API_SPEC A16)
N_UPDATED, N_UPDATE_FAILED = "word_files_updated", "word_files_update_failed"

#: scope <-> reason. `out_of_date` updates are `update` (a button) or `submit`; `all` is `rebuild`.
SCOPES = ("out_of_date", "all")


# ---------------------------------------------------------------------------
# plumbing
# ---------------------------------------------------------------------------
def _engine_path() -> None:
    eng = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       "engine")
    if eng not in sys.path:
        sys.path.insert(0, eng)


def _cid(name: Optional[str]) -> str:
    _engine_path()
    from review.export_guard import component_id
    return component_id(name)


def _core_engine():
    """The engine's database -- where the corrections, the render queue and the stored output
    are. None without one (the in-memory test seam, where no correction exists either)."""
    _engine_path()
    try:
        import core.db as core_db
        if not core_db.is_database_configured():
            return None
        return core_db.get_engine()
    except Exception:                                   # noqa: BLE001 -- nothing to ask
        return None


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    """ISO-8601 in UTC, as the contract says -- a value read back from Postgres carries the
    session's offset (+05:30 here), not UTC."""
    dt = _aware(dt)
    return dt.astimezone(UTC).isoformat() if dt else None


def version_documents(db: Any, version: Any) -> list:
    docs, _ = db.documents.list_for_project(version.project_id, version_id=version.id,
                                            per_page=ALL)
    return docs


def all_components(db: Any, version: Any, docs: Optional[list] = None) -> List[str]:
    """Every component the version has documents for, sorted."""
    return sorted({d.group for d in (docs if docs is not None else version_documents(db, version))
                   if d.group})


def _output_root(version: Any) -> Optional[str]:
    from . import doc_render
    root = doc_render.commit_output_root(version.project_id, getattr(version, "commit_sha", None),
                                         version.id)
    return str(root) if root is not None else None


def _state_rows(db: Any, version_id: str) -> Dict[str, dict]:
    """`version_components` rows by component ({} without a database: the in-memory backend).

    A read that FAILS raises: "no component is stale, no CLI run holds one" read from an error
    would let Approve freeze a file a layer made old, and a save land in a component being
    written. The callers answer an error instead (Submit reports it; R9 and Approve fail)."""
    from .version_components import state_rows
    try:
        return state_rows(getattr(db, "_engine", None), version_id)
    except Exception as exc:
        _log.error("version %s: component states could not be read (%s: %s)", version_id,
                   type(exc).__name__, exc)
        raise


def stale_layers(db: Any, version_id: str, rows: Optional[Dict[str, dict]] = None) -> Dict[str, list]:
    """`{component: [layer, ...]}` for the components a layer added to the version made old
    (`version_run.layer_added`: kept through a failed, cancelled or killed update, until the
    component is generated again)."""
    rows = _state_rows(db, version_id) if rows is None else rows
    _engine_path()
    from core.version_run import layer_added
    out = {}
    for c, r in rows.items():
        layers = layer_added(r)
        if layers is not None:
            out[c] = layers
    return out


def user_ref(db: Any, user_id: Optional[str], *, snake: bool) -> Optional[dict]:
    if not user_id:
        return None
    u = db.users.get_by_id(user_id)
    if u is None:
        return None
    return ({"user_id": u.id, "name": u.name, "initials": u.initials} if snake
            else {"userId": u.id, "name": u.name, "initials": u.initials})


# ---------------------------------------------------------------------------
# the rule, for documents
# ---------------------------------------------------------------------------
def file_states(db: Any, version: Any, docs: Optional[list] = None, *,
                rows: Optional[Dict[str, dict]] = None) -> Dict[str, Any]:
    """`{document id: FileState}` for `docs` (default: every document of the version) --
    `engine/review/word_files.states`, with each document's Word file time: `word_file_at`, else
    the file's time on this machine (a document recorded before 0018)."""
    _engine_path()
    from review.word_files import UP_TO_DATE, WordFile, file_written_at, states
    docs = version_documents(db, version) if docs is None else docs
    if not docs:
        return {}
    eng = _core_engine()
    if eng is None:
        return {d.id: UP_TO_DATE for d in docs}
    root = None
    files = []
    for d in docs:
        written = _aware(getattr(d, "word_file_at", None))
        if written is None:
            if root is None:
                root = _output_root(version) or ""
            written = file_written_at(root, d.group, d.process)
        files.append(WordFile(d.id, d.group or "", d.process or "", written))
    with eng.connect() as cx:
        return states(cx, version.id, files, stale_layers=stale_layers(db, version.id, rows))


def file_view(doc: Any, st: Any, *, updating: bool = False, approved: bool = False) -> dict:
    """One entry of R9's `outOfDate` / `approvedKept` (camelCase)."""
    out = {"documentId": doc.id, "component": doc.group, "name": doc.name,
           "docType": doc.process, "why": list(st.why), "corrections": st.corrections,
           "pictures": st.pictures, "layer": st.layer}
    if not approved:
        out["updating"] = updating
    return out


# ---------------------------------------------------------------------------
# what is running
# ---------------------------------------------------------------------------
def job_kind(job: Any) -> str:
    """`update` | `rebuild` | `export` | `resume` | `generation` -- what R9's `writer.kind` and a
    refusal call the job."""
    mode, reason = getattr(job, "mode", None), getattr(job, "reason", None)
    if mode == EXPORT_MODE:
        return "resume" if reason == "resume" else "export"
    if mode == REEXPORT_MODE:
        return "update" if reason in ("update", "submit") else "rebuild"
    return "generation"


def job_scope_name(job: Any) -> Optional[str]:
    """The update's `scope` as the contract names it: `out_of_date` | `all` (`export` for an
    export job; None for a generation)."""
    return scope_of(getattr(job, "mode", None), getattr(job, "reason", None))


def scope_of(mode: Optional[str], reason: Optional[str]) -> Optional[str]:
    if mode == EXPORT_MODE:
        return "export"
    if mode == REEXPORT_MODE:
        return "out_of_date" if reason in ("update", "submit") else "all"
    return None


def job_components(db: Any, version: Any, job: Any) -> List[str]:
    """The components a re-export or export job writes: its scope's names, or -- a scope not by
    component -- every component the version has documents for."""
    scope = getattr(job, "scope", None) or {}
    if scope.get("type") == "component" and scope.get("names"):
        return list(dict.fromkeys(scope["names"]))
    return all_components(db, version)


def active_render_jobs(db: Any, version_id: str) -> list:
    """The version's re-export (update) and export jobs at work now: their thread in this
    server lives, or -- a background run not followed again yet -- the version's writer lock is
    held. A row a stopped server left `running` is not one."""
    from . import pipeline_runner as pr
    jobs = [j for j in db.jobs.list_for_version(version_id)
            if getattr(j, "mode", None) in RENDER_MODES and j.status in ACTIVE]
    if not jobs:
        return []
    alive = None
    out = []
    for j in jobs:
        if not pr._reexport_alive(j.id) and alive is None:
            alive = pr.version_writer_alive(db, version_id)
        if pr._render_job_running(db, j, alive):
            out.append(j)
    return out


def components_done(rows: Dict[str, dict], components: Iterable[str],
                    since: Optional[datetime]) -> int:
    """Of `components`, how many a run that started at `since` has written: their state row says
    generated (or failed, or stale) and finished after it."""
    since = _aware(since)
    done = 0
    for c in components:
        r = rows.get(c)
        if not r or r.get("state") not in ("generated", "failed", "stale"):
            continue
        fin = _aware(r.get("finished_at"))
        if since is None or (fin is not None and fin >= since):
            done += 1
    return done


def _cli_run(db: Any, version_id: str) -> Optional[dict]:
    """The version's latest run row when a process holds its writer lock now, else None."""
    from . import pipeline_runner as pr
    if not pr.version_writer_alive(db, version_id):
        return None
    vr = pr._version_run_module()
    try:
        return (vr.run_row(version_id, engine=getattr(db, "_engine", None)) or {}) if vr else {}
    except Exception:                                  # noqa: BLE001
        return {}


_COMMAND_KIND = {"generate": "generation", "web": "generation", "export": "export",
                 "reexport": "update", "resume": "resume"}


def writer(db: Any, version: Any, *, snake: bool = False) -> Optional[dict]:
    """What holds the version now (R9 `writer`; `VERSION_BUSY`'s and Submit's `blocked_by`), or
    None: an update or export job of this server, the version's own generation job, or a process
    holding its writer lock (the command line)."""
    from . import pipeline_runner as pr
    rows = None

    def _rows():
        nonlocal rows
        if rows is None:
            try:
                rows = _state_rows(db, version.id)
            except Exception:                           # noqa: BLE001 -- progress only
                rows = {}
        return rows

    def shape(kind, job_id, command, since, components, done, total, started_by):
        out = {"kind": kind, "jobId": job_id, "command": command, "since": _iso(since),
               "components": components, "componentsDone": done, "componentsTotal": total,
               "startedBy": user_ref(db, started_by, snake=snake)}
        if snake:
            out = {"kind": kind, "job_id": job_id, "command": command, "since": _iso(since),
                   "components": components, "components_done": done,
                   "components_total": total, "started_by": out["startedBy"]}
        return out

    jobs = active_render_jobs(db, version.id)
    if jobs:
        j = jobs[0]
        comps = job_components(db, version, j)
        return shape(job_kind(j), j.id, getattr(j, "mode", None), j.started_at, comps,
                     components_done(_rows(), comps, j.started_at), len(comps),
                     getattr(j, "started_by", None))
    gens = [j for j in db.jobs.list_for_version(version.id)
            if getattr(j, "mode", None) not in RENDER_MODES
            and j.status in ("queued", "running", "paused")]
    held = None
    for j in gens:
        if pr.job_alive(j.id) or (held := pr.version_writer_alive(db, version.id)):
            asked = [c for c, r in _rows().items()
                     if _aware(r.get("requested_at")) and _aware(j.started_at)
                     and _aware(r.get("requested_at")) >= _aware(j.started_at)]
            return shape("generation", j.id, "generate", j.started_at, None,
                         components_done(_rows(), asked, j.started_at) if asked else None,
                         len(asked) or None, getattr(j, "started_by", None))
    run = _cli_run(db, version.id) if held is not False else None
    if run is None:
        return None
    since = run.get("started_at")
    asked = [c for c, r in _rows().items()
             if since and _aware(r.get("requested_at")) and _aware(r.get("requested_at")) >= _aware(since)]
    kind = _COMMAND_KIND.get(run.get("command") or "", "other")
    return shape(kind, None, run.get("command"), since,
                 asked if kind in ("update", "export", "resume") and asked else None,
                 components_done(_rows(), asked, since) if asked else None,
                 len(asked) or None, None)


def updating_components(db: Any, version: Any) -> Dict[str, Optional[Any]]:
    """`{component_id: job or None}` -- the components an update or export is writing now: a job
    of this server's scope, or the components a command-line `reexport`, `export` or `resume`
    holding the version asked for (None: no job)."""
    out: Dict[str, Optional[Any]] = {}
    for j in active_render_jobs(db, version.id):
        for c in job_components(db, version, j):
            out.setdefault(_cid(c), j)
    if out:
        return out
    run = _cli_run(db, version.id)
    if not run or _COMMAND_KIND.get(run.get("command") or "") not in ("update", "export", "resume"):
        return out
    since = _aware(run.get("started_at"))
    for c, r in _state_rows(db, version.id).items():
        req = _aware(r.get("requested_at"))
        if since and req and req >= since and r.get("state") in ("waiting", "generating", "generated"):
            out[_cid(c)] = None
    return out


# ---------------------------------------------------------------------------
# R9 / A15
# ---------------------------------------------------------------------------
def readiness(db: Any, version: Any, document: Optional[Any] = None) -> dict:
    """R9's Word-file fields: `outOfDate`, `approvedKept`, `writer`, and whether the version has
    documents at all (`hasDocuments`, for the route's fallback)."""
    docs = version_documents(db, version)
    rows = _state_rows(db, version.id)
    states = file_states(db, version, docs, rows=rows)
    updating = updating_components(db, version) if states else {}
    wanted = [document] if document is not None else docs
    out_of_date, kept = [], []
    for d in sorted(wanted, key=lambda x: ((x.name or "").lower(), x.process or "", x.id)):
        st = states.get(d.id)
        if st is None or not st.out_of_date:
            continue
        if d.status == "approved":
            kept.append(file_view(d, st, approved=True))
        else:
            out_of_date.append(file_view(d, st, updating=_cid(d.group) in updating))
    return {"outOfDate": out_of_date, "approvedKept": kept, "writer": writer(db, version),
            "hasDocuments": bool(docs)}


def failed_components(db: Any, version: Any, job: Any,
                      rows: Optional[Dict[str, dict]] = None) -> Dict[str, str]:
    """`{component: why}` -- the components of an update's scope that ended `failed` in its run
    (finished after it started). Their Word files were not written."""
    since = _aware(getattr(job, "started_at", None))
    if rows is None:
        rows = _state_rows(db, version.id)
    out = {}
    for c in job_components(db, version, job):
        r = rows.get(c) or {}
        fin = _aware(r.get("finished_at"))
        if r.get("state") == "failed" and (since is None or (fin is not None and fin >= since)):
            out[c] = (r.get("error") or "").strip() or "it failed"
    return out


def reexport_extra(db: Any, version: Any, job_row: Any) -> dict:
    """R9 `reexport`'s new fields, from the newest update job's row (`scope`, `reason`,
    `started_by`, `started_at`). `componentsFailed`: the ones of its components that failed
    (WORD_FILE_UPDATES §4.2) -- their Word files were not written."""
    scope = getattr(job_row, "scope", None) or {}
    names = (list(scope.get("names") or []) if scope.get("type") == "component"
             else all_components(db, version))
    reason = getattr(job_row, "reason", None)
    try:
        rows = _state_rows(db, version.id)
    except Exception:                                   # noqa: BLE001 -- progress only
        rows = {}
    job = type("J", (), {"scope": scope, "started_at": getattr(job_row, "started_at", None)})()
    return {"scope": scope_of(REEXPORT_MODE, reason),
            "reason": reason,
            "components": names,
            "componentsDone": components_done(rows, names, getattr(job_row, "started_at", None)),
            "componentsFailed": sorted(failed_components(db, version, job, rows)),
            "startedBy": user_ref(db, getattr(job_row, "started_by", None), snake=False)}


# ---------------------------------------------------------------------------
# the update route
# ---------------------------------------------------------------------------
def _http(status: int, code: str, message: str, **extra) -> HTTPException:
    return HTTPException(status_code=status,
                         detail={"code": code, "message": message, "status": status, **extra})


def _refused(exc: Any) -> HTTPException:
    detail = {"code": exc.code, "message": str(exc), "status": exc.status, **exc.extra}
    if exc.job_id:
        detail["job_id"] = exc.job_id
    return HTTPException(status_code=exc.status, detail=detail)


def start_update(db: Any, version: Any, user: Any, *, scope: Optional[str],
                 components: Optional[List[str]] = None, document_id: Optional[str] = None,
                 reason: Optional[str] = None) -> Tuple[int, dict]:
    """`POST V/reexport` (WORD_FILE_UPDATES §4.1): `(HTTP status, body)`, or raises HTTPException.

    The caller has checked membership and that the version is the project's."""
    from . import pipeline_runner as pr
    from . import review_workflow as rw
    scope = scope or "all"
    if scope not in SCOPES:
        raise _http(422, "VALIDATION_ERROR", "scope is out_of_date or all, not %r." % scope)
    doc = None
    if document_id:
        doc = db.documents.get(document_id)
        if doc is None or doc.project_id != version.project_id or doc.version_id != version.id:
            raise _http(404, "NOT_FOUND", "Document %s is not one of this version's." % document_id)
    admin = rw.is_admin(db, version.project_id, user)
    if scope == "all" and not admin:
        raise _http(403, "FORBIDDEN", "Rebuilding every Word file of a version is for admins; "
                                      "update the out-of-date ones (scope out_of_date).")
    docs = version_documents(db, version)
    asked = list(dict.fromkeys(c for c in (components or []) if c)) or None
    if asked:
        # A component as the config spells it ("Layer1.Sample Core") or in another case is its
        # documents' group ("Layer1.Sample-Core"), as run_views compares them; a name with no
        # document in the version (a typo, a bare name) is said so, as the `all` scope does --
        # not filtered away into "up to date", nor a 403.
        by_ident = {d.group.strip().replace(" ", "-").casefold(): d.group for d in docs}
        mapped = [by_ident.get(c.strip().replace(" ", "-").casefold()) for c in asked]
        unknown = [c for c, m in zip(asked, mapped) if m is None]
        asked = list(dict.fromkeys(m for m in mapped if m)) or None
        if unknown:
            raise _http(422, "INVALID_COMPONENTS",
                        "No documents in version '%s' for: %s. Name a component as its documents "
                        "do (e.g. Layer1.My-Sample)." % (version.id, ", ".join(unknown)),
                        components=unknown)
    if not admin:
        reviews = db.assignments.reviewers([d.id for d in docs])
        bound = {d.group for d in docs if reviews.get(d.id) == user.id}
        if doc is not None:
            bound.add(doc.group)
        if asked:
            outside = [c for c in asked if c not in bound]
            if outside:
                raise _http(403, "NOT_YOUR_DOCUMENTS",
                            "You update the Word files of the documents you review, and of the "
                            "one you have open. Not yours: %s." % ", ".join(outside),
                            components=outside)
        else:
            asked = sorted(bound)
    if scope == "out_of_date":
        states = file_states(db, version, docs)
        out_of_date = sorted({d.group for d in docs if d.status != "approved"
                              and states.get(d.id) is not None and states[d.id].out_of_date})
        targets = [c for c in out_of_date if asked is None or c in asked]
        if not targets:
            return 200, {"job_id": None, "status": "up_to_date", "version_id": version.id,
                         "scope": scope, "components": [], "joined": False}
    else:
        targets = asked
    reason = reason or ("rebuild" if scope == "all" else "update")
    try:
        job, joined, writes = pr.start_update(db, version, targets, started_by=user.id,
                                              reason=reason, document_id=document_id)
    except pr.ReexportRefused as exc:
        raise _refused(exc)
    # Nothing read from the database here: the job's thread has started (see start_update).
    return (200 if joined else 202), {
        "job_id": job.id, "status": job.status, "version_id": version.id,
        "scope": job_scope_name(job) or scope, "components": writes, "joined": joined}


# ---------------------------------------------------------------------------
# Submit, Approve, the saves
# ---------------------------------------------------------------------------
def submit_word_file(db: Any, doc: Any, user: Any) -> dict:
    """A5's `word_file`: after the submit, the update of the document's component when its Word
    file is out of date. A refusal -- another update, a generation holding the version -- is
    reported, never raised: the submit has gone through."""
    try:
        version = db.versions.get(doc.version_id)
        st = file_states(db, version, [doc]).get(doc.id)
        if st is None or not st.out_of_date:
            return {"state": "up_to_date", "job_id": None, "blocked_by": None}
        status, body = start_update(db, version, user, scope="out_of_date",
                                    components=[doc.group], document_id=doc.id, reason="submit")
        if body.get("job_id"):
            return {"state": "updating", "job_id": body["job_id"], "blocked_by": None}
        return {"state": "up_to_date", "job_id": None, "blocked_by": None}
    except HTTPException as exc:
        d = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        if d.get("code") == "VERSION_BUSY" and isinstance(d.get("writer"), dict):
            blocked = dict(d["writer"], message=d.get("message"))
        elif d.get("code") in ("REEXPORT_RUNNING", "EXPORT_RUNNING"):
            blocked = {"kind": d.get("kind") or "update", "job_id": d.get("job_id"),
                       "components": d.get("components") or [], "message": d.get("message")}
        else:
            blocked = {"kind": "other", "job_id": d.get("job_id"), "components": None,
                       "message": d.get("message")}
        return {"state": "out_of_date", "job_id": None, "blocked_by": blocked}
    except Exception as exc:                            # noqa: BLE001 -- see docstring
        _log.exception("submit of %s: its Word file's update could not start", doc.id)
        return {"state": "out_of_date", "job_id": None,
                "blocked_by": {"kind": "other", "job_id": None, "components": None,
                               "message": "the update could not start (%s)" % type(exc).__name__}}


def approval_state(db: Any, doc: Any) -> Tuple[Optional[Any], bool, Optional[str]]:
    """`(FileState or None, updating, job id)` -- what Approve asks: is its component being
    updated now (and by which job), else is its Word file out of date. The state is None when it
    cannot be asked here (no engine database: no correction exists either)."""
    if doc.process not in ("SWE.3", "SWE.4"):
        return None, False, None
    version = db.versions.get(doc.version_id)
    if version is None:
        return None, False, None
    upd = updating_components(db, version)
    if _cid(doc.group) in upd:
        job = upd[_cid(doc.group)]
        return None, True, getattr(job, "id", None)
    if _core_engine() is None:
        return None, False, None
    return file_states(db, version, [doc]).get(doc.id), False, None


def _save_components(version_id: str, slot_kind: Optional[str], slot_key: Optional[str],
                     function_id: Optional[str], candidates: Iterable[str] = ()) -> Optional[set]:
    """The components a save's text is printed in (component_id form); None: any. A struct
    description: those of `candidates` whose stored unit header table shows it, or cannot say
    (per component -- `review.word_files.struct_placement`)."""
    _engine_path()
    if function_id is not None:
        return {_cid(function_id.split("|", 1)[0])} if "|" in function_id else None
    from review import slot as _slot
    from review.derive import component_of
    from review.export_guard import _component_of
    try:
        comp = _component_of(slot_kind, slot_key, component_of)
    except Exception:                                   # noqa: BLE001 -- cannot place: any
        return None
    if comp is not None:
        return {comp}
    if slot_kind != _slot.STRUCT_DESCRIPTION:
        return None
    eng = _core_engine()
    if eng is None:
        return None
    from review.word_files import struct_placement
    with eng.connect() as cx:
        placement = struct_placement(cx, version_id)
    try:
        type_key = _slot.parse(slot_kind, slot_key).get("entity_key") or slot_key
    except Exception:                                   # noqa: BLE001
        type_key = slot_key
    return {c for c in candidates if placement.prints(type_key, c)}


def refuse_if_updating(db: Any, project_id: str, version_id: str, slot_kind: Optional[str] = None,
                       slot_key: Optional[str] = None, *, function_id: Optional[str] = None) -> None:
    """409 `WORD_FILE_UPDATING` when an update or export is writing the component a save's text
    is printed in (WORD_FILE_UPDATES §4.6): its capture would replace the save's rows. A save in any
    other component goes through, and the update leaves it alone."""
    version = db.versions.get(version_id)
    if version is None:
        return
    upd = updating_components(db, version)
    if not upd:
        return
    comps = _save_components(version_id, slot_kind, slot_key, function_id, candidates=upd)
    hits = sorted(upd) if comps is None else sorted(c for c in comps if c in upd)
    if not hits:
        return
    job = next((upd[c] for c in hits if upd[c] is not None), None)
    raise _http(409, "WORD_FILE_UPDATING",
                "Its Word file is being updated now; corrections to it wait until that is done. "
                "Save again then.", job_id=getattr(job, "id", None),
                components=job_components(db, version, job) if job is not None else hits)


# ---------------------------------------------------------------------------
# an update's end
# ---------------------------------------------------------------------------
_told: set = set()
_told_lock = threading.Lock()


def _names(db: Any, version: Any, components: List[str]) -> str:
    """`Brake Controller`, `Brake Controller and HVAC Ctrl`, `3 components`."""
    by_group = {d.group: d.name for d in version_documents(db, version)}
    names = [by_group.get(c) or c.split(".", 1)[-1] for c in components]
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return "%s and %s" % (names[0], names[1])
    return "%d components" % len(names)


def _why(message: Optional[str]) -> str:
    first = (message or "").strip().splitlines()[0] if (message or "").strip() else "see the job"
    first = first.rstrip(".")
    return first[:200]


def tell_update_end(db: Any, job_id: str) -> None:
    """Tell an update's starter how it ended -- and the admins, when Submit started it and it
    failed (WORD_FILE_UPDATES §4.7). Once per job; a cancelled one tells nobody. Never raises."""
    try:
        job = db.jobs.get(job_id)
        if job is None or getattr(job, "mode", None) != REEXPORT_MODE \
                or job.status not in ("complete", "failed") or not getattr(job, "started_by", None):
            return
        with _told_lock:
            if job_id in _told:
                return
            _told.add(job_id)
        version = db.versions.get(job.version_id) if job.version_id else None
        if version is None:
            return
        from . import review_workflow as rw
        rebuild = job_kind(job) == "rebuild"
        tag = version.tag or version.id
        comps = job_components(db, version, job)
        try:
            failed = failed_components(db, version, job)
        except Exception:                               # noqa: BLE001 -- as the job says
            failed = {}
        doc_id = (job.scope or {}).get("document_id")
        doc = db.documents.get(doc_id) if doc_id else None
        verb = "Rebuild" if rebuild else "Update"

        def tell_failed(of: str, why: str) -> None:
            rw.notify(db, [job.started_by], version.project_id, doc, N_UPDATE_FAILED,
                      "%s failed: %s \u2014 %s." % (verb, of, why))
            if getattr(job, "reason", None) == "submit":
                starter = db.users.get_by_id(job.started_by)
                who = starter.name if starter is not None else "a reviewer"
                rw.notify(db, rw.admin_ids(db, version.project_id), version.project_id, doc,
                          N_UPDATE_FAILED, "%s failed: %s, started by the submit of %s \u2014 %s."
                          % (verb, of, who, why), skip=job.started_by)

        if job.status == "complete":
            # A component that failed in it was not written: never "updated" (S7 of the review).
            done = [c for c in comps if c not in failed]
            if done:
                of = tag if (rebuild and not failed) else \
                    "%s in %s" % (_names(db, version, done), tag)
                msg = ("Word files rebuilt: %s." % of) if (rebuild and not failed) \
                    else ("Word files updated: %s." % of)
                rw.notify(db, [job.started_by], version.project_id, doc, N_UPDATED, msg)
            if failed:
                tell_failed("%s in %s" % (_names(db, version, sorted(failed)), tag),
                            _why(next(iter(failed.values()))))
            return
        of = tag if rebuild else "%s in %s" % (_names(db, version, comps), tag)
        # Every component failed (`_complete_reexport`): say why the first one did.
        tell_failed(of, _why(next(iter(failed.values())) if failed else job.error_message))
    except Exception as exc:                            # noqa: BLE001 -- see docstring
        _log.warning("job %s: its end could not be told (%s: %s)", job_id, type(exc).__name__, exc)
