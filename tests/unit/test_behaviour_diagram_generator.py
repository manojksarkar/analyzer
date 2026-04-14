"""Unit tests for the behaviour diagram generator.

Tests the generator contract independently of the pipeline.
LLM calls are mocked via the llm_client seam so tests are fast and deterministic.

Contract the real generator must satisfy:
- generate_all_diagrams(function_key, output_dir) creates one .mmd per external caller.
  "External" means a caller whose module differs from the current function's module.
- Internal callers (same module) are silently skipped.
- Each .mmd file contains a valid Mermaid diagram produced by the LLM.
- Returns a list of paths to the created .mmd files.
- Returns [] when the function has no external callers.
- File naming: <current_key_sanitized>__<caller_key_sanitized>.mmd
- Graceful fallback when LLM returns empty string.
- Code fences in LLM response are stripped before writing.
"""
import json
import os
import re
import sys
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from fake_behaviour_diagram_generator import FakeBehaviourGenerator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MERMAID_HEADERS = re.compile(
    r"^(%%\{|flowchart|graph|sequenceDiagram|classDiagram|stateDiagram)",
    re.MULTILINE,
)

SAMPLE_MERMAID = "flowchart TD\n  A[Start] --> B[End]"
FENCED_MERMAID = f"```mermaid\n{SAMPLE_MERMAID}\n```"


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _make_generator(tmp_path, functions: dict) -> FakeBehaviourGenerator:
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    functions_path = str(model_dir / "functions.json")
    modules_path = str(model_dir / "modules.json")
    units_path = str(model_dir / "units.json")
    _write_json(functions_path, functions)
    _write_json(modules_path, {})
    _write_json(units_path, {})
    return FakeBehaviourGenerator(modules_path, units_path, functions_path)


# ---------------------------------------------------------------------------
# External-caller filtering (pure logic — works on current implementation)
# ---------------------------------------------------------------------------

class TestExternalCallerFiltering:
    def _functions(self, caller_module: str) -> dict:
        return {
            "Core|Core|compute|": {
                "qualifiedName": "compute",
                "calledByIds": [f"{caller_module}|Main|main|"],
            },
            f"{caller_module}|Main|main|": {
                "qualifiedName": "main",
                "calledByIds": [],
            },
        }

    def test_external_caller_produces_mmd_file(self, tmp_path):
        gen = _make_generator(tmp_path, self._functions("App"))
        out_dir = str(tmp_path / "bd")
        paths = gen.generate_all_diagrams("Core|Core|compute|", out_dir)
        assert paths, "Expected at least one .mmd file for external caller"

    def test_internal_caller_produces_no_file(self, tmp_path):
        """Caller in same module (Core) must be skipped."""
        gen = _make_generator(tmp_path, self._functions("Core"))
        out_dir = str(tmp_path / "bd")
        paths = gen.generate_all_diagrams("Core|Core|compute|", out_dir)
        assert paths == [], "Internal caller must not produce a .mmd file"

    def test_no_callers_returns_empty_list(self, tmp_path):
        functions = {
            "Core|Core|compute|": {"qualifiedName": "compute", "calledByIds": []},
        }
        gen = _make_generator(tmp_path, functions)
        paths = gen.generate_all_diagrams("Core|Core|compute|", str(tmp_path / "bd"))
        assert paths == []

    def test_multiple_external_callers_produce_multiple_files(self, tmp_path):
        functions = {
            "Core|Core|compute|": {
                "qualifiedName": "compute",
                "calledByIds": ["App|Main|main|", "Cross|Hub|hub|"],
            },
            "App|Main|main|": {"qualifiedName": "main", "calledByIds": []},
            "Cross|Hub|hub|": {"qualifiedName": "hub", "calledByIds": []},
        }
        gen = _make_generator(tmp_path, functions)
        paths = gen.generate_all_diagrams("Core|Core|compute|", str(tmp_path / "bd"))
        assert len(paths) == 2


# ---------------------------------------------------------------------------
# File naming convention (pure logic — works on current implementation)
# ---------------------------------------------------------------------------

class TestFileNaming:
    def test_files_use_double_underscore_separator(self, tmp_path):
        functions = {
            "Core|Core|compute|": {
                "qualifiedName": "compute",
                "calledByIds": ["App|Main|main|"],
            },
            "App|Main|main|": {"qualifiedName": "main", "calledByIds": []},
        }
        gen = _make_generator(tmp_path, functions)
        paths = gen.generate_all_diagrams("Core|Core|compute|", str(tmp_path / "bd"))
        assert paths
        fname = os.path.basename(paths[0])
        assert "__" in fname, f"Expected '__' separator in filename: {fname}"

    def test_files_have_mmd_extension(self, tmp_path):
        functions = {
            "Core|Core|compute|": {
                "qualifiedName": "compute",
                "calledByIds": ["App|Main|main|"],
            },
            "App|Main|main|": {"qualifiedName": "main", "calledByIds": []},
        }
        gen = _make_generator(tmp_path, functions)
        paths = gen.generate_all_diagrams("Core|Core|compute|", str(tmp_path / "bd"))
        for path in paths:
            assert path.endswith(".mmd"), f"Expected .mmd extension: {path}"

    def test_pipe_chars_sanitized_in_filename(self, tmp_path):
        functions = {
            "Core|Core|compute|": {
                "qualifiedName": "compute",
                "calledByIds": ["App|Main|main|"],
            },
            "App|Main|main|": {"qualifiedName": "main", "calledByIds": []},
        }
        gen = _make_generator(tmp_path, functions)
        paths = gen.generate_all_diagrams("Core|Core|compute|", str(tmp_path / "bd"))
        for path in paths:
            assert "|" not in os.path.basename(path), f"Pipe char in filename: {path}"


# ---------------------------------------------------------------------------
# File content: Mermaid validity (works on current implementation)
# ---------------------------------------------------------------------------

class TestMmdContent:
    def _generate(self, tmp_path) -> list:
        functions = {
            "Core|Core|compute|": {
                "qualifiedName": "compute",
                "calledByIds": ["App|Main|main|"],
            },
            "App|Main|main|": {"qualifiedName": "main", "calledByIds": []},
        }
        gen = _make_generator(tmp_path, functions)
        return gen.generate_all_diagrams("Core|Core|compute|", str(tmp_path / "bd"))

    def test_mmd_files_are_non_empty(self, tmp_path):
        paths = self._generate(tmp_path)
        for path in paths:
            with open(path, encoding="utf-8") as f:
                content = f.read()
            assert content.strip(), f"Empty .mmd file: {path}"

    def test_mmd_files_contain_valid_mermaid(self, tmp_path):
        paths = self._generate(tmp_path)
        for path in paths:
            with open(path, encoding="utf-8") as f:
                content = f.read()
            # Strip code fences if present (real LLM may wrap output)
            stripped = content.strip()
            m = re.match(r"^```(?:mermaid)?\s*\n?(.*?)```\s*$", stripped, re.DOTALL)
            inner = m.group(1).strip() if m else stripped
            assert _MERMAID_HEADERS.search(inner), (
                f"Not a valid Mermaid diagram in {os.path.basename(path)}: {inner[:60]!r}"
            )


# ---------------------------------------------------------------------------
# LLM content contract (requires real LLM seam — xfail until implemented)
# ---------------------------------------------------------------------------

class TestLlmContract:
    """These tests define what the real generator must do with the LLM.
    They are marked xfail because the current generator does not call llm_client.
    Remove xfail markers once the real implementation is wired up.
    """

    def _generate_with_mock(self, tmp_path, llm_response: str) -> list:
        functions = {
            "Core|Core|compute|": {
                "qualifiedName": "compute",
                "calledByIds": ["App|Main|main|"],
                "location": {"file": "Core.cpp", "line": 1, "endLine": 5},
            },
            "App|Main|main|": {"qualifiedName": "main", "calledByIds": []},
        }
        gen = _make_generator(tmp_path, functions)
        with patch("fake_behaviour_diagram_generator.llm_client") as mock_llm:
            mock_llm._call_ollama.return_value = llm_response
            return gen.generate_all_diagrams("Core|Core|compute|", str(tmp_path / "bd"))

    @pytest.mark.xfail(reason="real LLM seam not yet wired in generator", strict=False)
    def test_llm_response_written_to_mmd(self, tmp_path):
        paths = self._generate_with_mock(tmp_path, SAMPLE_MERMAID)
        assert paths
        with open(paths[0], encoding="utf-8") as f:
            content = f.read()
        assert "flowchart TD" in content

    @pytest.mark.xfail(reason="real LLM seam not yet wired in generator", strict=False)
    def test_code_fences_stripped_from_llm_response(self, tmp_path):
        paths = self._generate_with_mock(tmp_path, FENCED_MERMAID)
        assert paths
        with open(paths[0], encoding="utf-8") as f:
            content = f.read()
        assert "```" not in content

    @pytest.mark.xfail(reason="real LLM seam not yet wired in generator", strict=False)
    def test_fallback_on_empty_llm_response(self, tmp_path):
        """Empty LLM response must not produce an empty or broken .mmd file."""
        paths = self._generate_with_mock(tmp_path, "")
        assert paths
        with open(paths[0], encoding="utf-8") as f:
            content = f.read()
        assert _MERMAID_HEADERS.search(content.strip()), (
            f"Expected fallback Mermaid diagram, got: {content!r}"
        )
