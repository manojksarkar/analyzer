"""A run must report how many LLM calls it made and how many produced nothing.

`tokens` records what was SPENT; it cannot say whether the spending bought anything. That gap
hid a real failure: a run took 2062 seconds and produced mechanical flowchart labels while the
gateway answered every request correctly — the replies were being destroyed after arrival by
`strip_think_section`. Token usage looked healthy throughout, and no report line said "1 call in
3 came back empty", which is the number that points straight at it.

The counting has to survive PROCESS boundaries: the four phases and the flowchart engine are
separate subprocesses, so an in-memory counter only ever sees a fraction of a run.
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "engine")]

from llm_core import callstats            # noqa: E402
from incremental.report import _llm_lines  # noqa: E402


@pytest.fixture(autouse=True)
def _clean():
    callstats.reset()
    yield
    callstats.reset()


class TestCounting:
    def test_outcomes_are_tallied_by_kind(self):
        callstats.record("description", callstats.OK, 3)
        callstats.record("description", callstats.EMPTY)
        callstats.record("flowchart-label", callstats.ERROR, 2)
        t = callstats.totals()
        assert t == {"calls": 6, "ok": 3, "empty": 1, "error": 2}

    def test_a_call_is_counted_once_not_once_per_retry(self):
        """Retries are visible in the log. Counting them here would make a healthy run with one
        flaky retry look broken, which is the opposite of what this is for.

        Three sites per public method — success, exhausted-empty, exhausted-error — across both
        `generate()` and `call()`. Both must be covered: an early version instrumented only
        `generate()`, but the two methods share an `if cleaned:` block, so the edit silently
        landed inside `call()` as well, where `kind` was not in scope and would have raised
        NameError on the first successful multi-turn call.
        """
        import inspect
        src = inspect.getsource(__import__("llm_core.client", fromlist=["x"]))
        assert src.count("callstats.record(") == 6, \
            "expected three record sites in each of generate() and call()"
        assert src.count('kind: str = "other"') == 2, \
            "both public methods need their own kind parameter"

    def test_reset_clears(self):
        callstats.record("description", callstats.OK)
        callstats.reset()
        assert callstats.totals()["calls"] == 0


class TestTheReportSection:
    def test_a_failing_run_states_the_failure_rate(self):
        lines = "\n".join(_llm_lines({"description|ok": 40, "description|empty": 12,
                                      "flowchart-label|ok": 55, "flowchart-label|error": 2}))
        assert "Total" in lines and "109" in lines
        assert "Failed" in lines
        assert "produced NOTHING" in lines
        assert "fallback text or" in lines, "it must say what a failure MEANS for the document"

    def test_a_healthy_run_does_not_cry_wolf(self):
        lines = "\n".join(_llm_lines({"description|ok": 40, "flowchart-label|ok": 55}))
        assert "answered 95 (100%)" in lines
        assert "Failed" not in lines
        assert "produced NOTHING" not in lines

    def test_the_breakdown_names_each_kind(self):
        """'Where are the failures' is the actionable question — labels failing is a different
        problem from descriptions failing."""
        lines = "\n".join(_llm_lines({"description|ok": 1, "flowchart-label|empty": 9}))
        assert "description" in lines and "flowchart-label" in lines

    def test_no_calls_produces_no_section(self):
        """A --no-llm run should not grow an empty LLM block."""
        assert _llm_lines({}) == []
        assert _llm_lines({"description|ok": 0}) == []


class TestCrossProcess:
    def test_the_schema_keeps_the_phase_breakdown(self):
        """Summing on read is fine; losing WHICH process failed is not."""
        from api.db.postgres import schema as s
        cols = set(s.llm_call_stats.c.keys())
        assert {"version_id", "phase", "kind", "outcome", "n"} <= cols

    def test_flush_without_a_version_is_a_no_op(self):
        """A standalone phase has no version to attribute counts to; it must not raise."""
        callstats.record("description", callstats.OK)
        callstats.flush()          # no run context installed
