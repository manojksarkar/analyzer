#!/usr/bin/env python3
"""Entry: python run.py <project_path>"""
import os
import sys
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)

if len(sys.argv) < 2:
    print("Usage: python run.py <project_path>")
    print("Example: python run.py test_cpp_project")
    print("         (project_path is relative to script dir or absolute)")
    sys.exit(1)

project_path = sys.argv[1]
resolved = os.path.abspath(project_path) if os.path.isabs(project_path) else os.path.join(SCRIPT_DIR, project_path)
if not os.path.isdir(resolved):
    print(f"Error: Project path not found: {resolved}")
    sys.exit(1)

# Phase 1: Parse -> model/; Phase 2: Derive & views; Phase 3: DOCX (if enabled)
print("=== Phase 1: Parse C++ source ===", flush=True)
r1 = subprocess.run([sys.executable, os.path.join("src", "parser.py"), resolved], cwd=SCRIPT_DIR)
if r1.returncode != 0:
    sys.exit(r1.returncode)

print("\n=== Phase 2: Derive model & generate views ===", flush=True)
r2 = subprocess.run([sys.executable, os.path.join("src", "generator.py")], cwd=SCRIPT_DIR)
if r2.returncode != 0:
    sys.exit(r2.returncode)

config = {}
try:
    from src.utils import load_config
    config = load_config(SCRIPT_DIR)
except Exception:
    pass
export_cfg = config.get("export", {})
if export_cfg.get("enableDocx", True):
    print("\n=== Phase 3: Export interface tables to DOCX ===", flush=True)
    r3 = subprocess.run([sys.executable, os.path.join("src", "docx_exporter.py")], cwd=SCRIPT_DIR)
    if r3.returncode != 0:
        sys.exit(r3.returncode)
else:
    print("\nPhase 3: DOCX export disabled (export.enableDocx=false)", flush=True)

print("\nDone.", flush=True)
