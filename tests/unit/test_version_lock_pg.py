"""The version's writer lock on a real Postgres (engine/core/version_run.py).

One writer per version: a second `generate`/`export`/`reexport`/`resume` (or web job) on a version
being written is refused, saying who holds it; the lock goes with the holder's connection, so a
killed run never leaves its version locked. Postgres advisory locks have no SQLite equivalent, so
this needs a scratch Postgres database and is skipped without one:

    ANALYZER_TEST_PG_DSN=postgresql+psycopg://user:pw@127.0.0.1:5432/scratch \
        python -m pytest tests/unit/test_version_lock_pg.py

No table is needed: the lock is not a row. (The run record is, and its absence is only noted.)
"""
import os
import sys
import uuid

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "engine")]

DSN = os.environ.get("ANALYZER_TEST_PG_DSN", "").strip()
if not DSN:
    pytest.skip("set ANALYZER_TEST_PG_DSN to a scratch Postgres database", allow_module_level=True)


@pytest.fixture
def engine():
    from sqlalchemy import create_engine
    eng = create_engine(DSN)
    yield eng
    eng.dispose()


def test_a_second_writer_is_refused_and_told_who_writes(engine):
    from core.version_run import VersionBusy, alive, holder, writing
    vid = "lock-" + uuid.uuid4().hex[:8]
    assert alive(vid, engine=engine) is False
    with writing(vid, command="generate", engine=engine):
        h = holder(vid, engine=engine)
        assert h and h["application"].startswith("analyzer generate pid %d" % os.getpid())
        assert alive(vid, engine=engine) is True
        with pytest.raises(VersionBusy) as exc:
            with writing(vid, command="export", engine=engine):
                pass
        assert "analyzer generate pid" in str(exc.value)
    assert alive(vid, engine=engine) is False, "released when the writer finishes"


def test_another_version_is_not_held_up(engine):
    from core.version_run import writing
    a, b = ("lock-" + uuid.uuid4().hex[:8] for _ in range(2))
    with writing(a, command="generate", engine=engine):
        with writing(b, command="export", engine=engine):
            pass


def test_a_dead_holder_releases_the_version(engine):
    """A killed run: its connection goes, and so does the lock -- no stale lock to clear."""
    from sqlalchemy import text
    from core.version_run import LOCK_NAMESPACE, alive, writing
    vid = "lock-" + uuid.uuid4().hex[:8]
    cx = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    cx.execute(text("SELECT pg_advisory_lock(:ns, (hashtext(:v) & 2147483647))"),
               {"ns": LOCK_NAMESPACE, "v": vid})
    assert alive(vid, engine=engine) is True
    cx.invalidate()                         # the process died: its session is gone
    cx.close()
    engine.dispose()
    import time
    for _ in range(50):                      # the server notices within moments
        if alive(vid, engine=engine) is False:
            break
        time.sleep(0.1)
    assert alive(vid, engine=engine) is False
    with writing(vid, command="resume", engine=engine):
        pass


def test_a_lost_session_is_noticed_and_the_lock_taken_again(engine, monkeypatch):
    """A firewall or an idle timeout can end the lock's session after hours, releasing the lock in
    silence. The heartbeat notices and takes it again on a new session."""
    import time
    from sqlalchemy import text
    import core.version_run as vr
    monkeypatch.setattr(vr, "HEARTBEAT_SECONDS", 0.3)
    vid = "lock-" + uuid.uuid4().hex[:8]
    with vr.writing(vid, command="generate", engine=engine):
        first = vr.holder(vid, engine=engine)["backend_pid"]
        with engine.connect() as cx:                       # what the firewall does
            cx.execute(text("SELECT pg_terminate_backend(:p)"), {"p": first})
            cx.commit()
        for _ in range(50):
            h = vr.holder(vid, engine=engine)
            if h and h["backend_pid"] != first:
                break
            time.sleep(0.1)
        assert h and h["backend_pid"] != first, "the lock was not taken again"
    assert vr.alive(vid, engine=engine) is False


def test_the_heartbeat_keeps_trying_until_the_lock_is_free_again(engine, monkeypatch):
    """After a lost session the server may still hold the dead session's lock for a while: one
    failed attempt must not be the last, or the version stays unlocked for the rest of the run."""
    import time
    from sqlalchemy import text
    import core.version_run as vr
    monkeypatch.setattr(vr, "HEARTBEAT_SECONDS", 0.3)
    vid = "lock-" + uuid.uuid4().hex[:8]
    with vr.writing(vid, command="generate", engine=engine):
        ours = vr.holder(vid, engine=engine)["backend_pid"]
        squatter = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        with engine.connect() as cx:                     # our session dies...
            cx.execute(text("SELECT pg_terminate_backend(:p)"), {"p": ours})
            cx.commit()
        time.sleep(0.05)
        squatter.execute(text("SELECT pg_advisory_lock(:ns, (hashtext(:v) & 2147483647))"),
                         {"ns": vr.LOCK_NAMESPACE, "v": vid})   # ...and the lock is not free yet
        time.sleep(1.2)                                   # several beats fail to take it
        squatter.execute(text("SELECT pg_advisory_unlock(:ns, (hashtext(:v) & 2147483647))"),
                         {"ns": vr.LOCK_NAMESPACE, "v": vid})
        squatter_pid = squatter.execute(text("SELECT pg_backend_pid()")).scalar()
        for _ in range(50):
            h = vr.holder(vid, engine=engine)
            if h and h["backend_pid"] not in (ours, squatter_pid):
                break
            time.sleep(0.1)
        squatter.close()
        assert h and h["backend_pid"] not in (ours, squatter_pid), "never taken again"
    assert vr.alive(vid, engine=engine) is False
