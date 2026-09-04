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

from typing import Any, Dict, Iterable, List, Set

from incremental.virtual_dispatch import spread_virtual_families


def _norm(p: str) -> str:
    """Normalize a repo-relative path for set membership: forward slashes, case-folded.

    Folds on every platform, not only Windows -- see `affected._norm` for why. The drop set
    here is matched against `entity_files`, whose spellings come from libclang, against a
    `changed` list whose spellings come from git. A baseline parsed on one platform and
    merged on another would otherwise fail to drop the entity, leaving the baseline's copy
    in place with its old hash and no error. Over-matching costs a re-parse; under-matching
    is a stale document.
    """
    return (p or "").replace("\\", "/").strip("/").lower()


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
    affected TUs transitively #include, and only the dropped files were fully re-parsed.

    **File-less entries are the exception.** `_file_of` returns "" for an entry that has no
    `entity_files` mapping and no `@file` in its key — dataDictionary entries added by the
    external `--data-dictionary` CSV, the `PRIMITIVES` seed, and the canonical builtins
    `_register_builtin_range` records. "" is never in `drop`, so the plain rule kept the
    baseline copy and threw the fresh one away: a CSV added after the baseline never landed
    at all, and an edited range lost to the stale baseline value — silently, on every
    incremental run.

    Since no file owns them, the by-file rule cannot arbitrate: take the fresh entry.
    **Union, not replace** — a narrowed parse only calls `_register_builtin_range` for the
    builtins its re-parsed TUs use, so dropping baseline file-less entries absent from
    `fresh` would lose builtin ranges belonging to untouched TUs. The residual gap is a row
    DELETED from the CSV: its entry survives until the next full parse."""
    out = {k: v for k, v in (baseline or {}).items() if _file_of(k, entity_files) not in drop}
    for k, v in (fresh or {}).items():
        f = _file_of(k, entity_files)
        if f in drop or not f:
            out[k] = v
    return out


def _merge_func_keys(baseline: Dict[str, str], fresh: Dict[str, str],
                     entity_files: Dict[str, str], drop: Set[str]) -> Dict[str, str]:
    """Merge {mangled-func-key -> fid} by the file of the VALUE.

    `_merge_keyed` cannot serve here: it resolves a file from the entry's KEY, and these keys are
    mangled C++ names, not entity keys. Using it silently kept every baseline entry and discarded
    every fresh one, because no mangled name is ever found in `entity_files`.
    """
    out = {k: v for k, v in (baseline or {}).items() if _file_of(v, entity_files) not in drop}
    for k, v in (fresh or {}).items():
        if _file_of(v, entity_files) in drop:
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


def _merge_address_taken(baseline_recs, fresh_recs, entity_files, drop) -> List[list]:
    """[[target_fid, registering_unit], …] — keep baseline records whose TARGET's file wasn't
    re-parsed, then add fresh ones for targets in re-parsed files (dedup).

    Without this a narrowed parse that doesn't touch the table's file loses the registration,
    the function flips back to private, and the same source yields a different document.
    """
    out: List[list] = []
    seen: Set[tuple] = set()
    for rec in list(baseline_recs or []):
        tgt = rec[0] if rec else None
        if tgt and _file_of(tgt, entity_files) not in drop and tuple(rec) not in seen:
            out.append(list(rec)); seen.add(tuple(rec))
    for rec in list(fresh_recs or []):
        tgt = rec[0] if rec else None
        if tgt and _file_of(tgt, entity_files) in drop and tuple(rec) not in seen:
            out.append(list(rec)); seen.add(tuple(rec))
    return out


def _apply_address_taken(functions: Dict[str, dict], records: List[list],
                         entity_files: Dict[str, str], drop: Set[str]) -> None:
    """Re-attach addressTakenByUnits to the merged functions from the merged records.

    Clearing is restricted to functions whose DEFINING FILE was re-parsed. For those the
    fresh records are authoritative, so a registration deleted from a re-parsed table must
    disappear -- that is the deletion semantics this has to keep.

    For every other function this run has no evidence either way, and popping the field was
    destructive: `_merge_address_taken` can only carry a baseline record forward if the
    baseline HAS one, so a missing baseline `address_taken` artifact looked exactly like a
    deliberate removal. The field was then wiped from functions in files nobody touched,
    even though the baseline's own functions.json still carried it.

    That is not hypothetical. `address_taken` was only registered in DB_BACKED_PARSE in
    421f4e5; any version generated in database mode before that wrote the artifact to a
    file nothing reads, so its parse snapshot has none. Chaining an incremental run off
    such a version silently flipped every function published only through a file-scope
    pointer table to private -- `_fn_is_private` keeps those public via this field alone,
    since no CALL_EXPR names them -- and they vanished from the interface tables, the unit
    and behaviour diagrams, and the document.
    """
    by_fid: Dict[str, Set[str]] = {}
    for rec in records or []:
        if len(rec) >= 2 and rec[0] in functions and rec[1]:
            by_fid.setdefault(rec[0], set()).add(rec[1])
    for fid, f in functions.items():
        units = by_fid.get(fid)
        if units:
            f["addressTakenByUnits"] = sorted(units)
        elif _file_of(fid, entity_files) in drop:
            f.pop("addressTakenByUnits", None)
        # else: file not re-parsed, no evidence -- keep what the baseline carried.


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

    address_taken = _merge_address_taken(baseline.get("address_taken"), fresh.get("address_taken"),
                                         entity_files, drop)
    # A baseline with no address_taken records, whose own functions nonetheless carry
    # addressTakenByUnits, is the poisoned shape: the artifact was never captured (it was
    # registered in DB_BACKED_PARSE only in 421f4e5), so nothing can be carried forward
    # from it and only the file-scoped guard above keeps those registrations alive. Say so
    # -- silently inheriting it is how every pointer-table entry flipped private.
    if not (baseline.get("address_taken") or []):
        _stale = sorted(fid for fid, f in (baseline.get("functions") or {}).items()
                        if f.get("addressTakenByUnits"))
        if _stale:
            from utils import log as _log
            _log("baseline has no address_taken snapshot, but %d of its function(s) are "
                 "published by a pointer table. Their registrations are preserved from the "
                 "baseline model, not re-derived -- regenerate the baseline with --full if a "
                 "table changed there. Affected: %s%s"
                 % (len(_stale), ", ".join(_stale[:3]),
                    "" if len(_stale) <= 3 else " ..."),
                 component="incremental", err=True)
    _apply_address_taken(functions, address_taken, entity_files, drop)

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
        # The baseline's {mangled-func-key -> fid} map, merged by the fid's FILE.
        #
        # It was not merged or republished at all, so a narrowed parse produced a version whose
        # stored snapshot had no func_keys. The map is what lets a call from a re-parsed file
        # into an UN-parsed one resolve to an edge, so the NEXT narrowed parse against that
        # version silently lost cross-TU call edges — the document then shows a function calling
        # less than it does, with nothing logged. One narrowed parse from a full baseline worked,
        # which is why the gate did not catch it: the damage needs two in a row.
        "func_keys": _merge_func_keys(baseline.get("func_keys") or {},
                                      fresh.get("func_keys") or {}, merged_entity_files, drop),
        # Function-pointer table registrations, replayed because a narrowed parse may not
        # re-parse the file holding the table. Same reasoning as func_keys above.
        "address_taken": address_taken,
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
