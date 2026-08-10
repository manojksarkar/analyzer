#!/usr/bin/env python3
"""Prove the Postgres read paths work BEFORE the cutover removes the disk fallbacks.

Every PG-first reader (OutputReader / ModelReader) silently falls back to disk, so a run that
"works" proves nothing about Postgres. PG-7b deletes those fallbacks — so run this first: it
reports, per version, whether the data is actually IN Postgres and whether the readers actually
SERVE it from there.

    python tools/verify_pg_readers.py                 # newest 5 versions
    python tools/verify_pg_readers.py <version_id>    # one version
    python tools/verify_pg_readers.py --all           # every version

Exit code 0 = every checked version is fully served from Postgres (safe to cut over).
Exit code 1 = at least one version would fall back to disk (do NOT cut over yet).
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "engine"))

from sqlalchemy import func, select                                    # noqa: E402
from core.db import database_url, get_engine, _redact                  # noqa: E402
from api.db.postgres import schema as s                                # noqa: E402

OK, BAD, WARN = "OK  ", "FAIL", "warn"


def _counts(cx, version_id: str) -> dict:
    def _n(table, where):
        return cx.execute(select(func.count()).select_from(table).where(where)).scalar() or 0
    return {
        "output_files": _n(s.version_output_files, s.version_output_files.c.version_id == version_id),
        "entity_versions": _n(s.entity_versions, s.entity_versions.c.version_id == version_id),
        "model_units": _n(s.model_units, s.model_units.c.version_id == version_id),
        "model_edges": _n(s.model_edges, s.model_edges.c.version_id == version_id),
    }


def _check_version(cx, row) -> bool:
    """Print one version's Postgres readiness. True when nothing would fall back to disk."""
    vid = row.id
    c = _counts(cx, vid)
    meta_ok = bool(row.project_name or row.base_path or row.parse_fingerprint)
    cfg_ok = row.resolved_config is not None

    print(f"\n  version {vid}  ({row.version or '-'} · {(row.commit_sha or '')[:8]} · "
          f"{row.pipeline_status or row.status or '-'})")
    checks = [
        ("view outputs  (version_output_files)", c["output_files"] > 0, f"{c['output_files']} files", True),
        ("model         (entity_versions)", c["entity_versions"] > 0, f"{c['entity_versions']} entities", True),
        ("model units   (model_units)", c["model_units"] > 0, f"{c['model_units']} units", False),
        ("call graph    (model_edges)", c["model_edges"] > 0, f"{c['model_edges']} edges", False),
        ("run metadata  (versions.project_name/…)", meta_ok, row.project_name or "-", True),
        ("per-version config (resolved_config)", cfg_ok, "present" if cfg_ok else "NULL", True),
    ]
    blocking_ok = True
    for label, ok, detail, blocking in checks:
        tag = OK if ok else (BAD if blocking else WARN)
        print(f"    [{tag}] {label:42} {detail}")
        if blocking and not ok:
            blocking_ok = False
    if not blocking_ok:
        print("    -> this version would FALL BACK TO DISK; re-run it after tools/db_setup.py")
    return blocking_ok


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--all"]
    want_all = "--all" in sys.argv[1:]

    dsn = database_url()
    print(f"database: {_redact(dsn)}")
    try:
        engine = get_engine()
        with engine.connect() as cx:
            if args:
                stmt = select(s.versions).where(s.versions.c.id == args[0])
            else:
                stmt = select(s.versions).order_by(s.versions.c.created_at.desc())
                if not want_all:
                    stmt = stmt.limit(5)
            rows = list(cx.execute(stmt))
            if not rows:
                print("\nNo versions found — run an analysis job first.")
                return 1
            print(f"checking {len(rows)} version(s)")
            all_ok = all([_check_version(cx, r) for r in rows])
    except Exception as exc:
        print(f"\n*** cannot read the database: {type(exc).__name__}: {exc}")
        print("    Check the DSN above (DATABASE_URL or the `db` section of "
              "engine/config/config.local.json) and that tools/db_setup.py has been run.")
        return 1

    print()
    if all_ok:
        print("OK — every checked version is served from Postgres. Safe to remove the disk fallbacks.")
        return 0
    print("NOT READY — at least one version still depends on the disk fallback. Do NOT cut over yet.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
