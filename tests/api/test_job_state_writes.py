"""A job's state changes only by `transition()`; `update()` writes its progress, never its state.

The runner rewrites a job for almost every line its run prints, from a copy read a moment before
(`_update_activity`). While `update()` wrote the whole row, a cancel made between that read and that
write was undone: the job said "running" again, the run -- stopped by the cancel -- then looked as if
it had died, the job ended "failed", and the draft version a cancel deletes was kept. Now a status
changes in one statement that checks the status it changes from
(docs/design/JOB_SCHEDULING_DESIGN.md §1). Both database backends.
"""
import datetime
import uuid

from api.models.domain import AnalysisJob, AnalysisPhase, JOB_STATUSES
from api.services import pipeline_runner as pr

UTC = datetime.timezone.utc


def _job(db, *, status="running", project_id="p1"):
    """A job of the seeded project p1 (alice is its admin), with no version: what is checked here
    is the job row alone."""
    job = AnalysisJob(
        id="job" + uuid.uuid4().hex[:8], project_id=project_id, commit_sha="0" * 40,
        version_id=None, reference_version_id=None, status=status, pause_after_phase1=False,
        layer_filter=None, phase=1, phase_pct=0, current_activity="Parsing C++ sources…",
        activity_detail="", elapsed_seconds=0, eta_seconds=None,
        phases=[AnalysisPhase(1, "Parse C++", "running", None)],
        started_at=datetime.datetime.now(UTC), completed_at=None, error_message=None)
    db.jobs.create(job)
    return job


class TestUpdateNeverWritesTheState:
    def test_a_progress_write_from_an_earlier_copy_does_not_undo_a_cancel(self, db):
        job = _job(db)
        copy = db.jobs.get(job.id)                       # the runner reads it for a log line...
        assert db.jobs.transition(job.id, ("running",), "cancelled",       # ...the cancel lands...
                                  completed_at=datetime.datetime.now(UTC))
        copy.activity_detail = "[41/100] engine/parser.cpp"
        copy.phase_pct = 41
        db.jobs.update(copy)                             # ...and the runner writes its copy back

        got = db.jobs.get(job.id)
        assert got.status == "cancelled" and got.completed_at is not None
        assert got.phase_pct == 0, "a cancelled job takes no more progress"

    def test_progress_is_written_and_the_state_is_not(self, db):
        job = _job(db)
        copy = db.jobs.get(job.id)
        copy.status, copy.error_message = "complete", "never written by update"
        copy.completed_at = datetime.datetime.now(UTC)
        copy.phase_pct, copy.activity_detail = 40, "[40/100] engine/run.cpp"
        db.jobs.update(copy)

        got = db.jobs.get(job.id)
        assert (got.status, got.error_message, got.completed_at) == ("running", None, None)
        assert (got.phase_pct, got.activity_detail) == (40, "[40/100] engine/run.cpp")

    def test_a_job_object_changed_after_create_is_not_the_stored_one(self, db):
        job = _job(db, status="queued")
        job.status = "running"                           # never written: no update, no transition
        assert db.jobs.get(job.id).status == "queued"


class TestTransition:
    def test_it_changes_the_status_only_from_the_ones_it_expects(self, db):
        job = _job(db, status="queued")
        assert db.jobs.transition(job.id, ("running",), "complete") is False
        assert db.jobs.get(job.id).status == "queued"

        assert db.jobs.transition(job.id, ("queued",), "running", current_activity="Preparing…")
        got = db.jobs.get(job.id)
        assert (got.status, got.current_activity) == ("running", "Preparing…")

    def test_a_job_that_does_not_exist_is_not_changed(self, db):
        assert db.jobs.transition("job-none", JOB_STATUSES, "cancelled") is False

    def test_phases_are_written_as_phases(self, db):
        job = _job(db)
        phases = [AnalysisPhase(1, "Parse C++", "done", 3),
                  AnalysisPhase(2, "Derive Model", "running", None)]
        assert db.jobs.transition(job.id, ("running",), "running", phases=phases)
        got = db.jobs.get(job.id)
        assert [(p.number, p.status, p.duration_seconds) for p in got.phases] == \
            [(1, "done", 3), (2, "running", None)]

    def test_a_field_of_a_cancelled_job_changes_with_its_status_unchanged(self, db):
        """How a deleted version's jobs let go of it (`delete_version`, the in-memory backend):
        `update()` writes nothing to a cancelled job."""
        job = _job(db, status="cancelled")
        assert db.jobs.transition(job.id, ("cancelled",), "cancelled", activity_detail="kept")
        got = db.jobs.get(job.id)
        assert (got.status, got.activity_detail) == ("cancelled", "kept")


class TestTheRunnerKeepsACancel:
    def test_a_failure_recorded_after_the_cancel_does_not_replace_it(self, db):
        job = _job(db)
        assert db.jobs.transition(job.id, ("running",), "cancelled")
        pr._mark_failed(db, job.id, "run.py exited with code 2.")
        got = db.jobs.get(job.id)
        assert (got.status, got.error_message) == ("cancelled", None)

    def test_a_stop_recorded_after_the_cancel_does_not_replace_it(self, db):
        job = _job(db)
        assert db.jobs.transition(job.id, ("running",), "cancelled")
        pr._fail_keeping_work(db, job.id, pr.STOPPED_MESSAGE)
        assert db.jobs.get(job.id).status == "cancelled"

    def test_a_run_cancelled_before_it_started_does_not_start(self, db, monkeypatch):
        job = _job(db, status="queued")
        assert db.jobs.transition(job.id, ("queued",), "cancelled")

        def checkout(*a, **k):
            raise AssertionError("a cancelled job was started")
        monkeypatch.setattr(pr, "_checkout", checkout)
        pr._inner_run_locked(db, job.id, db.projects.get("p1"))
        assert db.jobs.get(job.id).status == "cancelled"


class TestTheCancelRoute:
    def test_a_run_that_ended_first_answers_job_finished(self, client, auth_header, db):
        job = _job(db)
        assert db.jobs.transition(job.id, ("running",), "complete")
        r = client.post(f"/api/v1/projects/p1/jobs/{job.id}/cancel", headers=auth_header)
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["code"] == "JOB_FINISHED"
        assert db.jobs.get(job.id).status == "complete"

    def test_a_running_job_is_cancelled(self, client, auth_header, db, monkeypatch):
        monkeypatch.setattr(pr, "cancel_subprocess", lambda job_id: None)
        monkeypatch.setattr(pr, "stop_background_run", lambda job: False)
        job = _job(db)
        r = client.post(f"/api/v1/projects/p1/jobs/{job.id}/cancel", headers=auth_header)
        assert r.status_code == 200, r.text
        got = db.jobs.get(job.id)
        assert got.status == "cancelled" and got.completed_at is not None
