"""The comparison ladder, one deliberate change at a time.

Two real documents that differ wholesale prove nothing about precision: every
rung lights up and any of them could be the reason. So each test here starts from
one tree, changes exactly one thing, and asserts what comes back -- both that the
finding is raised, and that nothing else is.

The last group is the one that matters most in practice. A missing unit must not
report its forty interfaces as forty missing rows; an inserted unit must not
report every unit below it as moved. Those are the failure modes of the line diff
this tool replaces, and they are what the ladder and the matcher exist to prevent.
"""
import copy
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.path.join(_ROOT, "tools") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "tools"))

from doccheck import compare as comparing, match, rules, swe3    # noqa: E402
from doccheck.model import HIGH, INFO, LOW, MEDIUM, Entity       # noqa: E402

pytestmark = pytest.mark.unit


# --- builders ---------------------------------------------------------------

def iface(name, index=0, unit_name="U", **fields):
    base = {
        "interfaceId": "IF_LAYER1_G_%s_%02d" % (unit_name.upper().replace("_", ""), index + 1),
        "information": "-",
        "dataTypeParams": ["int a"],
        "dataTypeReturn": "int",
        "dataRangeParams": ["0-1"],
        "dataRangeReturn": "0-1",
        "direction": "Out",
        "sourceDest": ["Layer1.App/Main"],
        "interfaceType": "Function",
    }
    base.update(fields)
    return Entity(kind="interface", name=name, index=index, fields=base)


def unit(name, ifaces=(), functions=(), index=0):
    u = Entity(kind="unit", name=name, index=index,
               fields={"hasHeaderTable": True, "hasInterfaceTable": True, "diagramCount": 1})
    stem = "".join(ch for ch in name if ch.isalnum()).upper()
    for i, f in enumerate(ifaces):
        f.index = i
        # The id is derived from the unit it sits in, so the fixture obeys the
        # same rule `id_integrity` checks -- a fixture that cannot pass the
        # self-checks would make every comparison test meaningless.
        f.fields["interfaceId"] = "IF_LAYER1_G_%s_%02d" % (stem, i + 1)
        u.children.append(f)
    for i, fname in enumerate(functions):
        u.children.append(Entity(kind="function", name=fname, index=i,
                                 fields={"flowchartCount": 1, "risk": "Medium",
                                         "capacity": "Common", "inputName": "A",
                                         "outputName": "B"}))
    return u


def component(name, units=(), interactions=(), index=0):
    c = Entity(kind="component", name=name, index=index,
               fields={"unitTableUnits": [u.name for u in units], "diagramCount": 2})
    for i, u in enumerate(units):
        u.index = i
        c.children.append(u)
    for i, ia in enumerate(interactions):
        ia.index = i
        c.children.append(ia)
    return c


def interaction(unit_name, func, caller_unit, caller_func, arrows=(), index=0):
    return Entity(
        kind="interaction",
        name="%s - %s (%s - %s)" % (unit_name, func, caller_unit, caller_func),
        index=index,
        fields={"unit": unit_name, "function": func, "callerUnit": caller_unit,
                "callerFunction": caller_func, "arrows": list(arrows),
                "risk": "Medium", "capacity": "Common", "diagramCount": 1},
    )


def document(components=()):
    d = Entity(kind="document", name="SWE.3")
    d.children.append(Entity(kind="section", name="Introduction", index=0))
    for i, c in enumerate(components):
        c.index = i
        d.children.append(c)
    d.children.append(Entity(kind="section", name="Code Metrics", index=1))
    return d


def sample():
    """Two components, four units, a handful of rows -- the shape of a real one."""
    return document([
        component("Diag", [
            unit("ClassStatics", [iface("statBump", 0), iface("statRead", 1),
                                  iface("s_count", 2, interfaceType="Global Variable",
                                        direction="In/Out", variableType="int",
                                        variableRange="0-255",
                                        dataTypeParams=None, dataTypeReturn=None,
                                        dataRangeParams=None, dataRangeReturn=None)],
                 functions=["statBump", "statRead"]),
            unit("VoidAsVar", [iface("voidArg", 0)], functions=["voidArg"]),
        ]),
        component("Support", [
            unit("Main", [iface("mainEntry", 0)], functions=["mainEntry"]),
            unit("Helper", [iface("helpOne", 0), iface("helpTwo", 1)],
                 functions=["helpOne", "helpTwo"]),
        ]),
    ])


def run(left, right, aliases=None):
    result = comparing.compare(left, right, swe3, aliases)
    rules.annotate(result, left, right)
    return result


def kinds(result, *wanted):
    return [f for f in result.findings if f.kind in wanted]


def paths(result, *wanted):
    return sorted(f.path for f in result.findings if f.kind in wanted)


# --- the floor --------------------------------------------------------------

def test_a_document_compared_with_itself_says_nothing():
    doc = sample()
    assert run(doc, copy.deepcopy(doc)).findings == []


def test_the_sample_passes_its_own_integrity_checks():
    # id_integrity numbers rows within a unit; the builder must not be lying.
    assert comparing.self_checks(sample(), swe3) == []


# --- L0: document shape -----------------------------------------------------

def test_a_missing_top_level_section_is_found_at_L0():
    right = sample()
    right.children = [c for c in right.children
                      if not (c.kind == "section" and c.name == "Code Metrics")]
    result = run(sample(), right)
    missing = kinds(result, "missing")
    assert [f.path for f in missing] == ["Code Metrics"]
    assert missing[0].level == "L0"


def test_an_added_section_is_reported_as_extra_not_as_a_change():
    right = sample()
    right.children.append(Entity(kind="section", name="Appendix B", index=2))
    result = run(sample(), right)
    assert [f.kind for f in kinds(result, "extra", "missing")] == ["extra"]


# --- L1: inventory ----------------------------------------------------------

def test_a_missing_unit_is_high_severity():
    right = sample()
    diag = right.of_kind("component")[0]
    diag.children = [c for c in diag.children if c.name != "VoidAsVar"]
    diag.fields["unitTableUnits"] = ["ClassStatics"]
    result = run(sample(), right)
    missing = [f for f in result.findings if f.kind == "missing" and "unit" in f.summary]
    assert len(missing) == 1
    assert missing[0].path == "Diag / VoidAsVar"
    assert missing[0].severity == HIGH
    assert missing[0].level == "L1"


def test_a_missing_unit_does_not_drag_its_rows_into_the_report():
    """The cascade this whole design exists to prevent."""
    right = sample()
    diag = right.of_kind("component")[0]
    diag.children = [c for c in diag.children if c.name != "ClassStatics"]
    diag.fields["unitTableUnits"] = ["VoidAsVar"]
    result = run(sample(), right)
    # ClassStatics has three interfaces and two functions. None of them may appear.
    below = [f for f in result.findings if "ClassStatics /" in f.path]
    assert below == [], "an unmatched unit leaked %d child findings" % len(below)
    assert len([f for f in result.findings if f.kind == "missing"]) == 1


def test_a_renamed_unit_is_a_rename_not_a_delete_and_an_add():
    right = sample()
    diag = right.of_kind("component")[0]
    diag.children[1].name = "VoidAsVars"          # VoidAsVar -> VoidAsVars
    diag.fields["unitTableUnits"] = ["ClassStatics", "VoidAsVars"]
    result = run(sample(), right)
    renamed = kinds(result, "renamed")
    assert len(renamed) == 1
    assert renamed[0].left == "VoidAsVar" and renamed[0].right == "VoidAsVars"
    assert not kinds(result, "missing", "extra")


def test_a_name_that_is_merely_different_is_not_matched_up():
    right = sample()
    diag = right.of_kind("component")[0]
    diag.children[1].name = "TotallyOther"
    diag.fields["unitTableUnits"] = ["ClassStatics", "TotallyOther"]
    result = run(sample(), right)
    assert not kinds(result, "renamed")
    assert len(kinds(result, "missing")) == 1 and len(kinds(result, "extra")) == 1


def test_case_spacing_and_underscores_are_not_differences():
    right = sample()
    diag = right.of_kind("component")[0]
    diag.children[0].name = "class_statics"
    diag.children[1].name = "Void As Var"
    diag.fields["unitTableUnits"] = ["class_statics", "Void As Var"]
    assert run(sample(), right).findings == []


def test_an_alias_file_settles_a_disagreement_no_algorithm_can():
    right = sample()
    diag = right.of_kind("component")[0]
    diag.children[1].name = "LegacyVoidHandler"
    diag.fields["unitTableUnits"] = ["ClassStatics", "LegacyVoidHandler"]
    aliases = match.Aliases([("VoidAsVar", "LegacyVoidHandler")])
    assert run(sample(), right, aliases).findings == []


# --- order ------------------------------------------------------------------

def test_reordered_units_are_reported_as_order_and_nothing_else():
    right = sample()
    support = right.of_kind("component")[1]
    support.children.reverse()
    for i, u in enumerate(support.children):
        u.index = i
    result = run(sample(), right)
    assert not kinds(result, "missing", "extra", "differs")
    order = kinds(result, "order")
    assert order and all(f.severity == LOW for f in order)


def test_moving_one_unit_reports_one_unit_not_all_of_them():
    """A single insertion must not read as 'everything below it moved'."""
    left = document([component("C", [unit("U%d" % i) for i in range(8)])])
    right = document([component("C", [unit("U%d" % i) for i in [7, 0, 1, 2, 3, 4, 5, 6]])])
    for c in list(left.of_kind("component")) + list(right.of_kind("component")):
        c.fields["unitTableUnits"] = [u.name for u in c.of_kind("unit")]
    result = run(left, right)
    moved = kinds(result, "order")
    assert len(moved) == 1, "one moved unit reported as %d" % len(moved)
    assert moved[0].path == "C / U7"


# --- L2: per unit -----------------------------------------------------------

def test_a_dropped_interface_row_is_found_and_counted():
    right = sample()
    u = right.of_kind("component")[0].of_kind("unit")[0]
    u.children = [c for c in u.children if c.name != "statRead"]
    result = run(sample(), right)
    missing = [f for f in result.findings if f.kind == "missing" and "interface" in f.summary]
    assert [f.path for f in missing] == ["Diag / ClassStatics / statRead"]
    counts = [f for f in result.findings if f.kind == "count" and "interface" in f.summary]
    assert counts and counts[0].left == 3 and counts[0].right == 2


def test_a_function_with_no_interface_row_is_caught_without_a_second_document():
    doc = sample()
    u = doc.of_kind("component")[0].of_kind("unit")[0]
    u.children.append(Entity(kind="function", name="ghostFunction", index=9,
                             fields={"flowchartCount": 1}))
    findings = comparing.self_checks(doc, swe3)
    assert any("ghostFunction" in f.summary for f in findings)


def test_a_unit_missing_from_the_component_table_is_caught_the_same_way():
    doc = sample()
    doc.of_kind("component")[0].fields["unitTableUnits"] = ["ClassStatics"]
    findings = comparing.self_checks(doc, swe3)
    assert any("VoidAsVar" in f.summary and "Component/Unit table" in f.summary
               for f in findings)


# --- L3: the fields of a matched row ----------------------------------------

def test_a_flipped_direction_is_high_severity():
    right = sample()
    row = right.of_kind("component")[0].of_kind("unit")[0].of_kind("interface")[0]
    row.fields["direction"] = "In"
    result = run(sample(), right)
    differs = kinds(result, "differs")
    assert len(differs) == 1
    assert differs[0].field == "direction" and differs[0].severity == HIGH


@pytest.mark.parametrize("written,same_as", [
    ("in", "In"), ("OUT", "Out"), ("In/Out", "InOut"), ("in / out", "In/Out"),
    ("input", "In"), ("output", "Out"), ("bidirectional", "In/Out"),
])
def test_direction_spellings_that_mean_the_same_thing_are_not_findings(written, same_as):
    left, right = sample(), sample()
    left.of_kind("component")[0].of_kind("unit")[0].of_kind("interface")[0].fields["direction"] = written
    right.of_kind("component")[0].of_kind("unit")[0].of_kind("interface")[0].fields["direction"] = same_as
    assert not kinds(run(left, right), "differs")


def test_an_unknown_direction_is_left_alone_and_reported():
    """Folding an unrecognised value into the nearest known one would hide it."""
    right = sample()
    right.of_kind("component")[0].of_kind("unit")[0].of_kind("interface")[0].fields["direction"] = "Inbound"
    differs = kinds(run(sample(), right), "differs")
    assert len(differs) == 1 and differs[0].field == "direction"


def test_callers_are_a_set_so_their_order_is_not_a_difference():
    left, right = sample(), sample()
    left.of_kind("component")[0].of_kind("unit")[0].of_kind("interface")[0].fields["sourceDest"] = ["A/x", "B/y"]
    right.of_kind("component")[0].of_kind("unit")[0].of_kind("interface")[0].fields["sourceDest"] = ["B/y", "A/x"]
    assert not kinds(run(left, right), "differs")


def test_a_caller_that_is_gone_is_a_difference():
    right = sample()
    right.of_kind("component")[0].of_kind("unit")[0].of_kind("interface")[0].fields["sourceDest"] = []
    differs = kinds(run(sample(), right), "differs")
    assert len(differs) == 1 and differs[0].field == "sourceDest"
    assert differs[0].severity == HIGH


def test_parameters_are_a_sequence_so_their_order_is_a_difference():
    left, right = sample(), sample()
    left.of_kind("component")[0].of_kind("unit")[0].of_kind("interface")[0].fields["dataTypeParams"] = ["int a", "int b"]
    right.of_kind("component")[0].of_kind("unit")[0].of_kind("interface")[0].fields["dataTypeParams"] = ["int b", "int a"]
    differs = kinds(run(left, right), "differs")
    assert len(differs) == 1 and differs[0].field == "dataTypeParams"


def test_the_interface_id_is_ours_and_is_never_compared_across_documents():
    right = sample()
    for i, row in enumerate(right.of_kind("component")[0].of_kind("unit")[0].of_kind("interface")):
        row.fields["interfaceId"] = "CLIENT_ID_%d" % i
    assert not [f for f in run(sample(), right).findings if f.field == "interfaceId"]


def test_a_reworded_description_is_informational_not_a_defect():
    right = sample()
    row = right.of_kind("component")[0].of_kind("unit")[0].of_kind("interface")[0]
    row.fields["information"] = "Bumps the counter by one."
    differs = kinds(run(sample(), right), "differs")
    assert len(differs) == 1
    assert differs[0].field == "information" and differs[0].severity == INFO


@pytest.mark.parametrize("a,b", [("-", "N/A"), ("", "-"), ("NA", "n/a"), ("-", "None")])
def test_two_ways_of_writing_nothing_are_not_a_difference(a, b):
    left, right = sample(), sample()
    left.of_kind("component")[0].of_kind("unit")[0].of_kind("interface")[0].fields["information"] = a
    right.of_kind("component")[0].of_kind("unit")[0].of_kind("interface")[0].fields["information"] = b
    assert not kinds(run(left, right), "differs")


def test_a_row_that_changed_kind_is_caught_by_the_type_column():
    right = sample()
    row = right.of_kind("component")[0].of_kind("unit")[0].of_kind("interface")[2]
    row.fields["interfaceType"] = "Function"
    differs = [f for f in kinds(run(sample(), right), "differs") if f.field == "interfaceType"]
    assert len(differs) == 1 and differs[0].severity == HIGH


# --- L4: dynamic behaviour --------------------------------------------------

def test_interactions_compare_as_a_set_of_four_names():
    left = document([component("Diag", [unit("A")], [
        interaction("A", "run", "B", "call", arrows=["A calls B", "B returns to A"]),
    ])])
    right = document([component("Diag", [unit("A")], [
        interaction("A", "run", "B", "call", arrows=["A calls B", "B returns to A"]),
    ])])
    for d in (left, right):
        d.of_kind("component")[0].fields["unitTableUnits"] = ["A"]
    assert run(left, right).findings == []


def test_a_dropped_interaction_is_found_at_L4():
    left = document([component("Diag", [unit("A")], [
        interaction("A", "run", "B", "call", index=0),
        interaction("A", "stop", "C", "halt", index=1),
    ])])
    right = document([component("Diag", [unit("A")], [
        interaction("A", "run", "B", "call", index=0),
    ])])
    for d in (left, right):
        d.of_kind("component")[0].fields["unitTableUnits"] = ["A"]
    result = run(left, right)
    missing = kinds(result, "missing")
    assert len(missing) == 1 and missing[0].level == "L4"


def test_changed_arrows_are_a_sequence_difference():
    left = document([component("Diag", [unit("A")], [
        interaction("A", "run", "B", "call", arrows=["A calls B", "B returns to A"]),
    ])])
    right = document([component("Diag", [unit("A")], [
        interaction("A", "run", "B", "call", arrows=["A calls B"]),
    ])])
    for d in (left, right):
        d.of_kind("component")[0].fields["unitTableUnits"] = ["A"]
    differs = kinds(run(left, right), "differs")
    assert len(differs) == 1 and differs[0].field == "arrows"


# --- rule attribution -------------------------------------------------------

def test_a_header_only_unit_on_their_side_is_explained_by_our_own_rule():
    right = sample()
    ghost = unit("HeaderOnly", index=9)
    ghost.children = []
    right.of_kind("component")[0].children.append(ghost)
    right.of_kind("component")[0].fields["unitTableUnits"].append("HeaderOnly")
    result = run(sample(), right)
    extra = [f for f in result.findings if f.kind == "extra" and f.path.endswith("HeaderOnly")]
    assert extra and "source file" in extra[0].rule


def test_extra_callers_on_their_side_point_at_the_callers_only_rule():
    right = sample()
    row = right.of_kind("component")[0].of_kind("unit")[0].of_kind("interface")[0]
    row.fields["sourceDest"] = ["Layer1.App/Main", "Layer1.Other/Callee"]
    result = run(sample(), right)
    differs = [f for f in result.findings if f.field == "sourceDest"]
    assert differs and "call" in differs[0].rule


def test_a_fixed_placeholder_drifting_is_demoted_to_informational():
    right = sample()
    fn = right.of_kind("component")[0].of_kind("unit")[0].of_kind("function")[0]
    fn.fields["risk"] = "High"
    result = run(sample(), right)
    differs = [f for f in result.findings if f.field == "risk"]
    assert differs and differs[0].severity == INFO and "fixed at Medium" in differs[0].rule


def test_an_unresolved_data_range_points_at_the_data_dictionary():
    right = sample()
    row = right.of_kind("component")[0].of_kind("unit")[0].of_kind("interface")[0]
    row.fields["dataRangeParams"] = ["NA"]
    result = run(sample(), right)
    differs = [f for f in result.findings if f.field == "dataRangeParams"]
    assert differs and "data dictionary" in differs[0].rule


# --- the report -------------------------------------------------------------

def test_the_score_counts_what_matched_not_what_was_found():
    right = sample()
    diag = right.of_kind("component")[0]
    diag.children = [c for c in diag.children if c.name != "VoidAsVar"]
    result = run(sample(), right)
    assert result.left_total["unit"] == 4 and result.matched["unit"] == 3
    assert result.score("unit") == pytest.approx(0.75)


def test_findings_are_ordered_worst_first():
    right = sample()
    diag = right.of_kind("component")[0]
    diag.children = [c for c in diag.children if c.name != "VoidAsVar"]
    row = diag.of_kind("unit")[0].of_kind("interface")[0]
    row.fields["information"] = "reworded"
    result = run(sample(), right)
    order = [f.severity for f in result.findings]
    rank = {HIGH: 0, MEDIUM: 1, LOW: 2, INFO: 3}
    assert order == sorted(order, key=lambda s: rank[s])


# --- unit header rows -------------------------------------------------------
#
# A header row is identified by the SYMBOL it declares, not by its declaration text. The
# old identity made the row's own value part of its identity, so a changed macro value read
# as one row missing plus one appearing -- and a changed value INSIDE parentheses vanished
# entirely, because the key dropped everything after the first '('.

def headerdef(decl, info="", index=0):
    """Built the way swe3.py builds one, so the tests exercise the real shape."""
    from doccheck import cells
    kind, sym, norm = cells.declaration(decl)
    fields = {"declKind": kind or "unparsed", "declaration": norm or decl}
    if kind in ("struct", "class") or (kind == "typedef" and "=" not in info):
        fields["description"] = info
    else:
        fields["value"] = info
    return Entity(kind="headerdef", name=sym or decl, index=index, fields=fields)


def with_headers(rows):
    u = unit("HdrUnit")
    for i, r in enumerate(rows):
        r.index = i
        u.children.append(r)
    return document([component("Comp", [u])])


def test_identical_header_tables_say_nothing():
    doc = with_headers([headerdef("#define MAXN 256", "256"),
                        headerdef("int g_x = 0;", "0")])
    assert run(doc, copy.deepcopy(doc)).findings == []


def test_changed_macro_value_is_one_differs_not_a_missing_and_an_extra():
    left = with_headers([headerdef("#define MAXN 256", "256")])
    right = with_headers([headerdef("#define MAXN 512", "512")])
    result = run(left, right)
    assert kinds(result, "missing", "extra") == []
    differs = kinds(result, "differs")
    assert {f.field for f in differs} == {"declaration", "value"}


def test_changed_value_inside_parentheses_is_seen():
    """The old key dropped everything after the first '(' -- this went unreported."""
    left = with_headers([headerdef("#define SCALE (1<<6)", "(1<<6)")])
    right = with_headers([headerdef("#define SCALE (1<<7)", "(1<<7)")])
    assert kinds(run(left, right), "differs")


def test_reformatting_a_declaration_is_not_a_difference():
    left = with_headers([headerdef("int  g_x=0 ;", "0")])
    right = with_headers([headerdef("int g_x = 0;   // now with a comment", "0")])
    assert run(left, right).findings == []


def test_a_renamed_symbol_is_missing_plus_extra():
    left = with_headers([headerdef("#define MAXN 256", "256")])
    right = with_headers([headerdef("#define MAX_ITEMS 256", "256")])
    result = run(left, right)
    assert len(kinds(result, "missing")) == 1
    assert len(kinds(result, "extra")) == 1


def test_a_reworded_struct_description_is_advisory():
    left = with_headers([headerdef("struct S { int a; };", "Structure for S")])
    right = with_headers([headerdef("struct S { int a; };", "A structure holding a")])
    differs = kinds(run(left, right), "differs")
    assert [f.field for f in differs] == ["description"]
    assert differs[0].severity == INFO


def test_counts_are_reported_per_kind():
    left = with_headers([headerdef("#define A 1", "1"), headerdef("#define B 2", "2"),
                         headerdef("int g_x = 0;", "0")])
    right = with_headers([headerdef("#define A 1", "1")])
    counts = [f.summary for f in kinds(run(left, right), "count")]
    assert any("headerdef define count: 2 -> 1" in c for c in counts)
    assert any("headerdef global count: 1 -> 0" in c for c in counts)


def test_a_private_row_only_we_have_carries_the_rule_and_drops_to_info():
    left = with_headers([headerdef("#define A 1", "1"), headerdef("PRIVATE int g_count = 0;", "0")])
    right = with_headers([headerdef("#define A 1", "1")])
    extra = [f for f in run(right, left).findings if f.kind == "extra"]
    assert len(extra) == 1
    assert "declares and uses" in extra[0].rule
    assert extra[0].severity == INFO


def test_a_union_only_they_have_is_explained():
    left = with_headers([headerdef("#define A 1", "1")])
    right = with_headers([headerdef("#define A 1", "1"), headerdef("union U { int a; };", "-")])
    missing = [f for f in run(right, left).findings if f.kind == "missing"]
    assert len(missing) == 1
    assert "not recorded by the parser" in missing[0].rule
