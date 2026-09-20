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
from .model import HIGH, INFO, LOW, MEDIUM, Entity, Policy

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

# The four values the wiki fixes, so a drift in them is a finding and not a guess.
FIXED = {
    "generationMethod": "Analysis of Requirements",
    "aliasTestId": "-",
    "risk": "-",
    "testMethod": "-",
    "linkedWorkItems": "-",
}


POLICIES = {
    "testcase": {
        "testCaseId":      Policy("ident", INFO, "Test Case ID (ours, not compared)"),
        "description":     Policy("text", INFO, "the sentence above the tables"),
        "evalEquipment":   Policy("exact", LOW, "Eval. Equipment Name"),
        "platform":        Policy("exact", LOW, "Test Platform"),
        "precondition":    Policy("seq", HIGH, "Precondition"),
        "input":           Policy("seq", HIGH, "Input"),
        "testSteps":       Policy("seq", HIGH, "Test Steps"),
        "testStepShape":   Policy("seq", HIGH, "Test Steps nesting"),
        "expected":        Policy("seq", HIGH, "Expected Results"),
        "priority":        Policy("exact", LOW, "Priority"),
        "risk":            Policy("exact", LOW, "Risk"),
        "testMethod":      Policy("exact", LOW, "Test Method"),
        "testEnvironment": Policy("exact", LOW, "Test Environment"),
        "generationMethod": Policy("exact", MEDIUM, "Test Case Generation Method"),
        "linkedWorkItems": Policy("exact", LOW, "Linked Work Items"),
        "hasTableA":       Policy("exact", HIGH, "Table A present"),
        "hasTableB":       Policy("exact", HIGH, "Table B present"),
    },
    "unit": {
        "testCaseCount": Policy("exact", MEDIUM, "test cases"),
    },
    "component": {},
    "section": {},
    "document": {},
}

LEVELS = {
    "section": "L0",
    "component": "L1",
    "unit": "L1",
    "testcase": "L2",
}


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
    for name, label in _TABLE_B_FIELDS:
        c = cells.find_label(kv, label)
        ent.fields[name] = c.text if c is not None else ""


def _is_table_b(block):
    """A two-column table whose first column reads like the metadata labels."""
    if not block.rows or len(block.rows[0]) != 2:
        return False
    labels = {(r[0].text or "").casefold() for r in block.rows if len(r) == 2}
    return "test case id" in labels or "test case generation method" in labels


def extract(blocks) -> Entity:
    """A SWE.4 block stream as an entity tree."""
    doc = Entity(kind="document", name=DOC_TYPE, key=DOC_TYPE)
    in_body = False
    component = None
    unit = None
    case = None
    counters = {}

    def _count(kind):
        counters[kind] = counters.get(kind, 0) + 1
        return counters[kind] - 1

    for b in blocks:
        if b.kind == "heading":
            if b.level == 1:
                component = unit = case = None
                title = (b.text or "").casefold()
                in_body = title.startswith(_BODY_HEADING)
                if not in_body and _is_fixed_section(b.text):
                    doc.children.append(Entity(kind="section", name=b.text,
                                               number=b.number, index=_count("section")))

            elif b.level == 2:
                unit = case = None
                if in_body:
                    component = Entity(kind="component", name=b.text, number=b.number,
                                       index=_count("component"))
                    doc.children.append(component)

            elif b.level == 3 and component is not None:
                case = None
                unit = Entity(kind="unit", name=b.text, number=b.number, index=_count("unit"))
                component.children.append(unit)

            elif b.level == 4 and unit is not None:
                name = cells.function_of(b.text, unit.name)
                case = Entity(kind="testcase", name=name, number=b.number,
                              index=_count("testcase"))
                case.fields["qualifiedName"] = b.text
                case.fields["hasTableA"] = False
                case.fields["hasTableB"] = False
                unit.children.append(case)

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

    _finalise(doc)
    return doc


def _finalise(doc):
    for component in doc.of_kind("component"):
        for unit in component.of_kind("unit"):
            unit.fields["testCaseCount"] = len(unit.of_kind("testcase"))


# --- checks a document can fail on its own ----------------------------------

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
    return out


def self_consistency(doc):
    """What one document can contradict about itself."""
    out = []
    for component in doc.of_kind("component"):
        for unit in component.of_kind("unit"):
            cases = unit.of_kind("testcase")
            if not cases:
                out.append(("unit-without-cases", "%s / %s" % (component.name, unit.name),
                            "the unit has a section but no test case"))
            for case in cases:
                where = "%s / %s / %s" % (component.name, unit.name, case.name)
                if not case.fields.get("hasTableA"):
                    out.append(("missing-table-a", where, "no Table A (the test content)"))
                if not case.fields.get("hasTableB"):
                    out.append(("missing-table-b", where, "no Table B (the metadata)"))
                qualified = case.fields.get("qualifiedName", "")
                if qualified and not qualified.startswith(unit.name + "-"):
                    out.append(("heading-unit-mismatch", where,
                                "the heading %r does not start with its unit %r"
                                % (qualified, unit.name)))
                steps = case.fields.get("testSteps") or []
                expected = case.fields.get("expected") or []
                if steps and not expected:
                    out.append(("no-expected-results", where,
                                "there are test steps but no expected results"))
                shape = case.fields.get("testStepShape") or []
                if shape and shape[0] != 1:
                    out.append(("steps-start-nested", where,
                                "the first test step is nested at depth %d" % shape[0]))
                for i in range(1, len(shape)):
                    if shape[i] - shape[i - 1] > 1:
                        out.append(("steps-skip-level", where,
                                    "test step nesting jumps from depth %d to %d"
                                    % (shape[i - 1], shape[i])))
                        break
    return out
