"""How an access token reaches git: ONE rule, read from the URL (docs/design/BITBUCKET_SUPPORT.md).

Every git call that talks to a remote handed the token over as the user name with an empty
password, `https://<token>:@host/...`. GitHub and GitLab accept that; Bitbucket does not: Data
Center takes `Authorization: Bearer <token>`, Cloud the token with the user name `x-token-auth`.
`incremental.clone.git_auth(url, token)` now decides, for every remote call:

    ssh://..., user@host:path, a local path   no token (the server's key; file access)
    https://bitbucket.org/...                 header  Authorization: Basic base64("x-token-auth:<t>")
    http(s)://.../scm/...                     header  Authorization: Bearer <t>
    any other http(s)                         https://<t>:@host/...  -- exactly as before

A header goes to git through the environment (`GIT_CONFIG_*`), scoped to the repository's host,
so the token is in no argument, no URL, no `.git/config` and no error message.

Also here: a Bitbucket PAGE address becomes its clone URL (`repo_git.clone_url`, D4), and a
refused sign-in is said as one, by whether a token was sent (`repo_git._friendly`, T3). The
same rules against a real HTTP git server: tests/api/test_bitbucket_repository.py.
"""
import base64
import os
import shutil
import subprocess
import sys
from urllib.parse import quote, urlsplit, urlunsplit

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (PROJECT_ROOT, os.path.join(PROJECT_ROOT, "engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from api.services import git_cli, repo_git          # noqa: E402
from incremental import clone as clone_mod           # noqa: E402
from incremental import git_ops                      # noqa: E402

pytestmark = pytest.mark.unit

TOKEN = "FAKE-token/with+odd=chars-0123456789"       # not a real token: odd characters on purpose
BASIC = base64.b64encode(f"x-token-auth:{TOKEN}".encode()).decode()
FORMS = (TOKEN, quote(TOKEN, safe=""), BASIC)          # every shape the token can take


def _leaks(text) -> bool:
    return any(f in str(text) for f in FORMS)


def _before(url: str, token: str) -> str:
    """The URL every remote call built before the rule: a frozen copy of the old `_auth_url`,
    called as `_auth_url(url, username=token, token="")`."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not token:
        return url
    host = parts.hostname or ""
    netloc = f"{quote(token, safe='')}:{quote('', safe='')}@{host}"
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


# ── D1: the rule, row by row ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "ssh://git@bitbucket.corp.example:7999/vcu/vcu-firmware.git",
    "git@bitbucket.corp.example:vcu/vcu-firmware.git",
    "git@bitbucket.org:ws/repo.git",
    "D:/src/vcu-firmware",
    "/srv/git/vcu-firmware",
    "file:///D:/src/vcu-firmware",
])
def test_ssh_and_local_get_no_token(url):
    assert clone_mod.git_auth(url, TOKEN) == (url, {})
    assert not clone_mod.sends_token(url, TOKEN)


def _header(env):
    """The one extraHeader entry git_auth adds: (key, value)."""
    keys = [k for k, v in env.items() if k.startswith("GIT_CONFIG_KEY_") and v.endswith(".extraHeader")]
    assert len(keys) == 1, sorted(env)
    n = keys[0][len("GIT_CONFIG_KEY_"):]
    return env[keys[0]], env[f"GIT_CONFIG_VALUE_{n}"]


@pytest.mark.parametrize("url", [
    "https://bitbucket.org/ws/repo.git",
    "https://user@bitbucket.org/ws/repo.git",          # Cloud's clone dialog puts the user name in
])
def test_bitbucket_cloud_gets_a_basic_header_with_x_token_auth(url):
    git_url, env = clone_mod.git_auth(url, TOKEN)
    assert git_url == "https://bitbucket.org/ws/repo.git"
    key, value = _header(env)
    assert key == "http.https://bitbucket.org/.extraHeader"
    assert value == f"Authorization: Basic {BASIC}"
    assert base64.b64decode(value.split()[-1]).decode() == f"x-token-auth:{TOKEN}"


@pytest.mark.parametrize("url, origin", [
    ("https://bitbucket.corp.example/scm/vcu/vcu-firmware.git", "https://bitbucket.corp.example"),
    ("https://bitbucket.corp.example/bitbucket/scm/vcu/vcu-firmware.git",
     "https://bitbucket.corp.example"),                                    # a context path
    ("https://Bitbucket.Corp.Example:8443/scm/~jdoe/tools.git", "https://bitbucket.corp.example:8443"),
    ("http://10.0.0.5:7990/scm/vcu/fw.git", "http://10.0.0.5:7990"),
])
def test_bitbucket_data_center_gets_a_bearer_header(url, origin):
    git_url, env = clone_mod.git_auth(url, TOKEN)
    assert not _leaks(git_url) and "@" not in urlsplit(git_url).netloc
    key, value = _header(env)
    assert key == f"http.{origin}/.extraHeader"
    assert value == f"Authorization: Bearer {TOKEN}"


@pytest.mark.parametrize("url", [
    "https://github.com/org/vcu-firmware.git",
    "https://gitlab.com/group/sub/vcu-firmware.git",
    "https://gitlab.corp.example:8443/group/vcu-firmware.git",
    "http://git.corp.example/vcu-firmware",
    "https://github.com/scm/tools.git",                # an organisation called "scm" on GitHub
    "https://gitlab.com/scm/tools.git",
])
@pytest.mark.parametrize("token", [TOKEN, "ghp_plainToken123", "glpat-x_y"])
def test_every_other_https_host_is_byte_for_byte_as_before(url, token):
    """D6: GitHub, GitLab and every other host keep the same URL and get no extra environment."""
    assert clone_mod.git_auth(url, token) == (_before(url, token), {})


@pytest.mark.parametrize("url", [
    "https://github.com/org/r.git", "https://gitlab.com/g/r.git", "git@host:p/r.git", "D:/src/r",
])
@pytest.mark.parametrize("token", ["", "   ", None])
def test_no_token_leaves_every_url_alone(url, token):
    assert clone_mod.git_auth(url, token) == (url, {})


@pytest.mark.parametrize("url", ["https://bitbucket.org/ws/r.git", "https://bb.corp.example/scm/p/r.git",
                                 "https://bb.corp.example:8443/ctx/scm/p/r.git"])
@pytest.mark.parametrize("token", ["", "   ", None])
def test_bitbucket_without_a_token_asks_no_credential_helper(url, token, monkeypatch):
    """No header, the same URL -- and neither this machine's credential helper nor an askpass
    program: Git Credential Manager made a refused sign-in wait about two minutes, and could
    have answered with a login stored on the server."""
    monkeypatch.delenv("GIT_CONFIG_COUNT", raising=False)
    git_url, env = clone_mod.git_auth(url, token)
    assert git_url == url
    assert env == {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "credential.helper",
                   "GIT_CONFIG_VALUE_0": "", "GIT_ASKPASS": ""}


def test_bitbucket_kind():
    kind = clone_mod.bitbucket_kind
    assert kind("https://bitbucket.org/ws/r.git") == "cloud"
    assert kind("https://bb.corp.example/ctx/scm/p/r.git") == "datacenter"
    assert kind("https://github.com/scm/r.git") is None
    assert kind("https://bb.corp.example/projects/P/repos/r") is None      # a page, not a clone URL
    assert kind("ssh://git@bb.corp.example:7999/scm/p/r.git") is None
    assert kind("D:/scm/p/r") is None


# ── D2: the header goes through the environment, scoped to the repository's host ────────────

def test_the_header_key_names_only_the_repositorys_host():
    _, env = clone_mod.git_auth("https://bb.corp.example:8443/ctx/scm/p/r.git", TOKEN)
    key, _ = _header(env)
    assert key == "http.https://bb.corp.example:8443/.extraHeader"
    assert "ctx" not in key and "/scm/" not in key


def _git_config_env(tmp_path, env):
    empty = tmp_path / "empty.gitconfig"
    empty.write_text("", encoding="utf-8")
    base = {k: v for k, v in os.environ.items() if not k.startswith("GIT_CONFIG")}
    return {**base, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": str(empty), **env}


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_git_sends_the_header_to_that_host_and_to_no_other(tmp_path):
    """Asked of git itself (`config --get-urlmatch`): a redirect to any other host, port or
    scheme never carries the token."""
    _, env = clone_mod.git_auth("https://bb.corp.example:8443/scm/p/r.git", TOKEN)
    full = _git_config_env(tmp_path, env)

    def header_for(url):
        r = subprocess.run(["git", "config", "--get-urlmatch", "http.extraheader", url],
                           env=full, cwd=tmp_path, capture_output=True, text=True)
        return r.stdout.strip()

    assert header_for("https://bb.corp.example:8443/scm/p/r.git") == f"Authorization: Bearer {TOKEN}"
    assert header_for("https://bb.corp.example:8443/scm/other/x.git/info/refs") != ""
    for elsewhere in ("https://bb.corp.example/scm/p/r.git",          # another port
                      "http://bb.corp.example:8443/scm/p/r.git",      # another scheme
                      "https://evil.example/scm/p/r.git",
                      "https://bb.corp.example.evil.example:8443/x"):
        assert header_for(elsewhere) == "", elsewhere


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_a_header_call_asks_no_credential_helper_and_no_askpass(tmp_path):
    """A refused token must fail at once: Git Credential Manager probes the server for tens of
    seconds (and may answer with a login of its own), an askpass program opens a window."""
    _, env = clone_mod.git_auth("https://bb.corp.example/scm/p/r.git", TOKEN)
    assert env["GIT_ASKPASS"] == ""
    cfg = tmp_path / "helper.gitconfig"
    cfg.write_text("[credential]\n\thelper = manager\n", encoding="utf-8")
    full = {**_git_config_env(tmp_path, env), "GIT_CONFIG_GLOBAL": str(cfg)}
    r = subprocess.run(["git", "config", "--get-all", "credential.helper"],
                       env=full, cwd=tmp_path, capture_output=True, text=True)
    assert r.stdout.splitlines()[-1:] == [""], "the last word must reset the helper list"


def test_an_existing_git_config_count_is_appended_to(monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_COUNT", "2")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.autocrlf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "false")
    monkeypatch.setenv("GIT_CONFIG_KEY_1", "http.sslVerify")
    monkeypatch.setenv("GIT_CONFIG_VALUE_1", "true")
    _, env = clone_mod.git_auth("https://bb.corp.example/scm/p/r.git", TOKEN)
    assert env["GIT_CONFIG_COUNT"] == "4"
    assert env["GIT_CONFIG_KEY_2"] == "http.https://bb.corp.example/.extraHeader"
    assert env["GIT_CONFIG_KEY_3"] == "credential.helper"
    assert not {"GIT_CONFIG_KEY_0", "GIT_CONFIG_KEY_1", "GIT_CONFIG_VALUE_0",
                "GIT_CONFIG_VALUE_1"} & set(env), "the process's own entries are left as they are"


# ── Every remote git call goes through the rule; the token never in argv ────────────────────

class _Proc:
    def __init__(self, rc=0, stderr="", stdout=""):
        self.returncode, self.stderr, self.stdout = rc, stderr, stdout


@pytest.fixture
def runs(monkeypatch):
    """Every git command the engine and the API would run: (argv, extra_env), none run."""
    seen = []

    def fake(args, *a, **kw):
        seen.append((list(args), kw.get("extra_env")))
        return _Proc()

    monkeypatch.setattr(clone_mod, "_run", fake)
    monkeypatch.setattr(clone_mod, "_check", lambda *a, **k: None)
    monkeypatch.setattr(git_ops, "_run", fake)
    monkeypatch.setattr(git_cli, "_run", fake)
    return seen


BITBUCKET_URLS = ["https://bitbucket.corp.example/scm/vcu/fw.git", "https://bitbucket.org/ws/fw.git"]


@pytest.mark.parametrize("url", BITBUCKET_URLS)
def test_a_bitbucket_token_is_in_no_argument_of_any_remote_call(url, runs, monkeypatch, tmp_path):
    monkeypatch.setattr(git_ops, "commit_exists", lambda *a: True)
    monkeypatch.setattr(git_ops, "checkout", lambda *a: None)
    clone_mod.shallow_clone(url, str(tmp_path / "a"), ref="main", depth=5, token=TOKEN)
    clone_mod._fetch_commit(str(tmp_path / "a"), url, "abc1234", token=TOKEN)
    clone_mod._do_checkout(str(tmp_path / "b"), url, "main", "abc1234", token=TOKEN)
    git_cli.ls_remote(url, token=TOKEN)
    git_cli.fetch(str(tmp_path / "a"), url, "main", token=TOKEN, depth=5)
    git_cli.shallow_clone(url, str(tmp_path / "c"), token=TOKEN, ref="main", depth=1, blobless=True)

    network = [(argv, env) for argv, env in runs
               if {"clone", "fetch", "ls-remote"} & set(argv)]
    assert len(network) >= 6
    for argv, env in network:
        assert not _leaks(" ".join(argv)), argv[:2]
        assert env and _header(env)[1].startswith("Authorization: "), argv[:2]
    assert not any(_leaks(" ".join(argv)) for argv, _ in runs)


def test_github_calls_are_the_same_arguments_as_before(runs, tmp_path, monkeypatch):
    """D6 at the argv level: same URL, same arguments, no extra environment."""
    url, dest = "https://github.com/org/fw.git", str(tmp_path / "d")
    auth = _before(url, TOKEN)
    clone_mod.shallow_clone(url, dest, ref="main", depth=50, token=TOKEN)
    git_cli.ls_remote(url, token=TOKEN)
    git_cli.fetch(dest, url, "main", token=TOKEN, depth=50)
    monkeypatch.setattr(git_ops, "commit_exists", lambda *a: True)
    clone_mod._fetch_commit(dest, url, "abc1234", token=TOKEN)
    remote = [r for r in runs if "set-url" not in r[0]]
    assert remote == [
        (["clone", "--depth", "50", "--branch", "main", auth, dest], None),
        (["ls-remote", "--symref", auth, "HEAD", "refs/heads/*"], None),
        (["-C", dest, "-c", f"remote.origin.url={auth}", "fetch", "--depth", "50",
          "origin", "+refs/heads/main:refs/remotes/origin/main"], None),
        (["-C", dest, "fetch", "--depth", "1", auth, "abc1234"], None),
    ]
    assert [r[0][-1] for r in runs if "set-url" in r[0]] == ["https://github.com/org/fw.git"]


def test_a_jobs_clone_passes_the_projects_token_once(runs, monkeypatch, tmp_path):
    """`pipeline_runner._checkout` hands the token to the clone as `token=` -- no more
    `username=token, password=""` -- so the rule decides how it reaches git."""
    from types import SimpleNamespace
    from api.services import pipeline_runner
    monkeypatch.setattr(pipeline_runner.subprocess, "run", lambda *a, **k: _Proc())
    url = "https://bitbucket.corp.example/scm/vcu/fw.git"
    project = SimpleNamespace(build_config={"repo_access_token": f" {TOKEN} "}, repo_url=url,
                              default_branch="dev")
    pipeline_runner._checkout(project, "abc1234", tmp_path / "co", "job-1")
    clone = [(argv, env) for argv, env in runs if "clone" in argv]
    assert len(clone) == 1
    argv, env = clone[0]
    assert argv[-2:] == [url, str(tmp_path / "co")] and "--branch" in argv and "dev" in argv
    assert _header(env) == ("http.https://bitbucket.corp.example/.extraHeader",
                            f"Authorization: Bearer {TOKEN}")


def test_the_api_has_no_credential_code_of_its_own():
    """`git_cli` kept its own copies of `_auth_url`/`_clean_url`: two rules that could drift."""
    assert not hasattr(git_cli, "_auth_url") and not hasattr(git_cli, "_clean_url")
    assert not hasattr(repo_git, "_creds")


# ── The token never in an error ─────────────────────────────────────────────────────────────

def _git_says(monkeypatch, stderr):
    def fake(args, *a, **kw):
        return _Proc(128, stderr=stderr)
    for mod in (clone_mod, git_ops, git_cli):
        monkeypatch.setattr(mod, "_run", fake)
    monkeypatch.setattr(git_ops, "commit_exists", lambda *a: False)


@pytest.mark.parametrize("url", BITBUCKET_URLS + ["https://github.com/org/fw.git"])
def test_a_git_error_never_carries_the_token(url, monkeypatch, tmp_path):
    # Whatever git might echo: the URL it was given, the token, its URL-encoded or Basic form.
    _git_says(monkeypatch, f"fatal: unable to access '{_before(url, TOKEN)}': 401\n"
                           f"header: Bearer {TOKEN} / Basic {BASIC} / {quote(TOKEN, safe='')}")
    calls = [
        lambda: clone_mod.shallow_clone(url, str(tmp_path / "a"), ref="main", token=TOKEN),
        lambda: clone_mod._fetch_commit(str(tmp_path / "a"), url, "abc1234", token=TOKEN),
        lambda: git_cli.ls_remote(url, token=TOKEN),
        lambda: git_cli.fetch(str(tmp_path / "a"), url, "main", token=TOKEN),
        lambda: git_cli.shallow_clone(url, str(tmp_path / "b"), token=TOKEN),
    ]
    for call in calls:
        with pytest.raises((git_ops.GitError, git_cli.GitError)) as exc:
            call()
        assert not _leaks(exc.value), type(exc.value).__name__
        assert "***" in str(exc.value) or urlsplit(url).hostname in str(exc.value)


def test_scrub_keeps_a_message_without_the_token_as_it_is():
    msg = "fatal: repository 'https://bb.corp.example/scm/p/r.git/' not found"
    assert clone_mod.scrub(msg, "https://bb.corp.example/scm/p/r.git", TOKEN) == msg
    assert clone_mod.scrub(msg, "https://bb.corp.example/scm/p/r.git", "") == msg


# ── D4: a Bitbucket page address becomes its clone URL ──────────────────────────────────────

@pytest.mark.parametrize("pasted, clone", [
    ("https://bb.corp.example/projects/VCU/repos/vcu-firmware",
     "https://bb.corp.example/scm/vcu/vcu-firmware.git"),
    ("https://bb.corp.example/projects/VCU/repos/vcu-firmware/browse",
     "https://bb.corp.example/scm/vcu/vcu-firmware.git"),
    ("https://bb.corp.example/projects/VCU/repos/vcu-firmware/browse/src/main.c?at=refs%2Fheads%2Fdev",
     "https://bb.corp.example/scm/vcu/vcu-firmware.git"),
    ("https://bb.corp.example/bitbucket/projects/VCU/repos/vcu-firmware/commits",
     "https://bb.corp.example/bitbucket/scm/vcu/vcu-firmware.git"),           # a context path
    ("https://bb.corp.example:7990/projects/VCU/repos/vcu-firmware/",
     "https://bb.corp.example:7990/scm/vcu/vcu-firmware.git"),
    ("  https://bb.corp.example/projects/VCU/repos/vcu-firmware/browse  ",
     "https://bb.corp.example/scm/vcu/vcu-firmware.git"),
    ("https://bb.corp.example/users/jdoe/repos/tools",
     "https://bb.corp.example/scm/~jdoe/tools.git"),
    ("https://bb.corp.example/ctx/users/jdoe/repos/tools/browse/x.c",
     "https://bb.corp.example/ctx/scm/~jdoe/tools.git"),
    ("https://bitbucket.org/ws/vcu-firmware", "https://bitbucket.org/ws/vcu-firmware.git"),
    ("https://bitbucket.org/ws/vcu-firmware/src/main/README.md",
     "https://bitbucket.org/ws/vcu-firmware.git"),
    ("https://bitbucket.org/ws/vcu-firmware.git", "https://bitbucket.org/ws/vcu-firmware.git"),
])
def test_a_page_address_becomes_its_clone_url(pasted, clone):
    assert repo_git.clone_url(pasted) == clone
    assert repo_git.is_bitbucket(clone)


@pytest.mark.parametrize("address", [
    "https://bb.corp.example/scm/vcu/vcu-firmware.git",         # already a clone URL
    "https://github.com/org/vcu-firmware.git",
    "https://github.com/projects/X/repos/y",                     # never read as a Bitbucket page
    "https://gitlab.com/group/vcu-firmware",
    "ssh://git@bb.corp.example:7999/vcu/vcu-firmware.git",
    "git@bb.corp.example:vcu/vcu-firmware.git",
    "D:/src/projects/VCU/repos/vcu-firmware",                     # a local path: checked first
    "D:\\src\\projects\\VCU\\repos\\vcu-firmware",
    '"D:\\src\\vcu-firmware"',
    "/srv/projects/VCU/repos/vcu-firmware",
    "file:///D:/projects/VCU/repos/x",
    "https://bitbucket.org/ws",
    "",
])
def test_anything_else_is_left_exactly_as_given(address):
    assert repo_git.clone_url(address) == address


def test_is_bitbucket_and_token_sent():
    assert repo_git.is_bitbucket("https://bitbucket.org/ws/r.git")
    assert repo_git.is_bitbucket("https://bb.corp.example/scm/p/r.git")
    assert not repo_git.is_bitbucket("https://github.com/org/r.git")
    assert not repo_git.is_bitbucket("D:/src/scm/p/r")
    assert repo_git.token_sent("https://bb.corp.example/scm/p/r.git", TOKEN)
    assert repo_git.token_sent("https://github.com/org/r.git", f"  {TOKEN} ")
    assert not repo_git.token_sent("https://github.com/org/r.git", "  ")
    assert not repo_git.token_sent("ssh://git@bb.corp.example:7999/p/r.git", TOKEN)
    assert not repo_git.token_sent("D:/src/r", TOKEN)


# ── T3: a refused sign-in is said as one ────────────────────────────────────────────────────

NEEDS = "Authentication failed — this repository needs an access token."
CHECK = "Authentication failed — check the access token."


@pytest.mark.parametrize("stderr", [
    "fatal: Authentication failed for 'https://github.com/org/r.git/'",
    "fatal: could not read Username for 'https://bb.corp.example': terminal prompts disabled",
    "fatal: could not read Password for 'https://jdoe@bb.corp.example': terminal prompts disabled",
    "fatal: unable to access 'https://bb.corp.example/scm/p/r.git/': The requested URL returned error: 401",
    "fatal: unable to access 'https://bb.corp.example/scm/p/r.git/': The requested URL returned error: 403",
])
def test_a_sign_in_failure_is_checked_first_and_said_by_whether_a_token_was_sent(stderr):
    assert repo_git._friendly(f"git ls-remote failed (exit 128): {stderr}") == NEEDS
    assert repo_git._friendly(f"git ls-remote failed (exit 128): {stderr}", token_sent=True) == CHECK


@pytest.mark.parametrize("stderr, said", [
    ("fatal: 'x' does not appear to be a git repository",
     "Not a git repository — check the URL or the folder."),
    ("remote: Repository not found.\nfatal: repository 'https://h/x.git/' not found",
     "Repository not found — check the URL (and token for private repos)."),
    ("fatal: unable to access 'https://h/x.git/': Could not resolve host: h",
     "Could not reach the remote — check the URL and your network."),
    ("fatal: unable to access 'https://h/x.git/': Failed to connect to h port 443",
     "Could not reach the remote — check the URL and your network."),
    ("warning: one\nfatal: something else entirely", "fatal: something else entirely"),
])
@pytest.mark.parametrize("sent", [False, True])
def test_the_other_answers_are_as_before(stderr, said, sent):
    assert repo_git._friendly(stderr, token_sent=sent) == said
