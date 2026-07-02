"""
Self-contained git CLI wrapper for the API server.

A thin, dependency-free wrapper over the system ``git`` executable — the only
place the API talks to git. It is intentionally **independent of the analyzer
backend** (`backend/git_service.py`); the API does not import from `backend/`.

Conventions (mirrors the rest of the platform):
* **`shell=False`** — git args carry URLs/credentials; routing them through a
  shell would mangle `%`, `&`, `^` and risk exposing the token. The git
  executable is resolved via ``shutil.which`` so no shell is needed.
* HTTPS credentials are injected into the clone/fetch URL, and the clone's
  ``origin`` is immediately reset to the credential-free URL so the token is
  never persisted on disk. Tokens are scrubbed from any error text.
* ``GIT_TERMINAL_PROMPT=0`` makes auth failures fail fast instead of hanging.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Dict, List, Optional
from urllib.parse import quote, urlsplit, urlunsplit

from .settings import get_settings


class GitError(RuntimeError):
    """A git command exited non-zero (stderr included in the message)."""


# Field/record separators for `git log` parsing — control chars that can't
# appear in a commit subject, so splitting is unambiguous.
_FS = "\x1f"
_RS = "\x1e"


def _git_exe() -> str:
    return shutil.which("git") or "git"


def _run(args: List[str], cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run(
        [_git_exe(), *args],
        cwd=cwd, capture_output=True, text=True, env=env, shell=False,
    )


def _check(proc: subprocess.CompletedProcess, what: str) -> subprocess.CompletedProcess:
    if proc.returncode != 0:
        raise GitError(f"git {what} failed (exit {proc.returncode}): {proc.stderr.strip()}")
    return proc


# ---------------------------------------------------------------------------
# Credential-injected URLs (HTTPS only; other schemes pass through untouched)
# ---------------------------------------------------------------------------

def _auth_url(clone_url: str, username: str, token: str) -> str:
    parts = urlsplit(clone_url)
    if parts.scheme not in ("http", "https") or not (username or token):
        return clone_url
    host = parts.hostname or ""
    netloc = f"{quote(username, safe='')}:{quote(token, safe='')}@{host}"
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _clean_url(clone_url: str) -> str:
    parts = urlsplit(clone_url)
    if parts.scheme not in ("http", "https"):
        return clone_url
    host = parts.hostname or ""
    netloc = f"{host}:{parts.port}" if parts.port else host
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


# ---------------------------------------------------------------------------
# Remote / read-only operations used by the new-project wizard
# ---------------------------------------------------------------------------

def ls_remote(clone_url: str, username: str = "", token: str = "") -> Dict:
    """List a remote's branches without cloning — the real connection test.

    `git ls-remote --symref <url> HEAD "refs/heads/*"` → branch heads + the
    symbolic HEAD (default branch). Returns
    `{defaultBranch, branches:[{name, lastCommit}]}`. Raises GitError on any
    failure (token scrubbed from the message)."""
    auth = _auth_url(clone_url, username, token)
    proc = _run(["ls-remote", "--symref", auth, "HEAD", "refs/heads/*"])
    if proc.returncode != 0:
        msg = proc.stderr.strip().replace(auth, _clean_url(clone_url))
        raise GitError(f"git ls-remote failed (exit {proc.returncode}): {msg}")

    default_branch: Optional[str] = None
    branches: List[Dict[str, str]] = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        if line.startswith("ref:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].startswith("refs/heads/"):
                default_branch = parts[1][len("refs/heads/"):]
            continue
        sha, _, ref = line.partition("\t")
        if not ref or ref == "HEAD":
            continue
        if ref.startswith("refs/heads/"):
            branches.append({"name": ref[len("refs/heads/"):], "lastCommit": sha.strip()})
    if default_branch is None and branches:
        names = [b["name"] for b in branches]
        default_branch = next((n for n in ("main", "master") if n in names), names[0])
    return {"defaultBranch": default_branch, "branches": branches}


def shallow_clone(
    clone_url: str, username: str, token: str, dest_dir: str,
    ref: Optional[str] = None, depth: int = 1, blobless: bool = False,
) -> None:
    """Shallow single-branch clone for read-only use (tree browsing needs ``depth=1``;
    listing commits needs a larger depth). Resets ``origin`` to the credential-free URL
    afterwards. ``ref`` selects the branch.

    ``blobless=True`` requests a partial clone (no file contents) — used for tree browsing,
    which only needs path names, so the whole repo's blobs are never downloaded.

    Delegates to the platform's single clone primitive (``src/incremental/clone``), so the
    API, the per-commit job checkout, and the standalone engine all share ONE
    implementation. Re-raised as ``git_cli.GitError`` to preserve this module's error type."""
    src_dir = str(get_settings().repo_root / "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    from incremental.clone import shallow_clone as _shared  # type: ignore[import]
    from incremental.git_ops import GitError as _EngineGitError  # type: ignore[import]
    try:
        _shared(clone_url, dest_dir, ref=ref, depth=depth, username=username, token=token,
                blobless=blobless)
    except _EngineGitError as exc:
        raise GitError(str(exc))


def fetch(
    repo_dir: str, clone_url: str, username: str, token: str,
    ref: str, depth: int = 50,
) -> None:
    """Update a cached shallow clone's ``origin/<ref>`` to the current remote tip.

    Fetches straight from the credential-injected URL (not the clone's
    credential-free ``origin``), so private repos keep working without
    persisting the token, and stays shallow (``--depth``) to match the clone.
    Without this a reused clone is frozen at clone time and newly-pushed commits
    never appear. Raises GitError on failure."""
    branch = (ref or "").strip()
    if not branch:
        return
    auth = _auth_url(clone_url, username, token)
    proc = _run(["-C", repo_dir, "fetch", "--depth", str(int(depth)), auth,
                 f"+refs/heads/{branch}:refs/remotes/origin/{branch}"])
    if proc.returncode != 0:
        msg = proc.stderr.strip().replace(auth, _clean_url(clone_url))
        raise GitError(f"git fetch failed (exit {proc.returncode}): {msg}")


def list_tree(repo_dir: str, ref: str = "HEAD") -> List[Dict]:
    """Nested tree at ``ref`` from ``git ls-tree -r --name-only``. Each node:
    ``{type:'folder', name, path, children:[...]}`` or ``{type:'file', name, path}``.
    Children sorted folders-first, then alphabetically."""
    out = _check(_run(["-C", repo_dir, "ls-tree", "-r", "--name-only", ref]),
                 "ls-tree").stdout
    top: List[Dict] = []
    folders: Dict[str, Dict] = {}

    def _ensure_folder(path: str) -> Dict:
        node = folders.get(path)
        if node is not None:
            return node
        name = path.rsplit("/", 1)[-1]
        node = {"type": "folder", "name": name, "path": path, "children": []}
        folders[path] = node
        parent = path.rsplit("/", 1)[0] if "/" in path else ""
        (_ensure_folder(parent)["children"] if parent else top).append(node)
        return node

    for line in out.splitlines():
        f = line.strip()
        if not f:
            continue
        parent = f.rsplit("/", 1)[0] if "/" in f else ""
        file_node = {"type": "file", "name": f.rsplit("/", 1)[-1], "path": f}
        (_ensure_folder(parent)["children"] if parent else top).append(file_node)

    def _sort(nodes: List[Dict]) -> None:
        nodes.sort(key=lambda n: (n["type"] == "file", n["name"].lower()))
        for n in nodes:
            if n["type"] == "folder":
                _sort(n["children"])

    _sort(top)
    return top


def list_commits(repo_dir: str, branch: str, limit: int = 50, offset: int = 0) -> Dict:
    """`{branch, total, commits:[{sha, shortSha, author, authorEmail, date, message}]}`
    for ``origin/<branch>``, newest first, paged by limit/offset."""
    ref = f"origin/{branch}"
    total_proc = _run(["-C", repo_dir, "rev-list", "--count", ref])
    if total_proc.returncode != 0:
        raise GitError(f"unknown branch {branch!r}: {total_proc.stderr.strip()}")
    total = int(total_proc.stdout.strip() or "0")
    fmt = f"%H{_FS}%h{_FS}%an{_FS}%ae{_FS}%aI{_FS}%s{_RS}"
    out = _check(
        _run(["-C", repo_dir, "log", ref, f"--format={fmt}",
              "-n", str(int(limit)), "--skip", str(int(offset))]),
        "log",
    ).stdout
    commits: List[Dict[str, str]] = []
    for rec in out.split(_RS):
        rec = rec.strip("\n")
        if not rec.strip():
            continue
        sha, short, author, email, date, message = (rec.split(_FS) + [""] * 6)[:6]
        commits.append({"sha": sha, "shortSha": short, "author": author,
                        "authorEmail": email, "date": date, "message": message})
    return {"branch": branch, "total": total, "commits": commits}
