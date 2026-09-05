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

import os
import threading
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

_MISSING = object()

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
# `address_taken` arrived with the poc-4 merge and belongs to exactly this category: Phase 1
# records which functions a file-scope initializer table publishes, and a LATER narrowed parse
# replays them because it may not re-parse the file holding the table. Unregistered, the write
# fell through to the file repository — so in database mode it landed in a directory nothing
# reads, the version's snapshot had no address_taken, and function-pointer table entries went
# back to reading as private on the next incremental run.
DB_BACKED_PARSE = frozenset(("entity_files", "func_keys", "override_pairs", "metadata",
                             "address_taken"))

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


class ScratchRepository(ModelRepository):
    """JSON in the run's model dir, for output that must NOT reach a version.

    Exactly one caller: the narrowed parse's partial pass. It re-parses only the changed
    translation units, so its output describes a fraction of the project and is valid only
    after `parse_merge` has folded it into the baseline. Writing that into the version's rows
    would leave a resume (`--use-model --from-phase 4`) exporting a document containing just
    the changed files.

    This is scratch, not a storage backend: no version id, nothing reads it but the merge that
    immediately follows, and `_clear_scratch_parse_files` deletes it afterwards. It is not
    selectable — there is no flag that points a real run at it.
    """

    def read(self, name, *, required=True, default=None):
        import json
        path = _scratch_path(name)
        if not os.path.isfile(path):
            if required:
                from core.model_io import ModelFileMissing
                raise ModelFileMissing(f"{path} not found. Run the upstream phase first.")
            return default
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def write(self, name, data):
        import json
        path = _scratch_path(name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)

    def missing(self, *names):
        return [n for n in names if not os.path.isfile(_scratch_path(n))]


def _scratch_path(name: str) -> str:
    # Through model_io, so there is ONE answer to "where does artifact X live as a file".
    from core.model_io import model_file_path
    return model_file_path(name)


class UnknownArtifact(KeyError):
    """A model artifact nobody registered in DB_BACKED.

    This used to fall through to a file on disk, which is worse than it sounds: the write
    succeeded, so nothing complained, and the artifact simply was not part of the version.
    `address_taken` spent the poc-4 merge in exactly that state. Raising makes a new artifact
    announce itself the moment it is first written.
    """


class DbRepository(ModelRepository):
    """The model in Postgres/SQLite for one version. The only repository there is."""

    def __init__(self, version_id: str, project_id: str):
        if not version_id:
            raise ValueError("DbRepository needs a version_id — a phase must be told WHICH "
                             "model it is working on (doc 10, D10-8)")
        self.version_id = version_id
        self.project_id = project_id
        self._pending: Dict[str, Any] = {}
        self._stored: Optional[Dict[str, Any]] = None      # whole-model read, cached
        self._exists: Optional[bool] = None                # "a model was persisted", cached
        self._aux: Dict[str, Any] = {}                     # parse/standalone reads, cached
        self._lock = threading.Lock()

    # -- reads -------------------------------------------------------------
    # One loader per artifact. Reading any single artifact used to call `load_model`, which
    # fetches ALL EIGHT — three of them expensive joins over entity_versions + entities +
    # content_blobs. A phase that wanted `units` paid for every function in the project, and
    # each of the four phases plus the orchestrator did it at least once per run. Profiling a
    # two-commit run of a TWO-function fixture counted 13 whole-model loads and 43 entity
    # joins; on a real project that is the difference the reported timings showed.
    _LOADERS = {
        "functions": "load_functions", "globalVariables": "load_globals",
        "dataDictionary": "load_types", "edges": "load_edges", "units": "load_units",
        "components": "load_components", "summaries": "load_summaries", "hashes": "load_hashes",
    }

    def _load_one(self, name: str) -> Any:
        """One artifact, fetched once and cached. `None` marks "not loaded yet"."""
        key = _PERSIST_KW[name]
        cached = self._stored.get(key, _MISSING) if self._stored is not None else _MISSING
        if cached is not _MISSING:
            return cached
        from core.db import get_engine
        from core import model_store
        loader = getattr(model_store, self._LOADERS[name])
        with get_engine().connect() as cx:
            val = loader(cx, self.version_id)
        if self._stored is None:
            self._stored = {}
        self._stored[key] = val
        return val

    def _load_stored(self) -> Dict[str, Any]:
        """The WHOLE model. Only for callers that genuinely need every part (the flush, which
        must complete a partial write). Per-artifact reads go through `_load_one`."""
        from core.db import get_engine
        from core import model_store
        with get_engine().connect() as cx:
            full = model_store.load_model(cx, self.version_id)
        self._stored = dict(full)
        return self._stored

    def _model_exists(self) -> bool:
        """Has Phase 1 persisted a model for this version at all?

        The positive signal that separates "empty" from "never written". `entity_versions` is
        the right table to ask: `persist_model` always writes rows there for a project with any
        functions or globals, and a project with neither has nothing for a later phase to do.
        Cached — every read of an empty artifact would otherwise re-query.
        """
        if self._exists is None:
            try:
                import sqlalchemy as sa
                from api.db.postgres import schema as s
                from core.db import get_engine
                with get_engine().connect() as cx:
                    n = cx.execute(
                        sa.select(sa.func.count()).select_from(s.entity_versions)
                        .where(s.entity_versions.c.version_id == self.version_id)).scalar()
                self._exists = bool(n)
            except Exception:
                self._exists = False        # cannot confirm -> behave as before (report missing)
        return self._exists

    def read(self, name, *, required=True, default=None):
        if name not in DB_BACKED:
            raise UnknownArtifact(
                f"model artifact {name!r} is not registered in DB_BACKED — add it to "
                f"DB_BACKED_MODEL, DB_BACKED_STANDALONE or DB_BACKED_PARSE in model_repo.py")
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
        val = self._load_one(name)
        if not _is_absent(val):
            return val
        # Empty is ambiguous on its own: a version with no globals and a version never persisted
        # both read as {}. Ask whether the MODEL is there before calling this one missing.
        #
        # Getting this wrong is not theoretical — treating empty as missing failed Phase 2
        # outright on any project with zero global variables, because `globalVariables` is
        # legitimately {} there. The file path never had the ambiguity: Phase 1 wrote
        # `globalVariables.json` containing {}, and an empty file is still a file.
        if self._model_exists():
            return val if val is not None else (default if default is not None else {})
        if required:
            from core.model_io import ModelFileMissing
            raise ModelFileMissing(
                f"model '{name}' is not in the database for version {self.version_id!r}. "
                f"Run the upstream phase first.")
        return default if default is not None else val

    # -- writes ------------------------------------------------------------
    def write(self, name, data):
        if name not in DB_BACKED:
            raise UnknownArtifact(
                f"model artifact {name!r} is not registered in DB_BACKED — add it to "
                f"DB_BACKED_MODEL, DB_BACKED_STANDALONE or DB_BACKED_PARSE in model_repo.py")
        if name in DB_BACKED_PARSE:
            self._write_parse(name, data)        # lands now; parse_snapshots is per-name
            self._aux[name] = data               # a later read must see this phase's write
            return
        if name in DB_BACKED_STANDALONE:
            # Lands NOW: no coupling to the rest of the model, and a phase must be able to hand
            # the plan to the next phase without also rewriting the whole model.
            self._write_standalone(name, data)
            self._aux[name] = data
            return
        with self._lock:
            self._pending[name] = data
            self._stored = None                  # a later read must see the new value
            self._exists = None                  # and re-ask whether a model is there

    # -- standalone artifacts (own table, no coupling to the rest) ----------
    _STANDALONE_IO = {
        "knowledge_base":   ("load_knowledge_base", "persist_knowledge_base"),
        "incremental_plan": ("load_incremental_plan", "persist_incremental_plan"),
        "tu_includes":      ("load_tu_includes", "persist_tu_includes"),
    }

    def _read_standalone(self, name):
        cached = self._aux.get(name, _MISSING)
        if cached is not _MISSING:
            return cached
        from core.db import get_engine
        from core import model_store
        loader = getattr(model_store, self._STANDALONE_IO[name][0])
        with get_engine().connect() as cx:
            val = loader(cx, self.version_id)
        self._aux[name] = val
        return val

    # -- parse-level artifacts (rows in parse_snapshots, keyed by name) -----
    def _read_parse(self, name):
        """Cached like the coupled model. Without this every `read_model_file(METADATA)` — and
        Phase 4 makes several — opened a fresh connection and re-queried parse_snapshots."""
        cached = self._aux.get(name, _MISSING)
        if cached is not _MISSING:
            return cached
        from core.db import get_engine
        from core import model_store
        with get_engine().connect() as cx:
            val = model_store.load_parse_snapshot_file(cx, self.version_id, f"{name}.json")
        self._aux[name] = val
        return val

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
                raise UnknownArtifact(
                    f"model artifact {n!r} is not registered in DB_BACKED")
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
            if _is_absent(self._load_one(n)):
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
        # NULs are stripped on the way in because Postgres can store none (db_util.scrub_nulls).
        # Say when that happened: the model on disk still holds the character, so a diff
        # between the JSON and the rows is explained rather than mysterious.
        from core.db_util import scrub_stats
        if scrub_stats["strings"]:
            from core.logging_setup import get_logger
            get_logger("model_repo").warning(
                "%d stored string(s) contained a NUL character, removed on write — "
                "PostgreSQL cannot represent one in text or jsonb. Usually a doc comment "
                "or an expression sliced out of a source file with a stray NUL byte.",
                scrub_stats["strings"])


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
    """The repository this run installed.

    There is no default any more. `model/*.json` was one until the file backing was removed,
    and a default is exactly what made a misconfigured run look successful: it wrote a model
    to disk, said nothing, and left the version empty in every table the API reads.
    """
    if _ACTIVE is None:
        raise RuntimeError(
            "no model repository is installed for this run. A phase needs --version-id (and "
            "--project-id) so it knows which version it is writing; the orchestrator normally "
            "passes both.")
    return _ACTIVE


def flush() -> None:
    """Flush the active repository. Safe to call when nothing is buffered."""
    repository().flush()
