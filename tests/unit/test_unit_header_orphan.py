"""Unit tests for docx_exporter._build_unit_header_table orphan-header surfacing.

A unit's header table must list, besides its own declarations, the
define/enum/typedef symbols defined in an *orphan header* (a header with no
same-name source) that THIS unit actually uses — driven by edges.json
macroUsers/typeUsers. Symbols the unit does not use, and symbols from a
companion header of another unit, must not appear.
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

import docx_exporter as dx  # noqa: E402


# Two real (source-backed) units, plus an orphan header Shared.h (no Shared.cpp).
SRC_PATHS = {"Comp/UserUnit", "Comp/OtherUnit"}

DD = {
    # orphan-header symbols (defined in Comp/Shared.h)
    "MAXN@Comp/Shared.h:3": {
        "kind": "define", "name": "MAXN", "qualifiedName": "MAXN",
        "value": "256", "text": "#define MAXN 256",
        "location": {"file": "Comp/Shared.h", "line": 3},
    },
    "SCALE@Comp/Shared.h:4": {
        "kind": "define", "name": "SCALE", "qualifiedName": "SCALE",
        "value": "8", "text": "#define SCALE 8",
        "location": {"file": "Comp/Shared.h", "line": 4},
    },
    "Level": {
        "kind": "enum", "name": "Level", "qualifiedName": "Level",
        "underlyingType": "UINT8",
        "enumerators": [{"name": "LO", "value": 0}, {"name": "HI", "value": 1}],
        "location": {"file": "Comp/Shared.h", "line": 6},
    },
    # UserUnit's own define
    "OWN@Comp/UserUnit.cpp:2": {
        "kind": "define", "name": "OWN", "qualifiedName": "OWN",
        "value": "1", "text": "#define OWN 1",
        "location": {"file": "Comp/UserUnit.cpp", "line": 2},
    },
    # A define in OtherUnit's companion header (NOT an orphan header)
    "COMPANION@Comp/OtherUnit.h:1": {
        "kind": "define", "name": "COMPANION", "qualifiedName": "COMPANION",
        "value": "9", "text": "#define COMPANION 9",
        "location": {"file": "Comp/OtherUnit.h", "line": 1},
    },
}

USER_FID = "Comp|UserUnit|useIt|int"
OTHER_FID = "Comp|OtherUnit|noUse|int"

# UserUnit uses MAXN + Level (orphan) and — to prove the companion-header guard —
# also "uses" COMPANION (defined in OtherUnit's companion header). SCALE is used
# by nobody here.
MACRO_USERS = {
    "MAXN@Comp/Shared.h": [USER_FID],
    "COMPANION@Comp/OtherUnit.h": [USER_FID],
}
TYPE_USERS = {"Level": [USER_FID]}


def _decls(rows):
    return [(r.get("declaration") or "") for r in rows]


def _build(unit_info):
    # base_path="" keeps this filesystem-free: enum decl snippet falls back to name.
    return dx._build_unit_header_table(
        unit_info, [], DD, {}, "", None, {}, MACRO_USERS, TYPE_USERS, SRC_PATHS
    )


class TestOrphanHeaderSurfacing:
    def _user_unit(self):
        return {"path": "Comp/UserUnit", "fileName": "UserUnit.cpp",
                "functionIds": [USER_FID], "globalVariableIds": []}

    def test_own_define_present(self):
        decls = _decls(_build(self._user_unit()))
        assert any("#define OWN 1" in d for d in decls)

    def test_used_orphan_define_present(self):
        decls = _decls(_build(self._user_unit()))
        assert any("#define MAXN 256" in d for d in decls)

    def test_used_orphan_enum_present(self):
        rows = _build(self._user_unit())
        # enum row info carries the enumerators
        assert any("LO=0" in (r.get("information") or "") for r in rows)

    def test_unused_orphan_define_absent(self):
        decls = _decls(_build(self._user_unit()))
        assert not any("SCALE" in d for d in decls)

    def test_companion_header_of_other_unit_not_pulled_in(self):
        # COMPANION lives in OtherUnit.h (has OtherUnit.cpp) → not an orphan header,
        # so even though UserUnit "uses" it, it must not appear.
        decls = _decls(_build(self._user_unit()))
        assert not any("COMPANION" in d for d in decls)

    def test_non_using_unit_gets_no_orphan_rows(self):
        other = {"path": "Comp/OtherUnit", "fileName": "OtherUnit.cpp",
                 "functionIds": [OTHER_FID], "globalVariableIds": []}
        decls = _decls(_build(other))
        assert not any(("MAXN" in d or "SCALE" in d or "Level" in d) for d in decls)
