"""
LLM client for Ollama: function descriptions.
Extracts source on-demand from file:line:endLine (no body in metadata).
"""
import os
import sys

from utils import load_config, norm_path

# Optional: use requests for HTTP, with fallback
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


def extract_source(base_path: str, loc: dict) -> str:
    """Extract function body from source file using location line/endLine."""
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


def _ollama_available(config: dict) -> bool:
    """Quick check if Ollama is reachable."""
    if not HAS_REQUESTS:
        return False
    base_url = config["ollamaBaseUrl"].rstrip("/")
    try:
        r = requests.get(f"{base_url}/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _call_ollama(prompt: str, config: dict) -> str:
    """Call Ollama API (generate endpoint). Returns response text or empty on failure."""
    if not HAS_REQUESTS:
        print("Warning: requests not installed. pip install requests", file=sys.stderr)
        return ""
    base_url = config["ollamaBaseUrl"].rstrip("/")
    url = f"{base_url}/api/generate"
    try:
        r = requests.post(
            url,
            json={"model": config["ollamaModel"], "prompt": prompt, "stream": False},
            timeout=config["ollamaTimeout"],
        )
        r.raise_for_status()
        data = r.json()
        return (data.get("response") or "").strip()
    except Exception as e:
        print(f"Ollama error: {e}", file=sys.stderr)
        print("  -> Is Ollama running? Start with: ollama serve", file=sys.stderr)
        return ""


def get_description(source: str, config: dict) -> str:
    """Get one-line function description from Ollama."""
    if not source:
        return ""
    prompt = f"""Describe this C++ function in one short sentence (what it does, not how):

```cpp
{source}
```

One-line description:"""
    return _call_ollama(prompt, config)


def _make_canonical_key(f: dict) -> str:
    """Use location file:line as stable key (avoids path separator issues)."""
    loc = f.get("location", {})
    return f"{loc.get('file', '')}:{loc.get('line', '')}"


def enrich_functions_with_descriptions(
    functions_data: list,
    base_path: str,
    config: dict,
) -> dict:
    """
    Add description to each function via Ollama.
    Returns dict canonical_key -> {description}. Use _make_canonical_key for lookup.
    """
    if not _ollama_available(config):
        print("  Ollama not reachable. Start with: ollama serve", file=sys.stderr)
        return {}

    result = {}
    total = len(functions_data)
    for idx, f in enumerate(functions_data):
        loc = f.get("location", {})
        if not loc:
            continue
        key = _make_canonical_key(f)
        source = extract_source(base_path, loc)
        desc = get_description(source, config)
        result[key] = {"description": desc}
        print(f"  LLM [{idx + 1}/{total}] {f.get('name', '?')}", file=sys.stderr)
    return result
