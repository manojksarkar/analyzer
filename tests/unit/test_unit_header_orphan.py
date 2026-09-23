"""Unit tests for views/unit_headers.py::build_rows -- orphan-header surfacing.

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

from views import unit_headers as dx  # noqa: E402


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
    return dx.build_rows(
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
        return dx.build_rows(
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
        return dx.build_rows(
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
        return dx.build_rows(
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
        rows = dx.build_rows(
            unit, [], {}, ORPHAN_GLOBALS, "", None, {},
            {}, {}, SRC_PATHS, None, GLOBAL_USERS,
        )
        assert "g_sharedFlag" not in _decls(rows)


# ── struct / class / union rows ──────────────────────────────────────────────
# The client's answers of 2026-09-23, one test each:
#   Q1  a record type is listed in its own right, not only through a typedef
#   Q2  the declaration as written, method signatures included
#   Q3  an inline BODY is reduced to a declaration
#   Q7  a type declared inside a class gets NO row of its own
#   Q9  a class static's definition gets NO row of its own
#   Q16 a union and a `using` alias are listed like a struct and a typedef
RECORD_DD = {
    "Cfg": {
        "kind": "struct", "name": "Cfg", "qualifiedName": "Cfg",
        "fields": [{"name": "mode", "type": "int"}],
        "location": {"file": "Comp/UserUnit.cpp", "line": 20},
    },
    "Owner": {
        "kind": "class", "name": "Owner", "qualifiedName": "Owner", "fields": [],
        "location": {"file": "Comp/UserUnit.cpp", "line": 30},
    },
    "Word": {
        "kind": "union", "name": "Word", "qualifiedName": "Word", "fields": [],
        "location": {"file": "Comp/UserUnit.cpp", "line": 40},
    },
    "Alias_t": {
        "kind": "typedef", "name": "Alias_t", "qualifiedName": "Alias_t",
        "underlyingType": "unsigned short",
        "location": {"file": "Comp/UserUnit.cpp", "line": 50},
    },
    # Declared INSIDE Owner: the class's own declaration already shows it.
    "Owner::Mode": {
        "kind": "enum", "name": "Mode", "qualifiedName": "Owner::Mode",
        "nestedIn": "Owner",
        "enumerators": [{"name": "FAST", "value": 0}],
        "location": {"file": "Comp/UserUnit.cpp", "line": 31},
    },
    "Owner::Key_t": {
        "kind": "typedef", "name": "Key_t", "qualifiedName": "Owner::Key_t",
        "nestedIn": "Owner", "underlyingType": "int",
        "location": {"file": "Comp/UserUnit.cpp", "line": 32},
    },
    "Owner::Slot": {
        "kind": "struct", "name": "Slot", "qualifiedName": "Owner::Slot",
        "nestedIn": "Owner", "fields": [],
        "location": {"file": "Comp/UserUnit.cpp", "line": 33},
    },
    # A namespace-qualified type is NOT nested in a class and keeps its row.
    "ns::Free": {
        "kind": "struct", "name": "Free", "qualifiedName": "ns::Free", "fields": [],
        "location": {"file": "Comp/UserUnit.cpp", "line": 60},
    },
    "(anonymous)@Comp/UserUnit.cpp:70": {
        "kind": "struct", "name": "(anonymous)", "qualifiedName": "(anonymous)@k",
        "fields": [], "location": {"file": "Comp/UserUnit.cpp", "line": 70},
    },
}

CLASS_STATIC_GLOBALS = {
    "Comp/UserUnit.cpp:80": {
        "variableId": "Comp/UserUnit.cpp:80", "variableName": "s_count",
        "qualifiedName": "Owner::s_count", "className": "Owner",
        "visibility": "public", "value": "0",
        "location": {"file": "Comp/UserUnit.cpp", "line": 80},
    },
    "Comp/UserUnit.cpp:81": {
        "variableId": "Comp/UserUnit.cpp:81", "variableName": "g_fileScope",
        "qualifiedName": "g_fileScope", "visibility": "public", "value": "1",
        "location": {"file": "Comp/UserUnit.cpp", "line": 81},
    },
}


class TestRecordRows:
    def _rows(self, dd=None, globals_data=None):
        unit = {"path": "Comp/UserUnit", "fileName": "UserUnit.cpp",
                "functionIds": [USER_FID],
                "globalVariableIds": list(globals_data or {})}
        return dx.build_rows(unit, [], dd if dd is not None else RECORD_DD,
                             globals_data or {}, "", None, {}, {}, {}, SRC_PATHS, None, {})

    def test_struct_class_and_union_are_listed(self):
        decls = _decls(self._rows())
        assert "Cfg" in decls and "Owner" in decls and "Word" in decls

    def test_labels_name_the_kind(self):
        by = {r["declaration"]: r["information"] for r in self._rows()}
        assert by["Cfg"] == "Structure for Cfg"
        assert by["Owner"] == "Class for Owner"
        assert by["Word"] == "Union for Word"

    # A `using` alias is asserted in tests/e2e/test_unit_headers.py instead: a typedef row
    # needs its declaration read back from source, and every typedef is skipped here where
    # base_path is "" -- the same guard that drops an extra alias on a `} a, *b;` line.

    def test_a_type_nested_in_a_class_gets_no_row(self):
        decls = _decls(self._rows())
        for nested in ("Mode", "Key_t", "Slot"):
            assert nested not in decls, nested

    def test_a_namespace_qualified_type_keeps_its_row(self):
        """`ns::Free` reads like `Owner::Slot` but is not nested in a class."""
        assert "Free" in _decls(self._rows())

    def test_an_anonymous_record_is_skipped(self):
        assert not any("anonymous" in d for d in _decls(self._rows()))

    def test_a_class_statics_definition_gets_no_row(self):
        decls = _decls(self._rows(globals_data=CLASS_STATIC_GLOBALS))
        assert "Owner::s_count" not in decls
        assert "g_fileScope" in decls


class TestDeclarationsOnly:
    def test_an_inline_body_becomes_a_declaration(self):
        out = dx._declarations_only(
            "class C {\npublic:\n    int status() { return 1; }\n};")
        assert "int status();" in out
        assert "return 1" not in out

    def test_a_multi_line_body_is_removed_whole(self):
        out = dx._declarations_only(
            "class C {\n    int f() {\n        return 2;\n    }\n    int m_x;\n};")
        assert "int f();" in out
        assert "return 2" not in out
        assert "int m_x;" in out

    def test_a_declared_only_method_is_untouched(self):
        src = "class C {\npublic:\n    int open(int slot);\n};"
        assert dx._declarations_only(src) == src

    def test_data_members_and_labels_survive(self):
        out = dx._declarations_only(
            "class C {\npublic:\n    int m_a;\nprivate:\n    static int s_b;\n};")
        assert "public:" in out and "private:" in out
        assert "int m_a;" in out and "static int s_b;" in out

    def test_nested_types_keep_their_bodies(self):
        out = dx._declarations_only(
            "class C {\n    enum E { A = 0, B = 1 };\n    struct S { int id; };\n};")
        assert "enum E { A = 0, B = 1 };" in out
        assert "struct S { int id; };" in out

    def test_default_and_pure_virtual_are_untouched(self):
        src = ("class C {\npublic:\n    virtual ~C() = default;\n"
               "    virtual int f(int a) = 0;\n};")
        assert dx._declarations_only(src) == src

    def test_a_function_pointer_member_is_data(self):
        out = dx._declarations_only("struct S {\n    int (*fp)(int);\n};")
        assert "(*fp)" in out

    def test_comments_are_dropped(self):
        out = dx._declarations_only(
            "class C {\n    // explains the method\n    int f();\n};")
        assert "explains" not in out and "int f();" in out


# ── the client's answers, against a REAL source file ─────────────────────────
# build_rows reads the declaration back from disk, so the cases that turn on what the
# source LOOKS like need a file. A temp file keeps them in the unit suite, which always
# runs, rather than in e2e where the pipeline is scoped to one group and they would skip.
_REAL_HEADER = """#pragma once

union Word {
    unsigned int whole;
    unsigned char bytes[4];
};

using Alias_t = unsigned short;

class Owner {
public:
    enum Mode { FAST = 0, SAFE = 1 };
    typedef int Key_t;
    static int s_count;
    int open(int slot);
    int status() { return 1; }
    int m_slot;
protected:
    int retryBudget();
private:
    using Byte_t = unsigned char;
    int secretKey() {
        return 4242;
    }
};
"""


class TestAgainstRealSource:
    def _rows(self, tmp_path):
        src = tmp_path / "Comp"
        src.mkdir()
        (src / "UserUnit.h").write_text(_REAL_HEADER, encoding="utf-8")
        (src / "UserUnit.cpp").write_text("#include \"UserUnit.h\"\n", encoding="utf-8")
        dd = {
            "Word": {"kind": "union", "name": "Word", "qualifiedName": "Word", "fields": [],
                     "location": {"file": "Comp/UserUnit.h", "line": 3}},
            "Alias_t": {"kind": "typedef", "name": "Alias_t", "qualifiedName": "Alias_t",
                        "underlyingType": "unsigned short",
                        "location": {"file": "Comp/UserUnit.h", "line": 8}},
            "Owner": {"kind": "class", "name": "Owner", "qualifiedName": "Owner", "fields": [],
                      "location": {"file": "Comp/UserUnit.h", "line": 10}},
            "Owner::Mode": {"kind": "enum", "name": "Mode", "qualifiedName": "Owner::Mode",
                            "nestedIn": "Owner", "enumerators": [{"name": "FAST", "value": 0}],
                            "location": {"file": "Comp/UserUnit.h", "line": 12}},
            "Owner::Byte_t": {"kind": "typedef", "name": "Byte_t",
                              "qualifiedName": "Owner::Byte_t", "nestedIn": "Owner",
                              "underlyingType": "unsigned char",
                              "location": {"file": "Comp/UserUnit.h", "line": 21}},
        }
        unit = {"path": "Comp/UserUnit", "fileName": "UserUnit.cpp",
                "functionIds": [USER_FID], "globalVariableIds": []}
        return dx.build_rows(unit, [], dd, {}, str(tmp_path), None, {},
                             {}, {}, SRC_PATHS, None, {})

    def test_union_and_using_are_listed_as_written(self, tmp_path):
        decls = _decls(self._rows(tmp_path))
        assert any(d.startswith("union Word {") for d in decls)
        assert any(d.startswith("using Alias_t = unsigned short;") for d in decls)

    def test_the_class_cell_keeps_signatures_and_drops_bodies(self, tmp_path):
        cell = next(d for d in _decls(self._rows(tmp_path)) if d.startswith("class Owner"))
        assert "int open(int slot);" in cell
        assert "int status();" in cell and "return 1" not in cell
        assert "int secretKey();" in cell and "4242" not in cell
        assert "int m_slot;" in cell and "static int s_count;" in cell
        assert "public:" in cell and "private:" in cell

    def test_nested_types_appear_only_inside_the_class(self, tmp_path):
        decls = _decls(self._rows(tmp_path))
        cell = next(d for d in decls if d.startswith("class Owner"))
        assert "enum Mode { FAST = 0, SAFE = 1 };" in cell
        assert "using Byte_t = unsigned char;" in cell
        others = [d for d in decls if d is not cell]
        assert not any("Mode" in d or "Byte_t" in d for d in others)
