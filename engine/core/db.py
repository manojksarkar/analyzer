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


def _db_section() -> dict:
    """The ``db`` section, read from ``config.local.json`` SPECIFICALLY (doc 10, step 1).

    Not from the merged config, and deliberately so. ``ANALYZER_CONFIG`` / ``--config`` REPLACES
    the config with a per-project one that carries no ``db`` section, so reading the merged
    config meant a phase subprocess saw no database and had to be told via ``DATABASE_URL``.
    Which database this machine talks to is a MACHINE-level setting, not a per-project one — so
    every process reads it from the same place, independently, and nothing has to be propagated.

    Falls back to the merged config so a ``db`` section placed in ``config.defaults.json``
    (or injected into a per-project config) still works.
    """
    from core.paths import paths
    from core.config import _strip_json_comments, _strip_trailing_commas
    import json as _json
    local = paths().config_local_path
    if os.path.isfile(local):
        with open(local, "r", encoding="utf-8") as fh:
            raw = _strip_trailing_commas(_strip_json_comments(fh.read()))
        db = (_json.loads(raw) or {}).get("db")
        if db:
            return db
    from core.config import load_config
    return load_config(paths().src_dir).get("db") or {}


def _sqlite_url(db: dict) -> Optional[str]:
    """A SQLite DSN from ``{"driver": "sqlite", "path": …}``, or None.

    SQLite is a first-class backend for local and internal testing (doc 10, D10-1) — the same
    code and the same schema serve it, because the schema is dialect-variant
    (``JSON().with_variant(JSONB(), "postgresql")``) and ``_insert_ignore`` is the only place
    the two differ. It is NOT for concurrency work: SQLite locks coarsely, so parallel jobs
    contend.

    A relative path resolves against the project root, so a config can say
    ``engine/config/analyzer-dev.db`` and mean it regardless of the working directory.
    """
    if str(db.get("driver", "")).strip().lower() not in ("sqlite", "sqlite3"):
        return None
    from core.paths import paths
    raw = str(db.get("path") or db.get("database") or "analyzer-dev.db")
    path = raw if os.path.isabs(raw) else os.path.join(paths().project_root, raw)
    return "sqlite:///" + os.path.abspath(path).replace("\\", "/")


def _dsn_from_config() -> Optional[str]:
    """Build a DSN from the ``db`` section of ``config.local.json``. None when unconfigured.

        "db": { "url": "postgresql+psycopg://analyzer:secret@10.0.0.9:5432/analyzer" }
        "db": { "url": "sqlite:///engine/config/analyzer-dev.db" }
        "db": { "driver": "sqlite", "path": "engine/config/analyzer-dev.db" }
        "db": { "driver": "postgresql+psycopg", "host": "10.0.0.9", "port": 5432,
                "user": "analyzer", "password": "secret", "database": "analyzer" }

    Precedence inside the section: ``url`` → ``driver: sqlite`` → host-based fields. ``url`` is
    the escape hatch for any backend SQLAlchemy supports without teaching this function its
    field names.

    Put credentials in ``engine/config/config.local.json`` (gitignored), never in
    ``config.defaults.json``, and never on a command line where ``ps`` would show them."""
    try:
        db = _db_section()
    except Exception as exc:
        # Say so instead of vanishing. Returning None here falls back to the compose default
        # (localhost), so a MALFORMED config.local.json used to be indistinguishable from a
        # MISSING one — the failure surfaced minutes later as a connection timeout against a
        # host nobody configured. §17 "fail loud on config errors" applies to the DSN too.
        import sys as _sys
        print(f"WARNING: could not read the 'db' section of config.local.json "
              f"({type(exc).__name__}: {exc}); falling back to the default DSN.",
              file=_sys.stderr)
        return None
    url = str(db.get("url") or "").strip()
    if url:
        return url
    sqlite = _sqlite_url(db)
    if sqlite:
        return sqlite
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


def is_database_configured() -> bool:
    """True when a database is configured — by `DATABASE_URL` **or** by the `db` section of
    `engine/config/config.local.json`.

    The single question every backend selector must ask. Historically they each tested
    ``os.environ.get("DATABASE_URL")`` directly, which made the env var the *only* way to turn
    Postgres on inside the engine: a standalone `run.py` / tools invocation fell back to the
    file store and silently wrote nothing to the database, even with a perfectly good `db`
    section in `config.local.json`. API-driven runs hid the problem, because the API resolves
    the DSN itself and injects `DATABASE_URL` into the subprocess.

    `config.local.json` is the configured home for the connection (root PROJECT_CONTEXT §6),
    so it must work on its own. `DATABASE_URL` still wins when set — it is how the API passes
    the DSN to a subprocess.

    Note this deliberately does NOT count the compose default: `database_url()` falls back to
    localhost so `docker compose up -d` needs no configuration, but "nothing is configured"
    must not read as "Postgres is on".
    """
    if os.environ.get("DATABASE_URL", "").strip():
        return True
    try:
        return bool(_dsn_from_config())
    except Exception:
        return False


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
    if url.startswith("sqlite"):
        # The API runs jobs on threads and hands the same Engine to each, so a connection
        # created on one thread WILL be used from another — SQLite rejects that by default.
        # `timeout` makes a writer wait for a competing write instead of failing instantly with
        # "database is locked"; SQLite still locks coarsely, so this makes single-job testing
        # reliable, not concurrent jobs fast (doc 10, D10-1).
        connect_args = {"check_same_thread": False, "timeout": CONNECT_TIMEOUT_SEC}
        _enforce_sqlite_foreign_keys()
    kwargs = dict(pool_pre_ping=True, future=True, connect_args=connect_args)
    from sqlalchemy import create_engine
    if dsn is not None:                       # explicit DSN -> caller-owned engine (tests)
        return create_engine(url, **kwargs)
    if _ENGINE is None:
        _ENGINE = create_engine(url, **kwargs)
    return _ENGINE


_FK_PRAGMA_INSTALLED = False


def _enforce_sqlite_foreign_keys() -> None:
    """Turn foreign keys ON for every SQLite connection.

    SQLite ignores foreign keys unless each connection asks for them, so `ondelete="CASCADE"`
    silently did nothing: deleting a version left its output files, entity rows and reuse
    pointers behind. Postgres cascaded correctly, which meant the SQLite backend — the one the
    gates and local testing run on — did not behave like production, and `check_db.py` found
    exactly that (26 orphan `version_output_files` rows).

    D10-2 is "one code path for both backends"; that has to include referential integrity.
    """
    global _FK_PRAGMA_INSTALLED
    if _FK_PRAGMA_INSTALLED:
        return
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    @event.listens_for(Engine, "connect")
    def _fk_on(dbapi_conn, _rec):
        try:
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
        except Exception:
            pass                      # not SQLite, or a driver that has no cursor() here
    _FK_PRAGMA_INSTALLED = True


def set_pipeline_status(status: str, *, version_id: Optional[str] = None) -> None:
    """Mark how far the run has got, on the version row (doc 09, C1 / D-17).

    ``versions.pipeline_status`` has existed since the migration but was never written, so
    the UI had to infer progress by scraping ``=== Phase N ===`` out of the log stream. A
    phase writing its own status is both simpler and correct across nodes.

    **Best-effort by design.** The version id comes from ``ANALYZER_VERSION_ID`` (set by the
    API per job) and is absent for a plain CLI run; there may be no database at all — the
    DB-less ``tools/verify_incremental.py`` gate runs the whole pipeline that way. Neither
    is an error, and a progress marker must never be the reason a pipeline dies, so every
    failure here is swallowed.

    Raw SQL on purpose: ``engine/core/`` is the bottom of the dependency graph, and the
    table definition lives two layers up in ``api/db/postgres/schema.py``. One UPDATE of one
    column needs no ORM and no upward import.
    """
    vid = version_id or os.environ.get("ANALYZER_VERSION_ID", "").strip()
    if not vid or not status:
        return
    try:
        from sqlalchemy import text
        with get_engine().begin() as cx:
            cx.execute(
                text("UPDATE versions SET pipeline_status = :s WHERE id = :v"),
                {"s": status, "v": vid},
            )
    except Exception:
        pass                                    # progress reporting never breaks a run


def reset_engine() -> None:
    """Drop the cached engine (tests that switch DSNs)."""
    global _ENGINE
    if _ENGINE is not None:
        try:
            _ENGINE.dispose()
        except Exception:
            pass
    _ENGINE = None


_LOCAL_HOSTS = frozenset(("localhost", "127.0.0.1", "::1", "0.0.0.0", ""))


def dsn_host_port(dsn: str) -> tuple:
    """(host, port) from a DSN, defaulting the port to 5432. ('', 5432) if unparseable."""
    try:
        rest = dsn.split("://", 1)[1]
        hostpart = rest.rsplit("@", 1)[-1].split("/", 1)[0]
        if hostpart.startswith("["):                      # IPv6 literal: [::1]:5432
            host, _, tail = hostpart[1:].partition("]")
            port = tail.lstrip(":")
        else:
            host, _, port = hostpart.partition(":")
        return host, int(port) if port.isdigit() else 5432
    except Exception:
        return "", 5432


def _unreachable_help(host: str, port: int, exc: Exception) -> str:
    """Advice that matches the ACTUAL failure, rather than one canned suggestion.

    The old message always said "docker compose up -d", which is wrong — and misleading —
    when the DSN points at a server on another machine: it sends you to inspect a local
    container that has nothing to do with the connection that failed.

    The distinction that matters is timeout vs refused. A **timeout** means the packets went
    nowhere and Postgres never saw the attempt (firewall DROP, unreachable host, blocked
    port). A **refusal** means something answered and nothing was listening on that port. They
    have completely different fixes, so they get completely different advice.
    """
    name, text = type(exc).__name__, str(exc).lower()
    timed_out = "timeout" in name.lower() or "timeout" in text
    refused = "refused" in text
    local = host in _LOCAL_HOSTS

    if local:
        return ("The analyzer requires PostgreSQL. To start it locally:\n"
                "    docker compose up -d\n"
                "Or point it at an existing server via the `db` section of "
                "engine/config/config.local.json.")

    lines = [f"The DSN points at a REMOTE server ({host}:{port}), so this is a connectivity "
             f"problem, not a local one - do NOT start a local container.", ""]
    if timed_out:
        lines += [
            "A TIMEOUT means nothing answered at all: the packets were dropped before they "
            "reached Postgres. Postgres itself never saw this attempt, so its own settings "
            "(user, password, pg_hba) are NOT the cause yet.",
            "",
            "Check, in this order:",
            f"  1. reachability from THIS machine:",
            f"       Windows : Test-NetConnection {host} -Port {port}",
            f"       Linux   : nc -vz {host} {port}",
            f"     Fails -> a firewall or the network is blocking it. Everything below is moot.",
            f"  2. on {host}: is the port published on all interfaces, not just loopback?",
            f"       docker ps                       # is a 0.0.0.0:{port}->{port} mapping shown?",
            f"       ss -lntp | grep {port}",
            f"  3. on {host}: host firewall",
            f"       sudo ufw status ; sudo ufw allow {port}/tcp",
            f"  4. corporate networks often block {port} between subnets - if 1 fails from "
            f"here but succeeds when run ON {host}, that is your answer.",
        ]
    elif refused:
        lines += [
            "A REFUSAL means the host answered but nothing is listening on that port.",
            f"  * on {host}: is the container running and the port published?",
            f"       docker ps ; ss -lntp | grep {port}",
            "  * a container started without -p publishes nothing outside itself.",
        ]
    else:
        lines += [
            "The host was reached, so this is most likely authentication or the database "
            "itself:",
            "  * user / password in the `db` section of engine/config/config.local.json",
            "  * pg_hba.conf on the server must allow this client's address",
            "  * the database may not exist yet -> python tools/db_setup.py",
        ]
    lines += ["", "Connection attempts give up after "
                  f"{CONNECT_TIMEOUT_SEC}s (raise DATABASE_CONNECT_TIMEOUT if the link is "
                  f"merely slow)."]
    return "\n".join(lines)


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
        host, port = dsn_host_port(target)
        raise DatabaseUnavailable(
            f"Cannot reach the database at {_redact(target)}\n"
            f"  reason: {type(exc).__name__}: {exc}\n"
            f"\n"
            f"{_unreachable_help(host, port, exc)}"
        ) from exc
