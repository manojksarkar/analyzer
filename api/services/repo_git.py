"""
Real git-backed repository introspection for the new-project wizard.

Thin adapter over [`api/services/git_cli.py`](./git_cli.py) — the API's own,
self-contained `git` CLI wrapper (the API does **not** import from `engine/`):

  * :func:`test_connection` runs ``git ls-remote`` — a real remote round-trip
    that authenticates and lists branches **without cloning**.
  * :func:`browse` does a depth-1 clone (cached per repo+ref under
    ``workspaces/_wizard/``) and reads the tree with ``git ls-tree``.
  * :func:`list_commits` does a depth-limited clone + ``git log``.

Access tokens are passed through to git as HTTPS credentials and are never
persisted (git_cli scrubs them from the clone's ``origin`` and from any error
text). The clone cache is transient — these are *pre-project* browses, so they
live under ``workspaces/_wizard/`` keyed by a hash of the URL+ref+depth.
"""
from __future__ import annotations

import hashlib
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

from . import git_cli

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


def _creds(access_token: Optional[str]) -> tuple[str, str]:
    """HTTPS creds for git. A PAT goes in the username position
    (``https://<token>@host``), which GitHub/GitLab both accept; public repos
    pass empty creds and git_service leaves the URL untouched."""
    tok = (access_token or "").strip()
    return (tok, "") if tok else ("", "")


def test_connection(repo_url: str, access_token: Optional[str] = None) -> dict[str, Any]:
    """Real connection test via ``git ls-remote``. Never raises — a failure is
    reported as ``connected: False`` with git's (token-scrubbed) message."""
    url = (repo_url or "").strip()
    if not url:
        return {"connected": False, "default_branch": None, "branches": [],
                "message": "Repository URL is required."}
    try:
        res = git_cli.ls_remote(url, *_creds(access_token))
    except git_cli.GitError as exc:
        return {"connected": False, "default_branch": None, "branches": [],
                "message": _friendly(str(exc))}

    branches = [b["name"] for b in res["branches"]]
    if not branches:
        return {"connected": False, "default_branch": None, "branches": [],
                "message": "Reached the remote, but it has no branches."}
    return {
        "connected": True,
        "default_branch": res["defaultBranch"],
        "branches": branches,
        "message": f"Connected · {len(branches)} branches found",
    }


def _cache_path(repo_url: str, ref: Optional[str], depth: int, blobless: bool = False) -> Path:
    key = hashlib.sha256(
        f"{repo_url.strip()}@{ref or ''}@d{depth}@b{int(blobless)}".encode()
    ).hexdigest()[:16]
    return _CACHE_DIR / key


def _clone_or_reuse(
    repo_url: str, ref: Optional[str], access_token: Optional[str],
    depth: int = 1, blobless: bool = False, refresh: bool = False,
) -> Path:
    dest = _cache_path(repo_url, ref, depth, blobless)
    with _folder_lock(dest):
        if (dest / ".git").exists():
            # A cached clone is frozen at clone time. When the caller needs fresh
            # history (commit list), pull the branch's current tip so newly-pushed
            # commits appear. Best-effort: on failure, fall back to the snapshot.
            if refresh and ref and not (blobless and _fetched_recently(dest)):
                try:
                    git_cli.fetch(str(dest), repo_url.strip(), *_creds(access_token),
                                  ref, depth=depth)
                    _mark_fetched(dest)
                except git_cli.GitError:
                    pass
            return dest
        git_cli.shallow_clone(
            repo_url.strip(), *_creds(access_token), str(dest),
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
    that tree is what every path of the new project is checked against. Raises
    git_cli.GitError on clone failure (the route maps it to 400)."""
    url = (repo_url or "").strip()
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


def _friendly(msg: str) -> str:
    """Trim git's multi-line stderr to a short, user-facing reason."""
    low = msg.lower()
    if "authentication failed" in low or "could not read username" in low:
        return "Authentication failed — check the access token."
    if "repository not found" in low or "not found" in low:
        return "Repository not found — check the URL (and token for private repos)."
    if "could not resolve host" in low or "unable to access" in low or "timed out" in low:
        return "Could not reach the remote — check the URL and your network."
    # Fall back to the last non-empty line of git's message.
    lines = [ln.strip() for ln in msg.splitlines() if ln.strip()]
    return lines[-1] if lines else "Could not connect to the repository."
