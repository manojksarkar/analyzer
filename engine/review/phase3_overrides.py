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
# how corrections reach a view
# ---------------------------------------------------------------------------
#: The config key Phase-3 views read their corrections from, keyed BY KIND:
#:
#:     {"nodeLabel":            {flowchart_id: {node_id: text}},
#:      "behaviourDescription": {slot_key: text}}
#:
#: Same convention as `_analyzerAllowedComponents`, so a view stays a pure function of the model
#: plus config and never reaches into a database.
CONFIG_KEY = "_analyzerTextOverrides"

#: Re-exported so a view names the kind through this module rather than spelling the
#: string itself -- one place to rename, one place to get it wrong.
NODE_LABEL_KIND = slot.NODE_LABEL
BEHAVIOUR_KIND = slot.BEHAVIOUR_DESCRIPTION

#: The shapes travel beside the labels, under their own key, because they are a different
#: fact about the same slots -- what graph the text was written for, not what the text is.
NODE_LABEL_SHAPES = "nodeLabelShapes"


def from_config(config, slot_kind: str):
    """This run's corrections for one kind, or `{}`.

    One definition of the shape, read by both views. Two views each destructuring the config
    their own way is how they end up disagreeing about it.
    """
    target_for(slot_kind)                       # refuse a kind that is not applied at derive time
    section = (config or {}).get(CONFIG_KEY) or {}
    value = section.get(slot_kind) if isinstance(section, dict) else None
    return value if isinstance(value, dict) else {}


def shapes_from_config(config) -> Dict[str, str]:
    """The `{flowchart_id: slot_shape}` claims this run must check before applying a label."""
    section = (config or {}).get(CONFIG_KEY) or {}
    value = section.get(NODE_LABEL_SHAPES) if isinstance(section, dict) else None
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------------------
# labels for one flowchart
# ---------------------------------------------------------------------------
def shapes_by_flowchart(rows: Iterable[Any]) -> Dict[str, str]:
    """`{flowchart_id: slot_shape}` from `text_overrides` rows that carry one.

    Read alongside `labels_by_flowchart` so the application can check REQ-ID-02 against the graph
    it is writing into. Every override on one flowchart carries the same shape, so the last one
    read wins and they agree by construction.
    """
    out: Dict[str, str] = {}
    for r in rows or ():
        if getattr(r, "slot_kind", None) != slot.NODE_LABEL:
            continue
        if getattr(r, "is_orphaned", False) or not getattr(r, "slot_shape", None):
            continue
        try:
            parts = slot.parse(slot.NODE_LABEL, getattr(r, "slot_key", ""))
        except slot.SlotKeyError:
            continue
        out[parts["entity_key"]] = r.slot_shape
    return out


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


def apply_to_flowchart_json(entries: Iterable[Any], by_flowchart: Mapping[str, Mapping[str, str]],
                            shapes: Optional[Mapping[str, str]] = None) -> List[str]:
    """Apply corrections across one unit's flowchart JSON. Returns the flowchart ids changed.

    A unit's file is a list of per-function entries; `functionKey` is the flowchart id
    (`REQ-ID-04`). Entries with no corrections are left exactly as they are, so a unit where
    nobody edited anything is rewritten byte-identically.

    `shapes` is `{flowchart_id: slot_shape}` from the override rows. **This is where REQ-ID-02 is
    really enforced**: it is the last moment before the text lands and the only point at which the
    graph being written actually exists. The carry-forward cannot do it -- it runs in Phase 2,
    before Phase 3 has produced the graph -- so it checks what it can and leaves the decisive
    check here.

    A correction whose shape disagrees with the CFG in hand is DROPPED, not applied to whatever
    now occupies that node id.
    """
    changed = []
    for entry in entries or ():
        if not isinstance(entry, dict):
            continue
        fid = entry.get("functionKey")
        labels = by_flowchart.get(fid) if fid else None
        if not labels:
            continue
        cfg = entry.get("cfg") or {}
        claimed = (shapes or {}).get(fid)
        if claimed:
            try:
                if not slot.shape_matches(claimed, slot.shape_of_cfg(cfg)):
                    continue      # renumbered since the correction was written -- REQ-ID-02
            except slot.SlotKeyError:
                continue          # a flowchart with no nodes has no shape to agree with
        if apply_to_cfg(cfg, labels):
            changed.append(fid)
    return changed


# ---------------------------------------------------------------------------
# behaviour rows
# ---------------------------------------------------------------------------
#: The bullets of one behaviour row are stored as ONE text, joined by this.
#:
#: Not JSON. `human_text` stays genuinely text for all seven kinds, so REQ-ST-06's emptiness
#: check is one rule, the REQ-TD-01 training pair stays sentence-against-sentence, and the
#: history is readable -- the same reasons a flowchart is stored per label and not as a blob.
#: Safe because `llm_call_description._one_line` collapses each bullet onto one line at the
#: point it is generated, so a bullet cannot contain the separator.
BULLET_SEP = chr(10)      # newline, written this way so no editor can eat it


def join_bullets(bullets) -> str:
    """A behaviour row's list of bullets -> the single text stored in `human_text`."""
    return BULLET_SEP.join(" ".join(str(b).split()) for b in (bullets or []) if str(b).strip())


def split_bullets(text: str):
    """The inverse. Blank lines are dropped: they carry no bullet and would render as an empty
    row in the DOCX table."""
    return [line.strip() for line in (text or "").split(BULLET_SEP) if line.strip()]


def behaviour_rows(docx_rows):
    """Walk `_docxRows` yielding `(component, unit, row)`.

    `_docxRows` is `{component: {unit: [row, ...]}}`. Written once here so nothing else has to
    know that shape.
    """
    for component, units in (docx_rows or {}).items():
        if not isinstance(units, dict):
            continue
        for unit, rows in units.items():
            for row in rows or []:
                if isinstance(row, dict):
                    yield component, unit, row


def behaviour_text_by_slot(rows) -> Dict[str, str]:
    """`text_overrides` rows -> `{slot_key: human_text}` for behaviour descriptions.

    Orphaned and malformed rows are skipped for the same reasons as `labels_by_flowchart`.
    """
    out: Dict[str, str] = {}
    for r in rows or ():
        if getattr(r, "slot_kind", None) != slot.BEHAVIOUR_DESCRIPTION:
            continue
        if getattr(r, "is_orphaned", False):
            continue
        text = (getattr(r, "human_text", "") or "").strip()
        key = getattr(r, "slot_key", "")
        if text and slot.is_valid(slot.BEHAVIOUR_DESCRIPTION, key):
            out[key] = text
    return out


def apply_to_docx_rows(docx_rows, by_slot: Mapping[str, str]) -> List[str]:
    """Put corrected behaviour descriptions into `_docxRows`, in place. Returns the slot keys
    applied.

    A row is addressed by `(currentFunctionId, externalCallerId)` -- both entity keys. A row
    with no `externalCallerId` is skipped rather than matched on its display label: the label is
    lossy and two rows can share one, so falling back to it would apply a correction to the wrong
    caller, silently. Better a correction that does not appear than one that appears in the wrong
    place.
    """
    done: List[str] = []
    if not by_slot:
        return done
    for _component, _unit, row in behaviour_rows(docx_rows):
        fid, caller = row.get("currentFunctionId"), row.get("externalCallerId")
        if not (fid and caller):
            continue
        try:
            key = slot.for_behaviour_row(fid, caller)
        except slot.SlotKeyError:
            continue
        text = by_slot.get(key)
        if not text:
            continue
        row["behaviorDescription"] = split_bullets(text)
        done.append(key)
    return done
