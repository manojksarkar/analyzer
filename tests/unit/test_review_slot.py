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


class TestRoundTrip:
    @pytest.mark.parametrize("kind", slot.ALL_KINDS)
    def test_every_kind_round_trips(self, kind):
        parts = {n: {"entity_key": ENTITY,
                     "unit_key": "Comp|UnitA",
                     "node_id": "n3",
                     "function_id": ENTITY,
                     "external_unit_function": "UnitB - doThing"}[n]
                 for n in slot.parts_for(kind)}
        key = slot.make(kind, **parts)
        assert slot.parse(kind, key) == parts

    def test_a_composite_survives_the_pipes_in_its_own_parts(self):
        """The part itself contains the separator a naive scheme would split on."""
        key = slot.for_node(ENTITY, "n12")
        got = slot.parse(slot.NODE_LABEL, key)
        assert got["entity_key"] == ENTITY, "the entity key's own pipes were mis-split"
        assert got["node_id"] == "n12"

    def test_a_behaviour_row_survives_a_spaced_display_name(self):
        key = slot.for_behaviour_row(ENTITY, "UHP_BackboneCom - ClearDtcm")
        got = slot.parse(slot.BEHAVIOUR_DESCRIPTION, key)
        assert got["function_id"] == ENTITY
        assert got["external_unit_function"] == "UHP_BackboneCom - ClearDtcm"

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


class TestUrlToken:
    def test_a_token_is_url_safe(self):
        token = slot.encode(slot.for_node(ENTITY, "n3"))
        assert all(c.isalnum() or c in "-_" for c in token), token
        assert "/" not in token and "|" not in token and "=" not in token

    def test_a_token_round_trips(self):
        key = slot.for_behaviour_row(ENTITY, "UnitB - doThing")
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
