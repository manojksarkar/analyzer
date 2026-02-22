"""Shared helpers."""
import os
import re
import sys
import json

# Separator for unique keys (function IDs, global IDs, unit keys). Avoid "/" for path confusion.
KEY_SEP = "|"


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



def _strip_json_comments(text: str) -> str:
    """Strip // and /* */ so config files can use comments."""
    result = []
    i = 0
    in_string = False
    escape = False
    while i < len(text):
        c = text[i]
        if escape:
            result.append(c)
            escape = False
            i += 1
            continue
        if c == "\\" and in_string:
            escape = True
            result.append(c)
            i += 1
            continue
        if c == '"' and not escape:
            in_string = not in_string
            result.append(c)
            i += 1
            continue
        if in_string:
            result.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < len(text):
            if text[i + 1] == "/":
                i += 2
                while i < len(text) and text[i] != "\n":
                    i += 1
                continue
            if text[i + 1] == "*":
                i += 2
                while i + 1 < len(text) and (text[i] != "*" or text[i + 1] != "/"):
                    i += 1
                i += 2
                continue
        result.append(c)
        i += 1
    return "".join(result)


def load_config(project_root: str) -> dict:
    """Load config from config/config.json, then config.local.json overrides."""
    config = {}
    config_dir = os.path.join(project_root, "config")
    for name in ("config.json", "config.local.json"):
        path = os.path.join(config_dir, name)
        if not os.path.isfile(path):
            path = os.path.join(project_root, name)
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    config.update(json.loads(_strip_json_comments(f.read())))
            except (json.JSONDecodeError, IOError):
                pass
    return config


def _path_to_module_unit(rel_file: str) -> tuple:
    """Return (module, unitname) from rel_file. Unitname = filename without extension (no subpath)."""
    path = rel_file.replace("\\", "/") if rel_file else ""
    parts = path.split("/")
    if not parts:
        return "unknown", ""
    module = parts[0]
    unitname = os.path.splitext(parts[-1])[0]
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


def get_module_name(file_path: str, base_path: str) -> str:
    if not file_path:
        return "unknown"
    try:
        abs_base = os.path.normcase(os.path.abspath(base_path))
        path = file_path if os.path.isabs(file_path) else os.path.join(base_path, file_path)
        abs_path = os.path.normcase(os.path.abspath(path))
        if not abs_path.startswith(abs_base):
            return "unknown"
        rel = os.path.relpath(abs_path, abs_base)
        parts = rel.replace("\\", "/").split("/")
        return parts[0] if parts and parts[0] else "unknown"
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
