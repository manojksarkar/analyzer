#!/usr/bin/env python3
"""Dump everything the analyzer stores in the database to one reviewable text file.

Built for reading, not for machines: every table in schema order, row counts first so the shape
is visible at a glance, then rows with long/JSON values folded to a readable width. Large
payloads are truncated with the full size stated, so a 400-line knowledge base does not bury the
rest of the report.

    python tools/dump_db.py                        # everything -> db_dump.txt
    python tools/dump_db.py --out report.txt
    python tools/dump_db.py --version ver123       # only rows for one version
    python tools/dump_db.py --full                 # do not truncate payloads (large!)
    python tools/dump_db.py --counts               # row counts only

Reads the same `db` configuration the engine uses, so it needs no arguments on a machine that
can already run a generation.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, "engine")]

_MAX_VALUE = 2000          # per-cell cap before truncation
_MAX_ROWS = 200            # per-table cap before "... N more"
_WIDE = 100                # wrap width for folded values

# Tables whose rows are big and repetitive; capped harder unless --full.
_BULKY = {"content_blobs", "entity_versions", "model_edges", "parse_snapshots",
          "version_output_files", "knowledge_base", "incremental_plans",
          "llm_description_cache", "model_flowcharts", "model_unit_diagrams"}


def _fmt(value, *, limit: int) -> str:
    """One cell, readable. JSON is pretty-printed; everything long is truncated with its size."""
    if value is None:
        return "NULL"
    if isinstance(value, (dict, list)):
        text = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, default=str)
        size = f"  [{len(text)} chars, {text.count(chr(10)) + 1} lines]"
    elif isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    elif isinstance(value, (int, float, bool)):
        return str(value)
    else:
        text = str(value)
        size = f"  [{len(text)} chars]" if len(text) > limit else ""
    if len(text) > limit:
        head = text[:limit]
        return f"{head}\n        …TRUNCATED…{size}"
    return text + (size if size and "\n" in text else "")


def _version_column(table):
    for name in ("version_id", "id"):
        if name in table.c:
            return table.c[name]
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=None,
                    help="write to this file instead of stdout")
    ap.add_argument("--version", default=None, help="only rows for this version id")
    ap.add_argument("--project", default=None, help="only rows for this project id")
    ap.add_argument("--full", action="store_true", help="do not truncate payloads")
    ap.add_argument("--counts", action="store_true", help="row counts only")
    ap.add_argument("--max-rows", type=int, default=_MAX_ROWS, help=f"per table (default {_MAX_ROWS})")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    import sqlalchemy as sa
    from api.db.postgres import schema as s
    from core.db import database_url, get_engine, require_database, _redact, DatabaseUnavailable

    try:
        require_database()
    except DatabaseUnavailable as exc:
        print(exc)
        return 2

    eng = get_engine()
    tables = list(s.metadata.sorted_tables)
    limit = 10 ** 9 if args.full else _MAX_VALUE

    # stdout unless a file is asked for. It used to always drop db_dump.txt into the
    # working directory, which for a command whose whole job is to SHOW you something
    # meant reading a file you did not ask to create.
    import contextlib, io
    out_path = os.path.abspath(args.out) if args.out else None
    _buf = io.StringIO()
    with (open(out_path, 'w', encoding='utf-8') if out_path
          else contextlib.nullcontext(_buf)) as fh:
        def w(line=""):
            fh.write(line + "\n")

        w("=" * _WIDE)
        w("ANALYZER DATABASE DUMP")
        w("=" * _WIDE)
        w(f"generated : {datetime.datetime.now().isoformat(timespec='seconds')}")
        w(f"database  : {_redact(database_url())}")
        w(f"tables    : {len(tables)}")
        if args.version:
            w(f"filter    : version_id = {args.version}")
        if args.project:
            w(f"filter    : project_id = {args.project}")
        if not args.full:
            w(f"note      : values over {_MAX_VALUE} chars are truncated (--full for everything)")
        w()

        # --- shape first: counts for every table, empties called out -------------------
        w("-" * _WIDE)
        w("ROW COUNTS")
        w("-" * _WIDE)
        counts = {}
        for t in tables:
            try:
                with eng.connect() as cx:
                    counts[t.name] = cx.execute(
                        sa.select(sa.func.count()).select_from(t)).scalar() or 0
            except Exception as exc:
                counts[t.name] = f"ERROR: {exc}"
        width = max(len(n) for n in counts)
        for name in sorted(counts, key=lambda n: (counts[n] == 0, n)):
            n = counts[name]
            flag = "   <- EMPTY" if n == 0 else ""
            w(f"  {name:<{width}}  {str(n):>8}{flag}")
        w()
        empties = [n for n, c in counts.items() if c == 0]
        if empties:
            w(f"{len(empties)} empty table(s): {', '.join(sorted(empties))}")
            w("An empty table is not necessarily wrong — some are written only by features you")
            w("have not used, and incremental_plans is CLEARED at the end of every run by design.")
        w()

        if args.counts:
            # --counts stops here: the header above IS the summary.
            if out_path:
                print(f"wrote {out_path}")
            else:
                print(_buf.getvalue(), end="")
            return 0

        # --- rows -----------------------------------------------------------------------
        for t in tables:
            if isinstance(counts.get(t.name), str):
                continue
            q = sa.select(t)
            if args.version and "version_id" in t.c:
                q = q.where(t.c.version_id == args.version)
            if args.project and "project_id" in t.c:
                q = q.where(t.c.project_id == args.project)
            cap = args.max_rows if t.name not in _BULKY or args.full else min(args.max_rows, 20)
            try:
                with eng.connect() as cx:
                    rows = cx.execute(q.limit(cap + 1)).mappings().all()
            except Exception as exc:
                w(f"\n{'=' * _WIDE}\nTABLE {t.name}\n{'=' * _WIDE}\n  ERROR: {exc}")
                continue

            w()
            w("=" * _WIDE)
            w(f"TABLE  {t.name}    ({counts[t.name]} row(s) total)")
            w(f"       columns: {', '.join(c.name for c in t.c)}")
            w("=" * _WIDE)
            if not rows:
                w("  (no rows)")
                continue
            for i, row in enumerate(rows[:cap], 1):
                w(f"\n  --- row {i} " + "-" * (_WIDE - 14))
                for col in t.c:
                    val = _fmt(row.get(col.name), limit=limit)
                    if "\n" in val:
                        w(f"    {col.name}:")
                        for ln in val.splitlines():
                            w(f"        {ln}")
                    else:
                        w(f"    {col.name}: {val}")
            if len(rows) > cap:
                w(f"\n  … {counts[t.name] - cap} more row(s) not shown "
                  f"(--max-rows to raise, --full for everything)")

    if out_path:
        size = os.path.getsize(out_path)
        print(f"wrote {out_path}  ({size:,} bytes)")
    else:
        print(_buf.getvalue(), end='')
    print("Empty tables are listed near the top — start there.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
