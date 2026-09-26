"""A re-export must not take a finished version out of the baseline pool.

The phase runner marks each phase it starts on the version row ('viewing', 'exporting'). A
generation's last step closes that at 'complete'; a re-export -- Phase 3 or 4 alone -- has no
such step, so every version re-exported from the web app was left at 'exporting'.
`pg_stores.list_versions` accepts only NULL or 'complete' as a baseline, so the next version
generated from it ran FULL: every LLM call paid again, and none of the reviewers' corrections
carried, because they are carried on the incremental path. Found by running the review flow end
to end: correct, re-export, generate the next version -- decision "full", 0 reused, 0 carried.
"""
import datetime
import os
import sys

import pytest
from sqlalchemy import create_engine, insert, select
from sqlalchemy.pool import StaticPool

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from api.db.postgres import schema as s  # noqa: E402
import core.db as coredb  # noqa: E402

UTC = datetime.timezone.utc


@pytest.fixture()
def eng(monkeypatch):
    e = create_engine("sqlite://", connect_args={"check_same_thread": False},
                      poolclass=StaticPool)
    s.metadata.create_all(e)
    now = datetime.datetime.now(UTC)
    with e.begin() as cx:
        cx.execute(insert(s.projects), {"id": "p", "name": "p", "created_at": now})
    coredb.reset_engine()
    monkeypatch.setattr(coredb, "get_engine", lambda *a, **k: e)
    monkeypatch.delenv("ANALYZER_VERSION_ID", raising=False)
    return e


def _version(eng, status):
    with eng.begin() as cx:
        cx.execute(insert(s.versions), {"id": "v1", "project_id": "p", "version": "v1",
                                        "commit_sha": "a" * 40, "status": "in_review",
                                        "pipeline_status": status,
                                        "created_at": datetime.datetime.now(UTC)})


def _status(eng):
    with eng.connect() as cx:
        return cx.execute(select(s.versions.c.pipeline_status)
                          .where(s.versions.c.id == "v1")).scalar()


def _phases():
    """What PhaseRunner writes for a Phase 3 + 4 run."""
    coredb.set_pipeline_status("viewing", version_id="v1")
    coredb.set_pipeline_status("exporting", version_id="v1")


class TestAFinishedVersionStaysFinished:
    @pytest.mark.parametrize("before", ["complete", None, "failed"])
    def test_its_status_is_put_back(self, eng, before):
        _version(eng, before)
        with coredb.finished_status_kept(True, version_id="v1"):
            _phases()
            assert _status(eng) == "exporting", "progress is still reported while it runs"
        assert _status(eng) == before

    def test_also_when_the_export_fails(self, eng):
        """The model was never touched, so the version is exactly as finished as it was."""
        _version(eng, "complete")
        with pytest.raises(SystemExit):
            with coredb.finished_status_kept(True, version_id="v1"):
                _phases()
                raise SystemExit(1)                  # what PhaseRunner raises on a failed phase
        assert _status(eng) == "complete"

    def test_it_is_still_a_baseline_afterwards(self, eng):
        from incremental import pg_stores
        _version(eng, "complete")
        with coredb.finished_status_kept(True, version_id="v1"):
            _phases()
        assert [v["versionId"] for v in pg_stores.list_versions(eng, "p")] == ["v1"]

    def test_the_version_id_comes_from_the_environment_as_the_phases_read_it(self, eng,
                                                                           monkeypatch):
        _version(eng, "complete")
        monkeypatch.setenv("ANALYZER_VERSION_ID", "v1")
        with coredb.finished_status_kept(True):
            coredb.set_pipeline_status("exporting")
        assert _status(eng) == "complete"


class TestAGenerationKeepsItsProgress:
    def test_a_status_in_progress_is_left_to_the_generation(self, eng):
        """A generation's own last step (write_manifest) closes it; putting 'deriving' back
        would show a finished Phase 4 as still deriving."""
        _version(eng, "deriving")
        with coredb.finished_status_kept(True, version_id="v1"):
            _phases()
        assert _status(eng) == "exporting"

    def test_inactive_changes_nothing(self, eng):
        _version(eng, "complete")
        with coredb.finished_status_kept(False, version_id="v1"):
            _phases()
        assert _status(eng) == "exporting"


class TestNeverTheReasonARunDies:
    def test_no_version_id_is_a_no_op(self, monkeypatch):
        monkeypatch.delenv("ANALYZER_VERSION_ID", raising=False)
        monkeypatch.setattr(coredb, "get_engine",
                            lambda *a, **k: pytest.fail("no version id: no database"))
        with coredb.finished_status_kept(True):
            pass

    def test_an_unreachable_database_is_swallowed(self, monkeypatch):
        def _boom(*a, **k):
            raise RuntimeError("no database here")
        monkeypatch.setattr(coredb, "get_engine", _boom)
        with coredb.finished_status_kept(True, version_id="v1"):
            pass


class TestRunPyWrapsThePhases:
    def test_the_phase_loop_runs_inside_the_guard_from_phase_3(self):
        """run.py is what BOTH re-export front doors spawn; the guard has to be there."""
        src = open(os.path.join(PROJECT_ROOT, "engine", "run.py"), encoding="utf-8").read()
        guard = src.index("with finished_status_kept(from_phase >= 3):")
        loop = src.index("runner.run(plan.phases", guard)
        between = src[guard:loop]
        assert "for plan in plans:" in between and between.count("\n") <= 4
