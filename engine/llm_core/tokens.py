"""Per-process token counter for LLM calls.

The counter is a module-level singleton because LLM calls happen from many
sites (parser enrichment, hierarchy summarizer, flowchart label generator,
unit description). At end of run we print one consolidated report.

Ollama returns prompt_eval_count + eval_count in the response body.
OpenAI-compatible servers return a `usage` block with prompt_tokens /
completion_tokens / total_tokens. Both are normalised to (prompt, completion)
pairs here.
"""

import threading
from collections import defaultdict
from typing import Dict, Tuple


class _TokenCounter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        # key = (provider, model) -> [prompt_tokens, completion_tokens, calls]
        self._totals: Dict[Tuple[str, str], list] = defaultdict(lambda: [0, 0, 0])

    def record(self, provider: str, model: str,
               prompt_tokens: int, completion_tokens: int) -> None:
        with self._lock:
            row = self._totals[(provider, model)]
            row[0] += int(prompt_tokens or 0)
            row[1] += int(completion_tokens or 0)
            row[2] += 1

    def snapshot(self) -> Dict[Tuple[str, str], Tuple[int, int, int]]:
        with self._lock:
            return {k: tuple(v) for k, v in self._totals.items()}

    def reset(self) -> None:
        with self._lock:
            self._totals.clear()

    def format_report(self) -> str:
        snap = self.snapshot()
        if not snap:
            # Empty string suppresses the at-exit report. The orchestrator
            # subprocess (run.py) never makes LLM calls itself, so we don't
            # want it to log "(no calls)" alongside the real reports from
            # model_deriver.py / flowchart_engine.py.
            return ""
        lines = ["LLM token usage:"]
        grand_p = grand_c = grand_n = 0
        for (provider, model), (p, c, n) in sorted(snap.items()):
            lines.append(
                f"  {provider:7s} {model:30s}  calls={n:5d}  "
                f"prompt={p:>10,}  completion={c:>10,}  total={p + c:>10,}"
            )
            grand_p += p
            grand_c += c
            grand_n += n
        if len(snap) > 1:
            lines.append(
                f"  {'TOTAL':7s} {'':30s}  calls={grand_n:5d}  "
                f"prompt={grand_p:>10,}  completion={grand_c:>10,}  "
                f"total={grand_p + grand_c:>10,}"
            )
        return "\n".join(lines)


_counter = _TokenCounter()


def record(provider: str, model: str,
           prompt_tokens: int, completion_tokens: int) -> None:
    _counter.record(provider, model, prompt_tokens, completion_tokens)


def snapshot() -> Dict[Tuple[str, str], Tuple[int, int, int]]:
    return _counter.snapshot()


def reset() -> None:
    _counter.reset()


def format_report() -> str:
    return _counter.format_report()
