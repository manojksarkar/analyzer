"""Cloning from a LOCAL git repo must not depend on the branch being a local branch.

`git clone --branch X` resolves X only against the SOURCE's refs/heads. A working copy
usually holds most branches as remote-tracking refs instead, so a branch the user can
plainly see in `git branch -a` makes the clone fail outright:

    warning: --depth is ignored in local clones; use file:// instead.
    fatal: Remote branch Ravora/Proj/v2_LOP_Auto not found in upstream origin

Reported from a real local repo, and the message is actively misleading -- the branch IS
in that repository, just not as a local one.

The branch was only ever an optimisation to land a SHALLOW clone near the wanted commit,
and a plain local path is not a shallow-capable transport: git ignores --depth and copies
the whole object store. So for a local path both flags are dropped. The caller checks the
commit out explicitly straight afterwards (`_do_checkout`), and a local clone carries every
object, so that checkout succeeds whatever ref the commit sits on -- including one
reachable from no local branch at all.
"""

import os
import subprocess
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (_ROOT, os.path.join(_ROOT, "engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from incremental import clone as clone_mod  # noqa: E402


class _Proc:
    returncode = 0
    stderr = ""
    stdout = ""


def _capture(monkeypatch):
    """Record the argv shallow_clone would run, without running git."""
    seen = []

    def fake_run(args, **_kw):
        seen.append(list(args))
        return _Proc()

    monkeypatch.setattr(clone_mod, "_run", fake_run)
    monkeypatch.setattr(clone_mod, "_check", lambda *a, **k: None)
    return seen


def test_local_path_drops_branch_and_depth(monkeypatch, tmp_path):
    src = tmp_path / "repo"
    src.mkdir()
    seen = _capture(monkeypatch)
    clone_mod.shallow_clone(str(src), str(tmp_path / "dest"), ref="feature/x", depth=50)
    argv = seen[0]
    assert "--branch" not in argv, "a local clone must not resolve the ref against refs/heads"
    assert "--depth" not in argv, "git ignores --depth for a local path anyway"
    assert str(src) in argv


def test_remote_url_is_unchanged(monkeypatch, tmp_path):
    """The shallow path is the whole point for a real remote -- do not regress it."""
    seen = _capture(monkeypatch)
    clone_mod.shallow_clone("https://example.com/x/y.git", str(tmp_path / "d"),
                            ref="main", depth=50)
    argv = seen[0]
    assert "--branch" in argv and "main" in argv
    assert "--depth" in argv and "50" in argv


def test_a_missing_local_dir_is_treated_as_remote(monkeypatch, tmp_path):
    """Only an existing directory is a local clone; a URL-ish string keeps the fast path."""
    seen = _capture(monkeypatch)
    clone_mod.shallow_clone(str(tmp_path / "nope"), str(tmp_path / "d"), ref="main", depth=5)
    assert "--branch" in seen[0]


def _git(*a, cwd=None):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)


def test_commit_on_a_remote_only_branch_can_be_checked_out(tmp_path):
    """End to end, on the shape that failed: the commit lives on a branch the source holds
    only as a remote-tracking ref, and is not reachable from its local HEAD."""
    up, work, dest = tmp_path / "up", tmp_path / "work", tmp_path / "dest"
    up.mkdir()
    _git("init", "-q", cwd=up)
    _git("symbolic-ref", "HEAD", "refs/heads/main", cwd=up)
    (up / "a.txt").write_text("x")
    _git("add", "-A", cwd=up)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "i", cwd=up)
    _git("clone", "-q", str(up), str(work))
    # a commit that exists ONLY on the side branch
    (up / "b.txt").write_text("y")
    _git("add", "-A", cwd=up)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "b", cwd=up)
    _git("branch", "-f", "feature/only", "HEAD", cwd=up)
    _git("reset", "-q", "--hard", "HEAD~1", cwd=up)
    _git("fetch", "-q", "origin", cwd=work)
    sha = _git("rev-parse", "origin/feature/only", cwd=work).stdout.strip()

    locals_ = _git("branch", "--format=%(refname:short)", cwd=work).stdout.split()
    assert "feature/only" not in locals_, "fixture must hold it as remote-tracking only"

    clone_mod.shallow_clone(str(work), str(dest), ref="feature/only", depth=50)
    assert _git("checkout", "-q", sha, cwd=dest).returncode == 0
    assert _git("rev-parse", "HEAD", cwd=dest).stdout.strip() == sha
    assert (dest / "b.txt").is_file()
