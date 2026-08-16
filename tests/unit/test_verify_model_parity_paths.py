"""verify_model_parity must find a version's model where runs actually write it.

C11b moved the model out of the shared <repo>/model into versions/<ver>/model. The parity
tool was written before that and looked only in the old place, so it failed with
"model dir not found" against any version produced by current code — i.e. exactly the runs
it exists to check, right when it was needed as the C11c gate.
"""
import json
import os
import sys

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "engine"))


def _load_tool():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "vmp", os.path.join(ROOT, "tools", "verify_model_parity.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _model(dirpath):
    os.makedirs(dirpath, exist_ok=True)
    with open(os.path.join(dirpath, "functions.json"), "w", encoding="utf-8") as fh:
        json.dump({"App|Main|calc|int": {"qualifiedName": "calc"}}, fh)
    return dirpath


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Point the data root at a temp dir so the real workspaces are not scanned."""
    import importlib
    cp = importlib.import_module("core.paths")
    before = cp._OVERRIDE_DATA_ROOT
    cp.set_data_root(str(tmp_path))
    yield tmp_path
    cp._OVERRIDE_DATA_ROOT = before
    cp._CACHED = None


def test_finds_the_version_keyed_model(isolated):
    vmp = _load_tool()
    target = _model(str(isolated / "workspaces" / "p1" / "versions" / "ver9" / "model"))
    assert os.path.normcase(vmp._resolve_model_dir("ver9")) == os.path.normcase(target)


def test_finds_a_legacy_commit_keyed_model(isolated):
    """Versions generated before the move keep theirs in <commit[:16]>/model."""
    vmp = _load_tool()
    vid = "abcdef1234567890feed"
    target = _model(str(isolated / "workspaces" / "p1" / vid[:16] / "model"))
    assert os.path.normcase(vmp._resolve_model_dir(vid)) == os.path.normcase(target)


def test_returns_none_when_there_is_no_model(isolated):
    vmp = _load_tool()
    assert vmp._resolve_model_dir("nope") is None


def test_candidates_are_listed_for_the_error_message(isolated):
    """The failure must say WHERE it looked — the old message named one stale path."""
    vmp = _load_tool()
    os.makedirs(str(isolated / "workspaces" / "p1"), exist_ok=True)
    cands = vmp._model_dir_candidates("ver9")
    assert any("versions" in c and "ver9" in c for c in cands)
    assert len(cands) >= 2
