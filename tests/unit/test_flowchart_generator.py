"""Unit tests for the flowchart generator.

Tests the generator contract independently of the pipeline.
LLM calls are mocked via the llm_client seam so tests are fast and deterministic.

Contract the real generator must satisfy:
- build_flowchart_for_function(func_data, source) calls LLM with a prompt
  that contains the source code and returns the Mermaid diagram as a string.
- run() groups functions by unit, writes one JSON file per unit,
  each file is a list of {name, flowchart} objects.
- Graceful fallback when LLM returns empty string.
- Code fences (```mermaid```) in LLM response are stripped before storing.
"""
import json
import os
import sys
import re
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

import fake_flowchart_generator as fc_gen


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MERMAID_HEADERS = re.compile(
    r"^(%%\{|flowchart|graph|sequenceDiagram|classDiagram|stateDiagram)",
    re.MULTILINE,
)

SAMPLE_MERMAID = "flowchart TD\n  A[Start] --> B[End]"
FENCED_MERMAID = f"```mermaid\n{SAMPLE_MERMAID}\n```"


def _functions_json(tmp_path, entries: dict) -> str:
    path = tmp_path / "functions.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# Pure logic: key extraction and safe naming
# ---------------------------------------------------------------------------

class TestFunctionIdToUnitKey:
    def test_standard_key(self):
        assert fc_gen.function_id_to_unit_key("Core|Core|add|int") == "Core|Core"

    def test_two_part_key(self):
        assert fc_gen.function_id_to_unit_key("Lib|Lib") == "Lib|Lib"

    def test_single_part_falls_back(self):
        result = fc_gen.function_id_to_unit_key("nopipe")
        assert result == "unknown|unknown"

    def test_empty_string(self):
        result = fc_gen.function_id_to_unit_key("")
        assert result == "unknown|unknown"


class TestSafeFilename:
    def test_replaces_unsafe_chars(self):
        result = fc_gen.safe_filename("Core|Core|add|int")
        assert "|" not in result

    def test_plain_name_unchanged(self):
        assert fc_gen.safe_filename("Core") == "Core"

    def test_empty_string(self):
        assert fc_gen.safe_filename("") == ""


# ---------------------------------------------------------------------------
# build_flowchart_for_function: LLM contract
# ---------------------------------------------------------------------------

@pytest.mark.llm
class TestBuildFlowchartForFunction:
    """Tests for what the real generator's build_flowchart_for_function must do.

    The real implementation must:
    1. Call the LLM with a prompt that contains the source code.
    2. Return the Mermaid string from the LLM response.
    3. Strip code fences if the LLM wraps output in ```mermaid```.
    4. Return a non-empty fallback when LLM gives an empty response.
    """

    def _build(self, llm_response: str, func_data: dict = None, source: str = "int add(int a) { return a; }"):
        """Call build_flowchart_for_function with the LLM mocked."""
        func_data = func_data or {"qualifiedName": "add", "params": []}
        # Patch at the seam the real generator will use.
        with patch("fake_flowchart_generator.llm_client") as mock_llm:
            mock_llm._call_ollama.return_value = llm_response
            return fc_gen.build_flowchart_for_function(func_data, source)

    @pytest.mark.xfail(reason="real LLM seam not yet wired in generator", strict=False)
    def test_returns_llm_response(self):
        result = self._build(SAMPLE_MERMAID)
        assert result == SAMPLE_MERMAID

    @pytest.mark.xfail(reason="real LLM seam not yet wired in generator", strict=False)
    def test_strips_code_fences(self):
        result = self._build(FENCED_MERMAID)
        assert "```" not in result
        assert "flowchart" in result

    @pytest.mark.xfail(reason="real LLM seam not yet wired in generator", strict=False)
    def test_fallback_on_empty_llm_response(self):
        """Empty LLM response must not produce an empty or broken diagram."""
        result = self._build("")
        assert result and _MERMAID_HEADERS.search(result.strip()), (
            f"Expected fallback Mermaid diagram, got: {result!r}"
        )

    @pytest.mark.xfail(reason="real LLM seam not yet wired in generator", strict=False)
    def test_prompt_contains_source_code(self):
        source = "int myFunc(int x) { return x * 2; }"
        with patch("fake_flowchart_generator.llm_client") as mock_llm:
            mock_llm._call_ollama.return_value = SAMPLE_MERMAID
            fc_gen.build_flowchart_for_function({"qualifiedName": "myFunc"}, source)
        prompt = mock_llm._call_ollama.call_args[0][0]
        assert source in prompt


# ---------------------------------------------------------------------------
# run(): file output contract
# ---------------------------------------------------------------------------

class TestRun:
    def _make_functions(self):
        return {
            "Core|Core|add|int": {"qualifiedName": "add", "params": [], "location": {"file": "Core.cpp", "line": 1, "endLine": 3}},
            "Core|Core|sub|int": {"qualifiedName": "sub", "params": [], "location": {"file": "Core.cpp", "line": 5, "endLine": 7}},
            "Lib|Lib|normalize|float": {"qualifiedName": "normalize", "params": [], "location": {"file": "Lib.cpp", "line": 1, "endLine": 4}},
        }

    def test_creates_one_file_per_unit(self, tmp_path):
        interface_json = _functions_json(tmp_path, self._make_functions())
        out_dir = tmp_path / "flowcharts"
        fc_gen.run(str(interface_json), str(out_dir))
        files = {f.name for f in out_dir.iterdir() if f.suffix == ".json"}
        assert "Core.json" in files
        assert "Lib.json" in files

    def test_output_is_list_of_name_flowchart(self, tmp_path):
        interface_json = _functions_json(tmp_path, self._make_functions())
        out_dir = tmp_path / "flowcharts"
        fc_gen.run(str(interface_json), str(out_dir))
        with open(out_dir / "Core.json", encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, list)
        for entry in data:
            assert "name" in entry
            assert "flowchart" in entry

    def test_function_count_matches(self, tmp_path):
        interface_json = _functions_json(tmp_path, self._make_functions())
        out_dir = tmp_path / "flowcharts"
        fc_gen.run(str(interface_json), str(out_dir))
        with open(out_dir / "Core.json", encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) == 2  # add + sub

    def test_function_names_are_simple_not_qualified(self, tmp_path):
        """Names must be the simple function name, not the full qualified name."""
        functions = {
            "Core|Core|MyClass::getValue|": {
                "qualifiedName": "MyClass::getValue",
                "params": [],
                "location": {"file": "Core.cpp", "line": 1, "endLine": 2},
            }
        }
        interface_json = _functions_json(tmp_path, functions)
        out_dir = tmp_path / "flowcharts"
        fc_gen.run(str(interface_json), str(out_dir))
        with open(out_dir / "Core.json", encoding="utf-8") as f:
            data = json.load(f)
        assert data[0]["name"] == "getValue"

    def test_flowchart_content_is_valid_mermaid(self, tmp_path):
        interface_json = _functions_json(tmp_path, self._make_functions())
        out_dir = tmp_path / "flowcharts"
        fc_gen.run(str(interface_json), str(out_dir))
        with open(out_dir / "Core.json", encoding="utf-8") as f:
            data = json.load(f)
        for entry in data:
            content = (entry.get("flowchart") or "").strip()
            assert content, f"Empty flowchart for function '{entry.get('name')}'"
            assert _MERMAID_HEADERS.search(content), (
                f"Not valid Mermaid for '{entry.get('name')}': {content[:60]!r}"
            )

    def test_empty_functions_json_produces_no_files(self, tmp_path):
        interface_json = _functions_json(tmp_path, {})
        out_dir = tmp_path / "flowcharts"
        fc_gen.run(str(interface_json), str(out_dir))
        json_files = list(out_dir.glob("*.json")) if out_dir.exists() else []
        assert json_files == []
