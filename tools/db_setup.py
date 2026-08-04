"""Create the database + schema, and print an environment diagnostic.

A Postgres SERVER hosts many named DATABASES; you can only connect to one that exists.
This connects to the always-present `postgres` maintenance database, creates the target
database if missing, then creates the schema in it. Idempotent.

IMPORTANT (learned the hard way on SQLAlchemy 2.0.51): pass **string** DSNs to
create_engine, never a make_url() URL object - on some SQLAlchemy builds a URL object
fails to resolve the `postgresql+psycopg` dialect (NoSuchModuleError) while the exact same
DSN as a string resolves fine. So every create_engine here gets a string.

    $env:DATABASE_URL = "postgresql+psycopg://user:pass@host:5432/analyzer"
    python tools/db_setup.py
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, "engine")]


def _diagnostic() -> None:
    import sqlalchemy
    print("=" * 60)
    print("ENVIRONMENT")
    print(f"  python     : {sys.executable}")
    print(f"  sqlalchemy : {sqlalchemy.__version__}   ({os.path.dirname(sqlalchemy.__file__)})")
    try:
        import psycopg
        print(f"  psycopg    : {psycopg.__version__}   ({os.path.dirname(psycopg.__file__)})")
    except Exception as exc:                        # noqa: BLE001
        print(f"  psycopg    : NOT IMPORTABLE -> {type(exc).__name__}: {exc}")
    print("=" * 60)


def _maint_dsn(raw: str) -> tuple[str, str]:
    """(maintenance DSN string -> the 'postgres' db, target database name). Uses make_url
    only to REBUILD strings - the strings, not the URL object, are what we hand out."""
    from sqlalchemy.engine import make_url
    url = make_url(raw)
    target_db = url.database or ""
    maint = url.set(database="postgres").render_as_string(hide_password=False)
    return maint, target_db


def main() -> int:
    try:  # keep a homoglyph/non-ASCII DSN from crashing prints on a cp1252 console
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    _diagnostic()

    raw = os.environ.get("DATABASE_URL", "").strip()
    if not raw:
        print("\nDATABASE_URL is not set. Set it, e.g.:")
        print('    $env:DATABASE_URL = "postgresql+psycopg://user:pass@host:5432/analyzer"')
        return 1

    # Sanitize the DSN: a pasted DATABASE_URL often carries an invisible/look-alike character
    # (a zero-width space, or a homoglyph such as a Cyrillic 'о' for ASCII 'o') that makes
    # SQLAlchemy fail with a baffling NoSuchModuleError: postgresql.psycopg. sanitize_dsn drops
    # invisibles and, for an unrepairable non-ASCII scheme, raises a clear "re-type it" error.
    try:
        from core.db import sanitize_dsn
        raw = sanitize_dsn(raw)
    except Exception as exc:                         # DatabaseUnavailable (bad scheme) etc.
        print(f"\n{exc}")
        return 1

    from sqlalchemy import create_engine, text

    is_pg = raw.startswith("postgres")
    ca = {"connect_timeout": 5} if is_pg else {}

    # Build the engines BEFORE importing api.* / schema (a defensive ordering: an engine
    # resolves and caches its dialect at creation, so create_all() below is unaffected by
    # whatever the import chain does afterwards).
    if is_pg:
        maint_dsn, target_db = _maint_dsn(raw)
        if "<" in target_db or ">" in target_db:
            print(f"\n!! The database name is still a placeholder: {target_db!r}")
            print("   Put your REAL database name in DATABASE_URL (e.g. .../analyzer).")
            return 1
        print(f"\ntarget database: {target_db!r}")
        # 1. ensure the target database exists (via the maintenance 'postgres' db)
        try:
            meng = create_engine(maint_dsn, connect_args=ca)          # STRING dsn
            with meng.connect() as cx:
                cx = cx.execution_options(isolation_level="AUTOCOMMIT")  # CREATE DATABASE needs it
                existing = [r[0] for r in cx.execute(
                    text("SELECT datname FROM pg_database WHERE datistemplate = false"))]
                print(f"databases on server: {existing}")
                if target_db not in existing:
                    cx.exec_driver_sql(f'CREATE DATABASE "{target_db}"')
                    print(f"created database: {target_db!r}")
                else:
                    print(f"database already exists: {target_db!r}")
        except Exception as exc:                    # noqa: BLE001
            print(f"\nCould not reach the server / create the database: "
                  f"{type(exc).__name__}: {exc}")
            print("  - can this user connect to 'postgres' and CREATE DATABASE?")
            return 1

    eng = create_engine(raw, connect_args=ca)       # target engine - dialect resolved here

    # 2. import the schema only NOW (engine already built) and create the tables
    from api.db.postgres.schema import metadata
    metadata.create_all(eng)
    print(f"\nschema created: {len(metadata.tables)} tables")
    print("\nOK - now run:  python tools\\verify_db_sync.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
