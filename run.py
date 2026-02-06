#!/usr/bin/env python3
"""
Entry point: parse C++ project → metadata → generate outputs
Usage: python run.py <project_path>
Example: python run.py test_cpp_project
"""
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

# Phase 1: Parse → metadata
print("=== Phase 1: Parser -> metadata ===")
r1 = subprocess.run([sys.executable, os.path.join("src", "parser.py"), resolved], cwd=SCRIPT_DIR)
if r1.returncode != 0:
    sys.exit(r1.returncode)

# Phase 2: metadata → outputs
print("\n=== Phase 2: metadata -> outputs ===")
r2 = subprocess.run([sys.executable, os.path.join("src", "generator.py")], cwd=SCRIPT_DIR)
if r2.returncode != 0:
    sys.exit(r2.returncode)

print("\nDone.")
