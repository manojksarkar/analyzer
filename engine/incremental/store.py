"""ArtifactStore — the version-keyed artifact seam (docs/production-redesign/08).

The incremental engine's per-version artifacts (model, hashes, edges, reuse index, config,
manifest, rendered output) are addressed by the **real `ver…` id**, never by `commit[:16]`.
This module is the interface + its two implementations; the engine is wired to it in a later
step (this module is standalone and imports nothing from the engine's run path).

  ArtifactStore  — the interface (method signatures = the contract).
  FileStore      — dev / test / standalone: artifacts under workspaces/<pid>/versions/<ver…>/.
  PgStore        — production: structured model/hashes/edges/reuse in Postgres, keyed by ver…
                   (a thin adapter over model_store.py + pg_stores.PgReuseIndex).

Two things stay on disk in BOTH stores (the deliberate hybrid boundary, 08 §4): the git
checkout (Workspace.commit_dir — libclang needs real files) and small operational metadata +
rendered output (config/manifest/documents — served as files). Only the *model* diverges: the
FileStore keeps it as JSON files, the PgStore as DB rows.
"""
from __future__ import annotations

import os
import shutil
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from incremental.stores import _read_json, _write_json, default_workspaces_root


def make_store(project_id: str, workspaces_root: Optional[str] = None) -> "ArtifactStore":
    """The production store for a run: `PgStore` when a Postgres `DATABASE_URL` is configured
    (artifacts in the DB, keyed by the real ver id), else the DB-less `FileStore`."""
    if os.environ.get("DATABASE_URL"):
        from core.db import get_engine
        return PgStore(project_id, get_engine(), workspaces_root=workspaces_root)
    return FileStore(project_id, workspaces_root=workspaces_root)

# model dict key -> the file name the pipeline produces / reads
_MODEL_FILES = {
    "functions": "functions.json", "globals": "globalVariables.json",
    "datadict": "dataDictionary.json", "edges": "edges.json", "units": "units.json",
    "components": "components.json", "summaries": "summaries.json", "hashes": "hashes.json",
}
_EMPTY_EDGES = {"typeUsers": {}, "macroUsers": {}}


class ArtifactStore(ABC):
    """Version-keyed artifact storage. `proj_root` (workspaces/<pid>) is set by subclasses and
    backs the shared file-area methods (config / manifest / output) below."""

    proj_root: str

    # --- file area: operational metadata + rendered output (files, both stores) ----------
    def artifact_dir(self, version_id: str) -> str:
        """Served-artifacts dir for a version (config, manifest, output, documents)."""
        return os.path.join(self.proj_root, "versions", version_id)

    def create_version(self, version_id: str) -> str:
        d = self.artifact_dir(version_id)
        os.makedirs(d, exist_ok=True)
        return d

    def version_exists(self, version_id: str) -> bool:
        return os.path.isdir(self.artifact_dir(version_id))

    def write_config(self, version_id: str, config: Dict[str, Any]) -> None:
        _write_json(os.path.join(self.artifact_dir(version_id), "config.json"), config)

    def read_config(self, version_id: str) -> Dict[str, Any]:
        return _read_json(os.path.join(self.artifact_dir(version_id), "config.json"), {})

    def write_run_metadata(self, version_id: str, meta: Dict[str, Any]) -> None:
        """Persist the run's identity metadata — basePath / projectName / parseFingerprint. This is
        what replaces model/metadata.json (doc 07 §3): PgStore puts it on the `versions` row, the
        file store keeps it beside the version's other artifacts."""
        _write_json(os.path.join(self.artifact_dir(version_id), "metadata.json"), meta)

    def read_run_metadata(self, version_id: str) -> Dict[str, Any]:
        """The version's identity metadata, or {}. `parseFingerprint` is the clang-flag guard the
        narrowed parse compares against its baseline."""
        return _read_json(os.path.join(self.artifact_dir(version_id), "metadata.json"), {})

    def write_manifest(self, version_id: str, manifest: Dict[str, Any]) -> None:
        _write_json(os.path.join(self.artifact_dir(version_id), "manifest.json"), manifest)

    def read_manifest(self, version_id: str) -> Optional[Dict[str, Any]]:
        return _read_json(os.path.join(self.artifact_dir(version_id), "manifest.json"), None)

    def capture_output(self, version_id: str, output_dir: str) -> List[str]:
        """Copy the run's rendered output/ into the version and collect every .docx into
        documents/. Returns the captured document filenames (sorted)."""
        d = self.artifact_dir(version_id)
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

    # --- model (diverges: files vs DB) ---------------------------------------------------
    @abstractmethod
    def write_model(self, version_id: str, model_dir: str) -> None:
        """Persist the structured model (functions/globals/datadict/edges/hashes/units/
        components/summaries) for `version_id` from a generated model/ dir. Idempotent."""

    @abstractmethod
    def read_model(self, version_id: str) -> Dict[str, Any]:
        """{functions, globals, datadict, edges, units, components, summaries, hashes}."""

    @abstractmethod
    def read_hashes(self, version_id: str) -> Dict[str, str]:
        """{entityKey -> source_hash} (the classify input)."""

    @abstractmethod
    def read_functions(self, version_id: str) -> Dict[str, Any]:
        """Baseline + cross-version reuse source."""

    @abstractmethod
    def read_globals(self, version_id: str) -> Dict[str, Any]:
        ...

    @abstractmethod
    def read_edges(self, version_id: str) -> Dict[str, Any]:
        ...

    # --- reuse index (diverges: json file vs reuse_index table) --------------------------
    @abstractmethod
    def reuse_get(self, fingerprint: str) -> Optional[Dict[str, str]]:
        ...

    @abstractmethod
    def reuse_put(self, fingerprint: str, version_id: str, entity_key: str, *,
                  overwrite: bool = False) -> bool:
        ...

    @abstractmethod
    def reuse_save(self) -> None:
        ...


class FileStore(ArtifactStore):
    """DB-less implementation: everything under workspaces/<pid>/versions/<ver…>/ (model in
    model/, config/manifest/output alongside) + a shared cache/index.json reuse index."""

    def __init__(self, project_id: str, workspaces_root: Optional[str] = None):
        self.project_id = project_id
        root = workspaces_root or default_workspaces_root()
        self.proj_root = os.path.join(root, project_id)
        os.makedirs(self.proj_root, exist_ok=True)
        self._reuse_path = os.path.join(self.proj_root, "cache", "index.json")
        self._reuse: Dict[str, Dict[str, str]] = _read_json(self._reuse_path, {})

    def _model_dir(self, version_id: str) -> str:
        return os.path.join(self.artifact_dir(version_id), "model")

    def _model_file(self, version_id: str, key: str, default: Any) -> Any:
        return _read_json(os.path.join(self._model_dir(version_id), _MODEL_FILES[key]), default)

    def write_model(self, version_id: str, model_dir: str) -> None:
        if os.path.isdir(model_dir):
            shutil.copytree(model_dir, self._model_dir(version_id), dirs_exist_ok=True)

    def read_hashes(self, version_id: str) -> Dict[str, str]:
        return self._model_file(version_id, "hashes", {})

    def read_functions(self, version_id: str) -> Dict[str, Any]:
        return self._model_file(version_id, "functions", {})

    def read_globals(self, version_id: str) -> Dict[str, Any]:
        return self._model_file(version_id, "globals", {})

    def read_edges(self, version_id: str) -> Dict[str, Any]:
        return self._model_file(version_id, "edges", dict(_EMPTY_EDGES))

    def read_model(self, version_id: str) -> Dict[str, Any]:
        return {
            "functions": self.read_functions(version_id),
            "globals": self.read_globals(version_id),
            "datadict": self._model_file(version_id, "datadict", {}),
            "edges": self.read_edges(version_id),
            "units": self._model_file(version_id, "units", {}),
            "components": self._model_file(version_id, "components", {}),
            "summaries": self._model_file(version_id, "summaries", {}),
            "hashes": self.read_hashes(version_id),
        }

    def reuse_get(self, fingerprint: str) -> Optional[Dict[str, str]]:
        return self._reuse.get(fingerprint)

    def reuse_put(self, fingerprint: str, version_id: str, entity_key: str, *,
                  overwrite: bool = False) -> bool:
        if not overwrite and fingerprint in self._reuse:
            return False
        self._reuse[fingerprint] = {"versionId": version_id, "entityKey": entity_key}
        return True

    def reuse_save(self) -> None:
        _write_json(self._reuse_path, self._reuse)


class PgStore(ArtifactStore):
    """Production implementation: the structured model/hashes/edges/reuse live in Postgres
    keyed by the real `ver…` id (adapter over model_store + PgReuseIndex). Config/manifest/
    output remain files under workspaces/<pid>/versions/<ver…>/ (08 §4 hybrid boundary).

    The `versions` row is owned by the API (reserved at job start); this store never creates
    it — it only writes artifacts keyed by an existing version id.
    """

    def __init__(self, project_id: str, engine, workspaces_root: Optional[str] = None):
        from incremental.pg_stores import PgReuseIndex
        self.project_id = project_id
        self.engine = engine
        root = workspaces_root or default_workspaces_root()
        self.proj_root = os.path.join(root, project_id)
        os.makedirs(self.proj_root, exist_ok=True)
        self._reuse = PgReuseIndex(engine, project_id)

    def capture_output(self, version_id: str, output_dir: str) -> List[str]:
        """Capture rendered output to the version's disk area (base behaviour — readers/DOCX still
        use files) AND persist the text/JSON view files to Postgres (PG-5a), so the API can read
        interface tables / flowchart + unit mermaid / behaviour rows from the DB. PNG/DOCX stay as
        files. The DB write is best-effort — a hiccup must not fail a run that already has its docs."""
        captured = super().capture_output(version_id, output_dir)
        try:
            from incremental.model_store import persist_output_files
            with self.engine.begin() as cx:
                persist_output_files(cx, version_id, output_dir)
        except Exception:                                    # best-effort: disk output is intact
            pass
        return captured

    def write_run_metadata(self, version_id: str, meta: Dict[str, Any]) -> None:
        """Onto the `versions` row (base_path / project_name / parse_fingerprint) instead of a
        metadata.json file. An UPDATE of columns only — the row is still owned by the API."""
        from incremental.model_store import persist_run_metadata
        with self.engine.begin() as cx:
            persist_run_metadata(cx, version_id, meta)

    def read_run_metadata(self, version_id: str) -> Dict[str, Any]:
        from incremental.model_store import load_run_metadata
        with self.engine.connect() as cx:
            return load_run_metadata(cx, version_id)

    def write_model(self, version_id: str, model_dir: str) -> None:
        from incremental.model_store import persist_model_from_dir
        with self.engine.begin() as cx:
            persist_model_from_dir(cx, self.project_id, version_id, model_dir)

    def read_model(self, version_id: str) -> Dict[str, Any]:
        from incremental.model_store import load_model
        with self.engine.connect() as cx:
            return load_model(cx, version_id)

    def read_hashes(self, version_id: str) -> Dict[str, str]:
        from incremental.model_store import load_hashes
        with self.engine.connect() as cx:
            return load_hashes(cx, version_id)

    def read_functions(self, version_id: str) -> Dict[str, Any]:
        from incremental.model_store import load_functions
        with self.engine.connect() as cx:
            return load_functions(cx, version_id)

    def read_globals(self, version_id: str) -> Dict[str, Any]:
        from incremental.model_store import load_globals
        with self.engine.connect() as cx:
            return load_globals(cx, version_id)

    def read_edges(self, version_id: str) -> Dict[str, Any]:
        from incremental.model_store import load_edges
        with self.engine.connect() as cx:
            return load_edges(cx, version_id) or dict(_EMPTY_EDGES)

    def reuse_get(self, fingerprint: str) -> Optional[Dict[str, str]]:
        return self._reuse.get(fingerprint)

    def reuse_put(self, fingerprint: str, version_id: str, entity_key: str, *,
                  overwrite: bool = False) -> bool:
        return self._reuse.put(fingerprint, version_id, entity_key, overwrite=overwrite)

    def reuse_save(self) -> None:
        self._reuse.save()
