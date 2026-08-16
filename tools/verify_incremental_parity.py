#!/usr/bin/env python3
"""An INCREMENTAL run must produce the same document as a FULL run of the same commit.

That is the whole promise of incremental generation, and until now nothing checked it.
`verify_incremental.py` proves a baseline is *found* and reuse *happens*; it uses interface
tables only, so it cannot see a diagram that failed to carry forward. The failure mode that
gets shipped is exactly that: the run succeeds, the accounting looks healthy, and the
document is missing images that a full run would have produced.

Method — build a two-commit repo, then generate commit 2 twice:

    FULL(commit2)         the reference: what the document SHOULD contain
    INCREMENTAL(commit2)  the same commit, reusing commit 1 as its baseline

and diff the produced files plus the images embedded in the DOCX. Any diagram the
incremental path drops shows up as a missing file, named.

Needs mermaid + Graphviz (mmdc, @viz-js/viz) because the point is the DIAGRAMS. Run
`python tools/doctor.py` first; the check skips with a clear message if they are absent.

    python tools/verify_incremental_parity.py

Exit 0 = the incremental document matches the full one.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "engine"))

PID = "verify-inc-parity"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def _inventory(root):
    """{relative path -> kind} for every produced artifact."""
    out = {}
    if not os.path.isdir(root):
        return out
    for base, _d, files in os.walk(root):
        for f in files:
            rel = os.path.relpath(os.path.join(base, f), root).replace(os.sep, "/")
            out[rel] = os.path.splitext(f)[1].lower()
    return out


def _docx_media(root):
    """{docx name -> number of embedded images} — what the reader actually sees."""
    out = {}
    for base, _d, files in os.walk(root):
        for f in files:
            if f.lower().endswith(".docx"):
                try:
                    with zipfile.ZipFile(os.path.join(base, f)) as z:
                        out[f] = sum(1 for n in z.namelist() if n.startswith("word/media/"))
                except OSError:
                    out[f] = -1
    return out


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # DB-less, isolated: this is about the FILES a run produces.
    os.environ.pop("DATABASE_URL", None)
    os.environ["ANALYZER_NO_DB"] = "1"

    from utils import mmdc_path
    if not os.path.isfile(os.path.join(_ROOT, "node_modules", "@viz-js", "viz", "package.json")):
        print("SKIP — @viz-js/viz is not installed, so flowcharts cannot render and the check "
              "would pass vacuously.  npm install @viz-js/viz")
        return 0
    if not mmdc_path(_ROOT) or mmdc_path(_ROOT) == "mmdc":
        print("SKIP — local mmdc not found (npm install), so diagrams cannot render.")
        return 0

    tmp = tempfile.mkdtemp(prefix="verify-inc-parity-")
    os.environ["ANALYZER_DATA_ROOT"] = tmp
    from core.paths import set_data_root
    set_data_root(tmp)
    ws_root = os.path.join(tmp, "workspaces")
    os.makedirs(os.path.join(ws_root, PID), exist_ok=True)

    # A source tree big enough to have several units, so carry-forward has something to lose.
    src_dir = os.path.join(_ROOT, "SampleCppProject")
    if not os.path.isdir(src_dir):
        print(f"SKIP — no fixture project at {src_dir}")
        return 0

    from utils import load_config
    cfg = load_config(os.path.join(_ROOT, "engine"))
    # Every diagram view ON — the whole point is the images.
    cfg["views"] = {"interfaceTables": True, "unitDiagrams": True, "flowcharts": True,
                    "behaviourDiagram": True, "componentStaticDiagram": True}
    cfg["llm"] = {**cfg.get("llm", {}), "descriptions": False, "behaviourNames": False,
                  "summarize": False}
    _write_json(os.path.join(ws_root, PID, "config.json"), cfg)
    _write_json(os.path.join(tmp, "api", "db", "data", "projects.json"),
                [{"id": PID, "name": PID, "repo_url": "", "default_branch": "main"}])

    # --- a two-commit repo ------------------------------------------------
    repo = os.path.join(tmp, "repo")
    shutil.copytree(src_dir, repo)
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "v1")
    sha1 = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()

    # Change ONE function body, so most units are unchanged and must be carried forward.
    changed = None
    for base, _d, files in os.walk(repo):
        if ".git" in base:
            continue
        for f in files:
            if f.endswith(".cpp"):
                changed = os.path.join(base, f)
                break
        if changed:
            break
    with open(changed, "a", encoding="utf-8") as fh:
        fh.write("\n// verify-incremental-parity: touch one file\n"
                 "int _vip_touch(void) { return 41 + 1; }\n")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "v2")
    sha2 = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()

    from incremental.generate import generate_full
    from incremental.engine import generate_incremental
    from incremental.store import make_store

    print(f"commit 1 {sha1[:10]}   commit 2 {sha2[:10]}   (one .cpp changed)")
    print("\n=== baseline: FULL(commit 1) ===")
    generate_full(PID, "main", sha1, {"type": "project"}, workspaces_root=ws_root,
                  no_llm=True, repo_url=repo, version_id="ver1")

    print("=== reference: FULL(commit 2) ===")
    generate_full(PID, "main", sha2, {"type": "project"}, workspaces_root=ws_root,
                  no_llm=True, repo_url=repo, version_id="verFULL")

    print("=== under test: INCREMENTAL(commit 2), baseline = ver1 ===")
    m = generate_incremental(PID, "main", sha2, {"type": "project"}, workspaces_root=ws_root,
                             no_llm=True, repo_url=repo, version_id="verINC",
                             base_version_id="ver1")
    print(f"   decision={m.get('decision')} regenerated={m.get('regenerated')} "
          f"reused={m.get('reused')}")

    store = make_store(PID, workspaces_root=ws_root)
    full_out = os.path.join(store.artifact_dir("verFULL"), "output")
    inc_out = os.path.join(store.artifact_dir("verINC"), "output")

    full_files, inc_files = _inventory(full_out), _inventory(inc_out)
    full_docx, inc_docx = _docx_media(full_out), _docx_media(inc_out)

    by_ext = {}
    for name, files in (("FULL", full_files), ("INCR", inc_files)):
        for rel, ext in files.items():
            view = rel.split("/")[1] if rel.count("/") >= 1 else "(root)"
            by_ext.setdefault((view, ext), {"FULL": 0, "INCR": 0})[name] += 1

    print("\n" + "=" * 62)
    print(f"{'view / kind':40}{'FULL':>10}{'INCR':>10}")
    print("=" * 62)
    for (view, ext), c in sorted(by_ext.items()):
        flag = "" if c["FULL"] == c["INCR"] else "   <-- DIFFERS"
        print(f"{view + ' ' + ext:40}{c['FULL']:>10}{c['INCR']:>10}{flag}")

    print("\nimages embedded in the DOCX:")
    for k in sorted(set(full_docx) | set(inc_docx)):
        a, b = full_docx.get(k, 0), inc_docx.get(k, 0)
        print(f"  {k:44} FULL {a:>4}   INCR {b:>4}" + ("   <-- DIFFERS" if a != b else ""))

    missing = sorted(set(full_files) - set(inc_files))
    print()
    if missing:
        print(f"MISSING from the incremental run ({len(missing)}):")
        for m_ in missing[:30]:
            print("   -", m_)
    if full_docx != inc_docx:
        print("The DOCX image counts differ — the incremental document is not equivalent.")

    shutil.rmtree(tmp, ignore_errors=True)
    if missing or full_docx != inc_docx:
        print("\nFAILED — the incremental run does not reproduce the full run's document.")
        return 1
    print("\nOK — the incremental document matches the full one.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
