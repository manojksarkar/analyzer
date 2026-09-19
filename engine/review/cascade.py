"""What else a correction invalidates, and recording it.

`REQ-CS-01`. Some LLM text is generated FROM other LLM text, so correcting one piece leaves the
text built on it describing wording the human has already rejected.

Four chains exist. Traced from each generator's inputs, not guessed:

    1  callee description             -> function description        get_description(source, callee_descriptions, …)
    2  function + global descriptions -> unit description            get_unit_description(unit, fn_items, gv_items, …)
    3  caller + callee descriptions   -> behaviour call description   _build_call_context()
    4  source -> function summary -> … -> node labels                 _summarize_function_batch(signature, body)

**Chain 4 starts from the SOURCE**, never from `description`. That is what bounds this: correcting
a description does not invalidate the ~42,000 flowchart node labels. Without that fact the cascade
would be the whole document.

## Why this records rather than regenerates

Checked, not assumed:

* `get_description` needs the function's **source**, and the source is not in the model — it is in
  the git checkout. The host saving a correction is not guaranteed to have one.
* regenerating is an LLM call; saving a sentence must not take minutes.

And skipping it is not an option either. The description cache is keyed on the callee's source plus
its dependency hashes (`llm_core.cache.compute_hash`), and correcting a *description* changes
neither — so the next run would hit the cache and the caller would keep its stale wording for ever.

So the dependents go in `regeneration_queue`, and a run with a checkout and an LLM consumes it.
`apply_override` can also be handed a generator and do it immediately; the two are the same list.

## One level

`REQ-CS-02`. A transitive cascade is unbounded in a deep call graph — one edit could regenerate
hundreds of functions, each an LLM call. One level is predictable, and a later full regeneration
picks up the rest.
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from typing import Any, Dict, List, NamedTuple, Optional, Sequence

from sqlalchemy import insert, select, update

from review import slot

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from api.db.postgres import schema as s   # noqa: E402


class Dependent(NamedTuple):
    """A slot whose text was built from the corrected one."""
    slot_kind: str
    slot_key: str
    reason: str


def unit_key_of(entity_key: str) -> str:
    """`Component|Unit` from an entity key, the way `model_store._split_key` reads it.

    The first two fields of the id itself, not a re-derivation from anything else — two ways to
    compute one key is how they drift apart.
    """
    parts = (entity_key or "").split("|")
    return "|".join(parts[:2]) if len(parts) >= 2 else ""


def dependents_of(conn, version_id: str, slot_kind: str, slot_key: str, *,
                  artifact: Optional[str] = None) -> List[Dependent]:
    """Everything one level down from this correction (`REQ-CS-01`).

    `artifact` distinguishes a function from a global — both are the `description` kind, and they
    cascade differently. It is what `resolver.locate` already returned, so nothing re-resolves it.

    A dependent that already carries **its own** override is left out (`REQ-CS-03`): a human's text
    is never replaced by a regeneration.
    """
    if slot_kind != slot.DESCRIPTION:
        # Every other kind cascades to nothing. REQ-CS-01's table is the whole list -- a unit or
        # struct description is an output of the chain, a behaviour name is built from the
        # signature, and a node label comes from the source summary chain.
        return []

    out: List[Dependent] = []
    unit_key = unit_key_of(slot_key)
    if unit_key:
        out.append(Dependent(slot.UNIT_DESCRIPTION, slot.for_unit(unit_key),
                             "its unit description is built from this one"))

    if artifact == "globalVariables":
        # A global feeds only its unit's description. It has no callers and appears in no
        # behaviour row.
        return _drop_overridden(conn, version_id, out)

    out += _direct_callers(conn, version_id, slot_key)
    out += _behaviour_rows_touching(conn, version_id, slot_key)
    return _drop_overridden(conn, version_id, out)


def _direct_callers(conn, version_id: str, entity_key: str) -> List[Dependent]:
    """Functions that call this one — one indexed lookup.

    `ix_edges_reverse` on `(version_id, kind, dst_key)` exists for exactly this; the schema
    comments it "who depends on X (impact)".
    """
    rows = conn.execute(
        select(s.model_edges.c.src_key)
        .where(s.model_edges.c.version_id == version_id,
               s.model_edges.c.kind == "call",
               s.model_edges.c.dst_key == entity_key)).fetchall()
    seen, out = set(), []
    for r in rows:
        caller = r.src_key
        if not caller or caller == entity_key or caller in seen:
            continue           # self-recursion is not a dependent of itself
        seen.add(caller)
        out.append(Dependent(slot.DESCRIPTION,
                             slot.for_entity(slot.DESCRIPTION, caller),
                             "its description was written with this function as context"))
    return out


def _behaviour_rows_touching(conn, version_id: str, entity_key: str) -> List[Dependent]:
    """Behaviour call descriptions where this function is the caller or the callee.

    `_build_call_context` uses both descriptions, so either end invalidates the row. Rows without
    an `externalCallerId` are skipped rather than matched on their display label -- see
    `slot.for_behaviour_row` for the two callers that share one.
    """
    from review import phase3_overrides as p3

    out, seen = [], set()
    rows = conn.execute(
        select(s.version_output_files.c.rel_path, s.version_output_files.c.content)
        .where(s.version_output_files.c.version_id == version_id)).fetchall()
    for r in rows:
        if not r.rel_path.endswith("_behaviour_pngs.json"):
            continue
        try:
            payload = json.loads(r.content or "{}")
        except ValueError:
            continue           # one unreadable manifest must not lose the rest of the cascade
        for _c, _u, row in p3.behaviour_rows((payload or {}).get("_docxRows")):
            fid, caller = row.get("currentFunctionId"), row.get("externalCallerId")
            if not (fid and caller) or entity_key not in (fid, caller):
                continue
            try:
                key = slot.for_behaviour_row(fid, caller)
            except slot.SlotKeyError:
                continue
            if key in seen:
                continue
            seen.add(key)
            out.append(Dependent(slot.BEHAVIOUR_DESCRIPTION, key,
                                 "this call description was written from both descriptions"))
    return out


def _drop_overridden(conn, version_id: str, items: Sequence[Dependent]) -> List[Dependent]:
    """`REQ-CS-03`. A slot a human has already corrected is not regenerated over."""
    if not items:
        return []
    overridden = {(r.slot_kind, r.slot_key) for r in conn.execute(
        select(s.text_overrides.c.slot_kind, s.text_overrides.c.slot_key)
        .where(s.text_overrides.c.version_id == version_id)).fetchall()}
    return [d for d in items if (d.slot_kind, d.slot_key) not in overridden]


# ---------------------------------------------------------------------------
# the queue
# ---------------------------------------------------------------------------
def enqueue(conn, version_id: str, dependents: Sequence[Dependent], *,
            source_kind: str = "", source_key: str = "",
            user_id: Optional[str] = None,
            now: Optional[datetime.datetime] = None) -> int:
    """Record dependents as needing regeneration. Returns how many rows the queue now names.

    Idempotent per slot: a second correction that invalidates the same caller **moves the entry
    forward** rather than adding a duplicate. Regenerating it twice would cost two LLM calls to
    reach the same place.
    """
    if not dependents:
        return 0
    stamp = now or datetime.datetime.now(datetime.timezone.utc)
    added = 0
    for d in dependents:
        where = (s.regeneration_queue.c.version_id == version_id,
                 s.regeneration_queue.c.slot_kind == d.slot_kind,
                 s.regeneration_queue.c.slot_key == d.slot_key)
        values = {"reason": d.reason, "source_slot_kind": source_kind,
                  "source_slot_key": source_key, "requested_by": user_id,
                  "requested_at": stamp}
        if not conn.execute(update(s.regeneration_queue).where(*where).values(**values)).rowcount:
            conn.execute(insert(s.regeneration_queue).values(
                version_id=version_id, slot_kind=d.slot_kind, slot_key=d.slot_key, **values))
        added += 1
    return added


def pending(conn, version_id: str, *, slot_kind: Optional[str] = None):
    """What is waiting to be regenerated, oldest first."""
    q = (select(s.regeneration_queue)
         .where(s.regeneration_queue.c.version_id == version_id)
         .order_by(s.regeneration_queue.c.requested_at, s.regeneration_queue.c.slot_key))
    if slot_kind:
        q = q.where(s.regeneration_queue.c.slot_kind == slot_kind)
    return conn.execute(q).fetchall()


def clear(conn, version_id: str, slot_kind: str, slot_key: str) -> bool:
    """Drop one entry, once it has actually been regenerated. True if there was one.

    Deliberately not "clear the version": an entry must survive until the thing it names has been
    rebuilt, or a half-finished run would leave the document quietly stale with an empty queue
    saying everything is fine.
    """
    return bool(conn.execute(
        s.regeneration_queue.delete().where(
            s.regeneration_queue.c.version_id == version_id,
            s.regeneration_queue.c.slot_kind == slot_kind,
            s.regeneration_queue.c.slot_key == slot_key)).rowcount)


# ---------------------------------------------------------------------------
# consuming it
# ---------------------------------------------------------------------------
def blank_queued_text(conn, version_id: str, model) -> List:
    """Empty the model text of every queued MODEL-BACKED slot, so Phase 2 rewrites it.

    No force-regenerate switch is needed, and adding one would be a second way to say the same
    thing: `_enrich_from_llm` already skips a function "when already present (the engine carries
    them forward)", so removing the stale text is exactly the instruction "generate this again".

    `model` is the artifact dict Phase 2 is holding. Mutated in place. Returns the entries it
    blanked, for the caller to clear once they have actually been rewritten -- clearing them
    here would lose the obligation if the phase then failed.

    `behaviourDescription` entries are not touched: their text is not in the model at all. Phase 3
    rewrites every behaviour row it emits, so `clear_behaviour_entries` retires those separately,
    where the rewriting happens.
    """
    from review import resolver

    blanked = []
    for row in pending(conn, version_id):
        if row.slot_kind not in resolver.MODEL_BACKED_KINDS:
            continue
        try:
            loc = resolver.locate(model, row.slot_kind, row.slot_key)
        except (resolver.SlotError, slot.SlotKeyError):
            # The slot no longer exists in this version. Retire the entry rather than leaving it
            # to be retried for ever against something that is not there.
            blanked.append(row)
            continue
        model[loc.artifact][loc.entry_key][loc.field] = ""
        blanked.append(row)
    return blanked


def clear_rewritten(conn, version_id: str, entries, model) -> int:
    """Retire the entries whose slot now carries text again. Returns how many.

    An entry whose slot came back **empty** is kept: the regeneration did not happen -- the LLM
    was unreachable, or descriptions are switched off -- and dropping it would quietly convert
    "still owed" into "done".
    """
    from review import resolver

    n = 0
    for row in entries or ():
        try:
            text = resolver.read_text(model, row.slot_kind, row.slot_key).strip()
        except (resolver.SlotError, slot.SlotKeyError):
            text = ""            # gone from this version: retire it, see blank_queued_text
            clear(conn, version_id, row.slot_kind, row.slot_key)
            n += 1
            continue
        if text:
            clear(conn, version_id, row.slot_kind, row.slot_key)
            n += 1
    return n


def clear_behaviour_entries(conn, version_id: str) -> int:
    """Retire the queued behaviour-row regenerations. Returns how many.

    Called after Phase 3, because the behaviour view rebuilds every row it writes -- a queued
    behaviour description is regenerated by the act of running that view, so once it has run the
    obligation is met.
    """
    n = 0
    for row in pending(conn, version_id, slot_kind=slot.BEHAVIOUR_DESCRIPTION):
        clear(conn, version_id, row.slot_kind, row.slot_key)
        n += 1
    return n
