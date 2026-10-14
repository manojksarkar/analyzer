"""Parse translation units ahead, on worker threads, and hand them back in the original order.

Phase 1 parses every translation unit twice and walks each AST six times. On the sample (218
TUs) libclang's own parse is about a third of the time and the Python walks the rest; code with
large headers parses longer. The visitors read and write state shared across files, and many of
its rules are "the first file wins" -- so they keep running one file at a time, in today's order.
Only the parse moves: up to `workers` threads parse the next files while the main thread visits
the current one. The model comes out exactly as a sequential run makes it (checked field by
field and in list order, tools/perf/compare_models.py).

Why threads work: `clang.cindex` calls libclang through ctypes (CDLL), which releases the GIL for
the length of the C call, so parses on different threads run at the same time. A libclang index
must not be used by two threads at once: `workers` indexes are made up front, on the calling
thread, and each parse borrows one.

Memory: a parsed translation unit holds its whole AST. At most `workers + ahead` are alive at
once: the one being visited, the ones being parsed, the ones parsed and waiting.
"""
from __future__ import annotations

import os
import queue
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Deque, Iterable, Iterator, List, Optional, Tuple


def default_workers() -> int:
    """For a caller that passes no `workers`: `ANALYZER_PARSE_WORKERS` if set, else 1 -- today's
    sequential parse. The parser passes the config's `speedups.parseWorkers` instead (with the same
    environment override: core.config.load_parse_config). Opt-in until the office code has had a
    clean run with it (30 clean runs on the sample: docs/design/PIPELINE_SPEED_PLAN.md §4.1); a
    sensible value is half the CPUs, at most 8 (each parsed-ahead TU holds its AST in memory)."""
    raw = os.environ.get("ANALYZER_PARSE_WORKERS", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return 1


def prefetch(paths: Iterable[str], parse: Callable[[Any, str], Any], index_factory: Callable[[], Any],
             workers: Optional[int] = None, ahead: int = 2) -> Iterator[Tuple[str, Any, Optional[BaseException]]]:
    """Yield `(path, result, error)` for every path, in the order given.

    `parse(index, path)` runs on a worker thread, with an index made on the calling thread and lent
    to one parse at a time; whatever it raises comes back as `error` (with `result` None), so the
    caller handles it in order, as before.
    With `workers` <= 1 it parses inline on the calling thread: today's behaviour exactly.
    """
    paths = list(paths)
    n = default_workers() if workers is None else max(1, workers)
    if n <= 1:
        index = index_factory()
        for p in paths:
            try:
                yield p, parse(index, p), None
            except BaseException as exc:                       # noqa: BLE001 - handed back in order
                yield p, None, exc
        return

    # Every index is made here, on the calling thread, and lent to one parse at a time: no
    # libclang index is created or freed on a worker thread. (A run whose workers made their own
    # crashed once with an access violation while writing the model -- 1 in 5 runs.) A TU keeps
    # its index alive (cindex `TranslationUnit.index`), so an index outlives what it parsed.
    indexes: List[Any] = [index_factory() for _ in range(n)]
    lend: "queue.Queue[Any]" = queue.Queue()
    for idx in indexes:
        lend.put(idx)

    def job(p: str) -> Any:
        idx = lend.get()
        try:
            return parse(idx, p)
        finally:
            lend.put(idx)

    window = n + max(0, ahead)
    pending: Deque[Tuple[str, Future]] = deque()
    with ThreadPoolExecutor(max_workers=n, thread_name_prefix="tu-parse") as pool:
        it = iter(paths)
        try:
            for p in it:
                pending.append((p, pool.submit(job, p)))
                if len(pending) >= window:
                    break
            while pending:
                p, fut = pending.popleft()
                try:
                    res, err = fut.result(), None
                except BaseException as exc:                   # noqa: BLE001 - handed back in order
                    res, err = None, exc
                nxt = next(it, None)
                if nxt is not None:
                    pending.append((nxt, pool.submit(job, nxt)))
                yield p, res, err
                del res                                         # free the AST before the next one
        finally:
            for _, fut in pending:                              # a caller that stops early
                fut.cancel()
