"""Narrowed-parse model merge (M4.3, doc 04 §11.2) — the core of the narrowed parse.

A narrowed parse re-parses only the affected TUs, producing a *partial* model (`fresh`)
with correct FORWARD data (callsIds / reads-writes / type-macro usage / hashes) for the
entities in those files. This module merges that into the baseline version's model and
recomputes the derived reverse edges, so the result is byte-identical to a full parse.

Merge rule (sound — see §11.2):
    merged = { baseline entities whose file ∉ drop_files } ∪ { all fresh entities }
where `drop_files` = files the partial parse covered (affected TUs + every file a fresh
entity lives in) ∪ deleted files. Then `calledByIds` is recomputed by inverting the
merged `callsIds` (after re-running the virtual-dispatch spread, D7/M3.13).

Operates only on the PARSER's artifacts — functions / globalVariables / dataDictionary /
hashes / edges / tu_includes (+ the merge-aux entity_files / override_pairs / metadata).
units / components / transitive-globals / descriptions are re-derived by Phase 2 from the
merged functions.json, exactly as after a full parse.

Pure (plain dicts) so it is unit-testable; the engine supplies the two models + drop set.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List, Set

from incremental.virtual_dispatch import spread_virtual_families


def _norm(p: str) -> str:
    """Normalize a repo-relative path for set membership: forward slashes, and case-folded
    on case-insensitive filesystems (Windows) so git-diff paths and entity_files line up."""
    p = (p or "").replace("\\", "/").strip("/")
    return p.lower() if os.name == "nt" else p


def _file_of(key: str, entity_files: Dict[str, str]) -> str:
    """Resolve an entity's defining file (normalized for matching). entity_files covers
    every hashed entity; macros also carry the file in their key (`name@relFile`)."""
    f = entity_files.get(key)
    if not f and "@" in key:
        f = key.split("@", 1)[1]
    return _norm(f)


def _merge_keyed(baseline: Dict[str, Any], fresh: Dict[str, Any],
                 entity_files: Dict[str, str], drop: Set[str]) -> Dict[str, Any]:
    """Generic by-file merge for a {key -> entry} artifact: for a DROPPED file use the
    fresh entry, for every other file keep the baseline entry. Fresh entries for non-dropped
    files are DISCARDED — a partial parse sees (incomplete) entities for everything its
    affected TUs transitively #include, and only the dropped files were fully re-parsed."""
    out = {k: v for k, v in (baseline or {}).items() if _file_of(k, entity_files) not in drop}
    for k, v in (fresh or {}).items():
        if _file_of(k, entity_files) in drop:
            out[k] = v
    return out


def _merge_edges(baseline_edges: Dict[str, Dict[str, List[str]]],
                 fresh_edges: Dict[str, Dict[str, List[str]]],
                 entity_files: Dict[str, str], drop: Set[str],
                 valid_fids: Set[str]) -> Dict[str, Dict[str, List[str]]]:
    """typeUsers / macroUsers are reverse maps {key -> [fids]}. A type/macro's users =
    (baseline users whose file isn't dropped) ∪ (fresh users), restricted to the merged
    functions; keys with no remaining user are dropped."""
    out: Dict[str, Dict[str, List[str]]] = {}
    for axis in ("typeUsers", "macroUsers"):
        merged: Dict[str, List[str]] = {}
        for key, fids in ((baseline_edges or {}).get(axis, {}) or {}).items():
            kept = [f for f in fids if f in valid_fids and _file_of(f, entity_files) not in drop]
            if kept:
                merged[key] = kept
        for key, fids in ((fresh_edges or {}).get(axis, {}) or {}).items():
            bucket = merged.setdefault(key, [])
            for f in fids:
                # only fresh users in a dropped (fully re-parsed) file — a partial parse's
                # view of a non-dropped file's usages is incomplete.
                if f in valid_fids and _file_of(f, entity_files) in drop and f not in bucket:
                    bucket.append(f)
        out[axis] = {k: v for k, v in merged.items() if v}
    return out


def _merge_override_pairs(baseline_pairs: Iterable, fresh_pairs: Iterable,
                          entity_files: Dict[str, str], drop: Set[str]) -> List[list]:
    """override→base pairs (fid-level). Keep baseline pairs whose override's file isn't
    dropped, then add fresh pairs (dedup)."""
    out: List[list] = []
    seen: Set[tuple] = set()
    for pair in list(baseline_pairs or []):
        ov = pair[0] if pair else None
        if ov and _file_of(ov, entity_files) not in drop and tuple(pair) not in seen:
            out.append(list(pair)); seen.add(tuple(pair))
    for pair in list(fresh_pairs or []):
        ov = pair[0] if pair else None
        if ov and _file_of(ov, entity_files) in drop and tuple(pair) not in seen:
            out.append(list(pair)); seen.add(tuple(pair))
    return out


def _recompute_call_edges(functions: Dict[str, dict], override_pairs: List[list]) -> None:
    """Mutate `functions`: drop callsIds to entities no longer in the model, re-run the
    virtual-dispatch family spread (D7/M3.13), then recompute calledByIds by inverting
    the merged callsIds. readsGlobalIds/writesGlobalIds/direction are forward fields and
    survive the by-file merge unchanged."""
    valid = set(functions)
    call_graph: Dict[str, List[str]] = {}
    for fid, f in functions.items():
        call_graph[fid] = [c for c in (f.get("callsIds") or []) if c in valid]
    reverse: Dict[str, List[str]] = {}
    for fid, callees in call_graph.items():
        for c in callees:
            reverse.setdefault(c, []).append(fid)

    spread_virtual_families(call_graph, reverse, override_pairs, valid)

    # write back callsIds; recompute calledByIds as the inversion of callsIds.
    called_by: Dict[str, List[str]] = {fid: [] for fid in functions}
    for fid in functions:
        callees = call_graph.get(fid, [])
        functions[fid]["callsIds"] = callees
        for c in callees:
            if c in called_by and fid not in called_by[c]:
                called_by[c].append(fid)
    for fid, f in functions.items():
        f["calledByIds"] = called_by[fid]


def merge_model(baseline: Dict[str, Any], fresh: Dict[str, Any], drop_files: Iterable[str]) -> Dict[str, Any]:
    """Merge a partial parse (`fresh`) into the baseline model and recompute reverse edges.

    Both dicts hold the parser artifacts keyed by name: functions, globalVariables,
    dataDictionary, hashes, edges, tu_includes, entity_files, override_pairs, metadata.
    `drop_files` = the files the partial parse covered (+ deleted files); baseline entities
    in those files are replaced by `fresh`. Returns the merged model dict.
    """
    drop = {_norm(f) for f in drop_files}
    # The authoritative key->file resolver. BASELINE wins for shared keys: an entity keeps
    # its baseline (canonical) file, so an entity DEFINED IN MULTIPLE FILES (e.g. a `typedef
    # int UNIT;` repeated across TUs) stays with the baseline's stable winner instead of
    # flipping to whichever affected TU re-parsed it — which would diverge from a full parse.
    entity_files = dict(fresh.get("entity_files") or {})
    entity_files.update(baseline.get("entity_files") or {})

    functions = _merge_keyed(baseline.get("functions"), fresh.get("functions"), entity_files, drop)
    globals_ = _merge_keyed(baseline.get("globalVariables"), fresh.get("globalVariables"), entity_files, drop)
    data_dict = _merge_keyed(baseline.get("dataDictionary"), fresh.get("dataDictionary"), entity_files, drop)
    hashes = _merge_keyed(baseline.get("hashes"), fresh.get("hashes"), entity_files, drop)
    merged_entity_files = _merge_keyed(baseline.get("entity_files"), fresh.get("entity_files"), entity_files, drop)
    override_pairs = _merge_override_pairs(baseline.get("override_pairs"), fresh.get("override_pairs"),
                                           entity_files, drop)
    edges = _merge_edges(baseline.get("edges"), fresh.get("edges"), entity_files, drop, set(functions))

    # tu_includes is keyed by TU path (a file): re-parsed TUs from fresh, the rest baseline.
    tu_includes = {tu: inc for tu, inc in (baseline.get("tu_includes") or {}).items()
                   if _norm(tu) not in drop}
    for tu, inc in (fresh.get("tu_includes") or {}).items():
        if _norm(tu) in drop:
            tu_includes[tu] = inc

    _recompute_call_edges(functions, override_pairs)

    return {
        "metadata": fresh.get("metadata") or baseline.get("metadata") or {},
        "functions": functions,
        "globalVariables": globals_,
        "dataDictionary": data_dict,
        "hashes": hashes,
        "edges": edges,
        "tu_includes": dict(sorted(tu_includes.items())),
        "entity_files": merged_entity_files,
        "override_pairs": override_pairs,
    }


# Function fields that are unordered edge sets — order is cosmetic (it doesn't affect
# classify / impact / reuse), so the self-check compares them as sets.
_EDGE_FIELDS = ("callsIds", "calledByIds", "readsGlobalIds", "writesGlobalIds")


def diff_models(narrowed: Dict[str, Any], full: Dict[str, Any], *, limit: int = 50) -> List[str]:
    """The M4.5 `--verify-parse` self-check: compare a narrowed parser-level model against
    a full-parse one and return human-readable mismatch lines (empty list = identical).
    Edge lists are compared as SETS (order is cosmetic). Pure — unit-testable."""
    out: List[str] = []

    def add(msg: str) -> None:
        if len(out) < limit:
            out.append(msg)

    # 1. entity key sets per keyed artifact
    for name in ("functions", "globalVariables", "hashes", "dataDictionary", "entity_files"):
        a, b = narrowed.get(name) or {}, full.get(name) or {}
        for k in sorted(set(b) - set(a)):
            add(f"{name}: MISSING {k}")
        for k in sorted(set(a) - set(b)):
            add(f"{name}: EXTRA {k}")

    # 2. per-function fields (edge lists as sets, everything else exact)
    af, bf = narrowed.get("functions") or {}, full.get("functions") or {}
    for k in sorted(set(af) & set(bf)):
        a, b = af[k], bf[k]
        for fld in sorted(set(a) | set(b)):
            av, bv = a.get(fld), b.get(fld)
            if fld in _EDGE_FIELDS:
                if sorted(av or []) != sorted(bv or []):
                    add(f"functions[{k}].{fld}: {sorted(av or [])} != {sorted(bv or [])}")
            elif av != bv:
                add(f"functions[{k}].{fld}: {av!r} != {bv!r}")

    # 3. hash values
    ah, bh = narrowed.get("hashes") or {}, full.get("hashes") or {}
    for k in sorted(set(ah) & set(bh)):
        if ah[k] != bh[k]:
            add(f"hashes[{k}]: {ah[k]} != {bh[k]}")

    # 4. edges (typeUsers / macroUsers), values as sets
    ae, be = narrowed.get("edges") or {}, full.get("edges") or {}
    for axis in ("typeUsers", "macroUsers"):
        aa, bb = ae.get(axis) or {}, be.get(axis) or {}
        for key in sorted(set(aa) | set(bb)):
            if sorted(aa.get(key) or []) != sorted(bb.get(key) or []):
                add(f"edges.{axis}[{key}]: {sorted(aa.get(key) or [])} != {sorted(bb.get(key) or [])}")
    return out
