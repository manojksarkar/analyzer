"""doc 10 step 8 — the user-facing flags must work with the model in the database.

These are the features an operator actually touches, and each was broken or misleading once the
model stopped being files:

  * `--use-model` asked the FILESYSTEM whether a model existed, so it refused a perfectly good
    stored model and exited 2.
  * re-export runs `--use-model --from-phase 4`; without being told where the model is, Phase 4
    looks in an empty directory and the job fails.
  * `--clean` deletes DIRECTORIES. With the model in the database that reads as a fresh start
    while the rows survive.
  * `verify_model_parity` printed OK after comparing ZERO files — a check that passes on
    nothing, which is precisely the failure it exists to catch.
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


class TestUseModel:
    def test_asks_the_repository_not_the_filesystem(self):
        src = _src(os.path.join("engine", "run.py"))
        assert "from core.model_io import model_files_present as _present" in src
        assert "missing = _present(FUNCTIONS, GLOBALS, UNITS, COMPONENTS)" in src
        assert "missing = [p for p in MODEL_FILES if not os.path.isfile(p)]" not in src, \
            "--use-model must not test the filesystem: the model may be rows"

    def test_message_names_where_it_looked(self):
        """"model files missing" is wrong and unhelpful when the model should be in a table."""
        src = _src(os.path.join("engine", "run.py"))
        assert '"the database" if model_store_arg == "db" else "model/"' in src


class TestReexport:
    def test_tells_the_phases_where_the_model_is(self):
        src = _src(os.path.join("api", "services", "pipeline_runner.py"))
        assert "model_store=_store_kind" in src
        assert "version_id=_vid if _store_kind else None" in src

    def test_it_asks_rather_than_assumes(self):
        """A version generated before this work has files; one generated after may have only
        rows. Guessing sends Phase 4 to the empty place."""
        src = _src(os.path.join("api", "services", "pipeline_runner.py"))
        assert ".model_is_persisted(_vid)" in src

    def test_build_cmd_emits_the_flags(self):
        sys.path.insert(0, ROOT)
        from api.services.pipeline_runner import _build_cmd
        job = type("J", (), {"scope": None, "layer_filter": None, "no_llm": False,
                             "data_dict_id": None, "project_id": "p1"})()
        cmd = _build_cmd(job, "/checkout", "/cfg.json", from_phase=4, use_model=True,
                         model_store="db", version_id="ver9")
        assert cmd[cmd.index("--model-store") + 1] == "db"
        assert cmd[cmd.index("--version-id") + 1] == "ver9"

    def test_flags_absent_for_a_file_backed_version(self):
        sys.path.insert(0, ROOT)
        from api.services.pipeline_runner import _build_cmd
        job = type("J", (), {"scope": None, "layer_filter": None, "no_llm": False,
                             "data_dict_id": None, "project_id": "p1"})()
        cmd = _build_cmd(job, "/checkout", "/cfg.json", from_phase=4, use_model=True)
        assert "--model-store" not in cmd and "--version-id" not in cmd


class TestClean:
    def test_says_what_it_does_not_delete(self):
        src = _src(os.path.join("engine", "run.py"))
        assert "--clean removed the directories only" in src, \
            "--clean must state that the stored model survives, or it reads as a fresh start"
        assert 'if model_store_arg == "db":' in src


class TestParityCannotPassVacuously:
    def test_zero_files_compared_is_a_failure(self):
        """It printed OK after comparing nothing — the exact bug class it hunts. Verified live:
        an empty dump directory now exits 2 with "compared 0 model files"."""
        src = _src(os.path.join("tools", "verify_model_parity.py"))
        assert "if checked == 0:" in src
        assert "compared 0 model files" in src


class TestDebugDump:
    def test_the_writer_exists_and_is_debug_only(self):
        """H6: verify_model_parity compares the database against FILES, so the writer has to
        survive the files going away — behind a flag no job uses."""
        src = _src(os.path.join("engine", "run.py"))
        assert '"--dump-model-files"' in src
        assert "def _dump_model_files(" in src
        assert "verification only" in src

    def test_run_py_installs_the_repository(self):
        """It reads the model for the dump, and set_run_context only RECORDS the choice — so
        without installing, the dump wrote whatever few files happened to be on disk (1 of 8)."""
        src = _src(os.path.join("engine", "run.py"))
        assert "_install_model_repo()" in src
