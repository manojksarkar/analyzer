"""Unit tests for src/views/unit_diagrams.py — pure functions only."""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

import importlib.util, types

# Stub the views package so relative imports in the module under test resolve
_views_pkg = types.ModuleType("views")
_views_pkg.__path__ = [os.path.join(PROJECT_ROOT, "src", "views")]
_views_pkg.__package__ = "views"
_registry_mod = types.ModuleType("views.registry")
_registry_mod.register = lambda name: (lambda fn: fn)
_views_pkg.registry = _registry_mod
sys.modules.setdefault("views", _views_pkg)
sys.modules.setdefault("views.registry", _registry_mod)

_spec = importlib.util.spec_from_file_location(
    "views.unit_diagrams",
    os.path.join(PROJECT_ROOT, "src", "views", "unit_diagrams.py"),
    submodule_search_locations=[],
)
_mod = importlib.util.module_from_spec(_spec)
_mod.__package__ = "views"
_spec.loader.exec_module(_mod)

_unit_part_id = _mod._unit_part_id
_escape_label = _mod._escape_label
_fid_to_unit = _mod._fid_to_unit
_build_unit_diagram = _mod._build_unit_diagram


# ---------------------------------------------------------------------------
# _unit_part_id
# ---------------------------------------------------------------------------

class TestUnitPartId:
    def test_pipe_replaced_by_underscore(self):
        assert _unit_part_id("Mod|core") == "Mod_core"

    def test_space_replaced_by_underscore(self):
        assert _unit_part_id("My Module") == "My_Module"

    def test_empty_string_returns_u(self):
        assert _unit_part_id("") == "u"

    def test_none_returns_u(self):
        assert _unit_part_id(None) == "u"

    def test_no_special_chars_unchanged(self):
        assert _unit_part_id("ModCore") == "ModCore"


# ---------------------------------------------------------------------------
# _escape_label
# ---------------------------------------------------------------------------

class TestEscapeLabel:
    def test_double_quotes_replaced_by_single(self):
        assert _escape_label('say "hello"') == "say 'hello'"

    def test_newline_replaced_by_space(self):
        assert _escape_label("line1\nline2") == "line1 line2"

    def test_pipe_replaced_by_broken_bar(self):
        result = _escape_label("a|b")
        assert "|" not in result
        assert "\u00a6" in result

    def test_empty_string(self):
        assert _escape_label("") == ""

    def test_none(self):
        assert _escape_label(None) == ""

    def test_plain_text_unchanged(self):
        assert _escape_label("IFC_001") == "IFC_001"


# ---------------------------------------------------------------------------
# _fid_to_unit (unit_diagrams version: maps to first unit only)
# ---------------------------------------------------------------------------

class TestFidToUnitDiagrams:
    def test_maps_fid_to_first_unit(self):
        units = {"Mod|core": {"functionIds": ["f1"]}}
        result = _fid_to_unit(units)
        assert result["f1"] == "Mod|core"

    def test_fid_first_unit_wins(self):
        # dict ordering: Python 3.7+ preserves insertion order
        units = {
            "Mod|a": {"functionIds": ["f1"]},
            "Mod|b": {"functionIds": ["f1"]},
        }
        result = _fid_to_unit(units)
        assert result["f1"] == "Mod|a"

    def test_empty_units(self):
        assert _fid_to_unit({}) == {}


# ---------------------------------------------------------------------------
# _build_unit_diagram
# ---------------------------------------------------------------------------

def _make_minimal_context(unit_key="Mod|core", filename="core.cpp"):
    unit_info = {"fileName": filename, "functionIds": [], "globalVariableIds": []}
    units_data = {unit_key: unit_info}
    functions_data = {}
    fid_to_unit = {}
    unit_names = {unit_key: unit_key.split("|")[-1]}
    return unit_info, units_data, functions_data, fid_to_unit, unit_names


class TestBuildUnitDiagram:
    def test_non_cpp_unit_returns_none(self):
        unit_info, units_data, functions_data, fid_to_unit, unit_names = _make_minimal_context(filename="header.h")
        result = _build_unit_diagram("Mod|header", unit_info, units_data, functions_data, fid_to_unit, unit_names)
        assert result is None

    def test_cpp_unit_returns_string(self):
        unit_info, units_data, functions_data, fid_to_unit, unit_names = _make_minimal_context()
        result = _build_unit_diagram("Mod|core", unit_info, units_data, functions_data, fid_to_unit, unit_names)
        assert isinstance(result, str)

    def test_output_starts_with_mermaid_init(self):
        unit_info, units_data, functions_data, fid_to_unit, unit_names = _make_minimal_context()
        result = _build_unit_diagram("Mod|core", unit_info, units_data, functions_data, fid_to_unit, unit_names)
        assert result.startswith("%%{init:")

    def test_output_contains_flowchart_lr(self):
        unit_info, units_data, functions_data, fid_to_unit, unit_names = _make_minimal_context()
        result = _build_unit_diagram("Mod|core", unit_info, units_data, functions_data, fid_to_unit, unit_names)
        assert "flowchart LR" in result

    def test_output_contains_subgraph_for_module(self):
        unit_info, units_data, functions_data, fid_to_unit, unit_names = _make_minimal_context()
        result = _build_unit_diagram("Mod|core", unit_info, units_data, functions_data, fid_to_unit, unit_names)
        assert "subgraph" in result

    def test_unit_node_appears_in_diagram(self):
        unit_info, units_data, functions_data, fid_to_unit, unit_names = _make_minimal_context()
        result = _build_unit_diagram("Mod|core", unit_info, units_data, functions_data, fid_to_unit, unit_names)
        assert "Mod_core" in result

    def test_callee_edge_labeled_with_interface_id(self):
        unit_key = "Mod|core"
        callee_key = "Ext|service"
        unit_info = {"fileName": "core.cpp", "functionIds": ["f1"], "globalVariableIds": []}
        units_data = {
            unit_key: unit_info,
            callee_key: {"fileName": "service.cpp", "functionIds": ["f2"], "globalVariableIds": []},
        }
        functions_data = {
            "f1": {
                "qualifiedName": "Mod::process",
                "callsIds": ["f2"],
                "calledByIds": [],
                "interfaceId": "IFC_001",
            },
            "f2": {
                "qualifiedName": "Ext::doWork",
                "callsIds": [],
                "calledByIds": ["f1"],
                "interfaceId": "IFC_002",
            },
        }
        fid_to_unit = {"f1": unit_key, "f2": callee_key}
        unit_names = {unit_key: "core", callee_key: "service"}
        result = _build_unit_diagram(unit_key, unit_info, units_data, functions_data, fid_to_unit, unit_names)
        assert "IFC_002" in result

    def test_self_calls_not_added_as_edges(self):
        unit_key = "Mod|core"
        unit_info = {"fileName": "core.cpp", "functionIds": ["f1", "f2"], "globalVariableIds": []}
        units_data = {unit_key: unit_info}
        functions_data = {
            "f1": {"qualifiedName": "Mod::a", "callsIds": ["f2"], "calledByIds": [], "interfaceId": ""},
            "f2": {"qualifiedName": "Mod::b", "callsIds": [], "calledByIds": ["f1"], "interfaceId": "IFC_SELF"},
        }
        fid_to_unit = {"f1": unit_key, "f2": unit_key}
        unit_names = {unit_key: "core"}
        result = _build_unit_diagram(unit_key, unit_info, units_data, functions_data, fid_to_unit, unit_names)
        # self-calls should be omitted — IFC_SELF must not appear as an edge
        assert "IFC_SELF" not in (result or "")

    def test_allowed_modules_marks_internal_units(self):
        unit_key = "Mod|core"
        peer_key = "Mod|peer"
        unit_info = {"fileName": "core.cpp", "functionIds": [], "globalVariableIds": []}
        peer_info = {"fileName": "peer.cpp", "functionIds": [], "globalVariableIds": []}
        units_data = {unit_key: unit_info, peer_key: peer_info}
        unit_names = {unit_key: "core", peer_key: "peer"}
        result = _build_unit_diagram(
            unit_key, unit_info, units_data, {}, {}, unit_names,
            allowed_modules={"mod"}
        )
        assert result is not None
        assert "Mod" in result  # module subgraph label
