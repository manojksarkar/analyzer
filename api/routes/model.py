"""
Model routes — ``/api/v1/model``

Exposes the data written into the ``model/`` directory by the document-generation
pipeline (Phases 1-4).  These endpoints let the UI (or any API client) inspect
pipeline output without re-running the pipeline.

All endpoints require authentication.  There is no project-level guard because
the model directory is a single shared workspace on the server; access control
is handled by the global auth middleware (``get_current_user``).

Endpoint summary
----------------
GET /api/v1/model                  — Status: which files exist, sizes, timestamps
GET /api/v1/model/metadata         — Raw metadata.json content
GET /api/v1/model/components       — Component list with optional layer filter
GET /api/v1/model/components/:name — Single component detail
GET /api/v1/model/units            — Unit list with component / layer filters
GET /api/v1/model/units/:key       — Single unit detail (key uses ~ instead of |)
GET /api/v1/model/functions        — Function list with filters + pagination
GET /api/v1/model/functions/:key   — Single function detail
GET /api/v1/model/globals          — Global variables with filters
GET /api/v1/model/dictionary       — Data-dictionary entries (typedefs/enums/defines)
GET /api/v1/model/summaries        — LLM hierarchy summaries
POST /api/v1/model/refresh         — Clear server-side model cache (admin only)
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from ..db.session import get_db
from ..db.in_memory import InMemoryDatabase
from ..middleware.auth import get_current_user, require_project_admin
from ..models.domain import User
from ..services.errors import not_found, bad_request
from ..services.model_reader import model_reader

router = APIRouter(tags=["model"])

# The unit key separator in URLs is `~` because `|` is not URL-safe.
# Routes decode it back to `|` before passing to model_reader.
_KEY_SEP = "|"
_URL_SEP = "~"


def _url_to_key(url_key: str) -> str:
    """Convert URL-safe ``~`` separator back to pipeline ``|`` separator."""
    return url_key.replace(_URL_SEP, _KEY_SEP)


def _key_to_url(key: str) -> str:
    """Convert pipeline ``|`` separator to URL-safe ``~`` separator."""
    return key.replace(_KEY_SEP, _URL_SEP)


def _strip_internal(d: dict) -> dict:
    """Return dict without the ``_key`` internal field."""
    return {k: v for k, v in d.items() if k != "_key"}


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@router.get("/model")
def model_status(
    current_user: User = Depends(get_current_user),
):
    """
    Return the availability status of all pipeline model files.

    ``available`` is True when at least ``metadata.json`` exists (i.e. the
    pipeline has completed Phase 1 at minimum).
    """
    return {
        "available": model_reader.is_available(),
        "model_dir": str(model_reader._model_dir),
        "project_name": model_reader.project_name(),
        "files": model_reader.file_stats(),
    }


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

@router.get("/model/metadata")
def get_metadata(
    current_user: User = Depends(get_current_user),
):
    """
    Return the raw ``model/metadata.json`` content.

    Contains: ``projectName``, ``basePath``, ``layers`` config,
    ``timestamp``, and other top-level pipeline bookkeeping values.
    """
    if not model_reader.is_available():
        raise bad_request("MODEL_NOT_AVAILABLE",
                          "Pipeline model not available — run the pipeline first.")
    return {"metadata": model_reader.metadata}


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------

@router.get("/model/components")
def list_components(
    layer: Optional[str] = Query(None, description="Filter by layer name"),
    current_user: User = Depends(get_current_user),
):
    """
    Return all components from ``model/components.json``.

    Each entry includes the component name, its layer, the list of unit names
    it contains, and an LLM-generated summary (if available).

    Query parameters
    ----------------
    layer
        When supplied, only components whose ``layer`` field matches are returned.
    """
    comps = model_reader.components
    result = []
    for name, data in comps.items():
        if not isinstance(data, dict):
            continue
        comp_layer = data.get("layer") or data.get("layerName") or ""
        if layer and comp_layer != layer:
            continue
        result.append({
            "name": name,
            "layer": comp_layer,
            "units": data.get("units") or [],
            "summary": data.get("summary") or data.get("description") or None,
            "interface_count": len(data.get("interfaces") or []),
        })
    result.sort(key=lambda c: (c["layer"], c["name"]))
    return {
        "components": result,
        "total": len(result),
        "layers": model_reader.list_layer_names(),
    }


@router.get("/model/components/{component_name}")
def get_component(
    component_name: str,
    current_user: User = Depends(get_current_user),
):
    """
    Return full detail for a single component.

    Includes all fields from ``components.json`` plus the list of units
    keyed by ``ComponentName|unit_name`` (returned with ``~`` separator for
    URL-safety) and a count of associated functions.
    """
    comp = model_reader.get_component(component_name)
    if comp is None:
        raise not_found("Component", component_name)

    # Attach unit details
    units = model_reader.list_units(component=component_name)
    unit_summaries = [
        {
            "key": _key_to_url(u["_key"]),
            "name": u.get("unitName") or u["_key"].split(_KEY_SEP)[-1],
            "path": u.get("path") or "",
            "summary": u.get("summary") or None,
        }
        for u in units
    ]

    # Function count
    fn_count = len(model_reader.list_functions(component=component_name))

    return {
        "component": {
            **_strip_internal(comp),
            "unit_details": unit_summaries,
            "function_count": fn_count,
        }
    }


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

@router.get("/model/units")
def list_units(
    component: Optional[str] = Query(None, description="Filter by component name"),
    layer: Optional[str] = Query(None, description="Filter by layer name"),
    current_user: User = Depends(get_current_user),
):
    """
    Return all units (source files) from ``model/units.json``.

    A unit corresponds to a ``.cpp``/``.h`` file pair.  The unit key uses
    ``~`` as the separator in URLs (pipeline uses ``|``).

    Query parameters
    ----------------
    component
        When supplied, only units belonging to this component are returned.
    layer
        When supplied, only units in this layer are returned.
    """
    units = model_reader.list_units(component=component, layer=layer)
    result = []
    for u in units:
        unit_key = u["_key"]
        parts = unit_key.split(_KEY_SEP, 1)
        result.append({
            "key": _key_to_url(unit_key),
            "component": u.get("componentName") or (parts[0] if parts else ""),
            "name": u.get("unitName") or (parts[1] if len(parts) > 1 else unit_key),
            "layer": u.get("layer") or u.get("layerName") or "",
            "path": u.get("path") or "",
            "summary": u.get("summary") or None,
            "global_variable_count": len(u.get("globalVariableIds") or []),
        })
    result.sort(key=lambda u: (u["layer"], u["component"], u["name"]))
    return {"units": result, "total": len(result)}


@router.get("/model/units/{unit_key}")
def get_unit(
    unit_key: str,
    current_user: User = Depends(get_current_user),
):
    """
    Return full detail for a single unit.

    The ``unit_key`` path parameter uses ``~`` as the separator between the
    component name and the unit name (e.g. ``MyComponent~my_file``).

    The response includes global variable IDs, the full unit path, and
    the LLM-generated unit summary (if available).
    """
    pipeline_key = _url_to_key(unit_key)
    unit = model_reader.get_unit(pipeline_key)
    if unit is None:
        raise not_found("Unit", unit_key)

    # Resolve global variable details
    gv_ids = unit.get("globalVariableIds") or []
    all_globals = model_reader.global_variables
    gv_details = []
    for gv_id in gv_ids:
        gv = all_globals.get(gv_id)
        if gv and isinstance(gv, dict):
            gv_details.append({
                "id": gv_id,
                "name": gv.get("qualifiedName") or gv.get("name") or gv_id,
                "type": gv.get("type") or "",
                "value": gv.get("value"),
                "visibility": gv.get("visibility") or "public",
            })

    return {
        "unit": {
            **_strip_internal(unit),
            "url_key": unit_key,
            "global_variables": gv_details,
        }
    }


# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------

@router.get("/model/functions")
def list_functions(
    component: Optional[str] = Query(None, description="Filter by component name"),
    layer: Optional[str] = Query(None, description="Filter by layer name"),
    visible_only: bool = Query(False, description="Exclude functions with isVisible=false"),
    include_hidden: bool = Query(False, description="Include functions marked hidden=true"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
    current_user: User = Depends(get_current_user),
):
    """
    Return functions from ``model/functions.json`` with optional filters and
    pagination.

    By default, hidden functions (``hidden: true``) are excluded.
    Use ``include_hidden=true`` to include them (e.g. for admin inspection).

    Query parameters
    ----------------
    component
        Filter by ``componentName`` field.
    layer
        Filter by ``layer``/``layerName`` field.
    visible_only
        When True, only functions with ``isVisible: true`` are returned.
    include_hidden
        When True, functions marked ``hidden: true`` are included.
    page / per_page
        Pagination (default 50 per page, max 500).
    """
    all_fns = model_reader.list_functions(
        component=component,
        layer=layer,
        visible_only=visible_only,
        include_hidden=include_hidden,
    )
    total = len(all_fns)
    start = (page - 1) * per_page
    page_fns = all_fns[start: start + per_page]

    return {
        "functions": [
            {
                "key": fn["_key"],
                "name": fn.get("name") or fn["_key"].split("::")[-1],
                "layer": fn.get("layer") or fn.get("layerName") or "",
                "component": fn.get("componentName") or fn.get("group") or "",
                "file": fn.get("file") or fn.get("filePath") or "",
                "description": fn.get("description") or "",
                "is_visible": bool(fn.get("isVisible", True)),
                "hidden": bool(fn.get("hidden", False)),
                "interface_id": fn.get("interfaceId") or None,
                "return_type": fn.get("returnType") or "",
                "parameter_count": len(fn.get("parameters") or []),
            }
            for fn in page_fns
        ],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": (total + per_page - 1) // per_page if per_page else 1,
        },
    }


@router.get("/model/functions/{fn_key:path}")
def get_function(
    fn_key: str,
    current_user: User = Depends(get_current_user),
):
    """
    Return full detail for a single function.

    The ``fn_key`` is the qualified function name
    (``Layer::Component::FunctionName``) or the internal ``id`` field.

    The response includes the full parameter list, return type, interface ID,
    callee IDs, and both the behaviourInputName and behaviourOutputName labels
    used in the DOCX flowchart sections.
    """
    fn = model_reader.get_function(fn_key)
    if fn is None:
        raise not_found("Function", fn_key)

    # Resolve callee function names for readability
    calls_ids = fn.get("callsIds") or []
    callees = []
    for callee_id in calls_ids:
        callee = model_reader.functions.get(callee_id) or {}
        callees.append({
            "id": callee_id,
            "name": callee.get("name") or callee_id.split("::")[-1],
            "component": callee.get("componentName") or "",
        })

    return {
        "function": {
            **_strip_internal(fn),
            "callees": callees,
        }
    }


# ---------------------------------------------------------------------------
# Global variables
# ---------------------------------------------------------------------------

@router.get("/model/globals")
def list_globals(
    component: Optional[str] = Query(None, description="Filter by component name"),
    layer: Optional[str] = Query(None, description="Filter by layer name"),
    visibility: Optional[str] = Query(None, description='"public" or "private"'),
    current_user: User = Depends(get_current_user),
):
    """
    Return global variables from ``model/globalVariables.json``.

    Query parameters
    ----------------
    component
        Filter by ``componentName`` field.
    layer
        Filter by ``layer``/``layerName`` field.
    visibility
        ``"public"`` or ``"private"`` — filter by ``visibility`` field.
    """
    if visibility and visibility.lower() not in ("public", "private"):
        raise bad_request("INVALID_PARAM", "visibility must be 'public' or 'private'")

    gvs = model_reader.list_global_variables(
        component=component,
        layer=layer,
        visibility=visibility,
    )
    result = [
        {
            "key": gv["_key"],
            "name": gv.get("qualifiedName") or gv.get("name") or gv["_key"],
            "type": gv.get("type") or "",
            "value": gv.get("value"),
            "visibility": gv.get("visibility") or "public",
            "layer": gv.get("layer") or gv.get("layerName") or "",
            "component": gv.get("componentName") or gv.get("group") or "",
            "file": gv.get("file") or gv.get("filePath") or "",
            "description": gv.get("description") or "",
        }
        for gv in gvs
    ]
    result.sort(key=lambda g: (g["component"], g["name"]))
    return {"globals": result, "total": len(result)}


# ---------------------------------------------------------------------------
# Data dictionary
# ---------------------------------------------------------------------------

@router.get("/model/dictionary")
def list_dictionary(
    kind: Optional[str] = Query(None, description='"typedef", "enum", or "define"'),
    current_user: User = Depends(get_current_user),
):
    """
    Return data-dictionary entries from ``model/dataDictionary.json``.

    These are the typedefs, enums, and preprocessor defines parsed from the
    C++ source tree by Phase 1.

    Query parameters
    ----------------
    kind
        ``"typedef"``, ``"enum"``, or ``"define"``.  Returns all when omitted.
    """
    if kind and kind.lower() not in ("typedef", "enum", "define"):
        raise bad_request("INVALID_PARAM", "kind must be 'typedef', 'enum', or 'define'")

    entries = model_reader.list_data_dictionary_entries(kind=kind)
    result = []
    for entry in entries:
        dd_kind = entry.get("kind") or ""
        item: dict = {
            "key": entry["_key"],
            "kind": dd_kind,
            "name": entry.get("name") or entry["_key"],
            "location": entry.get("location") or {},
        }
        if dd_kind == "typedef":
            item["underlying_type"] = entry.get("underlyingType") or ""
        elif dd_kind == "enum":
            item["enumerators"] = entry.get("enumerators") or []
        elif dd_kind == "define":
            item["value"] = entry.get("value") or ""
        else:
            item["text"] = entry.get("text") or ""
        result.append(item)

    result.sort(key=lambda e: (e["kind"], e["name"]))
    return {
        "entries": result,
        "total": len(result),
        "by_kind": {
            "typedef": sum(1 for e in result if e["kind"] == "typedef"),
            "enum":    sum(1 for e in result if e["kind"] == "enum"),
            "define":  sum(1 for e in result if e["kind"] == "define"),
        },
    }


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------

@router.get("/model/summaries")
def get_summaries(
    layer: Optional[str] = Query(None, description="Return only this layer's summaries"),
    component: Optional[str] = Query(None, description="Return only this component's summaries"),
    current_user: User = Depends(get_current_user),
):
    """
    Return LLM-generated hierarchy summaries from ``model/summaries.json``.

    Summaries are nested: ``{layer: {component: {unit: summary_text}}}``.

    Query parameters
    ----------------
    layer
        When supplied, only the given layer's subtree is returned.
    component
        When supplied (together with ``layer``), only the given component's
        subtree is returned.
    """
    summ = model_reader.summaries
    if not summ:
        return {
            "available": False,
            "summaries": {},
            "message": "Summaries not available — run pipeline with LLM summarization enabled.",
        }

    if layer:
        layer_data = summ.get(layer)
        if layer_data is None:
            raise not_found("Layer", layer)
        if component:
            comp_data = layer_data.get(component)
            if comp_data is None:
                raise not_found("Component", component)
            return {"available": True, "summaries": {layer: {component: comp_data}}}
        return {"available": True, "summaries": {layer: layer_data}}

    return {"available": True, "summaries": summ}


# ---------------------------------------------------------------------------
# Cache refresh
# ---------------------------------------------------------------------------

@router.post("/model/refresh")
def refresh_model_cache(
    project_id: str = Query(..., description="Project ID (used for RBAC)"),
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    """
    Clear the server-side model file cache so the next request reloads fresh
    data from disk.

    Call this after a pipeline run completes to make new model data immediately
    visible without restarting the server.

    Requires project admin role.
    """
    require_project_admin(project_id, current_user, db)
    model_reader.refresh()
    return {
        "message": "Model cache cleared.",
        "available": model_reader.is_available(),
        "files": model_reader.file_stats(),
    }
