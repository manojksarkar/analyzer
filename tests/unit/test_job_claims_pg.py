"""The job queue's guarantees on a real PostgreSQL (docs/design/JOB_SCHEDULING_DESIGN.md §2, §5, §7,
§11; docs/spec/JOB_SCHEDULING_SPEC.md REQ-JS-05, 14, 15, 18, 20, 28): what SQLite cannot show --
claims made at the same moment by several connections, the advisory lock they take turns under,
the partial unique index, and the version writer's lock that keeps a silent job from being
interrupted. Needs a scratch PostgreSQL database and is skipped without one:

    ANALYZER_TEST_PG_DSN=postgresql+psycopg://user:pw@127.0.0.1:5432/scratch \
        python -m pytest tests/unit/test_job_claims_pg.py

The schema is made in it (`metadata.create_all`) and the rows of each test go with their project.
"""
import datetime
import os
import sys
import threading
import uuid

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "engine")]

DSN = os.environ.get("ANALYZER_TEST_PG_DSN", "").strip()
if not DSN:
    pytest.skip("set ANALYZER_TEST_PG_DSN to a scratch Postgres database", allow_module_level=True)

UTC = datetime.timezone.utc


def _now():
    return datetime.datetime.now(UTC)


@pytest.fixture(scope="module")
def engine():
    from sqlalchemy import create_engine
    from api.db.postgres import schema as s
    eng = create_engine(DSN, pool_size=10)
    s.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    from api.db.postgres.database import SqlDatabase
    return SqlDatabase(engine)


@pytest.fixture
def project(db):
    from api.models.domain import Project
    pid = "ppg" + uuid.uuid4().hex[:6]
    db.projects.create(Project(
        id=pid, org_id="org1", name=pid, client="c", compliance_standard="ASPICE_L2",
        repo_url="", repo_provider="github", default_branch="main", build_config={},
        architecture_layers=[], status="not_run", created_by="u1", created_at=_now(),
        updated_at=_now()))
    yield db.projects.get(pid)
    import sqlalchemy as sa
    from api.db.postgres import schema as s
    with db._engine.begin() as cx:
        cx.execute(sa.delete(s.job_events).where(s.job_events.c.project_id == pid))
        cx.execute(sa.delete(s.analysis_jobs).where(s.analysis_jobs.c.project_id == pid))
        cx.execute(sa.delete(s.projects).where(s.projects.c.id == pid))


def _job(db, project, *, status="queued", lane="generation", forced=False):
    from api.models.domain import AnalysisJob
    job = AnalysisJob(
        id="job" + uuid.uuid4().hex[:8], project_id=project.id, commit_sha="a" * 40,
        version_id=None, reference_version_id=None, status=status, pause_after_phase1=False,
        layer_filter=None, phase=1, phase_pct=0, current_activity="", activity_detail="",
        elapsed_seconds=0, eta_seconds=None, phases=[], started_at=None, completed_at=None,
        error_message=None, mode="reexport" if lane == "update" else "auto",
        submitted_at=_now(), forced=forced)
    db.jobs.create(job)
    return job


def _at_once(n, fn):
    """`fn(i)` on `n` threads released together; their answers."""
    gate, out = threading.Barrier(n), [None] * n

    def run(i):
        gate.wait()
        out[i] = fn(i)
    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    return out


class TestClaims:
    def test_one_job_claimed_at_once_by_many_starts_once(self, db, project):
        job = _job(db, project)
        got = _at_once(8, lambda i: db.jobs.claim(job.id, "queued", cap=None,
                                                  runner="r%d" % i, now=_now()))
        assert got.count(True) == 1
        assert db.jobs.get(job.id).status == "running"

    def test_a_lane_s_waiting_jobs_claimed_at_once_start_one(self, db, project):
        jobs = [_job(db, project) for _ in range(6)]
        got = _at_once(6, lambda i: db.jobs.claim(jobs[i].id, "queued", cap=None,
                                                  runner="r", now=_now()))
        assert got.count(True) == 1
        assert len(db.jobs.lane_jobs(project.id, ("running",))) == 1

    def test_the_cap_holds_under_claims_at_once(self, db, engine):
        from api.models.domain import Project
        running = len([j for j in db.jobs.in_status(("running",)) if j.lane == "generation"])
        projects = []
        for _ in range(5):
            pid = "ppg" + uuid.uuid4().hex[:6]
            db.projects.create(Project(
                id=pid, org_id="org1", name=pid, client="c", compliance_standard="ASPICE_L2",
                repo_url="", repo_provider="github", default_branch="main", build_config={},
                architecture_layers=[], status="not_run", created_by="u1", created_at=_now(),
                updated_at=_now()))
            projects.append(db.projects.get(pid))
        try:
            jobs = [_job(db, p) for p in projects]
            got = _at_once(5, lambda i: db.jobs.claim(jobs[i].id, "queued", cap=running + 2,
                                                      runner="r", now=_now()))
            assert got.count(True) == 2
        finally:
            import sqlalchemy as sa
            from api.db.postgres import schema as s
            with engine.begin() as cx:
                ids = [p.id for p in projects]
                cx.execute(sa.delete(s.analysis_jobs).where(s.analysis_jobs.c.project_id.in_(ids)))
                cx.execute(sa.delete(s.projects).where(s.projects.c.id.in_(ids)))

    def test_command_line_runs_recorded_at_once_in_a_free_lane_start_one(self, db, project,
                                                                        monkeypatch):
        """Each checks the lane and records itself in one transaction, under the queue's lock
        and the project's row lock: the others find the lane taken (REQ-JS-28, 29)."""
        from api.services import job_queue as q
        monkeypatch.setattr(q, "_SETTINGS", {"maxGenerations": 10000})

        def go(i):
            try:
                q.record_cli_run(db, "generate", project_id=project.id, version_id=None,
                                 version_tag="cli%d" % i)
                return "recorded"
            except q.JobRefused as exc:
                return exc.code
        got = _at_once(4, go)
        assert sorted(got) == ["LANE_BUSY"] * 3 + ["recorded"]
        assert len(db.jobs.lane_jobs(project.id, ("running",))) == 1

    def test_a_claim_and_a_command_line_run_never_both_run(self, db, project, monkeypatch):
        """A job waits; the CLI run is refused whichever goes first, and one job runs."""
        from api.services import job_queue as q
        monkeypatch.setattr(q, "_SETTINGS", {"maxGenerations": 10000})
        waiting = _job(db, project)

        def go(i):
            if i == 0:
                return db.jobs.claim(waiting.id, "queued", cap=None, runner="api", now=_now())
            try:
                q.record_cli_run(db, "generate", project_id=project.id, version_id=None,
                                 version_tag="cli")
                return "recorded"
            except q.JobRefused as exc:
                return exc.code
        claimed, cli = _at_once(2, go)
        assert claimed is True and cli in ("LANE_BUSY", "JOBS_WAITING")
        assert [j.id for j in db.jobs.lane_jobs(project.id, ("running",))] == [waiting.id]


class TestTheUniqueIndex:
    def test_a_second_running_job_of_a_lane_is_refused(self, db, project):
        from sqlalchemy.exc import IntegrityError
        _job(db, project, status="running")
        with pytest.raises(IntegrityError):
            _job(db, project, status="paused")

    def test_a_forced_one_and_the_other_lane_are_not(self, db, project):
        _job(db, project, status="running")
        _job(db, project, status="running", forced=True)
        _job(db, project, status="running", lane="update")
        assert len(db.jobs.lane_jobs(project.id, ("running",))) == 3

    def test_a_status_change_into_a_taken_lane_is_not_made(self, db, project):
        _job(db, project, status="running")
        waiting = _job(db, project)
        assert db.jobs.transition(waiting.id, ("queued",), "running") is False
        assert db.jobs.get(waiting.id).status == "queued"


class TestTheSweep:
    def test_a_silent_job_whose_version_is_being_written_is_not_interrupted(
            self, db, project, monkeypatch):
        """Its process is alive -- it holds the version's writer lock -- though its alive signal
        is old (a long stall, a clock): never interrupted while the lock is held."""
        from api.models.domain import Version
        from api.services import job_queue as q, job_scheduler
        from core.version_run import writing
        monkeypatch.setattr(q, "_SETTINGS", {"interruptedAfterMinutes": 10, "pausedDays": 7,
                                             "keepFinishedDays": 90})
        vid = "verpg" + uuid.uuid4().hex[:6]
        db.versions.create(Version(id=vid, project_id=project.id, tag="v1", commit_sha="a" * 40,
                                   branch="main", description="", status="draft", docs_count=0,
                                   created_by="u1", created_at=_now()))
        job = _job(db, project, status="running")
        old = _now() - datetime.timedelta(minutes=30)
        assert db.jobs.transition(job.id, ("running",), "running", version_id=vid,
                                  heartbeat_at=old, started_at=old)
        sched = job_scheduler.Scheduler(db, lambda *a: None)
        sched._db_up_since = 0.0
        with writing(vid, command="generate", engine=db._engine):
            sched.sweep()
            assert db.jobs.get(job.id).status == "running"
        sched.sweep()
        assert db.jobs.get(job.id).status == "interrupted"
