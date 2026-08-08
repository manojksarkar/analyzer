"""Parse C++ source -> model/."""
import csv
import ctypes
import os
import re
import sys
import json
from datetime import datetime, timezone
from collections import defaultdict

from clang import cindex

from core.paths import paths as _paths
from core.config import (
    DEFAULT_VISIBILITY_MACROS,
    app_config as _app_config,
    clang_config as _clang_config,
    default_clang_macro_defs,
)
from core.macro_input import (
    MacroInputError,
    args_for_scope as _args_for_scope,
    find_conflicts as _find_macro_conflicts,
    load_macro_defs as _load_macro_defs,
    merge_macro_defs as _merge_macro_defs,
    scoped_args as _scoped_macro_args,
)
from incremental.hashing import hash_cursor, hash_macro_text
from incremental.edges import build_edges
from incremental.parse_includes import build_closure, to_repo_relative
from incremental.virtual_dispatch import spread_virtual_families

_p = _paths()
SCRIPT_DIR = _p.src_dir
PROJECT_ROOT = _p.project_root
if len(sys.argv) < 2:
    print("Usage: python parser.py <project_path> [--data-dictionary <path>]")
    raise SystemExit(1)
proj_arg = sys.argv[1]
MODULE_BASE_PATH = os.path.abspath(proj_arg) if os.path.isabs(proj_arg) else os.path.join(PROJECT_ROOT, proj_arg)

# Scan for optional flags passed by group_planner.
_data_dict_path: str | None = None
_macros_path: str | None = None
_macros_layer_args: list = []   # (layer, path) pairs from --macros-layer, repeatable
_selected_group: str | None = None
_selected_layer: str | None = None
_project_name_override: str | None = None
_only_files_path: str | None = None  # narrowed parse (M4.3): parse only the listed TUs
_include_emulator: bool = False  # opt out of the default *emul* file exclusion (3.1)
_i = 2
while _i < len(sys.argv):
    if sys.argv[_i] == "--data-dictionary" and _i + 1 < len(sys.argv):
        _data_dict_path = sys.argv[_i + 1]
        _i += 2
    elif sys.argv[_i] == "--only-files" and _i + 1 < len(sys.argv):
        _only_files_path = sys.argv[_i + 1]
        _i += 2
    elif sys.argv[_i] == "--macros" and _i + 1 < len(sys.argv):
        _macros_path = sys.argv[_i + 1]
        _i += 2
    elif sys.argv[_i] == "--macros-layer" and _i + 2 < len(sys.argv):
        _macros_layer_args.append((sys.argv[_i + 1], sys.argv[_i + 2]))
        _i += 3
    elif sys.argv[_i] == "--selected-group" and _i + 1 < len(sys.argv):
        _selected_group = sys.argv[_i + 1]
        _i += 2
    elif sys.argv[_i] == "--selected-layer" and _i + 1 < len(sys.argv):
        _selected_layer = sys.argv[_i + 1]
        _i += 2
    elif sys.argv[_i] == "--project-name" and _i + 1 < len(sys.argv):
        _project_name_override = sys.argv[_i + 1]
        _i += 2
    elif sys.argv[_i] == "--include-emulator":
        _include_emulator = True
        _i += 1
    else:
        _i += 1

PROJECT_NAME = _project_name_override or os.path.basename(MODULE_BASE_PATH)

from utils import (
    get_component_name as _get_component,
    get_range_for_type,
    load_config,
    make_function_key,
    make_global_key,
    PRIMITIVES,
)

_config = _app_config()
_clang = _config.get("clang") or {}
_llvm = _clang.get("llvmLibPath") or _config.get("llvmLibPath")
_clang_inc = _clang.get("clangIncludePath") or _config.get("clangIncludePath")
if _llvm and os.path.isfile(_llvm):
    # Windows can fail to load libclang when dependent DLLs (e.g. from LLVM)
    # are not on the DLL search path. Ensure the LLVM bin folder is discoverable.
    _llvm_bin_dir = os.path.dirname(_llvm)
    if _llvm_bin_dir and os.path.isdir(_llvm_bin_dir):
        try:
            # Python 3.8+: scoped DLL directory for the current process.
            os.add_dll_directory(_llvm_bin_dir)  # type: ignore[attr-defined]
        except Exception:
            # Fallback: extend PATH so dependent DLLs are found.
            os.environ["PATH"] = _llvm_bin_dir + os.pathsep + os.environ.get("PATH", "")
    cindex.Config.set_library_file(_llvm)

from core.config import get_flat_groups as _get_flat_groups, get_group_layer_name as _get_group_layer_name, get_layer_flat_groups as _get_layer_flat_groups, get_component_layer_name as _get_component_layer_name
if _selected_layer:
    _components_groups = _get_layer_flat_groups(_config, _selected_layer)
elif _selected_group:
    _layer_name = _get_group_layer_name(_config, _selected_group)
    _components_groups = _get_layer_flat_groups(_config, _layer_name) if _layer_name else _get_flat_groups(_config)
else:
    _components_groups = _get_flat_groups(_config)
_components_cfg = _config.get("components") or _config.get("modules") or {}
# If layer exists but no explicit component mapping is provided, merge all groups.
# This makes the model parse only the union of all configured component folders.
if not _components_cfg and isinstance(_components_groups, dict) and _components_groups:
    merged = {}
    for _, grp in _components_groups.items():
        if not isinstance(grp, dict):
            continue
        for component, paths in grp.items():
            if not paths:
                continue
            if isinstance(paths, str):
                paths_list = [paths]
            else:
                paths_list = list(paths) if isinstance(paths, list) else []
            if component not in merged:
                merged[component] = paths_list if len(paths_list) != 1 else paths_list[0]
            else:
                existing = merged.get(component)
                if isinstance(existing, str):
                    existing_list = [existing]
                else:
                    existing_list = list(existing) if isinstance(existing, list) else []
                for p in paths_list:
                    if p and p not in existing_list:
                        existing_list.append(p)
                merged[component] = existing_list if len(existing_list) != 1 else existing_list[0]
    _components_cfg = merged
_COMPONENT_FOLDERS = []
for _mod_paths in _components_cfg.values():
    if not _mod_paths:
        continue
    if isinstance(_mod_paths, str):
        _mod_paths = [_mod_paths]
    for _p in _mod_paths:
        _norm = (_p or "").replace("\\", "/").lstrip("./")
        if _norm:
            _COMPONENT_FOLDERS.append(_norm)

# ---------------------------------------------------------------------------
# Flat file-to-component map (replaces prefix-matching for lookup + filtering)
# ---------------------------------------------------------------------------

_SOURCE_EXTS = {'.cpp', '.cc', '.cxx', '.c', '.h', '.hpp', '.hxx'}


def _build_file_component_map(components_cfg: dict, base_path: str) -> dict:
    """Resolve component config to {lowercase_relpath: component}.

    Each entry (string or element of a list) is inspected individually:
    - Known C/C++ extension → added as an exact file.
    - No recognised extension → treated as a directory; all source files
      under it are included recursively.

    setdefault ensures the first component in config iteration order wins on overlap.
    """
    file_map: dict = {}
    for component, paths in (components_cfg or {}).items():
        if isinstance(paths, str):
            paths = [paths]
        for p in (paths or []):
            p_norm = (p or "").replace("\\", "/").lstrip("./").rstrip("/")
            if not p_norm:
                continue
            _, ext = os.path.splitext(p_norm)
            if ext.lower() in _SOURCE_EXTS:
                # Explicit file entry — add directly
                file_map.setdefault(p_norm.lower(), component.replace(" ", "-"))
            else:
                # Directory entry — walk the filesystem
                abs_dir = os.path.join(base_path, p_norm)
                if not os.path.isdir(abs_dir):
                    continue
                for root, _, files in os.walk(abs_dir):
                    for fname in files:
                        if os.path.splitext(fname)[1].lower() in _SOURCE_EXTS:
                            full = os.path.join(root, fname)
                            key = os.path.relpath(full, base_path).replace("\\", "/").lower()
                            file_map.setdefault(key, component.replace(" ", "-"))
    return file_map


_FILE_COMPONENT_MAP: dict = _build_file_component_map(_components_cfg, MODULE_BASE_PATH)

# Emulator/stub files are excluded from the parse scope by default (3.1): any file whose
# basename contains one of these (case-insensitive) substrings is skipped. Overridable per
# project via config `excludeNamePatterns` (a list); `--include-emulator` disables it.
_cfg_exclude = _config.get("excludeNamePatterns")
if _cfg_exclude is None:
    _cfg_exclude = ["emul"]
_EXCLUDE_NAME_PATTERNS: list = [] if _include_emulator else [
    str(p).lower() for p in _cfg_exclude if p
]

# Read layer include paths written by run.py before Phase 1 started.
_layer_include_paths: dict = {}
_clang_paths_file = os.path.join(PROJECT_ROOT, "model", "clang_include_paths.json")
if os.path.isfile(_clang_paths_file):
    try:
        with open(_clang_paths_file, "r", encoding="utf-8") as _f:
            _layer_include_paths = json.load(_f) or {}
    except (json.JSONDecodeError, OSError):
        pass

CLANG_ARGS = [
    "-x", "c++",  # treat every parsed TU as C++ — required so .h headers parse as C++ (3.2),
                  # otherwise libclang infers C/ambiguous for .h and the TU fails to load.
    "-std=c++14",
    f"-I{MODULE_BASE_PATH}",
    f"-I{_clang_inc}",
]
# Extend with layer include dirs (scoped to selected layer when --selected-group/--selected-layer is set).
_clang_args_seen = set(CLANG_ARGS)
for _dirs in _layer_include_paths.values():
    for _d in _dirs:
        _a = f"-I{_d}"
        if _a not in _clang_args_seen:
            _clang_args_seen.add(_a)
            CLANG_ARGS.append(_a)
# Visibility-style macros (PRIVATE/PROTECTED/PUBLIC/__OVLYINIT) come from
# `core.config.default_clang_macro_defs()` so the flowchart engine's
# per-function re-parser reuses the same set.
# Override locally by adding `-UPUBLIC` etc. to `clang.clangArgs` in config.
_VISIBILITY_KEYWORDS = set(DEFAULT_VISIBILITY_MACROS) - {"__OVLYINIT"}
for _arg in default_clang_macro_defs():
    if _arg not in CLANG_ARGS:
        CLANG_ARGS.append(_arg)
_extra = _clang.get("clangArgs")
if _extra:
    CLANG_ARGS.extend(_extra if isinstance(_extra, list) else [_extra])


# Macro -D flags, scope-keyed ("*" = every layer). The file may be a CSV or any
# of the JSON shapes core.macro_input accepts; --macros is global and
# --macros-layer pins a file to one layer. The resolved set is written to
# model/clang_macros.json so the Phase 3 flowchart engine defines exactly what
# Phase 1 did.
# Sources are config first, CLI second, so a flag overrides the config and the
# later file wins on a name collision. Config carries them because every entry
# point (run.py, incremental generate/engine) passes --config, while only run.py
# takes the flags: the API writes clang.macrosFile / clang.macrosByLayer into the
# per-project config instead of threading a path through each script.
_macro_sources: list = []
_cfg_macros_file = _clang.get("macrosFile")
if isinstance(_cfg_macros_file, str) and _cfg_macros_file.strip():
    _macro_sources.append((None, _cfg_macros_file.strip()))
for _cfg_layer, _cfg_path in (_clang.get("macrosByLayer") or {}).items():
    if isinstance(_cfg_path, str) and _cfg_path.strip():
        _macro_sources.append((_cfg_layer, _cfg_path.strip()))
if _macros_path:
    _macro_sources.append((None, _macros_path))
_macro_sources += _macros_layer_args

_MACRO_ARGS_BY_SCOPE: dict = {}
if _macro_sources:
    import logging as _logging
    _macro_log = _logging.getLogger("parser")
    _macro_defs: dict = {}
    for _scope, _path in _macro_sources:
        try:
            _defs, _report = _load_macro_defs(
                _path,
                scope_map=(_clang.get("macroScopes") or {}),
                default_scope=_scope,
            )
        except MacroInputError as _exc:
            print(f"ERROR: {_exc}")
            sys.exit(2)
        for _line in _report.lines():
            _macro_log.info("%s", _line)
        # A name defined by two lists is reported, never silently reconciled —
        # the precedence strategy across macro lists is still an open question.
        for _c_scope, _c_name, _c_old, _c_new in _find_macro_conflicts(_macro_defs, _defs):
            _macro_log.warning(
                "macro %s redefined in scope %s: %s -> %s (last one wins)",
                _c_name, _c_scope, _c_old, _c_new,
            )
        _macro_defs = _merge_macro_defs(_macro_defs, _defs)
    _MACRO_ARGS_BY_SCOPE = _scoped_macro_args(_macro_defs)

_macros_json = os.path.join(PROJECT_ROOT, "model", "clang_macros.json")
if _MACRO_ARGS_BY_SCOPE or os.path.isfile(_macros_json):
    # Written even when empty: otherwise a previous run's file survives and
    # Phase 3 keeps defining macros this parse did not use.
    with open(_macros_json, "w", encoding="utf-8") as _mf:
        json.dump(_MACRO_ARGS_BY_SCOPE, _mf, indent=2)



def _detect_visibility(file_path: str, line_no: int, scan_lines: int = 5) -> str:
    """Scan raw source lines at/before line_no to detect PRIVATE/PUBLIC/PROTECTED prefix.

    Returns 'private', 'public', 'protected', or 'default' if none found.
    Scans backwards from the declaration line to handle multi-line declarations like:
        PRIVATE UNIT __OVLYINIT
        _SomeFunction(GG *gg) {}
    """
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except (OSError, IOError):
        return "default"

    start = max(0, line_no - scan_lines)
    for i in range(line_no - 1, start - 1, -1):
        line = lines[i].strip()
        if not line or line.startswith("//") or line.startswith("/*") or line.startswith("*"):
            continue
        first_token = re.split(r"\s+", line)[0]
        if first_token in _VISIBILITY_KEYWORDS:
            return first_token.lower()
    return "default"


def get_component_name(file_path: str) -> str:
    if not file_path or not _FILE_COMPONENT_MAP:
        return _get_component(file_path, MODULE_BASE_PATH)
    try:
        rel = os.path.relpath(
            os.path.abspath(file_path), MODULE_BASE_PATH
        ).replace("\\", "/").lower()
    except ValueError:
        return "unknown"
    return _FILE_COMPONENT_MAP.get(rel, "unknown")


_LAYER_ARGS_CACHE: dict = {}


def clang_args_for(file_path: str) -> list:
    """CLANG_ARGS plus the macro defines in scope for this file's layer.

    Args are resolved per TU because one run can span layers: the global ("*")
    defines come first, then the layer's own, and Clang honours the *last* -D for
    a name — so a layer value overrides the global one by position. A file
    outside every configured component (an orphan header, say) resolves to no
    layer and is parsed with the global set only.
    """
    if not _MACRO_ARGS_BY_SCOPE:
        return CLANG_ARGS
    component = get_component_name(file_path)
    layer = (_get_component_layer_name(_config, component)
             if component and component != "unknown" else None)
    cached = _LAYER_ARGS_CACHE.get(layer)
    if cached is None:
        cached = CLANG_ARGS + _args_for_scope(_MACRO_ARGS_BY_SCOPE, layer)
        _LAYER_ARGS_CACHE[layer] = cached
    return cached


index = cindex.Index.create()


def _make_overridden_lookup():
    """This libclang Python binding lacks Cursor.get_overridden_cursors, but the C API
    (clang_getOverriddenCursors) is present — bind it via ctypes. Returns a function
    cursor -> [base method cursors] (queried on the canonical/in-class declaration, since
    out-of-line definitions report no overrides), or None if the C API is unavailable.
    Used for the D7 virtual-dispatch over-approximation."""
    try:
        lib = cindex.conf.lib
        f_ov = lib.clang_getOverriddenCursors
        f_ov.argtypes = [cindex.Cursor, ctypes.POINTER(ctypes.POINTER(cindex.Cursor)),
                         ctypes.POINTER(ctypes.c_uint)]
        f_ov.restype = None
        f_disp = lib.clang_disposeOverriddenCursors
        f_disp.argtypes = [ctypes.POINTER(cindex.Cursor)]
        f_disp.restype = None
    except Exception:
        return None

    def _overridden(cur):
        c = cur.canonical
        arr = ctypes.POINTER(cindex.Cursor)()
        num = ctypes.c_uint()
        f_ov(c, ctypes.byref(arr), ctypes.byref(num))
        out = []
        for i in range(int(num.value)):
            oc = arr[i]
            oc._tu = c._tu  # keep the TU alive for the borrowed cursor
            out.append(oc)
        f_disp(arr)
        return out

    return _overridden


_clang_overridden = _make_overridden_lookup()
functions = {}
globals_data = {}
data_dictionary = {}
# Incremental (M1.2): entityKey -> token-sha256, for all four entity kinds.
# Function/global keys are filled in build_metadata (need the model key); type and
# macro keys are filled directly in their passes. Written to model/hashes.json.
entity_hashes = {}
# Incremental (M4.0): per-TU include closure {tuRelPath -> [in-repo included rel paths]},
# captured during the first parse pass; written to model/tu_includes.json.
tu_includes = {}
# Incremental (M1.2b): slim type/macro usage index, written to model/edges.json.
# Collected by func_key (internal) during visit_usage; remapped to model fids in main().
type_users = defaultdict(set)      # type qn        -> set(func_key) that reference it
function_tokens = {}               # func_key       -> set(identifier token spellings) for macro matching
_type_keys = set()                 # project type qns that have a hash (filter target)
_macro_keys = set()                # macro keys "name@relFile" (filled in _scan_defines)
_active_macro_lines = {}           # (name, relFile) -> set of #define lines libclang's
                                   # preprocessor actually took (active #if/#else branch);
                                   # filled in parse_file, consumed by _scan_defines
_func_key_to_fid = {}              # internal func_key -> model fid (filled in build_metadata)
_visited_usage_keys = set()        # dedup for visit_usage across header includes
call_graph = defaultdict(list)  # caller -> [callees]
reverse_call_graph = defaultdict(list)  # callee -> [callers]
# (override_funcKey, base_funcKey) pairs from get_overridden_cursors — drives the D7
# virtual-dispatch over-approximation (spread_virtual_families) in build_metadata.
_override_pairs = []
# (override_fid, base_fid|base_funcKey) pairs (fid-level), built in build_metadata and
# written to model/override_pairs.json so a narrowed parse (M4.6) can re-spread virtual
# families across affected + UN-parsed files using the baseline's pairs.
_override_pairs_fid = []
# Incremental (M4.3): entityKey -> repo-relative defining file, for every hashed entity
# (function/global/type/macro). Written to model/entity_files.json; the narrowed-parse
# merge uses it to resolve each entity's file. Populated alongside entity_hashes.
entity_files = {}
# Incremental (M4.4): the BASELINE version's {mangled-func-key -> fid} map, loaded only in
# a narrowed (--only-files) parse so calls to functions defined in UN-parsed files still
# resolve to a call edge. Empty for a full parse (so behaviour is unchanged).
_baseline_func_keys = {}
component_functions = defaultdict(list)
function_to_component = {}
global_access_reads = defaultdict(set)   # func_key -> set of var_id
global_access_writes = defaultdict(set)  # func_key -> set of var_id
# First non-trivial return expression per function (for behaviour output naming)
function_return_expr = {}

# Track already-processed function keys to avoid redundant visits from header includes
_visited_function_keys = set()
_visited_call_keys = set()  # for visit_calls
_visited_global_access_keys = set()  # for visit_global_access

# ---------------------------------------------------------------------------
# Comment extraction helpers
# ---------------------------------------------------------------------------

_source_cache: dict = {}


def _get_source_lines(file_path: str):
    """Return cached source lines (list of str) for file_path."""
    if file_path not in _source_cache:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as _f:
                _source_cache[file_path] = _f.readlines()
        except (OSError, IOError):
            _source_cache[file_path] = []
    return _source_cache[file_path]


def _preceding_comment(cursor) -> str:
    """Return comment text on lines immediately above cursor (// or /* */ style)."""
    if not cursor.location.file:
        return ""
    lines = _get_source_lines(cursor.location.file.name)
    line_no = cursor.location.line  # 1-based
    collected: list = []
    i = line_no - 2  # 0-indexed line directly above
    while i >= 0:
        stripped = lines[i].strip()
        if stripped.startswith("//"):
            collected.insert(0, stripped.lstrip("/").strip())
            i -= 1
        elif stripped.endswith("*/"):
            # Block comment — walk back to find /*
            block: list = []
            while i >= 0:
                s = lines[i].strip()
                block.insert(0, s)
                if "/*" in s:
                    break
                i -= 1
            for bl in block:
                t = bl.lstrip("/*").rstrip("*/").strip("* \t")
                if t:
                    collected.insert(0, t)
            i -= 1
        elif stripped == "" or stripped.startswith("#"):
            break
        else:
            break
    return " ".join(collected)


def _inline_comment(cursor) -> str:
    """Return trailing // comment on the same line as cursor."""
    if not cursor.location.file:
        return ""
    lines = _get_source_lines(cursor.location.file.name)
    line_no = cursor.location.line  # 1-based
    if line_no < 1 or line_no > len(lines):
        return ""
    line = lines[line_no - 1]
    idx = line.find("//")
    if idx < 0:
        return ""
    return line[idx + 2:].strip()


def is_project_file(file_path: str) -> bool:
    """Return True if this path should be treated as project source for parsing.

    Uses the flat _FILE_COMPONENT_MAP built from config + filesystem scan.
    A file is included iff it is under MODULE_BASE_PATH AND appears in the map.
    When the map is empty (no component config) every file under the base passes.
    """
    if not file_path:
        return False
    if _EXCLUDE_NAME_PATTERNS:
        _bn = os.path.basename(file_path).lower()
        if any(pat in _bn for pat in _EXCLUDE_NAME_PATTERNS):
            return False
    abs_path = os.path.normcase(os.path.abspath(file_path))
    abs_base = os.path.normcase(os.path.abspath(MODULE_BASE_PATH))
    if not abs_path.startswith(abs_base):
        return False
    if _FILE_COMPONENT_MAP:
        try:
            rel = os.path.relpath(abs_path, MODULE_BASE_PATH).replace("\\", "/").lower()
        except ValueError:
            return False
        return rel in _FILE_COMPONENT_MAP
    return True


def get_qualified_name(cursor):
    parts = []
    parent = cursor.semantic_parent
    while parent:
        if parent.kind in (cindex.CursorKind.NAMESPACE, cindex.CursorKind.CLASS_DECL, cindex.CursorKind.STRUCT_DECL):
            parts.insert(0, parent.spelling or "(anonymous)")
        parent = parent.semantic_parent
    parts.append(cursor.spelling)
    return "::".join(parts) if parts else cursor.spelling


_CLASS_PARENT_KINDS = (
    cindex.CursorKind.CLASS_DECL,
    cindex.CursorKind.STRUCT_DECL,
    cindex.CursorKind.CLASS_TEMPLATE,
    cindex.CursorKind.CLASS_TEMPLATE_PARTIAL_SPECIALIZATION,
)


def get_class_scope(cursor):
    """Enclosing class/struct chain, namespaces dropped (e.g. 'Outer::Inner', '' for free functions).

    Deliberately separate from get_qualified_name rather than derived from it: a
    qualifiedName string can't be split back into namespace vs class parts, and
    get_qualified_name must not change — make_function_key builds every fid from it,
    so touching it re-keys the whole model.

    CLASS_TEMPLATE is included here even though get_qualified_name omits it, so methods
    of template classes get a class too. Template arguments aren't in the spelling, so
    Foo<int>::run and Foo<char>::run both read 'Foo::run'; mangled names still keep them
    apart in the model.
    """
    parts = []
    parent = cursor.semantic_parent
    while parent:
        if parent.kind in _CLASS_PARENT_KINDS and parent.spelling:
            parts.insert(0, parent.spelling)
        parent = parent.semantic_parent
    return "::".join(parts)


def get_function_key(cursor):
    # Mangled disambiguates overloads; fallback to qualified@file:line for templates/extern C
    mangled = cursor.mangled_name
    if mangled:
        return mangled
    qualified = get_qualified_name(cursor)
    if cursor.location.file:
        return f"{qualified}@{cursor.location.file.name}:{cursor.location.line}"
    return qualified


def _get_type_key(cursor):
    if cursor.location.file and cursor.location.file.name:
        try:
            rel = os.path.relpath(cursor.location.file.name, MODULE_BASE_PATH).replace("\\", "/")
        except ValueError:
            rel = os.path.normpath(cursor.location.file.name).replace("\\", "/")
        return f"{rel}:{cursor.location.line}"
    return get_qualified_name(cursor)


_ELABORATED_RE = re.compile(r"^(?:struct|enum|union|class)\s+")

_SIGNED_INT_KINDS = {
    cindex.TypeKind.SCHAR, cindex.TypeKind.CHAR_S, cindex.TypeKind.SHORT,
    cindex.TypeKind.INT, cindex.TypeKind.LONG, cindex.TypeKind.LONGLONG,
    cindex.TypeKind.INT128,
}
_UNSIGNED_INT_KINDS = {
    cindex.TypeKind.UCHAR, cindex.TypeKind.CHAR_U, cindex.TypeKind.USHORT,
    cindex.TypeKind.UINT, cindex.TypeKind.ULONG, cindex.TypeKind.ULONGLONG,
    cindex.TypeKind.UINT128, cindex.TypeKind.CHAR16, cindex.TypeKind.CHAR32,
}


def _range_from_clang_type(ctype) -> str:
    """Data range computed from the type itself, rather than guessed from its name.

    `get_canonical()` walks the typedef chain down to the real builtin and
    `get_size()` reports its width **for the target being parsed** — so `long` is
    4 bytes on Windows and 8 on Linux, which the hardcoded PRIMITIVES table cannot
    express. Returns "NA" for anything that is not a builtin (structs, enums,
    pointers, floats); those are answered from their own dictionary entries.
    """
    if ctype is None:
        return "NA"
    try:
        canon = ctype.get_canonical()
        kind = canon.kind
        if kind == cindex.TypeKind.VOID:
            return "VOID"
        if kind == cindex.TypeKind.BOOL:
            return "0-1"
        if kind in _SIGNED_INT_KINDS or kind in _UNSIGNED_INT_KINDS:
            size = canon.get_size()
            if size and size > 0:
                bits = size * 8
                if kind in _UNSIGNED_INT_KINDS:
                    return f"0-0x{(1 << bits) - 1:X}"
                return f"-0x{1 << (bits - 1):X}-0x{(1 << (bits - 1)) - 1:X}"
    except Exception:
        pass
    return "NA"


def _register_builtin_range(ctype) -> None:
    """Record a builtin's target-correct range under its canonical name.

    Called for every parameter / return type / global / field encountered, so the
    dictionary answers for the builtins this project actually uses with a measured
    width instead of the portable guess in PRIMITIVES (which is seeded afterwards
    with setdefault, and so no longer overwrites this).

    Only the CANONICAL spelling is registered ("unsigned char", "long"). Registering
    the written spelling would let a parameter typed `UINT8` overwrite the UINT8
    *typedef* entry with a primitive one, losing the location the unit header table
    needs.
    """
    if ctype is None:
        return
    try:
        canon = ctype.get_canonical()
        name = (canon.spelling or "").strip()
    except Exception:
        return
    if not name:
        return
    rng = _range_from_clang_type(canon)
    if rng == "NA":
        return
    existing = data_dictionary.get(name)
    if existing is not None and existing.get("kind") != "primitive":
        return  # never shadow a project type that happens to share the name
    data_dictionary[name] = {"kind": "primitive", "range": rng}


def _typedef_underlying(cursor) -> str:
    """What a `typedef` actually aliases.

    `cursor.type` on a TYPEDEF_DECL is the typedef type ITSELF, so its spelling is
    the alias's own name ("UINT8"), never what it points at — which left every
    typedef self-referential and its range "NA". `underlying_typedef_type` is the
    accessor that answers the question (`typedef unsigned char UINT8;` -> "unsigned
    char", `typedef int UNIT;` -> "int").

    Elaborated spellings ("enum Mode_t", "struct Widget_t") are reduced to the bare
    name so the result is usable as a dataDictionary key — that also keeps the
    typedef-of-anonymous-enum/struct forms self-referential, which is what the unit
    header table relies on to print the enumerator list.
    """
    underlying = ""
    try:
        u = cursor.underlying_typedef_type
        underlying = (u.spelling or "").strip() if u is not None else ""
    except Exception:
        underlying = ""
    if not underlying:
        underlying = (cursor.type.spelling or "").strip() if cursor.type else ""
    return _ELABORATED_RE.sub("", underlying).strip()


def _maybe_add_typedef_for_struct(name: str, qn: str, loc: dict, rel_file: str):
    """If this struct comes from a 'typedef struct { ... } Name;' pattern, add a typedef entry."""
    if not name or not rel_file or not loc:
        return
    # Heuristic: look a few lines around the struct location for 'typedef struct' ending with the name.
    try:
        abs_path = os.path.join(MODULE_BASE_PATH, rel_file)
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except (OSError, IOError):
        return
    line_no = int(loc.get("line", 0)) or 0
    if line_no < 1 or line_no > len(lines):
        return
    start = max(0, line_no - 10)
    end = min(len(lines), line_no + 10)
    typedef_line = None
    for idx in range(start, end):
        t = lines[idx].strip()
        if not t or t.startswith("//") or t.startswith("/*") or t.startswith("*"):
            continue
        if "typedef struct" in t or "typedef union" in t:
            typedef_line = idx + 1  # 1-based
            break
    if typedef_line is None:
        return
    key = f"typedef@{qn}:{rel_file}:{typedef_line}"
    if key in data_dictionary:
        return
    underlying = qn or name
    data_dictionary[key] = {
        "kind": "typedef",
        "name": name,
        "qualifiedName": qn,
        "underlyingType": underlying or "(opaque)",
        # underlyingType is the type's OWN name here (the alias names the struct it
        # follows), so deriving a range from it would be reading a range out of a
        # type name: get_range_for_type("Size_t") matches its "size_t" substring rule
        # and stamps a 64-bit integer range on a {int width; int height;} struct.
        # The struct entry under `qn` carries the real answer; leave this one unknown.
        "range": "NA",
        "location": {"file": rel_file, "line": typedef_line},
    }


def visit_type_definitions(cursor):
    if not cursor.location.file or not is_project_file(cursor.location.file.name):
        for child in cursor.get_children():
            visit_type_definitions(child)
        return

    rel_file = None
    try:
        rel_file = os.path.relpath(cursor.location.file.name, MODULE_BASE_PATH).replace("\\", "/")
    except ValueError:
        rel_file = cursor.location.file.name.replace("\\", "/")

    loc = {"file": rel_file, "line": cursor.location.line}

    if cursor.kind in (cindex.CursorKind.STRUCT_DECL, cindex.CursorKind.CLASS_DECL):
        if cursor.spelling or cursor.is_definition():
            key = _get_type_key(cursor)
            fields = []
            for c in cursor.get_children():
                if c.kind == cindex.CursorKind.FIELD_DECL and c.spelling:
                    _register_builtin_range(c.type)
                    _field_range = _range_from_clang_type(c.type)
                    if _field_range == "NA":
                        _field_range = get_range_for_type(c.type.spelling if c.type else "")
                    field_entry = {
                        "name": c.spelling,
                        "type": c.type.spelling if c.type else "",
                        "range": _field_range,
                    }
                    cmt = _inline_comment(c)
                    if cmt:
                        field_entry["comment"] = cmt
                    fields.append(field_entry)
            name = cursor.spelling or "(anonymous)"
            qn = get_qualified_name(cursor) if cursor.spelling else f"(anonymous)@{key}"
            struct_entry: dict = {
                "kind": "struct" if cursor.kind == cindex.CursorKind.STRUCT_DECL else "class",
                "name": name,
                "qualifiedName": qn,
                "fields": fields,
                "range": "NA",
                "location": loc,
            }
            cmt = _preceding_comment(cursor)
            if cmt:
                struct_entry["comment"] = cmt
            data_dictionary[qn] = struct_entry
            # Incremental (M1.2): type hash keyed by qn; a definition wins over a forward decl.
            if cursor.is_definition() or qn not in entity_hashes:
                entity_hashes[qn] = hash_cursor(cursor, comment=struct_entry.get("comment", ""))
            _type_keys.add(qn)  # M1.2b: known project type (edges.json filter target)
            entity_files[qn] = rel_file  # M4.3: defining file for the narrowed-parse merge
            # Also add typedef entry when this struct participates in a 'typedef struct { ... } Name;' pattern.
            if cursor.kind == cindex.CursorKind.STRUCT_DECL and cursor.spelling:
                _maybe_add_typedef_for_struct(name, qn, loc, rel_file)

    elif cursor.kind == cindex.CursorKind.ENUM_DECL:
        key = _get_type_key(cursor)
        enumerators = []
        for child in cursor.get_children():
            if child.kind == cindex.CursorKind.ENUM_CONSTANT_DECL:
                val = child.enum_value if hasattr(child, "enum_value") else None
                enum_entry: dict = {"name": child.spelling, "value": val}
                cmt = _inline_comment(child)
                if cmt:
                    enum_entry["comment"] = cmt
                enumerators.append(enum_entry)
        name = cursor.spelling or "(anonymous)"
        qn = get_qualified_name(cursor) if cursor.spelling else f"(anonymous)@{key}"
        underlying = cursor.type.spelling if cursor.type else ""
        vals = [e["value"] for e in enumerators if e["value"] is not None]
        enum_range = f"{min(vals)}-{max(vals)}" if vals else "NA"
        enum_dict: dict = {
            "kind": "enum",
            "name": name,
            "qualifiedName": qn,
            "underlyingType": underlying,
            "enumerators": enumerators,
            "range": enum_range,
            "location": loc,
        }
        cmt = _preceding_comment(cursor)
        if cmt:
            enum_dict["comment"] = cmt
        data_dictionary[qn] = enum_dict
        # Incremental (M1.2): enum hash keyed by qn; a definition wins over a forward decl.
        if cursor.is_definition() or qn not in entity_hashes:
            entity_hashes[qn] = hash_cursor(cursor, comment=enum_dict.get("comment", ""))
        _type_keys.add(qn)  # M1.2b
        entity_files[qn] = rel_file  # M4.3

    elif cursor.kind == cindex.CursorKind.TYPEDEF_DECL:
        if cursor.spelling:
            qn = get_qualified_name(cursor)
            underlying = _typedef_underlying(cursor)
            # If an enum already exists with the same name, keep it (enum has range),
            # but ALSO store the typedef as a separate entry (unique key) so it can appear in views.
            key = qn
            if qn in data_dictionary and data_dictionary[qn].get("kind") == "enum":
                key = f"typedef@{qn}:{rel_file}:{loc.get('line', '')}"
            # Range from the canonical type (exact, target-aware); the name table is
            # only consulted when libclang has no answer — e.g. a typedef of a struct.
            _td_range = _range_from_clang_type(cursor.underlying_typedef_type)
            if _td_range == "NA":
                _td_range = get_range_for_type(underlying or "")
            _register_builtin_range(cursor.underlying_typedef_type)
            typedef_dict: dict = {
                "kind": "typedef",
                "name": cursor.spelling,
                "qualifiedName": qn,
                "underlyingType": underlying or "(opaque)",
                "range": _td_range,
                "location": loc,
            }
            cmt = _preceding_comment(cursor)
            if cmt:
                typedef_dict["comment"] = cmt
            data_dictionary[key] = typedef_dict
            # Incremental (M1.2): typedef hash keyed by qn; don't clobber a struct/enum
            # definition's hash that already owns this qn (e.g. typedef of a named enum).
            entity_hashes.setdefault(qn, hash_cursor(cursor, comment=typedef_dict.get("comment", "")))
            _type_keys.add(qn)  # M1.2b
            entity_files[qn] = rel_file  # M4.3

    for child in cursor.get_children():
        visit_type_definitions(child)


def _get_var_init_value(cursor):
    """Extract initializer value from VAR_DECL cursor. Returns string or None."""
    try:
        if cursor.kind != cindex.CursorKind.VAR_DECL:
            return None
        if not cursor.location.file:
            return None
        with open(cursor.location.file.name, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        line_num = cursor.location.line
        if line_num < 1 or line_num > len(lines):
            return None
        line = lines[line_num - 1]
        idx = line.find("=")
        if idx < 0:
            return None
        value = line[idx + 1:].strip().rstrip(";").strip()
        return value if value else None
    except (OSError, IOError):
        return None


def _extent_source_text(cursor):
    """Return source text covered by cursor.extent (multi-line safe)."""
    try:
        start = cursor.extent.start
        end = cursor.extent.end
        if not start.file or not end.file:
            return None
        path = start.file.name
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        sline, eline = start.line, end.line
        if sline < 1 or eline > len(lines) or sline > eline:
            return None
        if sline == eline:
            row = lines[sline - 1]
            a = max(0, start.column - 1)
            b = end.column - 1 if end.column else len(row)
            b = min(len(row), max(a, b))
            return row[a:b]
        parts = []
        parts.append(lines[sline - 1][max(0, start.column - 1) :])
        for ln in range(sline + 1, eline):
            parts.append(lines[ln - 1])
        last = lines[eline - 1]
        ec = end.column - 1 if end.column else len(last)
        parts.append(last[: max(0, ec)])
        return "".join(parts)
    except (OSError, IOError, TypeError, ValueError):
        return None


def _strip_implicit_cast(cursor):
    c = cursor
    while "IMPLICIT_CAST" in _cursor_kind_name(c):
        ch = list(c.get_children())
        if len(ch) != 1:
            break
        c = ch[0]
    return c


def _cursor_kind_name(cursor):
    try:
        return str(cursor.kind).split(".")[-1] if cursor.kind else ""
    except Exception:
        return ""


def _var_decl_init_args_cursors(cursor):
    """Sub-expressions that Clang attaches as the '(a,b)' part of a mis-parsed 'T name(a,b)'."""
    for ch in cursor.get_children():
        kn = _cursor_kind_name(ch)
        subs = list(ch.get_children())
        if kn == "PAREN_EXPR":
            return subs
        if kn == "CALL_EXPR":
            return subs
        if kn == "CXX_FUNCTIONAL_CAST_EXPR":
            return subs
        if kn == "CXX_PAREN_LIST_INIT_EXPR":
            return subs
        if kn == "CXX_CONSTRUCT_EXPR" or ("CONSTRUCT" in kn and "DESTRUCT" not in kn):
            return subs
    # e.g. UNIT _SOME_FUNCTION(VOID) -> TYPE_REF + UNEXPOSED_EXPR(DECL_REF_EXPR VOID)
    args = []
    for ch in cursor.get_children():
        kn = _cursor_kind_name(ch)
        if kn == "TYPE_REF":
            continue
        if kn == "UNEXPOSED_EXPR":
            for sub in ch.get_children():
                args.append(sub)
    return args


def _var_decl_init_args_are_only_decl_refs(cursor):
    """True when (a,b) style init uses only identifier references — typical mis-parse of param list."""
    args = _var_decl_init_args_cursors(cursor)
    if not args:
        return False
    for a in args:
        leaf = _strip_implicit_cast(a)
        if leaf.kind != cindex.CursorKind.DECL_REF_EXPR:
            return False
    return True


def _var_decl_should_record_as_function_not_global(cursor):
    """Clang may emit VAR_DECL for 'T name(id1)' when (id1) is read as ctor init, not parameters."""
    if cursor.kind != cindex.CursorKind.VAR_DECL:
        return False
    text = _extent_source_text(cursor)
    if not text or "=" in text:
        return False
    name = cursor.spelling
    if not name:
        return False
    if not re.search(r"\b" + re.escape(name) + r"\s*\(", text):
        return False
    return _var_decl_init_args_are_only_decl_refs(cursor)


def visit_definitions(cursor):
    is_function = cursor.kind in (cindex.CursorKind.FUNCTION_DECL, cindex.CursorKind.CXX_METHOD)
    is_global_var = (
        cursor.kind == cindex.CursorKind.VAR_DECL
        and cursor.location.file
        and is_project_file(cursor.location.file.name)
        and cursor.semantic_parent
        and cursor.semantic_parent.kind in (cindex.CursorKind.TRANSLATION_UNIT, cindex.CursorKind.NAMESPACE)
    )

    if is_function and cursor.is_definition() and cursor.location.file and is_project_file(cursor.location.file.name):
        func_key = get_function_key(cursor)

        # Skip if already visited (from header included in another translation unit)
        if func_key in _visited_function_keys:
            for child in cursor.get_children():
                visit_definitions(child)
            return

        # Mark as visited
        _visited_function_keys.add(func_key)
        # Record virtual override -> base relations for the D7 virtual-dispatch
        # over-approximation (build_metadata spreads caller edges across the family).
        # Queried via the C API on the canonical decl (out-of-line defs report none).
        if cursor.kind == cindex.CursorKind.CXX_METHOD and _clang_overridden is not None:
            try:
                for _base in _clang_overridden(cursor):
                    _bkey = get_function_key(_base)
                    if _bkey:
                        _override_pairs.append((func_key, _bkey))
            except Exception:
                pass
        func_id = f"{cursor.location.file.name}:{cursor.location.line}"
        component_name = get_component_name(cursor.location.file.name)
        params = []
        try:
            for arg in cursor.get_arguments():
                # Seed the dictionary with this builtin's measured range, so the view's
                # name lookup resolves it exactly (see _register_builtin_range).
                _register_builtin_range(arg.type)
                params.append({"name": arg.spelling or "", "type": arg.type.spelling if arg.type else ""})
        except Exception:
            pass
        try:
            _register_builtin_range(cursor.result_type)
        except Exception:
            pass

        end_line = cursor.location.line
        try:
            if cursor.extent.end.file and cursor.extent.end.file.name == cursor.location.file.name:
                end_line = cursor.extent.end.line
        except Exception:
            pass

        fk = get_function_key(cursor)
        entry = {
            "functionId": func_id,
            "functionName": cursor.spelling,
            "qualifiedName": get_qualified_name(cursor),
            "className": get_class_scope(cursor),
            "mangledName": cursor.mangled_name or "",
            "componentName": component_name,
            "parameters": params,
            "returnType": cursor.result_type.spelling if cursor.result_type else "",
            "endLine": end_line,
            "visibility": _detect_visibility(cursor.location.file.name, cursor.location.line),
            "description": _preceding_comment(cursor),
        }
        # Incremental (M1.2): token hash of the body + doc comment, for output reuse.
        entry["_sourceHash"] = hash_cursor(cursor, comment=entry["description"])
        if cursor.is_definition():
            functions[fk] = entry
            if fk not in function_to_component:
                component_functions[component_name].append(fk)
                function_to_component[fk] = component_name
        elif fk not in functions:
            # Forward declaration only (e.g. "VOID _f(VOID);" with no body in this TU)
            entry["declarationOnly"] = True
            functions[fk] = entry
            component_functions[component_name].append(fk)
            function_to_component[fk] = component_name

    elif is_global_var and cursor.spelling and cursor.location.file:
        if _var_decl_should_record_as_function_not_global(cursor):
            func_id = f"{cursor.location.file.name}:{cursor.location.line}"
            component_name = get_component_name(cursor.location.file.name)
            params = []
            for a in _var_decl_init_args_cursors(cursor):
                leaf = _strip_implicit_cast(a)
                if leaf.kind == cindex.CursorKind.DECL_REF_EXPR and leaf.referenced:
                    ref = leaf.referenced
                    params.append({
                        "name": ref.spelling or "",
                        "type": ref.type.spelling if ref.type else "",
                    })
                else:
                    params.append({"name": "", "type": leaf.type.spelling if leaf.type else ""})
            end_line = cursor.location.line
            try:
                if cursor.extent.end.file and cursor.extent.end.file.name == cursor.location.file.name:
                    end_line = cursor.extent.end.line
            except Exception:
                pass
            fk = get_function_key(cursor)
            functions[fk] = {
                "functionId": func_id,
                "functionName": cursor.spelling,
                "qualifiedName": get_qualified_name(cursor),
                "mangledName": "",
                "componentName": component_name,
                "parameters": params,
                "returnType": cursor.type.spelling if cursor.type else "",
                "endLine": end_line,
                "syntheticFromVarDecl": True,
                "visibility": _detect_visibility(cursor.location.file.name, cursor.location.line),
                "_sourceHash": hash_cursor(cursor),
            }
            component_functions[component_name].append(fk)
            function_to_component[fk] = component_name
        else:
            var_id = f"{cursor.location.file.name}:{cursor.location.line}"
            value_str = _get_var_init_value(cursor)
            _register_builtin_range(cursor.type)
            globals_data[var_id] = {
                "variableId": var_id,
                "variableName": cursor.spelling,
                "qualifiedName": get_qualified_name(cursor),
                "className": get_class_scope(cursor),
                "componentName": get_component_name(cursor.location.file.name),
                "type": cursor.type.spelling if cursor.type else "",
                "visibility": _detect_visibility(cursor.location.file.name, cursor.location.line),
                "_sourceHash": hash_cursor(cursor),
            }
            if value_str:
                globals_data[var_id]["value"] = value_str

    for child in cursor.get_children():
        visit_definitions(child)


# Assignment-like operators: LHS is written. Compound (+= etc) = both read and write.
_ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="}


def _is_assign_op(cursor):
    if cursor.kind != cindex.CursorKind.BINARY_OPERATOR:
        return False, False
    try:
        tokens = list(cursor.get_tokens())
        # Tokens: [LHS, op, RHS] or [LHS, +, =, RHS] for +=
        if len(tokens) >= 2:
            op = tokens[1].spelling
            if op == "=":
                return True, False  # pure write
            if op in _ASSIGN_OPS:
                return True, True   # compound = both
            # Tokenized as separate: + and = -> +=
            if len(tokens) >= 3:
                combined = tokens[1].spelling + tokens[2].spelling
                if combined in _ASSIGN_OPS:
                    return True, True
    except Exception:
        pass
    return False, False


def _is_inc_dec_op(cursor):
    if cursor.kind != cindex.CursorKind.UNARY_OPERATOR:
        return False
    try:
        tokens = list(cursor.get_tokens())
        if tokens:
            return tokens[0].spelling in ("++", "--")
    except Exception:
        pass
    return False


def visit_global_access(cursor, current_key=None, is_write=False, is_compound=False):
    """Track global variable reads/writes per function for In/Out direction."""
    kind = cursor.kind

    if kind in (cindex.CursorKind.FUNCTION_DECL, cindex.CursorKind.CXX_METHOD):
        if cursor.is_definition() and cursor.location.file and is_project_file(cursor.location.file.name):
            func_key = get_function_key(cursor)
            outer_key = current_key
            if func_key in _visited_global_access_keys:
                return
            _visited_global_access_keys.add(func_key)
            for child in cursor.get_children():
                visit_global_access(child, func_key, False, False)
            # Propagate inner writes to outer function so outer becomes "In"
            if outer_key:
                for v in global_access_writes.get(func_key, set()):
                    global_access_writes[outer_key].add(v)
            return
        is_write = False
        is_compound = False
    elif kind == cindex.CursorKind.BINARY_OPERATOR:
        pure_write, compound = _is_assign_op(cursor)
        if pure_write or compound:
            children = list(cursor.get_children())
            if len(children) >= 2:
                visit_global_access(children[0], current_key, is_write=True, is_compound=compound)
                visit_global_access(children[1], current_key, is_write=False, is_compound=False)
            return
    elif kind == cindex.CursorKind.COMPOUND_ASSIGNMENT_OPERATOR:
        # +=, -=, etc: LHS is both read and write
        children = list(cursor.get_children())
        if len(children) >= 2:
            visit_global_access(children[0], current_key, is_write=True, is_compound=True)
            visit_global_access(children[1], current_key, is_write=False, is_compound=False)
        return
    elif kind == cindex.CursorKind.UNARY_OPERATOR:
        if _is_inc_dec_op(cursor):
            for child in cursor.get_children():
                visit_global_access(child, current_key, is_write=True, is_compound=False)
            return
    elif kind == cindex.CursorKind.RETURN_STMT and current_key:
        # Capture first return expression as text (e.g. 'release_status')
        if current_key not in function_return_expr:
            try:
                tokens = [t.spelling for t in cursor.get_tokens()]
                expr = " ".join(t for t in tokens if t not in ("return", ";")).strip()
                if expr:
                    function_return_expr[current_key] = expr
            except Exception:
                pass
    elif kind == cindex.CursorKind.DECL_REF_EXPR and current_key:
        ref = cursor.referenced
        if ref and ref.kind == cindex.CursorKind.VAR_DECL:
            par = ref.semantic_parent
            if par and par.kind in (cindex.CursorKind.TRANSLATION_UNIT, cindex.CursorKind.NAMESPACE):
                if ref.location.file and is_project_file(ref.location.file.name):
                    var_id = f"{ref.location.file.name}:{ref.location.line}"
                    if var_id in globals_data:
                        if is_write:
                            global_access_writes[current_key].add(var_id)
                            if is_compound:
                                global_access_reads[current_key].add(var_id)
                        else:
                            global_access_reads[current_key].add(var_id)
        return

    for child in cursor.get_children():
        visit_global_access(child, current_key, is_write, is_compound)


def visit_calls(cursor, current_key=None):
    if cursor.kind in (cindex.CursorKind.FUNCTION_DECL, cindex.CursorKind.CXX_METHOD):
        if cursor.is_definition() and cursor.location.file and is_project_file(cursor.location.file.name):
            func_key = get_function_key(cursor)
            # Skip if already visited (from header included in another translation unit)
            if func_key in _visited_call_keys:
                for child in cursor.get_children():
                    visit_calls(child, current_key)
                return
            # Mark as visited
            _visited_call_keys.add(func_key)
            current_key = func_key
    elif cursor.kind == cindex.CursorKind.CALL_EXPR and current_key:
        called_key = None
        if cursor.referenced:
            called_key = get_function_key(cursor.referenced)
            # M4.4 narrowed parse: a callee defined in an UN-parsed file isn't in `functions`;
            # accept it if the baseline knows it (so cross-TU call edges survive). For a full
            # parse `_baseline_func_keys` is empty, so this is unchanged.
            if called_key not in functions and called_key not in _baseline_func_keys:
                called_key = None
        if not called_key:
            for k in functions:
                if functions[k]["functionName"] == cursor.spelling:
                    called_key = k
                    break
        if called_key and (called_key in functions or called_key in _baseline_func_keys):
            # Use list to preserve insertion order, but avoid duplicates
            if called_key not in call_graph[current_key]:
                call_graph[current_key].append(called_key)
            if current_key not in reverse_call_graph[called_key]:
                reverse_call_graph[called_key].append(current_key)

    for child in cursor.get_children():
        visit_calls(child, current_key)


def _project_type_qn(t):
    """Given a clang Type, return the qualified name of the underlying *project*
    type declaration (struct/class/enum/typedef), stripping pointer/reference/array
    layers; or None if it isn't a named project type. Used to build typeUsers."""
    if t is None:
        return None
    try:
        for _ in range(10):  # peel pointer/ref/array layers to reach the named type
            k = t.kind
            if k == cindex.TypeKind.POINTER:
                t = t.get_pointee()
            elif k in (cindex.TypeKind.LVALUEREFERENCE, cindex.TypeKind.RVALUEREFERENCE):
                t = t.get_pointee()
            elif k in (cindex.TypeKind.CONSTANTARRAY, cindex.TypeKind.INCOMPLETEARRAY,
                       cindex.TypeKind.VARIABLEARRAY, cindex.TypeKind.DEPENDENTSIZEDARRAY):
                t = t.get_array_element_type()
            else:
                break
        decl = t.get_declaration()
        if decl and decl.kind in (cindex.CursorKind.STRUCT_DECL, cindex.CursorKind.CLASS_DECL,
                                  cindex.CursorKind.ENUM_DECL, cindex.CursorKind.TYPEDEF_DECL):
            if decl.location.file and is_project_file(decl.location.file.name):
                return get_qualified_name(decl)
    except Exception:
        return None
    return None


def _record_type_use(t, func_key):
    qn = _project_type_qn(t)
    if qn:
        type_users[qn].add(func_key)


def visit_usage(cursor, current_key=None):
    """Collect per-function TYPE usage (AST) + identifier tokens (for MACRO usage).
    Mirrors visit_calls: threads current_key for the enclosing function so usage is
    attributed to it. Macro matching is done later (in main) once #defines are known."""
    k = cursor.kind
    if k in (cindex.CursorKind.FUNCTION_DECL, cindex.CursorKind.CXX_METHOD):
        if cursor.is_definition() and cursor.location.file and is_project_file(cursor.location.file.name):
            fkey = get_function_key(cursor)
            if fkey in _visited_usage_keys:
                for child in cursor.get_children():
                    visit_usage(child, current_key)
                return
            _visited_usage_keys.add(fkey)
            current_key = fkey
            # Signature types (return + parameters).
            _record_type_use(cursor.result_type, current_key)
            try:
                for arg in cursor.get_arguments():
                    _record_type_use(arg.type, current_key)
            except Exception:
                pass
            # Identifier tokens over the function extent, for later macro-name matching.
            try:
                function_tokens[fkey] = {
                    t.spelling for t in cursor.get_tokens()
                    if t.kind == cindex.TokenKind.IDENTIFIER
                }
            except Exception:
                function_tokens[fkey] = set()
    elif current_key:
        if k == cindex.CursorKind.TYPE_REF:
            _record_type_use(cursor.type, current_key)
        elif k == cindex.CursorKind.VAR_DECL:
            _record_type_use(cursor.type, current_key)

    for child in cursor.get_children():
        visit_usage(child, current_key)


def _capture_tu_includes(tu, path):
    """M4.0: record this TU's in-repo transitive include closure (doc 04 §11.2).
    Best-effort — must never break parsing if libclang has no inclusion info."""
    try:
        inc_paths = []
        for fi in tu.get_includes():
            inc = getattr(fi, "include", None)
            name = getattr(inc, "name", None)
            if name:
                inc_paths.append(name)
        src_rel = to_repo_relative(path, MODULE_BASE_PATH)
        if src_rel is not None:
            tu_includes[src_rel] = build_closure(path, inc_paths, MODULE_BASE_PATH)
    except Exception as e:  # pragma: no cover - defensive
        print(f"include-closure capture failed for {path}: {e}")


def _collect_macro_defs(tu_cursor):
    """Record the source line(s) of each macro libclang's preprocessor actually
    defined — i.e. the *active* #if/#else branch only (inactive branches are not
    compiled, so they never appear here). _scan_defines uses this to drop
    inactive-branch #define duplicates. Project files only; built-in/system
    macros (location.file is None or non-project) are ignored."""
    for cur in tu_cursor.get_children():
        if cur.kind != cindex.CursorKind.MACRO_DEFINITION:
            continue
        f = cur.location.file
        if f is None or not is_project_file(f.name):
            continue
        try:
            rel = os.path.relpath(f.name, MODULE_BASE_PATH).replace("\\", "/")
        except ValueError:
            rel = f.name.replace("\\", "/")
        _active_macro_lines.setdefault((cur.spelling, rel), set()).add(cur.location.line)


def parse_file(path):
    try:
        tu = index.parse(path, args=clang_args_for(path), options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)
        _capture_tu_includes(tu, path)  # incremental (M4.0): per-TU include closure
        visit_definitions(tu.cursor)
        visit_type_definitions(tu.cursor)
        visit_usage(tu.cursor)  # incremental (M1.2b): type/macro usage on the same TU
        _collect_macro_defs(tu.cursor)  # active #if/#else macro branch (for _scan_defines)
    except cindex.TranslationUnitLoadError as e:
        print(f"Failed: {path}: {e}")


def parse_calls(path):
    try:
        tu = index.parse(path, args=clang_args_for(path), options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)
        visit_calls(tu.cursor)
    except cindex.TranslationUnitLoadError:
        pass


def parse_global_access(path):
    """Collect global read/write per function for direction (In/Out)."""
    try:
        tu = index.parse(path, args=CLANG_ARGS, options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)
        visit_global_access(tu.cursor)
    except cindex.TranslationUnitLoadError:
        pass


def build_metadata():
    base_path = os.path.abspath(MODULE_BASE_PATH)
    # D7 virtual-dispatch over-approximation: link callers of any virtual-family member
    # to ALL members, so a call that may dynamically dispatch to any override impacts the
    # whole family (never stale) and calledByIds is accurate. Must run before the
    # call_graph -> calledByIds/callsIds mapping below.
    _n_edges, _n_fams = spread_virtual_families(call_graph, reverse_call_graph,
                                                _override_pairs, set(functions))
    if _n_edges:
        print(f"  virtual-dispatch: linked {_n_edges} caller->override edge(s) across "
              f"{_n_fams} family(ies)")
    functions_dict = {}
    global_variables_dict = {}

    # Map internal function keys -> final functionIds (model keys) so we can expose precise call relationships
    func_key_to_fid = {}

    for func_key, f in functions.items():
        file_path = f["functionId"].rsplit(":", 1)[0]
        try:
            rel_file = os.path.relpath(file_path, base_path).replace("\\", "/")
        except ValueError:
            rel_file = file_path.replace("\\", "/")
        fid = make_function_key(f["componentName"], rel_file, f["qualifiedName"], f["parameters"])
        func_key_to_fid[func_key] = fid
        _func_key_to_fid[func_key] = fid  # incremental (M1.2b): for edges.json remap
        entity_hashes[fid] = f.get("_sourceHash", "")  # incremental (M1.2)
        entity_files[fid] = rel_file  # M4.3: defining file for the narrowed-parse merge
        functions_dict[fid] = {
            "qualifiedName": f["qualifiedName"],
            "location": {
                "file": rel_file,
                "line": int(f["functionId"].rsplit(":", 1)[1]),
                "endLine": f.get("endLine", int(f["functionId"].rsplit(":", 1)[1])),
            },
            "params": f["parameters"],
            "returnType": f.get("returnType", ""),
            "description": f.get("description", ""),
        }
        functions_dict[fid]["visibility"] = f.get("visibility", "default")
        if f.get("className"):
            functions_dict[fid]["className"] = f["className"]
        if f.get("syntheticFromVarDecl"):
            functions_dict[fid]["syntheticFromVarDecl"] = True
        if f.get("declarationOnly"):
            functions_dict[fid]["declarationOnly"] = True
        # Attach first return expression text if available (for behaviour output naming)
        ret_expr = function_return_expr.get(func_key)
        if ret_expr:
            functions_dict[fid]["returnExpr"] = ret_expr

    # Build globalVariables model entries and map raw var ids to model keys
    var_id_to_vid = {}
    for var_id, g in globals_data.items():
        file_path = var_id.rsplit(":", 1)[0]
        try:
            rel_file = os.path.relpath(file_path, base_path).replace("\\", "/")
        except ValueError:
            rel_file = file_path.replace("\\", "/")
        vid = make_global_key(rel_file, g["qualifiedName"])
        var_id_to_vid[var_id] = vid
        entity_hashes[vid] = g.get("_sourceHash", "")  # incremental (M1.2)
        entity_files[vid] = rel_file  # M4.3: defining file for the narrowed-parse merge
        g_entry = {
            "qualifiedName": g["qualifiedName"],
            "location": {"file": rel_file, "line": int(var_id.rsplit(":", 1)[1])},
            "type": g["type"],
        }
        if g.get("value"):
            g_entry["value"] = g["value"]
        g_entry["visibility"] = g.get("visibility", "default")
        if g.get("className"):
            g_entry["className"] = g["className"]
        global_variables_dict[vid] = g_entry

    # M4.4 narrowed parse: cross-TU callees live in files we did NOT re-parse, so they
    # aren't in func_key_to_fid yet — add the baseline's mapping so their edges resolve to
    # the right fid. (No-op for a full parse: _baseline_func_keys is empty.)
    for _bk, _bfid in _baseline_func_keys.items():
        func_key_to_fid.setdefault(_bk, _bfid)
        _func_key_to_fid.setdefault(_bk, _bfid)

    # M4.6: fid-level override->base pairs for the narrowed-parse virtual re-spread. base is
    # its fid when defined, else its (stable) mangled key as a grouping token.
    _override_pairs_fid.clear()
    for _ov_fk, _base_fk in _override_pairs:
        _ov_fid = func_key_to_fid.get(_ov_fk)
        if _ov_fid:
            _override_pairs_fid.append([_ov_fid, func_key_to_fid.get(_base_fk, _base_fk)])

    # Add precise caller/callee ids, global read/write ids and direction (In/Out) from global read/write analysis
    for func_key, f in functions.items():
        fid = func_key_to_fid.get(func_key)
        if not fid:
            continue
        called_ids = [
            func_key_to_fid[c]
            for c in reverse_call_graph.get(func_key, [])
            if c in func_key_to_fid
        ]
        calls_ids = [
            func_key_to_fid[c]
            for c in call_graph.get(func_key, [])
            if c in func_key_to_fid
        ]
        functions_dict[fid]["calledByIds"] = called_ids
        functions_dict[fid]["callsIds"] = calls_ids

        # Map raw global var ids to model keys for reads/writes
        read_raw = global_access_reads.get(func_key, set())
        write_raw = global_access_writes.get(func_key, set())
        read_vids = sorted({var_id_to_vid[v] for v in read_raw if v in var_id_to_vid})
        write_vids = sorted({var_id_to_vid[v] for v in write_raw if v in var_id_to_vid})
        if read_vids:
            functions_dict[fid]["readsGlobalIds"] = read_vids
        if write_vids:
            functions_dict[fid]["writesGlobalIds"] = write_vids

        # Direction: Get=Out, Set=In, both=In. No direct global access -> In.
        if write_raw:
            functions_dict[fid]["direction"] = "In"
        else:
            functions_dict[fid]["direction"] = "Out"

    return {
        "version": 1,
        "basePath": base_path,
        "projectName": PROJECT_NAME,
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "functions": functions_dict,
        "globalVariables": global_variables_dict,
    }


def _collect_source_files():
    # Parse .cpp translation units first, then headers (3.2). Symbols declared in a header and
    # defined in a .cpp are already captured during the .cpp parse (its #include pulls the header
    # into the TU); parsing headers as their own TUs additionally captures header-only definitions
    # (inline functions / header-only components) that no parsed .cpp includes. Headers go LAST so a
    # full-context .cpp definition wins the dedup (stable mangled func_key / _visited_usage_keys) and
    # standalone header parses only ADD what was otherwise missing.
    sources, headers = [], []
    for root, _, fnames in os.walk(MODULE_BASE_PATH):
        for f in fnames:
            if f.endswith((".cpp", ".cc", ".cxx")):
                bucket = sources
            elif f.endswith((".h", ".hpp", ".hxx")):
                bucket = headers
            else:
                continue
            path = os.path.join(root, f)
            if is_project_file(path):
                bucket.append(path)
    return sources + headers


def _restrict_to_only_files(source_files):
    """Narrowed parse (M4.3): keep only the TUs listed in --only-files (repo-relative,
    one per line). Matched against the collected absolute paths (case-insensitive)."""
    try:
        with open(_only_files_path, "r", encoding="utf-8") as fh:
            wanted = {
                os.path.normcase(os.path.abspath(os.path.join(MODULE_BASE_PATH, ln.strip())))
                for ln in fh if ln.strip()
            }
    except OSError:
        return source_files
    return [p for p in source_files if os.path.normcase(os.path.abspath(p)) in wanted]


def _collect_define_files():
    """Files to scan for #define (includes headers)."""
    exts = (".cpp", ".cc", ".cxx", ".h", ".hpp")
    files = []
    for root, _, fnames in os.walk(MODULE_BASE_PATH):
        for f in fnames:
            if f.endswith(exts):
                path = os.path.join(root, f)
                if is_project_file(path):
                    files.append(path)
    return files


def _scan_defines():
    """Populate data_dictionary with kind=define entries from #define lines.

    When one macro name is #defined more than once in a file (e.g. one per
    #if/#else branch), the textual scan alone would emit *every* branch. Pass 2
    keeps only the branch libclang's preprocessor actually took — the active
    line(s) collected in `_active_macro_lines` during parse_file. On any
    ambiguity (no libclang info for the name, or none of the textual lines match)
    all definitions are kept, so a macro is never lost.
    """
    files = _collect_define_files()
    grouped = {}  # (name, rel_file) -> list of entry dicts, in declaration order
    for path in files:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except (OSError, IOError):
            continue
        try:
            rel_file = os.path.relpath(path, MODULE_BASE_PATH).replace("\\", "/")
        except ValueError:
            rel_file = path.replace("\\", "/")
        i = 0
        n = len(lines)
        while i < n:
            raw = lines[i]
            i += 1
            stripped = raw.lstrip()
            if not stripped.startswith("#define"):
                continue
            line_no = i
            # Collect continuation lines ending with backslash
            macro_lines = [raw.rstrip("\n")]
            while macro_lines[-1].rstrip().endswith("\\") and i < n:
                macro_lines.append(lines[i].rstrip("\n"))
                i += 1
            full = "\n".join(macro_lines).strip()
            # Parse "#define NAME [value...]". Join continuation lines into one
            # logical line (drop the trailing "\") so a multi-line macro's value
            # is captured in full, not just its first line.
            logical = " ".join(
                ml.rstrip().rstrip("\\").strip() for ml in macro_lines
            ).strip()
            after = logical[len("#define"):].strip()
            if not after:
                continue
            parts = after.split(None, 1)
            name = parts[0]
            value = parts[1].strip() if len(parts) > 1 else ""
            grouped.setdefault((name, rel_file), []).append(
                {"line": line_no, "value": value, "full": full}
            )

    for (name, rel_file), entries in grouped.items():
        chosen = entries
        if len(entries) > 1:
            # Same macro defined on multiple lines in one file = conditional
            # (#if/#else) branches. Keep only the branch libclang compiled;
            # fall back to all if libclang can't disambiguate (never drop all).
            active = _active_macro_lines.get((name, rel_file))
            if active:
                matching = [e for e in entries if e["line"] in active]
                if matching:
                    chosen = matching
        for e in chosen:
            key = f"{name}@{rel_file}:{e['line']}"
            data_dictionary[key] = {
                "kind": "define",
                "name": name,
                "qualifiedName": name,
                "value": e["value"],
                "text": e["full"],
                "location": {"file": rel_file, "line": e["line"]},
            }
            # Incremental (M1.2): macro hash keyed by the line-stable `name@relFile`
            # (matches edges.json macroUsers; avoids false "changed" when a macro
            # shifts lines). Last definition of a name in a file wins.
            entity_hashes[f"{name}@{rel_file}"] = hash_macro_text(e["full"])
            _macro_keys.add(f"{name}@{rel_file}")  # M1.2b: known macro (edges.json)
            entity_files[f"{name}@{rel_file}"] = rel_file  # M4.3


def _format_csv_merge_report(matched_names, new_names, orphan_children, *, limit=10):
    """Lines telling the CSV author which rows actually landed on a parsed type.

    "new, not found in source" is the one that matters: a typo'd or renamed type is
    silently added as its own entry, so without this it looks exactly like a
    successful override while the real type keeps its old range.
    """
    def _names(names):
        shown = ", ".join(names[:limit])
        return shown + (f", +{len(names) - limit} more" if len(names) > limit else "")

    lines = []
    if matched_names:
        lines.append(f"    {len(matched_names)} matched a parsed type: {_names(matched_names)}")
    if new_names:
        lines.append(f"    {len(new_names)} new, not found in source: {_names(new_names)}")
    if orphan_children:
        lines.append(f"    {orphan_children} child row(s) skipped: no parent Name above them")
    return lines


def _merge_external_data_dictionary(path: str) -> None:
    """Merge a user-authored CSV into the component-level data_dictionary (external wins).

    CSV columns: Name, Kind, EntryName, Range, Comment
    - Name (required for top-level rows): type key in dataDictionary.
    - Kind: typedef/enum/define/struct/class/primitive (default: typedef).
    - EntryName: enumerator name (for Kind=enumerator) or field name (for Kind=field).
    - Range: range string (e.g. 0-255) or numeric value for enumerators.
    - Comment: description.

    Child rows (Kind=enumerator or Kind=field) have an empty Name column —
    the parser carries forward the last non-empty Name as the parent key.
    This matches how Excel merged-cell exports look in CSV.
    """
    if not os.path.isfile(path):
        print(f"[parser] ERROR: data dictionary CSV not found: {path}", file=sys.stderr)
        sys.exit(2)

    try:
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                print(f"[parser] ERROR: data dictionary CSV is empty: {path}", file=sys.stderr)
                sys.exit(2)

            # Normalise header names: strip BOM and whitespace.
            reader.fieldnames = [f.lstrip("﻿").strip() for f in reader.fieldnames]

            parent_key: str | None = None
            merged = 0
            # Which rows actually landed on something the parse found. A row naming a
            # type that does not exist (typo, or a type renamed in the code) is added as
            # a brand-new entry and would otherwise look identical to a successful
            # override — the author would believe it applied.
            matched_names: list = []
            new_names: list = []
            orphan_children = 0

            for row in reader:
                name     = (row.get("Name")      or "").strip()
                kind     = (row.get("Kind")       or "").strip().lower()
                entry_nm = (row.get("EntryName")  or "").strip()
                range_v  = (row.get("Range")      or "").strip()
                comment  = (row.get("Comment")    or "").strip()

                # Child rows: enumerator or field — attach to current parent.
                if not name and kind in ("enumerator", "field"):
                    if parent_key is None or not entry_nm:
                        orphan_children += 1
                        continue
                    entry = data_dictionary.get(parent_key)
                    if entry is None:
                        orphan_children += 1
                        continue
                    if kind == "enumerator":
                        entry.setdefault("enumerators", [])
                        try:
                            val = int(range_v) if range_v else 0
                        except ValueError:
                            val = range_v
                        child = {"name": entry_nm, "value": val}
                        if comment:
                            child["comment"] = comment
                        entry["enumerators"].append(child)
                    else:  # field
                        entry.setdefault("fields", [])
                        child = {"name": entry_nm}
                        if range_v:
                            child["range"] = range_v
                        if comment:
                            child["comment"] = comment
                        entry["fields"].append(child)
                    continue

                # Top-level row: create or update a dictionary entry.
                if not name:
                    continue

                parent_key = name
                kind = kind or "typedef"

                # Start from existing entry so unspecified sub-lists are preserved.
                existing = data_dictionary.get(name, {})
                (matched_names if existing else new_names).append(name)
                entry: dict = dict(existing)
                entry["kind"] = kind
                if range_v:
                    entry["range"] = range_v
                if comment:
                    entry["comment"] = comment
                # Reset enumerators/fields so child rows below append fresh.
                if kind in ("enum",):
                    entry["enumerators"] = []
                if kind in ("struct", "class"):
                    entry["fields"] = []

                data_dictionary[name] = entry
                merged += 1

    except csv.Error as exc:
        print(f"[parser] ERROR: failed to parse data dictionary CSV {path}: {exc}", file=sys.stderr)
        sys.exit(2)

    # Through the logger, not print(): this is the record of whether a client's CSV
    # actually applied, so it has to survive in logs/run_<date>.log rather than
    # scrolling past on the console. (The other Phase 1 summary lines are still
    # print-only.)
    from core.logging_setup import get_logger
    _plog = get_logger("parser")
    _plog.info(f"data dictionary: merged {merged} entries from {os.path.basename(path)}")
    for line in _format_csv_merge_report(matched_names, new_names, orphan_children):
        _plog.info(line.strip())


def main():
    from core.progress import ProgressReporter
    from core.logging_setup import get_logger
    plog = get_logger("parser")
    source_files = _collect_source_files()
    if _only_files_path:
        # Narrowed parse (M4.3): restrict to the listed TUs (repo-relative, one per line).
        source_files = _restrict_to_only_files(source_files)
        plog.info(f"narrowed parse: {len(source_files)} affected TU(s) (--only-files)")
        # M4.4: load the baseline's func-key map so cross-TU calls (to functions defined in
        # files we did NOT re-parse) still produce call edges.
        _bfk = os.environ.get("ANALYZER_BASELINE_FUNCKEYS")
        if _bfk and os.path.isfile(_bfk):
            try:
                with open(_bfk, "r", encoding="utf-8") as _f:
                    _baseline_func_keys.update(json.load(_f))
                plog.info(f"narrowed parse: loaded {len(_baseline_func_keys)} baseline func-keys "
                          f"for cross-TU call resolution")
            except (OSError, ValueError):
                pass
    total = len(source_files)

    p1 = ProgressReporter("parser:parse", total=total, logger=plog)
    p1.start(f"parsing {total} files")
    for path in source_files:
        p1.step()
        parse_file(path)
    p1.done()

    p2 = ProgressReporter("parser:calls", total=total, logger=plog)
    p2.start(f"collecting calls ({total} files)")
    for path in source_files:
        p2.step()
        parse_calls(path)
    p2.done()

    p3 = ProgressReporter("parser:globals", total=total, logger=plog)
    p3.start(f"collecting global access ({total} files)")
    for path in source_files:
        p3.step()
        parse_global_access(path)
    p3.done()

    metadata = build_metadata()
    model_dir = os.path.join(PROJECT_ROOT, "model")
    os.makedirs(model_dir, exist_ok=True)

    base_path = metadata["basePath"]
    meta_header = {
        "basePath": base_path,
        "projectName": metadata["projectName"],
        "generatedAt": metadata["generatedAt"],
        "version": metadata["version"],
    }
    # M4.6: a parse fingerprint over the clang args/std + libclang lib — the narrowed-parse
    # gate compares it to the baseline's and forces a full re-parse on any flag/toolchain change.
    from incremental.fingerprint import parse_fingerprint
    try:
        _toolchain = cindex.conf.get_filename() or ""
    except Exception:
        _toolchain = ""
    meta_header["parseFingerprint"] = parse_fingerprint(CLANG_ARGS, std="", toolchain=str(_toolchain))
    from core.model_io import (write_model_file, METADATA, FUNCTIONS, GLOBALS, DATA_DICTIONARY,
                               HASHES, EDGES, TU_INCLUDES, ENTITY_FILES, FUNC_KEYS, OVERRIDE_PAIRS)
    write_model_file(METADATA, meta_header)
    write_model_file(FUNCTIONS, metadata["functions"])
    write_model_file(GLOBALS, metadata["globalVariables"])
    # Add primitives (name as key). setdefault, NOT assignment: ranges measured from
    # libclang during the parse (_register_builtin_range) are facts about the target
    # and outrank this portable table, which e.g. hardcodes `long` as 32-bit.
    for name, info in PRIMITIVES.items():
        data_dictionary.setdefault(name, {"kind": "primitive", "range": info["range"]})
    # Add defines (kind=define)
    _scan_defines()
    # Merge user-supplied data dictionary CSV (external entries win on conflict).
    if _data_dict_path:
        _merge_external_data_dictionary(_data_dict_path)
    write_model_file(DATA_DICTIONARY, data_dictionary)

    # Incremental (M1.2): entity hash snapshot for change detection.
    # Functions/globals were keyed in build_metadata; types/macros above.
    write_model_file(HASHES, entity_hashes)

    # Incremental (M1.2b): slim type/macro usage index -> model/edges.json.
    # Reverse maps {typeKey/macroKey -> [model fids that use it]}. Calls/globals are
    # NOT here (they live in functions.json); M2's impact BFS reads those from there.
    edges = build_edges(type_users, function_tokens, _type_keys, _macro_keys, _func_key_to_fid)
    write_model_file(EDGES, edges)

    # Incremental (M4.0): per-TU include closure -> model/tu_includes.json. The
    # narrowed-parse engine (M4) intersects this with the git diff to find affected TUs.
    write_model_file(TU_INCLUDES, {k: tu_includes[k] for k in sorted(tu_includes)})

    # Incremental (M4.3): per-entity defining file -> model/entity_files.json. Lets the
    # narrowed-parse merge resolve each entity's file (types/hashes have no inline location).
    write_model_file(ENTITY_FILES, {k: entity_files[k] for k in sorted(entity_files)})

    # Incremental (M4.4): {mangled-func-key -> fid} -> model/func_keys.json. A future
    # narrowed parse loads the baseline's map to resolve calls into UN-parsed files.
    write_model_file(FUNC_KEYS, {k: _func_key_to_fid[k] for k in sorted(_func_key_to_fid)})

    # Incremental (M4.6): fid-level override->base pairs -> model/override_pairs.json, for
    # the narrowed-parse virtual-dispatch re-spread across affected + un-parsed files.
    write_model_file(OVERRIDE_PAIRS, sorted(_override_pairs_fid))

    n_funcs = len(metadata["functions"])
    n_vars = len(metadata["globalVariables"])
    n_types = len(data_dictionary)
    print("  model/metadata.json")
    print(f"  model/functions.json ({n_funcs})")
    print(f"  model/globalVariables.json ({n_vars})")
    kinds = {}
    for t in data_dictionary.values():
        k = t.get("kind", "?")
        kinds[k] = kinds.get(k, 0) + 1
    plural = lambda k: "classes" if k == "class" else k + "s"
    parts = [f"{v} {plural(k)}" for k, v in sorted(kinds.items())]
    print(f"  model/dataDictionary.json ({n_types} types: {', '.join(parts)})")
    print(f"  model/hashes.json ({len(entity_hashes)} entities)")
    print(f"  model/edges.json ({len(edges['typeUsers'])} types used, {len(edges['macroUsers'])} macros used)")
    _n_inc = sum(len(v) for v in tu_includes.values())
    print(f"  model/tu_includes.json ({len(tu_includes)} TUs, {_n_inc} in-repo include edges)")


if __name__ == "__main__":
    main()
