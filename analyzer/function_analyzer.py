import os
import json
from collections import defaultdict
from clang import cindex

# ================= CONFIG =================

PROJECT_ROOT = os.path.abspath("../cpp_projects/cpp_project")

# Update if your LLVM version is different
cindex.Config.set_library_file(
    r"C:\Program Files\LLVM\bin\libclang.dll"
)

CLANG_ARGS = [
    "-std=c++17",
    f"-I{PROJECT_ROOT}",
    r"-IC:\Program Files\LLVM\lib\clang\17\include"
]

# =========================================

index = cindex.Index.create()

functions = {}  # Key: mangled name or unique ID, Value: function info
call_graph = defaultdict(set)
reverse_call_graph = defaultdict(set)


def is_project_file(file_path: str) -> bool:
    return (
        file_path is not None
        and os.path.abspath(file_path).startswith(PROJECT_ROOT)
    )


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
        # Use mangled name as key, but we'll store qualified name separately
        return mangled
    
    # Fallback: build qualified name with namespace/class context
    qualified_name = get_qualified_name(cursor)
    
    # Add location to make it unique if still ambiguous
    if cursor.location.file:
        return f"{qualified_name}@{cursor.location.file.name}:{cursor.location.line}"
    return qualified_name


def visit_definitions(cursor):
    """First pass: collect all function definitions"""
    # Handle both free functions and member functions
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
        func_name = cursor.spelling
        func_key = get_function_key(cursor)
        func_id = f"{cursor.location.file.name}:{cursor.location.line}"
        module = os.path.basename(cursor.location.file.name)
        
        # Get qualified name for display (always build from semantic context, not from mangled name)
        qualified_name = get_qualified_name(cursor)

        functions[func_key] = {
            "functionName": func_name,
            "qualifiedName": qualified_name,
            "functionId": func_id,
            "moduleName": module,
            "callersFunctionNames": [],
            "calleesFunctionNames": []
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
                # Try by spelling as fallback (for external functions)
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
    for root, _, files in os.walk(PROJECT_ROOT):
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


with open("functions.json", "w", encoding="utf-8") as f:
    json.dump(list(functions.values()), f, indent=2)

print("Function table generated: functions.json")
