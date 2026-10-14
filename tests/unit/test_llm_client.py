"""Unit tests for src/llm_core/client.py (LlmClient).

Network calls are mocked via requests.post / requests.get so no running
server is needed.
"""
import os
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from llm_core.client import LlmClient, from_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ollama_client(**kwargs) -> LlmClient:
    defaults = dict(provider="ollama", base_url="http://localhost:11434",
                    model="test-model", num_ctx=2048, timeout=5)
    defaults.update(kwargs)
    return LlmClient(**defaults)


def _mock_ollama_response(text: str, status_code: int = 200):
    r = MagicMock()
    r.status_code = status_code
    r.raise_for_status = MagicMock()
    r.json.return_value = {"response": text, "prompt_eval_count": 0, "eval_count": 0}
    return r


def _mock_openai_response(text: str):
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json.return_value = {
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0},
    }
    return r


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

class TestConstructor:
    def test_requires_url_or_base_url(self):
        with pytest.raises(ValueError, match="url"):
            LlmClient(provider="ollama", model="m")

    def test_invalid_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            LlmClient(provider="badprovider", base_url="http://localhost", model="m")

    def test_ollama_endpoint_built_from_base_url(self):
        client = _ollama_client()
        assert client._endpoint.endswith("/api/generate")

    def test_openai_endpoint_built_from_base_url(self):
        client = LlmClient(provider="openai", base_url="http://host", model="m",
                           timeout=5, num_ctx=2048)
        assert client._endpoint.endswith("/chat/completions")

    def test_legacy_url_used_verbatim(self):
        client = LlmClient(url="http://host:11434/api/generate", model="m")
        assert client._endpoint == "http://host:11434/api/generate"

    def test_legacy_use_openai_format(self):
        client = LlmClient(url="http://host/v1/chat/completions",
                           model="m", use_openai_format=True)
        assert client.provider == "openai"

    def test_properties(self):
        client = _ollama_client(model="my-model", num_ctx=4096)
        assert client.provider == "ollama"
        assert client.model == "my-model"
        assert client.num_ctx == 4096


# ---------------------------------------------------------------------------
# generate() — Ollama
# ---------------------------------------------------------------------------

class TestGenerateOllama:
    def test_returns_response_text(self):
        client = _ollama_client()
        with patch("llm_core.client.requests.post",
                   return_value=_mock_ollama_response("hello")):
            result = client.generate("sys", "user")
        assert result == "hello"

    def test_strips_whitespace(self):
        client = _ollama_client()
        with patch("llm_core.client.requests.post",
                   return_value=_mock_ollama_response("  trimmed  \n")):
            result = client.generate("sys", "user")
        assert result == "trimmed"

    def test_returns_none_on_empty_after_retries(self):
        client = _ollama_client()
        with patch("llm_core.client.requests.post",
                   return_value=_mock_ollama_response("")):
            result = client.generate("sys", "user")
        assert result is None

    def test_retries_on_empty_response(self):
        client = LlmClient(provider="ollama", base_url="http://localhost:11434",
                           model="m", timeout=5, num_ctx=2048, max_retries=1)
        empty = _mock_ollama_response("")
        good = _mock_ollama_response("second")
        with patch("llm_core.client.requests.post", side_effect=[empty, good]):
            result = client.generate("sys", "user")
        assert result == "second"

    def test_retries_on_connection_error(self):
        import requests as req
        client = LlmClient(provider="ollama", base_url="http://localhost:11434",
                           model="m", timeout=5, num_ctx=2048, max_retries=1)
        good = _mock_ollama_response("recovered")
        with patch("llm_core.client.requests.post",
                   side_effect=[req.ConnectionError(), good]):
            result = client.generate("sys", "user")
        assert result == "recovered"

    def test_returns_none_after_persistent_failure(self):
        import requests as req
        client = _ollama_client()
        with patch("llm_core.client.requests.post",
                   side_effect=req.ConnectionError()):
            result = client.generate("sys", "user")
        assert result is None

    def test_uses_model_from_config(self):
        client = _ollama_client(model="specific-model")
        with patch("llm_core.client.requests.post",
                   return_value=_mock_ollama_response("ok")) as mock_post:
            client.generate("sys", "user")
        payload = mock_post.call_args[1]["json"]
        assert payload["model"] == "specific-model"

    def test_uses_num_ctx_from_config(self):
        client = _ollama_client(num_ctx=4096)
        with patch("llm_core.client.requests.post",
                   return_value=_mock_ollama_response("ok")) as mock_post:
            client.generate("sys", "user")
        payload = mock_post.call_args[1]["json"]
        assert payload["options"]["num_ctx"] == 4096


# ---------------------------------------------------------------------------
# generate() — OpenAI
# ---------------------------------------------------------------------------

class TestGenerateOpenAI:
    def _client(self):
        return LlmClient(provider="openai", base_url="http://host",
                         model="gpt-4", timeout=5, num_ctx=2048)

    def test_returns_response_text(self):
        with patch("llm_core.client.requests.post",
                   return_value=_mock_openai_response("answer")), \
             patch("llm_core.client.time.sleep"):
            result = self._client().generate("sys", "user")
        assert result == "answer"

    def test_returns_none_on_empty(self):
        with patch("llm_core.client.requests.post",
                   return_value=_mock_openai_response("")), \
             patch("llm_core.client.time.sleep"):
            result = self._client().generate("sys", "user")
        assert result is None

    def test_sends_system_and_user_messages(self):
        with patch("llm_core.client.requests.post",
                   return_value=_mock_openai_response("ok")) as mock_post, \
             patch("llm_core.client.time.sleep"):
            self._client().generate("system text", "user text")
        messages = mock_post.call_args[1]["json"]["messages"]
        roles = {m["role"] for m in messages}
        assert "system" in roles
        assert "user" in roles


# ---------------------------------------------------------------------------
# Gateway throttle (llmServer.rateLimitSeconds)
# ---------------------------------------------------------------------------

class TestRateLimit:
    def _client(self, **kwargs):
        defaults = dict(provider="openai", base_url="http://host",
                        model="gpt-4", timeout=5, num_ctx=2048)
        defaults.update(kwargs)
        return LlmClient(**defaults)

    def test_defaults_to_three_seconds(self):
        with patch("llm_core.client.requests.post",
                   return_value=_mock_openai_response("ok")), \
             patch("llm_core.client.time.sleep") as mock_sleep:
            self._client().generate("sys", "user")
        mock_sleep.assert_called_once_with(3.0)

    def test_honours_configured_value(self):
        with patch("llm_core.client.requests.post",
                   return_value=_mock_openai_response("ok")), \
             patch("llm_core.client.time.sleep") as mock_sleep:
            self._client(rate_limit_seconds=0.5).generate("sys", "user")
        mock_sleep.assert_called_once_with(0.5)

    def test_zero_never_sleeps(self):
        with patch("llm_core.client.requests.post",
                   return_value=_mock_openai_response("ok")), \
             patch("llm_core.client.time.sleep") as mock_sleep:
            self._client(rate_limit_seconds=0).generate("sys", "user")
        mock_sleep.assert_not_called()

    def test_sleeps_even_when_the_call_fails(self):
        """The pause is in a finally block — a retry storm must not burst the
        gateway just because every request errored."""
        import requests as _requests
        with patch("llm_core.client.requests.post",
                   side_effect=_requests.ConnectionError("boom")), \
             patch("llm_core.client.time.sleep") as mock_sleep:
            result = self._client(max_retries=1).generate("sys", "user")
        assert result is None
        assert mock_sleep.call_count == 2          # 1 initial attempt + 1 retry
        assert all(c.args == (3.0,) for c in mock_sleep.call_args_list)

    def test_ollama_never_sleeps(self):
        with patch("llm_core.client.requests.post",
                   return_value=_mock_ollama_response("ok")), \
             patch("llm_core.client.time.sleep") as mock_sleep:
            _ollama_client().generate("sys", "user")
        mock_sleep.assert_not_called()

    def test_from_config_passes_the_value_through(self):
        client = from_config({
            "provider": "openai",
            "baseUrl": "http://host",
            "defaultModel": "gpt-4",
            "timeoutSeconds": 5,
            "numCtx": 2048,
            "retries": 1,
            "rateLimitSeconds": 1.5,
        })
        with patch("llm_core.client.requests.post",
                   return_value=_mock_openai_response("ok")), \
             patch("llm_core.client.time.sleep") as mock_sleep:
            client.generate("sys", "user")
        mock_sleep.assert_called_once_with(1.5)


# ---------------------------------------------------------------------------
# call() — multi-turn
# ---------------------------------------------------------------------------

class TestCall:
    def test_ollama_call_returns_text(self):
        client = _ollama_client()
        r = MagicMock()
        r.raise_for_status = MagicMock()
        r.json.return_value = {
            "message": {"content": "response"},
            "prompt_eval_count": 0, "eval_count": 0,
        }
        with patch("llm_core.client.requests.post", return_value=r):
            result = client.call([{"role": "user", "content": "hi"}])
        assert result == "response"

    def test_returns_none_on_empty(self):
        client = _ollama_client()
        r = MagicMock()
        r.raise_for_status = MagicMock()
        r.json.return_value = {"message": {"content": ""}, "prompt_eval_count": 0, "eval_count": 0}
        with patch("llm_core.client.requests.post", return_value=r):
            result = client.call([{"role": "user", "content": "hi"}])
        assert result is None


# ---------------------------------------------------------------------------
# from_config
# ---------------------------------------------------------------------------

class TestFromConfig:
    def _cfg(self, **overrides):
        base = {
            "provider": "ollama",
            "baseUrl": "http://localhost:11434",
            "defaultModel": "test-model",
            "timeoutSeconds": 5,
            "numCtx": 2048,
            "retries": 1,
            "customHeaders": {},
            "apiKey": "",
        }
        base.update(overrides)
        return base

    def test_builds_ollama_client(self):
        client = from_config(self._cfg())
        assert client.provider == "ollama"
        assert client.model == "test-model"

    def test_builds_openai_client(self):
        client = from_config(self._cfg(provider="openai"))
        assert client.provider == "openai"

    def test_model_set_correctly(self):
        client = from_config(self._cfg(defaultModel="my-model"))
        assert client.model == "my-model"

    def test_num_ctx_set_correctly(self):
        client = from_config(self._cfg(numCtx=4096))
        assert client.num_ctx == 4096


class TestConfigurableRateLimit:
    """doc 09 B6 — the pause after each OpenAI call must be configurable.

    The two on-prem deployments need opposite values: the API **gateway** enforces a global
    ~1-call-per-3s limit, while an on-prem **hosted model** has none — and at 3s a 20k-call
    run would spend ~17 hours asleep for no reason. Default stays 3.0 so anyone who does not
    set it remains gateway-safe.
    """

    def test_default_is_the_gateway_safe_value(self):
        from llm_core.client import LlmClient, _OPENAI_RATE_LIMIT_SEC
        c = LlmClient(provider="openai", base_url="http://x", model="m")
        assert c._rate_limit == _OPENAI_RATE_LIMIT_SEC == 3.0

    def test_zero_disables_the_pause(self):
        from llm_core.client import LlmClient
        c = LlmClient(provider="openai", base_url="http://x", model="m",
                      rate_limit_seconds=0)
        assert c._rate_limit == 0

    def test_negative_is_clamped_not_crashing(self):
        from llm_core.client import LlmClient
        c = LlmClient(provider="openai", base_url="http://x", model="m",
                      rate_limit_seconds=-5)
        assert c._rate_limit == 0

    def test_from_config_threads_the_value(self):
        from llm_core.client import from_config
        c = from_config({"provider": "openai", "baseUrl": "http://x",
                         "defaultModel": "m", "rateLimitSeconds": 0})
        assert c._rate_limit == 0

    def test_config_validation_accepts_zero_and_rejects_nonsense(self):
        from core.config import load_llm_config, LlmConfigError
        base = {"llmServer": {"provider": "openai", "baseUrl": "http://x", "defaultModel": "m",
                              "timeoutSeconds": 60, "numCtx": 8192, "retries": 1}}
        import copy
        ok = copy.deepcopy(base); ok["llmServer"]["rateLimitSeconds"] = 0
        assert load_llm_config(ok)["rateLimitSeconds"] == 0.0
        # default when absent stays gateway-safe
        assert load_llm_config(copy.deepcopy(base))["rateLimitSeconds"] == 3.0
        for bad in ("soon", -1):
            cfg = copy.deepcopy(base); cfg["llmServer"]["rateLimitSeconds"] = bad
            with pytest.raises(LlmConfigError):
                load_llm_config(cfg)


# ---------------------------------------------------------------------------
# Anthropic -- the Claude Messages API (provider "anthropic")
# ---------------------------------------------------------------------------

def _mock_anthropic_response(text="", *, blocks=None, status=200):
    import requests
    r = MagicMock()
    r.status_code = status
    r.text = "overloaded" if status != 200 else ""
    r.headers = {}
    if status != 200:
        r.raise_for_status = MagicMock(side_effect=requests.HTTPError(response=r))
    else:
        r.raise_for_status = MagicMock()
    r.json.return_value = {
        "type": "message", "role": "assistant", "stop_reason": "end_turn",
        "content": blocks if blocks is not None else [{"type": "text", "text": text}],
        "usage": {"input_tokens": 12, "output_tokens": 3},
    }
    return r


class TestGenerateAnthropic:
    def _client(self, **kw):
        d = dict(provider="anthropic", base_url="https://api.anthropic.com",
                 model="claude-sonnet-5-5", api_key="sk-ant-test", timeout=5,
                 rate_limit_seconds=0)
        d.update(kw)
        return LlmClient(**d)

    @pytest.mark.parametrize("base, endpoint", [
        ("https://api.anthropic.com", "https://api.anthropic.com/v1/messages"),
        ("https://api.anthropic.com/", "https://api.anthropic.com/v1/messages"),
        ("https://proxy.test/v1", "https://proxy.test/v1/messages"),
        ("https://proxy.test/v1/messages", "https://proxy.test/v1/messages"),
    ])
    def test_the_endpoint_is_the_messages_api(self, base, endpoint):
        assert self._client(base_url=base)._endpoint == endpoint

    def test_sends_a_messages_api_request(self):
        with patch("llm_core.client.requests.post",
                   return_value=_mock_anthropic_response("answer")) as post:
            assert self._client().generate("system text", "user text") == "answer"
        args, kw = post.call_args
        assert args[0] == "https://api.anthropic.com/v1/messages"
        h = kw["headers"]
        assert h["x-api-key"] == "sk-ant-test" and h["anthropic-version"] == "2023-06-01"
        assert "Authorization" not in h and "x-dep-ticket" not in h, "none of the gateway's defaults"
        body = kw["json"]
        assert body["system"] == "system text", "the system prompt is its own field"
        assert body["messages"] == [{"role": "user", "content": "user text"}]
        assert (body["model"], body["max_tokens"], body["temperature"]) == ("claude-sonnet-5-5", 2048, 0.1)

    def test_no_system_prompt_sends_no_system_field(self):
        with patch("llm_core.client.requests.post",
                   return_value=_mock_anthropic_response("ok")) as post:
            self._client().generate("", "user text")
        assert "system" not in post.call_args[1]["json"]

    def test_the_text_blocks_are_the_answer(self):
        blocks = [{"type": "thinking", "thinking": "..."},
                  {"type": "text", "text": "Part one. "}, {"type": "text", "text": "Part two."}]
        with patch("llm_core.client.requests.post",
                   return_value=_mock_anthropic_response(blocks=blocks)):
            assert self._client().generate("s", "u") == "Part one. Part two."

    def test_an_empty_answer_is_retried_then_none(self):
        with patch("llm_core.client.requests.post",
                   return_value=_mock_anthropic_response("")) as post:
            assert self._client(max_retries=1).generate("s", "u") is None
        assert post.call_count == 2

    def test_overloaded_is_retried_and_then_answered(self):
        replies = [_mock_anthropic_response(status=529), _mock_anthropic_response("late")]
        with patch("llm_core.client.requests.post", side_effect=replies) as post:
            assert self._client(max_retries=1).generate("s", "u") == "late"
        assert post.call_count == 2

    def test_call_puts_the_system_messages_in_the_system_field(self):
        msgs = [{"role": "system", "content": "S1"}, {"role": "user", "content": "U1"},
                {"role": "assistant", "content": "A1"}, {"role": "user", "content": "U2"}]
        with patch("llm_core.client.requests.post",
                   return_value=_mock_anthropic_response("ok")) as post:
            assert self._client().call(msgs, temperature=0.7) == "ok"
        body = post.call_args[1]["json"]
        assert body["system"] == "S1" and body["temperature"] == 0.7
        assert [m["role"] for m in body["messages"]] == ["user", "assistant", "user"]

    def test_custom_headers_are_sent_as_they_are(self):
        with patch("llm_core.client.requests.post",
                   return_value=_mock_anthropic_response("ok")) as post:
            self._client(custom_headers={"x-proxy-ticket": "T"}).generate("s", "u")
        assert post.call_args[1]["headers"]["x-proxy-ticket"] == "T"

    def test_it_pauses_after_each_call_as_the_gateway_path_does(self):
        with patch("llm_core.client.requests.post",
                   return_value=_mock_anthropic_response("ok")), \
             patch("llm_core.client.time.sleep") as sleep:
            self._client(rate_limit_seconds=2).generate("s", "u")
        sleep.assert_called_with(2.0)

    def test_tokens_are_counted_from_usage(self):
        m = {"prompt": 0, "completion": 0}
        assert LlmClient._anthropic_read(
            {"content": [{"type": "text", "text": "x"}], "usage": {"input_tokens": 7, "output_tokens": 2}},
            m) == "x"
        assert (m["prompt"], m["completion"], m["outcome"]) == (7, 2, "ok")

    def test_lanes_send_each_key_as_x_api_key(self):
        """`speedups.llms` with Claude keys: each lane's key is sent as x-api-key."""
        from llm_core.pool import BUSY_STATUSES
        assert 529 in BUSY_STATUSES, "the API's overloaded answer cools a lane, as a 429 does"
        # a pause between calls on one key, so the next call takes the other (with none, the
        # first key is free again at once and takes every call -- the pool's own rule)
        c = self._client(api_key=None, lanes=[{"name": "a", "apiKey": "K-ANT-1"},
                                              {"name": "b", "apiKey": "K-ANT-2"}],
                         base_url="https://lanes.anthropic.test", rate_limit_seconds=0.05)
        assert c._pool is not None and all(l.endpoint == "https://lanes.anthropic.test/v1/messages"
                                           for l in c._pool.lanes)
        with patch("llm_core.client.requests.post",
                   return_value=_mock_anthropic_response("ok")) as post:
            for _ in range(4):
                assert c.generate("s", "u") == "ok"
        keys = {kw["headers"]["x-api-key"] for _a, kw in post.call_args_list}
        assert keys == {"K-ANT-1", "K-ANT-2"}


class TestAnthropicConfig:
    CFG = {"llmServer": {"provider": "anthropic", "baseUrl": "https://api.anthropic.com",
                         "defaultModel": "claude-sonnet-5-5"}}

    def _cfg(self, **server):
        import copy
        cfg = copy.deepcopy(self.CFG)
        cfg["llmServer"].update(server)
        return cfg

    def test_the_key_comes_from_config_local_json_only(self, monkeypatch):
        """No environment variable is read for a Claude key: a gateway key set in LLM_API_KEY
        (or LLM_API_KEYS) must never be sent to Anthropic."""
        from core.config import env_api_keys, llm_calls_at_once, load_llm_config
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env")
        monkeypatch.setenv("LLM_API_KEY", "gateway-key")
        monkeypatch.setenv("LLM_API_KEYS", "gw-1,gw-2")
        assert load_llm_config(self._cfg())["apiKey"] is None
        assert load_llm_config(self._cfg(apiKey="sk-file"))["apiKey"] == "sk-file"
        assert env_api_keys("anthropic") == [] and env_api_keys("openai") == ["gw-1", "gw-2"]
        assert llm_calls_at_once({}, "anthropic") == 1, "the env keys make no lanes for Claude"
        c = from_config(load_llm_config(self._cfg(apiKey="sk-file")))
        assert c._pool is None and c._api_key == "sk-file"
        # the other providers keep develop's rule: the environment wins
        gw = {"llmServer": {"provider": "openai", "baseUrl": "http://gw", "defaultModel": "m",
                            "apiKey": "file-key"}}
        assert load_llm_config(gw)["apiKey"] == "gateway-key"

    def test_from_config_builds_the_claude_client(self, monkeypatch):
        from core.config import load_llm_config
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        c = from_config(load_llm_config(self._cfg(apiKey="sk-file")))
        assert (c.provider, c._endpoint, c._api_key) == (
            "anthropic", "https://api.anthropic.com/v1/messages", "sk-file")

    def test_a_provider_it_does_not_know_is_refused(self):
        from core.config import LlmConfigError, load_llm_config
        with pytest.raises(LlmConfigError, match="'ollama', 'openai' or 'anthropic'"):
            load_llm_config(self._cfg(provider="claude"))

    def test_the_prompt_budget_is_the_gateway_s(self):
        from llm_core.budget import resolve_max_tokens
        assert resolve_max_tokens({"provider": "anthropic", "numCtx": 8192,
                                   "maxContextTokens": None}) == 127488
        assert resolve_max_tokens({"provider": "anthropic", "numCtx": 8192,
                                   "maxContextTokens": 190000}) == 190000

    def test_the_banner_says_what_it_ignores(self):
        from core.config import format_llm_config_banner, load_llm_config
        banner = format_llm_config_banner(load_llm_config(self._cfg()))
        assert "ignored on anthropic" in banner and "(ignored on ollama)" not in banner

    def test_a_hosted_api_is_not_pinged(self, monkeypatch):
        import llm_enrichment
        monkeypatch.setattr(llm_enrichment.requests, "get",
                            lambda *a, **kw: pytest.fail("no ping for a hosted API"))
        assert llm_enrichment.llm_provider_reachable(self._cfg()) is True


def test_a_failed_attempt_says_how_big_its_prompt_was(caplog):
    """A server that cannot take a prompt refuses it every time: the log says whether the
    failing calls are the big ones."""
    import logging
    import requests
    c = LlmClient(provider="openai", base_url="http://gw", model="m", timeout=5, max_retries=0,
                  rate_limit_seconds=0)
    with patch("llm_core.client.requests.post", side_effect=requests.ConnectionError("down")), \
         caplog.at_level(logging.WARNING, logger="llm_core.client"):
        assert c.generate("sys", "user prompt") is None
    assert any("prompt 14 chars" in r.getMessage() for r in caplog.records)
