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
    output_dir: str           # rendered output; per run via run.py --output-root
    logs_dir: str
    cache_dir: str            # .flowchart_cache


_LOCK = threading.Lock()
_OVERRIDE_ROOT: Optional[str] = None
_OVERRIDE_DATA_ROOT: Optional[str] = None
_OVERRIDE_OUTPUT_DIR: Optional[str] = None      # B1: set per run via run.py --output-root
_OVERRIDE_MODEL_DIR: Optional[str] = None       # C11b: set per run via run.py --model-root
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


def set_output_dir(path: str) -> None:
    """Point rendered output at `path` for this process.

    In-process only — deliberately **not** an environment variable. No phase subprocess needs
    the value: `core.group_planner` reads it here and hands each phase an absolute
    ``--output-dir`` on its command line, and `docx_exporter.OUTPUT_DIR` is only a fallback
    for when no path is passed. So the two processes that do need it — ``run.py`` (via
    ``--output-root``) and the orchestrator — each set it explicitly.

    A flag also keeps the run reproducible from its own logged command line, which an
    inherited env var does not.

    Clears the cached snapshot, because `paths()` memoises on first use and a caller has
    usually read it already by the time a version dir is known.

    Scoped to output on purpose; see the note in `paths()` on why relocating the whole data
    root instead would break the shared render caches.
    """
    global _OVERRIDE_OUTPUT_DIR, _CACHED
    with _LOCK:
        _OVERRIDE_OUTPUT_DIR = os.path.abspath(path)
        _CACHED = None


def set_model_dir(path: str) -> None:
    """Point the model directory at `path` for this process.

    Same reasoning as `set_output_dir`, and the same scope: model/ only, so logs and the
    shared render caches stay put. In-process, no environment variable.
    """
    global _OVERRIDE_MODEL_DIR, _CACHED
    with _LOCK:
        _OVERRIDE_MODEL_DIR = os.path.abspath(path)
        _CACHED = None


# The path flags every phase understands. Kept here, next to the setters they drive, so a new
# one cannot be added to run.py and silently forgotten in the phases.
_PATH_FLAGS = (("--model-root", set_model_dir), ("--output-root", set_output_dir))


def apply_cli_path_overrides(argv) -> list:
    """Apply any `--model-root` / `--output-root` in `argv`, and return argv WITHOUT them.

    Each phase is its OWN process and resolves `paths()` independently, so a relocation set
    in run.py does not reach them. Output happened to be safe — `group_planner` bakes absolute
    output paths into each phase's arguments — but model_dir is read straight from `paths()`
    inside every phase, so it must be passed and applied.

    Stripping is not optional: `docx_exporter` parses POSITIONAL arguments, so a flag it did
    not consume would be mistaken for the json/docx path. Callers assign the result back:

        sys.argv = apply_cli_path_overrides(sys.argv)

    An explicit call at the top of each phase, rather than this module scanning `sys.argv` on
    import: a library that silently reads the command line is invisible when it misbehaves,
    and impossible to test without faking argv.
    """
    argv = list(argv or ())
    flags = dict(_PATH_FLAGS)
    out, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a in flags and i + 1 < len(argv):
            flags[a](argv[i + 1])
            i += 2                                  # drop the flag AND its value
            continue
        out.append(a)
        i += 1
    return out


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
            # Per run (set_model_dir, from --model-root), so a job owns its model instead of
            # sharing <root>/model with every other job. Scoped like output_dir: logs and the
            # content-addressed render caches must NOT follow it.
            model_dir=_OVERRIDE_MODEL_DIR or os.path.join(data_root, "model"),
            # Rendered output is relocated PER RUN (set_output_dir, from run.py --output-root),
            # independently of the data root, so a job writes straight into its own
            # versions/<ver…>/output instead of a shared <root>/output that a concurrent full
            # generation would _rmtree_force (doc 09, B1).
            #
            # Deliberately NOT done by pointing ANALYZER_DATA_ROOT at the version dir: that
            # also moves logs_dir and cache_dir, which would scatter the daily log across
            # version folders and — worse — give every run a private .flowchart_cache. Those
            # caches are content-addressed and meant to be shared ACROSS runs; per-version
            # would mean a 0% hit rate and re-rendering every diagram, silently undoing the
            # M-A/M-B caching work.
            output_dir=_OVERRIDE_OUTPUT_DIR or os.path.join(data_root, "output"),
            logs_dir=os.path.join(data_root, "logs"),
            cache_dir=os.path.join(data_root, ".flowchart_cache"),
        )
        return _CACHED


# ---------------------------------------------------------------------------
# The per-project workspaces, and a stored path after they moved (BACKLOG NW-5)
# ---------------------------------------------------------------------------

def local_paths_block() -> dict:
    """`paths` of config.local.json: a machine setting, read from that file only. {} without one."""
    try:
        import json
        from .config import _strip_json_comments, _strip_trailing_commas
        path = paths().config_local_path
        if not os.path.isfile(path):
            return {}
        with open(path, encoding="utf-8") as fh:
            cfg = json.loads(_strip_trailing_commas(_strip_json_comments(fh.read()))) or {}
        block = cfg.get("paths")
        return block if isinstance(block, dict) else {}
    except Exception:                                   # noqa: BLE001 - unreadable: the default
        return {}


def configured_workspaces() -> Optional[str]:
    """`paths.workspaces` of config.local.json as an absolute path (a relative one is taken from
    the installation's root), or None when it names none."""
    conf = str(local_paths_block().get("workspaces") or "").strip()
    if not conf:
        return None
    return os.path.abspath(conf if os.path.isabs(conf) else os.path.join(paths().project_root, conf))


def workspaces_root() -> str:
    """The per-project workspaces folder (checkouts, every version's output, approved copies):
    `ANALYZER_WORKSPACES_DIR`, else `paths.workspaces` in config.local.json, else
    `<data root>/workspaces`. The API's `settings.workspaces` reads the same two settings."""
    env = os.environ.get("ANALYZER_WORKSPACES_DIR", "").strip()
    if env:
        return os.path.abspath(env)
    return configured_workspaces() or os.path.join(paths().data_root, "workspaces")


def rebase_stored_path(stored: Optional[str], root: Optional[str] = None) -> Optional[str]:
    """A path the database stored, as it is on this machine now.

    As stored when it exists. Otherwise the part after its `workspaces` folder, under today's
    workspaces root -- the folder was moved, or the database came from another machine (Windows
    or POSIX separators alike) -- when that exists. Else as stored: the caller says it is missing.
    Nothing is rewritten in the database; every reader resolves through here."""
    if not stored or os.path.exists(stored):
        return stored
    import re
    root = root or workspaces_root()
    names = {"workspaces", os.path.basename(os.path.normpath(root))}
    parts = [p for p in re.split(r"[\\/]+", str(stored)) if p]
    for i in range(len(parts) - 2, -1, -1):             # the deepest `workspaces` first
        if parts[i] in names:
            candidate = os.path.join(root, *parts[i + 1:])
            if os.path.exists(candidate):
                return candidate
    return stored
