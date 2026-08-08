"""Unit tests for the Phase-3 macro scope selection in views/flowcharts.py.

Phase 3 re-parses functions in a subprocess and must define exactly what Phase 1
defined for that group's layer — no more (another layer's macros must not leak in)
and no less. This guards the composition the view uses:

    args_for_scope(normalize_scoped_args(<model/clang_macros.json>),
                   _resolve_layer_name(config, group))

Mark: unit (pure functions, no pipeline)
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from core.macro_input import args_for_scope, normalize_scoped_args  # noqa: E402
from views.flowcharts import _resolve_layer_name  # noqa: E402


CFG = {"layers": {
    "Layer1": {"groups": {"My Sample": {}, "Diag": {}}},
    "Layer2": {"groups": {"Platform": {}}},
}}

STORED = {
    "*": ["-DPROJECT_WIDE=1"],
    "Layer1": ["-DSOME_THING=1", '-DFW_VERSION="UFS 3.1"'],
    "Layer2": ["-DPLATFORM_EMBEDDED=1"],
}


def _flags(group):
    return args_for_scope(normalize_scoped_args(STORED), _resolve_layer_name(CFG, group))


class TestLayerResolution:
    def test_group_resolves_to_its_layer(self):
        assert _resolve_layer_name(CFG, "My Sample") == "Layer1"
        assert _resolve_layer_name(CFG, "Platform") == "Layer2"

    def test_match_is_case_insensitive(self):
        assert _resolve_layer_name(CFG, "my sample") == "Layer1"

    @pytest.mark.parametrize("group", ["", None, "Unknown Group"])
    def test_no_group_or_unknown_group_resolves_to_nothing(self, group):
        assert _resolve_layer_name(CFG, group) is None


class TestFlagSelection:
    def test_group_gets_global_plus_its_own_layer(self):
        assert _flags("My Sample") == [
            "-DPROJECT_WIDE=1", "-DSOME_THING=1", '-DFW_VERSION="UFS 3.1"']

    def test_another_layers_macros_do_not_leak_in(self):
        assert "-DPLATFORM_EMBEDDED=1" not in _flags("My Sample")
        assert "-DSOME_THING=1" not in _flags("Platform")

    def test_unknown_group_still_gets_the_global_set(self):
        assert _flags("Unknown Group") == ["-DPROJECT_WIDE=1"]

    def test_layer_value_is_ordered_after_the_global_one(self):
        """Clang honours the last -D, so ordering is what makes the layer win."""
        stored = {"*": ["-DBUFFER_SIZE=4096"], "Layer1": ["-DBUFFER_SIZE=8192"]}
        assert args_for_scope(normalize_scoped_args(stored), "Layer1") == [
            "-DBUFFER_SIZE=4096", "-DBUFFER_SIZE=8192"]

    def test_pre_scope_flat_file_still_applies_to_every_group(self):
        flat = ["-DLEGACY=1"]
        assert args_for_scope(normalize_scoped_args(flat), "Layer1") == ["-DLEGACY=1"]
        assert args_for_scope(normalize_scoped_args(flat), "Layer2") == ["-DLEGACY=1"]

    def test_empty_file_yields_no_flags(self):
        assert args_for_scope(normalize_scoped_args({}), "Layer1") == []
