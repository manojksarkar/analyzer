"""Unit tests for src/utils.py — pure helper functions only."""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

import utils
from core.config import _strip_json_comments, _strip_trailing_commas
from utils import (
    safe_filename,
    short_name,
    scoped_name,
    get_range_for_type,
    get_range,
    init_component_mapping,
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
# scoped_name
# ---------------------------------------------------------------------------

class TestScopedName:
    def test_class_is_prefixed(self):
        assert scoped_name("MyClass::getValue", "MyClass") == "MyClass::getValue"

    def test_namespace_is_dropped(self):
        # The namespace only lengthens the cell; the CLASS is what disambiguates.
        assert scoped_name("pos::MyClass::getValue", "MyClass") == "MyClass::getValue"

    def test_nested_class_kept_whole(self):
        assert scoped_name("Outer::Inner::run", "Outer::Inner") == "Outer::Inner::run"

    def test_free_function_stays_bare(self):
        assert scoped_name("add", "") == "add"

    def test_namespaced_free_function_stays_bare(self):
        assert scoped_name("pos::add", "") == "add"

    def test_missing_class_falls_back_to_short_name(self):
        # Models parsed before className existed must render as they did before,
        # not half-qualified.
        assert scoped_name("MyClass::getValue") == "getValue"

    def test_same_short_name_different_classes_are_distinguishable(self):
        a = scoped_name("AddOperation::apply", "AddOperation")
        m = scoped_name("MultiplyOperation::apply", "MultiplyOperation")
        assert a == "AddOperation::apply"
        assert m == "MultiplyOperation::apply"
        assert a != m

    def test_empty(self):
        assert scoped_name("", "") == ""

    def test_none(self):
        assert scoped_name(None, None) == ""

    def test_class_without_base_does_not_dangle(self):
        assert scoped_name("", "MyClass") == ""

    def test_whitespace_class_treated_as_absent(self):
        assert scoped_name("MyClass::getValue", "   ") == "getValue"


# ---------------------------------------------------------------------------
# get_range_for_type
# ---------------------------------------------------------------------------

class TestGetRangeForType:
    @pytest.mark.parametrize("type_str,expected", [
        ("void",           "VOID"),
        ("bool",           "0-1"),  # matches the PRIMITIVES table (was NA — inconsistent)
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
        ("std::size_t",    "0-0xFFFFFFFFFFFFFFFF"),
        ("param_size_t",   "0-0xFFFFFFFFFFFFFFFF"),
        ("SomeStruct*",    "NA"),
        ("",               "NA"),
    ])
    def test_known_types(self, type_str, expected):
        assert get_range_for_type(type_str) == expected

    def test_const_qualified(self):
        assert get_range_for_type("const uint8_t") == "0-0xFF"

    def test_void_pointer_is_not_void(self):
        assert get_range_for_type("void*") != "VOID"

    @pytest.mark.parametrize("type_str", [
        "Size_t",        # Sample: a {int width; int height;} struct
        "BufSize_t",
        "PageSize_t",
        "my_size_type",
        "size_t *",      # a pointer is not the integer
    ])
    def test_name_containing_size_t_is_not_treated_as_size_t(self, type_str):
        """This maps known primitives — it must not infer a type from its spelling.
        Anything unrecognised is "NA" and gets answered from the data dictionary."""
        assert get_range_for_type(type_str) == "NA"

    @pytest.mark.parametrize("type_str", ["UINT8_T", "Int", "UInt32_t", "VOID"])
    def test_matching_is_case_sensitive(self, type_str):
        """C++ is case-sensitive; a project typedef that only resembles a primitive
        resolves through the data dictionary, not by spelling."""
        assert get_range_for_type(type_str) == "NA"


# ---------------------------------------------------------------------------
# make_unit_key / init_component_mapping
# ---------------------------------------------------------------------------

class TestMakeUnitKey:
    def setup_method(self):
        """Reset component mapping to a known state before each test."""
        init_component_mapping({
            "layers": {
                "Layer1": {
                    "path": "Layer1",
                    "groups": {
                        "Sample": {
                            "Core": "Sample/Core",
                            "Lib":  "Sample/Lib",
                        }
                    }
                }
            }
        })

    def teardown_method(self):
        """Restore default mapping after each test."""
        init_component_mapping(utils._CONFIG_CACHE)

    def test_resolves_component_from_path(self):
        key = make_unit_key("Layer1/Sample/Core/core.cpp")
        assert key.startswith("Core|")

    def test_unit_name_is_filename_without_extension(self):
        key = make_unit_key("Layer1/Sample/Core/core.cpp")
        assert key == "Core|core"

    def test_unknown_path_returns_unknown(self):
        key = make_unit_key("Unknown/something.cpp")
        assert key.startswith("unknown|")

    def test_empty_path(self):
        key = make_unit_key("")
        assert "unknown" in key


class TestGetRange:
    def test_empty_type_returns_na(self):
        assert get_range("", {}) == "NA"

    def test_none_type_returns_na(self):
        assert get_range(None, {}) == "NA"

    def test_empty_dict_falls_back_to_get_range_for_type(self):
        assert get_range("uint8_t", {}) == "0-0xFF"

    def test_direct_key_lookup_returns_range(self):
        dd = {"Speed": {"range": "0-255"}}
        assert get_range("Speed", dd) == "0-255"

    def test_direct_key_lookup_case_insensitive(self):
        dd = {"speed": {"range": "0-255"}}
        assert get_range("Speed", dd) == "0-255"

    def test_qualified_name_lookup(self):
        dd = {"some_key": {"qualifiedName": "MyModule::Speed", "range": "0-100"}}
        assert get_range("MyModule::Speed", dd) == "0-100"

    def test_typedef_resolves_underlying_type(self):
        dd = {"Speed_t": {"kind": "typedef", "underlyingType": "uint8_t"}}
        assert get_range("Speed_t", dd) == "0-0xFF"

    def test_typedef_chain_resolved(self):
        dd = {
            "Outer": {"kind": "typedef", "underlyingType": "Inner"},
            "Inner": {"kind": "typedef", "underlyingType": "uint16_t"},
        }
        assert get_range("Outer", dd) == "0-0xFFFF"

    def test_typedef_with_no_underlying_returns_na(self):
        dd = {"MyType": {"kind": "typedef", "underlyingType": ""}}
        assert get_range("MyType", dd) == "NA"

    def test_typedef_depth_guard(self):
        """Circular typedef chain must not recurse infinitely."""
        dd = {
            "A": {"kind": "typedef", "underlyingType": "B"},
            "B": {"kind": "typedef", "underlyingType": "A"},
        }
        result = get_range("A", dd)
        assert result == "NA"

    def test_entry_with_range_preferred_over_typedef(self):
        dd = {"MyType": {"kind": "typedef", "underlyingType": "uint8_t", "range": "0-10"}}
        assert get_range("MyType", dd) == "0-10"

    def test_pointer_type_strips_star(self):
        dd = {"MyStruct": {"range": "0-100"}}
        assert get_range("MyStruct*", dd) == "0-100"

    def test_ref_type_strips_ampersand(self):
        dd = {"MyStruct": {"range": "0-100"}}
        assert get_range("MyStruct&", dd) == "0-100"

    def test_const_qualified_strips_const(self):
        dd = {"Speed": {"range": "0-255"}}
        assert get_range("const Speed", dd) == "0-255"

    def test_unknown_type_not_in_dict_returns_na(self):
        assert get_range("SomeUnknownType", {"Other": {"range": "0-1"}}) == "NA"


class TestGetRangeBakedNA:
    """A typedef's own `range` is computed at parse time by get_range_for_type(), which
    never consults the data dictionary — so an alias of a project type is stored as
    "NA". These lock in that a baked "NA" does not block alias resolution, while an
    entry that really has no better answer still reports "NA"."""

    def test_baked_na_typedef_resolves_to_underlying(self):
        """The external-CSV case: the alias was parsed as NA, the base type got a range
        from the CSV — the alias must pick it up."""
        dd = {
            "MotorSpeed_t": {"kind": "typedef", "underlyingType": "Foo_t", "range": "NA"},
            "Foo_t": {"kind": "typedef", "underlyingType": "", "range": "0-3000"},
        }
        assert get_range("MotorSpeed_t", dd) == "0-3000"

    def test_baked_na_chain_resolves_through_two_aliases(self):
        dd = {
            "Outer": {"kind": "typedef", "underlyingType": "Inner", "range": "NA"},
            "Inner": {"kind": "typedef", "underlyingType": "uint16_t", "range": "NA"},
        }
        assert get_range("Outer", dd) == "0-0xFFFF"

    def test_real_range_still_wins_over_underlying(self):
        dd = {
            "MyType": {"kind": "typedef", "underlyingType": "uint8_t", "range": "0-10"},
        }
        assert get_range("MyType", dd) == "0-10"

    def test_unresolvable_alias_still_reports_na(self):
        dd = {"MyType": {"kind": "typedef", "underlyingType": "Mystery", "range": "NA"}}
        assert get_range("MyType", dd) == "NA"

    def test_self_referential_typedef_returns_na(self):
        """`typedef struct { ... } Name;` makes the parser store underlyingType == the
        type's own name. Resolving it must terminate, not recurse."""
        dd = {"UINT8": {"kind": "typedef", "name": "UINT8", "qualifiedName": "UINT8",
                        "underlyingType": "UINT8", "range": "NA"}}
        assert get_range("UINT8", dd) == "NA"

    def test_self_referential_typedef_uses_no_depth(self):
        """The self-reference guard must not consume the depth budget, or a legitimate
        alias pointing at a self-referential type would stop resolving."""
        dd = {
            "Alias": {"kind": "typedef", "underlyingType": "Self", "range": "NA"},
            "Self": {"kind": "typedef", "qualifiedName": "Self",
                     "underlyingType": "Self", "range": "NA"},
        }
        assert get_range("Alias", dd) == "NA"

    def test_struct_na_not_overridden_by_sibling_alias_entry(self):
        """Regression (Sample `Size_t`): the parser emits both `Name` (the struct) and
        `typedef@Name:file:line`, which share a qualifiedName. The sibling's range is
        baked by a fuzzy get_range_for_type() substring match ("size_t" in "Size_t"),
        so it must never override the struct actually asked about."""
        dd = {
            "Size_t": {"kind": "struct", "name": "Size_t", "qualifiedName": "Size_t",
                       "range": "NA"},
            "typedef@Size_t:Layer1/Types/PointRect.h:16": {
                "kind": "typedef", "name": "Size_t", "qualifiedName": "Size_t",
                "underlyingType": "Size_t", "range": "0-0xFFFFFFFFFFFFFFFF"},
        }
        assert get_range("Size_t", dd) == "NA"

    def test_struct_with_csv_supplied_range_wins(self):
        """External CSV setting a real range on a struct is still honoured."""
        dd = {"GG": {"kind": "struct", "qualifiedName": "GG", "range": "0-100"}}
        assert get_range("GG", dd) == "0-100"

    def test_missing_range_key_still_resolves_underlying(self):
        """Entries written before ranges were baked have no `range` key at all."""
        dd = {
            "Legacy_t": {"kind": "typedef", "underlyingType": "uint32_t"},
        }
        assert get_range("Legacy_t", dd) == "0-0xFFFFFFFF"

    def test_define_entry_without_range_falls_back_to_primitive_table(self):
        """`kind=define` entries carry no `range` key; a type sharing that name must
        still fall through to the built-in table."""
        dd = {"uint8_t": {"kind": "define", "name": "uint8_t", "value": "1"}}
        assert get_range("uint8_t", dd) == "0-0xFF"

    def test_void_primitive_entry_preserved(self):
        dd = {"void": {"kind": "primitive", "range": "VOID"}}
        assert get_range("void", dd) == "VOID"

    def test_pointer_to_na_alias_resolves_via_underlying(self):
        dd = {
            "Handle_t": {"kind": "typedef", "underlyingType": "uint32_t", "range": "NA"},
        }
        assert get_range("Handle_t *", dd) == "0-0xFFFFFFFF"

    def test_qualified_name_alias_with_baked_na(self):
        dd = {
            "k1": {"kind": "typedef", "qualifiedName": "Mod::Speed_t",
                   "underlyingType": "uint16_t", "range": "NA"},
        }
        assert get_range("Mod::Speed_t", dd) == "0-0xFFFF"
