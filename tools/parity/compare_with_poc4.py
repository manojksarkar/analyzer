"""Run the same document-generation scenario on poc-4 and on this branch, and compare.

poc-4 keeps its model in model/*.json and writes to <tree>/output. This branch keeps it in
the database and writes to the version's workspace. Everything else is meant to be the same,
so anything that differs in the OUTPUT is a migration defect until proven otherwise.

What it does per scenario: runs poc-4's `run.py <repo> --selected-<scope>`, then this
branch's `analyzer.py onboard` + `generate --scope ...` on the same commit, then collects
each side's whole output/ -- DOCX paragraphs and table rows, .mmd, .json, PNG names -- and
diffs it with timestamps, absolute paths and shas scrubbed.

Two things must be equalised or every scenario "differs" for no reason:
  * the config, written in each branch's own spelling (poc-4 reads engine/config/config.json,
    this branch takes --config), with every view on and the LLM off -- LLM prose is
    non-deterministic and would drown the real signal;
  * --project-name, which poc-4 defaults to the checkout directory's basename while this
    branch takes from the project's display name. Otherwise every cover page differs.

And one rule to mirror: --component-per-docx cannot be combined with --selected-component
(run.py refuses, and per_component_docx_args returns [] for a component scope).

Setup:
    git worktree add --detach <path> origin/poc-4
    # junction/symlink node_modules into it so both sides render mermaid identically
    python tools/parity/compare_with_poc4.py --poc4 <path>

Known shared non-determinism: dot_builder iterates a set to emit the invisible push-down
edges, so the DOT -- and the stored flowchart JSON -- comes out in a different order on
every process. This branch sorts them; poc-4 does not, so 2 of 25 flowcharts in the Iface
component will differ against an unpatched poc-4. That is a pre-existing bug shared by both
branches, not something the migration caused; apply the same one-line sort to the worktree
copy to compare exactly.

Result at the time of writing: 7/7 scenarios match, up to and including the project scope --
777 artifacts and 26 documents, every block equal.
"""
import argparse
import datetime
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

DB_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# A detached worktree of poc-4. Create one with:
#     git worktree add --detach <path> origin/poc-4
# and junction/symlink node_modules into it so both sides render mermaid identically.
POC4_ROOT = os.environ.get("POC4_WORKTREE") or os.path.join(
    tempfile.gettempdir(), "poc4-wt")
SCRATCH = os.path.join(tempfile.gettempdir(), "parity-e2e")
REPO = os.path.join(SCRATCH, "repo")
PROJECT_NAME = "SampleCppProject"
PY = sys.executable

# name -> (poc-4 run.py args, --scope for analyzer.py)
SCENARIOS = {
    "group-my-sample":  (["--selected-group", "My Sample"],  "group:My Sample"),
    "group-support":    (["--selected-group", "Support"],    "group:Support"),
    "group-full":       (["--selected-group", "Full"],       "group:Full"),
    "layer-layer1":     (["--selected-layer", "Layer1"],     "layer:Layer1"),
    "component-lib":    (["--selected-component", "Lib"],    "component:Lib"),
    "component-util":   (["--selected-component", "Util"],   "component:Util"),
    "project":          ([],                                  "project"),
}


def rmtree(path):
    """rmtree that clears read-only bits (git pack files on Windows)."""
    if not os.path.isdir(path):
        return

    def retry(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)

    kw = {"onexc": retry} if sys.version_info >= (3, 12) else {"onerror": retry}
    shutil.rmtree(path, **kw)


def run(cmd, cwd, env=None, timeout=1800):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          env=env, timeout=timeout, errors="replace")


# ---------------------------------------------------------------------------
# fixture
# ---------------------------------------------------------------------------
def make_repo():
    """SampleCppProject as its own git repo -- a version is identified by a commit."""
    rmtree(REPO)
    os.makedirs(SCRATCH, exist_ok=True)
    shutil.copytree(os.path.join(DB_ROOT, "SampleCppProject"), REPO)
    q = dict(check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["git", "-C", REPO, "init", "-q"], **q)
    subprocess.run(["git", "-C", REPO, "symbolic-ref", "HEAD", "refs/heads/main"], **q)
    subprocess.run(["git", "-C", REPO, "add", "-A"], **q)
    subprocess.run(["git", "-C", REPO, "-c", "user.email=p@t", "-c", "user.name=p",
                    "commit", "-q", "-m", "v1"], **q)
    sha = subprocess.run(["git", "-C", REPO, "rev-parse", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    return sha


def base_config():
    """The defaults, with every view on and the LLM off, from THIS branch's file."""
    sys.path.insert(0, os.path.join(DB_ROOT, "engine"))
    from core.config import _strip_json_comments, _strip_trailing_commas
    raw = open(os.path.join(DB_ROOT, "engine", "config", "config.defaults.json"),
               encoding="utf-8").read()
    cfg = json.loads(_strip_trailing_commas(_strip_json_comments(raw)))
    cfg["views"] = {"interfaceTables": True, "unitDiagrams": True, "flowcharts": True,
                    "behaviourDiagram": True, "componentStaticDiagram": True}
    cfg["llm"] = {**cfg.get("llm", {}), "descriptions": False,
                  "behaviourNames": False, "summarize": False}
    return cfg


# ---------------------------------------------------------------------------
# document extraction
# ---------------------------------------------------------------------------
_VOLATILE = [
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?"), "<TIME>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}"), "<DATE>"),
    (re.compile(r"[A-Za-z]:\\[^\s\"'|]+"), "<PATH>"),
    (re.compile(r"/tmp/[^\s\"'|]+"), "<PATH>"),
    (re.compile(r"\b[0-9a-f]{40}\b"), "<SHA>"),
    (re.compile(r"\b[0-9a-f]{16}\b"), "<SHA16>"),
]


def scrub(text):
    for pat, rep in _VOLATILE:
        text = pat.sub(rep, text)
    return text


def docx_content(path):
    """A DOCX as a comparable list of strings: paragraphs, then every table row."""
    xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8", "replace")
    # paragraph and cell boundaries -> newlines, then strip tags
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"</w:tc>", " | ", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    lines = [scrub(l.strip()) for l in text.splitlines()]
    return [l for l in lines if l and l != "|"]


def image_count(path):
    with zipfile.ZipFile(path) as z:
        return sum(1 for n in z.namelist() if n.startswith("word/media/"))


def collect(output_dir):
    """Every artifact a run produced, keyed by a path relative to the output root."""
    found = {}
    for root, _dirs, files in os.walk(output_dir):
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, output_dir).replace("\\", "/")
            if f.endswith(".docx"):
                found[rel] = ("docx", docx_content(full), image_count(full))
            elif f.endswith(".mmd"):
                found[rel] = ("mmd", [scrub(l.rstrip()) for l in
                                      open(full, encoding="utf-8").read().splitlines()], 0)
            elif f.endswith(".json"):
                found[rel] = ("json", scrub(open(full, encoding="utf-8").read()), 0)
            elif f.endswith(".png"):
                found[rel] = ("png", None, os.path.getsize(full))
    return found


# ---------------------------------------------------------------------------
# the two runs
# ---------------------------------------------------------------------------
def run_poc4(scenario, sha):
    args, _ = SCENARIOS[scenario]
    cfg = base_config()
    cfg_path = os.path.join(POC4_ROOT, "engine", "config", "config.json")
    json.dump(cfg, open(cfg_path, "w", encoding="utf-8"), indent=2)
    rmtree(os.path.join(POC4_ROOT, "output"))
    rmtree(os.path.join(POC4_ROOT, "model"))
    # --component-per-docx is mutually exclusive with --selected-component on both
    # branches: run.py errors if combined, and per_component_docx_args returns [] for a
    # component scope. Mirror that here or the poc-4 side just fails.
    per_comp = [] if "--selected-component" in args else ["--component-per-docx"]
    cmd = [PY, os.path.join(POC4_ROOT, "engine", "run.py"), REPO, "--clean",
           *per_comp, "--no-llm-summarize",
           "--project-name", PROJECT_NAME, *args]
    r = run(cmd, POC4_ROOT)
    return r, os.path.join(POC4_ROOT, "output")


def run_db(scenario, sha, pid):
    _, scope = SCENARIOS[scenario]
    cfg = base_config()
    cfg_path = os.path.join(SCRATCH, "db-config.json")
    json.dump(cfg, open(cfg_path, "w", encoding="utf-8"), indent=2)
    vid = "v1"
    clear_version(pid, vid)
    r = run([PY, os.path.join(DB_ROOT, "analyzer.py"), "onboard",
             "--project-id", pid, "--name", PROJECT_NAME, "--source", REPO,
             "--config", cfg_path, "--force-config", "--branch", "main",
             "--version-id", vid, "--commit", sha], DB_ROOT)
    if r.returncode != 0:
        return r, ""
    r = run([PY, os.path.join(DB_ROOT, "analyzer.py"), "generate",
             "--project-id", pid, "--version-id", vid, "--branch", "main",
             "--commit", sha, "--scope", scope, "--no-llm"], DB_ROOT)
    return r, os.path.join(DB_ROOT, "workspaces", pid, "versions", vid, "output")


def clear_version(pid, vid):
    sys.path[:0] = [DB_ROOT, os.path.join(DB_ROOT, "engine")]
    import sqlalchemy as sa
    from core.db import get_engine
    from api.db.postgres import schema as s
    with get_engine().begin() as cx:
        for t in (s.model_edges, s.entity_versions, s.model_units, s.model_components,
                  s.model_summaries, s.knowledge_base, s.incremental_plans,
                  s.tu_includes, s.parse_snapshots, s.version_output_files):
            cx.execute(sa.delete(t).where(t.c.version_id == vid))
        cx.execute(sa.delete(s.versions).where(s.versions.c.project_id == pid))
        cx.execute(sa.delete(s.projects).where(s.projects.c.id == pid))
    rmtree(os.path.join(DB_ROOT, "workspaces", pid))


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------
def compare(name, a, b):
    """a = poc-4 artifacts, b = db artifacts. Returns (verdict, list of notes)."""
    notes = []
    docs_a = {k for k in a if k.endswith(".docx")}
    docs_b = {k for k in b if k.endswith(".docx")}
    if docs_a != docs_b:
        for k in sorted(docs_a - docs_b):
            notes.append(f"DOCUMENT MISSING in db: {k}")
        for k in sorted(docs_b - docs_a):
            notes.append(f"DOCUMENT EXTRA in db  : {k}")

    for k in sorted(docs_a & docs_b):
        ca, cb = a[k][1], b[k][1]
        if ca != cb:
            diff = [(i, x, y) for i, (x, y) in enumerate(zip(ca, cb)) if x != y]
            notes.append(f"CONTENT differs: {k} ({len(diff)} of {len(ca)} blocks"
                         f"{'' if len(ca) == len(cb) else f'; lengths {len(ca)} vs {len(cb)}'})")
            for i, x, y in diff[:3]:
                notes.append(f"    [{i}] poc-4: {x[:110]}")
                notes.append(f"    [{i}] db   : {y[:110]}")
        if a[k][2] != b[k][2]:
            notes.append(f"IMAGES differ  : {k}  poc-4={a[k][2]} db={b[k][2]}")

    for ext, label in ((".mmd", "diagram"), (".json", "json")):
        ka = {k for k in a if k.endswith(ext)}
        kb = {k for k in b if k.endswith(ext)}
        for k in sorted(ka - kb):
            notes.append(f"{label.upper()} MISSING in db: {k}")
        for k in sorted(kb - ka):
            notes.append(f"{label.upper()} EXTRA in db  : {k}")
        for k in sorted(ka & kb):
            if a[k][1] != b[k][1]:
                notes.append(f"{label.upper()} differs: {k}")

    pa = sorted(k for k in a if k.endswith(".png"))
    pb = sorted(k for k in b if k.endswith(".png"))
    if pa != pb:
        notes.append(f"PNG set differs: poc-4={len(pa)} db={len(pb)}")
        for k in sorted(set(pa) - set(pb))[:4]:
            notes.append(f"    missing in db: {k}")
        for k in sorted(set(pb) - set(pa))[:4]:
            notes.append(f"    extra in db  : {k}")

    return ("MATCH" if not notes else "DIFFERS"), notes


def main():
    global POC4_ROOT
    ap = argparse.ArgumentParser()
    ap.add_argument("scenarios", nargs="*", default=None,
                    help="which to run (default: all): " + ", ".join(SCENARIOS))
    ap.add_argument("--poc4", help="path to the poc-4 worktree (default: %(default)s)",
                    default=POC4_ROOT)
    a = ap.parse_args()
    POC4_ROOT = a.poc4
    if not os.path.isdir(POC4_ROOT):
        print("no poc-4 worktree at %s.\n  Make one with:\n    git worktree add --detach %s origin/poc-4" % (POC4_ROOT, POC4_ROOT),
              file=sys.stderr)
        return 2
    names = a.scenarios or list(SCENARIOS)

    sha = make_repo()
    print(f"fixture: {REPO} @ {sha[:10]}\n")
    results = {}
    for i, name in enumerate(names, 1):
        print(f"[{i}/{len(names)}] {name}")
        r1, out1 = run_poc4(name, sha)
        if r1.returncode != 0:
            print(f"    poc-4 FAILED (exit {r1.returncode})")
            print("      " + (r1.stderr or r1.stdout).strip().splitlines()[-1][:160])
            results[name] = ("poc-4 failed", [])
            continue
        art1 = collect(out1)
        r2, out2 = run_db(name, sha, "parity" + str(i))
        if r2.returncode != 0:
            print(f"    db FAILED (exit {r2.returncode})")
            print("      " + (r2.stderr or r2.stdout).strip().splitlines()[-1][:160])
            results[name] = ("db failed", [])
            continue
        art2 = collect(out2)
        verdict, notes = compare(name, art1, art2)
        docs = len([k for k in art1 if k.endswith(".docx")])
        print(f"    poc-4 {len(art1):3d} artifacts / {docs} docs      db {len(art2):3d} artifacts")
        print(f"    {verdict}")
        for n in notes[:14]:
            print(f"      {n}")
        if len(notes) > 14:
            print(f"      ... {len(notes) - 14} more")
        results[name] = (verdict, notes)
        print()

    print("=" * 70)
    for k, (v, n) in results.items():
        print(f"  {k:<20} {v}{'' if not n else f'  ({len(n)} notes)'}")
    bad = [k for k, (v, _) in results.items() if v != "MATCH"]
    print("=" * 70)
    print(f"{len(results) - len(bad)}/{len(results)} scenarios match")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
