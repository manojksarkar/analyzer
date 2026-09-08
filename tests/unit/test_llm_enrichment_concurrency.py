"""Unit tests for CC-2 (docs/production-redesign/07-llm-concurrency-scaling.md):
concurrent call sites in llm_enrichment.py and model_deriver.py.

These mock out the actual LLM call (get_rich_description / _get_refined_description /
get_behaviour_names) rather than the network layer — CC-1's test_llm_client.py already
covers the client's own semaphore/rate-limiter. What's under test here is call-site
behaviour: wave synchronization (a callee's wave must finish before its caller's wave
starts), the worker-pool bound (never more in flight than llm.maxConcurrency), and that
the default (maxConcurrency=1) is a strict no-op — one call in flight at a time.
"""
import os
import sys
import threading
import time

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

import llm_enrichment as le  # noqa: E402
import model_deriver as md  # noqa: E402


def _cfg(max_concurrency=1, two_pass=False):
    return {
        "llm": {
            "provider": "openai",
            "baseUrl": "http://localhost:9999",
            "defaultModel": "m",
            "timeoutSeconds": 5,
            "numCtx": 2048,
            "retries": 0,
            "cacheVersion": 1,
            "maxConcurrency": max_concurrency,
            "enrichment": {"twoPassDescriptions": two_pass, "selfReview": False},
        }
    }


def _write_source(tmp_path, rel="foo.cpp", n_lines=40):
    (tmp_path / rel).write_text(
        "\n".join(f"// line {i}" for i in range(1, n_lines + 1)) + "\n",
        encoding="utf-8",
    )


def _loc(rel, start, end):
    return {"file": rel, "line": start, "endLine": end}


# ---------------------------------------------------------------------------
# enrich_functions_rich — wave synchronization
# ---------------------------------------------------------------------------

class TestEnrichFunctionsRichWaveSync:
    def test_callee_wave_completes_before_caller_wave_starts(self, tmp_path, monkeypatch):
        """A caller's context must see its callee's FINISHED description — proving
        the callee's wave is a hard sync point before the caller's wave starts,
        even though both waves run through a shared ThreadPoolExecutor."""
        _write_source(tmp_path)
        monkeypatch.setattr(le, "llm_provider_reachable", lambda config: True)

        seen_callee_context = {}

        def fake_get_rich_description(source, config, *, qualified_name="", callee_context="",
                                       **kwargs):
            if qualified_name == "caller":
                seen_callee_context["text"] = callee_context
            return f"desc for {qualified_name}"

        monkeypatch.setattr(le, "get_rich_description", fake_get_rich_description)

        funcs = {
            "callee_id": {"qualifiedName": "callee", "callsIds": [],
                          "location": _loc("foo.cpp", 1, 3)},
            "caller_id": {"qualifiedName": "caller", "callsIds": ["callee_id"],
                          "location": _loc("foo.cpp", 5, 7)},
        }
        result = le.enrich_functions_rich(funcs, str(tmp_path), _cfg(max_concurrency=4))

        assert result["callee_id"]["description"] == "desc for callee"
        assert result["caller_id"]["description"] == "desc for caller"
        assert "callee" in seen_callee_context["text"]

    def test_max_concurrency_one_is_sequential_noop(self, tmp_path, monkeypatch):
        """Default maxConcurrency=1 must never let two calls overlap."""
        _write_source(tmp_path)
        monkeypatch.setattr(le, "llm_provider_reachable", lambda config: True)

        lock = threading.Lock()
        state = {"current": 0, "high_water": 0}

        def fake_get_rich_description(source, config, *, qualified_name="", **kwargs):
            with lock:
                state["current"] += 1
                state["high_water"] = max(state["high_water"], state["current"])
            time.sleep(0.02)
            with lock:
                state["current"] -= 1
            return f"desc for {qualified_name}"

        monkeypatch.setattr(le, "get_rich_description", fake_get_rich_description)

        funcs = {
            f"f{i}_id": {"qualifiedName": f"f{i}", "callsIds": [],
                         "location": _loc("foo.cpp", 1, 3)}
            for i in range(6)
        }
        result = le.enrich_functions_rich(funcs, str(tmp_path), _cfg(max_concurrency=1))

        assert len(result) == 6
        assert state["high_water"] == 1

    def test_max_concurrency_n_bounds_overlap(self, tmp_path, monkeypatch):
        """Independent functions (single wave) overlap, but never past maxConcurrency."""
        _write_source(tmp_path)
        monkeypatch.setattr(le, "llm_provider_reachable", lambda config: True)

        lock = threading.Lock()
        state = {"current": 0, "high_water": 0}

        def fake_get_rich_description(source, config, *, qualified_name="", **kwargs):
            with lock:
                state["current"] += 1
                state["high_water"] = max(state["high_water"], state["current"])
            time.sleep(0.05)
            with lock:
                state["current"] -= 1
            return f"desc for {qualified_name}"

        monkeypatch.setattr(le, "get_rich_description", fake_get_rich_description)

        funcs = {
            f"f{i}_id": {"qualifiedName": f"f{i}", "callsIds": [],
                         "location": _loc("foo.cpp", 1, 3)}
            for i in range(12)
        }
        result = le.enrich_functions_rich(funcs, str(tmp_path), _cfg(max_concurrency=4))

        assert len(result) == 12
        assert 2 <= state["high_water"] <= 4

    def test_pass2_uses_pass1_snapshot_not_live_concurrent_result(self, tmp_path, monkeypatch):
        """Pass 2 refinement context must come from Pass 1's frozen output, never
        from another in-flight Pass-2 worker's refined text — otherwise the
        injected caller/callee context would depend on thread scheduling."""
        _write_source(tmp_path)
        monkeypatch.setattr(le, "llm_provider_reachable", lambda config: True)
        monkeypatch.setattr(le, "get_rich_description",
                            lambda source, config, *, qualified_name="", **kwargs:
                            f"pass1 desc for {qualified_name}")

        seen_caller_context = {}

        def fake_refine(source, config, *, qualified_name="", caller_context="", **kwargs):
            if qualified_name == "callee":
                seen_caller_context["text"] = caller_context
            return f"pass2 desc for {qualified_name}"

        monkeypatch.setattr(le, "_get_refined_description", fake_refine)

        funcs = {
            "callee_id": {"qualifiedName": "callee", "callsIds": [],
                          "calledByIds": ["caller_id"],
                          "location": _loc("foo.cpp", 1, 3)},
            "caller_id": {"qualifiedName": "caller", "callsIds": ["callee_id"],
                          "calledByIds": [],
                          "location": _loc("foo.cpp", 5, 7)},
        }
        le.enrich_functions_rich(funcs, str(tmp_path), _cfg(max_concurrency=4, two_pass=True))

        # "caller" is Pass 1's description for the caller (never overwritten by a
        # concurrently-running Pass-2 refinement of the caller itself).
        assert "pass1 desc for caller" in seen_caller_context["text"]


# ---------------------------------------------------------------------------
# model_deriver._enrich_behaviour_names_llm — flat wave
# ---------------------------------------------------------------------------

class TestEnrichBehaviourNamesLlmConcurrency:
    def test_max_concurrency_n_bounds_overlap_and_writes_are_correct(self, tmp_path, monkeypatch):
        _write_source(tmp_path)
        monkeypatch.setattr(md, "_static_behaviour_name_is_poor", lambda f: True)

        import llm_enrichment as _le
        monkeypatch.setattr(_le, "llm_provider_reachable", lambda config: True)

        lock = threading.Lock()
        state = {"current": 0, "high_water": 0}

        def fake_get_behaviour_names(source, params, globals_read, globals_written,
                                      return_type, return_expr, draft_input, draft_output,
                                      config, abbreviations):
            with lock:
                state["current"] += 1
                state["high_water"] = max(state["high_water"], state["current"])
            time.sleep(0.03)
            with lock:
                state["current"] -= 1
            return {"behaviourInputName": f"in-{return_expr}", "behaviourOutputName": f"out-{return_expr}"}

        monkeypatch.setattr(_le, "get_behaviour_names", fake_get_behaviour_names)

        functions_data = {
            f"f{i}_id": {
                "qualifiedName": f"f{i}", "returnExpr": f"f{i}",
                "location": _loc("foo.cpp", 1, 3),
                "parameters": [], "behaviourInputName": "", "behaviourOutputName": "",
            }
            for i in range(10)
        }
        config = _cfg(max_concurrency=4)
        md._enrich_behaviour_names_llm(str(tmp_path), functions_data, {}, config)

        for i in range(10):
            f = functions_data[f"f{i}_id"]
            assert f["behaviourInputName"] == f"in-f{i}"
            assert f["behaviourOutputName"] == f"out-f{i}"
        assert 2 <= state["high_water"] <= 4


# ---------------------------------------------------------------------------
# _get_client — CC-2 concurrent call sites must never construct two LlmClient
# instances for the same resolved config (each instance owns its own
# semaphore/rate limiter, so a race here would silently multiply the
# configured concurrency/rate cap instead of enforcing one shared limit).
# ---------------------------------------------------------------------------

class TestGetClientSingleton:
    def test_concurrent_first_calls_build_exactly_one_client(self, monkeypatch):
        monkeypatch.setattr(le, "_CLIENT_CACHE", {})

        build_count = {"n": 0}
        lock = threading.Lock()

        class _FakeClient:
            def __init__(self, **kwargs):
                with lock:
                    build_count["n"] += 1
                time.sleep(0.03)  # widen the race window

        monkeypatch.setattr(le, "LlmClient", _FakeClient)
        monkeypatch.setattr(le, "load_llm_config", lambda config: {
            "provider": "openai", "baseUrl": "http://host", "defaultModel": "m",
            "timeoutSeconds": 5, "numCtx": 2048, "retries": 0,
        })

        results = []
        threads = [threading.Thread(target=lambda: results.append(le._get_client({})))
                   for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert build_count["n"] == 1
        assert len({id(r) for r in results}) == 1
