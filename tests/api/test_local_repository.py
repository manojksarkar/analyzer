"""A project's repository can be a LOCAL path: a git repository's folder on the server.

The New Project wizard takes a Git URL or a local path, typed or picked in its Browse panel
(`GET /repositories/local-folders`, the server's folders one at a time). A local path must be a
full path to a git repository -- a plain folder is refused, in plain words (git's own answer
ended "...and the repository exists."). `repositories.localRoots` in config.local.json limits
the picker and the paths to some folders; empty, every drive.

Real git: repositories made in tmp_path.
"""
import os
import subprocess

import pytest

from api.services import git_cli, local_repos, repo_git

pytestmark = pytest.mark.unit


def _git(*args, cwd=None):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _p(path) -> str:
    return str(path).replace("\\", "/")


@pytest.fixture(autouse=True)
def no_limit(monkeypatch):
    """This machine's config.local.json is not the test's: no `localRoots` unless a test sets one."""
    monkeypatch.setattr(local_repos, "_setting", lambda: (True, None))


def _limit(monkeypatch, *roots_):
    monkeypatch.setattr(local_repos, "_setting", lambda: (True, [_p(r) for r in roots_]))


@pytest.fixture
def repos(tmp_path):
    """tmp/src: `firmware` (a work tree: main, dev, release/v1), `mirror.git` (bare), `docs` (a
    plain folder), `.hidden` and `$recycle` (left out of listings)."""
    src = tmp_path / "src"
    work = src / "firmware"
    work.mkdir(parents=True)
    _git("init", "-q", "-b", "main", cwd=work)
    (work / "main.cpp").write_text("int main() { return 0; }\n", encoding="utf-8")
    _git("add", ".", cwd=work)
    _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init", cwd=work)
    _git("branch", "dev", cwd=work)
    _git("branch", "release/v1", cwd=work)
    _git("clone", "-q", "--bare", str(work), str(src / "mirror.git"))
    (src / "docs" / "manuals").mkdir(parents=True)
    (src / ".hidden").mkdir()
    (src / "$recycle").mkdir()
    (src / "notes.txt").write_text("not a folder\n", encoding="utf-8")
    return {"src": src, "work": work, "bare": src / "mirror.git", "plain": src / "docs"}


# ── What a local path is ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", ["D:/src/x", "D:\\src\\x", "/srv/x", "\\\\host\\share\\x",
                                  "file:///D:/src/x", '"D:\\src\\x"', "src/x"])
def test_local_paths(text):
    assert local_repos.is_local(text)


@pytest.mark.parametrize("text", ["https://github.com/org/repo.git", "git@github.com:org/repo.git",
                                  "ssh://git@host/x.git", "git://host/x.git", ""])
def test_remotes_are_not_local(text):
    assert not local_repos.is_local(text)


def test_clean_drops_quotes_reads_file_links_and_uses_forward_slashes():
    assert local_repos.clean('"D:\\src\\vcu-firmware"') == "D:/src/vcu-firmware"
    assert local_repos.clean("file:///D:/src/my%20repo") == "D:/src/my repo"
    assert local_repos.clean("file:///srv/x") == "/srv/x"


# ── Which folder may be a repository ────────────────────────────────────────────────────────

def test_a_work_tree_and_a_bare_repository_may(repos):
    assert local_repos.problem(_p(repos["work"])) is None
    assert local_repos.problem(_p(repos["bare"])) is None
    assert local_repos.problem('"' + str(repos["work"]) + '"') is None       # "Copy as path"


def test_a_plain_folder_a_missing_one_and_a_relative_path_may_not_and_say_why(repos):
    plain = _p(repos["plain"])
    assert local_repos.problem(plain) == (
        f"{plain} is not a git repository (it has no .git): pick the repository's root folder.")
    assert local_repos.problem(_p(repos["src"] / "nope")) == f"No folder {_p(repos['src'] / 'nope')} on the server."
    assert "full folder path" in local_repos.problem("src/firmware")


def test_outside_the_allowed_folders_may_not_and_whether_it_exists_is_not_said(repos, tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    _limit(monkeypatch, allowed)
    for p in (repos["work"], tmp_path / "does-not-exist"):
        why = local_repos.problem(_p(p))
        assert "outside the folders this server allows repositories in" in why, why
        assert "No folder" not in why


def test_a_setting_that_cannot_be_read_allows_nothing(repos, monkeypatch):
    monkeypatch.setattr(local_repos, "_setting", lambda: (False, None))
    assert "allows no local repository" in local_repos.problem(_p(repos["work"]))


# ── The Browse panel's listing ──────────────────────────────────────────────────────────────

def test_a_folder_lists_its_folders_by_name_hidden_ones_left_out_repositories_marked(repos):
    out = local_repos.list_folders(_p(repos["src"]))
    assert out["path"] == _p(repos["src"])
    assert [(f["name"], f["git"]) for f in out["folders"]] == [
        ("docs", False), ("firmware", True), ("mirror.git", True)]
    assert out["folders"][1]["path"] == _p(repos["work"])
    assert out["parent"] == _p(repos["src"].parent)
    assert (out["limited"], out["truncated"]) == (False, False)


def test_the_top_list_is_the_drives_without_a_limit_and_the_allowed_folders_with_one(repos, monkeypatch):
    top = local_repos.list_folders("")
    assert top["path"] == "" and top["parent"] is None and not top["limited"]
    drive = os.path.splitdrive(str(repos["src"]))[0]
    assert (drive.upper() + "/" if drive else "/") in [f["path"].upper() if drive else f["path"] for f in top["folders"]]
    _limit(monkeypatch, repos["src"])
    top = local_repos.list_folders("")
    assert top["limited"] and [f["path"] for f in top["folders"]] == [_p(repos["src"])]
    assert top["folders"][0]["name"] == _p(repos["src"]), "an allowed folder is named by its full path"


def test_with_a_limit_its_folders_lead_back_to_the_top_and_nothing_above_is_listed(repos, monkeypatch):
    _limit(monkeypatch, repos["src"])
    assert local_repos.list_folders(_p(repos["src"]))["parent"] == ""
    assert local_repos.list_folders(_p(repos["plain"]))["parent"] == _p(repos["src"])
    for above in (repos["src"].parent, str(repos["src"]) + "/.."):
        with pytest.raises(local_repos.LocalPathError) as exc:
            local_repos.list_folders(_p(above))
        assert exc.value.status == 403


def test_relative_missing_and_too_many(repos, monkeypatch):
    with pytest.raises(local_repos.LocalPathError) as exc:
        local_repos.list_folders("src")
    assert exc.value.status == 400
    with pytest.raises(local_repos.LocalPathError) as exc:
        local_repos.list_folders(_p(repos["src"] / "nope"))
    assert exc.value.status == 404
    monkeypatch.setattr(local_repos, "MAX_FOLDERS", 2)
    out = local_repos.list_folders(_p(repos["src"]))
    assert out["truncated"] and [f["name"] for f in out["folders"]] == ["docs", "firmware"]


def test_a_link_inside_the_allowed_folders_to_one_outside_them_is_outside(repos, tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    link = allowed / "escape"
    try:
        os.symlink(repos["src"], link, target_is_directory=True)
    except (OSError, NotImplementedError):
        try:                                      # Windows without the symlink right: a junction
            import _winapi
            _winapi.CreateJunction(str(repos["src"]), str(link))
        except (ImportError, OSError):
            pytest.skip("this machine cannot make a directory link")
    _limit(monkeypatch, allowed)
    with pytest.raises(local_repos.LocalPathError) as exc:
        local_repos.list_folders(_p(link))
    assert exc.value.status == 403


# ── Git reads a local repository as it reads a remote ───────────────────────────────────────

def test_test_connection_lists_a_local_repositorys_branches(repos):
    res = repo_git.test_connection('"' + str(repos["work"]) + '"', access_token="ignored")
    assert res["connected"] and res["default_branch"] == "main"
    assert sorted(res["branches"]) == ["dev", "main", "release/v1"]


def test_test_connection_refuses_a_plain_folder_in_plain_words(repos):
    res = repo_git.test_connection(_p(repos["plain"]))
    assert not res["connected"] and "is not a git repository" in res["message"]
    assert "the repository exists" not in res["message"]


def test_the_files_the_commits_and_a_runs_clone_come_from_the_local_repository(repos, tmp_path, monkeypatch):
    monkeypatch.setattr(repo_git, "_CACHE_DIR", tmp_path / "cache")
    path = _p(repos["work"])
    assert {e["path"] for e in repo_git.browse(path, "dev")["entries"]} == {"main.cpp"}
    assert [c["message"] for c in repo_git.list_commits(path, "main")][:1] == ["init"]
    dest = tmp_path / "checkout"
    git_cli.shallow_clone(path, "", "", str(dest), ref="release/v1", depth=50)
    assert (dest / "main.cpp").is_file()


# ── Over HTTP ───────────────────────────────────────────────────────────────────────────────

def test_the_folders_route(client, auth_header, repos, monkeypatch):
    r = client.get("/api/v1/repositories/local-folders", params={"path": _p(repos["src"])}, headers=auth_header)
    assert r.status_code == 200, r.text
    assert [f["name"] for f in r.json()["folders"] if f["git"]] == ["firmware", "mirror.git"]
    for path, status, code in (("src", 400, "VALIDATION_ERROR"),
                               (_p(repos["src"] / "nope"), 404, "NOT_FOUND")):
        r = client.get("/api/v1/repositories/local-folders", params={"path": path}, headers=auth_header)
        assert r.status_code == status and r.json()["detail"]["code"] == code
    _limit(monkeypatch, repos["plain"])
    r = client.get("/api/v1/repositories/local-folders", params={"path": _p(repos["src"])}, headers=auth_header)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "FORBIDDEN"
    assert client.get("/api/v1/repositories/local-folders").status_code == 401


def test_test_connection_over_http(client, auth_header, repos):
    r = client.post("/api/v1/repositories/test-connection", json={"repo_url": _p(repos["work"])}, headers=auth_header)
    assert r.status_code == 200 and r.json()["connected"]
    r = client.post("/api/v1/repositories/test-connection", json={"repo_url": _p(repos["plain"])}, headers=auth_header)
    assert not r.json()["connected"] and "is not a git repository" in r.json()["message"]


def test_a_project_on_a_local_repository_is_stored_as_git_reads_it(client, auth_header, db, repos):
    body = {"name": "Local ECU", "client": "T", "compliance_standard": "ASPICE_L2",
            "repo_url": '"' + str(repos["work"]) + '"', "repo_provider": "github",
            "access_token": "ghp_not_for_a_folder", "default_branch": "main"}
    r = client.post("/api/v1/projects", json=body, headers=auth_header)
    assert r.status_code == 200, r.text
    project = db.projects.get(r.json()["project"]["id"] if "project" in r.json() else r.json()["id"])
    assert project.repo_url == _p(repos["work"])
    assert project.repo_provider == "local"
    assert "repo_access_token" not in (project.build_config or {})


def test_a_project_on_a_plain_folder_is_refused(client, auth_header, repos):
    body = {"name": "Plain", "client": "T", "compliance_standard": "ASPICE_L2",
            "repo_url": _p(repos["plain"]), "repo_provider": "local"}
    r = client.post("/api/v1/projects", json=body, headers=auth_header)
    assert r.status_code == 400 and "is not a git repository" in r.json()["detail"]["message"]
