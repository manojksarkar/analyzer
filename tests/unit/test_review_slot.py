"""Slot addressing is exact, and it is the ONLY place a key is built or split.

A key is assembled from ids that already exist, and two kinds address something *inside* an
entity, so their key carries two parts. The obvious separator is wrong: `entity_key` is itself
`component|unit|qualifiedName|paramTypes`, so a composite joined with `|` can only be split by
counting pipes and hoping. Today the second part happens to contain none, which makes the
heuristic work and makes it a trap.

The September interface-id collision was exactly this shape -- the numbering keyed on the unit
while the id encoded a lossy form of it, two expressions for one fact, drifting apart. These
tests pin the property that prevents it: whatever goes in comes back out.
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from review import slot

# A real entity key: four parts, three pipes, and a parameter list with a comma and a star.
ENTITY = "Garbage-Collection-Manager|MGCM_Completion|GCM_SetGcStartTime|PUINT32,UINT32 *"
# A caller's entity key. Behaviour rows are addressed by this, not by the "<unit> - <name>"
# display label, which two different callers can share.
CALLER = "UHP-Backbone|UHP_BackboneCom|ns::ClearDtcm|void"


class TestRoundTrip:
    @pytest.mark.parametrize("kind", slot.ALL_KINDS)
    def test_every_kind_round_trips(self, kind):
        parts = {n: {"entity_key": ENTITY,
                     "unit_key": "Comp|UnitA",
                     "node_id": "n3",
                     "function_id": ENTITY,
                     "external_caller_id": CALLER}[n]
                 for n in slot.parts_for(kind)}
        key = slot.make(kind, **parts)
        assert slot.parse(kind, key) == parts

    def test_a_composite_survives_the_pipes_in_its_own_parts(self):
        """The part itself contains the separator a naive scheme would split on."""
        key = slot.for_node(ENTITY, "n12")
        got = slot.parse(slot.NODE_LABEL, key)
        assert got["entity_key"] == ENTITY, "the entity key's own pipes were mis-split"
        assert got["node_id"] == "n12"

    def test_a_behaviour_row_is_addressed_by_two_entity_keys(self):
        """Not by the `externalUnitFunction` display label. That label is
        `"<unit> - <shortName>"`, so AddOperation::apply and MultiplyOperation::apply in one unit
        produce the SAME string -- and a correction to one row would silently overwrite the
        other, because (version_id, slot_kind, slot_key) is unique."""
        key = slot.for_behaviour_row(ENTITY, CALLER)
        got = slot.parse(slot.BEHAVIOUR_DESCRIPTION, key)
        assert got["function_id"] == ENTITY
        assert got["external_caller_id"] == CALLER

    def test_two_callers_that_share_a_display_label_get_different_keys(self):
        """The collision the key change exists to prevent, stated as a property."""
        add = "CompX|UnitB|AddOperation::apply|"
        mul = "CompX|UnitB|MultiplyOperation::apply|"
        assert slot.for_behaviour_row(ENTITY, add) != slot.for_behaviour_row(ENTITY, mul)

    def test_two_slots_that_would_collide_under_naive_joining_do_not(self):
        """Joined with "|" these two produce the SAME string; split back, the wrong one wins."""
        a = slot.for_node("C|U|f|", "n1")          # entity "C|U|f|",   node "n1"
        b = slot.for_node("C|U|f|n1", "x")         # entity "C|U|f|n1", node "x"
        assert a != b
        assert slot.parse(slot.NODE_LABEL, a) == {"entity_key": "C|U|f|", "node_id": "n1"}
        assert slot.parse(slot.NODE_LABEL, b) == {"entity_key": "C|U|f|n1", "node_id": "x"}

    def test_a_key_survives_an_incidental_strip(self):
        key = slot.for_node(ENTITY, "n3")
        assert key.strip() == key
        assert slot.parse(slot.NODE_LABEL, key.strip()) == slot.parse(slot.NODE_LABEL, key)


class TestTheSeparatorIsNotWhitespace:
    """The separator must be a character `.strip()` will not eat.

    Python counts 0x1c-0x1f as whitespace. `hashing.py` joins on 0x1f, so 0x1f is the obvious
    character to reach for here -- and it is wrong here, because unlike a hash input a slot key
    is passed around: through a request body, through JSON, through a form field, through
    anything that trims what it is handed. A separator in the whitespace class means any of
    those can quietly rewrite a key.

    It already happened once. `make()` used to strip each part before checking it for the
    separator, so a part ending in 0x1f had it silently deleted and a DIFFERENT key came back
    instead of an error. `make()` checks the raw value now, but the property below is what
    makes the whole class of that bug impossible rather than fixed in one spot.
    """

    def test_strip_does_not_eat_the_separator(self):
        assert not slot.SEP.isspace(), (
            "a whitespace separator is deleted by any .strip() in the stack; 0x1f is one, "
            "which is why SEP is 0x01")
        assert slot.SEP.strip() == slot.SEP

    def test_a_part_that_is_only_the_separator_stays_visible_to_the_guard(self):
        """With a whitespace separator this part strips to "" and is reported as *missing*
        -- the right outcome by luck, for the wrong reason, and only while the guard happens
        to run. The part must reach the separator check intact."""
        with pytest.raises(slot.SlotKeyError, match="separator"):
            slot.make(slot.NODE_LABEL, entity_key=ENTITY, node_id=slot.SEP)

    def test_a_trailing_separator_is_an_error_not_a_silent_rewrite(self):
        """The exact shape of the original bug: strip-then-check turned this into the key for
        a different slot."""
        with pytest.raises(slot.SlotKeyError, match="separator"):
            slot.make(slot.NODE_LABEL, entity_key=ENTITY, node_id="n1" + slot.SEP)


class TestRejection:
    def test_an_unknown_kind_is_refused(self):
        with pytest.raises(slot.SlotKeyError):
            slot.make("somethingElse", entity_key=ENTITY)

    def test_a_missing_part_is_refused(self):
        with pytest.raises(slot.SlotKeyError):
            slot.make(slot.NODE_LABEL, entity_key=ENTITY)

    def test_an_empty_part_is_refused(self):
        with pytest.raises(slot.SlotKeyError):
            slot.make(slot.NODE_LABEL, entity_key=ENTITY, node_id="  ")

    def test_an_unexpected_part_is_refused(self):
        """A caller passing the wrong part name would otherwise build a key silently missing
        the value it meant to include."""
        with pytest.raises(slot.SlotKeyError):
            slot.make(slot.DESCRIPTION, entity_key=ENTITY, node_id="n1")

    def test_a_part_containing_the_separator_is_refused(self):
        with pytest.raises(slot.SlotKeyError):
            slot.make(slot.NODE_LABEL, entity_key="C|U|f|" + slot.SEP, node_id="n1")

    def test_a_malformed_key_does_not_parse(self):
        with pytest.raises(slot.SlotKeyError):
            slot.parse(slot.NODE_LABEL, "no-separator-here")

    def test_is_valid_never_raises(self):
        assert slot.is_valid(slot.DESCRIPTION, ENTITY)
        assert not slot.is_valid(slot.NODE_LABEL, "nope")
        assert not slot.is_valid("bogusKind", "x")

    def test_for_entity_refuses_a_composite_kind(self):
        with pytest.raises(slot.SlotKeyError):
            slot.for_entity(slot.NODE_LABEL, ENTITY)


class TestCfgShape:
    """REQ-ID-02. A node id is a POSITION, so "the source did not change" does not mean "n7 is
    still the same node". The shape is what turns that from an assumption into a check."""

    def _cfg(self, *ids):
        return {"nodes": [{"id": i, "label": "x"} for i in ids], "edges": []}

    def test_the_same_graph_has_the_same_shape(self):
        assert slot.shape_of_cfg(self._cfg("n0", "n1", "n2")) == \
               slot.shape_of_cfg(self._cfg("n0", "n1", "n2"))

    def test_walk_order_is_not_part_of_the_shape(self):
        """The node SET is the fact. A different traversal order is not a different graph."""
        assert slot.cfg_shape(["n2", "n0", "n1"]) == slot.cfg_shape(["n0", "n1", "n2"])

    def test_an_inserted_node_changes_the_shape(self):
        """The whole point: the builder split a compound condition, ids shifted by one, and the
        source hash did not move. Without this the override lands on the wrong node."""
        before = slot.shape_of_cfg(self._cfg("n0", "n1", "n2"))
        after = slot.shape_of_cfg(self._cfg("n0", "n1", "n2", "n3"))
        assert before != after

    def test_a_renumbered_graph_of_the_same_size_changes_the_shape(self):
        """Same node COUNT, different ids -- a count check would pass this and be wrong."""
        assert slot.cfg_shape(["n0", "n1", "n2"]) != slot.cfg_shape(["n0", "n1", "n5"])

    def test_an_empty_graph_has_no_shape(self):
        """NOT sha256(""). hashing.py hashed an empty token list for cursors it could not read,
        so thousands of unrelated functions shared one hash, compared equal, and 73% of a
        document silently stopped regenerating. An empty node list is a failure to read the
        CFG, and it must not produce a value that matches another caller's failure."""
        with pytest.raises(slot.SlotKeyError):
            slot.cfg_shape([])
        with pytest.raises(slot.SlotKeyError):
            slot.shape_of_cfg({"nodes": []})
        with pytest.raises(slot.SlotKeyError):
            slot.cfg_shape(["", "  "])

    def test_two_failures_do_not_agree_with_each_other(self):
        """The property the raise above buys, stated directly."""
        import hashlib
        empty_hash = hashlib.sha256(b"").hexdigest()
        assert slot.cfg_shape(["n0"]) != empty_hash


class TestShapeMatches:
    def test_the_same_shape_matches(self):
        s = slot.cfg_shape(["n0", "n1"])
        assert slot.shape_matches(s, s)

    def test_a_different_shape_does_not(self):
        assert not slot.shape_matches(slot.cfg_shape(["n0"]), slot.cfg_shape(["n0", "n1"]))

    def test_no_stored_shape_is_not_a_match(self):
        """Rows written before slot_shape existed make no claim about their graph. "No claim"
        must never read as "verified" -- that is how a guard becomes decoration."""
        assert not slot.shape_matches(None, slot.cfg_shape(["n0"]))
        assert not slot.shape_matches("", slot.cfg_shape(["n0"]))

    def test_no_current_shape_is_not_a_match(self):
        assert not slot.shape_matches(slot.cfg_shape(["n0"]), "")

    def test_two_missing_shapes_do_not_match_each_other(self):
        assert not slot.shape_matches("", "")
        assert not slot.shape_matches(None, None)


class TestUrlToken:
    def test_a_token_is_url_safe(self):
        token = slot.encode(slot.for_node(ENTITY, "n3"))
        assert all(c.isalnum() or c in "-_" for c in token), token
        assert "/" not in token and "|" not in token and "=" not in token

    def test_a_token_round_trips(self):
        key = slot.for_behaviour_row(ENTITY, CALLER)
        assert slot.decode(slot.encode(key)) == key

    def test_rubbish_is_refused(self):
        with pytest.raises(slot.SlotKeyError):
            slot.decode("!!! not base64 !!!")


class TestTheKindListMatchesTheSpec:
    def test_seven_editable_kinds(self):
        assert len(slot.ALL_KINDS) == 7, (
            "REQ-ED-01 lists seven editable kinds; adding or removing one changes what the "
            "UI must offer and what the cascade must consider")

    def test_every_kind_declares_its_parts(self):
        for kind in slot.ALL_KINDS:
            assert slot.parts_for(kind), kind



class TestKeysAsCallersSendThem:
    """`slot.from_request` -- a key as it arrives in a request, not as the server built it.

    A composite key's separator is U+0001. Every JSON viewer -- Swagger, Postman, a browser --
    DISPLAYS it as the six characters `\\u0001`, and nobody can type the real character. So a key
    copied from R7's response and pasted into R4 sent a backslash, and R4 answered
    "409 has no override" for a correction that existed; R5 answered `200 []`. Reported from the
    first manual test of undo on a flowchart label.
    """

    NODE = "Sample-Core|Core|coreAdd|int,int"

    def test_the_displayed_spelling_is_the_same_key(self):
        shown = self.NODE + slot.ESCAPED_SEP + "N3"            # what Swagger shows
        assert slot.from_request(slot.NODE_LABEL, shown) == slot.for_node(self.NODE, "N3")

    def test_the_real_key_is_unchanged(self):
        real = slot.for_node(self.NODE, "N3")
        assert slot.from_request(slot.NODE_LABEL, real) == real

    def test_the_escape_is_exactly_six_characters(self):
        """A constant that was accidentally the separator itself would make the replace a
        no-op and every test above vacuous."""
        assert slot.ESCAPED_SEP == chr(92) + "u0001" and slot.SEP not in slot.ESCAPED_SEP

    def test_behaviour_rows_too(self):
        shown = "Comp|U|f|" + slot.ESCAPED_SEP + "CompX|V|caller|"
        assert slot.from_request(slot.BEHAVIOUR_DESCRIPTION, shown) == \
            slot.for_behaviour_row("Comp|U|f|", "CompX|V|caller|")

    def test_a_flowchart_id_is_named_as_one(self):
        """The commonest mistake: labels are stored per NODE."""
        with pytest.raises(slot.SlotKeyError) as exc:
            slot.from_request(slot.NODE_LABEL, self.NODE)
        msg = str(exc.value)
        assert "flowchart id" in msg and "per node" in msg and "R7" in msg

    def test_a_behaviour_key_without_both_ids_says_where_to_get_one(self):
        with pytest.raises(slot.SlotKeyError) as exc:
            slot.from_request(slot.BEHAVIOUR_DESCRIPTION, "Comp|U|f|")
        assert "R11" in str(exc.value)

    def test_single_part_kinds_are_untouched(self):
        assert slot.from_request(slot.DESCRIPTION, "Comp|U|f|int") == "Comp|U|f|int"
        assert slot.from_request(slot.UNIT_DESCRIPTION, "Comp|U") == "Comp|U"
