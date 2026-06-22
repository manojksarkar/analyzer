"""Unit tests for src/incremental/git_ops.py — local git primitives (M2.1).

Builds a throwaway repo:  C1 - C2 - C3 (main line);  feat branches off C1 -> F1.
"""
import os
import subprocess
import sys
import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from incremental import git_ops


def _g(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True)


def _head(repo):
    return subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    d = str(tmp_path_factory.mktemp("gitops_repo"))
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
    return {"dir": d, "C1": c1, "C2": c2, "C3": c3, "F1": f1}


class TestAncestry:
    def test_is_ancestor_linear(self, repo):
        assert git_ops.is_ancestor(repo["dir"], repo["C1"], repo["C3"]) is True
        assert git_ops.is_ancestor(repo["dir"], repo["C3"], repo["C1"]) is False

    def test_is_ancestor_divergent_branch(self, repo):
        # feat branched at C1, so C2/C3 are NOT ancestors of F1
        assert git_ops.is_ancestor(repo["dir"], repo["C1"], repo["F1"]) is True
        assert git_ops.is_ancestor(repo["dir"], repo["C2"], repo["F1"]) is False

    def test_rev_list_count_distance(self, repo):
        assert git_ops.rev_list_count(repo["dir"], repo["C1"], repo["C3"]) == 2
        assert git_ops.rev_list_count(repo["dir"], repo["C2"], repo["C3"]) == 1

    def test_nearest_ancestor_picks_closest(self, repo):
        assert git_ops.nearest_ancestor(repo["dir"], [repo["C1"], repo["C2"]], repo["C3"]) == repo["C2"]

    def test_nearest_ancestor_branch_target(self, repo):
        # target on feat: only C1 is an ancestor among {C1,C2}
        assert git_ops.nearest_ancestor(repo["dir"], [repo["C1"], repo["C2"]], repo["F1"]) == repo["C1"]

    def test_nearest_ancestor_none_when_no_ancestor(self, repo):
        assert git_ops.nearest_ancestor(repo["dir"], [repo["C2"], repo["C3"]], repo["F1"]) is None


class TestDiffAndResolve:
    def test_changed_files(self, repo):
        assert "f.txt" in git_ops.changed_files(repo["dir"], repo["C1"], repo["C2"])

    def test_commit_exists(self, repo):
        assert git_ops.commit_exists(repo["dir"], repo["C1"]) is True
        assert git_ops.commit_exists(repo["dir"], "deadbeefdeadbeef") is False

    def test_resolve(self, repo):
        assert git_ops.resolve(repo["dir"], repo["C3"]) == repo["C3"]
        assert git_ops.resolve(repo["dir"], "nope") is None

    def test_merge_base(self, repo):
        # fork point of feat (F1) and the main line (C3) is C1
        assert git_ops.merge_base(repo["dir"], repo["F1"], repo["C3"]) == repo["C1"]
