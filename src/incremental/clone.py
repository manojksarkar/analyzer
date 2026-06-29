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

import json
import os
from typing import Optional, Tuple
from urllib.parse import quote, urlsplit, urlunsplit

from core.paths import paths as _paths
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
                  depth: int = 1, username: str = "", token: str = "") -> None:
    """The single shallow-clone primitive: ``git clone --depth <depth> [--branch <ref>]``
    into ``dest_dir`` with HTTPS auth injected, then reset ``origin`` to the credential-free
    URL. Raises GitError (token scrubbed from the message)."""
    os.makedirs(os.path.dirname(dest_dir) or ".", exist_ok=True)
    auth = _auth_url(repo_url, username, token)
    args = ["clone", "--depth", str(max(1, int(depth)))]
    if ref:
        args += ["--branch", ref]
    args += [auth, dest_dir]
    proc = _run(args)
    if proc.returncode != 0:
        msg = (proc.stderr or "").strip().replace(auth, _clean_url(repo_url))
        raise GitError(f"clone --depth failed (exit {proc.returncode}): {msg}")
    _check(_run(["-C", dest_dir, "remote", "set-url", "origin", _clean_url(repo_url)]),
           "remote set-url")


def ensure_commit_checkout(commit_dir: str, repo_url: str, branch: str, commit: str,
                           *, token: str = "", depth: int = _DEPTH) -> None:
    """Ensure ``commit_dir`` is a git checkout at ``commit``.

    If ``.git`` already exists there (e.g. the API pre-cloned it for a Job), just check out
    the commit. Otherwise shallow-clone ``branch`` (depth-50) into ``commit_dir`` via the
    shared primitive and check out the commit. Lets the CLI run independently — it downloads
    the commit if it isn't present."""
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


def resolve_project_repo(project_id: str, *, project_root: str = None) -> Tuple[str, str, str]:
    """Return ``(repo_url, default_branch, token)`` for a project from the API's JSON DB
    (``api/db/data/projects.json``, the onboarding record). Returns ``("", "main", "")``
    when the file or project is absent. Used by the CLI to clone a commit on demand; the
    API passes these explicitly so it never needs this lookup."""
    root = project_root or _paths().project_root
    path = os.path.join(root, "api", "db", "data", "projects.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            projects = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return "", "main", ""
    records = projects.values() if isinstance(projects, dict) else projects
    for p in records:
        if isinstance(p, dict) and p.get("id") == project_id:
            bc = p.get("build_config") or {}
            tok = bc.get("repo_access_token") or bc.get("access_token") or ""
            return (p.get("repo_url") or "", p.get("default_branch") or "main", tok)
    return "", "main", ""
