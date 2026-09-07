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


# ---------------------------------------------------------------------------
# Layer-qualified ids and multi-layer runs (2026-09-06 / 2026-09-07)
# ---------------------------------------------------------------------------

class TestQualifiedAndMultiLayerScope:
    """The flowchart subprocess gets ONE command line, so the layers this run covers
    decide its `-I` dirs and its `-D` set.

    `_resolve_layer_name` used to compare `group_name` against the config's BARE
    group names. The day group ids gained their layer prefix (`Layer1.Support`) it
    matched nothing and every run fell through to "all layers' dirs, global-only
    macros" — more headers than the layer should see and none of its own defines,
    silently. A component bundle was worse: its `group_name` is a virtual join of
    component ids that names no group at all.
    """

    LAYER_PATHS = {"Layer1": ["/p/L1a", "/p/L1b"], "Layer2": ["/p/L2a"]}

    def _names(self, group, comps=None):
        from views.flowcharts import _resolve_layer_names
        return _resolve_layer_names(CFG, group, comps)

    def _dirs(self, group, comps=None):
        from views.flowcharts import _resolve_layer_dirs
        return _resolve_layer_dirs(CFG, group, self.LAYER_PATHS, comps)

    def test_a_qualified_group_id_resolves_to_its_layer(self):
        assert self._names("Layer1.My Sample") == ["Layer1"]
        assert self._names("Layer2.Platform") == ["Layer2"]

    def test_a_qualified_group_sees_only_its_own_layers_dirs(self):
        """The regression: this returned every layer's dirs."""
        assert self._dirs("Layer1.My Sample") == ["/p/L1a", "/p/L1b"]
        assert self._dirs("Layer2.Platform") == ["/p/L2a"]

    def test_a_qualified_group_gets_only_its_own_layers_macros(self):
        from views.flowcharts import _macro_args_for_layers
        flags = _macro_args_for_layers(normalize_scoped_args(STORED),
                                       self._names("Layer1.My Sample"))
        assert flags == ["-DPROJECT_WIDE=1", "-DSOME_THING=1", '-DFW_VERSION="UFS 3.1"']
        assert "-DPLATFORM_EMBEDDED=1" not in flags

    def test_a_legacy_bare_group_name_still_resolves(self):
        assert self._names("My Sample") == ["Layer1"]
        assert self._names("my sample") == ["Layer1"]

    def test_a_component_bundle_spanning_layers_covers_both(self):
        """`group_name` is a virtual join here and names no group; the layers come
        from the component ids. They arrive CASEFOLDED, which is what made the
        first attempt at this resolve to one layer."""
        comps = ["layer1.my sample", "layer2.platform"]
        assert self._names("Layer1.My Sample_Layer2.Platform", comps) == ["Layer1", "Layer2"]
        assert self._dirs("Layer1.My Sample_Layer2.Platform", comps) == \
            ["/p/L1a", "/p/L1b", "/p/L2a"]

    def test_a_bundle_inside_one_layer_stays_in_that_layer(self):
        comps = ["layer2.platform"]
        assert self._names("Layer2.Platform_x", comps) == ["Layer2"]
        assert self._dirs("Layer2.Platform_x", comps) == ["/p/L2a"]

    def test_both_layers_macros_are_passed_for_a_cross_layer_bundle(self):
        from views.flowcharts import _macro_args_for_layers
        flags = _macro_args_for_layers(normalize_scoped_args(STORED), ["Layer1", "Layer2"])
        assert flags[0] == "-DPROJECT_WIDE=1"            # global first
        assert "-DSOME_THING=1" in flags and "-DPLATFORM_EMBEDDED=1" in flags

    def test_a_macro_the_layers_disagree_on_is_reported(self, caplog):
        """One command line cannot honour two values; say so rather than pick."""
        from views.flowcharts import _macro_args_for_layers
        scoped = {"*": [], "Layer1": ["-DCORE=1"], "Layer2": ["-DCORE=2"]}
        with caplog.at_level("ERROR"):
            flags = _macro_args_for_layers(scoped, ["Layer1", "Layer2"])
        assert flags == ["-DCORE=1", "-DCORE=2"]         # clang honours the last
        assert "defined differently" in caplog.text and "CORE" in caplog.text

    def test_one_layer_never_warns(self, caplog):
        from views.flowcharts import _macro_args_for_layers
        with caplog.at_level("ERROR"):
            _macro_args_for_layers(normalize_scoped_args(STORED), ["Layer1"])
        assert "defined differently" not in caplog.text

    def test_an_unscoped_run_still_falls_back_to_every_layer(self):
        assert self._names("") == []
        assert self._dirs("") == ["/p/L1a", "/p/L1b", "/p/L2a"]


class TestClangArgsFileLocation:
    """The response file records what a component was compiled with, so it has to
    belong to that component's run.

    It lived in the shared model dir — one path per VERSION — so once a run produced
    one document per component, each flowchart invocation overwrote the previous
    one's file. What survived on disk was the LAST component's flags, which is
    actively misleading when you open it to check which layer's -I/-D a component
    got. Verified on a real run: Layer1.Math's copy now holds 17 Layer1 paths and
    -DBUFFER_SIZE=4096, Layer2.Sample-Core's holds 20 Layer2 paths and =8192.
    """

    def test_it_sits_in_the_runs_own_output_dir(self):
        from views.flowcharts import clang_args_file
        assert clang_args_file(os.path.join("out", "Layer1.Math")) == \
            os.path.join("out", "Layer1.Math", ".flowcharts_clang_args.txt")

    def test_two_components_get_two_different_paths(self):
        """The whole point: no overwriting between per-component invocations."""
        from views.flowcharts import clang_args_file
        a = clang_args_file(os.path.join("out", "Layer1.Math"))
        b = clang_args_file(os.path.join("out", "Layer2.Sample-Core"))
        assert a != b

    def test_it_is_not_in_the_shared_model_dir(self):
        from views.flowcharts import clang_args_file
        assert "model" not in clang_args_file(os.path.join("v1", "output", "Layer1.Math"))
