"""What can be edited in a version — the slots themselves, not just the corrections.

`list_overrides` answers "what has been corrected here?" and returns an empty list on a version
nobody has touched. That is correct and it is an overlay: the UI merges it onto a document it
already holds. But it leaves one question unanswered for anyone who does NOT already hold that
document — *what is there to correct, and what is its key?* Without an answer, a slot key has to be
dug out of stored view output by hand, and a key is not something a caller may invent
(`REQ-ID-01`).

This is the other half of `REQ-API-01`: the slots of a version, with their current text and whether
each is overridden.

## The rule that keeps it honest

**The text shown here is read through `resolver`, the same way `apply_override` writes it.** Not
from the document, not from a view's output, not from whichever field looks right: a listing that
read `comment` while a save wrote `description` would show one sentence and replace a different
one, and both would look correct in isolation. Reading through the resolver makes that
disagreement impossible rather than unlikely.

## Volume

A version holds roughly 57,000 slots and ~42,000 of them are flowchart node labels, so `nodeLabel`
is listed **per flowchart** rather than per node — one row per function, with the token `R7` takes.
Everything else is paginated, and may be narrowed by unit or component.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, NamedTuple, Optional

from sqlalchemy import select

from review import phase3_overrides as p3, resolver, slot
from api.db.postgres import schema as s


class Page(NamedTuple):
    """One page of slots, and how many there are in total before paging."""
    items: List[Dict[str, Any]]
    total: int


class NotScoped(Exception):
    """A unit/component filter was given for a kind that has no such scoping."""
    status = 400


#: Kinds whose entity key starts `Component|Unit|`, so unit and component filters apply.
_SCOPED_BY_KEY = (slot.DESCRIPTION, slot.BEHAVIOUR_INPUT_NAME, slot.BEHAVIOUR_OUTPUT_NAME,
                  slot.UNIT_DESCRIPTION)


def _scope_of(entity_key: str):
    """`(component, unit)` from an entity key, or `(None, None)`.

    Function and global entries carry NO `unit`/`component` fields of their own — the scope is in
    the key, which is why this reads it from there rather than from the entry.
    """
    parts = (entity_key or "").split("|")
    if len(parts) >= 2:
        return parts[0] or None, parts[1] or None
    return None, None


def _overridden(conn, version_id: str, slot_kind: str) -> Dict[str, Any]:
    """`{slot_key: row}` for this kind — one query, not one per slot."""
    rows = conn.execute(
        select(s.text_overrides).where(s.text_overrides.c.version_id == version_id,
                                       s.text_overrides.c.slot_kind == slot_kind)).fetchall()
    return {r.slot_key: r for r in rows}


def _state(row, in_force: str) -> Dict[str, Any]:
    """The four facts about a slot's correction, and the text a reader actually sees.

    `text` is **what is in force** -- read from where the document reads it, never from the
    override row. For a live correction the two agree, because the save wrote the human text into
    the model (or the stored view row). For an ORPHAN they do not: it is kept (`REQ-ID-03`) but
    never applied, so the document carries the model's text and the row carries words written
    for code that has since changed.

    An earlier version took `text` from the row whenever one existed, and so showed a reviewer
    their stale correction as the current wording of a function whose document said something
    else entirely. `humanText` is returned separately so an orphan's work stays visible -- as
    what it is, not as what is printed.

    `isOverridden` means a correction is IN FORCE. An orphan is not one.
    """
    orphaned = bool(row is not None and row.is_orphaned)
    return {
        "text": in_force,
        "llmText": row.llm_text if row is not None else None,
        "humanText": row.human_text if row is not None else None,
        "isOverridden": row is not None and not orphaned,
        "isOrphaned": orphaned,
    }


def _page(items: List[Dict[str, Any]], limit: int, offset: int) -> Page:
    total = len(items)
    lo = max(0, int(offset))
    hi = lo + max(1, min(int(limit), 1000))
    return Page(items[lo:hi], total)


# ---------------------------------------------------------------------------
# the five model-backed kinds
# ---------------------------------------------------------------------------
def _model_backed(conn, version_id, kind, models, unit, component, limit, offset) -> Page:
    artifacts, _field = resolver._HOMES[kind]
    done = _overridden(conn, version_id, kind)
    items: List[Dict[str, Any]] = []

    for artifact in artifacts:
        for entity_key, entry in sorted((models.artifact(artifact) or {}).items()):
            if not isinstance(entry, dict):
                continue
            comp, un = _scope_of(entity_key)
            if unit and un != unit:
                continue
            if component and comp != component:
                continue
            key = (slot.for_unit(entity_key) if kind == slot.UNIT_DESCRIPTION
                   else slot.for_entity(kind, entity_key))
            try:
                text = resolver.read_text(models.as_model(), kind, key)
            except (resolver.SlotError, slot.SlotKeyError):
                continue          # not addressable in this version; not listable either
            row = done.get(key)
            items.append({
                "slotKind": kind,
                "slotKey": key,
                "label": entry.get("name") or entry.get("qualifiedName") or entity_key,
                "component": comp,
                "unit": un,
                "artifact": artifact,
                **_state(row, text),
            })
    return _page(items, limit, offset)


def _structs(conn, version_id, models, limit, offset) -> Page:
    """`structDescription` is keyed by type name and has no unit or component at all."""
    kind = slot.STRUCT_DESCRIPTION
    done = _overridden(conn, version_id, kind)
    items = []
    for type_name, entry in sorted((models.artifact("dataDictionary") or {}).items()):
        if not isinstance(entry, dict):
            continue
        key = slot.for_entity(kind, type_name)
        try:
            text = resolver.read_text(models.as_model(), kind, key)
        except (resolver.SlotError, slot.SlotKeyError):
            continue
        row = done.get(key)
        items.append({
            "slotKind": kind, "slotKey": key, "label": type_name,
            "component": None, "unit": None, "artifact": "dataDictionary",
            "kindOfType": entry.get("kind"),
            **_state(row, text),
        })
    return _page(items, limit, offset)


# ---------------------------------------------------------------------------
# the two Phase-3 kinds
# ---------------------------------------------------------------------------
def _flowcharts(conn, version_id, unit, component, limit, offset) -> Page:
    """`nodeLabel`, listed PER FLOWCHART.

    A version has ~42,000 node labels; one row each would be hundreds of pages of something
    nobody reads linearly. A flowchart is one function's graph, so this lists the functions that
    have one — with the token `R7` takes, which returns that flowchart's nodes.
    """
    done = _overridden(conn, version_id, slot.NODE_LABEL)
    per_flowchart: Dict[str, int] = {}
    for key, row in done.items():
        if row.is_orphaned:
            continue
        try:
            fid = slot.parse(slot.NODE_LABEL, key)["entity_key"]
        except slot.SlotKeyError:
            continue
        per_flowchart[fid] = per_flowchart.get(fid, 0) + 1

    rows = conn.execute(
        select(s.version_output_files.c.rel_path, s.version_output_files.c.content)
        .where(s.version_output_files.c.version_id == version_id)).fetchall()

    items = []
    for r in rows:
        if "/flowcharts/" not in r.rel_path or not r.rel_path.endswith(".json"):
            continue
        if r.rel_path.endswith("_summary.json"):
            continue
        try:
            entries = json.loads(r.content or "[]")
        except ValueError:
            continue
        for e in entries if isinstance(entries, list) else ():
            fid = (e or {}).get("functionKey")
            if not fid:
                continue
            comp, un = _scope_of(fid)
            if unit and un != unit:
                continue
            if component and comp != component:
                continue
            nodes = ((e.get("cfg") or {}).get("nodes") or [])
            items.append({
                "slotKind": slot.NODE_LABEL,
                "flowchartId": fid,
                "flowchartToken": slot.encode(fid),
                "functionName": e.get("name"),
                "component": comp,
                "unit": un,
                "nodeCount": len(nodes),
                "overriddenCount": per_flowchart.get(fid, 0),
            })
    items.sort(key=lambda i: (i["component"] or "", i["unit"] or "", i["flowchartId"]))
    return _page(items, limit, offset)


def _behaviour_rows(conn, version_id, unit, component, limit, offset) -> Page:
    """`behaviourDescription`, one row per call arrow.

    Read from the same `_behaviour_pngs.json` output `rerender.find_behaviour_row` writes back
    into, and addressed by the same two entity keys — never by the `externalUnitFunction` display
    label, which two different callers can share (`REQ-ID-01`).
    """
    kind = slot.BEHAVIOUR_DESCRIPTION
    done = _overridden(conn, version_id, kind)
    rows = conn.execute(
        select(s.version_output_files.c.rel_path, s.version_output_files.c.content)
        .where(s.version_output_files.c.version_id == version_id)).fetchall()

    items = []
    for r in rows:
        if not r.rel_path.endswith("_behaviour_pngs.json"):
            continue
        try:
            payload = json.loads(r.content or "{}")
        except ValueError:
            continue
        for comp, un, row in p3.behaviour_rows((payload or {}).get("_docxRows")):
            fid = row.get("currentFunctionId")
            caller = row.get("externalCallerId")
            if not (fid and caller):
                # Written before `externalCallerId` existed: it cannot be addressed
                # unambiguously, so it is not offered for editing either.
                continue
            if unit and un != unit:
                continue
            if component and comp != component:
                continue
            key = slot.for_behaviour_row(fid, caller)
            ov = done.get(key)
            # `behaviorDescription` -- the field the behaviour view writes, the DOCX exporter
            # reads (docx_exporter: row.get("behaviorDescription")) and R6 patches. An earlier
            # version read `behaviorDescriptionList`, which is only the exporter's PARAMETER name;
            # no row has ever carried it, so every behaviour row listed with no bullets at all.
            bullets = row.get("behaviorDescription") or []
            state = _state(ov, p3.join_bullets(bullets))
            items.append({
                "slotKind": kind,
                "slotKey": key,
                "functionId": fid,
                "externalCallerId": caller,
                "label": row.get("externalUnitFunction"),
                "component": comp,
                "unit": un,
                # What is in force -- the stored row, which R6 patches for a live correction and
                # which an orphan never reached.
                "bullets": list(bullets),
                "llmText": state["llmText"],
                "humanText": state["humanText"],
                "isOverridden": state["isOverridden"],
                "isOrphaned": state["isOrphaned"],
            })
    items.sort(key=lambda i: (i["component"] or "", i["unit"] or "", i["slotKey"]))
    return _page(items, limit, offset)


# ---------------------------------------------------------------------------
# the one entry point
# ---------------------------------------------------------------------------
def list_slots(conn, version_id: str, slot_kind: str, *, models=None,
               unit: Optional[str] = None, component: Optional[str] = None,
               limit: int = 200, offset: int = 0) -> Page:
    """The editable slots of one kind in a version, with their text and override state.

    `models` is a `ModelAccess`; the five model-backed kinds need it and the two Phase-3 kinds do
    not, so it is only built when it is used — an API process constructing a repository for a
    flowchart listing would be paying for a model read nobody asked for.
    """
    if slot_kind not in slot.ALL_KINDS:
        raise slot.SlotKeyError(
            "unknown slot kind %r; expected one of %s" % (slot_kind, ", ".join(slot.ALL_KINDS)))

    if (unit or component) and slot_kind == slot.STRUCT_DESCRIPTION:
        # Refused rather than ignored. A filter that silently does nothing is worse than one
        # that is rejected: the caller reads the unfiltered result as the filtered one.
        raise NotScoped("structDescription is not scoped by unit or component — "
                        "a data-dictionary type belongs to the project, not to a unit")

    if slot_kind == slot.NODE_LABEL:
        return _flowcharts(conn, version_id, unit, component, limit, offset)
    if slot_kind == slot.BEHAVIOUR_DESCRIPTION:
        return _behaviour_rows(conn, version_id, unit, component, limit, offset)
    if slot_kind == slot.STRUCT_DESCRIPTION:
        return _structs(conn, version_id, models, limit, offset)
    return _model_backed(conn, version_id, slot_kind, models, unit, component, limit, offset)
