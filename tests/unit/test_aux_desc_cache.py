"""Unit tests for the export-time description cache (M-B, llm_enrichment.py).

struct + unit summaries are pure functions of their inputs; an unchanged struct/unit
must reuse its description with NO LLM call.
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

import llm_enrichment as le  # noqa: E402
from llm_core.cache import EntityCache  # noqa: E402

_CFG = {"llm": {"defaultModel": "m", "cacheVersion": 1, "descriptions": True}}


def _fresh_cache(tmp_path, monkeypatch):
    """A cache with no project id, so it never touches the database.

    The in-memory half has to work on its own: these descriptions are asked for from several
    call sites in one export, and a cache that only dedupes when Postgres is reachable would
    quietly re-pay the LLM for each of them on any machine without one.
    """
    monkeypatch.setattr(le, "_AUX_DESC_CACHE", EntityCache("", "aux_descriptions", 1))


def test_struct_description_cached(tmp_path, monkeypatch):
    _fresh_cache(tmp_path, monkeypatch)
    calls = {"n": 0}

    def fake_call(prompt, config, *, system="", kind="default", **kwargs):
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

    def fake_call(prompt, config, *, system="", kind="default", **kwargs):
        calls["n"] += 1
        return "Input Name: the input\nOutput Name: the output"

    monkeypatch.setattr(le, "_call_llm", fake_call)
    args = ("int f(){return 1;}", [], [], [], "int", "1", "", "")
    r1 = le.get_behaviour_names(*args, _CFG)
    r2 = le.get_behaviour_names(*args, _CFG)
    assert r1 == r2 == {"inputName": "the input", "outputName": "the output"}
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


def test_rich_enrichment_regenerate_does_not_answer_from_the_cache(monkeypatch):
    """REQ-CS-01. A reviewer corrected a description this function was written from; the
    regeneration queue asks for it again. The cache key is the source plus the callees' SOURCE
    hashes, which a corrected description does not move -- so a cache hit hands back the very
    wording the queue exists to replace. `regenerate` names the functions that must not be
    answered from it, in either pass."""
    monkeypatch.setattr(le, "llm_provider_reachable", lambda config: True)
    monkeypatch.setattr(le, "load_llm_config", lambda config: {
        "provider": "openai", "defaultModel": "m", "cacheVersion": 1})
    monkeypatch.setattr(le, "extract_source", lambda base, loc: "int f() { return 1; }")
    monkeypatch.setattr(EntityCache, "get", lambda self, entity, h: "Stale, from the cache.")
    monkeypatch.setattr(le, "get_rich_description", lambda *a, **k: "Fresh, pass one.")
    monkeypatch.setattr(le, "_get_refined_description", lambda *a, **k: "Fresh, pass two.")

    def funcs():
        return {"A|U|f|": {"qualifiedName": "f", "description": "", "callsIds": [],
                           "location": {"file": "f.cpp", "line": 1}}}

    assert le.enrich_functions_rich(funcs(), "/tmp", _CFG)["A|U|f|"]["description"] == \
        "Stale, from the cache."
    assert le.enrich_functions_rich(funcs(), "/tmp", _CFG, regenerate={"A|U|f|"})[
        "A|U|f|"]["description"] == "Fresh, pass two."


def test_behaviour_call_descriptions_cached(tmp_path, monkeypatch):
    """FAST_WORD_FILE_UPDATES P4. Asked again on every Phase 3, every behaviour row was re-worded
    each run -- rows nobody corrected changed -- and each call paid the gateway's pause. Cached by
    the prompt: the same caller and callee descriptions give the same words with no call, and a
    corrected description (it is in the prompt) asks again."""
    from behaviour_diagram.llm_call_description import CallDescriptionGenerator
    _fresh_cache(tmp_path, monkeypatch)
    calls = []

    class Client:
        def generate(self, system, prompt):
            calls.append(prompt)
            return "Run calls compute to add the numbers."

    functions = {"A|U|run|": {"description": "Runs the job."},
                 "B|V|compute|": {"description": "Adds two numbers."}}

    def describe():
        gen = CallDescriptionGenerator(_CFG)
        gen._llm_available, gen._llm_client = True, Client()
        return gen.get_call_description("A|U|run|", "B|V|compute|", lambda k: k.split("|")[2],
                                        functions)

    assert describe() == describe() == "Run calls compute to add the numbers."
    assert len(calls) == 1                                       # the second run reused it
    functions["B|V|compute|"]["description"] = "Sums two integers."   # a reviewer's correction
    describe()
    assert len(calls) == 2                                       # its rows are asked again


def test_global_description_cached(tmp_path, monkeypatch):
    """REQ-JS-23. A global's description was asked on every run: two runs of one commit gave
    different Word files (tools/job_scheduling_test C01), and a resumed run asked again for
    answers it already had. Cached by the prompt, as a unit's: the same declaration gives the same
    words with no call; another declaration asks again."""
    _fresh_cache(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(le, "_call_llm", lambda prompt, config, **k: calls.append(prompt)
                        or "Counts the shared ticks.")
    assert le.get_global_description("int g_tick = 0;", _CFG) == "Counts the shared ticks."
    assert le.get_global_description("int g_tick = 0;", _CFG) == "Counts the shared ticks."
    assert len(calls) == 1                                       # the second run reused it
    le.get_global_description("long g_tick = 0;", _CFG)
    assert len(calls) == 2                                       # another declaration -> asked


def test_rich_global_description_cached(tmp_path, monkeypatch):
    """The rich path, the same way: its readers' and writers' descriptions are in the prompt, so
    a corrected one asks again -- and only then."""
    _fresh_cache(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(le, "_call_llm", lambda prompt, config, **k: calls.append(prompt)
                        or "The tick shared by the units.")

    def describe(readers):
        return le.get_rich_global_description("int g_tick = 0;", _CFG, qualified_name="g_tick",
                                              read_sites=readers)

    assert describe("  scale: Scales by the tick.") == describe("  scale: Scales by the tick.")
    assert len(calls) == 1
    describe("  scale: Multiplies a value by the tick.")         # a reviewer's correction
    assert len(calls) == 2


def test_global_fresh_replaces_the_cached_text(tmp_path, monkeypatch):
    """A rewrite asked for (the regeneration queue, a Word-file update) is answered past the
    cache, and its words REPLACE the cached ones: the next run keeps them instead of bringing the
    rejected wording back."""
    _fresh_cache(tmp_path, monkeypatch)
    answers = iter(["Old words.", "New words."])
    monkeypatch.setattr(le, "_call_llm", lambda *a, **k: next(answers))
    assert le.get_global_description("int g_tick = 0;", _CFG) == "Old words."
    assert le.get_global_description("int g_tick = 0;", _CFG, fresh=True) == "New words."
    assert le.get_global_description("int g_tick = 0;", _CFG) == "New words."   # no third call


def test_enrich_globals_regenerate_does_not_answer_from_the_cache(tmp_path, monkeypatch):
    """Both enrichment paths: a global `regenerate` names (by canonical key) is asked again; the
    others come from the cache."""
    _fresh_cache(tmp_path, monkeypatch)
    monkeypatch.setattr(le, "llm_provider_reachable", lambda config: True)
    monkeypatch.setattr(le, "load_abbreviations", lambda root, config: {})
    monkeypatch.setattr(le, "load_llm_config", lambda config: {
        "provider": "openai", "defaultModel": "m", "cacheVersion": 1})
    monkeypatch.setattr(le, "extract_source_line", lambda base, loc: "int g_%s = 0;" % loc["line"])
    count = {"n": 0}

    def fake_call(*a, **k):
        count["n"] += 1
        return "Words %d." % count["n"]
    monkeypatch.setattr(le, "_call_llm", fake_call)
    gl = {"G1": {"qualifiedName": "g_1", "location": {"file": "a.cpp", "line": 1}},
          "G2": {"qualifiedName": "g_2", "location": {"file": "a.cpp", "line": 2}}}
    plain = le.enrich_globals_with_descriptions(list(gl.values()), "/src", _CFG)
    rich = le.enrich_globals_rich(gl, {}, "/src", _CFG)
    assert count["n"] == 4                                       # the two paths, two prompts each
    again = le.enrich_globals_with_descriptions(list(gl.values()), "/src", _CFG,
                                                regenerate={"a.cpp:1"})
    assert again["a.cpp:2"] == plain["a.cpp:2"]                  # from the cache
    assert again["a.cpp:1"]["description"] == "Words 5."         # asked again
    again = le.enrich_globals_rich(gl, {}, "/src", _CFG, regenerate={"a.cpp:2"})
    assert again["a.cpp:1"] == rich["a.cpp:1"]
    assert again["a.cpp:2"]["description"] == "Words 6."
    assert count["n"] == 6


def test_phase_two_asks_queued_globals_past_the_cache(monkeypatch):
    """`_enrich_from_llm` hands the queued globals to the enrichment as `regenerate` -- only the
    functions' were, so with a cache a queued global would have been answered with the wording the
    queue exists to replace."""
    import types
    import model_deriver
    queued = [types.SimpleNamespace(row=types.SimpleNamespace(slot_key="G1")),
              types.SimpleNamespace(row=types.SimpleNamespace(slot_key="F1"))]
    monkeypatch.setattr(model_deriver, "_take_regeneration_queue", lambda model, kinds: queued)
    monkeypatch.setattr(model_deriver, "_retire_regeneration_queue", lambda q, model: None)
    monkeypatch.setattr(le, "enrich_functions_rich", lambda *a, **k: {})
    seen = {}
    monkeypatch.setattr(le, "enrich_globals_with_descriptions",
                        lambda gl, base, cfg, regenerate=None: seen.setdefault("plain", regenerate)
                        and {})
    monkeypatch.setattr(le, "enrich_globals_rich",
                        lambda gl, fns, base, cfg, knowledge=None, regenerate=None:
                        seen.setdefault("rich", regenerate) and {})
    functions = {"F1": {"qualifiedName": "f", "location": {"file": "a.cpp", "line": 9}}}
    gl = {"G1": {"location": {"file": "a.cpp", "line": 1}},
          "G2": {"location": {"file": "a.cpp", "line": 2}}}
    for variable_enrichment, path in ((False, "plain"), (True, "rich")):
        cfg = {"llm": {"descriptions": True,
                       "enrichment": {"variableEnrichment": variable_enrichment}}}
        model_deriver._enrich_from_llm("/src", functions, gl, cfg)
        assert seen[path] == {"a.cpp:1"}
