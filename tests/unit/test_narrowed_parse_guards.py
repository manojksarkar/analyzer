"""`_try_narrowed_parse` must be CALLED by a test, not just read.

Two bugs lived here because nothing invoked it: `--narrowed-parse` is opt-in, the API never
sets it, and neither gate exercises it.

  * `_stored` was referenced without ever being assigned — a NameError on EVERY call, in file
    mode too. Shipped in C2, described in the commit as applied; only half the edit landed.
  * the merge went through model_dir FILES, so in database mode it read empty dicts and would
    have written an EMPTY skeleton. That was guarded by refusing outright; the guard is gone
    now that the merge publishes through the model repository (doc 10, narrowed parse in db
    mode) and `tools/verify_narrowed_parse.py` proves narrowed == full end to end.

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
        # Non-empty: the gate requires a baseline that could actually support a merge. An
        # entity->file map with nothing in it cannot place a single merged entity.
        (d / "entity_files.json").write_text(
            json.dumps({"App|Main|main|int": "App/Main.cpp"}), encoding="utf-8")
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


class TestDatabaseModeIsSupported:
    """Database mode used to be refused outright, because the merge published through files.

    It publishes through the model repository now, so the refusal is gone. What must stay true
    is the reason it existed: database mode must never write parse artifacts as FILES, because
    Phase 2 would not read them and the model it derived would hold only the changed files.
    """

    def test_it_gets_past_the_gate_and_writes_no_parse_files(self, tmp_path):
        """Reaching the git diff is the proof it is no longer refused — it used to return False
        on the first line. GitError here just means tmp_path/repo is not a repository."""
        from incremental.git_ops import GitError
        eng._MODEL_STORE = "db"
        with pytest.raises(GitError):
            _call(tmp_path, _baseline(tmp_path))
        written = [p.name for p in (tmp_path / "model").glob("*.json")]
        assert not written, f"database mode must write no parse artifacts, got {written}"

    def test_the_refusal_is_gone(self):
        """A guard that silently disables the feature is worse than none — it cost the whole
        speed-up with no error to explain why."""
        import inspect
        src = inspect.getsource(eng._try_narrowed_parse)
        assert "not supported with --model-store db" not in src

    def test_the_publisher_targets_the_repository_in_db_mode(self):
        import inspect
        src = inspect.getsource(eng._write_parse_artifacts)
        assert 'if _MODEL_STORE == "db":' in src
        assert "DbRepository" in src


class TestStoreFirstSnapshot:
    def test_a_stored_snapshot_satisfies_the_gate_with_no_files(self, tmp_path):
        """C2's point: on a machine that did not build the baseline there are no files, so the
        gate has to accept the STORED snapshot."""
        eng._MODEL_STORE = "files"

        class _Store:
            def read_parse_snapshot(self, _vid):
                return {"tu_includes.json": {"App/Main.cpp": []},
                        "entity_files.json": {"App|Main|main|int": "App/Main.cpp"}}

        # base_parse_dir deliberately EMPTY — only the store has the snapshot. Reaching the
        # git diff (GitError, no repo here) proves the gate accepted the STORED snapshot; had it
        # only looked at files it would have returned False before getting there.
        from incremental.git_ops import GitError
        empty = tmp_path / "nobase" / "parse"
        empty.mkdir(parents=True)
        with pytest.raises(GitError):
            _call(tmp_path, str(empty), store=_Store(), base_vid="ver1")


class TestTheApiActuallyEnablesIt:
    """Narrowed parse being ON in the engine is worth nothing if the API turns it off.

    The flag inverted when it became the default — a job now opts OUT — and every layer still
    defaulted the field to False: the request body, the Job dataclass and the column. So each UI
    job would have sent `--no-narrowed-parse` and disabled the feature on exactly the path it
    was built for, while the engine, the CLI and every gate showed it working.

    Nothing would have failed. Runs would simply have stayed slow, which is how the two bugs
    underneath it survived this long in the first place.
    """

    def _src(self, rel):
        with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
            return fh.read()

    def test_the_job_model_defaults_to_on(self):
        assert "narrowed_parse: bool = True" in self._src(os.path.join("api", "models", "domain.py"))

    def test_the_request_body_defaults_to_on(self):
        assert "narrowed_parse: bool = True" in self._src(os.path.join("api", "routes", "jobs.py"))

    def test_the_column_defaults_to_on(self):
        src = self._src(os.path.join("api", "db", "postgres", "schema.py"))
        assert 'Column("narrowed_parse", Boolean, default=True)' in src

    def test_the_runner_sends_the_flag_only_to_disable(self):
        src = self._src(os.path.join("api", "services", "pipeline_runner.py"))
        assert '"--no-narrowed-parse"' in src
        assert '"--narrowed-parse"' not in src, \
            "the engine is on by default; sending the positive flag means the default is unused"
        assert 'getattr(job, "narrowed_parse", True) is False' in src

    def test_a_default_job_does_not_disable_it(self):
        """The end of the chain: a job created with no opinion must leave it ON."""
        sys.path.insert(0, ROOT)
        from api.models.domain import AnalysisJob
        import inspect
        default = inspect.signature(AnalysisJob).parameters["narrowed_parse"].default
        assert default is True, (
            f"a default AnalysisJob disables narrowed parse (got {default!r})")


class TestFuncKeysSurviveTheMerge:
    """A narrowed parse must republish the baseline's func-key map.

    `func_keys` maps a mangled function key to its fid, and it is what lets a call from a
    RE-PARSED file into a file this run did NOT re-parse still resolve to an edge. It was absent
    from both `_PARSE_ARTIFACTS` and `merge_model`, so a narrowed parse produced a version whose
    stored snapshot had no func_keys at all — reported by check_db.py as "parse snapshot missing
    func_keys.json" on a real incremental version.

    The damage needs TWO narrowed parses in a row: the first works from a full baseline, the
    second gets no map and silently drops every cross-TU call edge. The document then shows a
    function calling less than it does, with nothing logged. One narrowed parse from a full
    baseline is what the gate exercises, which is why it passed.
    """

    def test_it_is_published(self):
        assert "func_keys" in eng._PARSE_ARTIFACTS

    def test_the_merge_keeps_baseline_entries_for_untouched_files(self):
        from incremental.parse_merge import merge_model
        baseline = {
            "functions": {}, "globalVariables": {}, "dataDictionary": {}, "hashes": {},
            "edges": {"typeUsers": {}, "macroUsers": {}}, "tu_includes": {},
            "entity_files": {"F_UART": "uart.cpp", "F_TIMER": "timer.cpp"},
            "override_pairs": [], "metadata": {},
            "func_keys": {"_Z9uart_sendv": "F_UART", "_Z10timer_waitv": "F_TIMER"},
        }
        # A real partial parse re-emits entity_files for the file it re-parsed, so the new fid
        # resolves to a dropped file. Without that the merge cannot tell where it belongs.
        fresh = dict(baseline,
                     entity_files={"F_UART_NEW": "uart.cpp", "F_TIMER": "timer.cpp"},
                     func_keys={"_Z9uart_sendv": "F_UART_NEW"})
        merged = merge_model(baseline, fresh, ["uart.cpp"])
        fk = merged["func_keys"]
        assert fk["_Z10timer_waitv"] == "F_TIMER", \
            "the untouched file's func-key was dropped; cross-TU calls into it stop resolving"
        assert fk["_Z9uart_sendv"] == "F_UART_NEW", "the re-parsed file's func-key was not updated"

    def test_a_baseline_without_func_keys_does_not_break_the_merge(self):
        """Versions produced before this fix have no func_keys; merging must still work."""
        from incremental.parse_merge import merge_model
        baseline = {"functions": {}, "globalVariables": {}, "dataDictionary": {}, "hashes": {},
                    "edges": {"typeUsers": {}, "macroUsers": {}}, "tu_includes": {},
                    "entity_files": {}, "override_pairs": [], "metadata": {}}
        merged = merge_model(baseline, dict(baseline), [])
        assert merged["func_keys"] == {}
