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
from typing import Any, Dict, List, Set

_SEP = "\x1f"


def parse_fingerprint(clang_args: List[str], std: str = "", toolchain: str = "",
                      base_path: str = "") -> str:
    """A hash of everything that determines a TU's AST *other than the source itself*:
    the clang args (include paths `-I` and defines `-D`, **order preserved** — include
    order matters), the C++ std, and a toolchain marker (libclang version/path).

    Distinct from both other fingerprints: it gates the **narrowed parse** (M4) — if it
    differs from the baseline version's, the baseline model was parsed with different
    flags/toolchain, so a narrowed parse against it is unsafe and the engine must do a
    full re-parse (doc 04 §11.4). It does NOT include the LLM recipe.

    `base_path` — the checkout root — is replaced by a placeholder in every argument before
    hashing. **This is load-bearing, not tidiness.** Each commit is checked out to its own
    directory (`workspaces/<pid>/<commit[:16]>`), so without it every `-I` differs between any
    two commits, the fingerprint differs on every run, and the gate trips every time. Narrowed
    parse then fell back to a full parse 100% of the time — correct output, none of the saving,
    and no error to explain why. Found by `tools/verify_narrowed_parse.py`.

    Normalising also makes the value comparable ACROSS machines, which the multi-node
    deployment needs: node B's checkout root is not node A's.

    Changing what is hashed invalidates fingerprints stored by earlier runs. That is safe by
    construction — a mismatch means "full parse", which is the conservative branch — and it
    self-corrects after one run per version.
    """
    parts = [str(std), str(toolchain), *(_norm_path_arg(a, base_path)
                                         for a in (clang_args or []))]
    return hashlib.sha256(_SEP.join(parts).encode("utf-8")).hexdigest()


def _norm_path_arg(arg: Any, base_path: str) -> str:
    """One clang argument with the checkout root folded out and separators normalised.

    Separator-insensitive because the same run can produce both flavours on Windows: the
    checkout root arrives with backslashes while some arguments are built with forward ones.
    """
    s = str(arg).replace("\\", "/")
    base = str(base_path or "").replace("\\", "/").rstrip("/")
    if base:
        s = s.replace(base, "<repo>")
    return s


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
    #
    # Their fingerprint folds in the ACCESSORS' source hashes, not just their own. A global's
    # LLM description is built from the descriptions of the functions that read and write it
    # (`enrich_globals_rich` puts them in the prompt), so a changed reader changes the global's
    # input. With `_fingerprint(sh, [])` — own source only — the fingerprint did NOT move, the
    # reuse index scored a hit, and the global kept a description written against the reader's
    # OLD behaviour. Silently stale, and exactly the failure the content-addressed design exists
    # to prevent: "a dependency change, even in an unchanged file, changes the fingerprint"
    # (doc 04 §4). Functions already did this with their callees; globals were the gap.
    accessors: Dict[str, Set[str]] = {}
    for fid, f in (functions or {}).items():
        for gkey in list(f.get("readsGlobalIds") or []) + list(f.get("writesGlobalIds") or []):
            accessors.setdefault(gkey, set()).add(fid)

    for key, sh in hashes.items():
        if key in out or key in functions:
            continue
        if key.count("|") == 2:  # component|unit|qualifiedName  (global)
            dep_hashes = [hashes[a] for a in accessors.get(key, ()) if a in hashes]
            out[key] = _fingerprint(sh, dep_hashes)

    return out
