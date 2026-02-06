"""
Parser: C++ source -> metadata.json
Call graph in function properties (callers/callees).
"""
import os
import sys
import json
from datetime import datetime, timezone
from collections import defaultdict

from clang import cindex

from utils import get_module_name as _get_module, load_config as _load_config_file

# ================= CONFIG =================
if len(sys.argv) < 2:
    print("Usage: python parser.py <project_path>")
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
proj_arg = sys.argv[1]
MODULE_BASE_PATH = os.path.abspath(proj_arg) if os.path.isabs(proj_arg) else os.path.join(PROJECT_ROOT, proj_arg)
PROJECT_NAME = os.path.basename(MODULE_BASE_PATH)


def _load_config():
    """Load config from config/, then config.local.json overrides."""
    defaults = {
        "llvmLibPath": r"C:\Program Files\LLVM\bin\libclang.dll",
        "clangIncludePath": r"C:\Program Files\LLVM\lib\clang\17\include",
    }
    defaults.update(_load_config_file(PROJECT_ROOT))
    return defaults


_config = _load_config()
llvm_path = _config.get("llvmLibPath", "")
if llvm_path and os.path.isfile(llvm_path):
    cindex.Config.set_library_file(llvm_path)

CLANG_ARGS = [
    "-std=c++17",
    f"-I{MODULE_BASE_PATH}",
    f"-I{_config.get('clangIncludePath', r'C:\Program Files\LLVM\lib\clang\17\include')}",
]


def get_module_name(file_path: str) -> str:
    return _get_module(file_path, MODULE_BASE_PATH)

# =========================================
index = cindex.Index.create()
functions = {}
globals_data = {}
call_graph = defaultdict(set)
reverse_call_graph = defaultdict(set)
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
    mangled = cursor.mangled_name
    if mangled:
        return mangled
    qualified = get_qualified_name(cursor)
    if cursor.location.file:
        return f"{qualified}@{cursor.location.file.name}:{cursor.location.line}"
    return qualified


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
    except cindex.TranslationUnitLoadError as e:
        print(f"Failed: {path}: {e}")


def parse_calls(path):
    try:
        tu = index.parse(path, args=CLANG_ARGS, options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)
        visit_calls(tu.cursor)
    except cindex.TranslationUnitLoadError:
        pass


def build_metadata():
    for k in functions:
        functions[k]["callersFunctionNames"] = [
            functions[c]["qualifiedName"] for c in reverse_call_graph.get(k, []) if c in functions
        ]
        functions[k]["calleesFunctionNames"] = [
            functions[c]["qualifiedName"] for c in call_graph.get(k, []) if c in functions
        ]

    base_path = os.path.abspath(MODULE_BASE_PATH)
    functions_dict = {}
    global_variables_dict = {}

    for func_key, f in functions.items():
        file_path = f["functionId"].rsplit(":", 1)[0]
        try:
            rel_file = os.path.relpath(file_path, base_path).replace("\\", "/")
        except ValueError:
            rel_file = file_path.replace("\\", "/")
        fid = f"{rel_file}:{f['functionId'].rsplit(':', 1)[1]}"
        functions_dict[fid] = {
            "name": f["functionName"],
            "qualifiedName": f["qualifiedName"],
            "location": {
                "file": rel_file,
                "line": int(f["functionId"].rsplit(":", 1)[1]),
                "endLine": f.get("endLine", int(f["functionId"].rsplit(":", 1)[1])),
            },
            "module": f["moduleName"],
            "params": f["parameters"],
            "callersFunctionNames": f["callersFunctionNames"],
            "calleesFunctionNames": f["calleesFunctionNames"],
        }

    for var_id, g in globals_data.items():
        file_path = var_id.rsplit(":", 1)[0]
        try:
            rel_file = os.path.relpath(file_path, base_path).replace("\\", "/")
        except ValueError:
            rel_file = file_path.replace("\\", "/")
        vid = f"{rel_file}:{var_id.rsplit(':', 1)[1]}"
        global_variables_dict[vid] = {
            "name": g["variableName"],
            "qualifiedName": g["qualifiedName"],
            "location": {"file": rel_file, "line": int(var_id.rsplit(":", 1)[1])},
            "module": g["moduleName"],
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
    output_dir = os.path.join(PROJECT_ROOT, "output")
    os.makedirs(output_dir, exist_ok=True)
    metadata_path = os.path.join(output_dir, "metadata.json")
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    n_funcs = len(metadata["functions"])
    n_vars = len(metadata["globalVariables"])
    print(f"Generated: output/metadata.json ({n_funcs} functions, {n_vars} globals)")


if __name__ == "__main__":
    main()
