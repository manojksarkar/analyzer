"""Unit tests for the L2 prompt-parity capture hook (docs/production-redesign/07 §2).

LLM output is non-deterministic, so refactors are verified by proving the *input*
never changed. `_dump_prompt` is the single capture point (every call site reaches
the model through LlmClient), and it is content-addressed so the corpus compares
as a set — independent of ordering and of which phase-subprocess produced it.
"""
import json
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from llm_core.client import _dump_prompt, _dump_dir


def _parts(user="hello"):
    return [{"role": "system", "content": "sys"}, {"role": "user", "content": user}]


def _corpus(d):
    """(prompt files, call records) written into the dump dir."""
    files = sorted(f for f in os.listdir(str(d)) if f.endswith(".json"))
    calls_path = os.path.join(str(d), "calls.jsonl")
    calls = []
    if os.path.isfile(calls_path):
        with open(calls_path, encoding="utf-8") as fh:
            calls = [json.loads(ln) for ln in fh if ln.strip()]
    return files, calls


class TestDumpGating:
    def test_no_dump_when_env_unset(self, tmp_path, monkeypatch):
        monkeypatch.delenv("LLM_PROMPT_DUMP", raising=False)
        assert _dump_dir() is None
        _dump_prompt("openai", "m", _parts())          # must be a no-op
        assert os.listdir(str(tmp_path)) == []

    def test_never_raises_on_unserialisable_payload(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LLM_PROMPT_DUMP", str(tmp_path))
        _dump_prompt("openai", "m", [{"role": "user", "content": object()}])  # not JSON-safe
        # A dump failure must never abort a run.


class TestCorpus:
    def test_writes_prompt_and_call_record(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LLM_PROMPT_DUMP", str(tmp_path))
        _dump_prompt("openai", "gpt", _parts(), num_ctx=8192, temperature=0.1)
        files, calls = _corpus(tmp_path)
        assert len(files) == 1 and len(calls) == 1
        rec = json.loads((tmp_path / files[0]).read_text(encoding="utf-8"))
        assert rec["provider"] == "openai" and rec["model"] == "gpt"
        assert rec["params"]["num_ctx"] == 8192          # params affect output -> captured
        assert rec["parts"][1]["content"] == "hello"
        assert calls[0]["digest"] == files[0][:-5]

    def test_identical_prompts_dedup_but_still_counted(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LLM_PROMPT_DUMP", str(tmp_path))
        for _ in range(3):
            _dump_prompt("openai", "gpt", _parts())
        files, calls = _corpus(tmp_path)
        assert len(files) == 1     # content-addressed -> stored once
        assert len(calls) == 3     # ...but a dropped/extra call is still detectable

    def test_different_prompt_differs(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LLM_PROMPT_DUMP", str(tmp_path))
        _dump_prompt("openai", "gpt", _parts("a"))
        _dump_prompt("openai", "gpt", _parts("b"))
        files, _ = _corpus(tmp_path)
        assert len(files) == 2

    def test_changed_params_change_the_digest(self, tmp_path, monkeypatch):
        # temperature/num_ctx change the model's behaviour, so they are part of identity
        monkeypatch.setenv("LLM_PROMPT_DUMP", str(tmp_path))
        _dump_prompt("openai", "gpt", _parts(), temperature=0.0)
        _dump_prompt("openai", "gpt", _parts(), temperature=0.9)
        files, _ = _corpus(tmp_path)
        assert len(files) == 2

    def test_digest_is_order_independent_across_processes(self, tmp_path, monkeypatch):
        """Same prompt from a different 'process' maps to the same file (set semantics)."""
        monkeypatch.setenv("LLM_PROMPT_DUMP", str(tmp_path))
        _dump_prompt("openai", "gpt", _parts())
        first, _ = _corpus(tmp_path)
        _dump_prompt("openai", "gpt", _parts())
        second, calls = _corpus(tmp_path)
        assert first == second and len(calls) == 2


class TestFakeResponses:
    """Deterministic stand-in replies let the baseline be captured with no gateway."""

    def test_disabled_by_default(self, monkeypatch):
        from llm_core.client import _fake_enabled
        monkeypatch.delenv("LLM_FAKE_RESPONSES", raising=False)
        assert _fake_enabled() is False

    @pytest.mark.parametrize("val,expected", [("1", True), ("true", True),
                                              ("0", False), ("false", False), ("", False)])
    def test_env_parsing(self, monkeypatch, val, expected):
        from llm_core.client import _fake_enabled
        monkeypatch.setenv("LLM_FAKE_RESPONSES", val)
        assert _fake_enabled() is expected

    def test_response_is_deterministic_and_non_empty(self):
        from llm_core.client import _fake_response
        a = _fake_response("sys", "user")
        assert a and a == _fake_response("sys", "user")      # stable across calls
        assert a != _fake_response("sys", "other")           # varies with the prompt
