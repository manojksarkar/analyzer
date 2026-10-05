"""Unit tests for `tools/start_app.py` - the checks that tell an old UI / old API apart.

Filesystem-only (tmp dirs); nothing is started, no port or database is touched.
"""
import json
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TOOLS = os.path.join(PROJECT_ROOT, "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import start_app as T                      # noqa: E402  (tools/ must be on sys.path first)


@pytest.mark.parametrize("version, rng, ok", [
    ("v24.13.1", "^20.19.0 || >=22.12.0", True),
    ("v22.12.0", "^20.19.0 || >=22.12.0", True),
    ("v22.11.0", "^20.19.0 || >=22.12.0", False),
    ("v20.19.2", "^20.19.0 || >=22.12.0", True),
    ("v20.18.9", "^20.19.0 || >=22.12.0", False),
    ("v21.7.0", "^20.19.0 || >=22.12.0", False),
    ("v18.20.0", ">=18 <19", True),
    ("v16.0.0", "~16.1.0", False),
])
def test_node_satisfies(version, rng, ok):
    assert T.node_satisfies(version, rng) is ok


def test_read_env_value_last_wins_and_quotes(tmp_path):
    f = tmp_path / ".env"
    f.write_text("# VITE_API_URL=http://commented\n"
                 "VITE_API_URL=http://first/api/v1\n"
                 "export VITE_API_URL=\"http://second/api/v1\"  \n"
                 "OTHER=x\n", encoding="utf-8")
    assert T.read_env_value(f, "VITE_API_URL") == "http://second/api/v1"
    assert T.read_env_value(f, "MISSING") is None
    assert T.read_env_value(tmp_path / "absent", "VITE_API_URL") is None


def test_web_shadow_file_beside_moved_folder(tmp_path):
    pages = tmp_path / "src" / "pages"
    (pages / "NewProjectPage").mkdir(parents=True)
    (pages / "NewProjectPage" / "index.tsx").write_text("new")
    (pages / "NewProjectPage.tsx").write_text("old")                 # left behind by a copy
    (pages / "ComparePage.tsx").write_text("fine")                   # no folder: not a shadow
    (pages / "Helpers").mkdir()
    (pages / "Helpers" / "util.ts").write_text("no index: not a shadow")
    (pages / "Helpers.ts").write_text("x")
    assert T.find_web_shadows(tmp_path / "src") == [
        (pages / "NewProjectPage.tsx", pages / "NewProjectPage")]


def test_py_shadow_package_beside_module(tmp_path):
    svc = tmp_path / "api" / "services"
    (svc / "doc_render").mkdir(parents=True)
    (svc / "doc_render" / "__init__.py").write_text("")
    (svc / "doc_render.py").write_text("")
    (svc / "other").mkdir()                                          # a namespace dir: loses
    (svc / "other.py").write_text("")
    assert T.find_py_shadows([tmp_path / "api"]) == [(svc / "doc_render", svc / "doc_render.py")]


def _pkg(root, name, version):
    d = root / "node_modules" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "package.json").write_text(json.dumps({"name": name, "version": version}))


def test_stale_node_modules(tmp_path, monkeypatch):
    lock = {"lockfileVersion": 3, "packages": {
        "": {"name": "app"},
        "node_modules/react": {"version": "19.0.0"},
        "node_modules/vite": {"version": "8.0.16", "dev": True},
        "node_modules/gone": {"version": "1.0.0"},
        "node_modules/react/node_modules/nested": {"version": "9.9.9"},         # ignored
        "node_modules/fsevents": {"version": "2.3.3", "optional": True, "os": ["darwin"]},
        "node_modules/@rolldown/binding-here": {"version": "1.0.0", "optional": True,
                                                "os": ["here"], "cpu": ["x64"]},
    }}
    (tmp_path / "package-lock.json").write_text(json.dumps(lock))
    assert T.stale_node_modules(tmp_path) == ["node_modules is missing"]
    _pkg(tmp_path, "react", "19.0.0")
    _pkg(tmp_path, "vite", "7.0.0")
    monkeypatch.setattr(T.sys, "platform", "here")
    monkeypatch.setattr("platform.machine", lambda: "AMD64")
    assert T.stale_node_modules(tmp_path) == [
        "vite: 7.0.0 installed, lock wants 8.0.16",
        "gone: missing",
        "@rolldown/binding-here: missing",      # this machine's native binary: required
    ]


def test_platform_binary_matching(monkeypatch):
    monkeypatch.setattr(T.sys, "platform", "win32")
    monkeypatch.setattr("platform.machine", lambda: "AMD64")
    assert T._for_this_platform({"os": ["win32"], "cpu": ["x64"]})
    assert not T._for_this_platform({"os": ["win32"], "cpu": ["arm64"]})
    assert not T._for_this_platform({"os": ["linux"], "cpu": ["x64"]})
    assert T._for_this_platform({"os": ["!darwin"]})
    assert not T._for_this_platform({"version": "1.0.0"})           # plain optional dependency


def test_served_api_url():
    injected = ('import.meta.env = {"BASE_URL": "/", "DEV": true, '
                '"VITE_API_URL": "http://10.0.0.5:8000/api/v1"};import x from "/src/a.ts";\n'
                'export const API_BASE_URL = import.meta.env.VITE_API_URL ?? '
                '"http://localhost:8000/api/v1";')
    assert T.served_api_url(injected) == "http://10.0.0.5:8000/api/v1"
    fallback = ('import.meta.env = {"BASE_URL": "/", "DEV": true};\n'
                'export const API_BASE_URL = import.meta.env.VITE_API_URL ?? '
                '"http://localhost:8000/api/v1";')
    assert T.served_api_url(fallback) == "http://localhost:8000/api/v1"
    assert T.served_api_url("<html>not the module</html>") is None


@pytest.mark.parametrize("cmd, name, kind", [
    ("node c:/x/web-app/node_modules/.bin//../vite/bin/vite.js --port 5173", "node.exe", "web"),
    ("cmd.exe /d /s /c vite", "cmd.exe", "web"),
    ("python -m uvicorn api.main:app --port 8000", "python.exe", "api"),
    ("python -m http.server 5173", "python.exe", "node/python"),
    ("bash -c vite_api_url=http://x npm test", "bash.exe", "other"),     # a mention, not Vite
    ("c:/windows/system32/svchost.exe -k netsvcs", "svchost.exe", "other"),
])
def test_kind(cmd, name, kind):
    assert T._kind(cmd, name) == kind


def test_clear_state_leaves_a_newer_start_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "RUN_DIR", tmp_path)
    monkeypatch.setattr(T, "STATE_FILE", tmp_path / "state.json")
    T.save_state({"api": {"pid": 200}, "web": {"pid": 201}})
    T.clear_state(own_pids={100, 101})                   # an older run finishing
    assert T.load_state()["api"]["pid"] == 200
    T.clear_state(own_pids={200, 201})
    assert T.load_state() == {}
