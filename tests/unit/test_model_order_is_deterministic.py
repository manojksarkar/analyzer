"""The database must hand back the model in the order the parser produced it.

poc-4 read model/functions.json, so it got the parser's order for free: functions in
file-then-line order, and each function's callsIds in the order the calls appear in its
body. Database mode has to ask for that order explicitly -- neither query had an ORDER
BY, so rows came back however the backend felt like returning them.

It is not cosmetic. Views iterate the model without re-sorting, so the documents inherit
it: a poc-4 vs database comparison of SampleCppProject differed in exactly one place,
utilBlend's Requirements cell, which lists the functions it calls --

    poc-4:  int utilHalve(int v)      int utilClamp(int v, int lo, int hi)
    db:     int utilClamp(...)        int utilHalve(int v)

-- because Util.cpp calls utilHalve twice and then utilClamp. Same content, wrong order,
and it would drift again between runs.
"""

import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (_ROOT, os.path.join(_ROOT, "engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _src():
    with open(os.path.join(_ROOT, "engine", "core", "model_store.py"), encoding="utf-8") as fh:
        return fh.read()


def _fn_body(name):
    src = _src()
    return src.split("def " + name + "(", 1)[1].split("\ndef ", 1)[0]


def test_entities_are_ordered_by_position_in_the_source():
    """file, then line -- the order the parser walks a translation unit."""
    body = _fn_body("_entity_rows")
    assert ".order_by(" in body
    assert "ev.c.file" in body.split(".order_by(", 1)[1]
    assert "ev.c.line" in body.split(".order_by(", 1)[1]


def test_entity_order_has_a_tiebreak():
    """Two entities can share a file and line (a macro and what it expands to). Without a
    final tiebreak the order between them is still the backend's choice."""
    tail = _fn_body("_entity_rows").split(".order_by(", 1)[1]
    assert "entity_key" in tail


def test_entity_order_is_backend_agnostic():
    """SQLite and Postgres disagree about where NULLs sort. coalesce settles it, so a
    version built on one backend lists its unlocated entities like the other."""
    tail = _fn_body("_entity_rows").split(".order_by(", 1)[1]
    assert "coalesce" in tail


def test_call_edges_come_back_in_insertion_order():
    """edge_id is insertion order, which is the order the parser found the calls."""
    body = _fn_body("load_functions")
    assert ".order_by(me.c.edge_id)" in body


def test_type_and_macro_edges_are_ordered_too():
    body = _fn_body("load_edges")
    assert ".order_by(me.c.edge_id)" in body


def test_no_unordered_model_edge_query_remains():
    """Any future read of model_edges needs the same treatment -- catch a new one.

    A query whose row order provably cannot reach the output may opt out by saying so
    in a preceding `# order-independent:` comment. One does today: it accumulates into
    sets that are sorted() before use, so an ORDER BY there would be a sort for nobody.
    Opting out is a claim you have to write down, which is the point.
    """
    src = _src()
    for m in re.finditer(r"select\(me\.c\.[^)]*\)(?:[^;]*?)\)\):", src, re.S):
        chunk = m.group(0)
        if "order_by" in chunk:
            continue
        preceding = src[max(0, m.start() - 400):m.start()]
        assert "order-independent:" in preceding, (
            "an unordered model_edges query with no justification:\n" + chunk[:200])


def test_units_come_back_in_path_order():
    """poc-4 writes units.json in the order the parser walked the files, which is path
    order, and the interface-tables view iterates units as it finds them. Unordered, the
    sections of interface_tables.json came out shuffled against the file-backed build."""
    body = _fn_body("load_units")
    head = body.split("functionIds", 1)[0]
    assert ".order_by(" in head
    assert "model_units.c.path" in head
    assert "model_units.c.unit_key" in head     # tiebreak


def test_a_units_function_list_follows_the_source():
    """The entities that fill functionIds/globalVariableIds are read in the same order as
    the model itself: file, then line."""
    body = _fn_body("load_units")
    tail = body.split("functionIds / globalVariableIds", 1)[1]
    assert "ev.c.file" in tail and "ev.c.line" in tail


def test_invisible_layout_edges_are_emitted_in_a_stable_order():
    """back_sources is a set, so iterating it raw gave a different DOT -- and a different
    stored flowchart JSON -- on every process, because string hashing is randomised per
    run. Not a migration defect: poc-4 has the identical line and is equally unstable.
    Layout is unaffected; Graphviz reads these as constraints, not as a sequence."""
    with open(os.path.join(_ROOT, "engine", "flowchart", "dot_builder.py"),
              encoding="utf-8") as fh:
        src = fh.read()
    assert "for tail in sorted(back_sources):" in src
