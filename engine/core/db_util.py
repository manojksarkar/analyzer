"""Portable bulk-write helpers shared by the model store and the reuse index (doc 10, step 4).

Two things every writer of a SHARED table needs, and one place to get them right.

**Conflict-tolerant insert.** `entities` (unique on `project_id, entity_key`) and
`content_blobs` (keyed on a global `content_hash`) are shared, and both were written
read-then-insert:

    have = SELECT existing…            two jobs both read
    new  = [rows not in have]          both compute the same missing row
    INSERT new                         both insert it -> IntegrityError

`content_blobs` makes that near-certain rather than rare: every entity with an empty payload
hashes to the SAME `content_hash`, so two concurrent jobs on ANY projects collide. That is why
this is a prerequisite for raising JOB_MAX_CONCURRENCY, independent of the rest of doc 10.

**Chunking.** A single `executemany` of 20k rows is one enormous statement. Both helpers chunk,
so behaviour does not change shape between a 100-function fixture and a 20k-function project.

Lives in `core/` because `core/model_store.py` needs it and `core/` may not import from
`incremental/`; `incremental/pg_stores.py` imports it from here so there is one implementation.
"""
from __future__ import annotations

from typing import Any, List

from sqlalchemy import insert as _plain_insert

# Rows per statement. 5000 matches the bound pg_stores already used for IN-clauses: big enough
# that batching is still the point, small enough to stay well inside driver parameter limits.
MAX_ROWS_PER_STATEMENT = 5000


def _chunks(rows: List[Any], size: int = MAX_ROWS_PER_STATEMENT):
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


# PostgreSQL stores no NUL in `text` and none in `jsonb` — the type system has no
# representation for it, so the driver raises rather than truncating:
#
#     psycopg.errors.UntranslatableCharacter: unsupported Unicode escape sequence
#     DETAIL: \u0000 cannot be converted to text.
#
# Python strings and JSON files hold one happily, so a NUL that arrives in a doc comment,
# a `returnExpr` sliced out of source, or an LLM response travels the whole pipeline
# unnoticed and kills the run at the last step — after the parse and every LLM call have
# been paid for. Seen on a real project: 17 minutes and 3.7M tokens spent, then Phase 2
# died on `INSERT INTO content_blobs`, one NUL inside one description.
#
# A NUL is never meaningful in text we store, so drop it rather than failing. Doing it here
# means no writer has to remember: both bulk helpers below go through it.
_NUL = "\x00"

# Counted, not silent — a run should be able to say the data was repaired.
scrub_stats = {"strings": 0}


def scrub_nulls(value: Any) -> Any:
    """Return `value` with every NUL removed from every string inside it.

    Recurses through dicts and lists so a JSONB payload is covered as well as a plain
    column. Returns the ORIGINAL object when there is nothing to change, so the common
    case costs one `in` test per string and allocates nothing.
    """
    if isinstance(value, str):
        if _NUL not in value:
            return value
        scrub_stats["strings"] += 1
        return value.replace(_NUL, "")
    if isinstance(value, dict):
        cleaned = None
        for k, v in value.items():
            ck, cv = scrub_nulls(k), scrub_nulls(v)
            if ck is not k or cv is not v:
                if cleaned is None:
                    cleaned = dict(value)
                if ck is not k:
                    cleaned.pop(k, None)
                cleaned[ck] = cv
        return cleaned if cleaned is not None else value
    if isinstance(value, list):
        cleaned = None
        for i, v in enumerate(value):
            cv = scrub_nulls(v)
            if cv is not v:
                if cleaned is None:
                    cleaned = list(value)
                cleaned[i] = cv
        return cleaned if cleaned is not None else value
    return value


def _scrubbed(rows: list) -> list:
    """The rows with NULs removed. Same list object when nothing needed changing."""
    out = None
    for i, row in enumerate(rows):
        clean = scrub_nulls(row)
        if clean is not row:
            if out is None:
                out = list(rows)
            out[i] = clean
    return out if out is not None else rows


def insert_ignore(conn, table, rows: list) -> None:
    """Bulk insert, skipping rows that collide (first writer wins).

    Portable: Postgres and SQLite both support ON CONFLICT DO NOTHING in SQLAlchemy 2.0, and
    the dialect branch is the ONLY place the two backends differ (doc 10, D10-2). Any other
    dialect falls back to a plain insert, which will raise on a genuine collision — honest
    rather than silently wrong.
    """
    if not rows:
        return
    rows = _scrubbed(rows)
    name = conn.engine.dialect.name
    if name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as _ins
    elif name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as _ins
    else:                                            # pragma: no cover
        for chunk in _chunks(rows):
            conn.execute(_plain_insert(table), chunk)
        return
    stmt = _ins(table).on_conflict_do_nothing()
    for chunk in _chunks(rows):
        conn.execute(stmt, chunk)


def insert_chunked(conn, table, rows: list) -> None:
    """Bulk insert in chunks, WITHOUT conflict tolerance.

    For per-version tables (`entity_versions`, `model_edges`, …) where a collision is a real
    bug — two writers persisting the same version at once — and must not be swallowed. The
    version's rows are cleared before a re-persist, so a conflict here means something
    genuinely unexpected.
    """
    if not rows:
        return
    rows = _scrubbed(rows)
    for chunk in _chunks(rows):
        conn.execute(_plain_insert(table), chunk)
