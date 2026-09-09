"""Unit tests for src/incremental/stores.py — D9 store interface, JSON impl (M1.3)."""
import json
import os
import sys
import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from incremental.stores import Workspace, VersionStore, WorkspaceNotFound


def _make_ws(tmp_path, project_id="proj"):
    # The root must exist; project + version metadata now come from api/db/data (not a
    # workspaces/<pid>/project.json), so the workspace itself just needs its dirs.
    root = tmp_path / "workspaces" / project_id
    (root / "datadict").mkdir(parents=True)
    return Workspace(project_id, str(tmp_path / "workspaces"))


class TestWorkspace:
    def test_missing_workspace_raises(self, tmp_path):
        with pytest.raises(WorkspaceNotFound):
            Workspace("nope", str(tmp_path / "workspaces"))

    def test_paths(self, tmp_path):
        ws = _make_ws(tmp_path)
        # Versions are commit-addressed: the per-commit dir IS the version dir (commit[:16]).
        assert ws.commit_dir("08d2f565cd03e72e82c32b57").endswith("08d2f565cd03e72e")
        assert ws.cache_dir.endswith("cache")
        assert ws.datadict_path("dd-001").endswith(os.path.join("datadict", "dd-001.csv"))


class TestVersionStore:
    def test_create_dir_idempotent(self, tmp_path):
        # The version dir == the commit dir (it holds the git checkout), so create_dir NEVER
        # wipes it — it ensures it exists and returns it; a re-create keeps existing files.
        vs = VersionStore(_make_ws(tmp_path))
        d = vs.create_dir("08d2f565cd03e72e")
        open(os.path.join(d, "x.txt"), "w").close()
        assert vs.create_dir("08d2f565cd03e72e") == d        # no raise
        assert os.path.isfile(os.path.join(d, "x.txt"))      # not wiped


    # capture_artifacts (model+output -> the commit dir) was removed in the PG-7b cutover: the
    # store now owns artifacts (ArtifactStore.capture_output -> versions/<ver…>/, model -> the
    # store). Its equivalent is covered by tests/unit/test_output_files_store.py.




