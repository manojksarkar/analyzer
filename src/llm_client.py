"""Ollama LLM: descriptions. Direction is derived in parser (global read/write)."""
import os
import sys

from utils import norm_path, short_name

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


def get_description(source: str, config: dict, callee_descriptions: dict = None) -> str:
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

    prompt = f"""Describe this C++ function in one short sentence (what it does, not how).{context}

Also, consider the following abbreviations:


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
    return _enrich_functions_loop(functions_data, base_path, config, get_description, "description", "LLM-description")


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
