"""
DB session — the single point where the concrete database is chosen.

**Postgres is the only real backend** (D-16). It is selected automatically as soon as a database
is configured — ``DATABASE_URL`` in the environment, or a ``db`` section in
``engine/config/config.local.json`` — so no env var is needed to run the product:

    uvicorn api.main:app --reload

``InMemoryDatabase`` survives ONLY as a test/dev seam (seed data, resets every restart) and is
used when no database is configured, or when ``API_DB_BACKEND=memory`` is set explicitly. It is
not a production option: nothing it holds is persisted, and the startup check in ``api/main.py``
says so loudly. The JSON-file backend (``JsonDatabase`` / ``api/db/data/*.json``) was removed in
the PG-7b cutover — D-7 "drop JsonDatabase", D-14 "zero JSON data".
"""
import os

from .in_memory import InMemoryDatabase

# ---------------------------------------------------------------------------
# Instantiate the database.
# Backend selection: API_DB_BACKEND env var wins ("memory" | "postgres"). When it is unset, use
# Postgres if a database is configured — DATABASE_URL env OR a `db` section in
# engine/config/config.local.json — else the in-memory test seam.
# ---------------------------------------------------------------------------
def _engine_on_path() -> None:
    import sys
    _eng = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "engine")
    if _eng not in sys.path:
        sys.path.insert(0, _eng)


def _db_configured() -> bool:
    if os.environ.get("DATABASE_URL", "").strip():
        return True
    try:
        _engine_on_path()
        from core.db import _dsn_from_config
        return bool(_dsn_from_config())
    except Exception:
        return False


_backend = os.environ.get("API_DB_BACKEND", "").lower().strip()
if not _backend:
    _backend = "postgres" if _db_configured() else "memory"


def _make_postgres():
    """The SQL backend over the process Postgres engine (engine/core/db.py owns the DSN).

    engine/ is added to sys.path so the API and the CLI resolve the same DSN. The
    engine is created lazily, so importing this module never requires a live DB —
    the fail-fast check belongs at app startup / first request, not import time.
    """
    import sys
    _engine_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "engine")
    if _engine_dir not in sys.path:
        sys.path.insert(0, _engine_dir)
    from .postgres.database import SqlDatabase
    return SqlDatabase()


# `postgres` is the product backend and is chosen automatically whenever a DB is configured.
# `memory` is the test/dev seam only — it persists nothing.
if _backend == "postgres":
    _db = _make_postgres()
else:
    _db = InMemoryDatabase()


def get_db():
    """FastAPI dependency — injects the shared DB instance into route handlers."""
    return _db
