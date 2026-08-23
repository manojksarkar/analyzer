"""Shared helpers."""
import contextlib
import os
import re
import sys
import time
from datetime import datetime, timezone
import platform

# Config loading lives in core.config (these are re-exports for backward
# compatibility with existing call sites that still `from utils import ...`).
from core.config import (  # noqa: E402,F401
    LlmConfigError,
    format_llm_config_banner,
    load_config,
    load_llm_config,
)

# Separator for unique keys (function IDs, global IDs, unit keys). Avoid "/" for path confusion.
KEY_SEP = "|"
os_type = platform.system()

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
    """Path to mermaid-cli mmdc (local node_modules, npm global, or system)."""
    ext = ".cmd" if sys.platform == "win32" else ""
    local = os.path.join(project_root, "node_modules", ".bin", "mmdc" + ext)
    if os.path.isfile(local):
        return local
    # Check npm global prefix on Windows (%APPDATA%\npm\mmdc.cmd)
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            global_mmdc = os.path.join(appdata, "npm", "mmdc.cmd")
            if os.path.isfile(global_mmdc):
                return global_mmdc
    return "mmdc"


# Content-addressed Mermaid->PNG cache (M-A). mmdc is the slow primitive (~5-8s/call);
# identical diagrams (same text + render opts) are rendered once and reused across
# units / components / versions. Lives at <project_root>/.mmdc_cache; content-addressed,
# so it is safe across projects and persists across version runs.
_MMDC_CACHE_DIR = ".mmdc_cache"


def mermaid_cache_key(mermaid: str, *, scale=None, puppeteer: bool = True) -> str:
    import hashlib
    src = f"{mermaid or ''}|scale={scale}|pup={int(bool(puppeteer))}"
    return hashlib.sha256(src.encode("utf-8")).hexdigest()


def _log_render_failure(tool: str, result, *, tail_lines: int = 15) -> None:
    """Report why a renderer failed instead of returning a bare False (doc 09, A0).

    Both renderers already captured stderr and discarded it, so a missing Chromium
    or a bad DOT string surfaced only as a diagram that never appeared. Renders run
    once per diagram, so the tail is kept short — enough to name the cause without
    flooding the log when every render in a run fails the same way.
    """
    text = (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "").strip()
    if not text:
        log(f"{tool} exited with code {getattr(result, 'returncode', '?')} (no output)",
            component="render", err=True)
        return
    lines = text.splitlines()[-tail_lines:]
    log(f"{tool} exited with code {getattr(result, 'returncode', '?')}: "
        + " | ".join(lines), component="render", err=True)


def _run_mmdc(project_root: str, mermaid: str, png_path: str, *,
              scale=None, puppeteer: bool = True, timeout: int = 90) -> bool:
    """Invoke mmdc on `mermaid` -> png_path (writes a temp .mmd it cleans up). Returns
    True iff png_path exists afterward. The single place that shells out to mmdc."""
    import subprocess
    import tempfile
    mmdc = mmdc_path(project_root)
    out_dir = os.path.dirname(png_path) or "."
    os.makedirs(out_dir, exist_ok=True)
    fd, mmd_path = tempfile.mkstemp(suffix=".mmd", dir=out_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(mermaid or "")
        cmd = [mmdc, "-i", mmd_path, "-o", png_path]
        if scale is not None:
            cmd += ["--scale", str(scale)]
        pup = os.path.join(project_root, "engine", "config", "puppeteer-config.json")
        if puppeteer and os.path.isfile(pup):
            cmd += ["-p", pup]
        try:
            if os_type == "Windows":
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False, shell=True)
            else:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            log(f"mmdc could not run: {type(exc).__name__}: {exc}",
                component="render", err=True)
            return False
        if r.returncode != 0:
            _log_render_failure("mmdc", r)
            return False
        return os.path.isfile(png_path)
    finally:
        try:
            os.remove(mmd_path)
        except OSError:
            pass


def render_mermaid_cached(project_root: str, mermaid: str, png_path: str, *,
                          scale=None, puppeteer: bool = True, timeout: int = 90) -> bool:
    """Render `mermaid` to png_path, reusing a content-addressed PNG cache so an identical
    diagram is only ever rendered once. Returns True iff png_path exists afterward. Any
    cache error degrades gracefully to a direct render (never breaks a build)."""
    import shutil
    cache_dir = os.path.join(project_root, _MMDC_CACHE_DIR)
    cache_png = os.path.join(cache_dir, mermaid_cache_key(mermaid, scale=scale, puppeteer=puppeteer) + ".png")
    os.makedirs(os.path.dirname(png_path) or ".", exist_ok=True)
    if os.path.isfile(cache_png):                     # hit -> copy out, no mmdc
        try:
            shutil.copyfile(cache_png, png_path)
            return True
        except OSError:
            pass                                       # fall through to a real render
    ok = _run_mmdc(project_root, mermaid, png_path, scale=scale, puppeteer=puppeteer, timeout=timeout)
    if ok:                                             # populate the cache (best-effort, atomic)
        try:
            os.makedirs(cache_dir, exist_ok=True)
            tmp = f"{cache_png}.{os.getpid()}.tmp"   # PID-unique: see stores._write_json
            shutil.copyfile(png_path, tmp)
            os.replace(tmp, cache_png)
        except OSError:
            pass
    return ok


def safe_filename(s: str) -> str:
    """Filesystem-safe name: spaces -> -, unsafe chars -> _.
    Includes , & ; to avoid Windows cmd parsing issues when paths are passed to mmdc.
    """
    return re.sub(r'[<>:"/\\|?*,&;]', "_", (s or "").replace(" ", "-"))


# Content-addressed Graphviz(DOT)->PNG cache. Flowcharts are rendered with
# Graphviz (viz-js -> SVG -> puppeteer PNG) instead of Mermaid; the render is the
# slow primitive, so identical diagrams are rendered once and reused.
_DOT_CACHE_DIR = ".dot_cache"


def dot_cache_key(dot: str, *, scale=None) -> str:
    import hashlib
    src = f"{dot or ''}|scale={scale}"
    return hashlib.sha256(src.encode("utf-8")).hexdigest()


def _run_dot_render(project_root: str, dot: str, png_path: str, *,
                    scale=2, timeout: int = 90) -> bool:
    """Invoke engine/config/render_dot.mjs on `dot` -> png_path (writes a temp
    .dot it cleans up). Returns True iff png_path exists afterward. The single
    place that shells out to the Node DOT renderer."""
    import subprocess
    import tempfile
    script = os.path.join(project_root, "engine", "config", "render_dot.mjs")
    if not os.path.isfile(script):
        return False
    out_dir = os.path.dirname(png_path) or "."
    os.makedirs(out_dir, exist_ok=True)
    fd, dot_path = tempfile.mkstemp(suffix=".dot", dir=out_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(dot or "")
        cmd = ["node", script, dot_path, png_path, str(scale)]
        try:
            if os_type == "Windows":
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   timeout=timeout, check=False, shell=True)
            else:
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   timeout=timeout, check=False)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            log(f"render_dot.mjs could not run: {type(exc).__name__}: {exc}",
                component="render", err=True)
            return False
        if r.returncode != 0:
            _log_render_failure("render_dot.mjs", r)
            return False
        return os.path.isfile(png_path)
    finally:
        try:
            os.remove(dot_path)
        except OSError:
            pass


def render_dot_cached(project_root: str, dot: str, png_path: str, *,
                      scale=2, timeout: int = 90) -> bool:
    """Render a Graphviz DOT script to png_path, reusing a content-addressed PNG
    cache so an identical diagram is only ever rendered once. Returns True iff
    png_path exists afterward. Any cache error degrades gracefully to a direct
    render (never breaks a build)."""
    import shutil
    cache_dir = os.path.join(project_root, _DOT_CACHE_DIR)
    cache_png = os.path.join(cache_dir, dot_cache_key(dot, scale=scale) + ".png")
    os.makedirs(os.path.dirname(png_path) or ".", exist_ok=True)
    if os.path.isfile(cache_png):                     # hit -> copy out, no render
        try:
            shutil.copyfile(cache_png, png_path)
            return True
        except OSError:
            pass                                       # fall through to a real render
    ok = _run_dot_render(project_root, dot, png_path, scale=scale, timeout=timeout)
    if ok:                                             # populate the cache (best-effort, atomic)
        try:
            os.makedirs(cache_dir, exist_ok=True)
            tmp = f"{cache_png}.{os.getpid()}.tmp"   # PID-unique: see stores._write_json
            shutil.copyfile(png_path, tmp)
            os.replace(tmp, cache_png)
        except OSError:
            pass
    return ok



_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
_CONFIG_CACHE = load_config(_SCRIPT_DIR)  # _SCRIPT_DIR == engine/, which contains config/

# Component mapping cache (initialized at import).
_COMPONENT_OVERRIDES: dict = {}
_GROUP_MAP: dict = {}  # component name -> group name


def init_component_mapping(config: dict) -> None:
    """Initialize component folder mapping used by get_component_name/make_*_key helpers."""
    global _COMPONENT_OVERRIDES, _GROUP_MAP
    cfg = config or {}
    _COMPONENT_OVERRIDES = cfg.get("components") or cfg.get("modules") or {}
    _GROUP_MAP = {}
    if _COMPONENT_OVERRIDES:
        return
    from core.config import get_flat_groups
    groups = get_flat_groups(cfg)
    if not isinstance(groups, dict) or not groups:
        _COMPONENT_OVERRIDES = {}
        return
    merged: dict = {}
    for group_name, grp in groups.items():
        if not isinstance(grp, dict):
            continue
        for component, paths in grp.items():
            _GROUP_MAP.setdefault(component, group_name)
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
    _COMPONENT_OVERRIDES = merged


# Default initialization from on-disk config.
init_component_mapping(_CONFIG_CACHE)

def resolve_group(component: str) -> str:
    """Return the layer group name for a component, or empty string if unknown."""
    return _GROUP_MAP.get(component, "")


def _resolve_component_from_rel(rel_file: str) -> str:
    """Resolve component name for a path relative to the project base."""
    path = rel_file.replace("\\", "/") if rel_file else ""
    if not path:
        return "unknown"

    if _COMPONENT_OVERRIDES:
        for component, paths in _COMPONENT_OVERRIDES.items():
            if not paths:
                continue
            if isinstance(paths, str):
                paths = [paths]
            for folder in paths:
                p = (folder or "").replace("\\", "/").lstrip("./")
                if not p:
                    continue
                if path == p or path.lower().startswith(p.lower() + "/"):
                    return component.replace(" ", "-")
        return "unknown"

    parts = path.split("/")
    return parts[0] if parts and parts[0] else "unknown"


def _path_to_component_unit(rel_file: str) -> tuple:
    """Return (component, unitname) from rel_file. Unitname = filename without extension (no subpath)."""
    path = rel_file.replace("\\", "/") if rel_file else ""
    if not path:
        return "unknown", ""
    component = _resolve_component_from_rel(path)
    parts = path.split("/")
    unitname = os.path.splitext(parts[-1])[0] if parts else ""
    return component, unitname


def make_unit_key(rel_file: str) -> str:
    """Unit unique key: component|unitname (assumes single-name units, no path in key)."""
    component, unitname = _path_to_component_unit(rel_file)
    return f"{component}{KEY_SEP}{unitname}"


def path_from_unit_rel(rel_file: str) -> str:
    """Path without extension (for storing in unit info)."""
    path = (rel_file or "").replace("\\", "/")
    return os.path.splitext(path)[0]


def make_global_key(rel_file: str, full_name: str) -> str:
    """Unique key: component|unitname|qualifiedName."""
    component, unit = _path_to_component_unit(rel_file)
    return f"{component}{KEY_SEP}{unit}{KEY_SEP}{full_name}"


def make_function_key(component: str, rel_file: str, full_name: str, parameters: list) -> str:
    """Unique key: component|unitname|qualifiedName|paramTypes."""
    path = rel_file.replace("\\", "/") if rel_file else ""
    parts = path.split("/")
    if not component and parts:
        component = parts[0]
    _, unit = _path_to_component_unit(rel_file)
    param_types = ",".join((p.get("type") or "").strip() for p in (parameters or []))
    return f"{component}{KEY_SEP}{unit}{KEY_SEP}{full_name}{KEY_SEP}{param_types}"


def short_name(full_name: str) -> str:
    """Last segment after :: (e.g. MyClass::foo -> foo)."""
    return ((full_name or "").split("::")[-1]).strip()


def scoped_name(full_name: str, class_name: str = "") -> str:
    """Class-qualified display name: MyClass::foo, or just foo for a free function.

    Namespaces are dropped — the class is what distinguishes same-named methods in a
    table, and the namespace only makes the cell longer. The class comes from the
    model's `className` (parser.get_class_scope) rather than by splitting full_name,
    which can't be split back into namespace vs class parts.

    Falls back to short_name() when className is absent, so models parsed before
    className existed keep rendering as they did rather than half-qualified.
    """
    base = short_name(full_name)
    cls = (class_name or "").strip()
    return f"{cls}::{base}" if cls and base else base


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


def get_component_name(file_path: str, base_path: str) -> str:
    if not file_path:
        return "unknown"
    try:
        path = file_path if os.path.isabs(file_path) else os.path.join(base_path, file_path)
        if not path_is_under(base_path, path):
            return "unknown"
        abs_base = os.path.normcase(os.path.abspath(base_path))
        abs_path = os.path.normcase(os.path.abspath(path))
        rel = os.path.relpath(abs_path, abs_base).replace("\\", "/")
        return _resolve_component_from_rel(rel)
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
    """Map C++ type to range string for interface tables (VOID, 0-0xFF, NA, etc.).

    Matching is CASE-SENSITIVE, because C++ is: lowercasing made `Size_t` (a
    `{int width; int height;}` struct) indistinguishable from `size_t` and gave it a
    64-bit integer range. A project type that merely resembles a primitive is "NA"
    here and gets answered from the data dictionary instead.
    """
    t = (type_str or "").strip()
    if t == "void" or (t.startswith("void ") and "*" not in t):
        return "VOID"
    base = t.replace("const ", "").replace("volatile ", "").strip()
    if base == "bool":
        return "0-1"
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
    # Exact names only. A substring test here ("size_t" in base) answers for any type
    # whose NAME merely contains it — `Size_t`, `BufSize_t`, `PageSize_t` — declaring a
    # `{int width; int height;}` struct to be a 64-bit integer. This function maps known
    # primitives; anything else is "NA" and gets answered from the data dictionary.
    if base in ("size_t", "std::size_t", "param_size_t") or base.endswith("::size_t"):
        return "0-0xFFFFFFFFFFFFFFFF"
    return "NA"


def _visible_to_layer(entry: dict, layer) -> bool:
    """Whether a dd entry is allowed to answer for `layer`.

    Layers partition: an entry stamped with a DIFFERENT layer is not a worse
    answer, it is the wrong type — a same-named type belonging to someone else.
    An entry with no layer is the global tier (builtins, project-wide CSV) and
    answers for everyone.

    `layer=None` means the caller has no layer context, so nothing is filtered and
    behaviour is exactly what it was before layers existed.
    """
    if layer is None:
        return True
    ent_layer = entry.get("layer")
    return ent_layer is None or ent_layer == layer


def get_range(type_str: str, data_dictionary: dict, layer=None, _depth: int = 0) -> str:
    """Look up range from data dictionary (keyed by name); fallback to get_range_for_type.

    `layer` scopes the lookup: the layer's own entry wins, the global tier answers
    when the layer is silent, and another layer's entry is never consulted. The
    filter is applied at ALL THREE lookup paths below — direct hit, qualifiedName
    scan, and the alias recursion — because rejecting only the direct hit lets the
    scan find the very entry that was just rejected.
    """
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
    # Direct lookup: this layer's own key first (parser writes `name@layer` when a
    # second layer defines a name the bare slot already holds), then the bare name
    # if it is this layer's or global.
    entry = None
    if layer:
        entry = dd.get(f"{base}@{layer}") or dd.get(f"{base_lower}@{layer}")
    if entry is None:
        _cand = dd.get(base) or dd.get(base_lower)
        if _cand is not None and _visible_to_layer(_cand, layer):
            entry = _cand
    if entry:
        r = entry.get("range")
        if r and r != "NA":
            return r
        # A typedef's own `range` is baked at parse time by get_range_for_type(), which
        # never sees the data dictionary — so an alias of a project type is stored as
        # "NA" even when the underlying type has a range (e.g. supplied later by the
        # external CSV). Treat that "NA" as "unknown, keep looking" and resolve the
        # alias chain here, at lookup time, when the dictionary is complete.
        if entry.get("kind") == "typedef" and _depth < 10:
            underlying = entry.get("underlyingType", "")
            # `underlying == base` is the self-referential alias the parser emits for
            # `typedef struct { ... } Name;` (underlyingType is the type's own name);
            # recursing on it only burns depth.
            if underlying and underlying != base:
                # `layer` rides the whole alias chain: resolving UINT8 -> Handle_t must
                # not pick up another layer's Handle_t one hop down.
                resolved = get_range(underlying, dd, layer, _depth + 1)
                if resolved and resolved != "NA":
                    return resolved
        # Nothing better found: the entry's own "NA" is the answer. Falling through to
        # the qualifiedName scan here would let a *sibling* entry sharing this
        # qualifiedName win (parser emits both `Name` and `typedef@Name:file:line`),
        # which can surface a wrong range for the type actually asked about.
        if r:
            return r
    # Search by qualifiedName — same precedence as the direct lookup above: a usable
    # range wins, else resolve the alias, else fall back to this entry's own "NA"
    # (first match still wins, so which entry answers does not change).
    # The layer filter matters most here: this scan is what would otherwise reach the
    # entry the direct lookup just refused, and it is also where the pre-existing
    # first-match-wins ambiguity between two layers' same-named types lived.
    for ent in dd.values():
        if not _visible_to_layer(ent, layer):
            continue
        if ent.get("qualifiedName") == base or ent.get("qualifiedName", "").lower() == base_lower:
            r = ent.get("range")
            if r and r != "NA":
                return r
            if ent.get("kind") == "typedef" and _depth < 10:
                underlying = ent.get("underlyingType", "")
                if underlying and underlying != base:
                    resolved = get_range(underlying, dd, layer, _depth + 1)
                    if resolved and resolved != "NA":
                        return resolved
                return r if r else "NA"
            if r:
                return r
            # No usable range on this match: keep scanning (a later entry may carry one).
    return get_range_for_type(type_str)
