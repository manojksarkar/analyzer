"""Unit tests for src/model_deriver.py.

Strategy: import individual functions and feed synthetic dicts.
No libclang, no file I/O, no pipeline needed.

Functions covered:
  _id_seg                  — pure string transformation
  _readable_label          — identifier → human label
  _propagate_global_access — transitive global reads/writes along call graph
  _enrich_interfaces       — sets interfaceId on functions and globals
  _enrich_behaviour_names  — sets behaviourInputName / behaviourOutputName
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

import utils
from utils import init_module_mapping, KEY_SEP
import model_deriver
from model_deriver import (
    _id_seg,
    _readable_label,
    _propagate_global_access,
    _enrich_behaviour_names,
    _enrich_interfaces,
    _build_interface_index,
)


# ---------------------------------------------------------------------------
# _id_seg
# ---------------------------------------------------------------------------

class TestIdSeg:
    def test_keeps_uppercase_letters(self):
        assert _id_seg("Sample") == "SAMPLE"

    def test_strips_digits_and_underscores(self):
        assert _id_seg("Core_123") == "CORE"

    def test_strips_spaces(self):
        assert _id_seg("My Module") == "MYMODULE"

    def test_empty_string(self):
        assert _id_seg("") == ""

    def test_none(self):
        assert _id_seg(None) == ""

    def test_all_non_letters(self):
        assert _id_seg("123_456") == ""


# ---------------------------------------------------------------------------
# _readable_label
# ---------------------------------------------------------------------------

class TestReadableLabel:
    def test_strips_g_prefix(self):
        assert _readable_label("g_sensorValue") == "SensorValue"

    def test_strips_s_prefix(self):
        assert _readable_label("s_mode") == "Mode"

    def test_strips_t_prefix(self):
        assert _readable_label("t_timer") == "Timer"

    def test_no_prefix_capitalizes(self):
        assert _readable_label("speed") == "Speed"

    def test_underscores_become_spaces(self):
        assert _readable_label("input_value") == "Input value"

    def test_short_name_returns_empty(self):
        assert _readable_label("g_x") == ""
        assert _readable_label("n") == ""

    def test_empty_returns_empty(self):
        assert _readable_label("") == ""

    def test_none_returns_empty(self):
        assert _readable_label(None) == ""


# ---------------------------------------------------------------------------
# _propagate_global_access
# ---------------------------------------------------------------------------

class TestPropagateGlobalAccess:
    def _make_func(self, calls=None, reads=None, writes=None):
        return {
            "callsIds": calls or [],
            "readsGlobalIds": reads or [],
            "writesGlobalIds": writes or [],
        }

    def test_direct_reads_unchanged(self):
        fns = {"f1": self._make_func(reads=["g1"])}
        _propagate_global_access(fns)
        assert "g1" in fns["f1"]["readsGlobalIdsTransitive"]

    def test_transitive_read_propagated(self):
        """f1 calls f2; f2 reads g1 → f1 should transitively read g1."""
        fns = {
            "f1": self._make_func(calls=["f2"]),
            "f2": self._make_func(reads=["g1"]),
        }
        _propagate_global_access(fns)
        assert "g1" in fns["f1"]["readsGlobalIdsTransitive"]

    def test_transitive_write_propagated(self):
        """f1 calls f2; f2 writes g1 → f1 should transitively write g1."""
        fns = {
            "f1": self._make_func(calls=["f2"]),
            "f2": self._make_func(writes=["g1"]),
        }
        _propagate_global_access(fns)
        assert "g1" in fns["f1"]["writesGlobalIdsTransitive"]

    def test_multi_hop_propagation(self):
        """f1 → f2 → f3 reads g1 → f1 should also transitively read g1."""
        fns = {
            "f1": self._make_func(calls=["f2"]),
            "f2": self._make_func(calls=["f3"]),
            "f3": self._make_func(reads=["g1"]),
        }
        _propagate_global_access(fns)
        assert "g1" in fns["f1"]["readsGlobalIdsTransitive"]
        assert "g1" in fns["f2"]["readsGlobalIdsTransitive"]

    def test_no_globals_produces_no_transitive_fields(self):
        fns = {"f1": self._make_func(calls=["f2"]), "f2": self._make_func()}
        _propagate_global_access(fns)
        assert "readsGlobalIdsTransitive" not in fns["f1"]
        assert "writesGlobalIdsTransitive" not in fns["f1"]

    def test_does_not_include_self_call(self):
        """Recursive function: f1 calls f1 — should not cause infinite loop."""
        fns = {"f1": self._make_func(calls=["f1"], reads=["g1"])}
        _propagate_global_access(fns)
        assert "g1" in fns["f1"]["readsGlobalIdsTransitive"]


# ---------------------------------------------------------------------------
# _enrich_behaviour_names
# ---------------------------------------------------------------------------

class TestEnrichBehaviourNames:
    def _run(self, func_dict, global_dict=None):
        fns = {"mod|unit|fn|": func_dict.copy()}
        _enrich_behaviour_names(fns, global_dict or {})
        return fns["mod|unit|fn|"]

    def test_uses_first_param_as_input(self):
        f = self._run({
            "parameters": [{"name": "speed", "type": "int"}],
            "returnType": "void", "returnExpr": "",
            "qualifiedName": "setSpeed",
        })
        assert "Speed" in f["behaviourInputName"]

    def test_uses_return_expr_as_output(self):
        f = self._run({
            "parameters": [],
            "returnType": "int", "returnExpr": "sum",
            "qualifiedName": "compute",
        })
        assert "Sum" in f["behaviourOutputName"]

    def test_uses_global_read_when_no_params(self):
        gvars = {"g1": {"qualifiedName": "g_temperature"}}
        f = self._run({
            "parameters": [],
            "returnType": "int", "returnExpr": "",
            "readsGlobalIds": ["g1"],
            "qualifiedName": "getTemp",
        }, gvars)
        assert "Temperature" in f["behaviourInputName"]

    def test_fallback_to_function_name(self):
        f = self._run({
            "parameters": [],
            "returnType": "void", "returnExpr": "",
            "qualifiedName": "MyClass::doWork",
        })
        assert "DoWork" in f["behaviourInputName"] or "input" in f["behaviourInputName"].lower()
        assert "DoWork" in f["behaviourOutputName"] or "result" in f["behaviourOutputName"].lower()

    def test_short_param_name_skipped(self):
        """Single-char param 'n' should be skipped — falls through to global or fallback."""
        f = self._run({
            "parameters": [{"name": "n", "type": "int"}],
            "returnType": "int", "returnExpr": "sum",
            "qualifiedName": "loopSum",
        })
        # returnExpr "sum" should win for output
        assert "Sum" in f["behaviourOutputName"]

    def test_output_uses_non_primitive_return_type(self):
        f = self._run({
            "parameters": [],
            "returnType": "SensorData", "returnExpr": "",
            "qualifiedName": "getData",
        })
        assert "SensorData" in f["behaviourOutputName"] or "Sensordata" in f["behaviourOutputName"]

    def test_fields_always_set(self):
        f = self._run({"parameters": [], "returnType": "void", "returnExpr": "", "qualifiedName": "f"})
        assert f.get("behaviourInputName")
        assert f.get("behaviourOutputName")


# ---------------------------------------------------------------------------
# _enrich_interfaces — interfaceId format
# ---------------------------------------------------------------------------

class TestEnrichInterfaces:
    def setup_method(self):
        init_module_mapping({
            "modulesGroups": {
                "Sample": {"Core": "Sample/Core"}
            }
        })

    def teardown_method(self):
        init_module_mapping(utils._CONFIG_CACHE)

    def _make_func(self, rel_file="Sample/Core/core.cpp"):
        return {
            "location": {"file": rel_file, "line": 1},
            "params": [],
            "parameters": [],
            "returnType": "int",
        }

    def test_interface_id_starts_with_IF(self):
        fns = {"Core|core|add|": self._make_func()}
        gvs = {}
        idx = {"Core|core|add|": 1}
        _enrich_interfaces("", "MyProject", fns, gvs, idx)
        assert fns["Core|core|add|"]["interfaceId"].startswith("IF_")

    def test_interface_id_contains_project_code(self):
        fns = {"Core|core|add|": self._make_func()}
        idx = {"Core|core|add|": 1}
        _enrich_interfaces("", "SampleCppProject", fns, {}, idx)
        assert "SAMPLECPPPROJECT" in fns["Core|core|add|"]["interfaceId"]

    def test_interface_id_contains_group_code(self):
        fns = {"Core|core|add|": self._make_func()}
        idx = {"Core|core|add|": 1}
        _enrich_interfaces("", "Proj", fns, {}, idx)
        iid = fns["Core|core|add|"]["interfaceId"]
        assert "SAMPLE" in iid

    def test_interface_id_index_zero_padded(self):
        fns = {"Core|core|add|": self._make_func()}
        idx = {"Core|core|add|": 5}
        _enrich_interfaces("", "Proj", fns, {}, idx)
        iid = fns["Core|core|add|"]["interfaceId"]
        assert iid.endswith("05")

    def test_non_letter_chars_stripped_from_project(self):
        fns = {"Core|core|add|": self._make_func()}
        idx = {"Core|core|add|": 1}
        _enrich_interfaces("", "My_Project_123", fns, {}, idx)
        iid = fns["Core|core|add|"]["interfaceId"]
        # _ separates segments (always present); digits/underscores stripped from the project segment only
        assert "123" not in iid
        # Project segment is "MYPROJECT" (underscores and digits stripped by _id_seg)
        assert "MYPROJECT" in iid
