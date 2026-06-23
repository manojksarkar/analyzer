"""
ModelReader — structured access to the ``model/`` directory.

The pipeline (Phases 1-4) writes a set of JSON files under ``<project_root>/model/``
after a document-generation run:

    model/
      metadata.json          Project-level metadata (projectName, basePath, …)
      functions.json         All parsed functions, keyed by qualified name
      units.json             All units (files), keyed by component|unit key
      components.json        Component-level summaries and unit lists
      globalVariables.json   Global variables, keyed by qualified name
      dataDictionary.json    Typedefs / enums / defines, keyed by name
      summaries.json         LLM-generated hierarchy summaries
      knowledge_base.json    Call graph + type context for the flowchart engine
      clang_include_paths.json  Layer → [abs include dirs] (written by run.py)

``ModelReader`` loads each file lazily (on first access) and exposes clean,
well-typed query methods consumed by:

  - ``api/db/json_db.py``       (replaces its inline ``_load_pipeline_functions``)
  - ``api/services/document_renderer.py``  (replaces its scattered ``_load_model_file`` calls)
  - ``api/routes/model.py``     (new endpoints that expose model data to the UI)

Concurrency note
----------------
``ModelReader`` is instantiated once at startup and shared across requests.
It is **read-only** after initialisation; no locking is required.

Usage
-----
    from api.services.model_reader import ModelReader
    reader = ModelReader()           # auto-detects project root
    meta   = reader.metadata         # dict, {} if file absent
    fns    = reader.functions         # dict[qualified_name, fn_dict]
    units  = reader.units             # dict[unit_key, unit_dict]
    comps  = reader.components        # dict[component_name, comp_dict]
    globs  = reader.global_variables  # dict[qualified_name, var_dict]
    dd     = reader.data_dictionary   # dict[type_name, type_dict]
    summ   = reader.summaries         # dict (nested hierarchy)
    kb     = reader.knowledge_base    # dict (call graph, used by flowchart engine)

    # Convenience helpers
    component_names = reader.list_component_names()
    fn_list = reader.list_functions(component=None, layer=None, visible_only=False)
    unit_info = reader.get_unit(unit_key)
    fn_info = reader.get_function(fn_key_or_id)
    available = reader.is_available()   # True if at least metadata.json exists
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# File name constants (mirrors src/core/model_io.py)
# ---------------------------------------------------------------------------

_METADATA           = "metadata.json"
_FUNCTIONS          = "functions.json"
_UNITS              = "units.json"
_COMPONENTS         = "components.json"
_GLOBAL_VARIABLES   = "globalVariables.json"
_DATA_DICTIONARY    = "dataDictionary.json"
_SUMMARIES          = "summaries.json"
_KNOWLEDGE_BASE     = "knowledge_base.json"
_CLANG_INCLUDES     = "clang_include_paths.json"

_KEY_SEP = "|"   # same separator used by utils.KEY_SEP throughout the pipeline


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _find_root() -> Path:
    """Walk up from this file to find the project root (contains run.py)."""
    here = Path(__file__).resolve().parent
    for candidate in [here, here.parent, here.parent.parent, here.parent.parent.parent]:
        if (candidate / "run.py").exists():
            return candidate
    return here.parent.parent   # best-effort fallback


def _load_json(path: Path) -> Any:
    """Load JSON file; return {} on missing or corrupt file."""
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


# ---------------------------------------------------------------------------
# ModelReader
# ---------------------------------------------------------------------------

class ModelReader:
    """
    Read-only accessor for every file in the pipeline's ``model/`` directory.

    All properties are loaded lazily on first access so that importing the
    module never performs I/O.  A ``refresh()`` call reloads everything from
    disk, which is useful when the server stays up across multiple pipeline
    runs.

    Parameters
    ----------
    model_dir : str | Path | None
        Explicit path to the ``model/`` directory.  If *None* the project root
        is auto-detected and ``model/`` appended to it.
    """

    def __init__(self, model_dir: Optional[str | Path] = None) -> None:
        if model_dir is None:
            root = _find_root()
            self._model_dir = root / "model"
        else:
            self._model_dir = Path(model_dir)

        # Cache dict — populated lazily
        self._cache: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, filename: str) -> Any:
        """Return cached data, loading from disk on first access."""
        if filename not in self._cache:
            self._cache[filename] = _load_json(self._model_dir / filename)
        return self._cache[filename]

    def _get_dict(self, filename: str) -> dict:
        data = self._get(filename)
        return data if isinstance(data, dict) else {}

    # ------------------------------------------------------------------
    # Raw properties (typed)
    # ------------------------------------------------------------------

    @property
    def metadata(self) -> dict:
        """
        Project metadata written by Phase 1 (``model/metadata.json``).

        Keys include: ``projectName``, ``basePath``, ``layers``, ``groups``,
        ``timestamp``, and any ``--project-name`` override.
        """
        return self._get_dict(_METADATA)

    @property
    def functions(self) -> dict:
        """
        All functions parsed by Phase 1 and enriched by Phase 2
        (``model/functions.json``), keyed by qualified name
        (``Layer::Component::FunctionName``).

        Relevant fields per entry:
          name, file, layer, componentName, description,
          parameters, returnType, isVisible (bool), hidden (bool),
          interfaceId, behaviourInputName, behaviourOutputName,
          callsIds (list of qualified names of callees)
        """
        return self._get_dict(_FUNCTIONS)

    @property
    def units(self) -> dict:
        """
        Per-unit (per-file) metadata written by Phase 2
        (``model/units.json``), keyed by ``ComponentName|unit_name``.

        Relevant fields: path, globalVariableIds, summary, layer,
        componentName, unitName.
        """
        return self._get_dict(_UNITS)

    @property
    def components(self) -> dict:
        """
        Component-level summaries and unit lists written by Phase 2
        (``model/components.json``), keyed by component name.

        Relevant fields: layer, units (list of unit names),
        description/summary, interfaces.
        """
        return self._get_dict(_COMPONENTS)

    @property
    def global_variables(self) -> dict:
        """
        All global variables parsed by Phase 1
        (``model/globalVariables.json``), keyed by qualified name.

        Relevant fields: name, qualifiedName, type, value, visibility,
        file, layer, componentName.
        """
        return self._get_dict(_GLOBAL_VARIABLES)

    @property
    def data_dictionary(self) -> dict:
        """
        Typedefs, enums, and defines parsed by Phase 1
        (``model/dataDictionary.json``), keyed by type name.

        Relevant fields: kind (typedef|enum|define), text, location,
        enumerators (for enums), underlyingType (for typedefs), value (for defines).
        """
        return self._get_dict(_DATA_DICTIONARY)

    @property
    def summaries(self) -> dict:
        """
        LLM-generated hierarchy summaries written by Phase 2
        (``model/summaries.json``).

        Nested structure: {layer: {component: {unit: {function: summary}}}}
        Empty dict when LLM summarization is disabled or not yet run.
        """
        return self._get_dict(_SUMMARIES)

    @property
    def knowledge_base(self) -> dict:
        """
        Call graph and type context used by the flowchart engine
        (``model/knowledge_base.json``).

        Primarily consumed by ``src/flowchart/flowchart_engine.py``; exposed
        here for diagnostic / introspection endpoints.
        """
        return self._get_dict(_KNOWLEDGE_BASE)

    @property
    def clang_include_paths(self) -> dict:
        """
        Layer → [absolute include directories] written by ``run.py`` before
        Phase 1 (``model/clang_include_paths.json``).
        """
        return self._get_dict(_CLANG_INCLUDES)

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """
        Return True if the model directory exists and contains at least
        ``metadata.json`` (i.e. the pipeline has run at least once).
        """
        return (self._model_dir / _METADATA).exists()

    def available_files(self) -> list[str]:
        """
        Return the list of model file names that exist on disk.
        Useful for the ``/api/v1/model`` status endpoint.
        """
        candidates = [
            _METADATA, _FUNCTIONS, _UNITS, _COMPONENTS,
            _GLOBAL_VARIABLES, _DATA_DICTIONARY, _SUMMARIES,
            _KNOWLEDGE_BASE, _CLANG_INCLUDES,
        ]
        return [f for f in candidates if (self._model_dir / f).exists()]

    def file_stats(self) -> list[dict]:
        """
        Return size and modification time for each existing model file.
        Useful for the status endpoint so clients can detect stale data.
        """
        stats = []
        for fname in self.available_files():
            p = self._model_dir / fname
            try:
                st = p.stat()
                stats.append({
                    "file": fname,
                    "size_bytes": st.st_size,
                    "modified_at": _iso(st.st_mtime),
                })
            except OSError:
                pass
        return stats

    # ------------------------------------------------------------------
    # Derived / convenience helpers
    # ------------------------------------------------------------------

    def list_component_names(self) -> list[str]:
        """
        Return a sorted list of component names from ``components.json``.
        Falls back to deriving them from ``functions.json`` if components
        data is absent (e.g. Phase 2 not yet run).
        """
        comps = self.components
        if comps:
            return sorted(comps.keys())
        # Derive from functions
        names: set[str] = set()
        for fn_data in self.functions.values():
            if isinstance(fn_data, dict):
                c = fn_data.get("componentName") or fn_data.get("group") or ""
                if c:
                    names.add(c)
        return sorted(names)

    def list_layer_names(self) -> list[str]:
        """
        Return a sorted list of layer names from ``metadata.json``.
        Falls back to deriving from ``functions.json``.
        """
        meta = self.metadata
        layers_cfg = meta.get("layers") or {}
        if layers_cfg:
            return sorted(layers_cfg.keys())
        names: set[str] = set()
        for fn_data in self.functions.values():
            if isinstance(fn_data, dict):
                lay = fn_data.get("layer") or fn_data.get("layerName") or ""
                if lay:
                    names.add(lay)
        return sorted(names)

    def list_functions(
        self,
        *,
        component: Optional[str] = None,
        layer: Optional[str] = None,
        visible_only: bool = False,
        include_hidden: bool = False,
    ) -> list[dict]:
        """
        Return a filtered list of function dicts.

        Parameters
        ----------
        component
            If given, only return functions whose ``componentName`` matches.
        layer
            If given, only return functions whose ``layer``/``layerName`` matches.
        visible_only
            If True, exclude functions with ``isVisible == False``.
        include_hidden
            If True, include functions marked ``hidden: true`` (normally
            excluded from DOCX).  Default False.
        """
        results = []
        for fn_key, fn_data in self.functions.items():
            if not isinstance(fn_data, dict):
                continue
            if not include_hidden and fn_data.get("hidden", False):
                continue
            if visible_only and not fn_data.get("isVisible", True):
                continue
            fn_component = fn_data.get("componentName") or fn_data.get("group") or ""
            fn_layer = fn_data.get("layer") or fn_data.get("layerName") or ""
            if component and fn_component != component:
                continue
            if layer and fn_layer != layer:
                continue
            results.append({"_key": fn_key, **fn_data})
        return results

    def get_function(self, key: str) -> Optional[dict]:
        """
        Look up a single function by its qualified key
        (``Layer::Component::FunctionName``) or by the ``id`` field stored
        inside the dict.
        """
        fns = self.functions
        if key in fns:
            return {"_key": key, **fns[key]}
        # Search by id
        for fn_key, fn_data in fns.items():
            if isinstance(fn_data, dict) and fn_data.get("id") == key:
                return {"_key": fn_key, **fn_data}
        return None

    def list_units(
        self,
        *,
        component: Optional[str] = None,
        layer: Optional[str] = None,
    ) -> list[dict]:
        """
        Return a filtered list of unit dicts from ``units.json``.

        Each dict includes the unit key under ``_key`` and all original fields.
        """
        results = []
        for unit_key, unit_data in self.units.items():
            if not isinstance(unit_data, dict):
                continue
            # Component name is the first segment of the key: Component|unit_name
            parts = unit_key.split(_KEY_SEP, 1)
            unit_component = unit_data.get("componentName") or (parts[0] if parts else "")
            unit_layer = unit_data.get("layer") or unit_data.get("layerName") or ""
            if component and unit_component != component:
                continue
            if layer and unit_layer != layer:
                continue
            results.append({"_key": unit_key, **unit_data})
        return results

    def get_unit(self, unit_key: str) -> Optional[dict]:
        """Return a single unit dict by its key (``ComponentName|unit_name``)."""
        data = self.units.get(unit_key)
        if data and isinstance(data, dict):
            return {"_key": unit_key, **data}
        return None

    def get_component(self, component_name: str) -> Optional[dict]:
        """Return a single component dict by name."""
        data = self.components.get(component_name)
        if data and isinstance(data, dict):
            return {"_key": component_name, **data}
        return None

    def list_global_variables(
        self,
        *,
        component: Optional[str] = None,
        layer: Optional[str] = None,
        visibility: Optional[str] = None,
    ) -> list[dict]:
        """
        Return a filtered list of global variable dicts.

        Parameters
        ----------
        component
            Filter by ``componentName`` field.
        layer
            Filter by ``layer`` / ``layerName`` field.
        visibility
            ``"public"`` or ``"private"`` — filter by ``visibility`` field.
        """
        results = []
        for gv_key, gv_data in self.global_variables.items():
            if not isinstance(gv_data, dict):
                continue
            gv_component = gv_data.get("componentName") or gv_data.get("group") or ""
            gv_layer = gv_data.get("layer") or gv_data.get("layerName") or ""
            gv_visibility = (gv_data.get("visibility") or "public").lower()
            if component and gv_component != component:
                continue
            if layer and gv_layer != layer:
                continue
            if visibility and gv_visibility != visibility.lower():
                continue
            results.append({"_key": gv_key, **gv_data})
        return results

    def list_data_dictionary_entries(
        self,
        *,
        kind: Optional[str] = None,
    ) -> list[dict]:
        """
        Return a filtered list of data-dictionary entries.

        Parameters
        ----------
        kind
            ``"typedef"``, ``"enum"``, or ``"define"``.  If None, returns all.
        """
        results = []
        for dd_key, dd_data in self.data_dictionary.items():
            if not isinstance(dd_data, dict):
                continue
            if kind and dd_data.get("kind") != kind:
                continue
            results.append({"_key": dd_key, **dd_data})
        return results

    def project_name(self) -> str:
        """Convenience — return ``projectName`` from metadata, or empty string."""
        return self.metadata.get("projectName", "")

    def get_summary(self, layer: str, component: str, unit: Optional[str] = None) -> Optional[str]:
        """
        Retrieve a hierarchy summary generated by the LLM.

        If ``unit`` is given, returns the unit-level summary; otherwise
        returns the component-level summary.  Returns None if summaries
        were not generated or the path does not exist.
        """
        summ = self.summaries
        layer_data = summ.get(layer) or {}
        comp_data = layer_data.get(component) or {}
        if unit:
            unit_data = comp_data.get(unit)
            if isinstance(unit_data, str):
                return unit_data
            if isinstance(unit_data, dict):
                return unit_data.get("summary")
            return None
        # Component-level summary
        if isinstance(comp_data, str):
            return comp_data
        if isinstance(comp_data, dict):
            return comp_data.get("summary")
        return None

    # ------------------------------------------------------------------
    # Pipeline-function loader (used by json_db.py)
    # ------------------------------------------------------------------

    def load_pipeline_functions(
        self,
        project_id: str = "p1",
        version_id: str = "ver3",
        job_id: str = "job1",
    ) -> Optional[dict]:
        """
        Map ``model/functions.json`` entries to the ``Function`` domain model
        and return them keyed by ``job_id``.

        This is the authoritative loader used by ``JsonDatabase`` on startup.
        Returns None when ``functions.json`` doesn't exist yet.

        Parameters
        ----------
        project_id
            Project ID to assign to every Function; defaults to seed value "p1".
        version_id
            Version ID to assign to every Function; defaults to seed value "ver3".
        job_id
            Key under which to store the function list; defaults to "job1".
        """
        import uuid
        from ..models.domain import Function

        if not (self._model_dir / _FUNCTIONS).exists():
            return None

        raw = self.functions
        if not raw:
            return None

        # Prefer projectName from metadata
        meta = self.metadata
        if meta.get("projectName"):
            project_id = meta["projectName"]

        functions: list[Function] = []
        for fn_key, fn_data in raw.items():
            if not isinstance(fn_data, dict):
                continue
            fn_name = fn_data.get("name") or fn_key.split("::")[-1]
            file_path = fn_data.get("file", fn_data.get("filePath", ""))
            layer = fn_data.get("layer", fn_data.get("layerName", ""))
            group = fn_data.get("componentName", fn_data.get("group", ""))
            description = fn_data.get("description", "")
            is_visible = fn_data.get("isVisible", fn_data.get("is_visible", True))
            fn_id = fn_data.get("id", str(uuid.uuid4()))

            functions.append(Function(
                id=fn_id,
                project_id=project_id,
                version_id=version_id,
                name=fn_name,
                file_path=file_path,
                layer=layer,
                group=group,
                is_visible=bool(is_visible),
                is_new=False,
                description=description,
            ))

        return {job_id: functions}

    # ------------------------------------------------------------------
    # Cache control
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """
        Clear the in-memory cache so the next property access reloads from disk.

        Call this after a pipeline run completes to pick up new model files
        without restarting the server.
        """
        self._cache.clear()

    def __repr__(self) -> str:
        return f"ModelReader(model_dir={self._model_dir!r}, available={self.is_available()})"


# ---------------------------------------------------------------------------
# Module-level singleton — importable as a ready-to-use instance
# ---------------------------------------------------------------------------

#: Shared ``ModelReader`` instance.  Routes and services import this directly.
#: Call ``model_reader.refresh()`` to reload after a pipeline run.
model_reader = ModelReader()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso(mtime: float) -> str:
    """Convert a Unix mtime float to an ISO 8601 string (UTC)."""
    from datetime import datetime, timezone
    return datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
