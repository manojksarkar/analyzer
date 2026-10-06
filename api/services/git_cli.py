"""
Git CLI wrapper for the API server.

A thin wrapper over the system ``git`` executable — the only place the API talks to git.
How an access token reaches git is the engine's one rule, ``incremental.clone.git_auth``
(docs/design/BITBUCKET_SUPPORT.md D1): the clone itself is the engine's
(``shallow_clone`` delegates), and ``ls_remote`` / ``fetch`` take their URL and environment
from the same function.

Conventions (mirrors the rest of the platform):
* **`shell=False`** — git args carry URLs/credentials; routing them through a
  shell would mangle `%`, `&`, `^` and risk exposing the token. The git
  executable is resolved via ``shutil.which`` so no shell is needed.
* A token goes where ``git_auth`` says: a Bitbucket one in an ``Authorization`` header passed
  through the environment, any other HTTPS host's in the clone/fetch URL. A clone's ``origin``
  is reset to the credential-free URL, so the token is never persisted on disk, and tokens are
  scrubbed from any error text.
* ``GIT_TERMINAL_PROMPT=0`` makes auth failures fail fast instead of hanging.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Dict, List, Optional

from .settings import get_settings


class GitError(RuntimeError):
    """A git command exited non-zero (stderr included in the message)."""


# Field/record separators for `git log` parsing — control chars that can't
# appear in a commit subject, so splitting is unambiguous.
_FS = "\x1f"
_RS = "\x1e"


def _git_exe() -> str:
    return shutil.which("git") or "git"


#: Seconds one git command may run before it is stopped. A clone or fetch of a large repository
#: over a slow link takes minutes; listing a remote's branches, seconds. With no limit, a slow or
#: unreachable server -- or a credential helper waiting for a login nobody can type -- held the
#: request for ever (one test waited an hour). `ANALYZER_GIT_TIMEOUT` overrides the network ones.
TIMEOUTS = {"clone": 1800, "fetch": 900, "ls-remote": 120}
LOCAL_TIMEOUT = 600
#: The exit code a stopped command reports (as coreutils `timeout` does).
TIMED_OUT = 124


def _timeout(args: List[str]) -> float:
    for a in args:
        if a in TIMEOUTS:
            try:
                return float(os.environ.get("ANALYZER_GIT_TIMEOUT") or TIMEOUTS[a])
            except ValueError:
                return TIMEOUTS[a]
    return LOCAL_TIMEOUT


def quiet_env() -> Dict[str, str]:
    """The environment git runs in: it never asks for anything, it fails instead."""
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"           # no username/password prompt on a console
    env["GCM_INTERACTIVE"] = "never"           # Git Credential Manager: no login window
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")   # no ssh password prompt
    return env


def _stop_tree(proc: subprocess.Popen) -> None:
    """Kill `proc` and everything beneath it (git starts helpers that hold its pipes open).
    Best-effort: never raises."""
    try:
        import psutil                                   # type: ignore[import]
        for child in psutil.Process(proc.pid).children(recursive=True):
            try:
                child.kill()
            except Exception:                           # noqa: BLE001
                pass
    except Exception:                                   # noqa: BLE001 - no psutil, or gone
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True)
    try:
        proc.kill()
    except Exception:                                   # noqa: BLE001
        pass


def _run(args: List[str], cwd: Optional[str] = None,
         extra_env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
    """`git <args>`, stopped -- the whole process tree -- once it has run longer than its limit
    (`TIMEOUTS`), and then answered as a failure (exit `TIMED_OUT`) like any other, so every
    caller's handling of a failed git command applies. The message never carries the arguments:
    a clone URL can hold a token. `extra_env` is merged over `quiet_env()` (what `git_auth`
    returns for a token sent as a header)."""
    cmd = [_git_exe(), *args]
    limit = _timeout(args)
    env = quiet_env()
    if extra_env:
        env.update(extra_env)
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, env=env, shell=False)
    try:
        out, err = proc.communicate(timeout=limit)
    except subprocess.TimeoutExpired:
        _stop_tree(proc)
        try:
            proc.communicate(timeout=10)
        except Exception:                               # noqa: BLE001 - the pipes are closing
            pass
        what = next((a for a in args if a in TIMEOUTS), "command")
        return subprocess.CompletedProcess(
            cmd, TIMED_OUT, "",
            f"git {what} did not finish within {int(limit)} s and was stopped: the repository is "
            f"slow or unreachable, or git is waiting for a login, which cannot be typed here")
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def _check(proc: subprocess.CompletedProcess, what: str) -> subprocess.CompletedProcess:
    if proc.returncode != 0:
        raise GitError(f"git {what} failed (exit {proc.returncode}): {proc.stderr.strip()}")
    return proc


# ---------------------------------------------------------------------------
# Credentials: the engine's one rule (incremental.clone.git_auth)
# ---------------------------------------------------------------------------

def _clone_module():
    """`incremental.clone` -- the platform's clone primitive and its credential rule."""
    src_dir = str(get_settings().repo_root / "engine")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    from incremental import clone  # type: ignore[import]
    return clone


# ---------------------------------------------------------------------------
# Remote / read-only operations used by the new-project wizard
# ---------------------------------------------------------------------------

def ls_remote(clone_url: str, token: str = "") -> Dict:
    """List a remote's branches without cloning — the real connection test.

    `git ls-remote --symref <url> HEAD "refs/heads/*"` → branch heads + the
    symbolic HEAD (default branch). Returns
    `{defaultBranch, branches:[{name, lastCommit}]}`. Raises GitError on any
    failure (token scrubbed from the message)."""
    clone = _clone_module()
    git_url, env = clone.git_auth(clone_url, token)
    proc = _run(["ls-remote", "--symref", git_url, "HEAD", "refs/heads/*"], extra_env=env or None)
    if proc.returncode != 0:
        msg = clone.scrub(proc.stderr.strip(), clone_url, token)
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
    clone_url: str, dest_dir: str, *, token: str = "",
    ref: Optional[str] = None, depth: int = 1, blobless: bool = False,
) -> None:
    """Shallow single-branch clone for read-only use (tree browsing needs ``depth=1``;
    listing commits needs a larger depth). Resets ``origin`` to the credential-free URL
    afterwards. ``ref`` selects the branch.

    ``blobless=True`` requests a partial clone (no file contents) — used for tree browsing,
    which only needs path names, so the whole repo's blobs are never downloaded.

    Delegates to the platform's single clone primitive (``engine/incremental/clone``), so the
    API, the per-commit job checkout, and the standalone engine all share ONE
    implementation. Re-raised as ``git_cli.GitError`` to preserve this module's error type."""
    clone = _clone_module()
    from incremental.git_ops import GitError as _EngineGitError  # type: ignore[import]
    try:
        clone.shallow_clone(clone_url, dest_dir, ref=ref, depth=depth, token=token,
                            blobless=blobless)
    except _EngineGitError as exc:
        raise GitError(str(exc))


def fetch(
    repo_dir: str, clone_url: str, ref: str, *, token: str = "", depth: int = 50,
) -> None:
    """Update a cached shallow clone's ``origin/<ref>`` to the current remote tip.

    Fetches from ``origin`` with the URL ``git_auth`` gives supplied for this one
    command (``-c remote.origin.url=...``) and its environment, so private repos keep working
    without persisting the token, and stays shallow (``--depth``) to match the clone.
    Through ``origin`` - not the bare URL - because a blobless clone's filter belongs
    to that remote: fetching the URL downloaded the content of every file the new
    commits added or changed. Without
    this a reused clone is frozen at clone time and newly-pushed commits never
    appear. Raises GitError on failure."""
    branch = (ref or "").strip()
    if not branch:
        return
    clone = _clone_module()
    git_url, env = clone.git_auth(clone_url, token)
    proc = _run(["-C", repo_dir, "-c", f"remote.origin.url={git_url}", "fetch",
                 "--depth", str(int(depth)), "origin",
                 f"+refs/heads/{branch}:refs/remotes/origin/{branch}"], extra_env=env or None)
    if proc.returncode != 0:
        msg = clone.scrub(proc.stderr.strip(), clone_url, token)
        raise GitError(f"git fetch failed (exit {proc.returncode}): {msg}")


def has_ref(repo_dir: str, ref: str) -> bool:
    """Whether ``ref`` names a commit in the clone."""
    return _run(["-C", repo_dir, "rev-parse", "--verify", "--quiet",
                 f"{ref}^{{commit}}"]).returncode == 0


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
