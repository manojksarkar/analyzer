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
        "export_guard.assert_exportable": ("engine/run.py", "assert_exportable"),
        "export_guard.assert_exportable (cli, fails fast)": ("analyzer.py", "assert_exportable"),
        "export_guard.staleness (api re-export)": ("api/services/pipeline_runner.py",
                                                   "staleness"),
        "export_guard.stamp_pipeline_derivation": ("engine/incremental/store.py",
                                                   "stamp_pipeline_derivation"),
        "cascade.enqueue": ("engine/review/override_service.py", "_cascade.enqueue"),
        "render_queue.enqueue": ("engine/review/override_service.py", "render_queue.enqueue"),
        "render_queue.run_pending": ("engine/incremental/store.py", "run_pending"),
        "cascade.blank_queued_text": ("engine/model_deriver.py", "blank_queued_text"),
        "cascade.clear_behaviour_entries": ("engine/run_views.py", "clear_behaviour_entries"),
    }

    @pytest.mark.parametrize("what", sorted(WIRED))
    def test_it_is_called_from_the_pipeline(self, what):
        path, needle = self.WIRED[what]
        assert needle in _src(path), "%s has no caller in %s" % (what, path)

    def test_nothing_in_the_feature_is_left_without_a_caller(self):
        """Every module under `engine/review/` must be reachable from a run, the API or the CLI.

        A module nobody calls is the failure this whole class guards: all its tests pass and it
        does nothing. When a new one is added it belongs in WIRED above, beside the place that
        calls it -- or it does not belong in the tree yet.
        """
        review_dir = os.path.join(PROJECT_ROOT, "engine", "review")
        modules = {f[:-3] for f in os.listdir(review_dir)
                   if f.endswith(".py") and not f.startswith("__")}
        callers = "".join(_src(p) for p in (
            "engine/incremental/engine.py", "engine/incremental/store.py",
            "engine/run_views.py", "engine/model_deriver.py", "analyzer.py",
            "engine/run.py", "api/routes/text_overrides.py",
            "api/services/pipeline_runner.py", "engine/views/flowcharts.py",
            "engine/views/behaviour_diagram.py"))
        # Reached THROUGH the others rather than directly. Naming them says that is deliberate
        # rather than an omission nobody noticed.
        indirect = {"slot", "resolver", "redraw", "rerender", "derive", "export_guard",
                    "phase3_overrides"}
        missing = sorted(m for m in modules - indirect if m not in callers)
        assert not missing, (
            "these review modules have no caller in the pipeline, the API or the CLI: %s. "
            "Either wire them in, or add them to `indirect` with the reason."
            % ", ".join(missing))


class TestTheExportGuardCoversBothFrontDoors:
    """`analyzer.py` is not the only way a Phase-4-only export starts.

    The guard used to live in `analyzer.py` alone. The API's re-export service spawns
    `engine/run.py --from-phase 4` directly and never went near it, so the terminal refused a
    stale export and the UI -- where reviewers actually work -- produced one silently.

    The failure that reaches a reader is not "slightly old text". Correcting a node label on a
    host with no output tree patches the text in the database immediately and leaves the PNG
    owed; exporting then yields a document whose sentence says one thing and whose picture beside
    it says another.

    `_restore_output_from_db` was already placed in `run.py` for exactly this reason. This is the
    same lesson applied to its other half.
    """

    RUN = "engine/run.py"
    CALL = re.compile(r"^[ \t]*_refuse_stale_export\(from_phase, force_export\)", re.M)

    def test_run_py_asks_before_exporting(self):
        assert self.CALL.search(_src(self.RUN)), (
            "engine/run.py no longer checks, so any caller that spawns it directly -- the API's "
            "re-export among them -- can ship a stale document with no warning")

    def test_the_check_can_fail(self):
        """The matcher must not also match the definition. That mistake has been made twice in
        this feature; it makes the test pass however the code behaves."""
        assert not self.CALL.search(
            "def _refuse_stale_export(from_phase, force_export) -> None:")
        assert self.CALL.search("    _refuse_stale_export(from_phase, force_export)")

    def test_it_runs_beside_the_restore_it_belongs_with(self):
        """Both answer "is what we are about to export actually current?" -- the restore for the
        text, the guard for everything the restore cannot reach."""
        src = _src(self.RUN)
        assert src.index("_restore_output_from_db(from_phase)") < self.CALL.search(src).start()

    def test_it_runs_before_any_phase(self):
        """Refusing after Phase 4 has produced the document would be theatre."""
        src = _src(self.RUN)
        assert self.CALL.search(src).start() < src.index("runner = PhaseRunner(")

    def test_only_phase_4_is_gated(self):
        """A run that includes Phase 3 is applying the corrections on its way through -- and the
        derivation is stamped when output is CAPTURED, after Phase 4, so at Phase 4 the stamps
        are still the previous run's. Checking there would refuse the very run that fixes it."""
        src = _src(self.RUN)
        body = src[src.index("def _refuse_stale_export("):]
        assert "if from_phase < 4 or force:" in body

    def test_force_travels_from_the_cli_to_the_backstop(self):
        """Otherwise `--force` would be honoured by the front door and then refused by run.py --
        the user insists, and the tool says no anyway."""
        assert '--force-export' in _src("analyzer.py")

    def test_the_flag_is_on_run_pys_allowlist(self):
        """run.py rejects anything not on it, so an unlisted flag fails the export outright."""
        src = _src(self.RUN)
        assert '"--force-export"' in src[:src.index("clean_all")], (
            "--force-export must be in the KNOWN-flags allowlist near the top of run.py")


class TestTheApiRederivesInsteadOfRefusing:
    """A reviewer pressing "re-export" should not have to know what a phase is.

    The guard's own message names re-deriving as the remedy (`--from-phase 3`). On the API path
    that remedy is applied rather than recommended: the job runs Phase 3 first, which rebuilds
    the view rows with the corrections applied and draws the pictures that were owed.
    """

    SRC = "api/services/pipeline_runner.py"

    def test_the_re_export_asks_first(self):
        src = _src(self.SRC)
        assert "_reexport_from_phase(" in src

    def test_the_answer_is_what_is_actually_run(self):
        """A decision nobody acts on is worse than no decision -- it reads as covered."""
        src = _src(self.SRC)
        assert re.search(r"^[ \t]*from_phase = _reexport_from_phase\(", src, re.M)
        assert "_build_cmd(job, cdir, config_path, from_phase=from_phase" in src
        assert "from_phase=4" not in src, (
            "the re-export still hard-codes phase 4 somewhere, so the check is decoration")

    def test_it_falls_back_to_4_when_it_cannot_ask(self):
        """No version, no database, or the guard itself failing. An unavailable guard must not
        silently change what the pipeline does."""
        src = _src(self.SRC)
        body = src[src.index("def _reexport_from_phase("):src.index("def _do_reexport(")]
        assert body.count("return 4") >= 3 and "except Exception" in body
