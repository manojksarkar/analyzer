"""A layer added to a version's model (engine/incremental/extend.py).

`analyzer.py export` of a component from a layer the version did not parse re-parses every layer
(which replaces the model's rows with a blank skeleton), puts the text the version already had
back, and lets Phase 2 describe only what is new. These drive the steps around the parse on a
SQLite database: what is captured, what is put back, what the plan asks Phase 2 to describe, and
which components count as changed.
"""
import datetime
import os
import sys

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.pool import StaticPool

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (PROJECT_ROOT, os.path.join(PROJECT_ROOT, "engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from api.db.postgres import schema as s          # noqa: E402
from core import model_store                     # noqa: E402
from incremental import extend                   # noqa: E402

pytestmark = pytest.mark.unit

PROJECT, VERSION = "p1", "ver1"
ADD = "Layer1.Math|Utils|add|int,int"
SUB = "Layer1.Math|Utils|sub|int,int"
LOG = "Layer1.Diag|Diag|logIt|"
GPIO = "Layer2.Gpio|Gpio|gpio_get|int"
G_SPEED = "Layer1.Math|Utils|g_speed"


def _fn(file, line, **kw):
    return {"qualifiedName": kw.pop("qn", "f"), "location": {"file": file, "line": line},
            "visibility": "public", "parameters": [], **kw}


def _layer1(described=True):
    d = (lambda text: {"description": text, "inputName": text + " in",
                       "outputName": text + " out"}) if described else (lambda text: {})
    return {
        ADD: _fn("Layer1/Math/Utils.cpp", 1, qn="add", **d("Adds"), callsIds=[], calledByIds=[]),
        SUB: _fn("Layer1/Math/Utils.cpp", 9, qn="sub", **d("Subtracts")),
        LOG: _fn("Layer1/Diag/Diag.cpp", 3, qn="logIt", **d("Logs")),
    }


def _persist(cx, functions, globals_, edges_calls=()):
    model_store.clear_version(cx, VERSION)
    for src, dst in edges_calls:
        functions[src].setdefault("callsIds", []).append(dst)
    model_store.persist_model(
        cx, PROJECT, VERSION, functions=functions, globals=globals_,
        datadict={"Speed": {"kind": "struct", "name": "Speed", "qualifiedName": "Speed",
                            **({"description": "A speed"} if globals_.get(G_SPEED, {}).get(
                                "description") else {})}},
        edges={"typeUsers": {}, "macroUsers": {}},
        units={"Layer1.Math|Utils": {"name": "Utils", "path": "Layer1/Math/Utils.cpp",
                                     "description": "Math helpers"
                                     if functions[ADD].get("description") else None},
               "Layer1.Diag|Diag": {"name": "Diag", "path": "Layer1/Diag/Diag.cpp",
                                    "description": None}})


@pytest.fixture
def db(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    s.metadata.create_all(eng)
    now = datetime.datetime.now(datetime.timezone.utc)
    with eng.begin() as cx:
        cx.execute(insert(s.projects).values(id=PROJECT, name="p1", created_at=now))
        cx.execute(insert(s.versions).values(id=VERSION, project_id=PROJECT, version="v1",
                                             created_at=now))
        _persist(cx, _layer1(), {G_SPEED: {"qualifiedName": "g_speed",
                                           "location": {"file": "Layer1/Math/Utils.cpp", "line": 0},
                                           "type": "int", "description": "The speed"}})
    monkeypatch.setattr(extend, "_engine", lambda: eng)
    return eng


def _reparse_with_layer2(eng):
    """What Phase 1 over both layers leaves: every row replaced by a blank skeleton, Layer 2's
    function in it, and Layer 2 calling Layer 1's `add`."""
    fns = _layer1(described=False)
    fns[GPIO] = _fn("Layer2/Platform/Gpio/Gpio.cpp", 5, qn="gpio_get", callsIds=[])
    g = {G_SPEED: {"qualifiedName": "g_speed", "type": "int",
                   "location": {"file": "Layer1/Math/Utils.cpp", "line": 0}},
         "Layer2.Gpio|Gpio|g_pin": {"qualifiedName": "g_pin", "type": "int",
                                    "location": {"file": "Layer2/Platform/Gpio/Gpio.cpp",
                                                 "line": 0}}}
    with eng.begin() as cx:
        _persist(cx, fns, g, edges_calls=[(GPIO, ADD)])


class TestTheTextTheVersionHadComesBack:
    def test_captured_then_put_back_on_the_entities_still_there(self, db):
        saved = extend.capture(VERSION)
        assert saved["functions"][ADD] == {"description": "Adds", "inputName": "Adds in",
                                           "outputName": "Adds out"}
        assert saved["units"] == {"Layer1.Math|Utils": "Math helpers"}
        _reparse_with_layer2(db)
        n = extend.restore_text(VERSION, saved)
        assert n["functions"] == 3 and n["globals"] == 1
        with db.connect() as cx:
            fns = model_store.load_functions(cx, VERSION)
            gl = model_store.load_globals(cx, VERSION)
        assert fns[ADD]["description"] == "Adds"
        assert fns[SUB]["outputName"] == "Subtracts out"
        assert not fns[GPIO].get("description"), "the new layer is left for Phase 2"
        assert gl[G_SPEED]["description"] == "The speed"

    def test_text_the_new_parse_has_is_not_overwritten(self, db):
        saved = extend.capture(VERSION)
        with db.begin() as cx:
            model_store.set_entity_field(cx, VERSION, ADD, "description", "Newer", "function")
        extend.restore_text(VERSION, saved)
        with db.connect() as cx:
            assert model_store.load_functions(cx, VERSION)[ADD]["description"] == "Newer"

    def test_a_function_stored_under_the_old_names_is_written_under_the_new(self, db):
        """`inputName` / `outputName` were `behaviourInputName` / `behaviourOutputName` until
        2026-10-05 (REVIEW_UPDATE_HANDOVER §4.34). An entity whose stored payload still has an old
        key keeps its own value, as with any filled field, and the payload put back carries the
        new names only."""
        from sqlalchemy import select, update
        saved = extend.capture(VERSION)
        _reparse_with_layer2(db)
        old = {"parameters": [], "behaviourInputName": "Own input"}
        with db.begin() as cx:
            ch = model_store._content_hash(old)
            model_store._insert_blobs(cx, {ch: ("function", old)})
            eid = cx.execute(select(s.entities.c.entity_id)
                             .where(s.entities.c.entity_key == ADD)).scalar_one()
            cx.execute(update(s.entity_versions)
                       .where(s.entity_versions.c.version_id == VERSION,
                              s.entity_versions.c.entity_id == eid).values(content_hash=ch))
        extend.restore_text(VERSION, saved)
        with db.connect() as cx:
            payload = cx.execute(
                select(s.content_blobs.c.payload).select_from(s.entity_versions.join(
                    s.content_blobs,
                    s.content_blobs.c.content_hash == s.entity_versions.c.content_hash))
                .where(s.entity_versions.c.version_id == VERSION,
                       s.entity_versions.c.entity_id == eid)).scalar_one()
        assert payload["inputName"] == "Own input" and payload["outputName"] == "Adds out"
        assert payload["description"] == "Adds"
        assert "behaviourInputName" not in payload


class TestThePlanForPhase2:
    def test_only_what_is_new_is_described_and_units_keep_their_text(self, db):
        saved = extend.capture(VERSION)
        _reparse_with_layer2(db)
        plan = extend.write_plan(VERSION, PROJECT, saved)
        assert plan["impactFids"] == [GPIO]
        assert plan["impactedGlobals"] == ["Layer2.Gpio|Gpio|g_pin"]
        assert plan["unitDescriptions"] == {"Layer1.Math|Utils": "Math helpers"}
        assert plan["flowchartFids"] == []
        with db.connect() as cx:
            assert model_store.load_incremental_plan(cx, VERSION)["impactFids"] == [GPIO]

    def test_the_plan_the_version_had_is_put_back(self, db):
        with db.begin() as cx:
            model_store.persist_incremental_plan(cx, VERSION, {"flowchartFids": ["x"]})
        saved = extend.capture(VERSION)
        extend.write_plan(VERSION, PROJECT, saved)
        extend.restore_plan(VERSION, saved)
        with db.connect() as cx:
            assert model_store.load_incremental_plan(cx, VERSION) == {"flowchartFids": ["x"]}

    def test_the_plan_of_an_add_cut_short_is_not_put_back(self, db):
        with db.begin() as cx:
            model_store.persist_incremental_plan(cx, VERSION, {"impactFids": [GPIO],
                                                              "flowchartFids": [],
                                                              "addedLayers": True})
        saved = extend.capture(VERSION)
        extend.write_plan(VERSION, PROJECT, saved)
        extend.restore_plan(VERSION, saved)
        with db.connect() as cx:
            assert model_store.load_incremental_plan(cx, VERSION) == {}

    def test_no_plan_before_means_none_after(self, db):
        saved = extend.capture(VERSION)
        extend.write_plan(VERSION, PROJECT, saved)
        extend.restore_plan(VERSION, saved)
        with db.connect() as cx:
            assert model_store.load_incremental_plan(cx, VERSION) == {}


class TestWhichDocumentsTheNewLayerChanges:
    def test_a_component_the_new_layer_calls_into_is_changed_another_is_not(self, db):
        saved = extend.capture(VERSION)
        _reparse_with_layer2(db)
        extend.restore_text(VERSION, saved)
        # Math's `add` is called from Layer 2 now; Diag is untouched.
        assert extend.changed_components(VERSION, saved, ["Layer1.Math", "Layer1.Diag"]) \
            == ["Layer1.Math"]

    def test_text_alone_does_not_count(self):
        a = {"functions": {ADD: {"description": "x", "callsIds": []}}, "globals": {}, "units": {}}
        b = {"functions": {ADD: {"description": "y", "callsIds": []}}, "globals": {}, "units": {}}
        assert extend.fingerprints(a) == extend.fingerprints(b)

    def test_a_new_caller_does(self):
        a = {"functions": {ADD: {"calledByIds": []}}, "globals": {}, "units": {}}
        b = {"functions": {ADD: {"calledByIds": [GPIO]}}, "globals": {}, "units": {}}
        assert extend.fingerprints(a)["Layer1.Math"] != extend.fingerprints(b)["Layer1.Math"]


class TestTheRecordedScope:
    def test_a_component_scope_gains_the_new_components(self):
        assert extend.widen_scope({"type": "component", "names": ["Layer1.Math"]}, ["Layer1.Math"],
                                  ["Layer2.Gpio"]) == {"type": "component",
                                                       "names": ["Layer1.Math", "Layer2.Gpio"]}

    def test_a_layer_scope_becomes_what_the_version_documents_plus_them(self):
        assert extend.widen_scope({"type": "layer", "names": ["Layer1"]},
                                  ["Layer1.Math", "Layer1.Diag"], ["Layer2.Gpio"]) \
            == {"type": "component", "names": ["Layer1.Math", "Layer1.Diag", "Layer2.Gpio"]}
