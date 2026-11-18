"""Calls through a function pointer: which functions each one can reach (review SWE3-V5-02).

A call through a pointer names a SLOT, not a function -- a struct field (`ops->read(lba)`), a
variable (`fp(x)`, `table[i](x)`) or a parameter (`cb(x)`) -- so libclang resolves it to that
field or variable and the call graph had no edge for it. Phase 1 now records two facts:

  stores  (site_file, slot, value)  a value put into a slot: `fn:<function>`, or `slot:<slot>`
                                    when one slot is copied into another (`o->read = d.k`,
                                    an argument passed for a function-pointer parameter)
  calls   (caller, slot)            a call through that slot

and a call through a slot is linked to every function any store, anywhere, can put there
(SWE3_WIKI SWE3-UI-01). By slot, not by object: `a.read` and `b.read` are one slot, the field
`read` of their struct type. Over-approximate in the same direction as the virtual-dispatch
spread: it links more, never fewer.

Pure -- the two call-graph dicts are mutated in place, no globals -- so the full parse
(`parser.build_metadata`) and the narrowed-parse merge (`parse_merge`) share it.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Sequence, Set, Tuple

FN = "fn:"
SLOT = "slot:"


def slot_contents(stores: Iterable[Sequence[str]]) -> Dict[str, Set[str]]:
    """{slot -> the functions it can hold}, following slot-to-slot copies to a fixpoint."""
    direct: Dict[str, Set[str]] = defaultdict(set)
    copies: Dict[str, Set[str]] = defaultdict(set)
    for store in stores:
        if len(store) < 3:
            continue
        _site, slot, value = store[0], store[1], store[2]
        if value.startswith(FN):
            direct[slot].add(value[len(FN):])
        elif value.startswith(SLOT):
            src = value[len(SLOT):]
            if src != slot:
                copies[slot].add(src)
    holds: Dict[str, Set[str]] = {s: set(v) for s, v in direct.items()}
    changed = True
    while changed:
        changed = False
        for dst, srcs in copies.items():
            cur = holds.setdefault(dst, set())
            before = len(cur)
            for src in srcs:
                cur |= holds.get(src, set())
            if len(cur) != before:
                changed = True
    return holds


def link_pointer_calls(call_graph: Dict[str, List[str]],
                       reverse_call_graph: Dict[str, List[str]],
                       stores: Iterable[Sequence[str]],
                       calls: Iterable[Sequence[str]],
                       valid: Set[str]) -> List[Tuple[str, str]]:
    """Add caller -> target for every call through a slot; return the edges ADDED.

    Only edges the graph did not already have are returned: those are the ones a later
    narrowed-parse merge must take back out before it links again (a direct call to the same
    function is not the pointer's to remove). A function reaching itself is skipped, as the
    address-taken edges skip it.
    """
    holds = slot_contents(stores)
    added: List[Tuple[str, str]] = []
    for call in sorted({(c[0], c[1]) for c in calls if len(c) >= 2}):
        caller, slot = call
        if caller not in valid:
            continue
        for target in sorted(holds.get(slot, ())):
            if target == caller or target not in valid:
                continue
            callees = call_graph.setdefault(caller, [])
            if target in callees:
                continue
            callees.append(target)
            callers = reverse_call_graph.setdefault(target, [])
            if caller not in callers:
                callers.append(caller)
            added.append((caller, target))
    return added


def strip_edges(call_graph: Dict[str, List[str]], edges: Iterable[Sequence[str]]) -> None:
    """Take pointer edges back out of `call_graph` (callsIds only; the caller recomputes the
    reverse side)."""
    for edge in edges:
        if len(edge) < 2:
            continue
        callees = call_graph.get(edge[0])
        if callees and edge[1] in callees:
            callees.remove(edge[1])
