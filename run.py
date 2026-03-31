#!/usr/bin/env python3
"""Entry: python run.py [--clean] [--selected-group <name>] <project_path>"""
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

raw_args = [a for a in sys.argv[1:] if a not in ("--clean", "--selected-group", "--use-model", "--skip-model")]
clean_all = "--clean" in sys.argv[1:]
use_model = ("--use-model" in sys.argv[1:]) or ("--skip-model" in sys.argv[1:])
selected_group_arg = None
if "--selected-group" in sys.argv:
    i = sys.argv.index("--selected-group")
    if i + 1 < len(sys.argv):
        selected_group_arg = sys.argv[i + 1]


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
    print("Usage: python run.py [--clean] [--use-model|--skip-model] [--selected-group <name>] <project_path>")
    print("Example: python run.py test_cpp_project")
    print("         python run.py --clean test_cpp_project")
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

PHASES_DEFAULT = [
    ("Phase 1: Parse C++ source", "parser.py", [resolved]),
    ("Phase 2: Derive model", "model_deriver.py", []),
    ("Phase 3: Generate views", "run_views.py", []),
    ("Phase 4: Export to DOCX", "docx_exporter.py", []),
]
PHASES_BUILD_MODEL = PHASES_DEFAULT[:2]
MODEL_FILES = (
    os.path.join(SCRIPT_DIR, "model", "functions.json"),
    os.path.join(SCRIPT_DIR, "model", "globalVariables.json"),
    os.path.join(SCRIPT_DIR, "model", "units.json"),
    os.path.join(SCRIPT_DIR, "model", "modules.json"),
)

def _run_pipeline() -> float:
    """Run all phases once with current config."""
    total = 0.0
    for i, (label, script, phase_args) in enumerate(PHASES_DEFAULT, 1):
        print(f"\n=== {label} ===" if i > 1 else f"=== {label} ===", flush=True)
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

def _run_phases(phases) -> float:
    total = 0.0
    for i, (label, script, phase_args) in enumerate(phases, 1):
        print(f"\n=== {label} ===" if i > 1 else f"=== {label} ===", flush=True)
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

cfg = load_config(SCRIPT_DIR)
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
        total_time += _run_phases(
            [
                ("Phase 1: Parse C++ source", "parser.py", [resolved]),
                ("Phase 2: Derive model", "model_deriver.py", []),
            ],
        )
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
        total_time += _run_phases(
            [
                ("Phase 1: Parse C++ source", "parser.py", [resolved]),
                ("Phase 2: Derive model", "model_deriver.py", []),
            ],
        )
    total_time += _run_phases(
        [
            ("Phase 3: Generate views", "run_views.py", ["--selected-group", resolved_selected]),
            ("Phase 4: Export to DOCX", "docx_exporter.py", ["--selected-group", resolved_selected]),
        ],
    )
else:
    # No modulesGroups configured: just run once.
    if use_model:
        missing = [p for p in MODEL_FILES if not os.path.isfile(p)]
        if missing:
            log(f"--use-model set but model files missing: {missing[0]}", component="run", err=True)
            sys.exit(2)
        total_time += _run_phases(PHASES_DEFAULT[2:])
    else:
        total_time += _run_pipeline()

print(flush=True)
log(f"Done. Total: {total_time:.2f}s", component="run")
