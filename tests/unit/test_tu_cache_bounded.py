"""The flowchart engine's TU cache must stay bounded (doc 09, M1).

`TranslationUnitParser` cached one libclang TranslationUnit per source file it touched and
NEVER evicted — and `get_tu_full` deliberately parses WITH function bodies, the expensive
kind. So peak memory grew with FILE COUNT rather than with change size: even a one-line
incremental on a large codebase paid for every file it visited. It is per job, so it
multiplies by concurrency, and it is the first thing that exhausts a container on a big repo.

libclang is not needed here: the cache is exercised through a stubbed parse, so these run
anywhere and stay fast.
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "engine"))
sys.path.insert(0, os.path.join(ROOT, "engine", "flowchart"))

clang = pytest.importorskip("clang.cindex", reason="needs the clang python bindings")

from ast_engine.parser import TranslationUnitParser      # noqa: E402


class _FakeTU:
    def __init__(self, path):
        self.path = path
        self.diagnostics = []


class _Parser(TranslationUnitParser):
    """Real cache logic, stubbed parsing — no libclang index, no files on disk."""

    def __init__(self, size):
        self._std = "c++14"
        self._extra_args = []
        self._index = None
        from collections import OrderedDict
        self._tu_cache = OrderedDict()
        self._tu_cache_size = size
        self.parses = []

    def _build_parse(self, path):
        self.parses.append(path)
        return _FakeTU(path)

    def get_tu(self, abs_path):
        return self._cached(abs_path, lambda: self._build_parse(abs_path))


def test_cache_never_exceeds_its_bound():
    p = _Parser(4)
    for i in range(50):
        p.get_tu(f"/src/file{i}.cpp")
    assert len(p._tu_cache) == 4, "the cache must not grow with the number of files parsed"
    assert len(p.parses) == 50


def test_repeated_access_to_one_file_parses_once():
    """The access pattern that matters: functions are processed grouped by source file."""
    p = _Parser(4)
    for _ in range(20):
        p.get_tu("/src/Main.cpp")
    assert p.parses == ["/src/Main.cpp"], "a hot file must be parsed exactly once"


def test_least_recently_used_is_evicted_first():
    p = _Parser(2)
    p.get_tu("/a.cpp")
    p.get_tu("/b.cpp")
    p.get_tu("/a.cpp")            # touch A -> B is now the least recently used
    p.get_tu("/c.cpp")            # evicts B
    assert set(p._tu_cache) == {"/a.cpp", "/c.cpp"}


def test_file_grouped_access_keeps_a_full_hit_rate():
    """Real shape: all of one file's functions, then the next file. Nothing re-parses."""
    p = _Parser(4)
    for f in ("/one.cpp", "/two.cpp", "/three.cpp"):
        for _ in range(10):       # ten functions in that file
            p.get_tu(f)
    assert p.parses == ["/one.cpp", "/two.cpp", "/three.cpp"]


def test_bound_is_at_least_one():
    """A 0 or negative bound would evict the entry just inserted and re-parse every call."""
    p = TranslationUnitParser.__new__(TranslationUnitParser)
    TranslationUnitParser.__init__(p, "c++14", [], tu_cache_size=0)
    assert p._tu_cache_size >= 1


# ---------------------------------------------------------------------------
# Concurrency hardening — atomic writes must not share a temp path
# ---------------------------------------------------------------------------

class TestAtomicWritesArePidUnique:
    """Two processes writing the SAME path must not share one .tmp file.

    The tmp+replace pattern is only atomic if the tmp is private. With a fixed
    `path + ".tmp"`, a second process truncates the same file while the first is mid-write,
    so os.replace can publish a HALF-WRITTEN file. Harmless while jobs ran one at a time
    (JOB_MAX_CONCURRENCY=1); a real hazard as soon as that is raised — which is the point of
    the per-version directory work.
    """

    def _src(self, rel):
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        with open(os.path.join(root, rel), encoding="utf-8") as fh:
            return fh.read()

    @pytest.mark.parametrize("rel", [
        "engine/incremental/stores.py",     # manifests, config, hashes, edges, reuse index
        "engine/llm_core/cache.py",         # the LLM entity cache
        "engine/utils.py",                  # the mermaid + DOT render caches
    ])
    def test_no_shared_temp_path(self, rel):
        src = self._src(rel)
        assert '+ ".tmp"' not in src, (
            f"{rel}: a fixed .tmp path is shared between concurrent processes")
        assert "getpid()" in src, f"{rel}: the temp path must be process-private"

    def test_write_json_still_writes(self, tmp_path):
        """Hardening must not break the write itself."""
        import json as _json
        from incremental.stores import _write_json, _read_json
        p = str(tmp_path / "sub" / "x.json")
        _write_json(p, {"a": 1})
        assert _read_json(p, None) == {"a": 1}
        assert not [f for f in os.listdir(os.path.dirname(p)) if f.endswith(".tmp")], \
            "the temp file must not be left behind"
