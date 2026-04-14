"""Unit tests for src/llm_client.py.

Strategy: the LLM functions depend on Ollama (HTTP) at runtime, but all
network calls flow through two narrow points:
  - `requests.get`  used by _ollama_available()
  - `requests.post` used by _call_ollama()

We mock those two calls to test all logic without a running Ollama server.

Also covered with no mocking:
  - load_abbreviations()  — pure file I/O
  - extract_source()      — pure file I/O
  - get_behaviour_names() — response parsing (tested via mocked _call_ollama)
"""
import os
import sys
import tempfile
import textwrap
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

import llm_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg(**overrides):
    """Minimal config dict for llm_client functions."""
    base = {
        "llm": {
            "baseUrl": "http://localhost:11434",
            "defaultModel": "test-model",
            "timeoutSeconds": 5,
            "numCtx": 2048,
        }
    }
    base["llm"].update(overrides)
    return base


def _mock_post_response(text: str, status_code: int = 200):
    """Build a mock requests.Response for _call_ollama."""
    r = MagicMock()
    r.status_code = status_code
    r.raise_for_status = MagicMock()
    r.json.return_value = {"response": text}
    return r


# ---------------------------------------------------------------------------
# load_abbreviations
# ---------------------------------------------------------------------------

class TestLoadAbbreviations:
    def test_colon_format(self, tmp_path):
        f = tmp_path / "abbrevs.txt"
        f.write_text("SWC: Software Component\nECU: Electronic Control Unit\n")
        cfg = {"llm": {"abbreviationsPath": str(f)}}
        result = llm_client.load_abbreviations(str(tmp_path), cfg)
        assert result["SWC"] == "Software Component"
        assert result["ECU"] == "Electronic Control Unit"

    def test_equals_format(self, tmp_path):
        f = tmp_path / "abbrevs.txt"
        f.write_text("SWC=Software Component\n")
        cfg = {"llm": {"abbreviationsPath": str(f)}}
        result = llm_client.load_abbreviations(str(tmp_path), cfg)
        assert result["SWC"] == "Software Component"

    def test_comments_ignored(self, tmp_path):
        f = tmp_path / "abbrevs.txt"
        f.write_text("# this is a comment\nSWC: Software Component\n")
        cfg = {"llm": {"abbreviationsPath": str(f)}}
        result = llm_client.load_abbreviations(str(tmp_path), cfg)
        assert "SWC" in result
        assert len(result) == 1

    def test_blank_lines_ignored(self, tmp_path):
        f = tmp_path / "abbrevs.txt"
        f.write_text("\n\nSWC: Software Component\n\n")
        cfg = {"llm": {"abbreviationsPath": str(f)}}
        result = llm_client.load_abbreviations(str(tmp_path), cfg)
        assert len(result) == 1

    def test_missing_file_returns_empty(self, tmp_path):
        cfg = {"llm": {"abbreviationsPath": str(tmp_path / "nonexistent.txt")}}
        assert llm_client.load_abbreviations(str(tmp_path), cfg) == {}

    def test_no_path_in_config_returns_empty(self, tmp_path):
        cfg = {"llm": {}}
        assert llm_client.load_abbreviations(str(tmp_path), cfg) == {}


# ---------------------------------------------------------------------------
# extract_source
# ---------------------------------------------------------------------------

class TestExtractSource:
    def _write(self, tmp_path, content):
        f = tmp_path / "sample.cpp"
        f.write_text(content)
        return str(tmp_path), str(f.name)

    def test_extracts_correct_lines(self, tmp_path):
        code = "line1\nline2\nline3\nline4\nline5\n"
        f = tmp_path / "sample.cpp"
        f.write_text(code)
        loc = {"file": "sample.cpp", "line": 2, "endLine": 4}
        result = llm_client.extract_source(str(tmp_path), loc)
        assert "line2" in result
        assert "line4" in result
        assert "line1" not in result
        assert "line5" not in result

    def test_single_line(self, tmp_path):
        f = tmp_path / "sample.cpp"
        f.write_text("only\n")
        loc = {"file": "sample.cpp", "line": 1, "endLine": 1}
        assert llm_client.extract_source(str(tmp_path), loc) == "only"

    def test_missing_file_returns_empty(self, tmp_path):
        loc = {"file": "nonexistent.cpp", "line": 1, "endLine": 2}
        assert llm_client.extract_source(str(tmp_path), loc) == ""

    def test_invalid_line_range_returns_empty(self, tmp_path):
        f = tmp_path / "sample.cpp"
        f.write_text("line1\n")
        loc = {"file": "sample.cpp", "line": 5, "endLine": 3}
        assert llm_client.extract_source(str(tmp_path), loc) == ""


# ---------------------------------------------------------------------------
# _ollama_available
# ---------------------------------------------------------------------------

class TestOllamaAvailable:
    def test_returns_true_when_200(self):
        r = MagicMock()
        r.status_code = 200
        with patch("llm_client.HAS_REQUESTS", True), \
             patch("llm_client.requests.get", return_value=r):
            assert llm_client._ollama_available(_cfg()) is True

    def test_returns_false_when_not_200(self):
        r = MagicMock()
        r.status_code = 500
        with patch("llm_client.HAS_REQUESTS", True), \
             patch("llm_client.requests.get", return_value=r):
            assert llm_client._ollama_available(_cfg()) is False

    def test_returns_false_on_connection_error(self):
        import requests as req
        with patch("llm_client.HAS_REQUESTS", True), \
             patch("llm_client.requests.get", side_effect=req.ConnectionError()):
            assert llm_client._ollama_available(_cfg()) is False

    def test_returns_false_when_requests_not_installed(self):
        with patch("llm_client.HAS_REQUESTS", False):
            assert llm_client._ollama_available(_cfg()) is False


# ---------------------------------------------------------------------------
# _call_ollama
# ---------------------------------------------------------------------------

class TestCallOllama:
    def test_returns_response_text(self):
        with patch("llm_client.HAS_REQUESTS", True), \
             patch("llm_client.requests.post", return_value=_mock_post_response("hello")):
            result = llm_client._call_ollama("prompt", _cfg())
        assert result == "hello"

    def test_strips_whitespace_from_response(self):
        with patch("llm_client.HAS_REQUESTS", True), \
             patch("llm_client.requests.post", return_value=_mock_post_response("  trimmed  \n")):
            result = llm_client._call_ollama("prompt", _cfg())
        assert result == "trimmed"

    def test_retries_on_empty_response(self):
        """Empty response → retry once. Second call returns real text."""
        empty = _mock_post_response("")
        good = _mock_post_response("second attempt")
        with patch("llm_client.HAS_REQUESTS", True), \
             patch("llm_client.requests.post", side_effect=[empty, good]):
            result = llm_client._call_ollama("prompt", _cfg())
        assert result == "second attempt"

    def test_returns_empty_after_two_empties(self):
        empty = _mock_post_response("")
        with patch("llm_client.HAS_REQUESTS", True), \
             patch("llm_client.requests.post", return_value=empty):
            result = llm_client._call_ollama("prompt", _cfg())
        assert result == ""

    def test_returns_empty_when_requests_not_installed(self):
        with patch("llm_client.HAS_REQUESTS", False):
            result = llm_client._call_ollama("prompt", _cfg())
        assert result == ""

    def test_retries_on_request_exception(self):
        import requests as req
        good = _mock_post_response("recovered")
        with patch("llm_client.HAS_REQUESTS", True), \
             patch("llm_client.requests.post", side_effect=[req.RequestException(), good]):
            result = llm_client._call_ollama("prompt", _cfg())
        assert result == "recovered"

    def test_uses_correct_model_from_config(self):
        with patch("llm_client.HAS_REQUESTS", True) as _, \
             patch("llm_client.requests.post", return_value=_mock_post_response("ok")) as mock_post:
            llm_client._call_ollama("prompt", _cfg(defaultModel="my-model"))
        payload = mock_post.call_args[1]["json"]
        assert payload["model"] == "my-model"

    def test_uses_num_ctx_from_config(self):
        with patch("llm_client.HAS_REQUESTS", True), \
             patch("llm_client.requests.post", return_value=_mock_post_response("ok")) as mock_post:
            llm_client._call_ollama("prompt", _cfg(numCtx=4096))
        payload = mock_post.call_args[1]["json"]
        assert payload["options"]["num_ctx"] == 4096


# ---------------------------------------------------------------------------
# get_description
# ---------------------------------------------------------------------------

class TestGetDescription:
    def test_returns_llm_response(self):
        with patch("llm_client._call_ollama", return_value="Adds two integers."):
            result = llm_client.get_description("int add(int a, int b) { return a+b; }", _cfg())
        assert result == "Adds two integers."

    def test_returns_empty_for_empty_source(self):
        result = llm_client.get_description("", _cfg())
        assert result == ""

    def test_prompt_contains_source(self):
        source = "int add(int a, int b) { return a+b; }"
        with patch("llm_client._call_ollama", return_value="ok") as mock:
            llm_client.get_description(source, _cfg())
        prompt = mock.call_args[0][0]
        assert source in prompt

    def test_prompt_includes_callee_descriptions(self):
        with patch("llm_client._call_ollama", return_value="ok") as mock:
            llm_client.get_description(
                "int foo() {}",
                _cfg(),
                callee_descriptions={"helper": "Normalizes input"},
            )
        prompt = mock.call_args[0][0]
        assert "helper" in prompt
        assert "Normalizes input" in prompt

    def test_prompt_includes_abbreviations(self):
        with patch("llm_client._call_ollama", return_value="ok") as mock:
            llm_client.get_description(
                "int foo() {}",
                _cfg(),
                abbreviations={"SWC": "Software Component"},
            )
        prompt = mock.call_args[0][0]
        assert "SWC" in prompt


# ---------------------------------------------------------------------------
# get_behaviour_names
# ---------------------------------------------------------------------------

class TestGetBehaviourNames:
    def _call(self, raw_response, **kwargs):
        with patch("llm_client._call_ollama", return_value=raw_response):
            return llm_client.get_behaviour_names(
                source="int f(int x) { return x; }",
                params=kwargs.get("params", [{"name": "x", "type": "int"}]),
                globals_read=kwargs.get("globals_read", []),
                globals_written=kwargs.get("globals_written", []),
                return_type="int",
                return_expr="x",
                draft_input="x",
                draft_output="result",
                config=_cfg(),
            )

    def test_parses_well_formed_response(self):
        result = self._call("Input Name: Sensor Value\nOutput Name: Computed Result")
        assert result["behaviourInputName"] == "Sensor Value"
        assert result["behaviourOutputName"] == "Computed Result"

    def test_case_insensitive_parsing(self):
        result = self._call("input name: Foo\noutput name: Bar")
        assert result["behaviourInputName"] == "Foo"
        assert result["behaviourOutputName"] == "Bar"

    def test_returns_empty_dict_on_empty_response(self):
        result = self._call("")
        assert result == {}

    def test_returns_empty_dict_on_unparseable_response(self):
        result = self._call("This is not the expected format at all.")
        assert result == {}

    def test_returns_partial_if_only_one_line(self):
        result = self._call("Input Name: Partial Only")
        assert result.get("behaviourInputName") == "Partial Only"
        assert "behaviourOutputName" not in result

    def test_returns_empty_for_empty_source(self):
        with patch("llm_client._call_ollama", return_value="Input Name: X\nOutput Name: Y"):
            result = llm_client.get_behaviour_names(
                source="",
                params=[], globals_read=[], globals_written=[],
                return_type="void", return_expr="",
                draft_input="", draft_output="",
                config=_cfg(),
            )
        assert result == {}

    def test_prompt_includes_params(self):
        with patch("llm_client._call_ollama", return_value="") as mock:
            llm_client.get_behaviour_names(
                source="int f(int speed) {}",
                params=[{"name": "speed", "type": "int"}],
                globals_read=[], globals_written=[],
                return_type="int", return_expr="",
                draft_input="", draft_output="",
                config=_cfg(),
            )
        prompt = mock.call_args[0][0]
        assert "speed" in prompt

    def test_prompt_includes_globals_read(self):
        with patch("llm_client._call_ollama", return_value="") as mock:
            llm_client.get_behaviour_names(
                source="int f() {}",
                params=[],
                globals_read=[{"name": "g_temperature", "type": "int"}],
                globals_written=[],
                return_type="int", return_expr="",
                draft_input="", draft_output="",
                config=_cfg(),
            )
        prompt = mock.call_args[0][0]
        assert "g_temperature" in prompt

    def test_prompt_includes_abbreviations(self):
        with patch("llm_client._call_ollama", return_value="") as mock:
            llm_client.get_behaviour_names(
                source="int f() {}",
                params=[], globals_read=[], globals_written=[],
                return_type="void", return_expr="",
                draft_input="", draft_output="",
                config=_cfg(),
                abbreviations={"ECU": "Electronic Control Unit"},
            )
        prompt = mock.call_args[0][0]
        assert "ECU" in prompt


# ---------------------------------------------------------------------------
# get_global_description
# ---------------------------------------------------------------------------

class TestGetGlobalDescription:
    def test_returns_llm_response(self):
        with patch("llm_client._call_ollama", return_value="Stores the sensor reading."):
            result = llm_client.get_global_description("int g_sensorVal = 0;", _cfg())
        assert result == "Stores the sensor reading."

    def test_returns_empty_for_empty_source(self):
        assert llm_client.get_global_description("", _cfg()) == ""

    def test_prompt_contains_source(self):
        source = "int g_counter = 0;"
        with patch("llm_client._call_ollama", return_value="ok") as mock:
            llm_client.get_global_description(source, _cfg())
        assert source in mock.call_args[0][0]
