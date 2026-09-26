"""The five levels, one behaviour at a time.

    L1 headings    every kind of heading is there
    L2 inventory   the same components, units, dynamic behaviours -- by name
    L3 sections    per unit: the same function headings and sub-sections
    L4 views       per table and diagram: the same rows (by name), images, counts
    L5 content     what the matched rows say

The tests pin what makes the levels worth having: names are compared and not only
counts; each level checks only what the level above matched; and one fact is
counted once, at the first level that sees it -- the levels below show it as
`follows`, for its detail.
"""
import copy
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.path.join(_ROOT, "tools") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "tools"))

from doccheck import compare as comparing, rules, swe3, swe4    # noqa: E402
from doccheck.model import P1, P2, P3, P4, Entity                # noqa: E402

pytestmark = pytest.mark.unit


# --- a SWE.3 tree, built the way the extractor builds one ----------------------

def row(name, itype="Function", **fields):
    base = {"interfaceId": "", "information": "-", "dataTypeParams": ["int a"],
            "dataTypeReturn": "int", "dataRangeParams": ["0-1"], "dataRangeReturn": "0-1",
            "direction": "Out", "sourceDest": ["Layer1.App/Main"], "interfaceType": itype}
    base.update(fields)
    return Entity(kind="interface", name=name, fields=base)


def func(name, **fields):
    base = {"flowchartCount": 1, "risk": "Medium", "capacity": "Common",
            "inputName": "In", "outputName": "Out", "heading": name}
    base.update(fields)
    return Entity(kind="function", name=name, fields=base)


def unit(name, functions=(), globals_=(), header=True, interface=True):
    u = Entity(kind="unit", name=name,
               fields={"hasHeaderSection": header, "hasHeaderTable": header,
                       "hasInterfaceSection": interface, "hasInterfaceTable": interface,
                       "diagramCount": 1,
                       "interfaceColumnSet": ["interfaceId", "interfaceName", "direction",
                                              "interfaceType"],
                       "interfaceColumns": ["Interface ID", "Interface Name",
                                            "Direction(In/Out)", "Interface Type"]})
    stem = "".join(ch for ch in name if ch.isalnum()).upper()
    n = 0
    for fname in functions:
        u.children.append(func(fname, heading="%s-%s" % (name, fname)))
        n += 1
        u.children.append(row(fname, interfaceId="IF_L1_G_%s_%02d" % (stem, n)))
    for gname in globals_:
        n += 1
        u.children.append(row(gname, "Global Variable", interfaceId="IF_L1_G_%s_%02d" % (stem, n),
                              direction="In/Out", variableType="int", variableRange="0-1",
                              dataTypeParams=None, dataTypeReturn=None,
                              dataRangeParams=None, dataRangeReturn=None))
    for i, c in enumerate(u.children):
        c.index = i
    return u


def doc(*units, sections=("Introduction", "Code Metrics"), component="Comp"):
    d = Entity(kind="document", name="SWE.3")
    d.children.append(Entity(kind="section", name=sections[0], index=0))
    c = Entity(kind="component", name=component,
               fields={"unitTableUnits": [u.name for u in units], "diagramCount": 2})
    for i, u in enumerate(units):
        u.index = i
        c.children.append(u)
    d.children.append(c)
    for i, name in enumerate(sections[1:]):
        d.children.append(Entity(kind="section", name=name, index=i + 1))
    return d


def base():
    return doc(unit("Io", ["ioRead", "ioReadByte", "ioFlush", "ioWrite", "ioInit"]),
               unit("Math", ["add", "sub"], ["g_scale"]))


def run(left, right, level=5, profile=swe3):
    result = comparing.compare(left, right, profile, max_level=level)
    rules.annotate(result, left, right, profile)
    return result


def counted(result, level=None):
    return [f for f in result.findings if f.counted and (level is None or f.level == level)]


def checks(result, level, what=None, unit=None):
    return [c for c in result.checks if c.level == level and (what is None or c.what == what)
            and (unit is None or c.unit == unit)]


def rename_function(d, unit_name, old, new):
    u = [u for u in d.of_kind("component")[0].of_kind("unit") if u.name == unit_name][0]
    for child in u.children:
        if child.name == old:
            child.name = new


# --- the floor --------------------------------------------------------------

def test_a_document_against_itself_has_no_findings_and_every_check_agrees():
    result = run(base(), base())
    assert result.findings == []
    assert result.checks and all(c.ok for c in result.checks)
    assert {c.level for c in result.checks} == {"L1", "L2", "L3", "L4"}


def test_every_finding_sits_on_one_of_the_five_levels():
    right = base()
    rename_function(right, "Io", "ioFlush", "ioSync")
    right.of_kind("component")[0].of_kind("unit")[1].of_kind("interface")[0] \
        .fields["direction"] = "In"
    for f in run(base(), right).findings:
        assert f.level in ("L1", "L2", "L3", "L4", "L5")


# --- L3: names, not only counts --------------------------------------------------

def test_five_function_headings_against_five_is_still_a_difference_when_names_differ():
    right = base()
    rename_function(right, "Io", "ioFlush", "ioSync")          # too different: not a rename
    rename_function(right, "Io", "ioReadByte", "ioReadBytes")  # a rename
    result = run(base(), right)
    row_ = checks(result, "L3", "function headings", "Io")[0]
    assert (row_.left, row_.right) == (5, 5)
    assert not row_.ok and row_.names == "✗ 3 differ"
    l3 = counted(result, "L3")
    assert sorted((f.kind, f.item) for f in l3) == [
        ("extra", "ioSync"), ("missing", "ioFlush"), ("renamed", "ioReadByte")]


def test_the_row_of_a_function_heading_only_one_side_has_follows_the_heading():
    right = base()
    right.of_kind("component")[0].of_kind("unit")[0].children += [func("ioReset"),
                                                                    row("ioReset")]
    result = run(base(), right)
    l3 = [f for f in result.findings if f.level == "L3"]
    l4 = [f for f in result.findings if f.level == "L4" and f.item == "ioReset"]
    assert [f.kind for f in l3] == ["extra"] and l3[0].counted
    assert l4 and all(f.follows == "function heading at L3" for f in l4)
    assert len(counted(result)) == 1                             # one fact, counted once


def test_a_renamed_function_is_compared_below_its_heading():
    right = base()
    rename_function(right, "Io", "ioReadByte", "ioReadBytes")
    io = right.of_kind("component")[0].of_kind("unit")[0]
    [r for r in io.of_kind("interface") if r.name == "ioReadBytes"][0].fields["direction"] = "In"
    result = run(base(), right)
    direction = [f for f in result.findings if f.field == "direction"]
    assert direction and direction[0].level == "L5" and direction[0].priority == P1


def test_a_missing_unit_header_section_is_L3_and_its_table_follows_it():
    right = base()
    io = right.of_kind("component")[0].of_kind("unit")[0]
    io.fields["hasHeaderSection"] = io.fields["hasHeaderTable"] = False
    result = run(base(), right)
    section = [f for f in result.findings if f.field == "hasHeaderSection"]
    table = [f for f in result.findings if f.field == "hasHeaderTable"]
    assert section and section[0].level == "L3" and section[0].counted
    assert table and table[0].level == "L4" and table[0].follows


def test_the_rows_of_a_table_one_side_lacks_are_skipped_not_missing():
    left, right = base(), base()
    left.of_kind("component")[0].of_kind("unit")[1].children.append(
        swe3.header_row("#define SCALE 8", "8"))
    right.of_kind("component")[0].of_kind("unit")[1].fields["hasHeaderTable"] = False
    result = run(left, right)
    assert not [f for f in result.findings if f.entity == "headerdef"]
    skipped = checks(result, "L4", "unit header table rows", "Math")
    assert skipped and skipped[0].skipped


# --- L2: inventory by name --------------------------------------------------------

def test_the_component_unit_table_follows_the_unit_headings():
    right = doc(unit("Io", ["ioRead", "ioReadByte", "ioFlush", "ioWrite", "ioInit"]))
    result = run(base(), right)
    table = [f for f in result.findings if f.field == "unitTableUnits"]
    assert table and table[0].follows == "unit at L2"
    assert [(f.level, f.kind, f.item, f.priority) for f in counted(result)] == \
        [("L2", "missing", "Math", P1)]
    assert checks(result, "L2", "Component/Unit table rows")[0].follows == "units"


def test_a_unit_only_one_side_has_is_not_looked_inside():
    right = doc(unit("Io", ["ioRead", "ioReadByte", "ioFlush", "ioWrite", "ioInit"]))
    result = run(base(), right)
    assert not checks(result, "L3", unit="Math")
    assert not [f for f in result.findings if f.unit == "Math" and f.level != "L2"]


# --- L1: heading kinds -----------------------------------------------------------

def test_a_heading_kind_one_side_has_none_of_is_L1_and_what_it_hides_follows():
    right = base()
    for u in right.of_kind("component")[0].of_kind("unit"):
        u.children = [c for c in u.children if c.kind != "function"]
    result = run(base(), right)
    l1 = counted(result, "L1")
    assert [(f.kind, f.item) for f in l1] == [("missing", "<Unit> › <Unit>-<Function>")]
    below = [f for f in result.findings if f.level == "L3"]
    assert below and all(f.follows == "heading at L1" for f in below)
    assert not counted(result, "L3")


def test_an_unknown_heading_on_their_side_is_named_by_its_title():
    left = base()
    right = doc(*base().of_kind("component")[0].of_kind("unit"),
                sections=("Introduction", "Code Metrics", "Revision History"))
    f = counted(run(left, right), "L1")
    assert [x.item for x in f] == ["H1 Revision History"]
    assert f[0].kind == "extra" and "do not write this section" in f[0].rule


def test_the_l1_checks_list_every_known_heading_kind():
    result = run(base(), base())
    names = [c.what for c in checks(result, "L1")]
    assert names[:2] == ["Introduction", "Introduction › Purpose"]
    assert "<Unit> › unit interface" in names and "Appendix A · Design Guideline" in names


# --- L4: views -----------------------------------------------------------------

def test_a_missing_interface_column_is_P2_and_its_wording_follows():
    right = base()
    io = right.of_kind("component")[0].of_kind("unit")[0]
    io.fields["interfaceColumnSet"] = ["interfaceId", "interfaceName", "interfaceType"]
    io.fields["interfaceColumns"] = ["Interface ID", "Interface Name", "Interface Type"]
    result = run(base(), right)
    columns = [f for f in result.findings if f.field.startswith("interfaceColumn")]
    assert {(f.field, f.priority, bool(f.follows)) for f in columns} == {
        ("interfaceColumnSet", P2, False), ("interfaceColumns", P4, True)}


def test_flowchart_images_are_summed_per_unit_and_named_per_function():
    right = base()
    [f for f in right.of_kind("component")[0].of_kind("unit")[0].of_kind("function")
     if f.name == "ioRead"][0].fields["flowchartCount"] = 3
    result = run(base(), right)
    row_ = checks(result, "L4", "flowchart images", "Io")[0]
    assert (row_.left, row_.right, row_.ok) == (5, 7, False)
    assert "ioRead" in row_.detail


# --- L5: content ------------------------------------------------------------------

def test_content_is_grouped_by_the_view_it_is_read_from():
    right = base()
    math = right.of_kind("component")[0].of_kind("unit")[1]
    math.of_kind("interface")[0].fields["direction"] = "In"
    math.of_kind("function")[0].fields["inputName"] = "Other"
    result = run(base(), right)
    views = {f.field: f.view for f in result.findings}
    assert views == {"direction": "interface table", "inputName": "function sections"}
    assert result.compared[("Comp", "Math", "interface table")] == 3


# --- how far down -------------------------------------------------------------------

@pytest.mark.parametrize("level,deepest", [(1, "L1"), (2, "L2"), (3, "L3"), (4, "L4"), (5, "L5")])
def test_the_level_limit_stops_the_walk(level, deepest):
    right = base()
    right.children = [c for c in right.children if c.name != "Code Metrics"]
    rename_function(right, "Io", "ioFlush", "ioSync")
    io = right.of_kind("component")[0].of_kind("unit")[0]
    io.fields["diagramCount"] = 2
    right.of_kind("component")[0].of_kind("unit")[1].of_kind("interface")[0] \
        .fields["direction"] = "In"
    right.of_kind("component")[0].fields["unitTableUnits"] = ["Io"]
    result = run(base(), right, level=level)
    found = {f.level for f in result.findings} | {c.level for c in result.checks}
    assert max(found) == deepest


# --- SWE.4 --------------------------------------------------------------------------

def case(name, steps=("Issue function f.", "Return x."), **fields):
    base_ = {"hasTableA": True, "hasTableB": True, "precondition": ["None"],
             "input": ["int a[0-1]"], "testSteps": list(steps),
             "testStepShape": [1] * len(steps), "expected": ["Returned x in step 2"],
             "testCaseId": "TC_" + name, "priority": "Medium", "risk": "-",
             "testMethod": "-", "aliasTestId": "-", "linkedWorkItems": "-",
             "generationMethod": "Analysis of Requirements", "testEnvironment": "Emulator",
             "evalEquipment": "PC", "platform": "Win", "heading": "U-" + name,
             "tableBLabels": ["Test Case ID", "Priority"]}
    base_.update(fields)
    for key, source in (("preconditionCount", "precondition"), ("inputCount", "input"),
                        ("stepCount", "testSteps"), ("expectedCount", "expected")):
        base_[key] = len(base_[source])
    base_["stepDepth"] = max(base_["testStepShape"] or [0])
    return Entity(kind="testcase", name=name, fields=base_)


def spec(*cases_):
    d = Entity(kind="document", name="SWE.4")
    c = Entity(kind="component", name="Comp")
    u = Entity(kind="unit", name="U")
    for i, x in enumerate(cases_):
        x.index = i
        u.children.append(x)
    c.children.append(u)
    d.children.append(c)
    return d


def test_swe4_a_step_more_is_counted_at_L4_and_shown_at_L5():
    right = spec(case("f", steps=("Issue function f.", "Check a.", "Return x.")))
    result = run(spec(case("f")), right, profile=swe4)
    assert [(f.level, f.field) for f in counted(result)] == [("L4", "stepCount")]
    shown = [f for f in result.findings if f.field in ("testSteps", "testStepShape")]
    assert shown and all(f.follows for f in shown)


def test_swe4_a_reworded_step_is_L5_in_table_a():
    right = spec(case("f", steps=("Issue function f.", "Return y.")))
    f = counted(run(spec(case("f")), right, profile=swe4))
    assert [(x.level, x.field, x.view, x.priority) for x in f] == \
        [("L5", "testSteps", "Table A", P2)]


def test_swe4_a_missing_table_b_is_a_blocker():
    right = spec(case("f", hasTableB=False))
    f = counted(run(spec(case("f")), right, profile=swe4))
    assert [(x.level, x.field, x.priority) for x in f] == [("L4", "hasTableB", P1)]


def test_swe4_gets_swe4_rules_not_swe3_rules():
    left = spec(case("f"))
    right = spec(case("f"))
    extra = Entity(kind="unit", name="HeaderOnly")
    right.of_kind("component")[0].children.append(extra)
    result = run(left, right, profile=swe4)
    f = [x for x in result.findings if x.entity == "unit"]
    assert f and "SWE4_WIKI" in f[0].rule and "source file" not in f[0].rule


def test_swe4_a_fixed_value_is_explained_and_a_configured_one_too():
    right = spec(case("f", risk="High", priority="High"))
    result = run(spec(case("f")), right, profile=swe4)
    by_field = {f.field: f for f in result.findings}
    assert by_field["risk"].priority == P3 and "fixed at '-'" in by_field["risk"].rule
    assert by_field["priority"].priority == P3 and "configuration" in by_field["priority"].rule
    assert not counted(result) or all(f.priority == P3 for f in counted(result))


def test_swe4_a_missing_test_case_carries_the_header_rule_as_a_possible_reason():
    result = run(spec(case("f"), case("g")), spec(case("f")), profile=swe4)
    f = counted(result)
    assert [(x.level, x.kind, x.item) for x in f] == [("L3", "missing", "g")]
    assert "defined in a header" in f[0].rule and not f[0].explained


# --- self checks sit on levels ------------------------------------------------------

def test_a_self_check_carries_its_level_priority_and_view():
    d = base()
    io = d.of_kind("component")[0].of_kind("unit")[0]
    io.of_kind("interface")[1].fields["interfaceId"] = "IF_L1_G_IO_09"
    found = comparing.self_checks(d, swe3)
    gap = [f for f in found if f.field == "id-gap"]
    assert gap and (gap[0].level, gap[0].priority, gap[0].view) == ("L5", P1, "interface table")
    assert gap[0].component == "Comp" and gap[0].unit == "Io"


def test_a_function_row_with_no_flowchart_heading_is_caught_on_its_own():
    d = base()
    io = d.of_kind("component")[0].of_kind("unit")[0]
    io.children = [c for c in io.children if not (c.kind == "function" and c.name == "ioInit")]
    found = [f for f in comparing.self_checks(d, swe3) if f.field == "row-without-heading"]
    assert found and found[0].item == "ioInit" and found[0].level == "L3"


def test_two_specs_under_one_heading_are_a_self_check_blocker():
    d = spec(case("f"), case("f"))
    found = [f for f in comparing.self_checks(d, swe4) if f.field == "duplicate-heading"]
    assert found and found[0].priority == P1


def test_the_self_check_level_limit_drops_deeper_checks():
    d = base()
    d.of_kind("component")[0].of_kind("unit")[0].of_kind("interface")[1] \
        .fields["interfaceId"] = "bogus"
    assert comparing.self_checks(d, swe3, max_level=4) == []
    assert comparing.self_checks(d, swe3, max_level=5)


def test_explained_findings_keep_the_priority_they_had():
    right = base()
    right.of_kind("component")[0].of_kind("unit")[0].of_kind("function")[0] \
        .fields["risk"] = "High"
    f = [x for x in run(base(), right).findings if x.field == "risk"][0]
    assert (f.priority, f.was, f.explained) == (P3, P2, True)


def test_a_document_compared_with_a_deep_copy_of_itself_is_clean_at_every_level():
    for level in (1, 2, 3, 4, 5):
        d = base()
        assert run(d, copy.deepcopy(d), level=level).findings == []


# --- headings name their unit: the same rules on both documents -----------------------

def test_a_swe3_function_heading_under_the_wrong_unit_is_caught_like_swe4():
    d = base()
    f = d.of_kind("component")[0].of_kind("unit")[0].of_kind("function")[0]
    f.fields["heading"] = "Other-" + f.name
    found = [x for x in comparing.self_checks(d, swe3) if x.field == "heading-unit-mismatch"]
    assert found and (found[0].level, found[0].priority) == ("L3", P2)


def test_a_spaced_dash_is_still_the_unit_on_both_documents():
    d = base()
    f = d.of_kind("component")[0].of_kind("unit")[0].of_kind("function")[0]
    f.fields["heading"] = "Io - " + f.name
    assert not [x for x in comparing.self_checks(d, swe3) if x.field == "heading-unit-mismatch"]
    s = spec(case("f", heading="U - f"))
    assert not [x for x in comparing.self_checks(s, swe4) if x.field == "heading-unit-mismatch"]


def _interaction(unit_name, function):
    return Entity(kind="interaction", name="%s - %s (Main - run)" % (unit_name, function),
                  fields={"unit": unit_name, "function": function, "callerUnit": "Main",
                          "callerFunction": "run"})


@pytest.mark.parametrize("unit_name,function,code", [
    ("Nowhere", "ioRead", "interaction-unit-unknown"),
    ("Io", "ghost", "interaction-function-unknown"),
])
def test_a_swe3_interaction_heading_must_name_a_unit_and_function_of_its_component(
        unit_name, function, code):
    d = base()
    d.of_kind("component")[0].children.append(_interaction(unit_name, function))
    found = [x.field for x in comparing.self_checks(d, swe3) if x.field.startswith("interaction")]
    assert found == [code]


def test_a_swe3_interaction_heading_that_names_what_is_there_passes():
    d = base()
    d.of_kind("component")[0].children.append(_interaction("Io", "ioRead"))
    assert not [x for x in comparing.self_checks(d, swe3) if x.field.startswith("interaction")]


def test_an_unreadable_swe3_interaction_heading_is_caught_like_swe4():
    d = base()
    d.of_kind("component")[0].children.append(
        Entity(kind="interaction", name="something else entirely"))
    found = [x for x in comparing.self_checks(d, swe3)
             if x.field == "interaction-heading-unreadable"]
    assert found and found[0].level == "L2"
