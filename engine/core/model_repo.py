"""Where the model lives — the seam `model_io` reads and writes through (doc 10, step 2).

`core/model_io.py` is the single gateway 51 of the 76 model access sites already use. This
module gives it two interchangeable backings:

    FileRepository   model/*.json          today's behaviour, unchanged
    DbRepository     Postgres or SQLite    keyed by version_id

Function signatures above the seam do not change: a phase keeps calling
`read_model_file(FUNCTIONS)` and gets the same dict. That is what lets the storage move without
touching the pipeline.

**Why writes are buffered.** The database is not a per-file store. `persist_functions` takes
`hashes` in the same call and writes `model_edges` from the same data, so "write functions.json"
alone is not a valid database operation — the pieces have to land together, in order, in one
transaction. So `DbRepository.write()` records into a pending map and `flush()` persists the
whole model once. That is also the transaction shape doc 10 H2 asks for: a phase that dies
mid-write leaves the previous state, not a half-updated model.

`flush()` is called at the phase boundary, which is where the C11a `on_phase_done` hook already
fires — the same seam, reused rather than a second one invented.

**Reads see this phase's own writes.** Phase 2 writes functions and then reads them back, so
`read()` checks the pending map before the database. Without that overlay a phase would read
its own stale input.
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

# The COUPLED model: `persist_model` writes these together (functions carries hashes and derives
# model_edges), so a write to any of them is buffered and the whole set flushed as one transaction.
DB_BACKED_MODEL = frozenset((
    "functions", "globalVariables", "dataDictionary", "edges",
    "units", "components", "summaries", "hashes",
))

# Whole-object artifacts with their OWN table and no coupling to anything else (doc 10, step 6),
# so a write lands immediately instead of waiting for the flush. Each is a hand-off that one
# phase writes and another reads — a phase must be able to pass the plan on without also
# rewriting the entire model.
DB_BACKED_STANDALONE = frozenset(("knowledge_base", "incremental_plan", "tu_includes"))

# Parse-level artifacts: whole-object, per-version, produced by Phase 1 and consumed by a LATER
# run's narrowed parse rather than by this one (doc 10, step 11). They land in `parse_snapshots`,
# which already has exactly this shape and is already where `snapshot_parse_model` copied them —
# writing there directly makes Phase 1's output the snapshot instead of a file the snapshot has
# to go back and read.
#
# `metadata` is here too. Its DURABLE fields (basePath / projectName / parseFingerprint) are
# `versions` columns written by `persist_run_metadata`; this row is the in-run channel, which is
# what Phase 4 and the flowchart engine actually read.
DB_BACKED_PARSE = frozenset(("entity_files", "func_keys", "override_pairs", "metadata"))

DB_BACKED = DB_BACKED_MODEL | DB_BACKED_STANDALONE | DB_BACKED_PARSE

# Still a file, deliberately: `clang_include_paths` is per-run, machine-specific scratch —
# absolute include directories under THIS machine's checkout. Storing it would hand the next node
# paths that do not exist there, which is worse than not storing it at all.

# canonical model name -> the keyword `model_store.persist_model` expects
_PERSIST_KW = {
    "functions": "functions", "globalVariables": "globals", "dataDictionary": "datadict",
    "edges": "edges", "hashes": "hashes", "units": "units", "components": "components",
    "summaries": "summaries",
}


def _is_absent(val: Any) -> bool:
    """Whether a loaded value should count as "not there", matching a missing FILE.

    Not just falsiness. The loaders return a SHAPED empty — `load_summaries` always yields
    ``{"project": "", "components": {}, "files": {}}`` — so a version with no summaries reads as
    a truthy dict, while the file path would have returned the caller's default. A skeleton whose
    every value is empty is the same thing as no file, and treating it otherwise makes
    `if not summaries:` behave differently in the two modes.
    """
    if not val:
        return True
    if isinstance(val, dict):
        return all(not v for v in val.values())
    return False


class ModelRepository(ABC):
    """Read/write the model by canonical name."""

    @abstractmethod
    def read(self, name: str, *, required: bool = True, default: Any = None) -> Any: ...

    @abstractmethod
    def write(self, name: str, data: Any) -> None: ...

    @abstractmethod
    def missing(self, *names: str) -> List[str]:
        """The subset of `names` that is NOT available. Drives 'can this phase be skipped?'."""

    def flush(self) -> None:
        """Persist anything buffered. No-op where a write already landed."""


class FileRepository(ModelRepository):
    """model/*.json — today's behaviour, delegating to the file helpers in `model_io`."""

    def read(self, name, *, required=True, default=None):
        from core.model_io import _read_file
        return _read_file(name, required=required, default=default)

    def write(self, name, data):
        from core.model_io import _write_file
        _write_file(name, data)

    def missing(self, *names):
        from core.model_io import _missing_files
        return _missing_files(*names)


class DbRepository(ModelRepository):
    """The model in Postgres/SQLite for one version.

    Anything the database does not back yet is delegated to `fallback` (a FileRepository), so
    this can be switched on before every last artifact has moved.
    """

    def __init__(self, version_id: str, project_id: str, *, fallback: ModelRepository = None):
        if not version_id:
            raise ValueError("DbRepository needs a version_id — a phase must be told WHICH "
                             "model it is working on (doc 10, D10-8)")
        self.version_id = version_id
        self.project_id = project_id
        self._fallback = fallback or FileRepository()
        self._pending: Dict[str, Any] = {}
        self._stored: Optional[Dict[str, Any]] = None      # whole-model read, cached
        self._lock = threading.Lock()

    # -- reads -------------------------------------------------------------
    def _load_stored(self) -> Dict[str, Any]:
        """The stored model, read once. Keyed by `model_store.load_model`'s names."""
        if self._stored is None:
            from core.db import get_engine
            from core import model_store
            with get_engine().connect() as cx:
                self._stored = model_store.load_model(cx, self.version_id)
        return self._stored

    def read(self, name, *, required=True, default=None):
        if name not in DB_BACKED:
            return self._fallback.read(name, required=required, default=default)
        with self._lock:
            if name in self._pending:            # this phase's own write wins
                return self._pending[name]
        if name in DB_BACKED_STANDALONE or name in DB_BACKED_PARSE:
            val = (self._read_parse(name) if name in DB_BACKED_PARSE
                   else self._read_standalone(name))
            if not _is_absent(val):
                return val
            if required:
                from core.model_io import ModelFileMissing
                raise ModelFileMissing(
                    f"model '{name}' is not in the database for version {self.version_id!r}.")
            return default if default is not None else val
        stored = self._load_stored()
        key = _PERSIST_KW[name]
        val = stored.get(key)
        if not _is_absent(val):
            return val
        # Empty is ambiguous: a version with no summaries and a version never persisted both
        # look like {}. Treat it as absent so `required` behaves as it does for a missing file.
        if required:
            from core.model_io import ModelFileMissing
            raise ModelFileMissing(
                f"model '{name}' is not in the database for version {self.version_id!r}. "
                f"Run the upstream phase first.")
        return default if default is not None else val

    # -- writes ------------------------------------------------------------
    def write(self, name, data):
        if name not in DB_BACKED:
            self._fallback.write(name, data)
            return
        if name in DB_BACKED_PARSE:
            self._write_parse(name, data)        # lands now; parse_snapshots is per-name
            return
        if name in DB_BACKED_STANDALONE:
            # Lands NOW: no coupling to the rest of the model, and a phase must be able to hand
            # the plan to the next phase without also rewriting the whole model.
            self._write_standalone(name, data)
            return
        with self._lock:
            self._pending[name] = data
            self._stored = None                  # a later read must see the new value

    # -- standalone artifacts (own table, no coupling to the rest) ----------
    _STANDALONE_IO = {
        "knowledge_base":   ("load_knowledge_base", "persist_knowledge_base"),
        "incremental_plan": ("load_incremental_plan", "persist_incremental_plan"),
        "tu_includes":      ("load_tu_includes", "persist_tu_includes"),
    }

    def _read_standalone(self, name):
        from core.db import get_engine
        from core import model_store
        loader = getattr(model_store, self._STANDALONE_IO[name][0])
        with get_engine().connect() as cx:
            return loader(cx, self.version_id)

    # -- parse-level artifacts (rows in parse_snapshots, keyed by name) -----
    def _read_parse(self, name):
        from core.db import get_engine
        from core import model_store
        with get_engine().connect() as cx:
            return model_store.load_parse_snapshot_file(cx, self.version_id, f"{name}.json")

    def _write_parse(self, name, data):
        from core.db import get_engine
        from core import model_store
        with get_engine().begin() as cx:
            model_store.persist_parse_snapshot_file(cx, self.version_id, f"{name}.json", data)

    def _write_standalone(self, name, data):
        from core.db import get_engine
        from core import model_store
        writer = getattr(model_store, self._STANDALONE_IO[name][1])
        with get_engine().begin() as cx:
            writer(cx, self.version_id, data)

    def missing(self, *names):
        out: List[str] = []
        for n in names:
            if n not in DB_BACKED:
                out += self._fallback.missing(n)
                continue
            with self._lock:
                if n in self._pending:
                    continue
            if n in DB_BACKED_PARSE:
                if _is_absent(self._read_parse(n)):
                    out.append(n)
                continue
            if n in DB_BACKED_STANDALONE:
                if _is_absent(self._read_standalone(n)):
                    out.append(n)
                continue
            if _is_absent(self._load_stored().get(_PERSIST_KW[n])):
                out.append(n)
        return out

    # -- flush -------------------------------------------------------------
    def flush(self) -> None:
        """Persist every buffered piece in ONE transaction.

        `persist_model` needs functions/globals/datadict/edges together, so a partial phase
        (Phase 2 rewrites functions but not units) is completed from what is already stored —
        otherwise persisting would delete the rows it did not mention.
        """
        with self._lock:
            # Only the COUPLED set: standalone artifacts already landed on write.
            pending = {k: v for k, v in self._pending.items() if k in DB_BACKED_MODEL}
            self._pending = {}
        if not pending:
            return
        from core.db import get_engine
        from core import model_store
        stored = self._load_stored() if any(
            n not in pending for n in ("functions", "globalVariables", "dataDictionary", "edges")
        ) else {}
        def _pick(name):
            return pending.get(name, stored.get(_PERSIST_KW[name]) or {})
        with get_engine().begin() as cx:          # one transaction: all-or-nothing (H2)
            # persist_model is NOT idempotent on its own — re-persisting a version collides on
            # entity_versions' (version_id, entity_id). `persist_model_from_dir` clears first;
            # doing the same here is what makes a re-run, or a second phase writing the same
            # version, work. clear_version touches ONLY the 5 model tables, so the parse
            # snapshot and the stored view outputs are untouched.
            model_store.clear_version(cx, self.version_id)
            model_store.persist_model(
                cx, self.project_id, self.version_id,
                functions=_pick("functions"), globals=_pick("globalVariables"),
                datadict=_pick("dataDictionary"), edges=_pick("edges"),
                hashes=_pick("hashes"), units=_pick("units"),
                components=_pick("components"), summaries=_pick("summaries"))
        self._stored = None


# ---------------------------------------------------------------------------
# Active repository (process-wide, like paths())
# ---------------------------------------------------------------------------
_LOCK = threading.Lock()
_ACTIVE: Optional[ModelRepository] = None


def set_repository(repo: Optional[ModelRepository]) -> None:
    """Install the repository for this process. None restores the file default."""
    global _ACTIVE
    with _LOCK:
        _ACTIVE = repo


def repository() -> ModelRepository:
    """The active repository — `FileRepository` unless something installed otherwise.

    Defaulting to files is what makes this step behaviour-neutral: nothing changes until a
    caller opts in.
    """
    global _ACTIVE
    if _ACTIVE is None:
        with _LOCK:
            if _ACTIVE is None:
                _ACTIVE = FileRepository()
    return _ACTIVE


def flush() -> None:
    """Flush the active repository. Safe to call when nothing is buffered."""
    repository().flush()
