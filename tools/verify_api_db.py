"""Validate the API repositories (SqlDatabase) against a REAL Postgres.

The API test suite runs on SQLite (dual-backend parity). This proves the *same* repositories
seed and round-trip on the actual deployment Postgres - exercising JSONB, real type coercion,
and real foreign keys that SQLite only approximates.

It uses a THROWAWAY database on the same server (created and dropped here), so it never
touches your 'analyzer' data and is safe to re-run.

    $env:DATABASE_URL = "postgresql+psycopg://user:pass@host:5432/analyzer"
    python tools/verify_api_db.py
"""
from __future__ import annotations

import datetime
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, "engine")]

SMOKE_DB = "analyzer_apismoke"


def _validate(db) -> None:
    """Seed + read + write-round-trip against whatever SqlDatabase is given."""
    db.seed()
    print("    seeded all tables                : OK")

    alice = db.users.get_by_email("alice@aspice.dev")
    assert alice and alice.id == "u1", f"alice lookup: {alice}"
    projs = db.projects.list_for_user("u1")
    p1 = db.projects.get("p1")
    assert p1 and p1.id == "p1", f"p1 lookup: {p1}"
    seedver = db.versions.get_by_tag("p1", "v1.0.0")
    assert seedver and seedver.id == "ver1", f"seed version: {seedver}"
    print(f"    reads back                       : alice={alice.email}, "
          f"projects_for_u1={len(projs)}, p1={p1.name!r}, ver1.tag={seedver.tag!r}")

    from api.models.domain import Version
    now = datetime.datetime.now(datetime.timezone.utc)
    nv = Version("smoke1", "p1", "SMOKE-1.0", "deadbee", "main", "smoke test",
                 "draft", 0, "u1", now)
    db.versions.create(nv)
    got = db.versions.get_by_tag("p1", "SMOKE-1.0")
    assert got and got.id == "smoke1" and got.tag == "SMOKE-1.0", f"round-trip: {got}"
    print("    version write + read round-trip  : OK")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    from core.db import sanitize_dsn, DatabaseUnavailable, get_engine
    raw = os.environ.get("DATABASE_URL", "").strip()
    if not raw:
        print("Set DATABASE_URL first (a Postgres DSN).")
        return 1
    try:
        raw = sanitize_dsn(raw)
    except DatabaseUnavailable as exc:
        print(exc)
        return 1

    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    url = make_url(raw)
    if url.get_backend_name() != "postgresql":
        print("This check requires a Postgres DATABASE_URL.")
        return 1

    maint_dsn = url.set(database="postgres").render_as_string(hide_password=False)
    smoke_dsn = url.set(database=SMOKE_DB).render_as_string(hide_password=False)

    meng = create_engine(maint_dsn, connect_args={"connect_timeout": 5})

    def _drop(cx) -> None:
        # kill any lingering connections so DROP DATABASE can't be blocked
        cx.exec_driver_sql(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{SMOKE_DB}' AND pid <> pg_backend_pid()")
        cx.exec_driver_sql(f'DROP DATABASE IF EXISTS "{SMOKE_DB}"')

    try:
        with meng.connect() as cx:
            cx = cx.execution_options(isolation_level="AUTOCOMMIT")
            _drop(cx)
            cx.exec_driver_sql(f'CREATE DATABASE "{SMOKE_DB}"')
        print(f"created throwaway db             : {SMOKE_DB!r}")

        from api.db.postgres.database import SqlDatabase
        eng = get_engine(smoke_dsn)
        _validate(SqlDatabase(eng, create_schema=True))
        eng.dispose()
        print("\nOK - API repositories seed + round-trip on real Postgres.")
        return 0
    except Exception as exc:                             # noqa: BLE001
        print(f"\nFAILED: {type(exc).__name__}: {exc}")
        return 1
    finally:
        try:
            with meng.connect() as cx:
                cx = cx.execution_options(isolation_level="AUTOCOMMIT")
                _drop(cx)
            print(f"dropped throwaway db            : {SMOKE_DB!r}")
        except Exception as exc:                         # noqa: BLE001
            print(f"(cleanup note: could not drop {SMOKE_DB!r}: {exc})")


if __name__ == "__main__":
    raise SystemExit(main())
