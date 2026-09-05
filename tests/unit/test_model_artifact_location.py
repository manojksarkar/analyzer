"""Model artifacts live in the database, and the logs must say so.

Phase summaries printed `model/functions.json (2818)` whatever the run had done. That file
has not existed since the file backing was removed -- `repository()` has no default any
more, and every artifact is registered in DB_BACKED -- so the line pointed a reader at a
path nobody wrote. It cost a real reader real time.

The same wording hid a genuine defect next door: `swe4_exporter` opened
`MODEL_DIR/metadata.json` directly behind an `os.path.isfile` guard, so in database mode
the guard was simply false and every SWE.4 cover page read "Software Project" instead of
the project's name. Silent, because a missing file was treated as "no name available".
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from core import model_repo
from core.model_io import artifact_location


class _Db(model_repo.DbRepository):
    def __init__(self):
        pass                       # describe() reads no state


@pytest.fixture
def db_repo():
    before = model_repo._ACTIVE
    model_repo._ACTIVE = _Db()
    yield
    model_repo._ACTIVE = before


class TestArtifactLocation:
    def test_says_database_not_a_filename(self, db_repo):
        for name in ("functions", "globalVariables", "knowledge_base", "metadata"):
            where = artifact_location(name)
            assert "database" in where
            assert ".json" not in where, f"{name} named a file that is not written"

    def test_distinguishes_buffered_from_immediate(self, db_repo):
        # Worth showing: a coupled artifact is not in the database until the flush, which is
        # where a failure surfaces (a NUL in a description killed exactly that step).
        assert "flush" in artifact_location("functions")
        assert artifact_location("knowledge_base") == "database"
        assert "parse_snapshots" in artifact_location("metadata")

    def test_never_raises_without_a_repository(self):
        before = model_repo._ACTIVE
        model_repo._ACTIVE = None
        try:
            assert artifact_location("functions") == "?"
        finally:
            model_repo._ACTIVE = before

    def test_scratch_mode_reports_the_real_file(self, tmp_path, monkeypatch):
        # The narrowed parse's partial pass DOES write files; the label must follow.
        monkeypatch.setattr(model_repo, "_scratch_path",
                            lambda name: os.path.join(str(tmp_path), name + ".json"))
        before = model_repo._ACTIVE
        model_repo._ACTIVE = model_repo.ScratchRepository()
        try:
            assert artifact_location("functions").endswith("functions.json")
        finally:
            model_repo._ACTIVE = before


class TestSwe4ReadsMetadataThroughTheGateway:
    def test_no_direct_metadata_file_read(self):
        src = open(os.path.join(PROJECT_ROOT, "engine", "swe4_exporter.py"),
                   encoding="utf-8").read()
        assert 'os.path.join(MODEL_DIR, "metadata.json")' not in src, (
            "metadata is DB_BACKED_PARSE; a direct file read silently yields no project name")
        assert "load_model_json" in src, "it must resolve metadata through the gateway"

    def test_swe3_and_swe4_agree_on_the_source(self):
        # The SWE.3 exporter already reads metadata through the gateway. Both documents come
        # from one run and must not disagree about the project's name.
        for mod, needle in (("docx_exporter.py", "read_model_file"),
                            ("swe4_exporter.py", "load_model_json")):
            src = open(os.path.join(PROJECT_ROOT, "engine", mod), encoding="utf-8").read()
            assert needle in src
