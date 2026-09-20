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
from doccheck.model import HIGH, INFO, LOW, MEDIUM                      # noqa: E402

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
    assert result.findings == [], [f.summary for f in result.findings]


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
    assert len([f for f in result.findings if f.kind == "missing"]) == len(ROWS)


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
    assert len(differs) == 1 and differs[0].severity == HIGH


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
    assert json.load(open(js, encoding="utf-8"))["summary"]["high"] >= 1


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
