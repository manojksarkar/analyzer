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
is listed **per flowchart** rather than per node — one row per function, with the `flowchartId`
`R7` and `R8` take.
Everything else is paginated, and may be narrowed by unit or component.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, NamedTuple, Optional, Set

from sqlalchemy import or_, select

from review import phase3_overrides as p3, resolver, slot
from review.export_guard import component_id
from api.db.postgres import schema as s


class Page(NamedTuple):
    """One page of slots, and how many there are in total before paging."""
    items: List[Dict[str, Any]]
    total: int


class NotScoped(Exception):
    """A unit/component filter was given for a kind that has no such scoping."""
    status = 400


#: Kinds whose entity key starts `Component|Unit|`, so unit and component filters apply.
_SCOPED_BY_KEY = (slot.DESCRIPTION, slot.INPUT_NAME, slot.OUTPUT_NAME, slot.UNIT_DESCRIPTION)


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


def slot_view(slot_kind: str, slot_key: str, text: Optional[str], row) -> Dict[str, Any]:
    """One slot, in the shape every review response gives it (`REQ-API-09`).

    Every route that returns a slot's text returns this -- R1, R2, R3, R4, R6, R11, and each node
    of R7 and R8 -- so a client reads one set of fields whatever the kind or the route. Before it,
    R3 had `previousText` and no `isOverridden`, R7 had `text` and R2 did not, R8 returned no text
    at all, and `llmText` was null until a first correction in one route and filled in another.

    * `text` -- **what the document prints now**, read from where the document reads it, never
      from the override row (`texts_in_force`). For a live correction the two agree, because the
      save wrote the human text into the model or the stored view row. For an ORPHAN they do not:
      it is kept (`REQ-ID-03`) but never applied, so the document carries the current LLM text.
      An earlier version took `text` from the row whenever one existed, and so showed a reviewer
      their stale correction as the wording of a function whose document said something else.
      `""` when the slot is no longer in this version and only an orphan's record remains.
    * `llmText` -- the LLM's wording for this slot: the original a correction in force replaced,
      else the same as `text` (which is then LLM text). `None` only when the LLM wrote nothing --
      the slot was empty before its first correction, which is also why undo can be refused.
    * `humanText` -- the reviewer's words, `None` when there is no correction. An orphan keeps
      its words here, visible as what they are rather than as what is printed.
    * `isOverridden` -- a correction is IN FORCE: the document prints `humanText`. An orphan is
      not one.
    * `isOrphaned` -- a correction exists, written for code that has since changed; not printed.
    * `canUndo` -- an undo would change the text: a correction in force, an original to go back
      to, and the two differ. Decided here so no client carries the rule.
    * `updatedBy`, `updatedAt` -- the last save of the correction, `None` when there is none.

    Plus the slot's address where its key has parts: a node label's `flowchartId` and `nodeId`, a
    behaviour row's `functionId`, `externalCallerId` and `bullets` (the lines of `text`).
    """
    text = text or ""
    orphaned = bool(row is not None and row.is_orphaned)
    in_force = row is not None and not orphaned
    llm = (row.llm_text if in_force else text) or ""
    llm = llm if llm.strip() else None
    human = row.human_text if row is not None else None
    out = {
        "slotKind": slot_kind,
        "slotKey": slot_key,
        "text": text,
        "llmText": llm,
        "humanText": human,
        "isOverridden": in_force,
        "isOrphaned": orphaned,
        "canUndo": bool(in_force and llm is not None
                        and (human or "").strip() != llm.strip()),
        "updatedBy": row.updated_by if row is not None else None,
        "updatedAt": (row.updated_at.isoformat()
                      if row is not None and row.updated_at else None),
    }
    out.update(_address(slot_kind, slot_key, text))
    return out


def _address(slot_kind: str, slot_key: str, text: str) -> Dict[str, Any]:
    """The parts of a composite key, so a client never takes a key apart (`REQ-ID-01`)."""
    try:
        if slot_kind == slot.NODE_LABEL:
            parts = slot.parse(slot_kind, slot_key)
            return {"flowchartId": parts["entity_key"], "nodeId": parts["node_id"]}
        if slot_kind == slot.BEHAVIOUR_DESCRIPTION:
            parts = slot.parse(slot_kind, slot_key)
            return {"functionId": parts["function_id"],
                    "externalCallerId": parts["external_caller_id"],
                    "bullets": p3.split_bullets(text)}
    except slot.SlotKeyError:
        pass
    return {}


def texts_in_force(conn, version_id: str, pairs, models=None) -> Dict[tuple, Optional[str]]:
    """`{(slot_kind, slot_key): text}` -- what the document prints for each slot, or `None` for
    a slot that is not in this version.

    Read from where the document reads it: the model for the five model-backed kinds (through
    `resolver`, the way a save writes it), the stored flowchart for a node label, the stored
    behaviour manifest for a behaviour row. `models` is a `ModelAccess`, or None when no
    model-backed kind is asked for; only the artifacts the asked kinds live in are read.
    """
    from review import rerender

    pairs = list(dict.fromkeys(pairs or ()))
    out: Dict[tuple, Optional[str]] = {}
    backed = [(k, key) for k, key in pairs if k in resolver.MODEL_BACKED_KINDS]
    if backed:
        needed = {a for k, _key in backed for a in resolver._HOMES[k][0]}
        model = {a: models.artifact(a) for a in needed} if models is not None else {}
        for pair in backed:
            try:
                out[pair] = resolver.read_text(model, *pair)
            except (resolver.SlotError, slot.SlotKeyError):
                out[pair] = None

    wanted: Dict[str, Set[str]] = {}
    for k, key in pairs:
        if k == slot.NODE_LABEL:
            try:
                parts = slot.parse(k, key)
            except slot.SlotKeyError:
                out[(k, key)] = None
                continue
            wanted.setdefault(parts["entity_key"], set()).add(parts["node_id"])
    if wanted:
        labels = _stored_labels(conn, version_id, wanted)
        for fid, nodes in wanted.items():
            for node in nodes:
                out[(slot.NODE_LABEL, slot.for_node(fid, node))] = \
                    (labels.get(fid) or {}).get(node)

    rows = [(k, key) for k, key in pairs if k == slot.BEHAVIOUR_DESCRIPTION]
    if rows:
        stored: Dict[str, str] = {}
        for r in rerender.output_rows(conn, version_id, rerender.BEHAVIOUR_MANIFEST):
            try:
                payload = json.loads(r.content or "{}")
            except ValueError:
                continue
            for _c, _u, row in p3.behaviour_rows((payload or {}).get("_docxRows")):
                fid, caller = row.get("currentFunctionId"), row.get("externalCallerId")
                if fid and caller:
                    try:
                        key = slot.for_behaviour_row(fid, caller)
                    except slot.SlotKeyError:
                        continue
                    stored.setdefault(key, p3.join_bullets(row.get("behaviorDescription")))
        for pair in rows:
            out[pair] = stored.get(pair[1])

    for pair in pairs:
        out.setdefault(pair, None)
    return out


def _stored_labels(conn, version_id: str, wanted) -> Dict[str, Dict[str, str]]:
    """`{flowchart_id: {node_id: label}}` for the flowcharts in `wanted`, from the stored rows.

    A few flowcharts are looked up one by one (`find_flowchart_row` asks for the rows that mention
    each); more are found in one pass over the version's flowchart rows, parsing only the rows
    that mention one of them.
    """
    from review import rerender

    def _labels(entry):
        return {str(n.get("id")): str(n.get("label") or "")
                for n in ((entry or {}).get("cfg") or {}).get("nodes") or []
                if isinstance(n, dict) and n.get("id")}

    def _entry(content, fid):
        try:
            entries = json.loads(content or "[]")
        except ValueError:
            return None
        if not isinstance(entries, list):
            return None
        return next((e for e in entries
                     if isinstance(e, dict) and e.get("functionKey") == fid), None)

    out: Dict[str, Dict[str, str]] = {}
    if len(wanted) <= 3:
        for fid in wanted:
            found = rerender.find_flowchart_row(conn, version_id, fid)
            if found:
                out[fid] = _labels(_entry(found[2], fid))
        return out
    spelled = {fid: json.dumps(fid)[1:-1] for fid in wanted}
    for r in rerender.output_rows(conn, version_id, rerender.FLOWCHARTS):
        content = r.content or ""
        for fid in [f for f, sp in spelled.items() if f not in out and sp in content]:
            entry = _entry(content, fid)
            if entry is not None:
                out[fid] = _labels(entry)
    for fid in set(wanted) - set(out):
        found = rerender.find_flowchart_row(conn, version_id, fid)     # spelled otherwise
        if found:
            out[fid] = _labels(_entry(found[2], fid))
    return out


def slot_views(conn, version_id: str, pairs, models=None, *, rows=None) -> List[Any]:
    """`slot_view` for each `(slot_kind, slot_key)`, in order -- `None` for a slot that is
    neither in this version nor corrected in it.

    `rows` are override rows already in hand (`{(kind, key): row}`); the rest are read. A slot
    that left the version but still has a correction -- an orphan, typically -- is returned with
    `text` `""`: its record is the reviewer's work, and is shown rather than hidden.
    """
    from review.override_service import overrides_by_key

    pairs = list(pairs or ())
    have = dict(rows or {})
    by_kind: Dict[str, List[str]] = {}
    for k, key in pairs:
        if (k, key) not in have:
            by_kind.setdefault(k, []).append(key)
    for k, keys in by_kind.items():
        for key, r in overrides_by_key(conn, version_id, k, keys).items():
            have[(k, key)] = r
    texts = texts_in_force(conn, version_id, pairs, models)
    out = []
    for pair in pairs:
        row, text = have.get(pair), texts.get(pair)
        out.append(None if row is None and text is None
                   else slot_view(pair[0], pair[1], text, row))
    return out


class _Placement(NamedTuple):
    """Where this version's SWE.3 documents show a text, read from its stored views."""
    listed: Dict[str, List[str]]        # entity key -> unit keys whose interface table lists it
    in_behaviour: Dict[str, List[str]]  # function id -> unit keys whose Dynamic Behaviour rows show it
    drawn_units: Set[str]               # unit keys whose functions have a stored flowchart
    documented_units: Set[str]          # unit keys with a section in a document


def _placement(conn, version_id: str) -> _Placement:
    """Read where each text is shown, so a row can say so (`shownIn`).

    A slot exists for every function and global in the model, but a document shows only some of
    them: a function gets an interface row -- and with it a flowchart table and its behaviour
    names -- only when another unit in the parsed scope calls it (develop 470d15c), so in a run
    scoped to one group most functions are shown nowhere. A correction to one of those saves and
    is never seen; without this a reviewer could not tell it from one that is.

    Read from the stored view output, which IS what the documents print, rather than recomputed
    from the model. Flowcharts are matched to units by their file NAME inside the same output
    directory as the unit's interface table -- only the names are read, because their content is
    the bulk of a version and nothing here needs it.
    """
    vof = s.version_output_files
    listed: Dict[str, List[str]] = {}
    in_behaviour: Dict[str, List[str]] = {}
    units_by_dir: Dict[str, Set[str]] = {}

    def _add(where: Dict[str, List[str]], key: str, unit_key: str) -> None:
        if unit_key not in where.setdefault(key, []):
            where[key].append(unit_key)

    for r in conn.execute(
            select(vof.c.rel_path, vof.c.content)
            .where(vof.c.version_id == version_id,
                   or_(vof.c.rel_path.like("%interface_tables.json"),
                       vof.c.rel_path.like("%_behaviour_pngs.json")))).fetchall():
        path = (r.rel_path or "").replace("\\", "/")
        try:
            payload = json.loads(r.content or "{}") or {}
        except ValueError:
            continue
        if path.endswith("interface_tables.json"):
            out_dir = path[:-len("interface_tables.json")]
            for unit_key, unit in payload.items():
                if unit_key == "unitNames" or not isinstance(unit, dict):
                    continue
                units_by_dir.setdefault(out_dir, set()).add(unit_key)
                for entry in unit.get("entries") or []:
                    key = (entry or {}).get("functionId") or (entry or {}).get("globalId")
                    if key:
                        _add(listed, key, unit_key)
        else:
            for comp, unit, row in p3.behaviour_rows(payload.get("_docxRows")):
                fid = row.get("currentFunctionId")
                if fid:
                    _add(in_behaviour, fid, "%s|%s" % (comp, unit))

    drawn: Set[str] = set()
    for r in conn.execute(
            select(vof.c.rel_path)
            .where(vof.c.version_id == version_id,
                   vof.c.rel_path.like("%/flowcharts/%.json"))).fetchall():
        path = (r.rel_path or "").replace("\\", "/")
        if path.endswith("_summary.json"):
            continue
        out_dir, _, name = path.rpartition("/flowcharts/")
        stem = name[:-len(".json")]
        drawn |= {u for u in units_by_dir.get(out_dir + "/", ()) if u.split("|")[-1] == stem}

    documented = set().union(*units_by_dir.values()) if units_by_dir else set()
    return _Placement(listed, in_behaviour, drawn, documented)


def _shown_for(kind: str, entity_key: str, entry: Dict[str, Any], where: _Placement) -> List[str]:
    """The units whose SWE.3 document shows this slot's text; `[]` for none."""
    if entry.get("hidden"):
        return []                               # the exporter drops a hidden function entirely
    if kind == slot.UNIT_DESCRIPTION:
        return [entity_key] if entity_key in where.documented_units else []
    listed = where.listed.get(entity_key, [])
    if kind == slot.DESCRIPTION:
        return list(listed)
    # input/output names: printed in a published function's flowchart table (so only
    # where it was drawn), and in the Dynamic Behaviour rows that show the function.
    shown = [u for u in listed if u in where.drawn_units]
    return shown + [u for u in where.in_behaviour.get(entity_key, []) if u not in shown]


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
    where = _placement(conn, version_id)
    items: List[Dict[str, Any]] = []

    for artifact in artifacts:
        for entity_key, entry in sorted((models.artifact(artifact) or {}).items()):
            if not isinstance(entry, dict):
                continue
            comp, un = _scope_of(entity_key)
            if unit and un != unit:
                continue
            if component and component_id(comp) != component:
                continue
            key = (slot.for_unit(entity_key) if kind == slot.UNIT_DESCRIPTION
                   else slot.for_entity(kind, entity_key))
            try:
                text = resolver.read_text(models.as_model(), kind, key)
            except (resolver.SlotError, slot.SlotKeyError):
                continue          # not addressable in this version; not listable either
            items.append({
                **slot_view(kind, key, text, done.get(key)),
                "label": entry.get("name") or entry.get("qualifiedName") or entity_key,
                "component": comp,
                "unit": un,
                "artifact": artifact,
                "shownIn": _shown_for(kind, entity_key, entry, where),
            })
    return _page(items, limit, offset)


def _shown_in(conn, version_id):
    """`(known, {type key: [unit keys]})` -- which units' header tables show each record's
    description, read from this version's stored unit header rows (`typeKey`).

    The rows are the table itself, so this is exact where anything computed from the model would
    have to re-implement the view's row rules -- orphan-header lending among them. `known` is
    False when the stored rows predate `typeKey` (every row carries the field now, `None` on a
    row that prints a value), or when there are none: then nothing can be said about where a
    description is shown.
    """
    vof = s.version_output_files
    rows = conn.execute(
        select(vof.c.rel_path, vof.c.content)
        .where(vof.c.version_id == version_id, vof.c.rel_path.like("%unit_headers.json"))
    ).fetchall()
    known = False
    shown: Dict[str, List[str]] = {}
    for r in rows:
        if not (r.rel_path or "").replace("\\", "/").endswith("unit_headers.json"):
            continue
        try:
            by_unit = json.loads(r.content or "{}")
        except ValueError:
            continue
        for unit_key, unit_rows in (by_unit or {}).items():
            for hrow in unit_rows or []:
                if not isinstance(hrow, dict) or "typeKey" not in hrow:
                    continue
                known = True
                type_key = hrow.get("typeKey")
                if type_key and unit_key not in shown.setdefault(type_key, []):
                    shown[type_key].append(unit_key)
    return known, shown


def _structs(conn, version_id, models, unit, component, limit, offset) -> Page:
    """`structDescription`: the records a document can show a description for.

    Keyed by type, so the key names no unit -- but the unit header table shows the description
    under particular units, and that is where a reviewer meets it. `shownIn` lists them (from the
    stored rows, see `_shown_in`); `unit` and `component` filter on it, the same way they filter
    the kinds whose key does carry a unit.
    """
    kind = slot.STRUCT_DESCRIPTION
    known, shown = _shown_in(conn, version_id)
    if (unit or component) and not known:
        # Refused rather than answered empty: an empty list would read as "this unit shows no
        # struct descriptions" when the truth is "this output cannot say".
        raise NotScoped("this version's unit header table was derived before its rows named "
                        "their type, so it cannot say which unit shows which description. "
                        "Re-export the version, or list structDescription without a filter")
    done = _overridden(conn, version_id, kind)
    model = models.as_model()
    items = []
    for type_name, entry in sorted((models.artifact("dataDictionary") or {}).items()):
        if not isinstance(entry, dict):
            continue
        key = slot.for_entity(kind, type_name)
        try:
            text = resolver.read_text(model, kind, key)
        except (resolver.SlotError, slot.SlotKeyError):
            continue          # not a record a document describes; see resolver
        where = shown.get(type_name) or []
        scopes = [_scope_of(u) for u in where]
        if unit or component:
            if not any((not unit or un == unit)
                       and (not component or component_id(comp) == component)
                       for comp, un in scopes):
                continue
        comp, un = scopes[0] if scopes else (None, None)
        items.append({
            **slot_view(kind, key, text, done.get(key)),
            "label": type_name,
            "component": comp, "unit": un, "artifact": "dataDictionary",
            "kindOfType": entry.get("kind"),
            "shownIn": where,
        })
    return _page(items, limit, offset)


# ---------------------------------------------------------------------------
# the two Phase-3 kinds
# ---------------------------------------------------------------------------
def _flowcharts(conn, version_id, unit, component, limit, offset) -> Page:
    """`nodeLabel`, listed PER FLOWCHART.

    A version has ~42,000 node labels; one row each would be hundreds of pages of something
    nobody reads linearly. A flowchart is one function's graph, so this lists the functions that
    have one — with the `flowchartId` `R7` takes, which returns that flowchart's nodes.
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

    from review import rerender
    rows = rerender.output_rows(conn, version_id, rerender.FLOWCHARTS)
    # A flowchart is printed in the flowchart table of a function the interface table lists.
    listed = _placement(conn, version_id).listed

    items = []
    for r in rows:
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
            if component and component_id(comp) != component:
                continue
            nodes = ((e.get("cfg") or {}).get("nodes") or [])
            items.append({
                "slotKind": slot.NODE_LABEL,
                "flowchartId": fid,
                "functionName": e.get("name"),
                "component": comp,
                "unit": un,
                "nodeCount": len(nodes),
                "overriddenCount": per_flowchart.get(fid, 0),
                "shownIn": list(listed.get(fid, [])),
            })
    items.sort(key=lambda i: (i["component"] or "", i["unit"] or "", i["flowchartId"]))
    return _page(items, limit, offset)


def _behaviour_rows(conn, version_id, unit, component, limit, offset) -> Page:
    """`behaviourDescription`, one row per call arrow.

    Read from the same `_behaviour_pngs.json` output `rerender.find_behaviour_row` writes back
    into, and addressed by the same two entity keys — never by the `externalUnitFunction` display
    label, which two different callers can share (`REQ-ID-01`).
    """
    from review import rerender
    kind = slot.BEHAVIOUR_DESCRIPTION
    done = _overridden(conn, version_id, kind)

    items = []
    for r in rerender.output_rows(conn, version_id, rerender.BEHAVIOUR_MANIFEST):
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
            if component and component_id(comp) != component:
                continue
            key = slot.for_behaviour_row(fid, caller)
            # `behaviorDescription` -- the field the behaviour view writes, the DOCX exporter
            # reads (docx_exporter: row.get("behaviorDescription")) and R6 patches. An earlier
            # version read `behaviorDescriptionList`, which is only the exporter's PARAMETER name;
            # no row has ever carried it, so every behaviour row listed with no bullets at all.
            # What is in force is the stored row, which R6 patches for a live correction and which
            # an orphan never reached; `slot_view` carries it as `text` and as `bullets`.
            text = p3.join_bullets(row.get("behaviorDescription") or [])
            items.append({
                **slot_view(kind, key, text, done.get(key)),
                "label": row.get("externalUnitFunction"),
                "component": comp,
                "unit": un,
                # A behaviour row is the Dynamic Behaviour section itself: shown where it sits.
                "shownIn": ["%s|%s" % (comp, un)],
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

    # One spelling for the filter. A key spells a component with hyphens (`Layer1.My-Sample`), the
    # config and the CLI with spaces (`Layer1.My Sample`); both name the same component, and the
    # second one used to match nothing -- an empty list, read as "no slots here".
    component = component_id(component) if component else None

    if slot_kind == slot.NODE_LABEL:
        return _flowcharts(conn, version_id, unit, component, limit, offset)
    if slot_kind == slot.BEHAVIOUR_DESCRIPTION:
        return _behaviour_rows(conn, version_id, unit, component, limit, offset)
    if slot_kind == slot.STRUCT_DESCRIPTION:
        return _structs(conn, version_id, models, unit, component, limit, offset)
    return _model_backed(conn, version_id, slot_kind, models, unit, component, limit, offset)
