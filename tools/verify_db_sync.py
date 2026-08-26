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
    # f1 carries EVERY field a parsed function can, so the round-trip below is a real
    # check on the whole schema rather than on the handful a small fixture happens to
    # mention. Eight fields were once lost between Phase 1 and Phase 2 -- parameters,
    # returnExpr, className, addressTakenByUnits and both pairs of global-access lists --
    # and this gate passed throughout, because it only ever compared hashes and its
    # fixture named almost none of them.
    "f1": {"name": "add", "qualifiedName": "Calc::add", "className": "Calc",
           "file": "src/calc.cpp", "line": 10, "endLine": 14, "unit": "Calc",
           "component": "App", "visibility": "public", "direction": "In",
           "directionReason": "In: writes global(s) g_count.", "interfaceId": "IF_APP_01",
           "isVisible": True, "returnType": "int", "returnExpr": "a + b",
           # `params` is Phase 1's spelling and `parameters` is Phase 2's -- both must
           # survive, because each phase reads the model the other one wrote.
           "params": [{"name": "a", "type": "int"}, {"name": "b", "type": "int"}],
           "parameters": [{"name": "a", "type": "int"}, {"name": "b", "type": "int"}],
           "behaviourInputName": "a", "behaviourOutputName": "sum",
           "addressTakenByUnits": ["Other"],
           "readsGlobalIds": ["g1"], "writesGlobalIds": ["g1"],
           "readsGlobalIdsTransitive": ["g1"], "writesGlobalIdsTransitive": ["g1"],
           "description": "Adds two numbers.", "callsIds": ["f2"], "calledByIds": []},
    "f2": {"name": "mul", "qualifiedName": "Calc::mul", "className": "Calc",
           "file": "src/calc.cpp", "line": 20, "endLine": 24, "unit": "Calc",
           "component": "App", "visibility": "private", "direction": "In",
           "returnType": "int", "syntheticFromVarDecl": True,
           "description": "Multiplies two numbers.", "callsIds": [], "calledByIds": ["f1"]},
}
GLOBALS = {"g1": {"name": "g_count", "file": "src/calc.cpp", "line": 3, "unit": "Calc",
                  "component": "App", "type": "int", "value": "0", "className": "Calc",
                  "description": "Call counter."}}

# Fields that must come back EXACTLY as they went in. Deliberately not everything: `name`,
# `unit`, `component` and the flat file/line/endLine are folded into entity keys and
# location columns, so they are checked by the row counts rather than by value.
FN_VERBATIM = ("qualifiedName", "className", "visibility", "direction", "directionReason",
               "interfaceId", "returnType", "returnExpr", "params", "parameters",
               "behaviourInputName", "behaviourOutputName", "addressTakenByUnits",
               "readsGlobalIds", "writesGlobalIds", "readsGlobalIdsTransitive",
               "writesGlobalIdsTransitive", "description", "callsIds", "calledByIds",
               "syntheticFromVarDecl")
GLOBAL_VERBATIM = ("type", "value", "className", "description")


def _field_diffs(sent, got, fields):
    """Which of `fields` did not survive the round-trip, and how."""
    out = []
    for key, original in sent.items():
        back = got.get(key)
        if back is None:
            out.append(f"{key}: absent after reload")
            continue
        for f in fields:
            if f not in original:
                continue
            a, b = original[f], back.get(f, "<MISSING>")
            if isinstance(a, list) and isinstance(b, list):
                a, b = sorted(a, key=repr), sorted(b, key=repr)
            if a != b:
                out.append(f"{key}.{f}: sent {a!r}, got {b!r}")
    return out
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

    # Clean the fixture up. It used to sync a REAL generation's model dir, so what it left
    # behind looked like a version; the synthetic one does not, and `verify_db_rebuild`
    # inspects the NEWEST version in the database — which was this fixture, reported as an
    # unrebuildable version. A gate has no business leaving rows in a developer's database.
    with engine.begin() as cx:
        model_store.clear_version(cx, VID)
        cx.execute(s.versions.delete().where(s.versions.c.id == VID))
        cx.execute(s.projects.delete().where(s.projects.c.id == PID))

    ok = loaded == HASHES
    print(f"\n  load_hashes() == what went in : {'YES' if ok else 'NO'} "
          f"({len(loaded)} vs {len(HASHES)} keys)")

    # The model itself, field by field. Hashes matching only proves the hash rows are
    # there; a field silently dropped on the way in changes no hash and broke nothing
    # here for months.
    diffs = (_field_diffs(FUNCTIONS, model["functions"], FN_VERBATIM)
             + _field_diffs(GLOBALS, model["globals"], GLOBAL_VERBATIM))
    print(f"  every model field survived        : {'YES' if not diffs else 'NO'}")
    for d in diffs:
        print(f"      ! {d}")
    ok = ok and not diffs
    print("\nOK - model persisted to Postgres and reads back intact."
          if ok and ev > 0 else "\nMISMATCH - see above.")
    return 0 if (ok and ev > 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
