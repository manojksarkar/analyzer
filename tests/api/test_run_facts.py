"""GET /projects/{pid}/versions/{vid}/run-facts (api/services/run_facts.py): what a run has found so
far, for the Overview while it runs -- the LLM's trouble counted from the live log, per version."""
import datetime as dt
import json
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (PROJECT_ROOT, os.path.join(PROJECT_ROOT, "engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from api.services import live_logs as ll  # noqa: E402
from api.services import run_facts as rf  # noqa: E402

TODAY = dt.date.today().isoformat()


def _ts(i):
    start = dt.datetime.combine(dt.date.today(), dt.time(8, 0)).astimezone()
    return (start + dt.timedelta(seconds=i)).isoformat(timespec="milliseconds")


@pytest.fixture
def reader(tmp_path, monkeypatch):
    r = ll.LiveLogReader(str(tmp_path))
    monkeypatch.setattr(ll, "READER", r)
    folder = tmp_path / TODAY
    folder.mkdir(parents=True)
    lines = [
        {"logger": "llm_client", "level": "WARNING", "version": "ver1",
         "message": "LLM (openai/m) HTTP 503: An invalid response was received from the upstream server (attempt 1/2)"},
        {"logger": "llm_client", "level": "WARNING", "version": "ver1",
         "message": "LLM (openai/m) HTTP 503: An invalid response was received from the upstream server (attempt 2/2)"},
        {"logger": "llm_client", "level": "ERROR", "version": "ver1",
         "message": "LLM (openai/m) failed after 2 attempt(s): 503 Server Error\nTraceback ..."},
        {"logger": "parser", "level": "WARNING", "version": "ver1", "message": "Hint: missing include"},
        {"logger": "llm_client", "level": "WARNING", "version": "ver2", "message": "another version's (attempt 1/2)"},
        {"logger": "progress", "level": "INFO", "version": "ver1", "message": "LLM-description: 12/38"},
    ]
    with open(folder / "engine-1.jsonl", "w", encoding="utf-8", newline="\n") as fh:
        for i, rec in enumerate(lines):
            fh.write(json.dumps({"ts": _ts(i), "source": "engine", **rec}) + "\n")
    r.poll()
    return r


def test_the_llm_trouble_of_this_version(client, auth_header, reader):
    body = client.get("/api/v1/projects/p1/versions/ver1/run-facts", headers=auth_header).json()
    assert body["llm"]["retries"] == 2, "each failed attempt"
    assert body["llm"]["failed_calls"] == 1, "a call that got nothing in the end"
    assert body["llm"]["last_failure"]["message"] == "LLM (openai/m) failed after 2 attempt(s): 503 Server Error"
    assert body["parse"]["warnings"] == 1
    assert body["model"] is None, "the in-memory database keeps no model"


def test_nothing_to_say_is_zeros_not_an_error(client, auth_header, monkeypatch):
    def no_reader():
        raise RuntimeError("no live log in this process")
    monkeypatch.setattr(ll, "get_reader", no_reader)
    body = client.get("/api/v1/projects/p1/versions/ver1/run-facts", headers=auth_header).json()
    assert body["llm"] == {"failed_calls": 0, "retries": 0, "last_failure": None}
    assert body["parse"] == {"warnings": 0}


def test_members_only_and_a_version_of_the_project(client, auth_header, reader):
    assert client.get("/api/v1/projects/p1/versions/ver1/run-facts").status_code == 401
    assert client.get("/api/v1/projects/p1/versions/nope/run-facts", headers=auth_header).status_code == 404


def test_model_counts_need_a_database():
    assert rf.model_counts(object(), "ver1") is None
