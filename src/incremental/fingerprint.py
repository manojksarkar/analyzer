"""Reuse-index fingerprints for incremental output reuse (doc 04 §4).

Distinct from the per-entity *source_hash* (model/hashes.json, M1.2a):

  source_hash(entity)  = token hash of the entity's OWN source (change detection)
  fingerprint(entity)  = sha256( source_hash
                               + sorted(dependency source_hashes) )   (OUTPUT reuse key)

A function's LLM description/flowchart depends on its callees' code + the globals,
types and macros it uses — so the reuse key folds all of those in. A dependency change
(even in an unchanged file) changes the fingerprint, so a stale output is never reused;
a revert / cross-branch-identical entity reproduces the same fingerprint and is reused.

The fingerprint is **content-only** — it deliberately does NOT fold in the LLM recipe
(model/prompt/engine version). An already-generated, approved document is reused
regardless of which model produced it; we do not re-run the LLM just because the model
or prompt changed (decision: recipe-fingerprint invalidation dropped).

Pure (operates on plain dicts) so it is unit-testable; the engine supplies the
parsed model (functions.json / hashes.json / edges.json).
"""
from __future__ import annotations

import hashlib
from typing import Dict, List, Set

_SEP = "\x1f"


def _invert_users(users: Dict[str, List[str]]) -> Dict[str, Set[str]]:
    """{key -> [fids]}  ->  {fid -> {keys}} (forward deps of each function)."""
    fwd: Dict[str, Set[str]] = {}
    for key, fids in (users or {}).items():
        for fid in fids:
            fwd.setdefault(fid, set()).add(key)
    return fwd


def _fingerprint(source_hash: str, dep_hashes: List[str]) -> str:
    blob = _SEP.join([source_hash, *sorted(dep_hashes)])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def compute_fingerprints(hashes: Dict[str, str],
                         functions: Dict[str, dict],
                         edges: Dict[str, Dict[str, List[str]]]) -> Dict[str, str]:
    """Return {entityKey -> fingerprint} for every entity with a reusable output
    (functions + globals).

    Function deps = callees (callsIds) + globals (reads/writesGlobalIds) + types &
    macros it uses (forward-inverted from edges). Globals currently fold in only
    their own source_hash (no deps) — refine later if needed.
    """
    fid_to_types = _invert_users((edges or {}).get("typeUsers", {}))
    fid_to_macros = _invert_users((edges or {}).get("macroUsers", {}))

    out: Dict[str, str] = {}

    # Functions
    for fid, f in (functions or {}).items():
        sh = hashes.get(fid)
        if not sh:
            continue
        dep_keys: Set[str] = set()
        dep_keys.update(f.get("callsIds") or [])
        dep_keys.update(f.get("readsGlobalIds") or [])
        dep_keys.update(f.get("writesGlobalIds") or [])
        dep_keys.update(fid_to_types.get(fid, set()))
        dep_keys.update(fid_to_macros.get(fid, set()))
        dep_hashes = [hashes[k] for k in dep_keys if k in hashes]
        out[fid] = _fingerprint(sh, dep_hashes)

    # Globals: model keys with exactly 2 pipes that aren't already functions.
    for key, sh in hashes.items():
        if key in out or key in functions:
            continue
        if key.count("|") == 2:  # component|unit|qualifiedName  (global)
            out[key] = _fingerprint(sh, [])

    return out
