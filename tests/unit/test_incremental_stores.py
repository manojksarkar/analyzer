"""Unit tests for src/incremental/stores.py — D9 store interface, JSON impl (M1.3)."""
import json
import os
import sys
import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from incremental.stores import (Workspace, VersionStore, HashStore, EdgeStore,
                                ReuseIndex, WorkspaceNotFound)


def _make_ws(tmp_path, project_id="proj"):
    root = tmp_path / "workspaces" / project_id
    (root / "datadict").mkdir(parents=True)
    (root / "repo").mkdir()
    (root / "project.json").write_text(json.dumps(
        {"projectId": project_id, "layers": {"L1": {"groups": {}}}, "currentDataDictId": "dd-001"}))
    return Workspace(project_id, str(tmp_path / "workspaces"))


class TestWorkspace:
    def test_missing_workspace_raises(self, tmp_path):
        with pytest.raises(WorkspaceNotFound):
            Workspace("nope", str(tmp_path / "workspaces"))

    def test_reads_project_and_paths(self, tmp_path):
        ws = _make_ws(tmp_path)
        assert ws.project()["projectId"] == "proj"
        assert ws.repo_dir.endswith("repo")
        assert ws.datadict_path("dd-001").endswith(os.path.join("datadict", "dd-001.csv"))


class TestVersionStore:
    def test_next_version_id_sequence(self, tmp_path):
        vs = VersionStore(_make_ws(tmp_path))
        assert vs.next_version_id() == "v1"
        vs.create_dir("v1")
        vs.write_manifest("v1", {"versionId": "v1", "status": "complete"})
        assert vs.next_version_id() == "v2"

    def test_create_dir_force(self, tmp_path):
        vs = VersionStore(_make_ws(tmp_path))
        d = vs.create_dir("v1")
        (open(os.path.join(d, "x.txt"), "w")).close()
        with pytest.raises(FileExistsError):
            vs.create_dir("v1")
        vs.create_dir("v1", force=True)  # wipes + recreates
        assert not os.path.isfile(os.path.join(d, "x.txt"))

    def test_manifest_roundtrip_and_index_row(self, tmp_path):
        vs = VersionStore(_make_ws(tmp_path))
        vs.create_dir("v1")
        man = {"versionId": "v1", "branch": "main", "commit": "abc", "scope": {"type": "project"},
               "decision": "full", "regenerated": 5, "reused": 0, "status": "complete",
               "createdAt": "t", "recipeFingerprint": "rfp"}
        vs.write_manifest("v1", man)
        assert vs.get("v1")["recipeFingerprint"] == "rfp"     # full manifest kept
        rows = vs.list()
        assert len(rows) == 1 and rows[0]["versionId"] == "v1"
        assert "recipeFingerprint" not in rows[0]              # index row is compact

    def test_index_newest_first_and_upsert(self, tmp_path):
        vs = VersionStore(_make_ws(tmp_path))
        for vid in ("v1", "v2"):
            vs.create_dir(vid)
            vs.write_manifest(vid, {"versionId": vid, "status": "complete"})
        assert [r["versionId"] for r in vs.list()] == ["v2", "v1"]
        # re-writing v1 upserts (no duplicate row), moves it to front
        vs.write_manifest("v1", {"versionId": "v1", "status": "complete"})
        ids = [r["versionId"] for r in vs.list()]
        assert ids.count("v1") == 1

    def test_capture_artifacts_collects_docx(self, tmp_path):
        ws = _make_ws(tmp_path)
        vs = VersionStore(ws)
        vs.create_dir("v1")
        model = tmp_path / "model"; model.mkdir(); (model / "functions.json").write_text("{}")
        out = tmp_path / "output" / "G"; out.mkdir(parents=True)
        (out / "software_detailed_design_G.docx").write_bytes(b"PK\x03\x04")
        (out / "interface_tables.json").write_text("{}")
        docs = vs.capture_artifacts("v1", model_dir=str(model), output_dir=str(tmp_path / "output"))
        assert docs == ["software_detailed_design_G.docx"]
        vd = vs.version_dir("v1")
        assert os.path.isfile(os.path.join(vd, "model", "functions.json"))
        assert os.path.isfile(os.path.join(vd, "documents", "software_detailed_design_G.docx"))


class TestHashEdgeStore:
    def test_hash_and_edge_roundtrip(self, tmp_path):
        vs = VersionStore(_make_ws(tmp_path)); vs.create_dir("v1")
        HashStore(vs).write("v1", {"K|U|f|": "deadbeef"})
        EdgeStore(vs).write("v1", {"typeUsers": {"T": ["K|U|f|"]}, "macroUsers": {}})
        assert HashStore(vs).read("v1") == {"K|U|f|": "deadbeef"}
        assert EdgeStore(vs).read("v1")["typeUsers"] == {"T": ["K|U|f|"]}

    def test_missing_reads_return_empty(self, tmp_path):
        vs = VersionStore(_make_ws(tmp_path))
        assert HashStore(vs).read("vX") == {}
        assert EdgeStore(vs).read("vX") == {"typeUsers": {}, "macroUsers": {}}


class TestReuseIndex:
    def test_put_first_wins_and_persist(self, tmp_path):
        ws = _make_ws(tmp_path)
        ri = ReuseIndex(ws)
        assert ri.put("fp1", "v1", "K|U|a|") is True
        assert ri.put("fp1", "v2", "K|U|a|") is False        # first version keeps it
        assert ri.get("fp1") == {"versionId": "v1", "entityKey": "K|U|a|"}
        ri.save()
        # reload from disk
        ri2 = ReuseIndex(ws)
        assert ri2.get("fp1")["versionId"] == "v1"
        assert len(ri2) == 1

    def test_overwrite_flag(self, tmp_path):
        ri = ReuseIndex(_make_ws(tmp_path))
        ri.put("fp", "v1", "k")
        assert ri.put("fp", "v9", "k", overwrite=True) is True
        assert ri.get("fp")["versionId"] == "v9"
