"""What a version's run has found so far, for the Overview while it runs (read only, no new state).

    model   counts from the stored model: functions, globals, units, components -- as soon as Parse
            and Derive have written them (None before, or on a database that keeps no model)
    llm     the LLM's trouble for this version, from the `llm_client` warnings and errors in the live
            log the API holds: attempts that failed and were retried, calls that got nothing in the
            end (their text stays empty), and the latest problem's first line
    parse   the parser's warnings for this version (a missing include, ...)

The LLM count comes from the live log's in-memory buffer (api/services/live_logs.py), so it covers
what the buffer still holds -- the recent hours on a busy server -- and is 0 when the API keeps no
live log (the test suite)."""
from __future__ import annotations

from typing import Any, Dict, Optional

#: How many of the buffer's newest records are looked through.
SCAN = 20_000


def model_counts(db: Any, version_id: str) -> Optional[Dict[str, int]]:
    eng = getattr(db, "_engine", None)
    if eng is None:
        return None
    try:
        from sqlalchemy import func, select
        from api.db.postgres import schema as s
        ev, ent = s.entity_versions, s.entities
        with eng.connect() as cx:
            kinds = dict(cx.execute(
                select(ent.c.kind, func.count())
                .select_from(ev.join(ent, ent.c.entity_id == ev.c.entity_id))
                .where(ev.c.version_id == version_id)
                .group_by(ent.c.kind)).all())
            units = cx.execute(select(func.count()).select_from(s.model_units)
                               .where(s.model_units.c.version_id == version_id)).scalar() or 0
            comps = cx.execute(select(func.count(func.distinct(s.model_components.c.name)))
                               .where(s.model_components.c.version_id == version_id)).scalar() or 0
    except Exception:                                   # noqa: BLE001 - facts are a courtesy
        return None
    functions, globals_ = int(kinds.get("function", 0)), int(kinds.get("global", 0))
    if not (functions or globals_ or units):
        return None                                     # nothing parsed yet
    return {"functions": functions, "globals": globals_, "units": int(units), "components": int(comps)}


def log_facts(version_id: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {"llm": {"failed_calls": 0, "retries": 0, "last_failure": None},
                           "parse": {"warnings": 0}}
    try:
        from api.services import live_logs
        reader = live_logs.get_reader()
        records, _ = reader.tail(SCAN, "WARNING", {"version": version_id})
    except Exception:                                   # noqa: BLE001 - no live log here
        return out
    last = None
    for rec in records:
        logger = str(rec.get("logger") or "")
        if logger.endswith("llm_client"):
            # llm_core/client.py: one warning per failed attempt ("(attempt 1/2)"), then one line
            # for a call that got nothing in the end ("failed after", "empty response after").
            message = str(rec.get("message") or "")
            if "failed after" in message or "empty response after" in message:
                out["llm"]["failed_calls"] += 1
            else:
                out["llm"]["retries"] += 1
            last = rec
        elif logger == "parser" and rec.get("level") == "WARNING":
            out["parse"]["warnings"] += 1
    if last is not None:
        out["llm"]["last_failure"] = {"ts": last.get("ts"),
                                      "message": str(last.get("message") or "").split("\n")[0][:300]}
    return out


def run_facts(db: Any, version_id: str) -> Dict[str, Any]:
    return {"version_id": version_id, "model": model_counts(db, version_id), **log_facts(version_id)}
