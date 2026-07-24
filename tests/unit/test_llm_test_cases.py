"""Unit tests for the SWE.4 test-case builder in engine/llm_enrichment.py.

Covers the pure, deterministic pieces — fact extraction (cache key), prompt
grounding, and defensive JSON parsing. The live LLM call is not exercised here.
"""
import os
import sys
import json

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from llm_enrichment import _parse_test_cases, _build_test_case_prompt, _test_case_facts


def _spec():
    return {
        "name": "scale", "description": "Scale n by the stored factor.",
        "returnType": "int", "returnRange": "0-9",
        "location": {"line": 42}, "interfaceId": "IF_9",  # non-fact fields
        "parameters": [{"name": "n", "type": "int", "range": "0-9"}],
        "precondition": {
            "globals": [{"name": "g_factor", "type": "int", "direction": "read", "value": "2"}],
            "mockFunctions": ["clamp()"],
        },
    }


class TestFacts:
    def test_excludes_volatile_fields(self):
        facts = _test_case_facts(_spec())
        assert "location" not in facts and "interfaceId" not in facts

    def test_stable_across_calls(self):
        a = json.dumps(_test_case_facts(_spec()), sort_keys=True)
        b = json.dumps(_test_case_facts(_spec()), sort_keys=True)
        assert a == b

    def test_unrelated_field_change_does_not_alter_facts(self):
        s1 = _spec()
        s2 = _spec(); s2["location"] = {"line": 999}; s2["interfaceId"] = "IF_X"
        assert _test_case_facts(s1) == _test_case_facts(s2)


class TestPrompt:
    def test_grounds_on_signature_globals_mocks(self):
        p = _build_test_case_prompt(_test_case_facts(_spec()))
        assert "int n" in p and "range 0-9" in p
        assert "g_factor (read" in p and "initial 2" in p
        assert "clamp()" in p
        assert "Analysis-of-Requirements" in p

    def test_void_parameters_rendered(self):
        facts = _test_case_facts({"name": "f", "parameters": [], "precondition": {}})
        assert "VOID" in _build_test_case_prompt(facts)


class TestParse:
    def test_extracts_cases_and_steps(self):
        raw = 'prefix {"cases":[{"input":"n=1","expected":"returns 2"}],"steps":["a","b"]} suffix'
        out = _parse_test_cases(raw)
        assert out["inputSets"] == ["n=1"]
        assert out["expectedSets"] == ["returns 2"]
        assert out["testSteps"] == ["a", "b"]

    def test_index_alignment_preserved(self):
        raw = '{"cases":[{"input":"a","expected":"x"},{"input":"b","expected":"y"}]}'
        out = _parse_test_cases(raw)
        assert out["inputSets"] == ["a", "b"] and out["expectedSets"] == ["x", "y"]

    def test_missing_expected_becomes_empty_string(self):
        out = _parse_test_cases('{"cases":[{"input":"a"}]}')
        assert out["inputSets"] == ["a"] and out["expectedSets"] == [""]

    @pytest.mark.parametrize("raw", ["", "not json", "{broken", "[]", "null"])
    def test_garbage_returns_empties(self, raw):
        assert _parse_test_cases(raw) == {"inputSets": [], "expectedSets": [], "testSteps": []}
