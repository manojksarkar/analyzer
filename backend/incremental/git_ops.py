"""Canonical local git primitives — no auth, no network (M2; consolidated in M3).

Operates on an already-cloned repo. Kept in src/ so the engine has **no dependency on
backend/**. This is the single home for every local git read/checkout op (ancestry,
diff, branch/commit listing, …); `backend/git_service.py` keeps only the credentialed
network ops (clone/fetch) and re-exports these. Both are thin `shell=False` wrappers
over the system git (shell=False is deliberate — credential/URL safety).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Dict, List, Optional

# Field/record separators for `git log`/`for-each-ref` parsing — control chars that
# cannot appear in a ref name or commit subject, so splitting is unambiguous.
_FS = "\x1f"  # between fields
_RS = "\x1e"  # between records


class GitError(RuntimeError):
    pass


def _run(args: List[str]) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run([shutil.which("git") or "git", *args],
                          capture_output=True, text=True, env=env, shell=False)


def _check(proc: subprocess.CompletedProcess, what: str) -> str:
    if proc.returncode != 0:
        raise GitError(f"git {what} failed (exit {proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout.strip()


def checkout(repo_dir: str, ref: str) -> None:
    _check(_run(["-C", repo_dir, "checkout", ref]), f"checkout {ref}")


def current_commit(repo_dir: str) -> str:
    return _check(_run(["-C", repo_dir, "rev-parse", "HEAD"]), "rev-parse HEAD")


def commit_exists(repo_dir: str, ref: str) -> bool:
    return _run(["-C", repo_dir, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"]).returncode == 0


def resolve(repo_dir: str, ref: str) -> Optional[str]:
    """Full SHA for a ref/commit/branch, or None if it doesn't resolve."""
    p = _run(["-C", repo_dir, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"])
    return p.stdout.strip() or None if p.returncode == 0 else None


def is_ancestor(repo_dir: str, ancestor: str, descendant: str) -> bool:
    """True iff `ancestor` is an ancestor of `descendant` (exit-code test)."""
    proc = _run(["-C", repo_dir, "merge-base", "--is-ancestor", ancestor, descendant])
    if proc.returncode in (0, 1):
        return proc.returncode == 0
    raise GitError(f"merge-base --is-ancestor failed (exit {proc.returncode}): {proc.stderr.strip()}")


def merge_base(repo_dir: str, a: str, b: str) -> Optional[str]:
    proc = _run(["-C", repo_dir, "merge-base", a, b])
    return (proc.stdout.strip() or None) if proc.returncode == 0 else None


def rev_list_count(repo_dir: str, base: str, target: str) -> int:
    """Number of commits in `base..target` (the 'distance' from base to target)."""
    return int(_check(_run(["-C", repo_dir, "rev-list", "--count", f"{base}..{target}"]),
                      "rev-list --count") or "0")


def changed_files(repo_dir: str, base: str, target: str) -> List[str]:
    """`git diff <base>..<target> --name-only` — the *what-changed* step."""
    out = _check(_run(["-C", repo_dir, "diff", f"{base}..{target}", "--name-only"]), "diff --name-only")
    return [ln for ln in out.splitlines() if ln.strip()]


def changed_files_status(repo_dir: str, base: str, target: str) -> List[tuple]:
    """`git diff <base>..<target> --name-status` -> [(status, path)] where status is a
    single letter: A(dded) / M(odified) / D(eleted) / R(enamed) / C(opied) / T(ype). The
    narrowed parse (M4) needs add/delete to detect header-shadowing and dropped TUs."""
    out = _check(_run(["-C", repo_dir, "diff", f"{base}..{target}", "--name-status"]), "diff --name-status")
    pairs: List[tuple] = []
    for ln in out.splitlines():
        if not ln.strip():
            continue
        cols = ln.split("\t")
        status = cols[0][:1] if cols[0] else ""
        # Renames/copies are "Rxx\told\tnew" — record the NEW path (and the old as deleted).
        if status in ("R", "C") and len(cols) >= 3:
            pairs.append(("D", cols[1]))
            pairs.append(("A", cols[2]))
        elif len(cols) >= 2:
            pairs.append((status, cols[1]))
    return pairs


def nearest_ancestor(repo_dir: str, candidate_commits: List[str], target: str) -> Optional[str]:
    """Among `candidate_commits`, keep ancestors of `target` and return the nearest
    (smallest base..target distance). None when no candidate is an ancestor."""
    best: Optional[str] = None
    best_distance: Optional[int] = None
    for c in candidate_commits:
        if not c or not is_ancestor(repo_dir, c, target):
            continue
        distance = rev_list_count(repo_dir, c, target)
        if best_distance is None or distance < best_distance:
            best, best_distance = c, distance
    return best


def list_branches(repo_dir: str) -> List[Dict[str, str]]:
    """List remote-tracking branches as `[{name, lastCommit, lastCommitDate}]`,
    sorted by most-recent commit first. Skips `origin/HEAD`."""
    fmt = f"%(refname:short){_FS}%(objectname){_FS}%(committerdate:iso-strict)"
    out = _check(_run(["-C", repo_dir, "for-each-ref", f"--format={fmt}",
                       "--sort=-committerdate", "refs/remotes/origin"]), "for-each-ref")
    branches: List[Dict[str, str]] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        short, sha, date = (line.split(_FS) + ["", "", ""])[:3]
        # `refs/remotes/origin/HEAD` collapses to "origin" in refname:short — skip that
        # symref; real branches are "origin/<name>".
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
    out = _check(_run(["-C", repo_dir, "log", ref, f"--format={fmt}",
                       "-n", str(int(limit)), "--skip", str(int(offset))]), "log")
    commits: List[Dict[str, str]] = []
    for rec in out.split(_RS):
        rec = rec.strip("\n")
        if not rec.strip():
            continue
        sha, short, author, date, message = (rec.split(_FS) + [""] * 5)[:5]
        commits.append({"sha": sha, "shortSha": short, "author": author,
                        "date": date, "message": message})
    return {"branch": branch, "total": total, "commits": commits}
