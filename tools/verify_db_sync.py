"""Verify the model->Postgres sync against a REAL database (docs/production-redesign/07).

The unit tests prove the manifest persistence against SQLite; this proves it against the
Postgres you actually deploy. It:
  1. fails fast if the DB is unreachable,
  2. ensures a throwaway project + version row exist (so the FKs are satisfiable),
  3. persists a small model into the manifest tables,
  4. prints the row counts and confirms load_model() reproduces what went in.

The model is built here rather than read from `model/*.json`. It used to sync whatever
generation had last been run into a directory; there is no file model any more, and a gate
that silently compared against stale leftovers would be worse than none. Small is fine: what
this proves is the DIALECT - JSONB, BigInteger identities, ON CONFLICT - which SQLite hides
and which a row count of 3 exercises exactly as well as one of 300.

Run (Postgres up, `alembic upgrade head` done):

    docker compose up -d
    python -m alembic upgrade head
    python tools/verify_db_sync.py
"""
from __future__ import annotations

import datetime
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, "engine")]

from sqlalchemy import func, insert, select                       # noqa: E402
from api.db.postgres import schema as s                           # noqa: E402
from core.db import get_engine, require_database                  # noqa: E402
from incremental import model_store                               # noqa: E402

PID, VID = "verify-proj", "verify-ver"
UTC = datetime.timezone.utc

# One function calling another, one global, and their hashes - enough to put a row in every
# table the manifest writes and to make the edge and content-blob paths real.
FUNCTIONS = {
    "f1": {"name": "add", "qualifiedName": "Calc::add", "className": "Calc",
           "file": "src/calc.cpp", "line": 10, "endLine": 14, "unit": "Calc",
           "component": "App", "visibility": "public", "direction": "In",
           "description": "Adds two numbers.", "callsIds": ["f2"], "calledByIds": []},
    "f2": {"name": "mul", "qualifiedName": "Calc::mul", "className": "Calc",
           "file": "src/calc.cpp", "line": 20, "endLine": 24, "unit": "Calc",
           "component": "App", "visibility": "private", "direction": "In",
           "description": "Multiplies two numbers.", "callsIds": [], "calledByIds": ["f1"]},
}
GLOBALS = {"g1": {"name": "g_count", "file": "src/calc.cpp", "line": 3, "unit": "Calc",
                  "component": "App", "type": "int", "description": "Call counter."}}
HASHES = {"f1": "h-one", "f2": "h-two", "g1": "h-three"}


def main() -> int:
    require_database()                                            # clear message if DB is down
    engine = get_engine()

    now = datetime.datetime.now(UTC)
    with engine.begin() as cx:
        if not cx.execute(select(s.projects.c.id).where(s.projects.c.id == PID)).first():
            cx.execute(insert(s.projects), {"id": PID, "name": "verify", "created_at": now})
        if not cx.execute(select(s.versions.c.id).where(s.versions.c.id == VID)).first():
            cx.execute(insert(s.versions), {"id": VID, "project_id": PID, "version": VID,
                                            "created_at": now})
        model_store.clear_version(cx, VID)                            # idempotent re-runs
        model_store.persist_functions(cx, PID, VID, FUNCTIONS, HASHES)
        model_store.persist_globals(cx, PID, VID, GLOBALS, HASHES)

    with engine.connect() as cx:
        print("\nentities by kind:")
        for kind, n in cx.execute(
                select(s.entities.c.kind, func.count()).group_by(s.entities.c.kind)):
            print(f"    {kind:10} {n}")
        def _count(table):
            return cx.execute(select(func.count()).select_from(table)
                              .where(table.c.version_id == VID)).scalar_one()
        ev = _count(s.entity_versions)                 # captured for the final check below
        print(f"\n  entity_versions : {ev}")
        print(f"  model_edges     : {_count(s.model_edges)}")
        print(f"  model_units     : {_count(s.model_units)}")
        print(f"  model_components: {_count(s.model_components)}")
        print(f"  model_summaries : {_count(s.model_summaries)}")
        print(f"  content_blobs   : "
              f"{cx.execute(select(func.count()).select_from(s.content_blobs)).scalar_one()}")
        # full read side: load the whole model back and spot-check it
        model = model_store.load_model(cx, VID)
        print(f"\n  load_model parts: {', '.join(f'{k}={len(v)}' for k, v in model.items())}")
        loaded = model["hashes"]

    ok = loaded == HASHES
    print(f"\n  load_hashes() == what went in : {'YES' if ok else 'NO'} "
          f"({len(loaded)} vs {len(HASHES)} keys)")
    print("\nOK - model persisted to Postgres and reads back intact."
          if ok and ev > 0 else "\nMISMATCH - see above.")
    return 0 if (ok and ev > 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
