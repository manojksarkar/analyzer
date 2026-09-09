"""The incremental core off the DB == off the files (docs/production-redesign/07, PG-4).

The point of persisting the model is that classify + impact keep working, unchanged,
when they read Postgres instead of JSON. This drives the REAL model through the manifest
tables and asserts classify() and impact_set() give identical results whether fed the
file model or the DB-loaded model - across every edge kind (call / global / type / macro).
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
from incremental.impact import classify, impact_set

UTC = datetime.timezone.utc
MODEL_DIR = os.path.join(PROJECT_ROOT, "model")
_HAS_MODEL = os.path.isfile(os.path.join(MODEL_DIR, "functions.json"))
PID = "p"


def _load(name):
    p = os.path.join(MODEL_DIR, name)
    return json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else {}


def _persisted(functions, globals_, datadict, edges, hashes, vid="v"):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(eng, "connect")
    def _fk(c, _r):
        c.execute("PRAGMA foreign_keys=ON")

    s.metadata.create_all(eng)
    with eng.begin() as cx:
        cx.execute(insert(s.projects), {"id": PID, "name": "P",
                                        "created_at": datetime.datetime.now(UTC)})
        cx.execute(insert(s.versions), {"id": vid, "project_id": PID, "version": vid,
                                        "created_at": datetime.datetime.now(UTC)})
        model_store.persist_model(cx, PID, vid, functions=functions, globals=globals_,
                                  datadict=datadict, edges=edges, hashes=hashes)
    return eng


@pytest.mark.skipif(not _HAS_MODEL, reason="needs a parsed model/")
def test_impact_set_db_equals_file_all_edge_kinds():
    functions = _load("functions.json")
    globals_ = _load("globalVariables.json")
    datadict = _load("dataDictionary.json")
    edges = _load("edges.json")
    hashes = _load("hashes.json")

    eng = _persisted(functions, globals_, datadict, edges, hashes)
    with eng.connect() as cx:
        db_functions = model_store.load_functions(cx, "v")
        db_edges = model_store.load_edges(cx, "v")

    # changed-sets that exercise each seeding path: a global -> its users; a used type;
    # a used macro; a called function -> its callers; and the union.
    globals_keys = list(globals_)[:5]
    type_keys = list((edges.get("typeUsers") or {}))[:5]
    macro_keys = list((edges.get("macroUsers") or {}))[:5]
    fn_keys = list(functions)[:8]
    change_sets = {
        "globals": set(globals_keys), "types": set(type_keys), "macros": set(macro_keys),
        "functions": set(fn_keys), "mixed": set(globals_keys + type_keys + macro_keys + fn_keys),
    }

    hit = 0
    for label, changed in change_sets.items():
        file_imp = impact_set(changed, functions, edges)
        db_imp = impact_set(changed, db_functions, db_edges)
        assert file_imp == db_imp, f"impact diverged for {label}"
        hit += len(db_imp)
    assert hit > 0, "test degenerate - no impact produced by any change set"


@pytest.mark.skipif(not _HAS_MODEL, reason="needs a parsed model/")
def test_classify_db_equals_file_on_a_real_diff():
    """Two versions with a synthetic diff (change/delete/new) classify identically
    whether the hashes come from the DB or the files."""
    functions = _load("functions.json")
    globals_ = _load("globalVariables.json")
    datadict = _load("dataDictionary.json")
    edges = _load("edges.json")
    base_hashes = _load("hashes.json")

    keys = list(base_hashes)
    target_hashes = dict(base_hashes)
    target_hashes[keys[0]] = "deadbeef"          # changed
    del target_hashes[keys[1]]                   # deleted
    target_hashes["Z|Z|new_fn|"] = "cafef00d"    # new

    eng = _persisted(functions, globals_, datadict, edges, base_hashes, vid="base")
    # a second version carrying the target hashes (only the hash map matters to classify)
    with eng.begin() as cx:
        cx.execute(insert(s.versions), {"id": "tgt", "project_id": PID, "version": "tgt",
                                        "created_at": datetime.datetime.now(UTC)})
        model_store.persist_bare_entities(cx, PID, "tgt", target_hashes)

    with eng.connect() as cx:
        db_base = model_store.load_hashes(cx, "base")
        db_tgt = model_store.load_hashes(cx, "tgt")

    file_cls = classify(base_hashes, target_hashes)
    db_cls = classify(db_base, db_tgt)
    for bucket in ("changed", "new", "deleted", "unchanged"):
        assert db_cls[bucket] == file_cls[bucket], f"classify {bucket} diverged"
    assert keys[0] in db_cls["changed"] and keys[1] in db_cls["deleted"]
    assert "Z|Z|new_fn|" in db_cls["new"]
