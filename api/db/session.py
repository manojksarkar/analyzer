"""
DB session — the single point where the concrete database is chosen.

To swap the storage backend, change ONE import here and nothing else.
"""
from .in_memory import InMemoryDatabase

# ---------------------------------------------------------------------------
# Instantiate the database.
# Replace this line to switch to Postgres, SQLite, etc.
# ---------------------------------------------------------------------------
_db = InMemoryDatabase()


def get_db() -> InMemoryDatabase:
    """FastAPI dependency — injects the shared DB instance into route handlers."""
    return _db
