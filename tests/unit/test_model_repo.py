"""core/model_repo — the seam model_io reads and writes through (doc 10, step 2).

The point of the seam is that `read_model_file(FUNCTIONS)` returns the same dict whether the
model is in files or in the database, so the phases need no changes. These tests hold that
equivalence, and pin the three behaviours that are easy to get wrong:

  * a phase must see its OWN writes before they are flushed (Phase 2 writes functions, then
    reads them back);
  * a flush must not delete rows the phase did not mention (Phase 2 rewrites functions but not
    units — persisting only what was written would drop the units);
  * anything the database does not back yet must fall through to files, so this can be switched
    on before every artifact has moved.
"""
import datetime
import json
import os
import sys

import pytest
from sqlalchemy import create_engine, event, insert
from sqlalchemy.pool import StaticPool

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "engine"))

from api.db.postgres import schema as s              # noqa: E402
from core import model_repo                          # noqa: E402
from core.model_io import ModelFileMissing           # noqa: E402

UTC = datetime.timezone.utc
PID, VID = "proj-repo", "ver-repo"

FUNCS = {"App|Main|calc|int": {"qualifiedName": "calc", "returnType": "int",
                              "description": "Adds two numbers.",
                              "location": {"file": "App/Main.cpp", "line": 10},
                              "callsIds": [], "readsGlobalIds": [], "writesGlobalIds": []}}
HASHES = {"App|Main|calc|int": "aaa"}
UNITS = {"App|Main": {"component": "App", "name": "Main"}}


@pytest.fixture
def db(monkeypatch):
    """A FK-enforcing SQLite database with the parent rows, wired in as the process engine."""
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)

    @event.listens_for(eng, "connect")
    def _fk(dbapi_conn, _rec):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    s.metadata.create_all(eng)
    now = datetime.datetime.now(UTC)
    with eng.begin() as cx:
        cx.execute(insert(s.projects), {"id": PID, "name": "R", "created_at": now})
        cx.execute(insert(s.versions),
                   {"id": VID, "project_id": PID, "version": "v1", "created_at": now})
    import core.db as coredb
    monkeypatch.setattr(coredb, "get_engine", lambda *a, **k: eng)
    yield eng
    model_repo.set_repository(None)


def _repo(db):
    r = model_repo.DbRepository(VID, PID)
    model_repo.set_repository(r)
    return r


class TestEmptyIsNotMissing:
    """A project with no global variables must not fail.

    `_is_absent` treats an empty artifact as missing, which is right when nothing has been
    written and wrong once something has: `globalVariables` is legitimately `{}` on a project
    that declares none. Phase 2 then died with "model 'globalVariables' is not in the database.
    Run the upstream phase first" on a model that was perfectly complete.

    The file path never had this ambiguity — Phase 1 wrote `globalVariables.json` containing
    `{}`, and an empty file is still a file. Caught by `verify_incremental.py` the moment that
    gate moved off the file path; the fixture there has functions and no globals.
    """

    def test_an_empty_artifact_reads_as_empty_once_a_model_exists(self, db):
        from core.model_io import read_model_file, write_model_file, FUNCTIONS, GLOBALS, HASHES as H
        repo = _repo(db)
        write_model_file(FUNCTIONS, FUNCS)
        write_model_file(H, HASHES)
        write_model_file(GLOBALS, {})                 # a project with no globals
        repo.flush()

        fresh = model_repo.DbRepository(VID, PID)
        model_repo.set_repository(fresh)
        assert read_model_file(GLOBALS) == {}, "an empty artifact must not read as missing"

    def test_still_missing_when_nothing_was_ever_written(self, db):
        """The guard must not swing the other way: a phase reading before its upstream ran
        should still be told so, or it silently produces an empty document."""
        from core.model_io import read_model_file, GLOBALS, ModelFileMissing
        _repo(db)
        with pytest.raises(ModelFileMissing):
            read_model_file(GLOBALS)


class TestDatabaseBacking:
    def test_write_then_read_through_model_io(self, db):
        """The whole point: model_io's API, database underneath."""
        from core.model_io import read_model_file, write_model_file, FUNCTIONS, HASHES as H
        repo = _repo(db)
        write_model_file(FUNCTIONS, FUNCS)
        write_model_file(H, HASHES)

        # visible to this phase BEFORE the flush
        assert read_model_file(FUNCTIONS)["App|Main|calc|int"]["description"] == "Adds two numbers."

        repo.flush()
        # and to a FRESH repository afterwards — i.e. it really landed
        fresh = model_repo.DbRepository(VID, PID)
        model_repo.set_repository(fresh)
        got = read_model_file(FUNCTIONS)
        assert set(got) == set(FUNCS)
        assert got["App|Main|calc|int"]["returnType"] == "int"
        assert read_model_file(H) == HASHES

    def test_flush_does_not_delete_what_the_phase_did_not_write(self, db):
        """Phase 2 rewrites functions but not units. Persisting only the pending pieces would
        drop the units — the flush has to complete itself from what is stored."""
        from core.model_io import read_model_file, write_model_file, FUNCTIONS, UNITS as U, HASHES as H
        repo = _repo(db)
        write_model_file(FUNCTIONS, FUNCS)
        write_model_file(H, HASHES)
        write_model_file(U, UNITS)
        repo.flush()

        # a later phase rewrites ONLY functions (with a description filled in)
        repo2 = model_repo.DbRepository(VID, PID)
        model_repo.set_repository(repo2)
        enriched = json.loads(json.dumps(FUNCS))
        enriched["App|Main|calc|int"]["description"] = "Enriched by phase 2."
        write_model_file(FUNCTIONS, enriched)
        repo2.flush()

        fresh = model_repo.DbRepository(VID, PID)
        model_repo.set_repository(fresh)
        assert read_model_file(FUNCTIONS)["App|Main|calc|int"]["description"] == "Enriched by phase 2."
        assert set(read_model_file(U)) == set(UNITS), "units must survive a functions-only phase"

    def test_missing_required_raises_the_same_error_as_a_missing_file(self, db):
        from core.model_io import read_model_file, FUNCTIONS
        _repo(db)
        with pytest.raises(ModelFileMissing):
            read_model_file(FUNCTIONS)

    def test_missing_optional_returns_the_default(self, db):
        from core.model_io import read_model_file, SUMMARIES
        _repo(db)
        assert read_model_file(SUMMARIES, required=False, default={}) == {}

    def test_model_files_present_answers_from_the_database(self, db):
        from core.model_io import model_files_present, write_model_file, FUNCTIONS, HASHES as H
        repo = _repo(db)
        assert model_files_present(FUNCTIONS) == [FUNCTIONS]      # absent
        write_model_file(FUNCTIONS, FUNCS); write_model_file(H, HASHES)
        assert model_files_present(FUNCTIONS) == []               # pending counts as present
        repo.flush()
        assert model_files_present(FUNCTIONS) == []

    def test_a_version_id_is_required(self, db):
        """A phase must be told WHICH model it is working on (D10-8)."""
        with pytest.raises(ValueError, match="version_id"):
            model_repo.DbRepository("", PID)






class TestStandaloneArtifacts:
    """knowledge_base / incremental_plan / tu_includes have their OWN tables (doc 10, step 6).

    They are hand-offs — one phase writes, another reads — with no coupling to the rest of the
    model, so a write lands immediately rather than waiting for the flush. A phase must be able
    to pass the plan on without also rewriting the whole model.
    """

    @pytest.mark.parametrize("name,payload", [
        ("knowledge_base", {"project": "P", "components": {"App": {}}}),
        ("incremental_plan", {"impactFids": ["App|Main|calc|int"], "flowchartFids": []}),
        ("tu_includes", {"App/Main.cpp": ["App/Main.h", "Lib/Util.h"]}),
    ])
    def test_round_trip_without_a_flush(self, db, name, payload):
        from core.model_io import read_model_file, write_model_file
        _repo(db)
        write_model_file(name, payload)
        # NO flush — a standalone artifact must be visible to the next phase immediately
        fresh = model_repo.DbRepository(VID, PID)
        model_repo.set_repository(fresh)
        assert read_model_file(name) == payload

    def test_writing_an_empty_plan_clears_a_previous_one(self, db):
        """An absent plan means "regenerate everything". Leaving a stale row behind would make a
        FULL run inherit the last incremental run's restriction and regenerate almost nothing."""
        from core.model_io import read_model_file, write_model_file, INCREMENTAL_PLAN
        _repo(db)
        write_model_file(INCREMENTAL_PLAN, {"impactFids": ["a"]})
        write_model_file(INCREMENTAL_PLAN, {})
        fresh = model_repo.DbRepository(VID, PID)
        model_repo.set_repository(fresh)
        assert read_model_file(INCREMENTAL_PLAN, required=False, default={}) == {}

    def test_absent_optional_is_the_default(self, db):
        from core.model_io import read_model_file, INCREMENTAL_PLAN
        _repo(db)
        assert read_model_file(INCREMENTAL_PLAN, required=False, default={}) == {}

    def test_tu_includes_is_stored_per_tu(self, db):
        """One row per TU on the (version_id, tu_path) index, so a reader can look up a single
        header instead of pulling the whole map. The table existed and nothing wrote it."""
        from sqlalchemy import func, select as _select
        from core.model_io import write_model_file, TU_INCLUDES
        _repo(db)
        write_model_file(TU_INCLUDES, {f"f{i}.cpp": [f"h{i}.h"] for i in range(5)})
        with db.connect() as cx:
            n = cx.execute(_select(func.count()).select_from(s.tu_includes)).scalar()
        assert n == 5, "expected one row per TU, not a single blob"
