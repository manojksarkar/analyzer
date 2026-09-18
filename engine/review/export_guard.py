"""Refusing to export a document that would ship the previous text.

`REQ-AP-04`, and the piece that makes this feature reliable rather than merely correct.

`analyzer.py reexport --from-phase 4` is documented as *"export only"* and **skips Phase 3** — the
step that rebuilds the view rows the document is built from. A correction saved a second earlier
updates the model and the override table; the export then reads rows Phase 3 wrote last time and
ships the old wording, with nothing to notice. Moving output into the database did not fix this: it
is still the row Phase 3 wrote last time.

So the export asks rather than assumes:

    newest text_overrides.updated_at  >  oldest view_derivations.derived_at   =>  stale

A **check, not an assumption**. Even if some future write path forgets to re-derive, the export
still cannot quietly ship stale text — which is the whole reason it is a query over stored facts
and not a flag someone sets.

## The baseline

`view_derivations` answers "when was this version's output last derived". Two things write it:

* the pipeline, through `stamp_pipeline_derivation` when Phase-3 output is captured — one row per
  group, `view_name` = `PIPELINE_ALL`;
* `override_service`, for the specific views it re-derived after a correction.

`PIPELINE_ALL` is a wildcard and is spelled as one deliberately. Phase 3 runs as a subprocess and
the capture point does not know which individual views ran, so naming them there would be inventing
precision this code does not have. The guard needs `min(derived_at)`, which is correct either way.

## Cost when nobody has corrected anything

Which is every project today. The first query is `SELECT max(updated_at) ... WHERE version_id = ?`
against `ix_text_overrides_updated`; it returns NULL and the guard stops. No scan, no join.
"""
from __future__ import annotations

import datetime
import os
import sys
from typing import NamedTuple, Optional

from sqlalchemy import func, insert, select, update

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from api.db.postgres import schema as s   # noqa: E402

#: `view_derivations.view_name` for "the whole Phase-3 output of this group". See the docstring.
PIPELINE_ALL = "*"


class StaleExport(Exception):
    """The document would carry text that a correction has already replaced."""


class Staleness(NamedTuple):
    is_stale: bool
    reason: str
    newest_override_at: Optional[datetime.datetime]
    oldest_derivation_at: Optional[datetime.datetime]
    override_count: int
    #: Pictures still being produced. Any of these blocks an export (REQ-IM-02).
    pending_renders: int = 0
    #: Renders that gave up. These do NOT block -- see `staleness`.
    failed_renders: int = 0

    def explain(self) -> str:
        """One line a CLI or an API error can print as-is."""
        bits = []
        if self.is_stale:
            bits.append(self.reason)
        if self.failed_renders:
            bits.append("%d flowchart image(s) could not be drawn and are out of date"
                        % self.failed_renders)
        if not bits:
            return "up to date"
        return "%s (%d correction(s) in this version)" % ("; ".join(bits), self.override_count)


def staleness(conn, version_id: str) -> Staleness:
    """Whether this version's derived output is older than a correction to it."""
    newest, count = conn.execute(
        select(func.max(s.text_overrides.c.updated_at),
               func.count(s.text_overrides.c.slot_key))
        .where(s.text_overrides.c.version_id == version_id)).first()

    if not newest:
        # Nobody has corrected anything, which is every project today. Nothing to be stale
        # against, and the guard costs one indexed lookup.
        return Staleness(False, "no corrections", None, None, 0)

    # REQ-IM-02. A picture still being drawn makes the version unexportable however fresh the
    # TEXT is: an export now ships the new wording and the old image.
    #
    # A FAILED render does not block. It cannot be waited for, and blocking on it would make one
    # unrenderable flowchart permanently unexportable -- the cure worse than the disease. It is
    # reported instead, through `failed_renders` and `explain()`, so the document goes out with
    # somebody knowing the picture is stale rather than nobody.
    from review.render_queue import counts as _render_counts
    renders = _render_counts(conn, version_id)

    oldest = conn.execute(
        select(func.min(s.view_derivations.c.derived_at))
        .where(s.view_derivations.c.version_id == version_id)).scalar()

    if renders.pending:
        return Staleness(True, "%d flowchart image(s) are still being drawn" % renders.pending,
                         newest, _aware(oldest) if oldest else None, count,
                         renders.pending, renders.failed)

    if oldest is None:
        # Corrections exist and NOTHING recorded a derivation. That is not evidence of freshness,
        # it is the absence of evidence -- so it counts as stale. A guard that reads "no data" as
        # "fine" is the guard that does not guard.
        return Staleness(True, "corrections exist but no view derivation was ever recorded",
                         newest, None, count, renders.pending, renders.failed)

    newest, oldest = _aware(newest), _aware(oldest)
    if newest > oldest:
        return Staleness(True, "a correction is newer than the derived output", newest, oldest,
                         count, renders.pending, renders.failed)
    return Staleness(False, "up to date", newest, oldest, count,
                     renders.pending, renders.failed)


def _aware(dt: datetime.datetime) -> datetime.datetime:
    """Compare in UTC.

    SQLite hands back naive datetimes where Postgres hands back aware ones, and comparing the two
    raises `TypeError` -- which, inside an export path, would read as a crash rather than as the
    stale-or-not answer the caller asked for.
    """
    return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)


def assert_exportable(conn, version_id: str) -> Staleness:
    """Raise `StaleExport` if exporting now would ship superseded text."""
    st = staleness(conn, version_id)
    if st.is_stale:
        raise StaleExport(
            "version %s is not safe to export: %s.\n"
            "  Re-derive the views first:\n"
            "    python analyzer.py reexport --project-id <pid> --version-id %s --from-phase 3"
            % (version_id, st.explain(), version_id))
    return st


# ---------------------------------------------------------------------------
# recording a derivation
# ---------------------------------------------------------------------------
def stamp_pipeline_derivation(conn, version_id: str, group_name: str = "",
                              now: Optional[datetime.datetime] = None) -> None:
    """Record that Phase 3 produced this version's output for `group_name`.

    Called where the output is captured, so the baseline exists for every ordinary run and not
    only for versions somebody has corrected. Without it the first correction to any version would
    report the version as stale for ever, because there would be nothing to compare against.

    Idempotent: one row per `(version, PIPELINE_ALL, group)`, moved forward. The guard compares
    against the OLDEST derivation, so leaving a stale row behind would report a freshly derived
    version as stale.
    """
    stamp = now or datetime.datetime.now(datetime.timezone.utc)
    where = (s.view_derivations.c.version_id == version_id,
             s.view_derivations.c.view_name == PIPELINE_ALL,
             s.view_derivations.c.group_name == (group_name or ""))
    if not conn.execute(update(s.view_derivations).where(*where)
                        .values(derived_at=stamp)).rowcount:
        conn.execute(insert(s.view_derivations).values(
            version_id=version_id, view_name=PIPELINE_ALL, group_name=(group_name or ""),
            derived_at=stamp))
