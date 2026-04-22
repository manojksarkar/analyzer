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


class LlmConfigError(ValueError):
    """Raised when llm config has missing or invalid required fields.

    Strict validation: rather than falling back to silent defaults, the
    analyzer surfaces the exact field that is wrong so the user can fix
    config.json (or the matching env var) and re-run.
    """


def load_llm_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve and STRICTLY validate the llm config block.

    Required fields (no silent defaults — raises LlmConfigError if missing
    or invalid):
        provider          - "ollama" | "openai" | "anthropic"
        baseUrl           - non-empty endpoint base URL
        defaultModel      - non-empty model name
        timeoutSeconds    - positive int
        numCtx            - positive int (Ollama context window; informational
                            on OpenAI but still required for plumbing)
        retries           - int >= 0

    Optional fields (with documented defaults):
        descriptions      - bool, default True
        behaviourNames    - bool, default True
        abbreviationsPath - str, default ""
        customHeaders     - dict, default {}
        apiKey            - str | None (env LLM_API_KEY wins)
        maxContextTokens  - int | None (null → auto-derived from numCtx/provider)
        enrichment        - dict of feature toggles (each must be a bool):
            twoPassDescriptions (default True)
            selfReview          (default False)
            ensemble            (default False)
            cfgSimplification   (default False)
            variableEnrichment  (default True)
        cacheVersion      - int >= 1 (bump to invalidate entity cache)
        fewShotExamplesDir - str (default "few_shot_examples")

    Environment variables (override the matching config field if set):
        LLM_PROVIDER, LLM_BASE_URL, LLM_DEFAULT_MODEL,
        LLM_TIMEOUT_SECONDS, LLM_NUM_CTX, LLM_RETRIES, LLM_API_KEY

    Raises
    ------
    LlmConfigError
        If a required field is missing, empty, or not parseable.
    """
    if not config or not isinstance(config, dict):
        raise LlmConfigError("config.json is empty or not a JSON object")

    llm = config.get("llm")
    if not isinstance(llm, dict) or not llm:
        raise LlmConfigError("config.json has no 'llm' block")

    def _env_or(key: str, fallback):
        v = os.environ.get(key)
        return v if v is not None and v != "" else fallback

    def _require_str(field: str, env_var: str) -> str:
        raw = _env_or(env_var, llm.get(field))
        if raw is None or str(raw).strip() == "":
            raise LlmConfigError(
                f"Missing required llm.{field} (or env {env_var}) in config.json"
            )
        return str(raw).strip()

    def _require_pos_int(field: str, env_var: str) -> int:
        raw = _env_or(env_var, llm.get(field))
        if raw is None or raw == "":
            raise LlmConfigError(
                f"Missing required llm.{field} (or env {env_var}) in config.json"
            )
        try:
            val = int(raw)
        except (TypeError, ValueError):
            raise LlmConfigError(
                f"llm.{field} must be an integer (got {raw!r})"
            )
        if val <= 0:
            raise LlmConfigError(
                f"llm.{field} must be a positive integer (got {val})"
            )
        return val

    # ── Required fields ──
    provider = _require_str("provider", "LLM_PROVIDER").lower()
    if provider not in ("ollama", "openai", "anthropic"):
        raise LlmConfigError(
            f"llm.provider must be 'ollama', 'openai', or 'anthropic' (got {provider!r})"
        )

    base_url = _require_str("baseUrl", "LLM_BASE_URL").rstrip("/")
    model = _require_str("defaultModel", "LLM_DEFAULT_MODEL")
    timeout = _require_pos_int("timeoutSeconds", "LLM_TIMEOUT_SECONDS")
    num_ctx = _require_pos_int("numCtx", "LLM_NUM_CTX")

    # retries is required but allowed to be 0
    retries_raw = _env_or("LLM_RETRIES", llm.get("retries"))
    if retries_raw is None or retries_raw == "":
        raise LlmConfigError(
            "Missing required llm.retries (or env LLM_RETRIES) in config.json"
        )
    try:
        retries = int(retries_raw)
    except (TypeError, ValueError):
        raise LlmConfigError(
            f"llm.retries must be an integer (got {retries_raw!r})"
        )
    if retries < 0:
        raise LlmConfigError(
            f"llm.retries must be >= 0 (got {retries})"
        )

    # ── Optional fields with strict-typed validation ──
    api_key = _env_or("LLM_API_KEY", llm.get("apiKey"))
    api_key = str(api_key) if api_key else None

    # maxContextTokens: null → auto-derived later via budget.resolve_max_tokens
    max_ctx_raw = llm.get("maxContextTokens", None)
    if max_ctx_raw is None:
        max_ctx = None
    else:
        try:
            max_ctx = int(max_ctx_raw)
        except (TypeError, ValueError):
            raise LlmConfigError(
                f"llm.maxContextTokens must be null or an integer "
                f"(got {max_ctx_raw!r})"
            )
        if max_ctx <= 0:
            raise LlmConfigError(
                f"llm.maxContextTokens must be positive (got {max_ctx})"
            )

    # enrichment: every flag must be a bool
    enrich_raw = llm.get("enrichment", {}) or {}
    if not isinstance(enrich_raw, dict):
        raise LlmConfigError(
            f"llm.enrichment must be an object (got {type(enrich_raw).__name__})"
        )
    _enrich_defaults = {
        "twoPassDescriptions": True,
        "selfReview": False,
        "ensemble": False,
        "cfgSimplification": False,
        "variableEnrichment": True,
    }
    enrichment: Dict[str, bool] = {}
    for key, default in _enrich_defaults.items():
        val = enrich_raw.get(key, default)
        if not isinstance(val, bool):
            raise LlmConfigError(
                f"llm.enrichment.{key} must be true or false (got {val!r})"
            )
        enrichment[key] = val

    # cacheVersion
    cache_v_raw = llm.get("cacheVersion", 1)
    try:
        cache_version = int(cache_v_raw)
    except (TypeError, ValueError):
        raise LlmConfigError(
            f"llm.cacheVersion must be an integer (got {cache_v_raw!r})"
        )
    if cache_version < 1:
        raise LlmConfigError(
            f"llm.cacheVersion must be >= 1 (got {cache_version})"
        )

    few_shot_dir = llm.get("fewShotExamplesDir", "few_shot_examples")
    if not isinstance(few_shot_dir, str) or not few_shot_dir.strip():
        raise LlmConfigError(
            f"llm.fewShotExamplesDir must be a non-empty string "
            f"(got {few_shot_dir!r})"
        )

    descriptions = llm.get("descriptions", True)
    if not isinstance(descriptions, bool):
        raise LlmConfigError(
            f"llm.descriptions must be true or false (got {descriptions!r})"
        )
    behaviour_names = llm.get("behaviourNames", True)
    if not isinstance(behaviour_names, bool):
        raise LlmConfigError(
            f"llm.behaviourNames must be true or false (got {behaviour_names!r})"
        )

    custom_headers = llm.get("customHeaders", {}) or {}
    if not isinstance(custom_headers, dict):
        raise LlmConfigError(
            f"llm.customHeaders must be an object (got {type(custom_headers).__name__})"
        )

    return {
        "provider": provider,
        "baseUrl": base_url,
        "defaultModel": model,
        "timeoutSeconds": timeout,
        "numCtx": num_ctx,
        "retries": retries,
        "descriptions": descriptions,
        "behaviourNames": behaviour_names,
        "abbreviationsPath": str(llm.get("abbreviationsPath", "") or ""),
        "customHeaders": dict(custom_headers),
        "apiKey": api_key,
        "maxContextTokens": max_ctx,
        "enrichment": enrichment,
        "cacheVersion": cache_version,
        "fewShotExamplesDir": few_shot_dir.strip(),
    }


# ---------------------------------------------------------------------------
# Startup banner
# ---------------------------------------------------------------------------

def format_llm_config_banner(llm_cfg: Dict[str, Any]) -> str:
    """Format a multi-line banner showing the resolved LLM config.

    Used by run.py and flowchart_engine.py to print exactly which provider,
    model, endpoint, and budgets the run is going to use. The point is to
    eliminate "I thought it was X but it ran with Y" surprises.
    """
    # Lazy import to avoid an import cycle (budget imports nothing from core)
    try:
        from llm_core.budget import resolve_max_tokens
        resolved_max = resolve_max_tokens(llm_cfg)
    except Exception:  # pragma: no cover — defensive
        resolved_max = None

    enrichment = llm_cfg.get("enrichment", {}) or {}
    flags_on = sorted(k for k, v in enrichment.items() if v)
    flags_off = sorted(k for k, v in enrichment.items() if not v)

    api_key_display = "set" if llm_cfg.get("apiKey") else "(none)"
    max_ctx_raw = llm_cfg.get("maxContextTokens")
    if max_ctx_raw is None:
        max_ctx_display = f"auto -> {resolved_max}" if resolved_max else "auto"
    else:
        max_ctx_display = str(max_ctx_raw)

    lines = [
        "-" * 60,
        "LLM configuration (will be used for this run)",
        "-" * 60,
        f"  provider          : {llm_cfg.get('provider')}",
        f"  baseUrl           : {llm_cfg.get('baseUrl')}",
        f"  defaultModel      : {llm_cfg.get('defaultModel')}",
        f"  numCtx            : {llm_cfg.get('numCtx')}  "
        f"({'used' if llm_cfg.get('provider') == 'ollama' else 'ignored on ' + llm_cfg.get('provider', 'openai')})",
        f"  maxContextTokens  : {max_ctx_display}",
        f"  timeoutSeconds    : {llm_cfg.get('timeoutSeconds')}",
        f"  retries           : {llm_cfg.get('retries')}",
        f"  apiKey            : {api_key_display}",
        f"  cacheVersion      : {llm_cfg.get('cacheVersion')}",
        f"  fewShotExamplesDir: {llm_cfg.get('fewShotExamplesDir')}",
        f"  descriptions      : {llm_cfg.get('descriptions')}",
        f"  behaviourNames    : {llm_cfg.get('behaviourNames')}",
        f"  enrichment ON     : {', '.join(flags_on) if flags_on else '(none)'}",
        f"  enrichment OFF    : {', '.join(flags_off) if flags_off else '(none)'}",
        "-" * 60,
    ]
    return "\n".join(lines)


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


# ---------------------------------------------------------------------------
# Default clang preprocessor flags shared by every libclang entry point
# ---------------------------------------------------------------------------
#
# Both Phase 1 (`src/parser.py`) and the flowchart engine's per-function
# re-parser (`src/flowchart/ast_engine/parser.py`) feed source through
# libclang. Real C/C++ projects almost always use visibility-style macros
# (`PUBLIC`, `PRIVATE`, `PROTECTED`) and sometimes a `VOID` alias that the
# build system defines but a standalone libclang invocation does not see.
# Without these defines, libclang reports `unknown type name 'PUBLIC'`
# warnings and the AST is incomplete, which then breaks CFG construction.
#
# Defining the macros here (rather than in two separate parser files) keeps
# the two libclang entry points in lock-step. Override locally by passing
# `-UPUBLIC` etc. via `clang.clangArgs` in config.json.

DEFAULT_VISIBILITY_MACROS = ("PRIVATE", "PROTECTED", "PUBLIC", "__OVLYINIT")


def default_clang_macro_defs() -> list:
    """Return the `-D…` macro defines every libclang call should include.

    Used by `src/parser.py` (Phase 1) and `src/flowchart/ast_engine/parser.py`
    (flowchart engine re-parser) so both parsers share the exact same set of
    visibility-macro shims and `VOID` alias.
    """
    args = [f"-D{name}=" for name in DEFAULT_VISIBILITY_MACROS]
    return args


def modules_groups() -> Dict[str, Any]:
    """Return the `modulesGroups` block (or {} if absent)."""
    return app_config().get("modulesGroups") or {}
