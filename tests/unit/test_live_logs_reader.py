"""The live-log reader (api/services/live_logs.py; docs/spec/LIVE_LOGS_SPEC.md REQ-LL-04 … -13).

Files are written the way the processes write them -- one JSON object per line, one file per
process -- into a temporary folder, and read back through the reader.
"""
import datetime as dt
import json
import os
import sys
from types import SimpleNamespace

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (PROJECT_ROOT, os.path.join(PROJECT_ROOT, "engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from api.services import live_logs as ll  # noqa: E402

pytestmark = pytest.mark.unit

TODAY = dt.date.today().isoformat()
LOCAL = dt.datetime.now().astimezone().tzinfo


def _ts(h, m, s, ms=0):
    return dt.datetime.combine(dt.date.today(), dt.time(h, m, s, ms * 1000),
                               tzinfo=LOCAL).isoformat(timespec="milliseconds")


def _write(root, name, *records, day=TODAY, raw=None):
    folder = root / day
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / name, "a", encoding="utf-8", newline="\n") as fh:
        for rec in records:
            fh.write(json.dumps({"level": "INFO", "source": "engine", "logger": "t", **rec}) + "\n")
        if raw is not None:
            fh.write(raw)


def _messages(records):
    return [r["message"] for r in records]


ALL = {"source": None, "project": None, "version": None, "job": None, "step": None}


class TestFollowingTheFiles:
    def test_records_of_several_processes_come_back_in_time_order(self, tmp_path):
        _write(tmp_path, "engine-1.jsonl", {"ts": _ts(10, 0, 1), "message": "a"},
               {"ts": _ts(10, 0, 3), "message": "c"})
        _write(tmp_path, "server-2.jsonl", {"ts": _ts(10, 0, 2), "message": "b", "source": "server"})
        reader = ll.LiveLogReader(str(tmp_path))
        assert reader.poll() == 3
        assert _messages(reader.tail(10, "INFO", ALL)[0]) == ["a", "b", "c"]

    def test_only_what_was_added_is_read_again(self, tmp_path):
        _write(tmp_path, "engine-1.jsonl", {"ts": _ts(10, 0, 1), "message": "a"})
        reader = ll.LiveLogReader(str(tmp_path))
        reader.poll()
        _write(tmp_path, "engine-1.jsonl", {"ts": _ts(10, 0, 2), "message": "b"})
        _write(tmp_path, "engine-9.jsonl", {"ts": _ts(10, 0, 3), "message": "new process"})
        assert reader.poll() == 2
        assert _messages(reader.tail(10, "INFO", ALL)[0]) == ["a", "b", "new process"]

    def test_a_line_still_being_written_waits_for_its_end(self, tmp_path):
        whole = json.dumps({"ts": _ts(10, 0, 1), "level": "INFO", "message": "half"})
        _write(tmp_path, "engine-1.jsonl", raw=whole[:20])
        reader = ll.LiveLogReader(str(tmp_path))
        assert reader.poll() == 0
        _write(tmp_path, "engine-1.jsonl", raw=whole[20:] + "\n")
        assert reader.poll() == 1 and _messages(reader.tail(5, "INFO", ALL)[0]) == ["half"]

    def test_a_broken_line_is_skipped(self, tmp_path):
        _write(tmp_path, "engine-1.jsonl", raw="{not json\n")
        _write(tmp_path, "engine-1.jsonl", {"ts": _ts(10, 0, 1), "message": "fine"})
        reader = ll.LiveLogReader(str(tmp_path))
        reader.poll()
        assert _messages(reader.tail(5, "INFO", ALL)[0]) == ["fine"]

    def test_start_up_reads_the_end_of_what_is_there_then_only_what_is_new(self, tmp_path):
        _write(tmp_path, "engine-1.jsonl", *[{"ts": _ts(9, 0, i), "message": str(i)}
                                              for i in range(5)])
        reader = ll.LiveLogReader(str(tmp_path))
        assert reader.backfill() == 5
        assert reader.poll() == 0                       # nothing read twice
        _write(tmp_path, "engine-1.jsonl", {"ts": _ts(9, 1, 0), "message": "later"})
        assert reader.poll() == 1

    def test_at_start_up_older_files_than_it_reads_start_at_their_end(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ll, "BACKFILL_FILES", 1)
        _write(tmp_path, "engine-1.jsonl", {"ts": _ts(8, 0, 0), "message": "old"})
        os.utime(tmp_path / TODAY / "engine-1.jsonl", (1, 1))
        _write(tmp_path, "engine-2.jsonl", {"ts": _ts(9, 0, 0), "message": "newest"})
        reader = ll.LiveLogReader(str(tmp_path))
        reader.backfill()
        reader.poll()
        assert _messages(reader.tail(10, "INFO", ALL)[0]) == ["newest"]

    def test_yesterday_s_files_are_read_too(self, tmp_path):
        yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
        _write(tmp_path, "engine-1.jsonl", {"ts": _ts(23, 59, 59), "message": "y"}, day=yesterday)
        reader = ll.LiveLogReader(str(tmp_path))
        reader.poll()
        assert _messages(reader.tail(5, "INFO", ALL)[0]) == ["y"]


class TestSecretsAreMasked:
    @pytest.mark.parametrize("raw,shown", [
        ("connecting to postgresql://u:secret@h:5432/db", "connecting to postgresql://u:***@h:5432/db"),
        ("Authorization: Bearer abc.def.ghi", "Authorization: ***"),
        ("sent bearer abc.def", "sent bearer ***"),
        ("api_key=XYZ123 next", "api_key=*** next"),
        ('{"password": "hunter2", "user": "u"}', '{"password": "***", "user": "u"}'),
        ("max_tokens=512 tokens: 10", "max_tokens=512 tokens: 10"),          # not secrets
    ])
    def test_patterns(self, raw, shown):
        assert ll.Masker()(raw) == shown

    def test_the_configured_values_wherever_they_appear(self):
        assert ll.Masker(["s3cr3t-key"])("header x-dep-ticket=s3cr3t-key sent") == \
            "header x-dep-ticket=*** sent"

    def test_a_record_leaves_masked(self, tmp_path):
        _write(tmp_path, "engine-1.jsonl", {"ts": _ts(10, 0, 0), "message": "key KEY-123456"})
        reader = ll.LiveLogReader(str(tmp_path), secrets=["KEY-123456"])
        reader.poll()
        assert _messages(reader.tail(1, "INFO", ALL)[0]) == ["key ***"]


def _job(jid, mode, start, end):
    day = dt.date.today()
    utc = dt.timezone.utc
    return SimpleNamespace(
        id=jid, mode=mode,
        started_at=dt.datetime.combine(day, start, tzinfo=LOCAL).astimezone(utc),
        completed_at=None if end is None else dt.datetime.combine(day, end, tzinfo=LOCAL).astimezone(utc))


class TestTheJobOfAnEngineLine:
    def test_the_job_running_that_version_at_that_time(self, tmp_path):
        jobs = {"vera072": [_job("jobre", "reexport", dt.time(12, 0), None),
                            _job("jobgen", "full", dt.time(10, 0), dt.time(11, 0))]}
        _write(tmp_path, "engine-1.jsonl",
               {"ts": _ts(10, 30, 0), "message": "gen", "version": "vera072"},
               {"ts": _ts(12, 5, 0), "message": "re", "version": "vera072"},
               {"ts": _ts(11, 30, 0), "message": "between", "version": "vera072"},
               {"ts": _ts(10, 30, 0), "message": "cli", "version": "p1.v2"})
        reader = ll.LiveLogReader(str(tmp_path), jobs_for_version=lambda v: jobs.get(v, []))
        reader.poll()
        got = {r["message"]: (r.get("job"), r.get("run")) for r in reader.tail(10, "INFO", ALL)[0]}
        assert got == {"gen": ("jobgen", "generate"), "re": ("jobre", "reexport"),
                       "between": (None, None), "cli": (None, None)}

    def test_a_line_with_no_project_takes_its_job_s(self, tmp_path):
        """The flowchart engine is told the version only."""
        job = _job("jobgen", "full", dt.time(10, 0), None)
        job.project_id = "p1"
        _write(tmp_path, "engine-1.jsonl", {"ts": _ts(10, 30, 0), "message": "f", "version": "v"})
        reader = ll.LiveLogReader(str(tmp_path), jobs_for_version=lambda v: [job])
        reader.poll()
        assert reader.tail(1, "INFO", ALL)[0][0]["project"] == "p1"

    def test_a_server_line_keeps_the_job_its_request_named(self, tmp_path):
        _write(tmp_path, "server-1.jsonl", {"ts": _ts(10, 30, 0), "message": "POST",
                                            "source": "server", "job": "jobx"})
        reader = ll.LiveLogReader(str(tmp_path), jobs_for_version=lambda v: [])
        reader.poll()
        assert reader.tail(1, "INFO", ALL)[0][0]["job"] == "jobx"


class TestReadingTheBuffer:
    @pytest.fixture
    def reader(self, tmp_path):
        _write(tmp_path, "engine-1.jsonl",
               {"ts": _ts(10, 0, 0), "message": "debug", "level": "DEBUG"},
               {"ts": _ts(10, 0, 1), "message": "parse", "step": "Parse", "job": "j1"},
               {"ts": _ts(10, 0, 2), "message": "export", "step": "Export SWE.4", "job": "j2"},
               {"ts": _ts(10, 0, 3), "message": "warn", "level": "WARNING"})
        _write(tmp_path, "server-2.jsonl", {"ts": _ts(10, 0, 4), "message": "POST", "source": "server"})
        r = ll.LiveLogReader(str(tmp_path))
        r.poll()
        return r

    def test_the_level_is_the_lowest_shown(self, reader):
        assert _messages(reader.tail(10, "WARNING", ALL)[0]) == ["warn"]
        assert "debug" in _messages(reader.tail(10, "DEBUG", ALL)[0])
        assert "debug" not in _messages(reader.tail(10, "INFO", ALL)[0])

    @pytest.mark.parametrize("key,value,expected", [
        ("source", "server", ["POST"]), ("step", "Export SWE.4", ["export"]), ("job", "j1", ["parse"]),
    ])
    def test_filters(self, reader, key, value, expected):
        assert _messages(reader.tail(10, "INFO", {**ALL, key: value})[0]) == expected

    def test_the_last_n_oldest_first(self, reader):
        records, cursor = reader.tail(2, "INFO", ALL)
        assert _messages(records) == ["warn", "POST"] and cursor == reader.last_seq() == 5

    def test_after_a_cursor(self, reader):
        records, cursor, gap = reader.after(3, "INFO", ALL)
        assert _messages(records) == ["warn", "POST"] and cursor == 5 and not gap

    def test_records_the_buffer_no_longer_holds_are_reported(self, tmp_path):
        _write(tmp_path, "engine-1.jsonl", *[{"ts": _ts(10, 0, i), "message": str(i)}
                                              for i in range(6)])
        reader = ll.LiveLogReader(str(tmp_path), buffer=3)
        reader.poll()
        records, _, gap = reader.after(1, "INFO", ALL)
        assert gap and _messages(records) == ["3", "4", "5"]


class TestRetention:
    def test_folders_older_than_the_days_kept_go(self, tmp_path):
        today = dt.date(2026, 10, 6)
        for day in ("2026-09-05", "2026-09-06", "2026-10-06", "not-a-day"):
            (tmp_path / day).mkdir()
        reader = ll.LiveLogReader(str(tmp_path))
        assert reader.cleanup(30, today=today) == 1
        assert sorted(os.listdir(tmp_path)) == ["2026-09-06", "2026-10-06", "not-a-day"]
