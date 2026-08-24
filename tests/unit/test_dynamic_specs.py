"""Dynamic Behaviour test specs (SWE.4): boundary, selection, splice.

Rules under test come from docs/spec/SWE4_WIKI.md, "Dynamic Behaviour test specs".
The point of every case below is the one thing that separates a dynamic spec from
a function spec: the boundary is the COMPONENT, not the unit.
"""
import os
import sys

import pytest

ENGINE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "engine")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from views.dynamic_specs import (  # noqa: E402
    _component_of, _entry_point, _walk_boundary, build,
)
from views.test_steps import _splice_map, build_steps  # noqa: E402


def _fn(name, *, visibility="default", calls=(), called_by=(), params=(), ret="int",
        iid=""):
    # `calledByIds` matters as much as `callsIds` here: the behaviour selector
    # finds the external caller by walking BACKWARD, so a fixture without it
    # selects nothing.
    return {"qualifiedName": name, "visibility": visibility, "returnType": ret,
            "location": {"file": name + ".cpp", "line": 1},
            "parameters": list(params), "callsIds": list(calls),
            "calledByIds": list(called_by), "interfaceId": iid}


# Two units of one component (Sig|Drv -> Sig|Proc), entered from another
# component (Ext|Caller), with one callee outside the component (Oth|Far).
FUNCTIONS = {
    "Ext|Caller|entry": _fn("entry", visibility="public", calls=["Sig|Drv|drive"]),
    "Sig|Drv|drive": _fn("drive", visibility="public", iid="IF_DRV_01",
                         params=[{"name": "raw", "type": "int"}],
                         calls=["Sig|Proc|refine", "Oth|Far|remote"],
                         called_by=["Ext|Caller|entry"]),
    "Sig|Proc|refine": _fn("refine", visibility="public", calls=["Oth|Far|remote"],
                           called_by=["Sig|Drv|drive"]),
    "Oth|Far|remote": _fn("remote", visibility="public",
                          called_by=["Sig|Drv|drive", "Sig|Proc|refine"]),
}
UNITS = {
    "Ext|Caller": {"name": "Caller", "functionIds": ["Ext|Caller|entry"],
                   "fileName": "Caller.cpp"},
    "Sig|Drv": {"name": "Drv", "functionIds": ["Sig|Drv|drive"], "fileName": "Drv.cpp"},
    "Sig|Proc": {"name": "Proc", "functionIds": ["Sig|Proc|refine"],
                 "fileName": "Proc.cpp"},
    "Oth|Far": {"name": "Far", "functionIds": ["Oth|Far|remote"], "fileName": "Far.cpp"},
}
COMPONENTS = {
    "Ext": {"units": ["Ext|Caller"]}, "Sig": {"units": ["Sig|Drv", "Sig|Proc"]},
    "Oth": {"units": ["Oth|Far"]},
}
UNIT_OF = {fid: uk for uk, u in UNITS.items() for fid in u["functionIds"]}


class TestBoundary:
    def test_same_component_other_unit_executes(self):
        """The callee a function spec would stub is exactly the one that must run."""
        executing, mocked = _walk_boundary(
            FUNCTIONS["Sig|Drv|drive"], FUNCTIONS, UNIT_OF, "Sig")
        assert "Sig|Proc|refine" in executing
        assert "Sig|Proc|refine" not in mocked

    def test_other_component_is_mocked(self):
        executing, mocked = _walk_boundary(
            FUNCTIONS["Sig|Drv|drive"], FUNCTIONS, UNIT_OF, "Sig")
        assert "Oth|Far|remote" in mocked
        assert "Oth|Far|remote" not in executing

    def test_walks_through_an_executing_callee(self):
        """`refine` runs, so the call IT makes out of the component is this spec's
        problem too -- the same transitive rule the unit-scoped walk applies."""
        drive = dict(FUNCTIONS["Sig|Drv|drive"], callsIds=["Sig|Proc|refine"])
        _, mocked = _walk_boundary(drive, FUNCTIONS, UNIT_OF, "Sig")
        assert "Oth|Far|remote" in mocked

    def test_unresolvable_callee_counts_as_outside(self):
        """Its file was never parsed, so it cannot be this component's code."""
        drive = dict(FUNCTIONS["Sig|Drv|drive"], callsIds=["Ghost|Ghost|ghost"])
        executing, mocked = _walk_boundary(drive, FUNCTIONS, UNIT_OF, "Sig")
        assert mocked == {"Ghost|Ghost|ghost"}
        assert not executing

    def test_component_of(self):
        assert _component_of("Sig|Drv") == "Sig"
        assert _component_of("bare") == ""


class TestBuild:
    @pytest.fixture
    def specs(self):
        return build(UNITS, FUNCTIONS, {}, COMPONENTS, {}, allowed_components={"sig"})

    def test_one_spec_for_the_qualifying_function(self, specs):
        assert list(specs) == ["Sig"]
        assert [s["name"] for s in specs["Sig"]] == ["drive"]

    def test_entry_point_is_the_external_caller(self, specs):
        assert specs["Sig"][0]["entryPoint"] == "Caller - entry"

    def test_in_component_callee_is_absent_from_mocks(self, specs):
        mocks = specs["Sig"][0]["precondition"]["mockFunctions"]
        assert "remote()" in mocks
        assert "refine()" not in mocks

    def test_in_component_callee_return_is_absent_from_input(self, specs):
        """It is not stubbed, so there is no return value to set."""
        texts = " ".join(e["text"] for e in specs["Sig"][0]["input"]["entries"])
        assert "refine()" not in texts

    def test_cross_unit_call_is_asserted(self, specs):
        calls = specs["Sig"][0]["expected"]["crossUnitCalls"]
        assert [c["text"] for c in calls] == ["Proc.refine"]

    def test_test_case_id_differs_from_the_function_spec(self, specs):
        """Both describe `drive`; two rows in one document cannot share an ID."""
        assert specs["Sig"][0]["testCaseId"] == "TC_IF_DRV_01_DYN"

    def test_private_function_gets_no_spec(self):
        functions = dict(FUNCTIONS)
        functions["Sig|Drv|drive"] = dict(functions["Sig|Drv|drive"], visibility="private")
        assert build(UNITS, functions, {}, COMPONENTS, {},
                     allowed_components={"sig"}) == {}

    def test_single_unit_chain_gets_no_spec(self):
        """No second unit means no interaction to specify."""
        functions = dict(FUNCTIONS)
        functions["Sig|Drv|drive"] = dict(functions["Sig|Drv|drive"],
                                          callsIds=["Oth|Far|remote"])
        assert build(UNITS, functions, {}, COMPONENTS, {},
                     allowed_components={"sig"}) == {}

    def test_no_external_caller_gets_no_spec(self):
        functions = dict(FUNCTIONS)
        functions["Sig|Drv|drive"] = dict(functions["Sig|Drv|drive"], calledByIds=[])
        assert build(UNITS, functions, {}, COMPONENTS, {},
                     allowed_components={"sig"}) == {}

    def test_same_component_caller_is_not_external(self):
        """External means another COMPONENT; a sibling unit calling in is not an
        entry into the component and specifies no interaction with the outside."""
        functions = dict(FUNCTIONS)
        functions["Sig|Drv|drive"] = dict(functions["Sig|Drv|drive"],
                                          calledByIds=["Sig|Proc|refine"])
        assert build(UNITS, functions, {}, COMPONENTS, {},
                     allowed_components={"sig"}) == {}


class TestSplice:
    """The CFG pass: a cross-unit callee's own flow is walked in, not stubbed."""

    CFG_DRIVE = {
        "entry": "N1",
        "exits": ["N9"],
        "nodes": [{"id": "N1", "type": "START", "label": "start"},
                  {"id": "N2", "type": "RETURN", "label": "Return refine(raw)",
                   "rawCode": "return refine(raw);"},
                  {"id": "N9", "type": "END", "label": "End"}],
        "edges": [{"source": "N1", "target": "N2"}, {"source": "N2", "target": "N9"}],
    }
    CFG_REFINE = {
        "entry": "M1",
        "exits": ["M9"],
        "nodes": [{"id": "M1", "type": "START", "label": "start"},
                  {"id": "M2", "type": "DECISION", "label": "Check: v < 0",
                   "rawCode": "if (v < 0)"},
                  {"id": "M3", "type": "RETURN", "label": "Return 0", "rawCode": "return 0;"},
                  {"id": "M4", "type": "RETURN", "label": "Return v", "rawCode": "return v;"},
                  {"id": "M9", "type": "END", "label": "End"}],
        "edges": [{"source": "M1", "target": "M2"},
                  {"source": "M2", "target": "M3", "label": "Yes"},
                  {"source": "M2", "target": "M4", "label": "No"},
                  {"source": "M3", "target": "M9"}, {"source": "M4", "target": "M9"}],
    }

    @pytest.fixture
    def spec(self):
        return build(UNITS, FUNCTIONS, {}, COMPONENTS, {},
                     allowed_components={"sig"})["Sig"][0]

    @pytest.fixture
    def steps(self, spec):
        cfgs = {"Sig|Drv|drive": self.CFG_DRIVE, "Sig|Proc|refine": self.CFG_REFINE}
        splice = _splice_map(spec, cfgs, FUNCTIONS, UNIT_OF,
                             {uk: u["name"] for uk, u in UNITS.items()})
        steps, returns, _ = build_steps(self.CFG_DRIVE, spec,
                                        spec["precondition"]["mockFunctions"],
                                        splice, spec["unitName"])
        return steps, returns

    def test_call_step_names_both_units(self, steps):
        text = " ".join(s["text"] for s in steps[0])
        assert "Drv calls Proc.refine" in text

    def test_callee_branches_are_nested_under_the_call(self, steps):
        numbers = [s["number"] for s in steps[0]]
        assert "2" in numbers            # the calling step
        assert "2.1" in numbers          # the callee's decision, spliced in

    def test_callee_returns_become_assertions_of_this_spec(self, steps):
        """A function spec stubs `refine`, so these branches are asserted nowhere."""
        returned = {r["expression"] for r in steps[1]}
        assert {"0", "v"} <= returned

    def test_start_node_of_the_callee_is_not_re_issued(self, steps):
        issued = [s for s in steps[0] if s["text"].startswith("Issue function")]
        assert len(issued) == 1

    def test_ambiguous_short_name_is_not_spliced(self, spec):
        """Two executing callees sharing a short name would splice the WRONG body,
        so neither is descended into."""
        functions = dict(FUNCTIONS)
        functions["Sig|Other|refine"] = _fn("refine", visibility="public")
        units = dict(UNITS)
        units["Sig|Other"] = {"name": "Other", "functionIds": ["Sig|Other|refine"],
                              "fileName": "Other.cpp"}
        unit_of = {fid: uk for uk, u in units.items() for fid in u["functionIds"]}
        spec = dict(spec, executingFunctionIds=["Sig|Proc|refine", "Sig|Other|refine"])
        splice = _splice_map(spec, {}, functions, unit_of,
                             {uk: u["name"] for uk, u in units.items()})
        assert "refine" not in splice

    def test_function_spec_path_is_untouched(self, spec):
        """No `splice` argument -> byte-identical to the pre-existing behaviour."""
        steps, _, _ = build_steps(self.CFG_DRIVE, spec, ["refine()"])
        assert "calls" not in " ".join(s["text"] for s in steps)
        assert any("Expect mock function refine" in s["text"] for s in steps)


class TestEntryPoint:
    def test_unit_and_short_name(self):
        assert _entry_point("Cross|Hub|hubCompute|int,int") == "Hub - hubCompute"

    def test_qualified_method_uses_short_name(self):
        assert _entry_point("C|U|Klass::method|int") == "U - method"

    def test_malformed_key_passes_through(self):
        assert _entry_point("bare") == "bare"
