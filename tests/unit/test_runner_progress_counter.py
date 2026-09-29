"""The job's progress bar and time-left follow the engine's item counter.

Nothing set `phase_pct`, so the web app showed 0% for a whole phase, and `eta_seconds` was only
the two-minutes-per-phase guess made at each phase transition: "~4m remaining" for an LLM phase
that took an hour.
"""
import types
from unittest.mock import patch

import pytest

from api.services import pipeline_runner as pr


def _job(phase=2):
    return types.SimpleNamespace(id="jobcount", phase=phase, phase_pct=0, eta_seconds=240)


@pytest.fixture(autouse=True)
def _fresh_clock():
    pr._step_clocks.pop("jobcount", None)
    yield
    pr._step_clocks.pop("jobcount", None)


def _feed(job, detail, at):
    with patch.object(pr.time, "monotonic", return_value=at):
        pr._count_progress(job, detail)


class TestItemCounter:
    def test_the_percentage_follows_the_counter(self):
        job = _job()
        _feed(job, "[45/159] coreDoWhileClamp", 100.0)
        assert job.phase_pct == 28

    def test_the_time_left_is_the_rate_seen_so_far(self):
        job = _job(phase=2)
        _feed(job, "[10/110] a", 100.0)
        assert job.eta_seconds == 240, "one sighting gives no rate; the old guess stands"
        _feed(job, "[20/110] b", 200.0)            # 10 items in 100 s -> 10 s an item
        assert job.eta_seconds == 90 * 10 + 2 * 120  # this step, plus two phases to come

    def test_a_new_step_restarts_the_clock(self):
        job = _job()
        _feed(job, "[50/50] last", 100.0)
        _feed(job, "[5/20] next-step", 500.0)
        _feed(job, "[10/20] next-step", 510.0)     # 5 items in 10 s -> 2 s an item
        assert job.phase_pct == 50
        assert job.eta_seconds == 10 * 2 + 2 * 120

    @pytest.mark.parametrize("line", [
        "[2/4] === Derive Model ===",
        "[2/4] Derive Model — 12.30s",
        "[1/4] Parse — skipped (--from-phase 2)",
        "LLM cache: 0 entr(y/ies) loaded",
        "[7/5] impossible",
    ])
    def test_phase_lines_and_other_output_are_not_item_counts(self, line):
        job = _job()
        _feed(job, line, 100.0)
        assert job.phase_pct == 0
        assert job.eta_seconds == 240


class TestAStopBeforeTheParseLeadsTheError:
    """The web app shows a failed job's first line as its headline."""

    LINES = [
        "[13:00:01] INFO incremental:   WARNINGS",
        "[13:00:01] INFO incremental:     - Layer1 / G / Ghost: `Layer1/Gone` is not in the checkout",
        "[13:00:01] INFO incremental:   STOPPING BEFORE THE PARSE - fix these first:",
        "[13:00:01] INFO incremental:     - Layer1 / G / Ghost gets no source file: Phase 3 would stop",
        "[13:00:01] INFO incremental:     - Layer1 / G / Other gets no source file: Phase 3 would stop",
        "[13:00:01] INFO incremental: ================================================================",
        "stopped before the parse: ...",
    ]

    def test_the_engines_reasons_come_first(self):
        msg = pr._failure_message(2, self.LINES, "TAIL")
        assert msg.splitlines()[0] == ("Stopped before the parse: Layer1 / G / Ghost gets no source "
                                       "file: Phase 3 would stop")
        assert "- Layer1 / G / Other gets no source file" in msg and msg.endswith("TAIL")

    def test_any_other_failure_keeps_its_exit_code(self):
        assert pr._failure_message(1, ["[13:00:01] ERROR x: boom"], "TAIL") == "run.py exited with code 1.\nTAIL"
