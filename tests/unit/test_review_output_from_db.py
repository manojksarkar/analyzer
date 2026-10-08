"""Text output comes from the database, and a divergence is reported (REQ-PRE-02).

Two holes, both quiet.

**An export-only run reads whatever is on disk.** `--from-phase 4` skips Phase 3, so it exports the
text files this machine happens to have. But the database is where the view rows live, and it is
what a correction updates — `rerender.write_output_row` writes the row, not the file. Correct a
flowchart label and re-export, and the document is built from the previous text on a machine whose
disk was simply never told.

**The capture used to swallow its own failures.** `except Exception: pass`, under the note
"best-effort: disk output is intact" — and the disk being intact is exactly what made it dangerous.
The document served from the database, or from another node, silently kept the previous render
while this machine looked correct.
"""
import os
import re
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))


def _src(rel):
    return open(os.path.join(PROJECT_ROOT, *rel.split("/")), encoding="utf-8").read()


class TestTheCaptureNoLongerSwallowsFailures:
    SRC = "engine/incremental/store.py"

    def test_the_bare_swallow_is_gone(self):
        src = _src(self.SRC)
        assert "except Exception:                                    # best-effort" not in src
        assert re.search(r"except Exception as exc:\s*\n\s*#\s*NOT swallowed", src), (
            "the capture failure is silent again; a divergence between disk and database "
            "would go unreported")

    def test_the_failure_is_reported_at_error_level(self):
        """A warning would be lost in a run's output. This is the one place that knows the two
        stores have diverged."""
        src = _src(self.SRC)
        assert 'get_logger("incremental").error(' in src

    def test_it_still_does_not_fail_the_run(self):
        """The documents are already produced and on disk. Failing here would throw away a
        completed generation over a bookkeeping write."""
        src = _src(self.SRC)
        block = src[src.index("except Exception as exc:"):]
        assert "raise" not in block[:900]

    def test_what_landed_is_verified(self):
        """A returned count is not proof: it counts rows offered, not rows that survived. The
        cheap check is files-on-disk against rows-written."""
        # `components`: a run that stored only the components it rebuilt counts only their files.
        assert "_verify_output_capture(version_id, output_dir, stored, components)" in _src(self.SRC)


class TestTheVerifier:
    def test_a_match_says_nothing(self, tmp_path, caplog):
        import incremental.store as st
        (tmp_path / "a.json").write_text("{}", encoding="utf-8")
        (tmp_path / "b.mmd").write_text("x", encoding="utf-8")
        st._verify_output_capture("v1", str(tmp_path), 2)
        assert "disagree" not in caplog.text

    def test_a_mismatch_is_reported(self, tmp_path, caplog):
        import logging
        import incremental.store as st
        (tmp_path / "a.json").write_text("{}", encoding="utf-8")
        (tmp_path / "b.mmd").write_text("x", encoding="utf-8")
        with caplog.at_level(logging.WARNING):
            st._verify_output_capture("v1", str(tmp_path), 1)
        assert "disagree" in caplog.text

    def test_binaries_are_not_counted(self, tmp_path, caplog):
        """PNG and DOCX stay as files by design (D-14); counting them would report a divergence
        on every single run."""
        import logging
        import incremental.store as st
        (tmp_path / "a.json").write_text("{}", encoding="utf-8")
        (tmp_path / "pic.png").write_bytes(b"\x89PNG")
        (tmp_path / "doc.docx").write_bytes(b"PK")
        with caplog.at_level(logging.WARNING):
            st._verify_output_capture("v1", str(tmp_path), 1)
        assert "disagree" not in caplog.text

    def test_a_missing_directory_is_not_an_error(self):
        import incremental.store as st
        st._verify_output_capture("v1", "/no/such/dir", 0)

    def test_nested_output_is_counted(self, tmp_path, caplog):
        """Views write into `output/<group>/`, so a flat listing would under-count and report a
        divergence on every run that produced a group."""
        import logging
        import incremental.store as st
        sub = tmp_path / "Sample" / "flowcharts"
        sub.mkdir(parents=True)
        (sub / "UnitA.json").write_text("[]", encoding="utf-8")
        with caplog.at_level(logging.WARNING):
            st._verify_output_capture("v1", str(tmp_path), 1)
        assert "disagree" not in caplog.text


class TestAnExportOnlyRunReadsTheDatabase:
    SRC = "engine/run.py"
    CALL = re.compile(r"^_restore_output_from_db\(from_phase\)", re.M)

    def test_the_restore_is_called(self):
        assert self.CALL.search(_src(self.SRC)), (
            "an export-only run no longer restores its text from the database, so it exports "
            "whatever is on this machine's disk (REQ-PRE-02)")

    def test_the_matcher_rejects_the_definition(self):
        assert not self.CALL.search("def _restore_output_from_db(from_phase: int) -> None:")

    def test_it_runs_before_the_phases(self):
        src = _src(self.SRC)
        call = self.CALL.search(src)
        assert call and call.start() < src.index("runner = PhaseRunner(project_root=SCRIPT_DIR)")

    def test_a_re_derive_restores_too(self):
        """Not only an export-only run. A re-derive rebuilds only the views and groups it runs,
        and the capture after it REPLACES every stored row with this disk: from a stale or empty
        disk that put old rows back and dropped the rest -- a SWE.3 re-export lost a CLI version's
        SWE.4 specs. A generation starts at phase 1, and a new version has no rows to restore.

        Checked in the source rather than by calling it: `run.py` executes a whole pipeline at
        import, so it cannot be imported to probe one function.
        """
        body = _src(self.SRC)[_src(self.SRC).index("def _restore_output_from_db"):]
        head = body[:body.index("try:")]
        assert "if from_phase < 2:" in head and "return" in head

    def test_what_it_calls_exists(self):
        """THE DEFECT THIS CATCHES. The restore imported `restore_output_files`, which never
        existed. The ImportError was caught as "could not restore", every run exported from
        whatever was on disk, and every test in this class passed -- they read the source.
        Asking the module is what fails."""
        import importlib
        src = _src(self.SRC)
        body = src[src.index("def _restore_output_from_db"):src.index("def _refuse_stale_export")]
        names = re.findall(r"from (core\.\w+) import (\w+)", body)
        assert names, "the restore imports nothing from core any more -- re-read this test"
        for module, name in names:
            assert hasattr(importlib.import_module(module), name), "%s.%s" % (module, name)

    def test_every_name_it_uses_is_defined(self):
        """The same defect's twin, found once the import was fixed: it also called `_paths()`,
        which `run.py` never defined -- a NameError, caught as "could not restore" like the
        ImportError before it. A name used in the function must be bound in it, in `run.py`'s
        top level, or be a builtin."""
        import ast
        import builtins
        tree = ast.parse(_src(self.SRC))
        top = set()
        for node in tree.body:
            for n in ast.walk(node) if not isinstance(node, ast.FunctionDef) else (node,):
                if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
                    top.add(n.name)
                elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                    top.add(n.id)
                elif isinstance(n, (ast.Import, ast.ImportFrom)):
                    top.update((a.asname or a.name).split(".")[0] for a in n.names)
        fn = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "_restore_output_from_db")
        local = {a.arg for a in fn.args.args}
        for n in ast.walk(fn):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                local.add(n.id)
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                local.update((a.asname or a.name).split(".")[0] for a in n.names)
            elif isinstance(n, ast.ExceptHandler) and n.name:
                local.add(n.name)
            elif isinstance(n, ast.withitem) and isinstance(n.optional_vars, ast.Name):
                local.add(n.optional_vars.id)
        used = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        undefined = sorted(used - local - top - set(dir(builtins)))
        assert not undefined, "undefined in _restore_output_from_db: %s" % undefined

    def test_the_stored_row_wins_over_the_disk(self, tmp_path):
        """What the restore is for: a correction updated the row, not this machine's file."""
        import datetime
        import sqlalchemy as sa
        from api.db.postgres import schema as s
        from core.model_store import dump_output_files_to_dir

        eng = sa.create_engine("sqlite://")
        s.metadata.create_all(eng)
        (tmp_path / "G").mkdir()
        (tmp_path / "G" / "test_specs.json").write_text("the previous text", encoding="utf-8")
        with eng.begin() as cx:
            now = datetime.datetime.now(datetime.timezone.utc)
            cx.execute(sa.insert(s.projects).values(id="p", name="p", created_at=now))
            cx.execute(sa.insert(s.versions).values(id="v1", project_id="p", version="v1",
                                                    created_at=now))
            cx.execute(sa.insert(s.version_output_files).values(
                version_id="v1", rel_path="G/test_specs.json", content="the corrected text",
                group_name="G"))
            assert dump_output_files_to_dir(cx, "v1", str(tmp_path)) == 1
        assert (tmp_path / "G" / "test_specs.json").read_text(encoding="utf-8") == \
            "the corrected text"

    def test_an_export_only_run_restores_its_components_alone(self, tmp_path):
        """FAST_WORD_FILE_UPDATES P2: an export-only update of one component wrote every
        component's stored output to disk first. Matched as the guard matches a component."""
        import datetime
        import sqlalchemy as sa
        from api.db.postgres import schema as s
        from core.model_store import dump_output_files_to_dir

        eng = sa.create_engine("sqlite://")
        s.metadata.create_all(eng)
        with eng.begin() as cx:
            now = datetime.datetime.now(datetime.timezone.utc)
            cx.execute(sa.insert(s.projects).values(id="p", name="p", created_at=now))
            cx.execute(sa.insert(s.versions).values(id="v1", project_id="p", version="v1",
                                                    created_at=now))
            for rel, group in (("Layer1.Sample-Core/a.json", "Layer1.Sample-Core"),
                               ("Layer1.Lib/b.json", "Layer1.Lib"), ("top.json", None)):
                cx.execute(sa.insert(s.version_output_files).values(
                    version_id="v1", rel_path=rel, content="x", group_name=group))
            assert dump_output_files_to_dir(cx, "v1", str(tmp_path),
                                            groups=["Layer1.Sample Core"]) == 2
        assert (tmp_path / "Layer1.Sample-Core" / "a.json").is_file()
        assert (tmp_path / "top.json").is_file()
        assert not (tmp_path / "Layer1.Lib").exists()

    def test_only_an_export_only_run_restores_by_component(self):
        """A run that derives restores everything: a view may read another component's output. An
        update's Phase 3 limited to some views (`--views`: the flowcharts and SWE.4 views, which
        read their own directory) restores by component too (FAST_WORD_FILE_UPDATES P5)."""
        src = _src(self.SRC)
        body = src[src.index("def _restore_output_from_db"):]
        body = body[:body.index("\ndef ")]
        assert ("groups = (_doc_components(plans) or None) if from_phase >= 4 or views_arg "
                "else None") in body

    def test_an_export_only_run_draws_the_web_pictures_the_restore_put_back_stale(self):
        """FAST_WORD_FILE_UPDATES P2 made a label correction's Word-file update export-only. Its
        restore writes back the stored SVG -- the last capture's, drawn from the DOT before the
        correction -- over the one the save drew, and Phase 3, which draws them, does not run: the
        web page read "Flowchart not drawn for this run" after every label update while the Word
        file had the new picture. After the restore, those are drawn again (`refresh_web_svgs`)."""
        import importlib
        src = _src(self.SRC)
        body = src[src.index("def _restore_output_from_db"):]
        body = body[:body.index("\ndef ")]
        call = re.search(r"if from_phase >= 4:\s*\n\s*_refresh_web_flowcharts\(groups\)", body)
        assert call, "an export-only run no longer draws the web pictures after its restore"
        assert body.index("dump_output_files_to_dir(cx") < call.start()
        assert "refresh_web_svgs(" in src[src.index("def _refresh_web_flowcharts"):]
        assert hasattr(importlib.import_module("views.flowcharts"), "refresh_web_svgs")

    def test_it_is_never_fatal(self):
        """The export still runs from disk if the restore fails -- which is what it did before
        this existed -- but it says so."""
        src = _src(self.SRC)
        body = src[src.index("def _restore_output_from_db"):]
        head = body[:body.index("\ndef ")]                 # the function, whatever its length
        assert "except Exception as exc:" in head
        assert "err=True" in head
        assert "raise" not in head
