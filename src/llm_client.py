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
    except Exception:
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


def get_direction_label(source: str, config: dict, *, callees: list = None, callers: list = None) -> str:
    if not source:
        return "-"
    ctx = []
    if callees:
        ctx.append(f"Calls: {', '.join(short_name(c) for c in callees[:10])}")
    if callers:
        ctx.append(f"Called by: {', '.join(short_name(c) for c in callers[:10])}")
    context_block = "\n".join(ctx) + "\n\n" if ctx else ""

    prompt = f"""You are classifying the external interface *direction* of this C++ function.
Convention: Get (read from global data) = Out; Set (write to global data) = In. Both read and write (e.g. init) = In. No In/Out.

Classify as exactly ONE of: In, Out, -

Call graph context:
{context_block}Function:
```cpp
{source}
```

Answer with exactly one of: In, Out, -
"""
    raw = _call_ollama(prompt, config, kind="direction").strip()
    if not raw:
        return "-"
    text = raw.lower()
    if "in/out" in text or text.startswith("in/out"):
        return "In"  # both -> In
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
        return "In"
    return "-"

def _make_canonical_key(f: dict) -> str:
    """Stable key file:line for LLM result lookup."""
    loc = f.get("location", {})
    return f"{loc.get('file', '')}:{loc.get('line', '')}"


def _enrich_functions_loop(funcs: list, base_path: str, config: dict, processor_fn, result_key: str, label: str, show_val: bool = False, functions_by_fid: dict = None) -> dict:
    result = {}
    for idx, f in enumerate(funcs):
        loc = f.get("location", {})
        if not loc:
            continue
        key = _make_canonical_key(f)
        source = extract_source(base_path, loc)
        callee_names = []
        caller_names = []
        if functions_by_fid:
            for cid in (f.get("callsIds") or []):
                callee_names.append(functions_by_fid.get(cid, {}).get("qualifiedName", cid))
            for cid in (f.get("calledByIds") or []):
                caller_names.append(functions_by_fid.get(cid, {}).get("qualifiedName", cid))
        if processor_fn == get_direction_label:
            val = processor_fn(source, config, callees=callee_names, callers=caller_names)
        else:
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


def enrich_functions_with_direction(functions_data: list, base_path: str, config: dict, functions_by_fid: dict = None) -> dict:
    """Enrich functions with direction via LLM. Pass functions_by_fid {fid: func} for call graph context."""
    if not _ollama_available(config):
        print("  Ollama not reachable. Start with: ollama serve", file=sys.stderr)
        return {}
    return _enrich_functions_loop(functions_data, base_path, config, get_direction_label, "direction", "LLM-dir", show_val=True, functions_by_fid=functions_by_fid)
