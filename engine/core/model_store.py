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

from core.db_util import insert_chunked, insert_ignore

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from api.db.postgres import schema as s   # noqa: E402

_FN_PAYLOAD_FIELDS = (
    "returnType", "returnExpr", "description", "behaviourInputName", "behaviourOutputName",
    "parameters", "phases", "readsGlobalIdsTransitive", "writesGlobalIdsTransitive",
    # `syntheticFromVarDecl` marks an entry the parser synthesised from a variable declaration
    # rather than a real function. It is not cosmetic: flowchart_engine.py filters on it —
    #     processable = [e for e in target_entries if not e.synthetic_from_var_decl]
    # so dropping it makes the engine try to build a flowchart for a non-function once the model
    # is read from the database. Found by verify_model_parity on the first SQLite run; the
    # office Postgres run reported OK only because that project has no such entry.
    "syntheticFromVarDecl",
)
# `description` is LLM-generated (llm.enrichment.variableEnrichment) and renders in the DOCX
# unit-header table, so losing it costs real document content — yet it was absent here, so
# every global's description was dropped on the way into the database. Found by
# tools/verify_model_parity.py on the first real run, which is exactly the class of bug an
# allow-list invites: add a model field, forget this tuple, lose it silently.
_GLOBAL_PAYLOAD_FIELDS = ("type", "value", "description")


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
        # `entities` is SHARED across a project's versions, so two concurrent jobs both read,
        # both compute the same missing row, and both insert it — a unique violation on
        # (project_id, entity_key). ON CONFLICT DO NOTHING plus the re-read below gives the
        # right id map whichever writer won (doc 10, H1).
        insert_ignore(conn, s.entities, new)
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
        # Worse than `entities`: content_hash is GLOBAL, and every entity with an empty payload
        # hashes identically — so two concurrent jobs on ANY projects will race for that one
        # row, near-certainly rather than rarely. The row is content-addressed, so whoever wins
        # stored identical bytes and a skipped insert loses nothing (doc 10, H1).
        insert_ignore(conn, s.content_blobs, fresh)


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
        insert_chunked(conn, s.entity_versions, ev_rows)
    if edges:
        insert_chunked(conn, s.model_edges, edges)


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
        insert_chunked(conn, s.entity_versions, ev_rows)


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
        insert_chunked(conn, s.model_edges, rows)


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
# view outputs (PG-5a) — the text/JSON files under output/ (interface tables,
# flowchart + unit-diagram mermaid, behaviour rows). Binaries (PNG/DOCX) stay on disk.
# ---------------------------------------------------------------------------
_OUTPUT_TEXT_EXTS = (".json", ".mmd", ".txt", ".md", ".csv", ".dot", ".svg", ".html")


def dump_output_files_to_dir(conn, version_id, out_dir) -> int:
    """Write a version's stored TEXT view files back under `out_dir`. Returns files written.

    The counterpart of `persist_output_files`, and what lets a BASELINE's Phase-3 output be
    reconstructed on a machine that never produced it (doc 09, IN-3).

    That matters because incremental flowchart carry-forward copies the baseline's
    `<unit>.json` files — and those are a genuine INPUT, not a record: the flowchart engine
    writes the DOT text into them in one process and the view reads them back in another to
    render each PNG. With the files absent, carry-forward finds nothing, silently re-renders
    every flowchart, and the run still "succeeds" — just slowly and with 0% flowchart reuse.

    PNGs are NOT restored (they are not stored — D-14). A carried unit whose JSON is restored
    but whose PNG is missing simply gets re-rendered from the DOT, which is correct.
    """
    rows = conn.execute(select(s.version_output_files.c.rel_path,
                               s.version_output_files.c.content)
                        .where(s.version_output_files.c.version_id == version_id)).fetchall()
    if not rows:
        return 0
    n = 0
    for r in rows:
        dest = os.path.join(out_dir, *r.rel_path.split("/"))
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        try:
            with open(dest, "w", encoding="utf-8") as fh:
                fh.write(r.content or "")
            n += 1
        except OSError:
            continue                     # one unwritable file must not abort the restore
    return n


def persist_output_files(conn, version_id, output_dir) -> int:
    """Store every TEXT file under `output_dir` as one `version_output_files` row, so the API can
    read the Phase-3 views (interface tables / flowchart + unit mermaid / behaviour rows) from
    Postgres instead of a disk snapshot. Binary artifacts (PNG/DOCX) are skipped — they stay as
    files (D-14). Idempotent: replaces any rows already stored for this version. Returns the count."""
    conn.execute(delete(s.version_output_files)
                 .where(s.version_output_files.c.version_id == version_id))
    if not output_dir or not os.path.isdir(output_dir):
        return 0
    rows = []
    for root, _, files in os.walk(output_dir):
        for fn in files:
            if not fn.lower().endswith(_OUTPUT_TEXT_EXTS):
                continue
            abspath = os.path.join(root, fn)
            rel = os.path.relpath(abspath, output_dir).replace(os.sep, "/")
            try:
                with open(abspath, encoding="utf-8") as fh:
                    content = fh.read()
            except (OSError, UnicodeDecodeError):                # unreadable / not really text
                continue
            rows.append({"version_id": version_id, "rel_path": rel, "content": content,
                         "group_name": rel.split("/", 1)[0] if "/" in rel else None})
    if rows:
        conn.execute(insert(s.version_output_files), rows)
    return len(rows)


def load_output_files(conn, version_id) -> Dict[str, str]:
    """{rel_path -> content} for every persisted output file of a version."""
    vof = s.version_output_files
    return {r.rel_path: r.content
            for r in conn.execute(select(vof.c.rel_path, vof.c.content)
                                  .where(vof.c.version_id == version_id))}


def persist_run_metadata(conn, version_id, meta: Dict[str, Any]) -> None:
    """Store the run's identity metadata on the version row — the `versions` columns that replace
    model/metadata.json (doc 07 §3: "metadata.json (basePath/projectName/parseFingerprint) ->
    versions columns"). An UPDATE only: the row itself is created by the API at job start."""
    from sqlalchemy import update
    conn.execute(update(s.versions).where(s.versions.c.id == version_id).values(
        base_path=meta.get("basePath"),
        project_name=meta.get("projectName"),
        parse_fingerprint=meta.get("parseFingerprint")))


def persist_run_outcome(conn, version_id, manifest: Dict[str, Any]) -> None:
    """Store the run's incremental accounting on the version row — the columns that replace
    ``<commit>/manifest.json`` (doc 09, C1).

    Every field already had a column; the manifest was simply the transport the API read them
    from. Writing them here removes an engine->API file, and makes the accounting readable from
    any node instead of only the one that ran the job.

    An UPDATE only, and only of fields the manifest actually carried: the row is created and
    owned by the API at job start, and a partial manifest must not blank a good column.
    """
    from sqlalchemy import update
    vals: Dict[str, Any] = {}
    # Close out the pipeline lifecycle. PhaseRunner writes the IN-PROGRESS states
    # (parsing/deriving/viewing/exporting); nothing wrote a terminal one, so a finished run
    # stayed at 'exporting' forever. That is not cosmetic: `pg_stores.list_versions` only
    # accepts a baseline whose pipeline_status is NULL or 'complete', so every finished
    # version was silently disqualified — the next run found no baseline, fell back to a FULL
    # generation and reused 0%. Writing it here covers the API and standalone CLI runs alike,
    # because both go through write_manifest. Only terminal states: an in-progress 'running'
    # would clobber the finer-grained phase value.
    st = manifest.get("status")
    if st in ("complete", "failed"):
        vals["pipeline_status"] = st
    if manifest.get("decision") is not None:
        vals["decision"] = manifest.get("decision")
    if manifest.get("baselineVersionId") is not None:
        vals["baseline_version_id"] = manifest.get("baselineVersionId")
    if manifest.get("regenerated") is not None:
        vals["regenerated"] = manifest.get("regenerated")
    if manifest.get("reused") is not None:
        vals["reused"] = manifest.get("reused")
    # And the manifest verbatim. The named columns above are the queryable accounting; this
    # carries everything else it holds and no column covers — warnings, carriedForward,
    # crossVersionReused, documents. Without it versions/<ver>/manifest.json is genuinely
    # load-bearing rather than redundant, and an operator on another node cannot see why a
    # run warned.
    if manifest:
        vals["run_report"] = manifest
    if not vals:
        return
    conn.execute(update(s.versions).where(s.versions.c.id == version_id).values(**vals))


def load_run_outcome(conn, version_id) -> Dict[str, Any]:
    """The run's accounting back in manifest.json's shape ({} when the row is absent).

    Keyed the same way the manifest was, so a caller that used to read the file can switch to
    this without reshaping anything downstream.
    """
    row = conn.execute(select(s.versions.c.decision,
                              s.versions.c.baseline_version_id,
                              s.versions.c.regenerated,
                              s.versions.c.reused,
                              s.versions.c.run_report)
                       .where(s.versions.c.id == version_id)).first()
    if row is None:
        return {}
    # The stored manifest underneath, the typed columns on top: the columns are the values
    # something may have corrected since the run (a rename, a re-export), so they win.
    out: Dict[str, Any] = dict(row.run_report or {})
    out.update({"decision": row.decision, "baselineVersionId": row.baseline_version_id,
                "regenerated": row.regenerated, "reused": row.reused})
    return {k: v for k, v in out.items() if v is not None}


def load_run_metadata(conn, version_id) -> Dict[str, Any]:
    """The version's identity metadata in metadata.json's shape ({} when the row is absent or the
    columns were never populated). `parseFingerprint` is the clang-flag guard narrowed parse
    compares against its baseline."""
    v = s.versions
    r = conn.execute(select(v.c.base_path, v.c.project_name, v.c.parse_fingerprint)
                     .where(v.c.id == version_id)).first()
    if r is None:
        return {}
    out = {"basePath": r.base_path, "projectName": r.project_name,
           "parseFingerprint": r.parse_fingerprint}
    return {k: val for k, val in out.items() if val is not None}


def load_output_file(conn, version_id, rel_path) -> Optional[str]:
    """The content of one persisted output file (POSIX rel path under output/), or None."""
    vof = s.version_output_files
    r = conn.execute(select(vof.c.content).where(
        (vof.c.version_id == version_id) & (vof.c.rel_path == rel_path))).first()
    return r.content if r else None


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


# ---------------------------------------------------------------------------
# units / components / summaries  (D-13: relationship lists are DERIVED, not stored)
# ---------------------------------------------------------------------------
def persist_units(conn, version_id, units):
    rows = [{"version_id": version_id, "unit_key": uk, "component": _split_key(uk)[0],
             "name": u.get("name"), "path": u.get("path"), "file_name": u.get("fileName"),
             "included_headers": u.get("includedHeaders")}
            for uk, u in units.items()]
    if rows:
        conn.execute(insert(s.model_units), rows)


def _unit_of(fid: str) -> Optional[str]:
    p = fid.split("|")
    return f"{p[0]}|{p[1]}" if len(p) >= 2 else None


def load_units(conn, version_id) -> Dict[str, dict]:
    units: Dict[str, dict] = {}
    for r in conn.execute(select(s.model_units).where(s.model_units.c.version_id == version_id)):
        units[r.unit_key] = {"name": r.name, "path": r.path, "fileName": r.file_name,
                             "functionIds": [], "globalVariableIds": [],
                             "callerUnits": [], "calleesUnits": [],
                             "includedHeaders": r.included_headers or []}
    # functionIds / globalVariableIds: entities that live in each unit
    ev, ent = s.entity_versions, s.entities
    for r in conn.execute(select(ent.c.entity_key, ent.c.kind, ev.c.component, ev.c.unit)
                          .select_from(ev.join(ent, ent.c.entity_id == ev.c.entity_id))
                          .where(ev.c.version_id == version_id)):
        uk = f"{r.component}|{r.unit}"
        if uk in units:
            if r.kind == "function":
                units[uk]["functionIds"].append(r.entity_key)
            elif r.kind == "global":
                units[uk]["globalVariableIds"].append(r.entity_key)
    # caller/callee units: from the call graph (cross-unit edges only)
    from collections import defaultdict
    caller, callee = defaultdict(set), defaultdict(set)
    me = s.model_edges
    for r in conn.execute(select(me.c.src_key, me.c.dst_key)
                          .where((me.c.version_id == version_id) & (me.c.kind == "call"))):
        us, ud = _unit_of(r.src_key), _unit_of(r.dst_key)
        if us and ud and us != ud:
            callee[us].add(ud)
            caller[ud].add(us)
    for uk, u in units.items():
        u["callerUnits"] = sorted(caller.get(uk, ()))
        u["calleesUnits"] = sorted(callee.get(uk, ()))
    return units


def persist_components(conn, version_id, components):
    rows = [{"version_id": version_id, "name": name, "header_files": c.get("headerFiles")}
            for name, c in components.items()]
    if rows:
        conn.execute(insert(s.model_components), rows)


def load_components(conn, version_id) -> Dict[str, dict]:
    comps: Dict[str, dict] = {}
    for r in conn.execute(select(s.model_components).where(s.model_components.c.version_id == version_id)):
        comps[r.name] = {"units": [], "headerFiles": r.header_files or []}
    # ORDER BY: model_units has no ordinal, so without this the unit list comes back in
    # whatever order the database happens to return — which is not stable across engines or
    # even across runs. The container diagram draws one box per unit in list order, so an
    # unstable order means a visually different PNG for identical input.
    for r in conn.execute(select(s.model_units.c.component, s.model_units.c.unit_key)
                          .where(s.model_units.c.version_id == version_id)
                          .order_by(s.model_units.c.unit_key)):
        if r.component in comps:
            comps[r.component]["units"].append(r.unit_key)
    return comps


def persist_summaries(conn, version_id, summaries):
    blobs: Dict[str, tuple] = {}
    rows = []

    def add(scope, key, text):
        ch = _content_hash({"text": text})
        blobs[ch] = ("summary", {"text": text})
        rows.append({"version_id": version_id, "scope": scope, "key": key, "text_hash": ch})

    if summaries.get("project"):
        add("project", "", summaries["project"])
    for k, t in (summaries.get("components") or {}).items():
        add("component", k, t)
    for k, t in (summaries.get("files") or {}).items():
        add("file", k, t)
    _insert_blobs(conn, blobs)
    if rows:
        conn.execute(insert(s.model_summaries), rows)


def load_summaries(conn, version_id) -> Dict[str, Any]:
    ms, cb = s.model_summaries, s.content_blobs
    out: Dict[str, Any] = {"project": "", "components": {}, "files": {}}
    for r in conn.execute(select(ms.c.scope, ms.c.key, cb.c.payload)
                          .select_from(ms.outerjoin(cb, cb.c.content_hash == ms.c.text_hash))
                          .where(ms.c.version_id == version_id)):
        text = (r.payload or {}).get("text", "")
        if r.scope == "project":
            out["project"] = text
        elif r.scope == "component":
            out["components"][r.key] = text
        elif r.scope == "file":
            out["files"][r.key] = text
    return out


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
    for t in (s.entity_versions, s.model_edges, s.model_units, s.model_components,
              s.model_summaries):
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
                  hashes=_load("hashes.json"), units=_load("units.json"),
                  components=_load("components.json"), summaries=_load("summaries.json"))


def persist_model(conn, project_id, version_id, *, functions, globals, datadict, edges,
                  hashes=None, units=None, components=None, summaries=None):
    """Persist a whole parsed model for one version."""
    hashes = hashes or {}
    persist_functions(conn, project_id, version_id, functions, hashes)
    persist_globals(conn, project_id, version_id, globals, hashes)
    persist_types(conn, project_id, version_id, datadict, hashes)
    persist_edges(conn, version_id, edges)
    if units:
        persist_units(conn, version_id, units)
    if components:
        persist_components(conn, version_id, components)
    if summaries:
        persist_summaries(conn, version_id, summaries)
    # Any hashed entity not covered above (file-scope macros) still needs its hash row,
    # so load_hashes() reproduces hashes.json exactly (the classify input).
    covered = set(functions) | set(globals) | set(datadict)
    leftover = {k: h for k, h in hashes.items() if k not in covered}
    if leftover:
        persist_bare_entities(conn, project_id, version_id, leftover)


def load_model(conn, version_id) -> Dict[str, Any]:
    """The complete model for a version, in the same dict shapes model/*.json has.
    The read side used by version-scoped API reads and (via dump_model_to_dir) by the
    DB-native pipeline."""
    return {
        "functions": load_functions(conn, version_id),
        "globals": load_globals(conn, version_id),
        "datadict": load_types(conn, version_id),
        "edges": load_edges(conn, version_id),
        "units": load_units(conn, version_id),
        "components": load_components(conn, version_id),
        "summaries": load_summaries(conn, version_id),
        "hashes": load_hashes(conn, version_id),
    }


# model dict key -> the file the pipeline subprocesses expect
_DUMP_FILES = {
    "functions": "functions.json", "globals": "globalVariables.json",
    "datadict": "dataDictionary.json", "edges": "edges.json", "units": "units.json",
    "components": "components.json", "summaries": "summaries.json", "hashes": "hashes.json",
}


# ---------------------------------------------------------------------------
# Per-version whole-object artifacts (doc 10, step 6)
# ---------------------------------------------------------------------------
# knowledge_base and incremental_plans are single JSON objects a phase writes and another reads.
# tu_includes is a MAP, so it gets one row per TU on its (version_id, tu_path) index — the
# narrowed-parse engine and the flowchart engine both look up individual headers.

def persist_knowledge_base(conn, version_id, payload) -> None:
    """Store Phase 2's project knowledge object. Idempotent (replaces)."""
    conn.execute(delete(s.knowledge_base).where(s.knowledge_base.c.version_id == version_id))
    if payload:
        conn.execute(insert(s.knowledge_base),
                     {"version_id": version_id, "payload": payload})


def load_knowledge_base(conn, version_id) -> Dict[str, Any]:
    r = conn.execute(select(s.knowledge_base.c.payload)
                     .where(s.knowledge_base.c.version_id == version_id)).first()
    return (r.payload if r else None) or {}


def persist_incremental_plan(conn, version_id, payload) -> None:
    """Store what this run tells Phases 2 and 3 to regenerate. Idempotent (replaces).

    An empty/absent plan means "full regeneration", so writing nothing must DELETE any previous
    row rather than leave a stale plan behind — otherwise a full run would inherit the last
    incremental run's restriction and silently regenerate almost nothing.
    """
    conn.execute(delete(s.incremental_plans)
                 .where(s.incremental_plans.c.version_id == version_id))
    if payload:
        conn.execute(insert(s.incremental_plans),
                     {"version_id": version_id, "payload": payload})


def load_incremental_plan(conn, version_id) -> Dict[str, Any]:
    r = conn.execute(select(s.incremental_plans.c.payload)
                     .where(s.incremental_plans.c.version_id == version_id)).first()
    return (r.payload if r else None) or {}


def persist_tu_includes(conn, version_id, tu_includes) -> None:
    """Store the per-TU include closure: {tuPath -> [headers]}. Idempotent.

    The table has existed since the migration and nothing ever wrote it — the same
    declared-but-unwritten shape as `pipeline_status` and `versions.report`, both of which cost
    real bugs. One row per TU so a reader can look up a single header on the index instead of
    pulling the whole map.
    """
    conn.execute(delete(s.tu_includes).where(s.tu_includes.c.version_id == version_id))
    rows = [{"version_id": version_id, "tu_path": k, "headers": v}
            for k, v in (tu_includes or {}).items()]
    insert_chunked(conn, s.tu_includes, rows)


def load_tu_includes(conn, version_id) -> Dict[str, Any]:
    return {r.tu_path: (r.headers or []) for r in conn.execute(
        select(s.tu_includes.c.tu_path, s.tu_includes.c.headers)
        .where(s.tu_includes.c.version_id == version_id))}


def persist_parse_snapshot(conn, version_id, model_dir, names) -> int:
    """Store the post-Phase-1 skeleton for `version_id` (doc 09, C2). Returns files stored.

    Idempotent: replaces this version's rows, so re-running Phase 1 (or `--from-phase 1`)
    does not accumulate duplicates.

    Files are stored VERBATIM. Reconstructing the skeleton later by stripping LLM fields
    would need a hardcoded list of every field Phase 2 adds — and any field added after that
    list was written would silently poison the skeleton, which is the failure mode this
    snapshot exists to prevent.
    """
    from sqlalchemy import delete
    conn.execute(delete(s.parse_snapshots).where(s.parse_snapshots.c.version_id == version_id))
    rows = []
    for name in names:
        p = os.path.join(model_dir, name)
        if not os.path.isfile(p):
            continue                        # not every artifact exists on every run
        try:
            with open(p, encoding="utf-8") as fh:
                rows.append({"version_id": version_id, "name": name, "payload": json.load(fh)})
        except (OSError, ValueError):
            continue                        # a malformed artifact must not fail the run
    if rows:
        conn.execute(insert(s.parse_snapshots), rows)
    return len(rows)


def load_parse_snapshot(conn, version_id) -> Dict[str, Any]:
    """The stored skeleton as {filename: parsed json}, or {} when absent.

    Shaped like `_load_parse_dir` reads a directory, so a caller can switch source without
    reshaping anything downstream.
    """
    out: Dict[str, Any] = {}
    for r in conn.execute(select(s.parse_snapshots.c.name, s.parse_snapshots.c.payload)
                          .where(s.parse_snapshots.c.version_id == version_id)):
        out[r.name] = r.payload
    return out


def dump_parse_snapshot_to_dir(conn, version_id, out_dir) -> int:
    """Write the stored post-Phase-1 skeleton back out as files. Returns files written.

    The counterpart of `dump_model_to_dir`, and the reason the skeleton is stored verbatim:
    restoring it is a straight write-out, with no reassembly step that could fail to
    reproduce the shape the phases expect.

    Which one to restore depends on where you resume, and getting it wrong is a correctness
    bug rather than an inconvenience: Phase 2 SKIPS any function that already carries a
    description, so resuming Phase 2 from the *enriched* model would enrich nothing.

        resume at Phase 2      -> this (the skeleton)
        resume at Phase 3 / 4  -> dump_model_to_dir (the enriched model)
    """
    snap = load_parse_snapshot(conn, version_id)
    if not snap:
        return 0
    os.makedirs(out_dir, exist_ok=True)
    n = 0
    for name, payload in snap.items():
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        n += 1
    return n


def dump_model_to_dir(conn, version_id, out_dir) -> None:
    """Materialize a version's DB model back to model/*.json. The bridge for tools that
    still take file paths (the flowchart engine / scanner subprocesses) until they read
    the DB directly - the model stays sourced from Postgres, the file is a hand-off."""
    os.makedirs(out_dir, exist_ok=True)
    model = load_model(conn, version_id)
    for key, fname in _DUMP_FILES.items():
        with open(os.path.join(out_dir, fname), "w", encoding="utf-8") as fh:
            json.dump(model[key], fh, indent=2, ensure_ascii=False)


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
