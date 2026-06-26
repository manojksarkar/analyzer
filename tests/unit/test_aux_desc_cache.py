"""Unit tests for the export-time description cache (M-B, llm_enrichment.py).

struct + unit summaries are pure functions of their inputs; an unchanged struct/unit
must reuse its description with NO LLM call.
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

import llm_enrichment as le  # noqa: E402
from llm_core.cache import EntityCache  # noqa: E402

_CFG = {"llm": {"defaultModel": "m", "cacheVersion": 1, "descriptions": True}}


def _fresh_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(le, "_AUX_DESC_CACHE", EntityCache(str(tmp_path / "c"), 1))


def test_struct_description_cached(tmp_path, monkeypatch):
    _fresh_cache(tmp_path, monkeypatch)
    calls = {"n": 0}

    def fake_call(prompt, config, *, system="", kind="default"):
        calls["n"] += 1
        return "A point."

    monkeypatch.setattr(le, "_call_llm", fake_call)
    fields = [{"name": "x", "type": "int"}]
    assert le.get_struct_description("Point", fields, _CFG) == "A point."
    assert le.get_struct_description("Point", fields, _CFG) == "A point."   # cache hit
    assert calls["n"] == 1                                                  # only one LLM call
    le.get_struct_description("Point", [{"name": "y", "type": "int"}], _CFG)  # different fields
    assert calls["n"] == 2                                                  # -> miss


def test_unit_description_cached(tmp_path, monkeypatch):
    _fresh_cache(tmp_path, monkeypatch)
    calls = {"n": 0}
    monkeypatch.setattr(le, "_call_llm",
                        lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1) or "A unit."))
    fns = [("init", "Initializes things.")]
    assert le.get_unit_description("Core", fns, [], _CFG) == "A unit."
    assert le.get_unit_description("Core", fns, [], _CFG) == "A unit."      # cache hit
    assert calls["n"] == 1
    le.get_unit_description("Core", [("init", "Now does something else.")], [], _CFG)
    assert calls["n"] == 2                                                  # constituent change -> miss


def test_unnamed_struct_short_circuits(tmp_path, monkeypatch):
    _fresh_cache(tmp_path, monkeypatch)
    monkeypatch.setattr(le, "_call_llm", lambda *a, **k: pytest.fail("should not call LLM"))
    assert le.get_struct_description("", [], _CFG) == "Structure (unnamed, no fields)."
