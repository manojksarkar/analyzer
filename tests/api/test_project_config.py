"""Unit tests for _write_project_config — the per-version config split (config redesign).

Two outputs, one call:
  * analysis_cfg (returned) → stored in versions.resolved_config. NON-SECRET: config.defaults.json
    + this project's build_config + layers. Must never carry db or llm credentials.
  * the materialized workspace config.json (what the engine reads) → analysis_cfg PLUS the llm
    secrets from config.local.json, but with the db section stripped (engine uses DATABASE_URL).

Mark: unit (temp files + monkeypatched settings; no DB, no network).
"""
import json
from types import SimpleNamespace

import pytest

from api.services import pipeline_runner as pr

pytestmark = pytest.mark.unit


def _write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def _project(**kw):
    return SimpleNamespace(build_config=kw.get("build_config", {}),
                           architecture_layers=kw.get("architecture_layers", []),
                           created_by="u1")


def test_secrets_split_between_stored_config_and_workspace_file(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "engine" / "config"
    _write_json(cfg_dir / "config.defaults.json", {
        "llm": {"provider": "openai", "defaultModel": "m", "descriptions": True},
        "views": {"flowcharts": True},
    })
    _write_json(cfg_dir / "config.local.json", {
        "db": {"host": "10.0.0.5", "password": "topsecret"},
        "llm": {"baseUrl": "https://gw/v1", "customHeaders": {"x-tok": "CRED"}},
    })
    monkeypatch.setattr(pr, "get_settings", lambda: SimpleNamespace(repo_root=tmp_path))

    project = _project(build_config={"llm": {"descriptions": False}})   # per-project non-secret override
    out_path, analysis_cfg = pr._write_project_config(project, tmp_path / "workspaces" / "p1")

    # analysis_cfg == versions.resolved_config: non-secret only
    assert analysis_cfg["llm"]["provider"] == "openai"       # from defaults
    assert analysis_cfg["llm"]["descriptions"] is False      # build_config override applied
    assert "baseUrl" not in analysis_cfg["llm"]              # secret NOT persisted
    assert "customHeaders" not in analysis_cfg["llm"]        # secret NOT persisted
    assert "db" not in analysis_cfg                          # secret NOT persisted

    # workspace file == what the engine runs with: secrets overlaid, db stripped
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written["llm"]["customHeaders"]["x-tok"] == "CRED"   # cred reaches the engine
    assert written["llm"]["baseUrl"] == "https://gw/v1"
    assert written["llm"]["provider"] == "openai"               # non-secret preserved
    assert written["llm"]["descriptions"] is False              # build_config override preserved
    assert "db" not in written                                  # DB password never written to disk


def test_no_local_file_means_stored_equals_workspace(tmp_path, monkeypatch):
    # Without config.local.json there are no secrets to overlay, so the stored config and the
    # materialized workspace file are identical.
    cfg_dir = tmp_path / "engine" / "config"
    _write_json(cfg_dir / "config.defaults.json", {"llm": {"provider": "ollama"}})
    monkeypatch.setattr(pr, "get_settings", lambda: SimpleNamespace(repo_root=tmp_path))

    out_path, analysis_cfg = pr._write_project_config(_project(), tmp_path / "ws")
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert analysis_cfg == written == {"llm": {"provider": "ollama"}}


def test_overlay_does_not_mutate_stored_config(tmp_path, monkeypatch):
    # The deepcopy guard: overlaying secrets into the workspace file must not leak back into the
    # already-snapshotted analysis_cfg (they share no nested references).
    cfg_dir = tmp_path / "engine" / "config"
    _write_json(cfg_dir / "config.defaults.json", {"llm": {"provider": "openai", "numCtx": 8192}})
    _write_json(cfg_dir / "config.local.json", {"llm": {"customHeaders": {"x-tok": "CRED"}}})
    monkeypatch.setattr(pr, "get_settings", lambda: SimpleNamespace(repo_root=tmp_path))

    _, analysis_cfg = pr._write_project_config(_project(), tmp_path / "ws")
    assert "customHeaders" not in analysis_cfg["llm"]
    assert analysis_cfg["llm"]["numCtx"] == 8192
