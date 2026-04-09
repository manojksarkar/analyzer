"""Cached, typed accessors for the analyzer configuration.

All values still live in `config/config.json` (and `config.local.json`) so the
user can change anything by editing the JSON file. This module:
  1. Parses JSONC (JSON with // and /* */ comments and trailing commas).
  2. Loads + merges config.json + config.local.json once per process.
  3. Resolves the LLM config block, applying environment-variable overrides.
  4. Provides typed helpers (llm_config, views_config, exporter_config,
     modules_groups) so call sites stop typing `cfg.get("llm", {}).get(...)`.
  5. Re-exports the raw dict via `app_config()` for code that still wants the
     dict-style access.

This module is the bottom of the dependency graph for configuration; nothing
in `core/` may import from analyzer-level modules (utils.py, etc.).
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict, Optional

from .paths import paths

_LOCK = threading.Lock()
_CACHED: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# JSONC parsing
# ---------------------------------------------------------------------------

def _strip_json_comments(text: str) -> str:
    """Strip // and /* */ so config files can use comments."""
    result = []
    i = 0
    in_string = False
    escape = False
    while i < len(text):
        c = text[i]
        if escape:
            result.append(c)
            escape = False
            i += 1
            continue
        if c == "\\" and in_string:
            escape = True
            result.append(c)
            i += 1
            continue
        if c == '"' and not escape:
            in_string = not in_string
            result.append(c)
            i += 1
            continue
        if in_string:
            result.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < len(text):
            if text[i + 1] == "/":
                i += 2
                while i < len(text) and text[i] != "\n":
                    i += 1
                continue
            if text[i + 1] == "*":
                i += 2
                while i + 1 < len(text) and (text[i] != "*" or text[i + 1] != "/"):
                    i += 1
                i += 2
                continue
        result.append(c)
        i += 1
    return "".join(result)


def _strip_trailing_commas(text: str) -> str:
    """Remove trailing commas before } or ] (JSON5-style), outside strings."""
    out = []
    i = 0
    in_string = False
    escape = False
    n = len(text)
    while i < n:
        c = text[i]
        if escape:
            out.append(c)
            escape = False
            i += 1
            continue
        if c == "\\" and in_string:
            escape = True
            out.append(c)
            i += 1
            continue
        if c == '"':
            in_string = not in_string
            out.append(c)
            i += 1
            continue
        if not in_string and c == ",":
            j = i + 1
            while j < n and text[j] in (" ", "\t", "\r", "\n"):
                j += 1
            if j < n and text[j] in ("}", "]"):
                i += 1
                continue
        out.append(c)
        i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# load_config / load_llm_config (formerly in utils.py)
# ---------------------------------------------------------------------------

def load_config(project_root: str) -> Dict[str, Any]:
    """Load config from config/config.json, then config.local.json overrides."""
    config: Dict[str, Any] = {}
    config_dir = os.path.join(project_root, "config")
    for name in ("config.json", "config.local.json"):
        path = os.path.join(config_dir, name)
        if not os.path.isfile(path):
            path = os.path.join(project_root, name)
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = f.read()
                    stripped = _strip_json_comments(raw)
                    stripped = _strip_trailing_commas(stripped)
                    config.update(json.loads(stripped))
            except (json.JSONDecodeError, IOError):
                pass
    return config


def load_llm_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve the llm config block, applying environment-variable overrides.

    Returns a normalised dict with these keys:
        provider          - "ollama" | "openai"
        baseUrl           - endpoint base URL (no trailing slash)
        defaultModel      - model name string
        timeoutSeconds    - int
        numCtx            - int (Ollama context window)
        retries           - int (default 1)
        descriptions      - bool (whether to call LLM for descriptions)
        behaviourNames    - bool (whether to call LLM for behaviour names)
        abbreviationsPath - str
        customHeaders     - dict (passed through to OpenAI gateway)
        apiKey            - str | None (resolved from LLM_API_KEY env var first)

    Environment variables (override the matching config field if set):
        LLM_PROVIDER, LLM_BASE_URL, LLM_DEFAULT_MODEL,
        LLM_TIMEOUT_SECONDS, LLM_NUM_CTX, LLM_RETRIES, LLM_API_KEY
    """
    llm = (config or {}).get("llm") or {}

    def _env_or(key: str, default):
        v = os.environ.get(key)
        return v if v is not None and v != "" else default

    provider = _env_or("LLM_PROVIDER", llm.get("provider") or "ollama")
    base_url = _env_or("LLM_BASE_URL", llm.get("baseUrl") or "http://localhost:11434")
    model = _env_or("LLM_DEFAULT_MODEL", llm.get("defaultModel") or "qwen2.5-coder:14b")
    try:
        timeout = int(_env_or("LLM_TIMEOUT_SECONDS", llm.get("timeoutSeconds", 120)))
    except (TypeError, ValueError):
        timeout = 120
    try:
        num_ctx = int(_env_or("LLM_NUM_CTX", llm.get("numCtx", 8192)))
    except (TypeError, ValueError):
        num_ctx = 8192
    try:
        retries = int(_env_or("LLM_RETRIES", llm.get("retries", 1)))
    except (TypeError, ValueError):
        retries = 1
    api_key = _env_or("LLM_API_KEY", llm.get("apiKey"))
    return {
        "provider": str(provider).lower(),
        "baseUrl": str(base_url).rstrip("/"),
        "defaultModel": str(model),
        "timeoutSeconds": timeout,
        "numCtx": num_ctx,
        "retries": retries,
        "descriptions": bool(llm.get("descriptions", True)),
        "behaviourNames": bool(llm.get("behaviourNames", True)),
        "abbreviationsPath": str(llm.get("abbreviationsPath", "") or ""),
        "customHeaders": dict(llm.get("customHeaders") or {}),
        "apiKey": str(api_key) if api_key else None,
    }


# ---------------------------------------------------------------------------
# Cached, typed accessors
# ---------------------------------------------------------------------------

def app_config(*, refresh: bool = False) -> Dict[str, Any]:
    """Return the merged config dict (config.json + config.local.json).

    Cached process-wide. Pass refresh=True to force a re-read after edits.
    """
    global _CACHED
    if _CACHED is not None and not refresh:
        return _CACHED
    with _LOCK:
        if _CACHED is None or refresh:
            _CACHED = load_config(paths().project_root)
        return _CACHED


def llm_config() -> Dict[str, Any]:
    """Return the resolved LLM config block (env vars override JSON values).

    See `load_llm_config` for the schema.
    """
    return load_llm_config(app_config())


def views_config() -> Dict[str, Any]:
    """Return the `views` block from config.json (or {} if absent)."""
    return app_config().get("views") or {}


def exporter_config() -> Dict[str, Any]:
    """Return the `export` block from config.json (or {} if absent)."""
    return app_config().get("export") or {}


def clang_config() -> Dict[str, Any]:
    """Return the `clang` block from config.json (or {} if absent)."""
    return app_config().get("clang") or {}


def modules_groups() -> Dict[str, Any]:
    """Return the `modulesGroups` block (or {} if absent)."""
    return app_config().get("modulesGroups") or {}
