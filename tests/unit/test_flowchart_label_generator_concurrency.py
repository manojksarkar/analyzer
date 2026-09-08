"""Unit test for CC-2 (docs/production-redesign/07-llm-concurrency-scaling.md §3.3):

LabelGenerator._fallback_ids must be thread-local. Before CC-2 it was a plain
instance attribute reset at the start of every label_cfg() call — safe only
because flowchart_engine.py processed one function at a time. Now that run()
labels functions concurrently through one shared LabelGenerator instance,
two threads resetting/mutating/reading the same set would race (one thread's
reset wiping another's in-flight fallback ids, or a fallback count attributed
to the wrong function). This test proves each thread sees its own set.
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

from llm.generator import LabelGenerator  # noqa: E402


def test_fallback_ids_is_thread_local():
    gen = LabelGenerator(client=None, pkb=None)
    results = {}
    barrier = threading.Barrier(2)

    def worker(name, node_id):
        gen._fallback_ids = set()  # mirrors label_cfg()'s per-function reset
        barrier.wait()             # make sure both threads are mid-flight together
        gen._fallback_ids.add(node_id)
        time.sleep(0.03)
        results[name] = set(gen._fallback_ids)

    t1 = threading.Thread(target=worker, args=("a", "N1"))
    t2 = threading.Thread(target=worker, args=("b", "N2"))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert results["a"] == {"N1"}
    assert results["b"] == {"N2"}


def test_fallback_ids_defaults_to_empty_set_per_thread():
    gen = LabelGenerator(client=None, pkb=None)
    assert gen._fallback_ids == set()

    seen = {}

    def worker():
        seen["ids"] = gen._fallback_ids

    t = threading.Thread(target=worker)
    t.start()
    t.join()

    assert seen["ids"] == set()
