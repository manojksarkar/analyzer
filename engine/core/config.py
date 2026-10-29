"""Cached, typed accessors for the analyzer configuration.

All values live in two JSON files, one per kind of setting, so the user can change
anything by editing a file: `config/config.defaults.json` (how documents are made) and
`config/config.local.json` (this server: database, sign-in, repository folders, LLM
server, LLVM install -- see "Which file a setting is in" below). This module:
  1. Parses JSONC (JSON with // and /* */ comments and trailing commas).
  2. Loads + merges config.defaults.json + config.local.json once per process.
  3. Resolves the LLM settings (`llm` + `llmServer`), applying environment-variable
     overrides.
  4. Provides typed helpers (llm_config, views_config, exporter_config,
     components_groups) so call sites stop typing `cfg.get("llm", {}).get(...)`.
  5. Re-exports the raw dict via `app_config()` for code that still wants the
     dict-style access.

This module is the bottom of the dependency graph for configuration; nothing
in `core/` may import from analyzer-level modules (utils.py, etc.).
"""

from __future__ import annotations

import difflib
import json
import os
import threading
from typing import Any, Dict, List, Optional, Tuple

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

def _deep_merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge ``over`` into ``base``: nested dicts merge, scalars/lists replace. So
    config.local.json can override a single nested key (e.g. ``views.flowcharts``) without
    restating the whole block."""
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


# ---------------------------------------------------------------------------
# Which file a setting is in
# ---------------------------------------------------------------------------
# Two files, two jobs (config.local.json.example has the long form):
#
#   config.local.json     THIS SERVER: its database, sign-in, repository folders, LLM server,
#                         LLVM install and its speed-ups. Read from that file only, by every
#                         process, when it loads its config: not from the defaults, a project
#                         or a version.
#   config.defaults.json  HOW DOCUMENTS ARE MADE: the parse flags, the views, what the LLM writes
#                         and how it is prompted, the document texts. A project's own win.
#
# Every place that builds or reads a config goes by the names below, so the split is written once.

#: This server's blocks. Not in config.defaults.json, and never written into a project's or a
#: version's config (`without_server_settings`).
SERVER_BLOCKS = ("db", "auth", "repositories", "llmServer", "llvm", "speedups")
#: The server blocks a run reads through its config: laid over it when it is loaded
#: (`with_server_settings`). The others have readers of their own, on the same file:
#: `core.db._db_section`, `api.middleware.auth`, `api.services.local_repos`.
RUN_SERVER_BLOCKS = ("llmServer", "llvm", "speedups")
#: The keys of `llmServer` -- develop's. Until 2026-10-13 they were in `llm`, where they are not
#: read any more.
LLM_SERVER_KEYS = ("provider", "baseUrl", "defaultModel", "customHeaders", "apiKey",
                   "rateLimitSeconds", "timeoutSeconds", "retries", "numCtx", "maxContextTokens")
#: The speed settings' places before they all went into `speedups` (2026-10-14): (block, key) ->
#: its key in `speedups`. Not read there any more; a run's start says where they go.
SPEED_KEYS_BEFORE = {("llmServer", "lanes"): "llms", ("llmServer", "pacing"): "pacing",
                     ("llm", "lanes"): "llms", ("llm", "pacing"): "pacing",
                     ("parse", "workers"): "parseWorkers"}
#: `llvm`'s keys, by the name each had in `clang` until then.
LLVM_KEYS_BEFORE = {"llvmLibPath": "libPath", "clangIncludePath": "includePath"}


class ConfigFileError(ValueError):
    """config.local.json is there and cannot be read: a run stops rather than go on without this
    server's settings (and so without the LLM's text)."""


def _read_jsonc(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.loads(_strip_trailing_commas(_strip_json_comments(f.read())))
    return data if isinstance(data, dict) else {}


def local_config_path(config_root: Optional[str] = None) -> str:
    """This installation's config.local.json (it may not exist). `config_root` is the folder
    holding `config/`, the engine's by default.

    A detached run's code is a frozen copy (`core.frozen_run`), and the copy's file is the one of
    the day the run started; a key changed since is in the installation's, which
    `ANALYZER_DATA_ROOT` names."""
    data_root = os.environ.get("ANALYZER_DATA_ROOT", "").strip()
    if data_root:
        path = os.path.join(data_root, "engine", "config", "config.local.json")
        if os.path.isfile(path):
            return path
    root = config_root or paths().src_dir
    path = os.path.join(root, "config", "config.local.json")
    if not os.path.isfile(path) and os.path.isfile(os.path.join(root, "config.local.json")):
        path = os.path.join(root, "config.local.json")
    return path


def server_settings(config_root: Optional[str] = None, *, strict: bool = False) -> Dict[str, Any]:
    """The server blocks a run reads (`RUN_SERVER_BLOCKS`), as config.local.json has them now.
    No file, or no such block: without it. A file that cannot be read: `ConfigFileError` when
    `strict`, else none of them."""
    path = local_config_path(config_root)
    if not os.path.isfile(path):
        return {}
    try:
        local = _read_jsonc(path)
    except (ValueError, OSError) as exc:
        if strict:
            raise ConfigFileError(f"{path} could not be read ({exc}). It holds this server's "
                                  f"settings (the LLM server, LLVM): correct it and run again.") from exc
        return {}
    return {block: json.loads(json.dumps(local[block]))
            for block in RUN_SERVER_BLOCKS if isinstance(local.get(block), dict)}


def with_server_settings(config: Dict[str, Any], config_root: Optional[str] = None, *,
                         strict: bool = False) -> Dict[str, Any]:
    """`config`, in place, with this server's blocks as config.local.json has them: whatever the
    config held under those names is dropped first. So a change in that file reaches the next run
    of every project -- a config written at onboarding, or days ago for a version being resumed,
    does not keep the settings of that day."""
    for block in RUN_SERVER_BLOCKS:
        config.pop(block, None)
    config.update(server_settings(config_root, strict=strict))
    return config


def without_server_settings(config: Dict[str, Any]) -> Dict[str, Any]:
    """`config`, in place, without this server's settings: its blocks, and the names their keys
    had in `llm` and `clang` before. What a project's or a version's config may keep, and what
    is written to a workspace file -- which so holds no credential."""
    for block in SERVER_BLOCKS + ("parse",):          # `parse`: a server block until 2026-10-14
        config.pop(block, None)
    for section, keys in (("llm", LLM_SERVER_KEYS + ("lanes", "pacing")), ("clang", LLVM_KEYS_BEFORE)):
        if isinstance(config.get(section), dict):
            for key in keys:
                config[section].pop(key, None)
    return config


def moved_settings(config: Dict[str, Any]) -> List[str]:
    """What `config` still names the old way, each with its place now:
    `["llm.baseUrl -> llmServer.baseUrl", "clang.llvmLibPath -> llvm.libPath"]`."""
    out: List[str] = []
    llm = config.get("llm") if isinstance(config, dict) else None
    if isinstance(llm, dict):
        out.extend(f"llm.{k} -> llmServer.{k}" for k in LLM_SERVER_KEYS if k in llm)
    clang = config.get("clang") if isinstance(config, dict) else None
    if isinstance(clang, dict):
        out.extend(f"clang.{k} -> llvm.{new}" for k, new in LLVM_KEYS_BEFORE.items() if k in clang)
    for (block, key), new in SPEED_KEYS_BEFORE.items():
        section = config.get(block) if isinstance(config, dict) else None
        if isinstance(section, dict) and key in section:
            out.append(f"{block}.{key} -> speedups.{new}")
    speedups = config.get("speedups") if isinstance(config, dict) else None
    if isinstance(speedups, dict) and "enabled" in speedups:
        out.append("speedups.enabled -> none: each speed-up has its own key, and none set is develop's way")
    return out


def local_config_notes(config_root: Optional[str] = None) -> List[str]:
    """What is wrong with this installation's config.local.json, for the start of a run: it
    cannot be read, or it has server settings where they were before the split (they are not
    read there). Empty when there is nothing to say."""
    path = local_config_path(config_root)
    if not os.path.isfile(path):
        return []
    try:
        local = _read_jsonc(path)
    except (ValueError, OSError) as exc:
        return [f"{path} could not be read ({exc})"]
    moved = moved_settings(local)
    if not moved:
        return []
    return [f"{path} has settings under their old names, where they are not read any more: "
            f"{'; '.join(moved)}. Move them (config.local.json.example shows where each goes)."]


def llvm_paths(config: Dict[str, Any]) -> Tuple[str, str]:
    """(the libclang library, Clang's own include folder) of this machine: `llvm.libPath` and
    `llvm.includePath`. "" for one that is not set."""
    llvm = config.get("llvm") if isinstance(config, dict) else None
    llvm = llvm if isinstance(llvm, dict) else {}
    return str(llvm.get("libPath") or "").strip(), str(llvm.get("includePath") or "").strip()


def llm_server(config: Dict[str, Any]) -> Dict[str, Any]:
    """The `llmServer` block as written ({} when there is none). `load_llm_config` is the
    resolved, checked form; this is for a reader that must not stop a run over it."""
    server = config.get("llmServer") if isinstance(config, dict) else None
    return server if isinstance(server, dict) else {}


def has_llm_server(config: Dict[str, Any]) -> bool:
    """True when an LLM server is named: an `llmServer` block, or the environment's
    (`LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_DEFAULT_MODEL`)."""
    return bool(llm_server(config)) or any(
        os.environ.get(name) for name in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_DEFAULT_MODEL"))


def llm_text_wanted(config: Dict[str, Any], *, summarize: Optional[bool] = None) -> bool:
    """True when this config asks the LLM for any text: descriptions (which the flowchart labels
    and the behaviour descriptions follow), input and output names, or the summaries.
    `summarize`: the run's own answer where a flag decides it (`--no-llm-summarize`)."""
    llm = config.get("llm") if isinstance(config, dict) else None
    llm = llm if isinstance(llm, dict) else {}
    if summarize is None:
        summarize = bool(llm.get("summarize", True))
    return bool(llm.get("descriptions", True) or llm.get("behaviourNames", True) or summarize)


def load_config(project_root: str) -> Dict[str, Any]:
    """Load config from <project_root>/config/config.defaults.json, then config.local.json overrides.

    Callers pass the directory that *contains* ``config/``. Since the config now
    lives under ``engine/config/``, engine callers pass the engine dir
    (``paths().src_dir``), not the repo root.

    If the ``ANALYZER_CONFIG`` environment variable points to a file, that file
    is loaded **instead**, as the run's config — with no merge of
    ``config.local.json`` over its analysis settings. This is how a per-project /
    per-version config (carrying the project's ``layers``) is injected into the
    analyzer and every phase subprocess, which inherit the env var: the run is
    reproducible, a dev's local overrides do not bleed into it. See ``run.py --config``.
    A set-but-missing path fails loud rather than silently falling back.

    Either way THIS SERVER's blocks (``llmServer``, ``llvm``) are those of
    ``config.local.json``, read now (`with_server_settings`): the defaults hold none, and a
    per-run file's own are not used.
    """
    override = os.environ.get("ANALYZER_CONFIG", "").strip()
    if override:
        if not os.path.isfile(override):
            raise FileNotFoundError(
                f"ANALYZER_CONFIG points to a missing file: {override}"
            )
        with open(override, "r", encoding="utf-8") as f:
            stripped = _strip_trailing_commas(_strip_json_comments(f.read()))
        return with_server_settings(json.loads(stripped), project_root, strict=True)

    config: Dict[str, Any] = {}
    config_dir = os.path.join(project_root, "config")
    for name in ("config.defaults.json", "config.local.json"):
        path = os.path.join(config_dir, name)
        if not os.path.isfile(path):
            path = os.path.join(project_root, name)
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = f.read()
                    stripped = _strip_json_comments(raw)
                    stripped = _strip_trailing_commas(stripped)
                    _deep_merge(config, json.loads(stripped))   # local overrides per nested key
            except (json.JSONDecodeError, IOError):
                pass
    return with_server_settings(config, project_root)


class LlmConfigError(ValueError):
    """Raised when the LLM settings have missing or invalid fields.

    Strict validation: rather than falling back to silent defaults, the
    analyzer surfaces the exact field that is wrong so the user can fix
    the config (``llmServer`` in config.local.json, ``llm`` in config.defaults.json) or
    the matching env var and re-run.
    """


#: What a run uses for the `llmServer` keys that may be left out (config.local.json.example).
LLM_SERVER_DEFAULTS = {"timeoutSeconds": 300, "numCtx": 8192, "retries": 1}

NO_LLM_SERVER = ("no LLM server is set. Add an `llmServer` block (provider, baseUrl, "
                 "defaultModel) to engine/config/config.local.json -- config.local.json.example "
                 "shows it -- or run without the LLM (--no-llm)")


def load_llm_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve and STRICTLY validate the LLM settings: which server answers (``llmServer``,
    this server's own, from config.local.json) and what it is asked to write (``llm``).

    ``llmServer`` — required (raises LlmConfigError if missing or invalid):
        provider          - "ollama" | "openai" | "anthropic" (the Claude Messages API)
        baseUrl           - non-empty endpoint base URL
        defaultModel      - non-empty model name
    ``llmServer`` — may be left out:
        timeoutSeconds    - positive int, default 300
        numCtx            - positive int, default 8192 (Ollama context window;
                            informational on OpenAI)
        retries           - int >= 0, default 1
        customHeaders     - dict, default {}
        apiKey            - str | None (env LLM_API_KEY wins)
        maxContextTokens  - int | None (null → auto-derived from numCtx/provider)
        rateLimitSeconds  - float >= 0, default 3.0 (pause after every OpenAI
                            call to satisfy the gateway throttle; 0 disables
                            it; ignored on Ollama)
    ``llm`` — all optional:
        descriptions      - bool, default True
        behaviourNames    - bool, default True
        abbreviationsPath - str, default ""
        enrichment        - dict of feature toggles (each must be a bool):
            twoPassDescriptions (default True)
            selfReview          (default False)
            ensemble            (default False)
            cfgSimplification   (default False)
            variableEnrichment  (default True)
        cacheVersion      - int >= 1 (bump to invalidate entity cache)
        fewShotExamplesDir - str (default "few_shot_examples")

    The result is one flat dict of both, as before the two were told apart.

    Environment variables (override the matching ``llmServer`` field if set):
        LLM_PROVIDER, LLM_BASE_URL, LLM_DEFAULT_MODEL,
        LLM_TIMEOUT_SECONDS, LLM_NUM_CTX, LLM_RETRIES, LLM_API_KEY,
        LLM_RATE_LIMIT_SECONDS

    Raises
    ------
    LlmConfigError
        If no LLM server is set, or a field is missing, empty, or not parseable.
    """
    if not config or not isinstance(config, dict):
        raise LlmConfigError("config is empty or not a JSON object")

    llm = config.get("llm")
    llm = llm if isinstance(llm, dict) else {}
    server = llm_server(config)
    if not has_llm_server(config):
        moved = [m for m in moved_settings(config) if m.startswith("llm.")]
        raise LlmConfigError(NO_LLM_SERVER + (
            f". (This config names one the old way, which is not read: {'; '.join(moved)}.)"
            if moved else ""))

    def _env_or(key: str, fallback):
        v = os.environ.get(key)
        return v if v is not None and v != "" else fallback

    def _require_str(field: str, env_var: str) -> str:
        raw = _env_or(env_var, server.get(field))
        if raw is None or str(raw).strip() == "":
            raise LlmConfigError(
                f"Missing required llmServer.{field} (or env {env_var}) in "
                f"engine/config/config.local.json"
            )
        return str(raw).strip()

    def _pos_int(field: str, env_var: str) -> int:
        raw = _env_or(env_var, server.get(field))
        if raw is None or raw == "":
            raw = LLM_SERVER_DEFAULTS[field]
        try:
            val = int(raw)
        except (TypeError, ValueError):
            raise LlmConfigError(
                f"llmServer.{field} must be an integer (got {raw!r})"
            )
        if val <= 0:
            raise LlmConfigError(
                f"llmServer.{field} must be a positive integer (got {val})"
            )
        return val

    # ── The server: three required fields, the rest with a default ──
    provider = _require_str("provider", "LLM_PROVIDER").lower()
    if provider not in ("ollama", "openai", "anthropic"):
        raise LlmConfigError(
            f"llmServer.provider must be 'ollama', 'openai' or 'anthropic' (got {provider!r})"
        )

    base_url = _require_str("baseUrl", "LLM_BASE_URL").rstrip("/")
    model = _require_str("defaultModel", "LLM_DEFAULT_MODEL")
    timeout = _pos_int("timeoutSeconds", "LLM_TIMEOUT_SECONDS")
    num_ctx = _pos_int("numCtx", "LLM_NUM_CTX")

    # retries may be 0
    retries_raw = _env_or("LLM_RETRIES", server.get("retries"))
    if retries_raw is None or retries_raw == "":
        retries_raw = LLM_SERVER_DEFAULTS["retries"]
    try:
        retries = int(retries_raw)
    except (TypeError, ValueError):
        raise LlmConfigError(
            f"llmServer.retries must be an integer (got {retries_raw!r})"
        )
    if retries < 0:
        raise LlmConfigError(
            f"llmServer.retries must be >= 0 (got {retries})"
        )

    # The Claude API's key is read from config.local.json and nowhere else: no environment
    # variable -- LLM_API_KEY, set for a gateway, would otherwise be sent to Anthropic.
    api_key = (server.get("apiKey") if provider == "anthropic"
               else _env_or("LLM_API_KEY", server.get("apiKey")))
    api_key = str(api_key) if api_key else None

    # maxContextTokens: null → auto-derived later via budget.resolve_max_tokens
    max_ctx_raw = server.get("maxContextTokens", None)
    if max_ctx_raw is None:
        max_ctx = None
    else:
        try:
            max_ctx = int(max_ctx_raw)
        except (TypeError, ValueError):
            raise LlmConfigError(
                f"llmServer.maxContextTokens must be null or an integer "
                f"(got {max_ctx_raw!r})"
            )
        if max_ctx <= 0:
            raise LlmConfigError(
                f"llmServer.maxContextTokens must be positive (got {max_ctx})"
            )

    # rateLimitSeconds: pause after every OpenAI call, including failed ones, because the
    # corporate gateway throttles ~1 request per 3 seconds. 0 disables the throttle entirely.
    # Ollama is not gateway-throttled and never sleeps, so this is an OpenAI-only knob.
    #
    # The two on-prem deployments need opposite values (doc 09, B6): the API **gateway**
    # enforces that global limit, while an on-prem **hosted model** has none and 3s per call
    # would dominate the run. Default 3.0 keeps the gateway safe for anyone who does not set it.
    rate_limit_raw = _env_or("LLM_RATE_LIMIT_SECONDS",
                             server.get("rateLimitSeconds", 3.0))
    if rate_limit_raw is None or rate_limit_raw == "":
        raise LlmConfigError(
            "llmServer.rateLimitSeconds must be a number — "
            "use 0 to disable the throttle"
        )
    try:
        rate_limit = float(rate_limit_raw)
    except (TypeError, ValueError):
        raise LlmConfigError(
            f"llmServer.rateLimitSeconds must be a number (got {rate_limit_raw!r})"
        )
    if rate_limit < 0:
        raise LlmConfigError(
            f"llmServer.rateLimitSeconds must be >= 0 (got {rate_limit})"
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

    custom_headers = server.get("customHeaders", {}) or {}
    if not isinstance(custom_headers, dict):
        raise LlmConfigError(
            f"llmServer.customHeaders must be an object (got {type(custom_headers).__name__})"
        )

    speedups = speedup_settings(config)
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
        "rateLimitSeconds": rate_limit,
        "enrichment": enrichment,
        "cacheVersion": cache_version,
        "fewShotExamplesDir": few_shot_dir.strip(),
        # The speed-ups' (`speedups` block, llm_core/pool.py): more tickets or keys for this
        # server, start pacing, and how many calls a stage keeps in flight. Not set: one lane --
        # llmServer's own ticket -- the pause after each call, one call at a time, as on develop.
        # `workers` is not a setting: it is what the lanes allow (`llm_calls_at_once`).
        "lanes": [dict(x) for x in speedups["llms"]],
        "pacing": speedups["pacing"],
        "workers": llm_calls_at_once(speedups, provider),
    }


def env_api_keys(provider: Optional[str]) -> List[str]:
    """LLM_API_KEYS (env), one lane per key -- never for the Claude API, whose keys are
    config.local.json's only."""
    if str(provider or "").lower() == "anthropic":
        return []
    return [k.strip() for k in os.environ.get("LLM_API_KEYS", "").split(",") if k.strip()]


def llm_calls_at_once(speedups: Dict[str, Any], provider: Optional[str] = None) -> int:
    """How many LLM calls a stage keeps in flight, from `speedup_settings`. Not a setting: it
    follows the lanes.

    No `llms` (and no LLM_API_KEYS) and pacing "after": 1 -- one call at a time, as on develop.
    Otherwise twice what the lanes take at once (each lane's `maxConcurrent`, default 1). The
    lanes alone decide what really goes out (llm_core/pool.py); the spare half only has the next
    question ready the moment a lane frees up."""
    speedups = speedups or {}
    lanes = speedups.get("llms") if isinstance(speedups.get("llms"), list) else []
    env_keys = env_api_keys(provider)
    if not lanes and not env_keys and str(speedups.get("pacing") or "after").lower() != "start":
        return 1

    def _at_once(lane) -> int:
        try:
            return max(1, int((lane or {}).get("maxConcurrent") or 1))
        except (TypeError, ValueError, AttributeError):
            return 1
    capacity = sum(_at_once(l) for l in lanes) if lanes else (len(env_keys) or 1)
    return 2 * capacity


def _positive_int(raw: Any, name: str, error=None) -> int:
    error = error or LlmConfigError
    try:
        v = int(raw)
    except (TypeError, ValueError):
        raise error(f"{name} must be a whole number (got {raw!r})")
    if v < 1:
        raise error(f"{name} must be at least 1 (got {v})")
    return v


class SpeedupsConfigError(ValueError):
    """A `speedups` setting that cannot be used."""


#: Phase 1's setting until 2026-10-14 had its own error; it is a `speedups` key now.
ParseConfigError = SpeedupsConfigError

#: `speedups` with nothing set: develop's way, every one of them.
SPEEDUP_DEFAULTS = {"llms": [], "pacing": "after", "parseWorkers": 1,
                    "pictureBatches": False, "fastNullCheck": False}


def speedup_settings(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """This server's speed-ups: the `speedups` block of config.local.json, checked, every key
    filled in. A key not set is develop's way, so an empty or absent block runs as develop does.

        llms            more tickets or keys for the LLM server, side by side (llm_core/pool.py);
                        [] = llmServer's own ticket, one call at a time
        pacing          "after": a ticket's pause counts from the END of a call (develop's);
                        "start": from its start
        parseWorkers    files parsed ahead on threads: 1 (develop's), a number, or "auto" (half
                        the CPUs, at most 8); the environment's ANALYZER_PARSE_WORKERS wins
        pictureBatches  true: the pictures of a view drawn by one browser; false: each alone
        fastNullCheck   true: the parser's field check for libclang's null cursor (parser.py)

    None changes a document (docs/design/PIPELINE_SPEED_PLAN.md). A machine setting -- one of
    this server's blocks (`SERVER_BLOCKS`). A key this does not know is left alone; a moved one
    is named at a run's start (`moved_settings`). `config` None: this process's own."""
    block = (app_config() if config is None else config or {}).get("speedups")
    if block is None:
        block = {}
    if not isinstance(block, dict):
        raise SpeedupsConfigError("speedups must be an object, e.g. \"speedups\": {}")
    llms = block.get("llms")
    if llms in (None, ""):
        llms = []
    if not isinstance(llms, list) or not all(isinstance(x, dict) for x in llms):
        raise SpeedupsConfigError("speedups.llms must be a list of objects")
    pacing = str(block.get("pacing") or "after").strip().lower()
    if pacing not in ("after", "start"):
        raise SpeedupsConfigError(f"speedups.pacing must be \"after\" or \"start\" (got {block.get('pacing')!r})")
    env_workers = os.environ.get("ANALYZER_PARSE_WORKERS", "").strip()
    raw = env_workers or block.get("parseWorkers", 1)
    name = "ANALYZER_PARSE_WORKERS" if env_workers else "speedups.parseWorkers"
    if str(raw).strip().lower() == "auto":
        workers = max(1, min(8, (os.cpu_count() or 2) // 2))
    else:
        workers = _positive_int(raw, name, SpeedupsConfigError)
    flags = {}
    for key in ("pictureBatches", "fastNullCheck"):
        value = block.get(key, False)
        if not isinstance(value, bool):
            raise SpeedupsConfigError(f"speedups.{key} must be true or false (got {value!r})")
        flags[key] = value
    return {"llms": [dict(x) for x in llms], "pacing": pacing, "parseWorkers": workers, **flags}


def load_parse_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Phase 1's speed setting: `speedups.parseWorkers` (`speedup_settings`), as `workers`."""
    return {"workers": speedup_settings(config)["parseWorkers"]}


def parse_workers_note(config: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """How many files Phase 1 parses at once, for the log: `auto -> 4` when "auto" chose it --
    always, 1 included, so a log says what auto became on that machine -- the number when one
    above 1 is set, else None (one at a time, develop's)."""
    env = os.environ.get("ANALYZER_PARSE_WORKERS", "").strip()
    block = (app_config() if config is None else config or {}).get("speedups")
    raw = env or (block.get("parseWorkers", 1) if isinstance(block, dict) else 1)
    workers = speedup_settings(config)["parseWorkers"]
    if str(raw).strip().lower() == "auto":
        return f"auto -> {workers}"
    return str(workers) if workers > 1 else None


#: Where a version keeps one entry per run of the server settings it used (`run_settings_snapshot`):
#: at the top of its output, so it is stored with the version and is no component's.
RUN_SETTINGS_FILE = "_run_settings.json"
_SNAPSHOT_LLM_KEYS = ("provider", "baseUrl", "defaultModel", "timeoutSeconds", "retries", "numCtx",
                      "maxContextTokens", "rateLimitSeconds")
_HEADER_ENV_VARS = ("X_DEP_TICKET", "USER_TYPE", "USER_ID", "SEND_SYSTEM_NAME")


def _safe_url(url: Any) -> Any:
    """A URL without what could be a credential: its user:password and its query."""
    if not isinstance(url, str) or "://" not in url:
        return url
    from urllib.parse import urlsplit, urlunsplit
    try:
        p = urlsplit(url)
        host = p.hostname or ""
        netloc = host + (f":{p.port}" if p.port else "")
        return urlunsplit((p.scheme, netloc, p.path, "", ""))
    except ValueError:
        return "(unreadable)"


def run_settings_snapshot(config: Dict[str, Any]) -> Dict[str, Any]:
    """This server's settings as a run uses them, with NO secret: what a version records per run
    (`RUN_SETTINGS_FILE`). Built from allowed keys only -- a key added to llmServer later is left
    out until it is listed here. A key or a header value is never copied: an API key is "set" or
    "none", a header by its name; a URL loses its user:password and query."""
    try:
        llm = load_llm_config(config)                 # the resolved form: env overrides included
    except Exception:                                 # noqa: BLE001 - no LLM server: as written
        llm = llm_server(config)
    s = speedup_settings(config)

    def names(headers: Any) -> List[str]:
        return sorted(headers) if isinstance(headers, dict) else []

    server = {k: (_safe_url(llm[k]) if k == "baseUrl" else llm[k]) for k in _SNAPSHOT_LLM_KEYS if k in llm}
    server["apiKey"] = "set" if llm.get("apiKey") else "none"
    server["customHeaders"] = names(llm.get("customHeaders"))
    lanes = []
    for i, lane in enumerate(s["llms"], start=1):
        entry = {"name": str(lane.get("name") or f"lane{i}"),
                 "maxConcurrent": lane.get("maxConcurrent", 1)}
        for key in ("baseUrl", "defaultModel"):
            if lane.get(key):
                entry[key] = _safe_url(lane[key]) if key == "baseUrl" else lane[key]
        if lane.get("apiKey"):
            entry["apiKey"] = "set"
        if lane.get("customHeaders"):
            entry["customHeaders"] = names(lane["customHeaders"])
        lanes.append(entry)
    lib, inc = llvm_paths(config)
    return {
        "llmServer": server,
        "headersFromEnvironment": [v for v in _HEADER_ENV_VARS if os.environ.get(v, "").strip()],
        "speedups": {"llms": lanes, "pacing": s["pacing"],
                     "parseWorkers": parse_workers_note(config) or "1",
                     "pictureBatches": s["pictureBatches"], "fastNullCheck": s["fastNullCheck"]},
        "llvm": {"libPath": lib, "includePath": inc},
    }


def run_settings_line(entry: Dict[str, Any]) -> str:
    """One entry of `RUN_SETTINGS_FILE` as one line: `anthropic / claude-sonnet-5-5, 1 lane x 2, ...`."""
    server = entry.get("llmServer") or {}
    sp = entry.get("speedups") or {}
    lanes = sp.get("llms") or []
    lane_text = (", ".join(f"{l.get('name')} x{l.get('maxConcurrent', 1)}" for l in lanes)
                 if lanes else "no lanes")
    return (f"{server.get('provider', '?')} / {server.get('defaultModel', '?')} at "
            f"{server.get('baseUrl', '?')}; {lane_text}; pacing {sp.get('pacing', '?')}; "
            f"parseWorkers {sp.get('parseWorkers', '?')}")


def speed_summary(config: Dict[str, Any]) -> str:
    """One line for a run's start: the speed-ups this run uses, or that it runs as develop."""
    s = speedup_settings(config)
    keys = env_api_keys(llm_server(config).get("provider"))
    used = []
    if s["llms"]:
        used.append(f"{len(s['llms'])} llms")
    elif keys:
        used.append(f"{len(keys)} keys from LLM_API_KEYS")
    if s["pacing"] != "after":
        used.append(f"pacing {s['pacing']}")
    workers = parse_workers_note(config)
    if workers:
        used.append(f"parseWorkers {workers}")
    used += [k for k in ("pictureBatches", "fastNullCheck") if s[k]]
    if not used:
        return "none -- this run works as develop does (speedups in engine/config/config.local.json)"
    return ", ".join(used)


# ---------------------------------------------------------------------------
# Startup banner
# ---------------------------------------------------------------------------

def _lanes_display(llm_cfg: Dict[str, Any]) -> str:
    lanes = llm_cfg.get("lanes") or []
    env = env_api_keys(llm_cfg.get("provider"))
    if lanes:
        return f"{len(lanes)} (speedups.llms)"
    if env:
        return f"{len(env)} from LLM_API_KEYS"
    return "none (llmServer's own ticket: one call at a time, as develop)"


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
        f"({'used' if llm_cfg.get('provider') == 'ollama' else 'ignored on ' + str(llm_cfg.get('provider'))})",
        f"  maxContextTokens  : {max_ctx_display}",
        f"  timeoutSeconds    : {llm_cfg.get('timeoutSeconds')}",
        f"  retries           : {llm_cfg.get('retries')}",
        # Surfaced because it silently dominates wall-clock: at 3s a 20k-call run spends
        # ~17 hours asleep. The operator should see which mode this run is in — and that it
        # does nothing at all on ollama.
        f"  rateLimitSeconds  : {llm_cfg.get('rateLimitSeconds')}"
        f"{'  (no throttle)' if not llm_cfg.get('rateLimitSeconds') else '  (per process)'}"
        f"{'  (ignored on ollama)' if llm_cfg.get('provider') == 'ollama' else ''}",
        f"  apiKey            : {api_key_display}",
        # LLM lanes (llm_core/pool.py) -- counted, never printed: a lane's key is a secret too
        f"  lanes             : {_lanes_display(llm_cfg)}",
        f"  pacing            : {llm_cfg.get('pacing') or 'after'}",
        f"  calls at once     : {llm_cfg.get('workers') or 1}  (follows the lanes)",
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
            _CACHED = load_config(paths().src_dir)
        return _CACHED


#: The live log's settings when config names none (docs/spec/LIVE_LOGS_SPEC.md REQ-LL-14).
LOGS_DEFAULTS = {"liveLines": 500, "maxLines": 2000, "level": "INFO", "keepDays": 30}


def logs_config() -> Dict[str, Any]:
    """The `logs` section, read afresh on every call (a changed `level` needs no restart),
    over `LOGS_DEFAULTS`. A broken config file falls back to the defaults."""
    out = dict(LOGS_DEFAULTS)
    try:
        section = load_config(paths().src_dir).get("logs") or {}
    except Exception:                                   # noqa: BLE001
        section = {}
    if isinstance(section, dict):
        out.update({k: v for k, v in section.items() if k in LOGS_DEFAULTS})
    return out


def llm_config() -> Dict[str, Any]:
    """Return the resolved LLM config block (env vars override JSON values).

    See `load_llm_config` for the schema.
    """
    return load_llm_config(app_config())


def views_config() -> Dict[str, Any]:
    """Return the `views` block from the merged config (or {} if absent)."""
    return app_config().get("views") or {}


def exporter_config() -> Dict[str, Any]:
    """Return the `export` block from the merged config (or {} if absent)."""
    return app_config().get("export") or {}


def clang_config() -> Dict[str, Any]:
    """Return the `clang` block from the merged config (or {} if absent)."""
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
# `-UPUBLIC` etc. via `clang.clangArgs` in config.defaults.json.

DEFAULT_VISIBILITY_MACROS = ("PRIVATE", "PROTECTED", "PUBLIC", "__OVLYINIT")


def default_clang_macro_defs() -> list:
    """Return the `-D…` macro defines every libclang call should include.

    Used by `src/parser.py` (Phase 1) and `src/flowchart/ast_engine/parser.py`
    (flowchart engine re-parser) so both parsers share the exact same set of
    visibility-macro shims and `VOID` alias.
    """
    args = [f"-D{name}=" for name in DEFAULT_VISIBILITY_MACROS]
    return args


def _resolve_layer_paths(layers_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten layers into {groupId: {componentId: resolvedPaths}}, layer path prefixed.

    Both ids are LAYER-QUALIFIED (`Layer1.Support` / `Layer1.Math`). They used to be
    the bare config names, and because this dict is keyed across every layer at once,
    two layers sharing a group name meant one plain assignment overwrote the other and
    its components never reached the parser at all. Qualifying makes them what they
    always were: two different groups.
    """
    result: Dict[str, Any] = {}
    for layer_name, layer in (layers_cfg or {}).items():
        if not isinstance(layer, dict):
            continue
        layer_path = layer.get("path", layer_name)
        for group_name, modules in (layer.get("groups") or {}).items():
            if not isinstance(modules, dict):
                continue
            resolved: Dict[str, Any] = {}
            for mod_name, paths in modules.items():
                comp_id = make_qualified_id(layer_name, mod_name)
                if isinstance(paths, str):
                    resolved[comp_id] = f"{layer_path}/{paths}" if paths else layer_path
                elif isinstance(paths, list):
                    resolved[comp_id] = [f"{layer_path}/{p}" if p else layer_path for p in paths]
                else:
                    resolved[comp_id] = paths
            result[make_qualified_id(layer_name, group_name)] = resolved
    return result


def get_flat_groups(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Return {groupName: {componentName: paths}} from config, with layer paths resolved.

    Reads `layers` (new schema). Falls back to `layer` for old configs.
    """
    if "layers" in cfg:
        return _resolve_layer_paths(cfg.get("layers") or {})
    return cfg.get("layer") or {}


def get_layer_components(cfg: Dict[str, Any], group_id: str) -> set:
    """Return all component IDS in the same layer as `group_id`.

    Phase 3 and Phase 4 filter the model to this set so cross-component call edges
    inside the layer stay visible. The layer comes from the id's own prefix, so a
    group name another layer also uses can no longer drag that layer's components in.
    A bare name is still accepted and resolved, for callers that have not qualified.

    For a flat (non-layered) config, returns all components across all groups.
    Returns an empty set if the group is not found.
    """
    layer_name = get_group_layer_name(cfg, group_id)
    if layer_name:
        components: set = set()
        for grp in get_layer_flat_groups(cfg, layer_name).values():
            if isinstance(grp, dict):
                components.update(grp.keys())
        return components
    # Flat config (no layers): all components in all groups
    components = set()
    for grp in get_flat_groups(cfg).values():
        if isinstance(grp, dict):
            components.update(grp.keys())
    return components



def get_group_layer_name(cfg: Dict[str, Any], group_id: str) -> Optional[str]:
    """The layer owning `group_id`, or None.

    A qualified id answers this by itself - that is the point of qualifying. The
    search below runs only for a BARE name, and returns a layer only when exactly one
    layer has it: with two candidates there is no right answer, and picking the first
    is what used to send a run at the wrong layer's macros.
    """
    layer = qualified_layer(group_id)
    if layer and layer in (cfg.get("layers") or {}):
        return layer
    want = name_ident(group_id)
    matches = [ln for ln, lc in (cfg.get("layers") or {}).items()
               if any(name_ident(g) == want for g in ((lc or {}).get("groups") or {}))]
    return matches[0] if len(matches) == 1 else None


def get_component_layer_name(cfg: Dict[str, Any], component_id: str) -> Optional[str]:
    """The layer owning `component_id`, or None.

    Read straight off a qualified id. A BARE name is still resolved by searching,
    space-normalized ("My-Sample" matches a config key "My Sample"), but only when
    exactly one layer has it: two layers with a `Cache` component is legal now, and
    answering with the first would put one layer's files under the other's -D set and
    data dictionary, which is the bug qualifying exists to end.
    """
    layer = qualified_layer(component_id)
    if layer and layer in (cfg.get("layers") or {}):
        return layer
    want = name_ident(component_id)
    matches = []
    for layer_name, layer_cfg in (cfg.get("layers") or {}).items():
        for grp in ((layer_cfg or {}).get("groups") or {}).values():
            if isinstance(grp, dict) and any(name_ident(k) == want for k in grp):
                matches.append(layer_name)
                break
    return matches[0] if len(matches) == 1 else None


def resolve_group_id(groups: Dict[str, Any], requested: Optional[str]) -> tuple:
    """Resolve a requested group to its qualified id.

    Returns `(resolved_id_or_None, candidates)`. `candidates` holds every id the
    request matched, so a caller can tell the three cases apart:

      * one match   -> `(id, [id])`      generate that group
      * none        -> `(None, [])`      unknown group, list what exists
      * several     -> `(None, [a, b])`  AMBIGUOUS - two layers have this group name

    The third case is the whole point. Group ids are layer-qualified now, so
    `Support` may name `Layer1.Support` AND `Layer2.Support`; picking the first
    silently generated one layer's document under the other's name. The caller
    should refuse and print the candidates, and the user answers with either the
    qualified id (`--selected-group Layer1.Support`) or `--selected-layer`.

    Accepted spellings, in order: the exact id, the id case-insensitively, then
    the bare group NAME (`Support`, `My Sample`, `my-sample`) matched against every
    layer's groups. Comparison goes through `name_ident`, so spaces and case never
    decide the answer.
    """
    if not requested or not isinstance(groups, dict) or not groups:
        return None, []
    if requested in groups:
        return requested, [requested]

    want = name_ident(requested)
    exact = [k for k in groups if isinstance(k, str) and name_ident(k) == want]
    if len(exact) == 1:
        return exact[0], exact
    if exact:
        return None, sorted(exact)

    bare = [k for k in groups
            if isinstance(k, str) and name_ident(display_name(k)) == want]
    if len(bare) == 1:
        return bare[0], bare
    return None, sorted(bare)


def ambiguous_group_message(requested: str, candidates: List[str]) -> str:
    """The message for a group name that two or more layers both use.

    Names the qualified id rather than one entry point's flag: the same request
    arrives as `analyzer.py generate --scope "group:..."` and as
    `run.py --selected-group ...`, and quoting the wrong one sends the reader
    looking for a flag their command does not have.
    """
    return (f"Group {requested!r} is ambiguous - {len(candidates)} layers use that name: "
            f"{', '.join(candidates)}. Qualify it with the layer "
            f"(e.g. {candidates[0]!r}), or select the layer instead.")


def resolve_component_id(components, requested: Optional[str]) -> tuple:
    """Resolve a requested component to its qualified id. Same contract as
    `resolve_group_id` - `(resolved_or_None, candidates)`, several candidates
    meaning two layers both define a component with that name."""
    names = list(components or [])
    if not requested or not names:
        return None, []
    if requested in names:
        return requested, [requested]

    want = name_ident(requested)
    exact = [k for k in names if isinstance(k, str) and name_ident(k) == want]
    if len(exact) == 1:
        return exact[0], exact
    if exact:
        return None, sorted(exact)

    bare = [k for k in names
            if isinstance(k, str) and name_ident(display_name(k)) == want]
    if len(bare) == 1:
        return bare[0], bare
    return None, sorted(bare)


def get_layer_flat_groups(cfg: Dict[str, Any], layer_name: str) -> Dict[str, Any]:
    """Return flat groups for a single named layer, with layer paths resolved."""
    layer_cfg = (cfg.get("layers") or {}).get(layer_name)
    if not layer_cfg:
        return {}
    return _resolve_layer_paths({layer_name: layer_cfg})


# A layer may declare at most this many cores today. The config already stores
# `cores` as a LIST so multicore needs no config migration when it lands - only
# the scope resolution below changes. Until then a second core is refused rather
# than merged: two cores in one layer have different -D sets (one build defines
# _CONFIG_CMCORE, another does not), and merging them silently compiles a file
# under another core's macros.
MAX_CORES_PER_LAYER = 1


def get_layer_cores(cfg: Dict[str, Any], layer_name: str) -> List[str]:
    """Return the core names declared by `layers.<layer_name>.cores`."""
    layer_cfg = (cfg.get("layers") or {}).get(layer_name)
    if not isinstance(layer_cfg, dict):
        return []
    raw = layer_cfg.get("cores")
    if isinstance(raw, str):          # tolerate a single name written unwrapped
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [str(c) for c in raw if str(c).strip()]


# ---------------------------------------------------------------------------
# Layer-qualified identity
# ---------------------------------------------------------------------------
#
# Two layers may legitimately hold a group or a component with the SAME name -
# `FTL/Cache` and `HIL/Cache` are two different components, not a mistake. Every
# key the model builds starts from the component name (`unit_key` is
# `<component>|<unit>`, function and global ids extend it), so a bare name made
# them collide: the two layers' paths were merged into one component and one
# layer's files were parsed with the other's -D set.
#
# The layer is therefore part of the IDENTITY, and only the identity: a group id
# is `<Layer>.<Group>` and a component id is `<Layer>.<Component>`, while the
# document still shows the bare name. `interfaceId` already worked this way
# (`IF_LAYER1_SUPPORT_MATH_01`); this is the same fact, moved into the keys.
#
# The layer prefix is ALWAYS applied when the config has `layers`, whether or not
# a name is actually duplicated, so one project's keys have the same shape as
# every other's and adding a second layer never silently rewrites the first's.
# A legacy `layer` / `modulesGroups` config has no layer to qualify with and
# keeps bare ids.

LAYER_SEP = "."


def make_qualified_id(layer_name: Optional[str], name: str) -> str:
    """`<Layer>.<Name>`, or the bare identifier when there is no layer.

    The name half is passed through EXACTLY as configured, spaces included. Space
    normalization already happens where it is needed - `safe_filename`,
    `_resolve_component_from_rel`, the output-dir naming - and repeating it here
    would rename `My Sample` in the DOCX headings, which keep the configured
    spelling on purpose.
    """
    ident = (name or "").strip()
    layer = (layer_name or "").strip()
    return f"{layer}{LAYER_SEP}{ident}" if layer else ident


def split_qualified_id(qualified: str) -> tuple:
    """`("Layer1", "Core")` for a qualified id, `(None, "Core")` for a bare one.

    Splits on the FIRST separator: the layer name cannot contain one (refused by
    `validate_layer_names`), so anything after it belongs to the name.
    """
    text = (qualified or "").strip()
    if LAYER_SEP not in text:
        return None, text
    layer, _, name = text.partition(LAYER_SEP)
    return (layer or None), name


def qualified_layer(qualified: str) -> Optional[str]:
    """The layer a qualified group/component id belongs to, or None if bare."""
    return split_qualified_id(qualified)[0]


def display_name(qualified: str) -> str:
    """The bare name to SHOW - `Layer1.Sample-Core` -> `Sample-Core`.

    Never use this as a key: two layers can return the same string, which is the
    whole reason the id carries the layer.
    """
    return split_qualified_id(qualified)[1]


def core_source(cfg: Dict[str, Any], core_name: str, key: str) -> Optional[str]:
    """Return `cores.<core_name>.<key>` as a stripped path, or None."""
    core_cfg = (cfg.get("cores") or {}).get(core_name)
    if not isinstance(core_cfg, dict):
        return None
    raw = core_cfg.get(key)
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.strip()


def validate_cores(cfg: Dict[str, Any]) -> List[str]:
    """Return one message per problem with the `cores` / `layers.*.cores` wiring.

    Empty list means the config is usable. Checked up front so a typo'd core name
    fails loudly instead of parsing a layer with no macros and no dictionary.
    """
    errors: List[str] = []
    known = set((cfg.get("cores") or {}).keys())
    for layer_name in (cfg.get("layers") or {}):
        cores = get_layer_cores(cfg, layer_name)
        for core in cores:
            if core not in known:
                errors.append(
                    f"layers.{layer_name}.cores names unknown core {core!r}"
                    + (f". Defined cores: {', '.join(sorted(known))}" if known
                       else ". No `cores` section is defined"))
        if len(cores) > MAX_CORES_PER_LAYER:
            errors.append(
                f"layers.{layer_name}.cores lists {len(cores)} cores "
                f"({', '.join(cores)}); more than {MAX_CORES_PER_LAYER} per layer is "
                "not supported yet - macros and the data dictionary still resolve "
                "per layer, so a second core's -D flags would leak into the first's files")
    return errors


# ---------------------------------------------------------------------------
# Name-space validation for `layers`
# ---------------------------------------------------------------------------

def name_ident(name: str) -> str:
    """Identifier form of a config name - the form that survives downstream.

    Two rules collapse names on their way into keys, filenames and filters: a
    space becomes `-` everywhere a name becomes an identifier (see
    `safe_filename`, `_resolve_component_from_rel`, `_filter_model_to_components`),
    and every consumer that matches a group or component by name casefolds first
    (`_resolve_group_name`, the DOCX same-layer filter). Names that collapse to
    the same string here are indistinguishable to the pipeline, however different
    they look in the JSON.
    """
    return (name or "").strip().replace(" ", "-").casefold()


def _norm_cfg_path(path: str) -> str:
    """Repo-relative path in comparison form: '/' separators, no wrapping slashes."""
    return (path or "").replace("\\", "/").strip().strip("/").casefold()


def _fmt_owner(owner: tuple) -> str:
    """'Layer1/Support/Math' for a (layer, group, component) triple."""
    return "/".join(str(x) for x in owner if x)


def validate_layer_names(cfg: Dict[str, Any]) -> List[str]:
    """Return one message per name problem in the `layers` block.

    Empty list means the config is usable.

    **Two layers reusing a group or component name is NOT a problem** and is not
    reported: `FTL/Cache` and `HIL/Cache` are two different components, and every id
    is layer-qualified (`make_qualified_id`) so they no longer collide. What remains
    are the cases qualifying cannot fix, because the ambiguity is INSIDE one layer or
    in the paths rather than the names:

    * the same name twice in ONE layer - the layer prefix is identical, so
      `utils.init_component_mapping` still merges the two path lists into a single
      component and the first group listed takes it.
    * one path claimed by two components, or nested inside another component's path -
      `parser._build_file_component_map` uses `setdefault` and walks a directory
      entry recursively, so the first component in config order takes every file and
      the other silently gets none. This is the long-standing "each folder path
      appears in exactly one component" rule, enforced.
    * a name containing `LAYER_SEP` - ids are split on the FIRST separator, so a
      layer or component whose own name carries one cannot be taken apart again.
    * two layer names that collapse to the same identifier.

    A component named after a group is fine (the shipped config has `Access`,
    `Signal`, `Diag` as both) - the two are selected by different flags.
    """
    errors: List[str] = []
    layers = cfg.get("layers")
    if not isinstance(layers, dict) or not layers:
        return errors

    layer_names: Dict[str, List[str]] = {}
    path_owners: Dict[str, List[tuple]] = {}
    separator_hits: List[str] = []

    for layer_name, layer_cfg in layers.items():
        layer_names.setdefault(name_ident(layer_name), []).append(str(layer_name))
        if LAYER_SEP in str(layer_name):
            separator_hits.append(f"layer {layer_name!r}")
        if not isinstance(layer_cfg, dict):
            continue
        layer_path = str(layer_cfg.get("path") or layer_name)

        # Within ONE layer: group names, then component names across that layer's groups.
        group_idents: Dict[str, List[str]] = {}
        comp_idents: Dict[str, List[tuple]] = {}
        for group_name, comps in (layer_cfg.get("groups") or {}).items():
            group_idents.setdefault(name_ident(group_name), []).append(str(group_name))
            if LAYER_SEP in str(group_name):
                separator_hits.append(f"group {layer_name}/{group_name!r}")
            if not isinstance(comps, dict):
                continue
            for comp_name, paths in comps.items():
                comp_idents.setdefault(name_ident(comp_name), []).append((group_name, comp_name))
                if LAYER_SEP in str(comp_name):
                    separator_hits.append(f"component {layer_name}/{group_name}/{comp_name!r}")
                if isinstance(paths, str):
                    path_list = [paths]
                elif isinstance(paths, list):
                    path_list = [p for p in paths if isinstance(p, str)]
                else:
                    path_list = []
                for p in (path_list or [""]):
                    resolved = f"{layer_path}/{p}" if p else layer_path
                    path_owners.setdefault(_norm_cfg_path(resolved),
                                           []).append((layer_name, group_name, comp_name))

        for ident, names in sorted(group_idents.items()):
            if len(names) > 1:
                errors.append(
                    f"layer {layer_name!r} has {len(names)} groups that collapse to "
                    f"{ident!r} ({', '.join(repr(n) for n in names)}); a group name must be "
                    "unique WITHIN its layer - another layer may reuse it freely")
        for ident, owners in sorted(comp_idents.items()):
            if len(owners) > 1:
                where = ", ".join(f"{layer_name}/{g}/{c}" for g, c in owners)
                errors.append(
                    f"component name {ident!r} is used {len(owners)} times in layer "
                    f"{layer_name!r} ({where}); a component name must be unique WITHIN its "
                    "layer - the paths are merged into one component and only the first "
                    "group owns it. Another layer may reuse the name freely")

    for ident, names in sorted(layer_names.items()):
        if len(names) > 1:
            errors.append(
                f"layer names {', '.join(repr(n) for n in names)} collapse to the same "
                f"identifier {ident!r}; rename one - the layer is the prefix of every "
                "group and component id")

    for path, owners in sorted(path_owners.items()):
        distinct = sorted({_fmt_owner(o) for o in owners})
        if len(distinct) > 1:
            errors.append(
                f"path {path!r} is claimed by {len(distinct)} components "
                f"({', '.join(distinct)}); each path must belong to exactly one component - "
                "the first one in config order takes every file and the rest get none")

    sorted_paths = sorted(p for p in path_owners if p)
    for i, outer in enumerate(sorted_paths):
        prefix = outer + "/"
        for inner in sorted_paths[i + 1:]:
            if not inner.startswith(prefix):
                break
            outer_comps = {_fmt_owner(o) for o in path_owners[outer]}
            inner_comps = {_fmt_owner(o) for o in path_owners[inner]}
            if outer_comps == inner_comps:
                continue                     # one component listing a path twice: harmless
            errors.append(
                f"path {inner!r} ({', '.join(sorted(inner_comps))}) is nested inside "
                f"{outer!r} ({', '.join(sorted(outer_comps))}); a nested path is walked by "
                "both components and the first in config order silently takes the files")

    for hit in separator_hits:
        errors.append(
            f"{hit} contains {LAYER_SEP!r}, which separates the layer from the name in "
            "every group and component id; rename it")

    return errors


def layer_source(cfg: Dict[str, Any], layer_name: str, key: str) -> Optional[str]:
    """Return the path a layer resolves `key` (`dataDictionary`, `macros`) to.

    Resolution order:
      1. the layer's core - `cores.<core>.<key>`, via `layers.<layer>.cores`
      2. `layers.<layer_name>.<key>` directly (the pre-`cores` schema)

    The inputs live on the CORE because that is what actually owns them: a core
    is one build with one macro set and one dictionary, and a layer is the parse
    scope it feeds. The layer-level fallback keeps older configs - and the
    `--macros-layer` / `--data-dictionary-layer` flags that mirror them - working
    unchanged, so nothing outside this function had to learn about cores.
    """
    return layer_source_origin(cfg, layer_name, key)[0]


def layer_source_origin(cfg: Dict[str, Any], layer_name: str,
                        key: str) -> Tuple[Optional[str], Optional[str]]:
    """`layer_source`, plus where the path came from: the core's name, or "layer" for the
    pre-`cores` layer-level key. (None, None) when neither declares it."""
    for core in get_layer_cores(cfg, layer_name):
        path = core_source(cfg, core, key)
        if path:
            return path, core
    layer_cfg = (cfg.get("layers") or {}).get(layer_name)
    if not isinstance(layer_cfg, dict):
        return None, None
    raw = layer_cfg.get(key)
    if not isinstance(raw, str) or not raw.strip():
        return None, None
    return raw.strip(), "layer"


# What a core may declare. Nothing reads any other key under `cores.<name>`, so a typo such
# as `datadictionary` vanished without a word and the layer parsed with no dictionary.
CORE_KEYS = ("dataDictionary", "macros", "compileCommands")


def core_config_warnings(cfg: Dict[str, Any]) -> List[str]:
    """Config that is valid but silently ignored, one message each:

      * a key under `cores.<name>` that is not in CORE_KEYS - nothing reads it;
      * a core that no `layers.<layer>.cores` lists - its inputs reach no file;
      * a misspelled input key written directly on a layer (the pre-`cores` form).

    Warnings, not errors: the run is valid, it just is not using what the config seems to say.
    `validate_cores` already stops a run whose layer names a core that does not exist.
    """
    out: List[str] = []
    by_lower = {k.lower(): k for k in CORE_KEYS}
    layers = cfg.get("layers") or {}
    used = {core for name in layers for core in get_layer_cores(cfg, name)}
    for core, core_cfg in (cfg.get("cores") or {}).items():
        for key in (core_cfg if isinstance(core_cfg, dict) else {}):
            if key in CORE_KEYS:
                continue
            hint = by_lower.get(key.lower()) or next(
                iter(difflib.get_close_matches(key, CORE_KEYS, n=1)), None)
            out.append(f"cores.{core}.{key} is not a key anything reads"
                       + (f" - did you mean {hint!r}?" if hint
                          else f" (known: {', '.join(CORE_KEYS)})") + " It is ignored.")
        if core not in used:
            out.append(f"cores.{core} is listed by no layer (layers.<layer>.cores), "
                       "so its inputs are ignored.")
    for name, layer_cfg in layers.items():
        for key in (layer_cfg if isinstance(layer_cfg, dict) else {}):
            hint = by_lower.get(key.lower())
            if hint and key != hint:
                out.append(f"layers.{name}.{key} - did you mean {hint!r}? It is ignored.")
    return out


def missing_layer_inputs(cfg: Dict[str, Any], root: str, key: str) -> List[str]:
    """One message per layer whose `key` file does not exist. Relative paths resolve against
    `root` - the repo root, which is every phase's working directory."""
    out: List[str] = []
    for name in (cfg.get("layers") or {}):
        path, origin = layer_source_origin(cfg, name, key)
        if path and not os.path.isfile(path if os.path.isabs(path) else os.path.join(root, path)):
            where = f"cores.{origin}" if origin != "layer" else f"layers.{name}"
            out.append(f"{name}: {key} file not found: {path} (from {where}.{key})")
    return out


def layer_sources(cfg: Dict[str, Any], key: str) -> Dict[str, str]:
    """Return {layerName: path} for every layer declaring `key`.

    Layer order follows the config, which is what makes the per-source merge
    order in Phase 1 reproducible.
    """
    out: Dict[str, str] = {}
    for layer_name in (cfg.get("layers") or {}):
        path = layer_source(cfg, layer_name, key)
        if path:
            out[layer_name] = path
    return out


def components_groups() -> Dict[str, Any]:
    """Return flattened groups across all layers with paths resolved."""
    return get_flat_groups(app_config())
