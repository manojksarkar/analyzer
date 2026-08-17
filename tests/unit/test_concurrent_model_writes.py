"""Two jobs persisting at once must not collide on the SHARED tables (doc 10, H1 / step 4).

`entities` (unique on project_id+entity_key) and `content_blobs` (keyed on a GLOBAL
content_hash) are shared, and both were written read-then-insert:

    have = SELECT existing…        both jobs read
    new  = rows not in have        both compute the same missing row
    INSERT new                     both insert it -> IntegrityError

`content_blobs` makes it near-certain rather than rare: every entity with an empty payload
hashes to the same content_hash, so two concurrent jobs on ANY projects race for that one row.

This is a prerequisite for raising JOB_MAX_CONCURRENCY above 1 whether or not the rest of the
DB-native work lands, so it is tested by actually racing two writers — not by reading the source.
"""
import datetime
import os
import sys
import threading

import pytest
from sqlalchemy import create_engine, event, func, insert, select
from sqlalchemy.pool import StaticPool

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "engine"))

from api.db.postgres import schema as s          # noqa: E402
from core import model_store                     # noqa: E402
from core.db_util import insert_ignore, insert_chunked, MAX_ROWS_PER_STATEMENT  # noqa: E402

UTC = datetime.timezone.utc


def _engine(versions=("v1", "v2")):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)

    @event.listens_for(eng, "connect")
    def _fk(dbapi_conn, _rec):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    s.metadata.create_all(eng)
    now = datetime.datetime.now(UTC)
    with eng.begin() as cx:
        for pid in ("pA", "pB"):
            cx.execute(insert(s.projects), {"id": pid, "name": pid, "created_at": now})
        for v in versions:
            cx.execute(insert(s.versions),
                       {"id": v, "project_id": "pA", "version": v, "created_at": now})
    return eng


class TestSharedTableRaces:
    def test_two_writers_same_entity_key_do_not_collide(self):
        """Sequential but overlapping: the second writer computes the same missing row from a
        stale read, which is exactly what two jobs do."""
        eng = _engine()
        specs = {"App|Main|calc|int": ("function", "calc")}
        with eng.begin() as a:
            ids_a = model_store._ensure_entities(a, "pA", specs)
        with eng.begin() as b:
            ids_b = model_store._ensure_entities(b, "pA", specs)      # would raise before H1
        assert ids_a["App|Main|calc|int"] == ids_b["App|Main|calc|int"], \
            "both writers must end up with the SAME entity id"

    def test_identical_empty_payload_blob_from_two_projects(self):
        """The near-certain case: every entity with an empty payload hashes identically, so two
        jobs on DIFFERENT projects race for one global content_blobs row."""
        eng = _engine()
        h = model_store._content_hash({})
        rows = [{"content_hash": h, "kind": "function", "payload": {}}]
        with eng.begin() as a:
            insert_ignore(a, s.content_blobs, rows)
        with eng.begin() as b:
            insert_ignore(b, s.content_blobs, rows)                   # would raise before H1
        with eng.connect() as cx:
            n = cx.execute(select(func.count()).select_from(s.content_blobs)
                           .where(s.content_blobs.c.content_hash == h)).scalar()
        assert n == 1, "content-addressed: one row, whoever won"

    def test_genuinely_parallel_writers(self, tmp_path):
        """Threads with REAL per-thread connections, so the reads actually interleave.

        A file-backed database, not the in-memory one the other tests use: StaticPool shares a
        single sqlite3 connection across threads, which raises "bad parameter or other API
        misuse" and would test the pool rather than the insert. `timeout` lets a blocked writer
        wait — SQLite serialises writes, so this proves ON CONFLICT DO NOTHING survives
        interleaved READS, which is where the race actually is.
        """
        db = tmp_path / "race.db"
        eng = create_engine(f"sqlite:///{db.as_posix()}",
                            connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(eng, "connect")
        def _fk(dbapi_conn, _rec):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        s.metadata.create_all(eng)
        now = datetime.datetime.now(UTC)
        with eng.begin() as cx:
            cx.execute(insert(s.projects), {"id": "pA", "name": "pA", "created_at": now})
        errors = []
        specs = {f"App|Main|f{i}|void": ("function", f"f{i}") for i in range(40)}

        def worker():
            try:
                with eng.begin() as cx:
                    model_store._ensure_entities(cx, "pA", specs)
            except Exception as exc:                # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, f"concurrent writers raised: {errors[:2]}"
        with eng.connect() as cx:
            n = cx.execute(select(func.count()).select_from(s.entities)).scalar()
        assert n == 40, f"expected 40 distinct entities, got {n}"


class TestChunking:
    def test_insert_ignore_chunks_large_batches(self):
        """A single executemany of 20k rows is one enormous statement. Behaviour must not change
        shape between a small fixture and a real project."""
        eng = _engine()
        rows = [{"content_hash": f"h{i:06d}", "kind": "function", "payload": {}}
                for i in range(MAX_ROWS_PER_STATEMENT + 250)]
        with eng.begin() as cx:
            insert_ignore(cx, s.content_blobs, rows)
        with eng.connect() as cx:
            n = cx.execute(select(func.count()).select_from(s.content_blobs)).scalar()
        assert n == len(rows), "nothing may be dropped at a chunk boundary"

    def test_insert_chunked_keeps_every_row(self):
        eng = _engine()
        with eng.begin() as cx:
            ids = model_store._ensure_entities(
                cx, "pA", {f"k{i}": ("function", f"f{i}") for i in range(3)})
            rows = [{"version_id": "v1", "entity_id": ids[f"k{i}"], "component": "C",
                     "unit": "U", "is_visible": True} for i in range(3)]
            insert_chunked(cx, s.entity_versions, rows)
        with eng.connect() as cx:
            n = cx.execute(select(func.count()).select_from(s.entity_versions)).scalar()
        assert n == 3

    def test_empty_is_a_no_op(self):
        eng = _engine()
        with eng.begin() as cx:
            insert_ignore(cx, s.content_blobs, [])
            insert_chunked(cx, s.entity_versions, [])


class TestOneImplementation:
    def test_pg_stores_uses_the_core_helper(self):
        """Two copies of a dialect branch is how the backends drift apart (D10-2)."""
        from incremental import pg_stores
        assert pg_stores._insert_ignore is insert_ignore
