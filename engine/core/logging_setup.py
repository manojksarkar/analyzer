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
import contextvars
import json as _json
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

        # ---- live log (docs/design/LIVE_LOGS_DESIGN.md) ----
        global _LIVE_HANDLER
        _LIVE_HANDLER = LiveLogHandler()
        root.addHandler(_LIVE_HANDLER)

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


# ---------------------------------------------------------------------------
# Live log (docs/spec/LIVE_LOGS_SPEC.md, docs/design/LIVE_LOGS_DESIGN.md)
#
# Every process also writes its records, one JSON object per line, to its OWN file:
# <data root>/logs/live/<YYYY-MM-DD>/<source>-<pid>.jsonl. One file per process, so no two
# processes ever append to one file (Windows does not make that safe); the API reads them all
# (api/services/live_logs.py). Always at DEBUG: the level a reader sees is chosen when reading.
# ---------------------------------------------------------------------------

#: `engine` for every process but the API, which calls `set_live_source("server")`.
_LIVE_SOURCE = "engine"
#: False turns this process's live log off (the test suite's own process, for one): its default
#: handler writes nothing and the API starts no reader. A handler given its own folder still writes.
LIVE_LOG_ENABLED = True
#: What the API request being handled names -- `{"project": .., "version": .., "job": ..}` --
#: set by api/middleware/request_log.py; every record logged while it runs carries it.
REQUEST_CONTEXT: "contextvars.ContextVar[Optional[dict]]" = contextvars.ContextVar(
    "live_log_request", default=None)

#: Which step of a run a process is, by the script it runs (each phase is its own process).
_STEP_BY_SCRIPT = {"parser.py": "Parse", "model_deriver.py": "Derive", "run_views.py": "Views",
                   "flowchart_engine.py": "Views",          # started by Phase 3's flowcharts view
                   "docx_exporter.py": "Export SWE.3", "swe4_exporter.py": "Export SWE.4"}


_LIVE_HANDLER: Optional["LiveLogHandler"] = None


def live_handler() -> Optional["LiveLogHandler"]:
    """The process's live-log handler (one per process, so one open file), configuring logging
    if nothing has yet. For a logger that does not propagate to the root -- uvicorn's own, the
    API's request lines -- but must reach the live log."""
    if not _CONFIGURED:
        configure_logging()
    return _LIVE_HANDLER


def note_request_ids(**ids) -> None:
    """Add ids to the API request being handled: a route that CREATES a job names it here, so
    the request's own line (and every later one) carries the job and version its path could not.
    Outside a request it does nothing."""
    ctx = REQUEST_CONTEXT.get()
    if ctx is not None:
        ctx.update({k: v for k, v in ids.items() if v})


def set_live_source(source: str) -> None:
    """Mark this process's live-log records: `engine` (the default) or `server` (the API)."""
    global _LIVE_SOURCE
    _LIVE_SOURCE = source


def live_log_root() -> str:
    """`<data root>/logs/live` -- the same folder for every process on this machine (a detached
    run is handed the data root, so it writes here too, not into its code copy)."""
    try:
        from .paths import paths
        return os.path.join(paths().data_root, "logs", "live")
    except Exception:                                   # noqa: BLE001 - never stop logging
        return os.path.join(_logs_root(), "live")


def _process_context(argv=None) -> dict:
    """`step` and `components` of this process, from its own command line."""
    argv = list(sys.argv if argv is None else argv)
    out = {}
    step = _STEP_BY_SCRIPT.get(os.path.basename(argv[0] if argv else ""))
    if step:
        out["step"] = step
    if "--allowed-components" in argv:
        i = argv.index("--allowed-components")
        if i + 1 < len(argv):
            comps = [c.strip() for c in argv[i + 1].split(",") if c.strip()]
            if comps:
                out["components"] = comps
    return out


def _argv_ids(argv=None) -> dict:
    """`project` and `version` from this process's own command line -- for a phase that reads
    `--version-id` itself instead of through `core.run_context` (swe4_exporter.py)."""
    argv = list(sys.argv if argv is None else argv)
    out = {}
    for flag, key in (("--project-id", "project"), ("--version-id", "version")):
        if flag in argv and argv.index(flag) + 1 < len(argv):
            out[key] = argv[argv.index(flag) + 1]
    return out


class _PrintsToLiveLog:
    """`sys.stdout` that also sends each printed line to the live log (INFO, logger = the script):
    the phases print much of their progress, which would otherwise never reach it. The console
    gets exactly what it got before; `logs/run_<date>.log` gets nothing new."""

    def __init__(self, stream, logger_name: str):
        self._stream = stream
        self._name = logger_name
        self._pending = ""
        self._lock = threading.Lock()

    def write(self, text):
        written = self._stream.write(text)
        try:
            with self._lock:
                lines = (self._pending + text).split("\n")
                self._pending = lines.pop()
            handler = _LIVE_HANDLER
            for line in lines:
                line = line.rstrip("\r")
                if line.strip() and handler is not None:
                    handler.handle(logging.LogRecord(self._name, logging.INFO, "", 0, line,
                                                     None, None))
        except Exception:                               # noqa: BLE001 - printing never fails on us
            pass
        return written

    def flush(self):
        return self._stream.flush()

    def __getattr__(self, name):                        # encoding, isatty, reconfigure, buffer ...
        return getattr(self._stream, name)


def start_phase_logging() -> None:
    """For a run's step process (parser.py, model_deriver.py, ...): logging configured as the
    first `get_logger` would configure it -- a phase that logged only through `logging.getLogger`
    wrote nowhere -- and what it prints sent to the live log too.

    Only in the step's own process: these modules are also imported by the API and the tests,
    whose `sys.stdout` must stay theirs. Configured logging is left as it is (a `--quiet` the
    process set stays)."""
    if not _process_context().get("step"):
        return
    if not _CONFIGURED:
        configure_logging()
    if not isinstance(sys.stdout, _PrintsToLiveLog) and sys.stdout is not None:
        name = os.path.splitext(os.path.basename(sys.argv[0] if sys.argv else ""))[0] or "print"
        sys.stdout = _PrintsToLiveLog(sys.stdout, name)


class LiveLogHandler(logging.Handler):
    """Writes each record as one JSON line to this process's live-log file.

    The file is chosen per record -- a new one when the local date or the process's source
    changes -- and kept open. A failure to write is swallowed: a log line must never stop a run.
    """

    def __init__(self, root: Optional[str] = None):
        super().__init__(level=logging.DEBUG)
        self._root = root
        self._path: Optional[str] = None
        self._stream = None
        self._process = _process_context()
        self._argv_ids = _argv_ids()

    def _target(self, when: datetime) -> str:
        day = when.strftime("%Y-%m-%d")
        return os.path.join(self._root or live_log_root(), day,
                            "%s-%d.jsonl" % (_LIVE_SOURCE, os.getpid()))

    def record_dict(self, record: logging.LogRecord) -> dict:
        when = datetime.fromtimestamp(record.created).astimezone()
        message = record.getMessage()
        if record.exc_info:
            message += "\n" + logging.Formatter().formatException(record.exc_info)
        elif record.exc_text:
            message += "\n" + record.exc_text
        if record.stack_info:
            message += "\n" + record.stack_info
        out = {"ts": when.isoformat(timespec="milliseconds"), "level": record.levelname,
               "source": _LIVE_SOURCE, "logger": record.name, "message": message,
               "pid": os.getpid()}
        try:
            from . import run_context
            if run_context.project_id():
                out["project"] = run_context.project_id()
            if run_context.version_id():
                out["version"] = run_context.version_id()
        except Exception:                               # noqa: BLE001
            pass
        for key, value in self._argv_ids.items():
            out.setdefault(key, value)
        out.update(self._process)
        for key, value in (REQUEST_CONTEXT.get() or {}).items():
            if value:
                out[key] = value
        return out

    def emit(self, record: logging.LogRecord) -> None:
        if self._root is None and not LIVE_LOG_ENABLED:     # a handler given a folder still writes
            return
        try:
            line = _json.dumps(self.record_dict(record), ensure_ascii=False, default=str)
            path = self._target(datetime.now().astimezone())
            if path != self._path:
                self._close_stream()
                os.makedirs(os.path.dirname(path), exist_ok=True)
                self._stream = open(path, "a", encoding="utf-8", newline="\n")
                self._path = path
            self._stream.write(line + "\n")             # one write: the line is whole or absent
            self._stream.flush()
        except Exception:                               # noqa: BLE001 - see the class docstring
            pass

    def _close_stream(self) -> None:
        if self._stream is not None:
            try:
                self._stream.close()
            except Exception:                           # noqa: BLE001
                pass
        self._stream, self._path = None, None

    def close(self) -> None:
        self.acquire()
        try:
            self._close_stream()
        finally:
            self.release()
        super().close()
