"""`analyzer.py reexport` refuses a version id that is not the project's own -- at once, plainly.

Develop's 976ee0f makes a version id a name inside its project, so `reexport --project-id A
--version-id <B's id>` can never touch B's version. But the existence check ran only when neither
the version nor the PROJECT had a config file -- and a project almost always has one. Such an id
therefore went on to the checkout search, which printed "no commit is recorded", listed the
project's checkouts and advised `--commit` for a version that does not exist. Found running the
CLI against two projects that both onboarded `v1`.
"""
import argparse
import os
import sys

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "engine")]

import analyzer as A  # noqa: E402


class _Store:
    def __init__(self, root):
        self.root = root

    def artifact_dir(self, version_id):
        return os.path.join(self.root, "versions", version_id)


@pytest.fixture
def project_a(monkeypatch, tmp_path):
    """Project `own-a`: a workspace with its config, and one version, `own-a.v1`."""
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    import incremental.store as store_mod
    import incremental.stores as stores_mod
    monkeypatch.setattr(store_mod, "make_store", lambda pid, **k: _Store(str(tmp_path)))
    monkeypatch.setattr(stores_mod, "Workspace",
                        lambda pid, **k: type("W", (), {"root": str(tmp_path)})())
    monkeypatch.setattr(A, "_version_id_for", lambda pid, name: name if "." in name
                        else "%s.%s" % (pid, name))
    monkeypatch.setattr(A, "_known_versions",
                        lambda pid: [("own-a.v1", "v1", "38179af905", "complete")])
    monkeypatch.setattr(A, "_checkout_for", lambda *a, **k: pytest.fail(
        "reached the checkout search for a version that is not the project's"))
    return tmp_path


def _reexport(version_id):
    return A.cmd_reexport(argparse.Namespace(
        project_id="own-a", version_id=version_id, commit=None, from_phase=3, force=False,
        scope=None, unit=None, doc_type=None))


@pytest.mark.parametrize("version_id", ["own-b.v1", "v9"], ids=["another project's", "a typo"])
def test_it_is_refused_before_anything_else(project_a, capsys, version_id):
    assert _reexport(version_id) == 2
    err = capsys.readouterr().err
    assert "there is no version %r for project 'own-a'" % version_id in err
    assert "v1" in err, "it names the versions the project does have"
    assert "checkouts this project HAS" not in err
