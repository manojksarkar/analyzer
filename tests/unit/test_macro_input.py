"""Unit tests for core/macro_input.py — every accepted macro-input shape.

The reader replaces a CSV-only path, so the legacy 2-column form must keep its
exact behaviour (`ne` skip, empty value → bare define) while the JSON shapes —
toolchain dump, flat map, list, per-layer nested — land on the same rules.
"""
import json
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from core.macro_input import (  # noqa: E402
    GLOBAL_SCOPE,
    MacroInputError,
    args_for_scope,
    find_conflicts,
    load_macro_defs,
    merge_macro_defs,
    normalize_scoped_args,
    scoped_args,
    to_clang_args,
)


def _entry(**over):
    base = {
        "name": "X", "raw_value": "", "expanded_value": "", "computed_value": None,
        "is_fully_resolved": False, "dependency_chain": [], "note": None,
    }
    base.update(over)
    return base


def _dump(entries, cu="fcore", **meta):
    metadata = {"toolchain": "armclang", "macro_source": "fromelf_text",
                "total_macros": len(entries), "fully_resolved": 0}
    metadata.update(meta)
    return {"metadata": metadata, "macros_by_cu": {cu: entries}}


def _write(tmp_path, name, payload):
    p = tmp_path / name
    p.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    return str(p)


class TestToolchainDump:
    def test_resolved_macro_uses_computed_value(self, tmp_path):
        path = _write(tmp_path, "m.json", _dump({
            "MAX_LUN_COUNT": _entry(name="MAX_LUN_COUNT", raw_value="(8)", expanded_value="(8)",
                                    computed_value=8, is_fully_resolved=True),
        }))
        defs, _ = load_macro_defs(path)
        assert defs[GLOBAL_SCOPE] == {"MAX_LUN_COUNT": "8"}

    def test_computed_value_wins_over_expression_text(self, tmp_path):
        """(1 << SECTOR_SHIFT) only compiles if SECTOR_SHIFT is defined too; 4096 always does."""
        path = _write(tmp_path, "m.json", _dump({
            "BUFFER_SIZE": _entry(name="BUFFER_SIZE", raw_value="(1 << SECTOR_SHIFT)",
                                  expanded_value="(1 << 12)", computed_value=4096,
                                  is_fully_resolved=True),
        }))
        defs, report = load_macro_defs(path)
        assert defs[GLOBAL_SCOPE] == {"BUFFER_SIZE": "4096"}
        assert report.unresolved == 0

    def test_unresolved_macro_falls_back_to_expanded_text(self, tmp_path):
        path = _write(tmp_path, "m.json", _dump({
            "FTL_MAP_BASE": _entry(name="FTL_MAP_BASE", raw_value="(DRAM_BASE + 0x1000)",
                                   expanded_value="(DRAM_BASE + 0x1000)",
                                   dependency_chain=["DRAM_BASE"]),
        }))
        defs, report = load_macro_defs(path)
        assert defs[GLOBAL_SCOPE] == {"FTL_MAP_BASE": "(DRAM_BASE + 0x1000)"}
        assert report.unresolved == 1
        assert report.unresolved_names == ["FTL_MAP_BASE"]
        assert report.text_valued == 0

    def test_string_value_is_text_valued_not_flagged_as_unresolved(self, tmp_path):
        """A string/identifier has no dependency_chain — nothing to chase, so it
        must not be reported alongside macros that really do need other macros."""
        path = _write(tmp_path, "m.json", _dump({
            "FW_VERSION": _entry(name="FW_VERSION", raw_value='"UFS 3.1"',
                                 expanded_value='"UFS 3.1"'),
            "ALIAS_UINT": _entry(name="ALIAS_UINT", raw_value="unsigned int",
                                 expanded_value="unsigned int"),
            "LOG_LEVEL": _entry(name="LOG_LEVEL", raw_value="(VERBOSE_BASE + 2)",
                                expanded_value="(VERBOSE_BASE + 2)",
                                dependency_chain=["VERBOSE_BASE"]),
        }))
        defs, report = load_macro_defs(path)
        assert defs[GLOBAL_SCOPE] == {
            "FW_VERSION": '"UFS 3.1"', "ALIAS_UINT": "unsigned int",
            "LOG_LEVEL": "(VERBOSE_BASE + 2)"}
        assert report.unresolved == 1
        assert report.unresolved_names == ["LOG_LEVEL"]
        assert report.text_valued == 2
        joined = " ".join(report.lines())
        assert "FW_VERSION" not in joined
        assert "2 non-numeric value(s)" in joined

    def test_unresolved_falls_back_to_raw_when_expanded_is_empty(self, tmp_path):
        path = _write(tmp_path, "m.json", _dump({
            "A": _entry(name="A", raw_value="(1 + B)", expanded_value=""),
        }))
        defs, _ = load_macro_defs(path)
        assert defs[GLOBAL_SCOPE] == {"A": "(1 + B)"}

    def test_valueless_macro_becomes_a_bare_define(self, tmp_path):
        path = _write(tmp_path, "m.json", _dump({
            "ENABLE_DIAG": _entry(name="ENABLE_DIAG", is_fully_resolved=True),
        }))
        defs, report = load_macro_defs(path)
        assert defs[GLOBAL_SCOPE] == {"ENABLE_DIAG": None}
        assert to_clang_args(defs[GLOBAL_SCOPE]) == ["-DENABLE_DIAG"]
        assert report.unresolved == 0

    def test_function_like_macro_is_skipped(self, tmp_path):
        path = _write(tmp_path, "m.json", _dump({
            "MIN(a,b)": _entry(name="MIN(a,b)", raw_value="((a)<(b)?(a):(b))"),
            "KEEP": _entry(name="KEEP", computed_value=1, is_fully_resolved=True),
        }))
        defs, report = load_macro_defs(path)
        assert defs[GLOBAL_SCOPE] == {"KEEP": "1"}
        assert report.skipped_function_like == 1

    def test_ne_value_is_skipped(self, tmp_path):
        path = _write(tmp_path, "m.json", _dump({
            "NOT_EXPORTED": _entry(name="NOT_EXPORTED", raw_value="NE"),
            "KEEP": _entry(name="KEEP", computed_value=1, is_fully_resolved=True),
        }))
        defs, report = load_macro_defs(path)
        assert defs[GLOBAL_SCOPE] == {"KEEP": "1"}
        assert report.skipped_ne == 1

    def test_single_cu_lands_on_the_global_scope(self, tmp_path):
        path = _write(tmp_path, "m.json", _dump({"A": _entry(computed_value=1, is_fully_resolved=True)}))
        defs, report = load_macro_defs(path)
        assert list(defs) == [GLOBAL_SCOPE]
        assert report.kind == "toolchain"
        assert report.toolchain == "armclang"

    def test_multiple_cus_map_to_layers(self, tmp_path):
        payload = {"metadata": {"total_macros": 2},
                   "macros_by_cu": {
                       "fcore": {"A": _entry(computed_value=1, is_fully_resolved=True)},
                       "hil": {"B": _entry(computed_value=2, is_fully_resolved=True)}}}
        path = _write(tmp_path, "m.json", payload)
        defs, report = load_macro_defs(path, scope_map={"fcore": "Layer1", "hil": "Layer2"})
        assert defs == {"Layer1": {"A": "1"}, "Layer2": {"B": "2"}}
        assert report.warnings == []

    def test_unmapped_cu_falls_back_to_global_with_a_warning(self, tmp_path):
        payload = {"metadata": {"total_macros": 2},
                   "macros_by_cu": {
                       "fcore": {"A": _entry(computed_value=1, is_fully_resolved=True)},
                       "mystery": {"B": _entry(computed_value=2, is_fully_resolved=True)}}}
        path = _write(tmp_path, "m.json", payload)
        defs, report = load_macro_defs(path, scope_map={"fcore": "Layer1"})
        assert defs == {"Layer1": {"A": "1"}, GLOBAL_SCOPE: {"B": "2"}}
        assert any("mystery" in w for w in report.warnings)

    def test_declared_total_mismatch_warns(self, tmp_path):
        path = _write(tmp_path, "m.json", _dump(
            {"A": _entry(computed_value=1, is_fully_resolved=True)}, total_macros=99))
        _, report = load_macro_defs(path)
        assert any("total_macros=99" in w for w in report.warnings)

    def test_entry_table_without_the_wrapper_is_accepted(self, tmp_path):
        path = _write(tmp_path, "m.json", {
            "A": _entry(name="A", computed_value=7, is_fully_resolved=True)})
        defs, report = load_macro_defs(path)
        assert defs[GLOBAL_SCOPE] == {"A": "7"}
        assert report.kind == "entries"


class TestOtherJsonShapes:
    def test_flat_map(self, tmp_path):
        path = _write(tmp_path, "m.json", {"FEATURE_A": "1", "BARE": "", "SKIP": "ne"})
        defs, report = load_macro_defs(path)
        assert defs[GLOBAL_SCOPE] == {"FEATURE_A": "1", "BARE": None}
        assert report.kind == "map"
        assert report.skipped_ne == 1

    def test_list_form_from_the_web_wizard(self, tmp_path):
        path = _write(tmp_path, "m.json", ["FEATURE_A=1", "-DPLATFORM_EMBEDDED=2", "ENABLE_DIAG"])
        defs, report = load_macro_defs(path)
        assert defs[GLOBAL_SCOPE] == {
            "FEATURE_A": "1", "PLATFORM_EMBEDDED": "2", "ENABLE_DIAG": None}
        assert report.kind == "list"

    def test_scoped_nested_keys_are_layer_names(self, tmp_path):
        path = _write(tmp_path, "m.json", {"Layer1": {"A": "1"}, "Layer2": {"A": "2", "B": ""}})
        defs, report = load_macro_defs(path)
        assert defs == {"Layer1": {"A": "1"}, "Layer2": {"A": "2", "B": None}}
        assert report.kind == "scoped"

    def test_numeric_and_boolean_values_are_stringified(self, tmp_path):
        path = _write(tmp_path, "m.json", {"N": 64, "T": True, "F": False})
        defs, _ = load_macro_defs(path)
        assert defs[GLOBAL_SCOPE] == {"N": "64", "T": "1", "F": "0"}

    def test_malformed_json_raises(self, tmp_path):
        path = _write(tmp_path, "m.json", "{ not json")
        with pytest.raises(MacroInputError):
            load_macro_defs(path)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(MacroInputError):
            load_macro_defs(str(tmp_path / "nope.json"))


class TestLegacyCsv:
    def test_csv_parity(self, tmp_path):
        path = _write(tmp_path, "m.csv", "Name,Value\nVOID,void\nBARE,\nSKIP,ne\nSKIP2,NE\n")
        defs, report = load_macro_defs(path)
        assert defs[GLOBAL_SCOPE] == {"VOID": "void", "BARE": None}
        assert report.kind == "csv"
        assert report.skipped_ne == 2
        assert to_clang_args(defs[GLOBAL_SCOPE]) == ["-DVOID=void", "-DBARE"]

    def test_sample_config_csv_still_loads(self):
        """The shipped sample must keep working — it is the back-compat canary."""
        sample = os.path.join(PROJECT_ROOT, "engine", "config", "macros.csv")
        defs, _ = load_macro_defs(sample)
        assert defs[GLOBAL_SCOPE].get("VOID") == "void"


class TestScopeHandling:
    def test_default_scope_overrides_what_the_file_says(self, tmp_path):
        path = _write(tmp_path, "m.json", {"Layer9": {"A": "1"}, "Layer8": {"B": "2"}})
        defs, _ = load_macro_defs(path, default_scope="Layer1")
        assert defs == {"Layer1": {"A": "1", "B": "2"}}

    def test_merge_lets_the_later_file_win(self):
        merged = merge_macro_defs({GLOBAL_SCOPE: {"A": "1", "B": "2"}}, {GLOBAL_SCOPE: {"A": "9"}})
        assert merged == {GLOBAL_SCOPE: {"A": "9", "B": "2"}}

    def test_same_name_different_value_is_reported_not_hidden(self):
        found = find_conflicts({GLOBAL_SCOPE: {"A": "1", "B": "2"}},
                               {GLOBAL_SCOPE: {"A": "9", "B": "2", "C": "3"}})
        assert found == [(GLOBAL_SCOPE, "A", "1", "9")]

    def test_global_vs_layer_override_is_not_a_conflict(self):
        assert find_conflicts({GLOBAL_SCOPE: {"A": "1"}}, {"Layer1": {"A": "2"}}) == []

    def test_scoped_args_shape(self):
        args = scoped_args({GLOBAL_SCOPE: {"A": "1"}, "Layer1": {"B": None}})
        assert args == {GLOBAL_SCOPE: ["-DA=1"], "Layer1": ["-DB"]}

    def test_layer_args_come_after_global_so_clang_takes_the_layer_value(self):
        stored = {GLOBAL_SCOPE: ["-DA=1"], "Layer1": ["-DA=2"]}
        assert args_for_scope(stored, "Layer1") == ["-DA=1", "-DA=2"]
        assert args_for_scope(stored, "Layer2") == ["-DA=1"]
        assert args_for_scope(stored, None) == ["-DA=1"]

    def test_flat_list_file_loads_as_global(self):
        """model/clang_macros.json written before this change is a bare list."""
        assert normalize_scoped_args(["-DA=1"]) == {GLOBAL_SCOPE: ["-DA=1"]}
        assert normalize_scoped_args({"*": ["-DA=1"], "Layer1": []}) == {
            GLOBAL_SCOPE: ["-DA=1"], "Layer1": []}
        assert normalize_scoped_args(None) == {}
