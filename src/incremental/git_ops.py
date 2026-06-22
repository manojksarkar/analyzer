"""Local git primitives for the incremental engine (M2) — no auth, no network.

Operates on an already-cloned repo (onboarding owns clone/fetch/credentials via
backend/git_service.py). Kept in src/ so the engine has no dependency on backend/.
(git_service.py has overlapping ancestry/diff helpers; consolidation is an M3
cleanup — both are thin `shell=False` wrappers over the system git.)
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import List, Optional


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
