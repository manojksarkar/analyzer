"""Virtual-dispatch call-edge over-approximation (D7 — bias to over-regenerate).

A C++ virtual call (`base_ptr->m()`) is resolved by libclang to the *static* method
(usually the base, or — when the base is pure-virtual and absent from the model — an
arbitrary override picked by name). So a call that may dynamically dispatch to any
override is recorded against only one of them, leaving the siblings with no callers.
Consequence: changing an override would not impact the dispatcher (stale), and the
model falsely reports the override as never-called.

This module fixes both: given the override→base relations (`get_overridden_cursors`),
it unions each virtual *family* (a base + all its transitive overrides) and links every
caller of ANY member to ALL members present in the model. So changing any override
impacts every dispatcher, and `calledByIds` is accurate. Conservative by design — it
links more, never fewer (D7).

Pure: it mutates the two call-graph dicts it is handed (no globals), so it is unit-
testable; `parser.py` calls it with its `call_graph` / `reverse_call_graph`.

`spread_virtual_calls` is the exact form (review SWE3-028), used whenever the parse
recorded its virtual calls: a call reaches the method it names and every override BELOW
it -- never the base above it or a sibling -- and a call that names the class
(`Base::f()`) does not dispatch, so it is not recorded and reaches that method only. A
call through a `Base*` still reaches every override, so changing one still impacts the
dispatcher. `spread_virtual_families` stays for a baseline made before the parse
recorded its virtual calls.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Set, Tuple


def overrides_below(override_pairs: Iterable[Tuple[str, str]]) -> Dict[str, Set[str]]:
    """{method -> every override of it, at any depth below}, from (override, base) pairs."""
    children: Dict[str, Set[str]] = defaultdict(set)
    for ov, base in override_pairs:
        if ov != base:
            children[base].add(ov)
    below: Dict[str, Set[str]] = {}
    for top in list(children):
        seen: Set[str] = set()
        todo = list(children[top])
        while todo:
            m = todo.pop()
            if m not in seen:
                seen.add(m)
                todo.extend(children.get(m, ()))
        below[top] = seen
    return below


def spread_virtual_calls(call_graph: Dict[str, List[str]],
                         reverse_call_graph: Dict[str, List[str]],
                         override_pairs: Iterable[Tuple[str, str]],
                         virtual_calls: Iterable[Tuple[str, str]],
                         function_keys: Iterable[str]) -> Tuple[int, int]:
    """Link each virtual call (caller, method named) to every override below that method.

    `virtual_calls` holds only the calls that dispatch: a call naming its class
    (`Base::f()`) is left out by the parser. The method named keeps its own edge, made
    where the call was seen (when it is defined). Returns (edges_added, calls_spread)."""
    below = overrides_below(override_pairs)
    fkeys = set(function_keys)
    edges_added = calls_spread = 0
    for caller, named in sorted(set(virtual_calls)):
        targets = sorted(m for m in below.get(named, ()) if m in fkeys)
        if not targets:
            continue
        calls_spread += 1
        cg = call_graph.setdefault(caller, [])
        for m in targets:
            if m not in cg:
                cg.append(m)
                edges_added += 1
            rg = reverse_call_graph.setdefault(m, [])
            if caller not in rg:
                rg.append(caller)
    return edges_added, calls_spread


def spread_virtual_families(call_graph: Dict[str, List[str]],
                            reverse_call_graph: Dict[str, List[str]],
                            override_pairs: Iterable[Tuple[str, str]],
                            function_keys: Iterable[str]) -> Tuple[int, int]:
    """Link every caller of a virtual-family member to ALL members in `function_keys`.

    Args:
      call_graph:          {callerKey -> [calleeKey]}        (mutated, dedup-preserving)
      reverse_call_graph:  {calleeKey -> [callerKey]}        (mutated)
      override_pairs:      iterable of (overrideKey, baseKey) from get_overridden_cursors
      function_keys:       keys that are real (defined) functions in the model

    Returns (edges_added, families_spread).
    """
    pairs = list(override_pairs)
    if not pairs:
        return 0, 0

    # Union-find over every key appearing in an override relation -> virtual families.
    parent: Dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:           # path-compress
            parent[x], x = root, parent[x]
        return root

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for ov, base in pairs:
        union(ov, base)

    families: Dict[str, set] = defaultdict(set)
    for k in list(parent):
        families[find(k)].add(k)

    fkeys = set(function_keys)
    edges_added = 0
    families_spread = 0
    for members in families.values():
        members_in = sorted(m for m in members if m in fkeys)
        if len(members_in) < 2:            # nothing to spread to (lone/external family)
            continue
        families_spread += 1
        callers = set()
        for m in members:                  # every caller of ANY family member
            callers.update(reverse_call_graph.get(m, []) or [])
        for caller in callers:
            cg = call_graph.setdefault(caller, [])
            for m in members_in:
                if m not in cg:
                    cg.append(m)
                    edges_added += 1
                rg = reverse_call_graph.setdefault(m, [])
                if caller not in rg:
                    rg.append(caller)
    return edges_added, families_spread
