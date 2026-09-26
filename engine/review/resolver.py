"""Slot → the model field it names.

`slot.py` owns the *format* of a key; this module owns what a key *points at*. Keeping them
apart matters: the format is a pure string question with no model in sight, and mixing the two
is how a module ends up knowing both and being the only place that can answer either.

## Five of the seven kinds are model-backed

| kind | artifact | entry | field |
|---|---|---|---|
| `description` | `functions`, else `globalVariables` | `entity_key` | `description` |
| `behaviourInputName` | `functions` | `entity_key` | `behaviourInputName` |
| `behaviourOutputName` | `functions` | `entity_key` | `behaviourOutputName` |
| `unitDescription` | `units` | `unit_key` | `description` |
| `structDescription` | `dataDictionary` | `entity_key` | `description` |

`description` looks in `functions` first and then `globalVariables` because both carry one and a
key identifies which it is — a global's description is editable too (the cascade in
REVIEW_UPDATE_DESIGN §6 regenerates its unit's description from it).

## Two are not, and that is a real gap

`nodeLabel` lives in the flowchart JSON and `behaviourDescription` in `_behaviour_pngs.json`
(`_docxRows[…].behaviorDescription`) — both **Phase-3 view output**, with no model field behind
them. Writing an override into view output would be undone by the next derivation of that view,
which is the two-copies arrangement this whole feature exists to remove.

So they are refused here, loudly, with `SlotHasNoModelHome`. A silent no-op or a write that the
next Phase 3 quietly reverts is how the September defects got as far as they did.
"""
from __future__ import annotations

from typing import Any, Dict, NamedTuple, Optional, Tuple

from review import slot

# Artifact names, spelled as `core.model_io` spells them. Imported lazily in `_names()` so this
# module stays importable without the engine path set up (the API imports it to validate a
# request long before any model is loaded).
_FUNCTIONS = "functions"
_GLOBALS = "globalVariables"
_UNITS = "units"
_DATA_DICTIONARY = "dataDictionary"


class SlotError(LookupError):
    """Base for "this slot cannot be written"."""


class SlotNotFound(SlotError):
    """The key is well-formed but names nothing in this version — a rename or a deletion."""


class SlotHasNoModelHome(SlotError):
    """The kind is editable per REQ-ED-01 but its text is not stored in the model yet."""


class Location(NamedTuple):
    """Where a slot's text lives."""
    artifact: str       # a `core.model_io` artifact name
    entry_key: str      # the key within that artifact's dict
    field: str          # the field on that entry


#: kind -> (artifacts to search in order, field). Order matters for `description`.
_HOMES: Dict[str, Tuple[Tuple[str, ...], str]] = {
    slot.DESCRIPTION:           ((_FUNCTIONS, _GLOBALS), "description"),
    slot.BEHAVIOUR_INPUT_NAME:  ((_FUNCTIONS,), "behaviourInputName"),
    slot.BEHAVIOUR_OUTPUT_NAME: ((_FUNCTIONS,), "behaviourOutputName"),
    slot.UNIT_DESCRIPTION:      ((_UNITS,), "description"),
    slot.STRUCT_DESCRIPTION:    ((_DATA_DICTIONARY,), "description"),
}

#: Editable (REQ-ED-01) but stored only in Phase-3 view output. See the module docstring.
VIEW_ONLY_KINDS = (slot.NODE_LABEL, slot.BEHAVIOUR_DESCRIPTION)

MODEL_BACKED_KINDS = tuple(k for k in slot.ALL_KINDS if k in _HOMES)


def _entry_key(kind: str, key: str) -> str:
    """The dict key inside the artifact. For every model-backed kind the slot key IS it."""
    parts = slot.parse(kind, key)                 # raises SlotKeyError on a malformed key
    return parts.get("entity_key") or parts["unit_key"]


def locate(model: Dict[str, Any], kind: str, key: str) -> Location:
    """Where `kind`/`key` lives in `model`. Raises rather than guessing.

    `model` maps an artifact name to its dict, exactly as `core.model_io.load_model` returns it.
    A missing artifact is treated as empty, not as an error: a project with no data dictionary is
    ordinary, and it should read as "that struct is not here", not as a crash.
    """
    if kind in VIEW_ONLY_KINDS:
        raise SlotHasNoModelHome(
            "%s is editable but its text lives in Phase-3 view output, not the model, so an "
            "override written here would be reverted by the next derivation" % kind)
    try:
        artifacts, field = _HOMES[kind]
    except KeyError:
        raise slot.SlotKeyError(
            "unknown slot kind %r; expected one of %s" % (kind, ", ".join(slot.ALL_KINDS))) from None

    entry_key = _entry_key(kind, key)
    for artifact in artifacts:
        entries = model.get(artifact) or {}
        if entry_key in entries:
            return Location(artifact, entry_key, field)

    raise SlotNotFound(
        "%s: %r is not in %s for this version" % (kind, entry_key, " or ".join(artifacts)))


def read_text(model: Dict[str, Any], kind: str, key: str) -> str:
    """The text currently in the model for this slot. `""` when the field is unset.

    An unset field is not an error: `behaviourOutputName` is legitimately absent on a function
    that writes nothing, and the reviewer may be filling it in for the first time.
    """
    loc = locate(model, kind, key)
    entry = (model.get(loc.artifact) or {}).get(loc.entry_key) or {}
    return str(entry.get(loc.field) or "")


def write_text(model: Dict[str, Any], kind: str, key: str, text: str) -> Location:
    """Put `text` into the model, in place. Returns where it went, so the caller knows which
    artifact to persist — writing back all four when one changed is how a narrow edit turns
    into a wide one."""
    loc = locate(model, kind, key)
    model[loc.artifact][loc.entry_key][loc.field] = text
    return loc


def entity_of(kind: str, key: str) -> str:
    """The entity (or unit) id a slot key names, without caring which artifact holds it.

    `_entry_key` is the private version of this; a caller outside the module needs the same answer
    to address the entity in DERIVED output, where the model's artifact split does not exist.
    """
    return _entry_key(kind, key)


def artifact_for(kind: str) -> Optional[str]:
    """The artifact a kind writes to, when there is exactly one. `None` for `description`,
    which depends on whether the key names a function or a global."""
    homes = _HOMES.get(kind)
    return homes[0][0] if homes and len(homes[0]) == 1 else None
