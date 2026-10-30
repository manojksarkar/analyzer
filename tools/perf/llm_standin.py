"""A stand-in LLM server for timing the pipeline: answers like Ollama (`/api/generate`) and like an
OpenAI-compatible gateway (`/chat/completions`), after a set delay, and refuses with 503 beyond a
set number of calls at once -- or faster than a set rate -- as the review gateway does.

Every answer is a hash of the prompt (the same prompt, the same answer), so two runs that send the
same prompts store the same text: a speed-up that changes no prompt changes no document. `--vary`
adds the call's number, as a real LLM words one prompt differently each time: then two runs give
the same text only where a cache answers the second (tools/job_scheduling_test C01). A flowchart's
label prompt gets a JSON label for each of its nodes, as the label generator reads it.

    python tools/perf/llm_standin.py --port 18080 --latency 3 --max-concurrent 4 --min-interval 0 \
        --log C:/tmp/standin.jsonl

`--keys a,b`: only these bearer keys are accepted, each with its own concurrency and rate (a
gateway that limits per key). Every request is logged as one JSON line (start, end, key,
in-flight count, status) for the timing report (tools/perf/standin_report.py).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOCK = threading.Lock()
STATE = {"inflight": {}, "last_start": {}, "last_end": {}, "seq": 0}
ARGS = None


_NODES = "--- Nodes to Label ---\n"


def answer_for(prompt: str, seq: int = 0) -> str:
    """A hash of the prompt -- or, with --vary, of the prompt and the call's number: a real LLM
    words the same prompt differently from one call to the next, which a cache must hide.

    A flowchart's label prompt is answered as the label generator reads it, a JSON object with a
    label for every node it lists; its coherence pass, with no change. In plain text every chart
    fell back to mechanical labels, which are never cached -- so a run with the stand-in never
    used the label cache, and could not show a label written again."""
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:10]
    said = f" (call {seq})" if ARGS.vary else ""
    if "Return {} if nothing needs changing" in prompt:
        return "{}"
    at = prompt.find(_NODES)
    if at >= 0:
        try:
            nodes, _ = json.JSONDecoder().raw_decode(prompt, at + len(_NODES))
            return json.dumps({n["node_id"]: f"Step {digest} {n['node_id']}{said}"
                               for n in nodes if isinstance(n, dict) and n.get("node_id")})
        except ValueError:
            pass
    return f"Stand-in text {digest}{said}."


def log(rec: dict) -> None:
    if not ARGS.log:
        return
    with LOCK, open(ARGS.log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):          # quiet
        pass

    def _send(self, code: int, body: dict) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):                    # Ollama's /api/tags, a health check
        self._send(200, {"models": [{"name": ARGS.model}]})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        auth = self.headers.get("Authorization", "")
        key = auth.split(" ", 1)[1] if auth.startswith("Bearer ") else (self.headers.get("x-api-key") or "-")
        if ARGS.keys and key not in ARGS.keys:
            return self._send(401, {"error": "unknown key"})
        lane = key if ARGS.keys else "-"
        now = time.time()
        with LOCK:
            STATE["seq"] += 1
            seq = STATE["seq"]
            busy = STATE["inflight"].get(lane, 0)
            last = STATE["last_end" if ARGS.interval_from == "end" else "last_start"].get(lane, 0.0)
            too_soon = now - last < ARGS.min_interval
            refuse = busy >= ARGS.max_concurrent or too_soon
            if not refuse:
                STATE["inflight"][lane] = busy + 1
                STATE["last_start"][lane] = now
        if refuse:
            log({"seq": seq, "key": lane, "start": now, "end": time.time(), "status": 503,
                 "inflight": busy, "why": "busy" if busy >= ARGS.max_concurrent else "rate"})
            return self._send(503, {"error": "An invalid response was received from the upstream server"})
        try:
            if self.path.rstrip("/").endswith("/v1/messages"):
                # The Claude Messages API: the system prompt is its own field. Joined in the
                # chat order, so the same prompt gets the same answer as on /chat/completions.
                prompt = "\x00".join([str(body.get("system", ""))]
                                      + [str(m.get("content", "")) for m in body.get("messages", [])])
                time.sleep(ARGS.latency)
                text = answer_for(prompt, seq)
                out = {"id": f"msg_{seq}", "type": "message", "role": "assistant",
                       "content": [{"type": "text", "text": text}],
                       "model": body.get("model", ARGS.model), "stop_reason": "end_turn",
                       "usage": {"input_tokens": len(prompt) // 4, "output_tokens": 8}}
            elif self.path.rstrip("/").endswith("/chat/completions"):
                prompt = "\x00".join(str(m.get("content", "")) for m in body.get("messages", []))
                time.sleep(ARGS.latency)
                text = answer_for(prompt, seq)
                out = {"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": len(prompt) // 4, "completion_tokens": 8, "total_tokens": len(prompt) // 4 + 8},
                       "model": body.get("model", ARGS.model)}
            else:                        # Ollama /api/generate (and /api/chat)
                prompt = str(body.get("system", "")) + "\x00" + str(body.get("prompt", "")) \
                    + "\x00".join(str(m.get("content", "")) for m in body.get("messages", []))
                time.sleep(ARGS.latency)
                text = answer_for(prompt, seq)
                out = {"model": body.get("model", ARGS.model), "response": text, "done": True,
                       "message": {"role": "assistant", "content": text},
                       "prompt_eval_count": len(prompt) // 4, "eval_count": 8}
            self._send(200, out)
            log({"seq": seq, "key": lane, "start": now, "end": time.time(), "status": 200, "inflight": busy + 1,
                 "chars": len(prompt)})
        finally:
            with LOCK:
                STATE["inflight"][lane] -= 1
                STATE["last_end"][lane] = time.time()


def main() -> None:
    global ARGS
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--port", type=int, default=18080)
    p.add_argument("--latency", type=float, default=0.0, help="seconds before each answer")
    p.add_argument("--max-concurrent", type=int, default=1000, help="per key; beyond it: 503")
    p.add_argument("--min-interval", type=float, default=0.0, help="per key: seconds between starts; sooner: 503")
    p.add_argument("--interval-from", choices=("start", "end"), default="start",
                   help="count --min-interval from the last request's start (default) or its end")
    p.add_argument("--keys", default="", help="comma-separated bearer keys, each its own lane")
    p.add_argument("--model", default="standin")
    p.add_argument("--vary", action="store_true",
                   help="a different answer on every call, as a real LLM's wording changes")
    p.add_argument("--log", default="")
    ARGS = p.parse_args()
    ARGS.keys = [k for k in ARGS.keys.split(",") if k]
    srv = ThreadingHTTPServer(("127.0.0.1", ARGS.port), Handler)
    srv.daemon_threads = True
    print(f"stand-in LLM on 127.0.0.1:{ARGS.port} latency={ARGS.latency}s max_concurrent={ARGS.max_concurrent} "
          f"min_interval={ARGS.min_interval}s keys={ARGS.keys or 'any'}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
