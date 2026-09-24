"""Unit tests for `tools/check_llm.py`.

The probe is only worth running if it sends what the pipeline sends, so the first test puts one
config through the engine's `LlmClient` and through the tool and compares the requests. The rest
pin the Ollama failures the tool must name — a prompt Ollama cut to fit numCtx (it reports no
error) and a reasoning model that spends the whole output budget thinking — plus `--only`.
"""
import os
import sys
import time

import pytest
import requests

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (os.path.join(PROJECT_ROOT, "tools"), os.path.join(PROJECT_ROOT, "engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import check_llm as T                       # noqa: E402  (tools/ must be on sys.path first)
from core import config as core_config     # noqa: E402
from llm_core.client import from_config    # noqa: E402

LLM = {"provider": "ollama", "baseUrl": "http://ollama.test:11434", "defaultModel": "m",
       "timeoutSeconds": 30, "numCtx": 4096, "retries": 0, "rateLimitSeconds": 3.0}
ANSWER = {"response": "OK", "prompt_eval_count": 5000, "done_reason": "stop"}


class _Reply:
    status_code = 200

    def __init__(self, body):
        self._body = body
        self.text = str(body)

    def json(self):
        return dict(self._body)

    def raise_for_status(self):
        pass


def _capture(monkeypatch, body):
    """Answer every POST with `body`; return the list its (url, kwargs) pairs land in."""
    posted = []
    monkeypatch.setattr(requests, "post",
                        lambda url, **kw: posted.append((url, kw)) or _Reply(body))
    return posted


def _run(monkeypatch, body, *argv, llm=LLM):
    """Run the tool with `llm` as the resolved config. Returns (exit code, what it posted)."""
    monkeypatch.setattr(core_config, "load_config", lambda *_a, **_k: {"llm": dict(llm)})
    monkeypatch.setattr(core_config, "load_llm_config", lambda _cfg: dict(llm))
    posted = _capture(monkeypatch, body)
    return T.main(list(argv)), posted


def test_the_probe_sends_what_the_engine_sends(monkeypatch):
    monkeypatch.delenv("LLM_FAKE_RESPONSES", raising=False)
    monkeypatch.setattr(time, "sleep", lambda _s: pytest.fail("nothing sleeps on Ollama"))
    rc, probe = _run(monkeypatch, ANSWER)
    assert rc == 0 and len(probe) == 3
    for url, kw in probe:
        engine = _capture(monkeypatch, ANSWER)
        from_config(dict(LLM)).generate(kw["json"]["system"], kw["json"]["prompt"])
        (e_url, e_kw), = engine
        assert url == e_url == "http://ollama.test:11434/api/generate"
        assert kw["json"] == e_kw["json"]
        assert kw["timeout"] == e_kw["timeout"]
        assert not kw["headers"] and "headers" not in e_kw        # no auth on Ollama


@pytest.mark.parametrize("only", ["description", "DESCRIPTION", "2"])
def test_only_takes_a_name_or_a_number(monkeypatch, only):
    rc, posted = _run(monkeypatch, ANSWER, "--only", only)
    assert rc == 0
    assert [kw["json"]["system"] for _url, kw in posted] == [T._DESC_SYSTEM]


def test_only_rejects_an_unknown_prompt(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, ANSWER, "--only", "huge")
    assert exc.value.code == 2
    assert "tiny, description, large" in capsys.readouterr().err


# Both counts measured on Ollama 0.34 with llama3.2: the large prompt is 2968 tokens at numCtx
# 8192; at numCtx 1024 the model saw 514 of them and still answered, about a prompt it never read.
@pytest.mark.parametrize("seen, cut", [(2968, False), (514, True)])
def test_a_prompt_cut_to_fit_numctx_is_named(monkeypatch, capsys, seen, cut):
    rc, _ = _run(monkeypatch, {"response": "It appears that you have a C++ snippet",
                               "prompt_eval_count": seen, "done_reason": "stop"},
                 "--only", "large")
    out = capsys.readouterr().out
    assert ("PROMPT CUT" in out) is cut
    assert rc == (1 if cut else 0)


def test_a_model_that_spends_the_budget_thinking_is_named(monkeypatch, capsys):
    # gpt-oss on Ollama reasons into `thinking`; the client reads only `response`.
    rc, _ = _run(monkeypatch, {"response": "", "thinking": "The user says: reply OK. So we",
                               "done_reason": "length", "prompt_eval_count": 86},
                 "--only", "tiny", "--max-tokens", "16")
    out = capsys.readouterr().out
    assert rc == 1
    assert "EMPTY RESPONSE" in out
    assert "all 16 output tokens were spent thinking" in out


def test_the_openai_path_still_names_an_empty_reply(monkeypatch, capsys):
    llm = dict(LLM, provider="openai", baseUrl="http://gw.test/v1", rateLimitSeconds=0)
    rc, posted = _run(monkeypatch, {"choices": [{"message": {"content": ""},
                                                 "finish_reason": "length"}]},
                      "--only", "tiny", llm=llm)
    out = capsys.readouterr().out
    assert rc == 1
    assert posted[0][0] == "http://gw.test/v1/chat/completions"
    assert "EMPTY CONTENT" in out and "finish_reason=length" in out
