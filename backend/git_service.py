"""Git ingestion for the analyzer backend (M0 #1) — **network + auth only**.

After the M3 consolidation, every *local* git primitive (checkout, current_commit,
ancestry/diff, branch/commit listing) lives in the canonical
`src/incremental/git_ops.py` and is **re-exported here** so existing `git_service.<fn>`
callers keep working unchanged. This module now owns only the operations that need
credentials / the network:

  - `clone_repo` — clone once (HTTPS + username/token auth), then scrub the token
  - `fetch`      — fetch all branches into `refs/remotes/origin/*`

Design notes
------------
* **Auth (POC):** credentials are plaintext for now (see doc 04 / D8). For HTTPS we
  inject `username:token` into the clone/fetch URL, then immediately reset the clone's
  `origin` remote to the credential-free URL so the token is **not** persisted in
  `.git/config`. The token is never written to disk by us and never logged.
* **`shell=False` is deliberate** (it routes URLs/credentials safely) — `git_ops`
  uses the same runner, which we import here.
* `GIT_TERMINAL_PROMPT=0` (set by `git_ops._run`) fails fast instead of hanging on a
  credential prompt.
"""

from __future__ import annotations

import os
from typing import Optional
from urllib.parse import quote, urlsplit, urlunsplit

# Canonical local git primitives (consolidated into git_ops). Re-exported so existing
# `git_service.<fn>` callers — and `except git_service.GitError` — keep working.
from incremental.git_ops import (  # noqa: F401  (re-exported)
    GitError,
    _check,
    _run,
    changed_files,
    checkout,
    current_commit,
    is_ancestor,
    list_branches,
    list_commits,
    merge_base,
    nearest_ancestor,
)


# ---------------------------------------------------------------------------
# Credential-injected URLs (HTTPS only; other schemes pass through untouched)
# ---------------------------------------------------------------------------

def _auth_url(clone_url: str, username: str, token: str) -> str:
    """Return the clone URL with `username:token@` injected, for HTTPS only.

    Username and token are URL-encoded so special characters survive. Non-HTTPS
    URLs (ssh, local paths) are returned unchanged — those auth out-of-band.
    """
    parts = urlsplit(clone_url)
    if parts.scheme not in ("http", "https") or not (username or token):
        return clone_url
    host = parts.hostname or ""
    netloc = f"{quote(username, safe='')}:{quote(token, safe='')}@{host}"
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _clean_url(clone_url: str) -> str:
    """Strip any embedded credentials from a URL (used to reset `origin`)."""
    parts = urlsplit(clone_url)
    if parts.scheme not in ("http", "https"):
        return clone_url
    host = parts.hostname or ""
    netloc = f"{host}:{parts.port}" if parts.port else host
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


# ---------------------------------------------------------------------------
# Remote operations (need auth)
# ---------------------------------------------------------------------------

def clone_repo(
    clone_url: str,
    username: str,
    token: str,
    dest_dir: str,
    branch: Optional[str] = None,
) -> None:
    """Clone `clone_url` into `dest_dir` (full clone — all branches available for
    listing). After cloning, `origin` is reset to the credential-free URL so the
    token is not persisted. Optionally checks out `branch`.

    Raises GitError on failure (the message carries git's stderr, with the
    credential-bearing URL stripped).
    """
    os.makedirs(os.path.dirname(dest_dir) or ".", exist_ok=True)
    auth = _auth_url(clone_url, username, token)
    proc = _run(["clone", auth, dest_dir])
    if proc.returncode != 0:
        # Never leak the token: scrub the auth URL from any error text.
        msg = proc.stderr.strip().replace(auth, _clean_url(clone_url))
        raise GitError(f"git clone failed (exit {proc.returncode}): {msg}")
    # Drop the credential-bearing remote so the token isn't stored on disk.
    _check(_run(["-C", dest_dir, "remote", "set-url", "origin", _clean_url(clone_url)]),
           "remote set-url")
    if branch:
        checkout(dest_dir, branch)


def fetch(repo_dir: str, clone_url: str, username: str, token: str) -> None:
    """Fetch all branches into `refs/remotes/origin/*` (with `--prune`)."""
    auth = _auth_url(clone_url, username, token)
    proc = _run(["-C", repo_dir, "fetch", auth,
                 "+refs/heads/*:refs/remotes/origin/*", "--prune"])
    if proc.returncode != 0:
        msg = proc.stderr.strip().replace(auth, _clean_url(clone_url))
        raise GitError(f"git fetch failed (exit {proc.returncode}): {msg}")
