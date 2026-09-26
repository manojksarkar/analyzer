"""Corrections surviving into the next version (REQ-VR-01/02/03, REQ-ID-02/03).

This is where `slot_shape` finally gets a reader. It has been written and guarded since the schema
landed and nothing consumed it until now, so these tests are the first that can tell whether the
guard actually works rather than merely exists.

The failure it prevents is quiet and specific: v4 is generated from v3 on byte-identical source,
but a newer analyzer (or `cfgSimplification` crossing its threshold) renumbered the graph. `n7` is
now a different statement. `source_hash` is unchanged, so a gate built on that alone would carry
the correction onto the wrong node and the document would ship the right sentence against the wrong
box.
"""
import datetime
import json
import os
import sys

import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from api.db.postgres import schema as s
from core import model_store
from review import carry_forward as cf, slot

FID = "Comp|UnitA|ns::doThing|void"
CALLER = "App|AppMain|ns::start|void"
UNIT = "Comp|UnitA"
NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


def _cfg(*ids):
    return {"entry": ids[0], "exits": [ids[-1]],
            "nodes": [{"id": i, "type": "ACTION", "label": "llm " + i, "rawCode": "c",
                       "line": 1, "endLine": 1} for i in ids],
            "edges": [{"source": a, "target": b, "label": None} for a, b in zip(ids, ids[1:])]}


def _seed_version(cx, vid, *, source_hash="h1", node_ids=("n0", "n1", "n2"),
                  functions=(FID,), units=(UNIT,), behaviour=True, datadict=None):
    cx.execute(sa.insert(s.versions).values(id=vid, project_id="p", version=vid,
                                            created_at=NOW))
    model_store.persist_model(
        cx, "p", vid,
        functions={f: {"qualifiedName": "ns::x", "description": "d"} for f in functions},
        globals={}, datadict=datadict or {}, edges={"typeUsers": {}, "macroUsers": {}},
        hashes={f: source_hash for f in functions},
        units={u: {"name": u.split("|")[-1], "path": "a", "fileName": "f.cpp",
                   "includedHeaders": []} for u in units},
        components={}, summaries={})
    if node_ids:
        cx.execute(sa.insert(s.version_output_files).values(
            version_id=vid, rel_path="Sample/flowcharts/UnitA.json", group_name="Sample",
            content=json.dumps([{"name": "ns::doThing", "functionKey": FID,
                                 "cfg": _cfg(*node_ids), "flowchart": "digraph G {}"}])))
    if behaviour:
        cx.execute(sa.insert(s.version_output_files).values(
            version_id=vid, rel_path="Sample/behaviour_diagrams/_behaviour_pngs.json",
            group_name="Sample",
            content=json.dumps({"_docxRows": {"Comp": {"UnitA": [
                {"currentFunctionId": FID, "externalCallerId": CALLER,
                 "externalUnitFunction": "AppMain - start",
                 "behaviorDescription": ["start calls doThing"]}]}}})))


@pytest.fixture
def conn():
    eng = sa.create_engine("sqlite://")
    s.metadata.create_all(eng)
    with eng.begin() as cx:
        cx.execute(sa.insert(s.projects).values(id="p", name="p", created_at=NOW))
        _seed_version(cx, "v3")
        yield cx


def _override(conn, vid, kind, key, *, shape=None, human="Corrected.", orphaned=False):
    conn.execute(sa.insert(s.text_overrides).values(
        version_id=vid, slot_kind=kind, slot_key=key, llm_text="llm text",
        human_text=human, is_orphaned=orphaned, updated_at=NOW, slot_shape=shape))


class TestUnchangedCodeKeepsTheHumanText:
    def test_a_description_carries(self, conn):
        _override(conn, "v3", slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, FID))
        _seed_version(conn, "v4")
        out = cf.carry_overrides(conn, "v3", "v4")
        assert (out.carried, out.orphaned) == (1, 0)
        row = conn.execute(sa.select(s.text_overrides)
                           .where(s.text_overrides.c.version_id == "v4")).first()
        assert row.human_text == "Corrected." and row.llm_text == "llm text"
        assert row.is_orphaned in (False, 0)

    def test_a_unit_description_carries(self, conn):
        _override(conn, "v3", slot.UNIT_DESCRIPTION, slot.for_unit(UNIT))
        _seed_version(conn, "v4")
        assert cf.carry_overrides(conn, "v3", "v4").carried == 1

    def test_a_behaviour_row_carries(self, conn):
        _override(conn, "v3", slot.BEHAVIOUR_DESCRIPTION,
                  slot.for_behaviour_row(FID, CALLER))
        _seed_version(conn, "v4")
        assert cf.carry_overrides(conn, "v3", "v4").carried == 1

    def test_a_node_label_carries_when_the_graph_is_identical(self, conn):
        _override(conn, "v3", slot.NODE_LABEL, slot.for_node(FID, "n1"),
                  shape=slot.cfg_shape(["n0", "n1", "n2"]))
        _seed_version(conn, "v4")
        assert cf.carry_overrides(conn, "v3", "v4").carried == 1


class TestTheNodeListGuard:
    """REQ-ID-02's first real consumer."""

    def test_a_renumbered_graph_orphans_the_correction(self, conn):
        """Byte-identical source, different graph -- a newer CFG builder, or cfgSimplification
        crossing its threshold. `source_hash` is unchanged, so a gate built on that alone would
        put the right sentence on the wrong box."""
        _override(conn, "v3", slot.NODE_LABEL, slot.for_node(FID, "n1"),
                  shape=slot.cfg_shape(["n0", "n1", "n2"]))
        _seed_version(conn, "v4", source_hash="h1", node_ids=("n0", "n1", "n2", "n3"))
        out = cf.carry_overrides(conn, "v3", "v4")
        assert (out.carried, out.orphaned) == (0, 1)
        assert "renumbered" in out.reasons[0][2]

    def test_changed_code_orphans_it(self, conn):
        """REQ-VR-01: a function whose code changed gets fresh LLM text describing the new code."""
        _override(conn, "v3", slot.NODE_LABEL, slot.for_node(FID, "n1"),
                  shape=slot.cfg_shape(["n0", "n1", "n2"]))
        _seed_version(conn, "v4", source_hash="h2")
        out = cf.carry_overrides(conn, "v3", "v4")
        assert (out.carried, out.orphaned) == (0, 1)
        assert "code changed" in out.reasons[0][2]

    def test_a_correction_with_no_recorded_shape_does_not_carry(self, conn):
        """Written before `slot_shape` existed. It makes no claim about its graph, and "no claim"
        must not read as "verified"."""
        _override(conn, "v3", slot.NODE_LABEL, slot.for_node(FID, "n1"), shape=None)
        _seed_version(conn, "v4")
        assert cf.carry_overrides(conn, "v3", "v4").orphaned == 1

    def test_the_shape_travels_with_the_correction(self, conn):
        """An earlier version of this asserted the OPPOSITE -- that the shape is dropped,
        because it describes the baseline's graph.

        A real two-version run showed that was wrong. Dropping it means the NEXT generation sees
        "no claim", and `shape_matches` refuses a missing claim, so a node correction could
        survive exactly one version and then orphan itself for no reason anybody could see.

        The shape is a claim about the graph the TEXT was written for, and that claim stays true
        as the text travels. What validates it is `phase3_overrides`, against the CFG actually
        being written.
        """
        shape = slot.cfg_shape(["n0", "n1", "n2"])
        _override(conn, "v3", slot.NODE_LABEL, slot.for_node(FID, "n1"), shape=shape)
        _seed_version(conn, "v4")
        cf.carry_overrides(conn, "v3", "v4")
        row = conn.execute(sa.select(s.text_overrides)
                           .where(s.text_overrides.c.version_id == "v4")).first()
        assert row.slot_shape == shape

    def test_an_orphaned_correction_carries_no_shape(self, conn):
        """It makes no claim worth re-checking, and leaving one would invite a later run to
        treat it as verified."""
        _override(conn, "v3", slot.NODE_LABEL, slot.for_node(FID, "n1"),
                  shape=slot.cfg_shape(["n0", "n1", "n2"]))
        _seed_version(conn, "v4", source_hash="h2")          # code changed -> orphan
        cf.carry_overrides(conn, "v3", "v4")
        row = conn.execute(sa.select(s.text_overrides)
                           .where(s.text_overrides.c.version_id == "v4")).first()
        assert bool(row.is_orphaned) and row.slot_shape is None

    def test_a_target_with_no_flowchart_yet_still_carries(self, conn):
        """THE BUG A REAL RUN FOUND, and the reason this class exists in its current form.

        The carry-forward runs in Phase 2. Phase 3 is what produces the target's flowchart, so
        at carry time there is normally NOTHING to compare the shape against. Comparing against
        nothing and orphaning meant a node correction could never survive a generation -- proven
        on a two-version run where the source hash, the baseline shape and the recorded shape all
        matched and the correction orphaned anyway.

        So the check falls back to the BASELINE's graph, which is what is being carried from.
        """
        shape = slot.cfg_shape(["n0", "n1", "n2"])
        _override(conn, "v3", slot.NODE_LABEL, slot.for_node(FID, "n1"), shape=shape)
        _seed_version(conn, "v4", node_ids=())               # no flowchart output yet
        out = cf.carry_overrides(conn, "v3", "v4")
        assert (out.carried, out.orphaned) == (1, 0), out.reasons

    def test_a_baseline_whose_graph_disagrees_still_orphans(self, conn):
        """The fallback is a fallback, not a free pass: if even the baseline's graph does not
        match the recorded shape, the correction was never validly placed."""
        _override(conn, "v3", slot.NODE_LABEL, slot.for_node(FID, "n1"),
                  shape=slot.cfg_shape(["completely", "different"]))
        _seed_version(conn, "v4", node_ids=())
        out = cf.carry_overrides(conn, "v3", "v4")
        assert (out.carried, out.orphaned) == (0, 1)


class TestNothingIsEverDropped:
    def test_a_deleted_function_is_carried_orphaned(self, conn):
        """REQ-ID-03. It is the user's work and it is training data, and a rename may be
        reverted."""
        _override(conn, "v3", slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, FID))
        _seed_version(conn, "v4", functions=("Comp|UnitA|ns::other|void",))
        out = cf.carry_overrides(conn, "v3", "v4")
        assert (out.carried, out.orphaned) == (0, 1)
        assert conn.execute(sa.select(sa.func.count()).select_from(s.text_overrides)
                            .where(s.text_overrides.c.version_id == "v4")).scalar() == 1

    def test_an_already_orphaned_row_stays_orphaned(self, conn):
        """Whatever stopped resolving has not come back just because a version was generated."""
        _override(conn, "v3", slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, FID),
                  orphaned=True)
        _seed_version(conn, "v4")
        assert cf.carry_overrides(conn, "v3", "v4").orphaned == 1

    def test_every_orphan_carries_a_reason(self, conn):
        """A reviewer whose correction stopped applying is owed an explanation, not a silent
        disappearance."""
        _override(conn, "v3", slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, FID))
        _seed_version(conn, "v4", functions=("Comp|UnitA|ns::other|void",))
        assert all(r[2].strip() for r in cf.carry_overrides(conn, "v3", "v4").reasons)


class TestFullRegeneration:
    def test_no_baseline_carries_nothing_and_deletes_nothing(self, conn):
        """REQ-VR-03. `--full` is the standing remedy for several problems, so it must never
        destroy a reviewer's work."""
        _override(conn, "v3", slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, FID))
        _seed_version(conn, "v4")
        assert cf.carry_overrides(conn, "", "v4") == cf.Carried(0, 0, ())
        assert conn.execute(sa.select(sa.func.count()).select_from(s.text_overrides)
                            .where(s.text_overrides.c.version_id == "v3")).scalar() == 1

    def test_carrying_onto_itself_is_a_no_op(self, conn):
        _override(conn, "v3", slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, FID))
        assert cf.carry_overrides(conn, "v3", "v3").carried == 0


class TestTheTargetWins:
    def test_a_correction_made_against_the_new_version_is_not_overwritten(self, conn):
        """It is newer than anything the baseline can offer."""
        key = slot.for_entity(slot.DESCRIPTION, FID)
        _override(conn, "v3", slot.DESCRIPTION, key, human="From the baseline.")
        _seed_version(conn, "v4")
        _override(conn, "v4", slot.DESCRIPTION, key, human="Made against v4.")
        assert cf.carry_overrides(conn, "v3", "v4").carried == 0
        row = conn.execute(sa.select(s.text_overrides)
                           .where(s.text_overrides.c.version_id == "v4")).first()
        assert row.human_text == "Made against v4."


class TestWhatPhase3Receives:
    def test_the_config_payload_has_the_shape_the_views_read(self, conn):
        _override(conn, "v3", slot.NODE_LABEL, slot.for_node(FID, "n1"), human="Node text.")
        _override(conn, "v3", slot.BEHAVIOUR_DESCRIPTION,
                  slot.for_behaviour_row(FID, CALLER), human="Bullet one.")
        payload = cf.overrides_for_config(conn, "v3")
        assert payload["nodeLabel"] == {FID: {"n1": "Node text."}}
        assert payload["behaviourDescription"] == {
            slot.for_behaviour_row(FID, CALLER): "Bullet one."}

    def test_orphaned_rows_are_not_applied(self, conn):
        """They describe something that is no longer there; applying one would put the right
        sentence on whatever now occupies that position.

        Guarded twice -- by this query and again inside `labels_by_flowchart` -- so removing
        either alone changes nothing this test can see. That is deliberate defence in depth, not
        coverage: the second guard is pinned in test_review_phase3_overrides.
        """
        _override(conn, "v3", slot.NODE_LABEL, slot.for_node(FID, "n1"), orphaned=True)
        assert cf.overrides_for_config(conn, "v3")["nodeLabel"] == {}

    def test_the_five_model_backed_kinds_are_absent(self, conn):
        """Their text is in the model already, carried there by the engine's own
        carry-forward. Phase 3 derives from the model, so repeating them here would be a second
        copy of the same fact."""
        _override(conn, "v3", slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, FID))
        payload = cf.overrides_for_config(conn, "v3")
        assert set(payload) == {"nodeLabel", "nodeLabelShapes", "behaviourDescription"}
        assert payload["nodeLabel"] == {} and payload["behaviourDescription"] == {}

    def test_config_is_copied_not_mutated(self, conn):
        """The run's config is shared; attaching in place would leave a later run in the same
        process applying another version's corrections."""
        base = {"views": {"flowcharts": True}}
        out = cf.config_with_overrides(conn, "v3", base)
        assert "_analyzerTextOverrides" in out
        assert "_analyzerTextOverrides" not in base

    def test_a_version_with_no_corrections_is_cheap_and_empty(self, conn):
        payload = cf.overrides_for_config(conn, "v3")
        assert payload["nodeLabel"] == {} and payload["behaviourDescription"] == {}

    def test_the_shapes_travel_beside_the_labels(self, conn):
        """Phase 3 needs both: the text to write, and the claim about which graph it was written
        for. Without the second it would apply a correction to a renumbered flowchart."""
        shape = slot.cfg_shape(["n0", "n1", "n2"])
        _override(conn, "v3", slot.NODE_LABEL, slot.for_node(FID, "n1"), human="Node text.",
                  shape=shape)
        payload = cf.overrides_for_config(conn, "v3")
        assert payload["nodeLabel"] == {FID: {"n1": "Node text."}}
        assert payload["nodeLabelShapes"] == {FID: shape}


# ---------------------------------------------------------------------------------------------
# What a NEW version actually holds when the carry runs: its parse, and nothing Phase 2 builds.
#
# The tests above seed the target WITH units, which no real run has at that point -- Phase 2
# builds them after the carry. That is how every unit description came out orphaned on a real
# two-version run while these tests passed. Measured: v1 corrected, v2 generated from it, and v2
# showed "that unit is not in the new version" and the LLM's (empty) text.
# ---------------------------------------------------------------------------------------------
STRUCT = "GG"
GG = {"kind": "struct", "name": "GG", "qualifiedName": "GG",
      "fields": [{"name": "x", "type": "int"}], "range": "NA",
      "location": {"file": "a/gg.h", "line": 3}}


class TestTheCarryMatchesWhatANewVersionHolds:
    def test_a_unit_description_carries_before_phase_2_has_built_units(self, conn):
        _override(conn, "v3", slot.UNIT_DESCRIPTION, slot.for_unit(UNIT))
        _seed_version(conn, "v4", units=())                   # functions, but no units yet
        out = cf.carry_overrides(conn, "v3", "v4")
        assert (out.carried, out.orphaned) == (1, 0), out.reasons

    def test_a_unit_with_nothing_left_in_it_is_orphaned(self, conn):
        _override(conn, "v3", slot.UNIT_DESCRIPTION, slot.for_unit(UNIT))
        _seed_version(conn, "v4", units=(), functions=("Comp|UnitB|ns::other|void",))
        out = cf.carry_overrides(conn, "v3", "v4")
        assert out.orphaned == 1 and "unit" in out.reasons[0][2]

    def test_a_struct_description_carries_though_types_have_no_hash(self, conn):
        """Most data-dictionary entries have no source hash (19 of 91 on the sample)."""
        _seed_version(conn, "v3b", datadict={STRUCT: dict(GG, description="written by the LLM")})
        _override(conn, "v3b", slot.STRUCT_DESCRIPTION,
                  slot.for_entity(slot.STRUCT_DESCRIPTION, STRUCT))
        _seed_version(conn, "v4", datadict={STRUCT: dict(GG)})
        out = cf.carry_overrides(conn, "v3b", "v4")
        assert (out.carried, out.orphaned) == (1, 0), out.reasons

    def test_a_struct_that_only_moved_still_carries(self, conn):
        _seed_version(conn, "v3b", datadict={STRUCT: dict(GG)})
        _override(conn, "v3b", slot.STRUCT_DESCRIPTION,
                  slot.for_entity(slot.STRUCT_DESCRIPTION, STRUCT))
        moved = dict(GG, location={"file": "a/gg.h", "line": 9})
        _seed_version(conn, "v4", datadict={STRUCT: moved})
        assert cf.carry_overrides(conn, "v3b", "v4").carried == 1

    def test_a_struct_whose_definition_changed_is_orphaned(self, conn):
        _seed_version(conn, "v3b", datadict={STRUCT: dict(GG)})
        _override(conn, "v3b", slot.STRUCT_DESCRIPTION,
                  slot.for_entity(slot.STRUCT_DESCRIPTION, STRUCT))
        changed = dict(GG, fields=[{"name": "y", "type": "long"}])
        _seed_version(conn, "v4", datadict={STRUCT: changed})
        out = cf.carry_overrides(conn, "v3b", "v4")
        assert out.orphaned == 1 and "definition changed" in out.reasons[0][2]

    def test_a_struct_that_is_gone_is_orphaned(self, conn):
        _seed_version(conn, "v3b", datadict={STRUCT: dict(GG)})
        _override(conn, "v3b", slot.STRUCT_DESCRIPTION,
                  slot.for_entity(slot.STRUCT_DESCRIPTION, STRUCT))
        _seed_version(conn, "v4")
        assert cf.carry_overrides(conn, "v3b", "v4").orphaned == 1


class TestChangedCodeGetsFreshText:
    """`REQ-VR-01` for the function kinds, as node labels already had it. Carried as live, the
    correction claimed to be in force over the fresh LLM text the new code received."""

    @pytest.mark.parametrize("kind", [slot.DESCRIPTION, slot.BEHAVIOUR_INPUT_NAME,
                                      slot.BEHAVIOUR_OUTPUT_NAME])
    def test_it_is_kept_but_not_applied(self, conn, kind):
        _override(conn, "v3", kind, slot.for_entity(kind, FID))
        _seed_version(conn, "v4", source_hash="h2")
        out = cf.carry_overrides(conn, "v3", "v4")
        assert (out.carried, out.orphaned) == (0, 1)
        assert "code changed" in out.reasons[0][2]
        row = conn.execute(sa.select(s.text_overrides)
                           .where(s.text_overrides.c.version_id == "v4")).first()
        assert row.human_text == "Corrected."                 # kept (REQ-ID-03)

    @pytest.mark.parametrize("kind", [slot.DESCRIPTION, slot.BEHAVIOUR_INPUT_NAME,
                                      slot.BEHAVIOUR_OUTPUT_NAME])
    def test_unchanged_code_still_carries_it(self, conn, kind):
        _override(conn, "v3", kind, slot.for_entity(kind, FID))
        _seed_version(conn, "v4", source_hash="h1")
        assert cf.carry_overrides(conn, "v3", "v4").carried == 1


class TestCorrectionsGoBackIntoTheRebuiltModel:
    """`apply_live_corrections`: what Phase 2 calls once it has rebuilt the model."""

    def _model(self):
        return {"functions": {FID: {"description": "llm d", "behaviourInputName": "llm in",
                                    "behaviourOutputName": "llm out"}},
                "globalVariables": {},
                "units": {UNIT: {"name": "UnitA", "description": "llm unit"}},
                "dataDictionary": {STRUCT: dict(GG, description="llm struct")}}

    def _all(self, conn):
        for kind, key in [(slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, FID)),
                          (slot.BEHAVIOUR_INPUT_NAME,
                           slot.for_entity(slot.BEHAVIOUR_INPUT_NAME, FID)),
                          (slot.BEHAVIOUR_OUTPUT_NAME,
                           slot.for_entity(slot.BEHAVIOUR_OUTPUT_NAME, FID)),
                          (slot.UNIT_DESCRIPTION, slot.for_unit(UNIT)),
                          (slot.STRUCT_DESCRIPTION,
                           slot.for_entity(slot.STRUCT_DESCRIPTION, STRUCT))]:
            _override(conn, "v3", kind, key, human="human " + kind)

    def test_every_model_backed_kind_is_put_back(self, conn):
        self._all(conn)
        model = self._model()
        changed = cf.apply_live_corrections(conn, "v3", model)
        f = model["functions"][FID]
        assert f["description"] == "human description"
        assert f["behaviourInputName"] == "human behaviourInputName"
        assert f["behaviourOutputName"] == "human behaviourOutputName"
        assert model["units"][UNIT]["description"] == "human unitDescription"
        assert model["dataDictionary"][STRUCT]["description"] == "human structDescription"
        assert changed == {"functions": 3, "units": 1, "dataDictionary": 1}

    def test_an_orphan_is_never_applied(self, conn):
        _override(conn, "v3", slot.UNIT_DESCRIPTION, slot.for_unit(UNIT), orphaned=True)
        model = self._model()
        assert cf.apply_live_corrections(conn, "v3", model) == {}
        assert model["units"][UNIT]["description"] == "llm unit"

    def test_the_phase_3_kinds_are_left_to_phase_3(self, conn):
        _override(conn, "v3", slot.NODE_LABEL, slot.for_node(FID, "n1"))
        _override(conn, "v3", slot.BEHAVIOUR_DESCRIPTION, slot.for_behaviour_row(FID, CALLER))
        assert cf.apply_live_corrections(conn, "v3", self._model()) == {}

    def test_what_is_already_there_is_not_counted(self, conn):
        self._all(conn)
        model = self._model()
        cf.apply_live_corrections(conn, "v3", model)
        assert cf.apply_live_corrections(conn, "v3", model) == {}

    def test_a_slot_missing_from_the_model_is_skipped(self, conn):
        _override(conn, "v3", slot.UNIT_DESCRIPTION, slot.for_unit("Comp|Gone"))
        assert cf.apply_live_corrections(conn, "v3", self._model()) == {}

    def test_another_versions_corrections_are_not_applied(self, conn):
        self._all(conn)
        _seed_version(conn, "v4")
        assert cf.apply_live_corrections(conn, "v4", self._model()) == {}
