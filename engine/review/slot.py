"""Slot addressing — the one place a slot key is built or taken apart.

A **slot** is a place in a generated document that holds LLM-written text. It is addressed by
a `(version_id, kind, key)` triple; this module owns the `key` half.

Every key is built from an id that already exists — `entities.entity_key`,
`model_units.unit_key`, a function id — because inventing a second identifier for something
already identified is how two of them drift apart. See REQ-ID-01.

**Nothing else may construct or split a key.** The interface-id collision in September came
from exactly that: the numbering keyed on the unit while the id encoded a lossy form of it,
two expressions for one fact, and they disagreed. One module, one format, one parse.

## Composite keys

Two kinds address something *inside* an entity, so their key carries two parts. The obvious
separator is wrong: `entity_key` is itself `component|unit|qualifiedName|paramTypes`, so a
composite joined with `|` can only be split by counting pipes and hoping. Today the second
part happens to contain none (`externalUnitFunction` is `"UnitB - doThing"`), which makes the
heuristic work and makes it a trap — a later change to that format would break parsing with
no error.

So composites join on **SOH (0x01)**, which cannot occur in a C++ identifier, a path, or a
generated display name. Parsing is then exact rather than probabilistic. Not the 0x1f that
`hashing.py` joins on — see the note on `SEP` below for why that one is a trap here.

## Keys and URLs

A key contains `|`, `:`, `,`, `*` and spaces, and composites contain a control character.
**Keys therefore travel in a request body or a query parameter, never in a URL path segment** —
percent-encoding a path segment that may contain a separator is a routing bug waiting to be
written. `encode()` / `decode()` below give a URL-safe form for the cases that need one.
"""
from __future__ import annotations

import base64
from typing import Dict, Tuple

# ---------------------------------------------------------------------------
# kinds
# ---------------------------------------------------------------------------
DESCRIPTION = "description"
BEHAVIOUR_INPUT_NAME = "behaviourInputName"
BEHAVIOUR_OUTPUT_NAME = "behaviourOutputName"
BEHAVIOUR_DESCRIPTION = "behaviourDescription"
UNIT_DESCRIPTION = "unitDescription"
STRUCT_DESCRIPTION = "structDescription"
NODE_LABEL = "nodeLabel"

#: Every kind a reviewer may edit (REQ-ED-01). Ordered as the spec lists them.
ALL_KINDS: Tuple[str, ...] = (
    DESCRIPTION,
    BEHAVIOUR_INPUT_NAME,
    BEHAVIOUR_OUTPUT_NAME,
    BEHAVIOUR_DESCRIPTION,
    UNIT_DESCRIPTION,
    STRUCT_DESCRIPTION,
    NODE_LABEL,
)

#: kind -> the part names its key carries, in key order.
_PARTS: Dict[str, Tuple[str, ...]] = {
    DESCRIPTION:           ("entity_key",),
    BEHAVIOUR_INPUT_NAME:  ("entity_key",),
    BEHAVIOUR_OUTPUT_NAME: ("entity_key",),
    STRUCT_DESCRIPTION:    ("entity_key",),
    UNIT_DESCRIPTION:      ("unit_key",),
    BEHAVIOUR_DESCRIPTION: ("function_id", "external_unit_function"),
    NODE_LABEL:            ("entity_key", "node_id"),
}

# SOH (0x01). Cannot occur in an identifier, a path, or a generated display name, so a
# composite splits exactly instead of by counting the separators the parts already contain.
#
# NOT 0x1f, which is what `hashing.py` uses: Python counts 0x1c-0x1f as WHITESPACE, so
# `"a\x1f".strip()` deletes it. `.strip()` is everywhere — it laundered a malformed part
# straight past the guard below the first time this was written, and the test that should
# have caught it passed. A separator in the whitespace class is a corruption waiting to
# happen; 0x01 is not one.
SEP = "\x01"


class SlotKeyError(ValueError):
    """A kind that does not exist, or a key that does not match its kind's shape."""


# ---------------------------------------------------------------------------
# build / take apart
# ---------------------------------------------------------------------------
def parts_for(kind: str) -> Tuple[str, ...]:
    """The part names `kind`'s key carries. Raises for an unknown kind."""
    try:
        return _PARTS[kind]
    except KeyError:
        raise SlotKeyError(
            "unknown slot kind %r; expected one of %s" % (kind, ", ".join(ALL_KINDS))) from None


def make(kind: str, **parts: str) -> str:
    """The key for `kind` from its named parts.

    Every part must be present and non-empty, and none may contain the separator — a part
    that did would make the key ambiguous, which is the one thing this module exists to
    prevent.
    """
    names = parts_for(kind)
    missing = [n for n in names if not str(parts.get(n) or "").strip()]
    if missing:
        raise SlotKeyError("%s needs %s; missing or empty: %s"
                           % (kind, ", ".join(names), ", ".join(missing)))
    extra = sorted(set(parts) - set(names))
    if extra:
        raise SlotKeyError("%s takes only %s; got also %s"
                           % (kind, ", ".join(names), ", ".join(extra)))
    # Checked on the RAW value, before the strip. With SEP outside the whitespace class the
    # two orders agree, so this is belt-and-braces rather than the fix -- what actually keeps
    # a part from being laundered past this guard is SEP not being a character `.strip()`
    # eats. Checking raw means the guard stays right on its own if SEP is ever reconsidered.
    raw = [str(parts[n]) for n in names]
    bad = [n for n, v in zip(names, raw) if SEP in v]
    if bad:
        raise SlotKeyError("%s: %s may not contain the separator (0x01)"
                           % (kind, ", ".join(bad)))
    return SEP.join(v.strip() for v in raw)


def parse(kind: str, key: str) -> Dict[str, str]:
    """`key` split back into its named parts. The inverse of `make`."""
    names = parts_for(kind)
    values = (key or "").split(SEP)
    if len(values) != len(names) or not all(v.strip() for v in values):
        raise SlotKeyError(
            "%s key must be %d non-empty part(s) (%s); got %r"
            % (kind, len(names), ", ".join(names), key))
    return dict(zip(names, values))


def is_valid(kind: str, key: str) -> bool:
    """Whether `key` is well-formed for `kind`. Never raises."""
    try:
        parse(kind, key)
        return True
    except SlotKeyError:
        return False


# ---------------------------------------------------------------------------
# convenience builders — so callers never touch the part names as strings
# ---------------------------------------------------------------------------
def for_entity(kind: str, entity_key: str) -> str:
    """A key for one of the entity-addressed kinds."""
    if _PARTS.get(kind) != ("entity_key",):
        raise SlotKeyError("%s is not addressed by an entity key alone" % kind)
    return make(kind, entity_key=entity_key)


def for_unit(unit_key: str) -> str:
    return make(UNIT_DESCRIPTION, unit_key=unit_key)


def for_node(entity_key: str, node_id: str) -> str:
    return make(NODE_LABEL, entity_key=entity_key, node_id=node_id)


def for_behaviour_row(function_id: str, external_unit_function: str) -> str:
    return make(BEHAVIOUR_DESCRIPTION, function_id=function_id,
                external_unit_function=external_unit_function)


# ---------------------------------------------------------------------------
# URL-safe form
# ---------------------------------------------------------------------------
def encode(key: str) -> str:
    """`key` as a URL-safe token, for the places one must appear in a path.

    base64url without padding: the alphabet is `[A-Za-z0-9_-]`, so nothing needs escaping and
    no separator inside the key can be mistaken for a path separator.
    """
    raw = base64.urlsafe_b64encode((key or "").encode("utf-8")).decode("ascii")
    return raw.rstrip("=")


def decode(token: str) -> str:
    """The inverse of `encode`. Raises `SlotKeyError` on anything that is not one."""
    t = (token or "").strip()
    try:
        return base64.urlsafe_b64decode(t + "=" * (-len(t) % 4)).decode("utf-8")
    except Exception:
        raise SlotKeyError("not a slot-key token: %r" % token) from None
