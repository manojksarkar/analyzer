"""Every phase must apply --model-root/--output-root BEFORE it snapshots paths().

This bit twice. The phases are separate processes that each resolve `paths()` themselves, and
three of the four cache it in MODULE-LEVEL constants at import. Applying the overrides later —
inside main() — leaves every constant derived from that snapshot pointing at the DEFAULT
directories, while the run is using per-version ones.

It is not cosmetic and it does not raise. run_views hands `model_dir` to the views, which look
there for incremental_plan.json; with a stale value the plan is never found, carry-forward
never runs, and an incremental run silently emits ONLY the diagrams it regenerated. The
document then ships with most of its images missing — which is exactly how it was found, on a
real two-commit run, not here.

Source-level assertions on purpose: the failure is an import-time ordering property, which a
behavioural test in this process cannot observe.
"""
import os

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Every script group_planner can dispatch as a phase.
PHASE_SCRIPTS = ["parser.py", "model_deriver.py", "run_views.py", "docx_exporter.py"]


def _source(name):
    with open(os.path.join(ROOT, "engine", name), encoding="utf-8") as fh:
        return fh.read()


@pytest.mark.parametrize("name", PHASE_SCRIPTS)
def test_phase_applies_overrides_before_snapshotting_paths(name):
    src = _source(name)
    assert ("apply_cli_run_context" in src or "apply_cli_path_overrides" in src),         f"{name} ignores the run context (--model-root/--output-root/--version-id)"

    snapshots = [i for i in (src.find("_p = _paths()"), src.find("_p = paths()")) if i >= 0]
    if not snapshots:
        return                       # resolves paths() lazily; ordering cannot bite
    applied = min(i for i in (src.find("apply_cli_run_context"),
                              src.find("apply_cli_path_overrides")) if i >= 0)
    assert applied < min(snapshots), (
        f"{name}: paths() is snapshotted into module constants BEFORE the CLI overrides are "
        f"applied, so those constants point at the default directories for the whole run")


@pytest.mark.parametrize("name", PHASE_SCRIPTS)
def test_phase_strips_the_flags_from_argv(name):
    """docx_exporter parses POSITIONAL arguments, so an unconsumed flag becomes a file path."""
    src = _source(name)
    assert any(f"sys.argv = {fn}(sys.argv)" in src for fn in
               ("_apply_run_context", "apply_cli_run_context",
                "_apply_path_flags", "apply_cli_path_overrides")), \
        f"{name}: the result must be assigned back so the flags are removed from argv"


def test_orchestrator_forwards_both_roots():
    """The flags only help if the phase actually receives them.

    --output-root was originally omitted, on the reasoning that group_planner already bakes an
    absolute --output-dir into each phase. True for WRITING, but the incremental views also
    need the run's output ROOT to locate the same slot inside the baseline version.
    """
    with open(os.path.join(ROOT, "engine", "core", "orchestration.py"), encoding="utf-8") as fh:
        src = fh.read()
    assert '"--model-root", _OVERRIDE_MODEL_DIR' in src
    assert '"--output-root", _OVERRIDE_OUTPUT_DIR' in src


# ---------------------------------------------------------------------------
# doc 09 C11c — the prune flag must reach both orchestrators
# ---------------------------------------------------------------------------

def _orch(name):
    with open(os.path.join(ROOT, "engine", "incremental", name), encoding="utf-8") as fh:
        return fh.read()


@pytest.mark.parametrize("name", ["generate.py", "engine.py"])
def test_the_transition_scaffolding_is_gone(name):
    """`--prune-model-files` deleted model/*.json after a run; `--model-from-db`
    re-materialized the stored model between Phase 1 and Phase 2. Both existed to manage a
    period when the files and the database were BOTH live. Step 11b ended that period: the
    files are not written, so there is nothing to prune and nothing to re-materialize.

    Asserted rather than merely deleted because a flag that no longer does anything is worse
    than none — an operator passing it would reasonably expect an effect.
    """
    # Comments stripped: both files explain in prose what the flags used to do and why they
    # went, which is worth keeping and is not a live reference.
    code = "".join(ln for ln in _orch(name).splitlines(keepends=True)
                   if not ln.lstrip().startswith("#"))
    for gone in ("--prune-model-files", "prune_model_files_after", "--model-from-db",
                 "model_from_db"):
        assert gone not in code, f"{name}: {gone} outlived the transition it managed"
