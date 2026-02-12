"""Shared helpers."""
import os
import json


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


def short_name(qualified_name: str) -> str:
    """Last segment after :: (e.g. MyClass::foo -> foo)."""
    return ((qualified_name or "").split("::")[-1]).strip()


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
        return "-128-127"
    if base in ("int16_t", "std::int16_t", "param_int16_t"):
        return "-32768-32767"
    if base in ("int32_t", "std::int32_t", "param_int32_t"):
        return "-2147483648-2147483647"
    if base in ("int64_t", "std::int64_t", "param_int64_t"):
        return "-9223372036854775808-9223372036854775807"
    if base in ("intptr_t", "std::intptr_t", "param_intptr_t"):
        return "-9223372036854775808-9223372036854775807"
    if base in ("int", "signed int"):
        return "-2147483648-2147483647"
    if base in ("short", "short int", "signed short"):
        return "-32768-32767"
    if base in ("long", "long int", "signed long"):
        return "-2147483648-2147483647"
    if base in ("long long", "long long int", "signed long long"):
        return "-9223372036854775808-9223372036854775807"
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
