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
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

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
