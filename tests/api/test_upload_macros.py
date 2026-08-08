"""HTTP tests for POST /repositories/uploads — the macro-file upload path.

Two behaviours this guards:
  * per-kind extension validation (definitions accept .csv/.json only), so an
    unreadable file is rejected at upload instead of failing mid-pipeline;
  * bytes are persisted under workspaces/uploads/<id>/ rather than a
    process-local dict, so a job that starts after an API restart can still
    resolve the file its project's build_config points at.

Mark: unit (HTTP against the in-memory DB; writes only into a tmp workspace)
"""
import json

import pytest

from api.routes import repositories

pytestmark = pytest.mark.unit

UPLOAD_URL = "/api/v1/repositories/uploads"

DUMP = json.dumps({
    "metadata": {"fully_resolved": 1, "macro_source": "fromelf_text",
                 "toolchain": "armclang", "total_macros": 1},
    "macros_by_cu": {"fcore": {"SOME_THING": {
        "name": "SOME_THING", "raw_value": "(1)", "expanded_value": "(1)",
        "computed_value": 1, "is_fully_resolved": True,
        "dependency_chain": [], "note": None}}},
}).encode()


@pytest.fixture
def uploads_root(tmp_path, monkeypatch):
    """Point the upload store at a tmp dir so tests never touch real workspaces/."""
    monkeypatch.setattr(repositories, "_upload_dir",
                        lambda upload_id: tmp_path / "uploads" / upload_id)
    repositories._UPLOADS.clear()
    return tmp_path


def _upload(client, auth_header, name, data, kind="preprocessor_definitions"):
    return client.post(UPLOAD_URL, headers=auth_header,
                       files={"file": (name, data, "application/octet-stream")},
                       data={"kind": kind})


class TestAcceptedFiles:
    @pytest.mark.parametrize("name, data", [
        ("fcore_macros.json", DUMP),
        ("macros.csv", b"Name,Value\nVOID,void\n"),
        ("MACROS.JSON", DUMP),                      # extension check is case-insensitive
    ])
    def test_macro_files_are_accepted(self, client, auth_header, uploads_root, name, data):
        r = _upload(client, auth_header, name, data)
        assert r.status_code == 201, r.text
        assert r.json()["file_name"] == name

    def test_data_dictionary_still_accepts_xlsx(self, client, auth_header, uploads_root):
        r = _upload(client, auth_header, "dd.xlsx", b"x", kind="data_dictionary")
        assert r.status_code == 201, r.text


class TestRejectedFiles:
    @pytest.mark.parametrize("name", ["Makefile", "defs.mk", "notes.txt", "noext"])
    def test_unreadable_definition_files_are_rejected(self, client, auth_header,
                                                      uploads_root, name):
        r = _upload(client, auth_header, name, b"DEBUG=1")
        assert r.status_code == 400
        assert ".csv" in r.text and ".json" in r.text

    def test_json_is_not_accepted_as_a_data_dictionary(self, client, auth_header, uploads_root):
        r = _upload(client, auth_header, "dd.json", b"{}", kind="data_dictionary")
        assert r.status_code == 400

    def test_unknown_kind_is_rejected(self, client, auth_header, uploads_root):
        r = _upload(client, auth_header, "m.json", DUMP, kind="something_else")
        assert r.status_code == 400


class TestPersistence:
    def test_bytes_land_on_disk_and_resolve(self, client, auth_header, uploads_root):
        upload_id = _upload(client, auth_header, "fcore_macros.json", DUMP).json()["id"]
        resolved = repositories.resolve_upload(upload_id)
        assert resolved is not None and resolved.is_file()
        assert resolved.read_bytes() == DUMP

    def test_still_resolves_after_an_api_restart(self, client, auth_header, uploads_root):
        """The in-memory index is empty after a restart; the file must still be found."""
        upload_id = _upload(client, auth_header, "fcore_macros.json", DUMP).json()["id"]
        repositories._UPLOADS.clear()
        resolved = repositories.resolve_upload(upload_id)
        assert resolved is not None and resolved.read_bytes() == DUMP

    def test_unknown_id_resolves_to_none(self, uploads_root):
        assert repositories.resolve_upload("up_does_not_exist") is None
        assert repositories.resolve_upload("") is None

    def test_uploaded_dump_is_readable_by_the_engine_reader(self, client, auth_header,
                                                            uploads_root):
        """End of the chain: what the wizard uploads is what the parser can read."""
        import os
        import sys
        engine_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "engine")
        sys.path.insert(0, engine_dir)
        from core.macro_input import GLOBAL_SCOPE, load_macro_defs

        upload_id = _upload(client, auth_header, "fcore_macros.json", DUMP).json()["id"]
        defs, report = load_macro_defs(str(repositories.resolve_upload(upload_id)))
        assert report.kind == "toolchain"
        assert defs[GLOBAL_SCOPE] == {"SOME_THING": "1"}
