"""Unit tests for src/incremental/baseline.py — baseline selection (M2.1).

Same throwaway topology as git_ops:  C1 - C2 - C3;  feat off C1 -> F1.
versions (newest-first, all complete): v2@C2, v1@C1.
"""
import os
import subprocess
import sys
import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from incremental.baseline import select_baseline


def _g(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True)


def _head(repo):
    return subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    d = str(tmp_path_factory.mktemp("baseline_repo"))
    subprocess.run(["git", "init", "-q", d], check=True)
    _g(d, "config", "user.email", "t@t"); _g(d, "config", "user.name", "t")
    _g(d, "config", "commit.gpgsign", "false")
    f = os.path.join(d, "f.txt")
    open(f, "w").write("1"); _g(d, "add", "."); _g(d, "commit", "-q", "-m", "c1"); c1 = _head(d)
    open(f, "w").write("2"); _g(d, "add", "."); _g(d, "commit", "-q", "-m", "c2"); c2 = _head(d)
    open(f, "w").write("3"); _g(d, "add", "."); _g(d, "commit", "-q", "-m", "c3"); c3 = _head(d)
    _g(d, "checkout", "-q", "-b", "feat", c1)
    open(os.path.join(d, "g.txt"), "w").write("x"); _g(d, "add", "."); _g(d, "commit", "-q", "-m", "f1")
    f1 = _head(d)
    versions = [{"versionId": "v2", "commit": c2, "status": "complete"},
                {"versionId": "v1", "commit": c1, "status": "complete"}]
    return {"dir": d, "C1": c1, "C2": c2, "C3": c3, "F1": f1, "versions": versions}


class TestAutoBaseline:
    def test_nearest_ancestor_on_main(self, repo):
        r = select_baseline(repo["dir"], repo["versions"], repo["C3"])
        assert r["decision"] == "incremental"
        assert r["autoBaselineVersionId"] == "v2" and r["chosenBaseVersionId"] == "v2"
        assert r["chosenIsAncestor"] and r["chosenIsNearest"]
        assert r["changedFiles"] >= 1 and r["warnings"] == []

    def test_target_on_branch_picks_only_ancestor(self, repo):
        r = select_baseline(repo["dir"], repo["versions"], repo["F1"])
        assert r["autoBaselineVersionId"] == "v1"   # C2 not an ancestor of F1
        assert r["decision"] == "incremental"

    def test_no_versions_is_full(self, repo):
        r = select_baseline(repo["dir"], [], repo["C3"])
        assert r["decision"] == "full"
        assert r["autoBaselineVersionId"] is None and r["changedFiles"] is None


class TestOverride:
    def test_ancestor_but_not_nearest_warns(self, repo):
        r = select_baseline(repo["dir"], repo["versions"], repo["C3"], override_version_id="v1")
        assert r["chosenBaseVersionId"] == "v1"
        assert r["chosenIsAncestor"] and not r["chosenIsNearest"]
        assert any("nearest" in w for w in r["warnings"])

    def test_divergent_base_warns(self, repo):
        # base v2 (C2) is NOT an ancestor of a target on feat
        r = select_baseline(repo["dir"], repo["versions"], repo["F1"], override_version_id="v2")
        assert not r["chosenIsAncestor"]
        assert any("not an ancestor" in w for w in r["warnings"])
        assert r["decision"] == "incremental"   # still runs (correct, slower)

    def test_unknown_override_falls_back_to_auto(self, repo):
        r = select_baseline(repo["dir"], repo["versions"], repo["C3"], override_version_id="vZ")
        assert r["chosenBaseVersionId"] == "v2"  # auto
        assert any("not found" in w for w in r["warnings"])

    def test_incomplete_override_falls_back(self, repo):
        versions = repo["versions"] + [{"versionId": "v3", "commit": repo["C3"], "status": "running"}]
        r = select_baseline(repo["dir"], versions, repo["C3"], override_version_id="v3")
        assert r["chosenBaseVersionId"] == "v2"  # auto (v3 not complete)
        assert any("not complete" in w for w in r["warnings"])
