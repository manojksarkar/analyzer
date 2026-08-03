"""Alembic environment (docs/production-redesign/07, PG-1).

Targets the shared schema metadata and resolves the DB URL from the same place the
application does (engine/core/db.py), so migrations and runtime never disagree.
"""
import os
import sys

from alembic import context
from sqlalchemy import create_engine, pool

# Repo root on the path so `api.*` and `engine/core` import regardless of CWD.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "engine"))

from api.db.postgres.schema import metadata          # noqa: E402  (needs sys.path first)

try:
    from core.db import database_url                  # noqa: E402  canonical DSN
    _URL = database_url()
except Exception:                                     # engine import optional for offline SQL gen
    _URL = os.environ.get("DATABASE_URL", "").strip() \
        or "postgresql+psycopg://analyzer:analyzer@localhost:5432/analyzer"

target_metadata = metadata


def run_migrations_offline() -> None:
    context.configure(url=_URL, target_metadata=target_metadata,
                      literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Diagnostic: a `NoSuchModuleError: postgresql.psycopg` here means the SQLAlchemy
    # alembic runs lacks the psycopg dialect - almost always a DIFFERENT interpreter than
    # your `python`. These lines make alembic's actual environment visible so it can be
    # compared with `python tools/db_setup.py`.
    import sqlalchemy as _sa
    sys.stderr.write(f"[alembic] python     = {sys.executable}\n")
    sys.stderr.write(f"[alembic] sqlalchemy = {_sa.__version__} @ {os.path.dirname(_sa.__file__)}\n")
    sys.stderr.write(f"[alembic] url        = {_URL}\n")
    sys.stderr.flush()
    # Pass the DSN as a STRING (not a URL object): on SQLAlchemy 2.0.51 a URL object can
    # fail to resolve postgresql+psycopg (NoSuchModuleError) where the identical string
    # resolves fine. create_engine(<string>) is the proven path; engine_from_config could
    # re-wrap it into a URL object internally.
    connectable = create_engine(_URL, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
