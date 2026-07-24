"""Unit tests for engine/views/test_specs.py — deterministic scaffold (SWE.4)."""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

# The view modules are lightweight (utils + stdlib only), so import the real
# package — stubbing sys.modules["views.registry"] here would shadow the real
# registry (EXPORTER_REGISTRY etc.) for any other test in the session.
import views.test_specs as ts_mod
from views.test_specs import _build_test_specs, GENERATION_METHOD


def _model():
    """Small synthetic model: one .cpp unit with a public writer that calls a
    helper and consumes a global, plus a private function, plus a header unit."""
    functions = {
        "Comp|U|doWrite|int": {
            "qualifiedName": "doWrite", "interfaceId": "IF_01", "visibility": "public",
            "returnType": "void", "parameters": [{"name": "n", "type": "int"}],
            "location": {"line": 10}, "callsIds": ["Comp|U|helper|"],
            "writesGlobalIds": ["Comp|U|g_count"], "readsGlobalIds": ["Comp|U|g_count"],
        },
        "Comp|U|readOnly|": {
            "qualifiedName": "readOnly", "interfaceId": "IF_02", "visibility": "public",
            "returnType": "int", "parameters": [],
            "location": {"line": 20}, "readsGlobalIds": ["Comp|U|g_flag"],
        },
        "Comp|U|helper|": {
            "qualifiedName": "helper", "interfaceId": "IF_03", "visibility": "private",
            "returnType": "void", "parameters": [], "location": {"line": 30},
        },
    }
    globals_ = {
        "Comp|U|g_count": {"qualifiedName": "g_count", "type": "int", "value": "0"},
        "Comp|U|g_flag": {"qualifiedName": "g_flag", "type": "int"},
    }
    units = {
        "Comp|U": {"name": "U", "fileName": "U.cpp",
                   "functionIds": ["Comp|U|doWrite|int", "Comp|U|readOnly|", "Comp|U|helper|"]},
        "Comp|H": {"name": "H", "fileName": "H.h", "functionIds": []},
    }
    return units, functions, globals_


class TestScope:
    def test_public_functions_get_specs_private_excluded(self):
        ts = _build_test_specs(*_model())
        names = [s["name"] for s in ts["Comp|U"]["functions"]]
        assert names == ["doWrite", "readOnly"]  # helper (private) excluded, line-ordered

    def test_header_only_unit_produces_no_section(self):
        ts = _build_test_specs(*_model())
        assert "Comp|H" not in ts


class TestPrecondition:
    def _spec(self, name="doWrite"):
        ts = _build_test_specs(*_model())
        return next(s for s in ts["Comp|U"]["functions"] if s["name"] == name)

    def test_callees_listed_as_mock_calls(self):
        assert self._spec()["precondition"]["mockFunctions"] == ["helper()"]

    def test_parameters_listed(self):
        params = self._spec()["precondition"]["parameters"]
        assert [(p["name"], p["type"]) for p in params] == [("n", "int")]

    def test_consumed_global_has_direction_and_value(self):
        g = self._spec()["precondition"]["globals"][0]
        assert g["name"] == "g_count" and g["direction"] == "read/write" and g["value"] == "0"

    def test_read_only_global_direction(self):
        g = self._spec("readOnly")["precondition"]["globals"][0]
        assert g["name"] == "g_flag" and g["direction"] == "read" and "value" not in g


class TestInputExpected:
    def test_void_when_no_parameters(self):
        ts = _build_test_specs(*_model())
        ro = next(s for s in ts["Comp|U"]["functions"] if s["name"] == "readOnly")
        assert ro["input"]["isVoid"] is True

    def test_not_void_with_parameters(self):
        ts = _build_test_specs(*_model())
        dw = next(s for s in ts["Comp|U"]["functions"] if s["name"] == "doWrite")
        assert dw["input"]["isVoid"] is False

    def test_written_globals_in_expected(self):
        ts = _build_test_specs(*_model())
        dw = next(s for s in ts["Comp|U"]["functions"] if s["name"] == "doWrite")
        assert [g["name"] for g in dw["expected"]["writesGlobals"]] == ["g_count"]
        ro = next(s for s in ts["Comp|U"]["functions"] if s["name"] == "readOnly")
        assert ro["expected"]["writesGlobals"] == []


class TestMetadata:
    def test_one_deterministic_test_case_id_per_function(self):
        ts = _build_test_specs(*_model())
        ids = [s["testCaseId"] for s in ts["Comp|U"]["functions"]]
        assert ids == ["TC_IF_01", "TC_IF_02"]

    def test_generation_method_is_analysis_of_requirements(self):
        ts = _build_test_specs(*_model())
        assert all(s["generationMethod"] == "Analysis of Requirements"
                   for s in ts["Comp|U"]["functions"])
        assert GENERATION_METHOD == "Analysis of Requirements"


class TestDeterminism:
    def test_two_builds_identical(self):
        import json
        a = json.dumps(_build_test_specs(*_model()), sort_keys=False)
        b = json.dumps(_build_test_specs(*_model()), sort_keys=False)
        assert a == b


class TestDefaultTestSteps:
    def test_steps_present_without_llm(self):
        ts = _build_test_specs(*_model())
        dw = next(s for s in ts["Comp|U"]["functions"] if s["name"] == "doWrite")
        assert dw["testSteps"], "deterministic steps floor should never be empty"

    def test_steps_name_call_precondition_and_verify(self):
        ts = _build_test_specs(*_model())
        dw = next(s for s in ts["Comp|U"]["functions"] if s["name"] == "doWrite")
        joined = " ".join(dw["testSteps"])
        assert "helper()" in joined and "g_count" in joined  # precondition setup
        assert "Call doWrite(n)" in joined                    # invocation names the param
        assert "Verify" in joined and "g_count" in joined     # verify written global

    def test_void_no_param_call_rendered(self):
        ts = _build_test_specs(*_model())
        ro = next(s for s in ts["Comp|U"]["functions"] if s["name"] == "readOnly")
        assert any("Call readOnly()" in s for s in ro["testSteps"])


class TestLlmEnrichment:
    def test_summarize_off_keeps_deterministic_floor(self):
        ts = _build_test_specs(*_model())
        ts_mod._enrich_with_llm(ts, {"llm": {"summarize": False}})
        dw = next(s for s in ts["Comp|U"]["functions"] if s["name"] == "doWrite")
        assert dw["input"]["sets"] == []      # value sets stay LLM-only
        assert dw["testSteps"]                # but the steps floor remains

    def test_enrichment_fills_sets(self, monkeypatch):
        ts = _build_test_specs(*_model())
        monkeypatch.setattr(ts_mod, "get_test_cases", lambda spec, config: {
            "inputSets": ["n = 5"], "expectedSets": ["g_count = 5"], "testSteps": ["set n", "call"],
        }, raising=False)
        # get_test_cases is imported inside _enrich_with_llm from llm_enrichment;
        # patch there so the local import picks it up.
        import llm_enrichment
        monkeypatch.setattr(llm_enrichment, "get_test_cases", lambda spec, config: {
            "inputSets": ["n = 5"], "expectedSets": ["g_count = 5"], "testSteps": ["set n", "call"],
        })
        ts_mod._enrich_with_llm(ts, {"llm": {"summarize": True}})
        dw = next(s for s in ts["Comp|U"]["functions"] if s["name"] == "doWrite")
        assert dw["input"]["sets"] == ["n = 5"]
        assert dw["expected"]["sets"] == ["g_count = 5"]
        assert dw["testSteps"] == ["set n", "call"]

    def test_enrichment_failure_keeps_scaffold(self, monkeypatch):
        ts = _build_test_specs(*_model())
        def _boom(spec, config):
            raise RuntimeError("llm down")
        import llm_enrichment
        monkeypatch.setattr(llm_enrichment, "get_test_cases", _boom)
        ts_mod._enrich_with_llm(ts, {"llm": {"summarize": True}})  # must not raise
        dw = next(s for s in ts["Comp|U"]["functions"] if s["name"] == "doWrite")
        assert dw["input"]["sets"] == []
