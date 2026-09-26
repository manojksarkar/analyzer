"""The V-model pairing: a SWE.3 document against its SWE.4 document, level by level.

This is a different question from comparing two versions of the same document.
Here the two documents are *different documents about the same code*, and both
wikis state how they must line up:

- `SWE4_WIKI.md`, 'Who gets a spec' -- every function in the SWE.3 detailed design
  gets a spec, **except** public functions defined in a header, which are covered
  through their own unit's callers.
- `SWE4_WIKI.md`, 'Dynamic Behaviour test specs' -- a dynamic-behaviour spec exists
  **exactly** where SWE.3 draws a behaviour diagram. The two pair one-to-one.
- `SWE4_WIKI.md`, 'Table B' -- a Test Case ID is `TC_<interfaceId>`, so the SWE.4
  id and the SWE.3 id are the same string with three characters in front.

The levels read the same as in a comparison of two documents of one type:

    L1  headings    each SWE.3 heading kind has its SWE.4 counterpart
    L2  inventory   the same components and units; behaviour diagrams against
                    interaction specs, one to one
    L3  sections    per unit: function headings against test case headings
    L4  views       per unit: the interface table's Function rows against test
                    cases; per interaction: call arrows against cross-unit calls
    L5  content     Test Case ID = TC_ + Interface ID; every call arrow has its
                    cross-unit step; headings printed the same

SWE.3 is the input to SWE.4, and the check reads one way. Something only the
design has is a coverage gap -- it may be allowed (a header-defined function gets no
spec), so it is P2, for a person to judge. Something only the spec has was invented
by the spec: P1, whatever the level. The same holds for the ids: the spec takes the
design's numbers, so a design function with no spec leaves a gap in the spec's
Test Case IDs, and that gap is explained, not a defect.

The design is read twice for what it promises a test for: its function headings (L3) and its interface table (L4). A function
that has both and no spec is one finding, at L3; the L4 one follows from it. One
with a row and no heading is found at L4 alone.

None of that needs the source code, a model file or a pipeline run: it is all
printed in the two documents. Which makes it checkable at a client's desk, on a
pair of documents that came back from review.
"""
from __future__ import annotations

import re

from . import match as matching, swe3, swe4
from .compare import (Check, Finding, Result, _mark_follows, _names_detail, _names_status,
                      mark_heading_follows)
from .model import P1, P2, P3, P4, normalise_key, normalise_text

WIKI3 = "docs/spec/SWE3_WIKI.md"
WIKI4 = "docs/spec/SWE4_WIKI.md"
SIDES = ("design", "specification")
DOC_TYPE = "SWE.3 ↔ SWE.4"

# SWE.3 heading kind -> its SWE.4 counterpart. `Dynamic Behaviour` itself is left
# out: SWE.3 always writes the heading, SWE.4 only when there is something under it.
HEADING_MAP = (
    ("component", "component", "<Component>", P1),
    ("unit", "unit", "<Unit>", P1),
    ("function", "testcase", "<Unit>-<Function>  ↔  test case", P1),
    ("interaction", "interaction", "behaviour diagram  ↔  interaction spec", P1),
)

LEVEL_WHAT = {
    "L1": "each SWE.3 heading kind has its SWE.4 counterpart",
    "L2": "the same components and units; behaviour diagrams ↔ interaction specs, one to one",
    "L3": "per unit: function headings ↔ test case headings (count and names)",
    "L4": "per unit: interface Function rows ↔ test cases; per interaction: call arrows ↔ "
          "cross-unit calls (counts and names)",
    "L5": "Test Case ID = TC_ + Interface ID; every call arrow has its cross-unit step; "
          "headings printed the same",
}

_RULE_SPEC = ("every function in the detailed design gets a spec, except a public function "
              "defined in a header, which is covered through its own unit's callers (%s, "
              "'Who gets a spec'). Neither document says where a function is defined, so this "
              "needs a look at the code to settle" % WIKI4)
_RULE_EXTRA = ("every function with a spec should appear in the detailed design (%s, 'Who "
               "gets a spec'); a spec for something the design does not publish is a test for "
               "an interface nobody is told about" % WIKI4)
_RULE_NAMES = ("the design keeps the class in front of a method because that is what tells "
               "two same-named methods apart (%s, 'Names'); a specification that drops it "
               "cannot tell them apart" % WIKI3)
_RULE_HEADING = ("a spec is headed as the design entry it tests: `<Unit>-<Function>` for a "
                 "function, the behaviour diagram's own heading for an interaction (%s, 'What "
                 "is produced'; %s, 'Names')" % (WIKI4, WIKI3))
_RULE_ROW = ("every function in the detailed design gets a spec (%s, 'Who gets a spec'); the "
             "interface table is the design's list of public functions, so each Function row "
             "is a spec owed -- except a public function defined in a header" % WIKI4)
_RULE_ROW_ONLY = ("a public function is a row in the interface table AND a flowchart entry "
                  "(%s, 'N.1.5', 'N.1.6'); this one is a row only, so the design is at odds "
                  "with itself -- see the design's own check" % WIKI3)
_RULE_CALLS = ("an interaction spec executes every unit the diagram shows, and its Expected "
               "Results name one entry per cross-unit call (%s, 'Dynamic Behaviour test specs', "
               "'The tables'); an arrow with no call, or a call with no arrow, means the two "
               "describe different interactions" % WIKI4)
_RULE_PAIR = ("a dynamic-behaviour spec exists exactly where SWE.3 draws a behaviour diagram; "
              "the two pair one to one (%s, 'Dynamic Behaviour test specs'). They are two "
              "settings -- behaviourDiagram and dynamicBehaviourSpecs -- so a run with one "
              "on and the other off breaks the pairing" % WIKI4)


def _bare(name):
    """`SignalProcessor::normalize` -> `normalize`."""
    return normalise_key(str(name).split("::")[-1])


def _interaction_key(entity):
    """The four names a behaviour heading carries, as a comparable key."""
    f = entity.fields
    if not f.get("unit"):
        return (normalise_key(entity.name),)
    return (normalise_key(f.get("unit", "")), normalise_key(f.get("function", "")),
            normalise_key(f.get("callerUnit", "")), normalise_key(f.get("callerFunction", "")))


def _specced(unit):
    """Design functions a spec is expected for, as its sections say: function headings."""
    return unit.of_kind("function")


def _rows(unit):
    """Design functions a spec is expected for, as its interface table says."""
    return [r for r in unit.of_kind("interface")
            if (r.fields.get("interfaceType") or "").casefold().startswith("func")]


def _expects_spec(unit):
    return bool(_specced(unit) or _rows(unit))


# `A calls B`, `A calls B to <reason>` -- a Behavior Description bullet
# (`behaviour_diagram/mermaid_builder.py`). Returns are not calls.
_ARROW_RE = re.compile(r"^\s*(?P<caller>\S+)\s+calls\s+(?:[A-Za-z_][\w-]*\.)?"
                       r"(?P<callee>[A-Za-z_~][\w:~]*)")
# `<Unit> calls <Unit>.<function>` in a step, `Successfully called <Unit>.<function>` in an
# expected result (`views/test_steps.py`). A mock leaves the component, the diagram does
# not draw it, and it is left out.
_CALLED_RE = re.compile(r"(?:successfully called|\bcalls)\s+(?!mock\b)"
                        r"(?:[A-Za-z_][\w-]*\.)?(?P<f>[A-Za-z_~][\w:~]*)", re.IGNORECASE)


# A function a spec names: `utilAbs()`, `Unit.fn`, `Class::method()`.
_NAMED_RE = re.compile(r"(?:\b[A-Za-z_][\w-]*\.)?([A-Za-z_~][\w:~]*)\s*\(")


def _spec_mentions(spec):
    """{bare name: [(unit, test case, a mock?)]} -- every function a spec's text names.

    SWE4_WIKI 'Who gets a spec': a public function defined in a header gets no spec of
    its own; its own unit's callers run it inline, and a caller in another unit mocks
    it. Either leaves the function's name in some other spec, which is the evidence
    the documents can offer that its missing spec is that rule at work.
    """
    out = {}
    for component in spec.of_kind("component"):
        holders = [(u.name, c) for u in component.of_kind("unit") for c in u.of_kind("testcase")]
        holders += [(ia.fields.get("unit", ""), ia) for ia in component.of_kind("interaction")]
        for unit_name, case in holders:
            for field in ("precondition", "testSteps", "expected"):
                for line in case.fields.get(field) or []:
                    mock = "mock" in line.casefold()
                    for m in _NAMED_RE.finditer(line):
                        out.setdefault(_bare(m.group(1)), []).append((unit_name, case.name, mock))
    return out


def _design_calls(ia):
    """{bare callee: as written} for the call arrows of one behaviour, bar the entry."""
    target = _bare(ia.fields.get("function", ""))
    out = {}
    for arrow in ia.fields.get("arrows") or []:
        m = _ARROW_RE.match(arrow)
        if m and _bare(m.group("callee")) != target:
            out.setdefault(_bare(m.group("callee")), m.group("callee"))
    return out


def _spec_calls(ia):
    """{bare function: as written} for the cross-unit calls an interaction spec makes."""
    out = {}
    for line in (ia.fields.get("expected") or []) + (ia.fields.get("testSteps") or []):
        if "mock" in line.casefold():
            continue
        for m in _CALLED_RE.finditer(line):
            out.setdefault(_bare(m.group("f")), m.group("f"))
    return out


def _pair_by_bare_name(functions, cases):
    """Pair the leftovers that differ only by the class qualifier.

    SWE.3 prints a method with its class in front, because that is what tells two
    same-named methods apart. When SWE.4 prints the bare name, the same function
    appears once as a design entry with no spec and once as a spec with no design
    entry. Reporting that as two findings hides what it is -- one function, two
    names -- so the pair is found here and reported once.

    A bare name claimed by more than one entry on either side is the collision the
    qualifier exists to prevent -- `AddOperation::apply` and `MultiplyOperation::apply`
    both go to `apply`. Guessing which spec belongs to which method would invent an
    answer, so neither is paired and the ambiguity is reported instead.
    """
    by_bare_l, by_bare_r = {}, {}
    for f in functions:
        by_bare_l.setdefault(_bare(f.name), []).append(f)
    for c in cases:
        by_bare_r.setdefault(_bare(c.name), []).append(c)
    pairs, ambiguous = [], []
    for bare, lefts in by_bare_l.items():
        rights = by_bare_r.get(bare) or []
        if not rights:
            continue
        if len(lefts) > 1 or len(rights) > 1:
            ambiguous.append((bare, lefts, rights))
        else:
            pairs.append((lefts[0], rights[0]))
    return pairs, ambiguous


class _Pair:
    def __init__(self, result):
        self.r = result
        self.aliases = matching.Aliases()

    def on(self, n):
        return n <= self.r.max_level

    def add(self, **kw):
        self.r.add(Finding(**kw))

    # -- L1 ----------------------------------------------------------------------

    def headings(self, design, spec):
        dt, st = swe3.heading_types(design), swe4.heading_types(spec)
        for k3, k4, label, prio in HEADING_MAP:
            d, s = dt.get(k3, 0), st.get(k4, 0)
            ok = (d > 0) == (s > 0)
            self.r.check(Check(level="L1", what=label, left=d, right=s, ok=ok, entity="heading"))
            if ok:
                continue
            kind = "missing" if d else "extra"
            if k3 == "interaction":
                rule, breaks = _RULE_PAIR, True
            elif kind == "missing":
                rule, breaks = _RULE_SPEC, False
            else:
                rule, breaks = _RULE_EXTRA, True
            self.add(level="L1", kind=kind, path="(document)", item=label, entity="heading",
                     field="heading:" + k3, priority=P2 if kind == "missing" else prio,
                     left=d or None, right=s or None,
                     rule=rule, breaks=breaks,
                     summary="%s headings are in the %s and not in the %s"
                             % (label, SIDES[0] if d else SIDES[1], SIDES[1] if d else SIDES[0]))

    # -- L2 ----------------------------------------------------------------------

    def inventory(self, design, spec):
        wanted = [c for c in design.of_kind("component")
                  if any(_expects_spec(u) for u in c.of_kind("unit")) or c.of_kind("interaction")]
        quiet = len(design.of_kind("component")) - len(wanted)
        comps = spec.of_kind("component")
        pairs, left_only, right_only = matching.match(wanted, comps, self.aliases)
        differ = len(left_only) + len(right_only) + sum(1 for *_x, h in pairs if h == "similar")
        self.r.check(Check(level="L2", what="components", left=len(wanted), right=len(comps),
                           ok=not differ, names=_names_status(differ),
                           detail=_names_detail(left_only, right_only,
                                                [(l, r) for l, r, h in pairs if h == "similar"]),
                           skipped=("%d design component(s) with no function heading: no spec "
                                    "expected" % quiet) if quiet else "", entity="component"))
        for c in left_only:
            self.add(level="L2", kind="missing", path=c.name, component=c.name, item=c.name,
                     entity="component", priority=P2, rule=_RULE_SPEC,
                     summary="component %r has function headings in the design and no section "
                             "in the specification" % c.name)
        for c in right_only:
            self.add(level="L2", kind="extra", path=c.name, component=c.name, item=c.name,
                     entity="component", priority=P1, rule=_RULE_EXTRA, breaks=True,
                     summary="component %r is specified but not in the design" % c.name)
        for dc, sc, how in pairs:
            if how == "similar":
                self.add(level="L2", kind="renamed", path=dc.name, component=dc.name,
                         item=dc.name, entity="component", priority=P2, left=dc.name,
                         right=sc.name,
                         summary="component %r appears as %r" % (dc.name, sc.name))
            if self.on(5):
                self.heading_text(dc.name, "", dc, sc, "", "component",
                                  follows="component name at L2" if how == "similar" else "")
            self.component(dc, sc)

    def component(self, dc, sc):
        name = dc.name
        # Units: every design unit with a function heading has a spec section.
        wanted = [u for u in dc.of_kind("unit") if _expects_spec(u)]
        quiet = len(dc.of_kind("unit")) - len(wanted)
        units = sc.of_kind("unit")
        pairs, left_only, right_only = matching.match(wanted, units, self.aliases)
        renamed = [(l, r) for l, r, h in pairs if h == "similar"]
        differ = len(left_only) + len(right_only) + len(renamed)
        self.r.check(Check(level="L2", what="units", component=name, left=len(wanted),
                           right=len(units), ok=not differ, names=_names_status(differ),
                           detail=_names_detail(left_only, right_only, renamed),
                           skipped=("%d design unit(s) with no function heading: no spec "
                                    "expected" % quiet) if quiet else "", entity="unit"))
        for u in left_only:
            self.add(level="L2", kind="missing", path="%s / %s" % (name, u.name), component=name,
                     unit=u.name, item=u.name, entity="unit", priority=P2, rule=_RULE_SPEC,
                     summary="unit %r has %d function heading(s) in the design and no section in "
                             "the specification" % (u.name, len(_specced(u))))
        for u in right_only:
            self.add(level="L2", kind="extra", path="%s / %s" % (name, u.name), component=name,
                     unit=u.name, item=u.name, entity="unit", priority=P1, rule=_RULE_EXTRA, breaks=True,
                     summary="unit %r is specified but has no function heading in the design"
                             % u.name)
        for du, su in renamed:
            self.add(level="L2", kind="renamed", path="%s / %s" % (name, du.name),
                     component=name, unit=du.name, item=du.name, entity="unit", priority=P2,
                     left=du.name, right=su.name,
                     summary="unit %r appears as %r" % (du.name, su.name))

        # Behaviour diagrams against interaction specs: one to one, no exception.
        d_ia = {_interaction_key(ia): ia for ia in dc.of_kind("interaction")}
        s_ia = {_interaction_key(ia): ia for ia in sc.of_kind("interaction")}
        gone = [d_ia[k] for k in d_ia if k not in s_ia]
        came = [s_ia[k] for k in s_ia if k not in d_ia]
        self.r.check(Check(level="L2", what="behaviour diagrams ↔ interaction specs",
                           component=name, left=len(d_ia), right=len(s_ia),
                           ok=not (gone or came), names=_names_status(len(gone) + len(came)),
                           detail=_names_detail(gone, came, []), view="Dynamic Behaviour",
                           entity="interaction"))
        for ia in gone:
            self.add(level="L2", kind="missing", path="%s / %s" % (name, ia.name), component=name,
                     unit=ia.fields.get("unit", ""), item=ia.name, entity="interaction",
                     view="Dynamic Behaviour", priority=P2, rule=_RULE_PAIR, breaks=True,
                     summary="the design draws this behaviour diagram and the specification has "
                             "no interaction spec for it")
        for ia in came:
            self.add(level="L2", kind="extra", path="%s / %s" % (name, ia.name), component=name,
                     unit=ia.fields.get("unit", ""), item=ia.name, entity="interaction",
                     view="Dynamic Behaviour", priority=P1, rule=_RULE_PAIR, breaks=True,
                     summary="the specification has an interaction spec the design draws no "
                             "diagram for")

        if self.on(3):
            for du, su, how in pairs:
                self.unit(name, du, su)
                if self.on(4):
                    self.rows(name, du, su)
                if self.on(5):
                    self.heading_text(name, du.name, du, su, "", "unit",
                                      follows="unit name at L2" if how == "similar" else "")
        for key, dia in d_ia.items():
            sia = s_ia.get(key)
            if sia is None:
                continue
            if self.on(4):
                self.calls(name, dia, sia)
            if self.on(5):
                self.heading_text(name, dia.fields.get("unit", ""), dia, sia,
                                  "Dynamic Behaviour", "interaction")

    # -- L3 / L5 -----------------------------------------------------------------

    def unit(self, component, du, su):
        path = "%s / %s" % (component, du.name)
        functions, cases = _specced(du), su.of_kind("testcase")
        pairs, left_only, right_only = matching.match(functions, cases, self.aliases)
        pairs = [(l, r) for l, r, _h in pairs]
        bare_pairs, ambiguous = _pair_by_bare_name(left_only, right_only)
        paired_l = {id(l) for l, _r in bare_pairs} | {id(f) for _b, ls, _rs in ambiguous for f in ls}
        paired_r = {id(r) for _l, r in bare_pairs} | {id(c) for _b, _ls, rs in ambiguous for c in rs}
        left_only = [f for f in left_only if id(f) not in paired_l]
        right_only = [c for c in right_only if id(c) not in paired_r]
        differ = len(left_only) + len(right_only) + len(bare_pairs) + len(ambiguous)
        self.r.check(Check(level="L3", what="function headings ↔ test cases",
                           component=component, unit=du.name, left=len(functions),
                           right=len(cases), ok=not differ, names=_names_status(differ),
                           detail=_names_detail(left_only, right_only, bare_pairs),
                           view="test cases", entity="testcase"))

        where = dict(component=component, unit=du.name, view="test cases")
        rows = {normalise_key(r.name): r for r in _rows(du)}
        for f in left_only:
            priority, rule = self.inline_reason(du, f, rows.get(normalise_key(f.name)))
            self.add(level="L3", kind="missing", path="%s / %s" % (path, f.name), item=f.name,
                     entity="testcase", priority=priority, rule=rule, field="spec",
                     explained=priority == P3, was=P2 if priority == P3 else "",
                     summary="the design has the function heading %r and the specification has "
                             "no test case for it" % f.name, **where)
        rows = {normalise_key(r.name) for r in _rows(du)}
        for c in right_only:
            if normalise_key(c.name) in rows:
                # The design still publishes it -- in its interface table -- and has lost only
                # the flowchart entry. The spec follows the design's list of functions; the
                # design disagrees with itself (its own check: row-without-heading).
                self.add(level="L3", kind="extra", path="%s / %s" % (path, c.name), item=c.name,
                         entity="testcase", priority=P2, rule=_RULE_ROW_ONLY, field="spec",
                         summary="the specification has a test case for %r, which the design "
                                 "lists in its interface table but gives no flowchart entry"
                                 % c.name, **where)
                continue
            self.add(level="L3", kind="extra", path="%s / %s" % (path, c.name), item=c.name,
                     entity="testcase", priority=P1, rule=_RULE_EXTRA, breaks=True, field="spec",
                     summary="the specification has a test case for %r, which the design has no "
                             "function heading for" % c.name, **where)
        for f, c in bare_pairs:
            self.add(level="L3", kind="renamed", path="%s / %s" % (path, f.name), item=f.name,
                     entity="testcase", priority=P2, field="functionName", left=f.name,
                     right=c.name, rule=_RULE_NAMES, breaks=True,
                     summary="the design calls this function %r and the specification calls it "
                             "%r" % (f.name, c.name), **where)
        for bare, lefts, rights in ambiguous:
            names = sorted(f.name for f in lefts)
            self.add(level="L3", kind="integrity", path="%s / %s" % (path, bare), item=bare,
                     entity="testcase", priority=P1, field="ambiguousPairing", left=names,
                     right=sorted(c.name for c in rights), rule=_RULE_NAMES, breaks=True,
                     summary="%s cannot be paired: %s all reduce to the same bare name in the "
                             "specification" % (bare, ", ".join(names)), **where)

        if not self.on(5):
            return
        rows = {normalise_key(i.name): i for i in du.of_kind("interface")}
        if pairs or bare_pairs:
            key = (component, du.name, "test cases")
            self.r.compared[key] = self.r.compared.get(key, 0) + len(pairs) + len(bare_pairs)
        for f, c in pairs + bare_pairs:
            self.test_case_id(path, where, f, c, rows.get(normalise_key(f.name)))
            renamed = (f, c) in bare_pairs
            self.heading_text(component, du.name, f, c, "test cases", "testcase",
                              follows="function name at L3" if renamed else "")

    def inline_reason(self, du, func, row):
        """(priority, rule) for a design function the spec has no test case for.

        A public function defined in a header -- inline -- is in the design because a
        unit calls it, and gets no spec of its own. Where the spec shows it mocked by a
        caller, or run inside its own unit's specs, that is the rule at work: explained.
        Otherwise the documents cannot tell a header function from a forgotten spec:
        P2, naming the callers so the reader knows where to look.
        """
        hits = [h for h in self.mentions.get(_bare(func.name), [])
                if normalise_key(h[1]) != normalise_key(func.name)]
        if hits:
            unit_name, case, mock = hits[0]
            how = ("mocked by %s's spec for %s" % (unit_name, case) if mock
                   else "run inside %s's spec for %s" % (unit_name, case))
            more = " and %d more" % (len(hits) - 1) if len(hits) > 1 else ""
            return P3, ("a public function defined in a header gets no spec of its own; the "
                        "specification shows this one %s%s (%s, 'Who gets a spec')"
                        % (how, more, WIKI4))
        callers = ", ".join((row.fields.get("sourceDest") or []) if row is not None else [])
        called = " It is called from %s." % callers if callers else ""
        return P2, (_RULE_SPEC + "." + called)

    def rows(self, component, du, su):
        """L4: the interface table's Function rows against the test cases.

        The same function missing a heading AND a spec was found at L3; its row
        follows from that finding. A row with no heading and no spec is found here.
        """
        path = "%s / %s" % (component, du.name)
        rows, cases = _rows(du), su.of_kind("testcase")
        pairs, left_only, right_only = matching.match(rows, cases, self.aliases)
        bare_pairs, ambiguous = _pair_by_bare_name(left_only, right_only)
        paired_l = {id(l) for l, _r in bare_pairs} | {id(f) for _b, ls, _rs in ambiguous for f in ls}
        paired_r = {id(r) for _l, r in bare_pairs} | {id(c) for _b, _ls, rs in ambiguous for c in rs}
        left_only = [r for r in left_only if id(r) not in paired_l]
        right_only = [c for c in right_only if id(c) not in paired_r]
        differ = len(left_only) + len(right_only) + len(bare_pairs) + len(ambiguous)
        self.r.check(Check(level="L4", what="interface Function rows ↔ test cases",
                           component=component, unit=du.name, left=len(rows), right=len(cases),
                           ok=not differ, names=_names_status(differ),
                           detail=_names_detail(left_only, right_only, bare_pairs),
                           view="interface table", entity="testcase"))
        where = dict(component=component, unit=du.name, view="interface table")
        for r in left_only:
            self.add(level="L4", kind="missing", path="%s / %s" % (path, r.name), item=r.name,
                     entity="testcase", priority=P2, rule=_RULE_ROW, field="specForRow",
                     summary="the interface table has the Function row %r and the "
                             "specification has no test case for it" % r.name, **where)
        for c in right_only:
            self.add(level="L4", kind="extra", path="%s / %s" % (path, c.name), item=c.name,
                     entity="testcase", priority=P1, rule=_RULE_EXTRA, breaks=True,
                     field="specForRow",
                     summary="the specification has a test case for %r, which has no row in the "
                             "design's interface table" % c.name, **where)
        for r, c in bare_pairs:
            self.add(level="L4", kind="renamed", path="%s / %s" % (path, r.name), item=r.name,
                     entity="testcase", priority=P2, field="specForRow", left=r.name,
                     right=c.name, rule=_RULE_NAMES, breaks=True,
                     summary="the interface table calls this function %r and the specification "
                             "calls it %r" % (r.name, c.name), **where)

    def calls(self, component, dia, sia):
        """L4 counts and L5 names: the design's call arrows against the spec's calls."""
        drawn, called = _design_calls(dia), _spec_calls(sia)
        unit = dia.fields.get("unit", "")
        if not (dia.fields.get("arrows") or []):
            return                       # no description table to hold the spec to
        gone = [drawn[k] for k in drawn if k not in called]
        came = [called[k] for k in called if k not in drawn]
        self.r.check(Check(level="L4", what="call arrows ↔ cross-unit calls",
                           component=component, unit=unit, left=len(drawn), right=len(called),
                           ok=not (gone or came), names=_names_status(len(gone) + len(came)),
                           detail=" · ".join(["− %s" % g for g in gone] + ["+ %s" % c for c in came]),
                           view="Dynamic Behaviour", entity="interaction"))
        if not self.on(5):
            return
        key = (component, unit, "Dynamic Behaviour")
        self.r.compared[key] = self.r.compared.get(key, 0) + 1
        where = dict(component=component, unit=unit, view="Dynamic Behaviour",
                     entity="interaction", rule=_RULE_CALLS, breaks=True, field="interactionCall")
        for g in gone:
            self.add(level="L5", kind="missing", path="%s / %s" % (component, dia.name),
                     item="%s: %s" % (dia.name, g), priority=P2, left=g,
                     summary="the design's arrow to %s has no cross-unit call in the "
                             "specification" % g, **where)
        for c in came:
            self.add(level="L5", kind="extra", path="%s / %s" % (component, dia.name),
                     item="%s: %s" % (dia.name, c), priority=P1, right=c,
                     summary="the specification calls %s, which the design draws no arrow for" % c,
                     **where)

    def test_case_id(self, path, where, func, case, row):
        """The Test Case ID is the Interface ID with TC_ in front."""
        if row is None:
            return
        design_id = (row.fields.get("interfaceId") or "").strip().strip("`")
        spec_id = (case.fields.get("testCaseId") or "").strip().strip("`")
        if not design_id or not spec_id or spec_id == "TC_" + design_id:
            return
        self.add(level="L5", kind="differs", path="%s / %s" % (path, func.name), item=func.name,
                 entity="testcase", field="testCaseId", priority=P1, left=design_id,
                 right=spec_id, view="Table B", component=where["component"],
                 unit=where["unit"],
                 rule="a Test Case ID is derived as `TC_<interfaceId>` (%s, 'Table B')" % WIKI4,
                 breaks=True,
                 summary="Test Case ID %r is not TC_ plus the design's Interface ID %r"
                         % (spec_id, design_id))

    def heading_text(self, component, unit, d, s, view, entity, follows=""):
        """The two headings are printed the same -- the wiki says a SWE.4 heading reads as
        its SWE.3 heading. Case and spacing alone are cosmetic."""
        a = d.fields.get("heading") or d.name
        b = s.fields.get("heading") or s.name
        key = (component, unit, "headings")
        self.r.compared[key] = self.r.compared.get(key, 0) + 1
        if a == b:
            return
        loose = normalise_text(a).replace(" ", "") == normalise_text(b).replace(" ", "")
        self.add(level="L5", kind="differs", path="%s / %s" % (component, a), item=d.name,
                 entity=entity, field="headingText", priority=P4 if loose else P2,
                 left=a, right=b, view="headings", component=component, unit=unit,
                 follows=follows,
                 rule=_RULE_HEADING, breaks=True, summary="heading: %s -> %s" % (a, b))


def check(design, spec, max_level=5):
    """A Result from holding a SWE.3 document against its SWE.4 document."""
    result = Result(mode="pair", doc_type=DOC_TYPE, sides=SIDES, max_level=max_level,
                    level_what=dict(LEVEL_WHAT))
    p = _Pair(result)
    p.mentions = _spec_mentions(spec)
    p.headings(design, spec)
    if max_level >= 2:
        p.inventory(design, spec)
    result.notes = ["Interface IDs are compared only as Test Case ID = TC_ + Interface ID.",
                    "A call arrow and a cross-unit call are matched on the called function's "
                    "name; mocks leave the component and are not drawn, so they are not compared."]
    # One fact, counted once: a function missing its heading and its spec is an L3
    # finding, and its interface row at L4 follows from it.
    _mark_follows(result, p.aliases)
    # Findings name the SWE.3 heading kind their entity pairs with.
    mark_heading_follows(result, {"component": "component", "unit": "unit",
                                  "testcase": "function", "interaction": "interaction"})
    result.findings.sort(key=lambda f: f.sort_key())
    return result


_GAP_RE = re.compile(r"jumped to (\d+), expected (\d+)")
_NN_RE = re.compile(r"_(\d+)$")


def explain_id_gaps(spec_findings, design, spec):
    """A gap in the spec's Test Case IDs, explained by the design where it can be.

    The spec takes each Test Case ID from its design's Interface ID, so a design
    function with no spec -- one defined in a header -- leaves its number out. When
    every number a gap skips is such a function, the gap is the design's doing: P3,
    with the names. Returns how many it explained.
    """
    rows, cases = {}, {}
    for component in design.of_kind("component"):
        for unit in component.of_kind("unit"):
            for row in _rows(unit):
                m = _NN_RE.search((row.fields.get("interfaceId") or "").strip().strip("`"))
                if m:
                    rows.setdefault((normalise_key(component.name), normalise_key(unit.name)),
                                    {})[int(m.group(1))] = row.name
    for component in spec.of_kind("component"):
        for unit in component.of_kind("unit"):
            cases[(normalise_key(component.name), normalise_key(unit.name))] = {
                _bare(c.name) for c in unit.of_kind("testcase")}
    explained = 0
    for f in spec_findings:
        m = _GAP_RE.search(f.summary or "") if f.field == "tc-id-gap" else None
        if not m:
            continue
        key = (normalise_key(f.component), normalise_key(f.unit))
        jumped, expected = int(m.group(1)), int(m.group(2))
        skipped = [rows.get(key, {}).get(n) for n in range(expected, jumped)]
        if not skipped or any(name is None or _bare(name) in cases.get(key, set())
                              for name in skipped):
            continue
        f.was, f.priority, f.explained = f.priority, P3, True
        f.rule = ("the design's %s %s no spec, and the spec keeps the design's numbers, so its "
                  "Test Case IDs skip %s (%s, 'Table B')"
                  % (", ".join(skipped), "has" if len(skipped) == 1 else "have",
                     "it" if len(skipped) == 1 else "them", WIKI4))
        explained += 1
    return explained


def summary(design, spec, result_or_findings=None):
    """A line saying how far the two documents agree."""
    functions = sum(len(_specced(u)) for c in design.of_kind("component")
                    for u in c.of_kind("unit"))
    specs = sum(len(u.of_kind("testcase")) for c in spec.of_kind("component")
                for u in c.of_kind("unit"))
    d_ia = sum(len(c.of_kind("interaction")) for c in design.of_kind("component"))
    s_ia = sum(len(c.of_kind("interaction")) for c in spec.of_kind("component"))
    findings = getattr(result_or_findings, "findings", result_or_findings) or []
    return ("design has %d function heading(s), the specification %d test case(s); "
            "behaviour diagrams %d, interaction specs %d; %d finding(s)"
            % (functions, specs, d_ia, s_ia, len(findings)))
