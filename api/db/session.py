"""
DB session — the single point where the concrete database is chosen.

Backend selection
-----------------
Set the environment variable ``API_DB_BACKEND`` before starting the server:

    API_DB_BACKEND=memory   uvicorn api.main:app --reload   # default
    API_DB_BACKEND=json     uvicorn api.main:app --reload

``memory``  — InMemoryDatabase (seed data only; resets on every restart).
``json``    — JsonDatabase (persists to api/db/data/*.json; loads pipeline
              output from model/functions.json automatically on startup).

To swap via code instead of an env var, change the ``_db`` assignment below
(the original one-line swap contract is preserved):

    _db = JsonDatabase()      # or InMemoryDatabase()
"""
import os

from .in_memory import InMemoryDatabase
from .json_db import JsonDatabase

# ---------------------------------------------------------------------------
# Instantiate the database.
# Change API_DB_BACKEND env var (or replace this block) to switch backends.
# ---------------------------------------------------------------------------
_backend = os.environ.get("API_DB_BACKEND", "memory").lower().strip()


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


# `memory` (default) and `json` remain for tests/dev; `postgres` is the production
# backend. The default flips to `postgres` once validated against a live server
# (kept opt-in here because it cannot be exercised without one).
if _backend == "postgres":
    _db = _make_postgres()
elif _backend == "json":
    _db = JsonDatabase()
else:
    _db = InMemoryDatabase()


def get_db():
    """FastAPI dependency — injects the shared DB instance into route handlers."""
    return _db
