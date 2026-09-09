#!/usr/bin/env python3
"""An incremental run must NOT rebuild every flowchart (M3.6 gate).

Flowchart generation is the largest cost in Phase 3, and reuse is what makes an incremental run
cheaper than a full one. When it silently stops working, nothing fails: the document is correct,
the reuse report still claims the carry-forward happened, and the only symptom is that the run
takes as long as a full generation. That is precisely what was reported from a real two-commit
run — "Run views 8 min" on BOTH runs.

Two causes, both of the same shape: a writer and a reader disagreeing about the backing.

  * `_apply_incremental_plan` opened `functions_arg_path` as a FILE to load the model. In
    database mode nothing writes `model/functions.json`, so the open failed and the function
    returned "no plan" — full regeneration.
  * the orchestrator wrote the plan with `write_model_file`, but installs no model repository,
    so it landed in `model/incremental_plan.json` while Phase 3 read the `incremental_plans`
    table and found nothing.

Method: two commits, one changed function. Run 2 must restrict the engine to that function and
carry the rest forward.

**Evidence comes from the run LOG, not an in-process handler** — Phase 3 is a subprocess, and an
earlier version of this check installed a logging handler that could never see it, then reported
failure while the code worked.

    python tools/verify_flowchart_reuse.py

It also checks that an incremental run leaves the SAME clean version directory a full run
does. The partial parse writes model/*.json as scratch (its output is only valid after
parse_merge), nothing removed them, and snapshot_parse_model then copied that partial model into
versions/<id>/parse/ — so a full version was clean and an incremental one was full of
incomplete JSON.

Exit 0 = the incremental run reused the baseline's flowcharts and left a clean version.
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.getcwd()
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "engine"))

PID, VID, VID2 = "fcreuse", "vfc1", "vfc2"
tmp = tempfile.mkdtemp(prefix="fcrepro-")
ws = os.path.join(tmp, "workspaces")
os.makedirs(os.path.join(ws, PID), exist_ok=True)

raw = open(os.path.join(ROOT, "engine/config/config.defaults.json"), encoding="utf-8").read()
raw = re.sub(r"^\s*//.*$", "", raw, flags=re.M)
raw = re.sub(r",(\s*[}\]])", r"\1", raw)
cfg = json.loads(raw)
# Flowcharts ON — the view under test. Everything else off to keep it quick.
cfg["views"] = {"interfaceTables": True, "unitDiagrams": False, "flowcharts": True,
                "behaviourDiagram": False, "componentStaticDiagram": False}
cfg["llm"] = {**cfg.get("llm", {}), "descriptions": False, "behaviourNames": False,
              "summarize": False}
# A LAYER, mirroring the reported project shape (Layer1\App\Main.cpp).
cfg["layers"] = {"Layer1": {"path": "Layer1", "groups": {"Core": {"App": "App"}}}}
json.dump(cfg, open(os.path.join(ws, PID, "config.json"), "w", encoding="utf-8"), indent=2)
os.makedirs(os.path.join(tmp, "api", "db", "data"), exist_ok=True)
json.dump([{"id": PID, "name": PID, "repo_url": "", "default_branch": "main"}],
          open(os.path.join(tmp, "api", "db", "data", "projects.json"), "w", encoding="utf-8"))

repo = os.path.join(tmp, "repo")
src_dir_path = os.path.join(repo, "Layer1", "App")
os.makedirs(src_dir_path)
with open(os.path.join(src_dir_path, "Main.cpp"), "w", encoding="utf-8") as fh:
    fh.write("""int helper(int a) {
    if (a > 0) { return a * 2; }
    return 0;
}

int main_entry(int x) {
    int r = 0;
    for (int i = 0; i < x; ++i) { r = r + helper(i); }
    if (r > 100) { r = 100; }
    return r;
}
""")
for a in (("init", "-q"), ("symbolic-ref", "HEAD", "refs/heads/main"), ("add", "-A")):
    subprocess.run(["git", *a], cwd=repo, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "v1"],
               cwd=repo, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
sha = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                     capture_output=True, text=True).stdout.strip()

import sqlalchemy as sa                                     # noqa: E402
from core.db import get_engine                              # noqa: E402
from api.db.postgres import schema as s                     # noqa: E402

with get_engine().begin() as cx:
    for t in (s.entity_versions, s.model_edges, s.model_units, s.model_components,
              s.model_summaries, s.knowledge_base, s.incremental_plans, s.tu_includes,
              s.parse_snapshots, s.version_output_files):
        cx.execute(sa.delete(t).where(t.c.version_id.in_((VID, VID2))))
    cx.execute(sa.delete(s.versions).where(s.versions.c.id.in_((VID, VID2))))
    cx.execute(sa.delete(s.projects).where(s.projects.c.id == PID))
    cx.execute(sa.insert(s.projects), {"id": PID, "name": PID, "repo_url": "",
                                       "default_branch": "main",
                                       "created_at": datetime.datetime.now(datetime.timezone.utc)})
    cx.execute(sa.insert(s.versions), {
        "id": VID, "project_id": PID, "version": VID, "commit_sha": sha, "branch": "main",
        "status": "in_review", "created_at": datetime.datetime.now(datetime.timezone.utc)})

from incremental.generate import generate_full              # noqa: E402
from incremental.engine import generate_incremental          # noqa: E402
from core.paths import paths as _paths_fn


def _log_text():
    """Phase 3 runs as a SUBPROCESS, so an in-process logging handler never sees its output —
    an earlier version of this check installed one and reported failure while the fix worked.
    Read the run log the subprocess actually writes to."""
    d = _paths_fn().logs_dir
    if not os.path.isdir(d):
        return ""
    logs = sorted((os.path.join(d, f) for f in os.listdir(d) if f.endswith(".log")),
                  key=os.path.getmtime)
    if not logs:
        return ""
    with open(logs[-1], encoding="utf-8", errors="replace") as fh:
        return fh.read()


_mark = 0

print("=== run 1: FULL(commit 1) ===")
generate_full(PID, "main", sha, {"type": "project"}, workspaces_root=ws,
              no_llm=True, repo_url=repo, version_id=VID)

# commit 2 — change ONE function body; helper() is untouched and must be carried forward.
with open(os.path.join(src_dir_path, "Main.cpp"), "w", encoding="utf-8") as fh:
    fh.write("""int helper(int a) {
    if (a > 0) { return a * 2; }
    return 0;
}

int main_entry(int x) {
    int r = 0;
    for (int i = 0; i < x; ++i) { r = r + helper(i) + 7; }
    if (r > 200) { r = 200; }
    return r;
}
""")
subprocess.run(["git", "-C", repo, "add", "-A"], check=True,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t",
                "commit", "-q", "-m", "v2"], check=True,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
sha2 = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                      capture_output=True, text=True).stdout.strip()

with get_engine().begin() as cx:
    cx.execute(sa.insert(s.versions), {
        "id": VID2, "project_id": PID, "version": VID2, "commit_sha": sha2, "branch": "main",
        "status": "in_review", "created_at": datetime.datetime.now(datetime.timezone.utc)})

_mark = len(_log_text())
print("=== run 2: INCREMENTAL(commit 2) ===")
generate_incremental(PID, "main", sha2, scope={"type": "project"}, workspaces_root=ws,
                     no_llm=True, repo_url=repo, version_id=VID2, base_version_id=VID)

_run2 = _log_text()[_mark:]
_lines = _run2.splitlines()
restricted = [m for m in _lines if "incremental: flowcharts" in m]
carried = [m for m in _lines if "carried forward" in m and "flowchart" in m]
full_regen = [m for m in _lines if "full flowchart regen" in m or "no functions model" in m]
rendered = [m for m in _lines if "PNGs rendered" in m]

print()
for m in restricted + carried + full_regen + rendered:
    print("   " + m.strip())

# Bug: an incremental run left the PARTIAL parse's model/*.json in place, and
# snapshot_parse_model copied them into versions/<id>/parse/. A full version was clean, an
# incremental one was not.
MODEL_JSON = {"functions.json", "globalVariables.json", "dataDictionary.json", "edges.json",
              "hashes.json", "tu_includes.json", "entity_files.json", "func_keys.json",
              "override_pairs.json", "metadata.json"}
for _v in (VID, VID2):
    _md = os.path.join(ws, PID, "versions", _v, "model")
    _pd = os.path.join(ws, PID, "versions", _v, "parse")
    _mleft = sorted(MODEL_JSON & set(os.listdir(_md))) if os.path.isdir(_md) else []
    _pleft = sorted(os.listdir(_pd)) if os.path.isdir(_pd) else []
    print(f"    {_v}: model/*.json={_mleft}  parse/={len(_pleft)} file(s)")

fails = []
for _v in (VID, VID2):
    _md = os.path.join(ws, PID, "versions", _v, "model")
    _pd = os.path.join(ws, PID, "versions", _v, "parse")
    if os.path.isdir(_md) and (MODEL_JSON & set(os.listdir(_md))):
        fails.append(f"{_v}: scratch model/*.json left behind: "
                     f"{sorted(MODEL_JSON & set(os.listdir(_md)))}")
    if os.path.isdir(_pd) and os.listdir(_pd):
        fails.append(f"{_v}: versions/<id>/parse/ is not empty in db mode: {os.listdir(_pd)}")
if full_regen:
    fails.append(f"flowcharts fully regenerated instead of reused: {full_regen[0]}")
if not restricted:
    fails.append("no 'incremental: flowcharts ... restricted to N changed function(s)' line — "
                 "the plan was not applied, so every flowchart is rebuilt each run")
if not carried:
    fails.append("no baseline flowcharts were carried forward")

with get_engine().begin() as cx:
    for t in (s.entity_versions, s.model_edges, s.model_units, s.model_components,
              s.model_summaries, s.knowledge_base, s.incremental_plans, s.tu_includes,
              s.parse_snapshots, s.version_output_files):
        cx.execute(sa.delete(t).where(t.c.version_id.in_((VID, VID2))))
    cx.execute(sa.delete(s.versions).where(s.versions.c.id.in_((VID, VID2))))
    cx.execute(sa.delete(s.projects).where(s.projects.c.id == PID))
shutil.rmtree(tmp, ignore_errors=True)

print()
if fails:
    for f in fails:
        print("  !", f)
    raise SystemExit(1)
print("OK - incremental run restricted the flowchart engine and carried the baseline forward")
