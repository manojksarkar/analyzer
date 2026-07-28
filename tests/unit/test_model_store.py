"""ModelStore round-trip parity (docs/production-redesign/07, PG-4).

The DB-native model is only trustworthy if a parsed model survives persist -> load
unchanged. This drives the real `model/functions.json` (125 functions) through the
manifest tables on a FK-enforcing SQLite DB (Postgres-strict) and asserts the loaded
model is functionally identical to the original.

Comparison rules:
  * payload fields (returnType, description, parameters, ...) must match EXACTLY
    (parameters is order-significant -> exact list compare);
  * edge-derived lists (callsIds/calledByIds/reads/writesGlobalIds) are semantic SETS
    -> compared order-insensitively, None/missing normalised to empty.
"""
import datetime
import json
import os
import sys

import pytest
from sqlalchemy import create_engine, event, insert
from sqlalchemy.pool import StaticPool

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from api.db.postgres import schema as s
from incremental import model_store

MODEL_DIR = os.path.join(PROJECT_ROOT, "model")
_HAS_MODEL = os.path.isfile(os.path.join(MODEL_DIR, "functions.json"))

PID, VID = "proj-test", "ver-test"


def _fk_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _rec):            # Postgres-strict: enforce FKs on SQLite too
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    s.metadata.create_all(engine)
    with engine.begin() as cx:               # parent rows so the FKs are satisfiable
        cx.execute(insert(s.projects), {"id": PID, "name": "T",
                                        "created_at": datetime.datetime.now(datetime.timezone.utc)})
        cx.execute(insert(s.versions), {"id": VID, "project_id": PID, "version": "v1",
                                        "created_at": datetime.datetime.now(datetime.timezone.utc)})
    return engine


def _norm(v):
    return set(v or [])


@pytest.mark.skipif(not _HAS_MODEL, reason="needs model/functions.json (run the pipeline once)")
def test_functions_roundtrip_real_model():
    orig = json.load(open(os.path.join(MODEL_DIR, "functions.json"), encoding="utf-8"))
    hp = os.path.join(MODEL_DIR, "hashes.json")
    hashes = json.load(open(hp, encoding="utf-8")) if os.path.isfile(hp) else {}

    engine = _fk_engine()
    with engine.begin() as cx:
        model_store.persist_functions(cx, PID, VID, orig, hashes)
    with engine.connect() as cx:
        loaded = model_store.load_functions(cx, VID)

    assert set(loaded) == set(orig), "function set changed across the round-trip"

    for fid, o in orig.items():
        l = loaded[fid]
        # identity + structural
        assert l["qualifiedName"] == o.get("qualifiedName")
        assert l["location"] == o.get("location")
        assert l["direction"] == o.get("direction")
        assert l["visibility"] == o.get("visibility")
        assert l["interfaceId"] == o.get("interfaceId")
        # payload (exact; parameters order matters)
        assert l.get("returnType") == o.get("returnType")
        assert l.get("description") == o.get("description")
        assert l.get("parameters") == o.get("parameters")
        assert l.get("behaviourInputName") == o.get("behaviourInputName")
        # graph (semantic sets)
        assert _norm(l["callsIds"]) == _norm(o.get("callsIds")), f"callsIds {fid}"
        assert _norm(l["calledByIds"]) == _norm(o.get("calledByIds")), f"calledByIds {fid}"
        assert _norm(l["readsGlobalIds"]) == _norm(o.get("readsGlobalIds")), f"reads {fid}"
        assert _norm(l["writesGlobalIds"]) == _norm(o.get("writesGlobalIds")), f"writes {fid}"


@pytest.mark.skipif(not _HAS_MODEL, reason="needs model/functions.json")
def test_identical_payloads_dedup_to_one_blob():
    """Two functions with the same payload store the content once (D-9)."""
    engine = _fk_engine()
    p = {"description": "same", "parameters": [], "returnType": "void"}
    funcs = {"A|U|f|": {"qualifiedName": "f", **p}, "B|U|g|": {"qualifiedName": "g", **p}}
    with engine.begin() as cx:
        model_store.persist_functions(cx, PID, VID, funcs, {})
    with engine.connect() as cx:
        n = cx.execute(s.content_blobs.select()).fetchall()
    assert len(n) == 1, "identical payloads should collapse to a single content blob"
