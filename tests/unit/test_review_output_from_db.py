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
        assert "_verify_output_capture(version_id, output_dir, stored)" in _src(self.SRC)


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

    def test_only_an_export_only_run_restores(self):
        """A run that includes Phase 3 rewrites `output/` from the model, so restoring first
        would be work whose result is immediately overwritten.

        Checked in the source rather than by calling it: `run.py` executes a whole pipeline at
        import, so it cannot be imported to probe one function.
        """
        body = _src(self.SRC)[_src(self.SRC).index("def _restore_output_from_db"):]
        assert "if from_phase < 4:" in body[:900] and "return" in body[:900]

    def test_it_is_never_fatal(self):
        """The export still runs from disk if the restore fails -- which is what it did before
        this existed -- but it says so."""
        src = _src(self.SRC)
        body = src[src.index("def _restore_output_from_db"):]
        head = body[:2000]
        assert "except Exception as exc:" in head
        assert "err=True" in head
        assert "raise" not in head
