"""Carrying corrections into the next version.

`REQ-VR-01`. Generating v4 from v3: a function whose code did not change keeps the human's wording;
one whose code changed gets fresh LLM text describing the new code.

## What already works, and what this adds

The **text** of the five model-backed kinds carries itself. `engine.carry_forward_globals` and
`carry_forward_from_index` copy `description` from the baseline's stored model, and the baseline's
model already holds the human's text because that is where an override writes it. Nothing here has
to repeat that.

What is missing is the **override rows**. Without them the new version does not know which of its
text is human-authored, so:

* undo has nothing to restore to (`REQ-API-04`);
* the cascade would happily regenerate over a human's wording (`REQ-CS-03`);
* and for `nodeLabel` and `behaviourDescription` — whose text lives nowhere but the override table
  (`REQ-AP-05`) — the correction would simply vanish.

## The `nodeLabel` gate, and why `source_hash` alone is not it

A node id is a **position**, not an identity. Identical source renumbers when the CFG builder
changes or when `cfgSimplification` merges nodes past its threshold, so "the source did not change"
does not mean `n7` is still the same node. A correction reused across that lands on a different
statement, silently.

So a node override carries only when the function's `source_hash` is unchanged **and** its
`slot_shape` still matches the target's graph (`REQ-ID-02`). This is the first consumer of that
column: it has been written and guarded since the schema landed, and nothing read it until now.

## Nothing is ever dropped

A slot that no longer resolves is carried **orphaned**, not deleted (`REQ-ID-03`). It is the user's
work and it is training data, and a rename may be reverted. `--full` has no baseline, so nothing is
carried at all — and `REQ-VR-03` requires that this must not delete anything either, because
`--full` is the standing remedy for several problems.
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from typing import Any, Dict, NamedTuple, Optional, Set

from sqlalchemy import insert, select

from review import slot

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from api.db.postgres import schema as s   # noqa: E402


class Carried(NamedTuple):
    carried: int
    orphaned: int
    #: (slot_kind, slot_key, why) for everything that did not carry — a reviewer whose
    #: correction stopped applying is owed a reason, not a silent disappearance.
    reasons: tuple = ()


class _Target:
    """What the new version contains, loaded once and only when asked.

    A version with no corrections must cost nothing, and most do: without the laziness this would
    load every hash, unit and flowchart of every generated version for no reason.
    """

    def __init__(self, conn, version_id: str):
        self._conn, self._v = conn, version_id
        self._hashes: Optional[Dict[str, str]] = None
        self._units: Optional[Set[str]] = None
        self._types: Optional[Dict[str, dict]] = None
        self._shapes: Optional[Dict[str, str]] = None
        self._behaviour: Optional[Set[str]] = None

    @property
    def hashes(self) -> Dict[str, str]:
        if self._hashes is None:
            from core import model_store
            self._hashes = model_store.load_hashes(self._conn, self._v)
        return self._hashes

    @property
    def units(self) -> Set[str]:
        """The version's units -- stored ones, and those its functions and globals belong to.

        The carry runs after Phase 1 and BEFORE Phase 2, and units are built in Phase 2: a new
        version has no `model_units` rows yet. Asking only the table orphaned every unit
        description ("that unit is not in the new version") on every generation. A unit exists
        when something in it does, and the entity keys say which unit that is.
        """
        if self._units is None:
            from review.cascade import unit_key_of
            stored = {r.unit_key for r in self._conn.execute(
                select(s.model_units.c.unit_key)
                .where(s.model_units.c.version_id == self._v)).fetchall()}
            self._units = stored | {u for u in map(unit_key_of, self.hashes) if u}
        return self._units

    @property
    def types(self) -> Dict[str, dict]:
        """`{type_or_macro_key: entry}` -- the data dictionary, as Phase 1 stored it.

        Not `hashes`: most data-dictionary entries have no source hash (19 of 91 on the sample),
        so asking `hashes` orphaned nearly every struct description.
        """
        if self._types is None:
            from core import model_store
            self._types = model_store.load_types(self._conn, self._v)
        return self._types

    @property
    def shapes(self) -> Dict[str, str]:
        """`{flowchart_id: cfg_shape}` for this version's stored flowcharts."""
        if self._shapes is None:
            self._shapes = {}
            for r in self._conn.execute(
                    select(s.version_output_files.c.rel_path,
                           s.version_output_files.c.content)
                    .where(s.version_output_files.c.version_id == self._v)).fetchall():
                if "/flowcharts/" not in r.rel_path or not r.rel_path.endswith(".json"):
                    continue
                if r.rel_path.rsplit("/", 1)[-1] == "_summary.json":
                    continue
                try:
                    entries = json.loads(r.content or "[]")
                except ValueError:
                    continue
                for e in entries if isinstance(entries, list) else ():
                    if not isinstance(e, dict) or not e.get("functionKey"):
                        continue
                    try:
                        self._shapes[e["functionKey"]] = slot.shape_of_cfg(e.get("cfg") or {})
                    except slot.SlotKeyError:
                        continue      # a flowchart with no nodes has no shape to match
        return self._shapes

    @property
    def behaviour_keys(self) -> Set[str]:
        if self._behaviour is None:
            from review import phase3_overrides as p3
            self._behaviour = set()
            for r in self._conn.execute(
                    select(s.version_output_files.c.rel_path,
                           s.version_output_files.c.content)
                    .where(s.version_output_files.c.version_id == self._v)).fetchall():
                if not r.rel_path.endswith("_behaviour_pngs.json"):
                    continue
                try:
                    payload = json.loads(r.content or "{}")
                except ValueError:
                    continue
                for _c, _u, row in p3.behaviour_rows((payload or {}).get("_docxRows")):
                    fid, caller = row.get("currentFunctionId"), row.get("externalCallerId")
                    if fid and caller:
                        try:
                            self._behaviour.add(slot.for_behaviour_row(fid, caller))
                        except slot.SlotKeyError:
                            continue
        return self._behaviour


def _definition(entry: Optional[dict]) -> Optional[dict]:
    """A data-dictionary entry minus what is not its definition: the description (the very text
    being carried -- the baseline's holds the human's words) and the location (a line added
    above a type moves it without changing it)."""
    if entry is None:
        return None
    return {k: v for k, v in entry.items() if k not in ("description", "location")}


def _still_applies(row, target: _Target, baseline: _Target) -> Optional[str]:
    """`None` if the correction still applies, else why it does not."""
    kind, key = row.slot_kind, row.slot_key

    if kind == slot.UNIT_DESCRIPTION:
        return None if key in target.units else "that unit is not in the new version"

    if kind == slot.BEHAVIOUR_DESCRIPTION:
        return (None if key in target.behaviour_keys
                else "that call no longer appears in the behaviour diagrams")

    if kind == slot.NODE_LABEL:
        try:
            parts = slot.parse(slot.NODE_LABEL, key)
        except slot.SlotKeyError:
            return "the slot key is malformed"
        fid = parts["entity_key"]
        if fid not in target.hashes:
            return "that function is not in the new version"
        if baseline.hashes.get(fid) != target.hashes.get(fid):
            # The code changed, so the labels describe statements that may no longer exist.
            # Fresh LLM text is the right answer here (REQ-VR-01).
            return "that function's code changed"
        # The target's flowchart normally does NOT exist yet: this runs in Phase 2 and Phase 3
        # is what produces it. Comparing against nothing and orphaning would mean a node override
        # could never survive a generation -- which is exactly what a two-version run showed.
        #
        # So compare against whichever graph is available, and say which:
        #   target present  -> the real answer (a re-run over an already-generated version)
        #   target absent   -> the BASELINE's graph, which is what is being carried FROM
        #
        # The baseline check is weaker on its own: a builder change between the two versions
        # renumbers the target while the baseline still matches. `phase3_overrides` closes that
        # by re-checking the shape against the CFG it is actually writing into, which is the last
        # moment before the text lands and the only place the target's real graph exists.
        current = target.shapes.get(fid) or baseline.shapes.get(fid)
        if not slot.shape_matches(row.slot_shape, current):
            return ("the flowchart was renumbered even though the code did not change, so the "
                    "correction can no longer be placed")
        return None

    # The remaining four are addressed by an entity key.
    try:
        entity = slot.parse(kind, key)["entity_key"]
    except slot.SlotKeyError:
        return "the slot key is malformed"

    if kind == slot.STRUCT_DESCRIPTION:
        # A data-dictionary entry: compared by its definition, since most have no source hash.
        current = target.types.get(entity)
        if current is None:
            return "that type is not in the new version"
        if _definition(baseline.types.get(entity)) != _definition(current):
            return "that type's definition changed"
        return None

    # A function or a global: a description, or a behaviour input/output name.
    if entity not in target.hashes:
        return "that entity is not in the new version"
    if baseline.hashes.get(entity) != target.hashes.get(entity):
        # REQ-VR-01, as for node labels above: the words were written for code that is not there
        # any more. The new version gets fresh LLM text for it, and the correction is kept but not
        # applied. Carrying it as live used to leave it claiming to be in force over text it did
        # not write -- and re-applying it after Phase 2 would put the old words on the new code.
        return "its code changed"
    return None


def carry_overrides(conn, baseline_version_id: str, target_version_id: str, *,
                    now: Optional[datetime.datetime] = None) -> Carried:
    """Copy the baseline's corrections onto the new version (`REQ-VR-01`).

    Everything is copied. A slot that no longer resolves is copied **orphaned** rather than left
    behind: it is the user's work and it is training data, a rename may be reverted, and a
    correction that silently disappears between two versions is indistinguishable from one that
    was never saved.

    Already-present rows on the target are left alone — a correction made directly against the new
    version is newer than anything the baseline can offer.
    """
    if not baseline_version_id or baseline_version_id == target_version_id:
        return Carried(0, 0, ())

    src = conn.execute(select(s.text_overrides)
                       .where(s.text_overrides.c.version_id == baseline_version_id)).fetchall()
    if not src:
        return Carried(0, 0, ())

    existing = {(r.slot_kind, r.slot_key) for r in conn.execute(
        select(s.text_overrides.c.slot_kind, s.text_overrides.c.slot_key)
        .where(s.text_overrides.c.version_id == target_version_id)).fetchall()}

    target = _Target(conn, target_version_id)
    baseline = _Target(conn, baseline_version_id)      # lazy: only what a row needs is read
    stamp = now or datetime.datetime.now(datetime.timezone.utc)

    carried = orphaned = 0
    reasons = []
    for row in src:
        if (row.slot_kind, row.slot_key) in existing:
            continue
        why = _still_applies(row, target, baseline)
        # An already-orphaned correction stays orphaned: whatever stopped resolving in the
        # baseline has not come back just because a new version was generated.
        is_orphan = bool(why) or bool(row.is_orphaned)
        conn.execute(insert(s.text_overrides).values(
            version_id=target_version_id, slot_kind=row.slot_kind, slot_key=row.slot_key,
            llm_text=row.llm_text, human_text=row.human_text, is_orphaned=is_orphan,
            updated_by=row.updated_by, updated_at=row.updated_at or stamp,
            llm_model=row.llm_model, llm_cache_version=row.llm_cache_version,
            llm_context=row.llm_context,
            # The shape IS carried, for node labels that still apply.
            #
            # An earlier version of this nulled it, reasoning that it describes the baseline's
            # graph and carrying it would let the next carry-forward check against a shape nobody
            # verified. That was wrong in a way a two-version run made obvious: nulling it means
            # the NEXT generation sees "no claim", and `shape_matches` refuses a missing claim --
            # so a node correction could survive exactly one version and then orphan itself.
            #
            # The shape is a claim about the graph the TEXT was written for, and that claim stays
            # true as the text travels. What validates it is `phase3_overrides`, against the CFG
            # actually being written.
            slot_shape=(row.slot_shape if row.slot_kind == slot.NODE_LABEL and not is_orphan
                        else None)))
        if is_orphan:
            orphaned += 1
            reasons.append((row.slot_kind, row.slot_key, why or "orphaned in the baseline"))
        else:
            carried += 1
    return Carried(carried, orphaned, tuple(reasons))


def apply_live_corrections(conn, version_id: str, model: Dict[str, Any]) -> Dict[str, int]:
    """Write this version's corrections that are in force back into `model`, which Phase 2 has
    just rebuilt. Returns `{artifact: count}` for what it changed.

    A correction lives in the model -- that is where a save writes it, and Phase 3 and the
    exporter read it from there. But Phase 2 rebuilds parts of the model from scratch, and they
    lost what the reviewer wrote:

      * `units` is built afresh and every unit description re-generated;
      * the data dictionary of a NEW version comes from its own parse, so its struct
        descriptions are generated again;
      * behaviour input/output names are recomputed for every function a run derives -- all of
        them on `reexport --from-phase 2`.

    So the text is put back last, through the same resolver a save writes through. Only
    corrections in force: an orphan is kept but never applied (`REQ-ID-03`), and `carry_overrides`
    has already orphaned whatever a new version changed underneath (`REQ-VR-01`). The LLM cache
    is not touched (`REQ-VR-02`).
    """
    from review import resolver
    rows = conn.execute(
        select(s.text_overrides.c.slot_kind, s.text_overrides.c.slot_key,
               s.text_overrides.c.human_text)
        .where(s.text_overrides.c.version_id == version_id,
               s.text_overrides.c.is_orphaned.is_(False),
               s.text_overrides.c.slot_kind.in_(resolver.MODEL_BACKED_KINDS))).fetchall()
    changed: Dict[str, int] = {}
    for r in rows:
        text = (r.human_text or "").strip()
        if not text:
            continue
        try:
            loc = resolver.locate(model, r.slot_kind, r.slot_key)
            if resolver.read_text(model, r.slot_kind, r.slot_key) == text:
                continue
        except (resolver.SlotError, slot.SlotKeyError):
            continue      # nothing here to write it into; whether it applies was judged already
        resolver.write_text(model, r.slot_kind, r.slot_key, text)
        changed[loc.artifact] = changed.get(loc.artifact, 0) + 1
    return changed


def overrides_for_config(conn, version_id: str) -> Dict[str, Dict]:
    """The corrections a Phase-3 run must apply, in the shape `phase3_overrides.from_config`
    reads (`REQ-AP-05`):

        {"nodeLabel":            {flowchart_id: {node_id: text}},
         "behaviourDescription": {slot_key: text}}

    Built here rather than in the caller so there is one place that knows the shape. The two kinds
    differ because a node label is addressed inside a flowchart and a behaviour description is
    addressed whole.

    **Orphaned rows are left out.** They describe something that is no longer there; applying one
    would put the right sentence on whatever now occupies that position.

    Filtered here AND again inside `labels_by_flowchart` / `behaviour_text_by_slot`, so no test can
    tell the two apart -- removing this `where` clause changes nothing observable. It stays because
    this is the query: not fetching rows that will be discarded is the point, and a future caller
    of this function for some other purpose should not receive orphans just because the helper it
    happened to use filtered them.

    The five model-backed kinds are absent on purpose — their text is in the model already, carried
    there by `engine.carry_forward_globals`, and Phase 3 derives from the model.
    """
    from review import phase3_overrides as p3

    rows = conn.execute(select(s.text_overrides)
                        .where(s.text_overrides.c.version_id == version_id,
                               s.text_overrides.c.is_orphaned.is_(False))).fetchall()
    return {p3.NODE_LABEL_KIND: p3.labels_by_flowchart(rows),
            p3.NODE_LABEL_SHAPES: p3.shapes_by_flowchart(rows),
            p3.BEHAVIOUR_KIND: p3.behaviour_text_by_slot(rows)}


def config_with_overrides(conn, version_id: str, config: Optional[Dict] = None) -> Dict:
    """`config` with this version's corrections attached, for a Phase-3 run.

    A copy: the run's config is shared, and attaching to it in place would leave a later run in the
    same process applying another version's corrections.
    """
    from review import phase3_overrides as p3
    out = dict(config or {})
    out[p3.CONFIG_KEY] = overrides_for_config(conn, version_id)
    return out
