"""Holding a SWE.3 design against its SWE.4 specification.

The pairing rules are stated in the two wikis, not invented here: every design
function gets a spec bar the inline ones, a dynamic-behaviour spec exists exactly
where SWE.3 draws a diagram, and a Test Case ID is `TC_<interfaceId>`.

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
from doccheck.model import HIGH, MEDIUM, Entity                 # noqa: E402

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

@pytest.mark.skipif(not GROUPS, reason="no group has both documents on disk")
@pytest.mark.parametrize("label,design_p,spec_p", GROUPS, ids=[g[0] for g in GROUPS] or None)
def test_every_finding_names_the_rule_it_comes_from(label, design_p, spec_p):
    """The tool's promise: a difference is never reported without its reason."""
    findings = pairing.check(swe3.extract(blocks.read(design_p)),
                             swe4.extract(blocks.read(spec_p)))
    unexplained = [f.summary for f in findings if not f.rule]
    assert not unexplained, "%s: %s" % (label, unexplained)


@pytest.mark.skipif(not GROUPS, reason="no group has both documents on disk")
@pytest.mark.parametrize("label,design_p,spec_p", GROUPS, ids=[g[0] for g in GROUPS] or None)
def test_the_test_case_id_is_always_the_interface_id_with_TC_in_front(label, design_p, spec_p):
    """Derived mechanically on both sides, so this must never fire on our output."""
    findings = pairing.check(swe3.extract(blocks.read(design_p)),
                             swe4.extract(blocks.read(spec_p)))
    drift = [f.summary for f in findings if f.field == "testCaseId"]
    assert not drift, "%s: %s" % (label, drift)


@pytest.mark.skipif(not GROUPS, reason="no group has both documents on disk")
@pytest.mark.parametrize("label,design_p,spec_p", GROUPS, ids=[g[0] for g in GROUPS] or None)
def test_a_function_is_never_reported_as_both_missing_and_extra(label, design_p, spec_p):
    """One function under two names is one finding, not a delete plus an add."""
    findings = pairing.check(swe3.extract(blocks.read(design_p)),
                             swe4.extract(blocks.read(spec_p)))
    missing = {f.path.rsplit(" / ", 1)[-1].split("::")[-1].casefold()
               for f in findings if f.kind == "missing" and f.field == "spec"}
    extra = {f.path.rsplit(" / ", 1)[-1].split("::")[-1].casefold()
             for f in findings if f.kind == "extra" and f.field == "spec"}
    assert not (missing & extra), "%s: reported twice: %s" % (label, sorted(missing & extra))


# --- built by hand, one rule at a time --------------------------------------

def _design(units, interactions=()):
    doc = Entity(kind="document", name="SWE.3")
    component = Entity(kind="component", name="Diag", index=0,
                       fields={"unitTableUnits": [u for u, _ in units]})
    doc.children.append(component)
    for ui, (unit_name, functions) in enumerate(units):
        unit = Entity(kind="unit", name=unit_name, index=ui,
                      fields={"hasInterfaceTable": True})
        stem = "".join(c for c in unit_name if c.isalnum()).upper()
        for fi, fname in enumerate(functions):
            unit.children.append(Entity(
                kind="interface", name=fname, index=fi,
                fields={"interfaceId": "IF_LAYER1_G_%s_%02d" % (stem, fi + 1),
                        "interfaceType": "Function"}))
        component.children.append(unit)
    for ii, (u, f, cu, cf) in enumerate(interactions):
        component.children.append(Entity(
            kind="interaction", name="%s - %s (%s - %s)" % (u, f, cu, cf), index=ii,
            fields={"unit": u, "function": f, "callerUnit": cu, "callerFunction": cf}))
    return doc


def _spec(units, interactions=()):
    doc = Entity(kind="document", name="SWE.4")
    component = Entity(kind="component", name="Diag", index=0)
    doc.children.append(component)
    for ui, (unit_name, functions) in enumerate(units):
        unit = Entity(kind="unit", name=unit_name, index=ui)
        stem = "".join(c for c in unit_name if c.isalnum()).upper()
        for fi, fname in enumerate(functions):
            unit.children.append(Entity(
                kind="testcase", name=fname, index=fi,
                fields={"testCaseId": "TC_IF_LAYER1_G_%s_%02d" % (stem, fi + 1)}))
        component.children.append(unit)
    for ii, (u, f, cu, cf) in enumerate(interactions):
        component.children.append(Entity(
            kind="interaction", name="%s - %s (%s - %s)" % (u, f, cu, cf), index=ii,
            fields={"unit": u, "function": f, "callerUnit": cu, "callerFunction": cf,
                    "testCaseId": "TC_IF_LAYER1_G_U_01_DYN"}))
    return doc


def test_two_documents_that_agree_produce_nothing():
    units = [("ClassStatics", ["statBump", "statRead"])]
    assert pairing.check(_design(units), _spec(units)) == []


def test_a_design_function_with_no_spec_is_reported_with_the_inline_rule():
    findings = pairing.check(_design([("U", ["a", "b"])]), _spec([("U", ["a"])]))
    assert len(findings) == 1
    assert findings[0].kind == "missing" and findings[0].path.endswith("b")
    assert "inline public function" in findings[0].rule


def test_a_spec_for_a_function_the_design_does_not_publish_is_high_severity():
    findings = pairing.check(_design([("U", ["a"])]), _spec([("U", ["a", "ghost"])]))
    assert len(findings) == 1
    assert findings[0].kind == "extra" and findings[0].severity == HIGH


def test_the_same_function_under_two_names_is_one_finding_not_two():
    findings = pairing.check(_design([("U", ["Proc::normalize"])]),
                             _spec([("U", ["normalize"])]))
    assert len(findings) == 1
    assert findings[0].kind == "renamed"
    assert findings[0].left == "Proc::normalize" and findings[0].right == "normalize"
    assert "tells two same-named methods apart" in findings[0].rule


def test_a_diagram_with_no_interaction_spec_is_high_severity():
    findings = pairing.check(
        _design([("U", ["a"])], interactions=[("U", "a", "Caller", "call")]),
        _spec([("U", ["a"])]))
    assert len(findings) == 1
    assert findings[0].kind == "missing" and findings[0].field == "interaction"
    assert findings[0].severity == HIGH and findings[0].level == "L4"


def test_an_interaction_spec_with_no_diagram_is_high_severity():
    findings = pairing.check(
        _design([("U", ["a"])]),
        _spec([("U", ["a"])], interactions=[("U", "a", "Caller", "call")]))
    assert len(findings) == 1
    assert findings[0].kind == "extra" and findings[0].field == "interaction"
    assert findings[0].severity == HIGH
    assert "swe4_dynamic_diff" in findings[0].rule


def test_matching_interactions_produce_nothing():
    interactions = [("U", "a", "Caller", "call")]
    findings = pairing.check(_design([("U", ["a"])], interactions),
                             _spec([("U", ["a"])], interactions))
    assert findings == []


def test_a_test_case_id_that_is_not_the_interface_id_is_reported():
    design = _design([("U", ["a"])])
    spec = _spec([("U", ["a"])])
    spec.of_kind("component")[0].of_kind("unit")[0].of_kind("testcase")[0] \
        .fields["testCaseId"] = "TC_SOMETHING_ELSE"
    findings = pairing.check(design, spec)
    assert len(findings) == 1 and findings[0].field == "testCaseId"


def test_the_summary_counts_both_sides():
    line = pairing.summary(_design([("U", ["a", "b"])]), _spec([("U", ["a"])]), [])
    assert "publishes 2 function(s)" in line and "specifies 1" in line
