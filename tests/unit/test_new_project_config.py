"""tools/new_project.py — how a project's config.json is built.

Written after a real run: the caller passed a --config naming only `Math` and `App`, and the
run generated `Outer` as well. Two separate defects, both invisible until a document came out
wrong:

  * --config was COPIED verbatim, so a config carrying only `layers` produced a workspace
    config with no `clang`, `views` or `llm` — the run then had no include paths and no LLM
    settings. The API has always merged onto config.defaults.json (pipeline_runner
    ._write_project_config); the CLI did not, so the two paths disagreed.
  * it was read with a strict json.load, which rejects config.defaults.json itself — the file
    the docs tell you to copy, and which carries `//` comments.

And one that hid both: an existing workspaces/<pid>/config.json silently won over an explicit
--config, so the second attempt at a fix looked identical to the first.
"""
import json
import os
import sys

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "engine"), os.path.join(ROOT, "tools")]

import new_project as NP  # noqa: E402


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


class TestResolveConfig:
    def test_a_layers_only_config_still_gets_clang_views_and_llm(self, tmp_path):
        """The whole point of merging: you write down what is yours, not the whole file."""
        src = _write(tmp_path, "my.json", json.dumps(
            {"layers": {"L1": {"path": "L1", "groups": {"G": {"App": "App"}}}}}))
        cfg = NP._resolve_config(src)
        assert cfg["layers"]["L1"]["groups"]["G"] == {"App": "App"}
        for section in ("clang", "views", "llm"):
            assert section in cfg, f"{section} should come from the defaults"

    def test_layers_are_replaced_not_merged(self, tmp_path):
        """A deep merge would leave the sample tree's components underneath the caller's.

        This is the actual reported bug: a config naming Math and App generated Outer too,
        because Outer lives in the defaults' Support group and a merge kept it.
        """
        defaults = NP._load_defaults()
        support = defaults["layers"]["Layer1"]["groups"]["Support"]
        assert "Outer" in support, "fixture assumption: the defaults carry a third component"

        src = _write(tmp_path, "my.json", json.dumps(
            {"layers": {"Layer1": {"path": "Layer1",
                                   "groups": {"Support": {"Math": "Math", "App": "App"}}}}}))
        cfg = NP._resolve_config(src)
        assert list(cfg["layers"]["Layer1"]["groups"]["Support"]) == ["Math", "App"]
        assert list(cfg["layers"]) == ["Layer1"], "other layers must not survive either"

    def test_a_section_the_caller_does_set_wins(self, tmp_path):
        src = _write(tmp_path, "my.json", json.dumps(
            {"layers": {"L": {"path": "L", "groups": {}}},
             "views": {"flowcharts": False, "interfaceTables": False}}))
        cfg = NP._resolve_config(src)
        assert cfg["views"]["flowcharts"] is False
        assert cfg["views"]["interfaceTables"] is False

    def test_comments_and_trailing_commas_are_accepted(self, tmp_path):
        """Strict json.load rejected config.defaults.json — the file the docs say to copy."""
        src = _write(tmp_path, "my.json",
                     '{\n  // mine\n  "layers": {"L": {"path": "L", "groups": {"G": {"A": "a",}}}},\n}')
        cfg = NP._resolve_config(src)
        assert cfg["layers"]["L"]["groups"]["G"] == {"A": "a"}

    def test_config_defaults_json_itself_can_be_passed(self):
        """It has // comments in it; passing it used to fail with 'not valid JSON'."""
        cfg = NP._resolve_config(os.path.join(ROOT, "engine", "config", "config.defaults.json"))
        assert cfg["layers"], "the defaults should parse as a --config like any other file"

    def test_no_config_gives_the_plain_defaults(self):
        assert NP._resolve_config(None)["layers"] == NP._load_defaults()["layers"]

    def test_the_db_password_never_reaches_a_workspace_file(self, tmp_path, monkeypatch):
        """config.local.json is overlaid for machine settings (llm creds), but the engine
        reaches Postgres through its own config — a workspace file has no business holding it."""
        cfgdir = tmp_path / "config"
        cfgdir.mkdir()
        (cfgdir / "config.defaults.json").write_text(
            '{"layers": {"L": {"path": "L", "groups": {}}}, "llm": {"provider": "openai"}}',
            encoding="utf-8")
        (cfgdir / "config.local.json").write_text(
            '{"db": {"url": "postgresql://u:secret@h/d"}, "llm": {"baseUrl": "http://x"}}',
            encoding="utf-8")
        monkeypatch.setattr(NP, "_CONFIG_DIR", str(cfgdir))
        cfg = NP._resolve_config(None)
        assert "db" not in cfg
        assert cfg["llm"]["baseUrl"] == "http://x", "non-secret machine settings still apply"
        assert cfg["llm"]["provider"] == "openai", "and merge per key rather than replacing"


class TestDescribeLayers:
    def test_it_names_the_groups_and_components(self, capsys):
        NP._describe_layers({"layers": {"L1": {"groups": {"Support": {"Math": "", "App": ""}}}}})
        out = capsys.readouterr().out
        assert "L1 / Support: Math, App" in out

    def test_an_empty_config_says_so_rather_than_printing_nothing(self, capsys):
        NP._describe_layers({})
        assert "no `layers`" in capsys.readouterr().out


class TestNothingIsCreatedBeforeTheConfigIsResolved:
    r"""The reported failure, reconstructed.

    `--config D:\analyzer\engine\config\config.defaults.json` pointed at a path that did not
    exist. The check for that lived at step 3 — AFTER the projects row was inserted and the
    workspace directory created — so the command exited 2 having half-onboarded the project.
    The obvious next command then reserves a version and takes no --config at all, and that
    branch quietly wrote config.defaults.json into the empty workspace. The project ended up
    configured with the sample tree's layers, which is where the extra component came from.

    Both halves are closed here: a bad --config creates nothing, and a project with no config
    is never given the sample defaults without asking for them.
    """

    @pytest.fixture(autouse=True)
    def _isolated_workspaces(self, tmp_path, monkeypatch):
        import incremental.stores as st
        monkeypatch.setattr(st, "default_workspaces_root", lambda: str(tmp_path / "workspaces"))
        self.ws = tmp_path / "workspaces"

    @pytest.fixture(autouse=True)
    def _database_is_a_tripwire(self, monkeypatch):
        """Reaching the database means the ordering regressed — the config is resolved first."""
        import core.db
        def _boom():
            raise AssertionError("the database was touched before the config was resolved")
        monkeypatch.setattr(core.db, "require_database", _boom)

    def test_a_missing_config_path_creates_nothing(self, capsys):
        rc = NP.main(["--project-id", "p1", "--repo-url", "https://x/y.git",
                      "--config", r"D:\analyzer\engine\config\config.defaults.json"])
        assert rc == 2
        out = capsys.readouterr().out
        assert "--config not found" in out
        assert "Nothing was created" in out
        assert not self.ws.exists(), "no workspace should survive a rejected --config"

    def test_invalid_json_creates_nothing(self, tmp_path, capsys):
        bad = tmp_path / "bad.json"
        bad.write_text('{"layers": ', encoding="utf-8")
        rc = NP.main(["--project-id", "p1", "--config", str(bad)])
        assert rc == 2
        assert "not valid JSON" in capsys.readouterr().out
        assert not self.ws.exists()

    def test_no_config_at_all_is_refused_rather_than_given_the_sample_tree(self, capsys):
        """This is the branch that wrote the defaults silently. It has to ask now."""
        rc = NP.main(["--project-id", "p1", "--version-id", "v1", "--commit", "a" * 40])
        assert rc == 2
        out = capsys.readouterr().out
        assert "--config" in out and "--use-defaults" in out
        assert not self.ws.exists()

    def test_use_defaults_is_the_explicit_way_through(self, capsys):
        """It gets past the config guard — the tripwire fires, which is the next step along."""
        with pytest.raises(AssertionError, match="database was touched"):
            NP.main(["--project-id", "p1", "--use-defaults"])

    def test_an_existing_project_config_needs_no_flag(self, capsys):
        """Reserving a later version takes no --config, and must keep working."""
        (self.ws / "p1").mkdir(parents=True)
        (self.ws / "p1" / "config.json").write_text('{"layers": {}}', encoding="utf-8")
        with pytest.raises(AssertionError, match="database was touched"):
            NP.main(["--project-id", "p1", "--version-id", "v2", "--commit", "b" * 40])
