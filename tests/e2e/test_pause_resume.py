"""A run paused at a safe point, then resumed, makes what a run never paused makes
(docs/design/JOB_SCHEDULING_DESIGN.md §8; docs/spec/JOB_SCHEDULING_SPEC.md REQ-JS-22, 23).

A second version of the e2e commit, generated as a web job's run (`--job-id`): its job asks to pause
once Phase 2 has begun, and the run stops at its next pause point with exit 75 -- its run recorded
`paused`, the version not closed as failed, the web job left to the API. `analyzer.py resume`, as the
same job, finishes it: its views are the e2e version's, file for file.
"""
import datetime
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid

import pytest
import sqlalchemy as sa

from tests.e2e_paths import COMPONENTS, E2E_PID, E2E_VERSION_ID, GROUP, PROJECT_ROOT

from core.run_context import version_key

VID = "e2epause"
VERSION_ID = version_key(E2E_PID, VID)
REPO = os.path.join(tempfile.gettempdir(), "analyzer-e2e-sample")
UTC = datetime.timezone.utc

#: View outputs the same for the same commit, scope and settings, whichever version holds them.
_SAME = ("interface_tables.json", "test_specs.json", "ut_export.json", "unit_headers.json",
         "unit_descriptions.json", ".svg", ".mmd")


def _analyzer(*args):
    return subprocess.run([sys.executable, os.path.join(PROJECT_ROOT, "analyzer.py"), *args],
                          cwd=PROJECT_ROOT, capture_output=True, text=True,
                          env={k: v for k, v in os.environ.items() if k != "ANALYZER_JOB_ID"})


def _views(cx, s, version_id):
    rows = cx.execute(sa.select(s.version_output_files.c.rel_path,
                                s.version_output_files.c.content)
                      .where(s.version_output_files.c.version_id == version_id)).all()
    return {r.rel_path: r.content for r in rows}


def _forget(db):
    """Delete this test's version, its rows and its folder. Left, a database kept between
    sessions held the last session's, and its documents stayed on disk for the suites after it
    (tools/doccheck's tests read every e2e document they find)."""
    from api.services import pipeline_runner as pr
    pr.delete_version(db, VERSION_ID)
    pr._remove_version_folder(E2E_PID, VERSION_ID)          # a folder whose row went before


@pytest.fixture(scope="module")
def paused_then_resumed(run_pipeline):
    from api.db.postgres import schema as s
    from api.db.postgres.database import SqlDatabase
    from api.models.domain import JOB_STATUSES
    from core.db import get_engine
    eng = get_engine()
    db = SqlDatabase(eng)
    sha = subprocess.run(["git", "-C", REPO, "rev-parse", "HEAD"], capture_output=True,
                         text=True).stdout.strip()
    job_id = "jobpause" + uuid.uuid4().hex[:6]
    now = datetime.datetime.now(UTC)
    _forget(db)
    with eng.begin() as cx:
        # The web job this run is: what the API's claim leaves -- running, its alive signal set.
        cx.execute(sa.insert(s.analysis_jobs).values(
            id=job_id, project_id=E2E_PID, status="running", mode="auto", lane="generation",
            origin="web", commit_sha=sha, version_tag=VID, started_at=now, submitted_at=now,
            heartbeat_at=now, phases=[], current_activity="", activity_detail=""))
    asked, stop = [], threading.Event()

    def ask_once_phase_2_begins():
        deadline = time.monotonic() + 900
        while not stop.is_set() and time.monotonic() < deadline:
            with eng.connect() as cx:
                status = cx.execute(sa.select(s.versions.c.pipeline_status)
                                    .where(s.versions.c.id == VERSION_ID)).scalar()
            if status in ("deriving", "viewing", "exporting"):
                db.jobs.transition(job_id, ("running",), "running",
                                   pause_requested_at=datetime.datetime.now(UTC))
                asked.append(status)
                return
            time.sleep(0.05)

    out = {"job_id": job_id, "asked": asked}
    watcher = threading.Thread(target=ask_once_phase_2_begins, daemon=True)
    watcher.start()
    try:
        out["paused"] = _analyzer(
            "generate", "--project-id", E2E_PID, "--version-id", VID, "--branch", "main",
            "--commit", sha, "--scope", "group:" + GROUP, "--no-llm", "--doc-type", "all",
            "--full", "--create-version", "--job-id", job_id)
        stop.set()
        with eng.connect() as cx:
            out["run_after_pause"] = cx.execute(sa.select(s.version_runs.c.outcome).where(
                s.version_runs.c.version_id == VERSION_ID)).scalar()
            out["status_after_pause"] = cx.execute(sa.select(s.versions.c.pipeline_status)
                                                   .where(s.versions.c.id == VERSION_ID)).scalar()
        out["job_after_pause"] = db.jobs.get(job_id).status
        # Resumed: the API's claim clears the request; the run is the same job's.
        db.jobs.transition(job_id, ("running",), "running", pause_requested_at=None)
        out["resumed"] = _analyzer("resume", "--project-id", E2E_PID, "--version-id", VID,
                                   "--job-id", job_id)
        with eng.connect() as cx:
            out["status_after_resume"] = cx.execute(sa.select(s.versions.c.pipeline_status)
                                                    .where(s.versions.c.id == VERSION_ID)).scalar()
            out["components"] = dict(cx.execute(
                sa.select(s.version_components.c.component, s.version_components.c.state)
                .where(s.version_components.c.version_id == VERSION_ID)).all())
            out["views"] = _views(cx, s, VERSION_ID)
            out["e2e_views"] = _views(cx, s, E2E_VERSION_ID)
        yield out
    finally:
        stop.set()
        # Never left running: the next session's e2e generate would find its lane taken.
        db.jobs.transition(job_id, JOB_STATUSES, "complete",
                           completed_at=datetime.datetime.now(UTC))
        _forget(db)


def test_the_run_stops_at_a_safe_point_as_a_pause(paused_then_resumed):
    got = paused_then_resumed
    assert got["asked"], "the pause was never asked: the run ended before Phase 2 began"
    run = got["paused"]
    assert run.returncode == 75, run.stderr[-3000:]
    assert "Paused at a safe point" in run.stderr
    assert got["run_after_pause"] == "paused"
    assert got["status_after_pause"] != "failed", "a pause is not a failed version"
    assert got["job_after_pause"] == "running", "a web job's end is the API's"


def test_the_resume_finishes_the_version(paused_then_resumed):
    got = paused_then_resumed
    run = got["resumed"]
    assert run.returncode == 0, run.stderr[-3000:]
    assert got["status_after_resume"] == "complete"
    assert {c: got["components"].get(c) for c in COMPONENTS} == {c: "generated"
                                                                  for c in COMPONENTS}


def test_it_made_what_a_run_never_paused_made(paused_then_resumed):
    got = paused_then_resumed
    mine, theirs = got["views"], got["e2e_views"]
    assert set(mine) == set(theirs)
    same = sorted(p for p in theirs if p.endswith(_SAME))
    assert same, "nothing to compare"
    assert [p for p in same if mine[p] != theirs[p]] == []
