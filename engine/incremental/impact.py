"""Change classification + impact analysis for incremental regen (doc 04 §5 steps 4-5).

Two pure functions (operate on plain model dicts — no I/O, no libclang):

  classify(baseline_hashes, target_hashes) -> {changed, new, deleted, unchanged}
      A dict diff of two {entityKey -> source_hash} snapshots.

  impact_set(changed_keys, functions, edges, ...) -> set of function fids
      Reverse-reachability ("who depends on this?") UP the dependency graph, so a
      dependent in an UNCHANGED file is regenerated too. THIS IS THE #1 CORRECTNESS
      TRAP: "changed files" gives only the directly-changed entities; if a()
      (unchanged) calls b() (changed), a's description/flowchart describe b's
      behaviour and are stale unless impact propagates UP to a.

Axes (doc 04 §5): calls + globals come from functions.json (`calledByIds`,
`reads`/`writesGlobalIds`); types + macros come from edges.json (`typeUsers`,
`macroUsers`). The recursive closure is a BFS with a visited-set (handles cycles).
Bias is to OVER-approximate (never stale): a changed global/type/macro pulls in all
its users; deleted functions' baseline callers are seeded via `extra_seed_functions`.
"""
from __future__ import annotations

from collections import deque
from typing import Any, Dict, Iterable, List, Optional, Set


def classify(baseline_hashes: Dict[str, str],
             target_hashes: Dict[str, str]) -> Dict[str, Set[str]]:
    """Classify every entity key as changed / new / deleted / unchanged by comparing
    two source-hash snapshots."""
    b, t = set(baseline_hashes), set(target_hashes)
    common = b & t
    return {
        "changed": {k for k in common if baseline_hashes[k] != target_hashes[k]},
        "new": t - b,
        "deleted": b - t,
        "unchanged": {k for k in common if baseline_hashes[k] == target_hashes[k]},
    }


def _global_users(functions: Dict[str, dict]) -> Dict[str, Set[str]]:
    """Invert functions' global reads/writes -> {globalKey -> {fids that use it}}."""
    gu: Dict[str, Set[str]] = {}
    for fid, f in functions.items():
        for g in list(f.get("readsGlobalIds") or []) + list(f.get("writesGlobalIds") or []):
            gu.setdefault(g, set()).add(fid)
    return gu


def impact_set(changed_keys: Iterable[str],
               functions: Dict[str, dict],
               edges: Optional[Dict[str, Dict[str, List[str]]]] = None,
               *,
               extra_seed_functions: Optional[Iterable[str]] = None) -> Set[str]:
    """Return the set of function fids to regenerate: the changed/new functions
    themselves plus everything transitively depending on any changed entity.

    `changed_keys` may contain functions, globals, types and macros (the union of
    classify()'s changed+new, and changed types/macros). Non-function keys seed via
    their users. `extra_seed_functions` lets the engine inject functions that a
    DELETED entity affected (e.g. baseline callers of a removed function), which
    can't be discovered from the target model alone.
    """
    edges = edges or {}
    type_users = edges.get("typeUsers", {})
    macro_users = edges.get("macroUsers", {})
    global_users = _global_users(functions)

    result: Set[str] = set()
    frontier: deque = deque()

    def add(fid: str) -> None:
        if fid in functions and fid not in result:
            result.add(fid)
            frontier.append(fid)

    for key in changed_keys:
        if key in functions:                       # a changed/new function regenerates
            add(key)
        else:                                      # global / type / macro -> its users
            for f in global_users.get(key, ()):
                add(f)
            for f in type_users.get(key, ()):
                add(f)
            for f in macro_users.get(key, ()):
                add(f)

    for fid in (extra_seed_functions or ()):
        add(fid)

    while frontier:                                # propagate UP to callers (transitive)
        f = frontier.popleft()
        for caller in functions[f].get("calledByIds", ()):
            add(caller)

    return result
