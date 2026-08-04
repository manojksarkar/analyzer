"""Pinpoint exactly what breaks `postgresql.psycopg` dialect resolution on this machine.

No database is needed - create_engine() does not connect, it only resolves the dialect.
Run it and paste the ENTIRE output:

    python tools/diag_dialect.py

At each step it reports whether create_engine still resolves the dialect, the SQLAlchemy
in use, and the dialect registry's identity + contents. The step where `create_engine`
flips from OK to NoSuchModuleError is the culprit; a change in `id(registry)` means the
registry object was replaced (a re-import), a change in the sqlalchemy path means a second
install shadowed the first.
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DSN = "postgresql+psycopg://u:p@h:5432/d"


def probe(label: str) -> None:
    import sqlalchemy
    from sqlalchemy import create_engine
    from sqlalchemy.dialects import registry
    impls = getattr(registry, "impls", {})
    has = "postgresql.psycopg" in impls
    pg = sorted(k for k in impls if k.startswith("postgresql"))
    try:
        create_engine(DSN)
        ce = "OK"
    except Exception as exc:                        # noqa: BLE001
        ce = f"{type(exc).__name__}: {exc}"
    print(f"[{label}]")
    print(f"    sqlalchemy    : {sqlalchemy.__version__} @ {os.path.dirname(sqlalchemy.__file__)}")
    print(f"    id(registry)  : {id(registry)}   impls={len(impls)}   has psycopg={has}")
    print(f"    postgresql.*  : {pg}")
    print(f"    create_engine : {ce}")
    print()


def main() -> int:
    probe("0 fresh - nothing imported from the repo")

    sys.path[:0] = [_ROOT, os.path.join(_ROOT, "engine")]
    print("sys.path[:4] =", sys.path[:4], "\n")
    probe("1 after prepending repo root + engine/ to sys.path")

    from sqlalchemy.dialects.postgresql import JSONB  # noqa: F401  (what schema.py does)
    probe("2 after 'from sqlalchemy.dialects.postgresql import JSONB'")

    import api  # noqa: F401
    probe("3 after 'import api'")

    import api.db  # noqa: F401  (runs api/db/__init__.py -> session.py backend chain)
    probe("4 after 'import api.db'  (session.py + backends)")

    from api.db.postgres import schema  # noqa: F401
    probe("5 after 'from api.db.postgres import schema'")

    from sqlalchemy.engine import make_url
    _ = make_url(DSN).set(database="postgres").render_as_string(hide_password=False)
    probe("6 after make_url(...).set(...).render_as_string()")

    # ---- REAL-DSN probe: test the EXACT strings db_setup hands to create_engine ----
    # The step-probes above pass a clean hardcoded string; db_setup passes the
    # render_as_string() output of make_url(raw).set(database="postgres"). This section
    # tests that actual value. Passwords are masked in every printed line.
    raw = os.environ.get("DATABASE_URL", "").strip()
    print("=" * 60)
    print("REAL-DSN PROBE (uses your DATABASE_URL)")
    if not raw:
        print("    DATABASE_URL not set - set it and re-run to test the real path:")
        print('    $env:DATABASE_URL = "postgresql+psycopg://user:pass@host:5432/analyzer"')
        return 0

    from sqlalchemy import create_engine

    def mask(s: str) -> str:
        try:
            return make_url(s).render_as_string(hide_password=True)
        except Exception as exc:                    # noqa: BLE001
            return f"<make_url FAILED: {type(exc).__name__}: {exc}>"

    def try_ce(label: str, arg, **kw) -> None:
        try:
            create_engine(arg, **kw)
            print(f"    create_engine({label}) -> OK")
        except Exception as exc:                     # noqa: BLE001
            print(f"    create_engine({label}) -> {type(exc).__name__}: {exc}")

    u = make_url(raw)
    maint = u.set(database="postgres").render_as_string(hide_password=False)
    print(f"    raw   drivername      : {u.drivername!r}")     # repr exposes hidden chars
    print(f"    raw   (masked)        : {mask(raw)}")
    print(f"    maint drivername      : {make_url(maint).drivername!r}")
    print(f"    maint (masked)        : {mask(maint)}")
    print()
    try_ce("raw string", raw)
    try_ce("maint rendered string", maint)
    try_ce("maint rendered + connect_args", maint, connect_args={"connect_timeout": 5})
    try_ce("URL object .set(db=postgres)", u.set(database="postgres"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
