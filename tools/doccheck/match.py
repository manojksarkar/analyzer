"""Deciding which thing on the left is which thing on the right.

Everything the comparison says depends on this step. Two lists compared by
position report a single inserted unit as "every unit below it changed", which is
the failure mode of a line diff and the reason this tool exists.

So: match by key, then by similarity, then leave the rest unmatched. Order is
worked out afterwards, from the matched pairs, and reported separately -- a
reordered table is cosmetic, a missing row is not, and folding the two together
buries the one that matters.
"""
from __future__ import annotations

from difflib import SequenceMatcher

from .model import normalise_key

# Below this, two names are different names. Chosen so `FtlSetEntry` matches
# `FtlSetEntries` (0.93) but not `FtlGetEntry` (0.81) -- a rename is worth
# reporting as a rename, a different unit is not.
SIMILARITY = 0.86

# A ratio alone is unfair to short names: one character added to `Lib` scores
# 0.857 and fails, while the same edit on `FtlSetEntry` scores 0.917 and passes.
# So a suffix change is accepted outright -- `Lib`/`Libs`, `Map`/`Map2` -- while
# a changed letter *inside* a short name stays a different name, which is what
# keeps `Hub`/`Hug` and `Map`/`Max` apart.
SUFFIX_SLACK = 2


class Aliases:
    """Name pairs a human has settled, so a run's noise decays over time.

    Two documents can be right and still disagree about a name -- a different
    granularity, an agreed abbreviation, a unit the client splits in two. There
    is no algorithm for that; there is a file, kept next to the project, and read
    here.
    """

    def __init__(self, pairs=None):
        self.map = {}
        for left, right in (pairs or []):
            self.map[normalise_key(left)] = normalise_key(right)

    @classmethod
    def load(cls, path):
        """One `left = right` per line; `#` starts a comment."""
        pairs = []
        if not path:
            return cls(pairs)
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.split("#", 1)[0].strip()
                if not line or "=" not in line:
                    continue
                left, right = line.split("=", 1)
                pairs.append((left.strip(), right.strip()))
        return cls(pairs)

    def key(self, name) -> str:
        k = normalise_key(name)
        return self.map.get(k, k)

    def __len__(self):
        return len(self.map)


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _suffix_change(a: str, b: str) -> bool:
    """True when one name is the other with a short suffix added or removed."""
    if not a or not b or a == b:
        return False
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    return longer.startswith(shorter) and (len(longer) - len(shorter)) <= SUFFIX_SLACK


def looks_renamed(a: str, b: str) -> bool:
    """Whether two keys are the same thing under two names."""
    return _suffix_change(a, b) or _similar(a, b) >= SIMILARITY


def match(left, right, aliases=None):
    """Pair up two lists of entities.

    Returns (pairs, left_only, right_only), where a pair is
    (left entity, right entity, how) and `how` is 'key' or 'similar'.
    """
    aliases = aliases or Aliases()
    pairs = []

    by_key = {}
    for entity in right:
        by_key.setdefault(aliases.key(entity.name), []).append(entity)

    unmatched_left = []
    for entity in left:
        bucket = by_key.get(aliases.key(entity.name))
        if bucket:
            pairs.append((entity, bucket.pop(0), "key"))
        else:
            unmatched_left.append(entity)

    leftovers = [e for bucket in by_key.values() for e in bucket]

    # Second pass: a near-miss is a rename worth naming, not a delete plus an add.
    still_left, used = [], set()
    for entity in unmatched_left:
        key = aliases.key(entity.name)
        best, score = None, 0.0
        for candidate in leftovers:
            if id(candidate) in used:
                continue
            other = aliases.key(candidate.name)
            if not looks_renamed(key, other):
                continue
            # Among the candidates that could be a rename, take the closest.
            s = 1.0 if _suffix_change(key, other) else _similar(key, other)
            if s > score:
                best, score = candidate, s
        if best is not None:
            used.add(id(best))
            pairs.append((entity, best, "similar"))
        else:
            still_left.append(entity)

    right_only = [e for e in leftovers if id(e) not in used]

    # Keep the report in the left document's reading order.
    order = {id(e): i for i, e in enumerate(left)}
    pairs.sort(key=lambda p: order.get(id(p[0]), 0))
    return pairs, still_left, right_only


def _longest_increasing(seq):
    """Indices of a longest strictly-increasing subsequence (patience sorting)."""
    if not seq:
        return []
    tails, tails_idx, prev = [], [], [-1] * len(seq)
    for i, value in enumerate(seq):
        lo, hi = 0, len(tails)
        while lo < hi:
            mid = (lo + hi) // 2
            if tails[mid] < value:
                lo = mid + 1
            else:
                hi = mid
        if lo == len(tails):
            tails.append(value)
            tails_idx.append(i)
        else:
            tails[lo] = value
            tails_idx[lo] = i
        prev[i] = tails_idx[lo - 1] if lo > 0 else -1
    out, k = [], tails_idx[-1]
    while k >= 0:
        out.append(k)
        k = prev[k]
    return list(reversed(out))


def out_of_order(pairs):
    """The matched entities that had to move, as (left, right) pairs.

    The minimal set: everything outside a longest increasing run of the right-hand
    positions. Reporting "these two moved" beats reporting "these forty differ"
    when two rows were swapped.
    """
    if len(pairs) < 2:
        return []
    right_pos = {id(r): i for i, (_, r, _) in enumerate(sorted(pairs, key=lambda p: p[1].index))}
    seq = [right_pos[id(r)] for _, r, _ in pairs]
    keep = set(_longest_increasing(seq))
    return [(l, r) for i, (l, r, _) in enumerate(pairs) if i not in keep]
