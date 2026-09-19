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
from typing import Dict, NamedTuple, Optional, Set

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
        if self._units is None:
            self._units = {r.unit_key for r in self._conn.execute(
                select(s.model_units.c.unit_key)
                .where(s.model_units.c.version_id == self._v)).fetchall()}
        return self._units

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


def _still_applies(row, target: _Target, baseline_hashes: Dict[str, str]) -> Optional[str]:
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
        if baseline_hashes.get(fid) != target.hashes.get(fid):
            # The code changed, so the labels describe statements that may no longer exist.
            # Fresh LLM text is the right answer here (REQ-VR-01).
            return "that function's code changed"
        current = target.shapes.get(fid)
        if not slot.shape_matches(row.slot_shape, current):
            # Same source, different graph -- a builder change or cfgSimplification renumbering.
            # THIS is what source_hash alone would have missed, and it is why slot_shape exists.
            return ("the flowchart was renumbered even though the code did not change, so the "
                    "correction can no longer be placed")
        return None

    # The remaining four are addressed by an entity key.
    try:
        entity = slot.parse(kind, key)["entity_key"]
    except slot.SlotKeyError:
        return "the slot key is malformed"
    return None if entity in target.hashes else "that entity is not in the new version"


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

    from core import model_store
    baseline_hashes = model_store.load_hashes(conn, baseline_version_id)
    target = _Target(conn, target_version_id)
    stamp = now or datetime.datetime.now(datetime.timezone.utc)

    carried = orphaned = 0
    reasons = []
    for row in src:
        if (row.slot_kind, row.slot_key) in existing:
            continue
        why = _still_applies(row, target, baseline_hashes)
        # An already-orphaned correction stays orphaned: whatever stopped resolving in the
        # baseline has not come back just because a new version was generated.
        is_orphan = bool(why) or bool(row.is_orphaned)
        conn.execute(insert(s.text_overrides).values(
            version_id=target_version_id, slot_kind=row.slot_kind, slot_key=row.slot_key,
            llm_text=row.llm_text, human_text=row.human_text, is_orphaned=is_orphan,
            updated_by=row.updated_by, updated_at=row.updated_at or stamp,
            llm_model=row.llm_model, llm_cache_version=row.llm_cache_version,
            llm_context=row.llm_context,
            # The shape is NOT carried. It describes the graph the text was written against, and
            # that graph belongs to the baseline. Carrying it would let the next version's
            # carry-forward check a correction against a shape it never verified.
            slot_shape=None))
        if is_orphan:
            orphaned += 1
            reasons.append((row.slot_kind, row.slot_key, why or "orphaned in the baseline"))
        else:
            carried += 1
    return Carried(carried, orphaned, tuple(reasons))


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
