"""Persist / load the analyzer model to Postgres (docs/production-redesign/07, PG-4).

The manifest-of-pointers storage (D-9) in code. functions, globals, and types/macros
are ALL `entities` (distinguished by `entities.kind`); each contributes one thin row per
version to `entity_versions` (structural columns + the three hashes + a pointer) and its
heavy/variable fields to a shared, content-addressed `content_blobs` row. The dependency
graph is `model_edges`:

    call          src=caller  dst=callee            (from functions.callsIds)
    global_access src=fn      dst=global  mode=r/w  (from functions.reads/writesGlobalIds)
    type_use      src=user    dst=type              (from edges.json typeUsers)
    macro_use     src=user    dst=macro             (from edges.json macroUsers)

Every edge points user -> dependency, so "who depends on X" is a reverse lookup by
dst_key (the indexed impact-analysis query). `calledByIds` is never stored - it is the
reverse of `callsIds`, rebuilt on load.

`load_hashes(version)` returns exactly the `{entity_key: source_hash}` map that
`classify` diffs, so change detection can move to the DB with no other change.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from typing import Any, Dict, Optional

from sqlalchemy import delete, insert, select

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from api.db.postgres import schema as s   # noqa: E402

_FN_PAYLOAD_FIELDS = (
    "returnType", "returnExpr", "description", "behaviourInputName", "behaviourOutputName",
    "parameters", "phases", "readsGlobalIdsTransitive", "writesGlobalIdsTransitive",
)
_GLOBAL_PAYLOAD_FIELDS = ("type", "value")


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------
def _content_hash(payload: Dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _split_key(fid: str) -> tuple[str, str]:
    parts = fid.split("|")
    return (parts[0] if len(parts) > 0 else ""), (parts[1] if len(parts) > 1 else "")


def _entity_ids(conn, project_id: str) -> Dict[str, int]:
    return {r.entity_key: r.entity_id for r in conn.execute(
        select(s.entities.c.entity_key, s.entities.c.entity_id)
        .where(s.entities.c.project_id == project_id))}


def _ensure_entities(conn, project_id: str, specs: Dict[str, tuple]) -> Dict[str, int]:
    """specs: {entity_key: (kind, qualified_name)}. Insert the missing ones; return id map."""
    ids = _entity_ids(conn, project_id)
    new = [{"project_id": project_id, "entity_key": k, "kind": kind, "qualified_name": qn}
           for k, (kind, qn) in specs.items() if k not in ids]
    if new:
        conn.execute(insert(s.entities), new)
        ids = _entity_ids(conn, project_id)
    return ids


def _insert_blobs(conn, blobs: Dict[str, tuple]) -> None:
    """blobs: {content_hash: (kind, payload)} — insert only the ones not already stored."""
    if not blobs:
        return
    have = {r.content_hash for r in conn.execute(
        select(s.content_blobs.c.content_hash)
        .where(s.content_blobs.c.content_hash.in_(list(blobs))))}
    fresh = [{"content_hash": h, "kind": k, "payload": p}
             for h, (k, p) in blobs.items() if h not in have]
    if fresh:
        conn.execute(insert(s.content_blobs), fresh)


def _loc_cols(entry: dict) -> dict:
    loc = entry.get("location") or {}
    return {"file": loc.get("file"), "line": loc.get("line"), "end_line": loc.get("endLine")}


# ---------------------------------------------------------------------------
# functions
# ---------------------------------------------------------------------------
def persist_functions(conn, project_id, version_id, functions, hashes=None):
    hashes = hashes or {}
    ids = _ensure_entities(conn, project_id,
                           {k: ("function", (v or {}).get("qualifiedName")) for k, v in functions.items()})
    blobs, ev_rows, edges = {}, [], []
    for fid, fn in functions.items():
        fn = fn or {}
        payload = {f: fn[f] for f in _FN_PAYLOAD_FIELDS if f in fn}
        ch = _content_hash(payload)
        blobs[ch] = ("function", payload)
        comp, unit = _split_key(fid)
        ev_rows.append({"version_id": version_id, "entity_id": ids[fid], "component": comp, "unit": unit,
                        **_loc_cols(fn), "direction": fn.get("direction"),
                        "direction_reason": fn.get("directionReason"), "visibility": fn.get("visibility"),
                        "interface_id": fn.get("interfaceId"), "is_visible": bool(fn.get("isVisible", True)),
                        "source_hash": hashes.get(fid), "fingerprint": None, "content_hash": ch})
        for dst in (fn.get("callsIds") or []):
            edges.append({"version_id": version_id, "kind": "call", "src_key": fid, "dst_key": dst, "mode": None})
        for dst in (fn.get("readsGlobalIds") or []):
            edges.append({"version_id": version_id, "kind": "global_access", "src_key": fid, "dst_key": dst, "mode": "read"})
        for dst in (fn.get("writesGlobalIds") or []):
            edges.append({"version_id": version_id, "kind": "global_access", "src_key": fid, "dst_key": dst, "mode": "write"})
    _insert_blobs(conn, blobs)
    if ev_rows:
        conn.execute(insert(s.entity_versions), ev_rows)
    if edges:
        conn.execute(insert(s.model_edges), edges)


def load_functions(conn, version_id) -> Dict[str, dict]:
    funcs: Dict[str, dict] = {}
    for r in _entity_rows(conn, version_id, "function"):
        if r.payload is None:
            continue        # hash-only entity (classify), not a real function
        fn = {"qualifiedName": r.qualified_name,
              "location": {"file": r.file, "line": r.line, "endLine": r.end_line},
              "direction": r.direction, "directionReason": r.direction_reason,
              "visibility": r.visibility, "interfaceId": r.interface_id, "isVisible": r.is_visible,
              "callsIds": [], "calledByIds": [], "readsGlobalIds": [], "writesGlobalIds": []}
        fn.update(r.payload or {})
        funcs[r.entity_key] = fn
    me = s.model_edges
    for r in conn.execute(select(me.c.kind, me.c.src_key, me.c.dst_key, me.c.mode)
                          .where((me.c.version_id == version_id)
                                 & me.c.kind.in_(["call", "global_access"]))):
        if r.kind == "call":
            if r.src_key in funcs:
                funcs[r.src_key]["callsIds"].append(r.dst_key)
            if r.dst_key in funcs:
                funcs[r.dst_key]["calledByIds"].append(r.src_key)
        elif r.src_key in funcs:
            funcs[r.src_key]["writesGlobalIds" if r.mode == "write" else "readsGlobalIds"].append(r.dst_key)
    return funcs


# ---------------------------------------------------------------------------
# globals
# ---------------------------------------------------------------------------
def persist_globals(conn, project_id, version_id, globals_data, hashes=None):
    hashes = hashes or {}
    ids = _ensure_entities(conn, project_id,
                           {k: ("global", (v or {}).get("qualifiedName")) for k, v in globals_data.items()})
    blobs, ev_rows = {}, []
    for gid, g in globals_data.items():
        g = g or {}
        payload = {f: g[f] for f in _GLOBAL_PAYLOAD_FIELDS if f in g}
        ch = _content_hash(payload)
        blobs[ch] = ("global", payload)
        comp, unit = _split_key(gid)
        ev_rows.append({"version_id": version_id, "entity_id": ids[gid], "component": comp, "unit": unit,
                        **_loc_cols(g), "direction": g.get("direction"),
                        "direction_reason": g.get("directionReason"), "visibility": g.get("visibility"),
                        "interface_id": g.get("interfaceId"), "is_visible": True,
                        "source_hash": hashes.get(gid), "fingerprint": None, "content_hash": ch})
    _insert_blobs(conn, blobs)
    if ev_rows:
        conn.execute(insert(s.entity_versions), ev_rows)


def load_globals(conn, version_id) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for r in _entity_rows(conn, version_id, "global"):
        if r.payload is None:
            continue
        g = {"qualifiedName": r.qualified_name, "location": {"file": r.file, "line": r.line},
             "visibility": r.visibility, "interfaceId": r.interface_id, "direction": r.direction}
        if r.direction_reason is not None:
            g["directionReason"] = r.direction_reason
        g.update(r.payload or {})              # type, value
        out[r.entity_key] = g
    return out


# ---------------------------------------------------------------------------
# types + macros  (dataDictionary: kind 'define' -> macro, else type)
# ---------------------------------------------------------------------------
def persist_types(conn, project_id, version_id, datadict, hashes=None):
    hashes = hashes or {}
    ids = _ensure_entities(conn, project_id,
                           {k: ("macro" if (v or {}).get("kind") == "define" else "type",
                                (v or {}).get("qualifiedName")) for k, v in datadict.items()})
    blobs, ev_rows = {}, []
    for tid, t in datadict.items():
        t = t or {}
        payload = {k: v for k, v in t.items() if k != "location"}   # everything but location
        ch = _content_hash(payload)
        blobs[ch] = ("type", payload)
        ev_rows.append({"version_id": version_id, "entity_id": ids[tid], "component": None, "unit": None,
                        **_loc_cols(t), "direction": None, "direction_reason": None, "visibility": None,
                        "interface_id": None, "is_visible": True,
                        "source_hash": hashes.get(tid), "fingerprint": None, "content_hash": ch})
    _insert_blobs(conn, blobs)
    if ev_rows:
        conn.execute(insert(s.entity_versions), ev_rows)


def load_types(conn, version_id) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for r in _entity_rows(conn, version_id, ("type", "macro")):
        if r.payload is None:
            continue        # hash-only file-scope macro (classify), not a dataDictionary entry
        entry = dict(r.payload or {})          # kind, name, qualifiedName, underlyingType, ...
        if r.file is not None or r.line is not None:
            entry["location"] = {"file": r.file, "line": r.line}
        out[r.entity_key] = entry
    return out


# ---------------------------------------------------------------------------
# edges.json  (type/macro usage)
# ---------------------------------------------------------------------------
def persist_edges(conn, version_id, edges):
    rows = []
    for typ, users in (edges.get("typeUsers") or {}).items():
        rows += [{"version_id": version_id, "kind": "type_use", "src_key": u, "dst_key": typ, "mode": None}
                 for u in users]
    for mac, users in (edges.get("macroUsers") or {}).items():
        rows += [{"version_id": version_id, "kind": "macro_use", "src_key": u, "dst_key": mac, "mode": None}
                 for u in users]
    if rows:
        conn.execute(insert(s.model_edges), rows)


def load_edges(conn, version_id) -> Dict[str, dict]:
    me = s.model_edges
    tu: Dict[str, list] = {}
    mu: Dict[str, list] = {}
    for r in conn.execute(select(me.c.kind, me.c.src_key, me.c.dst_key)
                          .where((me.c.version_id == version_id)
                                 & me.c.kind.in_(["type_use", "macro_use"]))):
        (tu if r.kind == "type_use" else mu).setdefault(r.dst_key, []).append(r.src_key)
    return {"typeUsers": tu, "macroUsers": mu}


# ---------------------------------------------------------------------------
# hashes  (the classify input) + orchestration
# ---------------------------------------------------------------------------
def load_hashes(conn, version_id) -> Dict[str, str]:
    """{entity_key: source_hash} for every entity that has one - exactly hashes.json."""
    ev, ent = s.entity_versions, s.entities
    return {r.entity_key: r.source_hash for r in conn.execute(
        select(ent.c.entity_key, ev.c.source_hash)
        .select_from(ev.join(ent, ent.c.entity_id == ev.c.entity_id))
        .where((ev.c.version_id == version_id) & ev.c.source_hash.isnot(None)))}


def _entity_kind(key: str) -> str:
    """Classify an entity key by shape (mirrors engine._entity_kind)."""
    if "@" in key and "|" not in key:
        return "macro"
    if key.count("|") >= 3:
        return "function"
    if key.count("|") == 2:
        return "global"
    return "type"


def persist_bare_entities(conn, project_id, version_id, key_hashes: Dict[str, str]) -> None:
    """Entities that carry ONLY a hash (e.g. file-scope macros used but not in the data
    dictionary). They still need a row so `classify` sees their hash - no payload/graph."""
    ids = _ensure_entities(conn, project_id, {k: (_entity_kind(k), None) for k in key_hashes})
    rows = [{"version_id": version_id, "entity_id": ids[k], "source_hash": h, "is_visible": True}
            for k, h in key_hashes.items()]
    if rows:
        conn.execute(insert(s.entity_versions), rows)


def clear_version(conn, version_id) -> None:
    """Remove a version's per-version rows so a re-persist is idempotent. Shared
    `entities` and `content_blobs` are left alone (other versions may reference them)."""
    for t in (s.entity_versions, s.model_edges):
        conn.execute(delete(t).where(t.c.version_id == version_id))


def persist_model_from_dir(conn, project_id, version_id, model_dir) -> None:
    """Read a generation's model/*.json and persist it for `version_id` (idempotent).
    The bridge the pipeline runner uses to sync a completed run into the DB."""
    def _load(name):
        p = os.path.join(model_dir, name)
        try:
            with open(p, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}
    clear_version(conn, version_id)
    persist_model(conn, project_id, version_id,
                  functions=_load("functions.json"), globals=_load("globalVariables.json"),
                  datadict=_load("dataDictionary.json"), edges=_load("edges.json"),
                  hashes=_load("hashes.json"))


def persist_model(conn, project_id, version_id, *, functions, globals, datadict, edges, hashes=None):
    """Persist a whole parsed model for one version."""
    hashes = hashes or {}
    persist_functions(conn, project_id, version_id, functions, hashes)
    persist_globals(conn, project_id, version_id, globals, hashes)
    persist_types(conn, project_id, version_id, datadict, hashes)
    persist_edges(conn, version_id, edges)
    # Any hashed entity not covered above (file-scope macros) still needs its hash row,
    # so load_hashes() reproduces hashes.json exactly (the classify input).
    covered = set(functions) | set(globals) | set(datadict)
    leftover = {k: h for k, h in hashes.items() if k not in covered}
    if leftover:
        persist_bare_entities(conn, project_id, version_id, leftover)


def _entity_rows(conn, version_id, kind):
    """entity_versions joined to entities + content_blobs, filtered to a kind (or kinds)."""
    ev, ent, cb = s.entity_versions, s.entities, s.content_blobs
    kinds = (kind,) if isinstance(kind, str) else tuple(kind)
    q = (select(ent.c.entity_key, ent.c.qualified_name, ev.c.file, ev.c.line, ev.c.end_line,
                ev.c.direction, ev.c.direction_reason, ev.c.visibility, ev.c.interface_id,
                ev.c.is_visible, cb.c.payload)
         .select_from(ev.join(ent, ent.c.entity_id == ev.c.entity_id)
                      .outerjoin(cb, cb.c.content_hash == ev.c.content_hash))
         .where((ev.c.version_id == version_id) & ent.c.kind.in_(kinds)))
    return conn.execute(q)
