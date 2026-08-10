"""ModelReader (PG-7a) — read a version's MODEL, Postgres-first with a disk fallback.

Companion to ``output_reader.OutputReader`` (which serves Phase-3 *view* outputs). The model
(functions / units / globals / data dictionary) lives in the manifest-of-pointers tables
(``entities`` / ``entity_versions`` / ``content_blobs``), not in ``version_output_files``, so it
is read through the engine's ``incremental.model_store`` loaders — the same code the engine uses,
rather than a second implementation of the blob-join + edge-rebuild logic. Importing
``incremental.*`` from the API follows existing practice (``services/git_cli.py``,
``services/pipeline_runner.py``).

Falls back to reading ``model/*.json`` from a directory when Postgres has nothing for the version
(in-memory/json backends, or versions generated before the model moved to the DB).

Why this matters beyond storage: the document render previously read the **shared repo `model/`
dir** for repo-backed projects, i.e. whatever the *last* run left there — so an older version's
document could render against a newer version's model. Reading by ``version_id`` makes each
document render from its own version's model.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

# model dict name (as used by doc_render / model/*.json) -> model_store loader name.
# "metadata" has no DB equivalent (it is run metadata, not model entities) — disk only.
_PG_LOADERS = {
    "functions": "load_functions",
    "units": "load_units",
    "globalVariables": "load_globals",
    "dataDictionary": "load_types",
}


def _engine_on_path() -> None:
    eng = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "engine")
    if eng not in sys.path:
        sys.path.insert(0, eng)


class ModelReader:
    """Reads one version's model dicts. ``model_dir`` is the disk fallback (the dir holding
    ``functions.json`` etc.); either source may be absent."""

    def __init__(self, db: Any, version_id: Optional[str], model_dir: Optional[Path]):
        self.db = db
        self.version_id = version_id
        self.model_dir = model_dir
        self._cache: dict[str, dict] = {}
        self._pg_ok: Optional[bool] = None      # None = not probed yet

    # -- Postgres --------------------------------------------------------------
    def _pg_load(self, name: str) -> Optional[dict]:
        loader_name = _PG_LOADERS.get(name)
        engine = getattr(self.db, "_engine", None)
        if loader_name is None or engine is None or not self.version_id:
            return None
        try:
            _engine_on_path()
            from incremental import model_store          # type: ignore[import]
            with engine.connect() as cx:
                data = getattr(model_store, loader_name)(cx, self.version_id)
        except Exception:                                # no tables yet / not SQL -> disk
            return None
        if not data:
            return None
        if name == "functions":
            # The DB carries `isVisible` (entity_versions.is_visible, default True); the renderers
            # filter on `hidden`. Translate so hide/unhide works from the DB, and so a model with
            # nothing hidden behaves exactly as the on-disk model does (which has neither field).
            for fn in data.values():
                if fn.get("isVisible") is False:
                    fn["hidden"] = True
        return data

    # -- disk ------------------------------------------------------------------
    def _disk_load(self, name: str) -> dict:
        if self.model_dir is None:
            return {}
        p = Path(self.model_dir) / f"{name}.json"
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:                                # unreadable / malformed -> empty
            return {}

    # -- public ----------------------------------------------------------------
    def load(self, name: str) -> dict:
        """The model dict for `name` ("functions" | "units" | "globalVariables" |
        "dataDictionary" | "metadata"), Postgres-first then disk. Cached per reader."""
        if name in self._cache:
            return self._cache[name]
        data = self._pg_load(name)
        if data is not None:
            self._pg_ok = True
        else:
            data = self._disk_load(name)
        self._cache[name] = data
        return data

    def has_pg(self) -> bool:
        """True once any model dict has been served from Postgres."""
        if self._pg_ok is None:
            self.load("functions")
        return bool(self._pg_ok)
