"""The five levels: two entity trees in, summary rows and findings out.

Each level zooms in one step, and each checks only what the level above matched:

    L1  headings    every kind of heading is there
    L2  inventory   the same components, units and dynamic behaviours -- by count
                    AND by name
    L3  sections    per unit: the same function headings and sub-sections
    L4  views       per table and diagram: the same rows (by name), images, counts
    L5  content     what the matched rows, declarations and arrows say

Without that, one unmatched unit reports its forty interfaces as forty missing
rows, and the finding that mattered -- the unit -- is somewhere on page three.

Two outputs, because a reader needs both. A **check** is a summary row -- "units:
3 against 2, one name differs" -- and the report shows every one of them. A
**finding** is one thing that differs, with a priority (P1 blocker .. P4 cosmetic),
and the report lists them under the check they belong to.

Names are compared, not only counts: five function headings against five is still
a difference when two of the names differ. And one fact is counted once, at the
first level that sees it. A function heading only one side has is an L3 finding;
the same function's interface row at L4 is shown, marked `follows`, and not
counted again.

A finding is never called "wrong". `missing`, `extra` and `differs` are what the
tool can see; whether a difference is a defect is a judgement, and where one of
our own documented rules explains it, `rules.py` attaches the explanation.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import match as matching
from .model import (P2, P4, canonical_enum, is_placeholder, level_number, normalise_code,
                    normalise_text, priority_rank)

SIDES = ("reference", "compared document")

# What a report calls one entity of a kind.
NOUN = {"interface": "interface row", "headerdef": "header row",
        "function": "function heading", "unit": "unit", "component": "component",
        "interaction": "dynamic behaviour", "testcase": "test case", "heading": "heading"}


@dataclass
class Finding:
    """One thing that differs. `kind` says what, the location fields say where."""
    level: str
    kind: str                            # missing | extra | renamed | order | differs | integrity
    path: str
    summary: str
    priority: str = P2
    field: str = ""
    left: object = None
    right: object = None
    rule: str = ""                       # a documented rule that explains it, or may
    explained: bool = False              # the rule fully accounts for it: priority P3
    breaks: bool = False                 # the rule is the one this finding breaks
    follows: str = ""                    # counted already, as this; shown, not counted
    component: str = ""
    unit: str = ""
    view: str = ""
    item: str = ""                       # the row, function or heading it is about
    entity: str = ""                     # the entity kind it is about
    was: str = ""                        # the priority before a rule explained it

    @property
    def counted(self) -> bool:
        """Counts towards the totals: not a restatement of another finding."""
        return not self.follows

    def sort_key(self):
        return (priority_rank(self.priority), level_number(self.level), self.path, self.field)


@dataclass
class Check:
    """One summary row: something counted on both sides, and whether it agrees.

    `left` / `right` are a count, a flag or a short value. `names` is set when the
    row is a list of named things: "2 differ" even when the counts agree. `detail`
    says what differs, for a report column. `skipped` says why nothing was
    compared -- a table only one side has has no rows to compare.
    """
    level: str
    what: str
    component: str = ""
    unit: str = ""
    view: str = ""
    left: object = None
    right: object = None
    ok: bool = True
    names: str = ""
    detail: str = ""
    follows: str = ""
    skipped: str = ""
    entity: str = ""                     # the kind of entity the row counts


@dataclass
class Result:
    """Everything one comparison produced."""
    mode: str = "compare"                # compare | self | pair
    doc_type: str = ""
    sides: tuple = SIDES
    max_level: int = 5
    checks: list = field(default_factory=list)
    findings: list = field(default_factory=list)
    matched: dict = field(default_factory=dict)      # kind -> matched count
    left_total: dict = field(default_factory=dict)
    right_total: dict = field(default_factory=dict)
    self_left: list = field(default_factory=list)
    self_right: list = field(default_factory=list)
    notes: list = field(default_factory=list)        # what this check does not compare
    # (component, unit, view) -> matched entities whose L5 content was compared, so a
    # report can say "all content equal" and mean it.
    compared: dict = field(default_factory=dict)
    level_what: dict = field(default_factory=dict)   # level -> what it checks, for a report

    def add(self, finding):
        self.findings.append(finding)

    def check(self, check):
        self.checks.append(check)
        return check

    def by_priority(self, *priorities):
        return [f for f in self.findings if f.priority in priorities]

    def score(self, kind):
        """Matched share of the left document's entities of one kind, 0..1."""
        total = self.left_total.get(kind, 0)
        return 1.0 if not total else self.matched.get(kind, 0) / total


# --- comparing one field ------------------------------------------------------

def _values_differ(policy, name, left, right, aliases):
    """(differs, shown left, shown right) for one field under one policy."""
    how = policy.how
    if how in ("ignore", "ident"):
        return False, left, right

    if how == "names":
        # A set of names, read the way every other name is read -- key rules and
        # the alias file -- so the column agrees with the entities it names.
        a = {aliases.key(x) for x in (left or [])}
        b = {aliases.key(x) for x in (right or [])}
        return a != b, sorted(left or []), sorted(right or [])

    if how == "name":
        return (aliases.key(normalise_text(left)) != aliases.key(normalise_text(right)),
                left, right)

    if how == "set":
        a = {normalise_text(x) for x in (left or [])}
        b = {normalise_text(x) for x in (right or [])}
        return a != b, sorted(left or []), sorted(right or [])

    if how == "seq":
        a = [normalise_text(x) for x in (left or [])]
        b = [normalise_text(x) for x in (right or [])]
        return a != b, list(left or []), list(right or [])

    if how == "enum":
        ca, cb = canonical_enum(name, left), canonical_enum(name, right)
        return normalise_text(ca) != normalise_text(cb), ca, cb

    if how == "code":
        # A declaration, compared as code rather than as a string: see normalise_code.
        return normalise_code(left) != normalise_code(right), left, right

    if how == "text":
        # Advisory: two ways of writing nothing are not a difference, and two
        # different sentences are only worth a line at P4.
        if is_placeholder(left) and is_placeholder(right):
            return False, left, right
        return normalise_text(left) != normalise_text(right), left, right

    # exact
    return normalise_text(left) != normalise_text(right), left, right


def _brief(a, b):
    def show(v):
        if isinstance(v, (list, tuple)):
            return "[" + ", ".join(str(x) for x in v) + "]" if v else "(none)"
        s = str(v if v is not None else "")
        return s if s.strip() else "(empty)"
    return "%s -> %s" % (show(a), show(b))


def _join(path, name):
    return "%s / %s" % (path, name) if path else name


def _names_detail(left_only, right_only, renamed, limit=6):
    """`− a · + b · c → d`, cut after `limit` names."""
    parts = (["− %s" % e.name for e in left_only] + ["+ %s" % e.name for e in right_only]
             + ["%s → %s" % (l.name, r.name) for l, r in renamed])
    if len(parts) > limit:
        parts = parts[:limit] + ["and %d more" % (len(parts) - limit)]
    return " · ".join(parts)


def _names_status(n):
    return "✓" if not n else ("✗ 1 differs" if n == 1 else "✗ %d differ" % n)


# --- the walk -------------------------------------------------------------------

class _Walk:
    """One comparison: the profile, the aliases, and what it has found so far."""

    def __init__(self, result, profile, aliases):
        self.r, self.profile, self.aliases = result, profile, aliases
        self.kinds = getattr(profile, "KINDS", {})
        self.children = getattr(profile, "CHILDREN", {})
        self.follows = getattr(profile, "FOLLOWS", {})
        self.requires = getattr(profile, "FIELD_REQUIRES", {})
        # (level, component, unit, view, label) -> aggregate of one L3/L4 field over
        # many entities, turned into one Check at the end.
        self.agg = {}

    def on(self, level):
        return level_number(level) <= self.r.max_level

    # -- L1 ----------------------------------------------------------------------

    def headings(self, left, right):
        types = getattr(self.profile, "heading_types", None)
        lt = types(left) if types else (left.fields.get("headingTypes") or {})
        rt = types(right) if types else (right.fields.get("headingTypes") or {})
        known = {key: (label, prio) for key, label, prio in self.profile.HEADING_TYPES}
        order = [key for key, _l, _p in self.profile.HEADING_TYPES]
        order += sorted(k for k in set(lt) | set(rt) if k not in known)
        for key in order:
            label, prio = known.get(key, (key.split(": ", 1)[-1], P2))
            lc, rc = lt.get(key, 0), rt.get(key, 0)
            ok = (lc > 0) == (rc > 0)
            self.r.check(Check(level="L1", what=label, left=lc, right=rc, ok=ok,
                               entity="heading"))
            if ok:
                continue
            kind = "missing" if lc else "extra"
            side = SIDES[0] if lc else SIDES[1]
            self.r.add(Finding(level="L1", kind=kind, path="(document)", item=label,
                               entity="heading", priority=prio,
                               field="heading:" + key if key in known else "otherHeading",
                               left=lc or None, right=rc or None,
                               summary="heading %r is only in the %s" % (label, side)))

    # -- L2..L5 ------------------------------------------------------------------

    def walk(self, pl, pr, path="", component="", unit=""):
        for kind in self.children.get(pl.kind, ()):
            spec = self.kinds[kind]
            if not self.on(spec.level):
                continue
            lefts, rights = pl.of_kind(kind), pr.of_kind(kind)
            where = dict(component=component, unit=unit, view=spec.view, entity=kind)
            if spec.requires and not (pl.fields.get(spec.requires)
                                      and pr.fields.get(spec.requires)):
                if lefts or rights:
                    self.r.check(Check(level=spec.level, what=spec.noun, left=len(lefts),
                                       right=len(rights),
                                       skipped="the table is not on both sides", **where))
                continue
            self._list(spec, kind, lefts, rights, path, where)

    def _list(self, spec, kind, lefts, rights, path, where):
        r = self.r
        r.left_total[kind] = r.left_total.get(kind, 0) + len(lefts)
        r.right_total[kind] = r.right_total.get(kind, 0) + len(rights)
        pairs, left_only, right_only = matching.match(lefts, rights, self.aliases)
        r.matched[kind] = r.matched.get(kind, 0) + len(pairs)
        renamed = [(l, rr) for l, rr, how in pairs if how == "similar"]
        differ = len(left_only) + len(right_only) + len(renamed)

        r.check(Check(level=spec.level, what=spec.noun, left=len(lefts), right=len(rights),
                      ok=not differ, names=_names_status(differ),
                      detail=_names_detail(left_only, right_only, renamed), **where))

        # The same count BY SUB-KIND, where the entities carry one -- functions and
        # globals, defines and enums. A summary row only: the names are above.
        if spec.sub_field:
            spelled = {}
            for e in lefts + rights:
                v = (e.fields.get(spec.sub_field) or "").strip()
                if v:
                    spelled.setdefault(v.casefold(), v)
            for sk in sorted(spelled):
                la = sum(1 for e in lefts
                         if (e.fields.get(spec.sub_field) or "").strip().casefold() == sk)
                rb = sum(1 for e in rights
                         if (e.fields.get(spec.sub_field) or "").strip().casefold() == sk)
                r.check(Check(level=spec.level, what="%s · %s" % (spec.noun, spelled[sk]),
                              left=la, right=rb, ok=la == rb, follows=spec.noun,
                              **where))

        singular = spec.noun[:-1] if spec.noun.endswith("s") else spec.noun
        for entity in left_only:
            r.add(Finding(level=spec.level, kind="missing", path=_join(path, entity.name),
                          priority=spec.missing, left=entity.name, item=entity.name,
                          summary="%s %r is only in the %s" % (singular, entity.name, SIDES[0]),
                          **self._where(kind, entity, where)))
        for entity in right_only:
            r.add(Finding(level=spec.level, kind="extra", path=_join(path, entity.name),
                          priority=spec.extra, right=entity.name, item=entity.name,
                          summary="%s %r is only in the %s" % (singular, entity.name, SIDES[1]),
                          **self._where(kind, entity, where)))
        for l, rr in renamed:
            r.add(Finding(level=spec.level, kind="renamed", path=_join(path, l.name),
                          priority=P2, left=l.name, right=rr.name, item=l.name,
                          summary="%s %r appears as %r" % (singular, l.name, rr.name),
                          **self._where(kind, l, where)))
        for l, rr in matching.out_of_order(pairs):
            r.add(Finding(level=spec.level, kind="order", path=_join(path, l.name),
                          priority=P4, left=l.index + 1, right=rr.index + 1, item=l.name,
                          summary="%s %r sits at position %d here and %d there"
                                  % (singular, l.name, l.index + 1, rr.index + 1),
                          **self._where(kind, l, where)))

        for l, rr, _how in pairs:
            child = _join(path, l.name)
            loc = self._where(kind, l, where)
            self.fields(l, rr, child, loc)
            self.walk(l, rr, child, component=loc["component"], unit=loc["unit"])

    def _where(self, kind, entity, where):
        """Where one entity sits: a component and a unit name it sits under, when it
        IS one; an interaction sits under the unit it enters."""
        out = dict(where)
        if kind == "component":
            out["component"] = entity.name
        elif kind == "unit":
            out["unit"] = entity.name
        elif kind == "interaction":
            out["unit"] = entity.fields.get("unit") or out.get("unit", "")
        return out

    def fields(self, left, right, path, loc):
        """Every registered field of one matched pair, each at its own level."""
        policies = self.profile.POLICIES.get(left.kind, {})
        itself = left.kind in ("component", "unit")
        differed, views = {}, set()
        for name, policy in policies.items():
            if not self.on(policy.level):
                continue
            if name not in left.fields and name not in right.fields:
                continue
            needs = self.requires.get((left.kind, name))
            if needs and not (left.fields.get(needs) and right.fields.get(needs)):
                continue
            differs, a, b = _values_differ(policy, name, left.fields.get(name),
                                           right.fields.get(name), self.aliases)
            view = policy.view or loc.get("view", "")
            if policy.level in ("L2", "L3", "L4"):
                self._aggregate(policy, loc, view, left, a, b, differs, itself)
            else:
                views.add(view)
            if not differs:
                continue
            finding = Finding(level=policy.level, kind="differs", path=path, field=name,
                              priority=policy.priority, left=a, right=b,
                              summary="%s: %s" % (policy.label, _brief(a, b)),
                              component=loc["component"], unit=loc["unit"], view=view,
                              item="" if itself else left.name, entity=left.kind)
            differed[name] = finding
            self.r.add(finding)
        for view in views:
            key = (loc["component"], loc["unit"], view)
            self.r.compared[key] = self.r.compared.get(key, 0) + 1
        # A field that restates another one of the same entity is counted under it.
        for name, finding in differed.items():
            counted = self.follows.get((left.kind, name))
            if counted and counted in differed:
                finding.follows = "%s at %s" % (policies[counted].label,
                                                policies[counted].level)

    def _aggregate(self, policy, loc, view, entity, a, b, differs, itself):
        """Fold one L2..L4 field into the summary row for its unit and view."""
        key = (policy.level, loc["component"], loc["unit"], view, policy.label)
        slot = self.agg.get(key)
        if slot is None:
            slot = self.agg[key] = dict(left=0, right=0, n=0, bad=[], numeric=True,
                                        raw=None, entity=entity.kind)
        slot["n"] += 1
        if itself:
            slot["raw"] = (a, b)
        # A list counts as its length -- the Component/Unit table as its rows.
        a_n = len(a) if isinstance(a, (list, tuple)) else a
        b_n = len(b) if isinstance(b, (list, tuple)) else b
        numeric = all(isinstance(v, (bool, int)) for v in (a_n, b_n))
        slot["numeric"] = slot["numeric"] and numeric
        if numeric:
            slot["left"] += int(a_n)
            slot["right"] += int(b_n)
        if differs:
            slot["bad"].append(entity.name)

    def finish(self):
        for (level, component, unit, view, label), slot in self.agg.items():
            itself = slot["raw"] is not None and slot["n"] == 1
            detail = ""
            if itself and isinstance(slot["raw"][0], (list, tuple)):
                a, b = slot["raw"]
                left, right = len(a or []), len(b or [])
                ka = {normalise_text(x): x for x in a or []}
                kb = {normalise_text(x): x for x in b or []}
                parts = (["− %s" % ka[k] for k in ka if k not in kb]
                         + ["+ %s" % kb[k] for k in kb if k not in ka])
                detail = " · ".join(parts) if parts else ("order or wording" if slot["bad"] else "")
            elif itself:
                left, right = slot["raw"]
            elif slot["numeric"]:
                left, right = slot["left"], slot["right"]
            else:
                left = right = None
            bad = slot["bad"]
            if bad and not itself:
                shown = bad[:6] + (["and %d more" % (len(bad) - 6)] if len(bad) > 6 else [])
                detail = "differs in " + ", ".join(shown)
            self.r.check(Check(level=level, what=label, component=component, unit=unit,
                               view=view, left=left, right=right, ok=not bad, detail=detail,
                               entity=slot["entity"]))


def _mark_follows(result, aliases):
    """One fact, counted once: a later level restating an earlier one follows it.

    A function heading only one side has is an L3 finding; its interface row at L4 is
    the same function, and a row in the Component/Unit table is the same unit as the
    missing unit heading at L2.
    """
    first = {}
    for f in sorted(result.findings, key=lambda f: level_number(f.level)):
        if f.kind not in ("missing", "extra", "renamed") or f.follows:
            continue
        unit = "" if f.entity in ("unit", "component") else f.unit
        key = (f.component, unit, f.kind, aliases.key(f.item))
        earlier = first.get(key)
        if earlier is not None and level_number(earlier.level) < level_number(f.level):
            f.follows = "%s at %s" % (NOUN.get(earlier.entity, earlier.entity or "item"),
                                      earlier.level)
        elif earlier is None:
            first[key] = f

    # The Component/Unit table lists the units the headings are; when its difference
    # is exactly the difference in unit headings, it says the same thing twice.
    for f in result.findings:
        if f.field != "unitTableUnits" or f.kind != "differs":
            continue
        a = {aliases.key(x) for x in (f.left or [])}
        b = {aliases.key(x) for x in (f.right or [])}
        units = [g for g in result.findings
                 if g.entity == "unit" and g.component == f.component
                 and g.kind in ("missing", "extra", "renamed")]
        gone = {aliases.key(g.item) for g in units if g.kind == "missing"}
        came = {aliases.key(g.item) for g in units if g.kind == "extra"}
        for g in units:
            if g.kind == "renamed":
                gone.add(aliases.key(g.left))
                came.add(aliases.key(g.right))
        if units and a - b <= gone and b - a <= came:
            f.follows = "unit at L2"
    for c in result.checks:
        if c.what == "Component/Unit table rows" and not c.ok:
            if any(f.field == "unitTableUnits" and f.follows and f.component == c.component
                   for f in result.findings):
                c.follows = "units"


# A section flag that is the unit's own copy of a heading kind.
_FLAG_HEADING = {"hasHeaderSection": "unitheader", "hasInterfaceSection": "unitinterface"}


def mark_heading_follows(result, heading_of):
    """A later finding about a kind of heading one side has none of, follows L1.

    When a document has no function headings at all, L1 says so once; every unit's
    "function heading missing" below it is the same fact, shown but not counted.
    `heading_of` maps an entity kind to its heading kind.
    """
    absent = set()
    for f in result.findings:
        if f.level == "L1" and f.field.startswith("heading:"):
            absent.add((f.field.split(":", 1)[1], f.kind))
    if not absent:
        return
    for f in result.findings:
        if f.level == "L1" or f.follows:
            continue
        if f.kind in ("missing", "extra"):
            key = (heading_of.get(f.entity, ""), f.kind)
        elif f.kind == "differs" and f.field in _FLAG_HEADING:
            key = (_FLAG_HEADING[f.field], "missing" if f.left else "extra")
        else:
            continue
        if key in absent:
            f.follows = "heading at L1"


HEADING_OF = {"component": "component", "unit": "unit", "function": "function",
              "interaction": "interaction", "testcase": "testcase"}


def compare(left, right, profile, aliases=None, max_level=5):
    """Compare two extracted documents with a profile's policies, down to `max_level`."""
    result = Result(mode="compare", doc_type=profile.DOC_TYPE, max_level=max_level)
    aliases = aliases or matching.Aliases()
    walk = _Walk(result, profile, aliases)
    walk.headings(left, right)
    if max_level >= 2:
        walk.walk(left, right)
    walk.finish()
    _mark_follows(result, aliases)
    mark_heading_follows(result, HEADING_OF)
    result.notes = list(getattr(profile, "NOT_COMPARED", ()))
    result.level_what = dict(getattr(profile, "LEVEL_WHAT", {}))
    result.findings.sort(key=lambda f: f.sort_key())
    return result


def self_checks(doc, profile, max_level=5):
    """Findings a single document produces on its own, as `Finding`s."""
    out = []
    table = getattr(profile, "SELF_CHECKS", {})
    for name in ("id_integrity", "self_consistency"):
        fn = getattr(profile, name, None)
        if fn is None:
            continue
        for code, path, summary in fn(doc):
            level, priority, view = table.get(code, ("L5", P2, ""))
            if level_number(level) > max_level:
                continue
            parts = [p for p in (path or "").split(" / ") if p]
            out.append(Finding(
                level=level, kind="integrity", path=path, summary=summary,
                priority=priority, field=code, view=view,
                component=parts[0] if parts else "",
                unit=parts[1] if len(parts) > 1 else "",
                item=parts[2] if len(parts) > 2 else ""))
    out.sort(key=lambda f: f.sort_key())
    return out


def self_result(doc, profile, max_level=5):
    """A single document checked on its own, as a Result a report can render."""
    result = Result(mode="self", doc_type=profile.DOC_TYPE, sides=("document", ""),
                    max_level=max_level)
    result.findings = self_checks(doc, profile, max_level)
    result.level_what = dict(getattr(profile, "SELF_LEVEL_WHAT", {}) or
                             getattr(profile, "LEVEL_WHAT", {}))
    return result


__all__ = ["Finding", "Check", "Result", "compare", "self_checks", "self_result",
           "mark_heading_follows"]
