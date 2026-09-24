"""Find — or put back — the source checkout a version was generated from.

Re-exporting from Phase 3 reads the C++ SOURCE again (the flowchart engine rebuilds each graph
from it, and line numbers come from it), so it needs the commit on disk. It used to look in exactly
one place, `workspaces/<pid>/<recorded_sha[:16]>`, and tell the caller to "generate again" when that
was empty. Generating again is a full LLM run to recover what is, at most, a git checkout.

And "empty" was often not even true. Three ways the checkout is there, or recoverable, but not
where that one lookup expected it:

  1. **Named from a short SHA.** `generate` names the folder from the commit AS TYPED
     (`--commit 8b3e313f` -> `.../8b3e313f`) but records the FULL sha it resolved. Looking for
     `full[:16]` misses a folder that is sitting right there.
  2. **Another working copy on this machine.** `workspaces/` lives under the data root and is
     gitignored, so a second clone of the repo starts with none of it — while the database both
     share still lists every version. `versions.base_path` records the exact folder the version was
     generated from, wherever that was.
  3. **Genuinely absent** — cleaned up, or a different machine. That is a clone of one commit, not
     a regeneration.

Tried in that order, cheapest first, and the answer says which one it used. Every candidate is
verified to be AT the recorded commit before it is used: a folder with the right name and the wrong
source would produce a document whose line numbers describe different code, and nothing downstream
could tell.

The source is only READ, so a checkout belonging to another working copy is safe to use.
"""
from __future__ import annotations

import os
from typing import NamedTuple, Optional


class SourceUnavailable(RuntimeError):
    """The version's source is not on this machine and could not be restored. Says why."""


class SourceCheckout(NamedTuple):
    path: str
    #: "in place" | "base_path" | "short-sha folder" | "restored"
    how: str


def _at(path: Optional[str], commit: str) -> bool:
    """True when `path` is a git checkout whose HEAD is exactly `commit`."""
    if not path or not os.path.isdir(os.path.join(path, ".git")):
        return False
    try:
        from incremental import git_ops
        return git_ops.current_commit(path) == commit
    except Exception:                                  # noqa: BLE001 - "not usable" is the answer
        return False


def _version_row(project_id: str, version_id: str):
    from core.db import get_engine, is_database_configured
    if not is_database_configured():
        raise SourceUnavailable("no database is configured, so there is no record of which "
                                "commit version %r was built from" % version_id)
    import sqlalchemy as sa
    from api.db.postgres import schema as s
    with get_engine().connect() as cx:
        row = cx.execute(sa.select(s.versions.c.commit_sha, s.versions.c.branch,
                                   s.versions.c.base_path, s.versions.c.status)
                         .where(s.versions.c.id == version_id,
                                s.versions.c.project_id == project_id)).first()
        if row is None:
            known = [r.id for r in cx.execute(
                sa.select(s.versions.c.id).where(s.versions.c.project_id == project_id,
                                                 s.versions.c.commit_sha.isnot(None)))]
            raise SourceUnavailable(
                "project %r has no version %r. Versions that were generated: %s"
                % (project_id, version_id, ", ".join(known) or "(none)"))
        if not row.commit_sha:
            known = [r.id for r in cx.execute(
                sa.select(s.versions.c.id).where(s.versions.c.project_id == project_id,
                                                 s.versions.c.commit_sha.isnot(None)))]
            # The one case where the old message was right but unhelpful: a version reserved
            # (by onboard or the UI) and never generated has nothing to re-export.
            raise SourceUnavailable(
                "version %r was never generated — it is reserved (status %r) but has no commit, "
                "so there is nothing to re-export. Generate it first, or re-export one that was "
                "generated: %s" % (version_id, row.status, ", ".join(known) or "(none)"))
    return row


def locate_or_restore(project_id: str, version_id: str, *,
                      workspaces_root: Optional[str] = None) -> SourceCheckout:
    """The checkout `version_id` was generated from, restoring it if nothing usable is on disk."""
    row = _version_row(project_id, version_id)
    commit = row.commit_sha

    # The paths are computed, not taken from `Workspace(...)`: that raises when
    # `workspaces/<pid>/` does not exist at all -- which is exactly the fresh-working-copy case
    # this module is for, and would stop it before it looked at `base_path` or restored anything.
    from incremental.stores import default_workspaces_root
    ws_root = os.path.join(workspaces_root or default_workspaces_root(), project_id)
    expected = os.path.join(ws_root, commit[:16])

    # 1. where a full-SHA generation put it
    if _at(expected, commit):
        return SourceCheckout(expected, "in place")

    # 2. where THIS version was actually generated from -- covers a short-SHA folder name and
    #    another working copy on the same machine in one step
    if _at(row.base_path, commit):
        return SourceCheckout(row.base_path, "base_path")

    # 3. a short-SHA folder in this workspace when base_path was never recorded
    try:
        for name in sorted(os.listdir(ws_root)):
            cand = os.path.join(ws_root, name)
            if len(name) >= 7 and commit.startswith(name) and _at(cand, commit):
                return SourceCheckout(cand, "short-sha folder")
    except OSError:
        pass

    # 4. put it back: one commit from the project's repository, no LLM
    from incremental.clone import ensure_commit_checkout
    from incremental.project_db import resolve_project_repo
    repo_url, default_branch, token = resolve_project_repo(project_id)
    if not repo_url:
        raise SourceUnavailable(
            "the source for %r (commit %s) is not on this machine, and project %r has no "
            "repository recorded to fetch it from. Looked in: %s%s"
            % (version_id, commit[:12], project_id, expected,
               (" and %s" % row.base_path) if row.base_path else ""))
    try:
        ensure_commit_checkout(expected, repo_url, row.branch or default_branch, commit,
                               token=token)
    except Exception as exc:                           # noqa: BLE001 - reported, with the cause
        raise SourceUnavailable(
            "the source for %r (commit %s) is not on this machine and could not be restored "
            "from the project's repository: %s" % (version_id, commit[:12], exc)) from exc
    if not _at(expected, commit):
        raise SourceUnavailable("restored %s but it is not at commit %s"
                                % (expected, commit[:12]))
    return SourceCheckout(expected, "restored")
