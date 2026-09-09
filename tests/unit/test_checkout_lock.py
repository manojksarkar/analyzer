"""The per-commit checkout directory is shared, so preparing it must be serialized.

The checkout dir is keyed by COMMIT, so two jobs generating the same commit share it. Without
a lock they race two ways: both find no `.git` and clone into the same directory on top of
each other, or both run `git checkout` and one dies on `index.lock`. Neither corrupts a
version's data, but both fail a job for no reason — and that becomes likely the moment
JOB_MAX_CONCURRENCY is raised above 1, which is the whole point of the per-version work.
"""
import os
import sys
import threading
import time

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "engine"))

from incremental.clone import _dir_lock, _already_at         # noqa: E402
from incremental.git_ops import GitError                     # noqa: E402


class TestDirLock:
    def test_only_one_holder_at_a_time(self, tmp_path):
        target = str(tmp_path / "abc123")
        order = []

        def worker(tag):
            with _dir_lock(target):
                order.append(f"{tag}-in")
                time.sleep(0.15)
                order.append(f"{tag}-out")

        a = threading.Thread(target=worker, args=("a",))
        b = threading.Thread(target=worker, args=("b",))
        a.start(); time.sleep(0.02); b.start()
        a.join(); b.join()

        # Never interleaved: whoever entered first also left before the other entered.
        assert order in (["a-in", "a-out", "b-in", "b-out"],
                         ["b-in", "b-out", "a-in", "a-out"]), order

    def test_lock_is_released_even_on_error(self, tmp_path):
        target = str(tmp_path / "x")
        with pytest.raises(ValueError):
            with _dir_lock(target):
                raise ValueError("boom")
        with _dir_lock(target):                     # must be acquirable again
            pass
        assert not os.path.isdir(target + ".lock")

    def test_a_stale_lock_is_reclaimed(self, tmp_path, monkeypatch):
        """A killed job leaves its lock behind; it must not wedge the project forever."""
        import incremental.clone as clone
        target = str(tmp_path / "y")
        os.makedirs(target + ".lock")
        monkeypatch.setattr(clone, "_LOCK_STALE_S", -1)     # treat any lock as abandoned
        with clone._dir_lock(target):
            pass

    def test_times_out_rather_than_hanging(self, tmp_path, monkeypatch):
        import incremental.clone as clone
        target = str(tmp_path / "z")
        os.makedirs(target + ".lock")
        monkeypatch.setattr(clone, "_LOCK_TIMEOUT_S", 0.3)
        monkeypatch.setattr(clone, "_LOCK_STALE_S", 10_000)  # not stale
        with pytest.raises(GitError, match="timed out"):
            with clone._dir_lock(target):
                pass


class TestAlreadyAt:
    def test_false_without_a_checkout(self, tmp_path):
        assert _already_at(str(tmp_path / "nope"), "abc123") is False

    def test_false_without_a_commit(self, tmp_path):
        assert _already_at(str(tmp_path), "") is False
