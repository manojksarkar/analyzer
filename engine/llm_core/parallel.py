"""Ask the LLM about several items at once, keeping everything else as a sequential run does it.

How many calls a stage may have in flight follows the lanes (`llm_workers`: 1 without lanes or
start pacing, else twice what the lanes take at once). The lanes (pool.py) decide how many really
go out at once and how fast; the spare workers only have the next question ready.

`map_in_order` returns results in the items' order, so a caller that applies them in a loop writes
the model in the same order as before: the same text, in the same places, whatever finishes first.
Each thread runs in a copy of the caller's context, so its calls are counted under the caller's
LLM stage (llm_core/tokens.py) and not as "unspecified".
"""
from __future__ import annotations

import contextvars
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Callable, Iterable, Iterator, List, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def llm_workers(config: dict) -> int:
    """How many calls a stage keeps in flight: what the config's lanes allow
    (core.config.llm_calls_at_once) -- 1 without `speedups.llms` or start pacing. Not a setting."""
    from core.config import llm_calls_at_once, llm_server, speedup_settings
    return llm_calls_at_once(speedup_settings(config or {}), llm_server(config or {}).get("provider"))


@contextmanager
def executor(workers: int, name: str) -> Iterator[ThreadPoolExecutor]:
    """A thread pool that, when its block is left by an exception -- an error, a Ctrl+C --
    cancels the work still queued and does not wait for it. `with ThreadPoolExecutor()` waits for
    every queued item, and so does Python's own exit: a Ctrl+C in a round of 300 descriptions
    would go on asking the LLM for minutes. Now only the calls already in flight finish."""
    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix=name)
    try:
        yield pool
    except BaseException:
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    pool.shutdown(wait=True)


def map_in_order(fn: Callable[[T], R], items: Iterable[T], workers: int, name: str = "llm") -> List[R]:
    """`[fn(x) for x in items]` with up to `workers` running at once. An exception is raised when
    its item's turn comes, as the sequential loop would have raised it."""
    items = list(items)
    if workers <= 1 or len(items) <= 1:
        return [fn(x) for x in items]
    with executor(workers, name) as pool:
        futures = [pool.submit(contextvars.copy_context().run, fn, x) for x in items]
        return [f.result() for f in futures]
