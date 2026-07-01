"""
Real git-backed repository introspection for the new-project wizard.

Thin adapter over [`api/services/git_cli.py`](./git_cli.py) — the API's own,
self-contained `git` CLI wrapper (the API does **not** import from `backend/`):

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
from pathlib import Path
from typing import Any, Optional

from . import git_cli

# Project root (…/analyzer) — used only to locate the transient clone cache.
_ROOT = Path(__file__).resolve().parents[2]
_CACHE_DIR = _ROOT / "workspaces" / "_wizard"


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
    depth: int = 1, blobless: bool = False,
) -> Path:
    dest = _cache_path(repo_url, ref, depth, blobless)
    if (dest / ".git").exists():
        return dest
    git_cli.shallow_clone(
        repo_url.strip(), *_creds(access_token), str(dest),
        ref=ref or None, depth=depth, blobless=blobless,
    )
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
    repo_dir = _clone_or_reuse(url, branch, access_token, depth=max(1, limit))
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


def browse(
    repo_url: str,
    ref: Optional[str] = None,
    path: str = "",
    access_token: Optional[str] = None,
) -> dict[str, Any]:
    """Clone (cached, depth-1, **blobless**) and return the tree under ``path``. The
    partial clone fetches commit + tree objects but no file contents, so listing folder
    names doesn't download the whole repo. Raises git_cli.GitError on clone failure (the
    route maps it to 400)."""
    url = (repo_url or "").strip()
    repo_dir = _clone_or_reuse(url, ref, access_token, blobless=True)
    tree = git_cli.list_tree(str(repo_dir), "HEAD")
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
