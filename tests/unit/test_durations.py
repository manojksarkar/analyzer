"""Log lines say how long something took in minutes, hours and days, not 16384.27s
(core/durations.py)."""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "engine"))

from core.durations import human  # noqa: E402


@pytest.mark.parametrize("seconds, shown", [
    (0, "0.00s"), (0.034, "0.03s"), (2.434, "2.43s"), (21.71, "21.7s"),
    (59.96, "1m 00s"),                 # rounds into the next unit, never "60.0s"
    (252, "4m 12s"), (3599.6, "1h 00m 00s"), (4567.8, "1h 16m 08s"),
    (86399, "23h 59m 59s"), (90061, "1d 01h 01m"), (432000, "5d 00h 00m"),
    (-3, "0.00s"), ("n/a", "n/a"), (None, "None"),
])
def test_a_duration_reads_as_a_person_says_it(seconds, shown):
    assert human(seconds) == shown


def test_the_llm_report_shows_hours_in_its_time_columns():
    from llm_core import tokens
    rep = {"stages": [{"stage": "enrich.function_description.rich", "calls": 2400, "empty": 0,
                       "error": 3, "avgSeconds": 6.4, "maxSeconds": 288.0, "httpSeconds": 15360.0,
                       "throttleSeconds": 7200.0, "tokensPerSecond": 31.2}],
           "totals": {"calls": 2400, "empty": 0, "error": 3, "avgSeconds": 6.4, "maxSeconds": 288.0,
                      "httpSeconds": 15360.0, "throttleSeconds": 7200.0}}
    text = tokens.format_merged(rep)
    assert "4h 16m 00s" in text and "2h 00m 00s" in text and "4m 48s" in text
    head, _rule, row = text.splitlines()[1:4]
    assert row.index("4h 16m 00s") + len("4h 16m 00s") == head.index("http") + len("http"), \
        "the column stays right-aligned under its heading"


def test_a_stage_says_done_in_minutes(caplog, monkeypatch):
    import logging
    from core import progress as P
    now = [100.0]
    monkeypatch.setattr(P.time, "perf_counter", lambda: now[0])
    pr = P.ProgressReporter("demo", total=1, logger=logging.getLogger("demo"))
    with caplog.at_level(logging.INFO, logger="demo"):
        pr.start()
        now[0] += 252.4
        pr.done()
    assert any(r.getMessage() == "done in 4m 12s" for r in caplog.records)
