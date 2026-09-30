"""Saving a correction: what it writes, and what it must never overwrite.

Step 3 of REVIEW_UPDATE_DESIGN. The rules tested here are the ones whose breakage is SILENT --
an override that saves and never appears, an LLM original quietly replaced by human prose, a
history trim that eats the wrong end. None of those raise; all of them ship.

The database is sqlite built from the real `schema.py` metadata, so the tables, constraints and
indexes under test are the ones Postgres gets.
"""
import datetime
import os
import sys

import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from api.db.postgres import schema as s
from review import cascade, derive, override_service as svc, resolver, slot

FID = "Comp|UnitA|GCM_SetGcStartTime|PUINT32"
GID = "Comp|UnitA|gRetryCount"
UNIT = "Comp|UnitA"
TYPE = "Comp||Cfg|"


def _model():
    return {
        "functions": {FID: {"qualifiedName": "ns::GCM_SetGcStartTime",
                            "description": "Sets the time.",
                            "behaviourInputName": "Timer value",
                            "behaviourOutputName": "Status"}},
        "globalVariables": {GID: {"qualifiedName": "ns::gRetryCount",
                                  "description": "Counts retries."}},
        "units": {UNIT: {"name": "UnitA", "description": "Manages GC."}},
        "dataDictionary": {TYPE: {"kind": "struct", "name": "Cfg",
                                  "description": "Holds config."}},
    }


@pytest.fixture
def conn():
    eng = sa.create_engine("sqlite://")
    s.metadata.create_all(eng)
    with eng.begin() as cx:
        now = datetime.datetime.now(datetime.timezone.utc)
        cx.execute(sa.insert(s.projects).values(id="p", name="p", created_at=now))
        cx.execute(sa.insert(s.versions).values(id="v1", project_id="p", version="v1",
                                                created_at=now))
        yield cx


def _apply(conn, models, kind, key, text, **kw):
    return svc.apply_override(conn, "v1", kind, key, text, models=models, **kw)


# ---------------------------------------------------------------------------
class TestTheModelIsWritten:
    def test_a_function_description_lands_in_the_model(self, conn):
        m = svc.ModelAccess(artifacts=_model())
        out = _apply(conn, m, slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, FID),
                     "Sets the garbage-collection start time.")
        assert m.artifact("functions")[FID]["description"] == \
            "Sets the garbage-collection start time."
        assert out.location == resolver.Location("functions", FID, "description")

    def test_a_global_description_resolves_to_globals(self, conn):
        m = svc.ModelAccess(artifacts=_model())
        out = _apply(conn, m, slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, GID),
                     "Counts write retries.")
        assert out.location.artifact == "globalVariables"
        assert m.artifact("globalVariables")[GID]["description"] == "Counts write retries."

    def test_a_unit_description_lands_on_the_unit(self, conn):
        m = svc.ModelAccess(artifacts=_model())
        _apply(conn, m, slot.UNIT_DESCRIPTION, slot.for_unit(UNIT), "Runs GC for the drive.")
        assert m.artifact("units")[UNIT]["description"] == "Runs GC for the drive."

    def test_a_struct_description_lands_in_the_data_dictionary(self, conn):
        m = svc.ModelAccess(artifacts=_model())
        _apply(conn, m, slot.STRUCT_DESCRIPTION,
               slot.for_entity(slot.STRUCT_DESCRIPTION, TYPE), "Tuning parameters.")
        assert m.artifact("dataDictionary")[TYPE]["description"] == "Tuning parameters."

    @pytest.mark.parametrize("key,entry,why", [
        ("MAX_LEN", {"kind": "define", "name": "MAX_LEN", "value": "64"}, "is a define"),
        ("Mode_t", {"kind": "enum", "name": "Mode_t"}, "is an enum"),
        ("UINT8", {"kind": "typedef", "name": "UINT8"}, "is a typedef"),
        ("Cfg::Part", {"kind": "struct", "name": "Part", "nestedIn": "Cfg"},
         "declared inside Cfg"),
    ])
    def test_a_type_no_document_describes_is_refused(self, conn, key, entry, why):
        """Its entry has a `description` field the model would store, and no row prints it:
        the save would succeed and the correction never appear. Refused as not found."""
        model = _model()
        model["dataDictionary"][key] = entry
        m = svc.ModelAccess(artifacts=model)
        with pytest.raises(svc.SlotUnknown, match=why):
            _apply(conn, m, slot.STRUCT_DESCRIPTION,
                   slot.for_entity(slot.STRUCT_DESCRIPTION, key), "Words.")
        assert "description" not in m.artifact("dataDictionary")[key]

    def test_a_nested_record_a_typedef_row_shows_is_editable(self, conn):
        """`typedef Cfg::Part Part_t;` prints Part's description on its own row."""
        model = _model()
        model["dataDictionary"]["Cfg::Part"] = {"kind": "struct", "name": "Part",
                                                "nestedIn": "Cfg"}
        model["dataDictionary"]["Part_t"] = {"kind": "typedef", "name": "Part_t",
                                             "underlyingType": "Cfg::Part"}
        m = svc.ModelAccess(artifacts=model)
        _apply(conn, m, slot.STRUCT_DESCRIPTION,
               slot.for_entity(slot.STRUCT_DESCRIPTION, "Cfg::Part"), "One part.")
        assert m.artifact("dataDictionary")["Cfg::Part"]["description"] == "One part."

    def test_a_behaviour_name_lands_on_its_own_field(self, conn):
        m = svc.ModelAccess(artifacts=_model())
        _apply(conn, m, slot.BEHAVIOUR_INPUT_NAME,
               slot.for_entity(slot.BEHAVIOUR_INPUT_NAME, FID), "GC timer value")
        fn = m.artifact("functions")[FID]
        assert fn["behaviourInputName"] == "GC timer value"
        assert fn["description"] == "Sets the time.", "the description was not the target"

    def test_only_the_touched_artifact_is_written_back(self, conn):
        """A one-field edit must not rewrite the whole model. model_repo's flush guard has
        already been the subject of one defect; handing it four artifacts when one changed is
        how a narrow edit becomes a wide one."""
        m = svc.ModelAccess(artifacts=_model())
        out = _apply(conn, m, slot.UNIT_DESCRIPTION, slot.for_unit(UNIT), "Runs GC.")
        assert list(out.artifacts_written) == ["units"]


class TestTheOverrideRow:
    def test_both_texts_are_stored(self, conn):
        m = svc.ModelAccess(artifacts=_model())
        _apply(conn, m, slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, FID), "New words.")
        row = svc.get_override(conn, "v1", slot.DESCRIPTION,
                               slot.for_entity(slot.DESCRIPTION, FID))
        assert row.llm_text == "Sets the time."
        assert row.human_text == "New words."
        assert row.is_orphaned is False or row.is_orphaned == 0

    def test_the_llm_original_survives_a_second_edit(self, conn):
        """THE rule of REQ-ST-03. By the second edit the model holds the HUMAN's text, so
        re-reading it would overwrite the original with human prose -- leaving nothing to undo
        to and a training pair that is human-vs-human, which teaches the opposite of one."""
        m = svc.ModelAccess(artifacts=_model())
        key = slot.for_entity(slot.DESCRIPTION, FID)
        _apply(conn, m, slot.DESCRIPTION, key, "First correction.")
        _apply(conn, m, slot.DESCRIPTION, key, "Second correction.")
        _apply(conn, m, slot.DESCRIPTION, key, "Third correction.")
        row = svc.get_override(conn, "v1", slot.DESCRIPTION, key)
        assert row.llm_text == "Sets the time."
        assert row.human_text == "Third correction."

    def test_the_second_edit_reports_the_text_it_replaced(self, conn):
        m = svc.ModelAccess(artifacts=_model())
        key = slot.for_entity(slot.DESCRIPTION, FID)
        first = _apply(conn, m, slot.DESCRIPTION, key, "First.")
        second = _apply(conn, m, slot.DESCRIPTION, key, "Second.")
        assert first.first_edit and first.previous_text == "Sets the time."
        assert not second.first_edit and second.previous_text == "First."

    def test_one_row_per_slot(self, conn):
        m = svc.ModelAccess(artifacts=_model())
        key = slot.for_entity(slot.DESCRIPTION, FID)
        for i in range(4):
            _apply(conn, m, slot.DESCRIPTION, key, "Edit %d." % i)
        n = conn.execute(sa.select(sa.func.count()).select_from(s.text_overrides)).scalar()
        assert n == 1, "the current text is a lookup, not the newest of many rows (REQ-ST-05)"

    def test_two_versions_do_not_share_an_override(self, conn):
        """REQ-ST-02. Editing v3 must not change v1's document."""
        now = datetime.datetime.now(datetime.timezone.utc)
        conn.execute(sa.insert(s.versions).values(id="v2", project_id="p", version="v2",
                                                  created_at=now))
        key = slot.for_entity(slot.DESCRIPTION, FID)
        svc.apply_override(conn, "v1", slot.DESCRIPTION, key, "v1 text.",
                           models=svc.ModelAccess(artifacts=_model()))
        svc.apply_override(conn, "v2", slot.DESCRIPTION, key, "v2 text.",
                           models=svc.ModelAccess(artifacts=_model()))
        assert svc.get_override(conn, "v1", slot.DESCRIPTION, key).human_text == "v1 text."
        assert svc.get_override(conn, "v2", slot.DESCRIPTION, key).human_text == "v2 text."


class TestTheFlowchartShape:
    """REQ-ID-02's capture is not wired yet because `nodeLabel` cannot be written yet. These
    pin that it is genuinely absent rather than half-present -- a column that is written
    sometimes is worse than one that is never written, because the carry-forward guard would
    then pass for whichever rows happened to get one."""

    def test_no_override_this_service_writes_carries_a_shape(self, conn):
        m = svc.ModelAccess(artifacts=_model())
        for kind, key in ((slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, FID)),
                          (slot.UNIT_DESCRIPTION, slot.for_unit(UNIT)),
                          (slot.STRUCT_DESCRIPTION,
                           slot.for_entity(slot.STRUCT_DESCRIPTION, TYPE))):
            _apply(conn, m, kind, key, "Words.")
        rows = conn.execute(sa.select(s.text_overrides.c.slot_shape)).fetchall()
        assert rows and all(r.slot_shape is None for r in rows)

    def test_a_shapeless_row_is_not_reusable_by_the_carry_forward_guard(self):
        """Which is what makes "absent" safe: REQ-ID-02 refuses to carry a node override whose
        shape makes no claim, so nothing written today can be reused wrongly tomorrow."""
        assert not slot.shape_matches(None, slot.cfg_shape(["n0", "n1"]))

    def test_other_kinds_store_no_shape(self, conn):
        m = svc.ModelAccess(artifacts=_model())
        _apply(conn, m, slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, FID), "Words.")
        row = svc.get_override(conn, "v1", slot.DESCRIPTION,
                               slot.for_entity(slot.DESCRIPTION, FID))
        assert row.slot_shape is None, "a description has no graph to be wrong about"


class TestHistory:
    def _edit_n(self, conn, n, depth=None):
        m = svc.ModelAccess(artifacts=_model())
        key = slot.for_entity(slot.DESCRIPTION, FID)
        for i in range(n):
            _apply(conn, m, slot.DESCRIPTION, key, "Edit %d." % i, history_depth=depth)
        return key

    def test_every_edit_is_recorded(self, conn):
        key = self._edit_n(conn, 3)
        rows = svc.history_for(conn, "v1", slot.DESCRIPTION, key)
        assert [r.human_text for r in rows] == ["Edit 0.", "Edit 1.", "Edit 2."]
        assert [r.seq for r in rows] == [1, 2, 3]

    def test_the_oldest_edits_are_dropped_past_n(self, conn):
        """REQ-ST-04 with N=3 and five edits: the newest three remain."""
        key = self._edit_n(conn, 5, depth=3)
        rows = svc.history_for(conn, "v1", slot.DESCRIPTION, key)
        assert [r.human_text for r in rows] == ["Edit 2.", "Edit 3.", "Edit 4."]

    def test_the_llm_original_is_not_counted_against_n(self, conn):
        """It is not in the history table at all, which is what makes "never evicted"
        structural rather than a rule someone has to remember."""
        key = self._edit_n(conn, 5, depth=1)
        assert len(svc.history_for(conn, "v1", slot.DESCRIPTION, key)) == 1
        assert svc.get_override(conn, "v1", slot.DESCRIPTION, key).llm_text == "Sets the time."

    def test_a_depth_below_one_is_refused(self, conn):
        with pytest.raises(svc.OverrideError):
            self._edit_n(conn, 1, depth=0)

    def test_history_is_per_slot(self, conn):
        m = svc.ModelAccess(artifacts=_model())
        a = slot.for_entity(slot.DESCRIPTION, FID)
        b = slot.for_unit(UNIT)
        _apply(conn, m, slot.DESCRIPTION, a, "Fn text.")
        _apply(conn, m, slot.UNIT_DESCRIPTION, b, "Unit text.")
        assert [r.seq for r in svc.history_for(conn, "v1", slot.DESCRIPTION, a)] == [1]
        assert [r.seq for r in svc.history_for(conn, "v1", slot.UNIT_DESCRIPTION, b)] == [1]


class TestRejection:
    def test_empty_text_is_refused(self, conn):
        m = svc.ModelAccess(artifacts=_model())
        for bad in ("", "   ", "\t\n"):
            with pytest.raises(svc.EmptyText):
                _apply(conn, m, slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, FID), bad)

    def test_an_empty_update_does_not_touch_the_model(self, conn):
        """Checked before anything is read or written: an empty update that got as far as the
        model would have erased the LLM's text with nothing in its place."""
        m = svc.ModelAccess(artifacts=_model())
        with pytest.raises(svc.EmptyText):
            _apply(conn, m, slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, FID), "  ")
        assert m.artifact("functions")[FID]["description"] == "Sets the time."
        assert conn.execute(sa.select(sa.func.count())
                            .select_from(s.text_overrides)).scalar() == 0

    def test_a_slot_that_names_nothing_is_a_404(self, conn):
        m = svc.ModelAccess(artifacts=_model())
        with pytest.raises(svc.SlotUnknown):
            _apply(conn, m, slot.DESCRIPTION,
                   slot.for_entity(slot.DESCRIPTION, "Comp|UnitA|gone|"), "Words.")

    def test_a_malformed_key_is_a_404_not_a_crash(self, conn):
        """An empty key parses to an empty part, which `slot.parse` refuses. The service must
        turn that into the same 404 as a key that simply names nothing, not let a
        `SlotKeyError` escape to the API as a 500."""
        m = svc.ModelAccess(artifacts=_model())
        for bad in ("", "   ", slot.SEP):
            with pytest.raises(svc.SlotUnknown):
                _apply(conn, m, slot.DESCRIPTION, bad, "Words.")

    def test_an_unknown_kind_is_refused(self, conn):
        m = svc.ModelAccess(artifacts=_model())
        with pytest.raises(svc.SlotUnknown):
            _apply(conn, m, "somethingElse", FID, "Words.")

    def test_a_view_only_kind_says_so_rather_than_pretending(self, conn):
        """nodeLabel and behaviourDescription live in Phase-3 output with no model field. A
        silent no-op, or a write the next derivation reverts, is how the September defects got
        as far as they did."""
        m = svc.ModelAccess(artifacts=_model())
        with pytest.raises(svc.NotEditableHere):
            _apply(conn, m, slot.NODE_LABEL, slot.for_node(FID, "n3"), "Check the flag.")
        with pytest.raises(svc.NotEditableHere):
            _apply(conn, m, slot.BEHAVIOUR_DESCRIPTION,
                   slot.for_behaviour_row(FID, "UnitB - doThing"), "Calls doThing.")

    def test_a_rejected_edit_leaves_no_history(self, conn):
        m = svc.ModelAccess(artifacts=_model())
        with pytest.raises(svc.SlotUnknown):
            _apply(conn, m, slot.DESCRIPTION,
                   slot.for_entity(slot.DESCRIPTION, "Comp|UnitA|gone|"), "Words.")
        assert conn.execute(sa.select(sa.func.count())
                            .select_from(s.text_override_history)).scalar() == 0


class TestDerivation:
    def test_the_deriver_is_called_and_its_views_stamped(self, conn):
        seen = {}

        def _derive(*, version_id, slot_kind, location):
            seen.update(version_id=version_id, slot_kind=slot_kind, location=location)
            return ["interfaceTables"]

        m = svc.ModelAccess(artifacts=_model())
        out = _apply(conn, m, slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, FID),
                     "Words.", derive=_derive)
        assert seen["slot_kind"] == slot.DESCRIPTION
        assert list(out.views_derived) == ["interfaceTables"]
        rows = conn.execute(sa.select(s.view_derivations)).fetchall()
        # Stamped for the saved slot's component -- the guard judges every correction by its own
        # component's derivation, so a stamp naming none would vouch for nothing.
        assert [(r.view_name, r.group_name) for r in rows] == [("interfaceTables", "comp")]

    def test_a_slot_that_names_no_component_stamps_nothing(self, conn):
        """A parsed struct is keyed by its type's name (`Point`), which names no component. A
        stamp for no component would vouch for nothing; the guard asks every component instead."""
        model = _model()
        model["dataDictionary"]["Point"] = {"kind": "struct", "name": "Point"}
        m = svc.ModelAccess(artifacts=model)
        _apply(conn, m, slot.STRUCT_DESCRIPTION, slot.for_entity(slot.STRUCT_DESCRIPTION, "Point"),
               "Words.", derive=lambda **kw: ["unitHeaders"])
        assert conn.execute(sa.select(sa.func.count())
                            .select_from(s.view_derivations)).scalar() == 0

    def test_a_re_derivation_moves_the_stamp_forward(self, conn):
        """A re-derived view must have its row moved forward, not appended: the guard reads the
        newest stamp per view and component, and a second row is a second answer."""
        t0 = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        t1 = datetime.datetime(2026, 2, 1, tzinfo=datetime.timezone.utc)
        m = svc.ModelAccess(artifacts=_model())
        key = slot.for_entity(slot.DESCRIPTION, FID)
        d = lambda **kw: ["interfaceTables"]
        _apply(conn, m, slot.DESCRIPTION, key, "One.", derive=d, now=t0)
        _apply(conn, m, slot.DESCRIPTION, key, "Two.", derive=d, now=t1)
        rows = conn.execute(sa.select(s.view_derivations)).fetchall()
        assert len(rows) == 1, "one row per (version, view, component), moved forward not appended"

    def test_no_deriver_stamps_nothing(self, conn):
        m = svc.ModelAccess(artifacts=_model())
        _apply(conn, m, slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, FID), "Words.")
        assert conn.execute(sa.select(sa.func.count())
                            .select_from(s.view_derivations)).scalar() == 0


class TestTheViewMapping:
    def test_every_editable_kind_maps_to_a_view(self):
        """A kind nobody mapped invalidates nothing: the model holds the human's text, the
        document keeps the LLM's, and the edit appears to save."""
        for kind in slot.ALL_KINDS:
            assert derive.views_for(kind), kind

    def test_an_unmapped_kind_raises_rather_than_returning_nothing(self):
        with pytest.raises(slot.SlotKeyError):
            derive.views_for("somethingElse")

    def test_every_mapped_view_is_a_registered_view(self):
        """A mapping that names a view nobody registers is found only when a correction is
        derived -- `make_deriver` raises then. The unit header table leaving the DOCX exporter
        for a view of its own is exactly the kind of move that strands a name."""
        from views.registry import VIEW_REGISTRY
        import views  # noqa: F401 - importing the package is what registers the views
        for kind in slot.ALL_KINDS:
            for name in derive.views_for(kind):
                assert name in VIEW_REGISTRY, (kind, name)

    def test_a_struct_description_rebuilds_the_unit_header_table(self):
        """The table's information column for a struct, class or union row is the stored
        description; the interface tables never show it."""
        assert derive.views_for(slot.STRUCT_DESCRIPTION) == ("unitHeaders",)

    def test_a_description_rebuilds_the_swe4_specs_that_copy_it(self):
        assert "testSpecs" in derive.views_for(slot.DESCRIPTION)

    def test_the_component_comes_off_the_front_of_the_id(self):
        assert derive.component_of(slot.DESCRIPTION,
                                   slot.for_entity(slot.DESCRIPTION, FID)) == "Comp"
        assert derive.component_of(slot.UNIT_DESCRIPTION, slot.for_unit(UNIT)) == "Comp"
        assert derive.component_of(slot.NODE_LABEL, slot.for_node(FID, "n3")) == "Comp"

    def test_scoping_does_not_mutate_the_shared_config(self):
        """The run's config is shared. Narrowing it in place would leave every later view in
        the process scoped to whichever component was edited last."""
        cfg = {"views": {"interfaceTables": True}}
        scoped = derive.scoped_config(cfg, "Comp")
        assert scoped["_analyzerAllowedComponents"] == ["Comp"]
        assert "_analyzerAllowedComponents" not in cfg


class TestAnOrphanedCorrection:
    """An orphan was written for code that has since changed. It is kept (REQ-ID-03) but never
    applied, so the model holds the fresh LLM text for the new code -- and THAT is the slot's
    original now. A new edit starts a new correction; an undo has nothing of its own to restore."""

    KEY = slot.for_entity(slot.DESCRIPTION, FID)

    def _orphan(self, conn):
        conn.execute(sa.insert(s.text_overrides).values(
            version_id="v1", slot_kind=slot.DESCRIPTION, slot_key=self.KEY,
            llm_text="Written for the old code.", human_text="Corrected for the old code.",
            is_orphaned=True, updated_at=datetime.datetime.now(datetime.timezone.utc)))

    def test_a_new_edit_is_a_first_edit_against_the_current_text(self, conn):
        self._orphan(conn)
        out = _apply(conn, svc.ModelAccess(artifacts=_model()), slot.DESCRIPTION, self.KEY,
                     "Corrected for the new code.")
        assert out.first_edit and out.previous_text == "Sets the time."
        row = svc.get_override(conn, "v1", slot.DESCRIPTION, self.KEY)
        assert row.llm_text == "Sets the time."             # not the old code's original
        assert row.human_text == "Corrected for the new code."
        assert not row.is_orphaned

    def test_undo_after_it_restores_the_current_llm_text(self, conn):
        """Keeping the orphan's `llm_text` would restore a sentence about code that is gone."""
        self._orphan(conn)
        m = svc.ModelAccess(artifacts=_model())
        _apply(conn, m, slot.DESCRIPTION, self.KEY, "Corrected for the new code.")
        svc.undo_override(conn, "v1", slot.DESCRIPTION, self.KEY, models=m)
        assert m.artifact("functions")[FID]["description"] == "Sets the time."

    def test_undoing_the_orphan_itself_is_refused(self, conn):
        self._orphan(conn)
        m = svc.ModelAccess(artifacts=_model())
        with pytest.raises(svc.NothingToUndo, match="orphaned") as exc:
            svc.undo_override(conn, "v1", slot.DESCRIPTION, self.KEY, models=m)
        assert exc.value.status == 409
        assert m.artifact("functions")[FID]["description"] == "Sets the time."


class TestTheSavedSlotOwesNothing:
    """REQ-CS-03. A regeneration queued for a slot before a human corrected it would pay for an
    LLM call whose answer the correction then replaces."""

    def test_a_save_clears_its_own_queue_entry(self, conn):
        key = slot.for_entity(slot.DESCRIPTION, FID)
        cascade.enqueue(conn, "v1", [cascade.Dependent(slot.DESCRIPTION, key, "a callee")])
        _apply(conn, svc.ModelAccess(artifacts=_model()), slot.DESCRIPTION, key, "Human words.")
        assert (slot.DESCRIPTION, key) not in {(r.slot_kind, r.slot_key)
                                               for r in cascade.pending(conn, "v1")}

    def test_what_it_invalidates_is_still_queued(self, conn):
        """Its own entry goes; the unit it feeds is queued as before."""
        key = slot.for_entity(slot.DESCRIPTION, FID)
        _apply(conn, svc.ModelAccess(artifacts=_model()), slot.DESCRIPTION, key, "Human words.")
        assert (slot.UNIT_DESCRIPTION, slot.for_unit(UNIT)) in {
            (r.slot_kind, r.slot_key) for r in cascade.pending(conn, "v1")}


class TestOneSaveAtATime:
    """`_serialize_saves`: a transaction-scoped advisory lock per version on PostgreSQL."""

    class _Conn:
        def __init__(self, dialect):
            self.dialect = type("D", (), {"name": dialect})()
            self.calls = []

        def execute(self, stmt, params=None):
            self.calls.append((str(stmt), params))

    def test_postgres_takes_a_lock_per_version(self):
        a, b = self._Conn("postgresql"), self._Conn("postgresql")
        svc._serialize_saves(a, "ver-1")
        svc._serialize_saves(b, "ver-1")
        (sql, params), = a.calls
        assert "pg_advisory_xact_lock" in sql
        assert b.calls == a.calls, "one version, one lock"
        assert -2 ** 63 <= params["k"] < 2 ** 63
        c = self._Conn("postgresql")
        svc._serialize_saves(c, "ver-2")
        assert c.calls[0][1] != params, "another version does not wait on this one"

    def test_sqlite_needs_none(self, conn):
        spy = self._Conn("sqlite")
        svc._serialize_saves(spy, "v1")
        assert spy.calls == []


class TestASaveWritesOneRow:
    """`ModelAccess.save` against a stored model: the one field of the one entity, nothing else.

    It used to hand the whole artifact to the repository, whose flush runs `clear_version` and
    `persist_model` over the entire version -- from a snapshot read before the save's transaction.
    Two saves at once, or a save beside a Phase-2 run, then put back whatever the other had just
    changed. Here the snapshot is read, ANOTHER save changes a different function, and this save
    must not undo it."""

    OTHER = "Comp|UnitA|GCM_Other|void"

    @pytest.fixture
    def engine(self, monkeypatch):
        from sqlalchemy.pool import StaticPool
        from core import db as coredb, model_store
        eng = sa.create_engine("sqlite://", connect_args={"check_same_thread": False},
                               poolclass=StaticPool)
        s.metadata.create_all(eng)
        now = datetime.datetime.now(datetime.timezone.utc)
        with eng.begin() as cx:
            cx.execute(sa.insert(s.projects).values(id="p", name="p", created_at=now))
            cx.execute(sa.insert(s.versions).values(id="v1", project_id="p", version="v1",
                                                    created_at=now))
            model_store.persist_model(
                cx, "p", "v1",
                functions={FID: {"qualifiedName": "ns::GCM_SetGcStartTime",
                                 "description": "Sets the time."},
                           self.OTHER: {"qualifiedName": "ns::GCM_Other",
                                        "description": "Does the other thing."}},
                globals={}, datadict={}, edges={"typeUsers": {}, "macroUsers": {}},
                hashes={FID: "h1", self.OTHER: "h2"},
                units={UNIT: {"name": "UnitA", "path": "a", "fileName": "a.cpp",
                              "includedHeaders": [], "description": "Manages GC."}},
                components={}, summaries={})
        monkeypatch.setattr(coredb, "get_engine", lambda *a, **k: eng)
        return eng

    def _functions(self, eng):
        from core import model_store
        with eng.connect() as cx:
            return model_store.load_functions(cx, "v1")

    def test_a_save_does_not_put_back_what_another_changed(self, engine):
        from core import model_store
        m = svc.ModelAccess(version_id="v1", project_id="p")
        m.artifact("functions")                       # the snapshot, before either save
        with engine.begin() as cx:                    # another save, on another function
            model_store.set_entity_field(cx, "v1", self.OTHER, "description",
                                         "Another reviewer's words.", ("function",))
        with engine.begin() as cx:
            out = svc.apply_override(cx, "v1", slot.DESCRIPTION,
                                     slot.for_entity(slot.DESCRIPTION, FID), "This save's words.",
                                     models=m)
        assert list(out.artifacts_written) == ["functions"]
        fns = self._functions(engine)
        assert fns[FID]["description"] == "This save's words."
        assert fns[self.OTHER]["description"] == "Another reviewer's words."

    def test_a_unit_description_is_one_column(self, engine):
        from core import model_store
        with engine.begin() as cx:
            svc.apply_override(cx, "v1", slot.UNIT_DESCRIPTION, slot.for_unit(UNIT), "Runs GC.",
                               models=svc.ModelAccess(version_id="v1", project_id="p"))
        with engine.connect() as cx:
            assert model_store.load_units(cx, "v1")[UNIT]["description"] == "Runs GC."

    def test_a_model_replaced_under_the_save_is_409_and_saves_nothing(self, engine):
        """A run regenerating the version replaced the row the save read: the save must fail,
        not report a correction that stored nothing."""
        m = svc.ModelAccess(version_id="v1", project_id="p")
        m.artifact("functions")
        with engine.begin() as cx:
            cx.execute(sa.delete(s.entity_versions).where(s.entity_versions.c.version_id == "v1"))
        with pytest.raises(svc.VersionBusy) as exc:
            with engine.begin() as cx:
                svc.apply_override(cx, "v1", slot.DESCRIPTION,
                                   slot.for_entity(slot.DESCRIPTION, FID), "Lost words.", models=m)
        assert exc.value.status == 409
        with engine.connect() as cx:
            assert svc.get_override(cx, "v1", slot.DESCRIPTION,
                                    slot.for_entity(slot.DESCRIPTION, FID)) is None


class TestModelAccess:
    def test_an_in_memory_model_does_not_invent_missing_artifacts(self, conn):
        """"That function is not in this version" must not become "no functions exist" -- the
        slot would resolve against nothing instead of reporting a 404."""
        m = svc.ModelAccess(artifacts={"functions": {}})
        assert m.artifact("dataDictionary") == {}
        with pytest.raises(svc.SlotUnknown):
            _apply(conn, m, slot.STRUCT_DESCRIPTION,
                   slot.for_entity(slot.STRUCT_DESCRIPTION, TYPE), "Words.")
