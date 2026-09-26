"""A job's output loop can fail; the job must fail with it, never hang.

Found by running a generation through the API for real (2026-09-26). The runner reads the child's
output line by line and writes progress to the database for each line. The first such write
raised -- SQLite hands `started_at` back without a timezone, and aware-minus-naive is a
TypeError -- which ended the loop. The `finally` then waited for the child, and the child was
blocked writing into the pipe nobody read any more. The job sat at "running" for ever, with
`analyzer.py` and a `run.py` two levels down both parked.

Three things fixed, one test class each:

  * `_elapsed_since` reads a naive timestamp as the UTC it was written as;
  * `_progress` keeps a failed progress write from stopping the run;
  * anything else that ends the loop early stops the whole process tree before waiting.
"""
import datetime
import os
import sys
import textwrap
import threading
import uuid

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "engine")]

from api.services import pipeline_runner as pr  # noqa: E402

UTC = datetime.timezone.utc


def _db_with_job(job_id, started_at):
    from api.db.in_memory import InMemoryDatabase
    from api.models.domain import AnalysisJob, AnalysisPhase
    db = InMemoryDatabase()
    db.jobs.create(AnalysisJob(
        id=job_id, project_id="p1", commit_sha="0" * 40, version_id=None,
        reference_version_id=None, status="running", pause_after_phase1=False,
        layer_filter=None, phase=1, phase_pct=0, current_activity="", activity_detail="",
        elapsed_seconds=0, eta_seconds=None,
        phases=[AnalysisPhase(n, "p%d" % n, "pending", None) for n in (1, 2, 3, 4)],
        started_at=started_at, completed_at=None, error_message=None, branch="main",
        version_tag="t", mode="auto", scope=None, no_llm=False, data_dict_id=None,
        narrowed_parse=True))
    return db


class TestElapsedTimeFromEitherBackend:
    def test_a_naive_start_is_read_as_utc(self):
        """What SQLite returns. It used to raise TypeError."""
        now = datetime.datetime(2026, 9, 26, 10, 0, 30, tzinfo=UTC)
        assert pr._elapsed_since(datetime.datetime(2026, 9, 26, 10, 0, 0), now) == 30

    def test_an_aware_start_is_unchanged(self):
        """What PostgreSQL returns."""
        now = datetime.datetime(2026, 9, 26, 10, 0, 30, tzinfo=UTC)
        assert pr._elapsed_since(datetime.datetime(2026, 9, 26, 10, 0, 0, tzinfo=UTC), now) == 30

    def test_no_start_is_zero(self):
        assert pr._elapsed_since(None) == 0

    def test_the_progress_writers_accept_a_naive_start(self):
        naive = datetime.datetime.now(UTC).replace(tzinfo=None)
        db = _db_with_job("jobnaive1", naive)
        pr._update_activity(db, "jobnaive1", "parsing Core.cpp")
        pr._transition_phase(db, "jobnaive1", 1, 2, datetime.datetime.now(UTC))
        assert db.jobs.get("jobnaive1").elapsed_seconds >= 0


class TestAFailedProgressWriteDoesNotStopTheRun:
    def test_it_is_swallowed_and_reported_as_none(self):
        def boom(*_a):
            raise RuntimeError("database is locked")
        assert pr._progress("jobp1", boom, 1, 2) is None

    def test_a_cancel_check_that_fails_means_not_cancelled(self):
        def boom(*_a):
            raise RuntimeError("connection reset")
        assert not pr._progress("jobp2", boom)

    def test_it_is_logged_once_per_function_per_job(self, caplog):
        def boom(*_a):
            raise RuntimeError("down")
        with caplog.at_level("WARNING", logger=pr._log.name):
            for _ in range(5):
                pr._progress("jobp3", boom)
        assert sum("jobp3" in r.getMessage() for r in caplog.records) == 1
        pr._cleanup_state("jobp3")
        assert not any(k[0] == "jobp3" for k in pr._progress_warned)

    def test_the_value_comes_back_when_it_works(self):
        assert pr._progress("jobp4", lambda a, b: a + b, 2, 3) == 5


# ---------------------------------------------------------------------------------------------
# A real process tree: child -> (shell) -> grandchild flooding the pipe, as analyzer.py -> cmd.exe
# -> run.py is. The loop is made to fail on its first line; the call must come back, and neither
# process may be left running.
# ---------------------------------------------------------------------------------------------
def _alive_with(marker):
    psutil = pytest.importorskip("psutil")
    out = []
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            if marker in " ".join(p.info.get("cmdline") or []):
                out.append(p)
        except psutil.Error:
            pass
    return out


@pytest.fixture
def flooding_tree(tmp_path):
    marker = "hangprobe" + uuid.uuid4().hex[:8]
    grandchild = tmp_path / ("grandchild_%s.py" % marker)
    grandchild.write_text(textwrap.dedent("""
        import sys, time
        for i in range(200000):
            print("grandchild line %d with enough text to fill a pipe quickly" % i, flush=True)
        time.sleep(600)
    """), encoding="utf-8")
    child = tmp_path / ("child_%s.py" % marker)
    child.write_text(textwrap.dedent("""
        import subprocess, sys
        subprocess.run([sys.executable, r"%s"], shell=(sys.platform == "win32"))
    """ % grandchild), encoding="utf-8")
    yield [sys.executable, str(child)], marker
    for p in _alive_with(marker):            # never leak a flooding process past the test
        try:
            p.kill()
        except Exception:
            pass


class TestAnAbandonedLoopStopsTheTree:
    def test_it_returns_instead_of_hanging_and_leaves_nothing_running(self, monkeypatch,
                                                                      flooding_tree):
        cmd, marker = flooding_tree
        db = _db_with_job("jobtree1", datetime.datetime.now(UTC))
        pr._init_state("jobtree1")

        def fails(*_a, **_k):
            raise ValueError("a bug in the loop, not in progress bookkeeping")
        monkeypatch.setattr(pr, "_detect_phase", fails)

        outcome = {}

        def run():
            try:
                outcome["value"] = pr._execute_subprocess(db, "jobtree1", cmd)
            except Exception as exc:                          # noqa: BLE001
                outcome["error"] = exc
        t = threading.Thread(target=run, daemon=True)
        t.start()
        t.join(90)
        assert not t.is_alive(), "the runner hung waiting for a child nobody was reading"
        assert isinstance(outcome.get("error"), ValueError)   # the job fails, with its reason
        assert _alive_with(marker) == [], "a process of the job was left running"

    def test_a_cancel_stops_the_grandchild_too(self, monkeypatch, flooding_tree):
        """The same tree through the cancel path, which used to terminate the direct child
        only -- leaving the phase two levels down running on its own."""
        cmd, marker = flooding_tree
        db = _db_with_job("jobtree2", datetime.datetime.now(UTC))
        pr._init_state("jobtree2")
        monkeypatch.setattr(pr, "_is_cancelled", lambda *_a: True)

        outcome = {}
        t = threading.Thread(target=lambda: outcome.setdefault(
            "value", pr._execute_subprocess(db, "jobtree2", cmd)), daemon=True)
        t.start()
        t.join(90)
        assert not t.is_alive(), "the cancel path hung"
        assert outcome.get("value") is False
        assert _alive_with(marker) == [], "the cancelled job's grandchild was left running"
