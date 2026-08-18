#!/usr/bin/env python3
"""A NARROWED parse must produce the same model as a FULL parse (M4.4 gate).

Narrowed parse re-reads only the changed translation units and merges them into the baseline's
stored skeleton. Done right it is the single biggest non-LLM saving in the pipeline — parsing is
~65% of a run and scales with source volume, not model size. Done wrong it produces a model
containing only the changed files, and the run reports success.

Nothing has ever exercised it. It is opt-in, the API never set it, and no test ran it end to
end, which is how a plain `NameError` on the first line of `_try_narrowed_parse` survived: every
call would have crashed. That is what this gate is for.

Method — a two-commit fixture where one file changes and the others must be carried through:

    ver1  FULL(commit 1)                        the baseline skeleton
    verF  INCREMENTAL(commit 2) full parse      the reference model
    verN  INCREMENTAL(commit 2) narrowed parse  the model under test

then compare verN against verF entity by entity. They must agree.

Deliberately checks the CROSS-FILE call edge as well: `uart_send` calls `timer_wait`, defined in
a file the narrowed parse does NOT re-read. Resolving that depends on the baseline func-key map
arriving from `parse_snapshots`; if it does not, the edge silently disappears and only a check
like this one notices.

    python tools/verify_narrowed_parse.py

Exit 0 = narrowed and full agree.
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, "engine")]

PID = "verify-narrowed"

# Three files. Commit 2 changes ONLY uart.cpp, so timer.cpp and storage.cpp must survive the
# merge untouched — and uart_send's call into timer.cpp must still resolve.
TIMER_H = "#pragma once\nvoid timer_wait(int ms);\n"
TIMER_CPP = """#include "timer.h"
void timer_wait(int ms) {
    volatile int spin = ms;
    while (spin > 0) { spin = spin - 1; }
}
"""
STORAGE_H = "#pragma once\nint storage_read(int addr);\n"
STORAGE_CPP = """#include "storage.h"
int storage_read(int addr) {
    return addr * 2;
}
"""
UART_H = "#pragma once\nvoid uart_send(int byte);\n"
UART_V1 = """#include "uart.h"
#include "timer.h"
void uart_send(int byte) {
    timer_wait(1);
}
"""
UART_V2 = """#include "uart.h"
#include "timer.h"
void uart_send(int byte) {
    timer_wait(2);
    timer_wait(3);
}
"""


def _git(repo, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True,
                          text=True, env=env).stdout.strip()


def _write(path, body):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def _compare(ref, got):
    """Entity-by-entity diff of two models. Returns a list of human-readable differences.

    Edge lists compare as SETS — they are rebuilt from rows, so order is an artefact, the same
    bar verify_model_parity settled on.
    """
    EDGE = {"callsIds", "calledByIds", "readsGlobalIds", "writesGlobalIds"}
    out = []
    rf, gf = ref.get("functions") or {}, got.get("functions") or {}
    only_ref, only_got = set(rf) - set(gf), set(gf) - set(rf)
    if only_ref:
        out.append(f"{len(only_ref)} function(s) the narrowed parse LOST: {sorted(only_ref)[:5]}")
    if only_got:
        out.append(f"{len(only_got)} function(s) it invented: {sorted(only_got)[:5]}")
    for key in sorted(set(rf) & set(gf)):
        a, b = rf[key] or {}, gf[key] or {}
        for field, av in a.items():
            bv = b.get(field)
            if field in EDGE:
                if set(av or []) != set(bv or []):
                    out.append(f"{key}.{field}: full={sorted(av or [])} narrowed={sorted(bv or [])}")
            elif av != bv:
                out.append(f"{key}.{field}: full={av!r} narrowed={bv!r}")
    for part in ("globalVariables", "dataDictionary", "hashes"):
        a, b = ref.get(part) or {}, got.get(part) or {}
        if set(a) != set(b):
            out.append(f"{part}: keys differ (full={len(a)} narrowed={len(b)})")
    return out


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    tmp = tempfile.mkdtemp(prefix="verify-narrowed-")
    _db = os.path.join(tmp, "verify-narrowed.db").replace("\\", "/")
    os.environ["DATABASE_URL"] = f"sqlite:///{_db}"
    os.environ["ANALYZER_DATA_ROOT"] = tmp
    from core.paths import set_data_root
    set_data_root(tmp)
    ws_root = os.path.join(tmp, "workspaces")
    os.makedirs(os.path.join(ws_root, PID), exist_ok=True)

    from utils import load_config
    cfg = load_config(os.path.join(_ROOT, "engine"))
    cfg["views"] = {"interfaceTables": True, "unitDiagrams": False, "flowcharts": False,
                    "behaviourDiagram": False, "componentStaticDiagram": False}
    cfg["layers"] = {"App": {"path": ".", "groups": {"Core": {"Dev": "src"}}}}
    cfg["llm"] = {**cfg.get("llm", {}), "descriptions": False, "behaviourNames": False,
                  "summarize": False}
    _write_json(os.path.join(ws_root, PID, "config.json"), cfg)
    _write_json(os.path.join(tmp, "api", "db", "data", "projects.json"),
                [{"id": PID, "name": PID, "repo_url": "", "default_branch": "main"}])

    repo = os.path.join(tmp, "repo")
    os.makedirs(repo, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    for rel, body in (("src/timer.h", TIMER_H), ("src/timer.cpp", TIMER_CPP),
                      ("src/storage.h", STORAGE_H), ("src/storage.cpp", STORAGE_CPP),
                      ("src/uart.h", UART_H), ("src/uart.cpp", UART_V1)):
        _write(os.path.join(repo, rel), body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "v1")
    sha1 = _git(repo, "rev-parse", "HEAD")

    _write(os.path.join(repo, "src/uart.cpp"), UART_V2)      # ONLY uart.cpp changes
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "v2")
    sha2 = _git(repo, "rev-parse", "HEAD")

    import sqlalchemy as sa
    from api.db.postgres import schema as s
    from core.db import get_engine
    eng = get_engine()
    s.metadata.create_all(eng)
    now = datetime.datetime.now(datetime.timezone.utc)
    with eng.begin() as cx:
        cx.execute(sa.insert(s.projects), {"id": PID, "name": PID, "repo_url": "",
                                           "default_branch": "main", "created_at": now})

    def _reserve(vid, sha):
        with eng.begin() as cx:
            cx.execute(sa.insert(s.versions), {
                "id": vid, "project_id": PID, "version": vid, "commit_sha": sha,
                "branch": "main", "status": "in_review", "created_at": now})

    for vid, sha in (("ver1", sha1), ("verF", sha2), ("verN", sha2)):
        _reserve(vid, sha)

    from incremental.generate import generate_full
    from incremental.engine import generate_incremental

    print(f"commit 1 {sha1[:10]}   commit 2 {sha2[:10]}   (only src/uart.cpp changed)")
    print("\n=== baseline: FULL(commit 1) ===")
    generate_full(PID, "main", sha1, {"type": "project"}, workspaces_root=ws_root,
                  no_llm=True, repo_url=repo, version_id="ver1")

    print("=== reference: INCREMENTAL(commit 2), FULL parse ===")
    generate_incremental(PID, "main", sha2, scope={"type": "project"}, workspaces_root=ws_root,
                         no_llm=True, repo_url=repo, version_id="verF",
                         base_version_id="ver1", narrowed_parse=False)

    print("=== under test: INCREMENTAL(commit 2), NARROWED parse ===")
    # Narrowed parse falls back to a FULL parse whenever it cannot prove itself safe — correct
    # behaviour, and a silent way for this gate to pass having tested nothing. It did exactly
    # that on its first run ("baseline has no parser-level snapshot"), so capture the engine's
    # log and require positive evidence that the narrowed path actually ran.
    import logging
    captured = []

    class _Capture(logging.Handler):
        def emit(self, record):
            captured.append(record.getMessage())

    _h = _Capture()
    _eng_log = logging.getLogger("incremental")
    _eng_log.addHandler(_h)
    try:
        m = generate_incremental(PID, "main", sha2, scope={"type": "project"},
                                 workspaces_root=ws_root, no_llm=True, repo_url=repo,
                                 version_id="verN", base_version_id="ver1", narrowed_parse=True)
    finally:
        _eng_log.removeHandler(_h)

    ran_narrowed = [ln for ln in captured
                    if "narrowed parse:" in ln and ("re-parsed" in ln or "0 affected" in ln)]
    fell_back = [ln for ln in captured
                 if "narrowed parse unavailable" in ln or "narrowed parse skipped" in ln
                 or "narrowed parse: partial parse failed" in ln
                 or "narrowed parse: parse fingerprint changed" in ln]
    for ln in ran_narrowed + fell_back:
        print(f"    {ln}")

    from core import model_store
    with eng.connect() as cx:
        ref = model_store.load_model(cx, "verF")
        got = model_store.load_model(cx, "verN")

    ref_m = {"functions": ref.get("functions") or {}, "globalVariables": ref.get("globals") or {},
             "dataDictionary": ref.get("datadict") or {}, "hashes": ref.get("hashes") or {}}
    got_m = {"functions": got.get("functions") or {}, "globalVariables": got.get("globals") or {},
             "dataDictionary": got.get("datadict") or {}, "hashes": got.get("hashes") or {}}

    print(f"\nfunctions:  full={len(ref_m['functions'])}   narrowed={len(got_m['functions'])}")

    fails = _compare(ref_m, got_m)

    # The whole point of the func-key map: a call from the re-parsed file into one that was NOT
    # re-parsed. If the map did not arrive, this edge is simply absent and everything else looks
    # fine — so it is asserted by name rather than left to the bulk diff.
    send = next((k for k in got_m["functions"] if "uart_send" in k), None)
    wait = next((k for k in got_m["functions"] if "timer_wait" in k), None)
    if not send or not wait:
        fails.append(f"fixture entities missing: uart_send={send!r} timer_wait={wait!r}")
    elif wait not in (got_m["functions"][send].get("callsIds") or []):
        fails.append("uart_send -> timer_wait edge LOST — the baseline func-key map did not "
                     "reach the partial parse, so calls into un-parsed files do not resolve")

    if not got_m["functions"]:
        fails.append("the narrowed parse produced NO functions at all")

    # A pass means nothing unless the narrowed path ran. Checked last so a real difference is
    # reported first, but treated as just as much of a failure.
    if fell_back:
        fails.append("the narrowed parse FELL BACK to a full parse, so this check compared two "
                     f"full parses and proved nothing: {fell_back[0]}")
    elif not ran_narrowed:
        fails.append("no evidence the narrowed path ran at all — expected a 'narrowed parse: "
                     "re-parsed N affected TU(s)' line in the engine log")

    print(f"decision={m.get('decision')} reused={m.get('reused')} "
          f"regenerated={m.get('regenerated')}")

    print()
    if fails:
        print(f"FAILED — narrowed differs from full ({len(fails)} finding(s)):\n")
        for f in fails[:25]:
            print("  !", f)
        print(f"\n(workspace kept: {tmp})")
        return 1

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    print("OK — the narrowed parse produces the same model as a full parse, and the "
          "cross-file call edge survived.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
