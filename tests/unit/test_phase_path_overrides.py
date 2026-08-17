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
def test_prune_is_a_real_parameter_not_a_free_name(name):
    """The call site referenced `prune_model_files_after` before either signature declared it,
    so every run died with NameError at the very last step — after producing its documents.
    Caught by verify_incremental, not by the unit suite, because nothing here calls the
    orchestrators end to end."""
    src = _orch(name)
    assert "prune_model_files_after: bool = False" in src, \
        f"{name}: the prune flag is used but never declared as a parameter"
    assert "enabled=prune_model_files_after" in src, f"{name}: the flag is declared but unused"


@pytest.mark.parametrize("name", ["generate.py", "engine.py"])
def test_prune_flag_is_exposed_on_the_cli(name):
    assert '"--prune-model-files"' in _orch(name)


def test_incremental_forwards_prune_to_the_full_fallback():
    """generate_incremental falls back to a full generation with no usable baseline; the flag
    must survive that hand-off or the first version of a project never prunes."""
    src = _orch("engine.py")
    assert "prune_model_files_after=prune_model_files_after" in src
