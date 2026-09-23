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


class TestTextualFallback:
    """Symbols edges.json misses (file-scope usage) are recovered from the unit's
    own source text passed as used_symbol_names."""

    def _other_unit(self):
        return {"path": "Comp/OtherUnit", "fileName": "OtherUnit.cpp",
                "functionIds": [OTHER_FID], "globalVariableIds": []}

    def _build_with_text(self, unit_info, text_names):
        return dx._build_unit_header_table(
            unit_info, [], DD, {}, "", None, {}, MACRO_USERS, TYPE_USERS,
            SRC_PATHS, text_names,
        )

    def test_file_scope_macro_recovered_from_text(self):
        # OtherUnit has no edges usage, but its source text references SCALE
        # (e.g. an array size) — the fallback must surface it.
        decls = _decls(self._build_with_text(self._other_unit(), {"SCALE"}))
        assert any("#define SCALE 8" in d for d in decls)

    def test_symbol_absent_from_text_not_surfaced(self):
        decls = _decls(self._build_with_text(self._other_unit(), {"UNRELATED"}))
        assert not any("SCALE" in d or "MAXN" in d for d in decls)

    def test_orphan_enum_recovered_from_text(self):
        rows = self._build_with_text(self._other_unit(), {"Level"})
        assert any("LO=0" in (r.get("information") or "") for r in rows)

    def test_orphan_enum_recovered_via_enumerator_only(self):
        # The unit references only the enumerator HI, never the enum type Level.
        # Neither edges (typeUsers) nor the type-name text test would catch it, so
        # the enum must be recovered by matching the enumerator name.
        rows = self._build_with_text(self._other_unit(), {"HI"})
        assert any("LO=0" in (r.get("information") or "") for r in rows)


class TestCommentStringStripping:
    def test_symbol_in_comment_or_string_is_stripped(self):
        src = '// SCALE mentioned\nint x = 1; const char* s = "MAXN";\n/* Level */'
        cleaned = dx._COMMENT_STRING_RE.sub(" ", src)
        import re as _re
        ids = set(_re.findall(r"[A-Za-z_]\w*", cleaned))
        assert "SCALE" not in ids and "MAXN" not in ids and "Level" not in ids
        assert "x" in ids  # real code identifiers survive


# A unit's own globals, one public and one private. Visibility must NOT filter this
# table: it lists what the unit declares and uses, not what it publishes, so a private
# global named in the unit's own flowcharts is explained here (client decision,
# 2026-09-22; SWE3_WIKI N.1.4). The interface table is where visibility still applies.
GLOBALS = {
    "Comp/UserUnit.cpp:10": {
        "variableId": "Comp/UserUnit.cpp:10", "variableName": "g_public",
        "qualifiedName": "g_public", "visibility": "public", "value": "0",
        "location": {"file": "Comp/UserUnit.cpp", "line": 10},
    },
    "Comp/UserUnit.cpp:11": {
        "variableId": "Comp/UserUnit.cpp:11", "variableName": "s_private",
        "qualifiedName": "s_private", "visibility": "private", "value": "7",
        "location": {"file": "Comp/UserUnit.cpp", "line": 11},
    },
    "Comp/UserUnit.cpp:12": {
        "variableId": "Comp/UserUnit.cpp:12", "variableName": "s_secret",
        "qualifiedName": "Owner::s_secret", "visibility": "private", "value": "",
        "location": {"file": "Comp/UserUnit.cpp", "line": 12},
    },
}


class TestGlobalsNotFilteredByVisibility:
    def _unit(self):
        return {"path": "Comp/UserUnit", "fileName": "UserUnit.cpp",
                "functionIds": [USER_FID], "globalVariableIds": list(GLOBALS)}

    def _rows(self):
        return dx._build_unit_header_table(
            self._unit(), [], DD, GLOBALS, "", None, {}, MACRO_USERS, TYPE_USERS, SRC_PATHS
        )

    def test_public_global_present(self):
        assert any("g_public" in d for d in _decls(self._rows()))

    def test_private_global_present(self):
        assert any("s_private" in d for d in _decls(self._rows()))

    def test_private_class_static_present(self):
        assert any("Owner::s_secret" in d for d in _decls(self._rows()))

    def test_every_global_gets_a_row(self):
        decls = _decls(self._rows())
        assert sum(1 for d in decls if d in ("g_public", "s_private", "Owner::s_secret")) == 3


# A global declared in an orphan header belongs to no unit, so it is lent to the units
# that USE it — the same rule the header's macros and types follow. A global in a
# COMPANION header (a header whose .cpp exists) stays with its own unit.
ORPHAN_GLOBALS = {
    "Comp/Shared.h:5": {
        "variableId": "Comp/Shared.h:5", "variableName": "g_sharedFlag",
        "qualifiedName": "g_sharedFlag", "visibility": "public", "value": "",
        "location": {"file": "Comp/Shared.h", "line": 5},
    },
    "Comp/Shared.h:6": {
        "variableId": "Comp/Shared.h:6", "variableName": "g_unusedShared",
        "qualifiedName": "g_unusedShared", "visibility": "public", "value": "",
        "location": {"file": "Comp/Shared.h", "line": 6},
    },
    "Comp/OtherUnit.h:7": {
        "variableId": "Comp/OtherUnit.h:7", "variableName": "g_companion",
        "qualifiedName": "g_companion", "visibility": "public", "value": "",
        "location": {"file": "Comp/OtherUnit.h", "line": 7},
    },
    # extern + definition of ONE variable, both reaching UserUnit.
    "Comp/UserUnit.cpp:50": {
        "variableId": "Comp/UserUnit.cpp:50", "variableName": "g_dup",
        "qualifiedName": "g_dup", "visibility": "public", "value": "",
        "location": {"file": "Comp/UserUnit.cpp", "line": 50},
    },
    "Comp/UserUnit.cpp:51": {
        "variableId": "Comp/UserUnit.cpp:51", "variableName": "g_dup",
        "qualifiedName": "g_dup", "visibility": "public", "value": "1",
        "location": {"file": "Comp/UserUnit.cpp", "line": 51},
    },
}

# UserUnit's functions touch the orphan global and the companion one; nobody touches
# g_unusedShared.
GLOBAL_USERS = {
    "Comp/Shared.h:5": {USER_FID},
    "Comp/OtherUnit.h:7": {USER_FID},
    "Comp/Shared.h:6": {OTHER_FID},
}


class TestOrphanHeaderGlobals:
    def _rows(self, own_gids=()):
        unit = {"path": "Comp/UserUnit", "fileName": "UserUnit.cpp",
                "functionIds": [USER_FID], "globalVariableIds": list(own_gids)}
        return dx._build_unit_header_table(
            unit, [], {}, ORPHAN_GLOBALS, "", None, {},
            {}, {}, SRC_PATHS, None, GLOBAL_USERS,
        )

    def test_used_orphan_global_present(self):
        assert "g_sharedFlag" in _decls(self._rows())

    def test_unused_orphan_global_absent(self):
        assert "g_unusedShared" not in _decls(self._rows())

    def test_companion_header_global_not_lent(self):
        assert "g_companion" not in _decls(self._rows())

    def test_extern_dropped_when_definition_in_same_unit(self):
        decls = _decls(self._rows(own_gids=["Comp/UserUnit.cpp:50", "Comp/UserUnit.cpp:51"]))
        assert decls.count("g_dup") == 1

    def test_non_using_unit_gets_no_orphan_global(self):
        unit = {"path": "Comp/OtherUnit", "fileName": "OtherUnit.cpp",
                "functionIds": [OTHER_FID], "globalVariableIds": []}
        rows = dx._build_unit_header_table(
            unit, [], {}, ORPHAN_GLOBALS, "", None, {},
            {}, {}, SRC_PATHS, None, GLOBAL_USERS,
        )
        assert "g_sharedFlag" not in _decls(rows)
