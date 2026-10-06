"""
Real git-backed repository introspection for the new-project wizard.

Thin adapter over [`api/services/git_cli.py`](./git_cli.py) — the API's own,
self-contained `git` CLI wrapper (the API does **not** import from `engine/`):

  * :func:`test_connection` runs ``git ls-remote`` — a real remote round-trip
    that authenticates and lists branches **without cloning**.
  * :func:`browse` does a depth-1 clone (cached per repo+ref under
    ``workspaces/_wizard/``) and reads the tree with ``git ls-tree``.
  * :func:`list_commits` does a depth-limited clone + ``git log``.

Access tokens are passed through to git as the engine's one rule says
(``incremental.clone.git_auth``: a header for Bitbucket, the URL for other HTTPS hosts) and
are never persisted (git_cli scrubs them from the clone's ``origin`` and from any error
text). A Bitbucket page address is turned into its clone URL first (:func:`clone_url`).
The clone cache is transient — these are *pre-project* browses, so they
live under ``workspaces/_wizard/`` keyed by a hash of the URL+ref+depth.
"""
from __future__ import annotations

import hashlib
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

from . import git_cli, local_repos

# Project root (…/analyzer) — used only to locate the transient clone cache.
_ROOT = Path(__file__).resolve().parents[2]
_CACHE_DIR = _ROOT / "workspaces" / "_wizard"

# A wizard clone (blobless) fetched this recently is current enough: Test Connection reads the
# tree and then checks an imported config against it, and each fetch is a network round trip
# (seconds). Commit-list clones keep fetching every time.
_FRESH_SECONDS = 60
_FETCHED_MARK = "analyzer-fetched"

# One lock per clone folder: two requests for a branch no one has cloned yet - the tree and the
# config check, or two tabs - both ran `git clone` into it, and the second one failed.
_LOCKS: dict = {}
_LOCKS_GUARD = threading.Lock()


def _folder_lock(dest: Path) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(str(dest), threading.Lock())


def _fetched_recently(dest: Path) -> bool:
    try:
        return time.time() - (dest / ".git" / _FETCHED_MARK).stat().st_mtime < _FRESH_SECONDS
    except OSError:
        return False


def _mark_fetched(dest: Path) -> None:
    try:
        (dest / ".git" / _FETCHED_MARK).write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass


def repo_root_name(repo_url: str) -> str:
    """Derive a repo-root label (…/vcu-firmware.git → ``vcu-firmware``)."""
    t = repo_url.strip().rstrip("/")
    t = re.sub(r"\.git$", "", t, flags=re.IGNORECASE)
    if not t:
        return "project-root"
    return re.split(r"[/\\]", t)[-1] or "project-root"


def _token(access_token: Optional[str]) -> str:
    return (access_token or "").strip()


# ── A Bitbucket page address → its clone URL (BITBUCKET_SUPPORT.md D4) ────────────────────────
# The address people copy is the repository's PAGE; git answers "not found" to it.
# Data Center: <ctx>/projects/<KEY>/repos/<slug>[/browse…] and <ctx>/users/<name>/repos/<slug>[/…]
_DC_PROJECT_PAGE = re.compile(
    r"^(?P<ctx>(?:/[^/]+)*?)/projects/(?P<key>[^/]+)/repos/(?P<repo>[^/]+)(?:/.*)?$")
_DC_USER_PAGE = re.compile(
    r"^(?P<ctx>(?:/[^/]+)*?)/users/(?P<user>[^/]+)/repos/(?P<repo>[^/]+)(?:/.*)?$")
# Cloud: bitbucket.org/<workspace>/<repo>[/src/…]
_CLOUD_PAGE = re.compile(r"^/(?P<ws>[^/]+)/(?P<repo>[^/]+)(?:/.*)?$")
# Hosts whose paths are never read as a Bitbucket Data Center page.
_NOT_DATA_CENTER = {"github.com", "gitlab.com", "bitbucket.org"}


def _dot_git(repo: str) -> str:
    return repo if repo.lower().endswith(".git") else f"{repo}.git"


def clone_url(address: str) -> str:
    """The clone URL for a Bitbucket repository's page address; anything else as given.

    =================================================================  ==========================================
    ``https://host[/ctx]/projects/VCU/repos/vcu-firmware[/browse…]``   ``https://host[/ctx]/scm/vcu/vcu-firmware.git``
    ``https://host[/ctx]/users/<name>/repos/<repo>[/…]``               ``https://host[/ctx]/scm/~<name>/<repo>.git``
    ``https://bitbucket.org/<workspace>/<repo>[/src/…]``               ``https://bitbucket.org/<workspace>/<repo>.git``
    =================================================================  ==========================================

    A local path is checked first and never touched; so is an SSH URL, a clone URL and every
    other host's address. The project key is lower-cased, as Bitbucket's clone URLs have it."""
    text = (address or "").strip()
    if not text or local_repos.is_local(text):
        return address
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https"):
        return address
    host = (parts.hostname or "").lower()
    path = parts.path

    def _built(new_path: str) -> str:
        return urlunsplit((parts.scheme, parts.netloc, new_path, "", ""))

    if host == "bitbucket.org":
        m = _CLOUD_PAGE.match(path)
        if m:
            return _built(f"/{m['ws']}/{_dot_git(m['repo'])}")
        return address
    if host in _NOT_DATA_CENTER:
        return address
    m = _DC_PROJECT_PAGE.match(path)
    if m:
        return _built(f"{m['ctx']}/scm/{m['key'].lower()}/{_dot_git(m['repo'])}")
    m = _DC_USER_PAGE.match(path)
    if m:
        return _built(f"{m['ctx']}/scm/~{m['user']}/{_dot_git(m['repo'])}")
    return address


def is_bitbucket(repo_url: str) -> bool:
    """A Bitbucket clone URL -- Cloud (`bitbucket.org`) or Data Center (a `/scm/` path) -- by
    the same reading `git_auth` uses to send the token. For `projects.repo_provider` (D5)."""
    return git_cli._clone_module().bitbucket_kind(repo_url) is not None


def token_sent(repo_url: str, access_token: Optional[str]) -> bool:
    """Whether git is handed the token for this URL at all (not for SSH or a local path) --
    which of the two sign-in messages a failure gets."""
    url = (repo_url or "").strip()
    if not url or local_repos.is_local(url):
        return False
    return git_cli._clone_module().sends_token(url, _token(access_token))


def test_connection(repo_url: str, access_token: Optional[str] = None) -> dict[str, Any]:
    """Real connection test via ``git ls-remote``. Never raises — a failure is
    reported as ``connected: False`` with git's (token-scrubbed) message.

    ``repo_url`` in the answer is the URL git was given -- a Bitbucket page address turned into
    its clone URL, a local path as git reads it -- on success and on failure alike, so the
    wizard can put it in the box."""
    url = (repo_url or "").strip()
    if not url:
        return {"connected": False, "default_branch": None, "branches": [],
                "message": "Repository URL is required.", "repo_url": ""}
    token = _token(access_token)
    if local_repos.is_local(url):
        # A git repository's folder on the server: said plainly when it is not one (git's own
        # answer ended "...and the repository exists."), and no token is sent.
        url, token = local_repos.clean(url), ""
        why = local_repos.problem(url)
        if why:
            return {"connected": False, "default_branch": None, "branches": [], "message": why,
                    "repo_url": url}
    else:
        url = clone_url(url)
    try:
        res = git_cli.ls_remote(url, token=token)
    except git_cli.GitError as exc:
        return {"connected": False, "default_branch": None, "branches": [],
                "message": _friendly(str(exc), token_sent=token_sent(url, token)),
                "repo_url": url}

    branches = [b["name"] for b in res["branches"]]
    if not branches:
        return {"connected": False, "default_branch": None, "branches": [],
                "message": "Reached the remote, but it has no branches.", "repo_url": url}
    return {
        "connected": True,
        "default_branch": res["defaultBranch"],
        "branches": branches,
        "message": f"Connected · {len(branches)} branches found",
        "repo_url": url,
    }


def _cache_path(repo_url: str, ref: Optional[str], depth: int, blobless: bool = False,
                access_token: Optional[str] = None) -> Path:
    # The token is part of the key: a clone made with one person's token is never served to a
    # request without it (a refused refresh falls back to the cached clone, so a key without
    # the token let anyone browse a private repository someone else had opened).
    token = _token(access_token)
    key = hashlib.sha256(
        (f"{repo_url.strip()}@{ref or ''}@d{depth}@b{int(blobless)}"
         + (f"@t{token}" if token else "")).encode()
    ).hexdigest()[:16]
    return _CACHE_DIR / key


def _clone_or_reuse(
    repo_url: str, ref: Optional[str], access_token: Optional[str],
    depth: int = 1, blobless: bool = False, refresh: bool = False,
) -> Path:
    dest = _cache_path(repo_url, ref, depth, blobless, access_token)
    with _folder_lock(dest):
        if (dest / ".git").exists():
            # A cached clone is frozen at clone time. When the caller needs fresh
            # history (commit list), pull the branch's current tip so newly-pushed
            # commits appear. Best-effort: on failure, fall back to the snapshot.
            if refresh and ref and not (blobless and _fetched_recently(dest)):
                try:
                    git_cli.fetch(str(dest), repo_url.strip(), ref,
                                  token=_token(access_token), depth=depth)
                    _mark_fetched(dest)
                except git_cli.GitError:
                    pass
            return dest
        git_cli.shallow_clone(
            repo_url.strip(), str(dest), token=_token(access_token),
            ref=ref or None, depth=depth, blobless=blobless,
        )
        _mark_fetched(dest)
        return dest


def list_commits(
    repo_url: str,
    ref: Optional[str] = None,
    access_token: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Recent commits on ``ref`` via a depth-limited clone + ``git log``. Returns
    ``[{sha, shortSha, author, authorEmail, date, message}]`` (newest first).
    Raises git_cli.GitError on failure (caller decides whether to swallow)."""
    url = (repo_url or "").strip()
    branch = (ref or "").strip()
    if not url or not branch:
        return []
    repo_dir = _clone_or_reuse(url, branch, access_token, depth=max(1, limit), refresh=True)
    data = git_cli.list_commits(str(repo_dir), branch, limit=limit, offset=0)
    return data.get("commits", [])


def _children_at(nodes: list[dict], path: str) -> list[dict]:
    norm = path.strip().strip("/")
    if not norm:
        return nodes
    for n in nodes:
        if n.get("path") == norm:
            return n.get("children", []) if n.get("type") == "folder" else []
        if n.get("type") == "folder":
            found = _children_at(n.get("children", []), norm)
            if found:
                return found
    return []


def tree_ref(repo_dir: Path, ref: Optional[str]) -> str:
    """The commit to read a cached clone at: the branch's fetched tip (``origin/<ref>``) when
    the clone has it, else HEAD. A reused clone's HEAD stays at the commit it was cloned at, so
    reading HEAD after a refresh showed - and checked paths against - an old snapshot."""
    if ref and git_cli.has_ref(str(repo_dir), f"refs/remotes/origin/{ref}"):
        return f"refs/remotes/origin/{ref}"
    return "HEAD"


def browse(
    repo_url: str,
    ref: Optional[str] = None,
    path: str = "",
    access_token: Optional[str] = None,
    refresh: bool = False,
) -> dict[str, Any]:
    """Clone (cached, depth-1, **blobless**) and return the tree under ``path``. The
    partial clone fetches commit + tree objects but no file contents, so listing folder
    names doesn't download the whole repo. ``refresh`` first fetches the branch's current
    tip into a reused clone: the wizard asks for it when it connects or changes branch, since
    that tree is what every path of the new project is checked against. A Bitbucket page
    address is read at its clone URL, which ``repo_url`` in the answer gives. Raises
    git_cli.GitError on clone failure (the route maps it to 400)."""
    url = clone_url((repo_url or "").strip())
    repo_dir = _clone_or_reuse(url, ref, access_token, blobless=True, refresh=refresh)
    tree = git_cli.list_tree(str(repo_dir), tree_ref(repo_dir, ref))
    norm = (path or "").strip().strip("/")
    entries = _children_at(tree, norm) if norm else tree
    return {
        "repo_url": url,
        "ref": ref,
        "path": norm,
        "root_name": repo_root_name(url),
        "entries": entries,
    }


#: git's words for a refused sign-in: a wrong token ("Authentication failed for …"), none where
#: one is needed (git then asks for a login it cannot read), or the server's HTTP answer.
_SIGN_IN_FAILED = ("authentication failed", "could not read username", "could not read password",
                   "returned error: 401", "returned error: 403")


def _friendly(msg: str, token_sent: bool = False) -> str:
    """Trim git's multi-line stderr to a short, user-facing reason. A refused sign-in is
    checked first -- git words it "unable to access …: The requested URL returned error: 401",
    which read as an unreachable server -- and answered by whether a token was sent
    (:func:`token_sent`)."""
    low = msg.lower()
    if any(s in low for s in _SIGN_IN_FAILED):
        if token_sent:
            return "Authentication failed — check the access token."
        return "Authentication failed — this repository needs an access token."
    if "does not appear to be a git repository" in low:
        return "Not a git repository — check the URL or the folder."
    if "repository not found" in low or "not found" in low:
        return "Repository not found — check the URL (and token for private repos)."
    if "could not resolve host" in low or "unable to access" in low or "timed out" in low:
        return "Could not reach the remote — check the URL and your network."
    # Fall back to the last non-empty line of git's message.
    lines = [ln.strip() for ln in msg.splitlines() if ln.strip()]
    return lines[-1] if lines else "Could not connect to the repository."
