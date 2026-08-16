"""The platform's single git-clone primitive + on-demand per-commit checkout.

The new workspace layout addresses a version BY COMMIT: each commit's git checkout +
generated artifacts live under ``workspaces/<pid>/<commit[:16]>/``. The API server
(analyzer/api) creates that dir when a Job runs; the standalone CLI (generate.py /
engine.py) uses :func:`ensure_commit_checkout` to create it on demand — so the CLI is
independent and can clone for itself.

This module is the ONE shallow-clone implementation for the whole platform:
``api/services/git_cli.shallow_clone`` delegates here, so there is no duplicate clone
code. Kept in ``src/`` so the engine has no dependency on ``api/`` (the higher layer
depends on this one, not the reverse). HTTPS credentials are injected into the clone URL
then scrubbed from ``origin`` (never persisted to disk); tokens are scrubbed from errors.
"""
from __future__ import annotations

import contextlib
import os
import time
from typing import Optional
from urllib.parse import quote, urlsplit, urlunsplit

from incremental import git_ops
from incremental.git_ops import GitError, _check, _run

_DEPTH = 50


def _auth_url(clone_url: str, username: str, token: str) -> str:
    """Inject ``username:token@`` into an HTTPS URL (URL-encoded, port-preserving). Non-HTTPS
    URLs (ssh, local paths) and credential-free calls pass through unchanged."""
    parts = urlsplit(clone_url)
    if parts.scheme not in ("http", "https") or not (username or token):
        return clone_url
    host = parts.hostname or ""
    netloc = f"{quote(username, safe='')}:{quote(token, safe='')}@{host}"
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _clean_url(clone_url: str) -> str:
    """Strip any ``user:token@`` from an HTTPS URL (for safe errors + the origin reset)."""
    parts = urlsplit(clone_url)
    if parts.scheme not in ("http", "https"):
        return clone_url
    host = parts.hostname or ""
    netloc = f"{host}:{parts.port}" if parts.port else host
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def shallow_clone(repo_url: str, dest_dir: str, *, ref: Optional[str] = None,
                  depth: int = 1, username: str = "", token: str = "",
                  blobless: bool = False) -> None:
    """The single shallow-clone primitive: ``git clone --depth <depth> [--branch <ref>]``
    into ``dest_dir`` with HTTPS auth injected, then reset ``origin`` to the credential-free
    URL. Raises GitError (token scrubbed from the message).

    ``blobless=True`` adds ``--filter=blob:none --no-checkout`` for a *partial* clone that
    fetches commit + tree objects but **no file contents** — used for read-only tree
    browsing (the wizard folder picker), where only path names are needed. Blobs are
    fetched lazily on demand if ever accessed. Analysis clones (jobs/CLI) leave this off
    because they parse the source and need the blobs."""
    os.makedirs(os.path.dirname(dest_dir) or ".", exist_ok=True)
    auth = _auth_url(repo_url, username, token)
    args = ["clone", "--depth", str(max(1, int(depth)))]
    if blobless:
        args += ["--filter=blob:none", "--no-checkout"]
    if ref:
        args += ["--branch", ref]
    args += [auth, dest_dir]
    proc = _run(args)
    if proc.returncode != 0:
        msg = (proc.stderr or "").strip().replace(auth, _clean_url(repo_url))
        raise GitError(f"clone --depth failed (exit {proc.returncode}): {msg}")
    _check(_run(["-C", dest_dir, "remote", "set-url", "origin", _clean_url(repo_url)]),
           "remote set-url")


# How long to wait for another process to finish checking out the same commit dir, and how
# long before an existing lock is assumed abandoned (a killed job leaves its lock behind).
_LOCK_TIMEOUT_S = 300
_LOCK_STALE_S = 900


@contextlib.contextmanager
def _dir_lock(target_dir: str):
    """A cross-process mutex for one checkout directory.

    `os.mkdir` is atomic on every platform we run on — exactly one caller can create a given
    directory — which makes it a portable lock without a dependency or platform branches.

    Needed because the checkout dir is keyed by COMMIT, so two jobs generating the same commit
    share it. Without the lock they race in two ways: both find no `.git` and clone into the
    same directory on top of each other, or both run `git checkout` and one dies on
    `index.lock`. Neither can corrupt a version's data, but both fail a job for no reason —
    and that becomes likely the moment JOB_MAX_CONCURRENCY is raised above 1.

    A stale lock (owner killed) is reclaimed after `_LOCK_STALE_S`, so a crash cannot wedge a
    project permanently.
    """
    lock = target_dir.rstrip("/\\") + ".lock"
    os.makedirs(os.path.dirname(lock) or ".", exist_ok=True)
    deadline = time.time() + _LOCK_TIMEOUT_S
    while True:
        try:
            os.mkdir(lock)
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock) > _LOCK_STALE_S:
                    os.rmdir(lock)          # abandoned by a killed job — reclaim it
                    continue
            except OSError:
                pass                        # it vanished under us; just retry
            if time.time() > deadline:
                raise GitError(
                    f"timed out after {_LOCK_TIMEOUT_S}s waiting for another job to finish "
                    f"preparing the checkout at {target_dir!r}")
            time.sleep(0.25)
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            os.rmdir(lock)


def _already_at(commit_dir: str, commit: str) -> bool:
    """True when the checkout exists and HEAD is already the requested commit."""
    if not commit or not os.path.isdir(os.path.join(commit_dir, ".git")):
        return False
    try:
        from incremental import git_ops
        return git_ops.current_commit(commit_dir).strip().startswith(commit.strip()[:7])
    except Exception:
        return False

def ensure_commit_checkout(commit_dir: str, repo_url: str, branch: str, commit: str,
                           *, token: str = "", depth: int = _DEPTH) -> None:
    """Ensure ``commit_dir`` is a git checkout at ``commit``.

    If ``.git`` already exists there (e.g. the API pre-cloned it for a Job), just check out
    the commit. Otherwise shallow-clone ``branch`` (depth-50) into ``commit_dir`` via the
    shared primitive and check out the commit. Lets the CLI run independently — it downloads
    the commit if it isn't present."""
    # Fast path: already at the requested commit — no git write, so no lock and no contention.
    # This is the common case when two jobs target the same commit.
    if _already_at(commit_dir, commit):
        return
    with _dir_lock(commit_dir):
        if _already_at(commit_dir, commit):     # another job prepared it while we waited
            return
        _do_checkout(commit_dir, repo_url, branch, commit, token=token, depth=depth)


def _do_checkout(commit_dir: str, repo_url: str, branch: str, commit: str,
                 *, token: str = "", depth: int = _DEPTH) -> None:
    """The actual clone/checkout. Callers hold the directory lock."""
    if os.path.isdir(os.path.join(commit_dir, ".git")):
        git_ops.checkout(commit_dir, commit)
        return
    if not repo_url:
        raise GitError(f"cannot clone {commit_dir!r}: no repo_url for the project "
                       f"(onboard the project, or pass --repo-url)")
    # PAT goes in the username position (GitHub/GitLab accept token-as-username).
    shallow_clone(repo_url, commit_dir, ref=(branch or None), depth=depth,
                  username=(token or ""), token="")
    git_ops.checkout(commit_dir, commit)
