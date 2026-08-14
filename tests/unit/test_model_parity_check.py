"""The C11 parity oracle must actually detect a difference (doc 09, C11a).

`tools/verify_model_parity.py` is the gate that decides whether Postgres may replace
`model/*.json` as the channel between phases. A checker that always says "OK" is worse than
no checker — it would wave through exactly the silent field loss that C11 risks.

So these tests do two things: prove it stays quiet on a real round-trip, and prove it speaks
up for each kind of difference it exists to catch. The lossy-field case is the important one:
`_FN_PAYLOAD_FIELDS` is an allow-list, so a model field added later that nobody registers
would round-trip as missing and surface only as a wrong document.
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
sys.path.insert(0, os.path.join(PROJECT_ROOT, "tools"))

from api.db.postgres import schema as s          # noqa: E402
from incremental import model_store              # noqa: E402
import verify_model_parity as vmp                # noqa: E402

PID, VID = "proj-parity", "ver-parity"
_UTC = datetime.timezone.utc


def _engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)

    @event.listens_for(eng, "connect")
    def _fk_on(dbapi_conn, _rec):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    s.metadata.create_all(eng)
    now = datetime.datetime.now(_UTC)
    with eng.begin() as cx:
        cx.execute(insert(s.projects), {"id": PID, "name": "T", "created_at": now})
        cx.execute(insert(s.versions), {"id": VID, "project_id": PID, "version": "v1",
                                        "created_at": now})
    return eng


_FUNCS = {
    "Core|Core|calc|int": {
        "qualifiedName": "calc",
        "location": {"file": "Core/Core.cpp", "line": 10, "endLine": 20},
        "returnType": "int", "description": "Computes a value.",
        "parameters": [{"name": "a", "type": "int"}],
        "direction": "Out", "visibility": "public", "interfaceId": "IF_L1_C_CORE_01",
        "callsIds": ["Core|Core|helper|void"], "calledByIds": [],
        "readsGlobalIds": [], "writesGlobalIds": [],
    },
    "Core|Core|helper|void": {
        "qualifiedName": "helper",
        "location": {"file": "Core/Core.cpp", "line": 30, "endLine": 35},
        "returnType": "void", "description": "Helper.",
        "parameters": [],
        "direction": "Out", "visibility": "private", "interfaceId": "PIF_L1_C_CORE_01",
        "callsIds": [], "calledByIds": ["Core|Core|calc|int"],
        "readsGlobalIds": [], "writesGlobalIds": [],
    },
}


def _persisted(functions=None):
    """An engine holding `functions` (default `_FUNCS`), plus the DB-loaded copy."""
    eng = _engine()
    with eng.begin() as cx:
        model_store.persist_functions(cx, PID, VID, functions or _FUNCS, {})
    with eng.connect() as cx:
        return model_store.load_functions(cx, VID)


def test_clean_roundtrip_reports_nothing():
    """The baseline: persist -> load -> compare against the source must be silent."""
    db = _persisted()
    report = []
    vmp._compare_entities("functions", db, _FUNCS, report)
    assert report == [], f"false alarm on a clean round-trip: {report}"


def test_detects_a_field_the_db_silently_drops():
    """THE case this exists for — a field outside the payload allow-list.

    `customField` is not in _FN_PAYLOAD_FIELDS, so persist drops it. Without this check, that
    loss is invisible until a document renders wrong.
    """
    disk = json.loads(json.dumps(_FUNCS))
    disk["Core|Core|calc|int"]["customField"] = "value the DB will not keep"
    db = _persisted(disk)

    report = []
    vmp._compare_entities("functions", db, disk, report)

    assert report, "a dropped field must be reported"
    headline = report[0][0]
    assert "customField" in headline and "DROPPED" in headline, headline


def test_detects_an_entity_missing_from_the_db():
    db = _persisted()
    disk = json.loads(json.dumps(_FUNCS))
    disk["Core|Core|extra|void"] = {"qualifiedName": "extra",
                                    "location": {"file": "Core/Core.cpp", "line": 40}}
    report = []
    vmp._compare_entities("functions", db, disk, report)
    assert any("MISSING from the DB" in h for h, _ in report), report


def test_detects_a_changed_value():
    db = _persisted()
    disk = json.loads(json.dumps(_FUNCS))
    disk["Core|Core|calc|int"]["description"] = "Something completely different."
    report = []
    vmp._compare_entities("functions", db, disk, report)
    assert any("value mismatch" in h for h, _ in report), report


def test_edge_list_order_is_tolerated():
    """Edge lists are rebuilt from rows, so their order is an artefact. Same members in a
    different order must NOT be reported — otherwise the gate cries wolf on every run and
    stops being read."""
    disk = json.loads(json.dumps(_FUNCS))
    disk["Core|Core|calc|int"]["readsGlobalIds"] = ["g|a", "g|b"]
    db = _persisted(disk)
    # Set both sides explicitly rather than reversing whatever the DB returned — reversing a
    # 2-element list the DB had already ordered the other way reproduces the disk order
    # exactly, and then the test asserts nothing.
    db["Core|Core|calc|int"]["readsGlobalIds"] = ["g|b", "g|a"]      # same members, other order

    report = []
    order_only = vmp._compare_entities("functions", db, disk, report)
    assert report == [], f"order difference must not be a finding: {report}"
    assert order_only >= 1, "the order-only difference should still be counted and surfaced"


def test_db_only_fields_are_not_reported_as_differences():
    """`isVisible` exists only in the DB (D-18). Extra information is not a loss, and the
    comparison walks the DISK fields, so it must stay quiet."""
    db = _persisted()
    assert "isVisible" in db["Core|Core|calc|int"], "precondition: the DB adds isVisible"
    report = []
    vmp._compare_entities("functions", db, _FUNCS, report)
    assert report == []


def test_plain_compare_detects_hash_differences():
    """hashes/edges/summaries are compared by exact equality, not entity-wise."""
    report = []
    vmp._compare_plain("hashes", {"a": "1", "b": "2"}, {"a": "1", "b": "changed"}, report)
    assert any("value mismatch" in h for h, _ in report), report

    report = []
    vmp._compare_plain("hashes", {"a": "1"}, {"a": "1"}, report)
    assert report == []
