"""Persist / load the analyzer model to Postgres (docs/production-redesign/07, PG-4).

The manifest-of-pointers storage (D-9) in code:

    functions.json  ->  entities        (stable identity, one row ever per fn)
                        entity_versions (one THIN row per version: structural cols + hashes
                                         + a pointer to the payload)
                        content_blobs   (the heavy/variable fields, stored ONCE per distinct
                                         content, content-addressed)
                        model_edges     (call + global-access edges; reverse graph = impact)

`calledByIds` is NOT stored — it is the reverse of `callsIds` and is reconstructed on
load, so the graph is kept once. Likewise a function's edges live in `model_edges`, not
duplicated on the row.

This module is pure persistence: given a parsed model it writes rows; given a version it
reads them back into the same dict shape `functions.json` has. Round-trip fidelity is
covered by tests/unit/test_model_store.py against real model data.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from typing import Any, Dict, Optional

from sqlalchemy import insert, select

# Shared schema lives under api/; add the repo root so the engine can import it (the
# same thing alembic/env.py does).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from api.db.postgres import schema as s   # noqa: E402

# Heavy/variable function fields -> the content blob (everything not a queried column
# and not an edge). Order-preserving fields like `parameters` round-trip exactly via JSON.
_FN_PAYLOAD_FIELDS = (
    "returnType", "returnExpr", "description", "behaviourInputName", "behaviourOutputName",
    "parameters", "phases", "readsGlobalIdsTransitive", "writesGlobalIdsTransitive",
)


def _content_hash(payload: Dict[str, Any]) -> str:
    """Stable content address for a payload (identical payloads dedup to one blob)."""
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _split_key(fid: str) -> tuple[str, str]:
    parts = fid.split("|")
    return (parts[0] if len(parts) > 0 else ""), (parts[1] if len(parts) > 1 else "")


def _entity_ids(conn, project_id: str) -> Dict[str, int]:
    return {r.entity_key: r.entity_id for r in conn.execute(
        select(s.entities.c.entity_key, s.entities.c.entity_id)
        .where(s.entities.c.project_id == project_id))}


def persist_functions(conn, project_id: str, version_id: str,
                      functions: Dict[str, dict], hashes: Optional[Dict[str, str]] = None) -> None:
    """Write functions + their edges for one version. `conn` is an open connection/transaction."""
    hashes = hashes or {}

    # 1. entities: ensure a stable row per fid (identity is shared across versions).
    ids = _entity_ids(conn, project_id)
    new = [{"project_id": project_id, "entity_key": k, "kind": "function",
            "qualified_name": (functions[k] or {}).get("qualifiedName")}
           for k in functions if k not in ids]
    if new:
        conn.execute(insert(s.entities), new)
        ids = _entity_ids(conn, project_id)

    # 2. build content blobs (dedup), entity_versions rows, and edges.
    blobs: Dict[str, dict] = {}
    ev_rows: list[dict] = []
    edge_rows: list[dict] = []
    for fid, fn in functions.items():
        fn = fn or {}
        payload = {f: fn[f] for f in _FN_PAYLOAD_FIELDS if f in fn}
        ch = _content_hash(payload)
        blobs[ch] = payload
        comp, unit = _split_key(fid)
        loc = fn.get("location") or {}
        ev_rows.append({
            "version_id": version_id, "entity_id": ids[fid], "component": comp, "unit": unit,
            "file": loc.get("file"), "line": loc.get("line"), "end_line": loc.get("endLine"),
            "direction": fn.get("direction"), "direction_reason": fn.get("directionReason"),
            "visibility": fn.get("visibility"), "interface_id": fn.get("interfaceId"),
            "is_visible": bool(fn.get("isVisible", True)),
            "source_hash": hashes.get(fid), "fingerprint": None, "content_hash": ch,
        })
        for dst in (fn.get("callsIds") or []):
            edge_rows.append({"version_id": version_id, "kind": "call", "src_key": fid,
                              "dst_key": dst, "mode": None})
        for dst in (fn.get("readsGlobalIds") or []):
            edge_rows.append({"version_id": version_id, "kind": "global_access", "src_key": fid,
                              "dst_key": dst, "mode": "read"})
        for dst in (fn.get("writesGlobalIds") or []):
            edge_rows.append({"version_id": version_id, "kind": "global_access", "src_key": fid,
                              "dst_key": dst, "mode": "write"})

    # 3. insert only NEW blobs (content-addressed dedup), then the manifest + edges.
    if blobs:
        have = {r.content_hash for r in conn.execute(
            select(s.content_blobs.c.content_hash)
            .where(s.content_blobs.c.content_hash.in_(list(blobs))))}
        fresh = [{"content_hash": h, "kind": "function", "payload": p}
                 for h, p in blobs.items() if h not in have]
        if fresh:
            conn.execute(insert(s.content_blobs), fresh)
    if ev_rows:
        conn.execute(insert(s.entity_versions), ev_rows)
    if edge_rows:
        conn.execute(insert(s.model_edges), edge_rows)


def load_functions(conn, version_id: str) -> Dict[str, dict]:
    """Reconstruct `functions.json` for a version from the manifest tables."""
    ev, ent, cb = s.entity_versions, s.entities, s.content_blobs
    q = (select(ent.c.entity_key, ent.c.qualified_name, ev.c.file, ev.c.line, ev.c.end_line,
                ev.c.direction, ev.c.direction_reason, ev.c.visibility, ev.c.interface_id,
                ev.c.is_visible, cb.c.payload)
         .select_from(ev.join(ent, ent.c.entity_id == ev.c.entity_id)
                      .outerjoin(cb, cb.c.content_hash == ev.c.content_hash))
         .where((ev.c.version_id == version_id) & (ent.c.kind == "function")))

    funcs: Dict[str, dict] = {}
    for r in conn.execute(q):
        fn = {
            "qualifiedName": r.qualified_name,
            "location": {"file": r.file, "line": r.line, "endLine": r.end_line},
            "direction": r.direction, "directionReason": r.direction_reason,
            "visibility": r.visibility, "interfaceId": r.interface_id,
            "isVisible": r.is_visible,
            "callsIds": [], "calledByIds": [], "readsGlobalIds": [], "writesGlobalIds": [],
        }
        fn.update(r.payload or {})              # returnType, description, parameters, phases, ...
        funcs[r.entity_key] = fn

    # rebuild the graph: calls forward + reverse (calledBy), globals by mode.
    me = s.model_edges
    for r in conn.execute(select(me.c.kind, me.c.src_key, me.c.dst_key, me.c.mode)
                          .where(me.c.version_id == version_id)):
        if r.kind == "call":
            if r.src_key in funcs:
                funcs[r.src_key]["callsIds"].append(r.dst_key)
            if r.dst_key in funcs:
                funcs[r.dst_key]["calledByIds"].append(r.src_key)
        elif r.kind == "global_access" and r.src_key in funcs:
            key = "writesGlobalIds" if r.mode == "write" else "readsGlobalIds"
            funcs[r.src_key][key].append(r.dst_key)
    return funcs
