"""Unified LLM HTTP client.

Supports two providers:
  - "ollama"  : POST {baseUrl}/api/generate  (local Ollama)
  - "openai"  : POST {baseUrl}/chat/completions  (OpenAI-compatible gateway)

Selected via config['llm']['provider'] or the explicit `provider=` ctor arg.
Both providers go through the same `generate(system, user)` interface and the
same response post-processing (strip_think_section + token tracking).

Hard rules baked in:
  - OpenAI requests are serialised process-wide (1 in flight at a time) and
    every successful OpenAI call is followed by a 3-second sleep, because the
    corporate gateway throttles ~1 request per 3 seconds.
  - Configurable retry. Default = 1 retry on (HTTP error | empty response).
  - All responses pass through strip_think_section() before being returned.
  - Token usage from both providers is recorded into llm.tokens.

Backwards compat
----------------
The legacy positional/keyword constructor used by flowchart_engine.py and
project_scanner.py still works:

    LlmClient(url=..., model=..., timeout=..., temperature=..., num_ctx=...,
              use_openai_format=True/False)

In that mode the client treats the explicit `url` as the full endpoint URL
(no /chat/completions appended) and provider is inferred from
use_openai_format.
"""

import logging
import os
import sys
import threading
import time
from typing import Dict, Optional

import requests

from .headers import build_openai_headers, resolve_api_key
from .think import strip_think_section
from . import tokens as token_counter

logger = logging.getLogger(__name__)


_TRACE_COUNTER = 0


def _trace_enabled() -> bool:
    return bool(os.environ.get("LLM_TRACE_PROMPTS") or os.environ.get("FLOWCHART_TRACE"))


def _safe_write(body: str) -> None:
    """Write to stdout tolerating consoles that can't encode all characters.

    Windows cp1252 can't encode e.g. Korean source comments that appear in
    traced prompts/responses; fall back to an encode→decode(replace) round-trip
    so tracing never aborts the run.
    """
    try:
        sys.stdout.write(body)
        sys.stdout.flush()
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        sys.stdout.write(body.encode(encoding, errors="replace").decode(encoding, errors="replace"))
        sys.stdout.flush()


def _trace_request(provider: str, model: str, system_prompt: str, user_prompt: str) -> int:
    """Print the outgoing system + user prompts. Returns the call ordinal."""
    global _TRACE_COUNTER
    _TRACE_COUNTER += 1
    ordinal = _TRACE_COUNTER
    body = (
        "\n" + "=" * 72 + "\n"
        f"[LLM-TRACE #{ordinal}] REQUEST  provider={provider} model={model}\n"
        + "-" * 72 + "\n"
        f"[SYSTEM PROMPT]\n{system_prompt}\n\n"
        f"[USER PROMPT]\n{user_prompt}\n"
        + "=" * 72 + "\n"
    )
    _safe_write(body)
    return ordinal


def _trace_messages(provider: str, model: str, messages: list) -> int:
    """Print the outgoing multi-message conversation."""
    global _TRACE_COUNTER
    _TRACE_COUNTER += 1
    ordinal = _TRACE_COUNTER
    parts = [
        "\n" + "=" * 72 + "\n",
        f"[LLM-TRACE #{ordinal}] REQUEST  provider={provider} model={model} (multi-turn)\n",
        "-" * 72 + "\n",
    ]
    for m in messages:
        role = m.get("role", "?")
        content = m.get("content", "")
        parts.append(f"[{role.upper()}]\n{content}\n\n")
    parts.append("=" * 72 + "\n")
    _safe_write("".join(parts))
    return ordinal


def _trace_response(ordinal: int, response: Optional[str]) -> None:
    """Print the response that came back for a previously-traced request."""
    body = (
        "-" * 72 + "\n"
        f"[LLM-TRACE #{ordinal}] RESPONSE\n"
        + "-" * 72 + "\n"
        f"{response if response is not None else '<empty/None>'}\n"
        + "=" * 72 + "\n\n"
    )
    _safe_write(body)


# Process-wide serialisation for OpenAI calls. Class-level so every instance
# of LlmClient with provider="openai" shares it — even if multiple clients
# are constructed by different phases.
_OPENAI_LOCK = threading.Lock()
_OPENAI_RATE_LIMIT_SEC = 3.0


class LlmClient:
    """One client, two providers, one interface."""

    def __init__(
        self,
        # New-style preferred args
        provider: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        *,
        api_key: Optional[str] = None,
        custom_headers: Optional[Dict[str, str]] = None,
        timeout: int = 120,
        temperature: float = 0.1,
        num_ctx: int = 8192,
        max_retries: int = 1,
        # Legacy-compat args
        url: Optional[str] = None,
        use_openai_format: bool = False,
    ) -> None:
        # Resolve provider: explicit > legacy use_openai_format > default ollama
        if provider is None:
            provider = "openai" if use_openai_format else "ollama"
        provider = provider.lower()
        if provider not in ("ollama", "openai"):
            raise ValueError(f"Unknown LLM provider: {provider!r}")
        self._provider = provider
        self._model = model or ""
        self._timeout = int(timeout)
        self._temperature = float(temperature)
        self._num_ctx = int(num_ctx)
        self._max_retries = max(0, int(max_retries))
        self._api_key = api_key
        self._custom_headers = dict(custom_headers or {})

        # Endpoint resolution.
        # Legacy callers pass `url=` already pointing at the full endpoint
        # (e.g. http://host:11434/api/generate). New callers pass `base_url=`
        # and we append the provider-specific path.
        if url:
            self._endpoint = url.rstrip("/")
        elif base_url:
            base = base_url.rstrip("/")
            if provider == "openai":
                self._endpoint = f"{base}/chat/completions"
            else:
                self._endpoint = f"{base}/api/generate"
        else:
            raise ValueError("LlmClient: either url= or base_url= is required")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    @property
    def num_ctx(self) -> int:
        """Ollama context-window size this client was configured with.

        Still populated for OpenAI (from config) but not sent to the gateway —
        use `maxContextTokens` for budget math on OpenAI.
        """
        return self._num_ctx

    def generate(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """Call the LLM and return the (think-stripped) response text.

        Returns None on persistent failure (after retries) or empty response.
        """
        trace_ord = _trace_request(self._provider, self._model, system_prompt, user_prompt) \
            if _trace_enabled() else 0
        last_exc: Optional[BaseException] = None
        # max_retries=1 means: 1 initial attempt + 1 retry = 2 total tries.
        total_attempts = self._max_retries + 1
        for attempt in range(1, total_attempts + 1):
            try:
                if self._provider == "openai":
                    raw = self._call_openai(system_prompt, user_prompt)
                else:
                    raw = self._call_ollama(system_prompt, user_prompt)
                if raw:
                    cleaned = strip_think_section(raw)
                    if cleaned:
                        if trace_ord:
                            _trace_response(trace_ord, cleaned)
                        return cleaned
                # Empty response: log and (maybe) retry
                if attempt < total_attempts:
                    logger.warning(
                        "LLM (%s/%s) returned empty response on attempt %d/%d — retrying",
                        self._provider, self._model, attempt, total_attempts,
                    )
                    continue
                logger.warning(
                    "LLM (%s/%s) returned empty response after %d attempt(s)",
                    self._provider, self._model, total_attempts,
                )
                if trace_ord:
                    _trace_response(trace_ord, "")
                return None
            except requests.Timeout as exc:
                last_exc = exc
                logger.warning(
                    "LLM (%s/%s) timed out after %ds (attempt %d/%d)",
                    self._provider, self._model, self._timeout, attempt, total_attempts,
                )
            except requests.ConnectionError as exc:
                last_exc = exc
                logger.warning(
                    "LLM (%s/%s) connection error: %s (attempt %d/%d)",
                    self._provider, self._model, exc, attempt, total_attempts,
                )
            except requests.HTTPError as exc:
                last_exc = exc
                status = getattr(exc.response, "status_code", "?")
                body = getattr(exc.response, "text", "") or ""
                logger.warning(
                    "LLM (%s/%s) HTTP %s: %s (attempt %d/%d)",
                    self._provider, self._model, status, body[:200], attempt, total_attempts,
                )
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning(
                    "LLM (%s/%s) unexpected error: %s (attempt %d/%d)",
                    self._provider, self._model, exc, attempt, total_attempts,
                )
            # Fall through to next attempt
        if last_exc is not None:
            logger.error(
                "LLM (%s/%s) failed after %d attempt(s): %s",
                self._provider, self._model, total_attempts, last_exc,
            )
        if trace_ord:
            _trace_response(trace_ord, f"<failed: {last_exc}>" if last_exc else "<empty>")
        return None

    def call(self, messages: list, *, temperature: Optional[float] = None) -> Optional[str]:
        """Send a multi-message conversation to the LLM.

        This is the lower-level interface that ``generate()`` delegates to.
        Use it when you need multi-turn conversations (e.g. self-review:
        generate → review → revise) or per-call temperature overrides
        (e.g. ensemble at different temperatures).

        Parameters
        ----------
        messages : list[dict]
            OpenAI chat-format messages: ``[{"role": "system", "content": "..."},
            {"role": "user", "content": "..."}, ...]``.
        temperature : float, optional
            Override the instance default temperature for this call only.

        Returns
        -------
        str or None
            The (think-stripped) response text, or None on persistent failure.
        """
        temp = temperature if temperature is not None else self._temperature
        trace_ord = _trace_messages(self._provider, self._model, messages) \
            if _trace_enabled() else 0
        last_exc: Optional[BaseException] = None
        total_attempts = self._max_retries + 1
        for attempt in range(1, total_attempts + 1):
            try:
                if self._provider == "openai":
                    raw = self._call_openai_messages(messages, temp)
                else:
                    raw = self._call_ollama_messages(messages, temp)
                if raw:
                    cleaned = strip_think_section(raw)
                    if cleaned:
                        if trace_ord:
                            _trace_response(trace_ord, cleaned)
                        return cleaned
                if attempt < total_attempts:
                    logger.warning(
                        "LLM (%s/%s) call() empty response on attempt %d/%d — retrying",
                        self._provider, self._model, attempt, total_attempts,
                    )
                    continue
                logger.warning(
                    "LLM (%s/%s) call() empty response after %d attempt(s)",
                    self._provider, self._model, total_attempts,
                )
                if trace_ord:
                    _trace_response(trace_ord, "")
                return None
            except requests.Timeout as exc:
                last_exc = exc
                logger.warning(
                    "LLM (%s/%s) call() timed out (attempt %d/%d)",
                    self._provider, self._model, attempt, total_attempts,
                )
            except requests.ConnectionError as exc:
                last_exc = exc
                logger.warning(
                    "LLM (%s/%s) call() connection error: %s (attempt %d/%d)",
                    self._provider, self._model, exc, attempt, total_attempts,
                )
            except requests.HTTPError as exc:
                last_exc = exc
                status = getattr(exc.response, "status_code", "?")
                body = getattr(exc.response, "text", "") or ""
                logger.warning(
                    "LLM (%s/%s) call() HTTP %s: %s (attempt %d/%d)",
                    self._provider, self._model, status, body[:200], attempt, total_attempts,
                )
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning(
                    "LLM (%s/%s) call() unexpected error: %s (attempt %d/%d)",
                    self._provider, self._model, exc, attempt, total_attempts,
                )
        if last_exc is not None:
            logger.error(
                "LLM (%s/%s) call() failed after %d attempt(s): %s",
                self._provider, self._model, total_attempts, last_exc,
            )
        if trace_ord:
            _trace_response(trace_ord, f"<failed: {last_exc}>" if last_exc else "<empty>")
        return None

    # ------------------------------------------------------------------
    # Ollama
    # ------------------------------------------------------------------

    def _call_ollama(self, system: str, user: str) -> Optional[str]:
        payload = {
            "model": self._model,
            "system": system or "",
            "prompt": user,
            "stream": False,
            "options": {
                # num_ctx must be set explicitly — Ollama defaults to 2048
                # which silently truncates our prompts and returns empty.
                "num_ctx": self._num_ctx,
                "temperature": self._temperature,
                "top_p": 0.9,
                "num_predict": 2048,
            },
        }
        resp = requests.post(self._endpoint, json=payload, timeout=self._timeout)
        resp.raise_for_status()
        data = resp.json()
        text = (data.get("response") or "").strip()
        # Token tracking
        prompt_tokens = int(data.get("prompt_eval_count") or 0)
        completion_tokens = int(data.get("eval_count") or 0)
        token_counter.record("ollama", self._model, prompt_tokens, completion_tokens)
        if not text:
            err = data.get("error") or ""
            if err:
                logger.warning("Ollama error body: %s", err)
        return text or None

    def _call_ollama_messages(self, messages: list, temperature: float) -> Optional[str]:
        """POST to Ollama /api/chat with a pre-formed messages list."""
        # Derive the /api/chat endpoint from the stored endpoint.
        # _endpoint is either the legacy url= or {base}/api/generate.
        chat_endpoint = self._endpoint.replace("/api/generate", "/api/chat")
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {
                "num_ctx": self._num_ctx,
                "temperature": temperature,
                "top_p": 0.9,
                "num_predict": 2048,
            },
        }
        resp = requests.post(chat_endpoint, json=payload, timeout=self._timeout)
        resp.raise_for_status()
        data = resp.json()
        # /api/chat returns {"message": {"role": "assistant", "content": "..."}}
        msg = data.get("message") or {}
        text = (msg.get("content") or "").strip()
        # Token tracking
        prompt_tokens = int(data.get("prompt_eval_count") or 0)
        completion_tokens = int(data.get("eval_count") or 0)
        token_counter.record("ollama", self._model, prompt_tokens, completion_tokens)
        if not text:
            err = data.get("error") or ""
            if err:
                logger.warning("Ollama chat error body: %s", err)
        return text or None

    # ------------------------------------------------------------------
    # OpenAI-compatible
    # ------------------------------------------------------------------

    def _call_openai(self, system: str, user: str) -> Optional[str]:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system or ""},
                {"role": "user", "content": user},
            ],
            "temperature": self._temperature,
            "max_tokens": 2048,
        }
        # Serialise across the whole process. Even if multiple threads call
        # generate() concurrently, only one OpenAI request is in flight at a
        # time, and we always sleep 3s after to satisfy the gateway throttle.
        with _OPENAI_LOCK:
            headers = build_openai_headers(
                api_key=self._api_key,
                config_headers=self._custom_headers,
            )
            try:
                resp = requests.post(
                    self._endpoint,
                    headers=headers,
                    json=payload,
                    timeout=self._timeout,
                )
                resp.raise_for_status()
                data = resp.json()
            finally:
                # Sleep on every attempt — including failures — so a tight
                # retry loop never bursts the gateway.
                time.sleep(_OPENAI_RATE_LIMIT_SEC)
        choices = data.get("choices") or []
        text = ""
        if choices:
            msg = choices[0].get("message") or {}
            text = (msg.get("content") or "").strip()
        # Token tracking
        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        token_counter.record("openai", self._model, prompt_tokens, completion_tokens)
        return text or None

    def _call_openai_messages(self, messages: list, temperature: float) -> Optional[str]:
        """POST to OpenAI endpoint with a pre-formed messages list."""
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 2048,
        }
        with _OPENAI_LOCK:
            headers = build_openai_headers(
                api_key=self._api_key,
                config_headers=self._custom_headers,
            )
            try:
                resp = requests.post(
                    self._endpoint,
                    headers=headers,
                    json=payload,
                    timeout=self._timeout,
                )
                resp.raise_for_status()
                data = resp.json()
            finally:
                time.sleep(_OPENAI_RATE_LIMIT_SEC)
        choices = data.get("choices") or []
        text = ""
        if choices:
            msg = choices[0].get("message") or {}
            text = (msg.get("content") or "").strip()
        # Token tracking
        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        token_counter.record("openai", self._model, prompt_tokens, completion_tokens)
        return text or None


# ---------------------------------------------------------------------------
# Convenience constructor: build an LlmClient from a config dict.
# ---------------------------------------------------------------------------

def from_config(llm_cfg: Dict) -> LlmClient:
    """Build an LlmClient from the resolved llm config block.

    See utils.load_llm_config() for the expected shape.
    """
    provider = (llm_cfg.get("provider") or "ollama").lower()
    base_url = (llm_cfg.get("baseUrl") or "http://localhost:11434").rstrip("/")
    model = llm_cfg.get("defaultModel") or "qwen2.5-coder:14b"
    timeout = int(llm_cfg.get("timeoutSeconds", 120))
    num_ctx = int(llm_cfg.get("numCtx", 8192))
    retries = int(llm_cfg.get("retries", 1))
    custom_headers = llm_cfg.get("customHeaders") or {}
    api_key = resolve_api_key(llm_cfg)
    return LlmClient(
        provider=provider,
        base_url=base_url,
        model=model,
        api_key=api_key,
        custom_headers=custom_headers,
        timeout=timeout,
        num_ctx=num_ctx,
        max_retries=retries,
    )
