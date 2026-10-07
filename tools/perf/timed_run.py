"""One timed pipeline run on a scratch copy of SampleCppProject, for the speed study.

    python tools/perf/timed_run.py --label base --version-id v1 [--scope layer:Layer1] [--no-llm]
        [--env KEY=VALUE ...]

Needs DATABASE_URL (a throwaway database, `analyzer.py setup` run on it) and an LLM the config
points at (tools/perf/llm_standin.py). Writes <out>/<label>.log (the run's output) and prints, and
appends to <out>/runs.jsonl: wall time, each phase's seconds, and LLM calls / seconds by stage.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAMPLE = os.path.join(ROOT, "SampleCppProject")

PHASE = re.compile(r"Phase (\d): ([^—\n]+?) — ([\d.]+)s")
STAGE = re.compile(r"^\s+([a-z_.]+(?:\.[a-z_]+)*)\s+(\d+)\s+(\d+)\s+([\d.]+)s\s+([\d.]+)s\s+([\d.]+)s\s+([\d.]+)s", re.M)


def scratch_repo(path: str) -> str:
    """SampleCppProject as a git repo of its own (as tests/conftest.py builds it)."""
    if os.path.isdir(path):
        def force(func, p, _exc):                    # git's pack files are read-only on Windows
            os.chmod(p, 0o700)
            func(p)
        shutil.rmtree(path, onexc=force)
    shutil.copytree(SAMPLE, path)
    q = dict(check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["git", "-C", path, "init", "-q"], **q)
    subprocess.run(["git", "-C", path, "symbolic-ref", "HEAD", "refs/heads/main"], **q)
    subprocess.run(["git", "-C", path, "add", "-A"], **q)
    subprocess.run(["git", "-C", path, "-c", "user.email=perf@test", "-c", "user.name=perf", "commit", "-q", "-m", "perf"], **q)
    return subprocess.run(["git", "-C", path, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def summarize(text: str) -> dict:
    phases: dict = {}
    for n, name, secs in PHASE.findall(text):
        phases[f"{n} {name.strip()}"] = phases.get(f"{n} {name.strip()}", 0.0) + float(secs)
    stages: dict = {}
    for m in STAGE.finditer(text):
        name, calls, fails, avg, mx, http, throttle = m.groups()
        if name == "stage":
            continue
        s = stages.setdefault(name, {"calls": 0, "fail": 0, "http": 0.0, "throttle": 0.0})
        s["calls"] += int(calls); s["fail"] += int(fails); s["http"] += float(http); s["throttle"] += float(throttle)
    return {"phases": phases, "llm": stages}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--label", required=True)
    p.add_argument("--project-id", default="perf")
    p.add_argument("--version-id", default="v1")
    p.add_argument("--scope", default="")
    p.add_argument("--no-llm", action="store_true")
    p.add_argument("--repo", default="C:/tmp/perf-sample")
    p.add_argument("--out", default="C:/tmp/perf-out")
    p.add_argument("--env", action="append", default=[], help="KEY=VALUE for the run")
    p.add_argument("--reuse-repo", action="store_true", help="keep the scratch repo (same commit)")
    p.add_argument("--extra", action="append", default=[], help="one more argument for generate")
    a = p.parse_args()
    os.makedirs(a.out, exist_ok=True)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    for kv in a.env:
        k, _, v = kv.partition("=")
        env[k] = v
    if a.reuse_repo and os.path.isdir(a.repo):
        sha = subprocess.run(["git", "-C", a.repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    else:
        sha = scratch_repo(a.repo)
    py = sys.executable
    an = os.path.join(ROOT, "analyzer.py")
    log_path = os.path.join(a.out, f"{a.label}.log")
    with open(log_path, "w", encoding="utf-8") as log:
        subprocess.run([py, an, "onboard", "--project-id", a.project_id, "--source", a.repo, "--use-defaults",
                        "--branch", "main", "--version-id", a.version_id, "--commit", sha, "--force-config"],
                       cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        cmd = [py, an, "generate", "--project-id", a.project_id, "--version-id", a.version_id, "--branch", "main",
               "--commit", sha, "--doc-type", "all", "--full"]
        if a.scope:
            cmd += ["--scope", a.scope]
        if a.no_llm:
            cmd += ["--no-llm"]
        cmd += a.extra
        t0 = time.monotonic()
        r = subprocess.run(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        wall = time.monotonic() - t0
    text = open(log_path, encoding="utf-8", errors="replace").read()
    res = {"label": a.label, "exit": r.returncode, "wall": round(wall, 1), **summarize(text)}
    with open(os.path.join(a.out, "runs.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(res) + "\n")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
