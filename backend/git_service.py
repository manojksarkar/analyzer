"""Git ingestion service for the analyzer backend (M0 #1).

Thin, dependency-free wrapper over the system `git` CLI. It is the *only* place
the backend talks to git. Responsibilities:

  - clone a project once (HTTPS + username/token auth), checkout a commit
  - fetch updates, list branches and commits from the local clone
  - the baseline primitives for incremental generation:
      * `is_ancestor`   — `git merge-base --is-ancestor` (exit-code test)
      * `nearest_ancestor` — pick the closest prior commit that is an ancestor
      * `changed_files` — `git diff <base>..<target> --name-only`

Design notes
------------
* **Auth (POC):** credentials are plaintext for now (see doc 04 / D8). For HTTPS
  we inject `username:token` into the clone/fetch URL, then immediately reset the
  clone's `origin` remote to the credential-free URL so the token is **not**
  persisted in `.git/config`. The token is never written to disk by us and never
  logged (only the clean URL is logged).
* **`shell=False` is deliberate here.** Git arguments carry URLs and credentials;
  routing them through a Windows shell (`cmd.exe`) would mangle characters such as
  `%` (URL-encoding) and `&`/`^`, and would risk exposing the token to shell
  parsing. We resolve the absolute `git` path via `shutil.which` so the executable
  is still found without a shell. (This is a scoped exception to the project's
  general `shell=True` preference, which applies to spawning the analyzer pipeline.)
* `GIT_TERMINAL_PROMPT=0` makes auth failures fail fast instead of hanging on a
  credential prompt.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Dict, List, Optional
from urllib.parse import quote, urlsplit, urlunsplit


class GitError(RuntimeError):
    """A git command exited non-zero (stderr is included in the message)."""


# Field/record separators for `git log` parsing — control chars that cannot
# appear in a commit subject, so splitting is unambiguous even for messages
# containing '|', spaces, quotes, etc.
_FS = "\x1f"  # between fields
_RS = "\x1e"  # between records


def _git_exe() -> str:
    return shutil.which("git") or "git"


def _run(args: List[str], cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    """Run `git <args>` with no shell. Returns the CompletedProcess (caller
    decides how to treat the return code). stdout/stderr captured as text."""
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"  # never block on an interactive auth prompt
    return subprocess.run(
        [_git_exe(), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
        shell=False,  # deliberate — see module docstring (credential/URL safety)
    )


def _check(proc: subprocess.CompletedProcess, what: str) -> subprocess.CompletedProcess:
    if proc.returncode != 0:
        raise GitError(f"git {what} failed (exit {proc.returncode}): {proc.stderr.strip()}")
    return proc


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


# ---------------------------------------------------------------------------
# Local operations (no auth)
# ---------------------------------------------------------------------------

def checkout(repo_dir: str, ref: str) -> None:
    """Checkout a commit/branch (detached HEAD for a bare commit)."""
    _check(_run(["-C", repo_dir, "checkout", ref]), f"checkout {ref}")


def current_commit(repo_dir: str) -> str:
    return _check(_run(["-C", repo_dir, "rev-parse", "HEAD"]), "rev-parse HEAD").stdout.strip()


def list_branches(repo_dir: str) -> List[Dict[str, str]]:
    """List remote-tracking branches as `[{name, lastCommit, lastCommitDate}]`,
    sorted by most-recent commit first. Skips `origin/HEAD`."""
    fmt = f"%(refname:short){_FS}%(objectname){_FS}%(committerdate:iso-strict)"
    out = _check(
        _run(["-C", repo_dir, "for-each-ref", f"--format={fmt}",
              "--sort=-committerdate", "refs/remotes/origin"]),
        "for-each-ref",
    ).stdout
    branches: List[Dict[str, str]] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        short, sha, date = (line.split(_FS) + ["", "", ""])[:3]
        # `refs/remotes/origin/HEAD` collapses to the bare remote name ("origin")
        # in refname:short — skip that symref; real branches are "origin/<name>".
        if "/" not in short or short.endswith("/HEAD"):
            continue
        name = short.split("/", 1)[1]  # strip the leading "origin/"
        branches.append({"name": name, "lastCommit": sha, "lastCommitDate": date})
    return branches


def list_commits(repo_dir: str, branch: str, limit: int = 50, offset: int = 0) -> Dict:
    """Return `{branch, total, commits:[{sha, shortSha, author, date, message}]}`
    for `origin/<branch>`, newest first, paged by limit/offset."""
    ref = f"origin/{branch}"
    total_proc = _run(["-C", repo_dir, "rev-list", "--count", ref])
    if total_proc.returncode != 0:
        raise GitError(f"unknown branch {branch!r}: {total_proc.stderr.strip()}")
    total = int(total_proc.stdout.strip() or "0")
    fmt = f"%H{_FS}%h{_FS}%an{_FS}%aI{_FS}%s{_RS}"
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
        sha, short, author, date, message = (rec.split(_FS) + [""] * 5)[:5]
        commits.append({"sha": sha, "shortSha": short, "author": author,
                        "date": date, "message": message})
    return {"branch": branch, "total": total, "commits": commits}


# ---------------------------------------------------------------------------
# Baseline primitives for incremental generation
# ---------------------------------------------------------------------------

def is_ancestor(repo_dir: str, ancestor: str, descendant: str) -> bool:
    """True iff `ancestor` is an ancestor of `descendant`.

    `git merge-base --is-ancestor` is a silent test: exit 0 = ancestor,
    1 = not, any other code = error (raised)."""
    proc = _run(["-C", repo_dir, "merge-base", "--is-ancestor", ancestor, descendant])
    if proc.returncode in (0, 1):
        return proc.returncode == 0
    raise GitError(f"merge-base --is-ancestor failed (exit {proc.returncode}): {proc.stderr.strip()}")


def merge_base(repo_dir: str, a: str, b: str) -> Optional[str]:
    """Return the common-ancestor (fork point) commit of `a` and `b`, or None."""
    proc = _run(["-C", repo_dir, "merge-base", a, b])
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def changed_files(repo_dir: str, base: str, target: str) -> List[str]:
    """Files differing between two commits — `git diff <base>..<target> --name-only`.
    NOTE: this is the *what-changed* step; it does NOT find an ancestor and is only
    run after `nearest_ancestor` has chosen a valid baseline."""
    out = _check(_run(["-C", repo_dir, "diff", f"{base}..{target}", "--name-only"]),
                 "diff --name-only").stdout
    return [ln for ln in out.splitlines() if ln.strip()]


def nearest_ancestor(repo_dir: str, candidate_commits: List[str], target: str) -> Optional[str]:
    """Pick the baseline for an incremental run: among `candidate_commits`
    (the commits of previously-generated versions) keep those that are ancestors
    of `target`, and return the **nearest** one (fewest commits between it and
    `target`). Returns None when no candidate is an ancestor → caller does a
    FULL generation."""
    best: Optional[str] = None
    best_distance: Optional[int] = None
    for c in candidate_commits:
        if not c or not is_ancestor(repo_dir, c, target):
            continue
        proc = _run(["-C", repo_dir, "rev-list", "--count", f"{c}..{target}"])
        if proc.returncode != 0:
            continue
        distance = int(proc.stdout.strip() or "0")
        if best_distance is None or distance < best_distance:
            best, best_distance = c, distance
    return best
