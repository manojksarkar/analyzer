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


def test_behaviour_names_cached(tmp_path, monkeypatch):
    """M-C: behaviour names reuse the cache instead of re-calling the LLM each run."""
    _fresh_cache(tmp_path, monkeypatch)
    calls = {"n": 0}

    def fake_call(prompt, config, *, system="", kind="default"):
        calls["n"] += 1
        return "Input Name: the input\nOutput Name: the output"

    monkeypatch.setattr(le, "_call_llm", fake_call)
    args = ("int f(){return 1;}", [], [], [], "int", "1", "", "")
    r1 = le.get_behaviour_names(*args, _CFG)
    r2 = le.get_behaviour_names(*args, _CFG)
    assert r1 == r2 == {"behaviourInputName": "the input", "behaviourOutputName": "the output"}
    assert calls["n"] == 1                                  # cached -> one LLM call


def test_rich_enrichment_early_exit(monkeypatch):
    """M-C: when nothing needs a description, return BEFORE building the O(model) infra
    (and without any LLM call)."""
    monkeypatch.setattr(le, "llm_provider_reachable", lambda config: True)
    monkeypatch.setattr(le, "get_rich_description",
                        lambda *a, **k: pytest.fail("should not enrich anything"))
    funcs = {  # every function already has a description -> work set is empty
        "A|U|f|": {"qualifiedName": "f", "description": "Already described.",
                   "callsIds": [], "location": {}},
        "A|U|g|": {"qualifiedName": "g", "description": "Also described.",
                   "callsIds": ["A|U|f|"], "location": {}},
    }
    assert le.enrich_functions_rich(funcs, "/tmp", _CFG, knowledge=None) == {}
