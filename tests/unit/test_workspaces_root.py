"""Where the workspaces are, and a stored path after they moved (BACKLOG NW-5)."""
import json

import pytest

import importlib

cp = importlib.import_module("core.paths")      # `core` exports a function `paths` too


@pytest.fixture
def local(tmp_path, monkeypatch):
    """A config.local.json of the test's own; no ANALYZER_WORKSPACES_DIR."""
    monkeypatch.delenv("ANALYZER_WORKSPACES_DIR", raising=False)
    cfg = tmp_path / "config.local.json"
    real = cp.paths()
    monkeypatch.setattr(cp, "paths", lambda: type(real)(**{**real.__dict__, "config_local_path": str(cfg)}))

    def write(block):
        cfg.write_text("// a comment, as the real file has\n" + json.dumps({"paths": block}), encoding="utf-8")
    return write


class TestWorkspacesRoot:
    def test_not_set_is_the_data_roots_workspaces(self, local):
        assert cp.workspaces_root() == cp.os.path.join(cp.paths().data_root, "workspaces")

    def test_config_local_names_it(self, local, tmp_path):
        local({"workspaces": str(tmp_path / "ws")})
        assert cp.workspaces_root() == str(tmp_path / "ws")

    def test_a_relative_one_is_from_the_installation(self, local):
        local({"workspaces": "data/ws"})
        assert cp.workspaces_root() == cp.os.path.abspath(cp.os.path.join(cp.paths().project_root, "data/ws"))

    def test_the_environment_wins(self, local, tmp_path, monkeypatch):
        local({"workspaces": str(tmp_path / "ws")})
        monkeypatch.setenv("ANALYZER_WORKSPACES_DIR", str(tmp_path / "env"))
        assert cp.workspaces_root() == str(tmp_path / "env")

    def test_the_api_reads_the_same_setting(self, local, tmp_path):
        from api.services.settings import Settings
        local({"workspaces": str(tmp_path / "ws")})
        assert Settings(analyzer_workspaces_dir=None).workspaces == tmp_path / "ws"


class TestRebase:
    def _moved(self, tmp_path):
        new_root = tmp_path / "new" / "workspaces"
        f = new_root / "p1" / "versions" / "ver1" / "approved" / "d1" / "doc.docx"
        f.parent.mkdir(parents=True)
        f.write_text("x")
        return new_root, f

    def test_an_existing_path_is_as_stored(self, tmp_path):
        f = tmp_path / "a.docx"
        f.write_text("x")
        assert cp.rebase_stored_path(str(f), str(tmp_path / "other")) == str(f)

    @pytest.mark.parametrize("old", [
        r"C:\Users\me\analyzer\workspaces\p1\versions\ver1\approved\d1\doc.docx",
        "/srv/analyzer/workspaces/p1/versions/ver1/approved/d1/doc.docx",
    ])
    def test_a_moved_one_is_found_under_todays_root(self, tmp_path, old):
        new_root, f = self._moved(tmp_path)
        assert cp.rebase_stored_path(old, str(new_root)) == str(f)

    def test_a_root_of_another_name_is_found_too(self, tmp_path):
        root = tmp_path / "artifex-data"
        f = root / "p1" / "x.docx"
        f.parent.mkdir(parents=True)
        f.write_text("x")
        assert cp.rebase_stored_path("/old/artifex-data/p1/x.docx", str(root)) == str(f)

    def test_one_found_nowhere_stays_as_stored(self, tmp_path):
        old = "/srv/analyzer/workspaces/p9/gone.docx"
        assert cp.rebase_stored_path(old, str(tmp_path)) == old

    def test_none_stays_none(self):
        assert cp.rebase_stored_path(None) is None
