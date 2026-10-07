"""What else a correction invalidates, and recording it.

`REQ-CS-01`. Some LLM text is generated FROM other LLM text, so correcting one piece leaves the
text built on it describing wording the human has already rejected. Only a description is read by
another prompt -- traced from each prompt builder, not guessed (FAST_WORD_FILE_UPDATES §4.1):

    function and global descriptions  <- callers', callees', file siblings' and globals' descriptions
    unit description                  <- its functions' and globals' descriptions
    input and output names            <- the descriptions of the globals the function reads and writes
    behaviour call descriptions       <- both ends' descriptions
    flowchart node labels             <- the function's own, its callers', its callees' (four calls
                                         deep) and its globals' descriptions (`flowchart/pkb/builder`)

## Recorded at the save, rewritten by the update

Checked, not assumed:

* a description's prompt holds the function's **source**, which is not in the model -- it is in
  the git checkout. The host saving a correction is not guaranteed to have one.
* regenerating is an LLM call; saving a sentence must not take minutes.

So the save records the dependents in `regeneration_queue`, and the Word-file update of their
component rewrites them before it exports (`review.rewrite`; decided with the user, D1 and D3) --
a re-derive pays the ones it rebuilds, as before.

And skipping it is not an option either. The description cache is keyed on the source plus the
callees' source hashes (`llm_core.cache.compute_hash`), and the label cache on the source alone; a
corrected *description* moves neither -- so the next run would hit the cache and keep the stale
wording for ever.

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


#: A queued CHART: the node labels of one flowchart, which the LLM writes together and the
#: flowcharts view rewrites together (FAST_WORD_FILE_UPDATES P5). Not an editable slot kind -- a
#: reviewer corrects one label (`nodeLabel`) -- and keyed by the function's entity key.
FLOWCHART_LABELS = "flowchartLabels"

#: How far up the call graph a label prompt names callees and their descriptions
#: (`flowchart/pkb/builder._CALLEE_BFS_DEPTH`).
LABEL_CALLEE_DEPTH = 4


def dependents_of(conn, version_id: str, slot_kind: str, slot_key: str, *,
                  artifact: Optional[str] = None) -> List[Dependent]:
    """Everything one level down from this correction (`REQ-CS-01`): every text whose prompt can
    contain it. Read from the prompt builders (FAST_WORD_FILE_UPDATES §4.1); only a description
    is read by another prompt.

    A function's description `F` is in the prompt of: the descriptions of its callers, its callees
    and the other functions of its file, and of the globals it reaches through calls
    (`llm_enrichment._build_function_context`, `enrich_globals_rich`); its unit's description;
    the behaviour rows whose call tree it is in, or whose incoming call it makes
    (`CallDescriptionGenerator`); and the labels of its own chart, its callees' charts and every
    chart within `LABEL_CALLEE_DEPTH` calls above it (`flowchart/pkb/builder`). A global's is in
    the prompt of its unit's description and of the descriptions, input and output names and chart
    labels of every function that reaches it through calls (the knowledge base's read and write
    sets are transitive).

    These are CANDIDATES: prompts are cut to a token budget, so a far caller may not carry it.
    The update that rewrites them checks each prompt first (`review.rewrite`).

    `artifact` distinguishes a function from a global — both are the `description` kind, and they
    cascade differently. It is what `resolver.locate` already returned, so nothing re-resolves it.

    A dependent that already carries **its own** override is left out (`REQ-CS-03`): a human's text
    is never replaced by a regeneration.
    """
    if slot_kind != slot.DESCRIPTION:
        # Every other kind cascades to nothing: no prompt reads an input or output name, a unit,
        # struct or behaviour description, or a node label (FAST_WORD_FILE_UPDATES §4.1).
        return []

    out: List[Dependent] = []
    unit_key = unit_key_of(slot_key)
    if unit_key:
        out.append(Dependent(slot.UNIT_DESCRIPTION, slot.for_unit(unit_key),
                             "its unit description is built from this one"))
    graph = _Graph(conn, version_id)

    if artifact == "globalVariables":
        for fid in sorted(graph.reaching_global(slot_key)):
            out += [
                Dependent(slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, fid),
                          "its description was written with this global as context"),
                Dependent(slot.INPUT_NAME, slot.for_entity(slot.INPUT_NAME, fid),
                          "its input and output names were written with this global as context"),
                Dependent(FLOWCHART_LABELS, fid,
                          "its flowchart labels were written with this global as context")]
        return _drop_overridden(conn, version_id, out)

    described = (set(graph.callers(slot_key)) | set(graph.callees(slot_key))
                 | set(_same_file_functions(conn, version_id, slot_key))) - {slot_key}
    out += [Dependent(slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, fid),
                      "its description was written with this function as context")
            for fid in sorted(described)]
    out += [Dependent(slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, gid),
                      "its description was written with this function as context")
            for gid in sorted(graph.globals_reached(slot_key))]
    out += _behaviour_rows_touching(conn, version_id, slot_key,
                                    graph.callers_closure(slot_key) | {slot_key}
                                    | graph.callees_closure(slot_key))
    charts = ({slot_key} | set(graph.callees(slot_key))
              | graph.callers_closure(slot_key, depth=LABEL_CALLEE_DEPTH))
    out += [Dependent(FLOWCHART_LABELS, fid,
                      "its flowchart labels were written with this function as context")
            for fid in sorted(charts)]
    return _drop_overridden(conn, version_id, out)


class _Graph:
    """The version's call and global-access edges, read ONCE (two indexed queries), walked in
    memory: a correction's dependents reach through call chains, and a query per step would be
    a query per function on a real project."""

    def __init__(self, conn, version_id: str):
        e = s.model_edges
        self._down: Dict[str, set] = {}
        self._up: Dict[str, set] = {}
        for r in conn.execute(select(e.c.src_key, e.c.dst_key)
                              .where(e.c.version_id == version_id, e.c.kind == "call")):
            if r.src_key and r.dst_key and r.src_key != r.dst_key:
                self._down.setdefault(r.src_key, set()).add(r.dst_key)
                self._up.setdefault(r.dst_key, set()).add(r.src_key)
        self._touches: Dict[str, set] = {}
        self._touched_by: Dict[str, set] = {}
        for r in conn.execute(select(e.c.src_key, e.c.dst_key)
                              .where(e.c.version_id == version_id,
                                     e.c.kind == "global_access")):
            if r.src_key and r.dst_key:
                self._touches.setdefault(r.src_key, set()).add(r.dst_key)
                self._touched_by.setdefault(r.dst_key, set()).add(r.src_key)

    def callers(self, fid: str) -> set:
        return set(self._up.get(fid, ()))

    def callees(self, fid: str) -> set:
        return set(self._down.get(fid, ()))

    @staticmethod
    def _closure(start, step, depth: Optional[int] = None) -> set:
        seen, frontier, level = set(), set(start), 0
        while frontier and (depth is None or level < depth):
            level += 1
            nxt = set()
            for k in frontier:
                nxt |= step(k)
            frontier = nxt - seen
            seen |= frontier
        return seen

    def callers_closure(self, fid: str, depth: Optional[int] = None) -> set:
        """Every function that reaches `fid` through calls -- within `depth` calls if given."""
        return self._closure({fid}, self.callers, depth) - {fid}

    def callees_closure(self, fid: str) -> set:
        """Every function `fid` reaches through calls."""
        return self._closure({fid}, self.callees) - {fid}

    def globals_reached(self, fid: str) -> set:
        """The globals `fid` reads or writes, itself or through its callees (transitive, as the
        knowledge base's read and write sets are)."""
        reached = self._closure({fid}, self.callees) | {fid}
        return set().union(*(self._touches.get(f, set()) for f in reached))

    def reaching_global(self, gid: str) -> set:
        """Every function that reads or writes `gid`, itself or through a callee."""
        direct = set(self._touched_by.get(gid, ()))
        return direct | set().union(*(self._closure({f}, self.callers) for f in direct))


def _same_file_functions(conn, version_id: str, entity_key: str) -> List[str]:
    """The other functions of `entity_key`'s source file -- the siblings a rich description's
    prompt lists (`llm_enrichment._build_function_context`)."""
    ev, en = s.entity_versions, s.entities
    row = conn.execute(select(ev.c.file).select_from(ev.join(en, ev.c.entity_id == en.c.entity_id))
                       .where(ev.c.version_id == version_id,
                              en.c.entity_key == entity_key)).first()
    if not row or not row.file:
        return []
    return [r.entity_key for r in conn.execute(
        select(en.c.entity_key).select_from(ev.join(en, ev.c.entity_id == en.c.entity_id))
        .where(ev.c.version_id == version_id, ev.c.file == row.file,
               en.c.kind == "function", en.c.entity_key != entity_key))]


def _behaviour_rows_touching(conn, version_id: str, entity_key: str,
                             row_functions=None) -> List[Dependent]:
    """Behaviour rows whose call descriptions can be written from this function's description.

    A row's LLM bullets describe its incoming call -- from the caller the view drew it for -- and
    the calls of its function's call tree (`MermaidBuilder.build_diagram_for_caller`,
    `CallDescriptionGenerator`), each from both ends' descriptions; the "returns to" bullets are
    written without the LLM. So the rows of the function itself, of every function that reaches
    it through calls, and of every function it reaches -- it may be a row's caller, which the view
    takes from the callers of callers (`selector.get_external_callers_with_component`)
    (`row_functions`, candidates -- the update compares each call's prompt). Without
    `row_functions`: the rows of this function. Rows without an `externalCallerId` are skipped
    rather than matched on their display label -- see `slot.for_behaviour_row` for the two callers
    that share one.
    """
    from review import phase3_overrides as p3, rerender

    wanted = set(row_functions) if row_functions is not None else {entity_key}
    out, seen = [], set()
    for r in rerender.output_rows(conn, version_id, rerender.BEHAVIOUR_MANIFEST):
        try:
            payload = json.loads(r.content or "{}")
        except ValueError:
            continue           # one unreadable manifest must not lose the rest of the cascade
        for _c, _u, row in p3.behaviour_rows((payload or {}).get("_docxRows")):
            fid, caller = row.get("currentFunctionId"), row.get("externalCallerId")
            if not (fid and caller) or fid not in wanted:
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
    """`REQ-CS-03`. A slot a human has already corrected is not regenerated over.

    The input and output names are written together, so an `inputName` entry stands for both: it
    goes only when BOTH are corrected (the rewrite keeps whichever one is). A chart's entry stays
    whatever its labels: the rewrite puts each corrected label back on top."""
    if not items:
        return []
    overridden = {(r.slot_kind, r.slot_key) for r in conn.execute(
        select(s.text_overrides.c.slot_kind, s.text_overrides.c.slot_key)
        .where(s.text_overrides.c.version_id == version_id)).fetchall()}

    def human(d: Dependent) -> bool:
        if d.slot_kind == slot.INPUT_NAME:
            return all((k, d.slot_key) in overridden for k in (slot.INPUT_NAME, slot.OUTPUT_NAME))
        return (d.slot_kind, d.slot_key) in overridden

    return [d for d in items if not human(d)]


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
class Blanked(NamedTuple):
    """A queued slot whose model text was emptied, and the text that was there before.

    The previous text is carried so it can be PUT BACK. Blanking is not a decision that the text
    should go -- it is how this code says "write this again" to an enrichment step that skips
    anything already filled in. If the rewrite then does not happen, the blank is an outcome
    nobody chose, and publishing it would be worse than publishing the superseded wording.
    """
    row: Any
    previous_text: str


def blank_queued_text(conn, version_id: str, model, kinds=None) -> List["Blanked"]:
    """Empty the model text of every queued MODEL-BACKED slot, so Phase 2 rewrites it.

    `kinds` limits it to the entries whose text the caller is about to regenerate. Phase 2 takes
    the function descriptions before it describes functions and the unit descriptions before it
    describes units, each with the artifact that holds them; an entry of another kind is left
    queued, untouched. Handed a model without its artifact, an entry would read as "the slot no
    longer exists" and be retired unpaid -- which is how every queued unit description was lost.

    No force-regenerate switch is needed, and adding one would be a second way to say the same
    thing: `_enrich_from_llm` already skips a function "when already present (the engine carries
    them forward)", so removing the stale text is exactly the instruction "generate this again".

    `model` is the artifact dict Phase 2 is holding. Mutated in place. Returns a `Blanked` per
    entry -- the queue row and the text that was removed -- for the caller to hand back to
    `clear_rewritten`. Nothing is cleared here: that would lose the obligation if the phase then
    failed.

    `behaviourDescription` entries are not touched: their text is not in the model at all. Phase 3
    rewrites every behaviour row it emits, so `clear_behaviour_entries` retires those separately,
    where the rewriting happens.
    """
    from review import resolver

    blanked = []
    for row in pending(conn, version_id):
        if row.slot_kind not in resolver.MODEL_BACKED_KINDS:
            continue
        if kinds is not None and row.slot_kind not in kinds:
            continue
        try:
            loc = resolver.locate(model, row.slot_kind, row.slot_key)
        except (resolver.SlotError, slot.SlotKeyError):
            # The slot no longer exists in this version. Retire the entry rather than leaving it
            # to be retried for ever against something that is not there.
            blanked.append(Blanked(row, ""))
            continue
        previous = model[loc.artifact][loc.entry_key].get(loc.field) or ""
        model[loc.artifact][loc.entry_key][loc.field] = ""
        blanked.append(Blanked(row, previous))
    return blanked


class Retired(NamedTuple):
    """What `clear_rewritten` did: entries retired, and slots whose old text was put back."""
    cleared: int
    restored: int


def clear_rewritten(conn, version_id: str, entries, model) -> "Retired":
    """Retire the entries whose slot now carries text again; put the others back as they were.

    An entry whose slot came back **empty** is kept queued: the regeneration did not happen --
    the LLM was unreachable, or descriptions are switched off -- and dropping it would quietly
    convert "still owed" into "done".

    **And its previous text is restored.** Keeping the obligation is not enough on its own. The
    text was removed by `blank_queued_text` purely as a way of asking for a rewrite, so a rewrite
    that never came must leave the model exactly as it was found. Without this, one unreachable
    LLM turns a stale-but-readable description into an empty cell in the document -- worse than
    the wording the correction superseded, and worse than what the reader had before anybody
    corrected anything.

    What comes back is the superseded wording, which is precisely why the entry stays queued: the
    debt is still owed, and the next run with a working LLM pays it.
    """
    from review import resolver

    cleared = restored = 0
    for item in entries or ():
        row, previous = item if isinstance(item, Blanked) else Blanked(item, "")
        try:
            text = resolver.read_text(model, row.slot_kind, row.slot_key).strip()
        except (resolver.SlotError, slot.SlotKeyError):
            # Gone from this version: retire it, see blank_queued_text. There is nowhere to put
            # the old text back into, and nothing that would read it if there were.
            clear(conn, version_id, row.slot_kind, row.slot_key)
            cleared += 1
            continue
        if text:
            clear(conn, version_id, row.slot_kind, row.slot_key)
            cleared += 1
        elif previous:
            resolver.write_text(model, row.slot_kind, row.slot_key, previous)
            restored += 1
    return Retired(cleared, restored)


def clear_behaviour_entries(conn, version_id: str, rebuilt, components) -> int:
    """Retire the queued behaviour-row regenerations a behaviour-view run has paid. Returns how
    many.

    Called after Phase 3 when the `behaviourDiagram` view ran. The view rebuilds every row it
    writes, so a queued row is regenerated by that run exactly when the run covered it:

      * `rebuilt` -- the slot keys of the rows the run wrote: regenerated, retire;
      * a queued row whose function is in one of `components` (the run's scope) and that the run
        did NOT write: it no longer exists, so nothing is owed -- retire;
      * any other row: another component, not rebuilt by this run -- keep.

    Clearing every behaviour entry after every Phase 3, as this used to, retired rows a SWE.4-only
    run or a run over another component never touched, and the queue then said they were done.
    """
    from review.export_guard import component_id

    rebuilt = set(rebuilt or ())
    scope = {component_id(c) for c in (components or ()) if component_id(c)}
    n = 0
    for row in pending(conn, version_id, slot_kind=slot.BEHAVIOUR_DESCRIPTION):
        try:
            fid = slot.parse(slot.BEHAVIOUR_DESCRIPTION, row.slot_key)["function_id"]
        except slot.SlotKeyError:
            continue
        if row.slot_key in rebuilt or component_id(fid.split("|", 1)[0]) in scope:
            clear(conn, version_id, row.slot_kind, row.slot_key)
            n += 1
    return n
