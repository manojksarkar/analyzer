"""
Simulated analysis-job runner.

The in-memory/JSON API has no real analyzer worker, so an `AnalysisJob` would
otherwise sit at `queued` forever. This module spawns a lightweight background
**thread** that walks a job through the four pipeline phases (updating the job
record as it goes, which the SSE stream re-reads every few seconds so the
overview's progress banner animates), and on completion synthesises a `Version`
and a set of `Document`s derived from the project's architecture so the page
lands in a real, populated state.

It is intentionally a *simulation* — no C++ is parsed. Swapping in a real worker
means replacing `_run`; the start hook and job/document shapes stay the same.

Timing is read from `JOB_SIM_STEP_SECONDS` (env) at call time so tests can make
it near-instant without changing import order.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from ..models.domain import Version, Document

UTC = timezone.utc

_PHASES = [(1, "Parse C++"), (2, "Derive Model"), (3, "Run Views"), (4, "Export DOCX")]
_ACTIVITY = {
    1: "Parsing C++ sources with libclang…",
    2: "Deriving model + enriching with LLM…",
    3: "Rendering views, diagrams and flowcharts…",
    4: "Exporting Software Detailed Design DOCX…",
}
_INCREMENTS = [25, 50, 75, 100]
_MAX_UNIT_DOCS = 24


def _now() -> datetime:
    return datetime.now(UTC)


def _step_seconds() -> float:
    try:
        return max(0.0, float(os.getenv("JOB_SIM_STEP_SECONDS", "0.8")))
    except ValueError:
        return 0.8


def start(db: Any, job_id: str) -> None:
    """Kick off the simulated run on a daemon thread (returns immediately)."""
    threading.Thread(target=_run, args=(db, job_id), daemon=True, name=f"jobsim-{job_id}").start()


# ---------------------------------------------------------------------------
# Progression
# ---------------------------------------------------------------------------

def _run(db: Any, job_id: str) -> None:
    try:
        _progress(db, job_id)
    except Exception as exc:  # never let the thread die silently
        job = db.jobs.get(job_id)
        if job and job.status not in ("cancelled", "complete"):
            job.status = "failed"
            job.error_message = f"Simulated run error: {exc}"
            job.completed_at = _now()
            db.jobs.update(job)


def _stopped(job) -> bool:
    return job is None or job.status == "cancelled"


def _await_resume(db: Any, job_id: str) -> bool:
    """Block while a job is paused. Returns False if it was cancelled/removed."""
    while True:
        time.sleep(_step_seconds())
        job = db.jobs.get(job_id)
        if _stopped(job):
            return False
        if job.status == "running":
            return True


def _progress(db: Any, job_id: str) -> None:
    job = db.jobs.get(job_id)
    if _stopped(job):
        return
    job.status = "running"
    job.current_activity = _ACTIVITY[1]
    db.jobs.update(job)

    for num, name in _PHASES:
        phase_start = _now()
        for pct in _INCREMENTS:
            time.sleep(_step_seconds())
            job = db.jobs.get(job_id)
            if _stopped(job):
                return
            if job.status == "paused" and not _await_resume(db, job_id):
                return
            job.phase = num
            job.phase_pct = pct
            job.current_activity = _ACTIVITY[num]
            job.activity_detail = f"{name} · {pct}%"
            job.elapsed_seconds = int((_now() - job.started_at).total_seconds())
            job.eta_seconds = max(0, (len(_PHASES) - num) * 4)
            for p in job.phases:
                p.status = "done" if p.number < num else ("running" if p.number == num else "pending")
            if pct == 100:
                for p in job.phases:
                    if p.number == num:
                        p.status = "done"
                        p.duration_seconds = max(1, int((_now() - phase_start).total_seconds()))
            db.jobs.update(job)

        # Optional hold after Phase 1 (honours the start request's flag).
        if num == 1 and job.pause_after_phase1:
            job = db.jobs.get(job_id)
            if _stopped(job):
                return
            job.status = "paused"
            job.current_activity = "Paused after Phase 1 — review functions, then resume."
            db.jobs.update(job)
            if not _await_resume(db, job_id):
                return

    _complete(db, job_id)


# ---------------------------------------------------------------------------
# Completion — synthesise a version + documents so the overview is populated
# ---------------------------------------------------------------------------

def _complete(db: Any, job_id: str) -> None:
    job = db.jobs.get(job_id)
    if _stopped(job):
        return
    now = _now()
    project = db.projects.get(job.project_id)

    version = _make_version(db, project, job, now)
    docs = _make_documents(db, project, version, now)
    version.docs_count = len(docs)
    db.versions.update(version)

    job.status = "complete"
    job.phase = len(_PHASES)
    job.phase_pct = 100
    job.current_activity = "Done"
    job.activity_detail = f"{len(docs)} documents generated"
    job.eta_seconds = 0
    job.completed_at = now
    job.version_id = version.id
    job.elapsed_seconds = int((now - job.started_at).total_seconds())
    for p in job.phases:
        p.status = "done"
    db.jobs.update(job)

    # Move the project out of `not_run` so the overview shows generated content.
    if project:
        project.status = "in_review"
        project.updated_at = now
        db.projects.update(project)


def _make_version(db: Any, project: Any, job: Any, now: datetime) -> Version:
    existing = db.versions.list_for_project(project.id) if project else []
    taken = {v.tag for v in existing}
    # Prefer the version name the user typed in the Run Analysis modal; fall back
    # to an auto-incrementing tag. Guarantee uniqueness either way.
    tag = (getattr(job, "version_tag", None) or "").strip() or f"v0.{len(existing) + 1}.0"
    base, i = tag, 1
    while tag in taken:
        tag = f"{base}-{i}"
        i += 1
    version = Version(
        id=f"ver{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        tag=tag,
        commit_sha=job.commit_sha,
        branch=job.branch,
        description="Generated by analysis run",
        status="in_review",
        docs_count=0,
        created_by=(project.created_by if project else "u1"),
        created_at=now,
    )
    db.versions.create(version)
    return version


def _make_documents(db: Any, project: Any, version: Version, now: datetime) -> list[Document]:
    docs: list[Document] = []

    def add(process: str, name: str, subtitle: str, layer: str, group: str, status: str) -> None:
        doc = Document(
            id=f"doc{uuid.uuid4().hex[:8]}",
            project_id=project.id, version_id=version.id,
            process=process, name=name, subtitle=subtitle,
            layer=layer, group=group, status=status,
            due_date=None, created_at=now, updated_at=now,
        )
        db.documents.update(doc)   # in-mem/JSON `update` is an upsert
        docs.append(doc)

    # Always-present global documents.
    add("SYS.2", "System Requirements", "SyRS", "", "Global", "approved")
    add("SWE.1", "Software Requirements", "SRS", "", "Global", "approved")

    # One Component-Design (SWE.2) per group + one Unit-Design (SWE.3) per component,
    # derived from whatever architecture was captured (handles both shapes).
    unit_count = 0
    for layer in (project.architecture_layers or []):
        if not isinstance(layer, dict):
            continue
        lname = str(layer.get("name", "") or "")
        for g in layer.get("groups", []) or []:
            if isinstance(g, str):
                gname, comps = g, []
            elif isinstance(g, dict):
                gname, comps = str(g.get("name", "") or ""), (g.get("components", []) or [])
            else:
                continue
            if not gname:
                continue
            add("SWE.2", gname, "Component Design", lname, gname, "in_review")
            for c in comps:
                cname = c if isinstance(c, str) else (c.get("name", "") if isinstance(c, dict) else "")
                if not cname:
                    continue
                add("SWE.3", str(cname), "Unit Design", lname, gname, "in_review")
                unit_count += 1
                if unit_count >= _MAX_UNIT_DOCS:
                    return docs

    # Ensure at least one unit doc even if no components were mapped.
    if unit_count == 0:
        add("SWE.3", "Main Module", "Unit Design", "", "Global", "in_review")
    return docs
