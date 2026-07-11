"""ProgressReporter — one consistent way to report `[idx/total]` progress.

Behaviour:
  - On a TTY: live single-line update with `\\r`. Final `done()` writes a
    newline and an INFO log line so the file log captures the summary.
  - When stderr is piped/redirected (CI, log files): no `\\r` spam — only
    occasional INFO log lines (every `log_every` steps + at start + done),
    so the file log stays readable.
  - When the active stderr log level is WARNING or higher (--quiet), all
    visible output is suppressed except the final summary, which is logged
    at INFO so it still hits the log file.

Usage:
    pr = ProgressReporter("LLM-description", total=42, logger=logger)
    pr.start()
    for i, item in enumerate(items):
        pr.step(label=item.name)
        ... do work ...
    pr.done(summary=f"{processed} processed, {skipped} skipped")
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from typing import Optional


class ProgressReporter:
    def __init__(
        self,
        component: str,
        *,
        total: int = 0,
        logger: Optional[logging.Logger] = None,
        log_every: int = 0,
        stream=None,
    ) -> None:
        self.component = component
        self.total = max(0, int(total))
        self.logger = logger or logging.getLogger(component)
        # If log_every == 0, derive a sensible default: roughly every 10%, min 1.
        if log_every <= 0 and self.total > 0:
            log_every = max(1, self.total // 10)
        self.log_every = max(1, log_every)
        self.stream = stream or sys.stderr
        self._idx = 0
        self._started = False
        self._t0 = 0.0
        self._lock = threading.Lock()
        self._tty = bool(getattr(self.stream, "isatty", lambda: False)())
        self._line_active = False  # do we currently own a `\r` line?

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def start(self, msg: Optional[str] = None) -> None:
        with self._lock:
            self._started = True
            self._t0 = time.perf_counter()
            self._idx = 0
            text = msg or (f"start ({self.total} items)" if self.total else "start")
            self.logger.info(text)

    def step(self, label: Optional[str] = None) -> None:
        """Advance the counter by one and (optionally) update the live line."""
        with self._lock:
            if not self._started:
                self.start()
            self._idx += 1
            self._render(label)

    def done(self, summary: Optional[str] = None) -> None:
        with self._lock:
            self._clear_live_line()
            elapsed = time.perf_counter() - self._t0 if self._t0 else 0.0
            tail = f" — {summary}" if summary else ""
            self.logger.info(f"done in {elapsed:.2f}s{tail}")

    # ------------------------------------------------------------------
    # rendering
    # ------------------------------------------------------------------

    def _render(self, label: Optional[str]) -> None:
        idx = self._idx
        total = self.total
        progress = f"[{idx}/{total}]" if total else f"[{idx}]"
        suffix = f" {label}" if label else ""

        if self._tty and self._enabled_for_visible():
            try:
                self.stream.write(f"\r  {self.component} {progress}{suffix}\033[K")
                self.stream.flush()
                self._line_active = True
            except Exception:
                pass

        # Periodic INFO line (also goes to the file handler)
        if total == 0 or idx == total or (idx % self.log_every == 0):
            self.logger.info(f"{progress}{suffix}")

    def _clear_live_line(self) -> None:
        if self._line_active:
            try:
                self.stream.write("\r\033[K")
                self.stream.flush()
            except Exception:
                pass
            self._line_active = False

    def _enabled_for_visible(self) -> bool:
        """Returns False when --quiet (logger above INFO)."""
        return self.logger.isEnabledFor(logging.INFO)

    # ------------------------------------------------------------------
    # context manager sugar
    # ------------------------------------------------------------------

    def __enter__(self) -> "ProgressReporter":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.done()
        else:
            self._clear_live_line()
