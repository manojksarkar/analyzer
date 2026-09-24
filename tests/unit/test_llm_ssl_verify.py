"""`llm.sslVerify` — which certificates an LLM request trusts.

Reported against a company gateway:

    SSLError(SSLCertVerificationError(... CERTIFICATE_VERIFY_FAILED ... unable to get local
    issuer certificate ...))

The gateway's certificate is signed by the company's own CA. The browser trusts it because that CA
is in the Windows certificate store; Python does not, because `requests` uses its own CA list
(certifi) and nothing let the configuration say otherwise.

Three ways out, in order of preference: `"system"` (trust the OS store, as the browser does), a
path to the company CA bundle, or `false` (no verification -- a last resort, announced every run).
The default stays `true`: nobody's security changes unless they ask.

The properties that matter, each easy to lose:

  * every request path passes it -- the client has four, and one without `verify=` is the one
    that fails in production;
  * `llm_enrichment` builds its client WITHOUT `from_config`, so a setting threaded only through
    `from_config` is silently ignored by the phase that makes most of the calls (the throttle was
    once lost exactly this way);
  * `load_llm_config` returns a whitelist, so a key it does not return never reaches the client.
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from core.config import LlmConfigError, load_llm_config
from llm_core import client as client_mod
from llm_core.client import LlmClient, from_config, requests_verify


def _cfg(**llm):
    base = {"provider": "openai", "baseUrl": "https://gw.example/v1", "defaultModel": "m",
            "timeoutSeconds": 5, "numCtx": 2048, "retries": 0, "rateLimitSeconds": 0}
    base.update(llm)
    return {"llm": base}


def _openai_ok():
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json.return_value = {"choices": [{"message": {"content": "ok"}}],
                           "usage": {"prompt_tokens": 0, "completion_tokens": 0}}
    return r


def _ollama_ok():
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json.return_value = {"response": "ok", "message": {"content": "ok"},
                           "prompt_eval_count": 0, "eval_count": 0}
    return r


# ---------------------------------------------------------------------------
# the config value
# ---------------------------------------------------------------------------
class TestTheConfigValue:
    def test_absent_means_verify(self):
        """Nobody's security changes unless they ask."""
        assert load_llm_config(_cfg())["sslVerify"] is True

    def test_it_survives_the_whitelist(self):
        """load_llm_config returns an explicit dict; a key it does not return never reaches
        the client, and the setting would do nothing while looking configured."""
        assert load_llm_config(_cfg(sslVerify=False))["sslVerify"] is False

    def test_system(self):
        assert load_llm_config(_cfg(sslVerify="system"))["sslVerify"] == "system"
        assert load_llm_config(_cfg(sslVerify="SYSTEM"))["sslVerify"] == "system"

    def test_a_ca_bundle_path_is_resolved_and_must_exist(self, tmp_path):
        pem = tmp_path / "company-ca.pem"
        pem.write_text("-----BEGIN CERTIFICATE-----\n")
        assert load_llm_config(_cfg(sslVerify=str(pem)))["sslVerify"] == str(pem)

    def test_a_missing_bundle_fails_at_load_not_per_call(self):
        """Hours into a run, every call failing with the same TLS error is the expensive way to
        find a typo in a path."""
        with pytest.raises(LlmConfigError, match="CA bundle not found"):
            load_llm_config(_cfg(sslVerify="no/such/company-ca.pem"))

    @pytest.mark.parametrize("quoted", ["false", "False", "true", "0", "no", ""])
    def test_a_quoted_boolean_is_refused_not_guessed(self, quoted):
        """A security switch that turns off because of a quoting mistake is the wrong failure."""
        with pytest.raises(LlmConfigError, match="remove the quotes"):
            load_llm_config(_cfg(sslVerify=quoted))

    def test_a_wrong_type_is_refused(self):
        with pytest.raises(LlmConfigError, match="sslVerify"):
            load_llm_config(_cfg(sslVerify=1))

    def test_the_default_config_says_it(self):
        """Present in config.defaults.json, so the option can be found without reading code."""
        import json
        d = json.load(open(os.path.join(PROJECT_ROOT, "engine", "config",
                                        "config.defaults.json"), encoding="utf-8"))
        assert d["llm"]["sslVerify"] is True


# ---------------------------------------------------------------------------
# what requests is given
# ---------------------------------------------------------------------------
class TestWhatRequestsIsGiven:
    def test_true(self):
        assert requests_verify(True) is True

    def test_a_path_is_passed_through(self):
        assert requests_verify("C:/certs/company-ca.pem") == "C:/certs/company-ca.pem"

    def test_false_is_announced_once(self, caplog, monkeypatch):
        monkeypatch.setattr(client_mod, "_UNVERIFIED_ANNOUNCED", False)
        with caplog.at_level("WARNING", logger="llm_core.client"):
            assert requests_verify(False) is False
            assert requests_verify(False) is False
        warnings = [r for r in caplog.records if "NOT verified" in r.getMessage()]
        assert len(warnings) == 1, "announced once per process, not per call"

    def test_system_injects_the_os_store_once(self, monkeypatch):
        calls = []
        fake = MagicMock()
        fake.inject_into_ssl = lambda: calls.append(1)
        monkeypatch.setitem(sys.modules, "truststore", fake)
        monkeypatch.setattr(client_mod, "_SYSTEM_STORE_INJECTED", False)
        assert requests_verify("system") is True
        assert requests_verify("system") is True
        assert calls == [1]

    def test_system_without_truststore_says_how_to_fix_it(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "truststore", None)      # import raises ImportError
        monkeypatch.setattr(client_mod, "_SYSTEM_STORE_INJECTED", False)
        with pytest.raises(RuntimeError, match="pip install truststore"):
            requests_verify("system")


# ---------------------------------------------------------------------------
# every request path carries it
# ---------------------------------------------------------------------------
class TestEveryRequestCarriesIt:
    """The client has four request paths. One without `verify=` is the one that fails."""

    @pytest.mark.parametrize("verify", [False, "C:/certs/company-ca.pem"])
    def test_openai_generate(self, verify):
        c = LlmClient(provider="openai", base_url="https://gw/v1", model="m",
                      rate_limit_seconds=0, ssl_verify=verify)
        with patch("llm_core.client.requests.post", return_value=_openai_ok()) as post:
            c.generate("s", "u")
        assert post.call_args[1]["verify"] == verify

    @pytest.mark.parametrize("verify", [False, "C:/certs/company-ca.pem"])
    def test_openai_messages(self, verify):
        c = LlmClient(provider="openai", base_url="https://gw/v1", model="m",
                      rate_limit_seconds=0, ssl_verify=verify)
        with patch("llm_core.client.requests.post", return_value=_openai_ok()) as post:
            c.call([{"role": "user", "content": "u"}])
        assert post.call_args[1]["verify"] == verify

    def test_ollama_generate(self):
        c = LlmClient(provider="ollama", base_url="https://ollama:11434", model="m",
                      ssl_verify=False)
        with patch("llm_core.client.requests.post", return_value=_ollama_ok()) as post:
            c.generate("s", "u")
        assert post.call_args[1]["verify"] is False

    def test_ollama_messages(self):
        c = LlmClient(provider="ollama", base_url="https://ollama:11434", model="m",
                      ssl_verify=False)
        with patch("llm_core.client.requests.post", return_value=_ollama_ok()) as post:
            c.call([{"role": "user", "content": "u"}])
        assert post.call_args[1]["verify"] is False

    def test_no_request_in_the_client_is_left_without_it(self):
        """Structural, so a FIFTH request path cannot be added without it."""
        import re
        src = open(client_mod.__file__, encoding="utf-8").read()
        calls = [m.start() for m in re.finditer(r"^\s+resp = requests\.post\(", src, re.M)]
        assert len(calls) == 4
        for start in calls:
            end = src.index(")", src.index("timeout=self._timeout", start))
            assert "verify=self._verify" in src[start:end + 40], (
                "a requests.post in llm_core/client.py does not pass verify=")

    def test_the_default_is_unchanged(self):
        c = LlmClient(provider="openai", base_url="https://gw/v1", model="m",
                      rate_limit_seconds=0)
        with patch("llm_core.client.requests.post", return_value=_openai_ok()) as post:
            c.generate("s", "u")
        assert post.call_args[1]["verify"] is True


# ---------------------------------------------------------------------------
# every way a client gets built
# ---------------------------------------------------------------------------
class TestEveryBuilderThreadsIt:
    def test_from_config(self):
        c = from_config(load_llm_config(_cfg(sslVerify=False)))
        assert c._verify is False

    def test_the_enrichment_client_which_bypasses_from_config(self):
        """THE TRAP. `llm_enrichment` builds its own LlmClient, so a setting threaded only
        through from_config would be ignored by the phase that makes most of the calls."""
        import llm_enrichment as le
        le._CLIENT_CACHE.clear()
        c = le._get_client(_cfg(sslVerify=False, descriptions=True))
        assert c is not None and c._verify is False

    def test_the_enrichment_cache_does_not_hand_out_the_wrong_client(self):
        """Keyed on everything that changes the client -- including this."""
        import llm_enrichment as le
        le._CLIENT_CACHE.clear()
        a = le._get_client(_cfg(sslVerify=True, descriptions=True))
        b = le._get_client(_cfg(sslVerify=False, descriptions=True))
        assert a is not b and b._verify is False

    def test_check_llm_uses_the_same_helper(self):
        """`analyzer.py check-llm` exists to reproduce a run's connection problem. If it made its
        request differently, it could pass while the run fails."""
        src = open(os.path.join(PROJECT_ROOT, "tools", "check_llm.py"), encoding="utf-8").read()
        assert "verify=requests_verify(" in src
