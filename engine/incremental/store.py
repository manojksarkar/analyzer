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
from typing import Any, Dict, Iterable, List, Optional

from incremental.stores import _read_json, _write_json, default_workspaces_root


def make_store(project_id: str, workspaces_root: Optional[str] = None) -> "ArtifactStore":
    """The production store for a run: `PgStore` when a database is configured (artifacts in
    the DB, keyed by the real ver id), else the DB-less `FileStore`.

    "Configured" means `DATABASE_URL` **or** the `db` section of `config.local.json` — see
    `core.db.is_database_configured`. Testing the env var alone made a standalone engine run
    fall back to files while the same deployment's API-driven runs used Postgres, because the
    API injects the DSN into its subprocesses."""
    from core.db import is_database_configured
    if is_database_configured():
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


def _same_dir(a: str, b: str) -> bool:
    """True when two paths name the same directory.

    `os.path.samefile` is the honest check (it follows symlinks and resolves case on
    Windows) but raises when either side does not exist yet — normal here, since the
    destination is created on demand. Fall back to a normalised comparison."""
    try:
        return os.path.exists(a) and os.path.exists(b) and os.path.samefile(a, b)
    except OSError:
        pass
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


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

    def write_report(self, version_id: str, text: str) -> bool:
        """Store the end-of-run report. True if it went to a database.

        `versions.report` has existed since the migration ("was report.txt") but nothing ever
        wrote it — the same shape as pipeline_status. The file under versions/<ver>/ stays for
        DB-less runs; this makes the report readable from any node.
        """
        return False

    def capture_output(self, version_id: str, output_dir: str) -> List[str]:
        """Copy the run's rendered output/ into the version and collect every .docx into
        documents/. Returns the captured document filenames (sorted)."""
        d = self.artifact_dir(version_id)
        dst = os.path.join(d, "output")
        # When the run rendered STRAIGHT into the version dir (--output-root, doc 09 B1)
        # src and dst are the same directory and there is nothing to copy — copytree onto
        # itself would duplicate or fail. The .docx collection below still has to run.
        if os.path.isdir(output_dir) and not _same_dir(output_dir, dst):
            shutil.copytree(output_dir, dst, dirs_exist_ok=True)
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

    def write_parse_snapshot(self, version_id: str, model_dir: str, names) -> int:
        """Store the post-Phase-1 skeleton (doc 09, C2). Returns the number of files stored.

        The file copy under `versions/<ver>/parse/` is still written by the caller; this is
        the durable, machine-independent one. 0 for a store with no database — there the
        directory IS the snapshot."""
        return 0

    def read_parse_snapshot(self, version_id: str) -> Dict[str, Any]:
        """The stored skeleton as {filename: parsed json}, or {} when this store has none."""
        return {}

    def hydrate_parse_snapshot(self, version_id: str, model_dir: str) -> int:
        """Write the stored skeleton into `model_dir`. Returns files written.

        What makes `--from-phase 2` resumable from the database on ANY machine: the skeleton
        is what Phase 2 must start from. Restoring the ENRICHED model instead would be
        silently wrong — Phase 2 skips functions that already have a description, so it would
        enrich nothing. Use `hydrate_model` to resume at Phase 3/4.
        """
        return 0

    def model_is_persisted(self, version_id: str) -> bool:
        """True when this store definitely holds `version_id`'s model.

        The precondition for deleting the model FILES (doc 09, C11c). Deliberately a positive
        check rather than trusting that write_model returned without raising: persistence is
        best-effort in several places, and "the write did not throw" is not the same as "the
        rows are there". A false here just means the files are kept, which is always safe.
        """
        return False

    def hydrate_output(self, version_id: str, out_dir: str) -> int:
        """Write this version's stored TEXT view files into `out_dir`. Files written.

        Lets a BASELINE's Phase-3 output be reconstructed on a machine that never produced it,
        which is what incremental flowchart carry-forward reads. 0 for a store with no
        database — there the files on disk are the only copy."""
        return 0

    def hydrate_model(self, version_id: str, model_dir: str) -> bool:
        """Materialize this version's STORED model into `model_dir`. True if it did.

        The read half of C11: it makes Postgres — not whatever the previous phase left on
        disk — the source the next phase consumes, so `--from-phase N` resumes from real
        stored state rather than from a directory that may be stale or half-written.

        Overwrites only the files the store actually backs (the 8 in `_DUMP_FILES`) and
        leaves the rest of the directory alone. The others are deliberately not in the DB
        yet: the narrowed-parse artifacts (entity_files / func_keys / override_pairs /
        tu_includes -> **C2**), `clang_include_paths.json` (machine-specific, deleted by
        **C3**), `knowledge_base.json` (**C4**) and `metadata.json` (an in-run intermediate).
        A wipe-then-write would destroy those, so this is an overwrite, not a rebuild.

        Default is a no-op: for `FileStore` the files ARE the store, so there is nothing to
        materialize.
        """
        return False

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

    # Batched forms (doc 09, B5a). Both hot paths resolve a whole set of fingerprints at
    # once; doing that one statement at a time cost one connection acquisition per entity
    # under PgStore. Concrete (not abstract) with correct default implementations, so an
    # existing store subclass keeps working without change.
    def reuse_get_many(self, fingerprints: Iterable[str]) -> Dict[str, Dict[str, str]]:
        out: Dict[str, Dict[str, str]] = {}
        for fp in dict.fromkeys(fingerprints):
            if not fp:
                continue
            hit = self.reuse_get(fp)
            if hit is not None:
                out[fp] = hit
        return out

    def reuse_put_many(self, entries: Iterable[tuple], *, overwrite: bool = False) -> int:
        added = 0
        for fp, version_id, entity_key in entries:
            if self.reuse_put(fp, version_id, entity_key, overwrite=overwrite):
                added += 1
        return added

    @abstractmethod
    def reuse_save(self) -> None:
        ...


class FileStore(ArtifactStore):
    """DB-less implementation: everything under workspaces/<pid>/versions/<ver…>/ (model in
    model/, config/manifest/output alongside) + a shared cache/index.json reuse index."""

    def __init__(self, project_id: str, workspaces_root: Optional[str] = None):
        self.project_id = project_id
        root = workspaces_root or default_workspaces_root()
        # NOT created here. Constructing a store must not have a filesystem side effect: a
        # DB-less probe, or a run.py that turns out to have nothing to persist, would leave an
        # empty workspaces/<pid>/ behind for a project that may not exist. Every write path
        # already creates what it needs (`_write_json` makes its parent, `create_version`
        # makes the version dir).
        self.proj_root = os.path.join(root, project_id)
        self._reuse_path = os.path.join(self.proj_root, "cache", "index.json")
        self._reuse: Dict[str, Dict[str, str]] = _read_json(self._reuse_path, {})

    def _model_dir(self, version_id: str) -> str:
        return os.path.join(self.artifact_dir(version_id), "model")

    def _model_file(self, version_id: str, key: str, default: Any) -> Any:
        return _read_json(os.path.join(self._model_dir(version_id), _MODEL_FILES[key]), default)

    def write_model(self, version_id: str, model_dir: str) -> None:
        # Since C11b a run's model dir IS versions/<ver>/model, i.e. exactly where this would
        # copy it — copytree onto itself raises WinError 32 (files open by this process) and
        # would otherwise duplicate the tree. Nothing to do when they are the same directory:
        # the model is already in place. Mirrors the same guard in capture_output.
        if os.path.isdir(model_dir) and not _same_dir(model_dir, self._model_dir(version_id)):
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

    def reuse_get_many(self, fingerprints: Iterable[str]) -> Dict[str, Dict[str, str]]:
        # The whole index is already an in-memory dict here, so batching is free.
        return {fp: self._reuse[fp] for fp in dict.fromkeys(fingerprints)
                if fp and fp in self._reuse}

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
        self.proj_root = os.path.join(root, project_id)   # see FileStore: created on demand
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

    def write_manifest(self, version_id: str, manifest: Dict[str, Any]) -> None:
        """Also put the run's accounting on the `versions` row (doc 09, C1).

        The file is still written by ``super()`` — additive on purpose. The migration's own
        rule is *never delete a writer before its readers are repointed*; deleting the
        commit-dir dual-write ahead of its readers is exactly what would have silently broken
        flowchart reuse during the cutover. The file goes once the API reads the columns.
        """
        super().write_manifest(version_id, manifest)
        try:
            from incremental.model_store import persist_run_outcome
            with self.engine.begin() as cx:
                persist_run_outcome(cx, version_id, manifest)
        except Exception:                       # accounting must not fail a completed run
            pass

    def read_run_outcome(self, version_id: str) -> Dict[str, Any]:
        """The run's accounting from the version row, in manifest.json's shape."""
        from incremental.model_store import load_run_outcome
        with self.engine.connect() as cx:
            return load_run_outcome(cx, version_id)

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

    def write_parse_snapshot(self, version_id: str, model_dir: str, names) -> int:
        from incremental.model_store import persist_parse_snapshot
        with self.engine.begin() as cx:
            return persist_parse_snapshot(cx, version_id, model_dir, names)

    def read_parse_snapshot(self, version_id: str) -> Dict[str, Any]:
        from incremental.model_store import load_parse_snapshot
        with self.engine.connect() as cx:
            return load_parse_snapshot(cx, version_id)

    def write_report(self, version_id: str, text: str) -> bool:
        from sqlalchemy import update
        from api.db.postgres import schema as _s
        with self.engine.begin() as cx:
            cx.execute(update(_s.versions).where(_s.versions.c.id == version_id)
                       .values(report=text))
        return True

    def model_is_persisted(self, version_id: str) -> bool:
        from sqlalchemy import func, select
        from api.db.postgres import schema as _s
        try:
            with self.engine.connect() as cx:
                n = cx.execute(select(func.count()).select_from(_s.entity_versions)
                               .where(_s.entity_versions.c.version_id == version_id)).scalar()
            return bool(n)
        except Exception:
            return False                 # cannot confirm -> keep the files

    def hydrate_output(self, version_id: str, out_dir: str) -> int:
        from incremental.model_store import dump_output_files_to_dir
        with self.engine.connect() as cx:
            return dump_output_files_to_dir(cx, version_id, out_dir)

    def hydrate_parse_snapshot(self, version_id: str, model_dir: str) -> int:
        from incremental.model_store import dump_parse_snapshot_to_dir
        with self.engine.connect() as cx:
            return dump_parse_snapshot_to_dir(cx, version_id, model_dir)

    def hydrate_model(self, version_id: str, model_dir: str) -> bool:
        from incremental.model_store import dump_model_to_dir
        with self.engine.connect() as cx:
            dump_model_to_dir(cx, version_id, model_dir)
        return True

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

    def reuse_get_many(self, fingerprints: Iterable[str]) -> Dict[str, Dict[str, str]]:
        return self._reuse.get_many(fingerprints)

    def reuse_put(self, fingerprint: str, version_id: str, entity_key: str, *,
                  overwrite: bool = False) -> bool:
        return self._reuse.put(fingerprint, version_id, entity_key, overwrite=overwrite)

    def reuse_put_many(self, entries: Iterable[tuple], *, overwrite: bool = False) -> int:
        return self._reuse.put_many(entries, overwrite=overwrite)

    def reuse_save(self) -> None:
        self._reuse.save()
