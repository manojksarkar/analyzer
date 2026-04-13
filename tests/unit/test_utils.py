"""Unit tests for src/utils.py — pure helper functions only."""
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

import utils
from utils import (
    _strip_json_comments,
    _strip_trailing_commas,
    safe_filename,
    short_name,
    get_range_for_type,
    init_module_mapping,
    make_unit_key,
)


# ---------------------------------------------------------------------------
# _strip_json_comments
# ---------------------------------------------------------------------------

class TestStripJsonComments:
    def test_line_comment_removed(self):
        assert _strip_json_comments('{"a": 1 // comment\n}') == '{"a": 1 \n}'

    def test_block_comment_removed(self):
        assert _strip_json_comments('{"a": /* note */ 1}') == '{"a":  1}'

    def test_url_in_string_preserved(self):
        src = '{"url": "http://example.com"}'
        assert _strip_json_comments(src) == src

    def test_comment_marker_in_string_preserved(self):
        src = '{"key": "value // not a comment"}'
        assert _strip_json_comments(src) == src

    def test_no_comments_unchanged(self):
        src = '{"a": 1, "b": 2}'
        assert _strip_json_comments(src) == src

    def test_multiline_block_comment(self):
        src = '{"a": /* line1\nline2 */ 1}'
        assert _strip_json_comments(src) == '{"a":  1}'

    def test_empty_string(self):
        assert _strip_json_comments("") == ""


# ---------------------------------------------------------------------------
# _strip_trailing_commas
# ---------------------------------------------------------------------------

class TestStripTrailingCommas:
    def test_trailing_comma_before_brace(self):
        assert _strip_trailing_commas('{"a": 1,}') == '{"a": 1}'

    def test_trailing_comma_before_bracket(self):
        assert _strip_trailing_commas('[1, 2,]') == '[1, 2]'

    def test_comma_in_string_preserved(self):
        src = '{"key": "a,}"}'
        assert _strip_trailing_commas(src) == src

    def test_non_trailing_comma_preserved(self):
        src = '{"a": 1, "b": 2}'
        assert _strip_trailing_commas(src) == src

    def test_nested_trailing_commas(self):
        result = _strip_trailing_commas('{"a": [1, 2,], "b": 3,}')
        assert result == '{"a": [1, 2], "b": 3}'

    def test_empty_string(self):
        assert _strip_trailing_commas("") == ""


# ---------------------------------------------------------------------------
# load_config — comments + trailing commas + local override
# ---------------------------------------------------------------------------

class TestLoadConfig:
    def test_loads_json_with_comments(self, tmp_path):
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        (cfg_dir / "config.json").write_text('{\n  "key": "value" // comment\n}\n')
        result = utils.load_config(str(tmp_path))
        assert result["key"] == "value"

    def test_loads_json_with_trailing_comma(self, tmp_path):
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        (cfg_dir / "config.json").write_text('{"a": 1,}')
        result = utils.load_config(str(tmp_path))
        assert result["a"] == 1

    def test_local_override_merges(self, tmp_path):
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        (cfg_dir / "config.json").write_text('{"a": 1, "b": 2}')
        (cfg_dir / "config.local.json").write_text('{"b": 99}')
        result = utils.load_config(str(tmp_path))
        assert result["a"] == 1
        assert result["b"] == 99

    def test_missing_config_returns_empty(self, tmp_path):
        result = utils.load_config(str(tmp_path))
        assert result == {}


# ---------------------------------------------------------------------------
# safe_filename
# ---------------------------------------------------------------------------

class TestSafeFilename:
    def test_pipe_replaced(self):
        assert safe_filename("Core|Core") == "Core_Core"

    def test_slashes_replaced(self):
        assert safe_filename("a/b\\c") == "a_b_c"

    def test_safe_string_unchanged(self):
        assert safe_filename("CoreCore") == "CoreCore"

    def test_none_returns_empty(self):
        assert safe_filename(None) == ""

    def test_special_chars_replaced(self):
        result = safe_filename("a<b>c:d")
        assert "<" not in result
        assert ">" not in result
        assert ":" not in result


# ---------------------------------------------------------------------------
# short_name
# ---------------------------------------------------------------------------

class TestShortName:
    def test_qualified_name(self):
        assert short_name("MyClass::getValue") == "getValue"

    def test_deeply_nested(self):
        assert short_name("Ns::Class::method") == "method"

    def test_plain_name(self):
        assert short_name("add") == "add"

    def test_empty(self):
        assert short_name("") == ""

    def test_none(self):
        assert short_name(None) == ""


# ---------------------------------------------------------------------------
# get_range_for_type
# ---------------------------------------------------------------------------

class TestGetRangeForType:
    @pytest.mark.parametrize("type_str,expected", [
        ("void",           "VOID"),
        ("bool",           "NA"),   # bool falls through to NA (not in primitives fast-path)
        ("int",            "-0x80000000-0x7FFFFFFF"),
        ("unsigned int",   "0-0xFFFFFFFF"),
        ("uint8_t",        "0-0xFF"),
        ("uint16_t",       "0-0xFFFF"),
        ("uint32_t",       "0-0xFFFFFFFF"),
        ("int8_t",         "-0x80-0x7F"),
        ("int16_t",        "-0x8000-0x7FFF"),
        ("int32_t",        "-0x80000000-0x7FFFFFFF"),
        ("float",          "NA"),   # float falls through to NA in fast-path
        ("std::uint8_t",   "0-0xFF"),
        ("size_t",         "0-0xFFFFFFFFFFFFFFFF"),
        ("SomeStruct*",    "NA"),
        ("",               "NA"),
    ])
    def test_known_types(self, type_str, expected):
        assert get_range_for_type(type_str) == expected

    def test_const_qualified(self):
        assert get_range_for_type("const uint8_t") == "0-0xFF"

    def test_void_pointer_is_not_void(self):
        assert get_range_for_type("void*") != "VOID"


# ---------------------------------------------------------------------------
# make_unit_key / init_module_mapping
# ---------------------------------------------------------------------------

class TestMakeUnitKey:
    def setup_method(self):
        """Reset module mapping to a known state before each test."""
        init_module_mapping({
            "modulesGroups": {
                "Sample": {
                    "Core": "Sample/Core",
                    "Lib":  "Sample/Lib",
                }
            }
        })

    def teardown_method(self):
        """Restore default mapping after each test."""
        init_module_mapping(utils._CONFIG_CACHE)

    def test_resolves_module_from_path(self):
        key = make_unit_key("Sample/Core/core.cpp")
        assert key.startswith("Core|")

    def test_unit_name_is_filename_without_extension(self):
        key = make_unit_key("Sample/Core/core.cpp")
        assert key == "Core|core"

    def test_unknown_path_returns_unknown(self):
        key = make_unit_key("Unknown/something.cpp")
        assert key.startswith("unknown|")

    def test_empty_path(self):
        key = make_unit_key("")
        assert "unknown" in key
