"""Ollama LLM: descriptions. Direction is derived in parser (global read/write)."""
import os
import sys

from utils import norm_path, short_name


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

# Optional: use requests for HTTP, with fallback
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


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


def _get_llm_config(config: dict) -> dict:
    """Read llm block from config (baseUrl, defaultModel, timeoutSeconds)."""
    llm = config.get("llm") or {}
    return {
        "baseUrl": (llm.get("baseUrl") or "http://localhost:11434").rstrip("/"),
        "defaultModel": llm.get("defaultModel") or "llama3.2",
        "timeoutSeconds": int(llm.get("timeoutSeconds", 60)),
    }


def _ollama_available(config: dict) -> bool:
    if not HAS_REQUESTS:
        return False
    cfg = _get_llm_config(config)
    base_url = cfg["baseUrl"]
    try:
        r = requests.get(f"{base_url}/api/tags", timeout=3)
        return r.status_code == 200
    except (requests.RequestException, OSError):
        return False


def _call_ollama(prompt: str, config: dict, *, kind: str = "default") -> str:
    if not HAS_REQUESTS:
        print("Warning: requests not installed. pip install requests", file=sys.stderr)
        return ""
    cfg = _get_llm_config(config)
    base_url = cfg["baseUrl"]
    model = cfg["defaultModel"]
    url = f"{base_url}/api/generate"
    try:
        r = requests.post(
            url,
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=cfg["timeoutSeconds"],
        )
        r.raise_for_status()
        data = r.json()
        return (data.get("response") or "").strip()
    except (requests.RequestException, OSError) as e:
        print(f"Ollama error: {e}", file=sys.stderr)
        print("  -> Is Ollama running? Start with: ollama serve", file=sys.stderr)
        return ""


def _format_abbreviations(abbreviations: dict) -> str:
    """Format abbreviations dict as prompt block."""
    if not abbreviations:
        return ""
    lines = [f"  {k}: {v}" for k, v in sorted(abbreviations.items()) if k and v]
    return "\n".join(lines) + "\n\n" if lines else ""


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
    return _call_ollama(prompt, config, kind="description")


def get_global_description(source: str, config: dict) -> str:
    if not source:
        return ""
    prompt = f"""Describe this C++ global variable in one short sentence (what it stores or represents):

```cpp
{source}
```

One-line description:"""
    return _call_ollama(prompt, config, kind="description")


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
    return _call_ollama(prompt, config, kind="description")


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
    raw = _call_ollama(prompt, config, kind="behaviour_names")
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

    for idx, key in enumerate(order):
        f = func_by_key.get(key)
        if not f:
            continue

        loc = f.get("location", {})
        source = extract_source(base_path, loc)

        callee_descriptions = {}
        for callee_key in calls_map.get(key,set()):
            callee_f = func_by_key.get(callee_key)
            if callee_f:
                callee_name = callee_f.get("qualifiedName", "").split("::")[-1]
                callee_desc = result.get(callee_key, {}).get(result_key, "")
                if callee_desc:
                    callee_descriptions[callee_name] = callee_desc
        
        val = processor_fn(source, config, callee_descriptions)
        result[key] = {result_key: val}
        print(f"  {label} [{idx + 1}/{len(order)}] {short_name(f.get('qualifiedName', '')) or '?'}", end="\r", flush=True, file=sys.stderr)
    print(file=sys.stderr)
    return result


def enrich_functions_with_descriptions(functions_data: list, base_path: str, config: dict) -> dict:
    if not _ollama_available(config):
        print("  Ollama not reachable. Start with: ollama serve", file=sys.stderr)
        return {}
    abbreviations = load_abbreviations(base_path, config)
    processor = lambda source, cfg, callee: get_description(source, cfg, callee, abbreviations)
    return _enrich_functions_loop(functions_data, base_path, config, processor, "description", "LLM-description")


def _enrich_globals_loop(globals_list: list, base_path: str, config: dict, processor_fn, result_key: str, label: str) -> dict:
    result = {}
    for idx, g in enumerate(globals_list):
        loc = g.get("location", {})
        if not loc:
            continue
        key = _make_canonical_key(g)
        source = extract_source_line(base_path, loc)
        val = processor_fn(source, config)
        result[key] = {result_key: val}
        print(f"  {label} [{idx + 1}/{len(globals_list)}] {short_name(g.get('qualifiedName', '')) or '?'}", end="\r", flush=True, file=sys.stderr)
    print(file=sys.stderr)
    return result


def enrich_globals_with_descriptions(globals_data: list, base_path: str, config: dict) -> dict:
    if not _ollama_available(config):
        return {}
    return _enrich_globals_loop(globals_data, base_path, config, get_global_description, "description", "LLM-global")
