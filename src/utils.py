"""Shared helpers."""
import contextlib
import os
import re
import sys
import time
from datetime import datetime, timezone

# Config loading lives in core.config (these are re-exports for backward
# compatibility with existing call sites that still `from utils import ...`).
from core.config import load_config, load_llm_config  # noqa: E402,F401

# Separator for unique keys (function IDs, global IDs, unit keys). Avoid "/" for path confusion.
KEY_SEP = "|"


def _ts() -> str:
    """Current timestamp [HH:MM:SS.mmm]."""
    return datetime.now(timezone.utc).strftime("%H:%M:%S.") + f"{int(time.time() % 1 * 1000):03d}"


def log(msg: str, component: str = None, *, err: bool = False):
    """Unified log from anywhere. component prefixes the message.

    Routes through the central logging system (stderr + daily log file)
    so every legacy caller automatically gets file capture.
    """
    try:
        from core.logging_setup import get_logger
        logger = get_logger(component or "run")
        if err:
            logger.error(msg)
        else:
            logger.info(msg)
        return
    except Exception:
        # Fallback if core.logging_setup isn't importable yet (very early bootstrap)
        stream = sys.stderr if err else sys.stdout
        prefix = f"[{_ts()}] "
        text = f"{prefix}{component}: {msg}" if component else f"{prefix}{msg}"
        print(text, file=stream, flush=True)


@contextlib.contextmanager
def timed(component: str):
    """Context manager: log elapsed time on exit. Use: with timed('flowcharts'): ..."""
    t0 = time.perf_counter()
    yield
    elapsed = time.perf_counter() - t0
    log(f"{elapsed:.2f}s", component=component)


def mmdc_path(project_root: str) -> str:
    """Path to mermaid-cli mmdc (local node_modules or system)."""
    ext = ".cmd" if sys.platform == "win32" else ""
    local = os.path.join(project_root, "node_modules", ".bin", "mmdc" + ext)
    return local if os.path.isfile(local) else "mmdc"


def safe_filename(s: str) -> str:
    """Filesystem-safe name (| and other unsafe chars -> _).
    Includes , & ; to avoid Windows cmd parsing issues when paths are passed to mmdc.
    """
    return re.sub(r'[<>:"/\\|?*,&;]', "_", s or "")



_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
_CONFIG_CACHE = load_config(_PROJECT_ROOT)

# Module mapping cache (initialized at import).
_MODULE_OVERRIDES: dict = {}


def init_module_mapping(config: dict) -> None:
    """Initialize module folder mapping used by get_module_name/make_*_key helpers.

    This project no longer uses config.selectedGroup to affect module mapping.
    Module mapping is derived from:
    - top-level config.modules (if present), else
    - merged union of all config.modulesGroups entries.
    """
    global _MODULE_OVERRIDES
    cfg = config or {}
    _MODULE_OVERRIDES = cfg.get("modules") or {}
    if _MODULE_OVERRIDES:
        return
    groups = cfg.get("modulesGroups") or {}
    if not isinstance(groups, dict) or not groups:
        _MODULE_OVERRIDES = {}
        return
    merged: dict = {}
    for _, grp in groups.items():
        if not isinstance(grp, dict):
            continue
        for module, paths in grp.items():
            if not paths:
                continue
            if isinstance(paths, str):
                paths_list = [paths]
            else:
                paths_list = list(paths) if isinstance(paths, list) else []
            if module not in merged:
                merged[module] = paths_list if len(paths_list) != 1 else paths_list[0]
            else:
                existing = merged.get(module)
                if isinstance(existing, str):
                    existing_list = [existing]
                else:
                    existing_list = list(existing) if isinstance(existing, list) else []
                for p in paths_list:
                    if p and p not in existing_list:
                        existing_list.append(p)
                merged[module] = existing_list if len(existing_list) != 1 else existing_list[0]
    _MODULE_OVERRIDES = merged


# Default initialization from on-disk config.
init_module_mapping(_CONFIG_CACHE)


def _resolve_module_from_rel(rel_file: str) -> str:
    """Resolve module name for a path relative to the project base.

    Behaviour:
    - If config.modules is provided, only those mappings are used; unmatched
      paths resolve to "unknown".
    - If config.modules is not provided, fallback is first path segment
      (original behaviour).
    """
    path = rel_file.replace("\\", "/") if rel_file else ""
    if not path:
        return "unknown"

    # Configurable overrides: "modules": { "ModuleName": "folder" | ["folder1", "dir/subdir"] }
    if _MODULE_OVERRIDES:
        for module, paths in _MODULE_OVERRIDES.items():
            if not paths:
                continue
            if isinstance(paths, str):
                paths = [paths]
            for folder in paths:
                p = (folder or "").replace("\\", "/").lstrip("./").lower()
                if not p:
                    continue
                # Folder-based match: module is the folder and its subfolders.
                path_lower = path.lower()
                if path_lower == p or path_lower.startswith(p + "/"):
                    return module
        return "unknown"

    parts = path.split("/")
    return parts[0] if parts and parts[0] else "unknown"


def _path_to_module_unit(rel_file: str) -> tuple:
    """Return (module, unitname) from rel_file. Unitname = filename without extension (no subpath)."""
    path = rel_file.replace("\\", "/") if rel_file else ""
    if not path:
        return "unknown", ""
    module = _resolve_module_from_rel(path)
    parts = path.split("/")
    unitname = os.path.splitext(parts[-1])[0] if parts else ""
    return module, unitname


def make_unit_key(rel_file: str) -> str:
    """Unit unique key: module|unitname (assumes single-name units, no path in key)."""
    module, unitname = _path_to_module_unit(rel_file)
    return f"{module}{KEY_SEP}{unitname}"


def path_from_unit_rel(rel_file: str) -> str:
    """Path without extension (for storing in unit info)."""
    path = (rel_file or "").replace("\\", "/")
    return os.path.splitext(path)[0]


def make_global_key(rel_file: str, full_name: str) -> str:
    """Unique key: module|unitname|qualifiedName."""
    module, unit = _path_to_module_unit(rel_file)
    return f"{module}{KEY_SEP}{unit}{KEY_SEP}{full_name}"


def make_function_key(module: str, rel_file: str, full_name: str, parameters: list) -> str:
    """Unique key: module|unitname|qualifiedName|paramTypes."""
    path = rel_file.replace("\\", "/") if rel_file else ""
    parts = path.split("/")
    if not module and parts:
        module = parts[0]
    _, unit = _path_to_module_unit(rel_file)
    param_types = ",".join((p.get("type") or "").strip() for p in (parameters or []))
    return f"{module}{KEY_SEP}{unit}{KEY_SEP}{full_name}{KEY_SEP}{param_types}"


def short_name(full_name: str) -> str:
    """Last segment after :: (e.g. MyClass::foo -> foo)."""
    return ((full_name or "").split("::")[-1]).strip()


def path_is_under(base_path: str, candidate_path: str) -> bool:
    """True if candidate_path resolves to the project root or a path inside it.

    Uses ``normcase`` so different spellings/casing on Windows match. Uses
    ``relpath`` (not string prefix) so ``C:\\foo`` does not incorrectly include
    ``C:\\foobar``.
    """
    if not base_path or not candidate_path:
        return False
    try:
        b = os.path.normcase(os.path.abspath(base_path))
        p = os.path.normcase(os.path.abspath(candidate_path))
        rel = os.path.relpath(p, b)
    except ValueError:
        return False
    return not rel.startswith("..")


def get_module_name(file_path: str, base_path: str) -> str:
    if not file_path:
        return "unknown"
    try:
        path = file_path if os.path.isabs(file_path) else os.path.join(base_path, file_path)
        if not path_is_under(base_path, path):
            return "unknown"
        abs_base = os.path.normcase(os.path.abspath(base_path))
        abs_path = os.path.normcase(os.path.abspath(path))
        rel = os.path.relpath(abs_path, abs_base).replace("\\", "/")
        return _resolve_module_from_rel(rel)
    except ValueError:
        return "unknown"


def norm_path(path: str, base_path: str) -> str:
    if os.path.isabs(path):
        return os.path.normpath(path)
    return os.path.normpath(os.path.join(base_path, path))


PRIMITIVES = {
    "void": {"range": "VOID"},
    "bool": {"range": "0-1"},
    "char": {"range": "-0x80-0x7F"},
    "unsigned char": {"range": "0-0xFF"},
    "signed char": {"range": "-0x80-0x7F"},
    "short": {"range": "-0x8000-0x7FFF"},
    "short int": {"range": "-0x8000-0x7FFF"},
    "signed short": {"range": "-0x8000-0x7FFF"},
    "unsigned short": {"range": "0-0xFFFF"},
    "int": {"range": "-0x80000000-0x7FFFFFFF"},
    "signed int": {"range": "-0x80000000-0x7FFFFFFF"},
    "unsigned": {"range": "0-0xFFFFFFFF"},
    "unsigned int": {"range": "0-0xFFFFFFFF"},
    "long": {"range": "-0x80000000-0x7FFFFFFF"},
    "long int": {"range": "-0x80000000-0x7FFFFFFF"},
    "unsigned long": {"range": "0-0xFFFFFFFF"},
    "long long": {"range": "-0x8000000000000000-0x7FFFFFFFFFFFFFFF"},
    "long long int": {"range": "-0x8000000000000000-0x7FFFFFFFFFFFFFFF"},
    "unsigned long long": {"range": "0-0xFFFFFFFFFFFFFFFF"},
    "float": {"range": "IEEE 754"},
    "double": {"range": "IEEE 754"},
    "long double": {"range": "IEEE 754"},
    "int8_t": {"range": "-0x80-0x7F"},
    "uint8_t": {"range": "0-0xFF"},
    "int16_t": {"range": "-0x8000-0x7FFF"},
    "uint16_t": {"range": "0-0xFFFF"},
    "int32_t": {"range": "-0x80000000-0x7FFFFFFF"},
    "uint32_t": {"range": "0-0xFFFFFFFF"},
    "int64_t": {"range": "-0x8000000000000000-0x7FFFFFFFFFFFFFFF"},
    "uint64_t": {"range": "0-0xFFFFFFFFFFFFFFFF"},
    "intptr_t": {"range": "-0x8000000000000000-0x7FFFFFFFFFFFFFFF"},
    "uintptr_t": {"range": "0-0xFFFFFFFFFFFFFFFF"},
    "size_t": {"range": "0-0xFFFFFFFFFFFFFFFF"},
    "std::int8_t": {"range": "-0x80-0x7F"},
    "std::uint8_t": {"range": "0-0xFF"},
    "std::int16_t": {"range": "-0x8000-0x7FFF"},
    "std::uint16_t": {"range": "0-0xFFFF"},
    "std::int32_t": {"range": "-0x80000000-0x7FFFFFFF"},
    "std::uint32_t": {"range": "0-0xFFFFFFFF"},
    "std::int64_t": {"range": "-0x8000000000000000-0x7FFFFFFFFFFFFFFF"},
    "std::uint64_t": {"range": "0-0xFFFFFFFFFFFFFFFF"},
    "std::size_t": {"range": "0-0xFFFFFFFFFFFFFFFF"},
}


def get_range_for_type(type_str: str) -> str:
    """Map C++ type to range string for interface tables (VOID, 0-0xFF, NA, etc.)."""
    t = (type_str or "").strip().lower()
    if t == "void" or (t.startswith("void ") and "*" not in t):
        return "VOID"
    base = t.replace("const ", "").replace("volatile ", "").strip().lower()
    if base in ("uint8_t", "std::uint8_t", "param_uint8_t"):
        return "0-0xFF"
    if base in ("uint16_t", "std::uint16_t", "param_uint16_t"):
        return "0-0xFFFF"
    if base in ("uint32_t", "std::uint32_t", "param_uint32_t"):
        return "0-0xFFFFFFFF"
    if base in ("uint64_t", "std::uint64_t", "param_uint64_t"):
        return "0-0xFFFFFFFFFFFFFFFF"
    if base in ("uintptr_t", "std::uintptr_t", "param_uintptr_t"):
        return "0-0xFFFFFFFFFFFFFFFF"
    # Fixed-width signed (stdint or param_* typedefs)
    if base in ("int8_t", "std::int8_t", "param_int8_t"):
        return "-0x80-0x7F"
    if base in ("int16_t", "std::int16_t", "param_int16_t"):
        return "-0x8000-0x7FFF"
    if base in ("int32_t", "std::int32_t", "param_int32_t"):
        return "-0x80000000-0x7FFFFFFF"
    if base in ("int64_t", "std::int64_t", "param_int64_t"):
        return "-0x8000000000000000-0x7FFFFFFFFFFFFFFF"
    if base in ("intptr_t", "std::intptr_t", "param_intptr_t"):
        return "-0x8000000000000000-0x7FFFFFFFFFFFFFFF"
    if base in ("int", "signed int"):
        return "-0x80000000-0x7FFFFFFF"
    if base in ("short", "short int", "signed short"):
        return "-0x8000-0x7FFF"
    if base in ("long", "long int", "signed long"):
        return "-0x80000000-0x7FFFFFFF"
    if base in ("long long", "long long int", "signed long long"):
        return "-0x8000000000000000-0x7FFFFFFFFFFFFFFF"
    if base in ("unsigned int", "unsigned"):
        return "0-0xFFFFFFFF"
    if base == "unsigned short":
        return "0-0xFFFF"
    if base == "unsigned long":
        return "0-0xFFFFFFFF"
    if base == "unsigned long long":
        return "0-0xFFFFFFFFFFFFFFFF"
    if "size_t" in base and "*" not in base or base == "param_size_t":
        return "0-0xFFFFFFFFFFFFFFFF"
    return "NA"


def get_range(type_str: str, data_dictionary: dict, _depth: int = 0) -> str:
    """Look up range from data dictionary (keyed by name); fallback to get_range_for_type."""
    t = (type_str or "").strip()
    if not t:
        return "NA"
    dd = data_dictionary or {}
    # Normalize: strip const, volatile, pointers for base type
    base = t.replace("const ", "").replace("volatile ", "").strip()
    if "*" in base:
        base = base.split("*")[0].strip()
    if "&" in base:
        base = base.split("&")[0].strip()
    base_lower = base.lower()
    # Direct lookup (name/qualifiedName as key)
    entry = dd.get(base) or dd.get(base_lower)
    if entry:
        r = entry.get("range")
        if r:
            return r
        if entry.get("kind") == "typedef" and _depth < 10:
            underlying = entry.get("underlyingType", "")
            return get_range(underlying, dd, _depth + 1) if underlying else "NA"
    # Search by qualifiedName
    for ent in dd.values():
        if ent.get("qualifiedName") == base or ent.get("qualifiedName", "").lower() == base_lower:
            r = ent.get("range")
            if r:
                return r
            if ent.get("kind") == "typedef" and _depth < 10:
                underlying = ent.get("underlyingType", "")
                return get_range(underlying, dd, _depth + 1) if underlying else "NA"
    return get_range_for_type(type_str)
