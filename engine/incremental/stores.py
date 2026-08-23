"""D9 store interface for incremental document versioning (doc 04 §3, §10).

All version / hash / edge / reuse-index persistence goes through these classes, so
the eventual Postgres migration is a drop-in implementation of the *same methods*
(not a refactor). This is the **JSON-file implementation**; the method signatures
ARE the interface.

Scope = the incremental METADATA stores only (versions / hashes / edges / reuse
index). The analyzer's per-version model/ + output/ + documents/ artifacts stay
file-based (captured under versions/<id>/) until the DB-native pipeline rewrite.

Layout (per project) — versions are addressed BY COMMIT: each commit's git checkout
AND its generated artifacts live together under <commit[:16]>/ (there is no separate
versions/ tree). The API server (analyzer/api) owns onboarding + the per-commit clone;
the incremental engine clones a needed commit on demand.

    workspaces/<projectId>/
      cache/index.json                              # ReuseIndex  {fingerprint -> {versionId, entityKey}}
      versions.json                                 # VersionStore registry (flat)
      <commit[:16]>/                                # versionId == commit[:16]
        <repo checkout: source + .git>
        manifest.json hashes.json edges.json config.json  model/ output/ documents/
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import sys
from typing import Any, Dict, List, Optional

from core.paths import paths as _paths


def default_workspaces_root() -> str:
    """`<data_root>/workspaces` — the per-project workspaces root (created by the API at
    onboarding / job time; the engine reads project + version metadata from api/db/data).

    Anchored on the DATA root, not the code root. Workspaces are generated data — checkouts,
    per-version artifacts, the reuse index — so they belong wherever model/ output/ logs/ go.
    Anchoring them on the code root meant `ANALYZER_DATA_ROOT` did not apply to them, so a
    run isolated to a temp dir (`tools/verify_incremental.py`, any test) still created
    directories inside the repo and left them there.

    Unchanged for production: data_root defaults to the project root, so this is the same
    path unless something has deliberately relocated the data.
    """
    return os.path.join(_paths().data_root, "workspaces")


def _read_json(path: str, default: Any) -> Any:
    if not os.path.isfile(path):
        return default
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    # PID-unique: two processes writing the SAME path would otherwise share one .tmp —
    # each truncating it while the other is mid-write, so os.replace can publish a
    # half-written file. Fine while jobs ran one at a time; a real hazard at concurrency > 1.
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)  # atomic


def _rmtree_force(path: str) -> None:
    """rmtree that clears read-only bits (git pack files on Windows)."""
    if not os.path.isdir(path):
        return
    def _retry(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    kwargs = {"onexc": _retry} if sys.version_info >= (3, 12) else {"onerror": _retry}
    shutil.rmtree(path, **kwargs)


class WorkspaceNotFound(FileNotFoundError):
    pass


class Workspace:
    """Locates a project workspace and its onboarding-owned inputs (read-only here)."""

    def __init__(self, project_id: str, workspaces_root: Optional[str] = None):
        self.project_id = project_id
        self.workspaces_root = workspaces_root or default_workspaces_root()
        self.root = os.path.join(self.workspaces_root, project_id)
        if not os.path.isdir(self.root):
            raise WorkspaceNotFound(f"no workspace for project {project_id!r} at {self.root}")

    def commit_dir(self, commit: str) -> str:
        """Per-commit working+artifact dir workspaces/<pid>/<commit[:16]> — holds the git
        checkout (source + .git) AND that version's model/ output/ manifest. This is also
        the version dir (versionId == commit[:16]). The repo for a commit IS this dir."""
        return os.path.join(self.root, (commit or "")[:16])

    @property
    def cache_dir(self) -> str:
        return os.path.join(self.root, "cache")

    def datadict_path(self, data_dict_id: str) -> str:
        return os.path.join(self.root, "datadict", f"{data_dict_id}.csv")


class VersionStore:
    """The per-commit directory: where a commit's git checkout lives.

    It used to write the version's config and manifest alongside the checkout as JSON. Both
    are rows now (`versions.resolved_config`, `versions.manifest`), and a second copy on disk
    was one more thing that could disagree with them. What is left is the directory itself,
    which is not a record of anything — it is where the source code is.
    """

    def __init__(self, workspace: Workspace):
        self.ws = workspace

    def version_dir(self, version_id: str) -> str:
        """versionId == commit[:16]; the version dir IS the per-commit dir (which also
        holds the git checkout). Never wipe it — capture merges artifacts alongside src."""
        return self.ws.commit_dir(version_id)

    # --- creation ---------------------------------------------------------
    def create_dir(self, version_id: str, *, force: bool = False) -> str:
        """Ensure the per-commit dir exists. Unlike the old versions/<id> tree this dir
        also contains the git checkout, so we never rmtree it — just (re)create + return."""
        d = self.version_dir(version_id)
        os.makedirs(d, exist_ok=True)
        return d







