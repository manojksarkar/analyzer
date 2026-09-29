"""A project's cores in and out of the API (api/services/project_cores.py).

A core is one build: its macros, data dictionary and compile commands. Each layer is built for
one core; the run reads them as `cores.<Core>` and `layers.<Layer>.cores`, so a layer's files
parse with their own build's -D set. A project from before cores - one definitions file and one
dictionary for the whole project - is one core, Core1, that every layer uses.
"""
import datetime
import json
import uuid
from types import SimpleNamespace

import pytest

from api.models.domain import Project, ProjectMember
from api.routes import repositories
from api.services import pipeline_runner as pr
from api.services.project_cores import core_problems, project_cores

pytestmark = pytest.mark.unit

LAYERS = [
    {"name": "Layer1", "path": "Layer1", "core": "Core1",
     "groups": [{"name": "G", "components": [{"name": "A", "files": ["Layer1/A"]}]}]},
    {"name": "Layer2", "path": "Layer2", "core": "Core2",
     "groups": [{"name": "H", "components": [{"name": "B", "files": ["Layer2/B"]}]}]},
    {"name": "Layer3", "path": "Layer3", "core": None,
     "groups": [{"name": "I", "components": [{"name": "C", "files": ["Layer3/C"]}]}]},
]
CORES = [
    {"name": "Core1", "macros": {"mode": "upload", "file_id": "up_m1", "file_name": "m1.json"},
     "data_dictionary": {"file_id": "up_d1", "file_name": "dd1.csv"},
     "compile_commands": {"file_id": "up_c1", "file_name": "compile_commands.json"}},
    {"name": "Core2", "macros": {"mode": "manual", "defines": ["_CONFIG_CMCORE=1", " "]},
     "data_dictionary": None, "compile_commands": None},
]


class TestReadingCores:
    def test_each_layer_names_its_core(self):
        cores, layer_core = project_cores({"cores": CORES}, LAYERS)
        assert [c["name"] for c in cores] == ["Core1", "Core2"]
        assert cores[1]["macros"] == {"mode": "manual", "defines": ["_CONFIG_CMCORE=1"]}
        assert layer_core == {"Layer1": "Core1", "Layer2": "Core2", "Layer3": None}

    def test_a_project_from_before_cores_is_core1_for_every_layer(self):
        bc = {"preprocessor_definitions": {"mode": "upload", "file_id": "up_m", "file_name": "m.json"},
              "data_dictionary": {"file_id": "up_d", "file_name": "dd.csv"}}
        layers = [{k: v for k, v in l.items() if k != "core"} for l in LAYERS]
        cores, layer_core = project_cores(bc, layers)
        assert cores == [{"name": "Core1",
                          "macros": {"mode": "upload", "file_id": "up_m", "file_name": "m.json"},
                          "data_dictionary": {"file_id": "up_d", "file_name": "dd.csv"},
                          "compile_commands": None}]
        assert set(layer_core.values()) == {"Core1"}

    def test_a_project_with_nothing_has_no_core(self):
        assert project_cores({"preprocessor_definitions": {"mode": "manual", "defines": []}},
                             LAYERS[:1]) == ([], {"Layer1": None})


class TestCoresTheRunWouldRefuse:
    @pytest.mark.parametrize("cores, layers, message", [
        ([{"name": ""}], [], "Core 1 has no name."),
        ([{"name": "Core1"}, {"name": "core1"}], [], "Two cores are called core1."),
        ([{"name": "Core1"}], [{"name": "L", "core": "Core9"}],
         "Layer L uses core Core9, which the project does not have."),
        # the engine matches a layer's core by its exact name
        ([{"name": "Core1"}], [{"name": "L", "core": "core1"}],
         "Layer L uses core core1, which the project does not have."),
        ([{"name": "Core1", "data_dictionary": {"file_id": "u", "file_name": "dd.xlsx"}}], [],
         "Core1: the data dictionary must be a .csv file, not dd.xlsx."),
        ([{"name": "Core1", "compile_commands": {"file_id": "u", "file_name": "cc.txt"}}], [],
         "Core1: compile commands must be a compile_commands.json, not cc.txt."),
    ])
    def test_each_problem_is_named(self, cores, layers, message):
        assert core_problems({"cores": cores}, layers) == [message]

    def test_good_cores_and_old_projects_pass(self):
        assert core_problems({"cores": CORES}, LAYERS) == []
        assert core_problems({"preprocessor_definitions": {"mode": "manual", "defines": ["A"]}},
                             LAYERS) == []


class TestTheRunConfig:
    def _write(self, tmp_path, monkeypatch, build_config, layers=LAYERS):
        cfg_dir = tmp_path / "engine" / "config"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "config.defaults.json").write_text(json.dumps(
            {"cores": {"Sample": {"macros": "x.json"}}, "layers": {"S": {"cores": ["Sample"]}}}),
            encoding="utf-8")
        monkeypatch.setattr(pr, "get_settings", lambda: SimpleNamespace(repo_root=tmp_path))
        uploads = tmp_path / "uploads"
        monkeypatch.setattr(repositories, "_upload_dir", lambda uid: uploads / uid)
        for uid, name in (("up_m1", "m1.json"), ("up_d1", "dd1.csv"), ("up_c1", "compile_commands.json"),
                          ("up_m", "m.json"), ("up_d", "dd.csv")):
            (uploads / uid).mkdir(parents=True, exist_ok=True)
            (uploads / uid / name).write_text("[]", encoding="utf-8")
        project = SimpleNamespace(build_config=build_config, architecture_layers=layers,
                                  created_by="u1")
        _, cfg = pr._write_project_config(project, tmp_path / "ws")
        return cfg

    def test_each_core_is_a_set_of_files_and_each_layer_names_its_core(self, tmp_path, monkeypatch):
        cfg = self._write(tmp_path, monkeypatch, {"cores": CORES})
        c1, c2 = cfg["cores"]["Core1"], cfg["cores"]["Core2"]
        assert c1["macros"].endswith("m1.json") and c1["dataDictionary"].endswith("dd1.csv")
        assert c1["compileCommands"].endswith("compile_commands.json")
        # typed definitions are written for the engine to read
        typed = json.loads(open(c2["macros"], encoding="utf-8").read())
        assert typed == ["_CONFIG_CMCORE=1"] and set(c2) == {"macros"}
        assert [cfg["layers"][n].get("cores") for n in ("Layer1", "Layer2", "Layer3")] == [
            ["Core1"], ["Core2"], None]
        assert "Sample" not in cfg["cores"], "the defaults' own cores stay out"
        assert "macrosFile" not in (cfg.get("clang") or {}), "no project-wide macros any more"

    def test_a_project_from_before_cores_runs_as_core1_everywhere(self, tmp_path, monkeypatch):
        layers = [{k: v for k, v in l.items() if k != "core"} for l in LAYERS]
        cfg = self._write(tmp_path, monkeypatch, {
            "preprocessor_definitions": {"mode": "upload", "file_id": "up_m", "file_name": "m.json"},
            "data_dictionary": {"file_id": "up_d", "file_name": "dd.csv"}}, layers)
        assert set(cfg["cores"]) == {"Core1"}
        assert cfg["cores"]["Core1"]["dataDictionary"].endswith("dd.csv")
        assert all(cfg["layers"][n]["cores"] == ["Core1"] for n in ("Layer1", "Layer2", "Layer3"))


class TestTheApi:
    def test_compile_commands_upload_as_their_own_kind(self, client, auth_header, tmp_path, monkeypatch):
        monkeypatch.setattr(repositories, "_upload_dir", lambda uid: tmp_path / "uploads" / uid)
        r = client.post("/api/v1/repositories/uploads", headers=auth_header,
                        files={"file": ("compile_commands.json", b"[]", "application/json")},
                        data={"kind": "compile_commands"})
        assert r.status_code == 201, r.text
        assert r.json()["kind"] == "compile_commands"

    def test_a_project_with_broken_cores_is_refused(self, client, auth_header):
        r = client.post("/api/v1/projects", headers=auth_header, json={
            "name": "Broken cores " + uuid.uuid4().hex[:6], "client": "", "compliance_standard": "ISO_26262",
            "repo_url": "https://example.invalid/b.git", "repo_provider": "github",
            "default_branch": "main", "build_config": {"cores": [{"name": "Core1"}]},
            "architecture_layers": [{"name": "L", "path": "L", "core": "Core9", "groups": []}],
            "team": []})
        assert r.status_code == 400
        assert "Layer L uses core Core9" in r.json()["detail"]["message"]

    def test_the_project_view_lists_its_cores_and_each_layers_core(self, db, client, auth_header):
        pid = "pcore" + uuid.uuid4().hex[:6]
        now = datetime.datetime.now(datetime.timezone.utc)
        db.projects.create(Project(
            id=pid, org_id="org1", name=pid, client="", compliance_standard="ISO_26262",
            repo_url="https://example.invalid/b.git", repo_provider="github", default_branch="main",
            build_config={"cores": CORES}, architecture_layers=LAYERS, status="not_run",
            created_by="u1", created_at=now, updated_at=now))
        db.members.add_member(ProjectMember(
            id="m" + uuid.uuid4().hex[:8], project_id=pid, user_id="u1", role="admin",
            status="active", invited_by="u1", invited_at=now, joined_at=now))
        body = client.get(f"/api/v1/projects/{pid}", headers=auth_header).json()["project"]
        assert body["cores"] == [
            {"name": "Core1", "macros": "m1.json", "data_dictionary": "dd1.csv",
             "compile_commands": "compile_commands.json", "layers": ["Layer1"]},
            {"name": "Core2", "macros": "1 typed", "data_dictionary": None,
             "compile_commands": None, "layers": ["Layer2"]}]
        assert body["layer_cores"] == {"Layer1": "Core1", "Layer2": "Core2", "Layer3": None}
