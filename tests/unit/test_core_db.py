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
        assert database_url() == DEFAULT_DSN

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/x")
        assert database_url() == "postgresql+psycopg://u:p@db:5432/x"

    def test_blank_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "   ")
        assert database_url() == DEFAULT_DSN


class TestRedaction:
    def test_password_hidden_but_user_and_host_kept(self):
        out = _redact("postgresql+psycopg://analyzer:s3cret@localhost:5432/analyzer")
        assert "s3cret" not in out
        assert "analyzer" in out and "localhost:5432" in out

    def test_tolerates_dsn_without_credentials(self):
        assert _redact("postgresql:///analyzer") == "postgresql:///analyzer"


class TestFailFast:
    def test_unreachable_database_raises_actionable_error(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        reset_engine()
        with pytest.raises(DatabaseUnavailable) as excinfo:
            require_database(UNREACHABLE)
        msg = str(excinfo.value)
        # The operator must be told what to DO, not just what broke.
        assert "docker compose up -d" in msg
        assert "DATABASE_URL" in msg
        assert "127.0.0.1:59999" in msg          # which server was tried
        assert "secret" not in msg               # ...without leaking the password

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
