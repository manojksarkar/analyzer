"""A Bitbucket repository, end to end, without the office's server.

A small HTTP server in the test stands in for Bitbucket: it answers 401 to any request that does
not carry the expected `Authorization` header -- `Bearer <token>`, as Data Center wants, or
`Basic base64("x-token-auth:<token>")`, as Cloud does -- and hands the rest to `git http-backend`
(CGI) over a bare repository served at a `/scm/proj/repo.git` path. Through it run what the
wizard and a job do: Test Connection, the tree, the commit list and its refresh, and a job's
checkout (`ensure_commit_checkout`), then the same without a token and with a wrong one.

And over the API: a page address answers with its clone URL in `repo_url`, in Test Connection
and in the config preview; a project is created with that clone URL and `repo_provider`
"bitbucket"; the two sign-in messages.

Git runs here as on a server: no system or global config (so no credential helper of this
machine's), no askpass program, no proxy. Each git process costs about a second on Windows, so
the repository and the servers are made once per module and the real-network tests are few.
docs/design/BITBUCKET_SUPPORT.md; the same rules without a server: tests/unit/test_git_auth.py.
"""
import base64
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.path.join(PROJECT_ROOT, "engine") not in sys.path:
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from api.services import git_cli, repo_git           # noqa: E402
from incremental import clone as clone_mod            # noqa: E402
from incremental import git_ops                       # noqa: E402

GIT = shutil.which("git")


def _http_backend() -> bool:
    if not GIT:
        return False
    exec_path = subprocess.run([GIT, "--exec-path"], capture_output=True, text=True).stdout.strip()
    return any(os.path.isfile(os.path.join(exec_path, n))
               for n in ("git-http-backend", "git-http-backend.exe"))


pytestmark = [pytest.mark.unit,
              pytest.mark.skipif(not _http_backend(), reason="git http-backend is not installed")]

TOKEN = "FAKE-bitbucket-http-token-0123456789"        # not a real token
BASIC = base64.b64encode(f"x-token-auth:{TOKEN}".encode()).decode()
NEEDS = "Authentication failed — this repository needs an access token."
CHECK = "Authentication failed — check the access token."


def _git(*args, cwd=None):
    r = subprocess.run([GIT, *args], cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _fast_import(bare, stream: str, marks=None):
    """One git process for any number of commits. BYTES: text mode on Windows writes CRLF,
    and fast-import then reads `refs/heads/main\\r`."""
    args = [GIT, "-C", str(bare), "fast-import", "--quiet"]
    if marks:
        args.append(f"--export-marks={marks}")
    r = subprocess.run(args, input=stream.encode("utf-8"), capture_output=True)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")


def _commit(ref, when, message, path, content, parent=None, mark=None):
    """One fast-import commit adding `path`. ASCII only: `data` counts bytes."""
    out = f"commit {ref}\n" + (f"mark :{mark}\n" if mark else "")
    out += (f"committer t <t@t> {when} +0000\n"
            f"data {len(message)}\n{message}\n")
    if parent:
        out += f"from {parent}\n"
    return out + f"M 644 inline {path}\ndata {len(content)}\n{content}\n"


# ── The stand-in server ─────────────────────────────────────────────────────────────────────

def _body(handler) -> bytes:
    if handler.headers.get("Transfer-Encoding", "").lower() == "chunked":
        out = []
        while True:
            size = int(handler.rfile.readline().split(b";")[0].strip() or b"0", 16)
            if not size:
                while handler.rfile.readline().strip():      # trailers, up to the blank line
                    pass
                return b"".join(out)
            out.append(handler.rfile.read(size))
            handler.rfile.readline()
    n = int(handler.headers.get("Content-Length") or 0)
    return handler.rfile.read(n) if n else b""


def _serve(root: str, expected_auth: str):
    """A git smart-HTTP server over `root` that wants `expected_auth`. Returns (server, seen):
    `seen` lists every request as (method, path, Authorization header or None)."""
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _answer(self):
            auth = self.headers.get("Authorization")
            seen.append((self.command, self.path, auth))
            if auth != expected_auth:
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="Bitbucket"')
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = _body(self)
            path, _, query = self.path.partition("?")
            env = dict(os.environ,
                       GIT_PROJECT_ROOT=root, GIT_HTTP_EXPORT_ALL="1", PATH_INFO=path,
                       REQUEST_METHOD=self.command, QUERY_STRING=query,
                       CONTENT_TYPE=self.headers.get("Content-Type", ""),
                       CONTENT_LENGTH=str(len(body)),
                       HTTP_GIT_PROTOCOL=self.headers.get("Git-Protocol", ""),
                       HTTP_CONTENT_ENCODING=self.headers.get("Content-Encoding", ""),
                       REMOTE_ADDR="127.0.0.1")
            out = subprocess.run([GIT, "http-backend"], input=body, env=env,
                                 capture_output=True).stdout
            head, sep, rest = out.partition(b"\r\n\r\n")
            if not sep:
                head, _, rest = out.partition(b"\n\n")
            status, headers = 200, []
            for line in head.decode("latin-1").splitlines():
                name, _, value = line.partition(":")
                if name.lower() == "status":
                    status = int(value.split()[0])
                elif name:
                    headers.append((name, value.strip()))
            self.send_response(status)
            for name, value in headers:
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(rest)))
            self.end_headers()
            self.wfile.write(rest)

        do_GET = do_POST = _answer

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, seen


@pytest.fixture(scope="module")
def upstream(tmp_path_factory):
    """A bare repository at <root>/scm/proj/repo.git: main with 3 commits (src/m0.c … m2.c),
    and dev at the same commit. The commit-list test adds commits to dev only."""
    root = tmp_path_factory.mktemp("bitbucket")
    bare = root / "scm" / "proj" / "repo.git"
    _git("init", "-q", "--bare", "-b", "main", str(bare))
    with open(bare / "config", "a", encoding="utf-8") as fh:
        fh.write("[uploadpack]\n\tallowFilter = true\n\tallowReachableSHA1InWant = true\n")
    marks = root / "marks"
    stream = ""
    for i in range(3):
        stream += _commit("refs/heads/main", 1700000000 + i, f"commit {i}", f"src/m{i}.c",
                          f"int m{i};\n", mark=i + 1)
    stream += "reset refs/heads/dev\nfrom :3\n\n"
    _fast_import(bare, stream, marks=marks)
    shas = dict(line.split() for line in marks.read_text().splitlines())
    return {"root": str(root), "bare": bare, "shas": [shas[":1"], shas[":2"], shas[":3"]]}


@pytest.fixture(scope="module")
def servers(upstream):
    """Two servers over the same repository: Data Center (Bearer) and Cloud style (Basic)."""
    dc, dc_seen = _serve(upstream["root"], f"Bearer {TOKEN}")
    cloud, cloud_seen = _serve(upstream["root"], f"Basic {BASIC}")
    out = {}
    for name, (srv, seen) in {"dc": (dc, dc_seen), "cloud": (cloud, cloud_seen)}.items():
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        out[name] = {**upstream, "base": base, "url": f"{base}/scm/proj/repo.git", "seen": seen}
    yield out
    for srv in (dc, cloud):
        srv.shutdown()
        srv.server_close()


@pytest.fixture
def data_center(servers):
    servers["dc"]["seen"].clear()
    return servers["dc"]


@pytest.fixture
def cloud(servers, monkeypatch):
    """bitbucket.org cannot be pointed here; the rule's Cloud host list can."""
    monkeypatch.setattr(clone_mod, "_BITBUCKET_CLOUD_HOSTS", frozenset({"127.0.0.1"}))
    servers["cloud"]["seen"].clear()
    return servers["cloud"]


@pytest.fixture(autouse=True)
def git_as_on_a_server(tmp_path, monkeypatch):
    empty = tmp_path / "empty.gitconfig"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    for name in ("SSH_ASKPASS", "GIT_ASKPASS", "GIT_CONFIG_COUNT", "HTTP_PROXY", "HTTPS_PROXY",
                 "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("ANALYZER_GIT_TIMEOUT", "60")      # a hang fails the test, not the suite
    monkeypatch.setattr(repo_git, "_CACHE_DIR", tmp_path / "wizard-cache")
    monkeypatch.setattr(repo_git, "_FRESH_SECONDS", 0)


@pytest.fixture
def git_argv(monkeypatch):
    """Every git command line run, through either runner (the real commands still run)."""
    argv = []

    def spy(real):
        def run(args, *a, **kw):
            argv.append(list(args))
            return real(args, *a, **kw)
        return run

    monkeypatch.setattr(git_ops, "_run", spy(git_ops._run))
    monkeypatch.setattr(clone_mod, "_run", spy(clone_mod._run))
    monkeypatch.setattr(git_cli, "_run", spy(git_cli._run))
    return argv


def _no_token_anywhere(argv, *clones) -> None:
    assert argv, "no git command was recorded"
    assert not [a[:2] for a in argv if TOKEN in " ".join(a)], "the token is in a git argument"
    for clone in clones:
        text = (clone / ".git" / "config").read_text(encoding="utf-8")
        assert TOKEN not in text, f"the token is in {clone}/.git/config"


def _origin(repo_dir) -> str:
    return _git("-C", str(repo_dir), "remote", "get-url", "origin")


# ── Data Center: Bearer ─────────────────────────────────────────────────────────────────────

def test_the_wizard_reads_a_data_center_repository_from_its_page_address(data_center, git_argv):
    page = f"{data_center['base']}/projects/PROJ/repos/repo/browse?at=refs%2Fheads%2Fdev"
    res = repo_git.test_connection(page, TOKEN)
    assert res["connected"], res["message"]
    assert sorted(res["branches"]) == ["dev", "main"] and res["default_branch"] == "main"
    assert res["repo_url"] == data_center["url"], "the clone URL, for the wizard's box"

    listing = repo_git.browse(page, "main", "src", TOKEN)
    assert listing["repo_url"] == data_center["url"]
    assert sorted(e["name"] for e in listing["entries"]) == ["m0.c", "m1.c", "m2.c"]

    clone = repo_git._cache_path(data_center["url"], "main", 1, blobless=True, access_token=TOKEN)
    assert _origin(clone) == data_center["url"]
    _no_token_anywhere(git_argv, clone)
    assert data_center["seen"] and all(a == f"Bearer {TOKEN}" for _, _, a in data_center["seen"])
    assert not [p for _, p, _ in data_center["seen"] if TOKEN in p]


def test_the_commit_list_and_its_refresh_go_through_the_header(data_center, git_argv):
    url, before = data_center["url"], len(data_center["seen"])
    first = repo_git.list_commits(url, "dev", TOKEN, limit=10)
    assert [c["message"] for c in first][-3:] == ["commit 2", "commit 1", "commit 0"]

    # A commit pushed after the clone: the reused clone fetches it (git_cli.fetch), with the header.
    late = f"late {len(first)}"
    _fast_import(data_center["bare"], _commit("refs/heads/dev", 1700000100 + len(first), late,
                                              f"src/{late.replace(' ', '_')}.c", "int x;\n",
                                              parent="refs/heads/dev^0") + "\n")
    second = repo_git.list_commits(url, "dev", TOKEN, limit=10)
    assert second[0]["message"] == late and len(second) == len(first) + 1

    _no_token_anywhere(git_argv, repo_git._cache_path(url, "dev", 10, access_token=TOKEN))
    assert [a for a in git_argv if "fetch" in a], "the second list must have fetched"
    assert all(a == f"Bearer {TOKEN}" for _, _, a in data_center["seen"][before:])


def test_a_jobs_checkout_clones_and_fetches_an_older_commit(data_center, tmp_path, git_argv):
    oldest = data_center["shas"][0]
    dest = tmp_path / "ws" / "p1" / oldest[:16]
    # depth 1: the commit is outside the clone, so `_fetch_commit` fetches it by SHA.
    clone_mod.ensure_commit_checkout(str(dest), data_center["url"], "main", oldest,
                                     token=TOKEN, depth=1)
    assert git_ops.current_commit(str(dest)) == oldest
    assert _origin(dest) == data_center["url"]
    assert [a for a in git_argv if "fetch" in a], "the old commit must have been fetched"
    _no_token_anywhere(git_argv, dest)


def test_a_clone_made_with_a_token_is_not_served_without_it(data_center):
    """The wizard's clone cache is keyed by the token too: once someone browsed the private
    repository with theirs, a browse without one (or with another) must still be refused."""
    assert repo_git.browse(data_center["url"], "main", "src", TOKEN)["entries"]
    for other in (None, "FAKE-wrong-token"):
        with pytest.raises(git_cli.GitError):
            repo_git.browse(data_center["url"], "main", "src", other)


def test_no_token_and_a_wrong_token_are_told_apart(data_center, tmp_path):
    none = repo_git.test_connection(data_center["url"])
    assert (none["connected"], none["message"], none["repo_url"]) == (False, NEEDS, data_center["url"])
    wrong = repo_git.test_connection(data_center["url"], "FAKE-wrong-token")
    assert (wrong["connected"], wrong["message"], wrong["repo_url"]) == (False, CHECK, data_center["url"])

    with pytest.raises(git_ops.GitError) as exc:              # a job's clone, refused
        clone_mod.ensure_commit_checkout(str(tmp_path / "x"), data_center["url"], "main",
                                         data_center["shas"][-1], token=TOKEN + "-wrong")
    assert TOKEN not in str(exc.value)
    assert repo_git._friendly(str(exc.value), token_sent=True) == CHECK


# ── Cloud: Basic with x-token-auth ──────────────────────────────────────────────────────────

def test_cloud_style_basic_with_x_token_auth(cloud):
    assert clone_mod.bitbucket_kind(cloud["url"]) == "cloud"
    res = repo_git.test_connection(cloud["url"], TOKEN)
    assert res["connected"], res["message"]
    assert cloud["seen"] and all(a == f"Basic {BASIC}" for _, _, a in cloud["seen"])
    assert repo_git.test_connection(cloud["url"], "FAKE-wrong")["message"] == CHECK


# ── Over the API ────────────────────────────────────────────────────────────────────────────

TEST_CONNECTION = "/api/v1/repositories/test-connection"


def test_test_connection_answers_with_the_clone_url_over_http(client, auth_header, data_center):
    page = f"{data_center['base']}/projects/PROJ/repos/repo/browse"
    r = client.post(TEST_CONNECTION, headers=auth_header,
                    json={"repo_url": page, "access_token": TOKEN})
    assert r.status_code == 200, r.text
    assert r.json()["connected"] and r.json()["repo_url"] == data_center["url"]
    assert TOKEN not in r.text


def _git_refuses(monkeypatch):
    """git answers every remote call as a refused sign-in; records the URL each one was given."""
    urls = []

    def refuse(url, *a, **kw):
        urls.append(url)
        raise git_cli.GitError("git ls-remote failed (exit 128): fatal: could not read Username "
                               "for 'https://bitbucket.corp.example': terminal prompts disabled")

    monkeypatch.setattr(git_cli, "ls_remote", refuse)
    monkeypatch.setattr(repo_git, "_clone_or_reuse", refuse)
    return urls


PAGE = "https://bitbucket.corp.example/projects/VCU/repos/vcu-firmware/browse"
CLONE = "https://bitbucket.corp.example/scm/vcu/vcu-firmware.git"


def test_the_two_sign_in_messages_over_http(client, auth_header, monkeypatch):
    urls = _git_refuses(monkeypatch)
    for token, said in ((None, NEEDS), ("", NEEDS), (TOKEN, CHECK)):
        r = client.post(TEST_CONNECTION, headers=auth_header,
                        json={"repo_url": PAGE, "access_token": token})
        assert r.status_code == 200
        assert (r.json()["connected"], r.json()["message"], r.json()["repo_url"]) == (False, said, CLONE)
        r = client.post("/api/v1/repositories/browse", headers=auth_header,
                        json={"repo_url": PAGE, "ref": "main", "access_token": token})
        assert r.status_code == 400 and r.json()["detail"]["message"] == said
    assert set(urls) == {CLONE}, "git is given the clone URL, never the page"


def test_repo_url_is_in_every_answer(client, auth_header):
    for body, expected in (({"repo_url": "   "}, ""),
                           ({"repo_url": "relative/folder"}, "relative/folder")):
        r = client.post(TEST_CONNECTION, headers=auth_header, json=body)
        assert r.status_code == 200 and r.json()["repo_url"] == expected


def test_the_config_preview_reads_a_page_address_at_its_clone_url(client, auth_header, monkeypatch):
    text = '{"layers": {"Layer1": {"path": "src", "groups": {"G": {"C": "src"}}}}}'
    urls = _git_refuses(monkeypatch)
    for token, said in ((None, NEEDS), (TOKEN, CHECK)):
        r = client.post("/api/v1/projects/config/preview", headers=auth_header,
                        json={"text": text, "repo_url": PAGE, "branch": "main", "access_token": token})
        assert r.status_code == 200, r.text
        assert r.json()["repository_checked"] is False
        assert said in r.json()["report"][0]["text"]
    assert set(urls) == {CLONE}


def _create(client, auth_header, db, repo_url, provider=None, token=None):
    body = {"name": "Bitbucket ECU", "client": "T", "compliance_standard": "ASPICE_L2",
            "repo_url": repo_url, "default_branch": "main"}
    if provider:
        body["repo_provider"] = provider
    if token:
        body["access_token"] = token
    r = client.post("/api/v1/projects", json=body, headers=auth_header)
    assert r.status_code == 200, r.text
    assert TOKEN not in r.text
    return db.projects.get(r.json()["project"]["id"])


@pytest.mark.parametrize("pasted, stored", [
    (PAGE, CLONE),
    (CLONE, CLONE),
    ("https://bitbucket.org/ws/vcu-firmware/src/main/", "https://bitbucket.org/ws/vcu-firmware.git"),
])
@pytest.mark.parametrize("sent", [None, "github", "local"])
def test_a_bitbucket_project_is_stored_with_its_clone_url_as_bitbucket(
        client, auth_header, db, pasted, stored, sent):
    project = _create(client, auth_header, db, pasted, provider=sent, token=TOKEN)
    assert project.repo_url == stored
    assert project.repo_provider == "bitbucket"
    assert project.build_config["repo_access_token"] == TOKEN


@pytest.mark.parametrize("sent, kept", [(None, "github"), ("github", "github"),
                                        ("gitlab", "gitlab"), ("local", "github")])
def test_any_other_remote_keeps_the_provider_it_had(client, auth_header, db, sent, kept):
    project = _create(client, auth_header, db, "https://gitlab.corp.example/group/fw.git", provider=sent)
    assert project.repo_url == "https://gitlab.corp.example/group/fw.git"
    assert project.repo_provider == kept
