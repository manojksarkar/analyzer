"""Verify the model->Postgres sync against a REAL database (docs/production-redesign/07).

The unit tests prove the manifest persistence against SQLite; this proves it against the
Postgres you actually deploy. It:
  1. fails fast if the DB is unreachable,
  2. ensures a throwaway project + version row exist (so the FKs are satisfiable),
  3. syncs the local model/ directory into the manifest tables,
  4. prints the row counts and confirms load_hashes() reproduces hashes.json.

Run (Postgres up, `alembic upgrade head` done, a model/ present from any generation):

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
MODEL_DIR = os.path.join(_ROOT, "model")
UTC = datetime.timezone.utc


def main() -> int:
    require_database()                                            # clear message if DB is down
    engine = get_engine()

    if not os.path.isfile(os.path.join(MODEL_DIR, "functions.json")):
        print("No model/ found. Generate one first, e.g.:\n"
              "    python tools/parity/capture_baseline.py --out .parity/before")
        return 1

    now = datetime.datetime.now(UTC)
    with engine.begin() as cx:
        if not cx.execute(select(s.projects.c.id).where(s.projects.c.id == PID)).first():
            cx.execute(insert(s.projects), {"id": PID, "name": "verify", "created_at": now})
        if not cx.execute(select(s.versions.c.id).where(s.versions.c.id == VID)).first():
            cx.execute(insert(s.versions), {"id": VID, "project_id": PID, "version": VID,
                                            "created_at": now})
        model_store.persist_model_from_dir(cx, PID, VID, MODEL_DIR)   # idempotent

    with engine.connect() as cx:
        print("\nentities by kind:")
        for kind, n in cx.execute(
                select(s.entities.c.kind, func.count()).group_by(s.entities.c.kind)):
            print(f"    {kind:10} {n}")
        ev = cx.execute(select(func.count()).select_from(s.entity_versions)
                        .where(s.entity_versions.c.version_id == VID)).scalar_one()
        me = cx.execute(select(func.count()).select_from(s.model_edges)
                        .where(s.model_edges.c.version_id == VID)).scalar_one()
        cb = cx.execute(select(func.count()).select_from(s.content_blobs)).scalar_one()
        print(f"\n  entity_versions : {ev}")
        print(f"  model_edges     : {me}")
        print(f"  content_blobs   : {cb}")
        loaded = model_store.load_hashes(cx, VID)

    hp = os.path.join(MODEL_DIR, "hashes.json")
    hashes = json.load(open(hp, encoding="utf-8")) if os.path.isfile(hp) else {}
    ok = loaded == hashes
    print(f"\n  load_hashes() == hashes.json : {'YES' if ok else 'NO'} "
          f"({len(loaded)} vs {len(hashes)} keys)")
    print("\nOK - model persisted to Postgres and reads back intact."
          if ok and ev > 0 else "\nMISMATCH - see above.")
    return 0 if (ok and ev > 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
