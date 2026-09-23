"""Unit header table view: model -> output/unit_headers.json.

The one table in the document that used to be built at EXPORT time, inside
docx_exporter.py, and separately re-implemented in api/services/doc_render.py because
that one has no checkout to read declarations from. Two implementations of one rule is
how they drift: the same edit had to be made twice, and orphan-header lending only ever
existed on the DOCX side.

Phase 3 is the right home. It is the phase that turns the model into the document's
content, it CAN read the C++ source (metadata.json carries basePath, the same way the
exporter got it), and a change to a rendering rule re-runs views alone -- not a parse.
Phase 4 and the web view now both read the rows from here.

Reads the model plus, through core.model_io, `edges.json` and `metadata.json` -- model
files, written by phases 1-2. It reads no other VIEW's output.
"""
import json
import os
import re
from typing import Dict, List, Optional, Tuple

from .registry import register
from core.model_io import read_model_file
from core.paths import paths as _paths
from docx_common import load_abbreviations
from utils import log, KEY_SEP

NA = "N/A"

# A macro used at FILE scope -- an array bound, a global's initial value, another macro --
# is invisible to edges.json, which only records what a function body mentions. The text
# fallback below recovers those, with comments and string literals stripped first so a
# symbol merely named in a comment does not count as use.
_COMMENT_STRING_RE = re.compile(
    r'"(?:\\.|[^"\\])*"'      # string literal
    r"|'(?:\\.|[^'\\])*'"     # char literal
    r"|/\*.*?\*/"             # block comment
    r"|//[^\n]*",             # line comment
    re.DOTALL,
)

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


_INCLUDE_GUARD_RE = re.compile(r"^_*[A-Z][A-Z0-9_]*(?:_H|_HPP)_*$")
# Strip string/char literals and comments before scanning source for identifier
# usage (literals first so // or /* inside a string isn't treated as a comment).
_COMMENT_STRING_RE = re.compile(
    r'"(?:\\.|[^"\\])*"'      # string literal
    r"|'(?:\\.|[^'\\])*'"     # char literal
    r"|/\*.*?\*/"             # block comment
    r"|//[^\n]*",             # line comment
    re.DOTALL,
)


def _strip_comments(text: str) -> str:
    """Remove // and /* */ comments from a code snippet, preserving string and
    char literals (so a `//` inside a string is not mistaken for a comment).
    Trailing whitespace and lines emptied by a removed comment are dropped;
    newlines are otherwise kept so multi-line declarations keep their shape."""
    if not text:
        return text

    def _repl(m):
        tok = m.group(0)
        return "" if tok.startswith(("//", "/*")) else tok

    out = _COMMENT_STRING_RE.sub(_repl, text)
    lines = [ln.rstrip() for ln in out.splitlines()]
    lines = [ln for ln in lines if ln.strip()]
    return "\n".join(lines).strip()


def _struct_description(type_name: str, fields: list, config, abbreviations,
                       label: str = "Structure") -> str:
    """One-line description for the information column of a struct/class/union row.

    A record type has no value to print, so the cell carries meaning instead: the LLM's
    sentence when descriptions are on and the provider answers, else the name-derived
    fallback. Shared with the `typedef struct` path, so one type reads the same however it
    was declared.
    """
    info = _struct_info_from_name(type_name, label)
    if not config:
        return info
    try:
        from llm_enrichment import get_struct_description, llm_provider_reachable
        if llm_provider_reachable(config) and config.get("llm", {}).get("descriptions", True):
            llm_desc = get_struct_description(type_name, fields or [], config, abbreviations or {})
            if llm_desc:
                return llm_desc
    except ImportError:
        pass
    return info


_ACCESS_LABEL_RE = re.compile(r"^(public|protected|private)" + chr(92) + "s*:")
_RECORD_LABEL = {"class": "Class", "union": "Union", "struct": "Structure"}


def _is_member_method(line: str) -> bool:
    """True for a line that declares or defines a METHOD of the record being listed.

    Told apart from data by the name-then-paren shape, with three exclusions: a nested type
    keeps its own line, `int (*fp)(int);` is a function-POINTER member and therefore data,
    and an initialiser that happens to call something (`int n = f();`) is data too, since
    its `=` comes before the paren.
    """
    text = (line or "").strip()
    if "(" not in text:
        return False
    for kw in ("enum ", "struct ", "union ", "class ", "typedef ", "using ",
               "public:", "protected:", "private:"):
        if text.startswith(kw):
            return False
    if "(*" in text:
        return False
    head = text.split("(", 1)[0]
    if "=" in head:
        return False
    return bool(re.search(r"[A-Za-z_~][A-Za-z0-9_]*" + chr(92) + "s*$", head))


def _declarations_only(decl: str) -> str:
    """A record's declaration with every member body reduced to a declaration.

    Methods stay -- the client wants the declaration as written -- but an inline BODY does
    not: `int status() { return 1; }` is listed as `int status();`. The body is the unit's
    implementation, which the flowchart section documents; here it only makes the cell tall.

    Comments go first. Left in, they defeat nothing here, but they are stripped from the
    cell later anyway and removing them now keeps a multi-line body's tail from surviving
    as a comment after its code is gone.
    """
    lines = []
    in_block = False
    for ln in (decl or "").split(chr(10)):
        t = ln.strip()
        if in_block:
            if "*/" in t:
                in_block = False
            continue
        if t.startswith("/*") and "*/" not in t:
            in_block = True
            continue
        if t.startswith("//") or (t.startswith("/*") and t.endswith("*/")) or t.startswith("*"):
            continue
        if not t:
            continue
        lines.append(ln)

    out, dropping, depth = [], False, 0
    for ln in lines:
        if dropping:
            depth += ln.count("{") - ln.count("}")
            if depth <= 0:
                dropping = False
            continue
        if _is_member_method(ln) and "{" in ln:
            opened = ln.count("{") - ln.count("}")
            head = ln.split("{", 1)[0].rstrip()
            # `= default` / `= delete` live before the brace on some forms; a plain
            # signature just gains its semicolon.
            out.append(head + ";" if not head.endswith(";") else head)
            if opened > 0:
                dropping, depth = True, opened
            continue
        out.append(ln)
    return chr(10).join(out)


def _strip_ext(path: str) -> str:
    if not path:
        return path
    return (path or "").replace("\\", "/")


def _path_no_ext(path: str) -> str:
    base, _ = os.path.splitext(path)
    return base.replace("\\", "/")


def _unit_paths(unit_info: dict) -> List[str]:
    """Path(s) without extension for this unit (for matching dataDictionary locations)."""
    path = unit_info.get("path")
    if not path:
        return []
    if isinstance(path, list):
        return [_strip_ext(p) for p in path]
    return [_strip_ext(path)]

def _struct_info_from_name(name: str, label: str = "Structure") -> str:
    """Build a short description, e.g. 'HeapSort' -> 'Structure for Heap sorting'.

    `label` opens the sentence -- "Class" for a class, "Union" for a union, so a type is
    not announced as something it is not.
    """
    if not (name or "").strip():
        return f"{label} for (unnamed)"
    s = name.strip()
    # Snake_case -> spaces; CamelCase -> spaces before capitals
    readable = []
    for i, c in enumerate(s):
        if c == "_":
            readable.append(" ")
        elif c.isupper() and i > 0 and readable and readable[-1] != " ":
            readable.append(" ")
            readable.append(c)
        else:
            readable.append(c)
    base = "".join(readable).strip()
    # Optional: lowercase trailing 'ing' context, e.g. "Heap Sort" -> "Heap sorting"
    if base and base.endswith(" Sort"):
        base = base[:-5] + " sorting"
    return f"{label} for {base}"


def _read_decl_snippet(abs_file: str, start_line: int, *, kind: str) -> str:
    """Extract declaration snippet safely using brace depth."""

    if not abs_file or not os.path.isfile(abs_file) or start_line < 1:
        return "-"

    try:
        with open(abs_file, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except (OSError, IOError):
        return "-"

    if start_line > len(lines):
        return "-"

    i = start_line - 1
    buf = []
    max_lines = 60

    brace_depth = 0
    started = False

    for _ in range(max_lines):

        if i >= len(lines):
            break

        line = lines[i].rstrip("\n")
        stripped = line.strip()

        # skip leading comments
        if not started and (not stripped or stripped.startswith("//") or stripped.startswith("/*")):
            i += 1
            continue

        buf.append(line)

        if "{" in line:
            brace_depth += line.count("{")
            started = True

        if "}" in line:
            brace_depth -= line.count("}")

        # stop when typedef/struct block closes
        if started and brace_depth == 0 and ";" in line:
            break

        # stop simple declarations
        if not started and ";" in line:
            break

        i += 1

    out = "\n".join(buf).strip()

    # filter out function prototypes
    first_line = buf[0].strip() if buf else ""

    if "(" in first_line and ")" in first_line and first_line.endswith(";"):
        return "-"

    # `using T = int;` is recorded as a typedef -- the two declare the same thing -- so the
    # snippet guard has to accept both spellings, or a C++11 alias is read as "an extra
    # alias on a `} one_s, *one_s_2;` line" and dropped entirely.
    if kind == "typedef" and not out.lstrip().startswith(("typedef", "using")):
        return "-"

    if kind == "enum" and not (
        out.lstrip().startswith("enum") or out.lstrip().startswith("typedef enum")
    ):
        return "-"

    if kind in ("struct", "class", "union"):
        if not out.lstrip().startswith((kind, "typedef " + kind)):
            return "-"

    return out if out else "-"

def build_rows(
    unit_info: dict,
    interfaces: list,
    data_dictionary: dict,
    global_variables_data: dict,
    base_path: str,
    config: Optional[dict] = None,
    abbreviations: Optional[dict] = None,
    macro_users: Optional[dict] = None,
    type_users: Optional[dict] = None,
    source_unit_paths: Optional[set] = None,
    used_symbol_names: Optional[set] = None,
    global_users: Optional[dict] = None,
) -> List[Dict[str, str]]:
    """Build rows for unit header table.

    - Column 1: full declaration as in code
    - Column 2: value (initializer / underlying type / enumerator values)

    Besides declarations defined in the unit's own file, also surfaces
    define/enum/typedef symbols defined in an *orphan header* (a header with no
    same-name source) — but only the ones THIS unit uses, per model/edges.json
    (``macroUsers``/``typeUsers``). ``source_unit_paths`` is the set of
    extension-less paths that have a source file, used to tell an orphan header
    apart from a companion header.
    """
    rows: List[Dict[str, str]] = []
    dd = data_dictionary or {}
    unit_paths_set = set(_unit_paths(unit_info))

    # Orphan-header symbols this unit USES (from edges.json). A symbol qualifies
    # only if some function of this unit references it; symbols from an orphan
    # header the unit does not touch are never listed.
    unit_fids = set(unit_info.get("functionIds") or [])
    src_paths = source_unit_paths or set()
    # Identifier tokens appearing anywhere in this unit's own source — the textual
    # fallback that catches orphan-header usage edges.json misses (macros used at
    # file scope: array sizes, global initializers, macro-in-macro).
    text_names = used_symbol_names or set()
    used_macro_keys: set = set()
    used_type_qns: set = set()
    if unit_fids:
        for _mk, _fids in (macro_users or {}).items():
            if unit_fids.intersection(_fids):
                used_macro_keys.add(_mk)
        for _tq, _fids in (type_users or {}).items():
            if unit_fids.intersection(_fids):
                used_type_qns.add(_tq)

    # Globals: use model/globalVariables.json so we can read exact line(s)
    #
    # NOT filtered on visibility, unlike the interface table. This table says what the
    # unit DECLARES AND USES, not what it publishes -- a private global still appears in
    # the unit's own flowcharts and descriptions, so leaving it out left the reader with a
    # name the document never explains. Client decision, 2026-09-22; see SWE3_WIKI N.1.4.
    _gids = list(unit_info.get("globalVariableIds", []) or [])

    # A global declared in an ORPHAN header belongs to no unit, so it used to appear
    # nowhere at all -- while the flowcharts of the units reading it named it. Lent to
    # each unit that USES it, exactly as this header's macros and types already are
    # (`global_users` is varId -> fids, inverted from reads/writesGlobalIds). Include
    # alone is not enough: the unit has to reference it.
    if unit_fids and global_users:
        _own = set(_gids)
        for _gid, _fids in global_users.items():
            if _gid in _own or not unit_fids.intersection(_fids):
                continue
            _g = (global_variables_data or {}).get(_gid) or {}
            _rf = ((_g.get("location") or {}).get("file") or "").replace("\\", "/")
            if not _rf.lower().endswith((".h", ".hpp", ".hxx")):
                continue
            if _path_no_ext(_rf) in src_paths:          # companion header of some unit
                continue
            _gids.append(_gid)

    # One variable, two cursors: `extern int g_x;` here and `int g_x = 0;` elsewhere are
    # separate entries keyed by file:line, and nothing merges them. Where both reach one
    # unit, keep the one carrying an initial value -- the declaration says strictly less
    # about the same storage. Two initialiser-less statics of the same name stay separate:
    # they are different objects, not two views of one.
    _valued = {
        ((global_variables_data or {}).get(g) or {}).get("qualifiedName")
        for g in _gids
        if (((global_variables_data or {}).get(g) or {}).get("value") or "").strip()
    }

    for gid in _gids:
        g = (global_variables_data or {}).get(gid) or {}
        # A class's static member is already listed inside that class's own declaration, so
        # its out-of-line definition does not get a row of its own -- `int Foo::s_count = 0;`
        # would repeat what `static int s_count;` in the class already said. The cost is the
        # initial value, which lives only in the definition; accepted (client, 2026-09-23).
        if (g.get("className") or "").strip():
            continue
        if not (g.get("value") or "").strip() and g.get("qualifiedName") in _valued:
            continue
        loc = g.get("location") or {}
        rel_file = (loc.get("file") or "").replace("\\", "/")
        line = int(loc.get("line") or 0)
        abs_file = os.path.join(base_path, rel_file) if base_path and rel_file else ""
        decl = _read_decl_snippet(abs_file, line, kind="var")
        # Value column = the initializer (right of the first '='). The snippet is
        # brace-depth aware, so a multi-line array/struct initializer is captured
        # in full here; the single-line parser value (g["value"]) is the fallback.
        clean_decl = _strip_comments(decl)
        if "=" in clean_decl:
            rhs = clean_decl.split("=", 1)[1].strip().rstrip(";").strip()
        else:
            rhs = ""
        info = rhs or g.get("value") or NA
        if (decl or "").strip() in ("", "-"):
            decl = g.get("qualifiedName") or g.get("name") or str(gid) or NA
        rows.append({"declaration": decl or NA, "information": info})

    # typedef, enum, define: match by unit file(s)
    # Track (file, line) already emitted for typedefs so that multiple aliases
    # from the same declaration (e.g. "} one_s, *one_s_2;") don't produce
    # extra rows.
    _typedef_locations_seen: set = set()
    for _type_name, t in dd.items():
        loc = t.get("location") or {}
        rel_file = (loc.get("file") or "").replace("\\", "/")
        type_file = _path_no_ext(rel_file)
        if not type_file:
            continue
        kind = t.get("kind", "")
        # struct / class / union are listed in their own right now, not only through a
        # `typedef struct {...} S;` -- a type named in a flowchart or a description has to be
        # explained somewhere (client, 2026-09-23).
        if kind not in ("typedef", "enum", "define", "struct", "class", "union"):
            continue
        # A type declared INSIDE a class gets no row of its own: the class's declaration
        # already shows it, so a row would state it twice. `nestedIn` is stamped by the
        # parser, which is the only place that can tell `Outer::Inner` (a class) from
        # `ns::Type` (a namespace) -- the qualified name reads the same either way.
        if t.get("nestedIn"):
            continue
        # An anonymous record reaches us as the body of a `typedef ... {...} S;`, whose own
        # entry emits the full declaration from the same line.
        if kind in ("struct", "class", "union") and (t.get("name") or "") in ("", "(anonymous)"):
            continue
        is_own = type_file in unit_paths_set
        # An orphan header = a header file whose stem has no same-name source.
        is_orphan_header = (
            rel_file.lower().endswith((".h", ".hpp", ".hxx"))
            and type_file not in src_paths
        )
        if not is_own:
            # Only pull in orphan-header symbols this unit actually uses. "Used" =
            # the precise edges.json index OR (fallback) the symbol name appears in
            # this unit's own source text — the latter catches file-scope usages
            # (array sizes, initializers, macro-in-macro) that edges cannot see.
            if not is_orphan_header:
                continue
            _sym_name = t.get("name") or _type_name
            if kind == "define":
                if (f"{t.get('name') or ''}@{rel_file}" not in used_macro_keys
                        and _sym_name not in text_names):
                    continue
            else:
                _qn = t.get("qualifiedName") or _type_name
                _hit = (_qn in used_type_qns
                        or _sym_name in text_names or _qn in text_names)
                # An enum can be used purely via its enumerators (e.g. `x = eNone`)
                # without the enum type name ever appearing in source or edges —
                # recover it when any enumerator name shows up in this unit's text.
                if not _hit and kind == "enum":
                    _hit = any(
                        (e.get("name") or "") in text_names
                        for e in (t.get("enumerators") or [])
                    )
                if not _hit:
                    continue
        line = int(loc.get("line") or 0)
        if kind == "typedef":
            loc_key = (rel_file, line)
            if loc_key in _typedef_locations_seen:
                continue
            _typedef_locations_seen.add(loc_key)
        abs_file = os.path.join(base_path, rel_file) if base_path and rel_file else ""
        # Defines: use stored text/value from parser for exact macro
        if kind == "define":
            macro_name = t.get("name") or _type_name or ""
            macro_value = t.get("value", "") or ""
            # Skip include guards (#define FILE_NAME_H with no value)
            if not macro_value and _INCLUDE_GUARD_RE.match(macro_name):
                continue
            decl = t.get("text") or _read_decl_snippet(abs_file, line, kind="var")
            info = macro_value or NA
            if (decl or "").strip() in ("", "-"):
                decl = macro_name or NA
            rows.append({"declaration": decl or NA, "information": info})
            continue

        decl = _read_decl_snippet(abs_file, line, kind=kind)

        if kind == "typedef":
            # If the snippet didn't start with "typedef" or "using", this entry is an alias
            # at a non-start position (e.g. "} one_s, *one_s_2;" line).  The full
            # declaration is emitted by the entry at the actual "typedef struct" line,
            # so skip this one entirely rather than falling back to just the name.
            if (decl or "").strip() in ("", "-"):
                continue

            underlying = (t.get("underlyingType", "") or "").strip()

            # Only show values if typedef is aliasing an enum
            enum_ent = dd.get(underlying)

            if isinstance(enum_ent, dict) and enum_ent.get("kind") == "enum":
                enums = enum_ent.get("enumerators", []) or []
                parts = []
                for e in enums:
                    n = e.get("name", "")
                    v = e.get("value")
                    if n:
                        parts.append(f"{n}={v}" if v is not None else n)
                info = ", ".join(parts) if parts else NA

            elif isinstance(enum_ent, dict) and enum_ent.get("kind") in ("struct", "class", "union"):
                # typedef struct: description from name + fields (on the go, no store)
                info = _struct_description(
                    t.get("name") or underlying or _type_name,
                    enum_ent.get("fields") or [],
                    config, abbreviations,
                    _RECORD_LABEL.get(enum_ent.get("kind"), "Structure"),
                )
            else:
                info = NA
        elif kind == "enum":
            enums = t.get("enumerators", [])
            parts = []
            for e in enums:
                n = e.get("name", "")
                v = e.get("value")
                if n:
                    parts.append(f"{n}={v}" if v is not None else n)
            info = ", ".join(parts) if parts else NA
        elif kind in ("struct", "class", "union"):
            # The declaration as written, members and method SIGNATURES included -- only an
            # inline body is reduced to its declaration (client, 2026-09-23).
            decl = _declarations_only(decl)
            info = _struct_description(
                t.get("name") or _type_name, t.get("fields") or [], config, abbreviations,
                _RECORD_LABEL.get(kind, "Structure"),
            )
        else:
            info = NA

        if (decl or "").strip() in ("", "-"):
            decl = t.get("name") or _type_name or NA
        rows.append({"declaration": decl or NA, "information": info})

    # Strip comments from both columns — a comment is never part of a declaration
    # or a value (string/char literals are preserved). Done before dedup so rows
    # that differ only by a comment collapse together.
    for r in rows:
        r["declaration"] = _strip_comments(r.get("declaration") or "") or NA
        r["information"] = _strip_comments(r.get("information") or "") or NA

    # Deduplicate (same declaration can appear via enum + typedef entries)
    dedup = {}
    for r in rows:
        d = (r.get("declaration") or NA).strip()
        if d not in dedup:
            dedup[d] = r
        else:
            # Prefer the richer "name=value" info when both exist
            existing = dedup[d]
            existing_info = (existing.get("information") or "").strip()
            new_info = (r.get("information") or "").strip()
            if ("=" not in existing_info) and ("=" in new_info):
                dedup[d] = r
    out_rows = list(dedup.values())
    out_rows.sort(key=lambda r: (r.get("declaration") or "").lower())
    return out_rows




def _unit_used_names(functions_data: dict, globals_data: dict, base_path: str) -> Dict[str, set]:
    """unitKey -> every identifier token in that unit's own source files.

    The unit's files come from the model's own locations, not from guessing extensions.
    """
    # Per-unit identifier tokens from each unit's own source file(s) — textual
    # fallback for orphan-header usage that edges.json misses (macros used at file
    # scope aren't in macroUsers, which only sees function-body tokens).
    _unit_src_rels: Dict[str, set] = {}
    for _fid, _f in functions_data.items():
        _uk = KEY_SEP.join(_fid.split(KEY_SEP)[:2])
        _rf = ((_f.get("location") or {}).get("file") or "").replace("\\", "/")
        if _rf:
            _unit_src_rels.setdefault(_uk, set()).add(_rf)
    for _gid, _g in globals_data.items():
        _uk = KEY_SEP.join(_gid.split(KEY_SEP)[:2])
        _rf = ((_g.get("location") or {}).get("file") or "").replace("\\", "/")
        if _rf:
            _unit_src_rels.setdefault(_uk, set()).add(_rf)
    unit_used_names: Dict[str, set] = {}
    for _uk, _rels in _unit_src_rels.items():
        _ids: set = set()
        for _rel in _rels:
            _abs = os.path.join(base_path, _rel) if base_path and _rel else _rel
            try:
                with open(_abs, "r", encoding="utf-8", errors="replace") as _fh:
                    _src = _fh.read()
            except OSError:
                continue
            # Strip string/char literals and comments first so a symbol merely
            # mentioned in a comment doesn't count as usage (literals listed before
            # comments so // or /* inside a string isn't misread as a comment).
            _src = _COMMENT_STRING_RE.sub(" ", _src)
            _ids.update(re.findall(r"[A-Za-z_]\w*", _src))
        unit_used_names[_uk] = _ids
    return unit_used_names


def _global_users(functions_data: dict) -> Dict[str, set]:
    """varId -> the functions that read or write it.

    edges.json carries macroUsers and typeUsers but no equivalent for variables, and none
    is needed: the per-function read/write sets already say it.
    """
    users: Dict[str, set] = {}
    for fid, f in (functions_data or {}).items():
        for vid in (f.get("readsGlobalIds") or []) + (f.get("writesGlobalIds") or []):
            users.setdefault(vid, set()).add(fid)
    return users


@register("unitHeaders")
def run(model, output_dir, model_dir, config):
    units_data = model.get("units", {})
    functions_data = model.get("functions", {})
    globals_data = model.get("globalVariables", {})
    data_dict = model.get("dataDictionary", {})

    edges = read_model_file("edges", required=False, default={}) or {}
    macro_users = edges.get("macroUsers") or {}
    type_users = edges.get("typeUsers") or {}
    meta = read_model_file("metadata", required=False, default={}) or {}
    base_path = (meta.get("basePath") or "").strip()

    # Extension-less paths that HAVE a source file, from the full unit set: what tells an
    # orphan header (no same-name source, so no unit of its own) from a companion header.
    source_unit_paths = {
        u.get("path")
        for u in units_data.values()
        if (u.get("fileName") or "").lower().endswith((".cpp", ".cc", ".cxx")) and u.get("path")
    }
    global_users = _global_users(functions_data)
    used_names = _unit_used_names(functions_data, globals_data, base_path)
    # Only the typedef->struct description uses these, and only when the LLM is on.
    abbreviations = load_abbreviations(_paths().project_root, config)

    allowed = {c.lower() for c in (config.get("_analyzerAllowedComponents") or [])}
    rows_by_unit: Dict[str, List[Dict[str, str]]] = {}
    for unit_key, unit_info in units_data.items():
        if allowed and unit_key.split(KEY_SEP)[0].lower() not in allowed:
            continue
        # Only a source-backed unit gets a section in the document, so only one needs rows.
        # A header-only entry -- an orphan header, which units_data holds because a unit is
        # keyed off a file -- would put rows in the JSON that nothing renders, and its
        # symbols are already lent to the units that use them.
        if not (unit_info.get("fileName") or "").lower().endswith((".cpp", ".cc", ".cxx")):
            continue
        rows_by_unit[unit_key] = build_rows(
            unit_info, [], data_dict, globals_data, base_path, config, abbreviations,
            macro_users, type_users, source_unit_paths,
            used_names.get(unit_key),
            global_users,
        )

    out_path = os.path.join(output_dir, "unit_headers.json")
    os.makedirs(output_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows_by_unit, f, indent=2)
    log("unit_headers.json (%d units, %d rows)" % (
        len(rows_by_unit), sum(len(v) for v in rows_by_unit.values())))
