"""Corrections for text that Phase 3 produces, and where it sits in Phase 3's output.

`REQ-AP-05`. Five slot kinds are model fields and are handled by `resolver` — an override updates
the model and the view is re-derived. Two are not:

| kind | made by | lands in |
|---|---|---|
| `nodeLabel` | the flowchart engine | `cfg.nodes[].label`, in the unit's flowchart JSON |
| `behaviourDescription` | `MermaidBuilder`, while building arrows | `_docxRows[…][].behaviorDescription` |

Both are produced *during* Phase 3, so there is no model field for a correction to update. Writing
one into the view's output file does not work either: the next run of Phase 3 rebuilds that file
from the CFG, asks the LLM for labels again, and the correction is gone with no error.

So for these two, **the override table is the source and the correction is an input to Phase 3.**
Whenever Phase 3 runs — full, incremental, any group — it is handed the corrections and produces
corrected output the first time. Regenerating therefore cannot lose a correction, however often it
happens.

## Why this module exists at all

The failure it guards against is a kind that is in neither table: it would save fine, report
success, and never reach the document. `covered_kinds()` plus the test over `slot.ALL_KINDS` makes
that impossible to add by accident — the same coverage shape as `derive.views_for`.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, NamedTuple, Tuple

from review import slot


class Target(NamedTuple):
    """Where a kind's text lives in Phase-3 output."""
    view: str            #: the VIEW_REGISTRY name that produces it
    where: str           #: human-readable path, for messages and docs
    renders_image: bool  #: whether correcting it changes a picture


#: The two kinds Phase 3 produces. Anything here must NOT be in `resolver._HOMES`.
APPLIED_AT_DERIVE: Dict[str, Target] = {
    slot.NODE_LABEL: Target(
        view="flowcharts",
        where="cfg.nodes[].label",
        # The label IS the picture, so a correction means rebuilding the DOT and re-rendering.
        renders_image=True),
    slot.BEHAVIOUR_DESCRIPTION: Target(
        view="behaviourDiagram",
        where="_docxRows[].behaviorDescription",
        # It is NOT in the picture. `MermaidBuilder` labels each arrow `<callee>()` -- the
        # function's name -- and appends the description to a separate list. Only the JSON row
        # changes, so queueing a render for it would be wasted work (REQ-IM-01).
        renders_image=False),
}


def covered_kinds() -> Tuple[str, ...]:
    """Every kind this module applies. The coverage test reads this."""
    return tuple(APPLIED_AT_DERIVE)


def target_for(slot_kind: str) -> Target:
    """Where `slot_kind` lives in Phase-3 output. Raises for a kind that is not one of these."""
    try:
        return APPLIED_AT_DERIVE[slot_kind]
    except KeyError:
        raise slot.SlotKeyError(
            "%s is not applied at derive time; it is a model field (see review.resolver) or it "
            "is not an editable kind at all" % slot_kind) from None


def renders_image(slot_kind: str) -> bool:
    return target_for(slot_kind).renders_image


# ---------------------------------------------------------------------------
# labels for one flowchart
# ---------------------------------------------------------------------------
def labels_by_flowchart(rows: Iterable[Any]) -> Dict[str, Dict[str, str]]:
    """`text_overrides` rows -> `{flowchart_id: {node_id: human_text}}`.

    `rows` is anything with `slot_kind`, `slot_key` and `human_text` — the DB rows as read, no
    intermediate shape to keep in step with the table.

    Orphaned rows are skipped: the slot stopped resolving, so the text describes something that is
    no longer there. It is kept in the table (`REQ-ID-03`) but must not be applied.

    A key that does not parse is skipped rather than raised on. This runs inside Phase 3, and one
    malformed row must not take down a generation that has already paid for the parse and the LLM.
    """
    out: Dict[str, Dict[str, str]] = {}
    for r in rows or ():
        if getattr(r, "slot_kind", None) != slot.NODE_LABEL:
            continue
        if getattr(r, "is_orphaned", False):
            continue
        text = (getattr(r, "human_text", "") or "").strip()
        if not text:
            continue
        try:
            parts = slot.parse(slot.NODE_LABEL, getattr(r, "slot_key", ""))
        except slot.SlotKeyError:
            continue
        out.setdefault(parts["entity_key"], {})[parts["node_id"]] = text
    return out


def apply_to_cfg(cfg: Mapping[str, Any], labels: Mapping[str, str]) -> int:
    """Put `{node_id: text}` into a stored CFG dict, in place. Returns how many landed.

    Only nodes that exist are written. A correction naming a node the graph no longer has is
    dropped here rather than appended, because a CFG grown an extra node would otherwise render a
    node with no edges — `REQ-ID-02`'s shape check is what catches this case properly, upstream;
    this is the last line of defence, not the first.
    """
    nodes = (cfg or {}).get("nodes") or []
    applied = 0
    for node in nodes:
        if not isinstance(node, dict):
            continue
        text = labels.get(str(node.get("id")))
        if text:
            node["label"] = text
            applied += 1
    return applied


def apply_to_flowchart_json(entries: Iterable[Any], by_flowchart: Mapping[str, Mapping[str, str]]
                            ) -> List[str]:
    """Apply corrections across one unit's flowchart JSON. Returns the flowchart ids changed.

    A unit's file is a list of per-function entries; `functionKey` is the flowchart id
    (`REQ-ID-04`). Entries with no corrections are left exactly as they are, so a unit where
    nobody edited anything is rewritten byte-identically.
    """
    changed = []
    for entry in entries or ():
        if not isinstance(entry, dict):
            continue
        fid = entry.get("functionKey")
        labels = by_flowchart.get(fid) if fid else None
        if not labels:
            continue
        if apply_to_cfg(entry.get("cfg") or {}, labels):
            changed.append(fid)
    return changed
