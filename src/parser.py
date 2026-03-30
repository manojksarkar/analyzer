"""Parse C++ source -> model/."""
import os
import re
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

_modules_groups = _config.get("modulesGroups") or {}
# Prefer new "selectedGroup" key; fall back to legacy "modulesGroup" if present.
_selected_group = _config.get("selectedGroup") or _config.get("modulesGroup")
if _selected_group and isinstance(_modules_groups.get(_selected_group), dict):
    _modules_cfg = _modules_groups[_selected_group] or {}
else:
    # If no selected group (or invalid), fall back to top-level "modules" if present.
    # When that is also missing/empty, default behaviour is used: all files
    # under MODULE_BASE_PATH are parsed and module = first folder.
    _modules_cfg = _config.get("modules") or {}
_MODULE_FOLDERS = []
for _mod_paths in _modules_cfg.values():
    if not _mod_paths:
        continue
    if isinstance(_mod_paths, str):
        _mod_paths = [_mod_paths]
    for _p in _mod_paths:
        _norm = (_p or "").replace("\\", "/").lstrip("./")
        if _norm:
            _MODULE_FOLDERS.append(_norm)

CLANG_ARGS = [
    "-std=c++17",
    f"-I{MODULE_BASE_PATH}",
    f"-I{_clang_inc}",
]
# Common visibility-like macros seen in C/C++ codebases.
# Defining them keeps declarations such as
# "PROTECTED DB_TYPE foo(...)" parseable even when headers don't define them.
# __ONLYINT: empty placeholder sometimes placed between return type and the function name, e.g.
#   PRIVATE UNIT __ONLYINT
#   _SOME_FUNCTION(GG *gg){}
_default_macro_defs = ("PRIVATE", "PROTECTED", "PUBLIC", "__ONLYINT")
for _macro in _default_macro_defs:
    _arg = f"-D{_macro}="
    if _arg not in CLANG_ARGS:
        CLANG_ARGS.append(_arg)
_extra = _clang.get("clangArgs")
if _extra:
    CLANG_ARGS.extend(_extra if isinstance(_extra, list) else [_extra])


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
global_access_reads = defaultdict(set)   # func_key -> set of var_id
global_access_writes = defaultdict(set)  # func_key -> set of var_id
# First non-trivial return expression per function (for behaviour output naming)
function_return_expr = {}


def is_project_file(file_path: str) -> bool:
    """Return True if file should be analysed as part of the project.

    - Always requires the path to be under MODULE_BASE_PATH.
    - If config.modules is provided, only files whose relative path is inside
      one of the configured folders are included (folder or any subfolder).
    - If config.modules is not provided, all files under MODULE_BASE_PATH are included.
    """
    if not file_path:
        return False
    abs_path = os.path.normcase(os.path.abspath(file_path))
    abs_base = os.path.normcase(os.path.abspath(MODULE_BASE_PATH))
    if not abs_path.startswith(abs_base):
        return False

    if _MODULE_FOLDERS:
        try:
            rel = os.path.relpath(abs_path, MODULE_BASE_PATH).replace("\\", "/")
        except ValueError:
            rel = abs_path.replace("\\", "/")
        for folder in _MODULE_FOLDERS:
            # Folder-based match: folder itself or any subpath under it
            if rel == folder or rel.startswith(folder + "/"):
                return True
        return False

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
        "range": get_range_for_type(underlying or ""),
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
            # Also add typedef entry when this struct participates in a 'typedef struct { ... } Name;' pattern.
            if cursor.kind == cindex.CursorKind.STRUCT_DECL and cursor.spelling:
                _maybe_add_typedef_for_struct(name, qn, loc, rel_file)

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
            # If an enum already exists with the same name, keep it (enum has range),
            # but ALSO store the typedef as a separate entry (unique key) so it can appear in views.
            key = qn
            if qn in data_dictionary and data_dictionary[qn].get("kind") == "enum":
                key = f"typedef@{qn}:{rel_file}:{loc.get('line', '')}"
            data_dictionary[key] = {
                "kind": "typedef",
                "name": cursor.spelling,
                "qualifiedName": qn,
                "underlyingType": underlying or "(opaque)",
                "range": get_range_for_type(underlying or ""),
                "location": loc,
            }

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
            "returnType": cursor.result_type.spelling if cursor.result_type else "",
            "endLine": end_line,
        }
        module_functions[module_name].append(get_function_key(cursor))
        function_to_module[get_function_key(cursor)] = module_name

    elif is_global_var and cursor.spelling and cursor.location.file:
        if _var_decl_should_record_as_function_not_global(cursor):
            func_id = f"{cursor.location.file.name}:{cursor.location.line}"
            module_name = get_module_name(cursor.location.file.name)
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
                "moduleName": module_name,
                "parameters": params,
                "returnType": cursor.type.spelling if cursor.type else "",
                "endLine": end_line,
                "syntheticFromVarDecl": True,
            }
            module_functions[module_name].append(fk)
            function_to_module[fk] = module_name
        else:
            var_id = f"{cursor.location.file.name}:{cursor.location.line}"
            value_str = _get_var_init_value(cursor)
            globals_data[var_id] = {
                "variableId": var_id,
                "variableName": cursor.spelling,
                "qualifiedName": get_qualified_name(cursor),
                "moduleName": get_module_name(cursor.location.file.name),
                "type": cursor.type.spelling if cursor.type else "",
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
            current_key = get_function_key(cursor)
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


def parse_global_access(path):
    """Collect global read/write per function for direction (In/Out)."""
    try:
        tu = index.parse(path, args=CLANG_ARGS, options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)
        visit_global_access(tu.cursor)
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
            "returnType": f.get("returnType", ""),
        }
        if f.get("syntheticFromVarDecl"):
            functions_dict[fid]["syntheticFromVarDecl"] = True
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
        g_entry = {
            "qualifiedName": g["qualifiedName"],
            "location": {"file": rel_file, "line": int(var_id.rsplit(":", 1)[1])},
            "type": g["type"],
        }
        if g.get("value"):
            g_entry["value"] = g["value"]
        global_variables_dict[vid] = g_entry

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
        functions_dict[fid]["calledByIds"] = sorted(called_ids)
        functions_dict[fid]["callsIds"] = sorted(calls_ids)

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
        if write_raw and not read_raw:
            functions_dict[fid]["direction"] = "In"
        elif read_raw and not write_raw:
            functions_dict[fid]["direction"] = "Out"
        else:
            functions_dict[fid]["direction"] = "In"

    return {
        "version": 1,
        "basePath": base_path,
        "projectName": PROJECT_NAME,
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "functions": functions_dict,
        "globalVariables": global_variables_dict,
    }


def _collect_source_files():
    files = []
    for root, _, fnames in os.walk(MODULE_BASE_PATH):
        for f in fnames:
            if f.endswith((".cpp", ".cc", ".cxx")):  # exclude .h/.hpp (often fail as translation units)
                path = os.path.join(root, f)
                if is_project_file(path):
                    files.append(path)
    return files


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
    """Populate data_dictionary with kind=define entries from #define lines."""
    files = _collect_define_files()
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
            # Parse "#define NAME [value...]"
            after = stripped[len("#define"):].strip()
            if not after:
                continue
            parts = after.split(None, 1)
            name = parts[0]
            value = parts[1].strip() if len(parts) > 1 else ""
            key = f"{name}@{rel_file}:{line_no}"
            data_dictionary[key] = {
                "kind": "define",
                "name": name,
                "qualifiedName": name,
                "value": value,
                "text": full,
                "location": {"file": rel_file, "line": line_no},
            }


def main():
    source_files = _collect_source_files()
    total = len(source_files)
    print(f"Parsing {total} files...")
    for i, path in enumerate(source_files, 1):
        print(f"  parser: {i}/{total} files...", end="\r", flush=True)
        parse_file(path)
    print()

    print(f"Collecting calls ({total} files)...")
    for i, path in enumerate(source_files, 1):
        print(f"  parser: {i}/{total} files...", end="\r", flush=True)
        parse_calls(path)
    print()

    print(f"Collecting global access ({total} files)...")
    for i, path in enumerate(source_files, 1):
        print(f"  parser: {i}/{total} files...", end="\r", flush=True)
        parse_global_access(path)
    print()

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
    # Add defines (kind=define)
    _scan_defines()
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
