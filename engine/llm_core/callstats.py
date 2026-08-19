"""Per-run accounting of LLM calls and their outcomes.

`tokens.py` counts tokens, which says how much was *spent*. This says whether the spending
bought anything: how many calls were made, how many came back usable, and how many produced
nothing so the caller fell back to a mechanical result.

That distinction is not academic. A run once took 2062 seconds and produced mechanical
flowchart labels while the gateway answered every request correctly — the replies were being
destroyed after arrival. Token counts looked healthy. Nothing in the report said "1 call in 3
came back empty", which is the one number that would have pointed straight at it.

**Aggregated across processes via the database.** The four phases and the flowchart engine are
separate subprocesses, so an in-memory counter only ever sees a fraction of a run. Each process
records its own tally and flushes it against the version id; the orchestrator sums them for the
end-of-run report.

Never raises and never blocks a run: accounting that can fail a generation is worse than no
accounting.
"""
from __future__ import annotations

import atexit
import os
import threading
from typing import Dict, Tuple

# outcome values
OK = "ok"                  # a usable, non-empty reply
EMPTY = "empty"            # HTTP succeeded but nothing usable came back
ERROR = "error"            # transport/HTTP failure

_LOCK = threading.Lock()
_COUNTS: Dict[Tuple[str, str], int] = {}     # (kind, outcome) -> n
_REGISTERED = False


def record(kind: str, outcome: str, n: int = 1) -> None:
    """Count one call. `kind` is the caller's label — description, label, summary, …"""
    global _REGISTERED
    with _LOCK:
        _COUNTS[(kind or "other", outcome)] = _COUNTS.get((kind or "other", outcome), 0) + n
        if not _REGISTERED:
            atexit.register(flush)
            _REGISTERED = True


def snapshot() -> Dict[Tuple[str, str], int]:
    with _LOCK:
        return dict(_COUNTS)


def reset() -> None:
    with _LOCK:
        _COUNTS.clear()


def totals(counts: Dict[Tuple[str, str], int] = None) -> Dict[str, int]:
    """{calls, ok, empty, error} for a snapshot (defaults to this process's)."""
    c = snapshot() if counts is None else counts
    out = {"calls": 0, OK: 0, EMPTY: 0, ERROR: 0}
    for (_kind, outcome), n in c.items():
        out["calls"] += n
        out[outcome] = out.get(outcome, 0) + n
    return out


def flush() -> None:
    """Persist this process's tally against the run's version. Best-effort."""
    counts = snapshot()
    if not counts:
        return
    try:
        from core.run_context import version_id
        vid = version_id()
        if not vid:
            return
        from core.db import get_engine, is_database_configured
        if not is_database_configured():
            return
        from api.db.postgres import schema as s
        from core.db_util import insert_ignore     # noqa: F401  (import proves the module loads)
        import sqlalchemy as sa
        rows = [{"version_id": vid, "phase": _phase_label(), "kind": k, "outcome": o, "n": n}
                for (k, o), n in counts.items()]
        with get_engine().begin() as cx:
            cx.execute(sa.insert(s.llm_call_stats), rows)
        reset()                                    # so a second flush cannot double-count
    except Exception:
        pass


def _phase_label() -> str:
    """Which process is reporting — the script name is the honest answer."""
    import sys
    return os.path.basename(sys.argv[0] or "") or "unknown"


def load_for_version(conn, version_id: str) -> Dict[Tuple[str, str], int]:
    """Every process's tally for a version, summed. {(kind, outcome) -> n}."""
    import sqlalchemy as sa
    from api.db.postgres import schema as s
    out: Dict[Tuple[str, str], int] = {}
    for r in conn.execute(sa.select(s.llm_call_stats.c.kind, s.llm_call_stats.c.outcome,
                                    s.llm_call_stats.c.n)
                          .where(s.llm_call_stats.c.version_id == version_id)):
        out[(r.kind, r.outcome)] = out.get((r.kind, r.outcome), 0) + int(r.n or 0)
    return out
