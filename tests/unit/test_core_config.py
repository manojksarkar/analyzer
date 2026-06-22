"""Unit tests for src/core/config.py — load_llm_config and format_llm_config_banner."""
import json
import os
import sys
import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from core.config import load_config, load_llm_config, LlmConfigError, format_llm_config_banner


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


class TestLoadConfigAnalyzerConfigOverride:
    """`ANALYZER_CONFIG` env var injects a per-project/per-version config (M1.1)."""

    def test_no_override_reads_default_config(self, monkeypatch):
        monkeypatch.delenv("ANALYZER_CONFIG", raising=False)
        cfg = load_config(PROJECT_ROOT)
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
