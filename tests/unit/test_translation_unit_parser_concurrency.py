"""Unit test for CC-2 (docs/production-redesign/07-llm-concurrency-scaling.md §3.3):

TranslationUnitParser.get_tu_full()/get_tu() must serialize libclang parses.
flowchart_engine.py's run() now labels functions concurrently, so multiple
threads can call into the same TranslationUnitParser instance at once —
libclang's C API gives no documented guarantee that concurrent
clang_parseTranslationUnit calls against one shared CXIndex are safe, and a
racy cache-dict check-then-set would let two threads both parse the same file.
This test proves: (1) parses never overlap, and (2) the cache dedups repeat
requests for the same path to a single parse call.
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

from ast_engine.parser import TranslationUnitParser  # noqa: E402


class _FakeDiag:
    severity = 0


class _FakeTU:
    diagnostics = []


def _make_parser(monkeypatch):
    parser = TranslationUnitParser(std="c++14", extra_clang_args=[])

    lock = threading.Lock()
    state = {"current": 0, "high_water": 0, "calls": 0}

    def fake_parse(path, args=None, options=None):
        with lock:
            state["current"] += 1
            state["high_water"] = max(state["high_water"], state["current"])
            state["calls"] += 1
        time.sleep(0.03)
        with lock:
            state["current"] -= 1
        return _FakeTU()

    monkeypatch.setattr(parser._index, "parse", fake_parse)
    return parser, state


def test_parses_never_overlap(monkeypatch):
    parser, state = _make_parser(monkeypatch)

    threads = [
        threading.Thread(target=parser.get_tu_full, args=(f"file{i}.cpp",))
        for i in range(6)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert state["high_water"] == 1
    assert state["calls"] == 6


def test_same_path_parsed_only_once(monkeypatch):
    parser, state = _make_parser(monkeypatch)

    threads = [
        threading.Thread(target=parser.get_tu_full, args=("same_file.cpp",))
        for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert state["calls"] == 1
