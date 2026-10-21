"""A new version cancelled part way through a phase leaves nothing of itself
(docs/design/JOB_SCHEDULING_DESIGN.md §9; docs/spec/JOB_SCHEDULING_SPEC.md REQ-JS-25).

A web job's run of the e2e commit, into the draft version the API would have reserved, is stopped
once its phase has begun -- its whole process tree, as a cancel stops it -- and the cancel then does
what it does once the run has stopped: the job `cancelled`, its draft deleted. Whatever the run had
saved by then -- nothing, the parse, or the model and some components' views -- goes with it: no row of
the version in any table, and no folder.
"""
import datetime
import os
import subprocess
import sys
import tempfile
import time
import uuid

import pytest
import sqlalchemy as sa

from tests.e2e_paths import E2E_PID, GROUP, PROJECT_ROOT

REPO = os.path.join(tempfile.gettempdir(), "analyzer-e2e-sample")
UTC = datetime.timezone.utc


def _rows_of(cx, s, vid):
    """{table: rows of version `vid`} for every table with a `version_id`, the jobs aside (a
    cancelled job stays, naming no version)."""
    out = {}
    for t in s.metadata.sorted_tables:
        if "version_id" in t.c and t.name != "analysis_jobs":
            n = cx.execute(sa.select(sa.func.count()).select_from(t)
                           .where(t.c.version_id == vid)).scalar()
            if n:
                out[t.name] = n
    return out


@pytest.mark.parametrize("phase", ["parsing", "deriving", "viewing"])
def test_a_new_version_cancelled_in_a_phase_leaves_nothing(run_pipeline, phase):
    from api.db.postgres import schema as s
    from api.db.postgres.database import SqlDatabase
    from api.models.domain import JOB_STATUSES
    from api.services import pipeline_runner as pr
    from core.db import get_engine
    from core.subprocess_util import stop_tree
    eng = get_engine()
    db = SqlDatabase(eng)
    sha = subprocess.run(["git", "-C", REPO, "rev-parse", "HEAD"], capture_output=True,
                         text=True).stdout.strip()
    tag = uuid.uuid4().hex[:6]
    vid, name = "vercx" + tag, "e2ecancel-%s-%s" % (phase, tag)
    job_id = "jobcx" + uuid.uuid4().hex[:6]
    now = datetime.datetime.now(UTC)
    with eng.begin() as cx:
        # What the API's submit leaves: the draft version, then its job, claimed (running).
        cx.execute(sa.insert(s.versions).values(id=vid, project_id=E2E_PID, version=name,
                                                commit_sha=sha, status="draft", created_at=now))
        cx.execute(sa.insert(s.analysis_jobs).values(
            id=job_id, project_id=E2E_PID, version_id=vid, status="running", mode="auto",
            lane="generation", origin="web", commit_sha=sha, version_tag=name, started_at=now,
            submitted_at=now, heartbeat_at=now, phases=[], current_activity="",
            activity_detail=""))
    folder = os.path.join(PROJECT_ROOT, "workspaces", E2E_PID, "versions", vid)
    run = subprocess.Popen(
        [sys.executable, os.path.join(PROJECT_ROOT, "analyzer.py"), "generate",
         "--project-id", E2E_PID, "--version-id", name, "--branch", "main", "--commit", sha,
         "--scope", "group:" + GROUP, "--no-llm", "--doc-type", "all", "--full",
         "--job-id", job_id],
        cwd=PROJECT_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env={k: v for k, v in os.environ.items() if k != "ANALYZER_JOB_ID"})
    try:
        deadline = time.monotonic() + 900
        status = None
        while time.monotonic() < deadline and run.poll() is None:
            with eng.connect() as cx:
                status = cx.execute(sa.select(s.versions.c.pipeline_status)
                                    .where(s.versions.c.id == vid)).scalar()
            if status == phase:
                break
            time.sleep(0.05)
        assert status == phase and run.poll() is None, \
            "the run never reached %s while running (last: %s)" % (phase, status)
        stop_tree(run)                                  # the cancel stops the whole tree
        run.wait(60)
        with eng.connect() as cx:
            saved = _rows_of(cx, s, vid)
        # Once the run has stopped (job_queue.cancel -> _release_draft_version):
        assert db.jobs.transition(job_id, ("running",), "cancelled",
                                  completed_at=datetime.datetime.now(UTC))
        pr._release_draft_version(db, db.jobs.get(job_id))
        with eng.connect() as cx:
            left = _rows_of(cx, s, vid)
        assert db.versions.get(vid) is None
        assert left == {}, "rows left after the cancel (saved before it: %s)" % saved
        assert not os.path.exists(folder)
        if phase != "parsing":
            assert saved, "nothing had been saved: the test proved less than it says"
    finally:
        if run.poll() is None:
            stop_tree(run)
        db.jobs.transition(job_id, JOB_STATUSES, "cancelled",
                           completed_at=datetime.datetime.now(UTC))
