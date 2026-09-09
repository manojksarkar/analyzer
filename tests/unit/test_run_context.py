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
    v, p = run_context.version_id(), run_context.project_id()
    yield
    run_context.set_run_context(version=v or "", project=p or "")
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


    def test_no_version_id_raises(self):
        with pytest.raises(run_context.DatabaseRequired, match="no version id"):
            run_context.effective_model_store(None)

    def test_no_database_raises(self, monkeypatch):
        monkeypatch.setattr("core.db.is_database_configured", lambda: False)
        with pytest.raises(run_context.DatabaseRequired, match="no database is configured"):
            run_context.effective_model_store("ver1")

    def test_missing_versions_row_raises(self, monkeypatch):
        monkeypatch.setattr("core.db.is_database_configured", lambda: True)
        monkeypatch.setattr(run_context, "_version_row_exists", lambda vid: False)
        with pytest.raises(run_context.DatabaseRequired, match="ver-nope"):
            run_context.effective_model_store("ver-nope")

    def test_db_when_everything_is_in_place(self, monkeypatch):
        monkeypatch.setattr("core.db.is_database_configured", lambda: True)
        monkeypatch.setattr(run_context, "_version_row_exists", lambda vid: True)
        assert run_context.effective_model_store("ver1") == "db"

    def test_an_unreachable_database_raises_too(self, monkeypatch):
        """A dead database is not a reason to write files nobody will read."""
        def _boom():
            raise RuntimeError("connection refused")
        monkeypatch.setattr("core.db.get_engine", _boom)
        monkeypatch.setattr("core.db.is_database_configured", lambda: True)
        with pytest.raises(run_context.DatabaseRequired):
            run_context.effective_model_store("ver1")

    @pytest.mark.parametrize("bad,fix", [
        (None, "--version-id"),
        # Was "INSERT the row first", pointing at a design document. It names the command now.
        ("ver-nope", "analyzer.py onboard"),
    ])
    def test_the_message_says_how_to_fix_it(self, monkeypatch, bad, fix):
        """An operator hitting this at 2am should not have to read the source."""
        monkeypatch.setattr("core.db.is_database_configured", lambda: True)
        monkeypatch.setattr(run_context, "_version_row_exists", lambda vid: False)
        with pytest.raises(run_context.DatabaseRequired) as exc:
            run_context.effective_model_store(bad)
        assert fix in str(exc.value)


class TestCliParsing:
    def test_flags_are_applied_and_stripped(self):
        argv = ["prog", "SampleCppProject", "--version-id", "ver9",
                "--project-id", "p1", "--selected-group", "G"]
        out = run_context.apply_cli_run_context(argv)
        assert run_context.version_id() == "ver9"
        assert run_context.project_id() == "p1"
        # stripped so a positional-parsing phase (docx_exporter) cannot mistake them for paths
        assert out == ["prog", "SampleCppProject", "--selected-group", "G"]




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




class TestOrchestratorForwardsIdentity:
    def test_version_and_project_reach_the_phase(self):
        src = _src(os.path.join("engine", "core", "orchestration.py"))
        assert '"--version-id", version_id()' in src
        assert '"--project-id", project_id()' in src

    def test_identity_is_omitted_when_unset(self):
        """A run with no identity yet must not gain flags it cannot fill in."""
        from core.orchestration import Phase
        run_context.set_run_context(version="", project="")
        cmd = Phase("p", "parser.py", ["SampleCppProject"]).command(os.path.join(ROOT, "engine"))
        assert "--version-id" not in cmd and "--project-id" not in cmd




class TestIncrementalEngineInDatabaseMode:
    """The incremental path had three file-based reads/writes that database mode breaks.

    Verified end to end on SQLite (two commits, `decision=incremental regenerated=1
    reused=281`, 9 parse-snapshot files); these keep the conversions from being undone.
    """

    def test_target_model_is_read_from_the_store(self):
        """It classifies against the model Phase 1 just produced. Reading files instead
        yields four EMPTY dicts — every entity then looks DELETED, impact is empty, and the
        run regenerates nothing while reporting success."""
        src = _src(os.path.join("engine", "incremental", "engine.py"))
        assert "_tm = _orchestrator_model(store, version_id)" in src
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



class TestTheMissingVersionMessageIsActionable:
    """The error a CLI user hits most often must name the command that fixes it.

    It pointed at "docs/production-redesign/10-db-native-pipeline.md §9" — a design document —
    and was written before tools/new_project.py existed. Reading a plan's section 9 to discover
    that one command reserves the row is a poor trade for one line of output.
    """

    def test_it_names_the_command_with_the_real_values(self, monkeypatch):
        monkeypatch.setattr("core.db.is_database_configured", lambda: True)
        monkeypatch.setattr(run_context, "_version_row_exists", lambda vid: False)
        with pytest.raises(run_context.DatabaseRequired) as exc:
            run_context.effective_model_store("v1", project_id="myproj", commit="a" * 40)
        msg = str(exc.value)
        assert "analyzer.py onboard" in msg
        assert "--project-id myproj" in msg, "the message should carry the caller's own values"
        assert "--version-id v1" in msg
        assert "a" * 40 in msg
        assert "--create-version" in msg
        assert "10-db-native-pipeline.md" not in msg, "it should not send anyone to a design doc"

    def test_it_degrades_to_placeholders_when_it_has_no_values(self, monkeypatch):
        monkeypatch.setattr("core.db.is_database_configured", lambda: True)
        monkeypatch.setattr(run_context, "_version_row_exists", lambda vid: False)
        with pytest.raises(run_context.DatabaseRequired) as exc:
            run_context.effective_model_store("v1")
        assert "<project-id>" in str(exc.value)


class TestCreateVersionIsOptIn:
    """`--create-version` exists so a CLI-only run is one command, not two.

    Deliberately NOT the default: the row is the API's to own, and creating one silently would
    turn a mistyped --version-id into a brand-new version instead of the error it should be.
    """

    def test_without_the_flag_a_missing_row_still_raises(self, monkeypatch):
        monkeypatch.setattr("core.db.is_database_configured", lambda: True)
        monkeypatch.setattr(run_context, "_version_row_exists", lambda vid: False)
        created = []
        monkeypatch.setattr(run_context, "_create_version_row",
                            lambda *a: created.append(a) or True)
        with pytest.raises(run_context.DatabaseRequired):
            run_context.effective_model_store("v1", project_id="p", commit="c" * 40)
        assert not created, "the row was created without --create-version"

    def test_with_the_flag_it_creates_and_proceeds(self, monkeypatch):
        monkeypatch.setattr("core.db.is_database_configured", lambda: True)
        monkeypatch.setattr(run_context, "_version_row_exists", lambda vid: False)
        monkeypatch.setattr(run_context, "_create_version_row", lambda *a: True)
        assert run_context.effective_model_store(
            "v1", project_id="p", commit="c" * 40, create_version=True) == "db"

    def test_a_failed_create_still_raises(self, monkeypatch):
        """Reporting success on a row that was not created would be the worst outcome."""
        monkeypatch.setattr("core.db.is_database_configured", lambda: True)
        monkeypatch.setattr(run_context, "_version_row_exists", lambda vid: False)
        monkeypatch.setattr(run_context, "_create_version_row", lambda *a: False)
        with pytest.raises(run_context.DatabaseRequired, match="could not create"):
            run_context.effective_model_store(
                "v1", project_id="p", commit="c" * 40, create_version=True)

    def test_it_needs_both_project_and_commit(self, monkeypatch):
        """Without them there is nothing to write into the row."""
        monkeypatch.setattr("core.db.is_database_configured", lambda: True)
        monkeypatch.setattr(run_context, "_version_row_exists", lambda vid: False)
        monkeypatch.setattr(run_context, "_create_version_row",
                            lambda *a: pytest.fail("should not attempt a create"))
        with pytest.raises(run_context.DatabaseRequired):
            run_context.effective_model_store("v1", create_version=True)


@pytest.mark.parametrize("name", ["generate.py", "engine.py"])
def test_both_orchestrators_expose_create_version(name):
    """The FLAG lives on analyzer.py now — the orchestrators are library functions. What must
    survive is the parameter reaching effective_model_store, which is what actually reserves
    the row."""
    src = _src(os.path.join("engine", "incremental", name))
    assert "create_version=create_version" in src
    cli = _src("analyzer.py")
    assert '"--create-version"' in cli, "the CLI must still offer it"
    assert "create_version=a.create_version" in cli, "and pass it through"
