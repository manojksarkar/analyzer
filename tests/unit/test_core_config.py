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
    load_parse_config, ParseConfigError,
    layer_source, layer_sources, layer_source_origin, core_config_warnings,
    missing_layer_inputs,
    ConfigFileError, LLM_SERVER_KEYS, LLVM_KEYS_BEFORE, RUN_SERVER_BLOCKS, SERVER_BLOCKS,
    has_llm_server, llm_text_wanted, llvm_paths, local_config_notes, local_config_path,
    moved_settings, with_server_settings, without_server_settings,
)
from core.component_files import component_path_problems

_SERVER_ENV = ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_DEFAULT_MODEL", "LLM_TIMEOUT_SECONDS",
               "LLM_NUM_CTX", "LLM_RETRIES", "LLM_API_KEY", "LLM_RATE_LIMIT_SECONDS",
               "ANALYZER_CONFIG", "ANALYZER_DATA_ROOT")


@pytest.fixture(autouse=True)
def _no_server_in_the_environment(monkeypatch):
    """These tests say where each setting comes from: this shell's own must not answer."""
    for name in _SERVER_ENV:
        monkeypatch.delenv(name, raising=False)


def _cfg(**overrides):
    """A config that names an LLM server. An override goes where its key lives: the server's
    own (`llmServer`), or what the LLM writes (`llm`)."""
    base = {"llm": {}, "llmServer": {"provider": "ollama", "baseUrl": "http://localhost:11434",
                                     "defaultModel": "llama3.2", "timeoutSeconds": 120,
                                     "numCtx": 8192, "retries": 1}}
    for key, value in overrides.items():
        base["llmServer" if key in LLM_SERVER_KEYS else "llm"][key] = value
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
        cfg = _cfg(); del cfg["llmServer"]["defaultModel"]
        with pytest.raises(LlmConfigError, match="llmServer.defaultModel"):
            load_llm_config(cfg)

    def test_the_rest_of_the_server_block_may_be_left_out(self):
        r = load_llm_config({"llmServer": {"provider": "openai", "baseUrl": "https://gw/v1",
                                           "defaultModel": "m"}})
        assert (r["timeoutSeconds"], r["numCtx"], r["retries"]) == (300, 8192, 1)
        assert r["rateLimitSeconds"] == 3.0 and r["maxContextTokens"] is None
        assert r["customHeaders"] == {} and r["apiKey"] is None

    def test_what_the_llm_writes_is_read_from_llm(self):
        r = load_llm_config(_cfg(descriptions=False, cacheVersion=7))
        assert r["descriptions"] is False and r["cacheVersion"] == 7
        assert r["behaviourNames"] is True                      # its default, with no key

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

    def test_no_llm_server_raises_and_says_where_one_is_set(self):
        with pytest.raises(LlmConfigError, match="no LLM server is set.*config.local.json"):
            load_llm_config({"llm": {"descriptions": True}})

    def test_a_server_named_the_old_way_is_not_read(self):
        """Until 2026-10-13 the server's keys were in `llm`. They are not read there: the error
        names each one with its place now, instead of running on half a config."""
        old = {"llm": {"provider": "ollama", "baseUrl": "http://localhost:11434",
                       "defaultModel": "llama3.2", "timeoutSeconds": 120, "numCtx": 8192,
                       "retries": 1}}
        with pytest.raises(LlmConfigError) as err:
            load_llm_config(old)
        assert "no LLM server is set" in str(err.value)
        assert "llm.baseUrl -> llmServer.baseUrl" in str(err.value)

    def test_the_environment_alone_names_a_server(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "ollama")
        monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434")
        monkeypatch.setenv("LLM_DEFAULT_MODEL", "env-model")
        cfg = {"llm": {"descriptions": True}}
        assert has_llm_server(cfg)
        assert load_llm_config(cfg)["defaultModel"] == "env-model"

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
        # An injected config's analysis settings are used as they are: what config.local.json
        # says of the same must not bleed in. (Its server blocks are another matter:
        # TestWhichFileASettingIsIn.)
        root = _config_root(tmp_path, local={"views": {"flowcharts": True}, "only": "local's"})
        ovr = tmp_path / "override.json"
        ovr.write_text(json.dumps({"only": "this", "views": {"flowcharts": False}}))
        monkeypatch.setenv("ANALYZER_CONFIG", str(ovr))
        assert load_config(root) == {"only": "this", "views": {"flowcharts": False}}

    def test_missing_override_file_fails_loud(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ANALYZER_CONFIG", str(tmp_path / "nope.json"))
        with pytest.raises(FileNotFoundError, match="ANALYZER_CONFIG"):
            load_config(PROJECT_ROOT)


def _config_root(tmp_path, *, defaults=None, local=None, name="engine"):
    """A folder laid out as the engine's: `<root>/config/config.defaults.json` and, when given,
    `config.local.json`. Its path, as `load_config` takes it."""
    root = tmp_path / name
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "config.defaults.json").write_text(json.dumps(defaults or {}), encoding="utf-8")
    if local is not None:
        text = local if isinstance(local, str) else json.dumps(local)
        (root / "config" / "config.local.json").write_text(text, encoding="utf-8")
    return str(root)


_SERVER = {"provider": "openai", "baseUrl": "https://gw/v1", "defaultModel": "m",
           "customHeaders": {"x-dep-ticket": "credential:SECRET"}}
_LLVM = {"libPath": "C:/LLVM/bin/libclang.dll", "includePath": "C:/LLVM/lib/clang/17/include"}


class TestWhichFileASettingIsIn:
    """One file per kind of setting: config.local.json is THIS SERVER (database, sign-in,
    repository folders, LLM server, LLVM), config.defaults.json is how documents are made.
    The same key in two files is what made "which file do I edit?" a question."""

    @staticmethod
    def _shipped(name):
        from core.config import _strip_json_comments, _strip_trailing_commas
        path = os.path.join(PROJECT_ROOT, "engine", "config", name)
        with open(path, encoding="utf-8") as fh:
            return json.loads(_strip_trailing_commas(_strip_json_comments(fh.read())))

    def test_the_shipped_defaults_hold_no_server_setting(self):
        defaults = self._shipped("config.defaults.json")
        assert not set(defaults) & set(SERVER_BLOCKS)
        assert moved_settings(defaults) == [], "a server key is back in `llm` or `clang`"

    def test_the_local_example_holds_the_server_blocks_and_nothing_else(self):
        example = self._shipped("config.local.json.example")
        assert set(example) == set(SERVER_BLOCKS)
        assert set(example["llmServer"]) <= set(LLM_SERVER_KEYS)
        assert set(example["llvm"]) == set(LLVM_KEYS_BEFORE.values())
        assert not set(example) & set(self._shipped("config.defaults.json")), "a block in both files"
        load_llm_config({"llmServer": example["llmServer"]})      # the example is a valid server

    def test_the_server_blocks_are_the_local_files_alone(self, tmp_path):
        root = _config_root(tmp_path,
                            defaults={"llmServer": {"baseUrl": "from the defaults", "retries": 9},
                                      "llvm": {"libPath": "from the defaults"},
                                      "llm": {"descriptions": True}},
                            local={"llmServer": _SERVER})
        cfg = load_config(root)
        assert cfg["llmServer"] == _SERVER            # not merged with the defaults' block
        assert "llvm" not in cfg                      # the local file has none: there is none
        assert cfg["llm"] == {"descriptions": True}

    def test_without_a_local_file_there_is_no_server(self, tmp_path):
        cfg = load_config(_config_root(tmp_path, defaults={"llmServer": _SERVER, "llm": {}}))
        assert "llmServer" not in cfg and not has_llm_server(cfg)

    def test_a_run_config_gets_the_servers_blocks_as_they_are_now(self, tmp_path, monkeypatch):
        """A project's config is written at onboarding, a version's on its first day. Each held
        the LLM settings of that day, so a key changed in config.local.json never reached the
        next run -- the office asked which of the files to edit."""
        root = _config_root(tmp_path, local={"llmServer": _SERVER, "llvm": _LLVM})
        run_cfg = tmp_path / "workspace.json"
        run_cfg.write_text(json.dumps({
            "layers": {"L": {}},
            "llmServer": {"provider": "ollama", "baseUrl": "of the day it was written"},
            "llm": {"descriptions": True, "baseUrl": "the old place"}}))
        monkeypatch.setenv("ANALYZER_CONFIG", str(run_cfg))

        cfg = load_config(root)
        assert cfg["llmServer"] == _SERVER and cfg["llvm"] == _LLVM
        assert cfg["layers"] == {"L": {}} and cfg["llm"]["descriptions"] is True
        assert load_llm_config(cfg)["baseUrl"] == "https://gw/v1"     # not "the old place"

        rotated = dict(_SERVER, customHeaders={"x-dep-ticket": "credential:NEW"})
        _config_root(tmp_path, local={"llmServer": rotated})
        cfg = load_config(root)
        assert cfg["llmServer"]["customHeaders"] == {"x-dep-ticket": "credential:NEW"}
        assert "llvm" not in cfg, "a block taken out of the local file is gone, not remembered"

    def test_a_local_file_that_cannot_be_read_stops_a_run(self, tmp_path, monkeypatch):
        """A run with no server settings writes no LLM text and says little about it. A typo
        made in the file while a run of days is going must stop its next phase instead."""
        root = _config_root(tmp_path, local='{"llmServer": {"provider": "openai",}')   # no closing }
        assert "llmServer" not in load_config(root)         # the API keeps serving
        run_cfg = tmp_path / "workspace.json"
        run_cfg.write_text("{}")
        monkeypatch.setenv("ANALYZER_CONFIG", str(run_cfg))
        with pytest.raises(ConfigFileError, match="config.local.json could not be read"):
            load_config(root)
        assert any("could not be read" in n for n in local_config_notes(root))

    def test_a_detached_runs_copy_reads_the_installations_file(self, tmp_path, monkeypatch):
        """`--detach` runs a frozen copy of the code, config.local.json included: the copy's is
        the one of the day the run started."""
        copy = _config_root(tmp_path, local={"llmServer": dict(_SERVER, defaultModel="frozen")},
                            name="copy")
        install = tmp_path / "install" / "engine" / "config"
        install.mkdir(parents=True)
        (install / "config.local.json").write_text(json.dumps({"llmServer": _SERVER}))
        assert local_config_path(copy).startswith(copy)
        monkeypatch.setenv("ANALYZER_DATA_ROOT", str(tmp_path / "install"))
        assert load_config(copy)["llmServer"]["defaultModel"] == "m"
        monkeypatch.setenv("ANALYZER_DATA_ROOT", str(tmp_path / "no such data root"))
        assert load_config(copy)["llmServer"]["defaultModel"] == "frozen"

    def test_what_is_written_for_a_project_holds_no_server_setting(self):
        cfg = {"db": {"password": "p"}, "auth": {}, "repositories": {}, "llmServer": _SERVER,
               "llvm": _LLVM, "parse": {"workers": 6}, "views": {"flowcharts": True},
               "llm": {"descriptions": False, "baseUrl": "x", "customHeaders": {"k": "SECRET"},
                       "rateLimitSeconds": 0, "lanes": [{"apiKey": "SECRET"}], "pacing": "start"},
               "clang": {"clangArgs": ["-DX"], "llvmLibPath": "a", "clangIncludePath": "b"}}
        assert without_server_settings(cfg) == {
            "views": {"flowcharts": True}, "llm": {"descriptions": False},
            "clang": {"clangArgs": ["-DX"]}}

    def test_with_server_settings_drops_what_the_config_held(self, tmp_path):
        root = _config_root(tmp_path, local={"llvm": _LLVM})
        cfg = with_server_settings({"llmServer": {"baseUrl": "stale"}, "views": {}}, root)
        assert cfg == {"views": {}, "llvm": _LLVM}
        assert set(RUN_SERVER_BLOCKS) == {"llmServer", "llvm", "parse"}

    def test_how_many_files_are_parsed_at_once_is_this_machines(self, tmp_path, monkeypatch):
        """`parse.workers` follows the cores and memory of the machine that parses, not the
        project: a project's or a version's config does not set it."""
        root = _config_root(tmp_path, local={"parse": {"workers": 6}})
        run_cfg = tmp_path / "workspace.json"
        run_cfg.write_text(json.dumps({"parse": {"workers": 2}, "layers": {}}))
        monkeypatch.setenv("ANALYZER_CONFIG", str(run_cfg))
        monkeypatch.delenv("ANALYZER_PARSE_WORKERS", raising=False)
        assert load_parse_config(load_config(root)) == {"workers": 6}
        _config_root(tmp_path, local={})
        assert load_parse_config(load_config(root)) == {"workers": 1}

    def test_lanes_and_pacing_are_the_servers(self):
        """How many tickets a gateway gives and how it counts its gap are the server's: they are
        `llmServer` keys, and are not read from `llm`."""
        assert {"lanes", "pacing"} <= set(LLM_SERVER_KEYS)
        r = load_llm_config(_cfg(lanes=[{"apiKey": "a"}, {"apiKey": "b"}], pacing="start"))
        assert (len(r["lanes"]), r["pacing"], r["workers"]) == (2, "start", 4)
        old = _cfg()
        old["llm"].update(lanes=[{"apiKey": "a"}], pacing="start")
        r = load_llm_config(old)
        assert (r["lanes"], r["pacing"], r["workers"]) == ([], "after", 1)
        assert "llm.lanes -> llmServer.lanes" in moved_settings(old)

    def test_settings_under_their_old_names_are_named_with_their_place_now(self, tmp_path):
        old = {"llm": {"baseUrl": "https://gw", "customHeaders": {}, "descriptions": True},
               "clang": {"llvmLibPath": "x", "clangArgs": []}}
        assert moved_settings(old) == ["llm.baseUrl -> llmServer.baseUrl",
                                       "llm.customHeaders -> llmServer.customHeaders",
                                       "clang.llvmLibPath -> llvm.libPath"]
        [note] = local_config_notes(_config_root(tmp_path, local=old))
        assert "llm.baseUrl -> llmServer.baseUrl" in note and "not read" in note
        assert local_config_notes(_config_root(tmp_path, local={"llmServer": _SERVER}, name="ok")) == []
        assert local_config_notes(_config_root(tmp_path, name="none")) == []

    def test_llvm_paths(self):
        assert llvm_paths({"llvm": _LLVM}) == (_LLVM["libPath"], _LLVM["includePath"])
        assert llvm_paths({"clang": {"llvmLibPath": "the old place"}}) == ("", "")

    @pytest.mark.parametrize("llm, summarize, wanted", [
        ({}, None, True),                                                   # every default is on
        ({"descriptions": False, "behaviourNames": False, "summarize": False}, None, False),
        ({"descriptions": False, "behaviourNames": False}, False, False),   # --no-llm
        ({"descriptions": False, "behaviourNames": True, "summarize": False}, None, True),
        ({"descriptions": False, "behaviourNames": False, "summarize": False}, True, True),
    ])
    def test_a_run_that_asks_the_llm_for_nothing_needs_no_server(self, llm, summarize, wanted):
        assert llm_text_wanted({"llm": llm}, summarize=summarize) is wanted


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

    def test_lanes_are_counted_and_their_keys_never_printed(self):
        cfg = load_llm_config(_cfg(lanes=[{"apiKey": "sk-lane-1"}, {"apiKey": "sk-lane-2"}],
                                   pacing="start"))
        banner = format_llm_config_banner(cfg)
        assert "2 configured" in banner and "pacing            : start" in banner
        assert "calls at once     : 4" in banner, "twice what two lanes take at once"
        assert "sk-lane" not in banner

    def test_no_lanes_says_one_call_at_a_time(self, monkeypatch):
        monkeypatch.delenv("LLM_API_KEYS", raising=False)
        banner = format_llm_config_banner(load_llm_config(_cfg()))
        assert "none (one lane" in banner and "pacing            : after" in banner
        assert "calls at once     : 1" in banner


class TestParseConfig:
    """Phase 1's one speed setting: the config's `parse.workers`, overridden by the environment,
    as `llm`'s settings are."""

    @pytest.fixture(autouse=True)
    def _no_env(self, monkeypatch):
        monkeypatch.delenv("ANALYZER_PARSE_WORKERS", raising=False)

    def test_nothing_set_is_todays_parse(self):
        assert load_parse_config({}) == {"workers": 1}

    def test_the_config_block_is_read(self):
        assert load_parse_config({"parse": {"workers": 6}}) == {"workers": 6}

    def test_the_environment_overrides_the_config(self, monkeypatch):
        monkeypatch.setenv("ANALYZER_PARSE_WORKERS", "3")
        assert load_parse_config({"parse": {"workers": 6}})["workers"] == 3

    def test_options_that_were_removed_are_ignored_not_an_error(self):
        # fastNullCheck is always on (self-checked); skipCoveredHeaders is gone
        assert load_parse_config({"parse": {"workers": 2, "fastNullCheck": False,
                                            "skipCoveredHeaders": True}}) == {"workers": 2}

    def test_auto_is_half_the_cpus_at_most_eight(self, monkeypatch):
        monkeypatch.setattr(os, "cpu_count", lambda: 32)
        assert load_parse_config({"parse": {"workers": "auto"}})["workers"] == 8
        monkeypatch.setattr(os, "cpu_count", lambda: 6)
        assert load_parse_config({"parse": {"workers": "auto"}})["workers"] == 3

    @pytest.mark.parametrize("block", [{"workers": 0}, {"workers": "many"}])
    def test_a_bad_value_is_an_error_not_a_guess(self, block):
        with pytest.raises(ParseConfigError):
            load_parse_config({"parse": block})

    def test_llm_calls_at_once_are_not_a_setting(self, monkeypatch):
        monkeypatch.delenv("LLM_API_KEYS", raising=False)
        monkeypatch.setenv("LLM_WORKERS", "5")          # no such override
        assert load_llm_config(_cfg(workers=7))["workers"] == 1
        assert load_llm_config(_cfg(lanes=[{"apiKey": "a"}, {"apiKey": "b"}]))["workers"] == 4


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


class TestComponentPathsTheParseWouldMiss:
    """Phase 1 skips a component folder that is not there without a word, so a mistyped, moved
    or wrongly-cased path stopped the run hours later, in Phase 3. The run summary now names
    each one before the parse - with the parser's own rule (core.component_files)."""

    @staticmethod
    def _tree(root, *files):
        for f in files:
            p = root / f
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("", encoding="utf-8")

    @staticmethod
    def _cfg(groups, path="Layer1"):
        return {"layers": {"Layer1": {"path": path, "groups": groups}}}

    def test_a_config_the_checkout_matches_is_quiet(self, tmp_path):
        self._tree(tmp_path, "Layer1/Core/a.cpp", "Layer1/Util/u.h", "Layer1/Main.cpp")
        cfg = self._cfg({"G": {"Core": "Core", "Util": ["Util"], "App": "Main.cpp"}})
        assert component_path_problems(cfg, str(tmp_path)) == ([], [])

    def test_a_path_the_checkout_lacks_is_named_and_its_empty_component_stops_the_run(self, tmp_path):
        # Reproduced: a component with no file is not in the model, and Phase 3 stopped the run
        # on it AFTER the whole parse, blaming the scope. Now the run stops before the parse.
        self._tree(tmp_path, "Layer1/Core/a.cpp")
        warns, errors = component_path_problems(
            self._cfg({"G": {"Core": "Core", "Ghost": "Nowhere"}}), str(tmp_path))
        assert warns == ["Layer1 / G / Ghost: `Layer1/Nowhere` is not in the checkout"]
        assert errors == ["Layer1 / G / Ghost gets no source file: Phase 3 would stop the run on "
                          "it after the whole parse. Fix its path, or take it out"]

    def test_a_path_of_a_component_with_other_files_only_warns(self, tmp_path):
        self._tree(tmp_path, "Layer1/Core/a.cpp")
        warns, errors = component_path_problems(
            self._cfg({"G": {"Core": ["Core", "Gone"]}}), str(tmp_path))
        assert warns == ["Layer1 / G / Core: `Layer1/Gone` is not in the checkout"]
        assert errors == []

    @pytest.mark.parametrize("scope, stops", [
        (None, True),                                               # project: renders all
        ({"type": "project"}, True),
        ({"type": "group", "names": ["Layer1.G"]}, True),
        ({"type": "group", "names": ["Layer1.Other"]}, False),
        ({"type": "group", "names": ["G"]}, True),                  # a bare name, as typed
        ({"type": "component", "names": ["Ghost"]}, True),
        ({"type": "component", "names": ["Layer1.Ghost"]}, True),
        ({"type": "component", "names": ["Layer1.Core"]}, False),
        ({"type": "layer", "names": ["Layer1"]}, False),             # no document is rendered
    ])
    def test_only_a_component_the_run_renders_stops_it(self, tmp_path, scope, stops):
        self._tree(tmp_path, "Layer1/Core/a.cpp", "Layer1/Other/b.cpp")
        cfg = {"layers": {"Layer1": {"path": "Layer1", "groups": {
            "G": {"Core": "Core", "Ghost": "Nowhere"}, "Other": {"Else": "Other"}}}}}
        warns, errors = component_path_problems(cfg, str(tmp_path), scope=scope)
        assert bool(errors) is stops
        if not stops:
            assert "Layer1 / G / Ghost gets no source file: a run that renders it stops in Phase 3" in warns

    def test_a_folder_in_another_case_is_named_on_every_file_system(self, tmp_path):
        self._tree(tmp_path, "Layer1/Core/a.cpp")
        warns, _ = component_path_problems(self._cfg({"G": {"Core": "core"}}), str(tmp_path))
        if os.path.isdir(tmp_path / "Layer1" / "core"):     # Windows: found here, not on Linux
            assert warns == ["Layer1 / G / Core: `Layer1/core` is spelled `Layer1/Core` in the "
                             "checkout - found here, but missed on a case-sensitive file system "
                             "(Linux)"]
        else:
            assert warns[0] == ("Layer1 / G / Core: `Layer1/core` is not in the checkout - "
                                "it has `Layer1/Core`")

    def test_a_file_named_in_another_case_is_found_everywhere(self, tmp_path):
        # The parser matches a file entry in any case, on every file system.
        self._tree(tmp_path, "Layer1/Core/Main.cpp")
        cfg = self._cfg({"G": {"Core": "core/main.CPP"}})
        assert component_path_problems(cfg, str(tmp_path)) == ([], [])

    def test_what_the_parse_does_not_read_is_named(self, tmp_path):
        self._tree(tmp_path, "Layer1/Core/a.cpp", "Layer1/Legacy/old.c", "Layer1/x.c",
                   "Layer1/Stubs/emulator.cpp", "Layer1/notes.txt")
        cfg = self._cfg({"G": {"Core": "Core", "Legacy": "Legacy", "C": "x.c",
                               "Emu": "Stubs/emulator.cpp", "Notes": "notes.txt"}})
        warns, errors = component_path_problems(cfg, str(tmp_path))
        assert "Layer1 / G / Legacy: `Layer1/Legacy` has no file the parse reads" in warns[0]
        assert "Layer1 / G / C: `Layer1/x.c` is a .c file, which the parse does not read" in warns
        assert ("Layer1 / G / Emu: `Layer1/Stubs/emulator.cpp` is skipped by excludeNamePatterns "
                "(emul)") in warns
        assert any(w.startswith("Layer1 / G / Notes: `Layer1/notes.txt` is a file the parse "
                                "does not read") for w in warns)
        # none of the four gets a file the parse reads, so each would stop the run in Phase 3
        assert [e.split(" gets ")[0] for e in errors] == [
            "Layer1 / G / Legacy", "Layer1 / G / C", "Layer1 / G / Emu", "Layer1 / G / Notes"]

    def test_files_a_component_listed_before_took_are_named(self, tmp_path):
        self._tree(tmp_path, "Layer1/Core/a.cpp")
        warns, errors = component_path_problems(
            self._cfg({"G": {"First": "Core", "Second": "Core/a.cpp"}}), str(tmp_path))
        assert warns == []
        assert errors == ["Layer1 / G / Second gets no source file (its files belong to "
                          "Layer1 / G / First, listed before it): Phase 3 would stop the run on "
                          "it after the whole parse. Fix its path, or take it out"]

    def test_a_whole_layer_component_takes_the_layer(self, tmp_path):
        self._tree(tmp_path, "Layer1/a.cpp", "Layer1/sub/b.h")
        assert component_path_problems(self._cfg({"G": {"All": ""}}), str(tmp_path)) == ([], [])

    def test_no_component_with_a_file_stops_the_run(self, tmp_path):
        self._tree(tmp_path, "Other/a.cpp")
        _, errors = component_path_problems(self._cfg({"G": {"Core": "Core"}}), str(tmp_path))
        assert errors[0].startswith("None of the 1 components has a source file"), "first: the likely cause"
        _, errors = component_path_problems(self._cfg({"G": {"Core": "Core"}}), str(tmp_path),
                                            scope={"type": "layer", "names": ["Layer1"]})
        assert len(errors) == 1, "even a run that renders nothing has nothing to parse"

    def test_nothing_is_checked_without_components_or_a_checkout(self, tmp_path):
        assert component_path_problems({"layers": {}}, str(tmp_path)) == ([], [])
        assert component_path_problems(self._cfg({"G": {"Core": "Core"}}),
                                       str(tmp_path / "gone")) == ([], [])

    def test_a_long_report_is_cut(self, tmp_path):
        self._tree(tmp_path, "Layer1/Core/a.cpp")
        groups = {"G": {"Core": "Core", **{f"C{i}": f"Missing{i}" for i in range(30)}}}
        warns, errors = component_path_problems(self._cfg(groups), str(tmp_path))
        assert len(warns) == 30 and len(errors) == 30               # one path, one component each
        warns, _ = component_path_problems(self._cfg(groups), str(tmp_path),
                                           scope={"type": "layer", "names": ["Layer1"]})
        assert len(warns) == 41 and warns[-1] == "... and 20 more"

    def test_the_parser_reads_its_rule_from_the_same_module(self):
        with open(os.path.join(PROJECT_ROOT, "engine", "parser.py"), encoding="utf-8") as f:
            src = f.read()
        assert "from core.component_files import" in src
        assert "def _build_file_component_map" not in src, "a second copy would drift"
