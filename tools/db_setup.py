"""Create the database + schema, and print an environment diagnostic.

A Postgres SERVER hosts many named DATABASES; you can only connect to one that exists.
This connects to the always-present `postgres` maintenance database, creates the target
database if missing, then creates the schema in it. Idempotent.

It also prints exactly which Python / SQLAlchemy / driver is in use, which is what we need
to explain the alembic `NoSuchModuleError` (that error means the SQLAlchemy alembic runs
lacks the psycopg dialect - i.e. a different environment than this script).

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
    # Reproduce alembic's engine_from_config to see if THIS env has the dialect.
    from sqlalchemy import engine_from_config, pool
    try:
        engine_from_config({"sqlalchemy.url": "postgresql+psycopg://u:p@h:5432/d"},
                           prefix="sqlalchemy.", poolclass=pool.NullPool)
        print("  psycopg dialect (engine_from_config): OK")
    except Exception as exc:                        # noqa: BLE001
        print(f"  psycopg dialect (engine_from_config): FAILED -> {type(exc).__name__}: {exc}")
    print("=" * 60)


def main() -> int:
    _diagnostic()

    raw = os.environ.get("DATABASE_URL", "").strip()
    if not raw:
        print("\nDATABASE_URL is not set. Set it, e.g.:")
        print('    $env:DATABASE_URL = "postgresql+psycopg://user:pass@host:5432/analyzer"')
        return 1

    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    url = make_url(raw)
    print(f"\ntarget: {url.render_as_string(hide_password=True)}")

    if "<" in (url.database or "") or ">" in (url.database or ""):
        print(f"\n!! The database name is still a placeholder: {url.database!r}")
        print("   Put your REAL database name in DATABASE_URL (e.g. .../analyzer).")
        return 1

    from api.db.postgres.schema import metadata

    if url.get_backend_name() == "postgresql":
        # 1. ensure the target database exists (via the maintenance 'postgres' db)
        maint = url.set(database="postgres")
        try:
            meng = create_engine(maint, connect_args={"connect_timeout": 5},
                                 isolation_level="AUTOCOMMIT")
            with meng.connect() as cx:
                existing = [r[0] for r in cx.execute(
                    text("SELECT datname FROM pg_database WHERE datistemplate = false"))]
                print(f"databases on server: {existing}")
                if url.database not in existing:
                    cx.exec_driver_sql(f'CREATE DATABASE "{url.database}"')
                    print(f"created database: {url.database!r}")
                else:
                    print(f"database already exists: {url.database!r}")
        except Exception as exc:                    # noqa: BLE001
            print(f"\nCould not reach the server / create the database: "
                  f"{type(exc).__name__}: {exc}")
            print("  - is the db user allowed to connect to 'postgres' and CREATE DATABASE?")
            return 1

    # 2. create the schema in the target database
    eng = create_engine(url, connect_args=({"connect_timeout": 5}
                                           if url.get_backend_name() == "postgresql" else {}))
    metadata.create_all(eng)
    print(f"\nschema created: {len(metadata.tables)} tables in {url.database!r}")
    print("\nOK - now run:  python tools\\verify_db_sync.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
