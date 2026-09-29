"""A config file in and out of the New Project wizard (api/services/project_config.py).

`POST /projects/config/preview` fills the wizard from a config file -- as far as the file goes --
and reports what it could not fill; `GET /projects/{id}/config` writes a project back out as a
config file. The format is the engine's, plus an optional `project` block.
"""
import datetime
import uuid

import pytest

from api.models.domain import Project, ProjectMember
from api.services import project_config as pc
from api.services.pipeline_runner import _convert_layers

CONFIG = """
// a CLI config, comments and trailing commas included
{
  "project": {"name": "Brake ECU", "repository": "https://example.invalid/brake.git", "branch": "dev"},
  "layers": {
    "Layer1": {
      "path": "Layer1",
      "cores": ["Core1"],
      "groups": {
        "My Sample": {"Sample Core": "Sample/Core", "Both": ["Math/Utils.cpp", "App"],},
      },
    },
  },
  "cores": {"Core1": {"macros": "cfg/macros.json", "dataDictionary": "C:\\\\work\\\\dd.csv",
                      "compileCommands": "build/compile_commands.json"}},
  "clang": {"llvmLibPath": "C:/LLVM/bin/libclang.dll", "clangArgs": ["--target=arm-none-eabi"]},
  "views": {"flowcharts": true, "behaviourDiagram": false},
  "llm": {"baseUrl": "http://secret-gateway"},
}
"""

TREE = [
    {"type": "folder", "name": "Layer1", "path": "Layer1", "children": [
        {"type": "folder", "name": "Sample", "path": "Layer1/Sample", "children": [
            {"type": "folder", "name": "Core", "path": "Layer1/Sample/Core", "children": [
                {"type": "file", "name": "Core.cpp", "path": "Layer1/Sample/Core/Core.cpp"}]}]},
        {"type": "folder", "name": "Math", "path": "Layer1/Math", "children": [
            {"type": "file", "name": "Utils.cpp", "path": "Layer1/Math/Utils.cpp"}]}]},
    {"type": "folder", "name": "cfg", "path": "cfg", "children": [
        {"type": "file", "name": "macros.json", "path": "cfg/macros.json"}]},
]


def _texts(result, level):
    return [i["text"] for i in result["report"] if i["level"] == level]


class TestParse:
    def test_comments_and_trailing_commas_are_read(self):
        assert pc.parse(CONFIG)["project"]["name"] == "Brake ECU"

    def test_a_broken_file_says_where(self):
        with pytest.raises(pc.ConfigError, match="line 3"):
            pc.parse('{\n  "layers": {}\n  "views": {}\n}')

    def test_the_top_level_is_an_object(self):
        with pytest.raises(pc.ConfigError, match="object"):
            pc.parse("[1, 2]")


class TestWithoutTheRepository:
    def setup_method(self):
        self.r = pc.preview(pc.parse(CONFIG))
        self.d = self.r["draft"]

    def test_the_project_block_fills_step_one(self):
        assert (self.d["name"], self.d["repo_url"], self.d["branch"]) == (
            "Brake ECU", "https://example.invalid/brake.git", "dev")

    def test_layers_become_the_wizard_tree_with_paths_from_the_repo_root(self):
        comps = self.d["architecture_layers"][0]["groups"][0]["components"]
        assert [(c["name"], c["files"]) for c in comps] == [
            ("Sample Core", ["Layer1/Sample/Core"]),
            ("Both", ["Layer1/Math/Utils.cpp", "Layer1/App"])]
        assert "Paths are checked" in " ".join(_texts(self.r, "check"))

    def test_core_files_on_another_machine_are_left_to_upload(self):
        assert self.r["expected_uploads"] == {"definitions": "macros.json", "data_dictionary": "dd.csv"}
        assert self.d["definitions"] is None and self.d["data_dictionary"] is None

    def test_project_settings_are_kept_and_machine_and_server_ones_are_not(self):
        assert self.d["settings"] == {"clang": {"clangArgs": ["--target=arm-none-eabi"]},
                                      "views": {"flowcharts": True, "behaviourDiagram": False}}
        skipped = " ".join(_texts(self.r, "skipped"))
        assert "clang.llvmLibPath" in skipped and "`llm`" in skipped
        assert "compileCommands" in skipped


class TestTokensAreNeverRead:
    @pytest.mark.parametrize("text", [
        '{"project": {"name": "x", "token": "ghp_secret"}}',
        '{"accessToken": "ghp_secret", "layers": {}}',
    ])
    def test_a_token_in_the_file_is_reported_and_not_used(self, text):
        r = pc.preview(pc.parse(text))
        assert "ghp_secret" not in str(r["draft"])
        assert any("tokens are never read" in t for t in _texts(r, "skipped"))


class TestDefinitions:
    def test_project_defines_become_typed_definitions(self):
        r = pc.preview(pc.parse('{"project": {"defines": ["DEBUG=1", "ARM"]}, "layers": {}}'))
        assert r["draft"]["definitions"] == {"mode": "manual", "defines": ["DEBUG=1", "ARM"]}

    def test_a_definitions_file_wins_over_project_defines(self):
        r = pc.preview(pc.parse(
            '{"project": {"defines": ["X"]}, "layers": {"L": {"path": "L", "cores": ["C"],'
            ' "groups": {}}}, "cores": {"C": {"macros": "m.json"}}}'))
        assert r["draft"]["definitions"] is None
        assert r["expected_uploads"]["definitions"] == "m.json"
        assert any("project.defines" in t for t in _texts(r, "skipped"))

    def test_only_the_first_core_is_used(self):
        r = pc.preview(pc.parse(
            '{"layers": {"A": {"cores": ["C1"], "groups": {}}, "B": {"cores": ["C2"], "groups": {}}},'
            ' "cores": {"C1": {"macros": "one.json"}, "C2": {"macros": "two.json"}}}'))
        assert r["expected_uploads"]["definitions"] == "one.json"
        assert any("Not read: C2" in t for t in _texts(r, "skipped"))


class TestWithTheRepository:
    def _preview(self, text=CONFIG, read=None):
        stored = []
        r = pc.preview(
            pc.parse(text), tree_nodes=TREE,
            read_file=read or (lambda p: b'["FROM_REPO=1"]' if p == "cfg/macros.json" else None),
            store_file=lambda data, name, kind: stored.append((name, kind, data))
            or {"id": "up_1", "file_name": name, "size": len(data)})
        return r, stored

    def test_paths_not_in_the_repository_are_left_out_and_named(self):
        r, _ = self._preview()
        comps = r["draft"]["architecture_layers"][0]["groups"][0]["components"]
        assert comps[1]["files"] == ["Layer1/Math/Utils.cpp"]
        assert any("`Layer1/App`" in t for t in _texts(r, "check"))

    def test_a_path_spelled_in_another_case_takes_the_repositorys_spelling(self):
        r, _ = self._preview(CONFIG.replace('"Sample/Core"', '"sample/core"'))
        comps = r["draft"]["architecture_layers"][0]["groups"][0]["components"]
        assert comps[0]["files"] == ["Layer1/Sample/Core"]

    def test_a_definitions_file_in_the_repository_is_read_as_an_upload(self):
        r, stored = self._preview()
        assert stored == [("macros.json", "preprocessor_definitions", b'["FROM_REPO=1"]')]
        assert r["draft"]["definitions"] == {"mode": "upload", "file_id": "up_1",
                                             "file_name": "macros.json", "size": 15}
        # the data dictionary is a Windows path: never looked up in the repository
        assert r["expected_uploads"] == {"definitions": None, "data_dictionary": "dd.csv"}

    def test_an_unusable_file_is_reported_not_stored(self):
        def refuse(data, name, kind):
            raise ValueError("'macros.json' is not a supported file.")
        r = pc.preview(pc.parse(CONFIG), tree_nodes=TREE, read_file=lambda p: b"x", store_file=refuse)
        assert r["draft"]["definitions"] is None
        assert r["expected_uploads"]["definitions"] == "macros.json"
        assert any("could not be used" in t for t in _texts(r, "check"))


class TestRoutes:
    def test_preview_fills_the_wizard(self, client, auth_header):
        r = client.post("/api/v1/projects/config/preview", headers=auth_header, json={"text": CONFIG})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["draft"]["name"] == "Brake ECU"
        assert body["repository_checked"] is False

    def test_a_broken_file_is_a_400_that_says_why(self, client, auth_header):
        r = client.post("/api/v1/projects/config/preview", headers=auth_header, json={"text": "{nope"})
        assert r.status_code == 400
        assert "not a readable config file" in r.json()["detail"]["message"]

    def test_download_is_the_project_as_a_config_without_the_token(self, db, client, auth_header):
        pid = "pcfg" + uuid.uuid4().hex[:6]
        now = datetime.datetime.now(datetime.timezone.utc)
        layers = [{"name": "LAYER1", "path": "Layer1", "lib_paths": [], "groups": [
            {"name": "My Sample", "components": [
                {"name": "Lib", "files": ["Layer1/Sample/Lib/Lib.cpp", "Layer1/Sample/Lib/Lib.h"]}]}]}]
        db.projects.create(Project(
            id=pid, org_id="org1", name="Brake ECU", client="", compliance_standard="ISO_26262",
            repo_url="https://example.invalid/brake.git", repo_provider="github",
            default_branch="dev", architecture_layers=layers, status="not_run",
            created_by="u1", created_at=now, updated_at=now,
            build_config={"repo_access_token": "ghp_secret",
                          "preprocessor_definitions": {"mode": "upload", "file_id": "up_a",
                                                       "file_name": "macros.json"},
                          "data_dictionary": {"file_id": "up_b", "file_name": "dd.csv"},
                          "views": {"flowcharts": True}}))
        db.members.add_member(ProjectMember(
            id="m" + uuid.uuid4().hex[:8], project_id=pid, user_id="u1", role="admin",
            status="active", invited_by="u1", invited_at=now, joined_at=now))

        r = client.get(f"/api/v1/projects/{pid}/config", headers=auth_header)

        assert r.status_code == 200, r.text
        assert 'filename="Brake-ECU.config.json"' in r.headers["content-disposition"]
        assert "ghp_secret" not in r.text
        cfg = pc.parse(r.text)
        assert cfg["project"] == {"name": "Brake ECU", "repository": "https://example.invalid/brake.git",
                                  "branch": "dev"}
        expected_layers = _convert_layers(layers)
        expected_layers["LAYER1"]["cores"] = ["Core1"]
        assert cfg["layers"] == expected_layers
        assert cfg["cores"] == {"Core1": {"macros": "macros.json", "dataDictionary": "dd.csv"}}

        # ...and it imports back into the same wizard
        back = pc.preview(cfg)["draft"]
        assert back["architecture_layers"][0]["groups"][0]["components"][0]["files"] == \
            ["Layer1/Sample/Lib/Lib.cpp", "Layer1/Sample/Lib/Lib.h"]
        assert back["settings"] == {"views": {"flowcharts": True}}
