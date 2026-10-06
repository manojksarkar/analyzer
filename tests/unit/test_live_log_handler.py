"""The live-log writer (engine/core/logging_setup.py; docs/spec/LIVE_LOGS_SPEC.md REQ-LL-01, -02).

Every process writes its records, one JSON object per line, to its own file under
`<root>/<YYYY-MM-DD>/<source>-<pid>.jsonl`. These drive the handler on a temporary folder.
"""
import json
import logging
import os
import sys
from datetime import datetime

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (PROJECT_ROOT, os.path.join(PROJECT_ROOT, "engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core import logging_setup as ls  # noqa: E402
from core import run_context  # noqa: E402

pytestmark = pytest.mark.unit


@pytest.fixture
def logger(tmp_path, monkeypatch):
    # An engine process: importing api.main in the same test run marks the process `server`.
    monkeypatch.setattr(ls, "_LIVE_SOURCE", "engine")
    handler = ls.LiveLogHandler(root=str(tmp_path))
    log = logging.getLogger("test.live_log")
    log.setLevel(logging.DEBUG)
    log.propagate = False
    log.addHandler(handler)
    yield log
    log.removeHandler(handler)
    handler.close()


def _records(tmp_path):
    out = []
    for day in sorted(os.listdir(tmp_path)):
        for name in sorted(os.listdir(tmp_path / day)):
            with open(tmp_path / day / name, encoding="utf-8") as fh:
                out.extend((day, name, json.loads(line)) for line in fh)
    return out


class TestARecord:
    def test_its_fields(self, logger, tmp_path):
        logger.info("Phase 1 started, %d files", 42)
        [(day, name, rec)] = _records(tmp_path)
        assert name == "engine-%d.jsonl" % os.getpid()
        assert day == datetime.now().strftime("%Y-%m-%d")
        assert rec["message"] == "Phase 1 started, 42 files"
        assert (rec["level"], rec["source"], rec["logger"], rec["pid"]) == (
            "INFO", "engine", "test.live_log", os.getpid())
        when = datetime.fromisoformat(rec["ts"])
        assert when.tzinfo is not None and "." in rec["ts"]          # offset and milliseconds

    def test_debug_is_always_written(self, logger, tmp_path):
        logger.debug("detail")
        assert _records(tmp_path)[0][2]["level"] == "DEBUG"

    def test_a_traceback_stays_in_its_record(self, logger, tmp_path):
        try:
            raise ValueError("boom")
        except ValueError:
            logger.exception("it failed")
        [(_, _, rec)] = _records(tmp_path)
        assert rec["message"].startswith("it failed\nTraceback")
        assert "ValueError: boom" in rec["message"]

    def test_the_run_and_the_request_it_belongs_to(self, logger, tmp_path, monkeypatch):
        # Through monkeypatch: set_run_context(None) leaves a value in place, and a version id
        # left behind would follow every later test in this process.
        monkeypatch.setattr(run_context, "_VERSION_ID", "vera072")
        monkeypatch.setattr(run_context, "_PROJECT_ID", "p1")
        token = ls.REQUEST_CONTEXT.set({"job": "jobab17"})
        try:
            logger.info("x")
        finally:
            ls.REQUEST_CONTEXT.reset(token)
        rec = _records(tmp_path)[0][2]
        assert (rec["project"], rec["version"], rec["job"]) == ("p1", "vera072", "jobab17")

    def test_the_api_writes_as_the_server(self, logger, tmp_path):
        ls.set_live_source("server")
        try:
            logger.info("x")
        finally:
            ls.set_live_source("engine")
        day, name, rec = _records(tmp_path)[0]
        assert name == "server-%d.jsonl" % os.getpid() and rec["source"] == "server"


class TestTheStepOfAProcess:
    @pytest.mark.parametrize("script,step", [
        ("engine/parser.py", "Parse"), ("engine/model_deriver.py", "Derive"),
        ("engine/run_views.py", "Views"), ("engine/flowchart/flowchart_engine.py", "Views"),
        ("engine/docx_exporter.py", "Export SWE.3"), ("engine/swe4_exporter.py", "Export SWE.4"),
    ])
    def test_from_its_script(self, script, step):
        assert ls._process_context([script])["step"] == step

    def test_the_components_it_works_on(self):
        ctx = ls._process_context(["run_views.py", "--allowed-components",
                                   "Layer1.Sample Core,Layer1.Lib"])
        assert ctx["components"] == ["Layer1.Sample Core", "Layer1.Lib"]

    def test_a_process_that_is_no_step(self):
        assert ls._process_context(["analyzer.py", "generate"]) == {}


class TestWhatAStepPrints:
    """Phases print much of their progress; the live log must have it, the console unchanged."""

    def test_each_printed_line_reaches_the_live_log_and_the_console(self, tmp_path, monkeypatch):
        import io
        handler = ls.LiveLogHandler(root=str(tmp_path))
        monkeypatch.setattr(ls, "_LIVE_HANDLER", handler)
        monkeypatch.setattr(ls, "_LIVE_SOURCE", "engine")
        console = io.StringIO()
        out = ls._PrintsToLiveLog(console, "model_deriver")
        print("Derived 12 units", file=out)
        out.write("half a ")
        assert len(_records(tmp_path)) == 1                         # a partial line waits
        out.write("line\n")
        handler.close()
        assert console.getvalue() == "Derived 12 units\nhalf a line\n"
        recs = [r for _, _, r in _records(tmp_path)]
        assert [(r["logger"], r["level"], r["message"]) for r in recs] == [
            ("model_deriver", "INFO", "Derived 12 units"), ("model_deriver", "INFO", "half a line")]

    def test_only_in_the_step_s_own_process(self, monkeypatch):
        """The API and the tests import these modules: their stdout stays theirs."""
        before = sys.stdout
        monkeypatch.setattr(sys, "argv", ["pytest", "-q"])
        ls.start_phase_logging()
        assert sys.stdout is before

    def test_a_step_that_reads_its_own_version_id(self, tmp_path, monkeypatch):
        """swe4_exporter.py takes `--version-id` itself, not through core.run_context."""
        monkeypatch.setattr(run_context, "_VERSION_ID", None)
        monkeypatch.setattr(run_context, "_PROJECT_ID", None)
        monkeypatch.setattr(sys, "argv", ["engine/swe4_exporter.py", "--version-id", "ver9",
                                          "--project-id", "p9"])
        handler = ls.LiveLogHandler(root=str(tmp_path))
        rec = handler.record_dict(logging.LogRecord("t", logging.INFO, "", 0, "x", None, None))
        handler.close()
        assert (rec["version"], rec["project"], rec["step"]) == ("ver9", "p9", "Export SWE.4")


class TestFiles:
    def test_a_new_file_when_the_day_changes(self, logger, tmp_path, monkeypatch):
        class Day(datetime):
            today = datetime(2026, 10, 6, 23, 59, 59)

            @classmethod
            def now(cls, tz=None):
                return cls.today if tz is None else cls.today.astimezone(tz)
        monkeypatch.setattr(ls, "datetime", Day)
        logger.info("before midnight")
        Day.today = datetime(2026, 10, 7, 0, 0, 1)
        logger.info("after midnight")
        assert [d for d, _, _ in _records(tmp_path)] == ["2026-10-06", "2026-10-07"]

    def test_switched_off_the_default_handler_writes_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ls, "live_log_root", lambda: str(tmp_path / "default"))
        monkeypatch.setattr(ls, "LIVE_LOG_ENABLED", False)
        default, own = ls.LiveLogHandler(), ls.LiveLogHandler(root=str(tmp_path / "own"))
        rec = logging.LogRecord("t", logging.INFO, __file__, 1, "x", None, None)
        default.emit(rec)
        own.emit(rec)
        default.close()
        own.close()
        assert not (tmp_path / "default").exists() and (tmp_path / "own").exists()

    def test_a_failure_to_write_never_raises(self, tmp_path):
        blocker = tmp_path / "file"
        blocker.write_text("not a folder")
        handler = ls.LiveLogHandler(root=str(blocker))
        handler.emit(logging.LogRecord("t", logging.INFO, __file__, 1, "x", None, None))
        handler.close()
