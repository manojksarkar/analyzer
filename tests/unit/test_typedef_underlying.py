"""What a typedef records as its `underlyingType` (parser, Phase 1).

`cursor.type` on a TYPEDEF_DECL is the typedef type ITSELF — its spelling is the
alias's own name, never what it aliases. Reading it left every typedef
self-referential with range "NA", so every typedef'd parameter printed "NA" in the
interface table's Data Range column. `parser._typedef_underlying` uses
`underlying_typedef_type` instead and reduces elaborated spellings
("enum Mode_t") to the bare name so the result works as a dataDictionary key.

Needs libclang, so the module skips without it (see test_define_conditional.py).
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ENGINE = os.path.join(PROJECT_ROOT, "engine")

if _ENGINE not in sys.path:
    sys.path.insert(0, _ENGINE)

from utils import get_range  # noqa: E402


@pytest.fixture(scope="module")
def parser_mod():
    """Import parser.py (reads argv at import; also configures libclang).

    Never repoints MODULE_BASE_PATH — `parser` is a module-level singleton shared
    with every other test module that imports it.
    """
    old_argv = sys.argv
    sys.argv = ["parser.py", PROJECT_ROOT]
    try:
        import parser as P
    except Exception as e:  # libclang missing / load failure
        pytest.skip(f"parser/libclang unavailable: {e}")
    finally:
        sys.argv = old_argv
    yield P


def _typedefs(parser_mod, tmp_path, source):
    """Parse a snippet and return {typedef name: _typedef_underlying(cursor)}."""
    from clang import cindex

    src = tmp_path / "t.h"
    src.write_text(source, encoding="utf-8")
    tu = cindex.Index.create().parse(str(src), args=["-x", "c++"])
    found = {}

    def walk(c):
        if c.kind == cindex.CursorKind.TYPEDEF_DECL and c.spelling:
            found[c.spelling] = parser_mod._typedef_underlying(c)
        for ch in c.get_children():
            walk(ch)

    walk(tu.cursor)
    return found


class TestTypedefUnderlying:
    def test_primitive_alias_records_the_primitive(self, parser_mod, tmp_path):
        got = _typedefs(parser_mod, tmp_path, "typedef unsigned char UINT8;\n")
        assert got["UINT8"] == "unsigned char"

    def test_int_alias(self, parser_mod, tmp_path):
        got = _typedefs(parser_mod, tmp_path, "typedef int UNIT;\n")
        assert got["UNIT"] == "int"

    def test_alias_of_alias_records_the_alias(self, parser_mod, tmp_path):
        got = _typedefs(parser_mod, tmp_path,
                        "typedef unsigned short Foo_t;\ntypedef Foo_t MotorSpeed_t;\n")
        assert got["MotorSpeed_t"] == "Foo_t"

    def test_anonymous_enum_typedef_stays_self_referential(self, parser_mod, tmp_path):
        """"enum Mode_t" reduces to "Mode_t" — the unit header table looks the
        underlying name up in the dictionary to print the enumerator list."""
        got = _typedefs(parser_mod, tmp_path,
                        "typedef enum { MODE_A = 0, MODE_B = 1 } Mode_t;\n")
        assert got["Mode_t"] == "Mode_t"

    def test_named_enum_typedef_reduces_to_the_enum_name(self, parser_mod, tmp_path):
        got = _typedefs(parser_mod, tmp_path,
                        "enum Colour { RED = 0 };\ntypedef enum Colour Colour_t;\n")
        assert got["Colour_t"] == "Colour"

    def test_anonymous_struct_typedef_stays_self_referential(self, parser_mod, tmp_path):
        got = _typedefs(parser_mod, tmp_path,
                        "typedef struct { int width; int height; } Size_t;\n")
        assert got["Size_t"] == "Size_t"

    def test_pointer_alias_keeps_the_star(self, parser_mod, tmp_path):
        got = _typedefs(parser_mod, tmp_path, "typedef unsigned char * PtrU8;\n")
        assert got["PtrU8"] == "unsigned char *"


class TestUnderlyingReachesTheRangeColumn:
    """The point of recording a real underlying type: the Data Range column."""

    def test_primitive_alias_resolves_through_the_dictionary(self, parser_mod, tmp_path):
        got = _typedefs(parser_mod, tmp_path, "typedef unsigned char UINT8;\n")
        # What Phase 1 stores: the baked range is still "NA" (get_range_for_type has
        # no "unsigned char" case) — get_range resolves it against the dictionary.
        dd = {"UINT8": {"kind": "typedef", "name": "UINT8", "qualifiedName": "UINT8",
                        "underlyingType": got["UINT8"], "range": "NA"},
              "unsigned char": {"kind": "primitive", "range": "0-0xFF"}}
        assert get_range("UINT8", dd) == "0-0xFF"

    def test_alias_chain_resolves(self, parser_mod, tmp_path):
        got = _typedefs(parser_mod, tmp_path,
                        "typedef unsigned short Foo_t;\ntypedef Foo_t MotorSpeed_t;\n")
        dd = {"MotorSpeed_t": {"kind": "typedef", "qualifiedName": "MotorSpeed_t",
                               "underlyingType": got["MotorSpeed_t"], "range": "NA"},
              "Foo_t": {"kind": "typedef", "qualifiedName": "Foo_t",
                        "underlyingType": got["Foo_t"], "range": "NA"},
              "unsigned short": {"kind": "primitive", "range": "0-0xFFFF"}}
        assert get_range("MotorSpeed_t", dd) == "0-0xFFFF"

    def test_enum_alias_resolves_to_the_enum_range(self, parser_mod, tmp_path):
        got = _typedefs(parser_mod, tmp_path,
                        "typedef enum { MODE_A = 0, MODE_B = 2 } Mode_t;\n")
        dd = {"Mode_t": {"kind": "enum", "qualifiedName": "Mode_t", "range": "0-2"},
              "typedef@Mode_t:t.h:1": {"kind": "typedef", "qualifiedName": "Mode_t",
                                       "underlyingType": got["Mode_t"], "range": "NA"}}
        assert get_range("Mode_t", dd) == "0-2"


def _canonical_of(parser_mod, tmp_path, source, typedef_name):
    """Return the clang Type a typedef aliases, for range computation."""
    from clang import cindex

    src = tmp_path / "r.h"
    src.write_text(source, encoding="utf-8")
    tu = cindex.Index.create().parse(str(src), args=["-x", "c++"])
    found = {}

    def walk(c):
        if c.kind == cindex.CursorKind.TYPEDEF_DECL and c.spelling:
            found[c.spelling] = c.underlying_typedef_type
        for ch in c.get_children():
            walk(ch)

    walk(tu.cursor)
    return found[typedef_name]


class TestRangeFromClangType:
    """Ranges measured from the type, not guessed from its name."""

    @pytest.mark.parametrize("decl,name,expected", [
        ("typedef unsigned char U8;",          "U8",  "0-0xFF"),
        ("typedef unsigned short U16;",        "U16", "0-0xFFFF"),
        ("typedef unsigned int U32;",          "U32", "0-0xFFFFFFFF"),
        ("typedef unsigned long long U64;",    "U64", "0-0xFFFFFFFFFFFFFFFF"),
        ("typedef signed char S8;",            "S8",  "-0x80-0x7F"),
        ("typedef short S16;",                 "S16", "-0x8000-0x7FFF"),
        ("typedef int S32;",                   "S32", "-0x80000000-0x7FFFFFFF"),
        ("typedef long long S64;", "S64", "-0x8000000000000000-0x7FFFFFFFFFFFFFFF"),
        ("typedef bool B;",                    "B",   "0-1"),
    ])
    def test_builtin_ranges(self, parser_mod, tmp_path, decl, name, expected):
        ctype = _canonical_of(parser_mod, tmp_path, decl + "\n", name)
        assert parser_mod._range_from_clang_type(ctype) == expected

    def test_resolves_through_a_typedef_chain(self, parser_mod, tmp_path):
        """get_canonical() walks the whole chain, so no name lookup is needed."""
        ctype = _canonical_of(
            parser_mod, tmp_path,
            "typedef unsigned short Inner;\ntypedef Inner Middle;\ntypedef Middle Outer;\n",
            "Outer")
        assert parser_mod._range_from_clang_type(ctype) == "0-0xFFFF"

    @pytest.mark.parametrize("decl,name", [
        ("typedef struct { int a; } S;",       "S"),
        ("typedef enum { A_ = 0 } E;",         "E"),
        ("typedef int * P;",                   "P"),
        ("typedef float F;",                   "F"),
    ])
    def test_non_builtin_is_na(self, parser_mod, tmp_path, decl, name):
        """Structs/enums/pointers/floats are answered by their own entries, not here."""
        ctype = _canonical_of(parser_mod, tmp_path, decl + "\n", name)
        assert parser_mod._range_from_clang_type(ctype) == "NA"

    def test_none_is_na(self, parser_mod):
        assert parser_mod._range_from_clang_type(None) == "NA"


class TestRegisterBuiltinRange:
    """Seeding the dictionary with measured builtin ranges."""

    def test_registers_under_the_canonical_name(self, parser_mod, tmp_path):
        ctype = _canonical_of(parser_mod, tmp_path, "typedef unsigned char U8;\n", "U8")
        saved = dict(parser_mod.data_dictionary)
        parser_mod.data_dictionary.clear()
        try:
            parser_mod._register_builtin_range(ctype)
            # layer None = the global tier: a builtin's width is a property of the
            # target, not of a layer, so every layer may resolve against it.
            assert parser_mod.data_dictionary["unsigned char"] == {
                "kind": "primitive", "range": "0-0xFF", "layer": None}
            # NOT under the written alias — that would shadow the U8 typedef entry.
            assert "U8" not in parser_mod.data_dictionary
        finally:
            parser_mod.data_dictionary.clear()
            parser_mod.data_dictionary.update(saved)

    def test_never_shadows_a_project_type(self, parser_mod, tmp_path):
        ctype = _canonical_of(parser_mod, tmp_path, "typedef int Mine;\n", "Mine")
        saved = dict(parser_mod.data_dictionary)
        parser_mod.data_dictionary.clear()
        parser_mod.data_dictionary["int"] = {"kind": "struct", "qualifiedName": "int"}
        try:
            parser_mod._register_builtin_range(ctype)
            assert parser_mod.data_dictionary["int"]["kind"] == "struct"
        finally:
            parser_mod.data_dictionary.clear()
            parser_mod.data_dictionary.update(saved)

    def test_non_builtin_registers_nothing(self, parser_mod, tmp_path):
        ctype = _canonical_of(parser_mod, tmp_path, "typedef struct { int a; } S;\n", "S")
        saved = dict(parser_mod.data_dictionary)
        parser_mod.data_dictionary.clear()
        try:
            parser_mod._register_builtin_range(ctype)
            assert parser_mod.data_dictionary == {}
        finally:
            parser_mod.data_dictionary.clear()
            parser_mod.data_dictionary.update(saved)


class TestStructTypedefRangeIsNotDerivedFromTheName:
    """`_maybe_add_typedef_for_struct` names the struct itself as underlyingType, so
    deriving a range from it reads a range out of a type NAME: get_range_for_type
    matches its "size_t" substring rule against "Size_t" and stamps a 64-bit integer
    range on a {int width; int height;} struct."""

    def test_typedef_struct_entry_range_is_na(self, parser_mod, tmp_path):
        src = tmp_path / "s.h"
        src.write_text("typedef struct {\n int width;\n int height;\n} Size_t;\n",
                       encoding="utf-8")
        saved_base = parser_mod.MODULE_BASE_PATH
        saved_dd = dict(parser_mod.data_dictionary)
        parser_mod.MODULE_BASE_PATH = str(tmp_path)
        parser_mod.data_dictionary.clear()
        try:
            parser_mod._maybe_add_typedef_for_struct(
                "Size_t", "Size_t", {"file": "s.h", "line": 1}, "s.h")
            entries = [v for v in parser_mod.data_dictionary.values()
                       if v.get("kind") == "typedef"]
            assert entries, "no typedef entry was added"
            assert entries[0]["range"] == "NA"
        finally:
            parser_mod.MODULE_BASE_PATH = saved_base
            parser_mod.data_dictionary.clear()
            parser_mod.data_dictionary.update(saved_dd)
