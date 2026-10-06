"""The platform's single git-clone primitive + on-demand per-commit checkout.

The new workspace layout addresses a version BY COMMIT: each commit's git checkout +
generated artifacts live under ``workspaces/<pid>/<commit[:16]>/``. The API server
(analyzer/api) creates that dir when a Job runs; the standalone CLI (generate.py /
engine.py) uses :func:`ensure_commit_checkout` to create it on demand — so the CLI is
independent and can clone for itself.

This module is the ONE shallow-clone implementation for the whole platform:
``api/services/git_cli.shallow_clone`` delegates here, so there is no duplicate clone
code. Kept in ``src/`` so the engine has no dependency on ``api/`` (the higher layer
depends on this one, not the reverse).

How an access token reaches git is ONE rule, :func:`git_auth`, read from the URL alone
(docs/design/BITBUCKET_SUPPORT.md, D1/D2): a Bitbucket token goes in an ``Authorization``
header handed to git through the environment; any other HTTPS host gets the token in the URL,
as it always has, and ``origin`` is reset to the credential-free URL afterwards. Either way
the token is never persisted to disk and is scrubbed from every error.
"""
from __future__ import annotations

import base64
import contextlib
import os
import time
from typing import Dict, Optional, Tuple
from urllib.parse import quote, urlsplit, urlunsplit

from incremental import git_ops
from incremental.git_ops import GitError, _check, _run

_DEPTH = 50

#: Bitbucket Cloud. Its tokens go with the fixed user name `x-token-auth`.
_BITBUCKET_CLOUD_HOSTS = frozenset({"bitbucket.org"})
#: Hosts that are never Bitbucket Data Center, whatever their paths hold: an organisation
#: called `scm` on GitHub keeps the token-in-URL it has always had.
_NOT_DATA_CENTER = frozenset({"github.com", "gitlab.com"}) | _BITBUCKET_CLOUD_HOSTS


def bitbucket_kind(url: str) -> Optional[str]:
    """``"cloud"`` for ``https://bitbucket.org/…``, ``"datacenter"`` for an http(s) URL whose
    path holds ``/scm/`` (a context path before it is fine), else None -- an SSH URL, a local
    path and every other host included."""
    parts = urlsplit((url or "").strip())
    if parts.scheme not in ("http", "https"):
        return None
    host = (parts.hostname or "").lower()
    if host in _BITBUCKET_CLOUD_HOSTS:
        return "cloud"
    if host not in _NOT_DATA_CENTER and "/scm/" in parts.path:
        return "datacenter"
    return None


def sends_token(url: str, token: str) -> bool:
    """Whether :func:`git_auth` hands git the token at all: an http(s) URL and a token. An SSH
    URL (the server's key) and a local path (file access) never carry one."""
    return bool((token or "").strip()) and urlsplit((url or "").strip()).scheme in ("http", "https")


def _header_env(url: str, header: Optional[str]) -> Dict[str, str]:
    """`header` for git, through the environment and never the arguments, scoped to the
    repository's own host (``http.<scheme>://<host>[:port]/.extraHeader``) so a redirect to any
    other host never carries it. Appended after any ``GIT_CONFIG_COUNT`` entries the process
    already has. With or without a header, git asks neither this machine's credential helper
    (Git Credential Manager probes the server for tens of seconds, then may answer with a login
    stored on the server) nor an askpass program (a window nobody on a server can answer): a
    refused sign-in comes back at once."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    origin = f"{parts.scheme}://{host}:{parts.port}" if parts.port else f"{parts.scheme}://{host}"
    try:
        n = max(0, int(os.environ.get("GIT_CONFIG_COUNT") or 0))
    except ValueError:
        n = 0
    entries = [(f"http.{origin}/.extraHeader", header)] if header else []
    entries.append(("credential.helper", ""))      # empty: the helper list is reset
    env = {"GIT_CONFIG_COUNT": str(n + len(entries)),
           "GIT_ASKPASS": ""}                      # set but empty: no askpass, SSH_ASKPASS neither
    for i, (key, value) in enumerate(entries, start=n):
        env[f"GIT_CONFIG_KEY_{i}"] = key
        env[f"GIT_CONFIG_VALUE_{i}"] = value
    return env


def git_auth(url: str, token: str = "") -> Tuple[str, Dict[str, str]]:
    """``(git_url, extra_env)`` for one git command that talks to the remote ``url``.

    The one rule for how an access token reaches git (BITBUCKET_SUPPORT.md D1), read from the
    URL, never asked:

    * ``ssh://…``, ``user@host:path``, a local path or ``file://`` -- no token: ``(url, {})``.
    * ``https://bitbucket.org/…`` (Cloud) -- header
      ``Authorization: Basic base64("x-token-auth:<token>")``.
    * any http(s) URL whose path holds ``/scm/`` (Data Center) -- header
      ``Authorization: Bearer <token>``.
    * any other http(s) URL (GitHub, GitLab, …) -- exactly as before: ``https://<token>:@host/…``
      and no extra environment.

    A header goes through ``extra_env`` (pass it to ``git_ops._run``) with the credential-free
    URL, so the token is in no argument, no URL and no ``.git/config``. A Bitbucket URL without
    a token keeps its URL, and its environment still turns off this machine's credential helper
    and askpass: "needs an access token" at once, never a login stored on the server."""
    tok = (token or "").strip()
    kind = bitbucket_kind(url)
    if not tok or not sends_token(url, tok):
        return url, (_header_env(url.strip(), None) if kind else {})
    if kind is None:
        return _auth_url(url, tok, ""), {}
    if kind == "cloud":
        basic = base64.b64encode(f"x-token-auth:{tok}".encode("utf-8")).decode("ascii")
        header = f"Authorization: Basic {basic}"
    else:
        header = f"Authorization: Bearer {tok}"
    clean = _clean_url(url.strip())
    return clean, _header_env(clean, header)


def scrub(text: str, url: str, token: str) -> str:
    """`text` (git's stderr) with the credential-bearing URL replaced by the clean one and the
    token itself, in every form it may take, masked -- for an error message or a log line."""
    out = text or ""
    tok = (token or "").strip()
    if url and tok:
        out = out.replace(_auth_url(url, tok, ""), _clean_url(url))
    if tok:
        forms = {tok, quote(tok, safe=""),
                 base64.b64encode(f"x-token-auth:{tok}".encode("utf-8")).decode("ascii")}
        for form in sorted(forms, key=len, reverse=True):
            out = out.replace(form, "***")
    return out


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
                  depth: int = 1, token: str = "", blobless: bool = False) -> None:
    """The single shallow-clone primitive: ``git clone --depth <depth> [--branch <ref>]``
    into ``dest_dir`` with the access token handed over as :func:`git_auth` says, then reset
    ``origin`` to the credential-free URL. Raises GitError (token scrubbed from the message).

    ``blobless=True`` adds ``--filter=blob:none --no-checkout`` for a *partial* clone that
    fetches commit + tree objects but **no file contents** — used for read-only tree
    browsing (the wizard folder picker), where only path names are needed. Blobs are
    fetched lazily on demand if ever accessed. Analysis clones (jobs/CLI) leave this off
    because they parse the source and need the blobs."""
    os.makedirs(os.path.dirname(dest_dir) or ".", exist_ok=True)
    git_url, env = git_auth(repo_url, token)
    # A plain local directory is not a shallow-capable transport: git ignores --depth
    # ("--depth is ignored in local clones") and copies the whole object store anyway.
    # --branch is worse than useless there -- it resolves ONLY against the source's
    # refs/heads, so a branch the caller can see in `git branch -a`, but which the
    # source holds as a remote-tracking ref, fails the clone outright:
    #     fatal: Remote branch <name> not found in upstream origin
    # The branch is only ever an optimisation to land a SHALLOW clone near the commit;
    # the caller checks the commit out explicitly straight afterwards. A local clone
    # brings every object with it, so that checkout succeeds whatever ref the commit
    # sits on -- including one reachable from no local branch at all.
    _local_path = bool(repo_url) and os.path.isdir(repo_url)
    args = ["clone"]
    if not _local_path:
        args += ["--depth", str(max(1, int(depth)))]
    if blobless:
        args += ["--filter=blob:none", "--no-checkout"]
    if ref and not _local_path:
        args += ["--branch", ref]
    args += [git_url, dest_dir]
    proc = _run(args, extra_env=env or None)
    if proc.returncode != 0:
        msg = scrub((proc.stderr or "").strip(), repo_url, token)
        raise GitError(f"clone failed (exit {proc.returncode}): {msg}")
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
    if not os.path.isdir(os.path.join(commit_dir, ".git")):
        if not repo_url:
            raise GitError(f"cannot clone {commit_dir!r}: no repo_url for the project "
                           f"(onboard the project, or pass --repo-url)")
        shallow_clone(repo_url, commit_dir, ref=(branch or None), depth=depth, token=token)
    if not git_ops.commit_exists(commit_dir, commit):
        _fetch_commit(commit_dir, repo_url, commit, token=token)
    git_ops.checkout(commit_dir, commit)


def _fetch_commit(commit_dir: str, repo_url: str, commit: str, *, token: str = "") -> None:
    """Bring ONE commit into a shallow checkout that does not have it.

    The clone above keeps only the newest `_DEPTH` commits of the branch. That is fine for a new
    generation, which is almost always near the tip, and wrong for anything that comes back to an
    OLDER version -- re-exporting one after the branch has moved on, say. Its commit has scrolled
    out of the window and `checkout` fails with nothing to say why.

    Fetches the commit by SHA from the AUTHENTICATED url, not `origin`: `shallow_clone` resets
    `origin` to the credential-free URL on purpose, so a plain `git fetch origin` would fail on a
    private repo for a reason unrelated to the commit. Falls back to `--unshallow` for a server
    that refuses fetch-by-SHA, which is slower but gets there.
    """
    src, env = git_auth(repo_url, token) if repo_url else ("origin", {})
    safe = _clean_url(repo_url) if repo_url else "origin"
    proc = git_ops._run(["-C", commit_dir, "fetch", "--depth", "1", src, commit],
                        extra_env=env or None)
    if proc.returncode != 0 or not git_ops.commit_exists(commit_dir, commit):
        git_ops._run(["-C", commit_dir, "fetch", "--unshallow", src], extra_env=env or None)
    if not git_ops.commit_exists(commit_dir, commit):
        why = scrub((proc.stderr or "").strip(), repo_url, token)
        raise GitError(f"commit {commit[:12]} is not in the checkout and could not be fetched "
                       f"from {safe}: {why or 'no further detail from git'}")
