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


def _add_missing_columns(eng, metadata):
    """Add columns the schema declares but the live tables lack. Returns (added, blocked).

    Only **additive** and only where it is safe: a column is added when it is nullable or has a
    server default, because those are the only kinds a table with existing rows can accept. A
    NOT NULL column with no default is reported rather than attempted -- guessing a backfill
    value is how a schema repair turns into a data corruption.

    Nothing is ever dropped or retyped. A column that is live but not in the schema is left
    alone: it belongs to a newer branch, or to a migration somebody is mid-way through, and
    dropping it here would delete data to make a tool's output tidy.
    """
    from sqlalchemy import inspect
    from sqlalchemy.schema import CreateColumn

    insp = inspect(eng)
    live_tables = set(insp.get_table_names())
    prep = eng.dialect.identifier_preparer
    added, blocked = [], []

    for table in metadata.sorted_tables:
        if table.name not in live_tables:
            continue                       # create_all just made it, whole
        live_cols = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in live_cols:
                continue
            where = f"{table.name}.{col.name}"
            if not col.nullable and col.server_default is None:
                blocked.append(f"{where} ({col.type})")
                continue
            ddl = CreateColumn(col).compile(dialect=eng.dialect)
            with eng.begin() as cx:
                cx.exec_driver_sql(
                    f"ALTER TABLE {prep.format_table(table)} ADD COLUMN {ddl}")
            added.append(f"{where} ({col.type})")
    return added, blocked


def main() -> int:
    try:  # keep a homoglyph/non-ASCII DSN from crashing prints on a cp1252 console
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    _diagnostic()

    # Resolve the DSN: DATABASE_URL env -> the config `db` section -> the compose default.
    # database_url() also sanitizes (strips invisible/homoglyph chars; raises on a bad scheme).
    from core.db import database_url, _redact, DatabaseUnavailable
    # --sqlite <path>: create a local SQLite database and print the config line to paste.
    # For internal testing on a machine with no Postgres (doc 10, D10-1) — one code path, so
    # every gate that needs a database becomes runnable there.
    if "--sqlite" in sys.argv:
        i = sys.argv.index("--sqlite")
        target = sys.argv[i + 1] if i + 1 < len(sys.argv) else "engine/config/analyzer-dev.db"
        target = os.path.abspath(target)
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        raw = "sqlite:///" + target.replace("\\", "/")
        print(f"creating SQLite database: {target}")
        from sqlalchemy import create_engine as _ce
        from api.db.postgres.schema import metadata as _md
        _md.create_all(_ce(raw))
        print(f"\nschema created: {len(_md.tables)} tables")
        print("\nAdd this to engine/config/config.local.json:\n")
        print('  { "db": { "url": "%s" } }\n' % raw)
        return 0

    try:
        raw = database_url()
    except DatabaseUnavailable as exc:               # e.g. a non-ASCII scheme
        print(f"\n{exc}")
        return 1
    print(f"using DSN: {_redact(raw)}   (set DATABASE_URL or engine/config/config.local.json 'db')")

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
                  f"{type(exc).__name__}: {exc}\n")
            try:
                from core.db import dsn_host_port, _unreachable_help
                host, port = dsn_host_port(raw)
                print(_unreachable_help(host, port, exc))
            except Exception:
                pass
            print("\n  - if the server IS reachable: can this user connect to 'postgres' "
                  "and CREATE DATABASE?")
            return 1

    eng = create_engine(raw, connect_args=ca)       # target engine - dialect resolved here

    # 2. import the schema only NOW (engine already built) and create the tables
    from api.db.postgres.schema import metadata
    metadata.create_all(eng)
    print(f"\nschema created: {len(metadata.tables)} tables")

    # 2b. add columns that exist in the schema but not in the live table.
    #
    # `create_all()` creates MISSING TABLES and nothing else -- it never alters one that is
    # already there. So on a database that has been used before, every migration that adds a
    # column to an existing table is silently skipped, and the mismatch surfaces much later as
    # `UndefinedColumn: column model_units.description does not exist` in the middle of a run,
    # from a SELECT that names every column the schema declares.
    #
    # That is exactly what happened with `0009_model_units_description`: the three new TABLES on
    # that branch appeared, so the setup looked like it had worked, and the one new COLUMN did
    # not. A fresh database hides it completely, which is why it reached an office machine.
    #
    # This is not a replacement for Alembic -- `alembic upgrade head` remains the migration
    # path. It is what makes `analyzer.py setup` honest about the word "upgrade" on a database
    # whose tables were made by `create_all` and which therefore may have no usable
    # `alembic_version` to upgrade FROM.
    print()
    added, blocked = _add_missing_columns(eng, metadata)
    if added:
        for line in added:
            print(f"  added missing column: {line}")
        print(f"schema upgraded: {len(added)} column(s) added")
    else:
        print("schema up to date: no missing columns")
    if blocked:
        print("\n!! These columns are declared NOT NULL with no default, so they cannot be")
        print("   added to a table that already has rows. Run the migration instead:")
        print("       python -m alembic upgrade head")
        for line in blocked:
            print(f"     - {line}")
        return 1

    # 3. repair rows stranded mid-phase (idempotent).
    #
    # versions.pipeline_status was introduced unwritten, so NULL meant "finished" and
    # pg_stores.list_versions accepts NULL or 'complete' as baseline-eligible. When the
    # per-phase writer landed, runs began recording parsing/deriving/viewing/exporting but
    # nothing wrote a terminal state - so every FINISHED run stayed at its last phase and was
    # permanently refused as a baseline. The symptom is severe and silent: every later run
    # falls back to a full generation and reports 0% reuse.
    #
    # The writer is fixed, but that fix is forward-only; rows already written are still
    # stranded. A run that reached a real review status ('draft' means reserved-but-never-
    # generated) did finish, so it is safe to close out here.
    from sqlalchemy import text
    with eng.begin() as cx:
        # projects.updated_at was never written by CLI onboarding, and the API's project view
        # calls .isoformat() on it -- so one such row made `GET /projects` answer 500 for the
        # WHOLE list. The reader is null-safe now; this repairs the rows already written, since
        # a fix that only helps projects onboarded from today is not a fix for this database.
        m = cx.execute(text("UPDATE projects SET updated_at = created_at "
                            "WHERE updated_at IS NULL")).rowcount
        if m:
            print(f"repaired {m} project row(s) with no updated_at -> created_at")

        # The operator account. `is_superuser` arrives as `false` for every existing row, so a
        # database that has been in use would come back from this upgrade with NOBODY able to
        # reach a project -- the column would be there and mean nothing.
        #
        # Only when there is no superuser at all: once somebody has chosen who the operators
        # are, re-running setup must not quietly add another.
        if not cx.execute(text("SELECT 1 FROM users WHERE is_superuser")).first():
            k = cx.execute(text("UPDATE users SET is_superuser = %s WHERE email = 'admin@aspice.dev'"
                                % ("true" if is_pg else "1"))).rowcount
            if k:
                print("promoted admin@aspice.dev to superuser (access to every project)")

        # And give every superuser a membership row on every project. Access does not DEPEND on
        # these -- `require_project_member` lets a superuser through without one, which is what
        # makes it reliable -- but the team list and `my_role` are read from them, so without
        # this the operator appears on no team and the UI greys out controls the API honours.
        j = cx.execute(text(
            "INSERT INTO project_members (id, project_id, user_id, role, status, "
            "                             invited_by, invited_at, joined_at) "
            "SELECT 'm-su-' || u.id || '-' || p.id, p.id, u.id, 'admin', 'active', "
            "       u.id, p.created_at, p.created_at "
            "  FROM users u CROSS JOIN projects p "
            " WHERE u.is_superuser "
            "   AND NOT EXISTS (SELECT 1 FROM project_members m "
            "                    WHERE m.project_id = p.id AND m.user_id = u.id)")).rowcount
        if j:
            print(f"added {j} superuser membership row(s) across existing projects")

        n = cx.execute(text(
            "UPDATE versions SET pipeline_status = 'complete' "
            "WHERE pipeline_status IN ('parsing','deriving','viewing','exporting') "
            "  AND status IS NOT NULL AND status <> 'draft'")).rowcount
    if n:
        print(f"repaired {n} version row(s) stranded mid-phase -> 'complete' "
              f"(they are baseline-eligible again; reuse will work on the next run)")

    print("\nOK - now run:  python tools\\verify_db_sync.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
