"""FastAPI entry point for the analyzer backend.

Run with:
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

The UI (Vite dev server) is at http://localhost:5173 — that's the only
origin currently whitelisted by CORS. Widen the list when staging hosts
come online.

The structure mirrors the team's `main.py` (12 routes total). Routes are
filled in batch-by-batch against real CPP project data:

  Batch 1 (this commit): APIs 1-3   — repository, components, component-by-id
  Batch 2: APIs 4-6   — modules, function detail, function patch
  Batch 3: APIs 7-9   — flowchart, prepare job, prepare logs
  Batch 4: APIs 10-12 — job status, cancel, export job

Stubbed routes return HTTP 501 with a clear message so the UI surfaces
"not yet wired" rather than a confusing payload.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# Make the existing src/ package importable so we can reuse load_config()
# (which knows how to parse the JSONC + trailing commas in config/config.json).
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_BACKEND_DIR)
_SRC_DIR = os.path.join(_REPO_ROOT, "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from core.config import load_config  # noqa: E402

from backend.models import (  # noqa: E402
    Component,
    ComponentSummary,
    ExportJobRequest,
    Flowchart,
    FunctionDetailWithHidden,
    JobStartResult,
    Module,
    ModuleSummary,
    PatchFunctionBody,
    PatchFunctionResult,
    PrepLog,
    PrepareJobRequest,
    Repository,
    TreeNode,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Single hardcoded component for now. When config grows a "components" key
# this becomes a lookup keyed off that block.
_COMPONENT_ID = "FTL"
_COMPONENT_NAME = "FTL"
_COMPONENT_CODE = "FTL"
_COMPONENT_DESC = ""

# Files counted as "source files" for the per-module count and tree leaves.
_SOURCE_EXTS = (".cpp", ".c", ".cc", ".cxx", ".h", ".hpp", ".hh", ".hxx")


# ---------------------------------------------------------------------------
# In-memory stores (populated by later batches)
# ---------------------------------------------------------------------------

# Persisted patches from PATCH /functions/{fn_id} (batch 2).
_db: Dict[str, Dict[str, object]] = {
    "descriptions": {},
    "hidden_functions": {},
}

# Background-job state keyed by job_id (batches 3 & 4).
_jobs: Dict[str, Dict] = {}


# ---------------------------------------------------------------------------
# Real-data helpers (used by APIs 1-3)
# ---------------------------------------------------------------------------


def _project_base_path() -> Optional[str]:
    """Return basePath last recorded by the parser, or None if unknown.

    File/tree views are anchored to this directory. When no run has happened
    yet (model/metadata.json missing), the tree endpoints return empty
    children instead of guessing a path.
    """
    p = os.path.join(_REPO_ROOT, "model", "metadata.json")
    if not os.path.isfile(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    base = data.get("basePath") or ""
    return base or None


def _load_modules_groups() -> Dict[str, Dict[str, object]]:
    """Return config.json :: modulesGroups, or {} when missing/invalid."""
    cfg = load_config(_REPO_ROOT)
    groups = cfg.get("modulesGroups") or {}
    return groups if isinstance(groups, dict) else {}


def _load_functions() -> Dict[str, dict]:
    """Load model/functions.json — {} when missing or malformed."""
    p = os.path.join(_REPO_ROOT, "model", "functions.json")
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _normalize_dirs(spec) -> List[str]:
    """A logical-group's dirs may be a string or a list of strings.

    Empty/non-string entries are dropped so a malformed config never crashes
    the API — it just yields a thinner tree.
    """
    if not spec:
        return []
    if isinstance(spec, str):
        return [spec.replace("\\", "/").strip("/")] if spec.strip() else []
    if isinstance(spec, list):
        out: List[str] = []
        for s in spec:
            if isinstance(s, str) and s.strip():
                out.append(s.replace("\\", "/").strip("/"))
        return out
    return []


def _collect_module_dirs(inner: dict) -> List[str]:
    """Flatten every logical group's dirs into one ordered, deduped list."""
    if not isinstance(inner, dict):
        return []
    seen: set = set()
    out: List[str] = []
    for _group, spec in inner.items():
        for d in _normalize_dirs(spec):
            if d not in seen:
                seen.add(d)
                out.append(d)
    return out


def _count_source_files(base_path: str, rel_dirs: List[str]) -> int:
    """Recursively count C/C++ source files under any of rel_dirs."""
    if not base_path or not os.path.isdir(base_path):
        return 0
    total = 0
    for rel in rel_dirs:
        full = os.path.join(base_path, rel)
        if not os.path.isdir(full):
            continue
        for _root, _subdirs, files in os.walk(full):
            for f in files:
                if f.lower().endswith(_SOURCE_EXTS):
                    total += 1
    return total


def _functions_by_file(functions_data: Dict[str, dict]) -> Dict[str, List[dict]]:
    """Group {fn_id: info} by normalized location.file."""
    by_file: Dict[str, List[dict]] = {}
    for fid, info in functions_data.items():
        if not isinstance(info, dict):
            continue
        loc = info.get("location") or {}
        rel = (loc.get("file") or "").replace("\\", "/").strip("/")
        if not rel:
            continue
        by_file.setdefault(rel, []).append({"id": fid, "info": info})
    return by_file


def _fn_node(fid: str, info: dict) -> TreeNode:
    qname = info.get("qualifiedName") or fid
    return TreeNode(id=fid, type="fn", name=str(qname))


def _file_node(file_rel: str, by_file: Dict[str, List[dict]]) -> TreeNode:
    fns = by_file.get(file_rel, [])
    fns_sorted = sorted(
        fns, key=lambda x: int(((x.get("info") or {}).get("location") or {}).get("line") or 0)
    )
    fn_children = [_fn_node(fn["id"], fn["info"]) for fn in fns_sorted]
    return TreeNode(
        id=file_rel,
        type="submodule",
        name=os.path.basename(file_rel),
        children=fn_children or None,
    )


def _dir_node(base_path: str, rel_dir: str, by_file: Dict[str, List[dict]]) -> Optional[TreeNode]:
    """Build a submodule node for rel_dir, recursing into subdirectories and
    listing source files. Returns None if the dir doesn't exist on disk."""
    full = os.path.join(base_path, rel_dir)
    if not os.path.isdir(full):
        return None

    try:
        entries = sorted(os.listdir(full))
    except OSError:
        entries = []

    sub_dirs = [e for e in entries if os.path.isdir(os.path.join(full, e))]
    sub_files = [
        e for e in entries
        if not os.path.isdir(os.path.join(full, e)) and e.lower().endswith(_SOURCE_EXTS)
    ]

    children: List[TreeNode] = []
    for sub_dir in sub_dirs:
        child_rel = (rel_dir + "/" + sub_dir).strip("/")
        node = _dir_node(base_path, child_rel, by_file)
        if node is not None:
            children.append(node)
    for sub_file in sub_files:
        file_rel = (rel_dir + "/" + sub_file).strip("/")
        children.append(_file_node(file_rel, by_file))

    return TreeNode(
        id=rel_dir,
        type="submodule",
        name=os.path.basename(rel_dir) or rel_dir,
        children=children or None,
    )


def _logical_group_node(
    group_name: str,
    spec,
    base_path: str,
    by_file: Dict[str, List[dict]],
) -> TreeNode:
    """One inner-key (logical group) of modulesGroups → submodule node."""
    children: List[TreeNode] = []
    for rel in _normalize_dirs(spec):
        node = _dir_node(base_path, rel, by_file)
        if node is not None:
            children.append(node)
    return TreeNode(
        id=group_name,
        type="submodule",
        name=group_name,
        children=children or None,
    )


def _build_module_tree(
    module_key: str,
    inner: dict,
    base_path: Optional[str],
    by_file: Dict[str, List[dict]],
) -> TreeNode:
    """Build the tree for one module (one outer key of modulesGroups).

    Layout rules:
      - The tree root is always the module itself (type=submodule).
      - When the module has exactly one logical group whose name matches the
        module name, the logical-group level is collapsed — avoids the
        "core -> core -> app, math" double-nesting for the common case.
      - When the module has multiple logical groups, each appears as its own
        child — useful for the tests/tests_a/tests_b partition pattern.
    """
    inner_dict = inner if isinstance(inner, dict) else {}
    base = base_path or ""

    if not base or not os.path.isdir(base):
        return TreeNode(id=module_key, type="submodule", name=module_key)

    logical_keys = list(inner_dict.keys())

    if len(logical_keys) == 1 and logical_keys[0] == module_key:
        only_group = logical_keys[0]
        children: List[TreeNode] = []
        for rel in _normalize_dirs(inner_dict[only_group]):
            node = _dir_node(base, rel, by_file)
            if node is not None:
                children.append(node)
        return TreeNode(
            id=module_key,
            type="submodule",
            name=module_key,
            children=children or None,
        )

    children = [
        _logical_group_node(group_name, spec, base, by_file)
        for group_name, spec in inner_dict.items()
    ]
    return TreeNode(
        id=module_key,
        type="submodule",
        name=module_key,
        children=children or None,
    )


# ---------------------------------------------------------------------------
# App + middleware
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Analyzer Backend",
    description="Backend API for the analyzer document generation UI",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Routes — Batch 1 (implemented against real data)
# ---------------------------------------------------------------------------


@app.get("/api/v1/repository", response_model=Repository)
async def get_repository() -> Repository:
    """API 1 — repository metadata. Currently hardcoded; will be backed by
    config + parser metadata once the canonical project path lands."""
    return Repository(
        name="ASPICE",
        branch="release",
        path="C:/code-path",
        lastIndexed="2 min ago",
        files=500,
    )


@app.get("/api/v1/components", response_model=List[ComponentSummary])
async def list_components() -> List[ComponentSummary]:
    """API 2 — single hardcoded "FTL" wrapping every entry in
    config.json::modulesGroups. moduleCount tracks that dict live so the UI
    badge updates as soon as a new group is added (no restart needed)."""
    groups = _load_modules_groups()
    return [
        ComponentSummary(
            id=_COMPONENT_ID,
            code=_COMPONENT_CODE,
            name=_COMPONENT_NAME,
            desc=_COMPONENT_DESC,
            moduleCount=len(groups),
        )
    ]


@app.get("/api/v1/components/{component_id}", response_model=Component)
async def get_component(component_id: str) -> Component:
    """API 3 — full module breakdown for one component, including the
    directory/file/function tree built from metadata.json::basePath joined
    against model/functions.json. Case-insensitive component_id lookup.
    Unknown component_id → 404."""
    if component_id.upper() != _COMPONENT_ID.upper():
        raise HTTPException(status_code=404, detail=f"component {component_id!r} not found")

    groups = _load_modules_groups()
    base_path = _project_base_path()
    functions_data = _load_functions()
    by_file = _functions_by_file(functions_data)

    modules: List[Module] = []
    for module_key, inner in groups.items():
        inner_dict = inner if isinstance(inner, dict) else {}
        all_dirs = _collect_module_dirs(inner_dict)
        files_count = _count_source_files(base_path or "", all_dirs)
        tree = _build_module_tree(module_key, inner_dict, base_path, by_file)
        modules.append(
            Module(
                id=module_key,
                name=module_key,
                path=module_key,
                files=files_count,
                tree=tree,
            )
        )

    return Component(
        id=_COMPONENT_ID,
        code=_COMPONENT_CODE,
        name=_COMPONENT_NAME,
        desc=_COMPONENT_DESC,
        modules=modules,
    )


# ---------------------------------------------------------------------------
# Routes — Batches 2-4 (stubbed; return 501 until implemented)
# ---------------------------------------------------------------------------


def _not_implemented(api_num: int, batch_num: int) -> HTTPException:
    return HTTPException(
        status_code=501,
        detail=f"API {api_num} not yet implemented (scheduled for batch {batch_num})",
    )


@app.get("/api/v1/components/{component_id}/modules", response_model=List[ModuleSummary])
async def list_modules(component_id: str) -> List[ModuleSummary]:
    """API 4 — list modules for a component (no tree). Batch 2."""
    raise _not_implemented(4, 2)


@app.get("/api/v1/functions/{fn_id}", response_model=FunctionDetailWithHidden)
async def get_function(fn_id: str) -> FunctionDetailWithHidden:
    """API 5 — function detail (callers, callees, flowchart, description). Batch 2."""
    raise _not_implemented(5, 2)


@app.patch("/api/v1/functions/{fn_id}", response_model=PatchFunctionResult)
async def patch_function(fn_id: str, body: PatchFunctionBody) -> PatchFunctionResult:
    """API 6 — update function description / hidden flag. Batch 2."""
    raise _not_implemented(6, 2)


@app.get("/api/v1/flowcharts/{fn_id}", response_model=Flowchart)
async def get_flowchart(fn_id: str) -> Flowchart:
    """API 7 — fetch the Mermaid script for one function. Batch 3."""
    raise _not_implemented(7, 3)


@app.post("/api/v1/jobs/prepare", response_model=JobStartResult)
async def start_prepare(
    request: PrepareJobRequest, background_tasks: BackgroundTasks
) -> JobStartResult:
    """API 8 — start a `python run.py` prepare job. Batch 3."""
    raise _not_implemented(8, 3)


@app.get("/api/v1/jobs/{job_id}/prepare/logs", response_model=List[PrepLog])
async def get_prepare_logs(job_id: str) -> List[PrepLog]:
    """API 9 — tail recent log lines for a prepare job. Batch 3."""
    raise _not_implemented(9, 3)


@app.get("/api/v1/jobs/{job_id}/status")
async def get_job_status(job_id: str):
    """API 10 — job status / progress / error. Batch 4."""
    raise _not_implemented(10, 4)


@app.delete("/api/v1/jobs/{job_id}")
async def cancel_job(job_id: str):
    """API 11 — cancel a running job (full process-tree kill). Batch 4."""
    raise _not_implemented(11, 4)


@app.post("/api/v1/jobs/export", response_model=JobStartResult)
async def start_export(
    request: ExportJobRequest, background_tasks: BackgroundTasks
) -> JobStartResult:
    """API 12 — start the phase-4 docx export job. Batch 4."""
    raise _not_implemented(12, 4)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
