"""Database connection for the engine (docs/production-redesign/07, PG-0).

Postgres is **required** — there is no file-backed fallback (D-16). The pipeline's
phases run as separate subprocesses, so each resolves the DSN from the environment
rather than inheriting a connection.

The one rule worth stating: when the database is unreachable we fail **fast and
legibly**. A pipeline that half-runs and then dies on an obscure driver traceback
is far worse than one that refuses to start with an actionable message.

Usage
-----
    from core.db import get_engine, require_database
    require_database()                  # call once at entry; raises DatabaseUnavailable
    with get_engine().connect() as cx:  # normal SQLAlchemy from here
        ...
"""
from __future__ import annotations

import os
from typing import Optional

# Matches docker-compose.yml, so `docker compose up -d` needs no extra configuration.
DEFAULT_DSN = "postgresql+psycopg://analyzer:analyzer@localhost:5432/analyzer"

# Seconds to wait for a TCP connect before giving up. Without this libpq can stall
# for minutes on an unreachable host (measured: >120s), which defeats the whole
# point of a fail-fast check and drags the test suite with it.
CONNECT_TIMEOUT_SEC = int(os.environ.get("DATABASE_CONNECT_TIMEOUT", "5") or 5)

_ENGINE = None  # lazily created; a process-wide singleton (SQLAlchemy pools internally)


class DatabaseUnavailable(RuntimeError):
    """Raised when the database cannot be reached — carries operator instructions."""


def database_url() -> str:
    """The DSN from ``DATABASE_URL``, else the compose default."""
    return os.environ.get("DATABASE_URL", "").strip() or DEFAULT_DSN


def _redact(dsn: str) -> str:
    """Hide the password so a DSN can appear in logs and error messages."""
    if "://" not in dsn or "@" not in dsn:
        return dsn
    scheme, rest = dsn.split("://", 1)
    creds, host = rest.rsplit("@", 1)
    user = creds.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"


def get_engine(dsn: Optional[str] = None):
    """Process-wide SQLAlchemy Engine (created on first use)."""
    global _ENGINE
    url = dsn if dsn is not None else database_url()
    # pool_pre_ping: phases are long-lived; a container restart would otherwise hand out a
    # dead connection mid-run. connect_timeout bounds an unreachable-DB failure to seconds -
    # but it is a libpq option, so only pass it to Postgres (SQLite would reject it).
    connect_args = {"connect_timeout": CONNECT_TIMEOUT_SEC} if url.startswith("postgres") else {}
    kwargs = dict(pool_pre_ping=True, future=True, connect_args=connect_args)
    from sqlalchemy import create_engine
    if dsn is not None:                       # explicit DSN -> caller-owned engine (tests)
        return create_engine(dsn, **kwargs)
    if _ENGINE is None:
        _ENGINE = create_engine(url, **kwargs)
    return _ENGINE


def reset_engine() -> None:
    """Drop the cached engine (tests that switch DSNs)."""
    global _ENGINE
    if _ENGINE is not None:
        try:
            _ENGINE.dispose()
        except Exception:
            pass
    _ENGINE = None


def require_database(dsn: Optional[str] = None) -> None:
    """Verify the database is reachable, or raise :class:`DatabaseUnavailable`.

    Call at the start of any entry point that will touch the DB. The message is
    written for whoever is running the tool, not for a stack trace reader.
    """
    target = dsn or database_url()
    try:
        from sqlalchemy import text
        engine = get_engine(dsn) if dsn else get_engine()
        with engine.connect() as cx:
            cx.execute(text("SELECT 1"))
    except Exception as exc:                              # driver/network/auth all land here
        raise DatabaseUnavailable(
            f"Cannot reach the database at {_redact(target)}\n"
            f"  reason: {type(exc).__name__}: {exc}\n"
            f"\n"
            f"The analyzer requires PostgreSQL. To start it:\n"
            f"    docker compose up -d\n"
            f"Or point DATABASE_URL at an existing server:\n"
            f"    set DATABASE_URL=postgresql+psycopg://user:pass@host:5432/dbname"
        ) from exc
