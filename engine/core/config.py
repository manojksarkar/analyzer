"""Cached, typed accessors for the analyzer configuration.

All values still live in `config/config.json` (and `config.local.json`) so the
user can change anything by editing the JSON file. This module:
  1. Parses JSONC (JSON with // and /* */ comments and trailing commas).
  2. Loads + merges config.json + config.local.json once per process.
  3. Resolves the LLM config block, applying environment-variable overrides.
  4. Provides typed helpers (llm_config, views_config, exporter_config,
     components_groups) so call sites stop typing `cfg.get("llm", {}).get(...)`.
  5. Re-exports the raw dict via `app_config()` for code that still wants the
     dict-style access.

This module is the bottom of the dependency graph for configuration; nothing
in `core/` may import from analyzer-level modules (utils.py, etc.).
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict, List, Optional

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
    config.local.json can override a single nested key (e.g. ``llm.customHeaders`` or
    ``llm.baseUrl``) without restating the whole ``llm`` block."""
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def load_config(project_root: str) -> Dict[str, Any]:
    """Load config from <project_root>/config/config.defaults.json, then config.local.json overrides.

    Callers pass the directory that *contains* ``config/``. Since the config now
    lives under ``engine/config/``, engine callers pass the engine dir
    (``paths().src_dir``), not the repo root.

    If the ``ANALYZER_CONFIG`` environment variable points to a file, that file
    is loaded **instead**, as the complete self-contained per-run config — no
    ``config.local.json`` merge. This is how a per-project / per-version config
    (carrying the project's ``layers``) is injected into the analyzer and every
    phase subprocess, which inherit the env var. ``config.local.json`` is
    intentionally skipped so the injected config is fully reproducible (a dev's
    local overrides do not bleed into a per-project run). See ``run.py --config``.
    A set-but-missing path fails loud rather than silently falling back.
    """
    override = os.environ.get("ANALYZER_CONFIG", "").strip()
    if override:
        if not os.path.isfile(override):
            raise FileNotFoundError(
                f"ANALYZER_CONFIG points to a missing file: {override}"
            )
        with open(override, "r", encoding="utf-8") as f:
            stripped = _strip_trailing_commas(_strip_json_comments(f.read()))
        return json.loads(stripped)

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
    return config


class LlmConfigError(ValueError):
    """Raised when llm config has missing or invalid required fields.

    Strict validation: rather than falling back to silent defaults, the
    analyzer surfaces the exact field that is wrong so the user can fix
    the config (config.defaults.json / config.local.json) or the matching env var and re-run.
    """


def load_llm_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve and STRICTLY validate the llm config block.

    Required fields (no silent defaults — raises LlmConfigError if missing
    or invalid):
        provider          - "ollama" | "openai"
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
        rateLimitSeconds  - float >= 0, default 3.0 (pause after every OpenAI
                            call to satisfy the gateway throttle; 0 disables
                            it; ignored on Ollama)
        enrichment        - dict of feature toggles (each must be a bool):
            twoPassDescriptions (default True)
            selfReview          (default False)
            ensemble            (default False)
            cfgSimplification   (default False)
            variableEnrichment  (default True)
        cacheVersion      - int >= 1 (bump to invalidate entity cache)
        rateLimitSeconds  - float >= 0, pause after each OpenAI call (0 = none)
        fewShotExamplesDir - str (default "few_shot_examples")

    Environment variables (override the matching config field if set):
        LLM_PROVIDER, LLM_BASE_URL, LLM_DEFAULT_MODEL,
        LLM_TIMEOUT_SECONDS, LLM_NUM_CTX, LLM_RETRIES, LLM_API_KEY,
        LLM_RATE_LIMIT_SECONDS

    Raises
    ------
    LlmConfigError
        If a required field is missing, empty, or not parseable.
    """
    if not config or not isinstance(config, dict):
        raise LlmConfigError("config is empty or not a JSON object")

    llm = config.get("llm")
    if not isinstance(llm, dict) or not llm:
        raise LlmConfigError("config has no 'llm' block")

    def _env_or(key: str, fallback):
        v = os.environ.get(key)
        return v if v is not None and v != "" else fallback

    def _require_str(field: str, env_var: str) -> str:
        raw = _env_or(env_var, llm.get(field))
        if raw is None or str(raw).strip() == "":
            raise LlmConfigError(
                f"Missing required llm.{field} (or env {env_var}) in the llm config"
            )
        return str(raw).strip()

    def _require_pos_int(field: str, env_var: str) -> int:
        raw = _env_or(env_var, llm.get(field))
        if raw is None or raw == "":
            raise LlmConfigError(
                f"Missing required llm.{field} (or env {env_var}) in the llm config"
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
    if provider not in ("ollama", "openai"):
        raise LlmConfigError(
            f"llm.provider must be 'ollama' or 'openai' (got {provider!r})"
        )

    base_url = _require_str("baseUrl", "LLM_BASE_URL").rstrip("/")
    model = _require_str("defaultModel", "LLM_DEFAULT_MODEL")
    timeout = _require_pos_int("timeoutSeconds", "LLM_TIMEOUT_SECONDS")
    num_ctx = _require_pos_int("numCtx", "LLM_NUM_CTX")

    # retries is required but allowed to be 0
    retries_raw = _env_or("LLM_RETRIES", llm.get("retries"))
    if retries_raw is None or retries_raw == "":
        raise LlmConfigError(
            "Missing required llm.retries (or env LLM_RETRIES) in the llm config"
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

    # rateLimitSeconds: pause after every OpenAI call, including failed ones, because the
    # corporate gateway throttles ~1 request per 3 seconds. 0 disables the throttle entirely.
    # Ollama is not gateway-throttled and never sleeps, so this is an OpenAI-only knob.
    #
    # The two on-prem deployments need opposite values (doc 09, B6): the API **gateway**
    # enforces that global limit, while an on-prem **hosted model** has none and 3s per call
    # would dominate the run. Default 3.0 keeps the gateway safe for anyone who does not set it.
    rate_limit_raw = _env_or("LLM_RATE_LIMIT_SECONDS",
                             llm.get("rateLimitSeconds", 3.0))
    if rate_limit_raw is None or rate_limit_raw == "":
        raise LlmConfigError(
            "llm.rateLimitSeconds must be a number — "
            "use 0 to disable the throttle"
        )
    try:
        rate_limit = float(rate_limit_raw)
    except (TypeError, ValueError):
        raise LlmConfigError(
            f"llm.rateLimitSeconds must be a number (got {rate_limit_raw!r})"
        )
    if rate_limit < 0:
        raise LlmConfigError(
            f"llm.rateLimitSeconds must be >= 0 (got {rate_limit})"
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
        "rateLimitSeconds": rate_limit,
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
        f"({'used' if llm_cfg.get('provider') == 'ollama' else 'ignored on openai'})",
        f"  maxContextTokens  : {max_ctx_display}",
        f"  timeoutSeconds    : {llm_cfg.get('timeoutSeconds')}",
        f"  retries           : {llm_cfg.get('retries')}",
        # Surfaced because it silently dominates wall-clock: at 3s a 20k-call run spends
        # ~17 hours asleep. The operator should see which mode this run is in — and that it
        # does nothing at all on ollama.
        f"  rateLimitSeconds  : {llm_cfg.get('rateLimitSeconds')}"
        f"{'  (no throttle)' if not llm_cfg.get('rateLimitSeconds') else '  (per process)'}"
        f"{'' if llm_cfg.get('provider') == 'openai' else '  (ignored on ollama)'}",
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
            _CACHED = load_config(paths().src_dir)
        return _CACHED


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
    for core in get_layer_cores(cfg, layer_name):
        path = core_source(cfg, core, key)
        if path:
            return path
    layer_cfg = (cfg.get("layers") or {}).get(layer_name)
    if not isinstance(layer_cfg, dict):
        return None
    raw = layer_cfg.get(key)
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.strip()


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
