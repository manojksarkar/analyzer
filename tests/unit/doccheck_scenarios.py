"""One deliberate change to a real generated document, per scenario.

Each scenario copies a document our exporter wrote, changes ONE thing in it with
python-docx -- a heading renamed, a Direction flipped, a table removed -- and names
where the comparison must report it: the level, the kind of finding and its
priority. `test_doccheck_scenarios.py` asserts exactly that; `python
tests/unit/doccheck_scenarios.py OUT_DIR` applies all of them at once and writes
the three demo reports (SWE.3 compare, SWE.4 compare, SWE.3 against SWE.4) the
tool itself produces.

The source is `longdecl-ab.office/Access`: nine units, fifteen functions,
twenty-seven flowcharts, twenty-four header rows, and a SWE.4 beside it.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.path.join(_ROOT, "tools") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "tools"))

import docx                                                     # noqa: E402
from docx.oxml.ns import qn                                     # noqa: E402

SOURCE_DIR = os.path.join(_ROOT, "workspaces", "longdecl-ab", "versions", "longdecl-ab.office",
                          "documents")
DESIGN = os.path.join(SOURCE_DIR, "software_detailed_design_Layer1.Access.docx")
SPEC = os.path.join(SOURCE_DIR, "software_unit_test_specification_Layer1.Access.docx")


# --- reading and writing a document's body -------------------------------------

def _level(p):
    name = (p.style.name or "") if p.style is not None else ""
    if name.startswith("Heading "):
        try:
            return int(name.split()[1])
        except (IndexError, ValueError):
            return 0
    return 0


def _body(document):
    """The body's children in order, each as (element, paragraph or None)."""
    from docx.text.paragraph import Paragraph
    out = []
    for child in document.element.body.iterchildren():
        para = Paragraph(child, document) if child.tag == qn("w:p") else None
        out.append((child, para))
    return out


def _heading(document, level, suffix):
    """The heading paragraph at `level` whose text ends with `suffix`."""
    for _el, p in _body(document):
        if p is not None and _level(p) == level and p.text.strip().endswith(suffix):
            return p
    raise LookupError("no H%d ending with %r" % (level, suffix))


def _set_text(obj, text):
    """Replace a paragraph's or a cell's text, keeping the first run's formatting."""
    paras = obj.paragraphs if hasattr(obj, "paragraphs") else [obj]
    first = paras[0]
    if first.runs:
        first.runs[0].text = text
        for run in first.runs[1:]:
            run.text = ""
    else:
        first.add_run(text)
    for extra in paras[1:]:
        extra._p.getparent().remove(extra._p)


def _section_after(document, heading):
    """The body elements from `heading` up to the next heading at its level or above."""
    level = _level(heading)
    out, inside = [], False
    for el, p in _body(document):
        if el is heading._p:
            inside = True
            out.append(el)
            continue
        if not inside:
            continue
        if p is not None and 0 < _level(p) <= level:
            break
        if el.tag == qn("w:sectPr"):
            break
        out.append(el)
    return out


def _tables_after(document, heading):
    from docx.table import Table
    return [Table(el, document) for el in _section_after(document, heading)
            if el.tag == qn("w:tbl")]


def _column(table, prefix):
    header = [c.text.strip().casefold() for c in table.rows[0].cells]
    for i, h in enumerate(header):
        if h.startswith(prefix.casefold()):
            return i
    raise LookupError("no column %r in %s" % (prefix, header))


def _interface_table(document, unit):
    for table in _tables_after(document, _heading(document, 3, unit)):
        header = " ".join(c.text for c in table.rows[0].cells).casefold()
        if "interface name" in header:
            return table
    raise LookupError("no interface table under %s" % unit)


def _row(table, name, column=1):
    for row in table.rows[1:]:
        if row.cells[column].text.strip() == name:
            return row
    raise LookupError("no row %r" % name)


def _remove(elements):
    for el in elements:
        el.getparent().remove(el)


# --- SWE.3 changes ----------------------------------------------------------------

def rename_function_heading(unit, old, new):
    def apply(document):
        p = _heading(document, 4, "%s-%s" % (unit, old))
        _set_text(p, p.text.strip()[: -len(old)] + new)
    return apply


def set_interface_cell(unit, name, column, value):
    def apply(document):
        table = _interface_table(document, unit)
        _set_text(_row(table, name).cells[_column(table, column)], value)
    return apply


def delete_interface_row(unit, name):
    def apply(document):
        row = _row(_interface_table(document, unit), name)
        row._tr.getparent().remove(row._tr)
    return apply


def rename_interface_column(unit, old, new):
    def apply(document):
        table = _interface_table(document, unit)
        _set_text(table.rows[0].cells[_column(table, old)], new)
    return apply


def delete_section(level, suffix):
    def apply(document):
        _remove(_section_after(document, _heading(document, level, suffix)))
    return apply


def delete_unit_subsection(unit, title):
    """The `unit header` / `unit interface` sub-section of one unit."""
    def apply(document):
        unit_heading = _heading(document, 3, unit)
        section = _section_after(document, unit_heading)
        from docx.text.paragraph import Paragraph
        start = next(el for el in section if el.tag == qn("w:p")
                     and _level(Paragraph(el, document)) == 4
                     and Paragraph(el, document).text.strip().endswith(title))
        _remove([el for el in _section_after(document, Paragraph(start, document))])
    return apply


def set_header_cell(unit, symbol, column, value):
    """A unit header table cell: column 0 is the declaration, 1 the value."""
    def apply(document):
        unit_heading = _heading(document, 3, unit)
        for table in _tables_after(document, unit_heading):
            if "global variables" not in table.rows[0].cells[0].text.casefold():
                continue
            for row in table.rows[1:]:
                if re.search(r"\b%s\b" % re.escape(symbol), row.cells[0].text):
                    _set_text(row.cells[column], value)
                    return
        raise LookupError("no header row %r under %s" % (symbol, unit))
    return apply


def drop_flowchart(unit, function):
    """The first flowchart image of a function -- it sits in its Requirements cell."""
    def apply(document):
        heading = _heading(document, 4, "%s-%s" % (unit, function))
        for el in _section_after(document, heading)[1:]:
            drawings = el.findall(".//" + qn("w:drawing"))
            if drawings:
                run = drawings[0].getparent()
                run.getparent().remove(run)
                return
        raise LookupError("no flowchart under %s-%s" % (unit, function))
    return apply


def set_function_row(unit, function, label, value):
    """A row of the table under a flowchart entry (Risk, Input Name, ...)."""
    def apply(document):
        heading = _heading(document, 4, "%s-%s" % (unit, function))
        for table in _tables_after(document, heading):
            for row in table.rows:
                if row.cells[0].text.strip().casefold().startswith(label.casefold()):
                    _set_text(row.cells[1], value)
                    return
        raise LookupError("no %r row under %s-%s" % (label, unit, function))
    return apply


def delete_top_heading(prefix):
    def apply(document):
        for el, p in _body(document):
            if p is not None and _level(p) == 1 and prefix.casefold() in p.text.casefold():
                el.getparent().remove(el)
                return
        raise LookupError("no H1 %r" % prefix)
    return apply


def add_top_heading(title):
    def apply(document):
        document.add_heading(title, level=1)
    return apply


# --- SWE.4 changes ----------------------------------------------------------------

def _case_tables(document, heading_suffix, level=4):
    heading = _heading(document, level, heading_suffix)
    tables = _tables_after(document, heading)
    table_a = next(t for t in tables if len(t.rows[0].cells) >= 5)
    table_b = next((t for t in tables if len(t.rows[0].cells) == 2), None)
    return table_a, table_b


def set_steps(heading_suffix, column, lines, level=4):
    """Rewrite one Table A column of a spec: one paragraph per line."""
    def apply(document):
        table_a, _b = _case_tables(document, heading_suffix, level)
        cell = table_a.rows[1].cells[_column(table_a, column)]
        _set_text(cell, lines[0])
        for line in lines[1:]:
            cell.add_paragraph(line)
    return apply


def read_steps(heading_suffix, column, level=4):
    document = docx.Document(SPEC)
    table_a, _b = _case_tables(document, heading_suffix, level)
    cell = table_a.rows[1].cells[_column(table_a, column)]
    # A cell's lines may be paragraphs or line breaks inside one paragraph.
    return [line for p in cell.paragraphs for line in p.text.split("\n") if line.strip()]


def set_table_b(heading_suffix, label, value, level=4):
    def apply(document):
        _a, table_b = _case_tables(document, heading_suffix, level)
        for row in table_b.rows:
            if row.cells[0].text.strip().casefold() == label.casefold():
                _set_text(row.cells[1], value)
                return
        raise LookupError("no Table B row %r" % label)
    return apply


def drop_table_b(heading_suffix, level=4):
    def apply(document):
        _a, table_b = _case_tables(document, heading_suffix, level)
        table_b._tbl.getparent().remove(table_b._tbl)
    return apply


# --- the scenarios -----------------------------------------------------------------

@dataclass
class Scenario:
    name: str
    change: object
    level: str
    field: str                      # the finding's field, or its kind for a presence finding
    priority: str
    also: list = field(default_factory=list)   # other counted fields it may raise


SWE3 = [
    Scenario("a function heading renamed",
             rename_function_heading("AccessCompanion", "companionEntry", "companionEntries"),
             "L3", "renamed", "P2"),
    Scenario("a Direction flipped",
             set_interface_cell("AccessMatrixUser", "mtxCallSealed", "direction", "In"),
             "L5", "direction", "P1"),
    Scenario("Source/Destination emptied",
             set_interface_cell("AccessMatrix", "mtxUnmarkedCalled", "source", "-"),
             "L5", "sourceDest", "P1"),
    Scenario("a parameter type changed",
             set_interface_cell("AccessSession", "accessSessionBudget", "data type",
                                "uint16_t budget"),
             # the cell loses its `return:` line and its VOID, so the return type and
             # the parameter range go with it
             "L5", "dataTypeParams", "P1", also=["dataTypeReturn", "dataRangeParams"]),
    Scenario("an interface row deleted",
             delete_interface_row("AccessMatrix", "MtxStruct::plain"),
             "L4", "missing", "P2"),
    Scenario("a unit header section removed",
             delete_unit_subsection("AccessMatrixUser", "unit header"),
             "L3", "hasHeaderSection", "P2"),
    Scenario("a unit section removed",
             delete_section(3, "NestedTypesUser"),
             "L2", "missing", "P1"),
    Scenario("a class declaration changed",
             set_header_cell("AccessMatrix", "MtxStruct", 0,
                             "struct MtxStruct { public: int plain(); int exposed(); int added; };"),
             "L5", "declaration", "P2"),
    Scenario("a flowchart image missing",
             drop_flowchart("AccessMatrixUser", "mtxUseDerived"),
             "L4", "flowchartCount", "P2"),
    Scenario("an Output Name changed",
             set_function_row("AccessSession", "accessSessionBudget", "Output Name", "Budget"),
             "L5", "outputName", "P2"),
    Scenario("a Risk changed (a fixed value)",
             set_function_row("AccessMatrixUser", "mtxCallMarkedPublic", "Risk", "High"),
             "L5", "risk", "P3"),
    Scenario("an interface column reworded",
             rename_interface_column("AccessSession", "direction", "In/Out"),
             "L4", "interfaceColumns", "P4"),
    Scenario("an Information cell reworded",
             set_interface_cell("AccessCompanion", "companionEntry", "information",
                                "Entry point of the companion unit, reworded by a reviewer."),
             "L5", "information", "P4"),
    Scenario("the Code Metrics heading removed",
             delete_top_heading("Code Metrics"),
             "L1", "missing", "P2"),
    Scenario("a section the wiki does not name added",
             add_top_heading("Revision History"),
             "L1", "extra", "P2"),
]

_BUDGET = "AccessSession-accessSessionBudget"
_SEALED = "AccessMatrixUser-mtxCallSealed"

SWE4 = [
    Scenario("a test step reworded",
             lambda d: set_steps(_BUDGET, "test steps",
                                 [s.replace("Return", "Give back", 1)
                                  for s in read_steps(_BUDGET, "test steps")])(d),
             "L5", "testSteps", "P2"),
    Scenario("a test step added",
             lambda d: set_steps(_SEALED, "test steps",
                                 read_steps(_SEALED, "test steps") + ["9) Log the result."])(d),
             "L4", "stepCount", "P2"),
    Scenario("an expected result changed",
             lambda d: set_steps(_BUDGET, "expected",
                                 ["1) Successfully returned something else"]
                                 + read_steps(_BUDGET, "expected")[1:])(d),
             "L5", "expected", "P2"),
    Scenario("Table B removed",
             drop_table_b("AccessMatrix-mtxUnmarkedCalled"),
             "L4", "hasTableB", "P1"),
    Scenario("a test case removed",
             delete_section(4, "AccessMatrix-MtxStruct::exposed"),
             "L3", "missing", "P2"),
    Scenario("a Priority changed (configuration)",
             set_table_b("AccessCompanion-companionEntry", "Priority", "High"),
             "L5", "priority", "P3"),
    Scenario("an interaction spec removed",
             delete_section(4, "AccessSession - accessSessionBudget (Main - runAccessTests)"),
             "L2", "missing", "P2"),
]


def apply(source, scenarios, target):
    document = docx.Document(source)
    for s in scenarios:
        s.change(document)
    document.save(target)
    return target


# --- SWE.3 as the input to SWE.4 ------------------------------------------------------
#
# No generated design on this machine draws a behaviour diagram (the view is off in
# these runs), so the pair scenarios add one the way the exporter writes it: a level-3
# heading under Dynamic Behaviour and the five-row description table.

def add_behaviour(heading, arrows):
    def apply(document):
        dynamic = _heading(document, 2, "Dynamic Behaviour")
        anchor = _section_after(document, dynamic)[-1]
        new_heading = document.add_heading(heading, level=3)
        table = document.add_table(rows=5, cols=2)
        cells = table.rows[0].cells
        cells[0].text = "Requirements"
        cells[1].text = "Behavior Description"
        for arrow in arrows:
            cells[1].add_paragraph(arrow)
        for i, (label, value) in enumerate((("Risk", "Medium"), ("Capacity", "Common"),
                                            ("Input Name", "-"), ("Output Name", "-")), 1):
            table.rows[i].cells[0].text = label
            table.rows[i].cells[1].text = value
        anchor.addnext(new_heading._p)
        new_heading._p.addnext(table._tbl)
    return apply


def delete_function_heading(unit, function):
    """A function's flowchart entry goes; its interface row stays."""
    return delete_section(4, "%s-%s" % (unit, function))


# Applied to the DESIGN, held against the untouched SPEC.
PAIR = [
    Scenario("a behaviour diagram whose arrows match the interaction spec",
             add_behaviour("AccessMatrixUser - mtxCallSealed (Main - runMatrixTests)",
                           ["runMatrixTests calls mtxCallSealed",
                            "mtxCallSealed calls MtxStruct::sealed",
                            "MtxStruct::sealed returns to mtxCallSealed",
                            "mtxCallSealed returns to runMatrixTests"]),
             "L2", "-", "-"),
    Scenario("a behaviour diagram with an arrow the spec does not call",
             add_behaviour("AccessMatrixUser - mtxCallMarkedPublic (Main - runMatrixTests)",
                           ["runMatrixTests calls mtxCallMarkedPublic",
                            "mtxCallMarkedPublic calls MtxStruct::exposed",
                            "MtxStruct::exposed returns to mtxCallMarkedPublic"]),
             "L5", "interactionCall", "P2"),
    Scenario("a function row whose flowchart entry is gone",
             delete_function_heading("NestedTypes", "NestedOwner::nestedPublicMode"),
             "L3", "extra", "P2"),
]


def rewrite_heading(level, old, new):
    """A heading's title, number kept: `2.1.3.1 AccessMatrix-x` -> `2.1.3.1 <new>`."""
    def apply(document):
        p = _heading(document, level, old)
        _set_text(p, p.text.strip()[: -len(old)] + new)
    return apply


# Applied to the SPEC, held against the design (with its two behaviour diagrams).
PAIR_HEADINGS = [
    Scenario("a test case heading spaced differently",
             rewrite_heading(4, "AccessMatrix-mtxUnmarkedCalled",
                             "AccessMatrix - mtxUnmarkedCalled"),
             "L5", "headingText", "P4"),
    Scenario("a test case heading that drops the class",
             rewrite_heading(4, "AccessMatrix-MtxStruct::plain", "AccessMatrix-plain"),
             "L3", "renamed", "P2"),
    Scenario("a test case heading under a misspelt unit",
             rewrite_heading(4, "AccessMatrixUser-mtxUseDerived", "AccessMatrixUsr-mtxUseDerived"),
             "L5", "headingText", "P2"),
    Scenario("an interaction heading spaced differently",
             rewrite_heading(4, "AccessMatrixUser - mtxCallMarkedPublic (Main - runMatrixTests)",
                             "AccessMatrixUser - mtxCallMarkedPublic ( Main - runMatrixTests )"),
             "L5", "headingText", "P4"),
    Scenario("an interaction heading naming another entry point",
             rewrite_heading(4, "AccessMatrixUser - mtxCallSealed (Main - runMatrixTests)",
                             "AccessMatrixUser - mtxCallSealed (Main - runAllTests)"),
             "L2", "extra", "P1"),
    Scenario("a unit heading in another case",
             rewrite_heading(3, "NestedTypes", "Nestedtypes"),
             "L5", "headingText", "P4"),
    Scenario("the component heading in capitals",
             rewrite_heading(2, "Access", "ACCESS"),
             "L5", "headingText", "P4"),
]


# --- the demo reports ----------------------------------------------------------------

def write_demos(out_dir):
    """All scenarios at once, and the reports the tool writes for them.

    Run inside `out_dir` on copies with short names, so a report's header reads
    `design.docx`, not a temporary path.
    """
    import shutil
    from doccheck.__main__ import main
    os.makedirs(out_dir, exist_ok=True)
    here = os.getcwd()
    os.chdir(out_dir)
    try:
        shutil.copyfile(DESIGN, "design.docx")
        shutil.copyfile(SPEC, "spec.docx")
        apply("design.docx", SWE3, "design_changed.docx")
        apply("spec.docx", SWE4, "spec_changed.docx")
        apply("design.docx", PAIR, "design_with_behaviour.docx")
        apply("spec.docx", PAIR_HEADINGS, "spec_headings.docx")
        runs = [
            ("doccheck-demo-swe3-compare.md", ["design.docx", "design_changed.docx"]),
            ("doccheck-demo-swe4-compare.md", ["spec.docx", "spec_changed.docx"]),
            ("doccheck-demo-swe3-swe4-pair.md", ["design_with_behaviour.docx",
                                                 "spec_headings.docx"]),
            ("doccheck-demo-self.md", ["design_changed.docx", "--self"]),
        ]
        import contextlib
        for name, args in runs:
            # the terminal form too, as a pipe gets it (plain ASCII)
            with open(name.replace(".md", ".txt"), "w", encoding="utf-8") as fh,                     contextlib.redirect_stdout(fh):
                main(args + ["--markdown", name, "--color", "never"])
    finally:
        os.chdir(here)
    return [os.path.join(out_dir, name) for name, _a in runs]


if __name__ == "__main__":
    for path in write_demos(sys.argv[1] if len(sys.argv) > 1 else "."):
        print(path)
