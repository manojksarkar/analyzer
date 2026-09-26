"""A finished run registers one document per component DOCX it wrote.

The engine names each component's output dir -- and its DOCX -- by the component's
LAYER-QUALIFIED id (`Layer1.Sample-Core`) since group and component ids carry their layer
(1df3016). `_make_documents` still matched dirs against the bare component name, so it matched
none: every run from the web app finished with its documents on disk and no `documents` rows,
and the document list was empty.
"""
import datetime
import uuid
from unittest.mock import patch

from api.models.domain import Project, Version
from api.services import pipeline_runner as pr

LAYERS = [{"name": "Layer1", "path": "Layer1", "groups": [{"name": "My Sample", "components": [
    {"name": "Sample Core", "files": ["Layer1/Sample/Core"]},
    {"name": "Lib", "files": ["Layer1/Sample/Lib"]}]}]},
          {"name": "Layer2", "path": "Layer2", "groups": [{"name": "My Sample", "components": [
              {"name": "Lib", "files": ["Layer2/Sample/Lib"]}]}]}]


def _project(db):
    pid = "pdr" + uuid.uuid4().hex[:6]
    now = datetime.datetime.now(datetime.timezone.utc)
    project = Project(
        id=pid, org_id="org1", name=pid, client="c", compliance_standard="ASPICE_L2",
        repo_url="https://example.invalid/r.git", repo_provider="github",
        default_branch="main", build_config={}, architecture_layers=LAYERS,
        status="not_run", created_by="u1", created_at=now, updated_at=now)
    db.projects.create(project)
    return project


def _write_docx(out_root, dir_name):
    d = out_root / dir_name
    d.mkdir(parents=True)
    (d / f"software_detailed_design_{dir_name}.docx").write_bytes(b"PK")


def _register(db, tmp_path, dirs):
    project = _project(db)
    out_root = tmp_path / "output"
    out_root.mkdir()
    for name in dirs:
        _write_docx(out_root, name)
    now = datetime.datetime.now(datetime.timezone.utc)
    version = Version(id="ver" + uuid.uuid4().hex[:8], project_id=project.id, tag="v1",
                      commit_sha="0" * 40, branch="main", description="", status="in_review",
                      docs_count=0, created_by="u1", created_at=now)
    db.versions.create(version)
    with patch("api.services.doc_render.commit_output_root", return_value=out_root):
        return pr._make_documents(db, project, version, now)


class TestOneDocumentPerComponentDocx:
    def test_the_layer_qualified_dirs_the_engine_writes_are_registered(self, db, tmp_path):
        docs = _register(db, tmp_path, ["Layer1.Sample-Core", "Layer1.Lib", "Layer2.Lib"])
        got = sorted((d.name, d.layer, d.group) for d in docs)
        assert got == [("Lib", "Layer1", "Layer1.Lib"),
                       ("Lib", "Layer2", "Layer2.Lib"),
                       ("Sample Core", "Layer1", "Layer1.Sample-Core")]

    def test_the_group_is_the_dir_the_download_reads(self, db, tmp_path):
        """`group` is what find_docx / output_group_dir are handed, so it has to be the dir."""
        from api.services.doc_render import find_docx
        docs = _register(db, tmp_path, ["Layer1.Sample-Core"])
        assert len(docs) == 1
        assert find_docx(docs[0].group, tmp_path / "output") is not None

    def test_a_dir_no_component_declares_is_skipped(self, db, tmp_path):
        docs = _register(db, tmp_path, ["Layer1.Stale", "Layer3.Lib"])
        assert docs == []
