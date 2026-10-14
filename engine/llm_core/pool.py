"""LLM lanes: several endpoints or keys, each with its own limits, and failover between them.

Today every OpenAI-shaped call holds one process-wide lock and sleeps `rateLimitSeconds` AFTER it
returns (client.py `_OPENAI_LOCK`, `_throttle`): one request in flight, and each costs its own
latency plus the pause. A lane says how one endpoint+key may be used:

    maxConcurrent     requests in flight at once on this lane (default 1)
    rateLimitSeconds  the gap the gateway needs between requests on this lane
    pacing            "after": the gap runs from when a request ENDS (today's behaviour);
                      "start": from when it STARTS, so the next request goes as soon as the
                      gateway would accept it -- with a 3 s gateway and 5 s answers, a call
                      every ~5 s instead of every ~8 s, on the same key

A request takes the lane that can start soonest. A lane that answers 429/503 (or times out, or
refuses the connection) cools down -- `Retry-After` if the gateway sent one (at most
RETRY_AFTER_CAP), else a growing pause -- and the next attempt goes to another lane at once.

A lane learns what the gateway really allows:
- refused with several calls in flight: one fewer at a time (adaptive concurrency, RAISE_AFTER);
- paced "start" and refused with its one call in flight on more than GAP_GROW_SHARE of a window
  of GAP_WINDOW calls: the gateway counts its gap from a call's END (it then refuses about every
  other call). The lane adds GAP_STEP of the interval as a pause after every call -- the whole
  interval at once when half the window was refused that way -- up to the whole interval: pacing
  "after", today's behaviour (one warning when it gets there). GAP_EASE_WINDOWS clean windows in a
  row take a step off; a step off that brings the refusals back doubles the clean windows the next
  one waits for, so a lane that needs nearly the whole gap stops trying less. A refusal now and
  then with one call in flight -- the gateway still counting the last call when the next arrives
  at once -- moves nothing. Three simpler rules misread that and gave start pacing's gain away
  (L4c-L4e in the plan);
- a lane whose key the gateway refuses (401/403) is not used again in the run, while another lane
  is left -- a revoked key costs one attempt, not a share of every call (one warning).

Config (all optional; without it there is one lane, today's behaviour exactly):

    "llmServer": { "pacing": "start",
                   "lanes": [ {"apiKey": "K1"}, {"apiKey": "K2", "maxConcurrent": 2},
                              {"baseUrl": "http://other-gateway", "apiKey": "K3"} ] }

Both are the server's (config.local.json). A lane's missing fields come from the `llmServer` block. `LLM_API_KEYS=k1,k2` makes one lane per key on
the configured baseUrl. Lanes are shared by every client in the process, as the lock was: phases
run one at a time, so per process is per run -- except two web jobs at once (B6), which still
need a limit shared across processes.
"""
from __future__ import annotations

import atexit
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

BUSY_STATUSES = (429, 502, 503, 504, 529)      # 529: the Claude API's "overloaded"
AUTH_STATUSES = (401, 403)
# A Retry-After longer than this is not believed: a lane resting an hour holds the whole run.
RETRY_AFTER_CAP = 120.0
# Start pacing's learnt pause after a call ends, decided once per window of calls.
GAP_WINDOW = 20
GAP_GROW_SHARE = 0.25
GAP_EASE_WINDOWS = 5
GAP_STEP = 0.1

log = logging.getLogger(__name__)


@dataclass
class Lane:
    name: str
    endpoint: str
    api_key: Optional[str]
    headers: Dict[str, str] = field(default_factory=dict)
    max_concurrent: int = 1
    interval: float = 0.0
    pacing: str = "after"
    inflight: int = 0
    next_start: float = 0.0
    cool_until: float = 0.0
    strikes: int = 0                    # busy answers in a row: the cool-down grows with them
    effective: int = 0                  # calls allowed in flight now: lowered by busy answers
    ok_streak: int = 0                  # answers in a row since the last busy one
    dead: bool = False                  # its key was refused (401/403): skipped while others live
    after_gap: float = 0.0              # start pacing: the pause after a call ends, learnt
    win_calls: int = 0                  # this window: calls ended,
    win_lone: int = 0                   # ... and refused with this one call in flight
    clean_windows: int = 0              # windows in a row without such a refusal
    ease_after: int = 0                 # clean windows the next step off waits for (doubles)
    just_eased: bool = False            # the last window took a step off
    gap_warned: bool = False
    stats: Dict[str, float] = field(default_factory=lambda: {"calls": 0, "busy": 0, "busy_alone": 0, "waited": 0.0})


# Adaptive concurrency: a lane that is refused as busy while it has several calls in flight takes
# one fewer at a time (down to 1) -- it learns the gateway's real limit, and a lane configured for
# more than the gateway allows corrects itself; after this many answers in a row it tries one more
# again, up to its configured maxConcurrent.
RAISE_AFTER = 50


class LanePool:
    def __init__(self, lanes: List[Lane]):
        if not lanes:
            raise ValueError("LanePool needs at least one lane")
        for lane in lanes:
            lane.effective = lane.effective or lane.max_concurrent
        self.lanes = lanes
        self._cond = threading.Condition()

    def acquire(self, timeout: float = 600.0) -> Tuple[Lane, float]:
        """The lane that can start soonest, reserved; and the seconds waited for it."""
        t0 = time.monotonic()
        deadline = t0 + timeout
        with self._cond:
            while True:
                now = time.monotonic()
                best, best_t = None, None
                # every lane refused its key: try them anyway, so the error reaches the caller
                for lane in [l for l in self.lanes if not l.dead] or self.lanes:
                    if lane.inflight >= lane.effective:
                        continue
                    t = max(now, lane.next_start, lane.cool_until)
                    # ties: the lane with fewer requests in flight, so the work spreads
                    if best is None or t < best_t or (t == best_t and lane.inflight < best.inflight):
                        best, best_t = lane, t
                if best is not None and best_t <= now:
                    best.inflight += 1
                    if best.pacing == "start":
                        best.next_start = now + best.interval
                    best.stats["calls"] += 1
                    waited = now - t0
                    best.stats["waited"] += waited
                    return best, waited
                if now >= deadline:
                    raise TimeoutError("no LLM lane became free in time")
                wait = (best_t - now) if best is not None else None
                self._cond.wait(min(wait, deadline - now) if wait is not None else min(1.0, deadline - now))

    def release(self, lane: Lane, *, busy: bool = False, retry_after: Optional[float] = None,
                dead: bool = False) -> None:
        """A request on `lane` ended; `busy`: the gateway refused it (429/503) or did not answer;
        `dead`: it refused the lane's key (401/403)."""
        with self._cond:
            now = time.monotonic()
            had = lane.inflight
            lane.inflight -= 1
            if lane.pacing == "after":
                lane.next_start = max(lane.next_start, now + lane.interval)
            elif lane.after_gap > 0:
                lane.next_start = max(lane.next_start, now + lane.after_gap)
            if dead and not lane.dead and len(self.lanes) > 1:
                lane.dead = True
                log.warning("LLM lane %s: the gateway refused its key -- not used again in this run",
                            lane.name)
            if busy:
                lane.strikes += 1
                lane.stats["busy"] += 1
                lane.ok_streak = 0
                if had > 1 and lane.effective > 1:
                    lane.effective -= 1
                elif had == 1:
                    lane.stats["busy_alone"] += 1       # nothing else in flight: the pacing's
                if retry_after is not None:
                    pause = min(max(retry_after, 0.0), RETRY_AFTER_CAP)
                else:
                    pause = min(60.0, max(lane.interval, 1.0) * 2 ** (lane.strikes - 1))
                lane.cool_until = max(lane.cool_until, now + pause)
            else:
                lane.strikes = 0
                lane.ok_streak += 1
                if lane.ok_streak >= RAISE_AFTER and lane.effective < lane.max_concurrent:
                    lane.effective += 1
                    lane.ok_streak = 0
            if lane.pacing == "start" and lane.interval > 0:
                self._learn_gap(lane, lone=busy and had == 1)
            self._cond.notify_all()

    @staticmethod
    def _learn_gap(lane: Lane, *, lone: bool) -> None:
        lane.win_calls += 1
        lane.win_lone += 1 if lone else 0
        if lane.win_calls < GAP_WINDOW:
            return
        step = GAP_STEP * lane.interval
        ease_after = lane.ease_after or GAP_EASE_WINDOWS
        if lane.win_lone > GAP_GROW_SHARE * lane.win_calls:
            # half the window refused: no doubt left -- the whole gap at once, then ease down
            heavy = lane.win_lone >= 2 * GAP_GROW_SHARE * lane.win_calls
            lane.after_gap = lane.interval if heavy else min(lane.interval, lane.after_gap + step)
            lane.clean_windows = 0
            if lane.just_eased:                 # that step off was one too many
                lane.ease_after = min(8 * GAP_EASE_WINDOWS, 2 * ease_after)
            if lane.after_gap >= lane.interval and not lane.gap_warned:
                lane.gap_warned = True
                log.warning("LLM lane %s: refused with one call in flight until it paused the whole %.1fs "
                            "after each call -- the gateway counts its gap from a call's end, and start "
                            "pacing gains nothing on this lane", lane.name, lane.interval)
        elif lane.win_lone == 0:
            lane.clean_windows += 1
            if lane.clean_windows >= ease_after and lane.after_gap > 0:
                lane.after_gap = max(0.0, lane.after_gap - step)
                lane.clean_windows = 0
                lane.just_eased = True
                lane.win_calls = lane.win_lone = 0
                return
        else:
            lane.clean_windows = 0
        lane.just_eased = False
        lane.win_calls = lane.win_lone = 0

    def live_lanes(self, besides: Optional[Lane] = None) -> int:
        """Lanes whose key was not refused, `besides` not counted: whether a retry has elsewhere to go."""
        with self._cond:
            return sum(1 for lane in self.lanes if not lane.dead and lane is not besides)

    def summary(self) -> str:
        """One line per lane for the log: calls, busy answers, time waited."""
        from core.durations import human
        with self._cond:
            return "; ".join(
                f"{l.name}: {int(l.stats['calls'])} calls, {int(l.stats['busy'])} busy, "
                f"{human(l.stats['waited'])} waited, pacing {l.pacing}"
                f"{f' (+{l.after_gap:.2f}s after each call)' if l.after_gap else ''}"
                f"{', key refused' if l.dead else ''}"
                for l in self.lanes)


_POOLS: Dict[Tuple, LanePool] = {}
_POOLS_LOCK = threading.Lock()


def shared_pool(lanes: List[Lane]) -> LanePool:
    """One pool per set of lanes per process: every client built from the same config shares it,
    as every client shared the one lock before."""
    key = tuple((l.endpoint, l.api_key or "", l.max_concurrent, l.interval, l.pacing) for l in lanes)
    with _POOLS_LOCK:
        pool = _POOLS.get(key)
        if pool is None:
            pool = _POOLS[key] = LanePool(lanes)
            # what each lane did, once, when the phase ends: the place to see a busy gateway,
            # a refused key or the pause start pacing learnt
            atexit.register(_log_summary, pool)
        return pool


def _log_summary(pool: LanePool) -> None:
    # At exit the stream a handler holds may be closed already (pytest's capture, interpreter
    # teardown): as core/logging_setup._emit_token_report, a failed write stays silent.
    prev = logging.raiseExceptions
    logging.raiseExceptions = False
    try:
        log.info("LLM lanes: %s", pool.summary())
    except Exception:
        pass
    finally:
        logging.raiseExceptions = prev


def lanes_from_config(llm_cfg: Dict, *, provider: str, endpoint: str, api_key: Optional[str],
                      headers: Dict[str, str], rate_limit: float) -> List[Lane]:
    """The lanes the config asks for; one lane of today's behaviour when it asks for none."""
    pacing = str(llm_cfg.get("pacing") or "after").lower()
    if pacing not in ("after", "start"):
        pacing = "after"
    # Ollama never had a pause; keep it that way.
    base_interval = rate_limit if provider in ("openai", "anthropic") else 0.0
    specs = list(llm_cfg.get("lanes") or [])
    env_keys = ([k.strip() for k in os.environ.get("LLM_API_KEYS", "").split(",") if k.strip()]
                if provider != "anthropic" else [])         # Claude: config.local.json's keys only
    if not specs and env_keys:
        specs = [{"apiKey": k} for k in env_keys]
    if not specs:
        return [Lane("main", endpoint, api_key, dict(headers), 1, base_interval, pacing)]
    lanes = []
    for i, spec in enumerate(specs):
        ep = endpoint
        if spec.get("baseUrl"):
            base = str(spec["baseUrl"]).rstrip("/")
            from .client import provider_endpoint
            ep = provider_endpoint(provider, base)
        h = dict(headers)
        h.update(spec.get("customHeaders") or {})
        # The gap and the pacing are the llm block's, the same on every lane: one less thing to
        # get wrong per lane.
        lanes.append(Lane(
            name=str(spec.get("name") or f"lane{i + 1}"), endpoint=ep,
            api_key=spec.get("apiKey") or api_key, headers=h,
            max_concurrent=max(1, int(spec.get("maxConcurrent") or 1)),
            interval=float(base_interval), pacing=pacing,
        ))
    return lanes
