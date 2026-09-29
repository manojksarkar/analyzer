"""The New Project wizard checks paths against the branch as it is NOW.

`repo_git` keeps one cached blobless clone per repository and branch. It used to be read at its
HEAD - the commit it was cloned at - so a folder pushed (or moved) after the first clone was
missing from the tree the wizard showed and checked, and stayed missing. `browse(refresh=True)`,
which the wizard asks for on Test Connection and on a branch change, fetches the tip first and
reads the tree there; the preview of an imported config does the same.

Real git, no mocks: a local bare repository stands in for the remote.
"""
import subprocess

import pytest

from api.services import git_cli, repo_git

pytestmark = pytest.mark.unit


def _git(*args, cwd=None):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _commit(work, name):
    (work / name).write_text(f"// {name}\n", encoding="utf-8")
    _git("add", name, cwd=work)
    _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", name, cwd=work)
    _git("push", "origin", "main", cwd=work)


@pytest.fixture
def remote(tmp_path, monkeypatch):
    bare, work = tmp_path / "origin.git", tmp_path / "work"
    _git("init", "--bare", "-b", "main", str(bare))
    _git("config", "uploadpack.allowFilter", "true", cwd=bare)       # serve blobless clones
    _git("clone", str(bare), str(work))
    _git("checkout", "-b", "main", cwd=work)
    _commit(work, "a.cpp")
    monkeypatch.setattr(repo_git, "_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(repo_git, "_FRESH_SECONDS", 0)       # every refresh fetches
    return bare.as_uri(), work


def _paths(listing):
    return {e["path"] for e in listing["entries"]}


def test_a_refreshed_browse_sees_what_was_pushed_after_the_first_clone(remote):
    url, work = remote
    assert _paths(repo_git.browse(url, "main")) == {"a.cpp"}
    _commit(work, "b.cpp")
    assert _paths(repo_git.browse(url, "main")) == {"a.cpp"}, "the cached snapshot, as before"
    assert _paths(repo_git.browse(url, "main", refresh=True)) == {"a.cpp", "b.cpp"}


def test_the_refreshed_clone_stays_blobless(remote):
    url, work = remote
    repo_git.browse(url, "main")
    _commit(work, "c.cpp")
    repo_git.browse(url, "main", refresh=True)
    clone = repo_git._cache_path(url, "main", 1, blobless=True)
    new_blob = subprocess.run(["git", "-C", str(work), "rev-parse", "HEAD:c.cpp"],
                              capture_output=True, text=True, check=True).stdout.strip()
    # `?<sha>` = an object the clone does not have. The new file's content must be one of them:
    # fetching from the bare URL, as before, downloaded it (checked: 1 object missing, not 2).
    out = subprocess.run(["git", "-C", str(clone), "rev-list", "--objects", "--missing=print",
                          "refs/remotes/origin/main"], capture_output=True, text=True).stdout
    assert f"?{new_blob}" in out.split()


def test_a_refresh_right_after_the_last_one_reuses_the_clone(remote, monkeypatch):
    # Test Connection reads the tree and then checks an imported config: one fetch, not two.
    url, work = remote
    monkeypatch.setattr(repo_git, "_FRESH_SECONDS", 60)
    repo_git.browse(url, "main")
    _commit(work, "d.cpp")
    assert _paths(repo_git.browse(url, "main", refresh=True)) == {"a.cpp"}, "fetched < 60 s ago"
    monkeypatch.setattr(repo_git, "_FRESH_SECONDS", 0)
    assert "d.cpp" in _paths(repo_git.browse(url, "main", refresh=True))


def test_the_tree_is_read_at_the_fetched_tip_when_there_is_one(remote):
    url, _ = remote
    repo_git.browse(url, "main")
    clone = repo_git._cache_path(url, "main", 1, blobless=True)
    assert repo_git.tree_ref(clone, "main") == "refs/remotes/origin/main"
    assert repo_git.tree_ref(clone, "no-such-branch") == "HEAD"
    assert repo_git.tree_ref(clone, None) == "HEAD"
    assert git_cli.has_ref(str(clone), "refs/remotes/origin/main")
