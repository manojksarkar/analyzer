"""
LLM client for Ollama: function descriptions and flowcharts.
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


def _call_ollama(prompt: str, config: dict) -> str:
    """Call Ollama API (generate endpoint). Returns response text or empty on failure."""
    if not HAS_REQUESTS:
        print("Warning: requests not installed. pip install requests", file=sys.stderr)
        return ""
    base_url = (config.get("ollamaBaseUrl") or "http://localhost:11434").rstrip("/")
    model = config.get("ollamaModel") or "llama3.2"
    url = f"{base_url}/api/generate"
    try:
        r = requests.post(
            url,
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=config.get("ollamaTimeout", 60),
        )
        r.raise_for_status()
        data = r.json()
        return (data.get("response") or "").strip()
    except Exception as e:
        print(f"Ollama error: {e}", file=sys.stderr)
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


def get_flowchart(source: str, config: dict) -> str:
    """Get Mermaid flowchart from Ollama for the function logic."""
    if not source:
        return ""
    prompt = f"""Generate a Mermaid flowchart for this C++ function. Use flowchart TD or graph TD.
Show control flow: conditionals, loops, function calls. Output ONLY valid Mermaid code, no extra text.

```cpp
{source}
```

Mermaid flowchart:"""
    out = _call_ollama(prompt, config)
    # Try to extract ```mermaid ... ``` block if LLM wrapped it
    if "```" in out:
        parts = out.split("```")
        for i, p in enumerate(parts):
            if "mermaid" in p.lower() and i + 1 < len(parts):
                return parts[i + 1].strip()
            if p.strip().startswith(("flowchart", "graph")):
                return p.strip()
    return out


def enrich_functions_with_llm(
    functions_data: list,
    base_path: str,
    config: dict,
    *,
    descriptions: bool = True,
    flowcharts: bool = False,
) -> dict:
    """
    Add description and/or flowchart to each function. Returns dict function_id -> {description, flowchart}.
    """
    result = {}
    total = len(functions_data)
    for idx, f in enumerate(functions_data):
        fid = f.get("id", "")
        if ":" not in fid:
            continue
        loc = f.get("location", {})
        if not loc:
            continue
        source = extract_source(base_path, loc)
        desc = ""
        fc = ""
        if descriptions:
            desc = get_description(source, config)
            result[fid] = {"description": desc, "flowchart": ""}
        if flowcharts:
            fc = get_flowchart(source, config)
            if fid not in result:
                result[fid] = {"description": "", "flowchart": ""}
            result[fid]["flowchart"] = fc
        print(f"  LLM [{idx + 1}/{total}] {f.get('name', '?')}", file=sys.stderr)
    return result
