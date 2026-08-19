"""Unit tests for task 3.14 — description blocklist scrub + domain-context anchoring."""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

import llm_enrichment as le  # noqa: E402


# ── _scrub_blocklist ──────────────────────────────────────────────────────

def _cfg(words):
    return {"llm": {"descriptionBlocklist": words}}


def test_scrub_removes_whole_word():
    assert le._scrub_blocklist("Handles the audio buffer", _cfg(["audio"])) == "Handles the buffer"


def test_scrub_is_case_insensitive():
    assert le._scrub_blocklist("Decodes AUDIO frames", _cfg(["audio"])) == "Decodes frames"


def test_scrub_leaves_identifier_substrings_intact():
    # word-boundary: an identifier that merely contains the word is NOT touched
    out = le._scrub_blocklist("Returns the videoDecoderId value", _cfg(["video"]))
    assert out == "Returns the videoDecoderId value"


def test_scrub_cleans_punctuation():
    # word removed, the space before the comma is cleaned up
    out = le._scrub_blocklist("Streams audio, then flushes", _cfg(["audio"]))
    assert out == "Streams, then flushes"


def test_scrub_multiple_words():
    out = le._scrub_blocklist("Mixes audio and video tracks", _cfg(["audio", "video"]))
    assert out == "Mixes and tracks"


def test_scrub_empty_list_is_noop():
    text = "Mixes audio and video tracks"
    assert le._scrub_blocklist(text, _cfg([])) == text
    assert le._scrub_blocklist(text, {"llm": {}}) == text


def test_scrub_empty_text():
    assert le._scrub_blocklist("", _cfg(["audio"])) == ""


# ── load_domain_context ───────────────────────────────────────────────────

def test_load_domain_context_strips_comments(tmp_path):
    f = tmp_path / "domain.txt"
    f.write_text("# a comment\nFlash firmware.\n\n# another\nFTL/HIL/FIL layers.\n", encoding="utf-8")
    cfg = {"llm": {"domainContextPath": "domain.txt"}}
    assert le.load_domain_context(str(tmp_path), cfg) == "Flash firmware.\nFTL/HIL/FIL layers."


def test_load_domain_context_missing_returns_empty(tmp_path):
    cfg = {"llm": {"domainContextPath": "nope.txt"}}
    assert le.load_domain_context(str(tmp_path), cfg) == ""


def test_load_domain_context_unset_returns_empty(tmp_path):
    assert le.load_domain_context(str(tmp_path), {"llm": {}}) == ""


# ── _call_llm wiring (anchor system for descriptions, scrub output) ────────

class _FakeClient:
    provider = "ollama"

    def __init__(self, reply):
        self.reply = reply
        self.last_system = None
        self.last_prompt = None

    def generate(self, system, prompt, *, kind="other"):
        # `kind` labels the call for the run's LLM accounting (llm_core.callstats), which
        # reports how many calls produced nothing. The double has to accept it or every
        # description call raises TypeError.
        self.last_system = system
        self.last_prompt = prompt
        self.last_kind = kind
        return self.reply


def _patch(monkeypatch, reply):
    client = _FakeClient(reply)
    monkeypatch.setattr(le, "_get_client", lambda config: client)
    monkeypatch.setattr(le, "_get_domain_context", lambda config: "DOMAIN BRIEF")
    return client


def test_call_llm_anchors_description_system(monkeypatch):
    client = _patch(monkeypatch, "ok")
    le._call_llm("p", {}, system="base", kind="description")
    assert "DOMAIN BRIEF" in client.last_system
    assert "base" in client.last_system


def test_call_llm_does_not_anchor_other_kinds(monkeypatch):
    client = _patch(monkeypatch, "ok")
    le._call_llm("p", {}, system="base", kind="behaviour_names")
    assert client.last_system == "base"


def test_call_llm_scrubs_description_output(monkeypatch):
    _patch(monkeypatch, "Handles the audio buffer")
    cfg = {"llm": {"descriptionBlocklist": ["audio"]}}
    assert le._call_llm("p", cfg, kind="description") == "Handles the buffer"


def test_call_llm_does_not_scrub_other_kinds(monkeypatch):
    _patch(monkeypatch, "audio")
    cfg = {"llm": {"descriptionBlocklist": ["audio"]}}
    assert le._call_llm("p", cfg, kind="behaviour_names") == "audio"
