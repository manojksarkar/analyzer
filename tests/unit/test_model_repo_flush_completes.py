"""A flush must not delete the artifacts it was not handed.

`flush()` calls `clear_version` and then `persist_model`, so every coupled artifact absent
from the flush is DELETED. It completes a partial write from what is already stored -- but
the guard deciding whether to load that named only four of the eight coupled artifacts:

    functions, globalVariables, dataDictionary, edges

Phase 2 rewrites exactly those four. So the load was skipped and `hashes`, `units`,
`components` and `summaries` were persisted as {}. For `hashes` that is not cosmetic:
`persist_functions` reads source_hash from it, so every function lands with a NULL hash and
change detection is dead for the NEXT run -- while the document from THIS run looks fine.

Seen on a real project: 4321 functions with no source_hash after a fresh generate.
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from core import model_repo


class _Repo(model_repo.DbRepository):
    """Real flush logic, with the database and the load stubbed out."""

    def __init__(self, pending, stored):
        import threading
        self._lock = threading.Lock()
        self._pending = dict(pending)
        self._stored = None
        self._loaded = False
        self._fake_stored = stored
        self.project_id, self.version_id = "p", "v"
        self.persisted = None

    def _load_stored(self):
        self._loaded = True
        return dict(self._fake_stored)


def _run_flush(monkeypatch, pending, stored):
    repo = _Repo(pending, stored)
    captured = {}

    class _Cx:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _Engine:
        def begin(self): return _Cx()

    monkeypatch.setattr("core.db.get_engine", lambda *a, **k: _Engine(), raising=False)

    import core.model_store as ms
    monkeypatch.setattr(ms, "clear_version", lambda *a, **k: None)
    monkeypatch.setattr(ms, "persist_model",
                        lambda cx, pid, vid, **kw: captured.update(kw))
    monkeypatch.setattr("core.logging_setup.get_logger",
                        lambda *a, **k: type("L", (), {"warning": lambda *_a, **_k: None})(),
                        raising=False)
    repo.flush()
    return repo, captured


ALL_FOUR = {"functions": {"f": {}}, "globalVariables": {}, "dataDictionary": {}, "edges": {}}
STORED = {"functions": {}, "globals": {}, "datadict": {}, "edges": {},
          "hashes": {"f": "h1"}, "units": {"u": {}}, "components": {"c": {}},
          "summaries": {"s": {}}}


class TestFlushCompletesFromStored:
    def test_hashes_survive_a_phase_that_rewrites_only_the_four(self, monkeypatch):
        # Phase 2's shape: all four keyed artifacts present, hashes absent.
        repo, got = _run_flush(monkeypatch, ALL_FOUR, STORED)
        assert repo._loaded, "the stored model must be loaded to complete the write"
        assert got["hashes"] == {"f": "h1"}, (
            "hashes were dropped -- every function would persist with a NULL source_hash")

    def test_units_components_summaries_survive_too(self, monkeypatch):
        _repo, got = _run_flush(monkeypatch, ALL_FOUR, STORED)
        assert got["units"] and got["components"] and got["summaries"]

    def test_a_flush_carrying_everything_skips_the_load(self, monkeypatch):
        full = dict(ALL_FOUR)
        full.update(hashes={"f": "h2"}, units={}, components={}, summaries={})
        repo, got = _run_flush(monkeypatch, full, STORED)
        assert not repo._loaded, "nothing is missing, so there is nothing to complete"
        assert got["hashes"] == {"f": "h2"}, "the flush's own value must win"

    def test_pending_beats_stored(self, monkeypatch):
        pending = dict(ALL_FOUR)
        pending["hashes"] = {"f": "fresh"}
        _repo, got = _run_flush(monkeypatch, pending, STORED)
        assert got["hashes"] == {"f": "fresh"}
