"""Per-process LLM call metrics.

Every LLM call in the project goes through `LlmClient`, which reports each HTTP
attempt here. The counter is a module-level singleton because calls happen from
many sites (parser enrichment, hierarchy summarizer, flowchart label generator,
unit description) and we want one consolidated picture per process.

What is recorded per attempt
----------------------------
    stage       who asked for it — see `stage()` below
    provider    "ollama" | "openai"
    model       model name
    latency     seconds spent in the HTTP request itself
    throttle    seconds slept afterwards for the gateway rate limit
    outcome     "ok" | "empty" | "error"
    tokens      prompt + completion (0 for failed attempts)

Failed attempts are recorded too. That matters: a timeout costs full latency
plus a throttle sleep and produces nothing, so a report that only counts
successes understates both the call count and the time spent.

Ollama returns prompt_eval_count + eval_count in the response body. OpenAI
returns a `usage` block. Both are normalised to (prompt, completion) here.

Attribution
-----------
Callers wrap their work in `with tokens.stage("phase2.descriptions"):` so each
call is attributed to a part of the pipeline. It is a contextvar, so the label
follows the call down through helper layers without threading a parameter
through every signature. Unlabelled calls land in "unspecified".

Cross-process aggregation
-------------------------
Each phase runs as its own subprocess with its own counter. On exit every
process writes its own JSON via `write_json()`; `run.py` merges them into one
report at the end of the run. See `tools/llm_stats.py` to compare two runs.
"""

import contextvars
import json
import os
import sys
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Stage attribution
# ---------------------------------------------------------------------------

_UNSPECIFIED = "unspecified"
_STAGE: contextvars.ContextVar = contextvars.ContextVar("llm_stage", default=_UNSPECIFIED)


@contextmanager
def stage(name: str) -> Iterator[None]:
    """Attribute every LLM call made inside this block to *name*.

    Nests safely — an inner stage wins until its block exits. Use dotted names
    so the report groups readably: "phase3.flowchart.labels".
    """
    token = _STAGE.set(name or _UNSPECIFIED)
    try:
        yield
    finally:
        _STAGE.reset(token)


def current_stage() -> str:
    return _STAGE.get()


# ---------------------------------------------------------------------------
# Counter
# ---------------------------------------------------------------------------

_Key = Tuple[str, str, str]   # (stage, provider, model)


def _percentile(sorted_values: List[float], pct: float) -> float:
    """Nearest-rank percentile. Empty list → 0.0."""
    if not sorted_values:
        return 0.0
    idx = int(round(pct / 100.0 * len(sorted_values) + 0.5)) - 1
    idx = max(0, min(idx, len(sorted_values) - 1))
    return sorted_values[idx]


class _TokenCounter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: Dict[_Key, Dict[str, Any]] = defaultdict(self._new_row)
        # Resolved LLM config for this process, captured by LlmClient so a saved
        # report says what produced it. Last client built wins.
        self._config: Dict[str, Any] = {}
        self._t0 = time.time()

    @staticmethod
    def _new_row() -> Dict[str, Any]:
        return {
            "calls": 0, "ok": 0, "empty": 0, "error": 0,
            "prompt_tokens": 0, "completion_tokens": 0,
            "http_seconds": 0.0, "throttle_seconds": 0.0,
            "latencies": [],
        }

    # -- recording ---------------------------------------------------------

    def record(self, provider: str, model: str,
               prompt_tokens: int, completion_tokens: int,
               *,
               latency: float = 0.0,
               throttle: float = 0.0,
               outcome: str = "ok",
               stage_name: Optional[str] = None) -> None:
        """Record one HTTP attempt.

        Kept positionally compatible with the original 4-arg signature; the
        metric fields are keyword-only additions.
        """
        key = (stage_name or current_stage(), provider, model)
        with self._lock:
            row = self._rows[key]
            row["calls"] += 1
            row[outcome if outcome in ("ok", "empty", "error") else "ok"] += 1
            row["prompt_tokens"] += int(prompt_tokens or 0)
            row["completion_tokens"] += int(completion_tokens or 0)
            row["http_seconds"] += float(latency or 0.0)
            row["throttle_seconds"] += float(throttle or 0.0)
            row["latencies"].append(float(latency or 0.0))

    def record_config(self, **fields: Any) -> None:
        """Capture the resolved LLM config so a saved report is self-describing."""
        with self._lock:
            self._config.update({k: v for k, v in fields.items() if v is not None})

    def reset(self) -> None:
        with self._lock:
            self._rows.clear()
            self._config.clear()
            self._t0 = time.time()

    # -- reading -----------------------------------------------------------

    def snapshot(self) -> Dict[Tuple[str, str], Tuple[int, int, int]]:
        """Legacy view: (provider, model) -> (prompt, completion, calls)."""
        out: Dict[Tuple[str, str], List[int]] = defaultdict(lambda: [0, 0, 0])
        with self._lock:
            for (_stage, provider, model), row in self._rows.items():
                acc = out[(provider, model)]
                acc[0] += row["prompt_tokens"]
                acc[1] += row["completion_tokens"]
                acc[2] += row["calls"]
        return {k: tuple(v) for k, v in out.items()}

    def stages(self) -> List[Dict[str, Any]]:
        """One fully-derived record per (stage, provider, model), slowest first."""
        with self._lock:
            rows = [(key, dict(row, latencies=sorted(row["latencies"])))
                    for key, row in self._rows.items()]
        out = []
        for (stage_name, provider, model), row in rows:
            lat = row["latencies"]
            http = row["http_seconds"]
            out.append({
                "stage": stage_name,
                "provider": provider,
                "model": model,
                "calls": row["calls"],
                "ok": row["ok"],
                "empty": row["empty"],
                "error": row["error"],
                "httpSeconds": round(http, 2),
                "throttleSeconds": round(row["throttle_seconds"], 2),
                "totalSeconds": round(http + row["throttle_seconds"], 2),
                "avgSeconds": round(http / row["calls"], 2) if row["calls"] else 0.0,
                "maxSeconds": round(max(lat), 2) if lat else 0.0,
                "p95Seconds": round(_percentile(lat, 95), 2),
                "promptTokens": row["prompt_tokens"],
                "completionTokens": row["completion_tokens"],
                # Output tokens per second of HTTP time — separates "slow because
                # it generated a lot" from "slow server".
                "tokensPerSecond": round(row["completion_tokens"] / http, 1) if http > 0 else 0.0,
            })
        out.sort(key=lambda r: r["totalSeconds"], reverse=True)
        return out

    def totals(self) -> Dict[str, Any]:
        rows = self.stages()
        agg = {
            "calls": sum(r["calls"] for r in rows),
            "ok": sum(r["ok"] for r in rows),
            "empty": sum(r["empty"] for r in rows),
            "error": sum(r["error"] for r in rows),
            "httpSeconds": round(sum(r["httpSeconds"] for r in rows), 2),
            "throttleSeconds": round(sum(r["throttleSeconds"] for r in rows), 2),
            "promptTokens": sum(r["promptTokens"] for r in rows),
            "completionTokens": sum(r["completionTokens"] for r in rows),
        }
        agg["totalSeconds"] = round(agg["httpSeconds"] + agg["throttleSeconds"], 2)
        agg["avgSeconds"] = round(agg["httpSeconds"] / agg["calls"], 2) if agg["calls"] else 0.0
        agg["maxSeconds"] = max((r["maxSeconds"] for r in rows), default=0.0)
        return agg

    def to_dict(self, *, process: str = "") -> Dict[str, Any]:
        with self._lock:
            config = dict(self._config)
            started = self._t0
        return {
            "run": {
                "id": os.environ.get("ANALYZER_RUN_ID", ""),
                "process": process or os.path.basename(sys.argv[0] or ""),
                "pid": os.getpid(),
                "startedAt": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(started)),
                "wallSeconds": round(time.time() - started, 2),
            },
            "config": config,
            "stages": self.stages(),
            "totals": self.totals(),
        }

    # -- formatting --------------------------------------------------------

    def format_report(self) -> str:
        """Console/log report. Empty string when nothing was recorded.

        Empty output suppresses the at-exit report entirely, so subprocesses
        that never made an LLM call (run.py orchestrator, parser.py) stay quiet.
        """
        rows = self.stages()
        if not rows:
            return ""
        agg = self.totals()

        lines = ["LLM calls by stage:"]
        head = (f"  {'stage':32s} {'calls':>6s} {'fail':>5s} {'avg':>7s} "
                f"{'max':>7s} {'http':>9s} {'throttle':>9s} {'tok/s':>7s}")
        lines.append(head)
        lines.append("  " + "-" * (len(head) - 2))
        for r in rows:
            fails = r["empty"] + r["error"]
            lines.append(
                f"  {r['stage'][:32]:32s} {r['calls']:6d} {fails:5d} "
                f"{r['avgSeconds']:6.1f}s {r['maxSeconds']:6.1f}s "
                f"{r['httpSeconds']:8.1f}s {r['throttleSeconds']:8.1f}s "
                f"{r['tokensPerSecond']:7.1f}"
            )
        lines.append("  " + "-" * (len(head) - 2))
        fails = agg["empty"] + agg["error"]
        lines.append(
            f"  {'TOTAL':32s} {agg['calls']:6d} {fails:5d} "
            f"{agg['avgSeconds']:6.1f}s {agg['maxSeconds']:6.1f}s "
            f"{agg['httpSeconds']:8.1f}s {agg['throttleSeconds']:8.1f}s"
        )
        lines.append(
            f"  tokens: prompt={agg['promptTokens']:,} "
            f"completion={agg['completionTokens']:,} "
            f"total={agg['promptTokens'] + agg['completionTokens']:,}"
        )
        if agg["throttleSeconds"] > 0:
            share = 100.0 * agg["throttleSeconds"] / agg["totalSeconds"] if agg["totalSeconds"] else 0.0
            lines.append(
                f"  throttle is {share:.0f}% of LLM time "
                f"(llm.rateLimitSeconds, set to 0 to remove it)"
            )
        return "\n".join(lines)

    def write_json(self, dir_path: str, *, process: str = "") -> str:
        """Write this process's stats into *dir_path*. Returns the path, or "".

        One file per process (pid in the name) so concurrent phases never
        overwrite each other; `merge_dir()` combines them afterwards.
        """
        if not self._rows:
            return ""
        try:
            os.makedirs(dir_path, exist_ok=True)
            name = f"{(process or 'process').replace('.py', '')}-{os.getpid()}.json"
            path = os.path.join(dir_path, name)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self.to_dict(process=process), fh, indent=2)
            return path
        except OSError:
            return ""


_counter = _TokenCounter()


# ---------------------------------------------------------------------------
# Module-level API
# ---------------------------------------------------------------------------

def record(provider: str, model: str,
           prompt_tokens: int, completion_tokens: int,
           **kwargs: Any) -> None:
    _counter.record(provider, model, prompt_tokens, completion_tokens, **kwargs)


def record_config(**fields: Any) -> None:
    _counter.record_config(**fields)


def snapshot() -> Dict[Tuple[str, str], Tuple[int, int, int]]:
    return _counter.snapshot()


def stages() -> List[Dict[str, Any]]:
    return _counter.stages()


def totals() -> Dict[str, Any]:
    return _counter.totals()


def reset() -> None:
    _counter.reset()


def to_dict(*, process: str = "") -> Dict[str, Any]:
    return _counter.to_dict(process=process)


def format_report() -> str:
    return _counter.format_report()


def write_json(dir_path: str, *, process: str = "") -> str:
    return _counter.write_json(dir_path, process=process)


# ---------------------------------------------------------------------------
# Cross-process merge (used by run.py and tools/llm_stats.py)
# ---------------------------------------------------------------------------

def merge_dir(dir_path: str) -> Dict[str, Any]:
    """Merge every per-process JSON in *dir_path* into one report.

    Stages with the same (stage, provider, model) are summed. Averages are
    recomputed from the sums; max is the max of maxes. p95 cannot be summed
    from aggregates, so the merged p95 is the largest per-process p95 — close
    enough to spot outliers, and flagged as approximate in the schema.
    """
    merged: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    config: Dict[str, Any] = {}
    processes: List[Dict[str, Any]] = []

    if not os.path.isdir(dir_path):
        return {"config": {}, "processes": [], "stages": [], "totals": {}}

    for name in sorted(os.listdir(dir_path)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(dir_path, name), encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        config.update(data.get("config") or {})
        run = data.get("run") or {}
        processes.append({
            "process": run.get("process", ""),
            "pid": run.get("pid"),
            "wallSeconds": run.get("wallSeconds"),
            "calls": (data.get("totals") or {}).get("calls", 0),
        })
        for row in data.get("stages") or []:
            key = (row.get("stage", ""), row.get("provider", ""), row.get("model", ""))
            acc = merged.setdefault(key, {
                "stage": key[0], "provider": key[1], "model": key[2],
                "calls": 0, "ok": 0, "empty": 0, "error": 0,
                "httpSeconds": 0.0, "throttleSeconds": 0.0,
                "promptTokens": 0, "completionTokens": 0,
                "maxSeconds": 0.0, "p95Seconds": 0.0,
            })
            for f in ("calls", "ok", "empty", "error", "promptTokens", "completionTokens"):
                acc[f] += int(row.get(f) or 0)
            for f in ("httpSeconds", "throttleSeconds"):
                acc[f] += float(row.get(f) or 0.0)
            for f in ("maxSeconds", "p95Seconds"):
                acc[f] = max(acc[f], float(row.get(f) or 0.0))

    rows = []
    for acc in merged.values():
        http = acc["httpSeconds"]
        acc["httpSeconds"] = round(http, 2)
        acc["throttleSeconds"] = round(acc["throttleSeconds"], 2)
        acc["totalSeconds"] = round(http + acc["throttleSeconds"], 2)
        acc["avgSeconds"] = round(http / acc["calls"], 2) if acc["calls"] else 0.0
        acc["tokensPerSecond"] = round(acc["completionTokens"] / http, 1) if http > 0 else 0.0
        acc["p95Approx"] = True
        rows.append(acc)
    rows.sort(key=lambda r: r["totalSeconds"], reverse=True)

    agg = {
        "calls": sum(r["calls"] for r in rows),
        "ok": sum(r["ok"] for r in rows),
        "empty": sum(r["empty"] for r in rows),
        "error": sum(r["error"] for r in rows),
        "httpSeconds": round(sum(r["httpSeconds"] for r in rows), 2),
        "throttleSeconds": round(sum(r["throttleSeconds"] for r in rows), 2),
        "promptTokens": sum(r["promptTokens"] for r in rows),
        "completionTokens": sum(r["completionTokens"] for r in rows),
    }
    agg["totalSeconds"] = round(agg["httpSeconds"] + agg["throttleSeconds"], 2)
    agg["avgSeconds"] = round(agg["httpSeconds"] / agg["calls"], 2) if agg["calls"] else 0.0
    agg["maxSeconds"] = max((r["maxSeconds"] for r in rows), default=0.0)

    return {
        "run": {"id": os.environ.get("ANALYZER_RUN_ID", "")},
        "config": config,
        "processes": processes,
        "stages": rows,
        "totals": agg,
    }


def format_merged(report: Dict[str, Any]) -> str:
    """Format a merged report (from `merge_dir`) for the end-of-run summary."""
    rows = report.get("stages") or []
    if not rows:
        return ""
    agg = report.get("totals") or {}
    cfg = report.get("config") or {}

    caption = " / ".join(str(v) for v in (
        cfg.get("provider"), cfg.get("model"), cfg.get("baseUrl"),
    ) if v)
    rate = cfg.get("rateLimitSeconds")
    if rate is not None:
        caption += f"  rateLimit={rate}s"

    head = (f"  {'stage':32s} {'calls':>6s} {'fail':>5s} {'avg':>7s} "
            f"{'max':>7s} {'http':>9s} {'throttle':>9s} {'tok/s':>7s}")
    lines = ["LLM report - whole run" + (f"  ({caption})" if caption else ""), head,
             "  " + "-" * (len(head) - 2)]
    for r in rows:
        fails = r["empty"] + r["error"]
        lines.append(
            f"  {r['stage'][:32]:32s} {r['calls']:6d} {fails:5d} "
            f"{r['avgSeconds']:6.1f}s {r['maxSeconds']:6.1f}s "
            f"{r['httpSeconds']:8.1f}s {r['throttleSeconds']:8.1f}s "
            f"{r['tokensPerSecond']:7.1f}"
        )
    lines.append("  " + "-" * (len(head) - 2))
    fails = agg.get("empty", 0) + agg.get("error", 0)
    lines.append(
        f"  {'TOTAL':32s} {agg.get('calls', 0):6d} {fails:5d} "
        f"{agg.get('avgSeconds', 0):6.1f}s {agg.get('maxSeconds', 0):6.1f}s "
        f"{agg.get('httpSeconds', 0):8.1f}s {agg.get('throttleSeconds', 0):8.1f}s"
    )
    return "\n".join(lines)
