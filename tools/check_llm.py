#!/usr/bin/env python3
"""Is the LLM actually answering? Reads the real config and sends a few prompts.

The pipeline reports "returned empty response" and retries, which tells you nothing about WHY.
This sends the requests the phases send — to the OpenAI-compatible gateway or to Ollama,
whichever `llmServer.provider` names — and prints what came back: status, the stop reason, token
counts, and the raw body when the answer is empty. Those are the fields the client discards.

Three prompts, deliberately different sizes, because an empty reply that depends on size is a
token-budget problem and one that does not is a gateway/model problem:

  1. tiny        — "reply OK"; proves connectivity, auth and model name
  2. description — a function-description prompt, the shape Phase 2 sends
  3. large       — ~2.5k tokens, the shape the flowchart labeller sends in batches

    python tools/check_llm.py                     # all three
    python tools/check_llm.py --only description  # one prompt, by name or number (1-3)
    python tools/check_llm.py --raw               # print full response bodies
    python tools/check_llm.py --max-tokens N      # try a different output budget

With `llmServer.lanes` (several tickets or keys, llm_core/pool.py) the tiny prompt goes to EVERY
lane -- it is the one that proves a ticket -- and the result names each lane that did not answer.
The other two go once, on a lane that answered: what they show is the model's, not a ticket's.

On Ollama it also says when the model saw only part of a prompt (Ollama cuts what does not fit
`numCtx`, without an error) and how long loading the model took (it counts against the timeout).

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

_PROMPT_NAMES = ("tiny", "description", "large")

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


def _only(value: str) -> int:
    """`--only` takes a prompt's name or its number: 1/tiny, 2/description, 3/large."""
    v = value.strip().lower()
    if v in _PROMPT_NAMES:
        return _PROMPT_NAMES.index(v) + 1
    if v.isdigit() and 1 <= int(v) <= len(_PROMPT_NAMES):
        return int(v)
    raise argparse.ArgumentTypeError(
        f"no prompt {value!r}; use 1-{len(_PROMPT_NAMES)} or {', '.join(_PROMPT_NAMES)}")


def _openai_payload(model: str, system: str, user: str, max_tokens: int) -> dict:
    return {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.1,
        "max_tokens": max_tokens,
    }


def _ollama_payload(model: str, num_ctx: int, system: str, user: str, max_tokens: int) -> dict:
    """The body `LlmClient._call_ollama` sends, field for field."""
    return {
        "model": model,
        "system": system or "",
        "prompt": user,
        "stream": False,
        "options": {
            "num_ctx": num_ctx,
            "temperature": 0.1,
            "top_p": 0.9,
            "num_predict": max_tokens,
        },
    }


def _read_openai(data: dict, max_tokens: int) -> bool:
    """Print what an OpenAI-shaped reply holds. True when it carries an answer."""
    choices = data.get("choices") or []
    usage = data.get("usage") or {}
    print(f"  usage       : prompt={usage.get('prompt_tokens')} "
          f"completion={usage.get('completion_tokens')} total={usage.get('total_tokens')}")
    if not choices:
        print("  NO CHOICES returned — the gateway accepted the request and sent nothing.")
        print(f"  BODY: {json.dumps(data)[:1500]}")
        return False

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
        return True
    print("  EMPTY CONTENT — this is the pipeline's 'returned empty response'.")
    if finish == "length":
        print("     finish_reason=length: the output budget was consumed before any "
              "answer was produced. For a reasoning model that means reasoning ate")
        print(f"     all {max_tokens} tokens. Retry with --max-tokens 8192 to confirm.")
    print(f"  FULL MESSAGE: {json.dumps(msg)[:1200]}")
    return False


def _read_ollama(data: dict, approx: int, max_tokens: int) -> bool:
    """Print what an Ollama reply holds. True when the whole prompt got an answer."""
    text = (data.get("response") or "").strip()
    thinking = (data.get("thinking") or "").strip()
    done = data.get("done_reason")
    seen = data.get("prompt_eval_count")
    print(f"  tokens      : prompt={seen} completion={data.get('eval_count')}")
    load = (data.get("load_duration") or 0) / 1e9
    if load >= 1:
        print(f"  model load  : {load:.1f}s of that   <- counts against timeoutSeconds")
    print(f"  done_reason : {done}")
    if thinking:
        # Reasoning models (gpt-oss) think into this field; the client reads only `response`.
        print(f"  thinking    : {len(thinking)} chars   <- the pipeline never reads this field")
    print(f"  response    : {len(text)} chars")
    # Ollama cuts a prompt that does not fit num_ctx and reports no error; prompt_eval_count
    # falling short is the only trace. chars/4 under-counts these prompts (chat template, dense
    # code), so the model seeing under 3/4 of it means part of the prompt was dropped.
    cut = seen is not None and seen < approx * 3 / 4
    if cut:
        print(f"  PROMPT CUT — the model saw {seen} tokens of a ~{approx}-token prompt; Ollama "
              "dropped the rest")
        print("     to fit numCtx, without an error. Raise llmServer.numCtx.")
    if text:
        print(f"  -> {text[:300]}")
        return not cut
    print("  EMPTY RESPONSE — this is the pipeline's 'returned empty response'.")
    if done == "length":
        print(f"     done_reason=length: all {max_tokens} output tokens were spent "
              + ("thinking." if thinking else "before an answer appeared."))
        print("     Retry with --max-tokens 8192 to confirm.")
    print(f"  BODY: {json.dumps(data)[:1200]}")
    return False


_PER_REQUEST = ("Prompt-Msg-Id", "Completion-Msg-Id")    # a fresh id on every call


def _lane_headers(lane, ollama: bool) -> dict:
    """What a run sends on this lane: the client's own rule (`LlmClient._post`), so a header the
    environment or a default supplies is sent here too. Nothing on Ollama, as there."""
    if ollama:
        return {}
    from llm_core.headers import build_openai_headers
    return build_openai_headers(api_key=lane.api_key, config_headers=lane.headers)


def _same_ticket(lanes, ollama: bool) -> list:
    """Pairs of lane names that send the same thing to the same server: one ticket listed twice,
    or a header the environment replaced on every lane."""
    seen, pairs = {}, []
    for lane in lanes:
        sent = _lane_headers(lane, ollama)
        what = (lane.endpoint, tuple(sorted((k, v) for k, v in sent.items() if k not in _PER_REQUEST)))
        if what in seen:
            pairs.append((seen[what], lane.name))
        else:
            seen[what] = lane.name
    return pairs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", action="store_true", help="print full response bodies")
    ap.add_argument("--max-tokens", type=int, default=None,
                    help="override the output budget (the client hardcodes 2048)")
    ap.add_argument("--only", type=_only, default=None,
                    help="run one prompt: 1/tiny, 2/description or 3/large")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    import requests
    from core.config import load_config, load_llm_config
    from llm_core.pool import lanes_from_config

    cfg = load_config(os.path.join(_ROOT, "engine"))
    try:
        llm = load_llm_config(cfg)
    except Exception as exc:
        print(f"config error: {exc}")
        return 2

    provider = llm.get("provider")
    ollama = provider == "ollama"
    base_url = (llm.get("baseUrl") or "").rstrip("/")
    model = llm.get("defaultModel")
    api_key = llm.get("apiKey") or ""
    headers = dict(llm.get("customHeaders") or {})
    timeout = int(llm.get("timeoutSeconds") or 120)
    num_ctx = int(llm.get("numCtx") or 8192)
    rate = float(llm.get("rateLimitSeconds") or 0)
    max_tokens = args.max_tokens or 2048

    if ollama:
        # As LlmClient._call_ollama: no auth, no custom headers, and never a gateway pause.
        url = f"{base_url}/api/generate"
    else:
        url = f"{base_url}/chat/completions" if not base_url.endswith("/chat/completions") else base_url
    ignored = "   (ignored on ollama)" if ollama else ""
    # The lanes a run would use, by the pool's own rule: one, the block's ticket, when none is
    # listed. A lane's missing fields are the block's.
    lanes = lanes_from_config(llm, provider=provider, endpoint=url, api_key=api_key or None,
                              headers=headers, rate_limit=rate)
    several = len(lanes) > 1

    print(_SEP)
    print("LLM CONFIGURATION (as the pipeline resolves it)")
    print(_SEP)
    print(f"  provider          : {provider}")
    print(f"  baseUrl           : {base_url}")
    print(f"  endpoint          : {url}")
    print(f"  defaultModel      : {model}")
    print(f"  timeoutSeconds    : {timeout}")
    print(f"  rateLimitSeconds  : {rate}{ignored}")
    print(f"  numCtx            : {num_ctx}" + ("   (sent as num_ctx)" if ollama else ""))
    print(f"  maxContextTokens  : {llm.get('maxContextTokens')}")
    # With lanes these two are only what a lane that sets none falls back on.
    default = "   (the default of a lane that sets none)" if several else ""
    print(f"  apiKey            : "
          + (f"set ({len(api_key)} chars)" if api_key else 'not set (no "Authorization: Bearer" is sent)')
          + (ignored or default))
    print(f"  customHeaders     : {sorted(headers) if headers else 'none'}{ignored or default}")
    if several:
        every = ("each gets the tiny prompt" if args.only in (None, 1)
                 else "not checked: only the tiny prompt goes to every lane")
        print(f"  lanes             : {len(lanes)} -- {', '.join(l.name for l in lanes)}   ({every})")
    print(f"  {'num_predict sent' if ollama else 'max_tokens sent':<18}: {max_tokens}"
          + ("" if args.max_tokens else "   <- hardcoded in client.py, not configurable"))
    for first, second in _same_ticket(lanes, ollama):
        print(f"  WARNING: lanes {first} and {second} send the same thing to the same server -- one "
              "ticket, used twice.")
        print("           Check their customHeaders; a header set in the environment "
              "(X_DEP_TICKET, USER_ID) replaces every lane's.")
    print()

    prompts = [
        ("1. tiny", "Reply with exactly: OK", "You are a test endpoint."),
        ("2. description (realistic, the shape Phase 2 sends)", _DESC_USER, _DESC_SYSTEM),
        ("3. large (~2.5k tokens, flowchart-labeller size)", _big_prompt(),
         "You label control-flow graphs."),
    ]
    tiny = prompts[0]
    if args.only:
        prompts = [prompts[args.only - 1]]

    def ask(lane, user: str, system: str):
        """One request on one lane. None when it was answered, else what went wrong, in a word."""
        if several:
            print(f"  lane        : {lane.name}")
        payload = (_ollama_payload(model, num_ctx, system, user, max_tokens) if ollama
                   else _openai_payload(model, system, user, max_tokens))
        approx = (len(system) + len(user)) // 4
        print(f"  prompt size : {len(system) + len(user)} chars (~{approx} tokens)")
        t0 = time.perf_counter()
        try:
            resp = requests.post(lane.endpoint, headers=_lane_headers(lane, ollama), json=payload,
                                 timeout=timeout)
        except Exception as exc:
            print(f"  TRANSPORT FAILURE: {type(exc).__name__}: {exc}")
            return "no connection"
        dt = time.perf_counter() - t0
        print(f"  http status : {resp.status_code}   ({dt:.1f}s)")

        if resp.status_code != 200:
            print(f"  BODY: {resp.text[:1500]}")
            return f"http {resp.status_code}"

        try:
            data = resp.json()
        except Exception:
            print(f"  response was not JSON: {resp.text[:500]}")
            return "not JSON"

        if ollama:
            data.pop("context", None)      # the prompt's token ids echoed back — noise here
            answered = _read_ollama(data, approx, max_tokens)
        else:
            answered = _read_openai(data, max_tokens)
        if args.raw:
            print(f"  RAW: {json.dumps(data, indent=2)[:4000]}")
        if rate > 0 and not ollama:
            time.sleep(rate)
        return None if answered else "no answer"

    failures = sent = 0
    lane_results = {}                       # lane name -> what went wrong on the tiny prompt, or None
    for label, user, system in prompts:
        print(_SEP)
        print(label)
        print(_SEP)
        proves_a_ticket = label == tiny[0]
        if proves_a_ticket:
            on = lanes
        else:
            # Once, on a lane that answered -- or these two would only repeat a dead ticket's refusal.
            on = [next((l for l in lanes if lane_results.get(l.name, "") is None), lanes[0])]
        for lane in on:
            wrong = ask(lane, user, system)
            sent += 1
            failures += wrong is not None
            if proves_a_ticket:
                lane_results[lane.name] = wrong
            print()

    print(_SEP)
    what = "request(s)" if several else "prompt(s)"
    refused = [f"{name} ({wrong})" for name, wrong in lane_results.items() if wrong]
    if several and lane_results:
        print("LANES: " + (f"{len(refused)} of {len(lanes)} did not answer -- {', '.join(refused)}"
                           if refused else f"all {len(lanes)} answered"))
        if refused and len(refused) < len(lanes):
            print("A lane that failed while another answered: that lane's ticket or key (or its baseUrl).")
    if failures:
        print(f"RESULT: {failures} of {sent} {what} failed.")
        print("If only the LARGE prompt failed, it is a size/budget problem.")
        if ollama:
            print("If a prompt was CUT, raise llmServer.numCtx.")
            print(f"If ALL failed with done_reason=length, {max_tokens} output tokens are too few "
                  "for this model.")
            print("If only the FIRST timed out, loading the model took it; raise llmServer.timeoutSeconds.")
            print("If ALL failed with a non-200 or no connection, it is the server or the model name.")
        else:
            print("If ALL failed with finish_reason=length, raise max_tokens.")
            print("If ALL failed with no choices or a non-200, it is the gateway/model/auth.")
    else:
        print(f"RESULT: all {sent} {what} answered. The "
              f"{'Ollama server' if ollama else 'gateway'} is working; "
              "the pipeline's empty responses come from somewhere else.")
    print(_SEP)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
