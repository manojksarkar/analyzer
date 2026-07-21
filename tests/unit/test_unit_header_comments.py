"""Unit tests for comment stripping + multi-line initializer capture in the
unit header table (docx_exporter._build_unit_header_table).

Covers three reported issues:
  - comments must not appear in either column (declaration or value),
  - a `#define`'s value column shows the value without its trailing comment,
  - a multi-line array/struct initializer shows the real initializer in the
    value column, not a stray trailing comment.
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

import docx_exporter as dx  # noqa: E402


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
    rows = dx._build_unit_header_table(
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
    rows = dx._build_unit_header_table(
        unit_info, [], {}, globals_data, str(tmp_path), None, {}, {}, {}, set()
    )
    tbl = [r for r in rows if "tbl" in (r.get("declaration") or "")]
    assert tbl, "global tbl should be listed"
    info = tbl[0]["information"]
    # value column shows the real initializer, not the trailing comment
    assert "//" not in info and "pick" not in info
    assert "1" in info and "2" in info and "3" in info and "{" in info
