"""The job queue and its scheduler (docs/spec/JOB_SCHEDULING_SPEC.md, JOB_SCHEDULING_DESIGN.md).

Both database backends, a FRESH database per test: a scheduler looks at every project, so a job
another test left waiting would take the slot this one frees. The scheduler is installed with a
launch that only records -- no pipeline runs here.
"""
import datetime
import uuid

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from api.db.in_memory import InMemoryDatabase
from api.db.postgres.database import SqlDatabase
from api.models.domain import (AnalysisJob, AnalysisPhase, JOB_STATUSES, Project,
                               REEXPORT_MODE, EXPORT_MODE)
from api.services import job_queue as q
from api.services import job_scheduler
from api.services import pipeline_runner as pr

UTC = datetime.timezone.utc


def _fresh_sql() -> SqlDatabase:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _rec):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")
    return SqlDatabase(engine, create_schema=True).seed()


@pytest.fixture(params=["memory", "sql"])
def db(request):
    """This module's own database, fresh for each test (it overrides the session's)."""
    return InMemoryDatabase() if request.param == "memory" else _fresh_sql()


def _now():
    return datetime.datetime.now(UTC)


@pytest.fixture
def settings(monkeypatch):
    """This machine's config.local.json is not read: the defaults, as a test sets them -- the cap
    out of the way (the session's database keeps every earlier test's running jobs); the tests of
    the cap set it from what runs."""
    s = {"maxGenerations": 10000, "startQueuedAfterRestart": False, "pausedDays": 7,
         "interruptedAfterMinutes": 10, "keepFinishedDays": 90}
    monkeypatch.setattr(q, "_SETTINGS", s)
    return s


@pytest.fixture
def sched(db, settings, monkeypatch):
    """A scheduler on the test's database whose launch records the jobs it starts."""
    monkeypatch.setattr(q, "_kick", q._kick)            # put back after the test
    monkeypatch.setattr(q, "_try_start", q._try_start)
    launched = []
    s = job_scheduler.install(db, launch=lambda d, job, resumed: launched.append(
        (job.id, resumed)))
    s.launched = launched
    return s


def _project(db, **kw):
    pid = "pjq" + uuid.uuid4().hex[:6]
    db.projects.create(Project(
        id=pid, org_id="org1", name=pid, client="c", compliance_standard="ASPICE_L2",
        repo_url="https://example.invalid/r.git", repo_provider="github", default_branch="main",
        build_config={}, architecture_layers=[], status="not_run", created_by="u1",
        created_at=_now(), updated_at=_now(), **kw))
    return db.projects.get(pid)


def _job(project, tag=None, *, mode="auto", version_id=None, commit=None, scope=None,
         started_by=None, reason=None):
    commit = commit or uuid.uuid4().hex + "00000000"      # its own: no two are duplicates
    return AnalysisJob(
        id="job" + uuid.uuid4().hex[:8], project_id=project.id, commit_sha=commit,
        version_id=version_id, reference_version_id=None, status="queued",
        pause_after_phase1=False, layer_filter=None, phase=1, phase_pct=0,
        current_activity="", activity_detail="", elapsed_seconds=0, eta_seconds=None,
        phases=[AnalysisPhase(1, "Parse C++", "pending", None)], started_at=None,
        completed_at=None, error_message=None, version_tag=tag, mode=mode, scope=scope,
        started_by=started_by, reason=reason)


def _generation(db, project, tag, **kw):
    """A generation as `POST /jobs` makes it: its version reserved first."""
    job = _job(project, tag, version_id="ver" + uuid.uuid4().hex[:8], **kw)
    pr._reserve_version(db, job, project)
    return job


def _update(db, project, version_id, components=None, **kw):
    scope = {"type": "component", "names": components} if components else None
    return _job(project, mode=REEXPORT_MODE, version_id=version_id, scope=scope, **kw)


def _set(db, job, status, **values):
    assert db.jobs.transition(job.id, JOB_STATUSES, status, **values)


# ---------------------------------------------------------------------------
# submitting (REQ-JS-04, 06-09)
# ---------------------------------------------------------------------------
class TestSubmit:
    def test_a_free_lane_starts_the_job_at_once(self, db, sched):
        project = _project(db)
        answer = q.enqueue(db, _generation(db, project, "v1"), actor_id="u1")
        assert answer.status == "running" and answer.message == "Starts now"
        assert sched.launched == [(answer.job.id, False)]
        assert db.jobs.get(answer.job.id).heartbeat_at is not None

    def test_a_busy_lane_makes_it_wait_with_its_place(self, db, sched):
        project = _project(db)
        first = q.enqueue(db, _generation(db, project, "v1"), actor_id="u1")
        second = q.enqueue(db, _generation(db, project, "v2"), actor_id="u1")
        third = q.enqueue(db, _generation(db, project, "v3"), actor_id="u1")
        assert first.status == "running"
        assert (second.status, second.position) == ("queued", 1)
        assert (third.status, third.position) == ("queued", 2)
        assert third.message.startswith("Waits as #2")
        assert [a["job_id"] for a in third.ahead] == [first.job.id, second.job.id]
        stored = db.jobs.get(third.job.id)
        assert stored.current_activity.startswith("Waiting as #2")
        assert stored.started_at is None, "it has not started"

    def test_the_lane_limit_refuses_the_next_one_naming_the_jobs(self, db, sched):
        project = _project(db, generation_limit=2)
        a = q.enqueue(db, _generation(db, project, "v1"), actor_id="u1")
        b = q.enqueue(db, _generation(db, project, "v2"), actor_id="u1")
        with pytest.raises(q.JobRefused) as refused:
            q.enqueue(db, _generation(db, project, "v3"), actor_id="u1")
        assert refused.value.code == "LANE_FULL" and refused.value.status == 409
        detail = refused.value.detail()
        assert [j["job_id"] for j in detail["running"]] == [a.job.id]
        assert [j["job_id"] for j in detail["waiting"]] == [b.job.id]
        assert "2 of 2" in detail["message"]

    def test_lowering_a_limit_removes_nothing(self, db, sched):
        project = _project(db)
        jobs = [q.enqueue(db, _generation(db, project, "v%d" % i), actor_id="u1").job
                for i in range(3)]
        q.set_limits(db, project, "u1", generation_limit=1)
        assert all(db.jobs.get(j.id).status in ("running", "queued") for j in jobs)
        with pytest.raises(q.JobRefused):
            q.enqueue(db, _generation(db, project, "v9"), actor_id="u1")

    def test_an_identical_waiting_generation_is_refused(self, db, sched):
        project = _project(db)
        q.enqueue(db, _generation(db, project, "v1"), actor_id="u1")
        waiting = q.enqueue(db, _generation(db, project, "v2", commit="a" * 40), actor_id="u1")
        with pytest.raises(q.JobRefused) as refused:
            q.enqueue(db, _generation(db, project, "v3", commit="a" * 40), actor_id="u1")
        assert refused.value.code == "DUPLICATE_JOB"
        assert refused.value.extra["job_id"] == waiting.job.id

    def test_a_retried_request_answers_its_first_job(self, db, sched):
        project = _project(db)
        first = q.enqueue(db, _generation(db, project, "v1"), actor_id="u1", request_key="k1")
        again = q.enqueue(db, _generation(db, project, "v2"), actor_id="u1", request_key="k1")
        assert again.job.id == first.job.id
        assert len(db.jobs.lane_jobs(project.id, q.IN_LANE)) == 1

    def test_an_update_covered_by_a_waiting_one_is_already_queued(self, db, sched):
        project = _project(db)
        ver = _generation(db, project, "v1").version_id
        q.enqueue(db, _update(db, project, ver, ["A"]), actor_id="u1")      # running
        waiting = q.enqueue(db, _update(db, project, ver, ["A", "B"]), actor_id="u1")

        def covers(mine):
            hit = next((j for j in mine if j.status == "queued"), None)
            return ("already_queued", hit) if hit else None
        same = q.enqueue(db, _update(db, project, ver, ["B"]), actor_id="u1", covers=covers)
        assert (same.status, same.job.id) == ("already_queued", waiting.job.id)


# ---------------------------------------------------------------------------
# the order (REQ-JS-11, 12, 13) and the cap (REQ-JS-05)
# ---------------------------------------------------------------------------
class TestOrder:
    def test_high_priority_goes_first_within_a_project(self, db, sched):
        project = _project(db)
        running = q.enqueue(db, _generation(db, project, "v1"), actor_id="u1").job
        normal = q.enqueue(db, _generation(db, project, "v2"), actor_id="u1").job
        high = q.enqueue(db, _generation(db, project, "v3"), actor_id="u1", priority="high").job
        assert q.answer_for(db, high).position == 1
        _set(db, running, "complete", completed_at=_now())
        sched.round(sweep=False)
        assert db.jobs.get(high.id).status == "running"
        assert db.jobs.get(normal.id).status == "queued"

    def test_updates_are_first_come_first_served(self, db, sched):
        project = _project(db)
        ver1 = _generation(db, project, "v1").version_id
        ver2 = _generation(db, project, "v2").version_id
        a = q.enqueue(db, _update(db, project, ver1), actor_id="u1").job
        b = q.enqueue(db, _update(db, project, ver2), actor_id="u1").job
        c = q.enqueue(db, _update(db, project, ver1, ["X"]), actor_id="u1").job
        assert db.jobs.get(a.id).status == "running"
        _set(db, a, "complete", completed_at=_now())
        sched.round(sweep=False)
        assert db.jobs.get(b.id).status == "running" and db.jobs.get(c.id).status == "queued"

    def test_the_server_cap_counts_generations_of_every_project(self, db, sched, settings):
        before = len([j for j in db.jobs.in_status(("running",)) if j.lane == "generation"])
        settings["maxGenerations"] = before + 2
        p1, p2, p3 = _project(db), _project(db), _project(db)
        a = q.enqueue(db, _generation(db, p1, "v1"), actor_id="u1")
        b = q.enqueue(db, _generation(db, p2, "v1"), actor_id="u1")
        c = q.enqueue(db, _generation(db, p3, "v1"), actor_id="u1")
        assert (a.status, b.status, c.status) == ("running", "running", "queued")
        assert db.jobs.get(c.job.id).current_activity == "Waiting for a free server slot"
        _set(db, a.job, "complete", completed_at=_now())
        sched.round(sweep=False)
        assert db.jobs.get(c.job.id).status == "running"

    def test_the_longest_waiting_head_takes_a_free_slot(self, db, sched, settings):
        """REQ-JS-13's example: the slot goes to C, waiting since 10:00, not A's next job."""
        running = len([j for j in db.jobs.in_status(("running",)) if j.lane == "generation"])
        settings["maxGenerations"] = running + 2
        pa, pb, pc = _project(db), _project(db), _project(db)
        a = q.enqueue(db, _generation(db, pa, "a1"), actor_id="u1").job
        q.enqueue(db, _generation(db, pb, "b1"), actor_id="u1")
        c = q.enqueue(db, _generation(db, pc, "c1"), actor_id="u1").job        # waits: cap
        a_next = q.enqueue(db, _generation(db, pa, "a2"), actor_id="u1").job   # waits: lane
        _set(db, a, "complete", completed_at=_now())
        sched.round(sweep=False)
        assert db.jobs.get(c.id).status == "running"
        assert db.jobs.get(a_next.id).status == "queued"

    def test_a_paused_job_keeps_its_lane_but_not_a_server_slot(self, db, sched, settings):
        running = len([j for j in db.jobs.in_status(("running",)) if j.lane == "generation"])
        settings["maxGenerations"] = running + 1
        pa, pb = _project(db), _project(db)
        a = q.enqueue(db, _generation(db, pa, "a1"), actor_id="u1").job
        _set(db, a, "paused", paused_at=_now())
        next_a = q.enqueue(db, _generation(db, pa, "a2"), actor_id="u1")
        other = q.enqueue(db, _generation(db, pb, "b1"), actor_id="u1")
        assert next_a.status == "queued", "the paused job holds its project's lane"
        assert other.status == "running", "a paused job does not count against the cap"

    def test_an_update_whose_version_is_busy_is_passed(self, db, sched):
        project = _project(db)
        ver1 = _generation(db, project, "v1").version_id
        ver2 = _generation(db, project, "v2").version_id
        export = q.enqueue(db, _job(project, "v1", mode=EXPORT_MODE, version_id=ver1,
                                    reason="export"), actor_id="u1").job
        assert db.jobs.get(export.id).status == "running"
        blocked = q.enqueue(db, _update(db, project, ver1), actor_id="u1")
        assert blocked.status == "queued" and blocked.message.startswith("Waits for")
        later = q.enqueue(db, _update(db, project, ver2), actor_id="u1")
        assert later.status == "running", "passed the blocked one"
        assert q.answer_for(db, blocked.job).position == 1, "it keeps its place"


# ---------------------------------------------------------------------------
# the claim (REQ-JS-15)
# ---------------------------------------------------------------------------
class TestClaim:
    def test_a_job_is_claimed_once(self, db, settings):
        project = _project(db)
        job = _generation(db, project, "v1")
        db.jobs.create(job)
        first = db.jobs.claim(job.id, "queued", cap=None, runner="r1", now=_now())
        second = db.jobs.claim(job.id, "queued", cap=None, runner="r2", now=_now())
        assert (first, second) == (True, False)
        assert db.jobs.get(job.id).runner == "r1"

    def test_two_jobs_of_one_lane_never_run_at_once(self, db, settings):
        project = _project(db)
        a, b = _generation(db, project, "v1"), _generation(db, project, "v2")
        db.jobs.create(a)
        db.jobs.create(b)
        assert db.jobs.claim(a.id, "queued", cap=None, runner="r", now=_now())
        assert not db.jobs.claim(b.id, "queued", cap=None, runner="r", now=_now())

    def test_the_cap_is_checked_in_the_claim(self, db, settings):
        running = len([j for j in db.jobs.in_status(("running",)) if j.lane == "generation"])
        job = _generation(db, _project(db), "v1")
        db.jobs.create(job)
        assert not db.jobs.claim(job.id, "queued", cap=running, runner="r", now=_now())
        assert db.jobs.claim(job.id, "queued", cap=running + 1, runner="r", now=_now())


# ---------------------------------------------------------------------------
# held after a restart (REQ-JS-18)
# ---------------------------------------------------------------------------
class TestHeld:
    def test_a_restart_holds_waiting_jobs_and_what_is_submitted_after(self, db, sched):
        project = _project(db)
        q.enqueue(db, _generation(db, project, "v1"), actor_id="u1")
        waiting = q.enqueue(db, _generation(db, project, "v2"), actor_id="u1").job
        held = q.hold_waiting(db)
        assert held.get(project.id) == 1
        assert db.jobs.get(waiting.id).status == "held"
        later = q.enqueue(db, _generation(db, project, "v3"), actor_id="u1")
        assert later.status == "held"
        assert later.message.startswith("Held")

    def test_clear_some_and_start_the_rest_in_their_order(self, db, sched):
        project = _project(db, generation_limit=5)
        running = q.enqueue(db, _generation(db, project, "v1"), actor_id="u1").job
        a = q.enqueue(db, _generation(db, project, "v2"), actor_id="u1").job
        b = q.enqueue(db, _generation(db, project, "v3"), actor_id="u1").job
        c = q.enqueue(db, _generation(db, project, "v4"), actor_id="u1").job
        q.hold_waiting(db)
        out = q.release_held(db, "su", project_id=project.id, remove=[b.id])
        assert out["removed"] == [b.id] and set(out["released"]) == {a.id, c.id}
        assert db.jobs.get(b.id).status == "removed"
        assert db.versions.get(b.version_id) is None, "a removed job's name is free"
        assert [j.id for j in q.lanes_of(db, project.id)["generation"].waiting] == [a.id, c.id]
        assert db.jobs.get(running.id).status == "running"

    def test_clear_all(self, db, sched):
        project = _project(db)
        q.enqueue(db, _generation(db, project, "v1"), actor_id="u1")
        a = q.enqueue(db, _generation(db, project, "v2"), actor_id="u1").job
        q.hold_waiting(db)
        q.release_held(db, "su", project_id=project.id, remove="all")
        assert db.jobs.get(a.id).status == "removed"


# ---------------------------------------------------------------------------
# pause, resume, cancel, remove (REQ-JS-22-26)
# ---------------------------------------------------------------------------
class TestActions:
    def test_pause_is_asked_of_a_running_generation_only(self, db, sched):
        project = _project(db)
        gen = q.enqueue(db, _generation(db, project, "v1"), actor_id="u1").job
        asked = q.request_pause(db, db.jobs.get(gen.id), "u1")
        assert asked.pause_requested_at is not None
        assert asked.current_activity.startswith("Pausing")
        ver = _generation(db, project, "v2").version_id
        upd = q.enqueue(db, _update(db, project, ver), actor_id="u1").job
        with pytest.raises(q.JobRefused) as refused:
            q.request_pause(db, db.jobs.get(upd.id), "u1")
        assert refused.value.code == "NOT_PAUSABLE"

    def test_a_resumed_job_takes_the_first_free_slot(self, db, sched, settings):
        running = len([j for j in db.jobs.in_status(("running",)) if j.lane == "generation"])
        settings["maxGenerations"] = running + 1
        pa, pb = _project(db), _project(db)
        paused = q.enqueue(db, _generation(db, pa, "a1"), actor_id="u1").job
        _set(db, paused, "paused", paused_at=_now() - datetime.timedelta(hours=1))
        other = q.enqueue(db, _generation(db, pb, "b1"), actor_id="u1").job       # takes the slot
        waiting = q.enqueue(db, _generation(db, pb, "b2"), actor_id="u1").job
        q.request_resume(db, db.jobs.get(paused.id), "u1")
        assert db.jobs.get(paused.id).status == "paused", "no free slot yet"
        _set(db, other, "complete", completed_at=_now())
        sched.round(sweep=False)
        resumed = db.jobs.get(paused.id)
        assert resumed.status == "running" and (paused.id, True) in sched.launched
        assert resumed.paused_seconds >= 3500, "its paused hour is not counted"
        assert db.jobs.get(waiting.id).status == "queued"

    def test_removing_a_waiting_generation_frees_its_name(self, db, sched):
        project = _project(db)
        q.enqueue(db, _generation(db, project, "v1"), actor_id="u1")
        waiting = q.enqueue(db, _generation(db, project, "v2"), actor_id="u1").job
        user = type("U", (), {"id": "u1", "name": "Una", "is_superuser": True})()
        q.cancel(db, db.jobs.get(waiting.id), user)
        assert db.jobs.get(waiting.id).status == "removed"
        assert db.versions.get_by_tag(project.id, "v2") is None

    def test_a_paused_job_cancelled_deletes_a_version_that_never_finished(self, db, sched):
        project = _project(db)
        job = q.enqueue(db, _generation(db, project, "v1"), actor_id="u1").job
        _set(db, job, "paused", paused_at=_now())
        user = type("U", (), {"id": "u1", "name": "Una", "is_superuser": True})()
        q.cancel(db, db.jobs.get(job.id), user)
        assert db.jobs.get(job.id).status == "cancelled"
        assert db.versions.get(job.version_id) is None

    def test_a_cli_run_is_not_cancelled_from_the_web(self, db, sched):
        project = _project(db)
        job = q.enqueue(db, _generation(db, project, "v1"), actor_id="u1").job
        _set(db, job, "running", origin="cli", runner="cli dev@host pid 7")
        user = type("U", (), {"id": "u1", "name": "Una", "is_superuser": True})()
        with pytest.raises(q.JobRefused) as refused:
            q.cancel(db, db.jobs.get(job.id), user)
        assert refused.value.code == "CLI_RUN" and "dev@host" in refused.value.message


# ---------------------------------------------------------------------------
# sweeps: silent, paused too long, records (REQ-JS-20, 24, 34)
# ---------------------------------------------------------------------------
class TestSweeps:
    def test_a_silent_job_is_interrupted_and_the_next_starts(self, db, sched, monkeypatch):
        project = _project(db)
        silent = q.enqueue(db, _generation(db, project, "v1"), actor_id="u1").job
        waiting = q.enqueue(db, _generation(db, project, "v2"), actor_id="u1").job
        _set(db, silent, "running", heartbeat_at=_now() - datetime.timedelta(minutes=11))
        sched._db_up_since = 0.0                          # the database has answered long since
        sched.sweep()
        gone = db.jobs.get(silent.id)
        assert gone.status == "interrupted" and gone.error_message.startswith("Interrupted")
        assert "- Start it again" in gone.error_message
        sched.round(sweep=False)
        assert db.jobs.get(waiting.id).status == "running"

    def test_nobody_is_interrupted_just_after_an_outage(self, db, sched):
        project = _project(db)
        job = q.enqueue(db, _generation(db, project, "v1"), actor_id="u1").job
        _set(db, job, "running", heartbeat_at=_now() - datetime.timedelta(minutes=30))
        sched._db_up_since = None
        sched.round()                                     # the database answers again now
        assert db.jobs.get(job.id).status == "running"

    def test_a_job_paused_too_long_is_cancelled(self, db, sched, settings):
        project = _project(db)
        job = q.enqueue(db, _generation(db, project, "v1"), actor_id="u1").job
        _set(db, job, "paused", paused_at=_now() - datetime.timedelta(days=8))
        sched.sweep()
        assert db.jobs.get(job.id).status == "cancelled"
        assert "paused for 7 days" in db.jobs.get(job.id).error_message

    def test_old_records_go_but_a_versions_generation_job_stays(self, db, settings):
        project = _project(db)
        gen = _generation(db, project, "v1")
        db.jobs.create(gen)
        _set(db, gen, "complete", completed_at=_now() - datetime.timedelta(days=200))
        update = _update(db, project, gen.version_id)
        db.jobs.create(update)
        _set(db, update, "complete", completed_at=_now() - datetime.timedelta(days=200))
        db.jobs.prune_ended(_now() - datetime.timedelta(days=90))
        assert db.jobs.get(gen.id) is not None and db.jobs.get(update.id) is None


# ---------------------------------------------------------------------------
# a run from the command line (REQ-JS-27..29)
# ---------------------------------------------------------------------------
def _cli(db, project, command="generate", **kw):
    version_id = kw.pop("version_id", None) or _generation(db, project, "c" + uuid.uuid4().hex[:4]
                                                          ).version_id
    return q.record_cli_run(db, command, project_id=project.id, version_id=version_id,
                            version_tag="cli", **kw)


class TestCommandLine:
    def test_a_free_lane_records_the_run_as_running(self, db, sched):
        project = _project(db)
        job = _cli(db, project)
        got = db.jobs.get(job.id)
        assert (got.status, got.origin, got.lane, got.forced) == ("running", "cli", "generation",
                                                                  False)
        assert got.runner.startswith("cli ") and got.heartbeat_at is not None
        assert [e.kind for e in db.job_events.list_for_job(job.id)] == ["submitted", "started"]

    def test_a_busy_lane_refuses_naming_the_job(self, db, sched):
        project = _project(db)
        web = q.enqueue(db, _generation(db, project, "v1"), actor_id="u1").job
        with pytest.raises(q.JobRefused) as refused:
            _cli(db, project)
        assert refused.value.code == "LANE_BUSY"
        assert [j["job_id"] for j in refused.value.extra["jobs"]] == [web.id]
        assert web.id in refused.value.message and "--ignore-queue" in refused.value.message

    def test_waiting_jobs_refuse_it_too(self, db, sched):
        project = _project(db)
        waiting = _generation(db, project, "v1")
        db.jobs.create(waiting)                         # waits: no round has started it
        with pytest.raises(q.JobRefused) as refused:
            _cli(db, project)
        assert refused.value.code == "JOBS_WAITING"

    def test_the_cap_refuses_a_generation_not_an_update(self, db, sched, settings):
        running = len([j for j in db.jobs.in_status(("running",)) if j.lane == "generation"])
        settings["maxGenerations"] = running + 1
        q.enqueue(db, _generation(db, _project(db), "v1"), actor_id="u1")
        project = _project(db)
        with pytest.raises(q.JobRefused) as refused:
            _cli(db, project)
        assert refused.value.code == "SERVER_FULL"
        ver = _generation(db, project, "v2").version_id
        assert _cli(db, project, "reexport", version_id=ver).lane == "update"

    def test_ignore_queue_runs_beside_the_lane_s_job_and_the_lane_stays_taken(self, db, sched):
        project = _project(db)
        web = q.enqueue(db, _generation(db, project, "v1"), actor_id="u1").job
        cli = _cli(db, project, ignore_queue=True)
        assert db.jobs.get(cli.id).forced is True
        waiting = q.enqueue(db, _generation(db, project, "v2"), actor_id="u1").job
        _set(db, web, "complete", completed_at=_now())
        sched.round(sweep=False)
        assert db.jobs.get(waiting.id).status == "queued", "the forced run still holds the lane"
        assert q.end_cli_run(db, cli.id, "complete")
        sched.round(sweep=False)
        assert db.jobs.get(waiting.id).status == "running"

    def test_its_end_is_its_own_and_frees_the_lane(self, db, sched):
        project = _project(db)
        cli = _cli(db, project)
        waiting = q.enqueue(db, _generation(db, project, "v1"), actor_id="u1").job
        assert db.jobs.get(waiting.id).status == "queued"
        assert q.end_cli_run(db, cli.id, "failed", "Failed: exit code 1.")
        got = db.jobs.get(cli.id)
        assert (got.status, got.error_message) == ("failed", "Failed: exit code 1.")
        sched.round(sweep=False)
        assert db.jobs.get(waiting.id).status == "running"
        assert not q.end_cli_run(db, cli.id, "complete"), "ended once"

    def test_a_project_with_no_row_is_refused_with_the_way_to_onboard_it(self, db, sched):
        with pytest.raises(q.JobRefused) as refused:
            q.record_cli_run(db, "generate", project_id="p-none", version_id=None)
        assert refused.value.code == "NO_PROJECT" and "analyzer.py onboard" in refused.value.message

    def test_a_run_interrupted_while_silent_takes_its_real_end(self, db, sched):
        project = _project(db)
        cli = _cli(db, project)
        assert q.interrupt(db, db.jobs.get(cli.id), "Interrupted: silent.")
        assert q.end_cli_run(db, cli.id, "complete")
        assert db.jobs.get(cli.id).status == "complete"


# ---------------------------------------------------------------------------
# the record and the notices (REQ-JS-32, 33)
# ---------------------------------------------------------------------------
class TestRecord:
    def test_each_step_is_recorded_with_its_person(self, db, sched):
        project = _project(db)
        job = q.enqueue(db, _generation(db, project, "v1"), actor_id="u1").job
        q.request_pause(db, db.jobs.get(job.id), "u2")
        kinds = [(e.kind, e.actor_id) for e in db.job_events.list_for_job(job.id)]
        assert ("submitted", "u1") in kinds and ("started", None) in kinds
        assert ("pause_requested", "u2") in kinds

    def test_an_end_is_told_once(self, db, sched):
        project = _project(db)
        job = q.enqueue(db, _generation(db, project, "v1"), actor_id="u1").job
        _set(db, job, "complete", completed_at=_now())
        q.after_end(db, job.id)
        q.after_end(db, job.id)
        assert [e.kind for e in db.job_events.list_for_job(job.id)].count("completed") == 1
