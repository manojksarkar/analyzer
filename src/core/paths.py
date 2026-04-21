"""Single source of truth for project file system locations.

Every entry point used to compute its own SCRIPT_DIR/PROJECT_ROOT and resolve
model/output/cache paths inline. This module replaces that boilerplate with one
cached `ProjectPaths` snapshot.

Usage:
    from core.paths import paths
    p = paths()
    cfg_path = p.config_path
    out_dir  = p.output_dir
    model    = p.model_dir

Override the project root once (typically in run.py before any other import):
    from core.paths import set_project_root
    set_project_root("/some/abs/path")
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProjectPaths:
    project_root: str
    src_dir: str
    config_dir: str
    config_path: str          # config/config.json
    config_local_path: str    # config/config.local.json (may not exist)
    model_dir: str
    output_dir: str
    logs_dir: str
    cache_dir: str            # .flowchart_cache


_LOCK = threading.Lock()
_OVERRIDE_ROOT: Optional[str] = None
_CACHED: Optional[ProjectPaths] = None


def _detect_project_root() -> str:
    """Walk upward from this file to find the analyzer root.

    The analyzer root is the directory that contains both `src/` and `config/`.
    This file lives at <root>/src/core/paths.py, so two parents up is the root.
    """
    here = os.path.dirname(os.path.abspath(__file__))           # .../src/core
    src_dir = os.path.dirname(here)                              # .../src
    return os.path.dirname(src_dir)                              # .../


def set_project_root(path: str) -> None:
    """Override the auto-detected project root. Clears the cache."""
    global _OVERRIDE_ROOT, _CACHED
    with _LOCK:
        _OVERRIDE_ROOT = os.path.abspath(path)
        _CACHED = None


def paths() -> ProjectPaths:
    """Return a cached ProjectPaths snapshot for the current run."""
    global _CACHED
    if _CACHED is not None:
        return _CACHED
    with _LOCK:
        if _CACHED is not None:
            return _CACHED
        root = _OVERRIDE_ROOT or _detect_project_root()
        src = os.path.join(root, "src")
        cfg_dir = os.path.join(root, "config")
        _CACHED = ProjectPaths(
            project_root=root,
            src_dir=src,
            config_dir=cfg_dir,
            config_path=os.path.join(cfg_dir, "config.json"),
            config_local_path=os.path.join(cfg_dir, "config.local.json"),
            model_dir=os.path.join(root, "model"),
            output_dir=os.path.join(root, "output"),
            logs_dir=os.path.join(root, "logs"),
            cache_dir=os.path.join(root, ".flowchart_cache"),
        )
        return _CACHED
