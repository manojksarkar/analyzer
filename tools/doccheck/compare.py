"""The level ladder: two entity trees in, a list of findings out.

The ladder exists so a report stays readable when the two documents disagree
badly. Each rung runs only on what the rung above matched:

    L0  document shape      sections present, in order
    L1  inventory           components and units: which exist, then in what order
    L2  per unit            interfaces, header definitions, functions
    L3  per row             the fields of a matched row, by the profile's policy
    L4  dynamic behaviour   the set of interactions, and their arrows

Without that, one unmatched unit reports its forty interfaces as forty missing
rows, and the finding that mattered -- the unit -- is somewhere on page three.

A finding is never called "wrong". `missing`, `extra` and `differs` are what the
tool can see; whether a difference is a defect is a judgement, and where one of
our own documented rules explains it, `rules.py` attaches the explanation.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import match as matching
from .model import (HIGH, INFO, LOW, MEDIUM, Policy, canonical_enum,
                    is_placeholder, normalise_text)

_SEVERITY_ORDER = {HIGH: 0, MEDIUM: 1, LOW: 2, INFO: 3}


@dataclass
class Finding:
    """One thing the comparison can see. `kind` says what, `path` says where."""
    level: str
    kind: str                            # missing | extra | renamed | order | count | differs | integrity
    path: str
    summary: str
    severity: str = MEDIUM
    field: str = ""
    left: object = None
    right: object = None
    rule: str = ""                       # a documented rule that explains it

    def sort_key(self):
        return (_SEVERITY_ORDER.get(self.severity, 9), self.level, self.path, self.field)


@dataclass
class Result:
    """Everything one comparison produced."""
    findings: list = field(default_factory=list)
    matched: dict = field(default_factory=dict)      # kind -> matched count
    left_total: dict = field(default_factory=dict)
    right_total: dict = field(default_factory=dict)

    def add(self, finding):
        self.findings.append(finding)

    def by_severity(self, *levels):
        return [f for f in self.findings if f.severity in levels]

    def score(self, kind):
        """Matched share of the left document's entities of one kind, 0..1."""
        total = self.left_total.get(kind, 0)
        return 1.0 if not total else self.matched.get(kind, 0) / total


def _join(path, name):
    return "%s / %s" % (path, name) if path else name


def _values_differ(policy, left, right, aliases):
    """(differs, shown left, shown right) for one field under one policy."""
    how = policy.how
    if how == "ignore" or how == "ident":
        return False, left, right

    if how == "names":
        # A set of names, read the way every other name is read -- key rules and
        # the alias file -- so the column agrees with the entities it names.
        a = {aliases.key(x) for x in (left or [])}
        b = {aliases.key(x) for x in (right or [])}
        return a != b, sorted(left or []), sorted(right or [])

    if how == "name":
        return aliases.key(str(left or "")) != aliases.key(str(right or "")), left, right

    if how == "set":
        a = {normalise_text(x) for x in (left or [])}
        b = {normalise_text(x) for x in (right or [])}
        return a != b, sorted(left or []), sorted(right or [])

    if how == "seq":
        a = [normalise_text(x) for x in (left or [])]
        b = [normalise_text(x) for x in (right or [])]
        return a != b, list(left or []), list(right or [])

    if how == "enum":
        return None, left, right                     # handled by the caller, needs the field name

    if how == "text":
        # Advisory: two ways of writing nothing are not a difference, and two
        # different sentences are only worth a line at INFO.
        if is_placeholder(left) and is_placeholder(right):
            return False, left, right
        return normalise_text(str(left or "")) != normalise_text(str(right or "")), left, right

    # exact
    return normalise_text(str(left or "")) != normalise_text(str(right or "")), left, right


def _compare_fields(result, level, path, left, right, policies, aliases):
    """Every registered field of one matched pair."""
    for name, policy in policies.items():
        if name not in left.fields and name not in right.fields:
            continue
        a, b = left.fields.get(name), right.fields.get(name)

        if policy.how == "enum":
            ca, cb = canonical_enum(name, str(a or "")), canonical_enum(name, str(b or ""))
            differs = normalise_text(ca) != normalise_text(cb)
            shown_a, shown_b = ca, cb
        else:
            differs, shown_a, shown_b = _values_differ(policy, a, b, aliases)
            if differs is None:
                continue

        if differs:
            result.add(Finding(
                level=level, kind="differs", path=path, field=name,
                summary="%s: %s" % (policy.label, _brief(shown_a, shown_b)),
                severity=policy.severity, left=shown_a, right=shown_b,
            ))


def _brief(a, b):
    def show(v):
        if isinstance(v, (list, tuple)):
            return "[" + ", ".join(str(x) for x in v) + "]" if v else "(none)"
        s = str(v if v is not None else "")
        return s if s.strip() else "(empty)"
    return "%s -> %s" % (show(a), show(b))


def _walk(result, level_of, policies, path, left, right, aliases, depth=0):
    """Match the children of one pair, then recurse into what matched."""
    kinds = []
    for entity in list(left.children) + list(right.children):
        if entity.kind not in kinds:
            kinds.append(entity.kind)

    for kind in kinds:
        level = level_of.get(kind, "L%d" % min(depth + 1, 4))
        lefts, rights = left.of_kind(kind), right.of_kind(kind)
        result.left_total[kind] = result.left_total.get(kind, 0) + len(lefts)
        result.right_total[kind] = result.right_total.get(kind, 0) + len(rights)

        pairs, left_only, right_only = matching.match(lefts, rights, aliases)
        result.matched[kind] = result.matched.get(kind, 0) + len(pairs)

        if len(lefts) != len(rights):
            result.add(Finding(
                level=level, kind="count", path=path or "(document)",
                summary="%s count: %d -> %d" % (kind, len(lefts), len(rights)),
                severity=LOW, left=len(lefts), right=len(rights),
            ))

        for entity in left_only:
            result.add(Finding(
                level=level, kind="missing", path=_join(path, entity.name),
                summary="%s %r is in the reference and not in the other document"
                        % (kind, entity.name),
                severity=HIGH if kind in ("component", "unit") else MEDIUM,
                left=entity.name,
            ))
        for entity in right_only:
            result.add(Finding(
                level=level, kind="extra", path=_join(path, entity.name),
                summary="%s %r is in the other document and not in the reference"
                        % (kind, entity.name),
                severity=MEDIUM, right=entity.name,
            ))

        for l, r, how in pairs:
            if how == "similar":
                result.add(Finding(
                    level=level, kind="renamed", path=_join(path, l.name),
                    summary="%s %r appears as %r" % (kind, l.name, r.name),
                    severity=LOW, left=l.name, right=r.name,
                ))

        for l, r in matching.out_of_order(pairs):
            result.add(Finding(
                level=level, kind="order", path=_join(path, l.name),
                summary="%s %r sits at position %d here and %d there"
                        % (kind, l.name, l.index + 1, r.index + 1),
                severity=LOW, left=l.index + 1, right=r.index + 1,
            ))

        for l, r, _how in pairs:
            child_path = _join(path, l.name)
            _compare_fields(result, level, child_path, l, r, policies.get(kind, {}), aliases)
            _walk(result, level_of, policies, child_path, l, r, aliases, depth + 1)


def compare(left, right, profile, aliases=None):
    """Compare two extracted documents with a profile's policies."""
    result = Result()
    aliases = aliases or matching.Aliases()
    _compare_fields(result, "L0", "", left, right, profile.POLICIES.get("document", {}), aliases)
    _walk(result, profile.LEVELS, profile.POLICIES, "", left, right, aliases)
    result.findings.sort(key=lambda f: f.sort_key())
    return result


def self_checks(doc, profile):
    """Findings a single document produces on its own, as `Finding`s."""
    out = []
    for name, level, severity in (("id_integrity", "L2", HIGH),
                                  ("self_consistency", "L1", HIGH)):
        fn = getattr(profile, name, None)
        if fn is None:
            continue
        for kind, path, summary in fn(doc):
            out.append(Finding(level=level, kind="integrity", path=path,
                               summary=summary, severity=severity, field=kind))
    out.sort(key=lambda f: f.sort_key())
    return out
