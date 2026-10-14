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


GATEWAY = dict(LLM, provider="openai", baseUrl="http://gw.test/v1", rateLimitSeconds=0,
               customHeaders={"x-dep-ticket": "credential:A", "User-Id": "u1",
                              "Send-System-Name": "svc"})
LANES = [{"name": "ticket-a", "customHeaders": {"x-dep-ticket": "credential:A"}},
         {"customHeaders": {"x-dep-ticket": "credential:B"}},                    # no name: lane2
         {"name": "other", "baseUrl": "http://gw2.test/v1", "apiKey": "K3"}]
OK = {"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]}


def _sent(kw):
    """A request's headers without the two ids that are new on every call."""
    return {k: v for k, v in kw["headers"].items() if k not in T._PER_REQUEST}


def _gateway(monkeypatch, replies, *argv, llm):
    """Run the tool against a gateway that answers each ticket as `replies` says (200 otherwise)."""
    posted = []

    def post(url, **kw):
        posted.append((url, kw))
        ticket = kw["headers"].get("x-dep-ticket")
        reply = _Reply(OK)
        reply.status_code = replies.get(ticket, 200)
        return reply
    monkeypatch.setattr(core_config, "load_config", lambda *_a, **_k: {"llm": dict(llm)})
    monkeypatch.setattr(core_config, "load_llm_config", lambda _cfg: dict(llm))
    monkeypatch.setattr(requests, "post", post)
    return T.main(list(argv)), posted


@pytest.fixture
def no_gateway_env(monkeypatch):
    for name in ("X_DEP_TICKET", "USER_TYPE", "USER_ID", "SEND_SYSTEM_NAME", "LLM_API_KEY",
                 "LLM_API_KEYS", "LLM_FAKE_RESPONSES"):
        monkeypatch.delenv(name, raising=False)


def test_every_lane_gets_the_tiny_prompt_with_the_headers_a_run_sends_on_it(monkeypatch, no_gateway_env):
    from llm_core import pool
    llm = dict(GATEWAY, lanes=LANES)
    rc, probe = _gateway(monkeypatch, {}, "--only", "tiny", llm=llm)
    assert rc == 0 and len(probe) == len(LANES)
    for spec, (url, kw) in zip(LANES, probe):
        # the engine, given this lane alone, sends its one call on it
        monkeypatch.setattr(pool, "_POOLS", {})
        engine = _capture(monkeypatch, OK)
        from_config(dict(GATEWAY, lanes=[spec])).generate("s", "u")
        (e_url, e_kw), = engine
        assert url == e_url
        assert _sent(kw) == _sent(e_kw)
    # a lane's missing header is the block's
    tickets = [kw["headers"]["x-dep-ticket"] for _url, kw in probe]
    assert tickets == ["credential:A", "credential:B", "credential:A"]
    assert probe[2][0] == "http://gw2.test/v1/chat/completions"
    assert probe[2][1]["headers"]["Authorization"] == "Bearer K3"


def test_one_ticket_sends_what_the_engine_sends_too(monkeypatch, no_gateway_env):
    # no lanes: the block's ticket, with the headers the client adds (defaults, the two ids)
    rc, probe = _gateway(monkeypatch, {}, "--only", "tiny", llm=GATEWAY)
    engine = _capture(monkeypatch, OK)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    from_config(dict(GATEWAY)).generate("s", "u")
    assert rc == 0 and len(probe) == 1
    assert probe[0][0] == engine[0][0]
    assert _sent(probe[0][1]) == _sent(engine[0][1])
    assert set(T._PER_REQUEST) <= set(probe[0][1]["headers"])


def test_a_lane_whose_ticket_is_refused_is_named(monkeypatch, capsys, no_gateway_env):
    llm = dict(GATEWAY, lanes=LANES)
    rc, probe = _gateway(monkeypatch, {"credential:B": 401}, llm=llm)
    out = capsys.readouterr().out
    assert rc == 1
    assert "lanes             : 3 -- ticket-a, lane2, other" in out
    assert "LANES: 1 of 3 did not answer -- lane2 (http 401)" in out
    assert "RESULT: 1 of 5 request(s) failed." in out
    # the tiny prompt on each lane, the other two once
    assert [kw["json"]["messages"][0]["content"] for _u, kw in probe].count(T._DESC_SYSTEM) == 1
    assert len(probe) == 5


def test_the_other_prompts_go_on_a_lane_that_answered(monkeypatch, capsys, no_gateway_env):
    llm = dict(GATEWAY, lanes=LANES[:2])
    rc, probe = _gateway(monkeypatch, {"credential:A": 403}, llm=llm)
    assert rc == 1
    assert [kw["headers"]["x-dep-ticket"] for _u, kw in probe] == [
        "credential:A", "credential:B", "credential:B", "credential:B"]
    assert "all 2 answered" not in capsys.readouterr().out


def test_only_another_prompt_asks_one_lane_and_says_the_lanes_are_not_checked(monkeypatch, capsys,
                                                                                no_gateway_env):
    rc, probe = _gateway(monkeypatch, {}, "--only", "description", llm=dict(GATEWAY, lanes=LANES))
    out = capsys.readouterr().out
    assert rc == 0 and len(probe) == 1
    assert "not checked: only the tiny prompt goes to every lane" in out
    assert "LANES:" not in out


def test_one_ticket_reads_as_before(monkeypatch, capsys, no_gateway_env):
    rc, probe = _gateway(monkeypatch, {}, llm=GATEWAY)
    out = capsys.readouterr().out
    assert rc == 0 and len(probe) == 3
    assert "RESULT: all 3 prompt(s) answered." in out
    assert "lane" not in out.lower()


def test_two_lanes_that_send_the_same_ticket_are_named(monkeypatch, capsys, no_gateway_env):
    # the environment's ticket replaces every lane's (llm_core/headers._resolve): two lanes, one ticket
    monkeypatch.setenv("X_DEP_TICKET", "credential:ENV")
    rc, probe = _gateway(monkeypatch, {}, "--only", "tiny", llm=dict(GATEWAY, lanes=LANES[:2]))
    out = capsys.readouterr().out
    assert [kw["headers"]["x-dep-ticket"] for _u, kw in probe] == ["credential:ENV"] * 2
    assert "WARNING: lanes ticket-a and lane2 send the same thing to the same server" in out


def test_the_openai_path_still_names_an_empty_reply(monkeypatch, capsys):
    llm = dict(LLM, provider="openai", baseUrl="http://gw.test/v1", rateLimitSeconds=0)
    rc, posted = _run(monkeypatch, {"choices": [{"message": {"content": ""},
                                                 "finish_reason": "length"}]},
                      "--only", "tiny", llm=llm)
    out = capsys.readouterr().out
    assert rc == 1
    assert posted[0][0] == "http://gw.test/v1/chat/completions"
    assert "EMPTY CONTENT" in out and "finish_reason=length" in out
