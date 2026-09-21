"""Two methods of different classes in one unit must not share a heading.

`SWE3_WIKI` 'Names' keeps the class in front of a method precisely so that
`AddOperation::apply` and `MultiplyOperation::apply` stay apart. SWE.4 printed the
bare `name`, so both took the heading `Dispatch-apply` and both opened with
"Issue function apply with inputs a, b." -- two specifications a tester cannot
tell apart, and a design/specification pair that cannot be read side by side.

The `Sample` fixture has no class-qualified method, so nothing in the e2e suite
pins this. These build the spec JSON directly.
"""
import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for path in (os.path.join(_ROOT, "engine"), os.path.join(_ROOT, "tools")):
    if path not in sys.path:
        sys.path.insert(0, path)

pytest.importorskip("docx", reason="python-docx is needed to write a .docx")

pytestmark = pytest.mark.unit


def _spec(name, qualified, line, test_case_id):
    return {
        "functionId": "Layer1.Cross|Dispatch|%s|int,int" % name,
        "interfaceId": test_case_id[3:],
        "testCaseId": test_case_id,
        "name": name,
        "qualifiedName": qualified,
        "unitKey": "Layer1.Cross|Dispatch",
        "unitName": "Dispatch",
        "location": {"file": "Layer1/Cross/Dispatch.cpp", "line": line},
        "returnType": "int",
        "generationMethod": "Analysis of Requirements",
        "precondition": {"mockFunctions": [], "mocks": [], "globals": [],
                         "parameters": [{"name": "a", "type": "int"},
                                        {"name": "b", "type": "int"}]},
        "input": {"entries": [{"text": "int a[0-255]"}, {"text": "int b[0-255]"}]},
        "expected": {"mockFunctions": [], "returns": [], "outParameters": [], "globals": []},
        "testSteps": [{"number": "1", "text": "Issue function %s with inputs a, b." % qualified,
                       "nodeId": "N1", "type": "START"}],
    }


@pytest.fixture
def two_same_named_methods(tmp_path):
    """A unit with `AddOperation::apply` and `MultiplyOperation::apply`."""
    payload = {
        "unitNames": {"Layer1.Cross|Dispatch": "Dispatch"},
        "Layer1.Cross|Dispatch": {
            "name": "Dispatch",
            "functions": [
                _spec("apply", "AddOperation::apply", 10, "TC_IF_LAYER1_X_DISPATCH_01"),
                _spec("apply", "MultiplyOperation::apply", 20, "TC_IF_LAYER1_X_DISPATCH_02"),
                _spec("divide", "divide", 30, "TC_IF_LAYER1_X_DISPATCH_03"),
            ],
        },
    }
    json_path = tmp_path / "test_specs.json"
    json_path.write_text(json.dumps(payload), encoding="utf-8")
    docx_path = tmp_path / "spec.docx"

    from swe4_exporter import export_test_specs
    ok, written = export_test_specs(json_path=str(json_path), docx_path=str(docx_path))
    assert ok, "the exporter refused to write the document"
    return str(docx_path)


def _headings(path, level=4):
    from doccheck import blocks
    return [b.text for b in blocks.read(path) if b.kind == "heading" and b.level == level]


def test_the_two_methods_get_two_different_headings(two_same_named_methods):
    headings = _headings(two_same_named_methods)
    assert len(headings) == len(set(headings)), "two specs share a heading: %s" % headings


def test_each_heading_carries_the_class_in_front(two_same_named_methods):
    headings = _headings(two_same_named_methods)
    assert "Dispatch-AddOperation::apply" in headings
    assert "Dispatch-MultiplyOperation::apply" in headings


def test_a_plain_function_keeps_its_plain_heading(two_same_named_methods):
    """`qualifiedName` equals `name` for a free function, so nothing moves."""
    assert "Dispatch-divide" in _headings(two_same_named_methods)


def test_the_specifications_can_still_be_told_apart_by_the_pairing_check(two_same_named_methods):
    """The check that found this in the first place must now come back clean."""
    from doccheck import blocks, swe4
    doc = swe4.extract(blocks.read(two_same_named_methods))
    cases = [c for comp in doc.of_kind("component")
             for u in comp.of_kind("unit") for c in u.of_kind("testcase")]
    assert sorted(c.name for c in cases) == [
        "AddOperation::apply", "MultiplyOperation::apply", "divide"]


# --- the entry step, which names the function a tester must issue ------------

def test_the_entry_step_names_the_qualified_method():
    from views.test_steps import _entry_text
    spec = {"name": "apply", "qualifiedName": "AddOperation::apply",
            "precondition": {"parameters": [{"name": "a"}, {"name": "b"}]}}
    assert _entry_text(spec) == "Issue function AddOperation::apply with inputs a, b."


def test_the_entry_step_is_unchanged_for_a_plain_function():
    from views.test_steps import _entry_text
    spec = {"name": "divide", "qualifiedName": "divide",
            "precondition": {"parameters": [{"name": "a"}]}}
    assert _entry_text(spec) == "Issue function divide with inputs a."


def test_the_entry_step_falls_back_when_no_qualified_name_was_recorded():
    from views.test_steps import _entry_text
    assert _entry_text({"name": "reset"}) == "Issue function reset with input VOID."
    assert _entry_text({}) == "Issue function the function with input VOID."
