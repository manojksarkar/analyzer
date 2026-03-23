#!/usr/bin/env python3
"""Entry: python run.py [options] <project_path>

Options:
  --clean              Delete output/ and model/ before running
  --all-groups         Run the full pipeline once per modulesGroup
  --no-llm-summarize   Skip LLM phase/hierarchy summarization (faster, lower quality)
  --from-phase N       Resume from phase N (1=Parse, 2=Derive, 3=Views, 4=Export)

Examples:
  python run.py test_cpp_project
  python run.py --clean test_cpp_project
  python run.py --no-llm-summarize test_cpp_project
  python run.py --from-phase 3 test_cpp_project
  python run.py --all-groups test_cpp_project
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

from utils import log, timed, load_config

# ---------------------------------------------------------------------------
# Parse flags — walk argv once so every flag is handled cleanly
# ---------------------------------------------------------------------------

clean_all       = False
run_all_groups  = False
no_llm_summarize = False
from_phase      = 1
raw_args        = []   # collects non-flag arguments (project path)

i = 1
while i < len(sys.argv):
    a = sys.argv[i]
    if a == "--clean":
        clean_all = True
    elif a == "--all-groups":
        run_all_groups = True
    elif a == "--no-llm-summarize":
        no_llm_summarize = True
    elif a == "--llm-summarize":
        # Accepted for backwards-compatibility but has no effect: summarization
        # is now ON by default. Use --no-llm-summarize to disable it.
        pass
    elif a == "--from-phase":
        i += 1
        if i >= len(sys.argv):
            log("--from-phase requires an integer argument (1–4)", component="run", err=True)
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
    print("Usage: python run.py [--clean] [--all-groups] [--no-llm-summarize] [--from-phase N] <project_path>")
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
# LLM summarization (phases + hierarchy summaries) is ON by default.
# Pass --no-llm-summarize to skip it for faster runs at lower quality.
# ---------------------------------------------------------------------------

deriver_flags = [] if no_llm_summarize else ["--llm-summarize"]

PHASES = [
    ("Phase 1: Parse C++ source", "parser.py",        [resolved]),
    ("Phase 2: Derive model",     "model_deriver.py", deriver_flags),
    ("Phase 3: Generate views",   "run_views.py",     []),
    ("Phase 4: Export to DOCX",   "docx_exporter.py", []),
]


def _run_pipeline(from_ph: int = 1) -> float:
    """Run all phases from from_ph onwards."""
    total = 0.0
    for idx, (label, script, phase_args) in enumerate(PHASES, 1):
        if idx < from_ph:
            log(f"Skipped (--from-phase {from_ph})", component=label)
            continue
        print(f"\n=== {label} ===", flush=True)
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

config_dir = os.path.join(SCRIPT_DIR, "config")
local_cfg_path = os.path.join(config_dir, "config.local.json")
original_local_bytes: bytes | None = None

if run_all_groups:
    # Preserve any existing config.local.json
    if os.path.isfile(local_cfg_path):
        with open(local_cfg_path, "rb") as f:
            original_local_bytes = f.read()

    try:
        cfg = load_config(SCRIPT_DIR)
        groups_cfg = (cfg.get("modulesGroups") or {})
        group_names = sorted(groups_cfg.keys())
        if not group_names:
            log("No modulesGroups configured; running once with default settings.", component="run")
            total_time += _run_pipeline(from_ph=from_phase)
        else:
            os.makedirs(config_dir, exist_ok=True)
            for idx, g in enumerate(group_names, 1):
                log(f"Group {idx}/{len(group_names)}: {g}", component="run")
                with open(local_cfg_path, "w", encoding="utf-8") as f:
                    json.dump({"selectedGroup": g}, f, indent=2)
                total_time += _run_pipeline(from_ph=from_phase)
    finally:
        if original_local_bytes is not None:
            with open(local_cfg_path, "wb") as f:
                f.write(original_local_bytes)
        elif os.path.isfile(local_cfg_path):
            os.remove(local_cfg_path)
else:
    total_time += _run_pipeline(from_ph=from_phase)

print(flush=True)
log(f"Done. Total: {total_time:.2f}s", component="run")
