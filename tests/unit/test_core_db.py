"""Unit tests for engine/core/db.py (docs/production-redesign/07, PG-0).

No live database required: these cover DSN resolution, credential redaction and —
most importantly — that an unreachable database fails **fast with an actionable
message** rather than an obscure driver traceback (D-16).
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from core.db import (DEFAULT_DSN, DatabaseUnavailable, _redact, database_url,
                     require_database, reset_engine)

# A port nothing listens on, so the connection fails immediately.
UNREACHABLE = "postgresql+psycopg://analyzer:secret@127.0.0.1:59999/analyzer"


class TestDsnResolution:
    def test_defaults_to_compose_dsn(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setattr("core.db._dsn_from_config", lambda: None)   # no config db section
        assert database_url() == DEFAULT_DSN

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/x")
        assert database_url() == "postgresql+psycopg://u:p@db:5432/x"

    def test_blank_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "   ")
        monkeypatch.setattr("core.db._dsn_from_config", lambda: None)
        assert database_url() == DEFAULT_DSN

    def test_config_db_section_used_when_env_unset(self, monkeypatch):
        # DATABASE_URL unset -> the config `db` section (built into a DSN by _dsn_from_config) wins
        # over the default; env still overrides config when present.
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setattr("core.db._dsn_from_config",
                            lambda: "postgresql+psycopg://cu:cp@confhost:5432/cdb")
        assert database_url() == "postgresql+psycopg://cu:cp@confhost:5432/cdb"
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://eu:ep@envhost:5432/edb")
        assert database_url() == "postgresql+psycopg://eu:ep@envhost:5432/edb"


class TestRedaction:
    def test_password_hidden_but_user_and_host_kept(self):
        out = _redact("postgresql+psycopg://analyzer:s3cret@localhost:5432/analyzer")
        assert "s3cret" not in out
        assert "analyzer" in out and "localhost:5432" in out

    def test_tolerates_dsn_without_credentials(self):
        assert _redact("postgresql:///analyzer") == "postgresql:///analyzer"


class TestFailFast:
    def test_unreachable_local_database_raises_actionable_error(self, monkeypatch):
        """A LOCAL host: the fix really is to start the local container."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        reset_engine()
        with pytest.raises(DatabaseUnavailable) as excinfo:
            require_database(UNREACHABLE)
        msg = str(excinfo.value)
        # The operator must be told what to DO, not just what broke.
        assert "docker compose up -d" in msg
        # config.local.json is the configured home for the connection, so the advice names
        # it rather than DATABASE_URL (which it used to, before config became the norm).
        assert "config.local.json" in msg
        assert "127.0.0.1:59999" in msg          # which server was tried
        assert "secret" not in msg               # ...without leaking the password

    def test_unreachable_remote_database_does_not_advise_a_local_container(self, monkeypatch):
        """A REMOTE host must get connectivity advice, not "docker compose up -d".

        Telling someone to start a local container when their DSN points at another machine
        sends them to inspect something unrelated to the connection that failed — which is
        exactly what happened with a pgvector server on a separate host.
        """
        monkeypatch.delenv("DATABASE_URL", raising=False)
        reset_engine()
        remote = "postgresql+psycopg://analyzer:secret@203.0.113.9:59999/analyzer"
        with pytest.raises(DatabaseUnavailable) as excinfo:
            require_database(remote)
        msg = str(excinfo.value)
        assert "docker compose up -d" not in msg
        assert "203.0.113.9:59999" in msg
        assert "REMOTE" in msg
        assert "secret" not in msg

    def test_operator_advice_is_ascii_only(self, monkeypatch):
        """PROJECT_CONTEXT §18: this text prints to a Windows cp1252 console, where a single
        non-ASCII character renders as a replacement glyph (and can raise). Caught in review
        when an em-dash came out as garbage on the office machine."""
        from core.db import _unreachable_help
        for host in ("localhost", "203.0.113.9"):
            for exc in (TimeoutError("connection timeout expired"),
                        OSError("connection refused"),
                        RuntimeError("password authentication failed")):
                text = _unreachable_help(host, 5432, exc)
                bad = [(i, hex(ord(c))) for i, c in enumerate(text) if ord(c) > 126]
                assert not bad, f"non-ASCII in operator advice for {host}: {bad[:3]}"

    def test_failure_is_fast(self, monkeypatch):
        """An unreachable DB must report in seconds, not stall the run.

        Regression guard: without connect_timeout, libpq stalled >120s here, which
        both defeats the fail-fast contract and drags the whole suite.
        """
        import time
        monkeypatch.delenv("DATABASE_URL", raising=False)
        reset_engine()
        started = time.monotonic()
        with pytest.raises(DatabaseUnavailable):
            require_database(UNREACHABLE)
        assert time.monotonic() - started < 30


class TestARunWaitsForTheDatabase:
    """A connection that timed out on a busy server failed a whole component of a run
    (2026-10-04, `ConnectionTimeout` in Phase 3 under load). A run's engine tries again."""

    def _engine(self, monkeypatch, behaviour):
        import sqlalchemy as sa
        from core import db as core_db
        monkeypatch.setattr(core_db, "CONNECT_RETRIES", (0, 0, 0))
        engine = sa.create_engine("sqlite://")
        core_db.retry_connects(engine)
        real, calls = engine.dialect.connect, []

        def connect(*a, **k):
            calls.append(1)
            behaviour(len(calls))
            return real(*a, **k)
        monkeypatch.setattr(engine.dialect, "connect", connect)
        return engine, calls

    def test_a_connection_refused_twice_is_made_on_the_third_try(self, monkeypatch):
        import sqlite3
        import sqlalchemy as sa

        def behaviour(n):
            if n < 3:
                raise sqlite3.OperationalError("connection timeout expired")
        engine, calls = self._engine(monkeypatch, behaviour)
        with engine.connect() as cx:
            assert cx.execute(sa.text("select 1")).scalar() == 1
        assert len(calls) == 3

    def test_it_gives_up_after_the_last_wait(self, monkeypatch):
        import sqlite3

        def behaviour(n):
            raise sqlite3.OperationalError("connection refused")
        engine, calls = self._engine(monkeypatch, behaviour)
        with pytest.raises(Exception, match="connection refused"):
            engine.connect()
        assert len(calls) == 4                              # the first try and three more

    def test_anything_else_is_not_tried_again(self, monkeypatch):
        def behaviour(n):
            raise ValueError("a bug")
        engine, calls = self._engine(monkeypatch, behaviour)
        with pytest.raises(Exception, match="a bug"):
            engine.connect()
        assert len(calls) == 1

    def test_twice_on_one_engine_is_one_listener(self, monkeypatch):
        """A second listener would try every refused connection 5 x 5 times."""
        import sqlite3
        from core import db as core_db

        def behaviour(n):
            raise sqlite3.OperationalError("connection refused")
        engine, calls = self._engine(monkeypatch, behaviour)
        core_db.retry_connects(engine)
        with pytest.raises(Exception, match="connection refused"):
            engine.connect()
        assert len(calls) == 4

    def test_the_cli_s_engine_made_before_the_run_tries_again_too(self, monkeypatch):
        """analyzer.py reads the database before it sets ANALYZER_VERSION_ID, so its engine was
        made without retries -- and the run's own work used it (review 2026-10-04)."""
        import sqlalchemy as sa
        from core import db as core_db
        engine = sa.create_engine("postgresql+psycopg://u@localhost/x")
        monkeypatch.setattr(core_db, "_ENGINE", engine)
        assert engine not in core_db._RETRYING
        core_db.retry_connects_for_run()
        assert engine in core_db._RETRYING

    def test_the_writer_lock_s_own_engine_tries_again(self, monkeypatch):
        import sqlalchemy as sa
        from core import db as core_db
        from core.version_run import _LockSession
        lock = _LockSession(sa.create_engine("postgresql+psycopg://u@localhost/x"), "v1", "test")
        assert lock._engine in core_db._RETRYING
