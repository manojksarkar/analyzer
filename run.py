#!/usr/bin/env python3
"""Entry: python run.py [--clean] <project_path>"""
import os
import shutil
import sys
import subprocess
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)
sys.path.insert(0, os.path.join(SCRIPT_DIR, "src"))

from utils import log, timed

args = [a for a in sys.argv[1:] if a != "--clean"]
clean_all = "--clean" in sys.argv[1:]

if len(args) < 1:
    print("Usage: python run.py [--clean] <project_path>")
    print("Example: python run.py test_cpp_project")
    print("         python run.py --clean test_cpp_project")
    sys.exit(1)

if clean_all:
    for d in ("output", "model"):
        path = os.path.join(SCRIPT_DIR, d)
        if os.path.isdir(path):
            shutil.rmtree(path)
            log(f"Removed {d}/", component="run")

project_path = args[0]
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
total_time = 0.0
for i, (label, script, phase_args) in enumerate(PHASES, 1):
    print(f"\n=== {label} ===" if i > 1 else f"=== {label} ===", flush=True)
    t0 = time.perf_counter()
    r = subprocess.run([sys.executable, os.path.join("src", script)] + phase_args, cwd=SCRIPT_DIR)
    elapsed = time.perf_counter() - t0
    total_time += elapsed
    log(f"{elapsed:.2f}s", component=label)
    if r.returncode != 0:
        sys.exit(r.returncode)
print(flush=True)
log(f"Done. Total: {total_time:.2f}s", component="run")
