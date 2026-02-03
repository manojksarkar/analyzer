import os
import sys
import json
from collections import defaultdict
from clang import cindex

# ================= CONFIG =================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Base path where modules are located (first-level child folders will be modules).
# A relative path (from this script directory) MUST be passed as the first CLI argument.
if len(sys.argv) < 2:
    print("Usage: python analyzer.py <relative_project_path_from_this_directory>")
    sys.exit(1)

MODULE_BASE_PATH = os.path.abspath(os.path.join(SCRIPT_DIR, sys.argv[1]))

# Derive project code automatically from the LAST path segment of base path, e.g. "src" -> "SRC"
PROJECT_NAME = os.path.basename(MODULE_BASE_PATH)
PROJECT_CODE = PROJECT_NAME.upper()

# Update if your LLVM version is different
cindex.Config.set_library_file(
    r"C:\Program Files\LLVM\bin\libclang.dll"
)

CLANG_ARGS = [
    "-std=c++17",
    f"-I{MODULE_BASE_PATH}",
    r"-IC:\Program Files\LLVM\lib\clang\17\include"
]

# =========================================

index = cindex.Index.create()

functions = {}  # Key: mangled name or unique ID, Value: function info
globals = {}    # Key: unique ID, Value: global variable info
call_graph = defaultdict(set)
reverse_call_graph = defaultdict(set)
module_functions = defaultdict(list)  # Key: module name, Value: list of function keys
function_to_module = {}  # Key: function key, Value: module name


def get_module_name(file_path: str) -> str:
    """Determine which module a file belongs to based on its path"""
    if not file_path:
        return "unknown"
    
    abs_file_path = os.path.abspath(file_path)
    abs_base_path = os.path.abspath(MODULE_BASE_PATH)
    
    # Check if file is under the base path
    if not abs_file_path.startswith(abs_base_path):
        return "unknown"
    
    # Get relative path from base
    try:
        rel_path = os.path.relpath(abs_file_path, abs_base_path)
        # Split path and get first component (module name)
        parts = rel_path.split(os.sep)
        if parts and parts[0]:
            return parts[0]
    except ValueError:
        pass
    
    return "unknown"


def is_project_file(file_path: str) -> bool:
    """Check if file is within the module base path"""
    if not file_path:
        return False
    abs_file_path = os.path.abspath(file_path)
    abs_base_path = os.path.abspath(MODULE_BASE_PATH)
    return abs_file_path.startswith(abs_base_path)


def get_qualified_name(cursor):
    """Build qualified name with namespace/class context"""
    parts = []
    parent = cursor.semantic_parent
    while parent:
        if parent.kind == cindex.CursorKind.NAMESPACE:
            parts.insert(0, parent.spelling or "(anonymous)")
        elif parent.kind == cindex.CursorKind.CLASS_DECL or parent.kind == cindex.CursorKind.STRUCT_DECL:
            parts.insert(0, parent.spelling or "(anonymous)")
        parent = parent.semantic_parent
    
    parts.append(cursor.spelling)
    return "::".join(parts) if parts else cursor.spelling


def get_function_key(cursor):
    """Generate a unique key for a function to handle overloads, namespaces, etc."""
    # Use mangled name if available (handles overloads) for uniqueness
    mangled = cursor.mangled_name
    if mangled:
        return mangled
    
    # Fallback: build qualified name with namespace/class context
    qualified_name = get_qualified_name(cursor)
    
    # Add location to make it unique if still ambiguous
    if cursor.location.file:
        return f"{qualified_name}@{cursor.location.file.name}:{cursor.location.line}"
    return qualified_name


def visit_definitions(cursor):
    """First pass: collect all function definitions and global variables"""
    # Handle both free functions and member functions
    is_function = (
        cursor.kind == cindex.CursorKind.FUNCTION_DECL
        or cursor.kind == cindex.CursorKind.CXX_METHOD
    )
    is_global_var = (
        cursor.kind == cindex.CursorKind.VAR_DECL
        and cursor.location.file
        and is_project_file(cursor.location.file.name)
        and cursor.semantic_parent is not None
        and cursor.semantic_parent.kind in (
            cindex.CursorKind.TRANSLATION_UNIT,
            cindex.CursorKind.NAMESPACE,
        )
    )
    
    if (
        is_function
        and cursor.is_definition()
        and cursor.location.file
        and is_project_file(cursor.location.file.name)
    ):
        func_name = cursor.spelling
        func_key = get_function_key(cursor)
        func_id = f"{cursor.location.file.name}:{cursor.location.line}"
        module = os.path.basename(cursor.location.file.name)
        
        # Get qualified name for display
        qualified_name = get_qualified_name(cursor)
        
        # Determine which module this function belongs to
        module_name = get_module_name(cursor.location.file.name)

        # Collect basic parameter info for interface reporting
        params = []
        try:
            for arg in cursor.get_arguments():
                arg_type = arg.type.spelling if arg.type is not None else ""
                params.append({
                    "name": arg.spelling or "",
                    "type": arg_type,
                })
        except Exception:
            # Be defensive: parameter collection is nice-to-have, not critical
            params = []

        functions[func_key] = {
            "functionName": func_name,
            "qualifiedName": qualified_name,
            "functionId": func_id,
            "moduleName": module,
            "parameters": params,
            "parameterCount": len(params),
            "callersFunctionNames": [],
            "calleesFunctionNames": []
        }
        
        # Group by module and track function-to-module mapping
        module_functions[module_name].append(func_key)
        function_to_module[func_key] = module_name

    elif is_global_var:
        var_name = cursor.spelling
        if cursor.location.file and var_name:
            var_id = f"{cursor.location.file.name}:{cursor.location.line}"
            module = os.path.basename(cursor.location.file.name)
            qualified_name = get_qualified_name(cursor)
            module_name = get_module_name(cursor.location.file.name)
            var_type = cursor.type.spelling if cursor.type is not None else ""

            globals[var_id] = {
                "variableName": var_name,
                "qualifiedName": qualified_name,
                "variableId": var_id,
                "moduleName": module,
                "type": var_type,
            }

    # Recurse
    for child in cursor.get_children():
        visit_definitions(child)


def visit_calls(cursor, current_function_key=None):
    """Second pass: collect all function calls"""
    # ---- Function definition ----
    is_function = (
        cursor.kind == cindex.CursorKind.FUNCTION_DECL
        or cursor.kind == cindex.CursorKind.CXX_METHOD
    )
    
    if (
        is_function
        and cursor.is_definition()
        and cursor.location.file
        and is_project_file(cursor.location.file.name)
    ):
        current_function_key = get_function_key(cursor)

    # ---- Function call ----
    elif (
        cursor.kind == cindex.CursorKind.CALL_EXPR
        and current_function_key
    ):
        # Get the function being called
        called_func_key = None
        referenced = cursor.referenced
        
        if referenced:
            # Check if it's a function we're tracking
            called_func_key = get_function_key(referenced)
            if called_func_key not in functions:
                called_func_key = None
        
        # Fallback: try to match by spelling
        if not called_func_key:
            called_name = cursor.spelling
            # Try to find matching function by name (may have collisions)
            for func_key in functions:
                if functions[func_key]["functionName"] == called_name:
                    called_func_key = func_key
                    break
        
        if called_func_key and called_func_key in functions:
            call_graph[current_function_key].add(called_func_key)
            reverse_call_graph[called_func_key].add(current_function_key)

    # ---- Recurse ----
    for child in cursor.get_children():
        visit_calls(child, current_function_key)


def parse_cpp_file(file_path: str, visit_func):
    try:
        tu = index.parse(
            file_path,
            args=CLANG_ARGS,
            options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD
        )

        # Print diagnostics if any
        for diag in tu.diagnostics:
            print(diag)

        visit_func(tu.cursor)

    except cindex.TranslationUnitLoadError as e:
        print(f"Failed to parse {file_path}: {e}")


def collect_cpp_files():
    """Collect both .cpp and .h/.hpp files for analysis"""
    for root, _, files in os.walk(MODULE_BASE_PATH):
        for file in files:
            if file.endswith((".cpp", ".cc", ".cxx", ".h", ".hpp", ".hxx")):
                yield os.path.join(root, file)


# ================= EXECUTION =================

# First pass: collect all function definitions
print("Collecting function definitions...")
for cpp in collect_cpp_files():
    parse_cpp_file(cpp, visit_definitions)

# Second pass: collect all function calls
print("Collecting function calls...")
for cpp in collect_cpp_files():
    parse_cpp_file(cpp, visit_calls)

# Populate the relationships (using qualified names for output)
for func_key in functions:
    callees = call_graph.get(func_key, [])
    callers = reverse_call_graph.get(func_key, [])
    
    # Convert keys to qualified names for output
    functions[func_key]["calleesFunctionNames"] = [
        functions[callee_key]["qualifiedName"] 
        for callee_key in callees 
        if callee_key in functions
    ]
    functions[func_key]["callersFunctionNames"] = [
        functions[caller_key]["qualifiedName"] 
        for caller_key in callers 
        if caller_key in functions
    ]

# Build module-based structure with caller/callee modules
modules_data = []
for module_name in sorted(module_functions.keys()):
    module_path = os.path.join(MODULE_BASE_PATH, module_name)
    
    # Find caller modules (modules that call functions in this module)
    caller_modules = set()
    # Find callee modules (modules that are called by functions in this module)
    callee_modules = set()
    
    # Check all functions in this module
    for func_key in module_functions[module_name]:
        if func_key not in functions:
            continue
            
        # Find callers of this function (who calls functions in this module)
        callers = reverse_call_graph.get(func_key, [])
        for caller_key in callers:
            if caller_key in function_to_module:
                caller_module = function_to_module[caller_key]
                if caller_module != module_name:  # Don't include self
                    caller_modules.add(caller_module)
        
        # Find callees of this function (what modules this module calls)
        callees = call_graph.get(func_key, [])
        for callee_key in callees:
            if callee_key in function_to_module:
                callee_module = function_to_module[callee_key]
                if callee_module != module_name:  # Don't include self
                    callee_modules.add(callee_module)
    
    module_info = {
        "moduleName": module_name,
        "modulePath": os.path.abspath(module_path),
        "callerModules": sorted(list(caller_modules)),
        "calleeModules": sorted(list(callee_modules)),
        "functions": [
            functions[func_key] 
            for func_key in module_functions[module_name]
            if func_key in functions
        ]
    }
    modules_data.append(module_info)

# Build flat functions and globals lists
functions_list = list(functions.values())
globals_list = list(globals.values())
base_path = os.path.abspath(MODULE_BASE_PATH)

# Build files list with extra info per file
file_paths = sorted(set(
    f["functionId"].rsplit(":", 1)[0]
    for f in functions_list
))
files_data = []
for file_path in file_paths:
    funcs_in_file = [f for f in functions_list if f["functionId"].rsplit(":", 1)[0] == file_path]
    try:
        rel_path = os.path.relpath(file_path, base_path)
    except ValueError:
        rel_path = file_path
    files_data.append({
        "path": file_path,
        "relativePath": rel_path,
        "moduleName": get_module_name(file_path),
        "fileName": os.path.basename(file_path),
        "functionCount": len(funcs_in_file),
        "functionNames": sorted(set(f["qualifiedName"] for f in funcs_in_file)),
    })

# Output functions.json
with open(os.path.join(OUTPUT_DIR, "functions.json"), "w", encoding="utf-8") as f:
    json.dump({"basePath": base_path, "functions": functions_list}, f, indent=2)
print(f"Generated: functions.json ({len(functions_list)} functions)")

# Output files.json
with open(os.path.join(OUTPUT_DIR, "files.json"), "w", encoding="utf-8") as f:
    json.dump({"basePath": base_path, "files": files_data}, f, indent=2)
print(f"Generated: files.json ({len(files_data)} files)")

# Build units list (one unit per file)
# Map function qualifiedName -> file(s) it is defined in (handles duplicates conservatively)
qualified_name_to_file_paths = defaultdict(set)
for f in functions_list:
    f_path = f["functionId"].rsplit(":", 1)[0]
    qualified_name_to_file_paths[f["qualifiedName"]].add(f_path)

# Map file -> unitName (module/fileName)
unit_name_by_file_path = {}
for file_path in file_paths:
    unit_name_by_file_path[file_path] = f"{get_module_name(file_path)}/{os.path.basename(file_path)}"

units_data = []
for file_path in file_paths:
    funcs_in_file = [f for f in functions_list if f["functionId"].rsplit(":", 1)[0] == file_path]

    unit_module_name = get_module_name(file_path)
    unit_file_name = os.path.basename(file_path)
    unit_name = f"{unit_module_name}/{unit_file_name}"

    # Keep function-level callers/callees
    caller_functions = set()
    callee_functions = set()
    for func in funcs_in_file:
        caller_functions.update(func.get("callersFunctionNames", []))
        callee_functions.update(func.get("calleesFunctionNames", []))

    # Derive unit-level callers/callees from function-level relationships
    caller_unit_to_functions = defaultdict(set)
    callee_unit_to_functions = defaultdict(set)

    for caller_fn in caller_functions:
        for caller_fp in qualified_name_to_file_paths.get(caller_fn, set()):
            caller_unit = unit_name_by_file_path.get(
                caller_fp,
                f"{get_module_name(caller_fp)}/{os.path.basename(caller_fp)}",
            )
            if caller_unit != unit_name:
                caller_unit_to_functions[caller_unit].add(caller_fn)

    for callee_fn in callee_functions:
        for callee_fp in qualified_name_to_file_paths.get(callee_fn, set()):
            callee_unit = unit_name_by_file_path.get(
                callee_fp,
                f"{get_module_name(callee_fp)}/{os.path.basename(callee_fp)}",
            )
            if callee_unit != unit_name:
                callee_unit_to_functions[callee_unit].add(callee_fn)

    units_data.append({
        "unitName": unit_name,
        "fileName": unit_file_name,
        "moduleName": unit_module_name,
        "functionNames": sorted(set(f["qualifiedName"] for f in funcs_in_file)),
        "callerUnits": [
            {"unitName": u, "functionNames": sorted(fns)}
            for u, fns in sorted(caller_unit_to_functions.items(), key=lambda kv: kv[0])
        ],
        "calleesUnits": [
            {"unitName": u, "functionNames": sorted(fns)}
            for u, fns in sorted(callee_unit_to_functions.items(), key=lambda kv: kv[0])
        ],
    })

# Output units.json
with open(os.path.join(OUTPUT_DIR, "units.json"), "w", encoding="utf-8") as f:
    json.dump({"basePath": base_path, "units": units_data}, f, indent=2)
print(f"Generated: units.json ({len(units_data)} units)")

# Build interface table (functions as interfaces)

# Map interface (function/global) -> position index within its file (based on source line)
interfaces_by_file_path = defaultdict(list)
for f in functions_list:
    f_path = f["functionId"].rsplit(":", 1)[0]
    interfaces_by_file_path[f_path].append(("function", f["functionId"], f))

for g in globals_list:
    g_path = g["variableId"].rsplit(":", 1)[0]
    interfaces_by_file_path[g_path].append(("globalVariable", g["variableId"], g))

interface_index_by_id = {}
for f_path, entries in interfaces_by_file_path.items():
    sorted_entries = sorted(
        entries,
        key=lambda e: int(e[1].rsplit(":", 1)[1]),
    )
    for idx, (_, iid, _) in enumerate(sorted_entries, start=1):
        interface_index_by_id[iid] = idx

interfaces_data = []

# Function interfaces
for func in functions_list:
    func_id = func["functionId"]

    # Derive module and file info from functionId
    file_path = func_id.rsplit(":", 1)[0]
    module_name = get_module_name(file_path)
    module_code = module_name.upper() if module_name else "UNKNOWN_MODULE"

    file_name = os.path.basename(file_path)
    file_code = os.path.splitext(file_name)[0].upper()

    func_index = interface_index_by_id.get(func_id, 0)
    func_code = f"{func_index:02d}" if func_index > 0 else "00"

    # Build interface ID like: IF_SRC_MODULE3_MAIN_03
    formatted_interface_id = f"IF_{PROJECT_CODE}_{module_code}_{file_code}_{func_code}"

    # Interface name like: DLM_functionName
    base_func_name = func.get("functionName", "")
    interface_name = f"{file_code}_{base_func_name}" if base_func_name else file_code

    # Map callers/callees to units via their qualified names
    caller_units = set()
    callee_units = set()

    for caller_name in func.get("callersFunctionNames", []):
        for caller_fp in qualified_name_to_file_paths.get(caller_name, set()):
            caller_units.add(unit_name_by_file_path.get(
                caller_fp,
                f"{get_module_name(caller_fp)}/{os.path.basename(caller_fp)}",
            ))

    for callee_name in func.get("calleesFunctionNames", []):
        for callee_fp in qualified_name_to_file_paths.get(callee_name, set()):
            callee_units.add(unit_name_by_file_path.get(
                callee_fp,
                f"{get_module_name(callee_fp)}/{os.path.basename(callee_fp)}",
            ))

    params = func.get("parameters", [])
    param_ranges = []
    for idx, p in enumerate(params):
        param_ranges.append({
            "name": p.get("name", ""),
            "type": p.get("type", ""),
            "index": idx,
            "minIndex": idx,
            "maxIndex": idx,
        })

    interfaces_data.append({
        "interfaceId": formatted_interface_id,
        "interfaceName": interface_name,
        "interfaceType": "function",
        "parameters": params,
        "usedParametersRange": param_ranges,
        "callerUnits": sorted(caller_units),
        "calleesUnits": sorted(callee_units),
    })

# Global variable interfaces
for var in globals_list:
    var_id = var["variableId"]
    file_path = var_id.rsplit(":", 1)[0]
    module_name = get_module_name(file_path)
    module_code = module_name.upper() if module_name else "UNKNOWN_MODULE"

    file_name = os.path.basename(file_path)
    file_code = os.path.splitext(file_name)[0].upper()

    var_index = interface_index_by_id.get(var_id, 0)
    var_code = f"{var_index:02d}" if var_index > 0 else "00"

    formatted_interface_id = f"IF_{PROJECT_CODE}_{module_code}_{file_code}_{var_code}"

    base_var_name = var.get("variableName", "")
    interface_name = f"{file_code}_{base_var_name}" if base_var_name else file_code

    interfaces_data.append({
        "interfaceId": formatted_interface_id,
        "interfaceName": interface_name,
        "interfaceType": "globalVariable",
        "parameters": [],
        "usedParametersRange": [],
        "callerUnits": [],
        "calleesUnits": [],
    })

# Output interfaces.json
with open(os.path.join(OUTPUT_DIR, "interfaces.json"), "w", encoding="utf-8") as f:
    json.dump({"basePath": base_path, "interfaces": interfaces_data}, f, indent=2)
print(f"Generated: interfaces.json ({len(interfaces_data)} interfaces)")

# Output modules.json
with open(os.path.join(OUTPUT_DIR, "modules.json"), "w", encoding="utf-8") as f:
    json.dump({"basePath": base_path, "modules": modules_data}, f, indent=2)
print(f"Generated: modules.json ({len(modules_data)} modules)")

# Build component diagram structure
components_data = []
for module_info in modules_data:
    component = {
        "name": module_info["moduleName"],
        "incoming": module_info["callerModules"],
        "outgoing": module_info["calleeModules"],
        "functions": [
            func["functionName"]  # Just list function names as strings
            for func in module_info["functions"]
        ]
    }
    components_data.append(component)

# Output component.json
component_output = {
    "basePath": os.path.abspath(MODULE_BASE_PATH),
    "components": components_data
}

with open(os.path.join(OUTPUT_DIR, "component.json"), "w", encoding="utf-8") as f:
    json.dump(component_output, f, indent=2)

print(f"Component diagram generated: component.json")
print(f"Found {len(components_data)} components")
