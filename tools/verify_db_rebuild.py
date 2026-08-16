#!/usr/bin/env python3
"""Can a version be rebuilt from the DATABASE alone? (doc 09, C11 gate)

The migration's promise is that a version's work survives independently of the machine that
produced it. Every piece of that has been built — the model (C11b), the post-Phase-1 skeleton
(C2), the view outputs (C0), the run accounting (C1) — but nothing has ever checked the
promise end to end, and each piece was verified only in isolation.

This is the check. It reads a version out of Postgres and reports exactly what a fresh node
could reconstruct from it, and what it could not. READ-ONLY: it never writes to the database
and only materializes into a temp dir it removes afterwards.

Deliberately not a pipeline run. A full rebuild needs libclang, mermaid, Graphviz and minutes
of wall time; the question here is whether the DATA is complete, which is answerable in
seconds and is the part that actually regressed twice (a dropped `description`, an unwritten
`pipeline_status`).

    python tools/verify_db_rebuild.py                 # the newest version
    python tools/verify_db_rebuild.py ver8130ed2e     # a specific one

Exit 0 = a fresh node has everything it needs. Exit 1 = something is missing; the report
names it.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "engine"))


def _fail(msg: str) -> int:
    print(f"\nFAILED — {msg}")
    return 1


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    from core.db import is_database_configured, get_engine
    if not is_database_configured():
        print("No database configured (DATABASE_URL or the `db` section of "
              "config.local.json). This check is about what Postgres holds, so there is "
              "nothing to verify.")
        return 0

    from sqlalchemy import select
    from api.db.postgres import schema as s

    eng = get_engine()
    want = sys.argv[1] if len(sys.argv) > 1 else None

    with eng.connect() as cx:
        q = select(s.versions.c.id, s.versions.c.project_id, s.versions.c.version,
                   s.versions.c.commit_sha, s.versions.c.pipeline_status,
                   s.versions.c.decision, s.versions.c.regenerated, s.versions.c.reused,
                   s.versions.c.run_report, s.versions.c.report)
        if want:
            q = q.where(s.versions.c.id == want)
        else:
            q = q.order_by(s.versions.c.created_at.desc())
        row = cx.execute(q).first()

    if row is None:
        return _fail(f"no version {want!r} in the database" if want else
                     "the database has no versions yet — run a generation first")

    print(f"version   : {row.version}  ({row.id})")
    print(f"commit    : {(row.commit_sha or '')[:12]}")
    print(f"pipeline  : {row.pipeline_status or '(never written)'}")
    print(f"accounting: decision={row.decision} regenerated={row.regenerated} "
          f"reused={row.reused}")
    print()

    problems: list[str] = []

    # 1. the model — what Phase 2/3/4 consume.
    from incremental.store import make_store
    store = make_store(row.project_id)
    tmp = tempfile.mkdtemp(prefix="verify-rebuild-")
    try:
        model_dir = os.path.join(tmp, "model")
        if not store.hydrate_model(row.id, model_dir):
            problems.append("the model could not be materialized from the database")
        else:
            import json
            counts = {}
            for name in ("functions.json", "globalVariables.json", "units.json",
                         "components.json", "hashes.json"):
                p = os.path.join(model_dir, name)
                try:
                    with open(p, encoding="utf-8") as fh:
                        counts[name] = len(json.load(fh) or {})
                except (OSError, ValueError):
                    counts[name] = -1
            print("model from the database:")
            for name, n in counts.items():
                mark = "ok " if n > 0 else ("EMPTY" if n == 0 else "MISSING")
                print(f"  {mark:6} {name:22} {n if n >= 0 else ''}")
            if counts.get("functions.json", 0) <= 0:
                problems.append("the stored model has no functions — Phase 2 would produce "
                                "an empty document")
            if counts.get("hashes.json", 0) <= 0:
                problems.append("the stored model has no hashes — the next run could not "
                                "classify what changed and would regenerate everything")
        print()

        # 2. the post-Phase-1 skeleton — what a narrowed parse merges against (C2).
        snap = store.read_parse_snapshot(row.id)
        if snap:
            print(f"parse snapshot: {len(snap)} file(s) — narrowed parse can run on any node")
        else:
            print("parse snapshot: none — a narrowed parse on another node would fall back "
                  "to a FULL parse (correct, but slower)")
        print()

        # 3. the view outputs — what the rendered document reads (C0).
        with eng.connect() as cx:
            vof = s.version_output_files
            rows = cx.execute(select(vof.c.rel_path)
                              .where(vof.c.version_id == row.id)).fetchall()
        kinds: dict[str, int] = {}
        for r in rows:
            ext = os.path.splitext(r.rel_path)[1].lower() or "(none)"
            kinds[ext] = kinds.get(ext, 0) + 1
        if rows:
            print(f"view outputs  : {len(rows)} file(s) — " +
                  ", ".join(f"{n}{ext}" for ext, n in sorted(kinds.items())))
        else:
            problems.append("no view outputs stored — the rendered document would fall back "
                            "to local disk, so it is not readable from another node")

        # 4. accounting + report.
        if not row.pipeline_status:
            problems.append("pipeline_status is empty — this version will NOT be offered as "
                            "a baseline, so the next run regenerates everything")
        elif row.pipeline_status not in ("complete", "failed"):
            problems.append(f"pipeline_status is stuck at {row.pipeline_status!r} — the run "
                            f"never closed out, so this version is not baseline-eligible")
        if not row.report:
            print("report        : not stored (runs from before it was wired)")
        else:
            print(f"report        : stored ({len(row.report.splitlines())} lines)")
        if row.run_report:
            warn = (row.run_report or {}).get("warnings") or []
            print(f"run_report    : stored{f' — {len(warn)} warning(s)' if warn else ''}")
            for w in warn[:5]:
                print(f"                - {w}")
        else:
            print("run_report    : not stored (runs from before it was wired)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    # PNG/DOCX are deliberately NOT in the database (D-14) — state it rather than let a
    # green result imply a fresh node could serve documents without re-rendering.
    print("note: PNG and DOCX binaries stay as files by design (D-14). A fresh node can "
          "REBUILD them from the model above by running Phase 3+4; serving the existing "
          "ones without a re-render still needs shared storage.")

    if problems:
        print()
        for p in problems:
            print(f"  ! {p}")
        return _fail(f"{len(problems)} problem(s) — this version is not fully rebuildable "
                     f"from the database")
    print("\nOK — a fresh node has everything it needs to rebuild this version.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
