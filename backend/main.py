"""FastAPI entry point for the analyzer backend.

Run with:
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

The UI (Vite dev server) is expected at http://localhost:5173. Only that
origin is whitelisted by CORS for now; widen the list when staging/prod
hosts come online.

The first batch (APIs 1–3) is intentionally read-only and side-effect free —
later batches will add job orchestration, PATCH /functions, and download
endpoints.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# Make the existing src/ package importable so we can reuse load_config()
# (handles JSONC + trailing commas in config/config.json).
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_BACKEND_DIR)
_SRC_DIR = os.path.join(_REPO_ROOT, "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from core.config import load_config  # noqa: E402

from backend.models import (  # noqa: E402
    Component,
    ComponentSummary,
    Module,
    Repository,
    TreeNode,
)


# ---------------------------------------------------------------------------
# App + middleware
# ---------------------------------------------------------------------------

app = FastAPI(title="Analyzer Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The UI currently surfaces a single hardcoded "FTL" component that wraps
# every entry in config.json :: modulesGroups. When multi-component support
# lands, this becomes a lookup keyed off a new config block.
_COMPONENT_ID = "FTL"
_COMPONENT_NAME = "FTL"
_COMPONENT_CODE = "FTL"
_COMPONENT_DESC = ""

# Extensions counted as "source files" for the per-module file count and for
# tree-leaf inclusion.
_SOURCE_EXTS = (".cpp", ".c", ".cc", ".cxx", ".h", ".hpp", ".hh", ".hxx")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _project_base_path() -> Optional[str]:
    """Return the basePath last recorded by the parser, or None if unknown.

    The file/tree views are anchored to this directory. When no run has
    happened yet (model/metadata.json missing), the tree endpoints return
    empty children rather than guessing a path.
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
    """Return config.json :: modulesGroups, or an empty dict if missing/invalid."""
    cfg = load_config(_REPO_ROOT)
    groups = cfg.get("modulesGroups") or {}
    return groups if isinstance(groups, dict) else {}


def _load_functions() -> Dict[str, dict]:
    """Load model/functions.json, returning {} when missing or malformed."""
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
    """A logical-group's directory spec may be a string or a list of strings.

    Empty/non-string entries are dropped silently so a malformed config never
    crashes the API — it just produces a thinner tree.
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
    """Flatten every logical group's dirs for the file/count walk.

    De-duplicates while preserving insertion order so unstable filesystem
    ordering doesn't change the response.
    """
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
    """Recursively count files with C/C++ extensions under any of rel_dirs."""
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
    """Group functions by their location.file (normalised to forward-slashes).

    Each value entry is {"id": <function key>, "info": <functions.json entry>}.
    """
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
    """Build a submodule node for rel_dir, recursing into subdirectories and listing files.

    Returns None if rel_dir doesn't exist on disk; an existing-but-empty
    directory still yields a node with children=None so the UI can show it.
    """
    full = os.path.join(base_path, rel_dir)
    if not os.path.isdir(full):
        return None

    try:
        entries = sorted(os.listdir(full))
    except OSError:
        entries = []

    sub_dir_names = [e for e in entries if os.path.isdir(os.path.join(full, e))]
    sub_file_names = [
        e for e in entries
        if not os.path.isdir(os.path.join(full, e)) and e.lower().endswith(_SOURCE_EXTS)
    ]

    children: List[TreeNode] = []
    for sub_dir in sub_dir_names:
        child_rel = (rel_dir + "/" + sub_dir).strip("/")
        node = _dir_node(base_path, child_rel, by_file)
        if node is not None:
            children.append(node)
    for sub_file in sub_file_names:
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
    """Build a submodule node for one logical group (an inner key of modulesGroups).

    Each directory the group lists becomes one child of this node. Missing
    directories are skipped silently.
    """
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
        module name, the logical-group level is collapsed away — the module's
        direct children are the directory nodes. This avoids the awkward
        "core -> core -> app, math" double-nesting for the common case.
      - When the module has multiple logical groups, each appears as its own
        child node — useful for the "tests" pattern where `tests_a`/`tests_b`
        partition the same physical tree.
    """
    inner_dict = inner if isinstance(inner, dict) else {}
    base = base_path or ""

    if not base or not os.path.isdir(base):
        # No project on disk yet (no run / metadata.json missing) — return
        # an empty stub so the UI can still render the module header.
        return TreeNode(id=module_key, type="submodule", name=module_key)

    logical_keys = list(inner_dict.keys())

    if len(logical_keys) == 1 and logical_keys[0] == module_key:
        # Collapse the redundant logical-group layer.
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

    children = []
    for group_name, spec in inner_dict.items():
        children.append(_logical_group_node(group_name, spec, base, by_file))
    return TreeNode(
        id=module_key,
        type="submodule",
        name=module_key,
        children=children or None,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/api/v1/repository", response_model=Repository)
async def get_repository() -> Repository:
    """Return the (currently hardcoded) repository metadata.

    Will eventually be backed by config + the parser's metadata.json once we
    decide where the canonical project path lives.
    """
    return Repository(
        name="ASPICE",
        branch="release",
        path="C:/code-path",
        lastIndexed="2 min ago",
        files=500,
    )


@app.get("/api/v1/components", response_model=List[ComponentSummary])
async def list_components() -> List[ComponentSummary]:
    """List components — only "FTL" for now.

    moduleCount is read from config.json::modulesGroups so the UI badge
    updates the moment a new module group is added to config (no restart).
    """
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
    """Return the full module breakdown for one component, including the
    directory/file/function tree built from disk + functions.json.

    Unknown component_id → 404. Case-insensitive match so "ftl"/"FTL"/"Ftl"
    all hit the same single hardcoded component.
    """
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
                files=str(files_count),
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
