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
    global _CONFIGURED, _STDERR_HANDLER, _FILE_HANDLER, _LOG_FILE_PATH

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
        _CONFIGURED = True
        atexit.register(_emit_token_report)
        return log_file_path


def _emit_token_report() -> None:
    """At-exit hook: dump LLM token usage so each subprocess records its own.

    `format_report()` already starts its output with "LLM token usage:" and
    returns an empty string when nothing was recorded, so subprocesses that
    never made an LLM call (e.g. run.py orchestrator, parser.py) stay silent.
    """
    try:
        from llm_core import tokens as _tok
        report = _tok.format_report()
        if report and report.strip():
            logging.getLogger("tokens").info(report)
    except Exception:
        pass


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
