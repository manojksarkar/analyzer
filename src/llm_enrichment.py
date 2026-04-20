"""Prompt builders + enrichment loops used by Phase 2 (model_deriver) and Phase 4 (docx_exporter).

This module is NOT an LLM client. The only LLM client in the project lives at
src/llm_core/. This file owns the analyzer's prompts and enrichment logic,
and delegates every HTTP call to llm_core.LlmClient.

It provides:
  - extract_source / extract_source_line  : read function/global source by location
  - load_abbreviations                    : load abbreviations.txt
  - llm_provider_reachable                : is the configured provider reachable
  - get_description / get_global_description / get_unit_description /
    get_struct_description / get_behaviour_names
  - get_rich_description                  : budget-aware description with full context
  - enrich_functions_with_descriptions / enrich_globals_with_descriptions
  - enrich_functions_rich                 : budget-aware enrichment with degradation

Provider, headers, retry, think-section stripping and token tracking all live
in llm_core.LlmClient.
"""

import os
import sys
from typing import Dict, List, Optional

from utils import norm_path, short_name, load_llm_config
from core.logging_setup import get_logger
from core.progress import ProgressReporter

_log = get_logger("llm_enrichment")

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# Lazy import to avoid hard dependency at import time (e.g. when llm_core is
# being smoke-tested in isolation).
try:
    from llm_core.client import LlmClient
except ImportError:
    LlmClient = None  # type: ignore


# ---------------------------------------------------------------------------
# Source extraction
# ---------------------------------------------------------------------------

def load_abbreviations(project_root: str, config: dict) -> dict:
    """Load abbreviations from text file in config (llm.abbreviationsPath). Format: one per line, 'abbrev: meaning' or 'abbrev=meaning'; # = comment."""
    path = (config.get("llm") or {}).get("abbreviationsPath", "").strip()
    if not path:
        return {}
    full_path = os.path.join(project_root, path) if not os.path.isabs(path) else path
    if not os.path.isfile(full_path):
        return {}
    result = {}
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" in line:
                    k, _, v = line.partition(":")
                elif "=" in line:
                    k, _, v = line.partition("=")
                else:
                    continue
                k, v = k.strip(), v.strip()
                if k:
                    result[k] = v
        return result
    except OSError:
        return {}


def extract_source(base_path: str, loc: dict) -> str:
    """Extract function body from file using location line/endLine."""
    file_path = norm_path(loc["file"], base_path)
    if not os.path.isfile(file_path):
        return ""
    line_start = int(loc.get("line", 1))
    line_end = int(loc.get("endLine", line_start))
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except (IOError, OSError):
        return ""
    if line_start < 1 or line_end < line_start:
        return ""
    start_idx = max(0, line_start - 1)
    end_idx = min(len(lines), line_end)
    return "".join(lines[start_idx:end_idx]).strip()


def extract_source_line(base_path: str, loc: dict) -> str:
    """Extract single line from file (for globals, which have no endLine)."""
    file_path = norm_path(loc["file"], base_path)
    if not os.path.isfile(file_path):
        return ""
    line_num = int(loc.get("line", 1))
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except (IOError, OSError):
        return ""
    if line_num < 1 or line_num > len(lines):
        return ""
    return lines[line_num - 1].strip()


# ---------------------------------------------------------------------------
# LLM client cache (one client per process keyed on the resolved llm config)
# ---------------------------------------------------------------------------

_CLIENT_CACHE: Dict[str, "LlmClient"] = {}


def _client_cache_key(llm_cfg: dict) -> str:
    return "|".join([
        llm_cfg.get("provider", ""),
        llm_cfg.get("baseUrl", ""),
        llm_cfg.get("defaultModel", ""),
        str(llm_cfg.get("numCtx", "")),
        str(llm_cfg.get("retries", "")),
        str(llm_cfg.get("timeoutSeconds", "")),
    ])


def _get_client(config: dict) -> Optional["LlmClient"]:
    """Build or return a cached LlmClient for the resolved config."""
    if LlmClient is None:
        return None
    llm_cfg = load_llm_config(config)
    key = _client_cache_key(llm_cfg)
    cached = _CLIENT_CACHE.get(key)
    if cached is not None:
        return cached
    client = LlmClient(
        provider=llm_cfg["provider"],
        base_url=llm_cfg["baseUrl"],
        model=llm_cfg["defaultModel"],
        api_key=llm_cfg.get("apiKey"),
        custom_headers=llm_cfg.get("customHeaders") or {},
        timeout=llm_cfg["timeoutSeconds"],
        num_ctx=llm_cfg["numCtx"],
        max_retries=llm_cfg["retries"],
    )
    _CLIENT_CACHE[key] = client
    return client


def llm_provider_reachable(config: dict) -> bool:
    """Return True if the configured LLM provider is reachable.

    For ollama, ping /api/tags. For openai we cannot ping cheaply so we
    return True and rely on the per-call error handling in LlmClient.
    """
    if not HAS_REQUESTS or LlmClient is None:
        return False
    llm_cfg = load_llm_config(config)
    provider = llm_cfg["provider"]
    if provider == "openai":
        return True  # assume reachable; first call will surface any failure
    base_url = llm_cfg["baseUrl"]
    try:
        r = requests.get(f"{base_url}/api/tags", timeout=3)
        return r.status_code == 200
    except (requests.RequestException, OSError):
        return False


def _call_llm(prompt: str, config: dict, *, system: str = "", kind: str = "default") -> str:
    """Issue a single LLM call via the unified client. Returns "" on failure.

    Note: prompt/response tracing is centralized in LlmClient.generate()
    (controlled by the --trace-prompts CLI flag / LLM_TRACE_PROMPTS env var).
    """
    client = _get_client(config)
    if client is None:
        if not HAS_REQUESTS:
            _log.warning("requests not installed. pip install requests")
        return ""
    text = client.generate(system, prompt)
    if not text and client.provider == "ollama":
        _log.warning(
            "Ollama returned no response (prompt may exceed context window or "
            "ollama not running). Start with: ollama serve"
        )
    return text or ""


# ---------------------------------------------------------------------------
# Prompt builders / public LLM endpoints
# ---------------------------------------------------------------------------

def _format_abbreviations(abbreviations: dict) -> str:
    """Format abbreviations dict as prompt block."""
    if not abbreviations:
        return ""
    lines = [f"  {k}: {v}" for k, v in sorted(abbreviations.items()) if k and v]
    return "\n".join(lines) + "\n\n" if lines else ""


def _extract_target_keywords(func: dict, func_by_id: dict, callee_ids: set) -> set:
    """Derive keywords from a function for few-shot ranking.

    Keywords come from: function name tokens, return type, callee names,
    and parameter type tokens. Used to find relevant few-shot examples.
    """
    import re
    kws = set()

    # Function name → camelCase/snake_case tokens
    qn = func.get("qualifiedName", "") or ""
    simple = qn.split("::")[-1]
    for tok in re.findall(r"[A-Z][a-z]+|[a-z]+|[0-9]+", simple):
        if len(tok) > 2:
            kws.add(tok.lower())

    # Return type tokens
    rt = func.get("returnType", "") or ""
    for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", rt):
        if len(tok) > 2:
            kws.add(tok.lower())

    # Callee name tokens
    for cid in callee_ids:
        cf = func_by_id.get(cid)
        if cf:
            cqn = (cf.get("qualifiedName", "") or "").split("::")[-1]
            for tok in re.findall(r"[A-Z][a-z]+|[a-z]+", cqn):
                if len(tok) > 2:
                    kws.add(tok.lower())

    return kws


def get_description(source: str, config: dict, callee_descriptions: dict = None, abbreviations: dict = None) -> str:
    if not source:
        return ""

    context = ""
    if callee_descriptions:
        context_parts = []
        for callee_name, desc in callee_descriptions.items():
            if desc:
                context_parts.append(f" - {callee_name}: {desc}")
        if context_parts:
            context = "\n\nContext: This function calls the following functions:\n" + "\n".join(context_parts)

    abbrev_block = ""
    if abbreviations:
        formatted = _format_abbreviations(abbreviations)
        if formatted:
            abbrev_block = "\n\nAlso, consider the following abbreviations:\n\n" + formatted

    prompt = f"""Describe this C++ function in one short sentence (what it does, not how).{context}{abbrev_block}
```cpp
{source}
```

One-line description:"""
    return _call_llm(prompt, config, kind="description")


def get_global_description(source: str, config: dict, abbreviations: dict = None) -> str:
    if not source:
        return ""
    abbrev_block = ""
    if abbreviations:
        formatted = _format_abbreviations(abbreviations)
        if formatted:
            abbrev_block = "\n\nAlso, consider the following abbreviations:\n\n" + formatted
    prompt = f"""Describe this C++ global variable in one short sentence (what it stores or represents).{abbrev_block}

```cpp
{source}
```

One-line description:"""
    return _call_llm(prompt, config, kind="description")


def get_unit_description(
    unit_name: str,
    function_descriptions: list,
    global_descriptions: list,
    config: dict,
    abbreviations: dict = None,
) -> str:
    """Describe a unit from its functions/globals descriptions (summary for DOCX table)."""
    def _items_to_text(items: list) -> str:
        if not items:
            return ""
        # items: list[(name, description)]
        lines = []
        for name, desc in items:
            name = (name or "").strip()
            desc = (desc or "").strip()
            if not desc or desc in ("-", "N/A"):
                continue
            if name:
                lines.append(f" - {name}: {desc}")
            else:
                lines.append(f" - {desc}")
        return "\n".join(lines)

    abbrev_block = ""
    if abbreviations:
        lines = [f"  {k}: {v}" for k, v in sorted(abbreviations.items()) if k and v]
        if lines:
            abbrev_block = "\nConsider these abbreviations when interpreting names:\n" + "\n".join(lines) + "\n\n"

    fn_block = _items_to_text(function_descriptions)
    gv_block = _items_to_text(global_descriptions)
    if not (fn_block or gv_block):
        return ""

    prompt = f"""Given the following C++ function and global-variable descriptions that belong to this unit, write ONE short sentence summarizing what the unit does overall.
Be concrete but brief: at most ~25 words, no bullet list, no colon-separated catalog.

Unit name: {unit_name or '(unnamed)'}

Functions (descriptions):
{fn_block or '-'}

Globals (descriptions):
{gv_block or '-'}{abbrev_block}

One sentence:"""

    # Ensemble path: 3 temperatures + synthesis for higher-quality unit summaries.
    enrichment_cfg = (config.get("llm") or {}).get("enrichment") or {}
    if bool(enrichment_cfg.get("ensemble", False)):
        client = _get_client(config)
        if client is not None:
            try:
                from llm_core.review import ensemble_generate
                text = ensemble_generate(client, system="", user=prompt)
                if text:
                    return text
            except Exception as exc:  # pragma: no cover — defensive
                _log.debug("ensemble_generate for unit '%s' failed: %s", unit_name, exc)

    return _call_llm(prompt, config, kind="description")


def get_struct_description(struct_name: str, fields: list, config: dict, abbreviations: dict = None) -> str:
    """One-line description of a struct from its name and fields. Uses name + member variables, not name alone."""
    fields_part = ", ".join(f"{f.get('name', '')} ({f.get('type', '')})" for f in (fields or []) if f.get("name"))
    if not struct_name and not fields_part:
        return "Structure (unnamed, no fields)."
    abbrev_block = ""
    if abbreviations:
        lines = [f"  {k}: {v}" for k, v in sorted(abbreviations.items()) if k and v]
        if lines:
            abbrev_block = "\nConsider these abbreviations when interpreting names:\n" + "\n".join(lines) + "\n\n"
    prompt = f"""Describe this C/C++ structure in one short sentence. Use both the structure name and the member variables to infer what it represents. Do not rely only on the name—the fields are important.{abbrev_block}
Struct name: {struct_name or '(unnamed)'}
Fields: {fields_part or 'none'}

One-line description:"""
    return _call_llm(prompt, config, kind="description")


def get_behaviour_names(
    source: str,
    params: list,
    globals_read: list,
    globals_written: list,
    return_type: str,
    return_expr: str,
    draft_input: str,
    draft_output: str,
    config: dict,
    abbreviations: dict = None,
) -> dict:
    """Ask LLM for short human-readable Input Name and Output Name. Uses abbreviations.
    globals_read: list of globals this function reads (input side).
    globals_written: list of globals this function writes (output side).
    Returns {"behaviourInputName": str, "behaviourOutputName": str}; may be empty if parse fails.
    """
    if not source:
        return {}
    params_part = ", ".join(f"{p.get('name', '')} ({p.get('type', '')})" for p in (params or []) if p.get("name") or p.get("type"))

    def _globals_block(label: str, glist: list) -> str:
        if not glist:
            return ""
        lines = []
        for g in glist:
            name = g.get("name") or (g.get("qualifiedName") or "").split("::")[-1]
            typ = g.get("type", "")
            desc = (g.get("description") or "").strip()
            lines.append(f"  - {name} ({typ})" + (f": {desc}" if desc else ""))
        return "\n" + label + "\n" + "\n".join(lines)

    globals_read_part = _globals_block("Globals read (inputs):", globals_read or [])
    globals_written_part = _globals_block("Globals written (outputs):", globals_written or [])

    abbrev_block = ""
    if abbreviations:
        formatted = _format_abbreviations(abbreviations)
        if formatted:
            abbrev_block = "\n\nUse these abbreviations when naming (expand to full phrase where relevant):\n\n" + formatted
    prompt = f"""Given this C++ function, suggest two short human-readable labels for documentation:
1) Input Name: what this behaviour takes as input (parameters + globals it reads).
2) Output Name: what it produces (return value or globals it writes).

{abbrev_block}
Function:
```cpp
{source}
```
Parameters: {params_part or 'none'}
Return type: {return_type or 'void'}
Return expression: {return_expr or 'none'}{globals_read_part}{globals_written_part}

Current draft labels (improve if they are generic or code-like): Input="{draft_input or ''}", Output="{draft_output or ''}"

Reply with exactly two lines in this format (no other text):
Input Name: <short phrase>
Output Name: <short phrase>"""
    raw = _call_llm(prompt, config, kind="behaviour_names")
    if not raw:
        return {}
    result = {}
    for line in raw.split("\n"):
        line = line.strip()
        if line.lower().startswith("input name:"):
            result["behaviourInputName"] = line[11:].strip()
        elif line.lower().startswith("output name:"):
            result["behaviourOutputName"] = line[12:].strip()
    return result


def _make_canonical_key(f: dict) -> str:
    """Stable key file:line for LLM result lookup."""
    loc = f.get("location", {})
    return f"{loc.get('file', '')}:{loc.get('line', '')}"


def _enrich_functions_loop(funcs: list, base_path: str, config: dict, processor_fn, result_key: str, label: str) -> dict:
    func_by_key = {}
    for f in funcs:
        func_by_key[f["id"]] = f

    calls_map = {}
    for f in funcs:
        calls_map[f["id"]] = set(f.get("callsIds", []))

    processed = set()
    result = {}
    order = []

    all_keys = set(func_by_key.keys())

    while len(processed) < len(all_keys):
        ready = []
        for key in all_keys - processed:
            callees = calls_map.get(key, set())
            if callees.issubset(processed):
                ready.append(key)

        if not ready:
            ready = list(all_keys - processed)

        for key in ready:
            order.append(key)
            processed.add(key)

    progress = ProgressReporter(label, total=len(order), logger=_log)
    progress.start()
    for idx, key in enumerate(order):
        f = func_by_key.get(key)
        if not f:
            continue

        loc = f.get("location", {})
        source = extract_source(base_path, loc)

        callee_descriptions = {}
        for callee_key in calls_map.get(key, set()):
            callee_f = func_by_key.get(callee_key)
            if callee_f:
                callee_name = callee_f.get("qualifiedName", "").split("::")[-1]
                callee_desc = result.get(callee_key, {}).get(result_key, "")
                if callee_desc:
                    callee_descriptions[callee_name] = callee_desc

        val = processor_fn(source, config, callee_descriptions)
        result[key] = {result_key: val}
        progress.step(label=short_name(f.get("qualifiedName", "")) or "?")
    progress.done(summary=f"{len(result)} described")
    return result


def enrich_functions_with_descriptions(functions_data: list, base_path: str, config: dict) -> dict:
    if not llm_provider_reachable(config):
        _log.warning("LLM provider not reachable. Start Ollama (ollama serve) or check openai gateway settings.")
        return {}
    abbreviations = load_abbreviations(base_path, config)
    processor = lambda source, cfg, callee: get_description(source, cfg, callee, abbreviations)
    return _enrich_functions_loop(functions_data, base_path, config, processor, "description", "LLM-description")


def _enrich_globals_loop(globals_list: list, base_path: str, config: dict, processor_fn, result_key: str, label: str) -> dict:
    result = {}
    progress = ProgressReporter(label, total=len(globals_list), logger=_log)
    progress.start()
    for idx, g in enumerate(globals_list):
        loc = g.get("location", {})
        if not loc:
            continue
        key = _make_canonical_key(g)
        source = extract_source_line(base_path, loc)
        val = processor_fn(source, config)
        result[key] = {result_key: val}
        progress.step(label=short_name(g.get("qualifiedName", "")) or "?")
    progress.done(summary=f"{len(result)} described")
    return result


def enrich_globals_with_descriptions(globals_data: list, base_path: str, config: dict) -> dict:
    if not llm_provider_reachable(config):
        return {}
    abbreviations = load_abbreviations(base_path, config)
    processor = lambda source, cfg: get_global_description(source, cfg, abbreviations)
    return _enrich_globals_loop(globals_data, base_path, config, processor, "description", "LLM-global")


# ---------------------------------------------------------------------------
# Rich description — budget-aware, multi-section prompt
# ---------------------------------------------------------------------------

# System prompt for rich function descriptions
_RICH_DESCRIPTION_SYSTEM = """\
You are a senior C++ software engineer writing documentation.

Describe this function in 1-3 concise sentences focused on intent and purpose.
Do not narrate line-by-line. Do not repeat the function signature.
State WHAT the function does, not HOW it does it.

If the function reads or writes global state, mention the side effects.
If caller context is provided, use it to understand this function's role
in the larger system.
"""


def get_rich_description(
    source: str,
    config: dict,
    *,
    qualified_name: str = "",
    callee_context: str = "",
    caller_context: str = "",
    repo_map: str = "",
    types_globals: str = "",
    sibling_context: str = "",
    few_shot: str = "",
    abbreviations: dict = None,
) -> str:
    """Generate a function description using full budget-aware context.

    This is the upgraded version of get_description() that assembles richer
    context: callees, callers, repo map, types/globals, siblings.  Each
    section is pre-fitted to its token budget by the caller using
    ContextBuilder and RepoMap.

    Parameters
    ----------
    source : str
        Full function source code.
    config : dict
        Top-level config dict (used to build/cache LLM client).
    qualified_name : str
        Fully qualified function name (for prompt context).
    callee_context : str
        Pre-assembled callee context text (from ContextBuilder.fit_callees).
    caller_context : str
        Pre-assembled caller context text (from ContextBuilder.fit_callers).
    repo_map : str
        Pre-assembled repo map text (from RepoMap.for_function).
    types_globals : str
        Pre-assembled types + globals text (from ContextBuilder).
    sibling_context : str
        Pre-assembled sibling functions text.
    abbreviations : dict
        Abbreviation mappings.

    Returns
    -------
    str
        The generated description, or "" on failure.
    """
    if not source:
        return ""

    # Build user prompt with all available sections
    parts: List[str] = []

    if few_shot:
        parts.append(few_shot)

    if qualified_name:
        parts.append(f"Function: {qualified_name}")

    if repo_map:
        parts.append(f"\n[Repo Map]\n{repo_map}")

    parts.append(f"\n[Function Source]\n```cpp\n{source}\n```")

    if callee_context:
        parts.append(f"\n{callee_context}")

    if caller_context:
        parts.append(f"\n{caller_context}")

    if types_globals:
        parts.append(f"\n{types_globals}")

    if sibling_context:
        parts.append(f"\n{sibling_context}")

    if abbreviations:
        formatted = _format_abbreviations(abbreviations)
        if formatted:
            parts.append(f"\n[Abbreviations]\n{formatted}")

    parts.append("\nDescription:")

    user_prompt = "\n".join(parts)
    return _call_llm(user_prompt, config, system=_RICH_DESCRIPTION_SYSTEM, kind="description")


def _get_refined_description(
    source: str,
    config: dict,
    *,
    qualified_name: str = "",
    prior_description: str = "",
    callee_context: str = "",
    caller_context: str = "",
    repo_map: str = "",
    types_globals: str = "",
    abbreviations: dict = None,
) -> str:
    """Pass 2 refinement: revise a description given caller context.

    Called only when twoPassDescriptions is enabled. Uses the prior
    description from Pass 1 plus caller descriptions (now available)
    to produce a more accurate description.
    """
    if not source or not prior_description:
        return prior_description or ""

    system = """\
You are a senior C++ software engineer refining function documentation.

A previous analysis described this function. You now have additional context
about WHO calls this function and WHY. Revise the description if the caller
context reveals a more accurate purpose. Keep it 1-3 sentences.

If the previous description is already accurate and complete, return it unchanged.
Do not add filler or qualifications just to look different.
"""

    parts: List[str] = []
    if qualified_name:
        parts.append(f"Function: {qualified_name}")

    parts.append(f"\n[Previous Description]\n{prior_description}")

    if repo_map:
        parts.append(f"\n[Repo Map]\n{repo_map}")

    parts.append(f"\n[Function Source]\n```cpp\n{source}\n```")

    if callee_context:
        parts.append(f"\n{callee_context}")

    if caller_context:
        parts.append(f"\n{caller_context}")

    if types_globals:
        parts.append(f"\n{types_globals}")

    if abbreviations:
        formatted = _format_abbreviations(abbreviations)
        if formatted:
            parts.append(f"\n[Abbreviations]\n{formatted}")

    parts.append("\nRevised description:")

    return _call_llm("\n".join(parts), config, system=system, kind="description")


def get_rich_global_description(
    source: str,
    config: dict,
    *,
    qualified_name: str = "",
    write_sites: str = "",
    read_sites: str = "",
    containing_file_context: str = "",
    related_functions: str = "",
    abbreviations: dict = None,
) -> str:
    """Generate a global variable description using rich context.

    Upgraded version of get_global_description() that includes read/write
    sites rather than just the declaration line.
    """
    if not source:
        return ""

    parts: List[str] = []

    if qualified_name:
        parts.append(f"Global variable: {qualified_name}")

    parts.append(f"\n[Declaration]\n```cpp\n{source}\n```")

    if write_sites:
        parts.append(f"\n[Written by]\n{write_sites}")

    if read_sites:
        parts.append(f"\n[Read by]\n{read_sites}")

    if containing_file_context:
        parts.append(f"\n[Containing File]\n{containing_file_context}")

    if related_functions:
        parts.append(f"\n[Related Functions]\n{related_functions}")

    if abbreviations:
        formatted = _format_abbreviations(abbreviations)
        if formatted:
            parts.append(f"\n[Abbreviations]\n{formatted}")

    parts.append("\nOne-line description:")

    system = (
        "You are a senior C++ engineer. Describe this global variable in one "
        "short sentence: what it stores, what purpose it serves. Use the "
        "write/read site context to understand how it is used."
    )
    return _call_llm("\n".join(parts), config, system=system, kind="description")


def _build_function_context(
    key: str,
    func_by_id: dict,
    calls_map: dict,
    result: dict,
    knowledge,
    builder,
    repo_map_builder,
    counter,
    budget,
):
    """Build all context sections for one function (shared by Pass 1 and Pass 2)."""
    from llm_core.context_builder import ContextItem

    f = func_by_id[key]
    qn = f.get("qualifiedName", "")

    # --- Callee context (budget-aware) ---
    callee_items = []
    for callee_id in calls_map.get(key, set()):
        callee_f = func_by_id.get(callee_id)
        if not callee_f:
            continue
        callee_qn = callee_f.get("qualifiedName", "")
        callee_desc = result.get(callee_id, {}).get("description", "")
        if knowledge and callee_qn in knowledge.functions:
            fk = knowledge.functions[callee_qn]
            callee_sig = fk.signature or callee_qn
        else:
            callee_sig = callee_f.get("signature", callee_qn)
        callee_items.append(ContextItem(
            name=callee_qn,
            signature=callee_sig,
            description=callee_desc or callee_f.get("description", ""),
            priority=1.0,
        ))
    callee_text = builder.fit_callees(callee_items, budget.allocate("callees")) if callee_items else ""

    # --- Caller context ---
    caller_items = []
    for caller_id in f.get("calledByIds", []):
        caller_f = func_by_id.get(caller_id)
        if not caller_f:
            continue
        caller_qn = caller_f.get("qualifiedName", "")
        caller_desc = result.get(caller_id, {}).get("description", "")
        if knowledge and caller_qn in knowledge.functions:
            fk = knowledge.functions[caller_qn]
            caller_sig = fk.signature or caller_qn
        else:
            caller_sig = caller_f.get("signature", caller_qn)
        caller_items.append(ContextItem(
            name=caller_qn,
            signature=caller_sig,
            description=caller_desc or caller_f.get("description", ""),
            priority=1.0,
        ))
    caller_text = builder.fit_callers(caller_items, budget.allocate("callers")) if caller_items else ""

    # --- Repo map ---
    map_text = ""
    if repo_map_builder and qn:
        map_text = repo_map_builder.for_function(qn, budget.allocate("repo_map"), counter)

    # --- Types + globals context ---
    type_global_items = []
    if knowledge and qn in knowledge.functions:
        fk = knowledge.functions[qn]
        for gid in (fk.reads_globals or []) + (fk.writes_globals or []):
            gk = knowledge.globals.get(gid)
            if gk:
                type_global_items.append(ContextItem(
                    name=gk.qualified_name,
                    signature=f"{gk.qualified_name} : {gk.var_type}",
                    description=gk.description or "",
                    priority=0.8,
                ))
    types_text = builder.fit_globals(type_global_items, budget.allocate("types_globals")) if type_global_items else ""

    # --- Sibling functions (same file) ---
    sibling_text = ""
    if knowledge and qn in knowledge.functions:
        fk = knowledge.functions[qn]
        sibling_items = []
        for sib_qn, sib_fk in knowledge.functions.items():
            if sib_fk.file == fk.file and sib_qn != qn:
                sibling_items.append(ContextItem(
                    name=sib_qn,
                    signature=sib_fk.signature or sib_qn,
                    description=sib_fk.description or "",
                    priority=0.5,
                ))
        sibling_text = builder.fit_siblings(sibling_items, budget.allocate("siblings")) if sibling_items else ""

    return callee_text, caller_text, map_text, types_text, sibling_text


# ---------------------------------------------------------------------------
# Self-review helpers (used by the enrichment loop when selfReview=true)
# ---------------------------------------------------------------------------

def _should_self_review(source: str, *, min_lines: int = 20) -> bool:
    """Return True if *source* is substantial enough to warrant a 3x-cost review.

    Self-review triples the LLM call budget, so it only applies to functions
    whose body has at least *min_lines* non-blank lines — trivial wrappers get
    a single-pass description.
    """
    if not source:
        return False
    non_blank = sum(1 for ln in source.splitlines() if ln.strip())
    return non_blank >= min_lines


def _run_self_review(
    config: dict,
    *,
    draft: str,
    source: str,
    callee_context: str = "",
    caller_context: str = "",
) -> str:
    """Run the generate→review→revise cycle via the cached LlmClient.

    Returns the revised description on success, or the original *draft* on
    any failure (so callers can assign unconditionally).
    """
    client = _get_client(config)
    if client is None:
        return draft
    try:
        from llm_core.review import self_review as _sr
    except ImportError:
        return draft

    evidence_parts: List[str] = [f"[Function Source]\n{source}"]
    if callee_context:
        evidence_parts.append(callee_context)
    if caller_context:
        evidence_parts.append(caller_context)
    evidence = "\n\n".join(evidence_parts)

    try:
        result = _sr(client, draft=draft, evidence=evidence)
    except Exception as exc:  # pragma: no cover — defensive
        _log.debug("self_review failed: %s", exc)
        return draft
    return result or draft


def enrich_functions_rich(
    functions_data: dict,
    base_path: str,
    config: dict,
    knowledge=None,
) -> dict:
    """Budget-aware function description enrichment with optional two-pass.

    Pass 1 (always): bottom-up order, each function sees callee descriptions.
    Pass 2 (when enrichment.twoPassDescriptions=true): same order, but now
    both callee AND caller descriptions from Pass 1 are available. Uses a
    refinement prompt that compares the prior description against caller context.

    Parameters
    ----------
    functions_data : dict
        The full functions_data dict from model (keyed by function ID).
    base_path : str
        Project base path for source extraction.
    config : dict
        Top-level config dict.
    knowledge : ProjectKnowledge, optional
        If provided, used to build repo map, callee/caller/types context.

    Returns
    -------
    dict
        Mapping function_id → {"description": str}.
    """
    if not llm_provider_reachable(config):
        _log.warning("LLM provider not reachable for rich enrichment.")
        return {}

    from llm_core.token_counter import get_counter
    from llm_core.budget import ContextBudget, resolve_max_tokens
    from llm_core.context_builder import ContextBuilder
    from llm_core.repo_map import RepoMap
    from llm_core.few_shot import FewShotPool
    from llm_core.cache import EntityCache

    llm_cfg = load_llm_config(config)
    abbreviations = load_abbreviations(base_path, config)
    counter = get_counter(llm_cfg.get("defaultModel", ""))
    max_tokens = resolve_max_tokens(llm_cfg)
    builder = ContextBuilder(counter)
    repo_map_builder = RepoMap(knowledge) if knowledge else None

    # Few-shot pool (resolves to empty string if examples dir missing)
    fs_dir_cfg = (config.get("llm") or {}).get("fewShotExamplesDir", "few_shot_examples")
    fs_dir = fs_dir_cfg if os.path.isabs(fs_dir_cfg) else os.path.join(base_path, fs_dir_cfg)
    few_shot_pool = FewShotPool(fs_dir)

    # Entity cache for description results
    cache_version = int(llm_cfg.get("cacheVersion", 1))
    cache_dir = os.path.join(base_path, ".flowchart_cache", "llm_descriptions")
    entity_cache = EntityCache(cache_dir, cache_version=cache_version)
    # Track content hashes for dependency-tracked cache keys
    source_hashes: Dict[str, str] = {}

    # Check if two-pass is enabled
    enrichment_cfg = (config.get("llm") or {}).get("enrichment") or {}
    two_pass = bool(enrichment_cfg.get("twoPassDescriptions", True))
    self_review_enabled = bool(enrichment_cfg.get("selfReview", False))

    # Build topological order (callees before callers)
    func_by_id = {}
    calls_map = {}
    for key, f in functions_data.items():
        func_by_id[key] = f
        calls_map[key] = set(f.get("callsIds", []))

    processed = set()
    order = []
    all_keys = set(func_by_id.keys())
    while len(processed) < len(all_keys):
        ready = [k for k in all_keys - processed if calls_map.get(k, set()).issubset(processed)]
        if not ready:
            ready = list(all_keys - processed)
        for key in ready:
            order.append(key)
            processed.add(key)

    # Skip functions that already have a source comment
    order = [k for k in order if not func_by_id.get(k, {}).get("description")]

    # ── Pass 1: initial descriptions (bottom-up) ──
    result = {}
    progress = ProgressReporter("LLM-description-pass1", total=len(order), logger=_log)
    progress.start()

    for key in order:
        f = func_by_id.get(key)
        if not f:
            continue
        loc = f.get("location", {})
        source = extract_source(base_path, loc)
        if not source:
            progress.step(label="skip")
            continue

        qn = f.get("qualifiedName", "")
        budget = ContextBudget(max_tokens=max_tokens, task="function_description", counter=counter)
        callee_text, caller_text, map_text, types_text, sibling_text = _build_function_context(
            key, func_by_id, calls_map, result, knowledge, builder, repo_map_builder, counter, budget,
        )

        # Few-shot examples: tag keywords derived from callees + return type
        tags = _extract_target_keywords(f, func_by_id, calls_map.get(key, set()))
        few_shot_text = few_shot_pool.select("descriptions", tags, budget.allocate("few_shot"), counter)

        # Compute composite cache hash: source + sorted callee hashes
        source_hash = EntityCache.compute_hash(source)
        source_hashes[key] = source_hash
        callee_hashes = [source_hashes[cid] for cid in calls_map.get(key, set()) if cid in source_hashes]
        cache_hash = EntityCache.compute_hash(
            source + "|pass1|" + (qn or ""),
            dependency_hashes=callee_hashes,
        )
        cached = entity_cache.get(qn or key, cache_hash)
        if cached:
            result[key] = {"description": cached}
            progress.step(label=short_name(qn) or "?")
            continue

        desc = get_rich_description(
            source, config,
            qualified_name=qn,
            callee_context=callee_text,
            caller_context=caller_text,
            repo_map=map_text,
            types_globals=types_text,
            sibling_context=sibling_text,
            few_shot=few_shot_text,
            abbreviations=abbreviations,
        )

        # Self-review (only when two-pass is disabled — otherwise Pass 2 handles it)
        if (
            desc
            and self_review_enabled
            and not two_pass
            and _should_self_review(source)
        ):
            reviewed = _run_self_review(
                config, draft=desc, source=source,
                callee_context=callee_text, caller_context=caller_text,
            )
            if reviewed:
                desc = reviewed

        result[key] = {"description": desc}
        if desc:
            entity_cache.put(qn or key, cache_hash, desc, metadata={"pass": 1})
        progress.step(label=short_name(qn) or "?")

    progress.done(summary=f"{len(result)} described (pass 1) — cache: {entity_cache.stats()}")

    # ── Pass 2: refine with full caller context ──
    if two_pass and result:
        _log.info("Starting pass 2 — refining %d descriptions with caller context", len(order))
        progress2 = ProgressReporter("LLM-description-pass2", total=len(order), logger=_log)
        progress2.start()

        for key in order:
            f = func_by_id.get(key)
            if not f:
                continue
            prior = result.get(key, {}).get("description", "")
            if not prior:
                progress2.step(label="skip")
                continue

            loc = f.get("location", {})
            source = extract_source(base_path, loc)
            if not source:
                progress2.step(label="skip")
                continue

            qn = f.get("qualifiedName", "")
            budget = ContextBudget(
                max_tokens=max_tokens, task="function_description_refined", counter=counter,
            )
            callee_text, caller_text, map_text, types_text, _ = _build_function_context(
                key, func_by_id, calls_map, result, knowledge, builder, repo_map_builder, counter, budget,
            )

            # Pass 2 cache key includes caller IDs (caller context is what changes between passes)
            caller_ids = f.get("calledByIds", [])
            caller_hashes = [source_hashes[cid] for cid in caller_ids if cid in source_hashes]
            pass2_hash = EntityCache.compute_hash(
                source + "|pass2|" + (qn or "") + "|" + (prior or ""),
                dependency_hashes=caller_hashes + [source_hashes.get(key, "")],
            )
            cached = entity_cache.get(qn or key, pass2_hash)
            if cached:
                result[key] = {"description": cached}
                progress2.step(label=short_name(qn) or "?")
                continue

            refined = _get_refined_description(
                source, config,
                qualified_name=qn,
                prior_description=prior,
                callee_context=callee_text,
                caller_context=caller_text,
                repo_map=map_text,
                types_globals=types_text,
                abbreviations=abbreviations,
            )

            # Self-review after Pass 2 refinement for non-trivial functions
            if (
                refined
                and self_review_enabled
                and _should_self_review(source)
            ):
                reviewed = _run_self_review(
                    config, draft=refined, source=source,
                    callee_context=callee_text, caller_context=caller_text,
                )
                if reviewed:
                    refined = reviewed

            if refined:
                result[key] = {"description": refined}
                entity_cache.put(qn or key, pass2_hash, refined, metadata={"pass": 2})
            progress2.step(label=short_name(qn) or "?")

        progress2.done(summary=f"{len(result)} refined (pass 2) — cache: {entity_cache.stats()}")

    return result


def enrich_globals_rich(
    globals_data: dict,
    functions_data: dict,
    base_path: str,
    config: dict,
    knowledge=None,
) -> dict:
    """Budget-aware global variable description enrichment.

    Uses write/read site context to produce richer descriptions.

    Parameters
    ----------
    globals_data : dict
        Global variables from the model (keyed by qualified name or canonical key).
    functions_data : dict
        Functions data for extracting read/write site context.
    base_path : str
        Project base path.
    config : dict
        Top-level config dict.
    knowledge : ProjectKnowledge, optional
        If provided, used for rich read/write site context.

    Returns
    -------
    dict
        Mapping canonical_key → {"description": str}.
    """
    if not llm_provider_reachable(config):
        return {}

    from llm_core.token_counter import get_counter
    from llm_core.budget import ContextBudget, resolve_max_tokens
    from llm_core.context_builder import ContextBuilder, ContextItem

    llm_cfg = load_llm_config(config)
    abbreviations = load_abbreviations(base_path, config)
    counter = get_counter(llm_cfg.get("defaultModel", ""))
    max_tokens = resolve_max_tokens(llm_cfg)
    builder = ContextBuilder(counter)

    globals_list = list(globals_data.values()) if isinstance(globals_data, dict) else globals_data
    result = {}
    progress = ProgressReporter("LLM-rich-global", total=len(globals_list), logger=_log)
    progress.start()

    for g in globals_list:
        loc = g.get("location", {})
        if not loc:
            progress.step(label="skip")
            continue

        key = _make_canonical_key(g)
        source = extract_source_line(base_path, loc)
        if not source:
            progress.step(label="skip")
            continue

        qn = g.get("qualifiedName", "")
        budget = ContextBudget(max_tokens=max_tokens, task="variable_description", counter=counter)

        # Build write-site context
        write_sites = ""
        read_sites = ""
        if knowledge and qn in knowledge.globals:
            gk = knowledge.globals[qn]
            # Writers
            write_parts = []
            for writer_qn in (gk.written_by or [])[:5]:
                fk = knowledge.functions.get(writer_qn)
                if fk:
                    desc = fk.description or ""
                    write_parts.append(f"  {writer_qn}: {desc}" if desc else f"  {writer_qn}")
            write_sites = "\n".join(write_parts) if write_parts else ""

            # Readers
            read_parts = []
            for reader_qn in (gk.read_by or [])[:5]:
                fk = knowledge.functions.get(reader_qn)
                if fk:
                    desc = fk.description or ""
                    read_parts.append(f"  {reader_qn}: {desc}" if desc else f"  {reader_qn}")
            read_sites = "\n".join(read_parts) if read_parts else ""

        desc = get_rich_global_description(
            source,
            config,
            qualified_name=qn,
            write_sites=write_sites,
            read_sites=read_sites,
            abbreviations=abbreviations,
        )
        result[key] = {"description": desc}
        progress.step(label=short_name(qn) or "?")

    progress.done(summary=f"{len(result)} described")
    return result
