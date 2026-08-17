"""`_try_narrowed_parse` must be CALLED by a test, not just read.

Two bugs lived here because nothing invoked it: `--narrowed-parse` is opt-in, the API never
sets it, and neither gate exercises it.

  * `_stored` was referenced without ever being assigned — a NameError on EVERY call, in file
    mode too. Shipped in C2, described in the commit as applied; only half the edit landed.
  * the merge goes through model_dir FILES, so in database mode it would read empty dicts and
    write an EMPTY skeleton — a wrong model, silently.

These call the real function with a fabricated baseline, so the first line of it executing is
covered rather than inspected.
"""
import json
import os
import sys

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "engine"))

from incremental import engine as eng          # noqa: E402


@pytest.fixture(autouse=True)
def _restore_store_kind():
    before = eng._MODEL_STORE
    yield
    eng._MODEL_STORE = before


def _baseline(tmp_path, *, with_snapshot=True):
    """A baseline parse dir, optionally holding the two artifacts the gate looks for."""
    d = tmp_path / "base" / "parse"
    d.mkdir(parents=True)
    if with_snapshot:
        (d / "tu_includes.json").write_text(json.dumps({"App/Main.cpp": []}), encoding="utf-8")
        (d / "entity_files.json").write_text(json.dumps({}), encoding="utf-8")
    return str(d)


def _call(tmp_path, base_parse_dir, **kw):
    model_dir = tmp_path / "model"
    model_dir.mkdir(exist_ok=True)
    return eng._try_narrowed_parse(
        str(tmp_path / "cfg.json"), {"type": "project"}, True, None,
        str(tmp_path / "repo"), ROOT, str(model_dir),
        target="b" * 40, base_commit="a" * 40, base_parse_dir=base_parse_dir, **kw)


class TestItRunsAtAll:
    def test_no_baseline_snapshot_falls_back_without_raising(self, tmp_path):
        """The NameError case: this used to blow up before reaching any decision."""
        eng._MODEL_STORE = "files"
        assert _call(tmp_path, _baseline(tmp_path, with_snapshot=False)) is False

    def test_with_a_snapshot_it_gets_past_the_gate(self, tmp_path):
        """Getting as far as the git diff is the assertion.

        With a baseline snapshot present the availability gate passes and the next step is
        `git diff`, which fails here because tmp_path/repo is not a repository. Reaching a
        GitError proves the gate EXECUTED — the NameError used to happen before this point. A
        real run has a real repo and continues normally.
        """
        from incremental.git_ops import GitError
        eng._MODEL_STORE = "files"
        with pytest.raises(GitError):
            _call(tmp_path, _baseline(tmp_path))


class TestDatabaseModeIsRefused:
    def test_db_mode_returns_false_before_touching_files(self, tmp_path, caplog):
        """It must refuse rather than merge empty dicts into an empty skeleton."""
        import logging
        eng._MODEL_STORE = "db"
        with caplog.at_level(logging.INFO):
            assert _call(tmp_path, _baseline(tmp_path)) is False
        assert any("model-store db" in r.message for r in caplog.records), \
            "refusing in database mode must say so, not fail silently"

    def test_db_mode_does_not_write_a_skeleton(self, tmp_path):
        """The dangerous outcome: an EMPTY merged model written over the real one."""
        eng._MODEL_STORE = "db"
        _call(tmp_path, _baseline(tmp_path))
        written = list((tmp_path / "model").glob("*.json"))
        assert not written, f"database mode must write no parse artifacts, got {written}"


class TestStoreFirstSnapshot:
    def test_a_stored_snapshot_satisfies_the_gate_with_no_files(self, tmp_path):
        """C2's point: on a machine that did not build the baseline there are no files, so the
        gate has to accept the STORED snapshot."""
        eng._MODEL_STORE = "files"

        class _Store:
            def read_parse_snapshot(self, _vid):
                return {"tu_includes.json": {"App/Main.cpp": []}, "entity_files.json": {}}

        # base_parse_dir deliberately EMPTY — only the store has the snapshot. Reaching the
        # git diff (GitError, no repo here) proves the gate accepted the STORED snapshot; had it
        # only looked at files it would have returned False before getting there.
        from incremental.git_ops import GitError
        empty = tmp_path / "nobase" / "parse"
        empty.mkdir(parents=True)
        with pytest.raises(GitError):
            _call(tmp_path, str(empty), store=_Store(), base_vid="ver1")
