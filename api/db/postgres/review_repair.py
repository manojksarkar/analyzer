"""Bring stored documents to review and approval (0015) -- idempotent, any SQL database.

Run by migration 0015 and by `analyzer.py setup` (tools/db_setup.py), because `setup` only adds
missing tables and columns: it never changes a row or adds a constraint, and a database made by it
may have no `alembic_version` to migrate from.

1. A status outside the four (`never`, `unchanged`, NULL -- the old seed and placeholder values)
   becomes `in_review`.
2. A document keeps ONE reviewer, its newest assignment; then the unique index makes one the rule.
3. An approved document with no review record gets one event saying it was approved before the
   record existed -- so its activity is not empty and says why there is no more.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, insert, select, text, update

from . import schema as s

DOC_STATUSES = ("in_review", "submitted", "changes_requested", "approved")
UNIQUE_REVIEWER = "uq_document_assignments_document"


def repair_review(cx) -> dict:
    """Apply the three repairs on connection `cx` (inside the caller's transaction)."""
    d, a, e = s.documents, s.document_assignments, s.document_review_events
    done = {"statuses": 0, "assignments": 0, "events": 0}

    done["statuses"] = cx.execute(
        update(d).where(d.c.status.is_(None) | d.c.status.not_in(DOC_STATUSES))
        .values(status="in_review")).rowcount or 0

    newest: dict = {}
    drop = []
    for r in cx.execute(select(a.c.id, a.c.document_id, a.c.assigned_at)):
        key = (r.assigned_at.replace(tzinfo=None) if r.assigned_at else datetime.min, r.id)
        held = newest.get(r.document_id)
        if held is None:
            newest[r.document_id] = (key, r.id)
        elif key > held[0]:
            drop.append(held[1])
            newest[r.document_id] = (key, r.id)
        else:
            drop.append(r.id)
    if drop:
        cx.execute(delete(a).where(a.c.id.in_(drop)))
    done["assignments"] = len(drop)
    # On a fresh database `create_all` made this as a unique constraint (Postgres backs it with an
    # index of the same name); on an older one it is made here.
    cx.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS %s ON document_assignments (document_id)"
                    % UNIQUE_REVIEWER))

    logged = select(e.c.document_id)
    rows = cx.execute(select(d.c.id, d.c.project_id, d.c.version_id, d.c.approved_by,
                             d.c.approved_at, d.c.updated_at)
                      .where(d.c.status == "approved", d.c.id.not_in(logged))).fetchall()
    now = datetime.now(timezone.utc)
    for r in rows:
        cx.execute(insert(e).values(
            id="rev" + uuid.uuid4().hex[:12], document_id=r.id, project_id=r.project_id,
            version_id=r.version_id, kind="approved", actor_id=r.approved_by,
            at=r.approved_at or r.updated_at or now,
            comment="Approved before the review record existed.",
            payload={"before_record": True}))
    done["events"] = len(rows)
    return done
