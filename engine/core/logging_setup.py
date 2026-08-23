"""Centralized logging configuration for the analyzer + flowchart engine.

One configuration point. Every module just calls `get_logger(__name__)`.

Default behavior (after `configure_logging()`):
  - INFO and above go to stderr  (human-readable, single-line format)
  - DEBUG and above go to a daily file: <project_root>/logs/run_YYYYMMDD.log
  - --quiet  -> stderr level becomes WARNING
  - --verbose -> stderr level becomes DEBUG

The file handler always captures DEBUG so post-mortem inspection is possible
even when the console was quiet.

Environment overrides:
  - LOG_LEVEL=DEBUG|INFO|WARNING|ERROR  applied to the stderr handler
"""

from __future__ import annotations

import atexit
import logging
import os
import sys
import threading
from datetime import datetime, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_CONFIGURED = False
_LOCK = threading.Lock()
_STDERR_HANDLER: Optional[logging.Handler] = None
_FILE_HANDLER: Optional[logging.Handler] = None
_LOG_FILE_PATH: Optional[str] = None
_LOG_DIR: Optional[str] = None


def _logs_root() -> str:
    """The `logs/` directory this process writes into."""
    return _LOG_DIR or os.path.join(os.getcwd(), "logs")

_FORMAT = "[%(asctime)s] %(levelname)s %(name)s: %(message)s"
_DATEFMT = "%H:%M:%S"


def _resolve_env_level(default: int) -> int:
    raw = os.environ.get("LOG_LEVEL")
    if not raw:
        return default
    name = raw.strip().upper()
    return getattr(logging, name, default)


def configure_logging(
    *,
    project_root: Optional[str] = None,
    quiet: bool = False,
    verbose: bool = False,
    log_dir: Optional[str] = None,
) -> str:
    """Install handlers on the root logger. Idempotent.

    Returns the path of the log file that was opened (so callers can print it).

    Args:
        project_root: directory whose `logs/` subdirectory will hold the file.
                      Defaults to the current working directory.
        quiet:        WARNING and above on stderr (errors only).
        verbose:      DEBUG on stderr.
        log_dir:      override the directory entirely (absolute path).
    """
    global _CONFIGURED, _STDERR_HANDLER, _FILE_HANDLER, _LOG_FILE_PATH, _LOG_DIR

    with _LOCK:
        if _CONFIGURED:
            # second caller may want to adjust verbosity — honor that
            if _STDERR_HANDLER is not None:
                _STDERR_HANDLER.setLevel(_pick_stderr_level(quiet, verbose))
            return _LOG_FILE_PATH or ""

        # Decide log directory
        if log_dir is None:
            base = project_root or os.getcwd()
            log_dir = os.path.join(base, "logs")
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError:
            log_dir = None  # fall back to stderr-only

        formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

        root = logging.getLogger()
        root.setLevel(logging.DEBUG)  # let handlers filter

        # ---- stderr handler ----
        stderr_handler = logging.StreamHandler(stream=sys.stderr)
        stderr_handler.setFormatter(formatter)
        stderr_handler.setLevel(_pick_stderr_level(quiet, verbose))
        root.addHandler(stderr_handler)
        _STDERR_HANDLER = stderr_handler

        # ---- file handler ----
        log_file_path = ""
        if log_dir is not None:
            today = datetime.now(timezone.utc).strftime("%Y%m%d")
            log_file_path = os.path.join(log_dir, f"run_{today}.log")
            try:
                file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
                file_handler.setFormatter(formatter)
                file_handler.setLevel(logging.DEBUG)
                root.addHandler(file_handler)
                _FILE_HANDLER = file_handler
            except OSError:
                log_file_path = ""

        # Quiet noisy third-party loggers a bit
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("requests").setLevel(logging.WARNING)

        _LOG_FILE_PATH = log_file_path or None
        _LOG_DIR = log_dir
        _CONFIGURED = True
        atexit.register(_emit_token_report)
        return log_file_path


def _emit_token_report() -> None:
    """At-exit hook: dump this process's LLM metrics.

    `format_report()` returns an empty string when nothing was recorded, so
    subprocesses that never made an LLM call (e.g. run.py orchestrator,
    parser.py) stay silent.

    Also writes the machine-readable copy into `logs/llm_stats/<run-id>/`, one
    file per process. run.py merges the directory into a single report at the
    end of the run, and `tools/llm_stats.py` compares two of those merges.
    Writing happens once here, at exit — never per call.
    """
    try:
        from llm_core import tokens as _tok
        report = _tok.format_report()
        if not (report and report.strip()):
            return
        # Same totals, somewhere aggregatable (doc 09, D2a). Converting "how many
        # LLM calls does a run make" into a number is what turns the concurrency
        # question into arithmetic instead of a guess (B6).
        try:
            from . import run_metrics
            run_metrics.record_llm_totals()
        except Exception:
            pass
        # Shutdown-ordering hazard: by the time this atexit hook runs, the stream a
        # StreamHandler captured may already be closed - pytest closes its captured stderr at
        # end of session, and the interpreter tears streams down at exit. Writing a record to
        # it makes logging.Handler.handleError() spew "--- Logging error --- ValueError: I/O
        # operation on closed file" (our try/except can't catch it - logging swallows the write
        # error internally). Drop any handler whose stream is closed, and silence handleError
        # as a belt-and-braces guard, before emitting the best-effort report.
        root = logging.getLogger()
        for h in list(root.handlers):
            stream = getattr(h, "stream", None)
            if stream is not None and getattr(stream, "closed", False):
                root.removeHandler(h)
        prev_raise = logging.raiseExceptions
        logging.raiseExceptions = False
        try:
            logging.getLogger("tokens").info(report)
        finally:
            logging.raiseExceptions = prev_raise
        # The per-process stats file. After the restore, because this is not a logging call;
        # a failure here is caught by the outer handler like everything else in this path.
        _tok.write_json(llm_stats_dir(), process=os.path.basename(sys.argv[0] or ""))
    except Exception:
        pass


def llm_stats_dir(run_id: str = "") -> str:
    """Directory holding this run's per-process LLM stats files.

    Keyed on ANALYZER_RUN_ID (set by run.py) so subprocesses of the same run
    write into one place and separate runs never mix.
    """
    rid = run_id or os.environ.get("ANALYZER_RUN_ID") or "adhoc"
    return os.path.join(_logs_root(), "llm_stats", rid)


def _pick_stderr_level(quiet: bool, verbose: bool) -> int:
    if verbose:
        return _resolve_env_level(logging.DEBUG)
    if quiet:
        return _resolve_env_level(logging.WARNING)
    return _resolve_env_level(logging.INFO)


def set_level(level: int | str) -> None:
    """Adjust the stderr handler level after the fact."""
    global _STDERR_HANDLER
    if _STDERR_HANDLER is None:
        return
    if isinstance(level, str):
        level = getattr(logging, level.strip().upper(), logging.INFO)
    _STDERR_HANDLER.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """Get a logger. Auto-configures the root with defaults if no one has yet.

    The auto-config means modules can `get_logger(__name__)` and immediately
    log without every entry point having to remember to call configure_logging.
    """
    if not _CONFIGURED:
        configure_logging()
    return logging.getLogger(name)


def current_log_file() -> Optional[str]:
    """Path to the active log file, or None if file logging is disabled."""
    return _LOG_FILE_PATH
