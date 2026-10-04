"""The New Project wizard checks paths against the branch as it is NOW.

`repo_git` keeps one cached blobless clone per repository and branch. It used to be read at its
HEAD - the commit it was cloned at - so a folder pushed (or moved) after the first clone was
missing from the tree the wizard showed and checked, and stayed missing. `browse(refresh=True)`,
which the wizard asks for on Test Connection and on a branch change, fetches the tip first and
reads the tree there; the preview of an imported config does the same.

The routes that serve the tree are here too: `POST /repositories/browse` takes a private
repository's token in its body; `GET` refuses one in the query string, which logs record.

Real git: a local bare repository stands in for the remote.
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


# ---------------------------------------------------------------------------
# The routes: a private repository's token goes in a POST body, never in a URL.
# `GET /repositories/browse?...&access_token=` wrote the token to the server's access log,
# proxies and the browser's dev tools. POST takes it in the body; GET stays for a public
# repository and refuses a query string that carries one.
# ---------------------------------------------------------------------------

BROWSE_URL = "/api/v1/repositories/browse"
TOKEN = "ghp_do-not-log-me"


@pytest.fixture
def browse_calls(monkeypatch):
    """Every call the routes make to `repo_git.browse`, which still does the real work."""
    calls = []
    real = repo_git.browse

    def spy(repo_url, ref=None, path="", access_token=None, refresh=False):
        calls.append({"repo_url": repo_url, "ref": ref, "path": path,
                      "access_token": access_token, "refresh": refresh})
        return real(repo_url, ref, path, access_token, refresh=refresh)

    monkeypatch.setattr(repo_git, "browse", spy)
    return calls


def test_post_browse_takes_the_token_in_the_body(client, auth_header, remote, browse_calls):
    url, _ = remote
    r = client.post(BROWSE_URL, headers=auth_header, json={
        "repo_url": url, "ref": "main", "path": "", "access_token": TOKEN, "refresh": True})
    assert r.status_code == 200, r.text
    assert _paths(r.json()) == {"a.cpp"}
    assert browse_calls == [{"repo_url": url, "ref": "main", "path": "",
                             "access_token": TOKEN, "refresh": True}]


def test_post_browse_answers_as_get_does(client, auth_header, remote):
    url, _ = remote
    got = client.get(BROWSE_URL, headers=auth_header, params={"repo_url": url, "ref": "main"})
    posted = client.post(BROWSE_URL, headers=auth_header, json={"repo_url": url, "ref": "main"})
    assert got.status_code == posted.status_code == 200, (got.text, posted.text)
    assert posted.json() == got.json()


def test_get_browse_with_a_token_is_refused_and_git_is_not_run(client, auth_header, remote,
                                                               browse_calls, monkeypatch):
    url, _ = remote
    git_runs = []
    monkeypatch.setattr(git_cli, "_run", lambda *a, **k: git_runs.append(a))
    r = client.get(BROWSE_URL, headers=auth_header,
                   params={"repo_url": url, "ref": "main", "access_token": TOKEN})
    assert r.status_code == 400
    assert "POST" in r.json()["detail"]["message"]
    assert TOKEN not in r.text
    assert browse_calls == [] and git_runs == []


def test_get_browse_with_an_empty_token_is_refused_too(client, auth_header, browse_calls):
    r = client.get(BROWSE_URL, headers=auth_header,
                   params={"repo_url": "https://example.invalid/x.git", "access_token": ""})
    assert r.status_code == 400
    assert browse_calls == []


def test_get_browse_without_a_token_still_works(client, auth_header, remote, browse_calls):
    url, _ = remote
    r = client.get(BROWSE_URL, headers=auth_header,
                   params={"repo_url": url, "ref": "main", "refresh": "true"})
    assert r.status_code == 200, r.text
    assert _paths(r.json()) == {"a.cpp"}
    assert browse_calls == [{"repo_url": url, "ref": "main", "path": "",
                             "access_token": None, "refresh": True}]


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_both_routes_answer_the_same_errors(client, auth_header, tmp_path, monkeypatch, method):
    monkeypatch.setattr(repo_git, "_CACHE_DIR", tmp_path / "cache")

    def ask(repo_url, headers=auth_header):
        if method == "GET":
            return client.get(BROWSE_URL, headers=headers, params={"repo_url": repo_url})
        return client.post(BROWSE_URL, headers=headers, json={"repo_url": repo_url})

    assert ask("x", headers={}).status_code == 401                  # signed in, as before
    empty = ask("   ")
    assert empty.status_code == 400
    assert empty.json()["detail"]["message"] == "A repository URL is required to browse."
    missing = ask((tmp_path / "no-such-repo.git").as_uri())        # git fails: 400, not 500
    assert missing.status_code == 400
    assert missing.json()["detail"]["code"] == "VALIDATION_ERROR"
    if method == "GET":
        assert client.get(BROWSE_URL, headers=auth_header).status_code == 422
    else:
        assert client.post(BROWSE_URL, headers=auth_header, json={}).status_code == 422
