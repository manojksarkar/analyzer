"""Seed the demo data (users / projects / versions / …) into the configured database.

`db_setup.py` creates the schema but leaves it EMPTY — so the API has no users and login fails.
This loads the same seed data `InMemoryDatabase` ships with, so you can sign in and drive the API
against real Postgres. Idempotent: skips if already seeded.

    $env:DATABASE_URL = "postgresql+psycopg://user:pass@host:5432/analyzer"
    python tools/seed_db.py

Sign in afterwards with:  alice@aspice.dev / secret   (admin on the seed projects)
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, "engine")]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    from core.db import database_url, get_engine, require_database, DatabaseUnavailable, _redact
    if not os.environ.get("DATABASE_URL", "").strip():
        print("DATABASE_URL is not set. Set it to your remote Postgres first, e.g.:")
        print('    $env:DATABASE_URL = "postgresql+psycopg://user:pass@host:5432/analyzer"')
        return 1

    print(f"target database: {_redact(database_url())}")
    try:
        require_database()                         # clear message if unreachable
    except DatabaseUnavailable as exc:
        print(f"\n{exc}")
        return 1

    from api.db.postgres.database import SqlDatabase
    db = SqlDatabase(get_engine())                 # existing schema (db_setup.py built it)
    if db.users.get_by_email("alice@aspice.dev"):
        print("already seeded (alice@aspice.dev exists) — nothing to do.")
    else:
        db.seed()
        print("seeded demo data (users, projects, versions, documents).")
    print("\nSign in:  alice@aspice.dev / secret   (admin)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
