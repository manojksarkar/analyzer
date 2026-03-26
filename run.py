#!/usr/bin/env python3
"""Entry: python run.py [--clean] <project_path>"""
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

raw_args = [a for a in sys.argv[1:] if a not in ("--clean", "--all-groups")]
clean_all = "--clean" in sys.argv[1:]
run_all_groups = "--all-groups" in sys.argv[1:]

if len(raw_args) < 1:
    print("Usage: python run.py [--clean] [--all-groups] <project_path>")
    print("Example: python run.py test_cpp_project")
    print("         python run.py --clean test_cpp_project")
    print("         python run.py --all-groups test_cpp_project")
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

def _run_pipeline() -> float:
    """Run all phases once with current config (including any config.local.json)."""
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

config_dir = os.path.join(SCRIPT_DIR, "config")
local_cfg_path = os.path.join(config_dir, "config.local.json")
original_local_bytes: bytes | None = None


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
            total_time += _run_pipeline()
        else:
            os.makedirs(config_dir, exist_ok=True)
            # Build the full model once (no selectedGroup).
            with open(local_cfg_path, "w", encoding="utf-8") as f:
                json.dump({}, f, indent=2)
            log("Building full model once (all modules).", component="run")
            total_time += _run_phases(PHASES_BUILD_MODEL)

            # Then export per group (logical filtering happens in Phase 3/4 via config.selectedGroup).
            for idx, g in enumerate(group_names, 1):
                log(f"Group {idx}/{len(group_names)}: {g}", component="run")
                with open(local_cfg_path, "w", encoding="utf-8") as f:
                    json.dump({"selectedGroup": g}, f, indent=2)
                group_out = os.path.join(SCRIPT_DIR, "output", g)
                os.makedirs(group_out, exist_ok=True)

                total_time += _run_phases(
                    [
                        ("Phase 3: Generate views", "run_views.py", ["--output-dir", group_out]),
                        (
                            "Phase 4: Export to DOCX",
                            "docx_exporter.py",
                            [
                                os.path.join(group_out, "interface_tables.json"),
                                os.path.join(group_out, f"software_detailed_design_{g}.docx"),
                            ],
                        ),
                    ]
                )
    finally:
        # Restore previous config.local.json (if any), or remove our temporary one.
        if original_local_bytes is not None:
            with open(local_cfg_path, "wb") as f:
                f.write(original_local_bytes)
        elif os.path.isfile(local_cfg_path):
            os.remove(local_cfg_path)
else:
    total_time += _run_pipeline()

print(flush=True)
log(f"Done. Total: {total_time:.2f}s", component="run")
