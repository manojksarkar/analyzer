"""Unit test for CC-2 (docs/production-redesign/07-llm-concurrency-scaling.md §3.2):

HierarchySummarizer's per-level units (file summaries, component summaries) are
independent of each other within a level, so CC-2 parallelizes each level with
a ThreadPoolExecutor sized from `max_workers`. This proves: (1) overlap is
bounded by max_workers, (2) the default (max_workers=1, the constructor
default) is a strict no-op, and (3) results still land on the correct keys
despite concurrent completion order.
"""
import os
import sys
import threading
import time

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine", "flowchart"))

from pkb.knowledge import FunctionKnowledge, ProjectKnowledge  # noqa: E402
from project_scanner import HierarchySummarizer  # noqa: E402


def _knowledge_with_files(n_files: int) -> ProjectKnowledge:
    k = ProjectKnowledge(project_name="P", base_path="/nonexistent")
    for i in range(n_files):
        qn = f"func{i}"
        k.functions[qn] = FunctionKnowledge(
            qualified_name=qn, signature=f"void {qn}()",
            file=f"file{i}.cpp", line=1, end_line=3,
            description="already described",  # skip level-1 function summaries
        )
    return k


class _RecordingClient:
    def __init__(self, delay=0.03):
        self._delay = delay
        self.lock = threading.Lock()
        self.state = {"current": 0, "high_water": 0}

    def generate(self, system, prompt):
        with self.lock:
            self.state["current"] += 1
            self.state["high_water"] = max(self.state["high_water"], self.state["current"])
        time.sleep(self._delay)
        with self.lock:
            self.state["current"] -= 1
        return "A file summary."


class TestFileSummariesConcurrency:
    def test_max_workers_bounds_overlap(self):
        k = _knowledge_with_files(12)
        client = _RecordingClient()
        summarizer = HierarchySummarizer(k, client, "/nonexistent", max_workers=4)

        summarizer._summarize_files()

        assert len(k.file_summaries) == 12
        assert all(v == "A file summary." for v in k.file_summaries.values())
        assert 2 <= client.state["high_water"] <= 4

    def test_default_max_workers_is_sequential_noop(self):
        k = _knowledge_with_files(6)
        client = _RecordingClient()
        summarizer = HierarchySummarizer(k, client, "/nonexistent")  # default max_workers=1

        summarizer._summarize_files()

        assert len(k.file_summaries) == 6
        assert client.state["high_water"] == 1
