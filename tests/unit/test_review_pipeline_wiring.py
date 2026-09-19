"""The pipeline actually calls the review machinery (REQ-AP-05, REQ-VR-01).

Everything under these two call sites is built and tested. What no other test can see is whether a
real run reaches them — and a helper that works and is never called is the worst of both worlds:
every test passes and the feature silently does nothing.

This codebase has had exactly that. A guard's import moved, so it quietly stopped running and
nothing failed; and earlier in this same feature a wiring test could not fail, because its matcher
also matched the function's own `def` line.

`generate_incremental` and `run_views.main` cannot be invoked here — they need a checkout, a
database, libclang and a subprocess — so the call sites are checked in the source, the same way the
exporter is checked for LLM calls it must not make. The behaviour beneath them is covered by
test_review_carry_forward and test_review_phase3_input.
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


class TestPhase3IsHandedTheCorrections:
    """REQ-AP-05. Node labels and behaviour descriptions have no model field, so a run must be
    given them or every such correction is dropped by the next regeneration."""

    SRC = "engine/run_views.py"
    CALL = re.compile(r"^[ \t]*config = _with_text_overrides\(config\)", re.M)

    def test_the_runner_attaches_them(self):
        assert self.CALL.search(_src(self.SRC)), (
            "run_views no longer attaches text overrides, so every node-label and "
            "behaviour-description correction is silently dropped on the next run")

    def test_the_check_can_fail(self):
        """The matcher must not also match the definition -- that mistake was made once already
        in this feature, and the test passed however the code behaved."""
        assert not self.CALL.search("def _with_text_overrides(config):")
        assert self.CALL.search("    config = _with_text_overrides(config)")

    def test_it_happens_before_the_views_run(self):
        """Attached afterwards, the views would already have been built from the LLM's text."""
        src = _src(self.SRC)
        call = self.CALL.search(src)
        assert call and call.start() < src.index(
            "run_views(model, output_dir, model_dir, config, doc_type=doc_type)")

    def test_a_run_with_no_version_is_left_alone(self):
        """A standalone run has no version id and no database. Neither is a reason to fail a
        phase that has already paid for the parse."""
        import run_views
        cfg = {"views": {"flowcharts": True}}
        assert run_views._with_text_overrides(cfg) is cfg or \
            run_views._with_text_overrides(cfg) == cfg

    def test_a_failure_returns_the_config_unchanged(self, monkeypatch):
        import run_views
        from core import run_context
        monkeypatch.setattr(run_context, "version_id", lambda: "v1")
        import core.db as core_db
        monkeypatch.setattr(core_db, "is_database_configured", lambda *a, **k: True)
        monkeypatch.setattr(core_db, "get_engine",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no db")))
        cfg = {"views": {}}
        assert run_views._with_text_overrides(cfg) == cfg


class TestCorrectionsAreCarriedByAGeneration:
    """REQ-VR-01. The baseline's model carries the reviewer's TEXT already; what a run must also
    carry is the override ROWS, or the new version does not know which of its text is human."""

    SRC = "engine/incremental/engine.py"
    CALL = re.compile(r"^[ \t]*_carry_review_overrides\(base_vid, version_id\)", re.M)

    def test_the_incremental_run_carries_them(self):
        assert self.CALL.search(_src(self.SRC)), (
            "an incremental generation no longer carries reviewer corrections from its "
            "baseline, so every correction stops at the version it was made on")

    def test_the_check_can_fail(self):
        assert not self.CALL.search("def _carry_review_overrides(baseline_version_id, target):")

    def test_it_runs_beside_the_text_carry_forward(self):
        """The two belong together: one moves the words, the other moves the record of who wrote
        them. Separated, it is easy to keep one and lose the other."""
        src = _src(self.SRC)
        call = self.CALL.search(src)
        assert call and call.start() > src.index("n_carried_g = carry_forward_globals(")

    def test_a_failure_does_not_fail_the_generation(self, monkeypatch):
        """A run that has already paid for the parse and the LLM must not be lost because
        corrections could not be copied. They stay on the baseline for a later run."""
        import incremental.engine as eng
        import core.db as core_db
        monkeypatch.setattr(core_db, "is_database_configured", lambda *a, **k: True)
        monkeypatch.setattr(core_db, "get_engine",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        eng._carry_review_overrides("v3", "v4")          # must not raise

    def test_no_baseline_is_a_no_op(self):
        """`--full` has no baseline. REQ-VR-03: it must carry nothing and destroy nothing."""
        import incremental.engine as eng
        eng._carry_review_overrides("", "v4")
        eng._carry_review_overrides(None, "v4")


class TestEveryPieceHasACaller:
    """A map of what is wired and what is deliberately not, so an unwired piece is a decision
    rather than something nobody noticed."""

    WIRED = {
        "carry_forward.carry_overrides": ("engine/incremental/engine.py",
                                          "_carry_review_overrides"),
        "carry_forward.config_with_overrides": ("engine/run_views.py",
                                                "config_with_overrides"),
        "phase3_overrides.from_config": ("engine/views/flowcharts.py", "from_config"),
        "export_guard.assert_exportable": ("analyzer.py", "assert_exportable"),
        "export_guard.stamp_pipeline_derivation": ("engine/incremental/store.py",
                                                   "stamp_pipeline_derivation"),
        "cascade.enqueue": ("engine/review/override_service.py", "_cascade.enqueue"),
        "render_queue.enqueue": ("engine/review/override_service.py", "render_queue.enqueue"),
    }

    @pytest.mark.parametrize("what", sorted(WIRED))
    def test_it_is_called_from_the_pipeline(self, what):
        path, needle = self.WIRED[what]
        assert needle in _src(path), "%s has no caller in %s" % (what, path)

    def test_the_unwired_pieces_are_named(self):
        """`render_queue.run_pending` and the regeneration-queue consumer have no scheduled
        caller yet. That is recorded in the docs rather than left for someone to discover, and
        this test fails if one quietly acquires one -- at which point the docs need updating."""
        callers = _src("engine/incremental/engine.py") + _src("engine/run_views.py") + \
            _src("analyzer.py")
        assert "run_pending(" not in callers, (
            "run_pending now has a pipeline caller -- update the 'not yet implemented' lists in "
            "REVIEW_UPDATE_API_SPEC and the handover")
        assert "cascade.pending(" not in callers, (
            "the regeneration queue now has a consumer -- update the docs the same way")
