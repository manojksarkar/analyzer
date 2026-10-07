"""Pictures waiting to be redrawn, and the worker that draws them.

`REQ-IM-01/02/03`. Correcting a flowchart node label changes the picture, not only the text.

## Why a job row and not just "render it now"

Because the **export** has to be able to ask whether a picture is still being produced
(`REQ-IM-02`). Without a durable answer, an export a second after an edit ships the new text
everywhere and the old image — the split-origin failure that once left a stored graph and a
document picture coming from different versions.

It also decouples the render from the request. Rendering needs an output tree and Graphviz, and the
host saving a correction is not guaranteed to have either. Where it does, the render runs
immediately and the job is `done` before the response is sent; where it does not, the job stays
`pending` and `run_pending` finishes it wherever the tree lives.

## What is deliberately not collapsed

Two corrections to one flowchart make **two** jobs. Collapsing them would let a render that began
before the second edit satisfy it, leaving the picture one edit behind with nothing pending to say
so. Rendering twice is cheap by comparison — `render_dot_cached` is content-addressed, so the
second is a file copy when the graph did not change again.

## Failure is recorded, not swallowed

A failed render leaves `status='failed'` with the reason. It does **not** block the export for
ever, which a stuck `pending` would, and it does not quietly pass either: `stale_reasons` reports
failures separately so a document goes out with someone knowing the picture is old.
"""
from __future__ import annotations

import datetime
import os
import sys
from typing import List, NamedTuple, Optional, Sequence

from sqlalchemy import func, insert, select, update

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from api.db.postgres import schema as s   # noqa: E402

PENDING = "pending"
DONE = "done"
FAILED = "failed"


class Counts(NamedTuple):
    pending: int
    failed: int


def enqueue(conn, version_id: str, flowchart_id: str, png_name: str = "", *,
            user_id: Optional[str] = None,
            now: Optional[datetime.datetime] = None) -> int:
    """Record that one flowchart's picture needs redrawing. Returns the job id."""
    stamp = now or datetime.datetime.now(datetime.timezone.utc)
    res = conn.execute(insert(s.render_jobs).values(
        version_id=version_id, flowchart_id=flowchart_id, png_name=png_name or None,
        status=PENDING, requested_by=user_id, requested_at=stamp))
    key = res.inserted_primary_key
    return int(key[0]) if key else 0


def complete(conn, job_id: int, *, error: str = "",
             now: Optional[datetime.datetime] = None) -> None:
    """Mark a job finished. An `error` marks it failed and keeps the reason."""
    conn.execute(update(s.render_jobs)
                 .where(s.render_jobs.c.job_id == job_id)
                 .values(status=FAILED if error else DONE, error=error or None,
                         finished_at=now or datetime.datetime.now(datetime.timezone.utc)))


def counts(conn, version_id: str, component: Optional[str] = None) -> Counts:
    """How many of this version's renders are outstanding, and how many gave up -- of one
    `component`'s flowcharts when it is given (the first part of `flowchart_id`, compared in
    `export_guard.component_id` form): one picture being drawn puts its own component's Word file
    out of date, not every component's.

    One grouped query: the export asks this on every download, and a version nobody has corrected
    has no rows at all.
    """
    if component is not None:
        c = by_component(conn, version_id).get(_component_key(component), Counts(0, 0))
        return c
    rows = conn.execute(
        select(s.render_jobs.c.status, func.count())
        .where(s.render_jobs.c.version_id == version_id)
        .group_by(s.render_jobs.c.status)).fetchall()
    by_status = {r[0]: int(r[1]) for r in rows}
    return Counts(pending=by_status.get(PENDING, 0), failed=by_status.get(FAILED, 0))


def _component_key(name: str) -> str:
    from review.export_guard import component_id
    return component_id(name)


def by_component(conn, version_id: str) -> dict:
    """`{component (component_id form): Counts}` of this version's outstanding and failed renders,
    per component -- the first part of the flowchart's function id. One query; a version with no
    corrected label has no rows."""
    out: dict = {}
    for fid, status, n in conn.execute(
            select(s.render_jobs.c.flowchart_id, s.render_jobs.c.status, func.count())
            .where(s.render_jobs.c.version_id == version_id,
                   s.render_jobs.c.status.in_((PENDING, FAILED)))
            .group_by(s.render_jobs.c.flowchart_id, s.render_jobs.c.status)).fetchall():
        comp = _component_key((fid or "").split("|", 1)[0])
        pending, failed = out.get(comp, Counts(0, 0))
        out[comp] = Counts(pending + (int(n) if status == PENDING else 0),
                           failed + (int(n) if status == FAILED else 0))
    return out


def pending_jobs(conn, version_id: Optional[str] = None) -> Sequence:
    """Outstanding jobs, oldest first. Without a version, every version's."""
    q = (select(s.render_jobs).where(s.render_jobs.c.status == PENDING)
         .order_by(s.render_jobs.c.requested_at, s.render_jobs.c.job_id))
    if version_id:
        q = q.where(s.render_jobs.c.version_id == version_id)
    return conn.execute(q).fetchall()


# ---------------------------------------------------------------------------
# the worker
# ---------------------------------------------------------------------------
def failed_jobs(conn, version_id: str) -> Sequence:
    """Jobs that gave up, oldest first."""
    return conn.execute(select(s.render_jobs).where(s.render_jobs.c.version_id == version_id,
                                                    s.render_jobs.c.status == FAILED)
                        .order_by(s.render_jobs.c.requested_at, s.render_jobs.c.job_id)).fetchall()


def run_pending(conn, version_id: str, *, output_dir: str, project_root: str,
                limit: Optional[int] = 50, components=None,
                retry_failed: bool = False) -> List[int]:
    """Draw the pictures this version is waiting on. Returns the job ids finished.

    Each job is completed **individually**, so one flowchart that cannot be drawn does not leave
    the others pending for ever and does not hide the ones that succeeded.

    Reads the CORRECTED CFG from storage rather than anything carried along with the job: by the
    time this runs the graph may have been corrected again, and the picture must match what the
    document will show, not what was true when the job was made. Drawn in EVERY stored copy's
    directory, as `rerender.redraw_flowchart` writes every copy; two jobs for one flowchart draw
    it once.

    `components`: only the jobs of these components' flowcharts (a Word-file update draws what
    its components owe BEFORE it exports, FAST_WORD_FILE_UPDATES P2). `retry_failed`: also the
    jobs that gave up before -- the update is when the picture is needed. `limit` None: all.
    """
    jobs = list(pending_jobs(conn, version_id))
    if retry_failed:
        jobs += list(failed_jobs(conn, version_id))
    if components is not None:
        want = {_component_key(c) for c in components}
        jobs = [j for j in jobs
                if _component_key((j.flowchart_id or "").split("|", 1)[0]) in want]
    if limit is not None:
        jobs = jobs[:max(1, int(limit))]

    done: List[int] = []
    errors: dict = {}
    for job in jobs:
        if job.flowchart_id not in errors:
            errors[job.flowchart_id] = _draw(conn, version_id, job, output_dir, project_root)
        complete(conn, job.job_id, error=errors[job.flowchart_id])
        done.append(job.job_id)
    return done


def _draw(conn, version_id: str, job, output_dir: str, project_root: str) -> str:
    """Draw one job's flowchart in every stored copy's directory: "" when drawn, else why not."""
    import json
    from review import rerender
    try:
        found = rerender.find_flowchart_rows(conn, version_id, job.flowchart_id)
        if not found:
            return "no stored flowchart for %s" % job.flowchart_id
        for rel_path, unit_name, content in found:
            entry = next((e for e in json.loads(content)
                          if isinstance(e, dict) and e.get("functionKey") == job.flowchart_id),
                         None)
            if entry is None or not (entry.get("flowchart") or "").strip():
                return "no DOT stored for %s" % job.flowchart_id
            item = rerender.Redrawn(
                flowchart_id=job.flowchart_id,
                function_name=(entry.get("name") or ""),
                png_name=job.png_name or rerender.png_name_for(unit_name,
                                                               entry.get("name") or ""),
                dot=entry["flowchart"])
            fc_dir = os.path.join(output_dir, os.path.dirname(rel_path).replace("/", os.sep))
            if not rerender.render_png(project_root, fc_dir, item):
                return "graphviz produced no image"
        return ""
    except Exception as exc:                          # noqa: BLE001 - recorded, see run_pending
        return str(exc)[:500] or type(exc).__name__
