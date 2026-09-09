"""Layer-qualified identity: two layers may reuse a group or component name.

`FTL/Cache` and `HIL/Cache` are two different components, not a mistake. Every id
the model builds from therefore carries its layer — a group id is `Layer1.Support`,
a component id is `Layer1.Cache`, and `unit_key` is `Layer1.Cache|Buffer`. Only the
DISPLAY name drops the prefix.

Before that, identity was the bare name and everything downstream flattened across
layers: `get_flat_groups` keyed groups by name (so one layer's group replaced the
other's and its components never reached the parser), `init_component_mapping`
MERGED two layers' path lists into one component (so half the files were parsed
with the other layer's -D set and data dictionary), and `unit_key` collided.

What layer qualification does NOT fix is ambiguity *inside* one layer, or in the
paths — the same name twice in one layer, two components claiming one folder, a
folder nested inside another's. Those are still refused by `validate_layer_names`.

`interfaceId` already worked this way (`IF_LAYER1_SUPPORT_MATH_01`); this is the
same fact, moved into the keys.

All of it is pure — no libclang, no I/O.
"""
import json
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

import utils
from core.config import (
    LAYER_SEP, display_name, get_flat_groups, get_component_layer_name,
    get_group_layer_name, get_layer_components, make_qualified_id, name_ident,
    qualified_layer, resolve_component_id, resolve_group_id, split_qualified_id,
    validate_layer_names,
)
# At module scope on purpose: importing model_deriver runs apply_cli_run_context(), which
# resets the active model repository — inside a test it would wipe the one the fixture just
# installed, and only the FIRST test using it would fail.
import model_deriver


def _cfg(layers):
    return {"layers": layers}


def _layer(path, groups):
    return {"path": path, "groups": groups}


# Two layers, each with a `Support` group holding a `Cache` component. The whole
# point of the change: this is a legal, ordinary config.
TWIN = _cfg({
    "Layer1": _layer("Layer1", {"Support": {"Cache": "Sample/Cache"}}),
    "Layer2": _layer("Layer2", {"Support": {"Cache": "Plat/Cache"}}),
})


# ---------------------------------------------------------------------------
# The id itself
# ---------------------------------------------------------------------------

class TestQualifiedIds:
    def test_an_id_is_layer_then_name(self):
        assert make_qualified_id("Layer1", "Cache") == "Layer1" + LAYER_SEP + "Cache"

    def test_no_layer_leaves_the_name_bare(self):
        """A legacy `layer` / `modulesGroups` config has no layer to qualify with."""
        assert make_qualified_id(None, "Cache") == "Cache"
        assert make_qualified_id("", "Cache") == "Cache"

    def test_the_configured_spelling_survives(self):
        """Spaces are normalized where they matter (filenames, model keys), not here —
        the DOCX headings keep the name as written."""
        assert make_qualified_id("Layer1", "My Sample") == "Layer1.My Sample"

    def test_split_and_display_are_the_inverse(self):
        assert split_qualified_id("Layer1.Cache") == ("Layer1", "Cache")
        assert qualified_layer("Layer1.Cache") == "Layer1"
        assert display_name("Layer1.Cache") == "Cache"

    def test_a_bare_id_has_no_layer_and_displays_itself(self):
        assert split_qualified_id("Cache") == (None, "Cache")
        assert qualified_layer("Cache") is None
        assert display_name("Cache") == "Cache"


# ---------------------------------------------------------------------------
# Two layers, one name — the case this exists for
# ---------------------------------------------------------------------------

class TestTwoLayersMayShareNames:

    def test_both_groups_survive_the_flattening(self):
        """Keyed by bare name, the second layer's `Support` overwrote the first's and
        `Layer1.Cache` was never parsed at all."""
        flat = get_flat_groups(TWIN)
        assert sorted(flat) == ["Layer1.Support", "Layer2.Support"]
        assert list(flat["Layer1.Support"]) == ["Layer1.Cache"]
        assert list(flat["Layer2.Support"]) == ["Layer2.Cache"]

    def test_each_group_resolves_to_its_own_layer(self):
        assert get_group_layer_name(TWIN, "Layer1.Support") == "Layer1"
        assert get_group_layer_name(TWIN, "Layer2.Support") == "Layer2"

    def test_each_component_resolves_to_its_own_layer(self):
        """This is the one that decided which -D set and data dictionary a file was
        parsed with; first-match meant half the files got the wrong layer's."""
        assert get_component_layer_name(TWIN, "Layer1.Cache") == "Layer1"
        assert get_component_layer_name(TWIN, "Layer2.Cache") == "Layer2"

    def test_a_group_pulls_in_only_its_own_layers_components(self):
        assert get_layer_components(TWIN, "Layer1.Support") == {"Layer1.Cache"}
        assert get_layer_components(TWIN, "Layer2.Support") == {"Layer2.Cache"}

    def test_the_paths_are_not_merged_into_one_component(self):
        """`init_component_mapping` appended both layers' paths under one key, so a
        single `Cache` owned files from both layers."""
        saved = utils._CONFIG_CACHE
        try:
            utils.init_component_mapping(TWIN)
            assert utils._COMPONENT_OVERRIDES["Layer1.Cache"] == "Layer1/Sample/Cache"
            assert utils._COMPONENT_OVERRIDES["Layer2.Cache"] == "Layer2/Plat/Cache"
            assert utils._resolve_component_from_rel("Layer1/Sample/Cache/c.cpp") == "Layer1.Cache"
            assert utils._resolve_component_from_rel("Layer2/Plat/Cache/c.cpp") == "Layer2.Cache"
            assert utils.resolve_group("Layer1.Cache") == "Layer1.Support"
            assert utils.resolve_group("Layer2.Cache") == "Layer2.Support"
        finally:
            utils.init_component_mapping(saved)

    def test_model_keys_stay_distinct(self):
        """The reason the layer had to reach the ids at all: every model key starts
        with the component, so a bare name made these two strings identical."""
        saved = utils._CONFIG_CACHE
        try:
            utils.init_component_mapping(TWIN)
            assert utils.make_unit_key("Layer1/Sample/Cache/Buf.cpp") == "Layer1.Cache|Buf"
            assert utils.make_unit_key("Layer2/Plat/Cache/Buf.cpp") == "Layer2.Cache|Buf"
            assert utils.make_global_key("Layer1/Sample/Cache/Buf.cpp", "g") == "Layer1.Cache|Buf|g"
            assert utils.make_global_key("Layer2/Plat/Cache/Buf.cpp", "g") == "Layer2.Cache|Buf|g"
            assert (utils.make_function_key("", "Layer1/Sample/Cache/Buf.cpp", "f", [])
                    != utils.make_function_key("", "Layer2/Plat/Cache/Buf.cpp", "f", []))
        finally:
            utils.init_component_mapping(saved)

    def test_a_space_in_the_name_still_resolves_to_its_group(self):
        """`_GROUP_MAP` is keyed by the id `_resolve_component_from_rel` RETURNS. Keyed
        by the raw config name instead, every component with a space answered ""."""
        saved = utils._CONFIG_CACHE
        try:
            utils.init_component_mapping(_cfg({
                "Layer1": _layer("Layer1", {"My Group": {"Sample Core": "Sample/Core"}})}))
            assert utils.resolve_group("Layer1.Sample-Core") == "Layer1.My Group"
        finally:
            utils.init_component_mapping(saved)


# ---------------------------------------------------------------------------
# Selecting one of two same-named groups
# ---------------------------------------------------------------------------

class TestSelection:

    def test_a_qualified_name_selects_exactly_one(self):
        groups = get_flat_groups(TWIN)
        assert resolve_group_id(groups, "Layer1.Support")[0] == "Layer1.Support"
        assert resolve_group_id(groups, "layer2.support")[0] == "Layer2.Support"

    def test_a_bare_name_is_ambiguous_and_names_both(self):
        """There is no right answer, and picking the first generated one layer's
        document under a name meant for the other."""
        resolved, candidates = resolve_group_id(get_flat_groups(TWIN), "Support")
        assert resolved is None
        assert candidates == ["Layer1.Support", "Layer2.Support"]

    def test_the_ambiguity_message_names_no_entry_points_flag(self):
        """The same request arrives as `analyzer.py --scope "group:X"` and as
        `run.py --selected-group X`; quoting either sends half the readers looking
        for a flag their command does not have."""
        from core.config import ambiguous_group_message
        msg = ambiguous_group_message("Support", ["Layer1.Support", "Layer2.Support"])
        assert "Layer1.Support" in msg and "Layer2.Support" in msg
        assert "--scope" not in msg and "--selected-group" not in msg

    def test_a_bare_name_still_works_when_only_one_layer_has_it(self):
        cfg = _cfg({"Layer1": _layer("Layer1", {"Support": {"Cache": "c"}}),
                    "Layer2": _layer("Layer2", {"Platform": {"Gpio": "g"}})})
        groups = get_flat_groups(cfg)
        assert resolve_group_id(groups, "Support")[0] == "Layer1.Support"
        assert resolve_group_id(groups, "platform")[0] == "Layer2.Platform"

    def test_spaces_and_case_never_decide_the_answer(self):
        cfg = _cfg({"Layer1": _layer("Layer1", {"My Sample": {"Core": "c"}})})
        groups = get_flat_groups(cfg)
        for spelling in ("My Sample", "my-sample", "MY SAMPLE", "Layer1.my sample"):
            assert resolve_group_id(groups, spelling)[0] == "Layer1.My Sample", spelling

    def test_an_unknown_name_matches_nothing(self):
        assert resolve_group_id(get_flat_groups(TWIN), "Nope") == (None, [])

    def test_components_resolve_the_same_way(self):
        comps = ["Layer1.Cache", "Layer2.Cache", "Layer1.Math"]
        assert resolve_component_id(comps, "Layer2.Cache")[0] == "Layer2.Cache"
        assert resolve_component_id(comps, "Math")[0] == "Layer1.Math"
        assert resolve_component_id(comps, "Cache") == (None, ["Layer1.Cache", "Layer2.Cache"])


# ---------------------------------------------------------------------------
# What layer qualification does NOT fix
# ---------------------------------------------------------------------------

class TestValidateLayerNames:

    def test_the_shipped_config_is_clean(self):
        with open(os.path.join(PROJECT_ROOT, "engine", "config", "config.defaults.json"),
                  encoding="utf-8") as fh:
            assert validate_layer_names(json.load(fh)) == []

    def test_two_layers_sharing_group_and_component_names_is_not_an_error(self):
        """The headline of this change: TWIN is an ordinary config."""
        assert validate_layer_names(TWIN) == []

    def test_a_config_without_layers_reports_nothing(self):
        assert validate_layer_names({}) == []
        assert validate_layer_names({"layers": {}}) == []
        assert validate_layer_names({"layers": "nonsense"}) == []

    def test_a_component_name_twice_in_ONE_layer_is_reported(self):
        """Same layer prefix, so the ids are identical and the paths still merge."""
        errors = validate_layer_names(_cfg({
            "Layer1": _layer("Layer1", {"A": {"Core": "Sample/Core"},
                                        "B": {"Core": "Other/Core"}}),
        }))
        assert len(errors) == 1
        assert "component name 'core'" in errors[0] and "'Layer1'" in errors[0]
        assert "Another layer may reuse the name freely" in errors[0]

    def test_two_groups_in_one_layer_that_collapse_to_one_name_are_reported(self):
        errors = validate_layer_names(_cfg({
            "Layer1": _layer("Layer1", {"Support": {"A": "a"}, "support": {"B": "b"}}),
        }))
        assert len(errors) == 1 and "unique WITHIN its layer" in errors[0]

    def test_a_path_claimed_by_two_components_is_reported(self):
        errors = validate_layer_names(_cfg({
            "Layer1": _layer("Layer1", {"A": {"One": "Shared", "Two": "Shared"}}),
        }))
        assert len(errors) == 1
        assert "'layer1/shared'" in errors[0]
        assert "Layer1/A/One" in errors[0] and "Layer1/A/Two" in errors[0]

    def test_the_same_relative_path_in_two_layers_is_fine(self):
        """Layer paths make them different directories — the normal case."""
        assert validate_layer_names(_cfg({
            "Layer1": _layer("Layer1", {"A": {"One": "Core"}}),
            "Layer2": _layer("Layer2", {"B": {"Two": "Core"}}),
        })) == []

    def test_a_path_nested_in_another_components_path_is_reported(self):
        errors = validate_layer_names(_cfg({
            "Layer1": _layer("Layer1", {"A": {"Outer": "Sample", "Inner": "Sample/Core"}}),
        }))
        assert len(errors) == 1
        assert "nested inside" in errors[0] and "'layer1/sample/core'" in errors[0]

    def test_a_nested_file_under_another_components_folder_is_reported(self):
        errors = validate_layer_names(_cfg({
            "Layer1": _layer("Layer1", {"A": {"Folder": "Math", "OneFile": "Math/Utils.cpp"}}),
        }))
        assert len(errors) == 1 and "nested inside" in errors[0]

    def test_one_component_listing_a_folder_and_a_file_inside_it_is_allowed(self):
        """Redundant, but it is the SAME component — nothing is taken from anyone."""
        assert validate_layer_names(_cfg({
            "Layer1": _layer("Layer1", {"A": {"Both": ["Math", "Math/Utils.cpp"]}}),
        })) == []

    def test_a_component_named_after_a_group_is_allowed(self):
        """The shipped config does exactly this (Access, Signal, Diag)."""
        assert validate_layer_names(_cfg({
            "Layer1": _layer("Layer1", {"Access": {"Access": "Access"}}),
        })) == []

    def test_layer_names_that_collapse_to_one_identifier_are_reported(self):
        errors = validate_layer_names(_cfg({
            "Layer 1": _layer("a", {"A": {"One": "x"}}),
            "layer-1": _layer("b", {"B": {"Two": "y"}}),
        }))
        assert any("layer names" in e for e in errors)

    def test_a_name_carrying_the_separator_is_reported(self):
        """Ids split on the FIRST separator, so a name holding one cannot be undone."""
        errors = validate_layer_names(_cfg({
            "Layer1": _layer("Layer1", {"A": {"Dot.Name": "x"}}),
        }))
        assert len(errors) == 1 and "contains '.'" in errors[0]

    def test_every_problem_is_reported_not_just_the_first(self):
        errors = validate_layer_names(_cfg({
            "Layer1": _layer("Layer1", {"A": {"Core": "Shared"}, "B": {"Core": "Shared"}}),
        }))
        assert len(errors) == 2
        assert any("component name" in e for e in errors)
        assert any("claimed by" in e for e in errors)


# ---------------------------------------------------------------------------
# Unit keys — componentId|<basename>, still no directory
# ---------------------------------------------------------------------------

class TestUnitKeyCollisions:
    """Qualifying the component fixes the CROSS-LAYER collision. Two files with one
    basename inside a single component still fold into one unit — the key carries no
    directory — so that stays a warning."""

    @pytest.fixture(autouse=True)
    def _isolated_run(self, tmp_path):
        """Phase 2 writes units.json + components.json, so it needs a repository, and
        the component mapping is a module global every other test shares."""
        from core import model_repo
        from core.paths import set_model_dir, paths
        before_dir = paths().model_dir
        before_cfg = utils._CONFIG_CACHE
        set_model_dir(str(tmp_path / "model"))
        model_repo.set_repository(model_repo.ScratchRepository())
        yield
        model_repo.set_repository(None)
        set_model_dir(before_dir)
        utils.init_component_mapping(before_cfg)

    def _derive(self, layers, rel_files):
        utils.init_component_mapping(_cfg(layers))
        fns = {f"f{i}": {"location": {"file": rel, "line": 1}, "parameters": [],
                         "returnType": "void", "calledByIds": [], "callsIds": []}
               for i, rel in enumerate(rel_files)}
        return model_deriver._build_units_components(PROJECT_ROOT, fns, {})[0]

    def test_the_same_unit_name_in_two_layers_is_two_units(self):
        """`Cache|Buf` twice was one merged unit holding both layers' functions."""
        units = self._derive(
            {"Layer1": _layer("Layer1", {"G": {"Cache": "Sample/Cache"}}),
             "Layer2": _layer("Layer2", {"G": {"Cache": "Plat/Cache"}})},
            ["Layer1/Sample/Cache/Buf.cpp", "Layer2/Plat/Cache/Buf.cpp"])
        assert sorted(units) == ["Layer1.Cache|Buf", "Layer2.Cache|Buf"]
        assert len(units["Layer1.Cache|Buf"]["functionIds"]) == 1
        assert len(units["Layer2.Cache|Buf"]["functionIds"]) == 1

    def test_same_stem_in_two_directories_of_one_component_still_warns(self, caplog):
        with caplog.at_level("WARNING"):
            units = self._derive(
                {"Layer1": _layer("Layer1", {"G": {"Core": "Sample/Core"}})},
                ["Layer1/Sample/Core/a/Util.cpp", "Layer1/Sample/Core/b/Util.cpp"])
        assert list(units) == ["Layer1.Core|Util"]
        assert len(units["Layer1.Core|Util"]["functionIds"]) == 2
        assert "unit key 'Layer1.Core|Util'" in caplog.text
        assert "Layer1/Sample/Core/a/Util" in caplog.text
        assert "Layer1/Sample/Core/b/Util" in caplog.text

    def test_a_cpp_and_its_header_are_one_unit_and_are_not_warned_about(self, caplog):
        with caplog.at_level("WARNING"):
            units = self._derive(
                {"Layer1": _layer("Layer1", {"G": {"Core": "Sample/Core"}})},
                ["Layer1/Sample/Core/Util.cpp", "Layer1/Sample/Core/Util.h"])
        assert list(units) == ["Layer1.Core|Util"]
        assert "unit key" not in caplog.text

    def test_the_same_stem_in_two_components_does_not_collide(self, caplog):
        with caplog.at_level("WARNING"):
            units = self._derive(
                {"Layer1": _layer("Layer1", {"G": {"One": "A", "Two": "B"}})},
                ["Layer1/A/Util.cpp", "Layer1/B/Util.cpp"])
        assert sorted(units) == ["Layer1.One|Util", "Layer1.Two|Util"]
        assert "unit key" not in caplog.text


# ---------------------------------------------------------------------------
# name_ident — the comparison rule selection is built on
# ---------------------------------------------------------------------------

class TestNameIdent:
    def test_spaces_become_hyphens_and_case_is_folded(self):
        assert name_ident("My Sample") == name_ident("my-sample") == "my-sample"

    def test_surrounding_whitespace_is_ignored(self):
        assert name_ident("  Core  ") == "core"

    def test_none_and_empty_are_empty(self):
        assert name_ident(None) == "" and name_ident("") == ""
