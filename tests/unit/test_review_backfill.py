"""Descriptions of a version made before Phase 2 stored them (BACKLOG RF-6, `review/backfill.py`).

Such a version's LLM wording lives only in its own earlier output -- `unit_descriptions.json`
(the Component/Unit table) and `unit_headers.json` (each record row's Information) -- so a
re-export printed fallback text where that wording had been. `analyzer.py setup` copies it into
the model, once, and only what is safe to copy.
"""
import datetime
import json
import os
import sys

import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (ROOT, os.path.join(ROOT, "engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from api.db.postgres import schema as s  # noqa: E402
from core import model_store  # noqa: E402
from review.backfill import backfill, record_names  # noqa: E402

V = "ver-old"
UNIT_A, UNIT_B, UNIT_C = "Layer1.Cross|Dispatch", "Layer1.Cross|Hub", "Layer1.Cross|Empty"
LLM_UNIT = "This unit dispatches arithmetic operations to their handlers."
LLM_ADD = "AddOperation adds two buffers element by element."
LLM_GG = "GG holds a buffer index."

UNIT_DESCRIPTIONS = {UNIT_A: LLM_UNIT, UNIT_B: "N/A", UNIT_C: "-"}
UNIT_HEADERS = {
    UNIT_A: [
        {"declaration": "class AddOperation : public Operation {\npublic:\n    int apply();\n};",
         "information": LLM_ADD},
        # The name-derived fallback: never copied as if the LLM had written it.
        {"declaration": "class Operation {\npublic:\n    virtual ~Operation();\n};",
         "information": "Class for Operation"},
        {"declaration": "typedef struct GG {\n    int x;\n} GG;", "information": LLM_GG},
        # Two rows that disagree about one record: nothing is safe to copy.
        {"declaration": "struct Point {\n    int x;\n};", "information": "A point."},
        {"declaration": "int g_count = 0;", "information": "0"},
    ],
    UNIT_B: [{"declaration": "struct Point {\n    int x;\n};", "information": "Another point."}],
}


def _version(cx, version_id, *, llm=True, unit_description=None):
    now = datetime.datetime.now(datetime.timezone.utc)
    if not cx.execute(sa.select(s.projects.c.id).where(s.projects.c.id == "p")).first():
        cx.execute(sa.insert(s.projects).values(id="p", name="p", created_at=now))
    cx.execute(sa.insert(s.versions).values(
        id=version_id, project_id="p", version=version_id, created_at=now,
        resolved_config={"llm": {"descriptions": llm}}))
    records = {name: {"kind": kind, "name": name, "qualifiedName": name}
               for name, kind in (("AddOperation", "class"), ("Operation", "class"),
                                  ("GG", "struct"), ("Point", "struct"))}
    units = {uk: {"name": uk.split("|")[1], "path": "Layer1/Cross/" + uk.split("|")[1],
                  "fileName": uk.split("|")[1] + ".cpp", "functionIds": []}
             for uk in (UNIT_A, UNIT_B, UNIT_C)}
    if unit_description:
        units[UNIT_C]["description"] = unit_description
    model_store.persist_model(cx, "p", version_id, functions={}, globals={}, datadict=records,
                              edges={"typeUsers": {}, "macroUsers": {}}, hashes={}, units=units,
                              components={}, summaries={})
    for name, content in (("unit_descriptions.json", UNIT_DESCRIPTIONS),
                          ("unit_headers.json", UNIT_HEADERS)):
        cx.execute(sa.insert(s.version_output_files).values(
            version_id=version_id, rel_path="Layer1.Cross/" + name, group_name="Layer1.Cross",
            content=json.dumps(content)))


@pytest.fixture
def cx():
    eng = sa.create_engine("sqlite://")
    s.metadata.create_all(eng)
    with eng.begin() as conn:
        yield conn


def _unit_text(cx, version_id, unit_key):
    return model_store.load_units(cx, version_id)[unit_key]["description"]


def _struct_text(cx, version_id, key):
    return (model_store.load_types(cx, version_id)[key] or {}).get("description")


class TestAnOldVersion:
    def test_its_llm_unit_description_is_stored(self, cx):
        _version(cx, V)
        assert backfill(cx, V)["units"] == 1
        assert _unit_text(cx, V, UNIT_A) == LLM_UNIT
        assert _unit_text(cx, V, UNIT_B) == "", "N/A is no description"
        assert _unit_text(cx, V, UNIT_C) == ""

    def test_its_llm_struct_descriptions_are_stored(self, cx):
        _version(cx, V)
        assert backfill(cx, V)["structs"] == 2
        assert _struct_text(cx, V, "AddOperation") == LLM_ADD
        assert _struct_text(cx, V, "GG") == LLM_GG, "a typedef'd struct, by its tag or alias"

    def test_a_name_derived_sentence_is_not_llm_text(self, cx):
        _version(cx, V)
        backfill(cx, V)
        assert not _struct_text(cx, V, "Operation")

    def test_two_rows_that_disagree_copy_nothing(self, cx):
        _version(cx, V)
        backfill(cx, V)
        assert not _struct_text(cx, V, "Point")

    def test_a_second_run_finds_nothing_to_do(self, cx):
        _version(cx, V)
        backfill(cx, V)
        assert backfill(cx, V) == {"units": 0, "structs": 0}
        assert _unit_text(cx, V, UNIT_A) == LLM_UNIT


class TestWhatIsLeftAlone:
    def test_a_version_made_without_the_llm(self, cx):
        """Its earlier output holds the fallback itself, not LLM wording."""
        _version(cx, "ver-nollm", llm=False)
        assert backfill(cx, "ver-nollm") == {"units": 0, "structs": 0}
        assert _unit_text(cx, "ver-nollm", UNIT_A) == ""

    def test_a_version_phase_2_already_described(self, cx):
        """Made since the move: what it stores is what Phase 2 wrote."""
        _version(cx, "ver-new", unit_description="Stored by Phase 2.")
        assert backfill(cx, "ver-new")["units"] == 0
        assert _unit_text(cx, "ver-new", UNIT_A) == ""


class TestRecordNames:
    @pytest.mark.parametrize("declaration,names", [
        ("class AddOperation : public Operation {", ["AddOperation"]),
        ("struct Point {\n    int x;\n};", ["Point"]),
        ("typedef struct GG {\n    int x;\n} GG;", ["GG"]),
        ("typedef struct {\n    int w;\n} Widget_t;", ["Widget_t"]),
        ("typedef struct Tag {\n    int w;\n} Alias;", ["Tag", "Alias"]),
        ("int g_count = 0;", []),
        ("typedef int Count;", []),
    ])
    def test_the_names_a_row_declares(self, declaration, names):
        assert record_names(declaration) == names
