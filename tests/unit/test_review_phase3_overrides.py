"""Corrections for text Phase 3 produces (REQ-AP-05).

The failure these guard against is silent in every case: a kind nobody accounted for saves
successfully and never reaches the document; an orphaned row applied to a graph that moved on puts
the right sentence on the wrong box; one malformed row taking down a generation wastes a parse and
an LLM run that were already paid for.
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from review import phase3_overrides as p3, resolver, slot

FID = "Comp|UnitA|doThing|"
OTHER = "Comp|UnitA|other|"


class _Row:
    """A text_overrides row as read back."""
    def __init__(self, kind, key, text, orphaned=False):
        self.slot_kind, self.slot_key, self.human_text = kind, key, text
        self.is_orphaned = orphaned
        self.slot_shape = None


def _cfg(*ids):
    return {"nodes": [{"id": i, "label": "llm " + i, "type": "ACTION"} for i in ids],
            "edges": []}


class TestEveryKindIsAccountedFor:
    """The whole reason this module is a table and not scattered `if kind ==` checks."""

    def test_each_editable_kind_is_model_backed_or_applied_at_derive(self):
        model_backed = set(resolver.MODEL_BACKED_KINDS)
        at_derive = set(p3.covered_kinds())
        for kind in slot.ALL_KINDS:
            assert kind in model_backed or kind in at_derive, (
                "%s is in neither table: an override for it would save, report success, and "
                "never reach the document" % kind)

    def test_no_kind_is_in_both(self):
        """Two homes for one piece of text is the arrangement this feature exists to remove."""
        assert not set(resolver.MODEL_BACKED_KINDS) & set(p3.covered_kinds())

    def test_the_two_phase3_kinds_are_the_expected_ones(self):
        assert set(p3.covered_kinds()) == {slot.NODE_LABEL, slot.BEHAVIOUR_DESCRIPTION}

    def test_the_two_sets_add_up_to_all_seven(self):
        assert len(set(resolver.MODEL_BACKED_KINDS) | set(p3.covered_kinds())) == len(slot.ALL_KINDS)


class TestTargets:
    def test_a_node_label_renders_an_image(self):
        assert p3.renders_image(slot.NODE_LABEL)
        assert p3.target_for(slot.NODE_LABEL).view == "flowcharts"

    def test_a_behaviour_description_renders_nothing(self):
        """MermaidBuilder labels each arrow `<callee>()` -- the function's name -- and appends
        the description to a separate list. The text is not in the picture, so queueing a render
        for it is wasted work."""
        assert not p3.renders_image(slot.BEHAVIOUR_DESCRIPTION)

    def test_a_model_backed_kind_is_refused_here(self):
        with pytest.raises(slot.SlotKeyError):
            p3.target_for(slot.DESCRIPTION)


class TestGroupingRowsByFlowchart:
    def test_rows_group_under_their_flowchart(self):
        rows = [_Row(slot.NODE_LABEL, slot.for_node(FID, "n1"), "One"),
                _Row(slot.NODE_LABEL, slot.for_node(FID, "n2"), "Two"),
                _Row(slot.NODE_LABEL, slot.for_node(OTHER, "n1"), "Three")]
        assert p3.labels_by_flowchart(rows) == {FID: {"n1": "One", "n2": "Two"},
                                                OTHER: {"n1": "Three"}}

    def test_other_kinds_are_ignored(self):
        rows = [_Row(slot.DESCRIPTION, FID, "A description"),
                _Row(slot.NODE_LABEL, slot.for_node(FID, "n1"), "One")]
        assert p3.labels_by_flowchart(rows) == {FID: {"n1": "One"}}

    def test_an_orphaned_row_is_not_applied(self):
        """It is KEPT in the table (REQ-ID-03) because it is the user's work and training data --
        but it describes something that is no longer there, so applying it would put the right
        sentence on whatever now occupies that position."""
        rows = [_Row(slot.NODE_LABEL, slot.for_node(FID, "n1"), "Stale", orphaned=True),
                _Row(slot.NODE_LABEL, slot.for_node(FID, "n2"), "Good")]
        assert p3.labels_by_flowchart(rows) == {FID: {"n2": "Good"}}

    def test_a_malformed_key_is_skipped_not_raised(self):
        """This runs inside Phase 3. One bad row must not destroy a generation that has already
        paid for the parse and the LLM calls."""
        rows = [_Row(slot.NODE_LABEL, "no-separator-here", "Bad"),
                _Row(slot.NODE_LABEL, slot.for_node(FID, "n1"), "Good")]
        assert p3.labels_by_flowchart(rows) == {FID: {"n1": "Good"}}

    def test_empty_text_is_skipped(self):
        rows = [_Row(slot.NODE_LABEL, slot.for_node(FID, "n1"), "   ")]
        assert p3.labels_by_flowchart(rows) == {}

    def test_no_rows_is_not_an_error(self):
        assert p3.labels_by_flowchart([]) == {}
        assert p3.labels_by_flowchart(None) == {}


class TestApplyingToACfg:
    def test_a_label_is_replaced(self):
        cfg = _cfg("n0", "n1", "n2")
        assert p3.apply_to_cfg(cfg, {"n1": "Corrected"}) == 1
        by_id = {n["id"]: n["label"] for n in cfg["nodes"]}
        assert by_id == {"n0": "llm n0", "n1": "Corrected", "n2": "llm n2"}

    def test_a_correction_for_a_node_that_is_gone_is_dropped(self):
        """Not appended. A CFG that grew a node with no edges would render as a box floating
        beside the flowchart. REQ-ID-02's shape check catches this upstream; this is the last
        line of defence, not the first."""
        cfg = _cfg("n0", "n1")
        assert p3.apply_to_cfg(cfg, {"n7": "Nowhere"}) == 0
        assert len(cfg["nodes"]) == 2

    def test_nothing_to_apply_leaves_the_graph_alone(self):
        cfg = _cfg("n0", "n1")
        before = [dict(n) for n in cfg["nodes"]]
        assert p3.apply_to_cfg(cfg, {}) == 0
        assert cfg["nodes"] == before

    def test_rubbish_does_not_raise(self):
        assert p3.apply_to_cfg({}, {"n1": "x"}) == 0
        assert p3.apply_to_cfg({"nodes": None}, {"n1": "x"}) == 0
        assert p3.apply_to_cfg({"nodes": ["not a dict"]}, {"n1": "x"}) == 0


class TestApplyingAcrossAUnitFile:
    def _entries(self):
        return [{"name": "ns::doThing", "functionKey": FID, "cfg": _cfg("n0", "n1")},
                {"name": "ns::other", "functionKey": OTHER, "cfg": _cfg("n0")}]

    def test_only_the_corrected_flowchart_changes(self):
        entries = self._entries()
        untouched = [dict(n) for n in entries[1]["cfg"]["nodes"]]
        changed = p3.apply_to_flowchart_json(entries, {FID: {"n1": "Corrected"}})
        assert changed == [FID]
        assert entries[1]["cfg"]["nodes"] == untouched, (
            "a unit where nobody edited that function must be rewritten byte-identically")

    def test_no_corrections_changes_nothing(self):
        entries = self._entries()
        assert p3.apply_to_flowchart_json(entries, {}) == []

    def test_a_flowchart_id_not_in_this_unit_is_ignored(self):
        entries = self._entries()
        assert p3.apply_to_flowchart_json(entries, {"Comp|UnitZ|elsewhere|": {"n0": "x"}}) == []

    def test_an_entry_without_a_function_key_is_skipped(self):
        assert p3.apply_to_flowchart_json([{"cfg": _cfg("n0")}], {FID: {"n0": "x"}}) == []


class TestTheShapeIsCheckedWhereTheTextLands:
    """REQ-ID-02's decisive check.

    The carry-forward cannot make it: it runs in Phase 2, before Phase 3 has produced the graph.
    So it checks what it can and leaves the real one here -- the last moment before the text
    lands, and the only point at which the CFG being written actually exists.
    """

    def _entries(self, *ids):
        return [{"name": "ns::doThing", "functionKey": FID,
                 "cfg": {"nodes": [{"id": i, "label": "llm " + i, "type": "ACTION"}
                                   for i in ids], "edges": []}}]

    def test_a_matching_shape_applies(self):
        entries = self._entries("n0", "n1")
        shapes = {FID: slot.cfg_shape(["n0", "n1"])}
        assert p3.apply_to_flowchart_json(entries, {FID: {"n1": "Corrected"}}, shapes) == [FID]

    def test_a_renumbered_graph_is_refused(self):
        """Same node id, different graph -- a builder change between the two versions. Applying
        would put the right sentence on whatever now occupies n1."""
        entries = self._entries("n0", "n1", "n2")
        shapes = {FID: slot.cfg_shape(["n0", "n1"])}          # written against a 2-node graph
        assert p3.apply_to_flowchart_json(entries, {FID: {"n1": "Corrected"}}, shapes) == []
        labels = {n["id"]: n["label"] for n in entries[0]["cfg"]["nodes"]}
        assert labels["n1"] == "llm n1", "the LLM's label must survive untouched"

    def test_no_shape_claim_still_applies(self):
        """A correction made before shapes were recorded, or one saved directly against this
        version. There is nothing to check, and refusing would drop it for no reason."""
        entries = self._entries("n0", "n1")
        assert p3.apply_to_flowchart_json(entries, {FID: {"n1": "Corrected"}}, {}) == [FID]

    def test_reading_the_shapes_off_the_rows(self):
        rows = [_Row(slot.NODE_LABEL, slot.for_node(FID, "n1"), "text")]
        rows[0].slot_shape = "abc123"
        assert p3.shapes_by_flowchart(rows) == {FID: "abc123"}

    def test_an_orphaned_row_contributes_no_shape(self):
        rows = [_Row(slot.NODE_LABEL, slot.for_node(FID, "n1"), "text", orphaned=True)]
        rows[0].slot_shape = "abc123"
        assert p3.shapes_by_flowchart(rows) == {}
