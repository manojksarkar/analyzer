"""The SWE.4 profile: against the pipeline's own data, and one change at a time.

`test_specs.json` sits next to every generated unit test specification and holds
the steps with their numbers, so it is the same kind of free oracle that
`interface_tables.json` is for SWE.3 -- including the nesting, which is the part
of a SWE.4 document most worth getting right.

Each document is compared against *its own* sibling JSON, never against a fixed
expectation. The generated corpus on disk spans several months of the tool's life
(some of it predates alternating step numbers), and a test that asserted today's
numbering against last quarter's output would be testing the corpus, not the
extractor.
"""
import copy
import glob
import json
import os
import shutil
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.path.join(_ROOT, "tools") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "tools"))

docx_mod = pytest.importorskip("docx", reason="python-docx is needed to read a .docx")

from doccheck import blocks, cells, compare as comparing, rules, swe4     # noqa: E402
from doccheck.model import P1, P2, P3, P4, Entity                       # noqa: E402
from doccheck.model import normalise_key                                 # noqa: E402

pytestmark = pytest.mark.unit


def _pairs():
    """(label, docx, test_specs.json) for every generated SWE.4 group."""
    out, seen = [], set()
    patterns = [
        os.path.join(_ROOT, "workspaces", "*", "versions", "*", "output", "*"),
        os.path.join(_ROOT, "output", "*"),
        os.path.join(_ROOT, "output_review", "all-groups", "*"),
    ]
    for pattern in patterns:
        for d in sorted(glob.glob(pattern)):
            oracle = os.path.join(d, "test_specs.json")
            spec = sorted(glob.glob(os.path.join(d, "software_unit_test_specification_*.docx")))
            if not spec or not os.path.isfile(oracle):
                continue
            label = "%s-%s" % (os.path.basename(os.path.dirname(os.path.dirname(d))),
                               os.path.basename(d))
            if label in seen:
                continue
            seen.add(label)
            out.append((label, spec[0], oracle))
    return out


PAIRS = _pairs()
if not PAIRS:
    pytest.skip("no generated SWE.4 documents on disk", allow_module_level=True)

IDS = [p[0] for p in PAIRS]


def _extracted(path):
    doc = swe4.extract(blocks.read(path))
    out = {}
    for component in doc.of_kind("component"):
        for unit in component.of_kind("unit"):
            for case in unit.of_kind("testcase"):
                out[(normalise_key(unit.name), normalise_key(case.name))] = case
    return out


def _oracle(path):
    data = json.load(open(path, encoding="utf-8"))
    out = {}
    for key, block in data.items():
        if key in ("unitNames", "dynamicSpecs") or not isinstance(block, dict):
            continue
        unit = normalise_key(block.get("name", ""))
        for fn in block.get("functions", []):
            out[(unit, normalise_key(fn.get("name", "")))] = fn
    return out


# --- the extractor against the pipeline -------------------------------------

@pytest.mark.parametrize("label,docx_path,oracle_path", PAIRS, ids=IDS)
def test_every_specified_function_is_read_back_out_of_the_document(label, docx_path, oracle_path):
    got, want = _extracted(docx_path), _oracle(oracle_path)
    problems = []
    for key, fn in sorted(want.items()):
        case = got.get(key)
        if case is None:
            problems.append("%s/%s is specified but has no section" % key)
            continue
        for fieldname, wanted in (("testCaseId", fn.get("testCaseId", "")),
                                  ("generationMethod", fn.get("generationMethod", ""))):
            actual = (case.fields.get(fieldname) or "").strip().strip("`")
            if wanted and actual != wanted:
                problems.append("%s/%s %s: document=%r model=%r"
                                % (key[0], key[1], fieldname, actual, wanted))
    assert not problems, "%s:\n  %s" % (label, "\n  ".join(problems[:20]))


@pytest.mark.parametrize("label,docx_path,oracle_path", PAIRS, ids=IDS)
def test_test_steps_keep_their_wording_and_their_nesting(label, docx_path, oracle_path):
    got, want = _extracted(docx_path), _oracle(oracle_path)
    problems = []
    for key, fn in sorted(want.items()):
        case = got.get(key)
        if case is None:
            continue
        wanted_bodies = [s.get("text", "") for s in fn.get("testSteps", [])]
        wanted_depths = [len(str(s.get("number", "")).split(".")) for s in fn.get("testSteps", [])]
        if (case.fields.get("testSteps") or []) != wanted_bodies:
            problems.append("%s/%s steps: document=%r model=%r"
                            % (key[0], key[1], case.fields.get("testSteps"), wanted_bodies))
        if (case.fields.get("testStepShape") or []) != wanted_depths:
            problems.append("%s/%s nesting: document=%r model=%r"
                            % (key[0], key[1], case.fields.get("testStepShape"), wanted_depths))
    assert not problems, "%s:\n  %s" % (label, "\n  ".join(problems[:20]))


@pytest.mark.parametrize("label,docx_path,oracle_path", PAIRS, ids=IDS)
def test_the_document_specifies_no_function_the_model_does_not(label, docx_path, oracle_path):
    got, want = _extracted(docx_path), _oracle(oracle_path)
    extra = sorted("%s/%s" % k for k in got if k not in want)
    assert not extra, "%s: sections with no model entry: %s" % (label, extra[:10])


@pytest.mark.parametrize("label,docx_path,oracle_path", PAIRS, ids=IDS)
def test_interaction_specs_are_read_as_interactions_not_as_a_unit(label, docx_path, oracle_path):
    """`Dynamic Behaviour` is a section, not a unit, and its entries are one per
    interaction. Reading it as a unit made every interaction look like a function
    whose heading disagreed with its unit."""
    doc = swe4.extract(blocks.read(docx_path))
    assert not [u for c in doc.of_kind("component") for u in c.of_kind("unit")
                if u.name.casefold().startswith("dynamic behaviour")]
    oracle = json.load(open(oracle_path, encoding="utf-8"))
    wanted = len(oracle.get("dynamicSpecs") or [])
    got = sum(len(c.of_kind("interaction")) for c in doc.of_kind("component"))
    assert got == wanted, "%s: %d interaction specs read, %d in the model" % (label, got, wanted)


@pytest.mark.parametrize("label,docx_path,oracle_path", PAIRS, ids=IDS)
def test_a_generated_document_passes_its_own_checks(label, docx_path, oracle_path):
    doc = swe4.extract(blocks.read(docx_path))
    findings = comparing.self_checks(doc, swe4)
    # fresh/v1 predates 2026-09-21b, when a method's spec heading gained its class:
    # its Cross document has two specs headed `Dispatch-apply`. That is the defect the
    # duplicate-heading check exists for, so the check firing there is right.
    findings = [f for f in findings
                if not (f.field == "duplicate-heading" and "Dispatch-apply" in f.summary)]
    assert not findings, "%s: %s" % (label, [f.summary for f in findings][:10])


@pytest.mark.parametrize("label,docx_path,oracle_path", PAIRS, ids=IDS)
def test_a_document_compares_clean_with_itself(label, docx_path, oracle_path):
    doc = swe4.extract(blocks.read(docx_path))
    assert comparing.compare(doc, copy.deepcopy(doc), swe4).findings == []


# --- step numbering, both vintages ------------------------------------------

@pytest.mark.parametrize("label,depths", [
    ("1)", [1]),
    ("2.a)", [2]),
    ("3.1)", [2]),
    ("3.b.1.c)", [4]),
    ("4.a.3)", [3]),
])
def test_both_step_numbering_styles_are_read(label, depths):
    """Alternating (`2.a`) is today's; all-numeric (`3.1`) is in older output."""
    parsed = cells.numbered(["%s something happens." % label])
    assert [len(p["path"]) for p in parsed] == depths
    assert parsed[0]["body"] == "something happens."


def test_an_unnumbered_line_keeps_its_text_and_claims_no_depth():
    parsed = cells.numbered(["No return value; no global side effects"])
    assert parsed[0]["path"] == () and parsed[0]["body"].startswith("No return value")
    assert cells.shape(["No return value; no global side effects"]) == []


# --- the ladder, SWE.4 shaped -----------------------------------------------

def case(name, index=0, unit_name="U", **fields):
    base = {
        "testCaseId": "TC_IF_LAYER1_G_%s_%02d" % (unit_name.upper(), index + 1),
        "evalEquipment": "Emulator",
        "platform": "VectorCAST",
        "precondition": ["Globals: int s_count"],
        "input": ["int s_count[0-255]"],
        "testSteps": ["Issue function %s with input VOID." % name, "Increment the counter."],
        "testStepShape": [1, 1],
        "expected": ["Successfully updated int s_count[0-255] in step 2"],
        "priority": "Medium",
        "risk": "-",
        "testMethod": "-",
        "aliasTestId": "-",
        "linkedWorkItems": "-",
        "testEnvironment": "Emulator",
        "generationMethod": "Analysis of Requirements",
        "hasTableA": True,
        "hasTableB": True,
        "qualifiedName": "%s-%s" % (unit_name, name),
    }
    base.update(fields)
    return Entity(kind="testcase", name=name, index=index, fields=base)


def spec(units):
    doc = Entity(kind="document", name="SWE.4")
    doc.children.append(Entity(kind="section", name="Introduction", index=0))
    component = Entity(kind="component", name="Diag", index=0)
    doc.children.append(component)
    for ui, (unit_name, case_names) in enumerate(units):
        unit = Entity(kind="unit", name=unit_name, index=ui,
                      fields={"testCaseCount": len(case_names)})
        for ci, cname in enumerate(case_names):
            unit.children.append(case(cname, ci, unit_name))
        component.children.append(unit)
    return doc


def sample4():
    return spec([("ClassStatics", ["statBump", "statRead"]), ("Helper", ["helpOne"])])


def run4(left, right):
    result = comparing.compare(left, right, swe4)
    rules.annotate(result, left, right)
    return result


def test_a_specification_compared_with_itself_says_nothing():
    doc = sample4()
    assert run4(doc, copy.deepcopy(doc)).findings == []


def test_the_sample_passes_the_swe4_self_checks():
    assert comparing.self_checks(sample4(), swe4) == []


def test_a_dropped_test_case_is_found():
    right = sample4()
    unit = right.of_kind("component")[0].of_kind("unit")[0]
    unit.children = unit.children[:1]
    unit.fields["testCaseCount"] = 1
    result = run4(sample4(), right)
    missing = [f for f in result.findings if f.kind == "missing"]
    assert len(missing) == 1 and missing[0].path.endswith("statRead")


def test_reworded_test_steps_are_a_review_item():
    """Cell text is P2: another author words every step differently, and a worded step is
    a thing to judge. P1 is kept for structure -- a missing table, a missing unit."""
    right = sample4()
    c = right.of_kind("component")[0].of_kind("unit")[0].of_kind("testcase")[0]
    c.fields["testSteps"] = list(c.fields["testSteps"])
    c.fields["testSteps"][1] = "Decrement the counter."
    differs = [f for f in run4(sample4(), right).findings if f.field == "testSteps"]
    assert len(differs) == 1 and differs[0].priority == P2 and differs[0].level == "L5"


def test_flattening_the_nesting_is_caught_even_when_every_sentence_survives():
    """The wording is identical; only the control flow the steps describe changed."""
    right = sample4()
    c = right.of_kind("component")[0].of_kind("unit")[0].of_kind("testcase")[0]
    c.fields["testStepShape"] = [1, 2]
    differs = [f for f in run4(sample4(), right).findings if f.field == "testStepShape"]
    assert len(differs) == 1 and differs[0].priority == P2
    assert not [f for f in run4(sample4(), right).findings if f.field == "testSteps"]


def test_reordered_steps_are_a_difference_because_order_is_the_point():
    right = sample4()
    c = right.of_kind("component")[0].of_kind("unit")[0].of_kind("testcase")[0]
    c.fields["testSteps"] = list(reversed(c.fields["testSteps"]))
    assert [f.field for f in run4(sample4(), right).findings if f.kind == "differs"] == ["testSteps"]


def test_the_test_case_id_is_ours_and_is_not_compared():
    right = sample4()
    for unit in right.of_kind("component")[0].of_kind("unit"):
        for c in unit.of_kind("testcase"):
            c.fields["testCaseId"] = "CLIENT-TC-%s" % c.name
    assert not [f for f in run4(sample4(), right).findings if f.field == "testCaseId"]


def test_a_missing_table_is_caught_without_a_second_document():
    doc = sample4()
    doc.of_kind("component")[0].of_kind("unit")[0].of_kind("testcase")[0].fields["hasTableB"] = False
    findings = comparing.self_checks(doc, swe4)
    assert any("Table B" in f.summary for f in findings)


def test_a_drifting_fixed_value_is_caught_without_a_second_document():
    doc = sample4()
    doc.of_kind("component")[0].of_kind("unit")[0].of_kind("testcase")[0].fields["generationMethod"] = "Boundary Value"
    findings = comparing.self_checks(doc, swe4)
    assert any("generationMethod" in f.summary and "Analysis of Requirements" in f.summary
               for f in findings)


def test_steps_that_skip_a_nesting_level_are_caught_without_a_second_document():
    doc = sample4()
    doc.of_kind("component")[0].of_kind("unit")[0].of_kind("testcase")[0].fields["testStepShape"] = [1, 3]
    findings = comparing.self_checks(doc, swe4)
    assert any("nesting jumps" in f.summary for f in findings)


def test_steps_with_no_expected_results_are_caught_without_a_second_document():
    doc = sample4()
    doc.of_kind("component")[0].of_kind("unit")[0].of_kind("testcase")[0].fields["expected"] = []
    findings = comparing.self_checks(doc, swe4)
    assert any("no expected results" in f.summary for f in findings)


def test_a_missing_unit_does_not_drag_its_cases_into_the_report():
    right = sample4()
    component = right.of_kind("component")[0]
    component.children = component.children[1:]
    result = run4(sample4(), right)
    below = [f for f in result.findings if "ClassStatics /" in f.path]
    assert below == []
    assert len([f for f in result.findings if f.kind == "missing"]) == 1


# --- end to end, on a real document -----------------------------------------

@pytest.fixture
def mutable4(tmp_path):
    source = max(PAIRS, key=lambda p: os.path.getsize(p[1]))[1]
    target = tmp_path / "compared.docx"
    shutil.copyfile(source, target)

    class Harness:
        path = str(target)
        reference = source

        def compare(self):
            left = swe4.extract(blocks.read(self.reference))
            right = swe4.extract(blocks.read(self.path))
            result = comparing.compare(left, right, swe4)
            rules.annotate(result, left, right)
            return result

    return Harness()


def test_an_untouched_copy_of_a_real_specification_compares_clean(mutable4):
    assert mutable4.compare().findings == []


def test_changing_one_step_in_a_real_specification_reaches_the_report(mutable4):
    document = docx_mod.Document(mutable4.path)
    changed = None
    for table in document.tables:
        header = [c.text.strip().casefold() for c in table.rows[0].cells]
        col = next((i for i, h in enumerate(header) if h.startswith("test steps")), None)
        if col is None or len(table.rows) < 2:
            continue
        cell = table.rows[1].cells[col]
        para = cell.paragraphs[0]
        if not para.runs:
            continue
        para.runs[0].text = "1) A step that was never in this specification."
        for run in para.runs[1:]:
            run.text = ""
        changed = True
        break
    if not changed:
        pytest.skip("no Test Steps cell to edit")
    document.save(mutable4.path)

    result = mutable4.compare()
    differs = [f for f in result.findings if f.field == "testSteps"]
    assert differs and differs[0].priority == P2
