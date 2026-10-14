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


# ── the Input / Output Names prompt within the LLM's window (2026-10-14j) ───────────────────

_SERVER_CFG = {"llm": {"defaultModel": "m", "cacheVersion": 1, "descriptions": True},
               "llmServer": {"provider": "openai", "baseUrl": "http://gw", "defaultModel": "m",
                             "maxContextTokens": 4000}}


def _sent_prompt(tmp_path, monkeypatch, args, cfg, abbreviations=None):
    _fresh_cache(tmp_path, monkeypatch)
    sent = []
    monkeypatch.setattr(le, "_call_llm", lambda prompt, config, **kw: sent.append(prompt)
                        or "Input Name: i\nOutput Name: o")
    le.get_behaviour_names(*args, cfg, abbreviations)
    return sent[0]


def _prompt_before(source, params, globals_read, globals_written, return_type, return_expr,
                   draft_input, draft_output, abbreviations):
    """The prompt as get_behaviour_names built it until 2026-10-14j, verbatim."""
    params_part = ", ".join(f"{p.get('name', '')} ({p.get('type', '')})" for p in (params or [])
                            if p.get("name") or p.get("type"))

    def block(label, glist):
        if not glist:
            return ""
        lines = []
        for g in glist:
            name = g.get("name") or (g.get("qualifiedName") or "").split("::")[-1]
            desc = (g.get("description") or "").strip()
            lines.append(f"  - {name} ({g.get('type', '')})" + (f": {desc}" if desc else ""))
        return "\n" + label + "\n" + "\n".join(lines)
    abbrev_block = ""
    if abbreviations:
        formatted = le._format_abbreviations(abbreviations)
        if formatted:
            abbrev_block = "\n\nUse these abbreviations when naming (expand to full phrase where relevant):\n\n" + formatted
    return f"""Given this C++ function, suggest two short human-readable labels for documentation:
1) Input Name: what this behaviour takes as input (parameters + globals it reads).
2) Output Name: what it produces (return value or globals it writes).

{abbrev_block}
Function:
```cpp
{source}
```
Parameters: {params_part or 'none'}
Return type: {return_type or 'void'}
Return expression: {return_expr or 'none'}{block("Globals read (inputs):", globals_read)}{block("Globals written (outputs):", globals_written)}

Current draft labels (improve if they are generic or code-like): Input="{draft_input or ''}", Output="{draft_output or ''}"

Reply with exactly two lines in this format (no other text):
Input Name: <short phrase>
Output Name: <short phrase>"""


def test_a_prompt_that_fits_is_sent_as_it_was_built(tmp_path, monkeypatch):
    """Every prompt of the sample fits: not one character of it may move."""
    g = [{"name": "g_a", "qualifiedName": "g_a", "type": "int", "description": "The counter."}]
    args = ("int f(int x) {\n  return x + g_a;\n}", [{"name": "x", "type": "int"}], g, g, "int",
            "x + g_a", "f input", "f output")
    abbrev = {"FTL": "flash translation layer"}
    for cfg in (_CFG, _SERVER_CFG):                     # no LLM server known, and a small window
        assert _sent_prompt(tmp_path, monkeypatch, args, cfg, abbrev) == _prompt_before(*args, abbrev)


def test_a_prompt_too_big_for_the_window_is_cut_to_fit(tmp_path, monkeypatch):
    """A top-level function of the reviewed firmware reaches thousands of globals: its prompt was
    larger than the model takes. Now the descriptions go first, then the globals past their
    section, then the source past its section -- the instructions never."""
    from llm_core.budget import ContextBudget
    from llm_core.token_counter import get_counter
    many = [{"name": f"g_{i:04d}", "qualifiedName": f"g_{i:04d}", "type": "uint32_t",
             "description": f"A counter the flash translation layer keeps for block {i}."}
            for i in range(3000)]
    source = "int top(void) {\n" + "".join(f"  step{i}();\n" for i in range(800)) + "  return 0;\n}"
    args = (source, [], many, many[:1500], "int", "0", "", "")
    sent = _sent_prompt(tmp_path, monkeypatch, args, _SERVER_CFG)
    counter = get_counter("m")
    budget = ContextBudget(max_tokens=4000, task="behaviour_names", counter=counter)
    assert counter.count(sent) <= budget.effective_input() - budget.allocate("output_reserve")
    assert "A counter the flash" not in sent, "the descriptions go first"
    assert "  - g_0000 (uint32_t)" in sent and "more" in sent, "the first globals stay, the rest counted"
    assert "[truncated]" in sent, "the source past its section"
    assert sent.rstrip().endswith("Output Name: <short phrase>"), "the instructions are never cut"


def test_only_the_descriptions_go_when_that_is_enough(tmp_path, monkeypatch):
    many = [{"name": f"g_{i:03d}", "qualifiedName": f"g_{i:03d}", "type": "int",
             "description": "x" * 1200} for i in range(20)]
    args = ("int f(void) { return 0; }", [], many, [], "int", "0", "", "")
    sent = _sent_prompt(tmp_path, monkeypatch, args, _SERVER_CFG)
    assert "xxxx" not in sent and "  - g_019 (int)" in sent and "more" not in sent
