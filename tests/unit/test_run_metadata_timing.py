"""`versions.base_path` must exist BEFORE Phase 3 runs.

Reported from a real run: every flowchart came back empty with
`"error": "Source file not found: Layer1\App\Main.cpp"` — the RELATIVE path, meaning the
flowchart engine had rooted its `SourceExtractor` at "" or ".".

Two independent causes, both introduced by moving the model into the database:

  1. Both orchestrators read `model/metadata.json` off disk to populate the `versions` columns.
     Step 11a routed `metadata` into `parse_snapshots`, so that file stopped existing — one
     orchestrator then skipped the write entirely, the other stored `{}`.
  2. Even once read correctly, the write happened at the END of the run. Phase 3 executes
     inside the analyzer subprocess, i.e. BEFORE that point, so the engine still read NULL.

Both were silent: the run succeeded, the document was produced, and only the flowchart JSON
carried the error. These pin the read SOURCE and the write ORDER.
"""
import os
import re
import sys

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "engine"))


def _src(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


class TestItReadsFromTheRightBacking:
    def test_metadata_comes_from_the_repository_not_the_file(self):
        src = _src(os.path.join("engine", "incremental", "generate.py"))
        assert "def run_metadata(" in src
        assert 'DbRepository(version_id, project_id or "").read(' in src

    @pytest.mark.parametrize("name", ["generate.py", "engine.py"])
    def test_no_orchestrator_opens_metadata_json_directly(self, name):
        """The read that silently stopped working. Comments are stripped: both files explain
        the history in prose, which is worth keeping."""
        code = "".join(ln for ln in _src(os.path.join("engine", "incremental", name)).splitlines(True)
                       if not ln.lstrip().startswith("#"))
        assert '_read(model_dir, "metadata.json")' not in code
        assert 'os.path.join(model_dir, "metadata.json")' not in code or \
               "def run_metadata(" in code, f"{name}: still reads metadata.json off disk"


class TestItIsWrittenBeforePhase3:
    """The ordering half. Phase 3 is inside the analyzer subprocess, so the write has to come
    before that subprocess starts, not after it returns."""

    def test_generate_full_persists_before_running_phase_2_onwards(self):
        src = _src(os.path.join("engine", "incremental", "generate.py"))
        i_persist = src.index("_persist_run_metadata(store, version_id, project_id, model_dir")
        i_phase2 = src.index('base_cmd + ["--from-phase", "2", repo_dir]')
        assert i_persist < i_phase2, \
            "run metadata is written after the phases that need it — base_path will be NULL"

    def test_the_incremental_engine_persists_right_after_the_snapshot(self):
        src = _src(os.path.join("engine", "incremental", "engine.py"))
        i_snap = src.index("snapshot_parse_model(model_dir, _adir, store, version_id")
        i_persist = src.index("_persist_run_metadata(", i_snap)
        between = src[i_snap:i_persist]
        assert between.count("\n") < 12, \
            "the persist drifted away from the post-Phase-1 point it has to sit at"

    @pytest.mark.parametrize("name", ["generate.py", "engine.py"])
    def test_both_still_persist_at_the_end_too(self, name):
        """Idempotent second write, so a metadata refresh later in the run is not lost."""
        src = _src(os.path.join("engine", "incremental", name))
        assert src.count("_persist_run_metadata(") >= 2, \
            f"{name}: expected a post-Phase-1 write AND an end-of-run refresh"


class TestEmptyMetadataIsAudible:
    def test_it_warns_rather_than_passing_silently(self):
        """The original failure produced no log line at all — the only evidence was an error
        field inside a JSON file nobody opens on a green run."""
        src = _src(os.path.join("engine", "incremental", "generate.py"))
        i = src.index("def _persist_run_metadata(")
        body = src[i:i + 1200]
        assert "warning(" in body
        assert "base_path" in body
