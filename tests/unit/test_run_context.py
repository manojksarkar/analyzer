"""core/run_context — what a phase learns about the run it belongs to (doc 10, step 3).

A phase is its own process and starts knowing nothing. It used to infer the model from the
filesystem ("whatever is in model/"), which is implicit and stops working once the model is in
the database: there it must be told WHICH version it is working on (D10-8).

The two tests that matter most here are the ones a real run found, not review:

  * a writing phase must FLUSH before it exits. Database writes are buffered so the pieces
    persist together in one transaction, so a phase that exits without flushing loses
    everything it wrote — Phase 2 then reported "model 'functions' is not in the database".
  * the C11a file-based persist hook must be OFF in database mode. It persists by READING model
    files (write_model -> persist_model_from_dir -> clear_version + persist), so with no files
    it would clear the version and store an EMPTY model over what the phase just flushed.
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "engine"))

from core import run_context                     # noqa: E402

# Phases that WRITE the model, so losing their buffer loses real data.
WRITING_PHASES = ["parser.py", "model_deriver.py", "run_views.py"]


def _src(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(autouse=True)
def _restore():
    v, p, m = run_context.version_id(), run_context.project_id(), run_context.model_store_kind()
    yield
    run_context.set_run_context(version=v or "", project=p or "", model_store=m)
    from core import model_repo
    model_repo.set_repository(None)


class TestCliParsing:
    def test_flags_are_applied_and_stripped(self):
        argv = ["prog", "SampleCppProject", "--version-id", "ver9",
                "--project-id", "p1", "--model-store", "files", "--selected-group", "G"]
        out = run_context.apply_cli_run_context(argv)
        assert run_context.version_id() == "ver9"
        assert run_context.project_id() == "p1"
        # stripped so a positional-parsing phase (docx_exporter) cannot mistake them for paths
        assert out == ["prog", "SampleCppProject", "--selected-group", "G"]

    def test_default_is_files(self):
        run_context.apply_cli_run_context(["prog", "SampleCppProject"])
        assert run_context.model_store_kind() == "files"
        from core import model_repo
        assert isinstance(model_repo.repository(), model_repo.FileRepository)

    def test_db_without_a_version_id_falls_back_loudly(self, capsys):
        """A run that cannot identify its version must still produce a document, with a warning
        — not die at import."""
        run_context.set_run_context(version="", project="", model_store="files")
        run_context.apply_cli_run_context(["prog", "--model-store", "db"])
        from core import model_repo
        assert isinstance(model_repo.repository(), model_repo.FileRepository)
        assert "no --version-id" in capsys.readouterr().err


class TestPhasesFlush:
    """Found by a real DB-mode run: Phase 1 wrote, buffered, exited — and Phase 2 reported
    "model 'functions' is not in the database for version …". The unit suite was green."""

    @pytest.mark.parametrize("name", WRITING_PHASES)
    def test_writing_phase_flushes_before_exit(self, name):
        src = _src(os.path.join("engine", name))
        assert "flush_model()" in src, (
            f"{name} writes the model but never flushes — in database mode its writes are "
            f"buffered, so exiting without a flush loses them silently")

    @pytest.mark.parametrize("name", WRITING_PHASES)
    def test_flush_is_after_main_not_in_a_finally(self, name):
        """A phase that FAILED must not publish a half-built model."""
        src = _src(os.path.join("engine", name))
        tail = src[src.index('if __name__ == "__main__":'):]
        # Look for a `finally:` STATEMENT, not the word — the comment above the flush explains
        # why a finally would be wrong, and a substring check matches its own rationale.
        code = [ln.split("#", 1)[0].strip() for ln in tail.splitlines()]
        assert not any(ln.startswith("finally:") for ln in code), \
            f"{name}: flushing in a finally would publish a failed run's half-built model"
        assert tail.index("main()") < tail.index("flush_model()")


class TestC11aHookOffInDbMode:
    def test_hook_is_disabled_when_the_model_is_in_the_database(self):
        """It persists by READING model files, so in DB mode it would clear the version and
        store an empty model over what the phase just flushed."""
        src = _src(os.path.join("engine", "run.py"))
        assert 'if model_store_kind() == "db":\n        return None' in src, \
            "the file-based persist hook must be off in database mode"

    def test_hook_still_active_in_file_mode(self):
        """The dual-write is what C11a exists for; it must not be lost."""
        src = _src(os.path.join("engine", "run.py"))
        assert "store.write_model(version_id, _p().model_dir)" in src


class TestOrchestratorForwardsIdentity:
    def test_version_and_project_reach_the_phase(self):
        src = _src(os.path.join("engine", "core", "orchestration.py"))
        assert '"--version-id", version_id()' in src
        assert '"--project-id", project_id()' in src
        assert '"--model-store", model_store_kind()' in src

    def test_identity_is_omitted_when_unset(self):
        """A plain file run's argv must be byte-identical to before."""
        from core.orchestration import Phase
        run_context.set_run_context(version="", project="", model_store="files")
        cmd = Phase("p", "parser.py", ["SampleCppProject"]).command(os.path.join(ROOT, "engine"))
        assert "--version-id" not in cmd and "--model-store" not in cmd


class TestOrchestratorsRespectTheModelStore:
    """The orchestrators end a run with store.write_model(version_id, model_dir), which persists
    by READING model files: persist_model_from_dir -> clear_version + persist. In database mode
    the phases wrote to the database and the model dir holds only unmigrated artifacts, so that
    call would CLEAR the version and store an empty model over the real one.

    Verified end to end by a full orchestrated db-mode generation (26 documents, 281 functions
    still in the database afterwards); these keep the guards from being removed.
    """

    @pytest.mark.parametrize("name", ["generate.py", "engine.py"])
    def test_write_model_is_guarded(self, name):
        src = _src(os.path.join("engine", "incremental", name))
        i = src.index("store.write_model(version_id, model_dir)")
        before = src[max(0, i - 400):i]
        assert 'model_store != "db"' in before or '_MODEL_STORE != "db"' in before, \
            f"{name}: write_model must not run in database mode — it would clear the version"

    @pytest.mark.parametrize("name", ["generate.py", "engine.py"])
    def test_model_store_reaches_the_phases(self, name):
        """A phase writing files while the orchestrator reads the database is the worst of both."""
        src = _src(os.path.join("engine", "incremental", name))
        assert '"--model-store", "db"' in src, f"{name}: phases are not told the model store"

    @pytest.mark.parametrize("name", ["generate.py", "engine.py"])
    def test_model_store_is_a_real_parameter(self, name):
        src = _src(os.path.join("engine", "incremental", name))
        assert 'model_store: str = "files"' in src, f"{name}: model_store is not a parameter"
        assert '"--model-store"' in src, f"{name}: no CLI flag"

    def test_orchestrator_reads_the_model_from_the_store_in_db_mode(self):
        """The end-of-run report and fingerprints need the finished model. In db mode the files
        are not there, so reading them would report zero counts and seed nothing."""
        src = _src(os.path.join("engine", "incremental", "generate.py"))
        assert "def _orchestrator_model(" in src
        assert 'if model_store == "db":\n        return store.read_model(version_id) or {}' in src
