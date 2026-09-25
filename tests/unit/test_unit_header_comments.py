"""Unit tests for comment stripping + multi-line initializer capture in the
unit header table (views/unit_headers.py::build_rows).

Covers three reported issues:
  - comments must not appear in either column (declaration or value),
  - a `#define`'s value column shows the value without its trailing comment,
  - a multi-line array/struct initializer shows the real initializer in the
    value column, not a stray trailing comment,
  - a declaration is read until its braces close -- no 60-line cut, and a brace
    in a comment or a literal does not count.
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from views import unit_headers as dx  # noqa: E402


class TestStripComments:
    def test_line_comment_removed(self):
        assert dx._strip_comments("#define FOO (24) //some comment") == "#define FOO (24)"

    def test_value_line_comment_removed(self):
        assert dx._strip_comments("(24) //some comment") == "(24)"

    def test_block_comment_removed(self):
        assert dx._strip_comments("int g = 5; /* block\n spanning */") == "int g = 5;"

    def test_mid_declaration_block_comment_removed(self):
        out = dx._strip_comments("enum { eA, /* mid */ eB }")
        assert "/*" not in out and "mid" not in out and "eA" in out and "eB" in out

    def test_string_literal_preserved(self):
        # // and /* */ *inside a string* are not comments and must survive; the
        # real trailing comment is removed.
        assert dx._strip_comments('#define MSG "a//b/*c*/"  // real') == '#define MSG "a//b/*c*/"'

    def test_multiline_declaration_keeps_shape(self):
        out = dx._strip_comments("const T v[N] = // pick\n{\n  a,\n  b\n}")
        assert out == "const T v[N] =\n{\n  a,\n  b\n}"

    def test_empty(self):
        assert dx._strip_comments("") == ""


# --- integration: a `#define` with a trailing comment (filesystem-free) --------

_DD_DEFINE = {
    "FOO@Comp/U.cpp:2": {
        "kind": "define", "name": "FOO", "qualifiedName": "FOO",
        "value": "7 // seven", "text": "#define FOO 7 // seven",
        "location": {"file": "Comp/U.cpp", "line": 2},
    },
}


def test_define_column_has_no_comment():
    unit_info = {"path": "Comp/U", "fileName": "U.cpp",
                 "functionIds": [], "globalVariableIds": []}
    rows = dx.build_rows(
        unit_info, [], _DD_DEFINE, {}, "", None, {}, {}, {}, {"Comp/U"}
    )
    foo = [r for r in rows if "FOO" in (r.get("declaration") or "")]
    assert foo, "own #define FOO should be listed"
    r = foo[0]
    assert "//" not in r["declaration"] and "seven" not in r["declaration"]
    assert r["information"] == "7"


# --- integration: a multi-line array initializer (needs a real file) ----------

def test_global_multiline_initializer_value(tmp_path):
    src = tmp_path / "U.cpp"
    src.write_text(
        "const int tbl[3] = // pick one\n"
        "{\n"
        "    1,\n"
        "    2,\n"
        "    3\n"
        "};\n",
        encoding="utf-8",
    )
    globals_data = {
        "g1": {
            "name": "tbl", "qualifiedName": "tbl", "visibility": "public",
            "value": "// pick one",  # the buggy single-line parser value
            "location": {"file": "U.cpp", "line": 1},
        },
    }
    unit_info = {"path": "Comp/U", "fileName": "U.cpp",
                 "functionIds": [], "globalVariableIds": ["g1"]}
    rows = dx.build_rows(
        unit_info, [], {}, globals_data, str(tmp_path), None, {}, {}, {}, set()
    )
    tbl = [r for r in rows if "tbl" in (r.get("declaration") or "")]
    assert tbl, "global tbl should be listed"
    info = tbl[0]["information"]
    # value column shows the real initializer, not the trailing comment
    assert "//" not in info and "pick" not in info
    assert "1" in info and "2" in info and "3" in info and "{" in info


# --- a declaration is read until its braces close (needs a real file) ---------
# The reader used to stop after 60 source lines, comments and blank lines included, so a
# commented class lost its last members and its `};`. Fixture: Access/LongDecls.

def _record_rows(tmp_path, text, name, kind="class"):
    (tmp_path / "U.h").write_text(text, encoding="utf-8")
    dd = {name: {"kind": kind, "name": name, "location": {"file": "U.h", "line": 1}}}
    unit_info = {"path": "U", "fileName": "U.cpp",
                 "functionIds": [], "globalVariableIds": []}
    return dx.build_rows(unit_info, [], dd, {}, str(tmp_path), None, {}, {}, {}, set())


def test_a_class_over_60_lines_is_listed_whole(tmp_path):
    body = []
    for n in range(30):
        body += ["", f"    // method {n}", f"    static int m{n}();"]
    text = "\n".join(["class Big {", "public:", *body, "    static int last();", "};", ""])
    assert len(text.splitlines()) > 60
    cell = _record_rows(tmp_path, text, "Big")[0]["declaration"]
    assert "static int m29();" in cell and "static int last();" in cell
    assert cell.endswith("};")


def test_an_initializer_over_60_lines_is_listed_whole(tmp_path):
    entries = ",\n".join(f"    {n}" for n in range(64))
    (tmp_path / "U.cpp").write_text(
        "const int tbl[64] = {\n" + entries + "\n};\n", encoding="utf-8")
    globals_data = {"g1": {"name": "tbl", "qualifiedName": "tbl",
                           "location": {"file": "U.cpp", "line": 1}}}
    unit_info = {"path": "U", "fileName": "U.cpp",
                 "functionIds": [], "globalVariableIds": ["g1"]}
    row = dx.build_rows(unit_info, [], {}, globals_data, str(tmp_path), None,
                        {}, {}, {}, set())[0]
    assert row["declaration"].endswith("};")
    assert row["information"].rstrip().endswith("63\n}")


@pytest.mark.parametrize("member", [
    "    int first;  // was: if (first) {",
    "    int first;  /* was: if (first) {\n                   end of note */",
    "    char first = '{';",
    '    const char *first = "{";',
])
def test_a_brace_in_a_comment_or_literal_does_not_hold_the_record_open(tmp_path, member):
    text = ("struct S {\n" + member + "\n    int second;\n};\n\n"
            "typedef unsigned int After_t;\n")
    cell = _record_rows(tmp_path, text, "S", kind="struct")[0]["declaration"]
    assert "int second;" in cell and cell.endswith("};")
    assert "After_t" not in cell


def test_a_declaration_that_never_closes_stops_at_the_limit_and_says_so(tmp_path, monkeypatch):
    src = tmp_path / "U.h"
    src.write_text("struct S {\n" + "    int x;\n" * 20, encoding="utf-8")
    logged = []
    monkeypatch.setattr(dx, "_MAX_DECL_LINES", 5)
    monkeypatch.setattr(dx, "log", lambda msg, *a, **kw: logged.append((msg, kw)))
    snippet = dx._read_decl_snippet(str(src), 1, kind="struct")
    assert len(snippet.splitlines()) == 5
    assert len(logged) == 1 and logged[0][1].get("err") is True
    assert "never closed" in logged[0][0]


@pytest.mark.parametrize("line, in_block, code, still_open", [
    ("int a; // {", False, "int a; ", False),
    ("x /* { */ y", False, "x  y", False),
    ("a /* {", False, "a ", True),
    ("} */ b", True, " b", False),
    ("char c = '}';", False, "char c = ;", False),
    ('s = "{\\"}";', False, "s = ;", False),
    ("n = 1'000; {", False, "n = 1'000; {", False),
])
def test_code_only(line, in_block, code, still_open):
    assert dx._code_only(line, in_block) == (code, still_open)


# --- a brace inside a literal in an INLINE BODY ---------------------------------
# The reader gets the whole record, but the step that lists an inline method as its
# declaration (_declarations_only) counted braces on the raw line: the `{` in "{" read as a
# body still open, and the members after it were dropped as the rest of that body.

@pytest.mark.parametrize("body", [
    '{ return "{"; }',
    "{ return '{'; }",
    '{ return "}"; }',
    "{ return '}'; }",
    '{ return "{{"; }',
    '{ return "\\"{"; }',          # an escaped quote before the brace
])
def test_a_brace_in_a_literal_in_an_inline_body_keeps_the_members_after_it(body):
    decl = "class C {\npublic:\n    int mark(void) const " + body + "\n    int after;\n};"
    assert dx._declarations_only(decl).split("\n") == [
        "class C {", "public:", "    int mark(void) const;", "    int after;", "};"]


def test_a_literal_brace_in_a_multi_line_body_leaves_no_stray_brace():
    """`return '}';` used to close the body one line early, so its real `}` was listed as a
    member of the class."""
    decl = ("class C {\npublic:\n    char f(void) {\n        return '}';\n    }\n"
            "    int after;\n};")
    assert dx._declarations_only(decl).split("\n") == [
        "class C {", "public:", "    char f(void);", "    int after;", "};"]


def test_a_brace_in_a_default_argument_is_not_taken_for_the_body():
    decl = 'class C {\npublic:\n    void log(const char* f = "{") { go(); }\n    int after;\n};'
    assert dx._declarations_only(decl).split("\n") == [
        "class C {", "public:", '    void log(const char* f = "{");', "    int after;", "};"]


def test_an_inline_body_without_literals_is_reduced_as_before():
    decl = ("class C {\npublic:\n    int f(void) {\n        if (x) { return 1; }\n"
            "        return 0;\n    }\n    int g(void) const { return 2; }\n    int after;\n};")
    assert dx._declarations_only(decl).split("\n") == [
        "class C {", "public:", "    int f(void);", "    int g(void) const;", "    int after;",
        "};"]


# --- the real fixture: Diag/LongDeclShapes.h -----------------------------------
# Every kind the table lists, past 60 lines, plus the brace-in-noise cases and the 60/61
# boundary. Read from the real file through build_rows, so the fixture cannot drift from
# the test.

SHAPES_DIR = os.path.join(PROJECT_ROOT, "SampleCppProject", "Layer1", "Diag")
SHAPES_H = os.path.join(SHAPES_DIR, "LongDeclShapes.h")


def _shape_rows():
    import re
    with open(SHAPES_H, encoding="utf-8") as fh:
        src = fh.read().splitlines()
    dd = {}
    for n, text in enumerate(src, 1):
        m = re.match(r"^(class|struct|union|enum) (\w+) \{$", text)
        if m:
            dd[m.group(2)] = {"kind": m.group(1), "name": m.group(2),
                              "location": {"file": "LongDeclShapes.h", "line": n}}
        elif text == "typedef struct {":
            dd["LongPacket_t"] = {"kind": "typedef", "name": "LongPacket_t",
                                  "location": {"file": "LongDeclShapes.h", "line": n}}
    unit_info = {"path": "LongDeclShapes", "fileName": "LongDeclShapes.cpp",
                 "functionIds": [], "globalVariableIds": []}
    rows = dx.build_rows(unit_info, [], dd, {}, SHAPES_DIR, None, {}, {}, {}, set())
    by_name = {}
    for r in rows:
        head = r["declaration"].split("\n")[0]
        name = "LongPacket_t" if head == "typedef struct {" else head.split()[1]
        by_name[name] = r["declaration"].split("\n")
    return by_name


@pytest.mark.parametrize("name, n_lines, last_member, closing", [
    ("LongRegisterBank",   70, "    int lastRegister;",         "};"),
    ("LongFrame",          66, "    unsigned char lastByte;",   "};"),
    ("LongWord",           63, "    long lastView;",            "};"),
    ("LongOpcode",         68, "    OP_LAST = 99",              "};"),
    ("LongPacket_t",       64, "    unsigned short lastWord;",  "} LongPacket_t;"),
    ("BraceInComment",      5, "    int afterBrace;",           "};"),   # comment line stripped
    ("OpenBraceInComment",  4, "    int onlyMember;",           "};"),   # comment line stripped
    ("BraceInString",       7, "    int tail;",                 "};"),
    ("Exactly60",          60, "    int s56;",                  "};"),   # control: was whole
    ("Exactly61",          61, "    int s57;",                  "};"),
])
def test_every_long_declaration_is_listed_whole(name, n_lines, last_member, closing):
    cell = _shape_rows()[name]
    assert cell[-2:] == [last_member, closing], name
    assert len(cell) == n_lines, name


def test_the_fixture_lists_each_type_once_and_nothing_else():
    assert sorted(_shape_rows()) == sorted([
        "LongRegisterBank", "LongFrame", "LongWord", "LongOpcode", "LongPacket_t",
        "BraceInComment", "OpenBraceInComment", "BraceInString", "Exactly60", "Exactly61"])


def test_the_long_class_keeps_its_inline_method_as_a_declaration():
    cell = _shape_rows()["LongRegisterBank"]
    assert "    int width(void) const;" in cell
    assert not any("return 32" in ln for ln in cell)


def test_braces_in_literals_keep_every_member():
    assert _shape_rows()["BraceInString"] == [
        "class BraceInString {", "public:",
        "    const char* openMark(void) const;", "    int afterOpen;",
        "    char closeMark(void) const;", "    int tail;", "};"]
