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

Generated **data** (model/ output/ logs/ .flowchart_cache/ and the JSON DB under api/db/data)
can be relocated *independently* of the code root via the ``ANALYZER_DATA_ROOT`` env var (or
``set_data_root``). Defaults to the project root, so production is unchanged; a test / isolated
run points it at a scratch dir so a pipeline run never touches the repo's model/output. The env
var (not just the in-process override) is what an analyzer **subprocess** inherits.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProjectPaths:
    project_root: str         # CODE root — contains engine/ + config/
    data_root: str            # DATA root — holds model/ output/ logs/ cache/ + api/db/data
    src_dir: str              # engine source dir (== <root>/engine); field name kept for compat
    config_dir: str
    config_path: str          # engine/config/config.defaults.json
    config_local_path: str    # config/config.local.json (may not exist)
    model_dir: str
    output_dir: str
    logs_dir: str
    cache_dir: str            # .flowchart_cache


_LOCK = threading.Lock()
_OVERRIDE_ROOT: Optional[str] = None
_OVERRIDE_DATA_ROOT: Optional[str] = None
_CACHED: Optional[ProjectPaths] = None


def _detect_project_root() -> str:
    """Walk upward from this file to find the analyzer root.

    The analyzer root is the directory that contains both `engine/` and `config/`.
    This file lives at <root>/engine/core/paths.py, so two parents up is the root.
    """
    here = os.path.dirname(os.path.abspath(__file__))           # .../engine/core
    engine_dir = os.path.dirname(here)                          # .../engine
    return os.path.dirname(engine_dir)                          # .../


def set_project_root(path: str) -> None:
    """Override the auto-detected CODE root. Clears the cache."""
    global _OVERRIDE_ROOT, _CACHED
    with _LOCK:
        _OVERRIDE_ROOT = os.path.abspath(path)
        _CACHED = None


def set_data_root(path: str) -> None:
    """Override the DATA root (model/output/logs/cache/api-db-data). Clears the cache. Prefer
    the ``ANALYZER_DATA_ROOT`` env var when an analyzer subprocess must inherit the override."""
    global _OVERRIDE_DATA_ROOT, _CACHED
    with _LOCK:
        _OVERRIDE_DATA_ROOT = os.path.abspath(path)
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
        # Data may live apart from the code (env var so a subprocess inherits it); default = root.
        data_root = _OVERRIDE_DATA_ROOT or os.environ.get("ANALYZER_DATA_ROOT") or root
        data_root = os.path.abspath(data_root)
        cfg_dir = os.path.join(root, "engine", "config")
        _CACHED = ProjectPaths(
            project_root=root,
            data_root=data_root,
            src_dir=os.path.join(root, "engine"),
            config_dir=cfg_dir,
            config_path=os.path.join(cfg_dir, "config.defaults.json"),
            config_local_path=os.path.join(cfg_dir, "config.local.json"),
            model_dir=os.path.join(data_root, "model"),
            output_dir=os.path.join(data_root, "output"),
            logs_dir=os.path.join(data_root, "logs"),
            cache_dir=os.path.join(data_root, ".flowchart_cache"),
        )
        return _CACHED
