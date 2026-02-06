"""Shared helpers."""
import os


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
    t = (type_str or "").strip().lower()
    if t == "void" or (t.startswith("void ") and "*" not in t):
        return "VOID"
    base = t.replace("const ", "").replace("volatile ", "").strip()
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
