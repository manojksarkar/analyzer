"""Parse C++ source -> model/."""
import os
import sys
import json
from datetime import datetime, timezone
from collections import defaultdict

from clang import cindex

from utils import get_module_name as _get_module, get_range_for_type, load_config, make_function_key, make_global_key, PRIMITIVES

if len(sys.argv) < 2:
    print("Usage: python parser.py <project_path>")
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
proj_arg = sys.argv[1]
MODULE_BASE_PATH = os.path.abspath(proj_arg) if os.path.isabs(proj_arg) else os.path.join(PROJECT_ROOT, proj_arg)
PROJECT_NAME = os.path.basename(MODULE_BASE_PATH)

_config = load_config(PROJECT_ROOT)
if _config.get("llvmLibPath") and os.path.isfile(_config["llvmLibPath"]):
    cindex.Config.set_library_file(_config["llvmLibPath"])

CLANG_ARGS = [
    "-std=c++17",
    f"-I{MODULE_BASE_PATH}",
    f"-I{_config['clangIncludePath']}",
]


def get_module_name(file_path: str) -> str:
    return _get_module(file_path, MODULE_BASE_PATH)

index = cindex.Index.create()
functions = {}
globals_data = {}
data_dictionary = {}
call_graph = defaultdict(set)  # caller -> {callees}
reverse_call_graph = defaultdict(set)  # callee -> {callers}
module_functions = defaultdict(list)
function_to_module = {}


def is_project_file(file_path: str) -> bool:
    if not file_path:
        return False
    abs_path = os.path.normcase(os.path.abspath(file_path))
    abs_base = os.path.normcase(os.path.abspath(MODULE_BASE_PATH))
    return abs_path.startswith(abs_base)


def get_qualified_name(cursor):
    parts = []
    parent = cursor.semantic_parent
    while parent:
        if parent.kind in (cindex.CursorKind.NAMESPACE, cindex.CursorKind.CLASS_DECL, cindex.CursorKind.STRUCT_DECL):
            parts.insert(0, parent.spelling or "(anonymous)")
        parent = parent.semantic_parent
    parts.append(cursor.spelling)
    return "::".join(parts) if parts else cursor.spelling


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
            fields = [
                {
                    "name": c.spelling,
                    "type": c.type.spelling if c.type else "",
                    "range": get_range_for_type(c.type.spelling if c.type else ""),
                }
                for c in cursor.get_children()
                if c.kind == cindex.CursorKind.FIELD_DECL and c.spelling
            ]
            name = cursor.spelling or "(anonymous)"
            qn = get_qualified_name(cursor) if cursor.spelling else f"(anonymous)@{key}"
            data_dictionary[qn] = {
                "kind": "struct" if cursor.kind == cindex.CursorKind.STRUCT_DECL else "class",
                "name": name,
                "qualifiedName": qn,
                "fields": fields,
                "range": "NA",
                "location": loc,
            }

    elif cursor.kind == cindex.CursorKind.ENUM_DECL:
        key = _get_type_key(cursor)
        enumerators = []
        for child in cursor.get_children():
            if child.kind == cindex.CursorKind.ENUM_CONSTANT_DECL:
                val = child.enum_value if hasattr(child, "enum_value") else None
                enumerators.append({
                    "name": child.spelling,
                    "value": val,
                })
        name = cursor.spelling or "(anonymous)"
        qn = get_qualified_name(cursor) if cursor.spelling else f"(anonymous)@{key}"
        underlying = cursor.type.spelling if cursor.type else ""
        vals = [e["value"] for e in enumerators if e["value"] is not None]
        enum_range = f"{min(vals)}-{max(vals)}" if vals else "NA"
        data_dictionary[qn] = {
            "kind": "enum",
            "name": name,
            "qualifiedName": qn,
            "underlyingType": underlying,
            "enumerators": enumerators,
            "range": enum_range,
            "location": loc,
        }

    elif cursor.kind == cindex.CursorKind.TYPEDEF_DECL:
        if cursor.spelling:
            qn = get_qualified_name(cursor)
            underlying = cursor.type.spelling if cursor.type else ""
            # Don't overwrite enum with typedef when same name (enum has range)
            if qn not in data_dictionary or data_dictionary[qn].get("kind") != "enum":
                data_dictionary[qn] = {
                    "kind": "typedef",
                    "name": cursor.spelling,
                    "qualifiedName": qn,
                    "underlyingType": underlying or "(opaque)",
                    "range": get_range_for_type(underlying or ""),
                    "location": loc,
                }

    for child in cursor.get_children():
        visit_type_definitions(child)


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
        func_id = f"{cursor.location.file.name}:{cursor.location.line}"
        module_name = get_module_name(cursor.location.file.name)
        params = []
        try:
            for arg in cursor.get_arguments():
                params.append({"name": arg.spelling or "", "type": arg.type.spelling if arg.type else ""})
        except Exception:
            pass

        end_line = cursor.location.line
        try:
            if cursor.extent.end.file and cursor.extent.end.file.name == cursor.location.file.name:
                end_line = cursor.extent.end.line
        except Exception:
            pass

        functions[get_function_key(cursor)] = {
            "functionId": func_id,
            "functionName": cursor.spelling,
            "qualifiedName": get_qualified_name(cursor),
            "mangledName": cursor.mangled_name or "",
            "moduleName": module_name,
            "parameters": params,
            "endLine": end_line,
        }
        module_functions[module_name].append(get_function_key(cursor))
        function_to_module[get_function_key(cursor)] = module_name

    elif is_global_var and cursor.spelling and cursor.location.file:
        var_id = f"{cursor.location.file.name}:{cursor.location.line}"
        globals_data[var_id] = {
            "variableId": var_id,
            "variableName": cursor.spelling,
            "qualifiedName": get_qualified_name(cursor),
            "moduleName": get_module_name(cursor.location.file.name),
            "type": cursor.type.spelling if cursor.type else "",
        }

    for child in cursor.get_children():
        visit_definitions(child)


def visit_calls(cursor, current_key=None):
    if cursor.kind in (cindex.CursorKind.FUNCTION_DECL, cindex.CursorKind.CXX_METHOD):
        if cursor.is_definition() and cursor.location.file and is_project_file(cursor.location.file.name):
            current_key = get_function_key(cursor)
    elif cursor.kind == cindex.CursorKind.CALL_EXPR and current_key:
        called_key = None
        if cursor.referenced:
            called_key = get_function_key(cursor.referenced)
            if called_key not in functions:
                called_key = None
        if not called_key:
            for k in functions:
                if functions[k]["functionName"] == cursor.spelling:
                    called_key = k
                    break
        if called_key and called_key in functions:
            call_graph[current_key].add(called_key)
            reverse_call_graph[called_key].add(current_key)

    for child in cursor.get_children():
        visit_calls(child, current_key)


def parse_file(path):
    try:
        tu = index.parse(path, args=CLANG_ARGS, options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)
        for d in tu.diagnostics:
            print(d)
        visit_definitions(tu.cursor)
        visit_type_definitions(tu.cursor)
    except cindex.TranslationUnitLoadError as e:
        print(f"Failed: {path}: {e}")


def parse_calls(path):
    try:
        tu = index.parse(path, args=CLANG_ARGS, options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)
        visit_calls(tu.cursor)
    except cindex.TranslationUnitLoadError:
        pass


def build_metadata():
    base_path = os.path.abspath(MODULE_BASE_PATH)
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
        fid = make_function_key(f["moduleName"], rel_file, f["qualifiedName"], f["parameters"])
        func_key_to_fid[func_key] = fid
        functions_dict[fid] = {
            "qualifiedName": f["qualifiedName"],
            "location": {
                "file": rel_file,
                "line": int(f["functionId"].rsplit(":", 1)[1]),
                "endLine": f.get("endLine", int(f["functionId"].rsplit(":", 1)[1])),
            },
            "params": f["parameters"],
        }

    # Add precise caller/callee ids using the final function keys (includes overloads, same-name functions, etc.)
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
        functions_dict[fid]["calledByIds"] = sorted(called_ids)
        functions_dict[fid]["callsIds"] = sorted(calls_ids)

    for var_id, g in globals_data.items():
        file_path = var_id.rsplit(":", 1)[0]
        try:
            rel_file = os.path.relpath(file_path, base_path).replace("\\", "/")
        except ValueError:
            rel_file = file_path.replace("\\", "/")
        vid = make_global_key(rel_file, g["qualifiedName"])
        global_variables_dict[vid] = {
            "qualifiedName": g["qualifiedName"],
            "location": {"file": rel_file, "line": int(var_id.rsplit(":", 1)[1])},
            "type": g["type"],
        }

    return {
        "version": 1,
        "basePath": base_path,
        "projectName": PROJECT_NAME,
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "functions": functions_dict,
        "globalVariables": global_variables_dict,
    }


def main():
    print("Parsing...")
    for root, _, files in os.walk(MODULE_BASE_PATH):
        for f in files:
            if f.endswith((".cpp", ".cc", ".cxx", ".h", ".hpp", ".hxx")):
                parse_file(os.path.join(root, f))

    print("Collecting calls...")
    for root, _, files in os.walk(MODULE_BASE_PATH):
        for f in files:
            if f.endswith((".cpp", ".cc", ".cxx", ".h", ".hpp", ".hxx")):
                parse_calls(os.path.join(root, f))

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
    with open(os.path.join(model_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta_header, f, indent=2)

    with open(os.path.join(model_dir, "functions.json"), "w", encoding="utf-8") as f:
        json.dump(metadata["functions"], f, indent=2)
    with open(os.path.join(model_dir, "globalVariables.json"), "w", encoding="utf-8") as f:
        json.dump(metadata["globalVariables"], f, indent=2)
    # Add primitives (name as key)
    for name, info in PRIMITIVES.items():
        data_dictionary[name] = {"kind": "primitive", "range": info["range"]}
    with open(os.path.join(model_dir, "dataDictionary.json"), "w", encoding="utf-8") as f:
        json.dump(data_dictionary, f, indent=2)

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


if __name__ == "__main__":
    main()
