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
  --verbose            Enable DEBUG logs (cache hits, budgets, few-shot picks)
  --quiet              Only log WARNINGs and above
  --trace-prompts      Print full LLM prompts (system + user) to stdout.
                       WARNING: large runs can emit tens of MB of prompt text.

Examples:
  python run.py test_cpp_project
  python run.py --clean test_cpp_project
  python run.py --no-llm-summarize test_cpp_project
  python run.py --from-phase 3 test_cpp_project
  python run.py --selected-group MyGroup test_cpp_project
  python run.py --filter-mode single_per_function test_cpp_project
"""
import os
import shutil
import sys

# Force UTF-8 on stdout/stderr so non-ASCII source text (e.g. Korean/Chinese
# identifiers or comments) doesn't crash prints with UnicodeEncodeError on
# Windows (where the default code page is cp1252). Propagate via
# PYTHONIOENCODING so every Python subprocess we spawn inherits the same
# encoding. errors='replace' keeps the run alive even if one character is
# un-representable in the target encoding.
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)
sys.path.insert(0, os.path.join(SCRIPT_DIR, "src"))

# Bring up logging early so every subsequent log() call (and every subprocess
# this script spawns inheriting LOG_LEVEL) gets the same handlers.
from core.logging_setup import configure_logging
_quiet_flag = "--quiet" in sys.argv
_verbose_flag = "--verbose" in sys.argv
_trace_prompts_flag = "--trace-prompts" in sys.argv
if _verbose_flag:
    os.environ.setdefault("LOG_LEVEL", "DEBUG")
elif _quiet_flag:
    os.environ.setdefault("LOG_LEVEL", "WARNING")
if _trace_prompts_flag:
    os.environ.setdefault("LLM_TRACE_PROMPTS", "1")
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
filter_mode_arg    = None
raw_args           = []

i = 1
while i < len(sys.argv):
    a = sys.argv[i]
    if a == "--clean":
        clean_all = True
    elif a in ("--quiet", "--verbose", "--trace-prompts"):
        pass  # consumed at top of file (configure_logging / env vars)
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

def _resolve_group_name(groups: dict, requested: str | None) -> str | None:
    """Resolve requested group name against config.modulesGroups, case-insensitive."""
    if not requested:
        return None
    if not isinstance(groups, dict) or not groups:
        return None
    if requested in groups:
        return requested
    req_key = requested.casefold()
    for k in groups.keys():
        if isinstance(k, str) and k.casefold() == req_key:
            return k
    return None

if len(raw_args) < 1:
    print("Usage: python run.py [--clean] [--use-model|--skip-model] [--selected-group <name>]")
    print("                     [--no-llm-summarize] [--from-phase N] [--quiet|--verbose]")
    print("                     [--trace-prompts] [--filter-mode MODE] <project_path>")
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
_llvm = (cfg.get("clang") or {}).get("llvmLibPath", "")
if _llvm and os.path.isfile(_llvm):
    os.environ["LIBCLANG_PATH"] = _llvm

# Resolve and display the LLM config up-front so the user sees exactly which
# provider, endpoint, model, and token budget the run will use. Fails loud
# (LlmConfigError) if any required field is missing or invalid — better to
# stop here than half-way through a long run.
from core.config import load_llm_config, format_llm_config_banner, LlmConfigError
try:
    _resolved_llm_cfg = load_llm_config(cfg)
    for _line in format_llm_config_banner(_resolved_llm_cfg).splitlines():
        log(_line, component="run")
except LlmConfigError as e:
    log(f"Invalid LLM config: {e}", component="run", err=True)
    sys.exit(2)

try:
    plans = plan_runs(
        cfg,
        project_path=resolved,
        selected_group=selected_group_arg,
        use_model=use_model,
        no_llm_summarize=no_llm_summarize,
        from_phase=from_phase,
        filter_mode=filter_mode_arg
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
