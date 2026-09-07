"""`--create-version` must survive the fallback to a FULL generation.

`generate_incremental` delegates to `generate_full` whenever there is no usable
baseline — which is exactly the FIRST version of a project, the only time you would
pass `--create-version` at all. That delegation forwarded every other argument and
dropped this one, so the flag defaulted to False, `effective_model_store` refused
with "there is no versions row for '<id>'", and the run exited 2 telling the caller
to "add --create-version to this command" — which they had.

Reproduced twice against a real database before the fix; the workaround was a
separate `analyzer.py onboard --version-id … --commit …` first.

Mark: unit (the delegation only; no DB, no git, no pipeline)
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from incremental import engine as eng  # noqa: E402


@pytest.fixture
def captured(monkeypatch, tmp_path):
    """Drive generate_incremental to the delegation and capture what it passes on.

    Everything before the branch is stubbed: the delegation is the unit under test,
    not the checkout, the version list or the baseline choice.
    """
    seen = {}

    def _fake_full(project_id, branch, commit, scope=None, **kw):
        seen.update(kw)
        seen["_positional"] = (project_id, branch, commit, scope)
        return {"versionId": kw.get("version_id"), "status": "complete"}

    # A real workspace dir is required by Workspace(); tmp_path stands in for it.
    (tmp_path / "p1").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(eng, "generate_full", _fake_full)
    monkeypatch.setattr(eng, "ensure_commit_checkout", lambda *a, **k: None)
    monkeypatch.setattr(eng, "resolve_project_repo", lambda *a, **k: ("", "", ""))
    monkeypatch.setattr(eng, "list_versions", lambda *a, **k: [])
    monkeypatch.setattr(eng.git_ops, "resolve", lambda *a, **k: "a" * 40)
    # No baseline -> "full" -> the delegation under test.
    monkeypatch.setattr(eng, "select_baseline", lambda *a, **k: {"decision": "full"})
    seen["_ws_root"] = str(tmp_path)
    return seen


def _run(seen, create_version, **kw):
    return eng.generate_incremental(
        "p1", "main", "b" * 40, {"type": "project"},
        workspaces_root=seen["_ws_root"], version_id="v1", repo_url="https://x/y.git",
        create_version=create_version, **kw)


class TestCreateVersionSurvivesTheFallback:

    def test_it_is_forwarded_when_set(self, captured):
        _run(captured, True)
        assert captured.get("create_version") is True

    def test_it_is_forwarded_when_unset(self, captured):
        """Not just defaulted away — passed on as given, so a plain run stays strict."""
        _run(captured, False)
        assert captured.get("create_version") is False

    def test_the_other_arguments_still_ride_along(self, captured):
        """Guards against a fix that forwards this one and drops another."""
        _run(captured, True, no_llm=True, doc_type="all", config_path="/tmp/c.json")
        assert captured["no_llm"] is True
        assert captured["doc_type"] == "all"
        assert captured["config_path"] == "/tmp/c.json"
        assert captured["version_id"] == "v1"
