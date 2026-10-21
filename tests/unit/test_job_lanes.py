"""The lane rule the API's queue and the command line share (engine/core/job_lanes.py;
docs/design/JOB_SCHEDULING_DESIGN.md §11, docs/spec/JOB_SCHEDULING_SPEC.md REQ-JS-28)."""
import datetime
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from core import job_lanes as L

pytestmark = pytest.mark.unit


def _job(status, job_id=None, lane=L.GENERATION):
    return SimpleNamespace(id=job_id or status, status=status, lane=lane)


class TestTheCommandLinesRule:
    def test_a_free_lane_and_room_on_the_server(self):
        assert L.cli_refusal(L.GENERATION, [], 1, 2) is None

    def test_a_job_running_or_paused_takes_the_lane_and_the_waiting_are_named_too(self):
        running, paused, waiting = _job("running"), _job("paused"), _job("queued")
        assert L.cli_refusal(L.GENERATION, [waiting, running], 0, 2) == ("busy", [running,
                                                                                 waiting])
        assert L.cli_refusal(L.UPDATE, [paused], 0, 2) == ("busy", [paused])

    def test_jobs_waiting_refuse_a_run_that_would_go_before_them(self):
        held = _job("held")
        assert L.cli_refusal(L.UPDATE, [held], 0, None) == ("waiting", [held])

    def test_the_cap_holds_back_a_generation_only(self):
        assert L.cli_refusal(L.GENERATION, [], 2, 2) == ("cap", [])
        assert L.cli_refusal(L.UPDATE, [], 2, 2) is None
        assert L.cli_refusal(L.GENERATION, [], 5, None) is None

    def test_every_writing_command_has_its_lane(self):
        assert L.COMMAND_LANES == {"generate": "generation", "export": "generation",
                                   "resume": "generation", "reexport": "update"}
        assert (L.lane_of_mode("reexport"), L.lane_of_mode("export"),
                L.lane_of_mode(None)) == ("update", "generation", "generation")


class TestOneVocabulary:
    def test_the_api_s_statuses_are_the_lanes(self):
        """api/models/domain.py names the same statuses: a status added to one and not the other
        would be counted by the queue and not by the claim, or the reverse."""
        from api.models import domain
        assert domain.JOB_LANE_STATUSES == L.IN_LANE
        assert domain.JOB_HOLDING_STATUSES == L.HOLDING
        assert domain.JOB_ENDED_STATUSES == L.ENDED
        assert set(domain.JOB_STATUSES) == set(L.IN_LANE + L.ENDED)
        assert domain.REEXPORT_MODE == L.UPDATE_MODE


class TestTheCounts:
    """What a claim and a command-line record count, on the schema's own table."""

    @pytest.fixture
    def cx(self):
        from api.db.postgres import schema as s
        engine = sa.create_engine("sqlite://")
        s.metadata.create_all(engine)
        now = datetime.datetime.now(datetime.timezone.utc)
        with engine.begin() as cx:
            cx.execute(sa.insert(s.projects), [{"id": p, "name": p, "created_at": now}
                                               for p in ("pa", "pb")])
            rows = [("j1", "pa", "generation", "running", "v1"),
                    ("j2", "pa", "update", "paused", "v1"),
                    ("j3", "pb", "generation", "running", None),
                    ("j4", "pb", "generation", "queued", None),
                    ("j5", "pb", "update", "complete", None)]
            cx.execute(sa.insert(s.analysis_jobs), [
                {"id": i, "project_id": p, "lane": lane, "status": st, "version_id": None,
                 "forced": i == "j3"} for i, p, lane, st, _v in rows])
        with engine.connect() as cx:
            yield cx, s.analysis_jobs

    def test_holding_in_a_lane(self, cx):
        cx, t = cx
        assert L.holding(cx, t, project_id="pa", lane="generation") == 1
        assert L.holding(cx, t, project_id="pa") == 2
        assert L.holding(cx, t, project_id="pa", lane="generation", but="j1") == 0
        assert L.holding(cx, t, project_id="pb", lane="update") == 0

    def test_running_generations_count_every_project_forced_too_paused_not(self, cx):
        cx, t = cx
        assert L.running_generations(cx, t) == 2
        assert L.running_generations(cx, t, but="j3") == 1

    def test_the_queue_lock_is_postgres_only(self, cx):
        cx, _t = cx
        L.lock_queue(cx)                                # SQLite: nothing to take, no error
