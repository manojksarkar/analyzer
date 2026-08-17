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


def _load(name):
    p = os.path.join(MODEL_DIR, name)
    return json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else {}


@pytest.mark.skipif(not _HAS_MODEL, reason="needs a parsed model/")
def test_full_model_roundtrip_and_classify_input():
    """Persist the whole model; globals/types round-trip, edges round-trip, and
    load_hashes reproduces hashes.json exactly (the input classify diffs)."""
    functions = _load("functions.json")
    globals_ = _load("globalVariables.json")
    datadict = _load("dataDictionary.json")
    edges = _load("edges.json")
    hashes = _load("hashes.json")

    engine = _fk_engine()
    with engine.begin() as cx:
        model_store.persist_model(cx, PID, VID, functions=functions, globals=globals_,
                                  datadict=datadict, edges=edges, hashes=hashes)
    with engine.connect() as cx:
        lg = model_store.load_globals(cx, VID)
        lt = model_store.load_types(cx, VID)
        le = model_store.load_edges(cx, VID)
        lh = model_store.load_hashes(cx, VID)

    # globals: exact per-entry
    assert set(lg) == set(globals_)
    for k, o in globals_.items():
        assert lg[k] == o, f"global {k} changed across round-trip"

    # types/macros: exact per-entry (struct fields + macro value/text survive via payload)
    assert set(lt) == set(datadict)
    for k, o in datadict.items():
        assert lt[k] == o, f"type {k} changed across round-trip"

    # edges: type/macro user lists (semantic sets)
    for group in ("typeUsers", "macroUsers"):
        assert set(le[group]) == set(edges.get(group) or {})
        for key, users in (edges.get(group) or {}).items():
            assert set(le[group][key]) == set(users), f"{group}[{key}]"

    # THE classify input: hashes reconstructed from the DB == hashes.json, byte-for-byte
    assert lh == hashes, "load_hashes must reproduce hashes.json for DB-based classify"


@pytest.mark.skipif(not _HAS_MODEL, reason="needs a parsed model/")
def test_units_components_summaries_roundtrip():
    """units/components/summaries survive persist->load. Derived relations (functionIds,
    caller/callee units, component units) are compared as SETS; stored fields exact."""
    functions = _load("functions.json")
    globals_ = _load("globalVariables.json")
    datadict = _load("dataDictionary.json")
    edges = _load("edges.json")
    hashes = _load("hashes.json")
    units = _load("units.json")
    components = _load("components.json")
    summaries = _load("summaries.json")
    if not units:
        pytest.skip("no units.json in this model")

    engine = _fk_engine()
    with engine.begin() as cx:
        model_store.persist_model(cx, PID, VID, functions=functions, globals=globals_,
                                  datadict=datadict, edges=edges, hashes=hashes,
                                  units=units, components=components, summaries=summaries)
    with engine.connect() as cx:
        lu = model_store.load_units(cx, VID)
        lc = model_store.load_components(cx, VID)
        ls = model_store.load_summaries(cx, VID)

    assert set(lu) == set(units)
    for uk, o in units.items():
        l = lu[uk]
        assert (l["name"], l["path"], l["fileName"]) == (o["name"], o["path"], o["fileName"])
        assert l["includedHeaders"] == o.get("includedHeaders", [])          # stored exact
        for field in ("functionIds", "globalVariableIds", "callerUnits", "calleesUnits"):
            assert set(l[field]) == set(o.get(field) or []), f"{uk}.{field}"  # derived

    assert set(lc) == set(components)
    for name, o in components.items():
        assert set(lc[name]["units"]) == set(o.get("units") or [])
        assert set(lc[name]["headerFiles"]) == set(o.get("headerFiles") or [])

    assert ls["project"] == summaries.get("project", "")
    assert ls["components"] == (summaries.get("components") or {})
    assert ls["files"] == (summaries.get("files") or {})


@pytest.mark.skipif(not _HAS_MODEL, reason="needs a parsed model/")
def test_persist_from_dir_is_idempotent():
    """The runner's DB sync reads model/ and can re-run without doubling rows."""
    from sqlalchemy import func, select as _select
    engine = _fk_engine()

    def _counts():
        with engine.connect() as cx:
            ev = cx.execute(_select(func.count()).select_from(s.entity_versions)
                            .where(s.entity_versions.c.version_id == VID)).scalar_one()
            eg = cx.execute(_select(func.count()).select_from(s.model_edges)
                            .where(s.model_edges.c.version_id == VID)).scalar_one()
        return ev, eg

    with engine.begin() as cx:
        model_store.persist_model_from_dir(cx, PID, VID, MODEL_DIR)
    first = _counts()
    with engine.begin() as cx:
        model_store.persist_model_from_dir(cx, PID, VID, MODEL_DIR)   # sync again
    assert _counts() == first, "re-sync must be idempotent (clear_version before persist)"
    assert first[0] > 0 and first[1] > 0

    # and the hashes still reconstruct hashes.json after a re-sync
    with engine.connect() as cx:
        assert model_store.load_hashes(cx, VID) == _load("hashes.json")


@pytest.mark.skipif(not _HAS_MODEL, reason="needs a parsed model/")
def test_load_model_and_dump_to_dir_roundtrip(tmp_path):
    """files -> DB -> load_model gives every part back; dump_model_to_dir reproduces a
    usable model/ (the pipeline hand-off)."""
    engine = _fk_engine()
    with engine.begin() as cx:
        model_store.persist_model_from_dir(cx, PID, VID, MODEL_DIR)
    with engine.connect() as cx:
        model = model_store.load_model(cx, VID)
        model_store.dump_model_to_dir(cx, VID, str(tmp_path))

    # load_model returns all parts, non-empty
    assert set(model) == {"functions", "globals", "datadict", "edges", "units",
                          "components", "summaries", "hashes"}
    assert model["functions"] and model["hashes"]

    # dumped hashes.json byte-identical to the original (the classify input survives)
    dumped = json.load(open(tmp_path / "hashes.json", encoding="utf-8"))
    assert dumped == _load("hashes.json")
    # dumped functions cover the same set
    assert set(json.load(open(tmp_path / "functions.json", encoding="utf-8"))) \
        == set(_load("functions.json"))


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


def test_synthetic_from_var_decl_round_trips(tmp_path):
    """`syntheticFromVarDecl` must survive the database round-trip.

    It is not cosmetic. flowchart_engine.py filters on it:

        processable = [e for e in target_entries if not e.synthetic_from_var_decl]

    so an entry the parser synthesised from a VARIABLE declaration is excluded from flowchart
    generation. Drop the field and, once the model is read from the database, the engine tries
    to build a flowchart for something that is not a function.

    Found by tools/verify_model_parity.py on the first SQLite run. The office Postgres run
    reported "OK for all" only because that project contains no such entry — which is exactly
    why the check has to run against a fixture that does.
    """
    eng = _fk_engine()
    with eng.begin() as cx:
        functions = {
            "Diag|VoidAsVar|_SOME_FUNCTION|int": {
                "qualifiedName": "_SOME_FUNCTION", "returnType": "int",
                "syntheticFromVarDecl": True,
                "location": {"file": "Diag/VoidAsVar.cpp", "line": 12},
            },
            "Diag|VoidAsVar|realFn|void": {
                "qualifiedName": "realFn", "returnType": "void",
                "location": {"file": "Diag/VoidAsVar.cpp", "line": 20},
            },
        }
        model_store.persist_functions(cx, PID, VID, functions, {})
    with eng.connect() as cx:
        loaded = model_store.load_functions(cx, VID)

    assert loaded["Diag|VoidAsVar|_SOME_FUNCTION|int"]["syntheticFromVarDecl"] is True
    assert "syntheticFromVarDecl" not in loaded["Diag|VoidAsVar|realFn|void"], \
        "absent must stay absent — a default of False would silently change the filter"


def test_component_unit_order_is_deterministic(tmp_path):
    """The unit list must come back in a stable order.

    `model_units` has no ordinal column, so without an ORDER BY the list is whatever the
    database returns — not stable across engines or runs. The container diagram draws one box
    per unit in list order, so an unstable order renders a visually different PNG from
    identical input.
    """
    eng = _fk_engine()
    with eng.begin() as cx:
        model_store.persist_units(cx, VID, {
            "Z|Last": {"component": "C", "name": "Last"},
            "A|First": {"component": "C", "name": "First"},
            "M|Mid": {"component": "C", "name": "Mid"},
        })
        model_store.persist_components(cx, VID, {"C": {"units": ["Z|Last", "A|First", "M|Mid"]}})
    with eng.connect() as cx:
        got = model_store.load_components(cx, VID)["C"]["units"]
    assert got == sorted(got), f"unit order must be deterministic, got {got}"


def test_file_and_db_agree_on_component_unit_order():
    """The FILE side must sort too, not just the database.

    The container diagram draws one box per unit in list order. Unsorted, that list inherited
    the order the parser walked the directory — an accident of the filesystem, so the same
    commit could render a different picture on a different machine. And it has to match what
    `load_components` returns, or the mode-vs-mode parity check reports differences that mean
    nothing.

    Asserted on the source because the producing code is a dict comprehension inside a long
    derive function that a unit test cannot reach without running Phase 2.
    """
    import os as _os
    root = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    with open(_os.path.join(root, "engine", "model_deriver.py"), encoding="utf-8") as fh:
        src = fh.read()
    assert 'sorted(u for u in units_data if u.split(KEY_SEP)[0] == m)' in src, \
        "components.json must write its unit list sorted, to match load_components()"
