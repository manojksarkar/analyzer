"""Per-phase run metrics, appended as JSON lines (doc 09, D2a).

D2 asks where run time actually goes *before* anything else is optimised, and the
capacity question ("how many concurrent jobs fit on a node?") needs a peak-RSS
number that nothing currently produces.

Two of the three inputs already existed but only ever reached prose:
``PhaseRunner`` timed every phase into the human log, and ``llm_core.tokens``
already counts every LLM call per ``(provider, model)`` and dumps a report at
exit. What was missing was somewhere machine-readable to put them, plus memory.

This appends one JSON object per phase to ``logs/metrics_<YYYYMMDD>.jsonl``.

Why JSON Lines and not a table in Postgres: a metrics record must survive the
run that produced it failing, must not need a schema migration to add a field,
and must be writable from several unrelated subprocesses at once. Append-only
single-line records give all three -- concurrent writers need no coordination
because the OS makes a short ``O_APPEND`` write atomic, and a run summarises with
a few lines of Python.

**Diagnostics only.** Every failure in here is swallowed. Measurement must never
be the reason a pipeline dies.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, Optional

from .logging_setup import get_logger
from .paths import paths

_log = get_logger("run-metrics")

# Set by the API per job (doc 09, B1/B5b) so records from concurrent jobs can be
# told apart in a shared log directory. Absent for a plain CLI run.
_JOB_ENV = "ANALYZER_JOB_ID"
_VERSION_ENV = "ANALYZER_VERSION_ID"


def metrics_path() -> Optional[str]:
    """Path to today's metrics file, or ``None`` if metrics should not be written.

    Returns ``None`` under pytest. The at-exit LLM hook fires in the test process
    too, and the suite's fake providers ("test-model", "gpt-4") were landing in the
    repo's real metrics file — which would make a capacity measurement read as
    though a run had called an OpenAI model it never touched. Measured, not
    theorised: 32 such records after one suite run.

    Both checks are needed. ``PYTEST_CURRENT_TEST`` covers writes during a test but
    pytest clears it before teardown, so the at-exit hook — the one that was
    actually polluting — ran with it already unset. ``sys.modules`` still holds
    pytest at interpreter exit, so it catches that path.
    """
    if os.environ.get("PYTEST_CURRENT_TEST") or "pytest" in sys.modules:
        return None
    try:
        log_dir = paths().logs_dir
        os.makedirs(log_dir, exist_ok=True)
        return os.path.join(log_dir, f"metrics_{datetime.now():%Y%m%d}.jsonl")
    except Exception:
        return None


def record(event: str, **fields: Any) -> None:
    """Append one metrics record. Never raises."""
    path = metrics_path()
    if not path:
        return
    row: Dict[str, Any] = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "event": event,
        "pid": os.getpid(),
    }
    job = os.environ.get(_JOB_ENV)
    if job:
        row["jobId"] = job
    version = os.environ.get(_VERSION_ENV)
    if version:
        row["versionId"] = version
    row.update(fields)
    try:
        # One short line, opened per write: concurrent writers from separate
        # processes append safely without a lock.
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass                                    # diagnostics never break a run


def record_phase(name: str, *, elapsed_sec: float, returncode: int,
                 peak_rss_mb: Optional[float] = None, **extra: Any) -> None:
    """Record one completed pipeline phase."""
    record(
        "phase",
        name=name,
        elapsedSec=round(elapsed_sec, 3),
        returnCode=returncode,
        peakRssMb=peak_rss_mb,
        **extra,
    )


def record_llm_totals() -> None:
    """Record this process's LLM call/token totals, if it made any.

    ``llm_core.tokens`` already accumulates these; this lands the same numbers
    somewhere aggregatable. Called at exit alongside the existing text report, so
    an LLM-heavy phase reports both its wall clock and its call count -- which is
    what converts a measurement into a rate-limit answer (doc 09, B6).
    """
    try:
        from llm_core import tokens
        snap = tokens.snapshot()
    except Exception:
        return
    if not snap:
        return
    for (provider, model), (prompt, completion, calls) in snap.items():
        record(
            "llm",
            provider=provider,
            model=model,
            calls=calls,
            promptTokens=prompt,
            completionTokens=completion,
        )


class phase_timer:
    """Context manager timing an in-process block and recording it.

    For work that is not a subprocess (``PhaseRunner`` records those itself with
    a peak-RSS number it can only get from the child's PID).
    """

    def __init__(self, name: str, **extra: Any) -> None:
        self._name = name
        self._extra = extra
        self._t0 = 0.0

    def __enter__(self) -> "phase_timer":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        record_phase(
            self._name,
            elapsed_sec=time.perf_counter() - self._t0,
            returncode=0 if exc_type is None else 1,
            **self._extra,
        )
        return False                            # never suppress
