#!/usr/bin/env python3
"""Is the LLM gateway actually answering? Reads the real config and sends a few prompts.

The pipeline reports "returned empty response" and retries, which tells you nothing about WHY.
This sends the same requests through the same client the phases use, and prints what the
gateway sent back — status, `finish_reason`, the `usage` block, and the raw body when the
content is empty. Those are the fields `_call_openai` currently discards.

Three prompts, deliberately different sizes, because an empty reply that depends on size is a
token-budget problem and one that does not is a gateway/model problem:

  1. tiny        — "reply OK"; proves connectivity, auth and model name
  2. realistic   — a function-description prompt, the shape Phase 2 sends
  3. large       — ~2.5k tokens, the shape the flowchart labeller sends in batches

    python tools/check_llm.py                 # all three
    python tools/check_llm.py --raw           # print full response bodies
    python tools/check_llm.py --max-tokens N  # try a different output budget

No writes, no database, no pipeline state — safe to run at any time.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, "engine")]

_SEP = "-" * 78

_DESC_SYSTEM = ("You are a senior C++ engineer writing ASPICE software detailed design "
                "documentation. Answer with one plain sentence, no preamble.")
_DESC_USER = """Describe what this function does, in one sentence.

```cpp
int calculateChecksum(const uint8_t* data, size_t len) {
    uint32_t sum = 0;
    for (size_t i = 0; i < len; ++i) { sum += data[i]; }
    return static_cast<int>(sum & 0xFFFF);
}
```"""


def _big_prompt() -> str:
    """~2.5k tokens — the size the flowchart labeller reported failing on."""
    block = ("    int step%d = compute(input[%d]);\n"
             "    if (step%d > threshold) { accumulate(step%d); }\n")
    body = "".join(block % (i, i, i, i) for i in range(120))
    return ("Label each node of this control-flow graph with a short imperative phrase. "
            "Reply as JSON: {\"n1\": \"...\", \"n2\": \"...\"}.\n\n```cpp\nvoid process() {\n"
            + body + "}\n```\n\nNodes: n1, n2, n3, n4, n5")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", action="store_true", help="print full response bodies")
    ap.add_argument("--max-tokens", type=int, default=None,
                    help="override the output budget (the client hardcodes 2048)")
    ap.add_argument("--only", type=int, default=None, help="run only prompt N (1-3)")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    import requests
    from core.config import load_config, load_llm_config

    cfg = load_config(os.path.join(_ROOT, "engine"))
    try:
        llm = load_llm_config(cfg)
    except Exception as exc:
        print(f"config error: {exc}")
        return 2

    provider = llm.get("provider")
    base_url = (llm.get("baseUrl") or "").rstrip("/")
    model = llm.get("defaultModel")
    api_key = llm.get("apiKey") or ""
    headers = dict(llm.get("customHeaders") or {})
    timeout = int(llm.get("timeoutSeconds") or 120)
    rate = float(llm.get("rateLimitSeconds") or 0)
    max_tokens = args.max_tokens or 2048

    print(_SEP)
    print("LLM CONFIGURATION (as the pipeline resolves it)")
    print(_SEP)
    print(f"  provider          : {provider}")
    print(f"  baseUrl           : {base_url}")
    print(f"  defaultModel      : {model}")
    print(f"  timeoutSeconds    : {timeout}")
    print(f"  rateLimitSeconds  : {rate}")
    print(f"  numCtx            : {llm.get('numCtx')}")
    print(f"  maxContextTokens  : {llm.get('maxContextTokens')}")
    print(f"  apiKey            : {'set (' + str(len(api_key)) + ' chars)' if api_key else 'NOT SET'}")
    print(f"  customHeaders     : {sorted(headers) if headers else 'none'}")
    print(f"  max_tokens sent   : {max_tokens}"
          + ("" if args.max_tokens else "   <- hardcoded in client.py, not configurable"))
    print()

    if provider != "openai":
        print(f"NOTE: provider is {provider!r}; this probe exercises the OpenAI path only.")
        return 2

    url = f"{base_url}/chat/completions" if not base_url.endswith("/chat/completions") else base_url
    hdrs = {"Content-Type": "application/json", **headers}
    if api_key:
        hdrs["Authorization"] = f"Bearer {api_key}"

    prompts = [
        ("1. tiny", "Reply with exactly: OK", "You are a test endpoint."),
        ("2. realistic (function description)", _DESC_USER, _DESC_SYSTEM),
        ("3. large (~2.5k tokens, flowchart-labeller size)", _big_prompt(),
         "You label control-flow graphs."),
    ]
    if args.only:
        prompts = [prompts[args.only - 1]]

    failures = 0
    for label, user, system in prompts:
        print(_SEP)
        print(label)
        print(_SEP)
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": 0.1,
            "max_tokens": max_tokens,
        }
        approx = (len(system) + len(user)) // 4
        print(f"  prompt size : {len(system) + len(user)} chars (~{approx} tokens)")
        t0 = time.perf_counter()
        try:
            resp = requests.post(url, headers=hdrs, json=payload, timeout=timeout)
        except Exception as exc:
            print(f"  TRANSPORT FAILURE: {type(exc).__name__}: {exc}")
            failures += 1
            continue
        dt = time.perf_counter() - t0
        print(f"  http status : {resp.status_code}   ({dt:.1f}s)")

        if resp.status_code != 200:
            print(f"  BODY: {resp.text[:1500]}")
            failures += 1
            continue

        try:
            data = resp.json()
        except Exception:
            print(f"  response was not JSON: {resp.text[:500]}")
            failures += 1
            continue

        choices = data.get("choices") or []
        usage = data.get("usage") or {}
        print(f"  usage       : prompt={usage.get('prompt_tokens')} "
              f"completion={usage.get('completion_tokens')} total={usage.get('total_tokens')}")
        if not choices:
            print("  NO CHOICES returned — the gateway accepted the request and sent nothing.")
            print(f"  BODY: {json.dumps(data)[:1500]}")
            failures += 1
            continue

        ch = choices[0]
        msg = ch.get("message") or {}
        content = (msg.get("content") or "").strip()
        finish = ch.get("finish_reason")
        print(f"  finish_reason: {finish}")
        # Reasoning models put the answer elsewhere on some gateways; name what IS present.
        other = [k for k in msg if k not in ("role", "content") and msg.get(k)]
        if other:
            print(f"  other message fields present: {other}")
        print(f"  content     : {len(content)} chars")
        if content:
            print(f"  -> {content[:300]}")
        else:
            failures += 1
            print("  EMPTY CONTENT — this is the pipeline's 'returned empty response'.")
            if finish == "length":
                print("     finish_reason=length: the output budget was consumed before any "
                      "answer was produced. For a reasoning model that means reasoning ate")
                print(f"     all {max_tokens} tokens. Retry with --max-tokens 8192 to confirm.")
            print(f"  FULL MESSAGE: {json.dumps(msg)[:1200]}")
        if args.raw:
            print(f"  RAW: {json.dumps(data, indent=2)[:4000]}")
        if rate > 0:
            time.sleep(rate)
        print()

    print(_SEP)
    if failures:
        print(f"RESULT: {failures} of {len(prompts)} prompt(s) failed.")
        print("If only the LARGE prompt failed, it is a size/budget problem.")
        print("If ALL failed with finish_reason=length, raise max_tokens.")
        print("If ALL failed with no choices or a non-200, it is the gateway/model/auth.")
    else:
        print(f"RESULT: all {len(prompts)} prompt(s) answered. The gateway is working; "
              "the pipeline's empty responses come from somewhere else.")
    print(_SEP)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
