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
    re-derive the affected views             REQ-AP-01  (caller-supplied; see derive.py)
    stamp view_derivations                   REQ-AP-04

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

#: `llm.overrideHistoryDepth`. Newest N human edits per slot survive; the LLM original is not
#: counted against it because it does not live in the history table at all (REQ-ST-04).
DEFAULT_HISTORY_DEPTH = 10


class OverrideError(Exception):
    """The edit was refused. Carries a `status` the API maps straight onto HTTP."""
    status = 400


class EmptyText(OverrideError):
    """REQ-ST-06. Blank is not a correction; it is a slot with nothing in it."""
    status = 422


class SlotUnknown(OverrideError):
    """The key does not name anything in this version, or is not well-formed."""
    status = 404


class NotEditableHere(OverrideError):
    """The kind has no model home yet — see `resolver.SlotHasNoModelHome`."""
    status = 501


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

    def __init__(self, artifacts: Optional[Dict[str, Any]] = None, repo: Any = None,
                 version_id: Optional[str] = None, project_id: Optional[str] = None):
        self._repo = repo
        self._loaded: Dict[str, Any] = dict(artifacts or {})
        self._explicit = artifacts is not None
        self._dirty: set = set()
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

    def mark_dirty(self, name: str) -> None:
        self._dirty.add(name)

    def save(self, conn=None) -> Sequence[str]:
        """Write back only what changed, and **flush**. Returns the artifact names written.

        The flush is not optional. `DbRepository.write` only buffers — the row does not move
        until `flush`, so a save without one reports success and stores nothing, which is the
        exact shape of failure this whole feature exists to remove.

        `conn` is passed through so the model write joins the caller's transaction and lands
        with the override row or not at all (`REQ-AP-02`).
        """
        written = sorted(self._dirty)
        if not self._explicit:
            repo = self._repository()
            for name in written:
                repo.write(name, self._loaded[name])
            if written:
                repo.flush(conn)
        self._dirty.clear()
        return written


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
    arguments `(version_id, slot_kind, location)`. It returns the view names it re-derived.
    Injecting it keeps this module free of the view machinery, which needs an output directory
    and a config that no unit test should have to build.
    """
    text = (human_text or "").strip()
    if not text:
        # REQ-ST-06, and checked before anything is read: an empty update that got as far as
        # writing the model would have erased the LLM's text with nothing in its place.
        raise EmptyText("%s: an override may not be empty or whitespace" % slot_kind)

    if slot_kind not in slot.ALL_KINDS:
        raise SlotUnknown("unknown slot kind %r" % slot_kind)

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
    depth = DEFAULT_HISTORY_DEPTH if history_depth is None else int(history_depth)
    if depth < 1:
        raise OverrideError("history depth must be at least 1; got %r" % history_depth)

    existing = conn.execute(
        select(s.text_overrides.c.llm_text, s.text_overrides.c.human_text)
        .where(s.text_overrides.c.version_id == version_id,
               s.text_overrides.c.slot_kind == slot_kind,
               s.text_overrides.c.slot_key == slot_key)).first()

    first_edit = existing is None
    # Captured once. On a later edit the model holds the HUMAN's previous text, so reading it
    # again would destroy the original and leave a human-vs-human "correction" (REQ-ST-03).
    llm_text = current if first_edit else existing.llm_text
    previous_text = current if first_edit else (existing.human_text or "")

    # --- the model ---------------------------------------------------------
    resolver.write_text(model, slot_kind, slot_key, text)
    models.mark_dirty(location.artifact)
    artifacts_written = models.save(conn)

    # --- the override row --------------------------------------------------
    row = {"llm_text": llm_text, "human_text": text, "is_orphaned": False,
           "updated_by": user_id, "updated_at": stamp}
    if llm_model is not None:
        row["llm_model"] = llm_model
    if llm_cache_version is not None:
        row["llm_cache_version"] = llm_cache_version

    if first_edit:
        conn.execute(insert(s.text_overrides).values(
            version_id=version_id, slot_kind=slot_kind, slot_key=slot_key, **row))
    else:
        # llm_text is in the values deliberately: it is `existing.llm_text` here, so the write
        # is a no-op on it. Leaving the column out would be equally correct today and would
        # stop being correct the moment someone re-read `current` above.
        conn.execute(update(s.text_overrides)
                     .where(s.text_overrides.c.version_id == version_id,
                            s.text_overrides.c.slot_kind == slot_kind,
                            s.text_overrides.c.slot_key == slot_key)
                     .values(**row))

    seq = _append_history(conn, version_id, slot_kind, slot_key, text, user_id, stamp, depth)

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

    # --- the views ---------------------------------------------------------
    views = list(derive(version_id=version_id, slot_kind=slot_kind, location=location) or ()) \
        if derive else []
    _stamp_derivations(conn, version_id, views, stamp)

    return Applied(version_id=version_id, slot_kind=slot_kind, slot_key=slot_key,
                   llm_text=llm_text or "", human_text=text, previous_text=previous_text,
                   location=location, seq=seq, first_edit=first_edit,
                   artifacts_written=artifacts_written, views_derived=views,
                   queued_for_regeneration=[(d.slot_kind, d.slot_key) for d in queued])


# ---------------------------------------------------------------------------
# a whole flowchart in one call (REQ-API-08)
# ---------------------------------------------------------------------------
class FlowchartApplied(NamedTuple):
    version_id: str
    flowchart_id: str
    slot_shape: str
    applied: Sequence[str]              #: node ids written, in request order
    first_edits: Sequence[str]
    redrawn: Sequence[Any]              #: rerender.Redrawn, one per picture rebuilt
    views_derived: Sequence[str]


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

    stamp = now or datetime.datetime.now(datetime.timezone.utc)
    depth = DEFAULT_HISTORY_DEPTH if history_depth is None else int(history_depth)
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

    # --- validate the nodes, still before anything is written ---------------
    missing = sorted(n for n in labels if n not in current)
    if missing:
        raise SlotUnknown("%s has no node(s) %s" % (flowchart_id, ", ".join(missing)))

    # Read once, stamped onto every row of this flowchart, so they cannot disagree about which
    # graph they were written against (REQ-ID-02).
    shape = slot.cfg_shape(current.keys())

    applied, first_edits = [], []
    for node_id, text in labels.items():
        key = slot.for_node(flowchart_id, node_id)
        first = _upsert_override(conn, version_id, slot.NODE_LABEL, key,
                                 human_text=(text or "").strip(),
                                 llm_fallback=current.get(node_id, ""),
                                 user_id=user_id, stamp=stamp, slot_shape=shape)
        _append_history(conn, version_id, slot.NODE_LABEL, key, (text or "").strip(),
                        user_id, stamp, depth)
        applied.append(node_id)
        if first:
            first_edits.append(node_id)

    redrawn = rerender.redraw_flowchart(conn, version_id, flowchart_id,
                                        {n: (labels[n] or "").strip() for n in applied},
                                        output_dir=output_dir, project_root=project_root)

    # One derivation for the whole call, however many labels it carried, and it must cover the
    # component's SWE.4 specs as well as the flowchart (REQ-CS-04).
    views = list(derive(version_id=version_id, slot_kind=slot.NODE_LABEL,
                        flowchart_id=flowchart_id) or ()) if derive else []
    _stamp_derivations(conn, version_id, views, stamp)

    return FlowchartApplied(version_id=version_id, flowchart_id=flowchart_id, slot_shape=shape,
                            applied=applied, first_edits=first_edits, redrawn=redrawn,
                            views_derived=views)


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

    stamp = now or datetime.datetime.now(datetime.timezone.utc)
    depth = DEFAULT_HISTORY_DEPTH if history_depth is None else int(history_depth)
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

    first = _upsert_override(conn, version_id, slot.BEHAVIOUR_DESCRIPTION, key,
                             human_text=text,
                             llm_fallback=p3.join_bullets(row.get("behaviorDescription")),
                             user_id=user_id, stamp=stamp)
    _append_history(conn, version_id, slot.BEHAVIOUR_DESCRIPTION, key, text,
                    user_id, stamp, depth)

    rerender.write_behaviour_row(conn, version_id, rel_path, content, key, text)

    views = list(derive(version_id=version_id, slot_kind=slot.BEHAVIOUR_DESCRIPTION,
                        slot_key=key) or ()) if derive else []
    _stamp_derivations(conn, version_id, views, stamp)

    stored = get_override(conn, version_id, slot.BEHAVIOUR_DESCRIPTION, key)
    return BehaviourApplied(version_id=version_id, slot_key=key,
                            bullets=p3.split_bullets(text),
                            llm_text=(stored.llm_text or "") if stored else "",
                            first_edit=first, views_derived=views)


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
                     user_id, stamp, slot_shape=None) -> bool:
    """Write one override row. Returns whether this was the slot's first edit.

    `llm_fallback` is used as `llm_text` only on that first edit. On a later one the row already
    holds the original and it is left alone — re-reading the current text would replace the LLM's
    words with the human's previous words (`REQ-ST-03`).
    """
    existing = conn.execute(
        select(s.text_overrides.c.llm_text)
        .where(s.text_overrides.c.version_id == version_id,
               s.text_overrides.c.slot_kind == slot_kind,
               s.text_overrides.c.slot_key == slot_key)).first()
    values = {"human_text": human_text, "is_orphaned": False, "updated_by": user_id,
              "updated_at": stamp, "slot_shape": slot_shape}
    if existing is None:
        conn.execute(insert(s.text_overrides).values(
            version_id=version_id, slot_kind=slot_kind, slot_key=slot_key,
            llm_text=llm_fallback, **values))
        return True
    conn.execute(update(s.text_overrides)
                 .where(s.text_overrides.c.version_id == version_id,
                        s.text_overrides.c.slot_kind == slot_kind,
                        s.text_overrides.c.slot_key == slot_key)
                 .values(**values))
    return False


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
def _stamp_derivations(conn, version_id, views, stamp) -> None:
    """Record that these views were derived now — the export guard's input (REQ-AP-04).

    A view is `name` or `(name, group)`. The guard compares the OLDEST derivation against the
    newest override, so a view that was re-derived must have its row moved forward; leaving a
    stale row would report the version as permanently stale.
    """
    for view in views or ():
        name, group = view if isinstance(view, (tuple, list)) else (view, "")
        where = (s.view_derivations.c.version_id == version_id,
                 s.view_derivations.c.view_name == name,
                 s.view_derivations.c.group_name == (group or ""))
        touched = conn.execute(update(s.view_derivations).where(*where)
                               .values(derived_at=stamp)).rowcount
        if not touched:
            conn.execute(insert(s.view_derivations).values(
                version_id=version_id, view_name=name, group_name=(group or ""),
                derived_at=stamp))


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
    row = get_override(conn, version_id, slot_kind, slot_key)
    if row is None:
        raise NothingToUndo("%s %r has no override in version %s"
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
