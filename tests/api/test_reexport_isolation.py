"""Re-export must not touch the SHARED repo model/ and output/ (doc 09, B1 + C11b).

Generation was moved onto per-version directories, but re-export bypasses the incremental
orchestrator entirely and kept its own staging step:

    for sub in ("model", "output"):
        shutil.rmtree(root / sub)          # the shared <repo>/model, <repo>/output
        shutil.copytree(adir / sub, root / sub)

which is the exact concurrency hazard B1 removed — two jobs re-exporting at once wipe each
other's staged trees mid-run, and a re-export wipes a *generation* using those dirs. It also
copied the whole model and output twice per re-export.

These assert on the command and on the source, because the failure is "a directory was
deleted", which a normal unit test cannot observe after the fact.
"""
import os

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _source(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


class TestReexportRunsInPlace:
    def test_no_staging_into_the_shared_repo_dirs(self):
        src = _source("api/services/pipeline_runner.py")
        assert 'for sub in ("model", "output"):' not in src, (
            "re-export must not stage the version's trees into the shared repo dirs")
        assert "shutil.rmtree(dst, ignore_errors=True)" not in src, (
            "re-export must not rmtree a shared directory another job may be using")

    def test_reexport_passes_the_version_scoped_roots(self):
        src = _source("api/services/pipeline_runner.py")
        assert 'model_root=adir / "model"' in src
        assert 'output_root=adir / "output"' in src

    def test_build_cmd_emits_the_flags(self):
        """The flags have to reach run.py, not just exist as parameters."""
        import sys
        sys.path.insert(0, ROOT)
        from api.services.pipeline_runner import _build_cmd

        job = type("J", (), {"scope": None, "layer_filter": None, "no_llm": False,
                             "data_dict_id": None, "project_id": "p1"})()
        cmd = _build_cmd(job, "/checkout", "/cfg.json", from_phase=4, use_model=True,
                         model_root="/ver/model", output_root="/ver/output")
        assert "--model-root" in cmd and cmd[cmd.index("--model-root") + 1] == "/ver/model"
        assert "--output-root" in cmd and cmd[cmd.index("--output-root") + 1] == "/ver/output"

    def test_flags_are_omitted_when_not_given(self):
        """Generation calls _build_cmd without them; that path must be unchanged."""
        import sys
        sys.path.insert(0, ROOT)
        from api.services.pipeline_runner import _build_cmd

        job = type("J", (), {"scope": None, "layer_filter": None, "no_llm": False,
                             "data_dict_id": None, "project_id": "p1"})()
        cmd = _build_cmd(job, "/checkout", "/cfg.json")
        assert "--model-root" not in cmd and "--output-root" not in cmd


class TestReexportPersistsItsOutput:
    """With C0 the document renders from Postgres, so a re-export that only rewrote FILES
    would leave the stored views at the previous render — the re-export would appear to have
    done nothing at all."""

    def test_reexport_captures_output_back_into_the_store(self):
        src = _source("api/services/pipeline_runner.py")
        assert "_capture_reexport_output(db, job, adir)" in src
        assert "def _capture_reexport_output" in src
        assert "store.capture_output(version_id, str(adir / \"output\"))" in src

    def test_capture_is_skipped_without_a_version_id(self):
        """A legacy commit-keyed run has nothing version-scoped to update, and must not raise."""
        import sys
        sys.path.insert(0, ROOT)
        from api.services.pipeline_runner import _capture_reexport_output
        job = type("J", (), {"project_id": "p1", "version_id": None})()
        _capture_reexport_output(None, job, None)          # must be a silent no-op
