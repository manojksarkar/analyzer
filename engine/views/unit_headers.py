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


def _struct_description(type_name: str, entry: dict, label: str = "Structure") -> str:
    """One-line description for the information column of a struct/class/union row.

    A record type has no value to print, so the cell carries meaning instead: the description
    STORED on the type's data-dictionary entry, else the name-derived fallback. Shared with the
    `typedef struct` path, so one type reads the same however it was declared.

    Read, not generated (REQ-PRE-01). Phase 2 generates it and stores it on the entry, which is
    also where a reviewer's correction lands (`structDescription`). Asking the LLM here, while the
    view runs, kept the sentence nowhere: the page could not show it, every run re-paid for it, and
    a correction could never reach the document because this overwrote it on every render.
    """
    stored = str((entry or {}).get("description") or "").strip()
    return stored or _struct_info_from_name(type_name, label)


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

_HEADER_EXTS = (".h", ".hpp", ".hxx")
_LISTED_KINDS = ("typedef", "enum", "define", "struct", "class", "union")


def _orphan_candidates(dd: dict, globals_data: dict, source_unit_paths: set):
    """Every symbol declared in an ORPHAN header, keyed the way `lent` sets are.

    Returns ``{("dd", ddKey) | ("glb", varId): header path without extension}``. An orphan
    header is a header whose stem has no same-name source file, so it has no unit (and no
    section) of its own. The kind filters here are the ones the row loop applies, so a
    symbol that could never become a row cannot make a unit a USER of its header either.
    """
    src_paths = source_unit_paths or set()
    out: Dict[Tuple[str, str], str] = {}
    for key, t in (dd or {}).items():
        rel = ((t.get("location") or {}).get("file") or "").replace("\\", "/")
        hdr = _path_no_ext(rel)
        if not hdr or not rel.lower().endswith(_HEADER_EXTS) or hdr in src_paths:
            continue
        kind = t.get("kind", "")
        if kind not in _LISTED_KINDS or t.get("nestedIn"):
            continue
        if kind in ("struct", "class", "union") and (t.get("name") or "") in ("", "(anonymous)"):
            continue
        out[("dd", key)] = hdr
    for gid, g in (globals_data or {}).items():
        rel = ((g.get("location") or {}).get("file") or "").replace("\\", "/")
        hdr = _path_no_ext(rel)
        if not hdr or not rel.lower().endswith(_HEADER_EXTS) or hdr in src_paths:
            continue
        out[("glb", gid)] = hdr
    return out


def _orphan_uses(candidates: dict, dd: dict, unit_fids: set, used_macro_keys: set,
                 used_type_qns: set, text_names: set, global_users: dict) -> dict:
    """The orphan-header symbols ONE unit uses: the subset of `candidates` it references.

    "Uses" = the usage index (edges.json: a function of this unit mentions it) OR the name
    appears in the unit's own source text, comments and literals removed -- the text
    catches file-scope uses (array sizes, initialisers, macro-in-macro) the index cannot
    see. An enum also counts through any of its enumerator names. A global counts only
    through a function of the unit reading or writing it; including the header is not use.
    """
    out = {}
    for ck, hdr in candidates.items():
        cat, key = ck
        if cat == "glb":
            if unit_fids and unit_fids.intersection((global_users or {}).get(key) or ()):
                out[ck] = hdr
            continue
        t = dd.get(key) or {}
        sym = t.get("name") or key
        if t.get("kind") == "define":
            rel = ((t.get("location") or {}).get("file") or "").replace("\\", "/")
            hit = f"{t.get('name') or ''}@{rel}" in used_macro_keys or sym in text_names
        else:
            qn = t.get("qualifiedName") or key
            hit = qn in used_type_qns or sym in text_names or qn in text_names
            if not hit and t.get("kind") == "enum":
                hit = any((e.get("name") or "") in text_names for e in (t.get("enumerators") or []))
        if hit:
            out[ck] = hdr
    return out


def _unit_index_uses(unit_fids: set, macro_users: dict, type_users: dict):
    """(macro keys, type qualified names) that a function of the unit mentions, per edges.json."""
    used_macro_keys = {mk for mk, fids in (macro_users or {}).items() if unit_fids.intersection(fids)}
    used_type_qns = {tq for tq, fids in (type_users or {}).items() if unit_fids.intersection(fids)}
    return used_macro_keys, used_type_qns


def _orphan_owners(uses_by_unit: dict, header_component, unit_names: dict) -> Dict[str, set]:
    """unitKey -> the orphan-header symbols that unit lists. Each header is listed ONCE.

    One owner per header, not per symbol, so a header's symbols are never scattered across
    units: the first unit by name in the header's OWN component that uses anything from it,
    or -- when no unit there does -- the first using unit anywhere. The owner lists every
    symbol of that header that ANY unit uses; the other users list none of it (review
    RV-4, 2026-09-24: an enum repeated in every using unit). Chosen over the whole model,
    not the group being rendered, so one header lands in the same place in every document.
    """
    users: Dict[str, set] = {}
    used: Dict[str, set] = {}
    for uk, syms in uses_by_unit.items():
        for ck, hdr in syms.items():
            users.setdefault(hdr, set()).add(uk)
            used.setdefault(hdr, set()).add(ck)
    lent: Dict[str, set] = {}
    for hdr in sorted(users):
        comp = header_component(hdr)
        pool = [u for u in users[hdr] if comp and u.split(KEY_SEP)[0] == comp] or users[hdr]
        owner = min(pool, key=lambda u: ((unit_names.get(u) or u).casefold(), u))
        lent.setdefault(owner, set()).update(used[hdr])
    return lent


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
    lent: Optional[set] = None,
) -> List[Dict[str, str]]:
    """Build rows for unit header table.

    - Column 1: full declaration as in code
    - Column 2: value (initializer / underlying type / enumerator values)

    Besides declarations defined in the unit's own files, also lists symbols declared
    in an *orphan header* (a header with no same-name source): exactly the ``lent`` set,
    ``{("dd", ddKey) | ("glb", varId)}``. ``run`` hands each header's used symbols to ONE
    owner unit (`_orphan_owners`). Called without ``lent``, the unit lists the orphan
    symbols it uses itself -- the per-unit test the owner rule is built from.
    ``source_unit_paths`` is the set of extension-less paths that have a source file,
    used to tell an orphan header apart from a companion header.
    """
    rows: List[Dict[str, str]] = []
    dd = data_dictionary or {}
    unit_paths_set = set(_unit_paths(unit_info))

    unit_fids = set(unit_info.get("functionIds") or [])
    if lent is None:
        _mk, _tq = _unit_index_uses(unit_fids, macro_users, type_users)
        lent = set(_orphan_uses(
            _orphan_candidates(dd, global_variables_data, source_unit_paths),
            dd, unit_fids, _mk, _tq, used_symbol_names or set(), global_users,
        ))

    # Globals: use model/globalVariables.json so we can read exact line(s)
    #
    # NOT filtered on visibility, unlike the interface table. This table says what the
    # unit DECLARES AND USES, not what it publishes -- a private global still appears in
    # the unit's own flowcharts and descriptions, so leaving it out left the reader with a
    # name the document never explains. Client decision, 2026-09-22; see SWE3_WIKI N.1.4.
    _gids = list(unit_info.get("globalVariableIds", []) or [])

    # A global declared in an ORPHAN header belongs to no unit, so it used to appear
    # nowhere at all -- while the flowcharts of the units reading it named it. It is listed
    # with the rest of its header's symbols, by that header's owner unit (see `lent`).
    _own = set(_gids)
    _gids.extend(sorted(key for cat, key in lent if cat == "glb" and key not in _own))

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
        # Anything else is listed only when it comes from an orphan header and this unit
        # is where that header's symbols are listed (`lent`).
        if not is_own and ("dd", _type_name) not in lent:
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
                # typedef struct: the underlying record's stored description (REQ-PRE-01)
                info = _struct_description(
                    t.get("name") or underlying or _type_name,
                    enum_ent,
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
                t.get("name") or _type_name, t, _RECORD_LABEL.get(kind, "Structure"),
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


def _lent_by_unit(model, dd, globals_data, macro_users, type_users, source_unit_paths,
                  used_names, global_users) -> Dict[str, set]:
    """unitKey -> the orphan-header symbols it lists, over EVERY source-backed unit.

    Not limited to the group being rendered: the owner of a header must come out the same
    in every document, or two documents would each list it -- or neither would.
    """
    units_data = model.get("units", {}) or {}
    candidates = _orphan_candidates(dd, globals_data, source_unit_paths)
    if not candidates:
        return {}
    macro_by_fid: Dict[str, set] = {}
    for mk, fids in (macro_users or {}).items():
        for fid in fids:
            macro_by_fid.setdefault(fid, set()).add(mk)
    type_by_fid: Dict[str, set] = {}
    for tq, fids in (type_users or {}).items():
        for fid in fids:
            type_by_fid.setdefault(fid, set()).add(tq)
    uses = {}
    for uk, u in units_data.items():
        if not (u.get("fileName") or "").lower().endswith((".cpp", ".cc", ".cxx")):
            continue
        fids = set(u.get("functionIds") or [])
        mk = set().union(*(macro_by_fid.get(f, set()) for f in fids)) if fids else set()
        tq = set().union(*(type_by_fid.get(f, set()) for f in fids)) if fids else set()
        found = _orphan_uses(candidates, dd, fids, mk, tq, used_names.get(uk) or set(),
                             global_users)
        if found:
            uses[uk] = found
    # A header's component: the unit keyed off it when it has one (a header with a function
    # or a global), else the component whose source folders hold it.
    header_comp: Dict[str, str] = {}
    for uk, u in units_data.items():
        if u.get("path") and KEY_SEP in uk:
            header_comp.setdefault(u["path"], uk.split(KEY_SEP)[0])
    for comp, c in sorted((model.get("components") or {}).items()):
        for h in (c or {}).get("headerFiles") or []:
            header_comp.setdefault(_path_no_ext(h), comp)
    names = {uk: (u.get("name") or uk.split(KEY_SEP)[-1]) for uk, u in units_data.items()}
    return _orphan_owners(uses, lambda h: header_comp.get(h, ""), names)


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
    lent_by_unit = _lent_by_unit(model, data_dict, globals_data, macro_users, type_users,
                                 source_unit_paths, used_names, global_users)
    # Kept for build_rows' signature. Record descriptions are READ from the stored entry now
    # (see _struct_description), so nothing here asks the LLM.
    abbreviations = load_abbreviations(_paths().project_root, config)

    allowed = {c.lower() for c in (config.get("_analyzerAllowedComponents") or [])}
    rows_by_unit: Dict[str, List[Dict[str, str]]] = {}
    for unit_key, unit_info in units_data.items():
        if allowed and unit_key.split(KEY_SEP)[0].lower() not in allowed:
            continue
        # Only a source-backed unit gets a section in the document, so only one needs rows.
        # A header-only entry -- an orphan header, which units_data holds because a unit is
        # keyed off a file -- would put rows in the JSON that nothing renders, and its
        # symbols are already listed by the unit that owns that header (`_lent_by_unit`).
        if not (unit_info.get("fileName") or "").lower().endswith((".cpp", ".cc", ".cxx")):
            continue
        rows_by_unit[unit_key] = build_rows(
            unit_info, [], data_dict, globals_data, base_path, config, abbreviations,
            macro_users, type_users, source_unit_paths,
            used_names.get(unit_key),
            global_users,
            lent=lent_by_unit.get(unit_key, set()),
        )

    out_path = os.path.join(output_dir, "unit_headers.json")
    os.makedirs(output_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows_by_unit, f, indent=2)
    log("unit_headers.json (%d units, %d rows)" % (
        len(rows_by_unit), sum(len(v) for v in rows_by_unit.values())))
