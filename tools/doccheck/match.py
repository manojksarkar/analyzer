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

# A rename changes the *end* of a name. A similarity ratio does not know that,
# and gets both interesting cases wrong: `FtlSetEntry`/`FtlGetEntry` scores 0.91
# and would be paired -- two different functions, whose fields would then be
# reported as differing -- while `FtlSetEntry`/`FtlSetEntries` scores 0.83 and
# would not be. Pairing two different things is the more expensive mistake, so
# the rule is about where the difference sits, not how much of it there is:
#
#   most of the shorter name must be a shared prefix ...
PREFIX_SHARE = 0.7
#   ... and what follows it must be short.
TAIL_SLACK = 3


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

    def of(self, entity) -> str:
        """The matching key of an entity.

        An entity may carry a key of its own -- a fixed section keys to its
        canonical name, so `Introduction and Purpose` matches `Introduction`.
        Going back to the name here would throw that away.
        """
        k = entity.match_key()
        return self.map.get(k, k)

    def __len__(self):
        return len(self.map)


def _common_prefix(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def _similar(a: str, b: str) -> float:
    """How alike two names are, used only to pick the best of several candidates."""
    return SequenceMatcher(None, a, b).ratio()


def looks_renamed(a: str, b: str) -> bool:
    """Whether two keys are the same thing under two names.

    `Lib`/`Libs` and `FtlSetEntry`/`FtlSetEntries` are renames; `Hub`/`Hug`,
    `Map`/`Max` and `FtlSetEntry`/`FtlGetEntry` are different names, and
    `Main`/`MainLoop` adds too much to call it a rename.
    """
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    prefix = _common_prefix(shorter, longer)
    if prefix < max(3, PREFIX_SHARE * len(shorter)):
        return False
    return (len(longer) - prefix) <= TAIL_SLACK


def match(left, right, aliases=None):
    """Pair up two lists of entities.

    Returns (pairs, left_only, right_only), where a pair is
    (left entity, right entity, how) and `how` is 'key' or 'similar'.
    """
    aliases = aliases or Aliases()
    pairs = []

    by_key = {}
    for entity in right:
        by_key.setdefault(aliases.of(entity), []).append(entity)

    unmatched_left = []
    for entity in left:
        bucket = by_key.get(aliases.of(entity))
        if bucket:
            pairs.append((entity, bucket.pop(0), "key"))
        else:
            unmatched_left.append(entity)

    leftovers = [e for bucket in by_key.values() for e in bucket]

    # Second pass: a near-miss is a rename worth naming, not a delete plus an add.
    still_left, used = [], set()
    for entity in unmatched_left:
        key = aliases.of(entity)
        best, score = None, 0.0
        for candidate in leftovers:
            if id(candidate) in used:
                continue
            other = aliases.of(candidate)
            if not looks_renamed(key, other):
                continue
            # Among the candidates that could be a rename, take the closest.
            s = _similar(key, other)
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
