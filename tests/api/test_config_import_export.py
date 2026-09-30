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

    def test_each_cores_files_are_asked_for_with_the_path_the_config_names(self):
        assert self.d["cores"] == [{"name": "Core1", "macros": None, "data_dictionary": None,
                                    "compile_commands": None}]
        # as written, '/' separators: step 2 matches a picked folder on the path's end
        assert self.r["expected_uploads"] == {"Core1": {
            "macros": "cfg/macros.json", "data_dictionary": "C:/work/dd.csv",
            "compile_commands": "build/compile_commands.json"}}
        assert self.d["architecture_layers"][0]["core"] == "Core1"

    def test_the_files_are_asked_for_by_name_in_step_two(self):
        assert ("Core1: `macros.json`, `dd.csv`, `compile_commands.json` - pick the folder that "
                "holds them in step 2, or upload each file there.") in _texts(self.r, "check")

    def test_project_settings_are_kept_and_machine_and_server_ones_are_not(self):
        assert self.d["settings"] == {"clang": {"clangArgs": ["--target=arm-none-eabi"]},
                                      "views": {"flowcharts": True, "behaviourDiagram": False}}
        skipped = " ".join(_texts(self.r, "skipped"))
        assert "clang.llvmLibPath" in skipped and "`llm`" in skipped
        assert "compileCommands" not in skipped, "a core's compile commands are imported"


class TestTokensAreNeverRead:
    @pytest.mark.parametrize("text", [
        '{"project": {"name": "x", "token": "ghp_secret"}}',
        '{"accessToken": "ghp_secret", "layers": {}}',
    ])
    def test_a_token_in_the_file_is_reported_and_not_used(self, text):
        r = pc.preview(pc.parse(text))
        assert "ghp_secret" not in str(r["draft"])
        assert any("tokens are never read" in t for t in _texts(r, "skipped"))


class TestCores:
    def test_every_core_is_read_and_each_layer_takes_its_own(self):
        r = pc.preview(pc.parse(
            '{"layers": {"A": {"cores": ["C1"], "groups": {}}, "B": {"cores": ["C2"], "groups": {}}},'
            ' "cores": {"C1": {"macros": "one.json"}, "C2": {"macros": "two.json"}}}'))
        assert [c["name"] for c in r["draft"]["cores"]] == ["C1", "C2"]
        assert {k: v["macros"] for k, v in r["expected_uploads"].items()} == {
            "C1": "one.json", "C2": "two.json"}
        assert [(l["name"], l["core"]) for l in r["draft"]["architecture_layers"]] == [
            ("A", "C1"), ("B", "C2")]

    def test_a_core_no_layer_uses_is_named(self):
        r = pc.preview(pc.parse('{"layers": {"A": {"groups": {}}}, "cores": {"C1": {}}}'))
        assert [c["name"] for c in r["draft"]["cores"]] == ["C1"]
        assert r["draft"]["architecture_layers"][0]["core"] is None
        assert any("C1: no layer uses it" in t for t in _texts(r, "check"))

    def test_compile_commands_may_be_an_object_whose_prefix_is_worked_out(self):
        r = pc.preview(pc.parse(
            '{"layers": {"A": {"cores": ["C1"], "groups": {}}}, "cores": {"C1": {"compileCommands":'
            ' {"file": "build/compile_commands.json", "rootPrefix": "D:/work"}}}}'))
        assert r["expected_uploads"]["C1"]["compile_commands"] == "build/compile_commands.json"
        assert any("rootPrefix` is not used" in t for t in _texts(r, "skipped"))

    def test_a_plain_defines_list_is_core1_for_every_layer(self):
        # a file written before cores: its typed definitions were the whole project's
        r = pc.preview(pc.parse('{"project": {"defines": ["DEBUG=1", "ARM"]},'
                                ' "layers": {"L": {"path": "L", "groups": {}}}}'))
        assert r["draft"]["cores"] == [{"name": "Core1",
                                        "macros": {"mode": "manual", "defines": ["DEBUG=1", "ARM"]},
                                        "data_dictionary": None, "compile_commands": None}]
        assert r["draft"]["architecture_layers"][0]["core"] == "Core1"

    def test_typed_defines_go_to_their_core_unless_it_names_a_file(self):
        r = pc.preview(pc.parse(
            '{"project": {"defines": {"C": ["X"], "D": ["Y=1"], "E": ["Z"]}},'
            ' "layers": {"L": {"path": "L", "cores": ["C"], "groups": {}}},'
            ' "cores": {"C": {"macros": "m.json"}, "D": {}}}'))
        cores = {c["name"]: c for c in r["draft"]["cores"]}
        assert cores["C"]["macros"] is None and r["expected_uploads"]["C"]["macros"] == "m.json"
        assert cores["D"]["macros"] == {"mode": "manual", "defines": ["Y=1"]}
        skipped = " ".join(_texts(r, "skipped"))
        assert "`project.defines.C` was not used" in skipped
        assert "`project.defines.E`: `cores` has no core `E`" in skipped


class TestWithTheRepository:
    def _preview(self, text=CONFIG):
        return pc.preview(pc.parse(text), tree_nodes=TREE)

    def test_paths_not_in_the_repository_are_left_out_and_named(self):
        r = self._preview()
        comps = r["draft"]["architecture_layers"][0]["groups"][0]["components"]
        assert comps[1]["files"] == ["Layer1/Math/Utils.cpp"]
        assert any("`Layer1/App`" in t for t in _texts(r, "check"))

    def test_a_component_none_of_whose_paths_exists_is_left_out_with_its_group(self):
        r = self._preview(CONFIG.replace(
            '"groups": {\n', '"groups": {\n        "Ghost": {"Nowhere": "Does/Not/Exist"},\n', 1))
        names = [g["name"] for g in r["draft"]["architecture_layers"][0]["groups"]]
        assert names == ["My Sample"]
        assert any("Ghost / Nowhere (none of its paths" in t for t in _texts(r, "check"))

    def test_a_path_spelled_in_another_case_takes_the_repositorys_spelling(self):
        r = self._preview(CONFIG.replace('"Sample/Core"', '"sample/core"'))
        comps = r["draft"]["architecture_layers"][0]["groups"][0]["components"]
        assert comps[0]["files"] == ["Layer1/Sample/Core"]

    def test_core_files_are_never_taken_from_the_repository(self):
        # `cfg/macros.json` IS in the tree: a core's files are the user's inputs all the same
        r = self._preview()
        assert r["draft"]["cores"][0]["macros"] is None
        assert r["expected_uploads"]["Core1"]["macros"] == "cfg/macros.json"
        assert r["expected_uploads"] == pc.preview(pc.parse(CONFIG))["expected_uploads"]


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
        assert "pick their folder in step 2" in r.text

        # ...and it imports back into the same wizard
        back = pc.preview(cfg)["draft"]
        assert back["architecture_layers"][0]["groups"][0]["components"][0]["files"] == \
            ["Layer1/Sample/Lib/Lib.cpp", "Layer1/Sample/Lib/Lib.h"]
        assert back["settings"] == {"views": {"flowcharts": True}}


class TestCoresRoundTrip:
    def test_every_core_goes_out_and_comes_back(self):
        from types import SimpleNamespace
        layers = [
            {"name": "Layer1", "path": "Layer1", "core": "Core1", "groups": [
                {"name": "G", "components": [{"name": "A", "files": ["Layer1/A"]}]}]},
            {"name": "Layer2", "path": "Layer2", "core": "Core2", "groups": [
                {"name": "H", "components": [{"name": "B", "files": ["Layer2/B"]}]}]},
            {"name": "Layer3", "path": "Layer3", "core": None, "groups": [
                {"name": "I", "components": [{"name": "C", "files": ["Layer3/C"]}]}]}]
        project = SimpleNamespace(name="Brake ECU", repo_url="https://example.invalid/b.git",
                                  default_branch="main", architecture_layers=layers, build_config={
            "cores": [
                {"name": "Core1", "macros": {"mode": "upload", "file_id": "up_m", "file_name": "m1.json"},
                 "data_dictionary": {"file_id": "up_d", "file_name": "dd1.csv"},
                 "compile_commands": {"file_id": "up_c", "file_name": "compile_commands.json"}},
                {"name": "Core2", "macros": {"mode": "manual", "defines": ["_CONFIG_CMCORE=1"]},
                 "data_dictionary": None, "compile_commands": None}]})

        cfg = pc.parse(pc.to_config_text(project))

        assert cfg["cores"] == {"Core1": {"macros": "m1.json", "dataDictionary": "dd1.csv",
                                          "compileCommands": "compile_commands.json"},
                                "Core2": {}}
        assert cfg["project"]["defines"] == {"Core2": ["_CONFIG_CMCORE=1"]}
        assert [cfg["layers"][n].get("cores") for n in ("Layer1", "Layer2", "Layer3")] == [
            ["Core1"], ["Core2"], None]

        back = pc.preview(cfg)
        assert [(l["name"], l["core"]) for l in back["draft"]["architecture_layers"]] == [
            ("Layer1", "Core1"), ("Layer2", "Core2"), ("Layer3", None)]
        cores = {c["name"]: c for c in back["draft"]["cores"]}
        assert cores["Core2"]["macros"] == {"mode": "manual", "defines": ["_CONFIG_CMCORE=1"]}
        assert back["expected_uploads"]["Core1"] == {
            "macros": "m1.json", "data_dictionary": "dd1.csv",
            "compile_commands": "compile_commands.json"}


class TestTheWizardKnowsWhatEachItemIsAbout:
    def test_each_report_item_names_its_part_of_the_wizard(self):
        r = pc.preview(pc.parse(CONFIG))
        topic = {i["text"].split(":")[0]: i["topic"] for i in r["report"]}
        assert topic["Project"] == "project" and topic["Architecture"] == "architecture"
        assert topic["Cores"] == "files" and topic["Core1"] == "files"
        assert topic["Compiler settings"] == "settings"
        assert {i["topic"] for i in r["report"]} <= {"project", "architecture", "files",
                                                    "settings", "other"}


class TestLayerPaths:
    def _preview(self, text):
        return pc.preview(pc.parse(text), tree_nodes=TREE)

    def test_a_layer_path_in_another_case_takes_the_repositorys_spelling(self):
        r = self._preview(CONFIG.replace('"path": "Layer1"', '"path": "layer1"'))
        layer = r["draft"]["architecture_layers"][0]
        assert layer["path"] == "Layer1"
        assert layer["groups"][0]["components"][0]["files"] == ["Layer1/Sample/Core"]

    def test_a_layer_whose_path_is_not_there_is_left_out_whole(self):
        r = self._preview(CONFIG.replace('"path": "Layer1"', '"path": "Nowhere"'))
        assert r["draft"]["architecture_layers"] == []
        assert any("layer Layer1 (its path `Nowhere` is not a folder there)" in t
                   for t in _texts(r, "check"))
