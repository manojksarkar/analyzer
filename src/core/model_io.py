"""Single source of truth for reading/writing model files.

Every phase used to inline its own `json.load`/`json.dump` against
`model/*.json`. That made adding or renaming a model file a 4-5 file change
and produced inconsistent error messages. This module collapses it into:

  - canonical filename constants (FUNCTIONS, GLOBALS, UNITS, …)
  - read_model_file(name)             -> dict
  - write_model_file(name, data)      -> None        (atomic= opt-in)
  - load_model(*names)                -> {name: dict}  with required + optional
  - model_file_path(name)             -> absolute path
  - model_files_present(*names)       -> list of MISSING canonical names

All paths resolve via core.paths.paths().model_dir, so model location is
controlled in one place too.

Atomic writes are opt-in: pass `atomic=True` to write_model_file. The default
matches today's behaviour (open + json.dump in place).
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict, Iterable, List, Optional

from .paths import paths

# ---------------------------------------------------------------------------
# Canonical filenames
# ---------------------------------------------------------------------------

METADATA = "metadata"
FUNCTIONS = "functions"
GLOBALS = "globalVariables"
UNITS = "units"
MODULES = "modules"
DATA_DICTIONARY = "dataDictionary"
KNOWLEDGE_BASE = "knowledge_base"
SUMMARIES = "summaries"

ALL_MODEL_NAMES = (
    METADATA,
    FUNCTIONS,
    GLOBALS,
    UNITS,
    MODULES,
    DATA_DICTIONARY,
    KNOWLEDGE_BASE,
    SUMMARIES,
)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def model_file_path(name: str) -> str:
    """Return the absolute path of a model file by canonical name (no extension)."""
    return os.path.join(paths().model_dir, f"{name}.json")


def model_files_present(*names: str) -> List[str]:
    """Return the list of canonical names whose files are MISSING on disk."""
    return [n for n in names if not os.path.isfile(model_file_path(n))]


def ensure_model_dir() -> str:
    """Make sure the model directory exists. Returns its absolute path."""
    md = paths().model_dir
    os.makedirs(md, exist_ok=True)
    return md


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

class ModelFileMissing(FileNotFoundError):
    """Raised when a required model file is missing.

    The error message names the file and the upstream phase the user should
    run to produce it.
    """


def read_model_file(name: str, *, required: bool = True, default: Any = None) -> Any:
    """Read a single model file. Raises ModelFileMissing if required and absent.

    Args:
        name:     canonical name (use the constants from this module)
        required: if False, returns `default` when the file is missing
        default:  value to return when not required and file is absent
    """
    path = model_file_path(name)
    if not os.path.isfile(path):
        if required:
            raise ModelFileMissing(
                f"{path} not found. Run the upstream phase first."
            )
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_model(
    *required: str,
    optional: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Read multiple model files at once. Returns {canonical_name: data}.

    Required names raise ModelFileMissing if absent. Optional names return
    `{}` if absent (matching the current behaviour for dataDictionary).
    """
    out: Dict[str, Any] = {}
    for name in required:
        out[name] = read_model_file(name, required=True)
    for name in (optional or ()):
        out[name] = read_model_file(name, required=False, default={})
    return out


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def write_model_file(
    name: str,
    data: Any,
    *,
    atomic: bool = False,
    indent: int = 2,
    ensure_ascii: bool = True,
) -> str:
    """Write a model file as JSON. Returns the path written.

    By default this is a plain in-place write (matches existing behaviour).
    Pass `atomic=True` to write to a tempfile in the same directory and
    rename into place — safer if a crash mid-write would corrupt the file.
    """
    ensure_model_dir()
    path = model_file_path(name)
    if not atomic:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii)
        return path

    # Atomic path: write to a sibling temp file then os.replace().
    dirpath = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=f".{name}.", suffix=".json.tmp", dir=dirpath)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path
