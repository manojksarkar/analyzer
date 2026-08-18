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


class TestEffectiveModelStore:
    """Step 11b: a run that cannot reach the database FAILS. It used to fall back to files.

    That fallback was right at step 9, when files were still a working backing. They are not
    any more — the model, the parse artifacts and the phase hand-offs are all rows — so a
    silent fallback produces a version that *looks* generated and is absent from every table
    the API reads. A loud failure at the start is strictly better than a quiet lie at the end.

    Three ways a run can be unable to reach it, each with its own actionable message:
      * no version id (a phase invoked standalone);
      * no database configured at all;
      * a version id with no `versions` row — the API reserves that row at job start and
        PgStore never creates one, so every per-version insert would fail on the foreign key.
    """

    def test_explicit_files_is_still_honoured(self):
        """`--model-store files` is a deliberate opt-out, not an accident — it stays."""
        assert run_context.effective_model_store("files", "ver1") == "files"

    def test_no_version_id_raises(self):
        with pytest.raises(run_context.DatabaseRequired, match="no version id"):
            run_context.effective_model_store("db", None)

    def test_no_database_raises(self, monkeypatch):
        monkeypatch.setattr("core.db.is_database_configured", lambda: False)
        with pytest.raises(run_context.DatabaseRequired, match="no database is configured"):
            run_context.effective_model_store("db", "ver1")

    def test_missing_versions_row_raises(self, monkeypatch):
        monkeypatch.setattr("core.db.is_database_configured", lambda: True)
        monkeypatch.setattr(run_context, "_version_row_exists", lambda vid: False)
        with pytest.raises(run_context.DatabaseRequired, match="ver-nope"):
            run_context.effective_model_store("db", "ver-nope")

    def test_db_when_everything_is_in_place(self, monkeypatch):
        monkeypatch.setattr("core.db.is_database_configured", lambda: True)
        monkeypatch.setattr(run_context, "_version_row_exists", lambda vid: True)
        assert run_context.effective_model_store("db", "ver1") == "db"

    def test_an_unreachable_database_raises_too(self, monkeypatch):
        """A dead database is not a reason to write files nobody will read."""
        def _boom():
            raise RuntimeError("connection refused")
        monkeypatch.setattr("core.db.get_engine", _boom)
        monkeypatch.setattr("core.db.is_database_configured", lambda: True)
        with pytest.raises(run_context.DatabaseRequired):
            run_context.effective_model_store("db", "ver1")

    @pytest.mark.parametrize("bad,fix", [
        (None, "--version-id"),
        ("ver-nope", "INSERT the row first"),
    ])
    def test_the_message_says_how_to_fix_it(self, monkeypatch, bad, fix):
        """An operator hitting this at 2am should not have to read the source."""
        monkeypatch.setattr("core.db.is_database_configured", lambda: True)
        monkeypatch.setattr(run_context, "_version_row_exists", lambda vid: False)
        with pytest.raises(run_context.DatabaseRequired) as exc:
            run_context.effective_model_store("db", bad)
        assert fix in str(exc.value)


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

    @pytest.mark.parametrize("name,fn", [("generate.py", "def generate_full("),
                                         ("engine.py", "def generate_incremental(")])
    def test_the_orchestrator_entry_point_defaults_to_the_database(self, name, fn):
        """Step 9: the database is the default, so a UI job gets it without the API asking.

        Matched inside the entry point's own signature — an earlier version of this check looked
        for the default anywhere in the file and was satisfied by a private helper's, so
        generate.py "passed" while saying nothing about generate_full at all.
        """
        src = _src(os.path.join("engine", "incremental", name))
        sig = src[src.index(fn):]
        sig = sig[:sig.index(") -> Dict[str, Any]:")]
        assert 'model_store: str = "db"' in sig, f"{name}: {fn.strip()} does not default to db"
        assert '"--model-store"' in src, f"{name}: no CLI flag"
        assert 'ap.add_argument("--model-store", default="db"' in src, f"{name}: CLI default"

    @pytest.mark.parametrize("name", ["generate.py", "engine.py"])
    def test_the_default_is_resolved_against_the_machine(self, name):
        """'db' as a default has to survive a machine with no database and a CLI run whose
        version was never reserved — otherwise the default breaks those runs outright."""
        src = _src(os.path.join("engine", "incremental", name))
        assert "effective_model_store(model_store, version_id)" in src, \
            f"{name}: the requested store is used unresolved"

    def test_orchestrator_reads_the_model_from_the_store_in_db_mode(self):
        """The end-of-run report and fingerprints need the finished model. In db mode the files
        are not there, so reading them would report zero counts and seed nothing."""
        src = _src(os.path.join("engine", "incremental", "generate.py"))
        assert "def _orchestrator_model(" in src
        assert 'if model_store == "db":\n        return store.read_model(version_id) or {}' in src


class TestIncrementalEngineInDatabaseMode:
    """The incremental path had three file-based reads/writes that database mode breaks.

    Verified end to end on SQLite (two commits, `decision=incremental regenerated=1
    reused=281`, 9 parse-snapshot files); these keep the conversions from being undone.
    """

    def test_target_model_is_read_from_the_store(self):
        """It classifies against the model Phase 1 just produced. Reading files in database
        mode yields four EMPTY dicts — every entity then looks DELETED, impact is empty, and the
        run regenerates nothing while reporting success."""
        src = _src(os.path.join("engine", "incremental", "engine.py"))
        assert "_tm = _orchestrator_model(store, version_id, model_dir, _MODEL_STORE)" in src
        for name in ('_tm.get("hashes")', '_tm.get("functions")', '_tm.get("edges")',
                     '_tm.get("globals")'):
            assert name in src, f"target model still read from files: {name} missing"

    def test_carry_forward_is_published_where_phase_2_reads(self):
        """Carry-forward copies the baseline's descriptions onto the reuse set so Phase 2 can
        skip them. Writing files in database mode puts them where Phase 2 never looks, so every
        reused entity arrives blank and is regenerated — the reuse is computed then thrown away."""
        src = _src(os.path.join("engine", "incremental", "engine.py"))
        assert "_publish_model_for_next_phase(" in src
        assert "def _publish_model_for_next_phase" in src

    def test_parse_snapshot_takes_the_store_kind_explicitly(self):
        """It read the ambient run context, which the ORCHESTRATOR never populates — so the
        check always said "files" and the snapshot silently captured only the few artifacts that
        had not moved (4 of 9). Ambient state that one process sets and another reads is the bug."""
        gen = _src(os.path.join("engine", "incremental", "generate.py"))
        assert 'version_id: str = "", model_store: str = "files"' in gen
        assert "from core.run_context import model_store_kind" not in gen, \
            "the snapshot must not infer the store kind from ambient state"
        eng_src = _src(os.path.join("engine", "incremental", "engine.py"))
        assert "snapshot_parse_model(model_dir, _adir, store, version_id, _MODEL_STORE)" in eng_src
