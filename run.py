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
import subprocess
import time
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)
sys.path.insert(0, os.path.join(SCRIPT_DIR, "src"))

from utils import log, load_config

# ---------------------------------------------------------------------------
# Parse flags — walk argv once so every flag is handled cleanly
# ---------------------------------------------------------------------------

clean_all          = False
use_model          = False
no_llm_summarize   = False
llm_summarize_flag = False   # explicit --llm-summarize overrides config
from_phase         = 1
selected_group_arg = None
raw_args           = []   # collects non-flag arguments (project path)

i = 1
while i < len(sys.argv):
    a = sys.argv[i]
    if a in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    elif a == "--clean":
        clean_all = True
    elif a in ("--use-model", "--skip-model"):
        use_model = True
    elif a == "--no-llm-summarize":
        no_llm_summarize = True
    elif a == "--llm-summarize":
        llm_summarize_flag = True
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
    print("                     [--no-llm-summarize] [--from-phase N] <project_path>")
    print("Example: python run.py test_cpp_project")
    print("         python run.py --clean test_cpp_project")
    print("         python run.py --no-llm-summarize test_cpp_project")
    print("         python run.py --from-phase 3 test_cpp_project")
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
# Phase definitions
# PHASES_DEFAULT and deriver_flags are defined after config load (see below)
# so that llm.summarize config is respected before building the phase list.
# ---------------------------------------------------------------------------
MODEL_FILES = (
    os.path.join(SCRIPT_DIR, "model", "functions.json"),
    os.path.join(SCRIPT_DIR, "model", "globalVariables.json"),
    os.path.join(SCRIPT_DIR, "model", "units.json"),
    os.path.join(SCRIPT_DIR, "model", "modules.json"),
)


def _run_phases(phases, from_ph: int = 1) -> float:
    """Run a list of phases. Phases with index < from_ph are skipped."""
    total = 0.0
    for idx, (label, script, phase_args) in enumerate(phases, 1):
        if idx < from_ph:
            log(f"Skipped (--from-phase {from_ph})", component=label)
            continue
        print(f"\n=== {label} ===" if idx > 1 else f"=== {label} ===", flush=True)
        t0 = time.perf_counter()
        r = subprocess.run(
            [sys.executable, os.path.join("src", script)] + phase_args,
            cwd=SCRIPT_DIR,
        )
        elapsed = time.perf_counter() - t0
        total += elapsed
        log(f"{elapsed:.2f}s", component=label)
        if r.returncode != 0:
            sys.exit(r.returncode)
    return total


total_time = 0.0

cfg = load_config(SCRIPT_DIR)

# Config-driven LLM summarize toggle: llm.summarize=false behaves like --no-llm-summarize.
# --llm-summarize CLI flag overrides config; --no-llm-summarize always wins.
if not no_llm_summarize:
    if llm_summarize_flag:
        no_llm_summarize = False
    else:
        no_llm_summarize = not cfg.get("llm", {}).get("summarize", True)

deriver_flags = [] if no_llm_summarize else ["--llm-summarize"]

PHASES_DEFAULT = [
    ("Phase 1: Parse C++ source", "parser.py",        [resolved]),
    ("Phase 2: Derive model",     "model_deriver.py", deriver_flags),
    ("Phase 3: Generate views",   "run_views.py",     []),
    ("Phase 4: Export to DOCX",   "docx_exporter.py", []),
]
PHASES_BUILD_MODEL = PHASES_DEFAULT[:2]

groups_cfg = (cfg.get("modulesGroups") or {})
group_names = sorted(groups_cfg.keys()) if isinstance(groups_cfg, dict) else []
resolved_selected = _resolve_group_name(groups_cfg, selected_group_arg)
if selected_group_arg and not resolved_selected:
    log(
        f"Unknown --selected-group {selected_group_arg!r}. Valid groups: {', '.join(group_names) if group_names else '(none)'}",
        component="run",
        err=True,
    )
    sys.exit(2)
if selected_group_arg and resolved_selected and resolved_selected != selected_group_arg:
    log(f"--selected-group resolved to {resolved_selected!r} (case-insensitive match)", component="run")

if group_names and not selected_group_arg:
    # Default: export all groups when modulesGroups is configured.
    if use_model:
        missing = [p for p in MODEL_FILES if not os.path.isfile(p)]
        if missing:
            log(f"--use-model set but model files missing: {missing[0]}", component="run", err=True)
            sys.exit(2)
        log("Using existing model/ (skipping Phase 1/2).", component="run")
    else:
        log("Building full model once (all modules).", component="run")
        total_time += _run_phases(PHASES_BUILD_MODEL, from_ph=from_phase)
    for idx, g in enumerate(group_names, 1):
        log(f"Group {idx}/{len(group_names)}: {g}", component="run")
        group_out = os.path.join(SCRIPT_DIR, "output", g)
        os.makedirs(group_out, exist_ok=True)
        total_time += _run_phases(
            [
                ("Phase 3: Generate views", "run_views.py", ["--output-dir", group_out, "--selected-group", g]),
                (
                    "Phase 4: Export to DOCX",
                    "docx_exporter.py",
                    [
                        os.path.join(group_out, "interface_tables.json"),
                        os.path.join(group_out, f"software_detailed_design_{g}.docx"),
                        "--selected-group",
                        g,
                    ],
                ),
            ],
            from_ph=max(1, from_phase - 2),
        )
elif group_names and selected_group_arg:
    # Export only one group when requested.
    if use_model:
        missing = [p for p in MODEL_FILES if not os.path.isfile(p)]
        if missing:
            log(f"--use-model set but model files missing: {missing[0]}", component="run", err=True)
            sys.exit(2)
        log("Using existing model/ (skipping Phase 1/2).", component="run")
    else:
        log("Building full model once (all modules).", component="run")
        total_time += _run_phases(PHASES_BUILD_MODEL, from_ph=from_phase)
    total_time += _run_phases(
        [
            ("Phase 3: Generate views", "run_views.py", ["--selected-group", resolved_selected]),
            ("Phase 4: Export to DOCX", "docx_exporter.py", ["--selected-group", resolved_selected]),
        ],
        from_ph=max(1, from_phase - 2),
    )
else:
    # No modulesGroups configured: just run once.
    if use_model:
        missing = [p for p in MODEL_FILES if not os.path.isfile(p)]
        if missing:
            log(f"--use-model set but model files missing: {missing[0]}", component="run", err=True)
            sys.exit(2)
        total_time += _run_phases(PHASES_DEFAULT[2:], from_ph=max(1, from_phase - 2))
    else:
        total_time += _run_phases(PHASES_DEFAULT, from_ph=from_phase)

print(flush=True)
log(f"Done. Total: {total_time:.2f}s", component="run")
