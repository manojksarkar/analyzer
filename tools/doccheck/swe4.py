"""SWE.4 Software Unit Test Specification: block stream in, entity tree out.

The structure, as `docs/spec/SWE4_WIKI.md` states it:

    1        Introduction
    2        Software Unit Test Specification
    2.K      <Component>
    2.K.M    <Unit>
    2.K.M.J  <Unit>-<Function>       a sentence, then Table A, then Table B
    3        Code Metric, Coding Rule, Test Coverage
    Appendix A  Reference

Table A is one data row of six columns; Table B is a vertical metadata form. Four
of Table A's columns are numbered lists, and **only Test Steps nests** -- its
levels alternate numeric and alphabetic (`2.a)`, `3.b.1.c)`) because they follow
the control flow. That nesting is compared as its own field: a specification that
keeps every sentence and flattens the tree has stopped describing the same test.

As in SWE.3, the id is ours. `TC_<interfaceId>` is derived, so test cases are
matched on the function name and the id is checked for internal consistency.
"""
from __future__ import annotations

import re

from . import cells
from .model import P1, P2, P4, Entity, Kind, Policy

DOC_TYPE = "SWE.4"

_FIXED_SECTIONS = ("introduction", "code metric", "reference", "appendix")

# The level-1 heading the component sections hang under.
_BODY_HEADING = "software unit test specification"

_TABLE_A_COLUMNS = {
    "evalEquipment": ["Eval. Equipment Name", "Eval Equipment Name", "Equipment"],
    "precondition":  ["Precondition", "Preconditions"],
    "input":         ["Input", "Inputs"],
    "testSteps":     ["Test Steps", "Steps"],
    "expected":      ["Expected Results", "Expected Result", "Expected"],
    "platform":      ["Test Platform", "Platform"],
}

_TABLE_B_FIELDS = (
    ("testCaseId", "Test Case ID"),
    ("aliasTestId", "Alias Test ID"),
    ("priority", "Priority"),
    ("risk", "Risk"),
    ("testMethod", "Test Method"),
    ("testEnvironment", "Test Environment"),
    ("generationMethod", "Test Case Generation Method"),
    ("linkedWorkItems", "Linked Work Items"),
)

# TC_IF_LAYER1_DIAG_CLASSSTATICS_01
_TC_ID_RE = re.compile(r"^TC_(?P<iface>P?IF_.+_(?P<nn>\d+))$")

# A component's second kind of spec: one per interaction, under its own level-3
# heading after that component's units. The heading reads the same as the SWE.3
# behaviour diagram it pairs with, one to one.
_DYNAMIC_HEADING = "dynamic behaviour"
_INTERACTION_RE = re.compile(
    r"^(?P<unit>.+?)\s+-\s+(?P<func>.+?)\s*\(\s*(?P<cunit>.+?)\s+-\s+(?P<cfunc>.+?)\s*\)\s*$")

# The four values the wiki fixes, so a drift in them is a finding and not a guess.
FIXED = {
    "generationMethod": "Analysis of Requirements",
    "aliasTestId": "-",
    "risk": "-",
    "testMethod": "-",
    "linkedWorkItems": "-",
}


# --- how each field is compared ---------------------------------------------
#
# L4 counts what a table holds (how many preconditions, steps, results); L5 reads
# what they say. A count that differs is counted once, at L4, and the L5 detail
# that follows from it is shown but not counted again (`FOLLOWS`).
#
# Cell text is P2, not P1: another author words every step differently, and a
# worded step is a thing to judge. P1 is kept for structure -- a missing table, a
# missing unit -- where there is nothing to judge.

_TABLE_A, _TABLE_B = "Table A", "Table B"

POLICIES = {
    "testcase": {
        "hasTableA":         Policy("exact", P1, "Table A present", "L4", _TABLE_A),
        "hasTableB":         Policy("exact", P1, "Table B present", "L4", _TABLE_B),
        "preconditionCount": Policy("exact", P2, "Precondition items", "L4", _TABLE_A),
        "inputCount":        Policy("exact", P2, "Input items", "L4", _TABLE_A),
        "stepCount":         Policy("exact", P2, "Test Steps items", "L4", _TABLE_A),
        "stepDepth":         Policy("exact", P2, "Test Steps nesting depth", "L4", _TABLE_A),
        "expectedCount":     Policy("exact", P2, "Expected Results items", "L4", _TABLE_A),
        "tableBLabels":      Policy("set", P2, "Table B rows", "L4", _TABLE_B),
        "testCaseId":        Policy("ident", P4, "Test Case ID (ours, not compared)", "L5", _TABLE_B),
        "description":       Policy("text", P4, "the sentence above the tables", "L5", "description"),
        "evalEquipment":     Policy("exact", P2, "Eval. Equipment Name", "L5", _TABLE_A),
        "platform":          Policy("exact", P2, "Test Platform", "L5", _TABLE_A),
        "precondition":      Policy("seq", P2, "Precondition", "L5", _TABLE_A),
        "input":             Policy("seq", P2, "Input", "L5", _TABLE_A),
        "testSteps":         Policy("seq", P2, "Test Steps", "L5", _TABLE_A),
        "testStepShape":     Policy("seq", P2, "Test Steps nesting", "L5", _TABLE_A),
        "expected":          Policy("seq", P2, "Expected Results", "L5", _TABLE_A),
        "aliasTestId":       Policy("exact", P2, "Alias Test ID", "L5", _TABLE_B),
        "priority":          Policy("exact", P2, "Priority", "L5", _TABLE_B),
        "risk":              Policy("exact", P2, "Risk", "L5", _TABLE_B),
        "testMethod":        Policy("exact", P2, "Test Method", "L5", _TABLE_B),
        "testEnvironment":   Policy("exact", P2, "Test Environment", "L5", _TABLE_B),
        "generationMethod":  Policy("exact", P2, "Test Case Generation Method", "L5", _TABLE_B),
        "linkedWorkItems":   Policy("exact", P2, "Linked Work Items", "L5", _TABLE_B),
    },
    "unit": {},
    "component": {},
    "document": {},
}

# An interaction spec keeps every Table A / Table B field a function spec has,
# and adds the four names its heading carries. The Test Case ID is left alone
# here too -- the wiki records that scheme as still open.
POLICIES["interaction"] = dict(POLICIES["testcase"])
POLICIES["interaction"].update({
    "unit":           Policy("name", P1, "target unit", "L5", "heading"),
    "function":       Policy("name", P1, "target function", "L5", "heading"),
    "callerUnit":     Policy("name", P1, "entry-point unit", "L5", "heading"),
    "callerFunction": Policy("name", P1, "entry-point function", "L5", "heading"),
})

# A field that only restates another field of the same entity (see swe3.FOLLOWS).
FOLLOWS = {(kind, field): counted
           for kind in ("testcase", "interaction")
           for field, counted in (("precondition", "preconditionCount"),
                                  ("input", "inputCount"),
                                  ("testSteps", "stepCount"),
                                  ("testStepShape", "stepCount"),
                                  ("expected", "expectedCount"))}

# A cell of a table one side does not have is not "different": the table is missing,
# and that is the one finding.
FIELD_REQUIRES = {
    (kind, field): ("hasTableA" if policy.view == _TABLE_A else "hasTableB")
    for kind in ("testcase", "interaction")
    for field, policy in POLICIES[kind].items()
    if policy.view in (_TABLE_A, _TABLE_B) and field not in ("hasTableA", "hasTableB")
}

KINDS = {
    "component":   Kind("L2", "components", "", P1, P1),
    "unit":        Kind("L2", "units", "", P1, P1),
    "interaction": Kind("L2", "interaction specs", "Dynamic Behaviour"),
    "testcase":    Kind("L3", "test case headings", "test cases"),
}
CHILDREN = {
    "document": ("component",),
    "component": ("unit", "interaction"),
    "unit": ("testcase",),
}

HEADING_TYPES = (
    ("introduction", "Introduction", P2),
    ("introduction/purpose", "Introduction › Purpose", P4),
    ("introduction/scope", "Introduction › Scope", P4),
    ("introduction/terms", "Introduction › Terms, Abbreviations and Definitions", P4),
    ("body", "Software Unit Test Specification", P1),
    ("component", "<Component>", P1),
    ("unit", "<Unit>", P1),
    ("testcase", "<Unit> › <Unit>-<Function>", P1),
    ("dynamic", "<Component> › Dynamic Behaviour", P2),
    ("interaction", "<Unit> - <Function> (<CallerUnit> - <CallerFunction>)", P2),
    ("metrics", "Code Metric, Coding Rule, Test Coverage", P2),
    ("appendix", "Appendix A · Reference", P2),
)

LEVELS = {kind: spec.level for kind, spec in KINDS.items()}

LEVEL_WHAT = {
    "L1": "every heading type is present",
    "L2": "components, units and interaction specs (count and names)",
    "L3": "per unit: test case headings (count and names)",
    "L4": "per test case: Table A and B present, how many preconditions, inputs, steps, results",
    "L5": "what Table A and Table B say",
}

NOT_COMPARED = [
    "Test Case IDs are not compared across two documents: each is built on its own document's "
    "Interface IDs, so they are checked inside one document (see 'Each document on its own').",
]


def _fixed_type(title):
    """The heading type of a fixed level-1 section, or None."""
    t = (title or "").casefold()
    if t.startswith("introduction"):
        return "introduction"
    if t.startswith("code metric"):
        return "metrics"
    if t.startswith("reference") or t.startswith("appendix"):
        return "appendix"
    return None


_INTRO_SUBS = (("purpose", "introduction/purpose"), ("scope", "introduction/scope"),
               ("terms", "introduction/terms"))


def other_heading(level, title):
    """The heading type of a heading the wiki does not name: its level and its title."""
    return "other: H%d %s" % (level, (title or "").strip())


def _is_fixed_section(title):
    t = (title or "").casefold()
    return any(t.startswith(p) for p in _FIXED_SECTIONS)


def _table_a(ent, block):
    """The six-column test content table, one data row."""
    cols = cells.resolve_columns(block.header, _TABLE_A_COLUMNS)
    rows = [r for r in block.rows[1:] if any(c.text for c in r)]
    if not rows:
        return
    row = rows[0]

    def cell(name):
        i = cols.get(name)
        return row[i] if i is not None and i < len(row) else None

    ent.fields["hasTableA"] = True
    for name in ("evalEquipment", "platform"):
        c = cell(name)
        ent.fields[name] = c.text if c else ""
    for name in ("precondition", "input", "expected"):
        c = cell(name)
        ent.fields[name] = cells.steps(c.texts if c else [])
    steps_cell = cell("testSteps")
    ent.fields["testSteps"] = cells.steps(steps_cell.texts if steps_cell else [])
    ent.fields["testStepShape"] = cells.shape(steps_cell.texts if steps_cell else [])


def _table_b(ent, block):
    """The vertical metadata form."""
    kv = cells.key_value_rows(block.rows)
    ent.fields["hasTableB"] = True
    labels = []
    for name, label in _TABLE_B_FIELDS:
        c = cells.find_label(kv, label)
        ent.fields[name] = c.text if c is not None else ""
        if c is not None:
            labels.append(label)
    ent.fields["tableBLabels"] = labels


def _is_table_b(block):
    """A two-column table whose first column reads like the metadata labels."""
    if not block.rows or len(block.rows[0]) != 2:
        return False
    labels = {(r[0].text or "").casefold() for r in block.rows if len(r) == 2}
    return "test case id" in labels or "test case generation method" in labels


def extract(blocks) -> Entity:
    """A SWE.4 block stream as an entity tree."""
    doc = Entity(kind="document", name=DOC_TYPE, key=DOC_TYPE)
    headings = {}
    in_body = False
    in_dynamic = False
    fixed = None
    component = None
    unit = None
    case = None
    counters = {}

    def _count(kind):
        counters[kind] = counters.get(kind, 0) + 1
        return counters[kind] - 1

    def _seen(heading_type):
        headings[heading_type] = headings.get(heading_type, 0) + 1

    for b in blocks:
        if b.kind == "heading":
            if b.level == 1:
                component = unit = case = None
                in_dynamic = False
                title = (b.text or "").casefold()
                in_body = title.startswith(_BODY_HEADING)
                fixed = None if in_body else _fixed_type(b.text)
                if in_body:
                    _seen("body")
                elif fixed:
                    _seen(fixed)
                else:
                    _seen(other_heading(1, b.text))
                if not in_body and _is_fixed_section(b.text):
                    doc.children.append(Entity(kind="section", name=b.text,
                                               number=b.number, index=_count("section")))

            elif b.level == 2:
                unit = case = None
                in_dynamic = False
                if in_body:
                    _seen("component")
                    component = Entity(kind="component", name=b.text, number=b.number,
                                       index=_count("component"))
                    doc.children.append(component)
                elif fixed == "introduction":
                    t = (b.text or "").casefold()
                    _seen(next((key for word, key in _INTRO_SUBS if t.startswith(word)),
                               other_heading(2, b.text)))
                else:
                    _seen(other_heading(2, b.text))

            elif b.level == 3 and component is not None:
                case = None
                if (b.text or "").casefold().startswith(_DYNAMIC_HEADING):
                    # Not a unit: the component's interaction specs live here.
                    _seen("dynamic")
                    unit = None
                    in_dynamic = True
                else:
                    _seen("unit")
                    in_dynamic = False
                    unit = Entity(kind="unit", name=b.text, number=b.number,
                                  index=_count("unit"))
                    component.children.append(unit)

            elif b.level == 4 and in_dynamic and component is not None:
                _seen("interaction")
                case = Entity(kind="interaction", name=b.text, number=b.number,
                              index=_count("interaction"))
                m = _INTERACTION_RE.match(b.text)
                if m:
                    case.fields["unit"] = m.group("unit").strip()
                    case.fields["function"] = m.group("func").strip()
                    case.fields["callerUnit"] = m.group("cunit").strip()
                    case.fields["callerFunction"] = m.group("cfunc").strip()
                case.fields["qualifiedName"] = b.text
                case.fields["heading"] = b.text
                case.fields["hasTableA"] = False
                case.fields["hasTableB"] = False
                component.children.append(case)

            elif b.level == 4 and unit is not None:
                _seen("testcase")
                name = cells.function_of(b.text, unit.name)
                case = Entity(kind="testcase", name=name, number=b.number,
                              index=_count("testcase"))
                case.fields["qualifiedName"] = b.text
                case.fields["heading"] = b.text
                case.fields["hasTableA"] = False
                case.fields["hasTableB"] = False
                unit.children.append(case)

            else:
                _seen(other_heading(b.level, b.text))

        elif b.kind == "para":
            if case is not None and b.text and not case.fields.get("description"):
                case.fields["description"] = b.text
            if case is not None and b.images:
                case.images.extend(b.images)

        elif b.kind == "table" and case is not None:
            if _is_table_b(b):
                _table_b(case, b)
            else:
                _table_a(case, b)

    doc.fields["headingTypes"] = headings
    _finalise(doc)
    return doc


def _finalise(doc):
    for component in doc.of_kind("component"):
        cases = list(component.of_kind("interaction"))
        for unit in component.of_kind("unit"):
            unit.fields["testCaseCount"] = len(unit.of_kind("testcase"))
            cases.extend(unit.of_kind("testcase"))
        for case in cases:
            if not case.fields.get("hasTableA"):
                continue
            f = case.fields
            f["preconditionCount"] = len(f.get("precondition") or [])
            f["inputCount"] = len(f.get("input") or [])
            f["stepCount"] = len(f.get("testSteps") or [])
            f["stepDepth"] = max(f.get("testStepShape") or [0])
            f["expectedCount"] = len(f.get("expected") or [])


def heading_types(doc):
    """{heading type: how many}, as `extract` records it, or derived from the tree."""
    got = doc.fields.get("headingTypes")
    if got is not None:
        return got
    out = {}

    def seen(key, n=1):
        if n:
            out[key] = out.get(key, 0) + n
    for section in doc.of_kind("section"):
        seen(_fixed_type(section.name) or other_heading(1, section.name))
    if doc.of_kind("component"):
        seen("body")
    for component in doc.of_kind("component"):
        seen("component")
        units = component.of_kind("unit")
        seen("unit", len(units))
        seen("testcase", sum(len(u.of_kind("testcase")) for u in units))
        interactions = component.of_kind("interaction")
        seen("dynamic", 1 if interactions else 0)
        seen("interaction", len(interactions))
    return out


# --- checks a document can fail on its own ----------------------------------

SELF_LEVEL_WHAT = {
    "L1": "(no single-document check at this level)",
    "L2": "every interaction heading reads '<Unit> - <Function> (<Caller> - <Function>)'",
    "L3": "every unit has test cases; headings start with their unit; no two read the same",
    "L4": "every spec has Table A and Table B, and expected results when it has steps",
    "L5": "Test Case IDs are well formed and distinct; fixed values hold; steps nest cleanly",
}

# Each self-check's level, priority and the view it is about.
SELF_CHECKS = {
    "tc-id-missing":        ("L5", P2, "Table B"),
    "tc-id-malformed":      ("L5", P1, "Table B"),
    "tc-id-private":        ("L5", P1, "Table B"),
    # A gap is legal: a header-defined public function keeps its interface id and
    # gets no spec, so the ids of the specs that follow it skip a number.
    "tc-id-gap":            ("L5", P2, "Table B"),
    "tc-id-collision":      ("L5", P1, "Table B"),
    "fixed-value-drift":    ("L5", P2, "Table B"),
    "interaction-heading-unreadable": ("L2", P2, "Dynamic Behaviour"),
    "missing-table-a":      ("L4", P1, "Table A"),
    "missing-table-b":      ("L4", P1, "Table B"),
    "no-expected-results":  ("L4", P1, "Table A"),
    "heading-unit-mismatch": ("L3", P2, "test cases"),
    "duplicate-heading":    ("L3", P1, "test cases"),
    "unit-without-cases":   ("L3", P2, "test cases"),
    "steps-start-nested":   ("L5", P2, "Table A"),
    "steps-skip-level":     ("L5", P2, "Table A"),
}

def id_integrity(doc):
    """The Test Case ID against its place, and the values the wiki fixes."""
    out = []
    for component in doc.of_kind("component"):
        for unit in component.of_kind("unit"):
            expected = 0
            for case in unit.of_kind("testcase"):
                where = "%s / %s / %s" % (component.name, unit.name, case.name)
                raw = (case.fields.get("testCaseId") or "").strip().strip("`")
                m = _TC_ID_RE.match(raw)
                if not raw:
                    out.append(("tc-id-missing", where, "no Test Case ID"))
                    continue
                if not m:
                    # the wiki allows a fall-back to the qualified name when the
                    # function has no interface entry, so this is not an error by
                    # itself -- only an id that looks like ours and is malformed is.
                    if raw.upper().startswith("TC_IF") or raw.upper().startswith("TC_PIF"):
                        out.append(("tc-id-malformed", where,
                                    "Test Case ID %r does not read TC_<interfaceId>" % raw))
                    continue
                if m.group("iface").startswith("PIF"):
                    out.append(("tc-id-private", where,
                                "%s is built on a private interface id" % raw))
                expected += 1
                nn = int(m.group("nn"))
                if nn != expected:
                    out.append(("tc-id-gap", where,
                                "Test Case ID numbering jumped to %02d, expected %02d"
                                % (nn, expected)))
                    expected = nn

            for case in unit.of_kind("testcase"):
                where = "%s / %s / %s" % (component.name, unit.name, case.name)
                for name, wanted in FIXED.items():
                    got = (case.fields.get(name) or "").strip().strip("`")
                    if got and got.casefold() != wanted.casefold():
                        out.append(("fixed-value-drift", where,
                                    "%s reads %r; the wiki fixes it at %r"
                                    % (name, got, wanted)))

        # An interaction spec's id scheme is recorded as still open, so its shape
        # is not checked. What the wiki does require is that it stay distinct from
        # the id of the same function's own spec -- and that is checkable.
        function_ids = {(c.fields.get("testCaseId") or "").strip().strip("`")
                        for u in component.of_kind("unit") for c in u.of_kind("testcase")}
        function_ids.discard("")
        for ia in component.of_kind("interaction"):
            where = "%s / Dynamic Behaviour / %s" % (component.name, ia.name)
            raw = (ia.fields.get("testCaseId") or "").strip().strip("`")
            if not raw:
                out.append(("tc-id-missing", where, "no Test Case ID"))
            elif raw in function_ids:
                out.append(("tc-id-collision", where,
                            "the interaction spec reuses %s, the id of the function's own "
                            "spec; the wiki requires the two to stay distinct" % raw))
            for name, wanted in FIXED.items():
                got = (ia.fields.get(name) or "").strip().strip("`")
                if got and got.casefold() != wanted.casefold():
                    out.append(("fixed-value-drift", where,
                                "%s reads %r; the wiki fixes it at %r" % (name, got, wanted)))
    return out


def _table_checks(out, where, ent, expect_prefix=None):
    """The checks that read the same for a function spec and an interaction spec."""
    if not ent.fields.get("hasTableA"):
        out.append(("missing-table-a", where, "no Table A (the test content)"))
    if not ent.fields.get("hasTableB"):
        out.append(("missing-table-b", where, "no Table B (the metadata)"))
    qualified = ent.fields.get("qualifiedName", "")
    if expect_prefix and qualified and not cells.starts_with_unit(qualified, expect_prefix):
        out.append(("heading-unit-mismatch", where,
                    "the heading %r does not start with its unit %r"
                    % (qualified, expect_prefix)))
    steps = ent.fields.get("testSteps") or []
    if steps and not (ent.fields.get("expected") or []):
        out.append(("no-expected-results", where,
                    "there are test steps but no expected results"))
    shape = ent.fields.get("testStepShape") or []
    if shape and shape[0] != 1:
        out.append(("steps-start-nested", where,
                    "the first test step is nested at depth %d" % shape[0]))
    for i in range(1, len(shape)):
        if shape[i] - shape[i - 1] > 1:
            out.append(("steps-skip-level", where,
                        "test step nesting jumps from depth %d to %d"
                        % (shape[i - 1], shape[i])))
            break


def self_consistency(doc):
    """What one document can contradict about itself."""
    out = []
    for component in doc.of_kind("component"):
        for ia in component.of_kind("interaction"):
            where = "%s / Dynamic Behaviour / %s" % (component.name, ia.name)
            if not ia.fields.get("unit"):
                out.append(("interaction-heading-unreadable", where,
                            "the heading does not read "
                            "'<Unit> - <Function> (<CallerUnit> - <CallerFunction>)'"))
            _table_checks(out, where, ia)
        for unit in component.of_kind("unit"):
            cases = unit.of_kind("testcase")
            if not cases:
                out.append(("unit-without-cases", "%s / %s" % (component.name, unit.name),
                            "the unit has a section but no test case"))
            for case in cases:
                where = "%s / %s / %s" % (component.name, unit.name, case.name)
                _table_checks(out, where, case, expect_prefix=unit.name)
            # Two specs under one heading cannot be told apart by a tester, and cannot
            # be paired with the design -- the `Dispatch-apply` defect.
            by_heading = {}
            for case in cases:
                by_heading.setdefault((case.fields.get("heading") or case.name).casefold(),
                                      []).append(case)
            for group in by_heading.values():
                if len(group) > 1:
                    out.append(("duplicate-heading",
                                "%s / %s / %s" % (component.name, unit.name, group[0].name),
                                "%d test specifications share the heading %r"
                                % (len(group), group[0].fields.get("heading") or group[0].name)))
    return out
