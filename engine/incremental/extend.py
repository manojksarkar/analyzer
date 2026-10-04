"""Add layers to a version's model (staged generation).

A version's model covers the layers its run parsed. `analyzer.py export` of a component from
another layer adds that layer to the SAME version:

1. `capture` -- before anything is parsed, the text the version's model already has (function and
   global descriptions, behaviour names, unit and struct descriptions) and, per component, a
   fingerprint of what its documents are built from.
2. Phase 1 over every layer, old and new (analyzer.py). A full parse of the union is what one run
   of both layers would parse, so calls from the old layers into the new one are found too --
   a parse of the new layer alone, merged in, would miss them.
3. `restore_text` puts the old text back on the entities that are still there, and
   `write_plan` tells Phase 2 to describe ONLY the new entities (the incremental plan the
   incremental engine uses: `impactFids`, `impactedGlobals`), plus the units' old descriptions,
   which Phase 2 rebuilds without one (`unitDescriptions`). No LLM call for the old layers.
4. Phase 2 over the whole model (analyzer.py): units, call graph, global use, publication and
   interface ids are worked out across the layers.
5. `changed_components` -- components with documents whose fingerprint moved: their documents
   no longer match the model (a function of theirs is called from the new layer, a global is
   read from it ...). They are marked `stale`; nothing is regenerated.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Optional

from incremental.engine import _CARRY_FIELDS

#: What Phase 2 may write into an entity, LLM-generated or derived from LLM text; carried as is.
_GLOBAL_TEXT = ("description",)
_TYPE_TEXT = ("description",)
#: Not what a document shows: the text (carried, so equal anyway) and where the code sits.
_NOT_FINGERPRINTED = set(_CARRY_FIELDS) | {"description"}


def _engine():
    from core.db import get_engine
    return get_engine()


def _load(cx, version_id: str) -> Dict[str, Dict[str, dict]]:
    from core import model_store as ms
    return {"functions": ms.load_functions(cx, version_id),
            "globals": ms.load_globals(cx, version_id),
            "types": ms.load_types(cx, version_id),
            "units": ms.load_units(cx, version_id)}


def _pick(entities: Dict[str, dict], fields: Iterable[str]) -> Dict[str, dict]:
    out = {}
    for key, e in entities.items():
        kept = {f: e[f] for f in fields if e.get(f) not in (None, "", [])}
        if kept:
            out[key] = kept
    return out


def component_of(key: str) -> str:
    """`Layer1.Math|Utils|add|int` -> `Layer1.Math`."""
    return key.split("|", 1)[0]


def fingerprints(model: Dict[str, Dict[str, dict]]) -> Dict[str, str]:
    """Per component, one hash of what its documents are built from: its functions, globals and
    units with every structural field (calls, callers, global use, visibility, interface id,
    direction, ...), the text left out -- it is carried, and a re-export prints the carried
    text either way."""
    parts: Dict[str, List[str]] = {}
    for kind in ("functions", "globals"):
        for key in sorted(model.get(kind) or {}):
            e = {k: v for k, v in (model[kind][key] or {}).items() if k not in _NOT_FINGERPRINTED}
            parts.setdefault(component_of(key), []).append(
                kind + key + json.dumps(e, sort_keys=True, default=str))
    units = model.get("units") or {}
    by_header: Dict[str, set] = {}
    for uk, u in units.items():
        for h in (u or {}).get("includedHeaders") or []:
            by_header.setdefault(str(h), set()).add(uk)
    for uk in sorted(units):
        u = {k: v for k, v in (units[uk] or {}).items() if k != "description"}
        # The units of OTHER components that include a header this unit includes: the unit
        # header table lists a header no unit owns once, under one owner picked across all of
        # them -- a new layer's unit can take it over.
        sharing = sorted({o for h in (u.get("includedHeaders") or [])
                          for o in by_header.get(str(h), ()) if component_of(o) != component_of(uk)})
        parts.setdefault(component_of(uk), []).append(
            "unit" + uk + json.dumps(u, sort_keys=True, default=str) + json.dumps(sharing))
    return {c: hashlib.sha256("\n".join(p).encode("utf-8")).hexdigest()
            for c, p in parts.items()}


def _links(fn: dict) -> list:
    """What a function's behaviour names are worked out from, besides its own code."""
    return [sorted(fn.get(k) or []) for k in ("callsIds", "readsGlobalIds", "writesGlobalIds")]


def capture(version_id: str) -> Dict[str, Any]:
    """The version's model text and per-component fingerprints, before the parse replaces it."""
    with _engine().connect() as cx:
        model = _load(cx, version_id)
        from core import model_store as ms
        plan = ms.load_incremental_plan(cx, version_id)
    return {
        "functions": _pick(model["functions"], _CARRY_FIELDS),
        "globals": _pick(model["globals"], _GLOBAL_TEXT),
        "types": _pick(model["types"], _TYPE_TEXT),
        "units": {uk: u["description"] for uk, u in model["units"].items() if u.get("description")},
        "keys": {"functions": sorted(model["functions"]), "globals": sorted(model["globals"])},
        "links": {k: _links(f) for k, f in model["functions"].items()},
        "fingerprints": fingerprints(model),
        # An add cut short leaves its own plan behind; it is not the version's, so it is not
        # what the next add puts back (it would keep a later Phase 3 from drawing flowcharts).
        "plan": None if (plan or {}).get("addedLayers") else (plan or None),
    }


def _set_fields(cx, version_id: str, key: str, fields: Dict[str, Any], kinds) -> bool:
    """`model_store.set_entity_field` for several fields at once, only where the entity's own
    value is empty. False when the entity is not in the version (any more)."""
    from sqlalchemy import select, update
    from core import model_store as ms
    from api.db.postgres import schema as s
    ev, ent, cb = s.entity_versions, s.entities, s.content_blobs
    kinds = (kinds,) if isinstance(kinds, str) else tuple(kinds)
    row = cx.execute(
        select(ev.c.entity_id, ent.c.kind, cb.c.payload)
        .select_from(ev.join(ent, ent.c.entity_id == ev.c.entity_id)
                     .outerjoin(cb, cb.c.content_hash == ev.c.content_hash))
        .where(ev.c.version_id == version_id, ent.c.entity_key == key,
               ent.c.kind.in_(kinds))).first()
    if row is None or row.payload is None:
        return False
    payload = dict(row.payload)
    todo = {f: v for f, v in fields.items() if payload.get(f) in (None, "", [])}
    if not todo:
        return True
    payload.update(todo)
    ch = ms._content_hash(payload)
    ms._insert_blobs(cx, {ch: (ms._BLOB_KIND.get(row.kind, row.kind), payload)})
    cx.execute(update(ev).where(ev.c.version_id == version_id, ev.c.entity_id == row.entity_id)
               .values(content_hash=ch))
    return True


def restore_text(version_id: str, saved: Dict[str, Any]) -> Dict[str, int]:
    """Put the captured text back on the entities the new parse still has. One transaction."""
    n = {"functions": 0, "globals": 0, "types": 0}
    with _engine().begin() as cx:
        for key, fields in (saved.get("functions") or {}).items():
            n["functions"] += _set_fields(cx, version_id, key, fields, "function")
        for key, fields in (saved.get("globals") or {}).items():
            n["globals"] += _set_fields(cx, version_id, key, fields, "global")
        for key, fields in (saved.get("types") or {}).items():
            n["types"] += _set_fields(cx, version_id, key, fields, ("type", "macro"))
    return n


def write_plan(version_id: str, project_id: str, saved: Dict[str, Any]) -> Dict[str, Any]:
    """The incremental plan for the Phase 2 that follows: describe what is NEW (not in the
    captured model); keep the old units' descriptions. Returns the plan written."""
    from core import model_store as ms
    with _engine().connect() as cx:
        functions = ms.load_functions(cx, version_id)
        globals_ = ms.load_globals(cx, version_id)
    old_f = set((saved.get("keys") or {}).get("functions") or [])
    old_g = set((saved.get("keys") or {}).get("globals") or [])
    # An old function whose calls or global use changed (it calls into the new layer now), and
    # every caller above it: their behaviour names are worked out from what they reach, so Phase 2
    # works them out again -- their descriptions are kept (filled text is skipped).
    links = saved.get("links") or {}
    moved = [k for k in old_f & set(functions) if k in links and links[k] != _links(functions[k])]
    seen, todo = set(moved), list(moved)
    while todo:
        for caller in (functions.get(todo.pop()) or {}).get("calledByIds") or []:
            if caller in old_f and caller in functions and caller not in seen:
                seen.add(caller)
                todo.append(caller)
    plan = {"impactFids": sorted((set(functions) - old_f) | seen),
            "impactedGlobals": sorted(set(globals_) - old_g),
            "impactedFiles": [], "flowchartFiles": [], "flowchartFids": [],
            "unitDescriptions": dict(saved.get("units") or {}),
            "addedLayers": True}
    _put_plan(version_id, plan)
    return plan


def _put_plan(version_id: str, plan: Optional[Dict[str, Any]]) -> None:
    """Write the version's incremental plan, or remove it (None) -- where Phases 2 and 3 read it."""
    from core import model_store as ms
    with _engine().begin() as cx:
        ms.persist_incremental_plan(cx, version_id, plan or None)


def restore_plan(version_id: str, saved: Dict[str, Any]) -> None:
    """Put back the plan the version had before (or none): the one written for Phase 2 would
    otherwise steer the next Phase 3's flowcharts."""
    _put_plan(version_id, saved.get("plan"))


def changed_components(version_id: str, saved: Dict[str, Any],
                       among: Iterable[str]) -> List[str]:
    """Of `among` (components with documents), those whose fingerprint moved."""
    with _engine().connect() as cx:
        after = fingerprints(_load(cx, version_id))
    before = saved.get("fingerprints") or {}
    return sorted(c for c in among if before.get(c) != after.get(c))


def widen_scope(scope: Optional[Dict[str, Any]], documented: Iterable[str],
                added: Iterable[str], in_model: Iterable[str] = ()) -> Dict[str, Any]:
    """The version's recorded scope once `added` components (of new layers) are in it: what the
    next version is made like (`_scope_like`). A component scope gains them; any other scope (a
    layer or group run) becomes the components the version documents -- or, when it documents
    none yet (a `--model-only` run), every component of its model -- plus them: the same
    documents, and a parse of every layer, old and new."""
    added = [c for c in added]
    if (scope or {}).get("type") == "component":
        names = list(dict.fromkeys(list(scope.get("names") or []) + added))
        return {**scope, "names": names}
    base = list(documented) or sorted(in_model)
    return {"type": "component", "names": list(dict.fromkeys(base + added))}


#: The parse-snapshot row an add in progress keeps its capture in until it has finished. The parse
#: replaces the model's rows -- the old layers' text with them -- so an add cut short after it can
#: only be finished from what was saved before it. The parse never clears this row.
PENDING = "add_layers_pending"


def save_pending(version_id: str, pending: Optional[Dict[str, Any]]) -> None:
    """Store the capture of the add starting now (None removes it)."""
    from core import model_store as ms
    with _engine().begin() as cx:
        ms.persist_parse_snapshot_file(cx, version_id, PENDING, pending)


def load_pending(version_id: str) -> Optional[Dict[str, Any]]:
    """The capture of an add that has not finished, or None."""
    try:
        from core import model_store as ms
        with _engine().connect() as cx:
            return ms.load_parse_snapshot_file(cx, version_id, PENDING) or None
    except Exception:                                   # noqa: BLE001 - no database: no add
        return None


def clear_pending(version_id: str) -> None:
    save_pending(version_id, None)
