"""Download All puts every DOCX in the ZIP under its own file name.

The entries were named after the document (`Lib.docx`). Two layers each with a component called
Lib wrote two entries with one name, and unzipping kept only one of them. The DOCX file name
carries the layer-qualified component id, so it is unique.
"""
import datetime
import io
import uuid
import zipfile
from unittest.mock import patch

from api.models.domain import Document, Version


def test_same_named_components_of_two_layers_are_both_in_the_zip(db, client, auth_header, tmp_path):
    now = datetime.datetime.now(datetime.timezone.utc)
    version = Version(id="ver" + uuid.uuid4().hex[:8], project_id="p1", tag="zip-" + uuid.uuid4().hex[:6],
                      commit_sha="0" * 40, branch="main", description="", status="in_review",
                      docs_count=2, created_by="u1", created_at=now)
    db.versions.create(version)
    for group in ("Layer1.Lib", "Layer2.Lib"):
        d = tmp_path / group
        d.mkdir()
        (d / f"software_detailed_design_{group}.docx").write_bytes(group.encode())
        db.documents.update(Document(          # update() is the upsert
            id="doc" + uuid.uuid4().hex[:8], project_id="p1", version_id=version.id, process="SWE.3",
            name="Lib", subtitle="", layer=group.split(".")[0], group=group, status="in_review",
            due_date=None, created_at=now, updated_at=now))

    with patch("api.services.doc_render.commit_output_root", return_value=tmp_path):
        r = client.get("/api/v1/projects/p1/documents/export-all/download",
                       params={"version_id": version.id}, headers=auth_header)

    assert r.status_code == 200, r.text
    names = sorted(zipfile.ZipFile(io.BytesIO(r.content)).namelist())
    assert names == ["software_detailed_design_Layer1.Lib.docx",
                     "software_detailed_design_Layer2.Lib.docx"]
