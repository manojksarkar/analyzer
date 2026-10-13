"""Unit tests for _write_project_config — the per-version config split (config redesign).

Two outputs, one call:
  * analysis_cfg (returned) → stored in versions.resolved_config: config.defaults.json + this
    project's build_config + layers.
  * the materialized workspace config.json (what the engine reads) → analysis_cfg with this
    machine's overrides of the defaults (config.local.json) under the project's own settings.

Neither holds THIS SERVER's settings -- the database, the LLM server and its credentials, where
LLVM is. A run reads the two it needs (`llmServer`, `llvm`) from config.local.json when it loads
the workspace file (`core.config.load_config`), so a key changed there reaches the next run.

Mark: unit (temp files + monkeypatched settings; no DB, no network).
"""
import json
from types import SimpleNamespace

import pytest

from api.services import pipeline_runner as pr

pytestmark = pytest.mark.unit

_SERVER = {"provider": "openai", "baseUrl": "https://gw/v1", "defaultModel": "m",
           "customHeaders": {"x-tok": "CRED"}}
_SERVER_BLOCKS = {"db", "auth", "repositories", "llmServer", "llvm"}


@pytest.fixture(autouse=True)
def _this_shell_names_no_server(monkeypatch):
    for name in ("ANALYZER_CONFIG", "ANALYZER_DATA_ROOT", "LLM_PROVIDER", "LLM_BASE_URL",
                 "LLM_DEFAULT_MODEL", "LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def _as_a_run_reads_it(tmp_path, monkeypatch, config_path):
    """The config a phase gets from this file: `--config` sets ANALYZER_CONFIG, and the loader
    lays this server's blocks over it."""
    from core.config import load_config
    monkeypatch.setenv("ANALYZER_CONFIG", str(config_path))
    return load_config(str(tmp_path / "engine"))


def _write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def _project(**kw):
    return SimpleNamespace(build_config=kw.get("build_config", {}),
                           architecture_layers=kw.get("architecture_layers", []),
                           created_by="u1")


def test_no_server_setting_is_stored_or_written_and_a_run_still_gets_them(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "engine" / "config"
    _write_json(cfg_dir / "config.defaults.json", {
        "llm": {"descriptions": True, "cacheVersion": 2},
        "views": {"flowcharts": True},
    })
    _write_json(cfg_dir / "config.local.json", {
        "db": {"host": "10.0.0.5", "password": "topsecret"},
        "auth": {"accessTokenMinutes": 60},
        "repositories": {"localRoots": ["D:/src"]},
        "llmServer": _SERVER,
        "llvm": {"libPath": "D:/LLVM/bin/libclang.dll"},
    })
    monkeypatch.setattr(pr, "get_settings", lambda: SimpleNamespace(repo_root=tmp_path))

    project = _project(build_config={"llm": {"descriptions": False}})   # the project's own setting
    out_path, analysis_cfg = pr._write_project_config(project, tmp_path / "workspaces" / "p1")
    written = json.loads(out_path.read_text(encoding="utf-8"))

    # versions.resolved_config and the workspace file: how the documents are made, nothing else
    for cfg in (analysis_cfg, written):
        assert cfg["llm"] == {"descriptions": False, "cacheVersion": 2}
        assert not set(cfg) & _SERVER_BLOCKS
        assert "CRED" not in json.dumps(cfg) and "topsecret" not in json.dumps(cfg)

    # ...and the run that loads the workspace file calls this server's LLM, with its key
    from core.config import load_llm_config
    run = _as_a_run_reads_it(tmp_path, monkeypatch, out_path)
    assert load_llm_config(run)["customHeaders"] == {"x-tok": "CRED"}
    assert run["llvm"] == {"libPath": "D:/LLVM/bin/libclang.dll"}
    assert run["llm"]["descriptions"] is False and "db" not in run


def test_a_key_changed_in_the_local_file_reaches_the_next_run_of_a_written_config(tmp_path, monkeypatch):
    """The office asked which of the config files to edit: the workspace file held the LLM
    settings of the day it was written, so a change in config.local.json reached only what was
    written after it."""
    cfg_dir = tmp_path / "engine" / "config"
    _write_json(cfg_dir / "config.defaults.json", {"llm": {"descriptions": True}})
    _write_json(cfg_dir / "config.local.json", {"llmServer": _SERVER})
    monkeypatch.setattr(pr, "get_settings", lambda: SimpleNamespace(repo_root=tmp_path))
    out_path, _ = pr._write_project_config(_project(), tmp_path / "ws")

    _write_json(cfg_dir / "config.local.json", {"llmServer": dict(_SERVER, defaultModel="another")})
    assert _as_a_run_reads_it(tmp_path, monkeypatch, out_path)["llmServer"]["defaultModel"] == "another"


def test_no_local_file_means_stored_equals_workspace(tmp_path, monkeypatch):
    # Without config.local.json there is nothing of this machine's to lay over, so the stored
    # config and the materialized workspace file are identical.
    cfg_dir = tmp_path / "engine" / "config"
    _write_json(cfg_dir / "config.defaults.json", {"llm": {"descriptions": True}})
    monkeypatch.setattr(pr, "get_settings", lambda: SimpleNamespace(repo_root=tmp_path))

    out_path, analysis_cfg = pr._write_project_config(_project(), tmp_path / "ws")
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert analysis_cfg == written == {"llm": {"descriptions": True}}


def test_overlay_does_not_mutate_stored_config(tmp_path, monkeypatch):
    # The deepcopy guard: this machine's overrides laid into the workspace file must not leak
    # back into the already-snapshotted analysis_cfg (they share no nested references).
    cfg_dir = tmp_path / "engine" / "config"
    _write_json(cfg_dir / "config.defaults.json", {"views": {"flowcharts": False, "unitDiagrams": True}})
    _write_json(cfg_dir / "config.local.json", {"views": {"flowcharts": True}})
    monkeypatch.setattr(pr, "get_settings", lambda: SimpleNamespace(repo_root=tmp_path))

    out_path, analysis_cfg = pr._write_project_config(_project(), tmp_path / "ws")
    assert analysis_cfg["views"] == {"flowcharts": False, "unitDiagrams": True}
    assert json.loads(out_path.read_text(encoding="utf-8"))["views"] == {"flowcharts": True,
                                                                        "unitDiagrams": True}


# ---------------------------------------------------------------------------
# What the project says wins over this machine's config.local.json
# ---------------------------------------------------------------------------
# Office, 2026-10-05: a project imported with `clang.includePathsFromProjectWalk: true` ran with it
# off -- set true in the workspace file, the next generate wrote it false again. config.local.json
# is laid over every run's config, and a `clang` block in it (the walk off) beat the project's
# own setting, while the version's record said on.

def _machine(tmp_path, local):
    cfg_dir = tmp_path / "engine" / "config"
    _write_json(cfg_dir / "config.defaults.json", {
        "clang": {"includePathsFromProjectWalk": False, "clangArgs": ["--target=arm-none-eabi"]},
        "llm": {"descriptions": True, "cacheVersion": 2},
        "views": {"flowcharts": False},
    })
    _write_json(cfg_dir / "config.local.json", local)


def test_the_project_s_clang_setting_wins_over_this_machine_s_file(tmp_path, monkeypatch):
    _machine(tmp_path, {"clang": {"includePathsFromProjectWalk": False},
                        "views": {"flowcharts": False},
                        "llvm": {"libPath": "D:/LLVM/bin/libclang.dll"}})
    monkeypatch.setattr(pr, "get_settings", lambda: SimpleNamespace(repo_root=tmp_path))
    project = _project(build_config={"clang": {"includePathsFromProjectWalk": True}, "views": {"flowcharts": True}})
    out_path, analysis_cfg = pr._write_project_config(project, tmp_path / "ws")
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written["clang"]["includePathsFromProjectWalk"] is True          # the run does what the project says
    assert analysis_cfg["clang"]["includePathsFromProjectWalk"] is True     # and its record says the same
    assert written["views"]["flowcharts"] is True
    run = _as_a_run_reads_it(tmp_path, monkeypatch, out_path)
    assert run["llvm"] == {"libPath": "D:/LLVM/bin/libclang.dll"}          # this machine's LLVM still


def test_what_the_project_leaves_unsaid_this_machine_s_file_still_sets(tmp_path, monkeypatch):
    _machine(tmp_path, {"clang": {"clangArgs": ["--target=x86_64-pc-linux"]}})
    monkeypatch.setattr(pr, "get_settings", lambda: SimpleNamespace(repo_root=tmp_path))
    out_path, _ = pr._write_project_config(_project(build_config={"clang": {"includePathsFromProjectWalk": True}}),
                                           tmp_path / "ws")
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written["clang"]["clangArgs"] == ["--target=x86_64-pc-linux"]
    assert written["clang"]["includePathsFromProjectWalk"] is True


def test_a_project_cannot_point_the_run_at_another_machine_s_llvm_or_llm(tmp_path, monkeypatch):
    """A project made before the server's settings had blocks of their own may still hold an
    LLVM path in `clang` or a gateway in `llm`; one made since could name the blocks. None is
    used, stored or written: they are this server's."""
    _machine(tmp_path, {"llvm": {"libPath": "D:/LLVM/bin/libclang.dll"}, "llmServer": _SERVER})
    monkeypatch.setattr(pr, "get_settings", lambda: SimpleNamespace(repo_root=tmp_path))
    project = _project(build_config={
        "clang": {"llvmLibPath": "E:/elsewhere/libclang.dll", "clangArgs": ["-DX"]},
        "llm": {"baseUrl": "https://elsewhere", "customHeaders": {"k": "THEIRS"}, "cacheVersion": 3},
        "llmServer": {"baseUrl": "https://elsewhere"}, "llvm": {"libPath": "E:/elsewhere"}})
    out_path, analysis_cfg = pr._write_project_config(project, tmp_path / "ws")
    written = json.loads(out_path.read_text(encoding="utf-8"))
    for cfg in (analysis_cfg, written):
        assert cfg["clang"] == {"includePathsFromProjectWalk": False, "clangArgs": ["-DX"]}
        assert cfg["llm"] == {"descriptions": True, "cacheVersion": 3}
        assert not set(cfg) & _SERVER_BLOCKS and "elsewhere" not in json.dumps(cfg)
    run = _as_a_run_reads_it(tmp_path, monkeypatch, out_path)
    assert run["llvm"] == {"libPath": "D:/LLVM/bin/libclang.dll"} and run["llmServer"] == _SERVER


def test_a_no_llm_run_and_the_project_s_llm_settings_beat_this_machine_s_file(tmp_path, monkeypatch):
    _machine(tmp_path, {"llm": {"descriptions": True, "behaviourNames": True, "cacheVersion": 9}})
    monkeypatch.setattr(pr, "get_settings", lambda: SimpleNamespace(repo_root=tmp_path))
    out_path, _ = pr._write_project_config(_project(), tmp_path / "ws", no_llm=True)
    llm = json.loads(out_path.read_text(encoding="utf-8"))["llm"]
    assert (llm["descriptions"], llm["behaviourNames"]) == (False, False)
    assert llm["cacheVersion"] == 9                 # what the project leaves unsaid, this machine sets
    out_path, _ = pr._write_project_config(
        _project(build_config={"llm": {"descriptions": False, "cacheVersion": 3}}), tmp_path / "ws2")
    llm = json.loads(out_path.read_text(encoding="utf-8"))["llm"]
    assert (llm["descriptions"], llm["cacheVersion"]) == (False, 3)


# ---------------------------------------------------------------------------
# Name collisions — refused before the engine ever sees the config
# ---------------------------------------------------------------------------

def _minimal_defaults(tmp_path):
    _write_json(tmp_path / "engine" / "config" / "config.defaults.json", {"llm": {}})


def test_two_layers_reusing_a_group_and_component_name_is_accepted(tmp_path, monkeypatch):
    """`FTL/Cache` and `HIL/Cache` are two different components. Ids are layer-qualified,
    so this is an ordinary config - it used to be refused, and before that it silently
    dropped one layer's components."""
    _minimal_defaults(tmp_path)
    monkeypatch.setattr(pr, "get_settings", lambda: SimpleNamespace(repo_root=tmp_path))
    project = _project(architecture_layers=[
        {"name": "L1", "path": "Layer1",
         "groups": [{"name": "Support", "components": [{"name": "Cache", "files": []}]}]},
        {"name": "L2", "path": "Layer2",
         "groups": [{"name": "Support", "components": [{"name": "Cache", "files": []}]}]},
    ])
    _, analysis_cfg = pr._write_project_config(project, tmp_path / "ws")
    assert sorted(analysis_cfg["layers"]) == ["L1", "L2"]


def test_a_component_name_reused_inside_one_layer_fails_config_generation(tmp_path, monkeypatch):
    """The layer prefix is the same on both, so the ids collide and the paths merge."""
    _minimal_defaults(tmp_path)
    monkeypatch.setattr(pr, "get_settings", lambda: SimpleNamespace(repo_root=tmp_path))
    project = _project(architecture_layers=[
        {"name": "L1", "path": "Layer1", "groups": [
            {"name": "G1", "components": [{"name": "Core", "files": []}]},
            {"name": "G2", "components": [{"name": "Core", "files": []}]},
        ]},
    ])
    with pytest.raises(ValueError, match="component name 'core'"):
        pr._write_project_config(project, tmp_path / "ws")


def test_a_duplicate_group_inside_one_layer_fails_config_generation(tmp_path, monkeypatch):
    """This one never reaches `layers` at all — the list -> dict conversion drops it."""
    _minimal_defaults(tmp_path)
    monkeypatch.setattr(pr, "get_settings", lambda: SimpleNamespace(repo_root=tmp_path))
    project = _project(architecture_layers=[
        {"name": "L1", "path": "Layer1", "groups": [
            {"name": "G1", "components": [{"name": "A", "files": []}]},
            {"name": "G1", "components": [{"name": "B", "files": []}]},
        ]},
    ])
    with pytest.raises(ValueError, match="two groups named 'G1'"):
        pr._write_project_config(project, tmp_path / "ws")


def test_distinct_names_still_write_the_config(tmp_path, monkeypatch):
    _minimal_defaults(tmp_path)
    monkeypatch.setattr(pr, "get_settings", lambda: SimpleNamespace(repo_root=tmp_path))
    project = _project(architecture_layers=[
        {"name": "L1", "path": "Layer1",
         "groups": [{"name": "G1", "components": [{"name": "Core", "files": []}]}]},
        {"name": "L2", "path": "Layer2",
         "groups": [{"name": "G2", "components": [{"name": "Plat", "files": []}]}]},
    ])
    _, analysis_cfg = pr._write_project_config(project, tmp_path / "ws")
    assert sorted(analysis_cfg["layers"]) == ["L1", "L2"]


def test_the_defaults_sample_cores_do_not_reach_a_web_project(tmp_path, monkeypatch):
    # They belong to the defaults' own layers, which the project's replace: left in, every run
    # warned "cores.Core1 is listed by no layer" - on every version, in the web app.
    cfg_dir = tmp_path / "engine" / "config"
    _write_json(cfg_dir / "config.defaults.json", {
        "cores": {"Core1": {"macros": "macros.core1.example.json"}},
        "layers": {"Layer1": {"path": "Layer1", "cores": ["Core1"], "groups": {}}},
    })
    monkeypatch.setattr(pr, "get_settings", lambda: SimpleNamespace(repo_root=tmp_path))
    project = _project(architecture_layers=[{"name": "L1", "path": "Layer1", "groups": [
        {"name": "G", "components": [{"name": "Core", "files": ["Layer1/Sample/Core"]}]}]}])
    _, analysis_cfg = pr._write_project_config(project, tmp_path / "ws")
    assert "cores" not in analysis_cfg
    assert list(analysis_cfg["layers"]) == ["L1"]


def test_the_defaults_sample_project_block_does_not_reach_a_web_project(tmp_path, monkeypatch):
    # It names the sample (for the wizard's Import config); a version's stored config would
    # otherwise say every project is SampleCppProject.
    cfg_dir = tmp_path / "engine" / "config"
    _write_json(cfg_dir / "config.defaults.json", {
        "project": {"name": "SampleCppProject", "repository": "https://example.invalid/s.git"},
        "llm": {"descriptions": True}})
    monkeypatch.setattr(pr, "get_settings", lambda: SimpleNamespace(repo_root=tmp_path))
    out_path, analysis_cfg = pr._write_project_config(_project(), tmp_path / "ws")
    assert "project" not in analysis_cfg
    assert "project" not in json.loads(out_path.read_text(encoding="utf-8"))
