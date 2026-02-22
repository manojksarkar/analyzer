#!/usr/bin/env python3
"""Entry: python run.py [--clean] <project_path>"""
import os
import shutil
import sys
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)

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
            print(f"Removed {d}/")

project_path = args[0]
resolved = os.path.abspath(project_path) if os.path.isabs(project_path) else os.path.join(SCRIPT_DIR, project_path)
if not os.path.isdir(resolved):
    print(f"Error: Project path not found: {resolved}")
    sys.exit(1)

PHASES = [
    ("Phase 1: Parse C++ source", "parser.py", [resolved]),
    ("Phase 2: Derive model", "model_deriver.py", []),
    ("Phase 3: Generate views", "run_views.py", []),
    ("Phase 4: Export to DOCX", "docx_exporter.py", []),
]
for i, (label, script, args) in enumerate(PHASES, 1):
    print(f"\n=== {label} ===" if i > 1 else f"=== {label} ===", flush=True)
    r = subprocess.run([sys.executable, os.path.join("src", script)] + args, cwd=SCRIPT_DIR)
    if r.returncode != 0:
        sys.exit(r.returncode)
print("\nDone.", flush=True)
