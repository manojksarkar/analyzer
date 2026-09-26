"""The two queues are actually drained by a run (REQ-CS-01, REQ-IM-02).

Recording what a correction invalidated was step 6; drawing the picture it changed was step 7.
Both left an obligation in a table, and an obligation nobody collects is a slow lie -- the document
stays stale while the queue says somebody will deal with it.

The regeneration queue is paid in **two places**, because its two kinds live in different phases:

    description / unitDescription   Phase 2 -- blank the text, and the enrichment rewrites it
    behaviourDescription            Phase 3 -- the behaviour view rebuilds every row it writes

The render queue is paid where the output tree is, which is the host capturing the run's output.
"""
import datetime
import json
import os
import re
import sys

import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from api.db.postgres import schema as s
from review import cascade, slot

FN = "Comp|UnitA|ns::caller|void"
GLOBAL = "Comp|UnitA|gCounter"
UNIT = "Comp|UnitA"
CALLER = "App|AppMain|ns::start|void"
NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


@pytest.fixture
def conn():
    eng = sa.create_engine("sqlite://")
    s.metadata.create_all(eng)
    with eng.begin() as cx:
        cx.execute(sa.insert(s.projects).values(id="p", name="p", created_at=NOW))
        cx.execute(sa.insert(s.versions).values(id="v1", project_id="p", version="v1",
                                                created_at=NOW))
        yield cx


def _model():
    return {"functions": {FN: {"qualifiedName": "ns::caller",
                               "description": "Stale, written from the old wording."}},
            "globalVariables": {GLOBAL: {"qualifiedName": "gCounter",
                                         "description": "Also stale."}},
            "units": {UNIT: {"name": "UnitA", "description": "Unit text."}},
            "dataDictionary": {}}


def _queue(conn, kind, key):
    cascade.enqueue(conn, "v1", [cascade.Dependent(kind, key, "because")], now=NOW)


class TestPhase2PaysTheDebt:
    def test_a_queued_description_is_blanked_so_it_regenerates(self, conn):
        """No force-regenerate switch exists, and none is needed: `_enrich_from_llm` skips a
        function "when already present", so removing the stale text IS the instruction."""
        key = slot.for_entity(slot.DESCRIPTION, FN)
        _queue(conn, slot.DESCRIPTION, key)
        model = _model()
        blanked = cascade.blank_queued_text(conn, "v1", model)
        assert len(blanked) == 1
        assert model["functions"][FN]["description"] == ""

    def test_a_queued_unit_description_is_blanked(self, conn):
        _queue(conn, slot.UNIT_DESCRIPTION, slot.for_unit(UNIT))
        model = _model()
        cascade.blank_queued_text(conn, "v1", model)
        assert model["units"][UNIT]["description"] == ""

    def test_a_global_is_blanked_too(self, conn):
        _queue(conn, slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, GLOBAL))
        model = _model()
        cascade.blank_queued_text(conn, "v1", model)
        assert model["globalVariables"][GLOBAL]["description"] == ""

    def test_untouched_slots_keep_their_text(self, conn):
        _queue(conn, slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, FN))
        model = _model()
        cascade.blank_queued_text(conn, "v1", model)
        assert model["units"][UNIT]["description"] == "Unit text."

    def test_a_behaviour_entry_is_left_for_phase_3(self, conn):
        """Its text is not in the model at all, so Phase 2 cannot pay this one."""
        _queue(conn, slot.BEHAVIOUR_DESCRIPTION, slot.for_behaviour_row(FN, CALLER))
        model = _model()
        assert cascade.blank_queued_text(conn, "v1", model) == []
        assert len(cascade.pending(conn, "v1")) == 1

    def test_the_queue_is_not_cleared_by_blanking(self, conn):
        """Clearing here would lose the obligation if the phase then failed."""
        _queue(conn, slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, FN))
        cascade.blank_queued_text(conn, "v1", _model())
        assert len(cascade.pending(conn, "v1")) == 1


class TestRetiringOnlyWhatCameBack:
    def test_a_rewritten_slot_is_retired(self, conn):
        key = slot.for_entity(slot.DESCRIPTION, FN)
        _queue(conn, slot.DESCRIPTION, key)
        model = _model()
        queued = cascade.blank_queued_text(conn, "v1", model)
        model["functions"][FN]["description"] = "Freshly written."
        assert cascade.clear_rewritten(conn, "v1", queued, model) == (1, 0)
        assert cascade.pending(conn, "v1") == []

    def test_a_slot_still_empty_stays_queued(self, conn):
        """The regeneration did not happen -- the LLM was unreachable, or descriptions are off.
        Dropping the entry would turn "still owed" into "done"."""
        key = slot.for_entity(slot.DESCRIPTION, FN)
        _queue(conn, slot.DESCRIPTION, key)
        model = _model()
        queued = cascade.blank_queued_text(conn, "v1", model)
        assert cascade.clear_rewritten(conn, "v1", queued, model) == (0, 1)
        assert len(cascade.pending(conn, "v1")) == 1

    def test_a_slot_that_left_the_version_is_retired(self, conn):
        """Otherwise it would be retried for ever against something that is not there."""
        _queue(conn, slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, "Gone|Gone|x|"))
        model = _model()
        queued = cascade.blank_queued_text(conn, "v1", model)
        cascade.clear_rewritten(conn, "v1", queued, model)
        assert cascade.pending(conn, "v1") == []


class TestPhase3PaysTheRest:
    def test_behaviour_entries_are_retired_after_the_views_run(self, conn):
        """The behaviour view rebuilds every row it writes, so running it IS the regeneration."""
        _queue(conn, slot.BEHAVIOUR_DESCRIPTION, slot.for_behaviour_row(FN, CALLER))
        _queue(conn, slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, FN))
        assert cascade.clear_behaviour_entries(conn, "v1") == 1
        left = cascade.pending(conn, "v1")
        assert [r.slot_kind for r in left] == [slot.DESCRIPTION], (
            "a description is Phase 2's debt and must not be retired by Phase 3")


class TestTheConsumersAreWiredIn:
    """Each queue is drained by exactly one place, and that place is where the work happens.

    Every matcher below requires the call to be INDENTED, so it cannot match the function's own
    `def` line. That is not hypothetical care: the first version of this class matched
    `_take_regeneration_queue(functions_data`, which is also how the definition begins, so two of
    these tests were reading the definition's position and would have passed with no call site at
    all. `test_no_matcher_can_match_a_definition` is what stops that recurring.
    """

    #: name -> (file, the call as written, the def as written)
    CASES = {
        "Phase 2 blanks queued descriptions":
            ("engine/model_deriver.py",
             "_queued = _take_regeneration_queue(functions_data, global_variables_data)",
             "def _take_regeneration_queue(functions_data: dict, global_variables_data: dict):"),
        "Phase 2 retires what came back":
            ("engine/model_deriver.py",
             "_retire_regeneration_queue(_queued, functions_data, global_variables_data)",
             "def _retire_regeneration_queue(queued, functions_data: dict, "
             "global_variables_data: dict) -> None:"),
        "Phase 3 retires behaviour rows":
            ("engine/run_views.py",
             "_retire_behaviour_regenerations()",
             "def _retire_behaviour_regenerations() -> None:"),
        "output capture draws pending pictures":
            ("engine/incremental/store.py",
             "_draw_pending_pictures(self.engine, version_id, os.path.join(",
             "def _draw_pending_pictures(engine, version_id: str, output_dir: str) -> None:"),
    }

    @staticmethod
    def _matcher(call):
        return re.compile(r"^[ 	]+" + re.escape(call), re.M)

    @staticmethod
    def _src(path):
        return open(os.path.join(PROJECT_ROOT, *path.split("/")), encoding="utf-8").read()

    @pytest.mark.parametrize("what", sorted(CASES))
    def test_the_call_site_exists(self, what):
        path, call, _def = self.CASES[what]
        assert self._matcher(call).search(self._src(path)), (
            "%s: nothing calls %s in %s, so that queue is never drained" % (what, call, path))

    @pytest.mark.parametrize("what", sorted(CASES))
    def test_no_matcher_can_match_a_definition(self, what):
        """A matcher that also matches the `def` proves nothing -- it passes whether or not the
        function is ever called."""
        _path, call, definition = self.CASES[what]
        assert not self._matcher(call).search(definition)

    def test_blanking_happens_before_the_enrichment(self):
        """Blanked afterwards, the enrichment would have skipped the slot as already present and
        the stale text would survive untouched."""
        src = self._src("engine/model_deriver.py")
        call = self._matcher(self.CASES["Phase 2 blanks queued descriptions"][1]).search(src)
        assert call and call.start() < src.index("desc = enrich_functions_rich(")

    def test_retiring_happens_after_it(self):
        src = self._src("engine/model_deriver.py")
        call = self._matcher(self.CASES["Phase 2 retires what came back"][1]).search(src)
        assert call and call.start() > src.index("desc = enrich_functions_rich(")

    def test_behaviour_entries_are_retired_after_the_views(self):
        src = self._src("engine/run_views.py")
        call = self._matcher(self.CASES["Phase 3 retires behaviour rows"][1]).search(src)
        assert call and call.start() > src.index(
            "run_views(model, output_dir, model_dir, config, doc_type=doc_type)")


class TestAFailedRewriteLeavesTheModelAsItFoundIt:
    """The blank is a REQUEST, not a decision.

    `blank_queued_text` empties a description only because the enrichment skips anything already
    filled in -- emptying it is how this code says "write this again". So an empty slot at the end
    of the phase does not mean anybody decided the text should go; it means the request went
    unanswered. Publishing that blank is worse than publishing the superseded wording, and worse
    than what the reader had before anybody corrected anything.

    Found by auditing the feature against the pipeline rather than against its own tests: every
    test here passed while one unreachable LLM could empty a cell in the document.
    """

    def test_the_previous_wording_comes_back(self, conn):
        key = slot.for_entity(slot.DESCRIPTION, FN)
        _queue(conn, slot.DESCRIPTION, key)
        model = _model()
        before = model["functions"][FN]["description"]
        assert before, "the fixture must start with something to lose"

        queued = cascade.blank_queued_text(conn, "v1", model)
        assert model["functions"][FN]["description"] == "", "blanking still asks for the rewrite"

        # ... the LLM is unreachable, so nothing is written back ...
        out = cascade.clear_rewritten(conn, "v1", queued, model)

        assert model["functions"][FN]["description"] == before
        assert out.restored == 1 and out.cleared == 0

    def test_it_stays_queued_even_though_the_text_is_back(self, conn):
        """What came back is the wording the correction superseded. The debt is still owed."""
        _queue(conn, slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, FN))
        model = _model()
        queued = cascade.blank_queued_text(conn, "v1", model)
        cascade.clear_rewritten(conn, "v1", queued, model)
        assert len(cascade.pending(conn, "v1")) == 1

    def test_a_rewrite_that_DID_happen_is_not_overwritten(self, conn):
        """The restore must never beat fresh text -- that would undo the regeneration it exists
        to protect."""
        _queue(conn, slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, FN))
        model = _model()
        queued = cascade.blank_queued_text(conn, "v1", model)
        model["functions"][FN]["description"] = "Freshly written."
        out = cascade.clear_rewritten(conn, "v1", queued, model)
        assert model["functions"][FN]["description"] == "Freshly written."
        assert (out.cleared, out.restored) == (1, 0)

    def test_a_unit_description_is_restored_too(self, conn):
        """Not just functions: every model-backed kind goes through the same door."""
        _queue(conn, slot.UNIT_DESCRIPTION, slot.for_unit(UNIT))
        model = _model()
        before = model["units"][UNIT]["description"]
        queued = cascade.blank_queued_text(conn, "v1", model)
        cascade.clear_rewritten(conn, "v1", queued, model)
        assert model["units"][UNIT]["description"] == before

    def test_a_slot_that_left_the_version_restores_nothing(self, conn):
        """There is nowhere to put it back into, and nothing would read it if there were."""
        _queue(conn, slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, "Gone|Gone|x|"))
        model = _model()
        queued = cascade.blank_queued_text(conn, "v1", model)
        out = cascade.clear_rewritten(conn, "v1", queued, model)
        assert (out.cleared, out.restored) == (1, 0)

    def test_the_blanked_entry_carries_the_text_it_removed(self, conn):
        """Without this the restore has nothing to restore FROM -- the whole fix lives here."""
        _queue(conn, slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, FN))
        model = _model()
        before = model["functions"][FN]["description"]
        blanked = cascade.blank_queued_text(conn, "v1", model)
        assert blanked[0].previous_text == before
