"""The shape two documents are compared in, and the rules for comparing a field.

A profile (`swe3`, `swe4`) turns a block stream into a tree of `Entity`. Everything
below that point is generic: the comparator walks two trees, matches children by
key within a parent, and compares `fields` according to the policy registered for
that (kind, field). Adding a document type is therefore a profile plus a policy
table, not a new comparator.

Field policies exist because `==` is the wrong test for most of these columns:

    exact    normalised string equality            Data Type, Input Name
    enum     canonical form, then equality         Direction, Interface Type
    name     one name: key rules and aliases       a diagram's target unit
    names    a set of names, same rules            Source/Destination (callers)
    set      order does not matter, plain text     free-form sets
    seq      order does matter                     parameter types, test steps
    text     advisory only, never a defect         Information, descriptions
    ident    not compared across documents         Interface ID (see swe3)
    ignore   present for the report, not compared  section numbers

`name` and `names` exist because a cell that holds a *name* has to be read the
way a name is read everywhere else. A column of unit names compared as text calls
`Sample Core` and `Sample-Core` a difference, and ignores the alias file that a
human has already used to settle exactly that question.

`text` is separate from `exact` on purpose. Our bar is logical correctness, not a
byte match with the client, and a tool that calls every rewording a defect is one
nobody reads twice.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# A cell that says "nothing here". Two different spellings of nothing are not a
# difference worth a line in a report.
PLACEHOLDERS = {"", "-", "n/a", "na", "none", "tbd", "void"}

# Severity decides the order of the report and what a gate fails on.
HIGH, MEDIUM, LOW, INFO = "high", "medium", "low", "info"


@dataclass
class Entity:
    """One addressable thing in a document: a component, unit, interface, step."""
    kind: str
    name: str
    key: str = ""                        # normalised matching key
    number: str = ""                     # heading number as printed; never an identity
    fields: dict = field(default_factory=dict)
    children: list = field(default_factory=list)
    images: list = field(default_factory=list)
    index: int = 0                       # position among its siblings of the same kind

    def __post_init__(self):
        # A key given at construction is a deliberate override -- a fixed section
        # keys to its canonical name whatever it is titled. Anything else is
        # derived from the name on demand, so that changing the name cannot leave
        # a stale key behind to match on.
        self._explicit_key = bool(self.key)
        if not self.key:
            self.key = normalise_key(self.name)

    def match_key(self) -> str:
        """The key to match this entity on, honouring an override."""
        if getattr(self, "_explicit_key", False):
            return self.key
        return normalise_key(self.name)

    def of_kind(self, kind: str) -> list:
        return [c for c in self.children if c.kind == kind]

    def to_dict(self) -> dict:
        out = {"kind": self.kind, "name": self.name, "key": self.key}
        if self.number:
            out["number"] = self.number
        if self.fields:
            out["fields"] = self.fields
        if self.images:
            out["images"] = self.images
        if self.children:
            out["children"] = [c.to_dict() for c in self.children]
        return out


@dataclass
class Policy:
    """How one field is compared, and how loudly a difference is reported."""
    how: str
    severity: str = MEDIUM
    label: str = ""

    def __post_init__(self):
        if not self.label:
            self.label = self.how


def normalise_key(name: str) -> str:
    """The matching key for a name.

    Case, spaces, underscores and hyphens are noise across two documents written
    by different people; `Sample Core`, `sample_core` and `Sample-Core` are one
    thing.

    A layer/component path is deliberately *kept* whole: `Layer1.App/Main` and
    `Layer2.App/Main` are two different units, and the wiki allows two layers to
    hold a component of the same name, so trimming to the last part would merge
    units that are not the same unit.
    """
    s = (name or "").strip()
    s = s.split("(")[0].strip()          # drop a trailing "(...)" qualifier
    s = re.sub(r"[\s_\-]+", "", s)
    return s.casefold()


_CODE_COMMENT_RE = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)


def normalise_code(value) -> str:
    """A declaration reduced to what it declares.

    Two authors wrap, indent and comment the same declaration differently, and none of
    that changes what it declares. Comments go, every run of whitespace becomes one
    space, and the space around punctuation goes too -- so `int  g_x=0 ;` and
    `int g_x = 0;` are one declaration, while `int g_x = 1;` is not.
    """
    text = _CODE_COMMENT_RE.sub(" ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r" ?([(){}\[\],;=:*&<>]) ?", r"\1", text)
    return text


def normalise_text(value) -> str:
    """Whitespace-collapsed, case-folded -- for `exact`.

    Anything is accepted, not just a string: a field may legitimately hold a
    count or a list of nesting depths, and `0` must stay `0` rather than becoming
    the empty string that `value or ""` would make of it.
    """
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip()).casefold()


def is_placeholder(value) -> bool:
    """True when a value says 'nothing here' in any of its usual spellings."""
    if value is None:
        return True
    if isinstance(value, (list, tuple, set)):
        return not value or all(is_placeholder(v) for v in value)
    return normalise_text(str(value)).strip(" .") in PLACEHOLDERS


# --- canonical forms for the enum columns -----------------------------------

_DIRECTION = {
    "in": "In", "input": "In",
    "out": "Out", "output": "Out",
    "inout": "In/Out", "in/out": "In/Out", "in / out": "In/Out",
    "bidirectional": "In/Out", "both": "In/Out",
}

_IFACE_TYPE = {
    "function": "Function", "method": "Function", "api": "Function",
    "globalvariable": "Global Variable", "global": "Global Variable",
    "variable": "Global Variable", "data": "Global Variable",
}

ENUMS = {"direction": _DIRECTION, "interfaceType": _IFACE_TYPE}


def canonical_enum(field_name: str, value) -> str:
    """Canonical spelling of an enum cell, or the value unchanged when unknown.

    Unknown is left alone rather than forced: a value the client uses and we do
    not is exactly the finding worth printing, and silently folding it into the
    nearest known one would hide it.
    """
    text = "" if value is None else str(value)
    table = ENUMS.get(field_name)
    if not table:
        return text.strip()
    probe = re.sub(r"[\s_\-]+", "", text).casefold()
    return table.get(probe, text.strip())
