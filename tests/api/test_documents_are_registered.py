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


def _write_docx(out_root, dir_name, prefixes=("software_detailed_design",)):
    d = out_root / dir_name
    d.mkdir(parents=True)
    for prefix in prefixes:
        (d / f"{prefix}_{dir_name}.docx").write_bytes(b"PK")


def _register(db, tmp_path, dirs, prefixes=("software_detailed_design",)):
    project = _project(db)
    out_root = tmp_path / "output"
    out_root.mkdir()
    for name in dirs:
        _write_docx(out_root, name, prefixes)
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


BOTH = ("software_detailed_design", "software_unit_test_specification")


class TestTheUnitTestSpecificationBesideIt:
    """A run writes a component's SWE.4 DOCX next to its SWE.3 one; each is a document."""

    def test_both_documents_of_a_component_are_registered(self, db, tmp_path):
        docs = _register(db, tmp_path, ["Layer1.Lib", "Layer2.Lib"], BOTH)
        got = sorted((d.process, d.group, d.subtitle) for d in docs)
        assert got == [("SWE.3", "Layer1.Lib", "Detailed Design"),
                       ("SWE.3", "Layer2.Lib", "Detailed Design"),
                       ("SWE.4", "Layer1.Lib", "Unit Test Specification"),
                       ("SWE.4", "Layer2.Lib", "Unit Test Specification")]

    def test_each_finds_its_own_file(self, db, tmp_path):
        from api.services.doc_render import find_docx
        docs = _register(db, tmp_path, ["Layer1.Lib"], BOTH)
        files = {d.process: find_docx(d.group, tmp_path / "output", d.process).name for d in docs}
        assert files == {"SWE.3": "software_detailed_design_Layer1.Lib.docx",
                         "SWE.4": "software_unit_test_specification_Layer1.Lib.docx"}

    def test_no_swe4_file_no_swe4_document(self, db, tmp_path):
        docs = _register(db, tmp_path, ["Layer1.Lib"])
        assert [d.process for d in docs] == ["SWE.3"]

    def test_a_swe4_document_gets_the_chapters_of_its_docx(self, db, tmp_path):
        docs = _register(db, tmp_path, ["Layer1.Lib"], BOTH)
        now = datetime.datetime.now(datetime.timezone.utc)
        pr._make_sections(db, docs, now, tmp_path / "output")
        swe4 = next(d for d in docs if d.process == "SWE.4")
        keys = [s.section_key for s in sorted(db.documents.list_sections(swe4.id), key=lambda s: s.order)]
        assert keys == ["intro", "test_spec", "metrics"]
