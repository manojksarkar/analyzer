"""Saving a reviewer's correction. One entry point, used by the API and by tests.

    apply_override(conn, version_id, kind, key, human_text, models=...)

Everything it does is inside the caller's transaction (`REQ-AP-02`). A half-applied override —
the model moved, the view rows did not — is precisely the failure this feature exists to remove,
so there is no partial success to recover from: either the whole edit lands or none of it does.

## What it does, in order

    reject empty text                        REQ-ST-06
    resolve the slot -> a model field        resolver.py
    read the current model text
    capture llm_text, once, on first edit    REQ-ST-03
    write human_text into the model
    upsert text_overrides                    REQ-ST-05  (one row, direct lookup)
    append history and trim to N             REQ-ST-04
    re-derive the affected views             REQ-AP-01  (caller-supplied; see derive.py and
                                                        swe4_rederive.py)
    stamp view_derivations                   REQ-AP-04  (and mark the stored records)

The cascade (§6) and image renders (§7) are steps 6 and 7 of the build order and are not here.
Renders are deliberately *not* transactional anyway — they are slow, and idempotent if retried.

## Five kinds, not seven

`nodeLabel` and `behaviourDescription` are refused with `NotEditableHere`: their text lives only
in Phase-3 view output, so an override written for them would be reverted by the next derivation
(see `resolver`). `REQ-ID-02`'s `slot_shape` capture belongs in this function, right before the
model write, and is deliberately absent until `nodeLabel` has a model home — code no caller can
reach is code no test can check. `slot.cfg_shape()` and the column are ready for it.

## llm_text is captured once and never rewritten

On the second edit of a slot the model already holds the *human's* previous text, so reading it
again would overwrite the LLM original with human prose. There would then be nothing to undo to
(`REQ-API-04`) and the training pair would be human-vs-human (`REQ-TD-01`) — two texts that look
like a correction and teach the opposite of one.

## The model is written through the repository gateway

Never `entity_versions` directly. `ModelAccess` buffers the artifacts it touched and writes back
only those: persisting all four when one changed turns a one-field edit into a whole-model
rewrite, and `model_repo`'s flush guard has already been the subject of one defect.
"""
from __future__ import annotations

import datetime
import os
import sys
from typing import Any, Callable, Dict, NamedTuple, Optional, Sequence

from sqlalchemy import delete, func, insert, select, update

from review import resolver, slot

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from api.db.postgres import schema as s   # noqa: E402

#: Fallback for `llm.overrideHistoryDepth`. Newest N human edits per slot survive; the LLM
#: original is not counted against it because it does not live in the history table at all
#: (REQ-ST-04). Used only when the version's own config does not say -- see `version_settings`.
DEFAULT_HISTORY_DEPTH = 10


class VersionSettings(NamedTuple):
    """What the run that generated a version was configured with.

    Read from `versions.resolved_config`, which is THAT config -- not today's. A correction made
    now is a correction to text generated then, so its provenance is then's model and prompt
    version (`REQ-TD-02`), and the history cap it obeys is the one that version was created under.
    """
    history_depth: int
    llm_model: object
    llm_cache_version: object


def version_settings(conn, version_id: str) -> VersionSettings:
    """A version's own LLM settings, falling back to the defaults.

    Never raises. A version with no stored config is ordinary -- every version generated before
    `resolved_config` existed has none -- and a missing setting must not stop somebody saving a
    sentence.
    """
    try:
        cfg = conn.execute(select(s.versions.c.resolved_config)
                           .where(s.versions.c.id == version_id)).scalar() or {}
        llm = (cfg.get("llm") or {}) if isinstance(cfg, dict) else {}
        depth = llm.get("overrideHistoryDepth")
        cache_version = str(llm.get("cacheVersion") or "").strip()
        return VersionSettings(
            history_depth=int(depth) if depth else DEFAULT_HISTORY_DEPTH,
            llm_model=llm.get("model") or None,
            llm_cache_version=int(cache_version) if cache_version.isdigit() else None)
    except Exception:                                  # noqa: BLE001 - see docstring
        return VersionSettings(DEFAULT_HISTORY_DEPTH, None, None)


class OverrideError(Exception):
    """The edit was refused. Carries a `status` the API maps straight onto HTTP, and a `code`
    when a client must tell this refusal from the others (then the answer is an object)."""
    status = 400
    code = None


class EmptyText(OverrideError):
    """REQ-ST-06. Blank is not a correction; it is a slot with nothing in it."""
    status = 422


class SlotUnknown(OverrideError):
    """The key does not name anything in this version, or is not well-formed."""
    status = 404


class NoStoredGraph(OverrideError):
    """The flowchart exists but its stored output carries no graph, so its labels cannot be
    addressed.

    `cfg` has only been written since 2026-09-01 (`3355930`); a version generated before that has
    the picture and the DOT but not the graph they were built from. Reported as its own condition
    because the alternatives both mislead: an empty label list reads as "this flowchart has no
    nodes", and "no node n3" blames a node when the problem is the whole graph.

    Re-deriving the version restores it — the CFG is rebuilt from the model, not re-parsed.
    """
    status = 409


class NotEditableHere(OverrideError):
    """The kind has no model home yet — see `resolver.SlotHasNoModelHome`."""
    status = 501


class VersionBusy(OverrideError):
    """The version's model was replaced while the save was writing it -- a run is regenerating
    this version. Nothing was saved; save again once the run has finished."""
    status = 409
    #: The web app says "save again once the run has finished" for this one -- not a plain retry.
    code = "VERSION_REGENERATING"


def _begin():
    """A transaction of its own, for a caller that did not hand one in."""
    from core.db import get_engine
    return get_engine().begin()


def _serialize_saves(conn, version_id: str) -> None:
    """One save at a time per version (PostgreSQL; SQLite serialises writers by itself).

    A save reads before it writes -- the current text, whether the slot has an override row, the
    history's last sequence number, the stored rows the SWE.4 re-derive rebuilds -- so two saves
    on one version at the same moment could each act on what the other was changing: two first
    edits of one slot both inserting (a unique violation), two history rows with one sequence
    number, a re-derived spec without the other save's label. A transaction-scoped advisory lock
    on the version makes the second save wait for the first. It is released at commit or
    rollback, and taking it again in the same transaction -- undo calls a save -- costs nothing.
    """
    if getattr(getattr(conn, "dialect", None), "name", "") != "postgresql":
        return
    import hashlib
    from sqlalchemy import text as _sql
    key = int.from_bytes(hashlib.sha256(("review:" + version_id).encode("utf-8")).digest()[:8],
                         "big", signed=True)
    conn.execute(_sql("SELECT pg_advisory_xact_lock(:k)"), {"k": key})


class Applied(NamedTuple):
    version_id: str
    slot_kind: str
    slot_key: str
    llm_text: str
    human_text: str
    previous_text: str
    location: resolver.Location
    seq: int
    first_edit: bool
    artifacts_written: Sequence[str]
    views_derived: Sequence[str]
    #: Slots whose text was built from this one and now need regenerating (REQ-CS-01).
    queued_for_regeneration: Sequence[Any] = ()
    #: Interface-table entries whose copy of the description was brought into step.
    tables_patched: int = 0


# ---------------------------------------------------------------------------
# model access
# ---------------------------------------------------------------------------
class ModelAccess:
    """The model artifacts an edit touches, and the write-back of just those.

    Backed by `core.model_repo` in a real run. Tests pass `artifacts=` a plain dict, which is
    also what makes every rule below testable without a database or a parsed project.
    """

    #: Loaded on demand. `description` may land in either of the first two.
    ARTIFACTS = ("functions", "globalVariables", "units", "dataDictionary")

    #: How `save` writes one field of each artifact: the entity kinds of its `entity_versions`
    #: row, or None for `units`, whose description is a column of `model_units`.
    _ONE_ROW = {"functions": ("function",), "globalVariables": ("global",),
                "dataDictionary": ("type", "macro"), "units": None}

    def __init__(self, artifacts: Optional[Dict[str, Any]] = None, repo: Any = None,
                 version_id: Optional[str] = None, project_id: Optional[str] = None):
        self._repo = repo
        self._loaded: Dict[str, Any] = dict(artifacts or {})
        self._explicit = artifacts is not None
        self._dirty: set = set()
        self._dirty_fields: set = set()
        self._version_id = version_id
        self._project_id = project_id

    def _repository(self):
        """The repository for this version.

        Built from `(version_id, project_id)` when given, because an API process has no
        "current run" and therefore no repository installed — `model_repo.repository()` would
        raise, and deliberately: there is no default any more, since a default was once what
        made a misconfigured run look successful.
        """
        if self._repo is None:
            from core import model_repo
            if self._version_id:
                self._repo = model_repo.DbRepository(self._version_id, self._project_id or "")
            else:
                self._repo = model_repo.repository()
        return self._repo

    def artifact(self, name: str) -> Dict[str, Any]:
        if name not in self._loaded:
            if self._explicit:
                # An in-memory model is the whole model. Inventing an empty artifact here
                # would turn "that function is not in this version" into "no functions exist",
                # and the slot would resolve against nothing instead of reporting a 404.
                return {}
            self._loaded[name] = self._repository().read(name, required=False, default={}) or {}
        return self._loaded[name]

    def as_model(self) -> Dict[str, Any]:
        """The artifact dict `resolver` works against."""
        return {name: self.artifact(name) for name in self.ARTIFACTS}

    def loaded(self, name: str) -> Optional[Dict[str, Any]]:
        """The artifact if this edit already holds it -- with its correction, if it made one --
        else None. For a caller that must not read through a connection of its own once the
        save has written (`swe4_rederive.model_of`)."""
        if name in self._loaded:
            return self._loaded[name]
        return {} if self._explicit else None

    def mark_dirty(self, name: str, entry_key: Optional[str] = None,
                   field: Optional[str] = None) -> None:
        """Record what changed: one field of one entry (what a correction changes), or -- with
        no entry -- a whole artifact."""
        if entry_key is not None and field is not None:
            self._dirty_fields.add((name, entry_key, field))
        else:
            self._dirty.add(name)

    def save(self, conn=None) -> Sequence[str]:
        """Write back only what changed. Returns the artifact names written.

        **One row per changed field** (`model_store.set_entity_field`, `set_unit_description`).
        This used to hand the whole artifact to the repository and flush it, which runs
        `clear_version` and `persist_model` over the entire version from a snapshot read before
        this transaction: every function, global, type, edge and hash row rewritten for one
        sentence, and two saves at once -- or a save beside a Phase-2 run -- putting back
        whatever the other had just changed. A row that is gone (`ModelRowMissing`) fails the
        save rather than reporting a correction that stored nothing.

        `conn` is passed through so the model write joins the caller's transaction and lands
        with the override row or not at all (`REQ-AP-02`).
        """
        written = sorted(self._dirty | {artifact for artifact, _k, _f in self._dirty_fields})
        if not self._explicit:
            fields = sorted(self._dirty_fields)
            vid = (self._version_id or getattr(self._repository(), "version_id", None)
                   if fields else None)
            if fields and vid:
                self._write_rows(conn, vid, fields)
            elif fields:
                # A file-backed repository has no rows to update: the whole artifact, as before.
                self._dirty.update(artifact for artifact, _k, _f in fields)
            if self._dirty:
                # Whole artifacts: a file-backed repository's, or a caller's that marked one.
                repo = self._repository()
                for name in sorted(self._dirty):
                    repo.write(name, self._loaded[name])
                repo.flush(conn)
        self._dirty.clear()
        self._dirty_fields.clear()
        return written

    def _write_rows(self, conn, version_id: str, fields) -> None:
        import contextlib
        from core import model_store
        opened = contextlib.nullcontext(conn) if conn is not None else _begin()
        with opened as cx:
            for artifact, key, field in fields:
                value = ((self._loaded.get(artifact) or {}).get(key) or {}).get(field)
                if artifact == "units":
                    model_store.set_unit_description(cx, version_id, key, value)
                else:
                    model_store.set_entity_field(cx, version_id, key, field, value,
                                                 self._ONE_ROW.get(artifact) or (artifact,))


# ---------------------------------------------------------------------------
# the entry point
# ---------------------------------------------------------------------------
def apply_override(conn,
                   version_id: str,
                   slot_kind: str,
                   slot_key: str,
                   human_text: str,
                   *,
                   models: Optional[ModelAccess] = None,
                   user_id: Optional[str] = None,
                   now: Optional[datetime.datetime] = None,
                   history_depth: Optional[int] = None,
                   llm_model: Optional[str] = None,
                   llm_cache_version: Optional[int] = None,
                   derive: Optional[Callable[..., Sequence[str]]] = None) -> Applied:
    """Save one correction. See the module docstring for the order of operations.

    `conn` is an open SQLAlchemy connection inside a transaction the CALLER owns — this function
    neither begins nor commits, so an API handler can wrap the edit and its response in one unit
    and a test can roll the whole thing back.

    `derive` is called after the rows are written and before the stamp, with the keyword
    arguments `(version_id, slot_kind, location)`. It returns the view names it re-derived for the
    slot's component -- in every stored directory that carries them, since they are stamped for
    the component as a whole. Injecting it keeps this module free of the view machinery; the API
    passes `review.swe4_rederive.make_save_deriver`.
    """
    text = (human_text or "").strip()
    if not text:
        # REQ-ST-06, and checked before anything is read: an empty update that got as far as
        # writing the model would have erased the LLM's text with nothing in its place.
        raise EmptyText("%s: an override may not be empty or whitespace" % slot_kind)

    if slot_kind not in slot.ALL_KINDS:
        raise SlotUnknown("unknown slot kind %r" % slot_kind)

    # Before anything is read: everything below reads, then writes.
    _serialize_saves(conn, version_id)

    models = models if models is not None else ModelAccess()
    model = models.as_model()

    try:
        location = resolver.locate(model, slot_kind, slot_key)
    except resolver.SlotHasNoModelHome as exc:
        raise NotEditableHere(str(exc)) from None
    except (resolver.SlotNotFound, slot.SlotKeyError) as exc:
        raise SlotUnknown(str(exc)) from None

    current = resolver.read_text(model, slot_kind, slot_key)
    stamp = now or datetime.datetime.now(datetime.timezone.utc)
    settings = version_settings(conn, version_id)
    depth = settings.history_depth if history_depth is None else int(history_depth)
    if depth < 1:
        raise OverrideError("history depth must be at least 1; got %r" % history_depth)

    existing = conn.execute(
        select(s.text_overrides.c.llm_text, s.text_overrides.c.human_text,
               s.text_overrides.c.is_orphaned)
        .where(s.text_overrides.c.version_id == version_id,
               s.text_overrides.c.slot_kind == slot_kind,
               s.text_overrides.c.slot_key == slot_key)).first()

    # A first edit is one on a slot with no correction -- or with only an ORPHANED one. That was
    # written for code that has since changed and is not applied: the model holds the fresh LLM
    # text for the new code, and that text is this slot's original now. Keeping the orphan's
    # llm_text would make an undo restore a sentence about code that no longer exists.
    first_edit = existing is None or bool(existing.is_orphaned)
    # Captured once per original. On a later edit the model holds the HUMAN's previous text, so
    # reading it again would destroy the original and leave a human-vs-human "correction"
    # (REQ-ST-03).
    llm_text = current if first_edit else existing.llm_text
    previous_text = current if first_edit else (existing.human_text or "")

    # --- the model ---------------------------------------------------------
    # One row: the field this slot names, nothing else (`ModelAccess.save`).
    resolver.write_text(model, slot_kind, slot_key, text)
    models.mark_dirty(location.artifact, location.entry_key, location.field)
    try:
        artifacts_written = models.save(conn)
    except LookupError as exc:                  # model_store.ModelRowMissing
        raise VersionBusy("%s. A run is regenerating version %s; nothing was saved -- save "
                          "again once it has finished." % (exc, version_id)) from None

    # --- the override row --------------------------------------------------
    # REQ-TD-02. Which model and prompt version produced the text being corrected -- without
    # them a correction cannot be interpreted after a prompt change, which is the whole reason
    # the pair is stored at all. Taken from the VERSION's config rather than today's: the text
    # was generated under that one.
    row = {"llm_text": llm_text, "human_text": text, "is_orphaned": False,
           "updated_by": user_id, "updated_at": stamp,
           "llm_model": llm_model if llm_model is not None else settings.llm_model,
           "llm_cache_version": (llm_cache_version if llm_cache_version is not None
                                 else settings.llm_cache_version)}

    if existing is None:
        conn.execute(insert(s.text_overrides).values(
            version_id=version_id, slot_kind=slot_kind, slot_key=slot_key, **row))
    else:
        # llm_text is in the values deliberately: for a live correction it is
        # `existing.llm_text`, a no-op; for an orphan it is the current text, its new original.
        conn.execute(update(s.text_overrides)
                     .where(s.text_overrides.c.version_id == version_id,
                            s.text_overrides.c.slot_kind == slot_kind,
                            s.text_overrides.c.slot_key == slot_key)
                     .values(**row))

    seq = _append_history(conn, version_id, slot_kind, slot_key, text, user_id, stamp, depth)

    # --- the derived copy --------------------------------------------------
    # The document does not read a description from the model: the interface-tables view writes a
    # COPY into its own output, and both the DOCX exporter and the HTML view read that copy. The
    # model write above is therefore not enough on its own -- without this the page keeps showing
    # the LLM's words while the model holds the human's.
    #
    # Only `description` needs it. A unit or struct description and the behaviour names are read
    # from the model directly (`docx_exporter._load_model_json`), so they are already current.
    tables_patched = 0
    if slot_kind == slot.DESCRIPTION:
        from review import rerender as _rr
        tables_patched = _rr.patch_interface_tables(
            conn, version_id, resolver.entity_of(slot_kind, slot_key), text)

    # --- the cascade -------------------------------------------------------
    # Text generated FROM this text is now describing wording the human has rejected. The
    # dependents are RECORDED, not regenerated here: regenerating needs the function's source
    # (which is in the git checkout, not the model) and an LLM call, and a saved sentence must
    # not take minutes. See cascade.py for why skipping it instead would leave them stale for
    # ever -- the description cache would hit on the next run.
    from review import cascade as _cascade
    queued = _cascade.dependents_of(conn, version_id, slot_kind, slot_key,
                                    artifact=location.artifact)
    _cascade.enqueue(conn, version_id, queued, source_kind=slot_kind, source_key=slot_key,
                     user_id=user_id, now=stamp)
    # And the slot just written owes nothing: a human's text is never regenerated over
    # (REQ-CS-03), so an entry queued for it earlier would only pay for an LLM call whose answer
    # Phase 2 then replaces with this text.
    _cascade.clear(conn, version_id, slot_kind, slot_key)

    # --- the views ---------------------------------------------------------
    views = list(derive(version_id=version_id, slot_kind=slot_kind, location=location) or ()) \
        if derive else []
    _stamp_derivations(conn, version_id, views, stamp,
                       _component_of_id(next(iter(slot.parse(slot_kind, slot_key).values()), "")))

    return Applied(version_id=version_id, slot_kind=slot_kind, slot_key=slot_key,
                   llm_text=llm_text or "", human_text=text, previous_text=previous_text,
                   location=location, seq=seq, first_edit=first_edit,
                   artifacts_written=artifacts_written, views_derived=views,
                   queued_for_regeneration=[(d.slot_kind, d.slot_key) for d in queued],
                   tables_patched=tables_patched)


# ---------------------------------------------------------------------------
# a whole flowchart in one call (REQ-API-08)
# ---------------------------------------------------------------------------
class FlowchartApplied(NamedTuple):
    version_id: str
    flowchart_id: str
    slot_shape: str
    applied: Sequence[str]              #: node ids written, in request order
    first_edits: Sequence[str]
    #: `rerender.Redrawn`, one per flowchart whose JSON + DOT were rebuilt. This is a DATABASE
    #: fact and says nothing about the picture: `redraw_flowchart` rebuilds the DOT whether or
    #: not it has an output tree to draw a PNG in.
    redrawn: Sequence[Any]
    views_derived: Sequence[str]
    #: render_jobs ids raised for this save (REQ-IM-02). Already `done` when drawn inline.
    render_jobs: Sequence[int] = ()
    #: The picture is still owed -- a job was raised and NOT completed here.
    #:
    #: Derived from the jobs, not from `redrawn`. An earlier version asked
    #: `render_jobs and not redrawn`, which read "the DOT was rebuilt" as "the image was drawn"
    #: and so reported False on every API save: the API has no output tree, the PNG was never
    #: produced, and the export blocked on a job the caller had just been told was not pending.
    render_pending: bool = False
    #: `{node_id: label}` as the picture carried it before this save, for each node saved.
    previous: Dict[str, str] = {}


def apply_flowchart_overrides(conn,
                              version_id: str,
                              flowchart_id: str,
                              labels: Dict[str, str],
                              *,
                              user_id: Optional[str] = None,
                              now: Optional[datetime.datetime] = None,
                              history_depth: Optional[int] = None,
                              output_dir: Optional[str] = None,
                              project_root: Optional[str] = None,
                              derive: Optional[Callable[..., Sequence[str]]] = None
                              ) -> FlowchartApplied:
    """Save the corrected labels of one flowchart (`REQ-API-08`).

    `labels` is `{node_id: text}` and carries **only what the reviewer changed**. Sending a stale
    copy of an untouched label would overwrite a correction someone else made to that label
    seconds earlier, and nothing here could tell that from a deliberate revert — `REQ-API-07`'s
    "last write wins" was agreed per slot, and this is what keeps it meaning that.

    **All or nothing.** Every label is validated before any is written, so one bad node fails the
    call and the picture is never rebuilt from a half-applied edit.

    A node label is not a model field (`REQ-AP-05`), so this does not go through `apply_override`:
    there is nothing in the model to write. The override table is the source, and Phase 3 is handed
    it as an input.
    """
    from review import rerender

    if not labels:
        raise OverrideError("no labels to apply")

    _serialize_saves(conn, version_id)
    stamp = now or datetime.datetime.now(datetime.timezone.utc)
    settings = version_settings(conn, version_id)
    depth = settings.history_depth if history_depth is None else int(history_depth)
    if depth < 1:
        raise OverrideError("history depth must be at least 1; got %r" % history_depth)

    # --- validate the text, before anything is read -------------------------
    blank = sorted(n for n, t in labels.items() if not (t or "").strip())
    if blank:
        raise EmptyText("%s: empty text for node(s) %s" % (flowchart_id, ", ".join(blank)))

    found = rerender.find_flowchart_row(conn, version_id, flowchart_id)
    if not found:
        raise SlotUnknown("no flowchart %s in version %s" % (flowchart_id, version_id))
    _rel_path, _unit, content = found

    entry = _flowchart_entry(content, flowchart_id)
    cfg = entry.get("cfg") or {}
    current = {str(n.get("id")): str(n.get("label") or "")
               for n in (cfg.get("nodes") or []) if isinstance(n, dict) and n.get("id")}
    if not current:
        # Checked BEFORE the per-node validation below, or every node would be reported missing
        # and the message would blame the caller's node ids for the absence of the whole graph.
        raise NoStoredGraph(
            "%s has no stored graph in version %s, so its labels cannot be corrected. Its output "
            "predates the CFG being stored; re-derive the version first: "
            "python analyzer.py reexport --project-id <pid> --version-id %s --from-phase 3"
            % (flowchart_id, version_id, version_id))

    # --- validate the nodes, still before anything is written ---------------
    missing = sorted(n for n in labels if n not in current)
    if missing:
        raise SlotUnknown("%s has no node(s) %s" % (flowchart_id, ", ".join(missing)))

    # Read once, stamped onto every row this call writes, so they cannot disagree about which
    # graph they were written against (REQ-ID-02).
    shape = slot.cfg_shape(current.keys())

    # And the graph is in hand, so the flowchart's other corrections are judged against it: one
    # written for another graph -- carried from a version whose builder numbered the nodes
    # differently -- is orphaned rather than left claiming to be in force. Before the writes
    # below, so a node saved here over such a row starts a new correction, with the LLM's label
    # for THIS graph as its original.
    from review.carry_forward import orphan_misplaced_labels
    orphan_misplaced_labels(conn, version_id, graphs={flowchart_id: {shape}})

    applied, first_edits = [], []
    for node_id, text in labels.items():
        key = slot.for_node(flowchart_id, node_id)
        first = _upsert_override(conn, version_id, slot.NODE_LABEL, key,
                                 human_text=(text or "").strip(),
                                 llm_fallback=current.get(node_id, ""),
                                 user_id=user_id, stamp=stamp, slot_shape=shape,
                                 settings=settings)
        _append_history(conn, version_id, slot.NODE_LABEL, key, (text or "").strip(),
                        user_id, stamp, depth)
        applied.append(node_id)
        if first:
            first_edits.append(node_id)

    from review import render_queue

    redrawn = rerender.redraw_flowchart(conn, version_id, flowchart_id,
                                        {n: (labels[n] or "").strip() for n in applied},
                                        output_dir=output_dir, project_root=project_root)

    # A job per redrawn picture, so the EXPORT can ask whether one is still being produced
    # (REQ-IM-02). Recorded even when the render just happened here: the row is what an export
    # on another host consults, and "it was done inline" is not something it can see.
    # Whether the PICTURE was produced here, which is only possible with somewhere to put it.
    # `redrawn` cannot answer this: it is true as soon as the stored DOT is rebuilt.
    drew_inline = bool(output_dir and project_root)

    render_jobs = []
    for item in redrawn:
        job = render_queue.enqueue(conn, version_id, item.flowchart_id, item.png_name,
                                   user_id=user_id, now=stamp)
        render_jobs.append(job)
        if drew_inline:
            # Drawn inside this call, so it is already finished. Marking it done here rather than
            # not recording it keeps one answer to "is this version's picture current".
            render_queue.complete(conn, job, now=stamp)

    # One derivation for the whole call, however many labels it carried, and it must cover the
    # component's SWE.4 specs as well as the flowchart (REQ-CS-04).
    views = list(derive(version_id=version_id, slot_kind=slot.NODE_LABEL,
                        flowchart_id=flowchart_id) or ()) if derive else []
    _stamp_derivations(conn, version_id, views, stamp, _component_of_id(flowchart_id))

    return FlowchartApplied(version_id=version_id, flowchart_id=flowchart_id, slot_shape=shape,
                            applied=applied, first_edits=first_edits, redrawn=redrawn,
                            render_pending=bool(render_jobs) and not drew_inline,
                            views_derived=views, render_jobs=render_jobs,
                            previous={n: current.get(n, "") for n in applied})


# ---------------------------------------------------------------------------
# one behaviour row (REQ-ED-02)
# ---------------------------------------------------------------------------
class BehaviourApplied(NamedTuple):
    version_id: str
    slot_key: str
    bullets: Sequence[str]
    llm_text: str
    first_edit: bool
    views_derived: Sequence[str]
    #: The row's bullets before this save, one per line -- what the document printed.
    previous_text: str = ""


def apply_behaviour_override(conn,
                             version_id: str,
                             function_id: str,
                             external_caller_id: str,
                             bullets,
                             *,
                             user_id: Optional[str] = None,
                             now: Optional[datetime.datetime] = None,
                             history_depth: Optional[int] = None,
                             derive: Optional[Callable[..., Sequence[str]]] = None
                             ) -> BehaviourApplied:
    """Save the corrected description of one behaviour row (`REQ-ED-02`).

    `bullets` is the whole list, one per call arrow, edited together — the API accepts and returns
    it as a unit. There is no batching endpoint for this kind: a function has a handful of
    behaviour rows, not the ~42,000 node labels that made `REQ-API-08` necessary.

    Addressed by **two entity keys**, the current function and its external caller, never by the
    `externalUnitFunction` display label — see `slot.for_behaviour_row` for what that label loses
    and which two rows collide on it.

    No `slot_shape` (there is no graph to be wrong about) and no render: the description appears in
    no picture, because `MermaidBuilder` labels each arrow with the callee's name (`REQ-IM-01`).
    """
    from review import phase3_overrides as p3, rerender

    text = p3.join_bullets(bullets if not isinstance(bullets, str)
                           else p3.split_bullets(bullets))
    if not text:
        raise EmptyText("a behaviour description may not be empty")

    _serialize_saves(conn, version_id)
    stamp = now or datetime.datetime.now(datetime.timezone.utc)
    settings = version_settings(conn, version_id)
    depth = settings.history_depth if history_depth is None else int(history_depth)
    if depth < 1:
        raise OverrideError("history depth must be at least 1; got %r" % history_depth)

    try:
        key = slot.for_behaviour_row(function_id, external_caller_id)
    except slot.SlotKeyError as exc:
        raise SlotUnknown(str(exc)) from None

    found = rerender.find_behaviour_row(conn, version_id, function_id, external_caller_id)
    if not found:
        raise SlotUnknown("no behaviour row for %s called by %s in version %s"
                          % (function_id, external_caller_id, version_id))
    rel_path, content, row = found
    previous = p3.join_bullets(row.get("behaviorDescription"))

    first = _upsert_override(conn, version_id, slot.BEHAVIOUR_DESCRIPTION, key,
                             human_text=text,
                             llm_fallback=p3.join_bullets(row.get("behaviorDescription")),
                             user_id=user_id, stamp=stamp, settings=settings)
    _append_history(conn, version_id, slot.BEHAVIOUR_DESCRIPTION, key, text,
                    user_id, stamp, depth)

    rerender.write_behaviour_row(conn, version_id, rel_path, content, key, text)
    # The row a human just wrote owes no regeneration (REQ-CS-03) -- see apply_override.
    from review import cascade as _cascade
    _cascade.clear(conn, version_id, slot.BEHAVIOUR_DESCRIPTION, key)

    views = list(derive(version_id=version_id, slot_kind=slot.BEHAVIOUR_DESCRIPTION,
                        slot_key=key) or ()) if derive else []
    _stamp_derivations(conn, version_id, views, stamp, _component_of_id(function_id))

    stored = get_override(conn, version_id, slot.BEHAVIOUR_DESCRIPTION, key)
    return BehaviourApplied(version_id=version_id, slot_key=key,
                            bullets=p3.split_bullets(text),
                            llm_text=(stored.llm_text or "") if stored else "",
                            first_edit=first, views_derived=views, previous_text=previous)


def _flowchart_entry(content: str, flowchart_id: str) -> Dict[str, Any]:
    import json
    try:
        entries = json.loads(content or "[]")
    except ValueError:
        raise SlotUnknown("stored flowchart JSON is unreadable") from None
    for e in entries if isinstance(entries, list) else ():
        if isinstance(e, dict) and e.get("functionKey") == flowchart_id:
            return e
    raise SlotUnknown("no flowchart %s in the stored output" % flowchart_id)


def _upsert_override(conn, version_id, slot_kind, slot_key, *, human_text, llm_fallback,
                     user_id, stamp, slot_shape=None, settings=None) -> bool:
    """Write one override row. Returns whether this was the slot's first edit.

    `llm_fallback` is used as `llm_text` only on that first edit. On a later one the row already
    holds the original and it is left alone — re-reading the current text would replace the LLM's
    words with the human's previous words (`REQ-ST-03`). A row that is ORPHANED counts as no
    correction: it was written for code that has since changed, and the current text -- fresh
    LLM text, as an orphan is never applied -- is the slot's original now (see `apply_override`).
    """
    existing = conn.execute(
        select(s.text_overrides.c.llm_text, s.text_overrides.c.is_orphaned)
        .where(s.text_overrides.c.version_id == version_id,
               s.text_overrides.c.slot_kind == slot_kind,
               s.text_overrides.c.slot_key == slot_key)).first()
    values = {"human_text": human_text, "is_orphaned": False, "updated_by": user_id,
              "updated_at": stamp, "slot_shape": slot_shape,
              # REQ-TD-02, the same provenance the model-backed path records.
              "llm_model": settings.llm_model if settings else None,
              "llm_cache_version": settings.llm_cache_version if settings else None}
    if existing is None:
        conn.execute(insert(s.text_overrides).values(
            version_id=version_id, slot_kind=slot_kind, slot_key=slot_key,
            llm_text=llm_fallback, **values))
        return True
    if existing.is_orphaned:
        values["llm_text"] = llm_fallback
    conn.execute(update(s.text_overrides)
                 .where(s.text_overrides.c.version_id == version_id,
                        s.text_overrides.c.slot_kind == slot_kind,
                        s.text_overrides.c.slot_key == slot_key)
                 .values(**values))
    return bool(existing.is_orphaned)


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------
def _append_history(conn, version_id, slot_kind, slot_key, text, user_id, stamp, depth) -> int:
    """Append this edit and drop everything older than the newest `depth` (REQ-ST-04).

    `seq` is per slot and monotonic, so the trim is one indexed delete rather than "find the
    oldest rows" — `ix_override_history_slot` is on `(version_id, slot_kind, slot_key, seq)`.
    """
    where = (s.text_override_history.c.version_id == version_id,
             s.text_override_history.c.slot_kind == slot_kind,
             s.text_override_history.c.slot_key == slot_key)
    top = conn.execute(select(func.max(s.text_override_history.c.seq)).where(*where)).scalar()
    seq = int(top or 0) + 1

    conn.execute(insert(s.text_override_history).values(
        version_id=version_id, slot_kind=slot_kind, slot_key=slot_key,
        human_text=text, updated_by=user_id, updated_at=stamp, seq=seq))

    cutoff = seq - depth
    if cutoff > 0:
        conn.execute(delete(s.text_override_history)
                     .where(*where, s.text_override_history.c.seq <= cutoff))
    return seq


# ---------------------------------------------------------------------------
# derivation stamps
# ---------------------------------------------------------------------------
def _stamp_derivations(conn, version_id, views, stamp, component=None) -> None:
    """Record that these views were derived now — the export guard's input (REQ-AP-04).

    A view is `name` or `(name, component)`; a bare name was re-derived for `component`, the saved
    slot's, in every stored directory that carries it -- that is what `derive=` promises. Stamped
    at the save's own time, the correction's `updated_at`, and marked in the stored records so the
    next capture keeps the stamp (`export_guard.stamp_saved`). With no component to name -- a
    struct description's key is its type's name -- nothing is stamped: a stamp for no component
    would vouch for nothing, and the guard ignores one.
    """
    from review.export_guard import stamp_saved
    pairs = []
    for view in views or ():
        name, comp = view if isinstance(view, (tuple, list)) else (view, component)
        if name and comp:
            pairs.append((name, comp))
    stamp_saved(conn, version_id, pairs, stamp)


def _component_of_id(ident: Optional[str]) -> Optional[str]:
    """`Comp|Unit|name|params` (or `Comp|Unit`) -> `Comp`; None for an id that names no
    component, such as a data-dictionary key."""
    return ident.split("|", 1)[0] if ident and "|" in ident else None


# ---------------------------------------------------------------------------
# reading back
# ---------------------------------------------------------------------------
class NothingToUndo(OverrideError):
    """No override on this slot, or its original cannot be restored."""
    status = 409


def undo_override(conn, version_id: str, slot_kind: str, slot_key: str, *,
                  models: Optional[ModelAccess] = None,
                  user_id: Optional[str] = None,
                  now: Optional[datetime.datetime] = None,
                  history_depth: Optional[int] = None,
                  output_dir: Optional[str] = None,
                  project_root: Optional[str] = None,
                  derive: Optional[Callable[..., Sequence[str]]] = None):
    """Put the LLM's original wording back (`REQ-API-04`).

    **Undo is an ordinary edit whose text happens to be the original**, not a special state. So it
    goes through the same write path, the row survives with both texts, and the history records
    that the undo happened — which is what `REQ-API-04` asks for ("the override record survives").

    That also makes the after-state self-consistent everywhere else: re-applying the override
    during a Phase-3 run writes the LLM's own words back, which is a no-op, and `REQ-TD-01`'s rule
    that a training export skips pairs whose two texts are equal already excludes it.

    Refused when there is no original to restore. That happens when the slot was empty before the
    first correction — a function with no description, say — and `REQ-ST-06` forbids writing empty
    text. Deleting the row instead would destroy the user's work and the edit history to express
    "there was nothing here", which is worth an explicit error rather than a silent guess.
    """
    _serialize_saves(conn, version_id)
    row = get_override(conn, version_id, slot_kind, slot_key)
    if row is None:
        raise NothingToUndo("%s %r has no override in version %s"
                            % (slot_kind, slot_key, version_id))
    if row.is_orphaned:
        # Its `llm_text` is the original of code that has since changed. Restoring it would put a
        # sentence about code that no longer exists into the document; and the document already
        # shows the LLM's text for the current code, as an orphan is never applied.
        raise NothingToUndo(
            "%s %r in version %s is orphaned: it was written for code that has since changed, "
            "so it is not applied and the document already shows the LLM's text for the "
            "current code. There is nothing to undo; a new edit starts a new correction."
            % (slot_kind, slot_key, version_id))
    original = (row.llm_text or "").strip()
    if not original:
        raise NothingToUndo(
            "%s %r has no LLM original to restore: the slot was empty before it was first "
            "corrected, and an override may not be set to empty (REQ-ST-06). Delete it "
            "explicitly if that is what you mean." % (slot_kind, slot_key))

    common = dict(user_id=user_id, now=now, history_depth=history_depth, derive=derive)

    if slot_kind == slot.NODE_LABEL:
        parts = slot.parse(slot.NODE_LABEL, slot_key)
        if not _fits_the_stored_graph(conn, version_id, parts["entity_key"], row.slot_shape):
            # REQ-ID-02. Its `llm_text` is the LLM's label for the node that held this id in
            # the graph the correction was written for; here that id is another box.
            raise NothingToUndo(
                "%s %r in version %s was written for an earlier numbering of its flowchart's "
                "nodes, so it is not applied and the document already shows the LLM's label for "
                "the current graph. There is nothing to undo; a new edit starts a new "
                "correction." % (slot_kind, slot_key, version_id))
        return apply_flowchart_overrides(
            conn, version_id, parts["entity_key"], {parts["node_id"]: original},
            output_dir=output_dir, project_root=project_root, **common)

    if slot_kind == slot.BEHAVIOUR_DESCRIPTION:
        from review import phase3_overrides as p3
        parts = slot.parse(slot.BEHAVIOUR_DESCRIPTION, slot_key)
        return apply_behaviour_override(
            conn, version_id, parts["function_id"], parts["external_caller_id"],
            p3.split_bullets(original), **common)

    return apply_override(conn, version_id, slot_kind, slot_key, original,
                          models=models, **common)


def _fits_the_stored_graph(conn, version_id: str, flowchart_id: str,
                           claimed: Optional[str]) -> bool:
    """Whether a node-label correction claiming `claimed` fits the flowchart this version
    stores. No claim, or no stored graph to hold it against, is not a misfit here: the save
    that follows reports a missing graph itself."""
    if not claimed:
        return True
    from review import rerender
    found = rerender.find_flowchart_row(conn, version_id, flowchart_id)
    if not found:
        return True
    try:
        return slot.shape_matches(
            claimed, slot.shape_of_cfg(_flowchart_entry(found[2], flowchart_id).get("cfg")))
    except (SlotUnknown, slot.SlotKeyError):
        return True


def list_overrides(conn, version_id: str, *, slot_kind: Optional[str] = None,
                   limit: int = 200, offset: int = 0):
    """The corrections in a version, newest first — an **overlay**, not a slot enumeration.

    `REQ-API-01` asks for the slots of a document with their text and whether each is overridden. A
    version holds roughly 57,000 slots, so enumerating them here would rebuild the document the UI
    has already fetched. It fetches this instead and merges by slot key: the overridden ones are
    the few, the lookup is indexed (`ix_text_overrides_version_kind`), and a version nobody has
    corrected returns an empty list without touching the model.
    """
    q = (select(s.text_overrides)
         .where(s.text_overrides.c.version_id == version_id)
         .order_by(s.text_overrides.c.updated_at.desc(), s.text_overrides.c.slot_key)
         .limit(max(1, min(int(limit), 1000))).offset(max(0, int(offset))))
    if slot_kind:
        if slot_kind not in slot.ALL_KINDS:
            raise SlotUnknown("unknown slot kind %r" % slot_kind)
        q = q.where(s.text_overrides.c.slot_kind == slot_kind)
    return conn.execute(q).fetchall()


def overrides_by_key(conn, version_id: str, slot_kind: str, keys) -> Dict[str, Any]:
    """`{slot_key: row}` for exactly these keys -- one flowchart's nodes, say.

    Not `list_overrides(...)`, which pages the WHOLE version newest-first: the flowchart editor
    used it with `limit=1000`, so on a version with more than a thousand node corrections an
    older correction on the flowchart being opened fell off the page and its node was reported
    as never corrected. Asking for the keys actually needed has no such ceiling.

    Chunked because SQLite caps bound parameters; a flowchart large enough to hit it is unlikely,
    and a silent truncation is exactly the failure this function exists to remove.
    """
    keys = [k for k in dict.fromkeys(keys or ()) if k]
    out: Dict[str, Any] = {}
    for i in range(0, len(keys), 500):
        chunk = keys[i:i + 500]
        for r in conn.execute(select(s.text_overrides).where(
                s.text_overrides.c.version_id == version_id,
                s.text_overrides.c.slot_kind == slot_kind,
                s.text_overrides.c.slot_key.in_(chunk))):
            out[r.slot_key] = r
    return out


def count_overrides(conn, version_id: str, *, slot_kind: Optional[str] = None) -> int:
    """How many corrections a version has, for the list's `total`."""
    q = select(func.count()).select_from(s.text_overrides).where(
        s.text_overrides.c.version_id == version_id)
    if slot_kind:
        q = q.where(s.text_overrides.c.slot_kind == slot_kind)
    return int(conn.execute(q).scalar() or 0)


def get_override(conn, version_id: str, slot_kind: str, slot_key: str):
    """The current override row, or None. One indexed lookup (REQ-ST-05)."""
    return conn.execute(
        select(s.text_overrides)
        .where(s.text_overrides.c.version_id == version_id,
               s.text_overrides.c.slot_kind == slot_kind,
               s.text_overrides.c.slot_key == slot_key)).first()


def history_for(conn, version_id: str, slot_kind: str, slot_key: str):
    """Every retained edit for one slot, oldest first."""
    return conn.execute(
        select(s.text_override_history)
        .where(s.text_override_history.c.version_id == version_id,
               s.text_override_history.c.slot_kind == slot_kind,
               s.text_override_history.c.slot_key == slot_key)
        .order_by(s.text_override_history.c.seq)).fetchall()


def overrides_for_version(conn, version_id: str, slot_kind: Optional[str] = None):
    """Every override in a version, for the HTML render and for carry-forward.

    Fetched in one query rather than per slot: the page resolves thousands of slots, and a
    lookup each would make render cost grow with the document (REQ-ST-05).
    """
    q = select(s.text_overrides).where(s.text_overrides.c.version_id == version_id)
    if slot_kind:
        q = q.where(s.text_overrides.c.slot_kind == slot_kind)
    return conn.execute(q).fetchall()


def discard_orphans(conn, version_id: str, *, slot_kind: Optional[str] = None,
                    slot_key: Optional[str] = None) -> int:
    """Delete this version's ORPHANED corrections -- written for code that has since changed, so
    never printed (`REQ-ID-03`) -- and their history: all of them, those of one kind, or one slot.
    Returns how many. Final: an orphan is the reviewer's old words, kept for reference until
    someone decides they are not needed; nothing restores them, and a later version made from
    this one no longer carries them. A correction in force is never touched."""
    to, hist = s.text_overrides, s.text_override_history
    cond = (to.c.version_id == version_id) & to.c.is_orphaned.is_(True)
    if slot_kind:
        cond = cond & (to.c.slot_kind == slot_kind)
    if slot_key:
        cond = cond & (to.c.slot_key == slot_key)
    keys = conn.execute(select(to.c.slot_kind, to.c.slot_key).where(cond)).fetchall()
    for k in keys:
        conn.execute(delete(hist).where(hist.c.version_id == version_id,
                                        hist.c.slot_kind == k.slot_kind,
                                        hist.c.slot_key == k.slot_key))
    if keys:
        conn.execute(delete(to).where(cond))
    return len(keys)
