"""perf/pipeline-speed: the parse-ahead prefetcher (core/tu_prefetch.py), the LLM lanes
(llm_core/pool.py) and the description stage's rounds (llm_enrichment._run_in_rounds)."""
import os
import sys
import threading
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (ROOT, os.path.join(ROOT, "engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.tu_prefetch import prefetch  # noqa: E402
from llm_core.pool import Lane, LanePool, lanes_from_config  # noqa: E402


# ── prefetch ─────────────────────────────────────────────────────────────────────────────────

def test_results_come_back_in_the_order_given_whatever_finishes_first():
    delays = {"a": 0.20, "b": 0.01, "c": 0.10, "d": 0.0}
    out = list(prefetch(list(delays), lambda idx, p: (time.sleep(delays[p]), p.upper())[1], object, workers=4))
    assert [(p, r, e) for p, r, e in out] == [("a", "A", None), ("b", "B", None), ("c", "C", None), ("d", "D", None)]


def test_parses_overlap_on_several_threads():
    live, peak, lock = [0], [0], threading.Lock()

    def parse(idx, p):
        with lock:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        time.sleep(0.05)
        with lock:
            live[0] -= 1
        return p
    t0 = time.monotonic()
    assert [p for p, _, _ in prefetch([str(i) for i in range(8)], parse, object, workers=4)] == [str(i) for i in range(8)]
    assert peak[0] > 1 and time.monotonic() - t0 < 8 * 0.05


def test_an_index_is_made_on_the_calling_thread_and_never_used_by_two_parses_at_once():
    made_on, in_use, clash, lock = [], set(), [], threading.Lock()

    def factory():
        made_on.append(threading.get_ident())
        return object()

    def parse(idx, p):
        with lock:
            if id(idx) in in_use:
                clash.append(p)
            in_use.add(id(idx))
        time.sleep(0.01)
        with lock:
            in_use.discard(id(idx))
        return p
    list(prefetch([str(i) for i in range(24)], parse, factory, workers=3))
    assert made_on == [threading.get_ident()] * 3, "all indexes made up front, here"
    assert clash == []


def test_an_error_comes_back_in_its_place_and_the_rest_go_on():
    def parse(idx, p):
        if p == "bad":
            raise ValueError("cannot parse")
        return p
    out = list(prefetch(["ok1", "bad", "ok2"], parse, object, workers=2))
    assert [p for p, _, _ in out] == ["ok1", "bad", "ok2"]
    assert isinstance(out[1][2], ValueError) and out[1][1] is None and out[2][1] == "ok2"


def test_one_worker_parses_inline_as_before():
    threads = set()
    list(prefetch(["a", "b"], lambda idx, p: threads.add(threading.get_ident()), object, workers=1))
    assert threads == {threading.get_ident()}


def test_a_caller_that_stops_early_leaves_nothing_running():
    started = []

    def parse(idx, p):
        started.append(p)
        time.sleep(0.02)
        return p
    gen = prefetch([str(i) for i in range(50)], parse, object, workers=2, ahead=1)
    next(gen)
    gen.close()
    time.sleep(0.1)
    assert len(started) <= 5, "only the window was parsed ahead"


# ── lanes ────────────────────────────────────────────────────────────────────────────────────

def test_no_lanes_configured_is_one_lane_of_todays_behaviour():
    lanes = lanes_from_config({}, provider="openai", endpoint="http://g/chat/completions", api_key="K",
                              headers={}, rate_limit=3.0)
    assert len(lanes) == 1 and lanes[0].pacing == "after" and lanes[0].interval == 3.0 and lanes[0].max_concurrent == 1


def test_lanes_take_their_missing_fields_from_the_llm_block(monkeypatch):
    monkeypatch.delenv("LLM_API_KEYS", raising=False)
    lanes = lanes_from_config({"pacing": "start", "lanes": [{"apiKey": "K1"}, {"apiKey": "K2", "maxConcurrent": 2},
                                                             {"baseUrl": "http://other/", "rateLimitSeconds": 1}]},
                              provider="openai", endpoint="http://g/chat/completions", api_key="K0",
                              headers={"x": "1"}, rate_limit=3.0)
    assert [(l.api_key, l.max_concurrent, l.interval, l.pacing) for l in lanes] == [
        ("K1", 1, 3.0, "start"), ("K2", 2, 3.0, "start"), ("K0", 1, 1.0, "start")]
    assert lanes[2].endpoint == "http://other/chat/completions" and lanes[0].headers == {"x": "1"}


def test_keys_from_the_environment_make_one_lane_each(monkeypatch):
    monkeypatch.setenv("LLM_API_KEYS", "a, b")
    lanes = lanes_from_config({}, provider="openai", endpoint="http://g/chat/completions", api_key="K0",
                              headers={}, rate_limit=3.0)
    assert [l.api_key for l in lanes] == ["a", "b"]


def _starts(pool, n, hold):
    starts, lock = [], threading.Lock()

    def one():
        lane, _ = pool.acquire(timeout=10)
        with lock:
            starts.append((time.monotonic(), lane.name))
        time.sleep(hold)
        pool.release(lane)
    threads = [threading.Thread(target=one) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return sorted(starts)


def test_after_pacing_waits_the_gap_after_each_call_ends():
    pool = LanePool([Lane("a", "e", None, interval=0.1, pacing="after")])
    s = _starts(pool, 3, hold=0.05)
    gaps = [b[0] - a[0] for a, b in zip(s, s[1:])]
    assert all(g >= 0.14 for g in gaps), gaps          # hold + interval


def test_start_pacing_spaces_starts_not_ends():
    pool = LanePool([Lane("a", "e", None, max_concurrent=3, interval=0.1, pacing="start")])
    s = _starts(pool, 3, hold=0.3)
    gaps = [b[0] - a[0] for a, b in zip(s, s[1:])]
    assert all(0.09 <= g < 0.25 for g in gaps), gaps   # the next starts while the last still runs


def test_two_keys_run_side_by_side():
    pool = LanePool([Lane("k1", "e", "K1", interval=0.0), Lane("k2", "e", "K2", interval=0.0)])
    s = _starts(pool, 2, hold=0.2)
    assert {n for _, n in s} == {"k1", "k2"} and s[1][0] - s[0][0] < 0.1


def test_a_busy_lane_cools_down_and_the_next_call_takes_another():
    pool = LanePool([Lane("k1", "e", "K1"), Lane("k2", "e", "K2")])
    lane, _ = pool.acquire()
    pool.release(lane, busy=True, retry_after=5)
    nxt, waited = pool.acquire(timeout=1)
    assert nxt.name != lane.name and waited < 0.1
    pool.release(nxt)


def test_with_every_lane_cooling_the_call_waits_for_the_first_to_recover():
    pool = LanePool([Lane("k1", "e", "K1")])
    lane, _ = pool.acquire()
    pool.release(lane, busy=True, retry_after=0.2)
    _, waited = pool.acquire(timeout=2)
    assert 0.15 <= waited < 1.0


def test_busy_answers_in_a_row_grow_the_cool_down_and_a_good_one_resets_it():
    pool = LanePool([Lane("k1", "e", "K1", interval=1.0)])
    for expected in (1.0, 2.0, 4.0):
        lane, _ = pool.acquire(timeout=10)
        t = time.monotonic()
        pool.release(lane, busy=True)
        assert abs(lane.cool_until - t - expected) < 0.05
        lane.cool_until = 0.0                               # do not wait it out in a test
    lane, _ = pool.acquire()
    pool.release(lane)
    assert lane.strikes == 0


def test_no_lane_in_time_is_an_error_not_a_hang():
    pool = LanePool([Lane("k1", "e", "K1")])
    pool.acquire()
    with pytest.raises(TimeoutError):
        pool.acquire(timeout=0.1)


# ── description rounds ───────────────────────────────────────────────────────────────────────

def test_a_round_runs_at_once_and_a_cycle_round_in_order():
    import llm_enrichment
    log, lock = [], threading.Lock()

    def work(k):
        time.sleep(0.05 if k in ("a", "b", "c") else 0.0)
        with lock:
            log.append((k, threading.current_thread().name))
    rounds = [(["a", "b", "c"], False), (["x", "y", "z"], True)]
    t0 = time.monotonic()
    llm_enrichment._run_in_rounds(rounds, {"a", "b", "c", "x", "y", "z"}, work, workers=3)
    assert time.monotonic() - t0 < 0.14, "round 1 ran at once"
    assert [k for k, _ in log][3:] == ["x", "y", "z"], "the cycle's round keeps its order"
    assert all(not name.startswith("llm-desc") for k, name in log if k in "xyz")


def test_only_the_wanted_keys_run():
    import llm_enrichment
    done = []
    llm_enrichment._run_in_rounds([(["a", "b"], False), (["c"], False)], {"b", "c"}, done.append, workers=2)
    assert sorted(done) == ["b", "c"]


# ── adaptive concurrency and busy retries ────────────────────────────────────────────────────

def test_a_lane_refused_with_several_in_flight_takes_one_fewer_then_learns_back():
    from llm_core import pool as pool_mod
    lane = Lane("k1", "e", "K1", max_concurrent=3)
    pool = LanePool([lane])
    held = [pool.acquire()[0] for _ in range(3)]
    pool.release(held[0], busy=True, retry_after=0)
    assert lane.effective == 2
    for l in held[1:]:
        pool.release(l)
    for _ in range(pool_mod.RAISE_AFTER):
        l, _ = pool.acquire()
        pool.release(l)
    assert lane.effective == 3, "a run of answers lets it try one more again"


def test_alone_in_flight_a_busy_answer_only_cools_the_lane():
    lane = Lane("k1", "e", "K1", max_concurrent=1)
    pool = LanePool([lane])
    l, _ = pool.acquire()
    pool.release(l, busy=True, retry_after=0)
    assert lane.effective == 1


class _Resp:
    def __init__(self, status, text="ok text"):
        self.status_code, self.headers, self._text = status, {}, text

    def raise_for_status(self):
        import requests
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)

    def json(self):
        return {"choices": [{"message": {"content": self._text}}], "usage": {}}

    @property
    def text(self):
        return "busy"


def _lane_client():
    from llm_core.client import LlmClient
    from llm_core import pool as pool_mod
    pool_mod._POOLS.clear()
    return LlmClient(provider="openai", base_url="http://g", model="m", max_retries=1,
                     rate_limit_seconds=0, lanes=[{"apiKey": "k1"}, {"apiKey": "k2"}], pacing="start")


def test_with_lanes_busy_refusals_do_not_use_up_the_attempts(monkeypatch):
    from unittest.mock import patch
    client = _lane_client()
    for lane in client._pool.lanes:
        lane.interval = 0.0
    replies = [_Resp(503)] * 5 + [_Resp(200)]
    with patch("llm_core.client.requests.post", side_effect=replies), \
         patch("llm_core.pool.LanePool.release", autospec=True,
               side_effect=lambda self, lane, **kw: _release_no_cool(self, lane)):
        assert client.generate("sys", "user") == "ok text"


def _release_no_cool(pool, lane):
    with pool._cond:
        lane.inflight -= 1
        pool._cond.notify_all()


def _posts(client, replies):
    """generate() once against `replies` (a status, or an exception to raise), lanes never
    cooling; the answer and the lanes' keys in the order they were asked."""
    from unittest.mock import patch
    for lane in client._pool.lanes:
        lane.interval = 0.0
    keys, it = [], iter(replies)

    def post(url, headers=None, **kw):
        keys.append((headers or {}).get("Authorization", "").split()[-1])
        r = next(it)
        if isinstance(r, BaseException):
            raise r
        return _Resp(r)
    with patch("llm_core.client.requests.post", side_effect=post),          patch("llm_core.pool.LanePool.release", autospec=True,
               side_effect=lambda self, lane, **kw: _release_no_cool(self, lane)):
        return client.generate("sys", "user"), keys


def test_a_busy_refusal_leaves_every_counted_attempt():
    # 503 free, then three counted failures' worth of room: the third counted try answers
    answer, keys = _posts(_lane_client(), [503, 400, 400, 200])
    assert answer == "ok text" and len(keys) == 4


def test_busy_refusals_are_free_only_so_many_times_per_call():
    from llm_core.client import LlmClient
    answer, keys = _posts(_lane_client(), [503] * 50)
    assert answer is None
    assert len(keys) == LlmClient.BUSY_FREE_RETRIES + 3, "a prompt refused every time ends, as before"


def test_a_timeout_or_a_504_cools_the_lane_but_counts():
    import requests
    for reply in (504, requests.Timeout("slow")):
        answer, keys = _posts(_lane_client(), [reply] * 10)
        assert answer is None and len(keys) == 3, reply


def test_a_refused_key_is_tried_once_then_left_out():
    client = _lane_client()
    statuses = {"k1": 401, "k2": 200}
    from unittest.mock import patch
    for lane in client._pool.lanes:
        lane.interval = 0.0
    keys = []

    def post(url, headers=None, **kw):
        k = headers["Authorization"].split()[-1]
        keys.append(k)
        return _Resp(statuses[k])
    with patch("llm_core.client.requests.post", side_effect=post):
        assert client.generate("sys", "user") == "ok text"
        assert client.generate("sys", "user") == "ok text"
        assert client.generate("sys", "user") == "ok text"
    assert keys == ["k1", "k2", "k2", "k2"]
    assert [l.dead for l in client._pool.lanes] == [True, False]


def test_every_key_refused_fails_after_the_attempts_not_in_a_loop():
    from unittest.mock import patch
    client = _lane_client()
    for lane in client._pool.lanes:
        lane.interval = 0.0
    keys = []

    def post(url, headers=None, **kw):
        keys.append(headers["Authorization"].split()[-1])
        return _Resp(401)
    with patch("llm_core.client.requests.post", side_effect=post):
        assert client.generate("sys", "user") is None
    assert len(keys) == 4, "one free try on the other lane, then 3 counted"
    assert all(l.dead for l in client._pool.lanes)


def test_a_retry_after_beyond_the_cap_is_not_believed():
    from llm_core import pool as pool_mod
    lane = Lane("k1", "e", "K1")
    pool = LanePool([lane])
    l, _ = pool.acquire()
    pool.release(l, busy=True, retry_after=10_000)
    assert lane.cool_until - time.monotonic() <= pool_mod.RETRY_AFTER_CAP + 1


def _calls(pool, n, busy_every):
    for i in range(n):
        l, _ = pool.acquire(timeout=2)
        pool.release(l, busy=bool(busy_every) and i % busy_every == 0, retry_after=0)


def test_a_gateway_counting_from_the_end_teaches_the_whole_gap():
    # L6: about every other call refused with one in flight -- a step per window, up to the interval
    from llm_core import pool as pool_mod
    lane = Lane("k1", "e", "K1", interval=0.01, pacing="start")
    _calls(LanePool([lane]), pool_mod.GAP_WINDOW * 12, busy_every=2)
    assert lane.after_gap == pytest.approx(lane.interval), "the whole gap: pacing 'after', today's"
    assert lane.pacing == "start" and lane.gap_warned


def test_a_refusal_now_and_then_with_one_in_flight_moves_nothing():
    # L5/L4e: the gateway still counting the last call when the next one arrives at once
    from llm_core import pool as pool_mod
    lane = Lane("k1", "e", "K1", interval=0.01, pacing="start")
    _calls(LanePool([lane]), pool_mod.GAP_WINDOW * 10, busy_every=10)
    assert lane.after_gap == 0


def test_a_step_off_that_brings_refusals_back_waits_twice_as_long_next_time():
    from llm_core import pool as pool_mod
    lane = Lane("k1", "e", "K1", interval=0.01, pacing="start")
    lane.after_gap = lane.interval
    pool = LanePool([lane])
    _calls(pool, pool_mod.GAP_WINDOW * pool_mod.GAP_EASE_WINDOWS, busy_every=0)   # a step off
    _calls(pool, pool_mod.GAP_WINDOW, busy_every=2)                               # too much
    assert lane.after_gap == pytest.approx(lane.interval)
    assert lane.ease_after == 2 * pool_mod.GAP_EASE_WINDOWS
    _calls(pool, pool_mod.GAP_WINDOW * pool_mod.GAP_EASE_WINDOWS, busy_every=0)
    assert lane.after_gap == pytest.approx(lane.interval), "not yet: it waits twice as long"


def test_clean_windows_take_a_step_of_the_pause_off_again():
    from llm_core import pool as pool_mod
    lane = Lane("k1", "e", "K1", interval=0.01, pacing="start")
    lane.after_gap = lane.interval
    _calls(LanePool([lane]), pool_mod.GAP_WINDOW * pool_mod.GAP_EASE_WINDOWS, busy_every=0)
    assert lane.after_gap == pytest.approx(lane.interval * (1 - pool_mod.GAP_STEP))


def test_refusals_with_several_in_flight_lower_the_concurrency_not_the_pacing():
    # L4c/L4d: three asked of a gateway that allows one -- refused often, but for the concurrency
    lane = Lane("k1", "e", "K1", max_concurrent=3, interval=0.01, pacing="start")
    pool = LanePool([lane])
    from llm_core import pool as pool_mod
    for _ in range(pool_mod.GAP_WINDOW):
        lane.effective = 3
        held = [pool.acquire(timeout=2)[0] for _ in range(3)]
        for i, l in enumerate(held):
            pool.release(l, busy=i < 2, retry_after=0)
        lane.cool_until = 0.0
    assert lane.effective == 1 and lane.after_gap == 0 and lane.stats["busy_alone"] == 0


def test_after_pacing_learns_no_gap():
    lane = Lane("k1", "e", "K1", interval=0.01, pacing="after")
    _calls(LanePool([lane]), 5, busy_every=1)
    assert lane.after_gap == 0


def test_with_lanes_an_error_that_is_not_busy_still_fails_after_the_attempts():
    from unittest.mock import patch
    client = _lane_client()
    for lane in client._pool.lanes:
        lane.interval = 0.0
    calls = []

    def post(*a, **kw):
        calls.append(1)
        return _Resp(400)
    with patch("llm_core.client.requests.post", side_effect=post):
        assert client.generate("sys", "user") is None
    assert len(calls) == 3, "retries + one per extra lane, no more"


# ── Mermaid in one browser (utils.render_mermaid_many) ───────────────────────────────────────

def _fake_batch(monkeypatch, tmp_path, fail_outs=(), crash=False):
    import json as _json
    import utils
    calls = {"batch": 0, "mmdc": []}

    def run_capture(cmd, timeout=None, shell=False):
        calls["batch"] += 1
        if crash:
            raise OSError("node not found")
        jobs_path = cmd[2]
        jobs = _json.load(open(jobs_path, encoding="utf-8"))
        res = []
        for j in jobs:
            ok = os.path.basename(j["out"]) not in fail_outs
            if ok:
                open(j["out"], "wb").write(b"PNG-batch")
            res.append({"out": j["out"], "ok": ok})
        _json.dump(res, open(jobs_path + ".results.json", "w", encoding="utf-8"))

        class R:
            returncode = 0
        return R()

    def run_mmdc(project_root, mermaid, png_path, **kw):
        calls["mmdc"].append(os.path.basename(png_path))
        open(png_path, "wb").write(b"PNG-mmdc")
        return True
    import core.subprocess_util as su
    monkeypatch.setattr(su, "run_capture", run_capture)
    monkeypatch.setattr(utils, "_run_mmdc", run_mmdc)
    monkeypatch.setattr(utils, "mermaid_in_docker", lambda root: False)
    monkeypatch.setattr(utils, "picture_cache_dir", lambda root, name: str(tmp_path / "cache"))
    monkeypatch.delenv("ANALYZER_MMD_BATCH", raising=False)
    return calls


def test_the_misses_go_to_one_batch_and_a_cache_hit_draws_nothing(monkeypatch, tmp_path):
    import utils
    calls = _fake_batch(monkeypatch, tmp_path)
    items = [("graph A", str(tmp_path / "a.png")), ("graph B", str(tmp_path / "b.png"))]
    assert utils.render_mermaid_many(ROOT, items, scale=2) == {items[0][1]: True, items[1][1]: True}
    assert calls["batch"] == 1 and calls["mmdc"] == []
    for _, p in items:
        os.remove(p)
    calls2 = _fake_batch(monkeypatch, tmp_path)
    assert all(utils.render_mermaid_many(ROOT, items, scale=2).values())
    assert calls2["batch"] == 0, "both come from the cache"


def test_what_the_batch_could_not_draw_goes_through_mmdc(monkeypatch, tmp_path):
    import utils
    calls = _fake_batch(monkeypatch, tmp_path, fail_outs=("b.png",))
    items = [("graph A", str(tmp_path / "a.png")), ("graph B", str(tmp_path / "b.png"))]
    assert all(utils.render_mermaid_many(ROOT, items, scale=2).values())
    assert calls["mmdc"] == ["b.png"]


def test_a_batch_that_cannot_start_falls_back_to_one_by_one(monkeypatch, tmp_path):
    import utils
    calls = _fake_batch(monkeypatch, tmp_path, crash=True)
    items = [("graph A", str(tmp_path / "a.png")), ("graph B", str(tmp_path / "b.png"))]
    assert all(utils.render_mermaid_many(ROOT, items, scale=2).values())
    assert sorted(calls["mmdc"]) == ["a.png", "b.png"]


def test_a_batch_that_cannot_even_write_its_files_falls_back_to_one_by_one(monkeypatch, tmp_path):
    import tempfile
    import utils
    calls = _fake_batch(monkeypatch, tmp_path)

    def no_room(*a, **kw):
        raise OSError("No space left on device")
    monkeypatch.setattr(tempfile, "mkdtemp", no_room)
    items = [("graph A", str(tmp_path / "a.png")), ("graph B", str(tmp_path / "b.png"))]
    assert all(utils.render_mermaid_many(ROOT, items, scale=2).values())
    assert sorted(calls["mmdc"]) == ["a.png", "b.png"] and calls["batch"] == 0


def test_the_switch_off_is_todays_path(monkeypatch, tmp_path):
    import utils
    _fake_batch(monkeypatch, tmp_path)
    monkeypatch.setenv("ANALYZER_MMD_BATCH", "0")
    seen = []
    monkeypatch.setattr(utils, "render_mermaid_cached", lambda root, m, p, **kw: seen.append(p) or True)
    utils.render_mermaid_many(ROOT, [("graph A", str(tmp_path / "a.png"))], scale=2)
    assert seen == [str(tmp_path / "a.png")]


# ── llm_core.parallel ────────────────────────────────────────────────────────────────────────

def test_map_in_order_returns_results_in_item_order_whatever_finishes_first():
    from llm_core.parallel import map_in_order
    out = map_in_order(lambda x: (time.sleep(0.05 if x == 0 else 0.0), x * 10)[1], [0, 1, 2, 3], workers=4)
    assert out == [0, 10, 20, 30]


def test_map_in_order_raises_an_error_in_its_turn():
    from llm_core.parallel import map_in_order

    def f(x):
        if x == 2:
            raise ValueError("two")
        return x
    with pytest.raises(ValueError, match="two"):
        map_in_order(f, [0, 1, 2, 3], workers=3)


def test_each_thread_carries_the_callers_llm_stage():
    import contextvars
    from llm_core.parallel import map_in_order
    stage = contextvars.ContextVar("stage", default="unspecified")
    stage.set("enrich.behaviour_names")
    seen = map_in_order(lambda _x: stage.get(), range(6), workers=3)
    assert set(seen) == {"enrich.behaviour_names"}


def test_one_worker_stays_on_the_calling_thread():
    from llm_core.parallel import map_in_order
    me = threading.get_ident()
    assert set(map_in_order(lambda _x: threading.get_ident(), range(4), workers=1)) == {me}


def test_llm_workers_reads_the_config_and_never_goes_below_one():
    from llm_core.parallel import llm_workers
    assert llm_workers({}) == 1
    assert llm_workers({"llm": {"workers": 4}}) == 4
    assert llm_workers({"llm": {"workers": 0}}) == 1
    assert llm_workers({"llm": {"workers": "x"}}) == 1


# ── one cache entry, one question at a time ──────────────────────────────────────────────────

def _recording_work(seen, delay=0.05):
    def work(k):
        seen.append(("start", k, threading.current_thread().name))
        time.sleep(delay)
        seen.append(("end", k, threading.current_thread().name))
    return work


def test_keys_of_one_cache_entry_run_in_order_on_one_thread():
    import llm_enrichment
    seen = []
    keys = ["a1", "b", "a2", "c", "a3"]
    llm_enrichment._run_in_rounds([(keys, False)], set(keys), _recording_work(seen), workers=4,
                                  chain=lambda k: k[0])
    a = [(ev, k, th) for ev, k, th in seen if k.startswith("a")]
    assert [k for ev, k, _ in a if ev == "start"] == ["a1", "a2", "a3"]
    assert len({th for _, _, th in a}) == 1, "one chain, one thread"
    for k in ("a2", "a3"):                         # each starts only after the one before ended
        prev = {"a2": "a1", "a3": "a2"}[k]
        assert seen.index(("end", prev, a[0][2])) < seen.index(("start", k, a[0][2]))
    starts = [i for i, (ev, _, _) in enumerate(seen) if ev == "start"]
    assert seen[starts[1]][0] == "start" and starts[1] < seen.index(("end", "a1", a[0][2])), \
        "other chains overlap the first"


def test_one_question_asked_at_once_is_asked_of_the_llm_once(monkeypatch):
    import llm_enrichment

    class _Cache(dict):
        def get(self, name, h):
            return dict.get(self, h)

        def put(self, name, h, v):
            self[h] = v
    monkeypatch.setattr(llm_enrichment, "_aux_desc_cache", lambda config: cache)
    cache, asked, out = _Cache(), [], []

    def gen():
        asked.append(1)
        time.sleep(0.1)
        return "answer"
    ts = [threading.Thread(target=lambda: out.append(llm_enrichment._cached_desc({}, "same", gen)))
          for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(asked) == 1 and out == ["answer"] * 4


def test_charts_of_one_label_key_are_labelled_in_order_on_one_thread(monkeypatch):
    from types import SimpleNamespace
    sys.path.insert(0, os.path.join(ROOT, "engine", "flowchart"))
    import flowchart_engine as fe
    seen = []
    sources = {"f1": "void h(){}", "f2": "int g(){}", "f3": "void h(){}", "f4": "int k(){}"}
    monkeypatch.setattr(fe, "_build_cfg", lambda entry, *a: (SimpleNamespace(), sources[entry.key]))

    def label(cfg, entry, *a, **kw):
        seen.append(("start", entry.key, threading.current_thread().name))
        time.sleep(0.05)
        seen.append(("end", entry.key, threading.current_thread().name))
    monkeypatch.setattr(fe, "_label_chart", label)
    monkeypatch.setattr(fe, "_finish_chart", lambda cfg, entry: fe.FlowchartResult(
        function_key=entry.key, qualified_name=entry.key, mermaid_script="dot"))
    monkeypatch.setattr(fe, "_publish_progress", lambda *a, **kw: None)
    monkeypatch.setattr(fe, "LabelGenerator", lambda **kw: object())
    entries = [SimpleNamespace(key=k, qualified_name=k) for k in sources]
    config = SimpleNamespace(llm_max_retries=1, llm_batch_size=4, llm_model="m")
    results, ok, err = fe._process_all_parallel(
        {"a.cpp": entries[:2], "b.cpp": entries[2:]}, 4, 4, 0.0, None, None, None, object(),
        config, "", None, None, None, None, 0)
    assert (ok, err) == (4, 0)
    assert [r.function_key for fr in results for r in fr.flowcharts] == ["f1", "f2", "f3", "f4"]
    th = {k: t for ev, k, t in seen if ev == "start"}
    assert th["f1"] == th["f3"], "one source, one chain"
    assert seen.index(("end", "f1", th["f1"])) < seen.index(("start", "f3", th["f3"]))


def test_an_error_cancels_the_queued_work_instead_of_waiting_for_it():
    from llm_core.parallel import map_in_order
    ran = []

    def fn(x):
        ran.append(x)
        time.sleep(0.05)
        if x == 1:
            raise KeyboardInterrupt          # a Ctrl+C lands in the caller's thread the same way
        return x
    t0 = time.monotonic()
    with pytest.raises(KeyboardInterrupt):
        map_in_order(fn, range(40), workers=2)
    time.sleep(0.2)                          # anything still queued would have started by now
    assert len(ran) < 10, f"{len(ran)} of 40 ran: the queue was drained"
    assert time.monotonic() - t0 < 1.5
