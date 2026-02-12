"""Ollama LLM: descriptions, direction."""
import os
import sys

from utils import load_config, norm_path, short_name

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
    """Normalize llm block or legacy ollama* keys into single config dict."""
    llm = config.get("llm") or {}
    if llm:
        base_url = (llm.get("baseUrl") or "http://localhost:11434").rstrip("/")
        default_model = llm.get("defaultModel") or "llama3.2"
        cfg = {
            "baseUrl": base_url,
            "defaultModel": default_model,
            "descriptionModel": llm.get("descriptionModel") or default_model,
            "directionModel": llm.get("directionModel") or default_model,
            "flowchartModel": llm.get("flowchartModel") or default_model,
            "timeoutSeconds": int(llm.get("timeoutSeconds", 60)),
        }
        return cfg
    # Legacy fallback
    base_url = (config.get("ollamaBaseUrl") or "http://localhost:11434").rstrip("/")
    default_model = config.get("ollamaModel") or "llama3.2"
    return {
        "baseUrl": base_url,
        "defaultModel": default_model,
        "descriptionModel": default_model,
        "directionModel": default_model,
        "flowchartModel": default_model,
        "timeoutSeconds": int(config.get("ollamaTimeout", 60)),
    }


def _ollama_available(config: dict) -> bool:
    if not HAS_REQUESTS:
        return False
    cfg = _get_llm_config(config)
    base_url = cfg["baseUrl"]
    try:
        r = requests.get(f"{base_url}/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _call_ollama(prompt: str, config: dict, *, kind: str = "default") -> str:
    if not HAS_REQUESTS:
        print("Warning: requests not installed. pip install requests", file=sys.stderr)
        return ""
    cfg = _get_llm_config(config)
    base_url = cfg["baseUrl"]
    if kind == "description":
        model = cfg["descriptionModel"]
    elif kind == "direction":
        model = cfg["directionModel"]
    elif kind == "flowchart":
        model = cfg["flowchartModel"]
    else:
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
    except Exception as e:
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


def get_direction_label(source: str, config: dict) -> str:
    if not source:
        return "-"
    prompt = f"""You are classifying the external interface *direction* of this C++ function
from the perspective of its callers.

Classify it as exactly ONE of:
- In        (primarily consumes inputs; does not mainly produce outputs or change shared state)
- Out       (primarily produces/returns data or writes to shared state / output parameters)
- In/Out    (both consumes inputs and produces outputs or changes shared state)
- -         (cannot determine)

Function:
```cpp
{source}
```

Answer with exactly one of: In, Out, In/Out, -.
"""
    raw = _call_ollama(prompt, config, kind="direction").strip()
    if not raw:
        return "-"
    text = raw.lower()
    if "in/out" in text:
        return "In/Out"
    if text.startswith("in/out"):
        return "In/Out"
    if text.startswith("in " ) or text == "in":
        return "In"
    if text.startswith("out") or text == "out":
        return "Out"
    if text.startswith("-"):
        return "-"
    # Fallback: first token
    first = text.split()[0]
    if first in ("in", "in,", "in."):
        return "In"
    if first in ("out", "out,", "out."):
        return "Out"
    if "in/out" in first:
        return "In/Out"
    return "-"

def _make_canonical_key(f: dict) -> str:
    """Stable key file:line for LLM result lookup."""
    loc = f.get("location", {})
    return f"{loc.get('file', '')}:{loc.get('line', '')}"


def _enrich_functions_loop(funcs: list, base_path: str, config: dict, processor_fn, result_key: str, label: str, show_val: bool = False) -> dict:
    result = {}
    for idx, f in enumerate(funcs):
        loc = f.get("location", {})
        if not loc:
            continue
        key = _make_canonical_key(f)
        source = extract_source(base_path, loc)
        val = processor_fn(source, config)
        result[key] = {result_key: val}
        suffix = f" -> {val}" if show_val else ""
        print(f"  {label} [{idx + 1}/{len(funcs)}] {short_name(f.get('qualifiedName', '')) or '?'}{suffix}", file=sys.stderr)
    return result


def enrich_functions_with_descriptions(functions_data: list, base_path: str, config: dict) -> dict:
    if not _ollama_available(config):
        print("  Ollama not reachable. Start with: ollama serve", file=sys.stderr)
        return {}
    return _enrich_functions_loop(functions_data, base_path, config, get_description, "description", "LLM")


def enrich_functions_with_direction(functions_data: list, base_path: str, config: dict) -> dict:
    if not _ollama_available(config):
        print("  Ollama not reachable. Start with: ollama serve", file=sys.stderr)
        return {}
    return _enrich_functions_loop(functions_data, base_path, config, get_direction_label, "direction", "LLM-dir", show_val=True)
