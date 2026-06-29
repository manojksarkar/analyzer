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
    """`<project_root>/workspaces` — the per-project workspaces root (created by the API at
    onboarding / job time; the engine reads project + version metadata from api/db/data)."""
    return os.path.join(_paths().project_root, "workspaces")


def _read_json(path: str, default: Any) -> Any:
    if not os.path.isfile(path):
        return default
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
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
    """Version lifecycle: create per-commit version dirs (capturing model/output/documents)
    and write per-version manifests. The version REGISTRY is api/db/data/versions.json (the
    API's DB) — read via incremental.project_db; this store no longer keeps its own."""

    def __init__(self, workspace: Workspace):
        self.ws = workspace

    def get(self, version_id: str) -> Optional[Dict[str, Any]]:
        return _read_json(os.path.join(self.version_dir(version_id), "manifest.json"), None)

    def exists(self, version_id: str) -> bool:
        return os.path.isdir(self.version_dir(version_id))

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

    def capture_artifacts(self, version_id: str, *, model_dir: str, output_dir: str) -> List[str]:
        """Copy the analyzer's model/ + output/ into the version, and collect every
        .docx into documents/. Returns the list of captured document filenames."""
        d = self.version_dir(version_id)
        if os.path.isdir(model_dir):
            shutil.copytree(model_dir, os.path.join(d, "model"), dirs_exist_ok=True)
        if os.path.isdir(output_dir):
            shutil.copytree(output_dir, os.path.join(d, "output"), dirs_exist_ok=True)
        docs_dir = os.path.join(d, "documents")
        os.makedirs(docs_dir, exist_ok=True)
        captured: List[str] = []
        for root, _, files in os.walk(os.path.join(d, "output")):
            for f in files:
                if f.lower().endswith(".docx"):
                    shutil.copyfile(os.path.join(root, f), os.path.join(docs_dir, f))
                    captured.append(f)
        return sorted(captured)

    def write_config(self, version_id: str, config: Dict[str, Any]) -> None:
        _write_json(os.path.join(self.version_dir(version_id), "config.json"), config)

    def write_manifest(self, version_id: str, manifest: Dict[str, Any]) -> None:
        # Per-version record in the commit dir (the filesystem source of truth). The API's
        # _complete projects this into api/db/data/versions.json for the DB/UI.
        _write_json(os.path.join(self.version_dir(version_id), "manifest.json"), manifest)


class HashStore:
    """Per-version entity-hash snapshot: {entityKey -> token-sha256} (doc 04 §4)."""

    def __init__(self, version_store: VersionStore):
        self.vs = version_store

    def _path(self, version_id: str) -> str:
        return os.path.join(self.vs.version_dir(version_id), "hashes.json")

    def write(self, version_id: str, hashes: Dict[str, str]) -> None:
        _write_json(self._path(version_id), hashes)

    def read(self, version_id: str) -> Dict[str, str]:
        return _read_json(self._path(version_id), {})


class EdgeStore:
    """Per-version slim usage index: {typeUsers, macroUsers} (doc 04 §4)."""

    def __init__(self, version_store: VersionStore):
        self.vs = version_store

    def _path(self, version_id: str) -> str:
        return os.path.join(self.vs.version_dir(version_id), "edges.json")

    def write(self, version_id: str, edges: Dict[str, Any]) -> None:
        _write_json(self._path(version_id), edges)

    def read(self, version_id: str) -> Dict[str, Any]:
        return _read_json(self._path(version_id), {"typeUsers": {}, "macroUsers": {}})


class ReuseIndex:
    """Cross-version content-addressed pointer index (doc 04 §3, D3):
    {fingerprint -> {versionId, entityKey}}. Output content is never duplicated —
    the index only records *where* a fingerprint's output already lives."""

    def __init__(self, workspace: Workspace):
        self.ws = workspace
        self._path = os.path.join(self.ws.cache_dir, "index.json")
        self._index: Dict[str, Dict[str, str]] = _read_json(self._path, {})

    def get(self, fingerprint: str) -> Optional[Dict[str, str]]:
        return self._index.get(fingerprint)

    def put(self, fingerprint: str, version_id: str, entity_key: str, *, overwrite: bool = False) -> bool:
        """Record a pointer. By default the first version that produced a fingerprint
        keeps it (a later identical fingerprint reuses, doesn't re-point). Returns
        True if a new entry was added."""
        if not overwrite and fingerprint in self._index:
            return False
        self._index[fingerprint] = {"versionId": version_id, "entityKey": entity_key}
        return True

    def save(self) -> None:
        _write_json(self._path, self._index)

    def __len__(self) -> int:
        return len(self._index)
