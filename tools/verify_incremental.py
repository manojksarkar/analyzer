"""Two-version incremental e2e — the gate for the version-identity work (doc 08).

Runs the REAL incremental engine end-to-end on a throwaway C++ git fixture — its own SQLite
database, no LLM, views off — across two commits, and asserts the UNCHANGED function is reused
and the CHANGED one regenerated. `run_incremental`'s dir/identity plumbing has no unit coverage,
so this is the safety net: the reused/regenerated numbers must not move.

It was DB-LESS until doc 10 step 11b, exercising the file store. That stopped being production's
path at step 9, and the first run against a database turned up a bug the file path had hidden
for the life of the feature (an empty `globalVariables` reading as missing).

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
    tmp = tempfile.mkdtemp(prefix="verify-inc-")
    # This gate runs against a THROWAWAY SQLITE DATABASE, not the file path.
    #
    # It used to force a DB-less FileStore path. Since the database became the
    # default (doc 10 step 9) that tested a path production no longer takes — a gate that
    # passes on code nobody runs is worse than no gate. Pointing it at its own SQLite file
    # keeps the isolation that mattered (never touching a real Postgres) while exercising the
    # real path.
    #
    # DATABASE_URL is the one mechanism that reaches the analyzer SUBPROCESSES without editing
    # the developer's config.local.json. That is test isolation, not run configuration — no
    # product behaviour is selected by an environment variable here.
    _db_path = os.path.join(tmp, "verify-inc.db").replace("\\", "/")
    os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"
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

    # Schema + the rows the engine does not own. PgStore never creates a `versions` row (the
    # API reserves it at job start), so a run against an unreserved version falls back to files
    # — which is exactly what this gate must NOT silently do.
    import datetime as _dt
    import sqlalchemy as _sa
    from api.db.postgres import schema as _s
    from core.db import get_engine as _get_engine
    _eng = _get_engine()
    _s.metadata.create_all(_eng)
    _now = _dt.datetime.now(_dt.timezone.utc)
    with _eng.begin() as _cx:
        _cx.execute(_sa.insert(_s.projects), {"id": PID, "name": "verify-inc", "repo_url": "",
                                              "default_branch": "main", "created_at": _now})

    def _reserve(vid, sha):
        """What the API does before starting a job."""
        with _eng.begin() as cx:
            cx.execute(_sa.insert(_s.versions), {
                "id": vid, "project_id": PID, "version": vid, "commit_sha": sha,
                "branch": "main", "status": "in_review", "created_at": _now})

    from incremental.generate import generate_full
    from incremental.engine import generate_incremental

    _reserve("ver1", sha1)
    print(f"\n=== run 1 (FULL) commit {sha1[:10]} ===")
    m1 = generate_full(PID, "main", sha1, {"type": "project"},
                       workspaces_root=ws_root, no_llm=True, repo_url=repo, version_id="ver1")
    print(f"   version {m1.get('versionId')}: {m1.get('decision')} / {m1.get('status')}")

    # No versions.json to write: in database mode `list_versions` reads the versions table, and
    # only rows whose pipeline_status reached a terminal state qualify as baselines — which the
    # full run above has just set. That is itself part of what this gate now checks; the 0%-reuse
    # bug was exactly a version never reaching a terminal state.

    # commit 2 — change `add` only
    sha2 = _commit_file(repo, CPP_V2, "v2")
    _reserve("ver2", sha2)
    print(f"\n=== run 2 (INCREMENTAL) commit {sha2[:10]} ===")
    m2 = generate_incremental(PID, "main", sha2, scope={"type": "project"},
                              workspaces_root=ws_root, no_llm=True, repo_url=repo, version_id="ver2")

    decision = m2.get("decision")
    reused = int(m2.get("reused") or 0)
    regen = int(m2.get("regenerated") or 0)
    print(f"\nresult: decision={decision}  reused={reused}  regenerated={regen}")

    # The gate for the version-identity work: `incremental` proves list_versions + baseline
    # selection resolved the identity; reused>=1 proves the baseline model was READ back through
    # the store (carry-forward); regenerated>=1 proves the changed function was detected against
    # that baseline. All three are the exact store/identity paths the ArtifactStore wiring owns.
    ok = decision == "incremental" and reused >= 1 and regen >= 1
    if ok:
        print("\nOK — incremental: baseline resolved + its model reused, changed fn regenerated.")
    else:
        print("\nFAILED — expected an incremental run with reused>=1 and regenerated>=1 "
              "(baseline identity resolved + model read + change detected).")
    print(f"(workspace kept for inspection: {tmp})" if not ok else "")
    if ok:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
