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
import unicodedata
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


# Zero-width / BOM characters that survive .strip() and silently corrupt a pasted DSN:
# ZWSP, ZWNJ, ZWJ, WORD JOINER, BOM/ZWNBSP.
_INVISIBLE = frozenset(chr(c) for c in (0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF))


def sanitize_dsn(raw: str) -> str:
    """Strip invisible junk from a (usually pasted) DSN and reject a look-alike scheme.

    Copy-pasting a DSN from chat/a doc/a PDF frequently injects zero-width or control
    characters, or a Unicode homoglyph (e.g. a Cyrillic 'о' for ASCII 'o'). Both leave the
    string *looking* correct while making SQLAlchemy compute a dialect name that is not
    'postgresql.psycopg' - producing a baffling ``NoSuchModuleError: postgresql.psycopg``
    even though psycopg is installed. Invisible characters are safe to drop; a non-ASCII
    character in the SCHEME cannot be repaired by guessing, so we fail with a message that
    names the culprit instead of letting the driver raise something opaque.
    """
    s = "".join(ch for ch in raw.strip()
                if ch not in _INVISIBLE and unicodedata.category(ch) not in ("Cc", "Cf"))
    scheme = s.split("://", 1)[0]
    bad = [(i, hex(ord(c))) for i, c in enumerate(scheme) if ord(c) > 126]
    if bad:
        raise DatabaseUnavailable(
            f"DATABASE_URL scheme contains non-ASCII character(s) at position(s) {bad}.\n"
            f"  scheme seen: {scheme!r}\n"
            f"  This is a hidden/look-alike character pasted into the DSN (it renders "
            f"identically to normal text but is not ASCII).\n"
            f"  Fix: delete DATABASE_URL and RE-TYPE it by hand - do not paste the DSN."
        )
    return s


def _dsn_from_config() -> Optional[str]:
    """Build a DSN from the ``db`` section of the merged engine config (``config.json`` +
    ``config.local.json``), so the connection can be configured in a file instead of the
    ``DATABASE_URL`` env var. Returns ``None`` when there is no ``db.host``.

        "db": { "driver": "postgresql+psycopg", "host": "10.0.0.5", "port": 5432,
                "user": "analyzer", "password": "secret", "database": "analyzer" }

    Put credentials in ``engine/config/config.local.json`` (gitignored), not ``config.json``.
    Skipped inside an engine phase subprocess (``ANALYZER_CONFIG`` set to a per-project config
    that carries no ``db`` section) — those inherit ``DATABASE_URL`` from the API instead."""
    try:
        from core.config import load_config
        from core.paths import paths
        db = load_config(paths().src_dir).get("db") or {}
    except Exception:                                    # config missing/unreadable -> no DSN
        return None
    host = db.get("host")
    if not host:
        return None
    from urllib.parse import quote
    driver = db.get("driver") or "postgresql+psycopg"
    user = quote(str(db.get("user", "")), safe="")
    pw = quote(str(db.get("password", "")), safe="")
    cred = f"{user}:{pw}@" if (user or pw) else ""
    port = db.get("port", 5432)
    name = db.get("database") or db.get("dbname") or "analyzer"
    return f"{driver}://{cred}{host}:{port}/{name}"


def database_url() -> str:
    """The DSN, resolved in priority order and sanitized:
    ``DATABASE_URL`` env var → the config ``db`` section → the compose default."""
    env = os.environ.get("DATABASE_URL", "").strip()
    if env:
        return sanitize_dsn(env)
    from_cfg = _dsn_from_config()
    return sanitize_dsn(from_cfg or DEFAULT_DSN)


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
    url = sanitize_dsn(dsn) if dsn is not None else database_url()
    # pool_pre_ping: phases are long-lived; a container restart would otherwise hand out a
    # dead connection mid-run. connect_timeout bounds an unreachable-DB failure to seconds -
    # but it is a libpq option, so only pass it to Postgres (SQLite would reject it).
    connect_args = {"connect_timeout": CONNECT_TIMEOUT_SEC} if url.startswith("postgres") else {}
    kwargs = dict(pool_pre_ping=True, future=True, connect_args=connect_args)
    from sqlalchemy import create_engine
    if dsn is not None:                       # explicit DSN -> caller-owned engine (tests)
        return create_engine(url, **kwargs)
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
