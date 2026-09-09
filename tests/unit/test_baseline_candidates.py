"""Regression: a running job's own reserved version must never be a baseline candidate.

The API reserves the version row at job start (status 'draft') so the job + entity FKs resolve
during the run, and `pipeline_status` is never written. Before the fix, `pg_stores.list_versions`
treated a NULL pipeline_status as "generation finished", so the running version was offered as a
baseline at its OWN commit — the nearest possible match — giving a 0-changed-file diff that
regenerated nothing (the incremental run looked successful but did no work).
"""
import datetime
import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

_ENGINE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "engine")
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from incremental import pg_stores                     # noqa: E402
from api.db.postgres import schema as s               # noqa: E402

pytestmark = pytest.mark.unit

_NOW = datetime.datetime(2026, 8, 10, tzinfo=datetime.timezone.utc)


def _engine_with(versions):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    s.metadata.create_all(eng)
    with eng.begin() as cx:
        cx.execute(s.projects.insert().values(id="p1", name="P", created_at=_NOW))
        for v in versions:
            cx.execute(s.versions.insert().values(project_id="p1", created_at=_NOW, **v))
    return eng


def test_draft_version_is_not_a_baseline_candidate():
    eng = _engine_with([
        # the completed baseline from the first run
        {"id": "ver1", "version": "v1.0.0", "commit_sha": "aaa111", "status": "in_review"},
        # THIS run's row, reserved at job start at the target commit
        {"id": "ver2", "version": "v1.1.0", "commit_sha": "bbb222", "status": "draft"},
    ])
    ids = {v["versionId"] for v in pg_stores.list_versions(eng, "p1")}
    assert ids == {"ver1"}, "a reserved (draft) version must not be offered as a baseline"


def test_completed_versions_still_qualify():
    eng = _engine_with([
        {"id": "ver1", "version": "v1.0.0", "commit_sha": "aaa111", "status": "in_review"},
        {"id": "ver2", "version": "v1.1.0", "commit_sha": "bbb222", "status": "approved"},
        # legacy row: null pipeline_status + null status is still treated as complete
        {"id": "ver3", "version": "v0.9.0", "commit_sha": "ccc333"},
    ])
    ids = {v["versionId"] for v in pg_stores.list_versions(eng, "p1")}
    assert ids == {"ver1", "ver2", "ver3"}


def test_in_progress_pipeline_status_still_excluded():
    eng = _engine_with([
        {"id": "ver1", "version": "v1.0.0", "commit_sha": "aaa111", "status": "in_review"},
        {"id": "ver2", "version": "v1.1.0", "commit_sha": "bbb222",
         "status": "in_review", "pipeline_status": "parsing"},
    ])
    ids = {v["versionId"] for v in pg_stores.list_versions(eng, "p1")}
    assert ids == {"ver1"}
