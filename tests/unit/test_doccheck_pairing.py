"""Holding a SWE.3 design against its SWE.4 specification.

The pairing rules are stated in the two wikis, not invented here: every design
function heading gets a test case bar the header-defined ones, a dynamic-behaviour
spec exists exactly where SWE.3 draws a diagram, and a Test Case ID is
`TC_<interfaceId>`. The report reads on the same five levels as any comparison.

The corpus tests run over every generated group that has both documents. They do
not assert "no findings" -- some groups genuinely diverge, and freezing today's
divergences into a test would make the test a record of the bugs rather than a
check on the tool. They assert the properties that must hold whatever the
documents say.
"""
import glob
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.path.join(_ROOT, "tools") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "tools"))

pytest.importorskip("docx", reason="python-docx is needed to read a .docx")

from doccheck import blocks, pairing, swe3, swe4                # noqa: E402
from doccheck.model import P1, P2, P3, P4, Entity               # noqa: E402

pytestmark = pytest.mark.unit


def _groups():
    """(label, design docx, spec docx) for every group that has both."""
    out, seen = [], set()
    patterns = [
        os.path.join(_ROOT, "workspaces", "*", "versions", "*", "output", "*"),
        os.path.join(_ROOT, "output", "*"),
        os.path.join(_ROOT, "output_review", "all-groups", "*"),
    ]
    for pattern in patterns:
        for d in sorted(glob.glob(pattern)):
            design = glob.glob(os.path.join(d, "software_detailed_design_*.docx"))
            spec = glob.glob(os.path.join(d, "software_unit_test_specification_*.docx"))
            if not design or not spec:
                continue
            label = "%s-%s" % (os.path.basename(os.path.dirname(os.path.dirname(d))),
                               os.path.basename(d))
            if label in seen:
                continue
            seen.add(label)
            out.append((label, design[0], spec[0]))
    return out


GROUPS = _groups()


# --- over the generated corpus ----------------------------------------------

def _pair(design_p, spec_p):
    return pairing.check(swe3.extract(blocks.read(design_p)), swe4.extract(blocks.read(spec_p)))


@pytest.mark.skipif(not GROUPS, reason="no group has both documents on disk")
@pytest.mark.parametrize("label,design_p,spec_p", GROUPS, ids=[g[0] for g in GROUPS] or None)
def test_every_finding_names_the_rule_it_comes_from(label, design_p, spec_p):
    """The tool's promise: a difference is never reported without its reason."""
    unexplained = [f.summary for f in _pair(design_p, spec_p).findings if not f.rule]
    assert not unexplained, "%s: %s" % (label, unexplained)


@pytest.mark.skipif(not GROUPS, reason="no group has both documents on disk")
@pytest.mark.parametrize("label,design_p,spec_p", GROUPS, ids=[g[0] for g in GROUPS] or None)
def test_the_test_case_id_is_always_the_interface_id_with_TC_in_front(label, design_p, spec_p):
    """Derived mechanically on both sides, so this must never fire on our output."""
    drift = [f.summary for f in _pair(design_p, spec_p).findings if f.field == "testCaseId"]
    assert not drift, "%s: %s" % (label, drift)


@pytest.mark.skipif(not GROUPS, reason="no group has both documents on disk")
@pytest.mark.parametrize("label,design_p,spec_p", GROUPS, ids=[g[0] for g in GROUPS] or None)
def test_a_function_is_never_reported_as_both_missing_and_extra(label, design_p, spec_p):
    """One function under two names is one finding, not a delete plus an add."""
    findings = _pair(design_p, spec_p).findings
    missing = {f.item.split("::")[-1].casefold()
               for f in findings if f.kind == "missing" and f.field == "spec"}
    extra = {f.item.split("::")[-1].casefold()
             for f in findings if f.kind == "extra" and f.field == "spec"}
    assert not (missing & extra), "%s: reported twice: %s" % (label, sorted(missing & extra))


@pytest.mark.skipif(not GROUPS, reason="no group has both documents on disk")
@pytest.mark.parametrize("label,design_p,spec_p", GROUPS, ids=[g[0] for g in GROUPS] or None)
def test_every_finding_sits_on_a_level(label, design_p, spec_p):
    result = _pair(design_p, spec_p)
    assert all(f.level in ("L1", "L2", "L3", "L4", "L5") for f in result.findings), label
    assert all(c.level in ("L1", "L2", "L3", "L4") for c in result.checks), label


# --- built by hand, one rule at a time --------------------------------------

def _design(units, interactions=(), arrows=None, rows_only=()):
    """A design: every function is a flowchart heading AND an interface row.

    `rows_only` names functions that get a row and no heading; `arrows` maps an
    interaction's function to its Behavior Description bullets.
    """
    doc = Entity(kind="document", name="SWE.3")
    component = Entity(kind="component", name="Diag", index=0,
                       fields={"unitTableUnits": [u for u, _ in units]})
    doc.children.append(component)
    for ui, (unit_name, functions) in enumerate(units):
        unit = Entity(kind="unit", name=unit_name, index=ui,
                      fields={"hasInterfaceTable": True})
        stem = "".join(c for c in unit_name if c.isalnum()).upper()
        for fi, fname in enumerate(functions):
            if fname not in rows_only:
                unit.children.append(Entity(
                    kind="function", name=fname, index=fi,
                    fields={"heading": "%s-%s" % (unit_name, fname)}))
            unit.children.append(Entity(
                kind="interface", name=fname, index=fi,
                fields={"interfaceId": "IF_LAYER1_G_%s_%02d" % (stem, fi + 1),
                        "interfaceType": "Function"}))
        component.children.append(unit)
    for ii, (u, f, cu, cf) in enumerate(interactions):
        component.children.append(Entity(
            kind="interaction", name="%s - %s (%s - %s)" % (u, f, cu, cf), index=ii,
            fields={"unit": u, "function": f, "callerUnit": cu, "callerFunction": cf,
                    "arrows": list((arrows or {}).get(f, []))}))
    return doc


def _spec(units, interactions=(), calls=None):
    doc = Entity(kind="document", name="SWE.4")
    component = Entity(kind="component", name="Diag", index=0)
    doc.children.append(component)
    for ui, (unit_name, functions) in enumerate(units):
        unit = Entity(kind="unit", name=unit_name, index=ui)
        stem = "".join(c for c in unit_name if c.isalnum()).upper()
        for fi, fname in enumerate(functions):
            unit.children.append(Entity(
                kind="testcase", name=fname, index=fi,
                fields={"testCaseId": "TC_IF_LAYER1_G_%s_%02d" % (stem, fi + 1),
                        "heading": "%s-%s" % (unit_name, fname)}))
        component.children.append(unit)
    for ii, (u, f, cu, cf) in enumerate(interactions):
        component.children.append(Entity(
            kind="interaction", name="%s - %s (%s - %s)" % (u, f, cu, cf), index=ii,
            fields={"unit": u, "function": f, "callerUnit": cu, "callerFunction": cf,
                    "testCaseId": "TC_IF_LAYER1_G_U_01_DYN",
                    "expected": ["Successfully called %s in step 2" % c
                                 for c in (calls or {}).get(f, [])],
                    "testSteps": ["Issue function %s." % f]}))
    return doc


def counted(result):
    """The findings that count -- one restating another is shown, not counted."""
    return [f for f in result.findings if f.counted]


def test_two_documents_that_agree_produce_nothing():
    units = [("ClassStatics", ["statBump", "statRead"])]
    result = pairing.check(_design(units), _spec(units))
    assert result.findings == []
    assert all(c.ok for c in result.checks)


def test_a_design_function_with_no_spec_is_reported_with_the_header_rule():
    findings = counted(pairing.check(_design([("U", ["a", "b"])]), _spec([("U", ["a"])])))
    assert len(findings) == 1
    f = findings[0]
    assert f.kind == "missing" and f.item == "b" and f.level == "L3"
    assert "defined in a header" in f.rule and not f.breaks
    assert f.priority == P2


def test_a_spec_for_a_function_the_design_does_not_publish_is_a_blocker():
    findings = counted(pairing.check(_design([("U", ["a"])]), _spec([("U", ["a", "ghost"])])))
    assert len(findings) == 1
    assert findings[0].kind == "extra" and findings[0].priority == P1 and findings[0].breaks


def test_the_same_function_under_two_names_is_one_finding_not_two():
    result = pairing.check(_design([("U", ["Proc::normalize"])]), _spec([("U", ["normalize"])]))
    findings = counted(result)
    assert len(findings) == 1
    assert findings[0].kind == "renamed"
    assert findings[0].left == "Proc::normalize" and findings[0].right == "normalize"
    assert "tells two same-named methods apart" in findings[0].rule
    # the heading text differs too, and follows from the rename
    heading = [f for f in result.findings if f.field == "headingText"]
    assert heading and heading[0].follows


def test_two_methods_that_reduce_to_one_bare_name_cannot_be_paired():
    result = pairing.check(_design([("U", ["A::apply", "B::apply"])]), _spec([("U", ["apply"])]))
    findings = counted(result)
    assert [f.field for f in findings] == ["ambiguousPairing"]
    assert findings[0].priority == P1


def test_a_diagram_with_no_interaction_spec_is_a_gap_counted_once():
    """Only the design has it: a coverage gap to judge (P2), not something invented."""
    result = pairing.check(
        _design([("U", ["a"])], interactions=[("U", "a", "Caller", "call")]),
        _spec([("U", ["a"])]))
    findings = counted(result)
    assert len(findings) == 1
    assert findings[0].kind == "missing" and findings[0].level == "L1"
    assert findings[0].priority == P2 and findings[0].breaks
    # the L2 detail -- which interaction -- follows from the L1 finding
    detail = [f for f in result.findings if f.level == "L2" and f.entity == "interaction"]
    assert detail and detail[0].follows == "heading at L1"


def test_an_interaction_spec_with_no_diagram_names_the_settings():
    result = pairing.check(
        _design([("U", ["a"])], interactions=[("U", "b", "Caller", "go")]),
        _spec([("U", ["a"])], interactions=[("U", "a", "Caller", "call"),
                                             ("U", "b", "Caller", "go")]))
    findings = counted(result)
    assert len(findings) == 1
    f = findings[0]
    assert f.kind == "extra" and f.entity == "interaction" and f.level == "L2"
    assert f.priority == P1
    assert "behaviourDiagram and dynamicBehaviourSpecs" in f.rule
    assert "swe4_dynamic_diff" not in f.rule


def test_matching_interactions_produce_nothing():
    interactions = [("U", "a", "Caller", "call")]
    result = pairing.check(_design([("U", ["a"])], interactions),
                           _spec([("U", ["a"])], interactions))
    assert result.findings == []


def test_a_test_case_id_that_is_not_the_interface_id_is_reported_at_L5():
    design = _design([("U", ["a"])])
    spec = _spec([("U", ["a"])])
    spec.of_kind("component")[0].of_kind("unit")[0].of_kind("testcase")[0] \
        .fields["testCaseId"] = "TC_SOMETHING_ELSE"
    findings = counted(pairing.check(design, spec))
    assert len(findings) == 1 and findings[0].field == "testCaseId"
    assert findings[0].level == "L5" and findings[0].priority == P1


def test_a_heading_that_differs_only_in_spacing_is_cosmetic():
    design = _design([("U", ["a"])])
    spec = _spec([("U", ["a"])])
    spec.of_kind("component")[0].of_kind("unit")[0].of_kind("testcase")[0] \
        .fields["heading"] = "U - a"
    findings = counted(pairing.check(design, spec))
    assert [(f.field, f.priority) for f in findings] == [("headingText", P4)]


def test_a_design_unit_with_no_function_heading_expects_no_spec():
    design = _design([("U", ["a"]), ("HeaderOnly", [])])
    result = pairing.check(design, _spec([("U", ["a"])]))
    assert result.findings == []
    units = [c for c in result.checks if c.what == "units"][0]
    assert "no spec expected" in units.skipped


def test_a_whole_unit_without_a_spec_is_a_gap_at_L2():
    findings = counted(pairing.check(_design([("U", ["a"]), ("V", ["b"])]),
                                     _spec([("U", ["a"])])))
    assert [(f.level, f.entity, f.kind, f.priority) for f in findings] == \
        [("L2", "unit", "missing", P2)]


def test_a_unit_only_the_spec_has_is_a_blocker():
    findings = counted(pairing.check(_design([("U", ["a"])]),
                                     _spec([("U", ["a"]), ("V", ["b"])])))
    assert [(f.level, f.entity, f.kind, f.priority) for f in findings] == \
        [("L2", "unit", "extra", P1)]


def test_the_level_limit_stops_the_pairing():
    result = pairing.check(_design([("U", ["a", "b"])]), _spec([("U", ["a"])]), max_level=2)
    assert result.findings == []
    assert not [c for c in result.checks if c.level == "L3"]


def test_the_summary_counts_both_sides():
    line = pairing.summary(_design([("U", ["a", "b"])]), _spec([("U", ["a"])]), [])
    assert "2 function heading(s)" in line and "1 test case(s)" in line


# --- SWE.3 is the input to SWE.4: the interface table and the arrows ----------------

def test_a_function_row_with_no_heading_and_no_spec_is_found_at_L4():
    design = _design([("U", ["a", "b"])], rows_only=("b",))
    result = pairing.check(design, _spec([("U", ["a"])]))
    found = counted(result)
    assert [(f.level, f.kind, f.item, f.priority) for f in found] == [("L4", "missing", "b", P2)]
    assert "interface table" in found[0].rule


def test_a_function_missing_both_heading_spec_and_row_spec_is_counted_once():
    result = pairing.check(_design([("U", ["a", "b"])]), _spec([("U", ["a"])]))
    b = [f for f in result.findings if f.item == "b"]
    assert sorted(f.level for f in b) == ["L3", "L4"]
    assert [f.level for f in b if f.counted] == ["L3"]
    assert [f for f in b if f.level == "L4"][0].follows


def test_the_l4_summary_counts_rows_against_test_cases():
    result = pairing.check(_design([("U", ["a", "b"])], rows_only=("b",)), _spec([("U", ["a"])]))
    row = [c for c in result.checks if c.what == "interface Function rows ↔ test cases"][0]
    assert (row.level, row.left, row.right, row.ok) == ("L4", 2, 1, False)
    assert "− b" in row.detail


def test_every_call_arrow_has_its_cross_unit_step():
    ia = [("U", "a", "Caller", "call")]
    arrows = {"a": ["call calls a", "a calls V.helper", "helper returns to a", "a returns to call"]}
    design = _design([("U", ["a"])], ia, arrows=arrows)
    agree = pairing.check(design, _spec([("U", ["a"])], ia, calls={"a": ["V.helper"]}))
    assert agree.findings == []
    calls = [c for c in agree.checks if c.what == "call arrows ↔ cross-unit calls"][0]
    assert (calls.left, calls.right, calls.ok) == (1, 1, True)


def test_an_arrow_without_a_step_and_a_step_without_an_arrow_are_L5():
    ia = [("U", "a", "Caller", "call")]
    arrows = {"a": ["call calls a", "a calls helper to check the budget", "a calls other"]}
    result = pairing.check(_design([("U", ["a"])], ia, arrows=arrows),
                           _spec([("U", ["a"])], ia, calls={"a": ["V.helper", "W.extra"]}))
    found = sorted((f.level, f.kind, f.left or f.right, f.priority) for f in counted(result))
    # a call only the spec makes was invented by the spec (P1); an arrow it leaves out is
    # a gap in what it tests (P2)
    assert found == [("L5", "extra", "extra", P1), ("L5", "missing", "other", P2)]
    assert all(f.breaks and "cross-unit call" in f.rule for f in counted(result))


def test_a_mock_is_not_a_cross_unit_call():
    ia = [("U", "a", "Caller", "call")]
    design = _design([("U", ["a"])], ia, arrows={"a": ["call calls a"]})
    spec = _spec([("U", ["a"])], ia)
    spec.of_kind("component")[0].of_kind("interaction")[0].fields["expected"] = [
        "Successfully called mock functions retryBudget()"]
    assert pairing.check(design, spec).findings == []


def test_a_unit_heading_printed_differently_is_cosmetic():
    design = _design([("U", ["a"])])
    spec = _spec([("U", ["a"])])
    spec.of_kind("component")[0].of_kind("unit")[0].name = "u"
    found = counted(pairing.check(design, spec))
    assert [(f.level, f.field, f.priority, f.entity) for f in found] == \
        [("L5", "headingText", P4, "unit")]


# --- one way: SWE.3 is the input ------------------------------------------------------

def test_what_only_the_design_has_is_P2_and_what_only_the_spec_has_is_P1():
    design_only = counted(pairing.check(_design([("U", ["a", "b"])]), _spec([("U", ["a"])])))
    spec_only = counted(pairing.check(_design([("U", ["a"])]), _spec([("U", ["a", "b"])])))
    assert [f.priority for f in design_only] == [P2]
    assert [f.priority for f in spec_only] == [P1]


def test_a_gap_in_the_spec_ids_left_by_a_design_function_without_spec_is_explained():
    from doccheck import compare as comparing
    design = _design([("U", ["a", "b", "c"])])
    spec = _spec([("U", ["a", "c"])])
    case_c = spec.of_kind("component")[0].of_kind("unit")[0].of_kind("testcase")[1]
    case_c.fields["testCaseId"] = "TC_IF_LAYER1_G_U_03"          # the design's number for c
    own = comparing.self_checks(spec, swe4)
    gap = [f for f in own if f.field == "tc-id-gap"]
    assert gap and gap[0].priority == P2
    assert pairing.explain_id_gaps(own, design, spec) == 1
    assert gap[0].priority == P3 and gap[0].explained and "b has no spec" in gap[0].rule


def test_a_gap_the_design_does_not_explain_stays():
    from doccheck import compare as comparing
    design = _design([("U", ["a", "b", "c"])])
    spec = _spec([("U", ["a", "b", "c"])])
    spec.of_kind("component")[0].of_kind("unit")[0].of_kind("testcase")[2] \
        .fields["testCaseId"] = "TC_IF_LAYER1_G_U_05"
    own = comparing.self_checks(spec, swe4)
    assert pairing.explain_id_gaps(own, design, spec) == 0


# --- inline public functions: no spec of their own ------------------------------------

def _mock_in(spec, unit_index, case_index, line):
    spec.of_kind("component")[0].of_kind("unit")[unit_index].of_kind("testcase")[case_index] \
        .fields["precondition"] = [line]


def test_an_inline_function_a_caller_in_another_unit_mocks_is_explained():
    design = _design([("U", ["a", "inl"]), ("V", ["caller"])])
    spec = _spec([("U", ["a"]), ("V", ["caller"])])
    _mock_in(spec, 1, 0, "Mock functions: inl()")
    found = [f for f in pairing.check(design, spec).findings if f.item == "inl"]
    assert [(f.level, f.priority, f.explained) for f in found if f.counted] == [("L3", P3, True)]
    assert "mocked by V's spec for caller" in [f for f in found if f.counted][0].rule


def test_an_inline_function_its_own_unit_runs_inline_is_explained():
    design = _design([("U", ["a", "inl"])])
    spec = _spec([("U", ["a"])])
    spec.of_kind("component")[0].of_kind("unit")[0].of_kind("testcase")[0] \
        .fields["testSteps"] = ["Issue function a.", "Call function inl() with x."]
    found = [f for f in counted(pairing.check(design, spec)) if f.item == "inl"]
    assert found and found[0].priority == P3 and "run inside U's spec for a" in found[0].rule


def test_a_missing_spec_with_no_evidence_stays_P2_and_names_its_callers():
    design = _design([("U", ["a", "b"])])
    design.of_kind("component")[0].of_kind("unit")[0].of_kind("interface")[1] \
        .fields["sourceDest"] = ["Access/AccessCompanionUser"]
    found = [f for f in counted(pairing.check(design, _spec([("U", ["a"])]))) if f.item == "b"]
    assert found and found[0].priority == P2
    assert "called from Access/AccessCompanionUser" in found[0].rule
