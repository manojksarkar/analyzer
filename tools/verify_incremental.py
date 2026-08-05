"""DB-less two-version incremental e2e — the gate for the version-identity work (doc 08).

Runs the REAL incremental engine end-to-end on a throwaway C++ git fixture — no database, no
LLM, views off — across two commits, and asserts the UNCHANGED function is reused and the
CHANGED one regenerated. `run_incremental`'s dir/identity plumbing has no unit coverage, so this
is the safety net: run it BEFORE and AFTER wiring the ArtifactStore into the engine — the
reused/regenerated numbers must not move.

    python tools/verify_incremental.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, "engine")]

PID = "verify-inc"

# `multiply` is defined first so `add` can call it. V2 changes `add` only (it now calls
# multiply — a real call-graph change), so `multiply` is untouched and must be reused.
CPP_V1 = """int multiply(int a, int b) {
    int result = a * b;
    return result;
}

int add(int a, int b) {
    return a + b;
}
"""
CPP_V2 = """int multiply(int a, int b) {
    int result = a * b;
    return result;
}

int add(int a, int b) {
    return multiply(a, 1) + b;
}
"""


def _git(repo: str, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True,
                          text=True, env=env).stdout.strip()


def _commit_file(repo: str, body: str, msg: str) -> str:
    src = os.path.join(repo, "src")
    os.makedirs(src, exist_ok=True)
    with open(os.path.join(src, "calc.cpp"), "w", encoding="utf-8") as fh:
        fh.write(body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


def _write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    os.environ.pop("DATABASE_URL", None)          # this gate is DB-less (FileStore path)

    tmp = tempfile.mkdtemp(prefix="verify-inc-")
    # Isolate generated data (model/output/logs/cache/api-db-data) to tmp so the pipeline never
    # touches the repo's own model/output. The env var is what the analyzer SUBPROCESS inherits;
    # set_data_root also updates this process (and clears the paths cache). Code stays at the
    # real root, so the engine + config are still found.
    os.environ["ANALYZER_DATA_ROOT"] = tmp
    from core.paths import set_data_root
    set_data_root(tmp)
    ws_root = os.path.join(tmp, "workspaces")
    os.makedirs(os.path.join(ws_root, PID), exist_ok=True)   # Workspace needs the project dir

    # Config: point the parser at the fixture (src/), and keep only interfaceTables — it is
    # pure-python and its output is what the DOCX exporter requires; unitDiagrams/flowcharts/
    # componentStaticDiagram need mermaid/Graphviz/node, so they're off. LLM off (also --no-llm).
    from utils import load_config
    cfg = load_config(os.path.join(_ROOT, "engine"))
    cfg["views"] = {"interfaceTables": True, "unitDiagrams": False, "flowcharts": False,
                    "behaviourDiagram": False, "componentStaticDiagram": False}
    cfg["layers"] = {"App": {"path": ".", "groups": {"Core": {"Calc": "src"}}}}
    cfg["llm"] = {**cfg.get("llm", {}), "descriptions": False, "behaviourNames": False,
                  "summarize": False}
    _write_json(os.path.join(ws_root, PID, "config.json"), cfg)
    _write_json(os.path.join(tmp, "api", "db", "data", "projects.json"),
                [{"id": PID, "name": "verify-inc", "repo_url": "", "default_branch": "main"}])

    # fixture repo — commit 1 (baseline)
    repo = os.path.join(tmp, "repo")
    os.makedirs(repo, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")   # branch = main (git-version-agnostic)
    sha1 = _commit_file(repo, CPP_V1, "v1")

    from incremental.generate import generate_full
    from incremental.engine import generate_incremental

    print(f"\n=== run 1 (FULL) commit {sha1[:10]} ===")
    m1 = generate_full(PID, "main", sha1, {"type": "project"},
                       workspaces_root=ws_root, no_llm=True, repo_url=repo)
    print(f"   version {m1.get('versionId')}: {m1.get('decision')} / {m1.get('status')}")

    # record version 1 so list_versions (JSON mode) offers it as the baseline for run 2
    _write_json(os.path.join(tmp, "api", "db", "data", "versions.json"),
                [{"id": "ver1", "project_id": PID, "commit_sha": sha1, "branch": "main"}])

    # commit 2 — change `add` only
    sha2 = _commit_file(repo, CPP_V2, "v2")
    print(f"\n=== run 2 (INCREMENTAL) commit {sha2[:10]} ===")
    m2 = generate_incremental(PID, "main", sha2, scope={"type": "project"},
                              workspaces_root=ws_root, no_llm=True, repo_url=repo)

    decision = m2.get("decision")
    reused = int(m2.get("reused") or 0)
    regen = int(m2.get("regenerated") or 0)
    print(f"\nresult: decision={decision}  reused={reused}  regenerated={regen}")

    # The gate for the version-identity work: `incremental` proves list_versions + baseline
    # selection resolved the identity, and reused>=1 proves the baseline model was READ back
    # (carry-forward) — exactly the store paths the ArtifactStore wiring will change. Any
    # regeneration is a bonus signal (change detection), not what this gate guards.
    ok = decision == "incremental" and reused >= 1
    if ok:
        print("\nOK — incremental run: baseline resolved and its model reused (>=1).")
    else:
        print("\nFAILED — expected an incremental run with reused>=1 "
              "(baseline identity resolved + model read).")
    print(f"(workspace kept for inspection: {tmp})" if not ok else "")
    if ok:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
