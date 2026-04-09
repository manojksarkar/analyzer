#!/usr/bin/env python3
"""Entry: python run.py [options] <project_path>

Options:
  --clean              Delete output/ and model/ before running
  --selected-group <name>
                       Export only the named modulesGroup
  --use-model          Skip Phase 1/2 and reuse existing model/ files
  --skip-model         Alias of --use-model
  --no-llm-summarize   Skip LLM phase/hierarchy summarization (faster, lower quality)
  --from-phase N       Resume from phase N (1=Parse, 2=Derive, 3=Views, 4=Export)

Examples:
  python run.py test_cpp_project
  python run.py --clean test_cpp_project
  python run.py --no-llm-summarize test_cpp_project
  python run.py --from-phase 3 test_cpp_project
  python run.py --selected-group MyGroup test_cpp_project
"""
import os
import shutil
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)
sys.path.insert(0, os.path.join(SCRIPT_DIR, "src"))

# Bring up logging early so every subsequent log() call (and every subprocess
# this script spawns inheriting LOG_LEVEL) gets the same handlers.
from core.logging_setup import configure_logging
_quiet_flag = "--quiet" in sys.argv
_verbose_flag = "--verbose" in sys.argv
if _verbose_flag:
    os.environ.setdefault("LOG_LEVEL", "DEBUG")
elif _quiet_flag:
    os.environ.setdefault("LOG_LEVEL", "WARNING")
_log_path = configure_logging(project_root=SCRIPT_DIR, quiet=_quiet_flag, verbose=_verbose_flag)

from utils import log, load_config
from core import PhaseRunner, plan_runs
from core.model_io import model_file_path as _mfp, FUNCTIONS, GLOBALS, UNITS, MODULES

# ---------------------------------------------------------------------------
# Parse flags
# ---------------------------------------------------------------------------

clean_all          = False
use_model          = False
no_llm_summarize   = False
from_phase         = 1
selected_group_arg = None
raw_args           = []

i = 1
while i < len(sys.argv):
    a = sys.argv[i]
    if a == "--clean":
        clean_all = True
    elif a in ("--quiet", "--verbose"):
        pass  # consumed by configure_logging() above
    elif a in ("--use-model", "--skip-model"):
        use_model = True
    elif a == "--no-llm-summarize":
        no_llm_summarize = True
    elif a == "--llm-summarize":
        # Accepted for backwards-compatibility; summarization is ON by default.
        pass
    elif a == "--selected-group":
        i += 1
        if i >= len(sys.argv):
            log("--selected-group requires a group name", component="run", err=True)
            sys.exit(1)
        selected_group_arg = sys.argv[i]
    elif a == "--from-phase":
        i += 1
        if i >= len(sys.argv):
            log("--from-phase requires an integer argument (1-4)", component="run", err=True)
            sys.exit(1)
        try:
            from_phase = int(sys.argv[i])
            if from_phase < 1 or from_phase > 4:
                raise ValueError
        except ValueError:
            log(f"--from-phase must be 1, 2, 3, or 4 (got: {sys.argv[i]})", component="run", err=True)
            sys.exit(1)
    else:
        raw_args.append(a)
    i += 1


if len(raw_args) < 1:
    print("Usage: python run.py [--clean] [--use-model|--skip-model] [--selected-group <name>]")
    print("                     [--no-llm-summarize] [--from-phase N] [--quiet|--verbose] <project_path>")
    print("Example: python run.py test_cpp_project")
    sys.exit(1)

if clean_all:
    for d in ("output", "model"):
        path = os.path.join(SCRIPT_DIR, d)
        if os.path.isdir(path):
            shutil.rmtree(path)
            log(f"Removed {d}/", component="run")

project_path = raw_args[0]
resolved = os.path.abspath(project_path) if os.path.isabs(project_path) else os.path.join(SCRIPT_DIR, project_path)
if not os.path.isdir(resolved):
    log(f"Project path not found: {resolved}", component="run", err=True)
    sys.exit(1)

# ---------------------------------------------------------------------------
# When --use-model is set, refuse early if model files are missing.
# ---------------------------------------------------------------------------
if use_model:
    MODEL_FILES = (_mfp(FUNCTIONS), _mfp(GLOBALS), _mfp(UNITS), _mfp(MODULES))
    missing = [p for p in MODEL_FILES if not os.path.isfile(p)]
    if missing:
        log(f"--use-model set but model files missing: {missing[0]}", component="run", err=True)
        sys.exit(2)
    log("Using existing model/ (skipping Phase 1/2).", component="run")

# ---------------------------------------------------------------------------
# Plan and run
# ---------------------------------------------------------------------------
cfg = load_config(SCRIPT_DIR)

try:
    plans = plan_runs(
        cfg,
        project_path=resolved,
        selected_group=selected_group_arg,
        use_model=use_model,
        no_llm_summarize=no_llm_summarize,
        from_phase=from_phase,
    )
except ValueError as e:
    log(str(e), component="run", err=True)
    sys.exit(2)

runner = PhaseRunner(project_root=SCRIPT_DIR)
total_time = 0.0
for plan in plans:
    log(plan.label, component="run")
    total_time += runner.run(plan.phases, from_phase=plan.runner_from_phase)

print(flush=True)
log(f"Done. Total: {total_time:.2f}s", component="run")
if _log_path:
    log(f"Full log: {_log_path}", component="run")
