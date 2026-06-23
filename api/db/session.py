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

if _backend == "json":
    _db: InMemoryDatabase | JsonDatabase = JsonDatabase()
else:
    _db = InMemoryDatabase()


def get_db() -> InMemoryDatabase | JsonDatabase:
    """FastAPI dependency — injects the shared DB instance into route handlers."""
    return _db
