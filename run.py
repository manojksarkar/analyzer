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

from utils import log, timed, load_config

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

PHASES = [
    ("Phase 1: Parse C++ source", "parser.py", [resolved]),
    ("Phase 2: Derive model", "model_deriver.py", []),
    ("Phase 3: Generate views", "run_views.py", []),
    ("Phase 4: Export to DOCX", "docx_exporter.py", []),
]


def _run_pipeline() -> float:
    """Run all phases once with current config (including any config.local.json)."""
    total = 0.0
    for i, (label, script, phase_args) in enumerate(PHASES, 1):
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
            for idx, g in enumerate(group_names, 1):
                log(f"Group {idx}/{len(group_names)}: {g}", component="run")
                # Write a minimal config.local.json that selects this group (new key).
                with open(local_cfg_path, "w", encoding="utf-8") as f:
                    json.dump({"selectedGroup": g}, f, indent=2)
                total_time += _run_pipeline()
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
