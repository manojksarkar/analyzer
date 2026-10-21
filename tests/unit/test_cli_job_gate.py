"""A run from the command line is a job of its project's lane (docs/design/JOB_SCHEDULING_DESIGN.md
§11; docs/spec/JOB_SCHEDULING_SPEC.md REQ-JS-27..29): checked and recorded before it starts, sending
its alive signal, and ended by its own run -- a web job's run (`--job-id`) is the API's to end.

Through `analyzer.main()`, on a SQLite file of the test's own; the command's work is stood in for.
"""
import datetime
import os
import uuid

import pytest

pytestmark = pytest.mark.unit

UTC = datetime.timezone.utc
P = "pcli"


@pytest.fixture
def db(tmp_path, monkeypatch):
    """The run's database: a SQLite file with the schema, project P in it. This machine's
    configured database is never reached."""
    import core.db as core_db
    from api.db.postgres import schema as s
    from api.db.postgres.database import SqlDatabase
    from api.models.domain import Project
    from api.services import job_queue as q
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + (tmp_path / "jobs.db").as_posix())
    monkeypatch.setattr(q, "_SETTINGS", {"maxGenerations": 2, "startQueuedAfterRestart": False,
                                         "pausedDays": 7, "interruptedAfterMinutes": 10,
                                         "keepFinishedDays": 90})
    monkeypatch.delenv("ANALYZER_JOB_ID", raising=False)
    core_db.reset_engine()
    engine = core_db.get_engine()
    s.metadata.create_all(engine)
    out = SqlDatabase(engine)
    now = datetime.datetime.now(UTC)
    out.projects.create(Project(
        id=P, org_id="org1", name=P, client="c", compliance_standard="ASPICE_L2",
        repo_url="", repo_provider="github", default_branch="main", build_config={},
        architecture_layers=[], status="not_run", created_by="u1", created_at=now,
        updated_at=now))
    yield out
    core_db.reset_engine()
    engine.dispose()


@pytest.fixture
def ran(monkeypatch, db):
    """The commands' work, stood in for: what each saw, and what it answers (`ran.rc`, or
    `ran.raises`)."""
    import analyzer

    class Ran(list):
        rc, raises = 0, None

    calls = Ran()

    def stand_in(a):
        job_id = os.environ.get("ANALYZER_JOB_ID")
        job = db.jobs.get(job_id) if job_id else None
        calls.append({"command": a.command, "job_id": job_id,
                      "status": getattr(job, "status", None)})
        if calls.raises is not None:
            raise calls.raises
        return calls.rc

    for name in ("cmd_generate", "cmd_export", "cmd_resume", "cmd_reexport"):
        monkeypatch.setattr(analyzer, name, stand_in)
    return calls


def _main(*args):
    import analyzer
    return analyzer.main(list(args))


def _generate(*extra):
    return _main("generate", "--project-id", P, "--version-id", "v1", "--commit", "a" * 40,
                 *extra)


def _cli_jobs(db):
    """Every command-line job, of any state."""
    from api.services import job_queue as q
    return [j for j in db.jobs.in_status(q.IN_LANE + q.ENDED) if j.origin == "cli"]


def _web_job(db, status="running", lane_mode="auto"):
    from api.models.domain import AnalysisJob, AnalysisPhase
    job = AnalysisJob(
        id="job" + uuid.uuid4().hex[:8], project_id=P, commit_sha="b" * 40, version_id=None,
        reference_version_id=None, status=status, pause_after_phase1=False, layer_filter=None,
        phase=1, phase_pct=0, current_activity="", activity_detail="", elapsed_seconds=0,
        eta_seconds=None, phases=[AnalysisPhase(1, "Parse C++", "running", None)],
        started_at=datetime.datetime.now(UTC), completed_at=None, error_message=None,
        version_tag="v0", mode=lane_mode, submitted_at=datetime.datetime.now(UTC))
    db.jobs.create(job)
    return job


class TestARunIsAJobOfItsOwn:
    def test_a_free_lane_runs_it_as_a_job_it_ends_itself(self, db, ran):
        assert _generate() == 0
        (job,) = _cli_jobs(db)
        assert ran == [{"command": "generate", "job_id": job.id, "status": "running"}]
        assert (job.status, job.lane, job.forced) == ("complete", "generation", False)
        assert job.runner.startswith("cli ") and job.version_tag == "v1"
        assert [e.kind for e in db.job_events.list_for_job(job.id)] == [
            "submitted", "started", "completed"]

    @pytest.mark.parametrize("rc, status", [(3, "complete"), (1, "failed"), (2, "failed")])
    def test_its_exit_code_is_its_end(self, db, ran, rc, status):
        ran.rc = rc
        assert _generate() == rc
        (job,) = _cli_jobs(db)
        assert job.status == status
        if status == "failed":
            assert job.error_message.startswith("Failed: analyzer.py generate ended with exit "
                                                "code %d." % rc)

    def test_ctrl_c_cancels_it(self, db, ran):
        ran.raises = KeyboardInterrupt()
        with pytest.raises(KeyboardInterrupt):
            _generate()
        (job,) = _cli_jobs(db)
        assert job.status == "cancelled" and "Ctrl+C" in job.error_message

    def test_an_update_is_the_update_lane_s(self, db, ran):
        assert _main("reexport", "--project-id", P, "--version-id", "v1") == 0
        (job,) = _cli_jobs(db)
        assert (job.lane, job.mode, job.status) == ("update", "reexport", "complete")


class TestTheChecks:
    def test_a_taken_lane_refuses_it_naming_the_job(self, db, ran, capsys):
        web = _web_job(db)
        assert _generate() == 2
        err = capsys.readouterr().err
        assert "Refused: the generation lane of project pcli is taken." in err
        assert web.id in err and "--ignore-queue" in err
        assert ran == [] and _cli_jobs(db) == []

    def test_the_other_lane_is_free(self, db, ran):
        _web_job(db)                                    # a generation runs
        assert _main("reexport", "--project-id", P, "--version-id", "v1") == 0

    def test_ignore_queue_runs_it_beside_the_lane_s_job(self, db, ran, capsys):
        web = _web_job(db)
        assert _generate("--ignore-queue") == 0
        (job,) = _cli_jobs(db)
        assert job.forced is True and job.status == "complete"
        assert "started past the queue" in capsys.readouterr().err
        assert db.jobs.get(web.id).status == "running", "the lane's job is left as it was"


class TestAJobGivenToTheRun:
    def test_a_web_job_s_run_is_that_job_and_the_api_ends_it(self, db, ran):
        web = _web_job(db)
        assert _generate("--job-id", web.id) == 0
        assert ran == [{"command": "generate", "job_id": web.id, "status": "running"}]
        assert db.jobs.get(web.id).status == "running", "its end is the API's"
        assert _cli_jobs(db) == []

    def test_the_background_half_of_a_command_line_run_ends_its_job(self, db, ran):
        from api.services import job_queue as q
        mine = q.record_cli_run(db, "generate", project_id=P, version_id=None, version_tag="v1")
        assert _generate("--job-id", mine.id) == 0
        assert db.jobs.get(mine.id).status == "complete"

    def test_a_job_this_database_does_not_have_does_not_stop_the_run(self, db, ran, capsys):
        assert _generate("--job-id", "job-elsewhere") == 0
        assert ran[0]["job_id"] == "job-elsewhere"
        assert "not in this run's database" in capsys.readouterr().err


class TestDetach:
    def test_the_job_is_recorded_first_and_handed_to_the_background_run(self, db, ran,
                                                                         monkeypatch):
        import analyzer
        seen = []
        monkeypatch.setattr(analyzer, "_detach", lambda a: seen.append(list(a._argv)) or 0)
        assert _generate("--detach") == 0
        (job,) = _cli_jobs(db)
        assert job.status == "running", "the background run ends it"
        assert seen[0][-2:] == ["--job-id", job.id]

    def test_a_launch_that_fails_ends_the_job(self, db, ran, monkeypatch):
        import analyzer
        monkeypatch.setattr(analyzer, "_detach", lambda a: 2)
        assert _generate("--detach") == 2
        (job,) = _cli_jobs(db)
        assert job.status == "failed" and "did not start" in job.error_message


class TestResumeRunsARecordedGenerate:
    def test_without_the_job_it_ran_as(self):
        import analyzer
        assert analyzer._without_job_id(["generate", "--job-id", "j1", "--full",
                                         "--job-id=j2", "--project-id", "p"]) == [
            "generate", "--full", "--project-id", "p"]

    def test_inside_its_own_job_not_as_a_second_one(self, db, ran):
        import analyzer
        assert analyzer.main(["generate", "--project-id", P, "--version-id", "v1", "--commit",
                              "a" * 40], queue=False) == 0
        assert ran[0]["job_id"] is None and _cli_jobs(db) == []


class TestWithoutAQueue:
    def test_no_database_configured_runs_it_as_before(self, db, ran, monkeypatch):
        import core.db as core_db
        monkeypatch.setattr(core_db, "is_database_configured", lambda: False)
        assert _generate() == 0
        assert ran[0]["job_id"] is None and _cli_jobs(db) == []

    def test_a_database_from_before_job_scheduling_is_told_to_upgrade(self, db, ran, capsys,
                                                                      monkeypatch):
        from sqlalchemy.exc import OperationalError
        from api.services import job_queue as q

        def old(*a, **k):
            raise OperationalError("INSERT", {}, Exception("no such column: lane"))
        monkeypatch.setattr(q, "record_cli_run", old)
        assert _generate() == 2
        assert "python analyzer.py setup" in capsys.readouterr().err and ran == []
