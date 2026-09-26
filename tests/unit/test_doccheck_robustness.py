"""The scenario the tool exists for: a document somebody else wrote.

Everything else in this suite reads documents our own exporters produced, which
share a template, column order and section titles. A document that comes back
from a client shares none of that guaranteed, and a comparator that only works on
its own output is a comparator nobody can use on the day it matters.

So these build documents from scratch -- the same content, written differently --
and assert the tool still lines them up: columns renamed, columns reordered,
sections retitled, cells merged, a table missing entirely.
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.path.join(_ROOT, "tools") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "tools"))

docx = pytest.importorskip("docx", reason="python-docx is needed to write a .docx")

from doccheck import blocks, cells, compare as comparing, match, swe3   # noqa: E402
from doccheck.model import P1, P2, P3, P4                              # noqa: E402

pytestmark = pytest.mark.unit


OUR_COLUMNS = ["Interface ID", "Interface Name", "Information", "Data Type",
               "Data Range", "Direction(In/Out)", "Source/Destination", "Interface Type"]

# The same eight columns as a different author might head and order them.
THEIR_COLUMNS = ["ID", "Name", "Type", "Description", "Range", "Source/Dest",
                 "In/Out", "Interface Type"]
THEIR_ORDER = ["interfaceId", "interfaceName", "dataType", "information", "dataRange",
               "sourceDest", "direction", "interfaceType"]
OUR_ORDER = ["interfaceId", "interfaceName", "information", "dataType", "dataRange",
             "direction", "sourceDest", "interfaceType"]

ROWS = [
    {"interfaceId": "IF_LAYER1_G_CLASSSTATICS_01", "interfaceName": "statBump",
     "information": "-", "dataType": ["int a; int b", "return: int"],
     "dataRange": ["0-255; 0-255", "return: 0-255"], "direction": "Out",
     "sourceDest": "Layer1.App/Main, Layer1.Cross/Hub", "interfaceType": "Function"},
    {"interfaceId": "IF_LAYER1_G_CLASSSTATICS_02", "interfaceName": "statRead",
     "information": "-", "dataType": ["VOID", "return: int"],
     "dataRange": ["NA", "return: 0-255"], "direction": "Out",
     "sourceDest": "-", "interfaceType": "Function"},
    {"interfaceId": "IF_LAYER1_G_CLASSSTATICS_03", "interfaceName": "s_count",
     "information": "-", "dataType": ["int"], "dataRange": ["0-255"],
     "direction": "In/Out", "sourceDest": "Layer1.Diag/ClassStatics",
     "interfaceType": "Global Variable"},
]


def _fill(cell, value):
    """A cell holds one paragraph per value, which is how a return line is written."""
    values = value if isinstance(value, (list, tuple)) else [value]
    cell.paragraphs[0].add_run(str(values[0]))
    for extra in values[1:]:
        cell.add_paragraph(str(extra))


def build_design(path, columns=OUR_COLUMNS, order=OUR_ORDER,
                 intro="1 Introduction", static="2.1 Static Design",
                 unit_heading="2.1.1 ClassStatics", rows=ROWS,
                 interface_table=True, merge_header=False):
    """A minimal but complete SWE.3 document, written however the caller asks."""
    doc = docx.Document()
    doc.add_heading(intro, level=1)
    doc.add_heading("2 Diag", level=1)
    doc.add_heading(static, level=2)

    table = doc.add_table(rows=1, cols=4)
    for i, name in enumerate(["Component", "Unit", "Description", "Note"]):
        table.rows[0].cells[i].text = name
    row = table.add_row()
    for i, value in enumerate(["Diag", "ClassStatics", "N/A", "N/A"]):
        row.cells[i].text = value

    doc.add_heading(unit_heading, level=3)
    doc.add_heading("2.1.1.1 unit header", level=4)
    header = doc.add_table(rows=1, cols=2)
    header.rows[0].cells[0].text = "global variables / typedef / enum / define"
    header.rows[0].cells[1].text = "information"
    hrow = header.add_row()
    hrow.cells[0].text = "#define SCALE 8"
    hrow.cells[1].text = "8"

    doc.add_heading("2.1.1.2 unit interface", level=4)
    if interface_table:
        itable = doc.add_table(rows=1, cols=len(columns))
        for i, name in enumerate(columns):
            itable.rows[0].cells[i].text = name
        if merge_header:
            # A merged header cell -- python-docx reports it once per column it
            # spans, which a naive reader turns into a duplicated column.
            itable.rows[0].cells[0].merge(itable.rows[0].cells[1])
        for data in rows:
            r = itable.add_row()
            for i, fieldname in enumerate(order):
                _fill(r.cells[i], data[fieldname])
    doc.add_heading("3 Code Metrics, Coding Rule, Test Coverage", level=1)
    doc.save(path)
    return path


def _extract(path):
    return swe3.extract(blocks.read(path))


def _compare(a, b, aliases=None):
    return comparing.compare(_extract(a), _extract(b), swe3, aliases)


# --- the same content, written differently ----------------------------------

def test_a_document_we_wrote_compares_clean_with_itself(tmp_path):
    a = build_design(str(tmp_path / "a.docx"))
    b = build_design(str(tmp_path / "b.docx"))
    assert _compare(a, b).findings == []


def test_renamed_and_reordered_columns_are_still_the_same_eight_columns(tmp_path):
    """The client's table, with our content. Column position is not an identity."""
    ours = build_design(str(tmp_path / "ours.docx"))
    theirs = build_design(str(tmp_path / "theirs.docx"),
                          columns=THEIR_COLUMNS, order=THEIR_ORDER)
    result = _compare(ours, theirs)
    # Only the column headings' wording differs -- cosmetic, and said once.
    assert [(f.field, f.priority) for f in result.findings] == [("interfaceColumns", P4)]


def test_data_type_is_not_claimed_by_the_interface_type_column(tmp_path):
    """`Interface Type` must win `Type` outright, or every row's Data Type is wrong."""
    theirs = build_design(str(tmp_path / "theirs.docx"),
                          columns=THEIR_COLUMNS, order=THEIR_ORDER)
    doc = _extract(theirs)
    rows = doc.of_kind("component")[0].of_kind("unit")[0].of_kind("interface")
    assert rows[0].fields["dataTypeParams"] == ["int a", "int b"]
    assert rows[0].fields["interfaceType"] == "Function"


def test_a_retitled_introduction_is_still_the_introduction(tmp_path):
    ours = build_design(str(tmp_path / "ours.docx"))
    theirs = build_design(str(tmp_path / "theirs.docx"), intro="1 Introduction and Purpose")
    result = _compare(ours, theirs)
    assert not [f for f in result.findings if f.kind in ("missing", "extra")]


def test_a_merged_body_cell_is_read_once_not_once_per_column(tmp_path):
    """python-docx hands back a merged cell once for every column it spans."""
    path = str(tmp_path / "merged.docx")
    build_design(path)
    document = docx.Document(path)
    unit_table = next(t for t in document.tables
                      if t.rows[0].cells[0].text.strip() == "Component")
    row = unit_table.rows[1]
    row.cells[2].merge(row.cells[3])              # Description + Note -> one cell
    document.save(path)

    read = blocks.read(path)
    table = next(b for b in read if b.kind == "table" and b.header[:2] == ["Component", "Unit"])
    assert [c.text for c in table.rows[1]][:2] == ["Diag", "ClassStatics"]
    assert len(table.rows[1]) == 3, "the merged cell was counted twice"
    # and the unit is still found, which is what the merge must not break
    assert _extract(path).of_kind("component")[0].fields["unitTableUnits"] == ["ClassStatics"]


def test_a_missing_interface_table_is_a_finding_not_a_crash(tmp_path):
    ours = build_design(str(tmp_path / "ours.docx"))
    theirs = build_design(str(tmp_path / "theirs.docx"), interface_table=False)
    result = _compare(ours, theirs)
    assert [f.field for f in result.findings if f.kind == "differs"] == ["hasInterfaceTable"]
    # The rows of a table one side does not have are not compared -- the table is the
    # finding, not every row in it.
    assert not [f for f in result.findings if f.kind == "missing"]
    rows = [c for c in result.checks if c.what == "interface table rows"]
    assert rows and rows[0].skipped


# --- content that differs ---------------------------------------------------

def test_a_direction_written_differently_in_their_template_is_not_a_finding(tmp_path):
    rows = [dict(r) for r in ROWS]
    rows[0]["direction"] = "OUTPUT"
    ours = build_design(str(tmp_path / "ours.docx"))
    theirs = build_design(str(tmp_path / "theirs.docx"), columns=THEIR_COLUMNS,
                          order=THEIR_ORDER, rows=rows)
    assert not [f for f in _compare(ours, theirs).findings if f.field == "direction"]


def test_a_direction_that_really_changed_is_a_finding(tmp_path):
    rows = [dict(r) for r in ROWS]
    rows[0]["direction"] = "In"
    ours = build_design(str(tmp_path / "ours.docx"))
    theirs = build_design(str(tmp_path / "theirs.docx"), rows=rows)
    differs = [f for f in _compare(ours, theirs).findings if f.field == "direction"]
    assert len(differs) == 1 and differs[0].priority == P1


def test_a_global_row_keeps_its_declared_type_out_of_the_parameter_list(tmp_path):
    ours = build_design(str(tmp_path / "ours.docx"))
    doc = _extract(ours)
    rows = {r.name: r for r in doc.of_kind("component")[0].of_kind("unit")[0].of_kind("interface")}
    assert rows["s_count"].fields["variableType"] == "int"
    assert "dataTypeParams" not in rows["s_count"].fields


def test_a_void_function_has_no_parameters_and_no_ranges(tmp_path):
    ours = build_design(str(tmp_path / "ours.docx"))
    doc = _extract(ours)
    rows = {r.name: r for r in doc.of_kind("component")[0].of_kind("unit")[0].of_kind("interface")}
    assert rows["statRead"].fields["dataTypeParams"] == []
    assert rows["statRead"].fields["dataRangeParams"] == []


def test_non_ascii_content_survives_the_round_trip(tmp_path):
    rows = [dict(r) for r in ROWS]
    rows[0]["information"] = "Übergröße — naïve façade ✓"
    path = build_design(str(tmp_path / "a.docx"), rows=rows)
    doc = _extract(path)
    first = doc.of_kind("component")[0].of_kind("unit")[0].of_kind("interface")[0]
    assert first.fields["information"] == "Übergröße — naïve façade ✓"


# --- the tables no generated document on disk happens to contain -------------

def _five_row_table(doc, description, bullets, input_name, output_name,
                    capacity_label="Capacity"):
    """The Requirements / Risk / Capacity / Input Name / Output Name block."""
    table = doc.add_table(rows=5, cols=2)
    cell = table.rows[0].cells[1]
    cell.paragraphs[0].add_run("Behavior Description")
    for line in bullets:
        cell.add_paragraph(line)
    table.rows[0].cells[0].text = "Requirements"
    for i, (label, value) in enumerate(
            [("Risk", "Medium"), (capacity_label, "Common"),
             ("Input Name", input_name), ("Output Name", output_name)], start=1):
        table.rows[i].cells[0].text = label
        table.rows[i].cells[1].text = value
    return table


def build_with_behaviour(path, bullets, input_name="Lba", output_name="Status",
                         capacity_label="Capacity", heading="2.2.1 Map - lookup (Hub - flush)"):
    """A SWE.3 document carrying a flowchart entry and a Dynamic Behaviour entry.

    Neither table appears in any generated document currently on disk -- the runs
    that produced them had flowcharts off -- so without this the two richest
    extraction paths would only ever be exercised on trees built by hand.
    """
    doc = docx.Document()
    doc.add_heading("1 Introduction", level=1)
    doc.add_heading("2 Diag", level=1)
    doc.add_heading("2.1 Static Design", level=2)
    table = doc.add_table(rows=1, cols=4)
    for i, name in enumerate(["Component", "Unit", "Description", "Note"]):
        table.rows[0].cells[i].text = name
    row = table.add_row()
    for i, value in enumerate(["Diag", "Map", "N/A", "N/A"]):
        row.cells[i].text = value

    doc.add_heading("2.1.1 Map", level=3)
    doc.add_heading("2.1.1.1 unit header", level=4)
    doc.add_heading("2.1.1.2 unit interface", level=4)
    itable = doc.add_table(rows=1, cols=len(OUR_COLUMNS))
    for i, name in enumerate(OUR_COLUMNS):
        itable.rows[0].cells[i].text = name
    r = itable.add_row()
    for i, fieldname in enumerate(OUR_ORDER):
        _fill(r.cells[i], dict(ROWS[0], interfaceName="lookup",
                               interfaceId="IF_LAYER1_G_MAP_01")[fieldname])

    doc.add_heading("2.1.1.3 Map-lookup", level=4)
    _five_row_table(doc, "Looks an entry up.", ["Map calls Hub", "Hub returns to Map"],
                    input_name, output_name, capacity_label)

    doc.add_heading("2.2 Dynamic Behaviour", level=2)
    doc.add_heading(heading, level=3)
    _five_row_table(doc, "The interaction.", bullets, input_name, output_name, capacity_label)
    doc.save(path)
    return path


def test_a_dynamic_behaviour_entry_is_read_as_four_names_and_its_arrows(tmp_path):
    path = build_with_behaviour(str(tmp_path / "a.docx"),
                                ["Hub calls Map to look the entry up", "Map returns to Hub"])
    component = _extract(path).of_kind("component")[0]
    interactions = component.of_kind("interaction")
    assert len(interactions) == 1
    fields = interactions[0].fields
    assert (fields["unit"], fields["function"]) == ("Map", "lookup")
    assert (fields["callerUnit"], fields["callerFunction"]) == ("Hub", "flush")
    assert fields["arrows"] == ["Hub calls Map to look the entry up", "Map returns to Hub"]
    assert fields["risk"] == "Medium" and fields["capacity"] == "Common"
    assert fields["inputName"] == "Lba" and fields["outputName"] == "Status"


def test_the_behavior_description_header_is_not_read_as_an_arrow(tmp_path):
    path = build_with_behaviour(str(tmp_path / "a.docx"), ["A calls B", "B returns to A"])
    arrows = _extract(path).of_kind("component")[0].of_kind("interaction")[0].fields["arrows"]
    assert "Behavior Description" not in arrows


def test_capacity_and_capacity_density_are_the_same_row(tmp_path):
    """The flowchart table writes `Capacity(Density)`, the behaviour table `Capacity`."""
    plain = build_with_behaviour(str(tmp_path / "a.docx"), ["A calls B"])
    dense = build_with_behaviour(str(tmp_path / "b.docx"), ["A calls B"],
                                 capacity_label="Capacity(Density)")
    assert _compare(plain, dense).findings == []


def test_a_flowchart_entry_carries_its_input_and_output_names(tmp_path):
    path = build_with_behaviour(str(tmp_path / "a.docx"), ["A calls B"])
    unit = _extract(path).of_kind("component")[0].of_kind("unit")[0]
    functions = unit.of_kind("function")
    assert [f.name for f in functions] == ["lookup"]
    assert functions[0].fields["inputName"] == "Lba"
    assert functions[0].fields["outputName"] == "Status"


def test_a_changed_arrow_is_a_finding_and_a_reworded_one_is_not_silent(tmp_path):
    a = build_with_behaviour(str(tmp_path / "a.docx"), ["A calls B", "B returns to A"])
    b = build_with_behaviour(str(tmp_path / "b.docx"), ["A calls B"])
    result = _compare(a, b)
    differs = [f for f in result.findings if f.field == "arrows"]
    assert len(differs) == 1 and differs[0].level == "L5"
    # one bullet fewer is counted once, at L4; the L5 detail follows from it
    count = [f for f in result.findings if f.field == "arrowCount"]
    assert len(count) == 1 and count[0].level == "L4"
    assert differs[0].follows


def test_a_dropped_interaction_is_found_in_a_real_document(tmp_path):
    a = build_with_behaviour(str(tmp_path / "a.docx"), ["A calls B"])
    b = build_design(str(tmp_path / "b.docx"), unit_heading="2.1.1 Map",
                     rows=[dict(ROWS[0], interfaceName="lookup",
                                interfaceId="IF_LAYER1_G_MAP_01")])
    missing = [f for f in _compare(a, b).findings
               if f.kind == "missing" and f.entity == "interaction"]
    assert len(missing) == 1


def test_an_interaction_heading_that_does_not_parse_leaves_the_names_empty(tmp_path):
    path = build_with_behaviour(str(tmp_path / "a.docx"), ["A calls B"],
                                heading="2.2.1 something else entirely")
    interactions = _extract(path).of_kind("component")[0].of_kind("interaction")
    assert len(interactions) == 1
    assert "unit" not in interactions[0].fields


# --- the alias file ---------------------------------------------------------

def test_an_alias_file_is_read_from_disk(tmp_path):
    path = tmp_path / "aliases.txt"
    path.write_text("# ours = theirs\nVoidAsVar = LegacyVoidHandler\n\nSample Core=SampleCore\n",
                    encoding="utf-8")
    aliases = match.Aliases.load(str(path))
    assert len(aliases) == 2
    assert aliases.key("VoidAsVar") == aliases.key("LegacyVoidHandler")
    assert aliases.key("Sample Core") == aliases.key("SampleCore")


def test_an_alias_file_makes_a_renamed_unit_compare_clean(tmp_path):
    ours = build_design(str(tmp_path / "ours.docx"))
    theirs = build_design(str(tmp_path / "theirs.docx"), unit_heading="2.1.1 StaticCounters")
    assert [f.kind for f in _compare(ours, theirs).findings if f.kind in ("missing", "extra")]

    path = tmp_path / "aliases.txt"
    path.write_text("ClassStatics = StaticCounters\n", encoding="utf-8")
    aliases = match.Aliases.load(str(path))
    result = _compare(ours, theirs, aliases)
    assert not [f for f in result.findings if f.kind in ("missing", "extra", "differs")]


# --- the command line -------------------------------------------------------

def test_the_gate_decides_the_exit_code(tmp_path, capsys):
    from doccheck.__main__ import main
    rows = [dict(r) for r in ROWS]
    rows[0]["direction"] = "In"
    ours = build_design(str(tmp_path / "ours.docx"))
    theirs = build_design(str(tmp_path / "theirs.docx"), rows=rows)

    assert main([ours, theirs]) == 0                          # reporting only
    assert main([ours, theirs, "--gate", "high"]) == 1        # a high finding exists
    assert main([ours, ours, "--gate", "high"]) == 0          # identical documents


def test_the_cli_refuses_a_path_that_is_not_there(tmp_path, capsys):
    from doccheck.__main__ import main
    ours = build_design(str(tmp_path / "ours.docx"))
    assert main([ours, str(tmp_path / "nope.docx")]) == 2


def test_the_cli_writes_the_reports_it_is_asked_for(tmp_path):
    from doccheck.__main__ import main
    rows = [dict(r) for r in ROWS]
    rows[0]["direction"] = "In"
    ours = build_design(str(tmp_path / "ours.docx"))
    theirs = build_design(str(tmp_path / "theirs.docx"), rows=rows)
    md, js = str(tmp_path / "r.md"), str(tmp_path / "r.json")
    assert main([ours, theirs, "--markdown", md, "--json", js]) == 0
    assert "Direction" in open(md, encoding="utf-8").read()
    import json
    assert json.load(open(js, encoding="utf-8"))["summary"]["P1"] >= 1


def test_the_profile_is_detected_from_the_document(tmp_path):
    from doccheck.__main__ import detect
    from doccheck import swe4
    ours = build_design(str(tmp_path / "software_detailed_design_X.docx"))
    assert detect(blocks.read(ours), ours) is swe3
    assert detect([], "software_unit_test_specification_X.docx") is swe4


# --- the matcher, at the edges ----------------------------------------------

@pytest.mark.parametrize("a,b,renamed", [
    ("Lib", "Libs", True),          # a suffix on a short name
    ("Map", "Map2", True),          # a version suffix
    ("FtlSetEntry", "FtlSetEntries", True),
    ("Hub", "Hug", False),          # one letter changed inside: a different name
    ("Map", "Max", False),
    ("Main", "MainLoop", False),    # too much added to be a rename
    ("FtlSetEntry", "FtlGetEntry", False),
])
def test_what_counts_as_a_rename(a, b, renamed):
    from doccheck.model import normalise_key
    assert match.looks_renamed(normalise_key(a), normalise_key(b)) is renamed


def test_one_moved_row_among_many_is_reported_once():
    from doccheck.model import Entity
    left = [Entity(kind="interface", name="n%02d" % i, index=i) for i in range(40)]
    order = list(range(40))
    order.insert(0, order.pop(37))
    right = [Entity(kind="interface", name="n%02d" % n, index=i) for i, n in enumerate(order)]
    pairs, _l, _r = match.match(left, right)
    moved = match.out_of_order(pairs)
    assert len(moved) == 1 and moved[0][0].name == "n37"
