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
    # 0-based index
    start_idx = max(0, line_start - 1)
    end_idx = min(len(lines), line_end)
    return "".join(lines[start_idx:end_idx]).strip()


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


def get_description(source: str, config: dict) -> str:
    if not source:
        return ""
    prompt = f"""Describe this C++ function in one short sentence (what it does, not how):

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
    result = {}
    for idx, f in enumerate(funcs):
        loc = f.get("location", {})
        if not loc:
            continue
        key = _make_canonical_key(f)
        source = extract_source(base_path, loc)
        val = processor_fn(source, config)
        result[key] = {result_key: val}
        print(f"  {label} [{idx + 1}/{len(funcs)}] {short_name(f.get('qualifiedName', '')) or '?'}", end="\r", flush=True, file=sys.stderr)
    print(file=sys.stderr)
    return result


def enrich_functions_with_descriptions(functions_data: list, base_path: str, config: dict) -> dict:
    if not _ollama_available(config):
        print("  Ollama not reachable. Start with: ollama serve", file=sys.stderr)
        return {}
    return _enrich_functions_loop(functions_data, base_path, config, get_description, "description", "LLM-description")
