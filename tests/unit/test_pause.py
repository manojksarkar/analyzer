"""A run's pause (engine/core/pause.py; docs/design/JOB_SCHEDULING_DESIGN.md §8, docs/spec/
JOB_SCHEDULING_SPEC.md REQ-JS-22, 23): it stops at a safe point when its job asks, every LLM answer
received kept, and exit 75 travels up the chain as a pause -- never as a failure.
"""
import datetime
import sys
import threading
import time
import weakref

import pytest

pytestmark = pytest.mark.unit

from core import pause  # noqa: E402

UTC = datetime.timezone.utc


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    """Nothing read yet; this test's job, or none."""
    pause.reset()
    monkeypatch.delenv("ANALYZER_JOB_ID", raising=False)
    yield
    pause.reset()


def _asked(monkeypatch, answer=True):
    """The run's job, asking `answer` -- read through a stand-in, counting the reads."""
    monkeypatch.setenv("ANALYZER_JOB_ID", "jobp")
    reads = []

    def read(jid):
        reads.append(jid)
        return answer
    monkeypatch.setattr(pause, "_read", read)
    return reads


class TestTheRequest:
    def test_without_a_job_nothing_is_asked(self, monkeypatch):
        monkeypatch.setattr(pause, "_read", lambda jid: pytest.fail("read without a job"))
        assert pause.requested() is False
        pause.check("anywhere")                         # does nothing

    def test_it_is_read_at_most_every_few_seconds(self, monkeypatch):
        reads = _asked(monkeypatch, answer=False)
        assert pause.requested() is False and pause.requested() is False
        assert reads == ["jobp"]
        monkeypatch.setattr(pause, "ASK_EVERY", 0.0)
        pause.requested()
        assert len(reads) == 2

    def test_once_asked_it_stays_asked(self, monkeypatch):
        reads = _asked(monkeypatch, answer=True)
        assert pause.requested() and pause.requested()
        assert reads == ["jobp"]

    def test_it_is_read_from_the_job_s_row(self, tmp_path, monkeypatch):
        """Running and asked: yes. Paused already, or not asked, or no such job: no."""
        import sqlalchemy as sa
        import core.db as core_db
        from api.db.postgres import schema as s
        monkeypatch.setenv("DATABASE_URL", "sqlite:///" + (tmp_path / "p.db").as_posix())
        core_db.reset_engine()
        try:
            eng = core_db.get_engine()
            s.metadata.create_all(eng)
            now = datetime.datetime.now(UTC)
            with eng.begin() as cx:
                # One project each: a lane holds one running or paused job.
                cx.execute(sa.insert(s.projects), [{"id": p, "name": p, "created_at": now}
                                                   for p in ("pa", "pb", "pc")])
                cx.execute(sa.insert(s.analysis_jobs), [
                    {"id": "asked", "project_id": "pa", "status": "running",
                     "pause_requested_at": now},
                    {"id": "quiet", "project_id": "pb", "status": "running",
                     "pause_requested_at": None},
                    {"id": "done", "project_id": "pc", "status": "paused",
                     "pause_requested_at": now}])
            assert pause._read("asked") is True
            assert (pause._read("quiet"), pause._read("done"), pause._read("none")) == (
                False, False, False)
        finally:
            core_db.reset_engine()

    def test_a_database_that_cannot_answer_is_no_pause(self, monkeypatch):
        import core.db as core_db
        monkeypatch.setattr(core_db, "is_database_configured", lambda: True)
        monkeypatch.setattr(core_db, "get_engine", lambda: (_ for _ in ()).throw(
            RuntimeError("down")))
        assert pause._read("jobp") is False


class TestThePausePoint:
    def test_it_passes_through_except_exception(self, monkeypatch):
        _asked(monkeypatch)
        with pytest.raises(pause.PauseRequested) as stopped:
            try:
                pause.check("descriptions")
            except Exception:                           # a stage's own error handling
                pytest.fail("a pause was taken for an error")
        assert str(stopped.value) == "descriptions"

    def test_a_worker_thread_does_not_raise_it(self, monkeypatch):
        _asked(monkeypatch)
        seen = []
        t = threading.Thread(target=lambda: seen.append(pause.check("in a pool") or "went on"))
        t.start()
        t.join()
        assert seen == ["went on"]

    def test_a_step_script_s_entry_exits_75(self, monkeypatch, capsys):
        _asked(monkeypatch)

        @pause.exits_paused
        def main():
            pause.check("Phase 2")
            pytest.fail("went past the pause point")
        with pytest.raises(SystemExit) as gone:
            main()
        assert gone.value.code == pause.EXIT_PAUSED == 75
        assert "paused at a safe point: Phase 2" in capsys.readouterr().err

    def test_any_other_end_of_the_entry_is_untouched(self):
        @pause.exits_paused
        def main():
            raise ValueError("a real error")
        with pytest.raises(ValueError):
            main()


class TestTheLlmLoops:
    @pytest.mark.parametrize("workers", [1, 3])
    def test_items_not_started_are_dropped(self, monkeypatch, workers):
        """Asked to pause after two answers: the third item is never asked about -- and in
        parallel, the queued ones are cancelled and the ones in flight finish."""
        from llm_core import parallel
        monkeypatch.setenv("ANALYZER_JOB_ID", "jobp")
        monkeypatch.setattr(pause, "ASK_EVERY", 0.0)
        done = []

        def ask(x):
            time.sleep(0.05)
            done.append(x)
            return x
        monkeypatch.setattr(pause, "_read", lambda jid: len(done) >= 2)
        with pytest.raises(pause.PauseRequested):
            parallel.map_in_order(ask, range(40), workers, "test")
        time.sleep(0.3)                                 # what was in flight has finished
        assert 2 <= len(done) < 40

    def test_without_a_pause_every_item_is_answered_in_order(self, monkeypatch):
        from llm_core import parallel
        assert parallel.map_in_order(lambda x: x * 2, range(10), 3, "test") == [
            x * 2 for x in range(10)]


class TestExit75TravelsUp:
    def _script(self, tmp_path, body):
        path = tmp_path / "phase.py"
        path.write_text(body, encoding="utf-8")
        return str(path)

    def test_a_phase_that_paused_stops_the_run_as_a_pause(self, tmp_path, caplog):
        from core.orchestration import Phase, PhaseRunner
        script = self._script(tmp_path, "import sys\nsys.exit(75)\n")
        with pytest.raises(SystemExit) as gone:
            PhaseRunner().run([Phase("Phase 2: Derive", script)])
        assert gone.value.code == 75
        assert "paused at a safe point" in caplog.text and "failed" not in caplog.text

    def test_a_pause_asked_before_a_phase_does_not_start_it(self, tmp_path, monkeypatch):
        from core import orchestration
        marker = tmp_path / "ran"
        script = self._script(tmp_path, "open(%r, 'w').close()\n" % str(marker))
        monkeypatch.setattr(orchestration.pause, "requested", lambda: True)
        with pytest.raises(SystemExit) as gone:
            orchestration.PhaseRunner().run([orchestration.Phase("Phase 3: Views", script)])
        assert gone.value.code == 75 and not marker.exists()

    def test_the_run_record_says_paused(self):
        from core.version_run import _Run
        assert [_Run().ok(rc) for rc in (0, 75, 1)] == [0, 75, 1]
        outcomes = []
        for rc in (0, 75, 3):
            r = _Run()
            r.ok(rc)
            outcomes.append(r.outcome)
        assert outcomes == ["complete", "paused", "failed"]

    def test_writing_records_a_pause_that_exits(self, monkeypatch):
        from core import version_run
        ends = []
        monkeypatch.setattr(version_run, "record_start", lambda *a, **k: None)
        monkeypatch.setattr(version_run, "record_end", lambda vid, outcome, **k: ends.append(outcome))
        with pytest.raises(SystemExit):
            with version_run.writing("v1", command="generate", engine=None):
                raise SystemExit(75)
        assert ends == ["paused"]

    def test_the_cli_says_paused_and_returns_75(self, capsys):
        import analyzer
        from incremental.generate import AnalyzerRunFailed

        def paused(*a, **k):
            raise AnalyzerRunFailed("paused at a safe point", 75)
        a = type("A", (), {"full": True, "force": False, "project_id": "p", "no_register": True})()
        rc = analyzer._generate(a, "v1", "main", "a" * 40, None, {}, paused, paused,
                                AnalyzerRunFailed, RuntimeError, RuntimeError)
        assert rc == 75 and "Paused at a safe point" in capsys.readouterr().err


class TestEveryCacheSavesItsBufferAtExit:
    def test_the_exit_hook_flushes_a_live_cache_and_lets_go_of_a_dropped_one(self, monkeypatch):
        import atexit
        from llm_core import cache as cache_mod
        hooks = []
        monkeypatch.setattr(atexit, "register", hooks.append)

        class Cache:
            flushed = 0

            def flush(self):
                Cache.flushed += 1
        live, dropped = Cache(), Cache()
        cache_mod._flush_at_exit(live)
        cache_mod._flush_at_exit(dropped)
        ref = weakref.ref(dropped)
        del dropped
        import gc
        gc.collect()
        assert ref() is None, "the hook does not keep a cache alive"
        for hook in hooks:
            hook()
        assert Cache.flushed == 1

    def test_a_cache_with_a_database_registers_it(self, tmp_path, monkeypatch):
        import core.db as core_db
        from api.db.postgres import schema as s
        from llm_core import cache as cache_mod
        monkeypatch.setenv("DATABASE_URL", "sqlite:///" + (tmp_path / "c.db").as_posix())
        core_db.reset_engine()
        try:
            s.metadata.create_all(core_db.get_engine())
            registered = []
            monkeypatch.setattr(cache_mod, "_flush_at_exit", registered.append)
            c = cache_mod.EntityCache("p", "descriptions")
            assert registered == [c]
        finally:
            core_db.reset_engine()


class TestTheJobView:
    def test_a_pause_asked_of_a_run_that_ended_is_not_shown_pending(self):
        from types import SimpleNamespace
        from api.services import job_queue as q
        now = datetime.datetime.now(UTC)
        fields = dict(id="j", project_id="p", mode="auto", priority=1, submitted_at=now,
                      started_at=now, origin="web", runner=None, heartbeat_at=now,
                      pause_requested_at=now, resume_requested_at=None, paused_at=None)
        running = SimpleNamespace(status="running", **fields)
        ended = SimpleNamespace(status="complete", **fields)
        assert q.job_queue_fields(None, running)["pause_requested"] is True
        assert q.job_queue_fields(None, ended)["pause_requested"] is False
