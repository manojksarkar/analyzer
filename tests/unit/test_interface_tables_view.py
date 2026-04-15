"""Unit tests for src/views/interface_tables.py — pure functions only."""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

# Import the module directly, bypassing registry side-effects
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
    "views.interface_tables",
    os.path.join(PROJECT_ROOT, "src", "views", "interface_tables.py"),
    submodule_search_locations=[],
)
_mod = importlib.util.module_from_spec(_spec)
_mod.__package__ = "views"
_spec.loader.exec_module(_mod)

_strip_ext = _mod._strip_ext
_fid_to_unit = _mod._fid_to_unit
_build_interface_tables = _mod._build_interface_tables


# ---------------------------------------------------------------------------
# _strip_ext
# ---------------------------------------------------------------------------

class TestStripExt:
    def test_removes_cpp_extension(self):
        assert _strip_ext("file.cpp") == "file"

    def test_removes_h_extension(self):
        assert _strip_ext("header.h") == "header"

    def test_no_extension_unchanged(self):
        assert _strip_ext("noext") == "noext"

    def test_none_returns_none(self):
        assert _strip_ext(None) is None

    def test_empty_string(self):
        assert _strip_ext("") == ""

    def test_dotfile_treated_as_extension(self):
        # os.path.splitext(".hidden") -> ('.hidden', '') — no ext, unchanged
        assert _strip_ext(".hidden") == ".hidden"


# ---------------------------------------------------------------------------
# _fid_to_unit
# ---------------------------------------------------------------------------

class TestFidToUnit:
    def test_maps_fid_to_unit(self):
        units = {"Mod|core": {"functionIds": ["f1", "f2"]}}
        result = _fid_to_unit(units)
        assert result["f1"] == {"Mod|core"}
        assert result["f2"] == {"Mod|core"}

    def test_fid_in_multiple_units(self):
        units = {
            "Mod|a": {"functionIds": ["f1"]},
            "Mod|b": {"functionIds": ["f1"]},
        }
        result = _fid_to_unit(units)
        assert result["f1"] == {"Mod|a", "Mod|b"}

    def test_empty_units(self):
        assert _fid_to_unit({}) == {}

    def test_unit_with_no_function_ids(self):
        assert _fid_to_unit({"Mod|x": {}}) == {}


# ---------------------------------------------------------------------------
# _build_interface_tables
# ---------------------------------------------------------------------------

def _make_units(**overrides):
    base = {"Mod|core": {"name": "core", "fileName": "core.cpp", "functionIds": [], "globalVariableIds": []}}
    base.update(overrides)
    return base


def _make_func(fid, name, **overrides):
    base = {
        "interfaceId": f"IFC_{name}",
        "qualifiedName": f"Mod::{name}",
        "visibility": "public",
        "location": {"file": "core.cpp", "line": 10},
        "parameters": [],
        "calledByIds": [],
        "callsIds": [],
    }
    base.update(overrides)
    return fid, base


class TestBuildInterfaceTables:
    def test_empty_model_returns_unit_names(self):
        result = _build_interface_tables({}, {}, {})
        assert "unitNames" in result

    def test_skips_non_cpp_units(self):
        units = {"Mod|header": {"name": "header", "fileName": "header.h", "functionIds": [], "globalVariableIds": []}}
        result = _build_interface_tables(units, {}, {})
        assert "Mod|header" not in result

    def test_includes_cpp_unit(self):
        units = _make_units()
        result = _build_interface_tables(units, {}, {})
        assert "Mod|core" in result

    def test_unit_names_populated(self):
        units = _make_units()
        result = _build_interface_tables(units, {}, {})
        assert result["unitNames"]["Mod|core"] == "core"

    def test_public_function_included(self):
        units = {"Mod|core": {"name": "core", "fileName": "core.cpp", "functionIds": ["f1"], "globalVariableIds": []}}
        fid, func = _make_func("f1", "getValue")
        result = _build_interface_tables(units, {"f1": func}, {})
        entries = result["Mod|core"]["entries"]
        assert len(entries) == 1
        assert entries[0]["name"] == "getValue"

    def test_private_function_excluded(self):
        units = {"Mod|core": {"name": "core", "fileName": "core.cpp", "functionIds": ["f1"], "globalVariableIds": []}}
        fid, func = _make_func("f1", "helper", visibility="private")
        result = _build_interface_tables(units, {"f1": func}, {})
        assert result["Mod|core"]["entries"] == []

    def test_missing_function_id_skipped(self):
        units = {"Mod|core": {"name": "core", "fileName": "core.cpp", "functionIds": ["missing"], "globalVariableIds": []}}
        result = _build_interface_tables(units, {}, {})
        assert result["Mod|core"]["entries"] == []

    def test_global_variable_included(self):
        units = {"Mod|core": {"name": "core", "fileName": "core.cpp", "functionIds": [], "globalVariableIds": ["g1"]}}
        gvar = {
            "interfaceId": "IFC_G1",
            "qualifiedName": "Mod::gSpeed",
            "visibility": "public",
            "location": {"file": "core.cpp", "line": 5},
            "type": "uint8_t",
        }
        result = _build_interface_tables(units, {}, {"g1": gvar})
        entries = result["Mod|core"]["entries"]
        assert len(entries) == 1
        assert entries[0]["type"] == "Global Variable"
        assert entries[0]["range"] == "0-0xFF"

    def test_private_global_excluded(self):
        units = {"Mod|core": {"name": "core", "fileName": "core.cpp", "functionIds": [], "globalVariableIds": ["g1"]}}
        gvar = {"qualifiedName": "Mod::gSpeed", "visibility": "private", "type": "uint8_t"}
        result = _build_interface_tables(units, {}, {"g1": gvar})
        assert result["Mod|core"]["entries"] == []

    def test_allowed_modules_filters_out_other_modules(self):
        units = {
            "Mod|core": {"name": "core", "fileName": "core.cpp", "functionIds": [], "globalVariableIds": []},
            "Other|util": {"name": "util", "fileName": "util.cpp", "functionIds": [], "globalVariableIds": []},
        }
        result = _build_interface_tables(units, {}, {}, allowed_modules={"mod"})
        assert "Mod|core" in result
        assert "Other|util" not in result

    def test_function_entry_has_expected_keys(self):
        units = {"Mod|core": {"name": "core", "fileName": "core.cpp", "functionIds": ["f1"], "globalVariableIds": []}}
        fid, func = _make_func("f1", "process")
        result = _build_interface_tables(units, {"f1": func}, {})
        e = result["Mod|core"]["entries"][0]
        for key in ("interfaceId", "functionId", "type", "interfaceName", "name", "qualifiedName",
                    "unitKey", "unitName", "location", "parameters", "direction", "sourceDest"):
            assert key in e, f"Missing key: {key}"

    def test_file_extension_stripped_in_location(self):
        units = {"Mod|core": {"name": "core", "fileName": "core.cpp", "functionIds": ["f1"], "globalVariableIds": []}}
        fid, func = _make_func("f1", "process")
        result = _build_interface_tables(units, {"f1": func}, {})
        loc = result["Mod|core"]["entries"][0]["location"]
        assert not loc["file"].endswith(".cpp")

    def test_caller_unit_appears_in_source_dest(self):
        units = {
            "Mod|core": {"name": "core", "fileName": "core.cpp", "functionIds": ["f1"], "globalVariableIds": []},
            "Other|util": {"name": "util", "fileName": "util.cpp", "functionIds": ["f2"], "globalVariableIds": []},
        }
        fid, func = _make_func("f1", "process", calledByIds=["f2"])
        result = _build_interface_tables(units, {"f1": func, "f2": {"qualifiedName": "Other::helper", "visibility": "public", "location": {}, "parameters": [], "calledByIds": [], "callsIds": []}}, {})
        source_dest = result["Mod|core"]["entries"][0]["sourceDest"]
        assert "Other" in source_dest or source_dest != "-"

    def test_function_parameters_get_range(self):
        units = {"Mod|core": {"name": "core", "fileName": "core.cpp", "functionIds": ["f1"], "globalVariableIds": []}}
        fid, func = _make_func("f1", "setSpeed", parameters=[{"name": "speed", "type": "uint8_t"}])
        result = _build_interface_tables(units, {"f1": func}, {})
        params = result["Mod|core"]["entries"][0]["parameters"]
        assert params[0]["range"] == "0-0xFF"

    def test_description_added_when_present(self):
        units = {"Mod|core": {"name": "core", "fileName": "core.cpp", "functionIds": ["f1"], "globalVariableIds": []}}
        fid, func = _make_func("f1", "process", description="Does the processing")
        result = _build_interface_tables(units, {"f1": func}, {})
        assert result["Mod|core"]["entries"][0]["description"] == "Does the processing"

    def test_no_description_key_when_absent(self):
        units = {"Mod|core": {"name": "core", "fileName": "core.cpp", "functionIds": ["f1"], "globalVariableIds": []}}
        fid, func = _make_func("f1", "process")
        result = _build_interface_tables(units, {"f1": func}, {})
        assert "description" not in result["Mod|core"]["entries"][0]

    def test_functions_sorted_by_line(self):
        units = {"Mod|core": {"name": "core", "fileName": "core.cpp", "functionIds": ["f1", "f2"], "globalVariableIds": []}}
        fid1, func1 = _make_func("f1", "later", location={"file": "core.cpp", "line": 20})
        fid2, func2 = _make_func("f2", "earlier", location={"file": "core.cpp", "line": 5})
        result = _build_interface_tables(units, {"f1": func1, "f2": func2}, {})
        names = [e["name"] for e in result["Mod|core"]["entries"]]
        assert names == ["earlier", "later"]
