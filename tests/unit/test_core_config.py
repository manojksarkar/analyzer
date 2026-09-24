"""Unit tests for src/core/config.py — load_llm_config and format_llm_config_banner."""
import json
import os
import sys
import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from core.config import (
    load_config, load_llm_config, LlmConfigError, format_llm_config_banner,
    layer_source, layer_sources, layer_source_origin, core_config_warnings,
    missing_layer_inputs,
)


def _cfg(**overrides):
    base = {"llm": {"provider": "ollama", "baseUrl": "http://localhost:11434",
                    "defaultModel": "llama3.2", "timeoutSeconds": 120,
                    "numCtx": 8192, "retries": 1}}
    base["llm"].update(overrides)
    return base


class TestLoadLlmConfig:
    def test_valid_config_returns_all_required_fields(self):
        r = load_llm_config(_cfg())
        for f in ("provider", "baseUrl", "defaultModel", "timeoutSeconds", "numCtx", "retries"):
            assert f in r

    def test_provider_lowercased_and_trailing_slash_stripped(self):
        r = load_llm_config(_cfg(provider="Ollama", baseUrl="http://localhost/"))
        assert r["provider"] == "ollama"
        assert not r["baseUrl"].endswith("/")

    def test_invalid_provider_raises(self):
        with pytest.raises(LlmConfigError, match="provider"):
            load_llm_config(_cfg(provider="badprovider"))

    def test_missing_required_field_raises(self):
        cfg = _cfg(); del cfg["llm"]["defaultModel"]
        with pytest.raises(LlmConfigError, match="defaultModel"):
            load_llm_config(cfg)

    def test_non_positive_numeric_field_raises(self):
        with pytest.raises(LlmConfigError, match="timeoutSeconds"):
            load_llm_config(_cfg(timeoutSeconds=0))

    def test_retries_zero_is_valid(self):
        assert load_llm_config(_cfg(retries=0))["retries"] == 0

    def test_enrichment_defaults_and_override(self):
        r = load_llm_config(_cfg(enrichment={"selfReview": True}))
        assert r["enrichment"]["selfReview"] is True
        assert r["enrichment"]["twoPassDescriptions"] is True  # default preserved

    def test_enrichment_wrong_type_raises(self):
        with pytest.raises(LlmConfigError, match="enrichment"):
            load_llm_config(_cfg(enrichment={"selfReview": "yes"}))

    def test_env_var_overrides_config(self, monkeypatch):
        monkeypatch.setenv("LLM_DEFAULT_MODEL", "env-model")
        assert load_llm_config(_cfg())["defaultModel"] == "env-model"

    def test_empty_env_var_falls_back_to_config(self, monkeypatch):
        monkeypatch.setenv("LLM_DEFAULT_MODEL", "")
        assert load_llm_config(_cfg(defaultModel="cfg-model"))["defaultModel"] == "cfg-model"

    def test_missing_llm_block_raises(self):
        with pytest.raises(LlmConfigError, match="'llm' block"):
            load_llm_config({"other": "stuff"})

    def test_rate_limit_defaults_to_three_seconds(self):
        assert load_llm_config(_cfg())["rateLimitSeconds"] == 3.0

    def test_rate_limit_override(self):
        assert load_llm_config(_cfg(rateLimitSeconds=0.5))["rateLimitSeconds"] == 0.5

    def test_rate_limit_zero_is_valid(self):
        assert load_llm_config(_cfg(rateLimitSeconds=0))["rateLimitSeconds"] == 0.0

    def test_rate_limit_negative_raises(self):
        with pytest.raises(LlmConfigError, match="rateLimitSeconds"):
            load_llm_config(_cfg(rateLimitSeconds=-1))

    def test_rate_limit_non_numeric_raises(self):
        with pytest.raises(LlmConfigError, match="rateLimitSeconds"):
            load_llm_config(_cfg(rateLimitSeconds="fast"))

    def test_rate_limit_null_raises_with_hint(self):
        with pytest.raises(LlmConfigError, match="use 0 to disable"):
            load_llm_config(_cfg(rateLimitSeconds=None))

    def test_rate_limit_env_var_overrides_config(self, monkeypatch):
        monkeypatch.setenv("LLM_RATE_LIMIT_SECONDS", "0")
        assert load_llm_config(_cfg(rateLimitSeconds=3.0))["rateLimitSeconds"] == 0.0


class TestLoadConfigAnalyzerConfigOverride:
    """`ANALYZER_CONFIG` env var injects a per-project/per-version config (M1.1)."""

    def test_no_override_reads_default_config(self, monkeypatch):
        monkeypatch.delenv("ANALYZER_CONFIG", raising=False)
        cfg = load_config(os.path.join(PROJECT_ROOT, "engine"))
        assert "__injected__" not in cfg  # the marker only exists in an override

    def test_override_is_honored(self, monkeypatch, tmp_path):
        ovr = tmp_path / "override.json"
        ovr.write_text(json.dumps({"__injected__": True,
                                   "layers": {"ZLayer": {"path": "ZL", "groups": {}}}}))
        monkeypatch.setenv("ANALYZER_CONFIG", str(ovr))
        cfg = load_config(PROJECT_ROOT)
        assert cfg.get("__injected__") is True
        assert list(cfg["layers"].keys()) == ["ZLayer"]

    def test_override_supports_jsonc(self, monkeypatch, tmp_path):
        ovr = tmp_path / "override.jsonc"
        ovr.write_text('{\n  // a comment\n  "__injected__": true,\n}\n')  # comment + trailing comma
        monkeypatch.setenv("ANALYZER_CONFIG", str(ovr))
        assert load_config(PROJECT_ROOT).get("__injected__") is True

    def test_override_does_not_merge_config_local(self, monkeypatch, tmp_path):
        # An injected config is used as-is; config.local.json must not bleed in.
        ovr = tmp_path / "override.json"
        ovr.write_text(json.dumps({"only": "this"}))
        monkeypatch.setenv("ANALYZER_CONFIG", str(ovr))
        assert load_config(PROJECT_ROOT) == {"only": "this"}

    def test_missing_override_file_fails_loud(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ANALYZER_CONFIG", str(tmp_path / "nope.json"))
        with pytest.raises(FileNotFoundError, match="ANALYZER_CONFIG"):
            load_config(PROJECT_ROOT)


class TestFormatLlmConfigBanner:
    def test_banner_contains_key_fields(self):
        cfg = load_llm_config(_cfg(defaultModel="mymodel", numCtx=4096))
        banner = format_llm_config_banner(cfg)
        assert "ollama" in banner
        assert "mymodel" in banner
        assert "4096" in banner

    def test_api_key_value_not_exposed(self):
        cfg = load_llm_config(_cfg(apiKey="sk-secret"))
        banner = format_llm_config_banner(cfg)
        assert "sk-secret" not in banner
        assert "set" in banner


class TestLayerSources:
    """Per-layer inputs live INSIDE the layer block, beside `path` and `groups`."""

    CFG = {
        "layers": {
            "Layer1": {
                "path": "Layer1",
                "dataDictionary": " engine/config/dd.layer1.csv ",
                "macros": "engine/config/macros.layer1.json",
                "groups": {"G1": {"C1": "A"}},
            },
            "Layer2": {"path": "Layer2", "dataDictionary": "dd.layer2.csv", "groups": {}},
            "Layer3": {"path": "Layer3", "groups": {}},
        }
    }

    def test_layer_source_strips_whitespace(self):
        assert layer_source(self.CFG, "Layer1", "dataDictionary") == "engine/config/dd.layer1.csv"

    def test_absent_key_is_none(self):
        assert layer_source(self.CFG, "Layer3", "dataDictionary") is None
        assert layer_source(self.CFG, "Layer2", "macros") is None

    def test_unknown_layer_is_none(self):
        assert layer_source(self.CFG, "Nope", "dataDictionary") is None

    def test_empty_string_is_none(self):
        cfg = {"layers": {"L": {"dataDictionary": "   "}}}
        assert layer_source(cfg, "L", "dataDictionary") is None

    def test_layer_sources_collects_only_declaring_layers(self):
        assert layer_sources(self.CFG, "dataDictionary") == {
            "Layer1": "engine/config/dd.layer1.csv",
            "Layer2": "dd.layer2.csv",
        }
        assert layer_sources(self.CFG, "macros") == {
            "Layer1": "engine/config/macros.layer1.json",
        }

    def test_no_layers_block_is_empty(self):
        assert layer_sources({}, "dataDictionary") == {}

    def test_unknown_layer_keys_do_not_disturb_group_flattening(self):
        """`dataDictionary`/`macros` sit beside `groups`; _resolve_layer_paths must ignore them."""
        from core.config import get_flat_groups
        # Ids are layer-qualified: two layers may legitimately both have a `G1`.
        assert get_flat_groups(self.CFG) == {"Layer1.G1": {"Layer1.C1": "Layer1/A"}}


class TestCoresSection:
    """`cores` owns the build inputs; layers name the cores they are built from."""

    CFG = {
        "cores": {
            "Core1": {"dataDictionary": "dd1.csv", "macros": "m1.json"},
            "Core2": {"macros": "m2.json"},
        },
        "layers": {
            "Layer1": {"path": "Layer1", "cores": ["Core1"]},
            "Layer2": {"path": "Layer2", "cores": ["Core2"]},
            "Layer3": {"path": "Layer3", "cores": []},
        },
    }

    def test_a_layer_resolves_its_inputs_through_its_core(self):
        assert layer_source(self.CFG, "Layer1", "dataDictionary") == "dd1.csv"
        assert layer_source(self.CFG, "Layer1", "macros") == "m1.json"

    def test_a_key_the_core_does_not_define_is_absent(self):
        assert layer_source(self.CFG, "Layer2", "dataDictionary") is None

    def test_a_layer_with_no_core_resolves_nothing(self):
        assert layer_source(self.CFG, "Layer3", "macros") is None

    def test_a_layer_level_key_still_works_without_cores(self):
        """The pre-`cores` schema, and the shape --macros-layer mirrors."""
        old = {"layers": {"Layer1": {"path": "Layer1", "macros": "legacy.json"}}}
        assert layer_source(old, "Layer1", "macros") == "legacy.json"

    def test_the_core_wins_over_a_layer_level_key(self):
        both = {"cores": {"Core1": {"macros": "core.json"}},
                "layers": {"Layer1": {"cores": ["Core1"], "macros": "layer.json"}}}
        assert layer_source(both, "Layer1", "macros") == "core.json"

    def test_layer_sources_reports_every_layer_that_resolves(self):
        assert layer_sources(self.CFG, "macros") == {"Layer1": "m1.json", "Layer2": "m2.json"}


class TestValidateCores:

    def test_a_clean_config_reports_nothing(self):
        from core.config import validate_cores
        assert validate_cores(TestCoresSection.CFG) == []

    def test_an_unknown_core_name_is_reported(self):
        from core.config import validate_cores
        cfg = {"cores": {"Core1": {}}, "layers": {"Layer1": {"cores": ["Typo"]}}}
        errors = validate_cores(cfg)
        assert len(errors) == 1
        assert "unknown core 'Typo'" in errors[0]

    def test_a_second_core_in_one_layer_is_refused(self):
        """Not yet supported: macros still resolve per layer, so core 2's -D
        flags would silently apply to core 1's files."""
        from core.config import validate_cores
        cfg = {"cores": {"Core1": {}, "Core2": {}},
               "layers": {"Layer1": {"cores": ["Core1", "Core2"]}}}
        errors = validate_cores(cfg)
        assert len(errors) == 1
        assert "not supported yet" in errors[0]


def test_the_annotated_example_matches_the_shipped_defaults():
    """config.defaults.json.example is documentation ONLY if it stays in sync.

    It is never loaded, so nothing else would catch it drifting into describing
    a config that does not exist.
    """
    from core.config import _strip_json_comments, _strip_trailing_commas

    config_dir = os.path.join(PROJECT_ROOT, "engine", "config")
    with open(os.path.join(config_dir, "config.defaults.json"), encoding="utf-8") as fh:
        shipped = json.load(fh)          # strict JSON: no comments allowed here
    with open(os.path.join(config_dir, "config.defaults.json.example"), encoding="utf-8") as fh:
        annotated = json.loads(_strip_trailing_commas(_strip_json_comments(fh.read())))

    assert annotated == shipped


class TestInputsTheRunWouldIgnore:
    """A core input that is spelled wrong, or sits on a core no layer uses, was dropped without
    a word - the layer parsed with no dictionary and the log said "data dictionary : (none)"
    either way. Reported: "I have added dataDictionary inside core" and none was used."""

    def _cfg(self, core, layer_cores=("Core1",)):
        return {"cores": {"Core1": core},
                "layers": {"Layer1": {"path": "Layer1", "cores": list(layer_cores)}}}

    def test_origin_names_the_core_or_the_layer(self):
        assert layer_source_origin(self._cfg({"dataDictionary": "dd.csv"}),
                                   "Layer1", "dataDictionary") == ("dd.csv", "Core1")
        old = {"layers": {"Layer1": {"dataDictionary": "legacy.csv"}}}
        assert layer_source_origin(old, "Layer1", "dataDictionary") == ("legacy.csv", "layer")
        assert layer_source_origin(old, "Layer1", "macros") == (None, None)

    def test_a_correct_config_warns_about_nothing(self):
        assert core_config_warnings(self._cfg({"dataDictionary": "dd.csv", "macros": "m.json",
                                               "compileCommands": "cc.json"})) == []

    @pytest.mark.parametrize("key", ["datadictionary", "data_dictionary", "DataDictionary"])
    def test_a_misspelled_key_is_named_with_the_fix(self, key):
        cfg = self._cfg({key: "dd.csv"})
        assert layer_source(cfg, "Layer1", "dataDictionary") is None, "it really is ignored"
        [w] = core_config_warnings(cfg)
        assert f"cores.Core1.{key}" in w and "did you mean 'dataDictionary'" in w

    def test_an_unknown_key_lists_the_known_ones(self):
        [w] = core_config_warnings(self._cfg({"flags": "x"}))
        assert "cores.Core1.flags" in w and "dataDictionary, macros, compileCommands" in w

    def test_a_core_no_layer_lists_is_named(self):
        cfg = self._cfg({"dataDictionary": "dd.csv"}, layer_cores=())
        assert layer_source(cfg, "Layer1", "dataDictionary") is None, "it really is ignored"
        [w] = core_config_warnings(cfg)
        assert "cores.Core1 is listed by no layer" in w

    def test_a_misspelled_key_on_a_layer_is_named(self):
        cfg = {"layers": {"Layer1": {"path": "Layer1", "datadictionary": "dd.csv"}}}
        [w] = core_config_warnings(cfg)
        assert "layers.Layer1.datadictionary" in w and "'dataDictionary'" in w

    def test_other_layer_keys_are_left_alone(self):
        cfg = {"layers": {"Layer1": {"path": "L", "groups": {}, "cores": [], "note": "x"}}}
        assert core_config_warnings(cfg) == []

    def test_a_missing_dictionary_file_is_reported_with_where_it_came_from(self, tmp_path):
        (tmp_path / "here.csv").write_text("x", encoding="utf-8")
        cfg = {"cores": {"Core1": {"dataDictionary": "here.csv"},
                         "Core2": {"dataDictionary": "gone.csv"}},
               "layers": {"Layer1": {"cores": ["Core1"]}, "Layer2": {"cores": ["Core2"]}}}
        [m] = missing_layer_inputs(cfg, str(tmp_path), "dataDictionary")
        assert m == "Layer2: dataDictionary file not found: gone.csv (from cores.Core2.dataDictionary)"

    def test_an_absolute_path_is_checked_as_is(self, tmp_path):
        f = tmp_path / "abs.csv"
        f.write_text("x", encoding="utf-8")
        cfg = {"layers": {"Layer1": {"dataDictionary": str(f)}}}
        assert missing_layer_inputs(cfg, "/nowhere", "dataDictionary") == []
