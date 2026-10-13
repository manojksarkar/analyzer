"""What a function is called where a reader sees it, and what its flowchart is called on disk.

A unit may hold several functions of one name:

* overloads -- `scale(int)` and `scale(float)`: one qualified name, different parameters;
* the same name in different scopes -- `fast::init` and `slow::init`, or a method of two
  classes of one name in different namespaces.

`utils.scoped_name` prints a function as `Class::name` (namespaces dropped), which is one string
for all of them: two headings in the document read the same, and the reader cannot tell which
function a section is about. A flowchart was keyed by the qualified name inside its unit, so
overloads shared one file and one picture too -- the last one drawn.

ONE rule, here, for every place that prints a name (interface table, section headings, flowchart
titles, SWE.4, the web reader) and for every place that names a flowchart file:

* a name that is the only one of its kind in the unit is printed as before -- nothing moves for
  a function that shares its name with nobody;
* same name, different scopes: the full qualified name tells them apart (`fast::init`);
* same qualified name (overloads): the parameter types are added (`scale(int)`).

Judged among ALL functions of the unit, not the published ones, so a function's name does not
change when a sibling gains or loses a caller.

Kept free of engine-wide imports: the API's web render (api/services/doc_render.py) uses it too.
"""
import re
from typing import Any, Dict, Iterable, List, Mapping, Tuple

KEY_SEP = "|"

# A chart's picture is `<unit>_<name>` with the characters a file name cannot hold replaced by
# `_` (utils.safe_filename, core.flowchart_svg.svg_file_name) -- `*` and `&` among them, so
# `f(T *)` and `f(T &)` would be two charts with ONE picture. An overload's types are written
# with these spelled out.
_SPELLED = (("&&", "rref"), ("&", "ref"), ("*", "ptr"))
_FILE_UNSAFE = re.compile(r'[<>:"/\\|?*,&;]')


def _file_form(name: str) -> str:
    """What a chart's name comes to as a file name, on a file system that ignores case too."""
    return _FILE_UNSAFE.sub("_", (name or "").replace(" ", "-")).casefold()


def unit_of_key(function_key: str) -> str:
    """`component|unit` of a function key (`component|unit|qualifiedName|paramTypes`)."""
    return KEY_SEP.join((function_key or "").split(KEY_SEP)[:2])


def _short(qualified_name: str) -> str:
    return ((qualified_name or "").split("::")[-1]).strip()


def scoped(qualified_name: str, class_name: str = "") -> str:
    """`Class::name`, or `name` for a free function: `utils.scoped_name`, without its imports."""
    base = _short(qualified_name)
    cls = (class_name or "").strip()
    return f"{cls}::{base}" if cls and base else base


def signature(parameters: Any) -> str:
    """`(int, const char *)` from a function's parameters; `()` for none."""
    types: List[str] = []
    for p in parameters or []:
        t = p.get("type", "") if isinstance(p, dict) else str(p or "")
        types.append(" ".join(str(t or "").split()))
    return "(" + ", ".join(types) + ")"


def _parameters(f: Mapping[str, Any]) -> Any:
    return f.get("parameters") if f.get("parameters") is not None else f.get("params")


def display_names(functions: Mapping[str, Any]) -> Dict[str, str]:
    """{function key: the name a document prints for it}, for every function of `functions`."""
    groups: Dict[Tuple[str, str], List[str]] = {}
    for fid, f in (functions or {}).items():
        if isinstance(f, dict):
            base = scoped(f.get("qualifiedName", ""), f.get("className", ""))
            groups.setdefault((unit_of_key(fid), base), []).append(fid)
    names: Dict[str, str] = {}
    for (_unit, base), fids in groups.items():
        if len(fids) == 1:
            names[fids[0]] = base
            continue
        by_scope: Dict[str, List[str]] = {}
        for fid in fids:
            by_scope.setdefault(functions[fid].get("qualifiedName", "") or base, []).append(fid)
        for qualified, same in by_scope.items():
            name = qualified if len(by_scope) > 1 else base
            for fid in same:
                names[fid] = name + (signature(_parameters(functions[fid])) if len(same) > 1 else "")
    return names


def overload_signatures(functions: Mapping[str, Any]) -> Dict[str, str]:
    """{function key: `(int, float)`} for the overloads alone: the functions whose qualified
    name another function of their unit has. For a document that already prints the full
    qualified name (SWE.4), this is all that is missing from it."""
    groups: Dict[Tuple[str, str], List[str]] = {}
    for fid, f in (functions or {}).items():
        if isinstance(f, dict) and f.get("qualifiedName"):
            groups.setdefault((unit_of_key(fid), f["qualifiedName"]), []).append(fid)
    return {fid: signature(_parameters(functions[fid]))
            for fids in groups.values() if len(fids) > 1 for fid in fids}


def display_name(function_key: str, functions: Mapping[str, Any]) -> str:
    """One function's printed name. For a single lookup; a view asks `display_names` once."""
    return display_names(functions).get(function_key, "")


def chart_name(function_key: str, qualified_name: str, shared: bool) -> str:
    """A flowchart's name inside its unit's file: the qualified name -- with the key's own
    parameter types when another function of the unit has that qualified name (`shared`)."""
    if not shared:
        return qualified_name
    parts = (function_key or "").split(KEY_SEP, 3)
    types = parts[3] if len(parts) > 3 else ""
    for mark, word in _SPELLED:
        types = types.replace(mark, word)
    return f"{qualified_name}({types})"


def chart_names_of(keyed: Iterable[Tuple[str, str]]) -> Dict[str, str]:
    """{function key: flowchart name} from (function key, qualified name) pairs: every function
    of the units concerned, not only the ones being drawn -- an overload drawn alone must get
    the name it has when both are."""
    keyed = [(k, q) for k, q in keyed if k and q]
    count: Dict[Tuple[str, str], int] = {}
    for key, qualified in keyed:
        count[(unit_of_key(key), qualified)] = count.get((unit_of_key(key), qualified), 0) + 1
    names = {key: chart_name(key, qualified, count[(unit_of_key(key), qualified)] > 1)
             for key, qualified in keyed}
    # Whatever is left that would still be one file in its unit (names apart only by case, or
    # by two characters a file name cannot hold) is numbered, in key order.
    files: Dict[Tuple[str, str], List[str]] = {}
    for key in sorted(names):
        files.setdefault((unit_of_key(key), _file_form(names[key])), []).append(key)
    for keys in files.values():
        for n, key in enumerate(keys[1:], start=2):
            names[key] = f"{names[key]}-{n}"
    return names


def chart_names(functions: Mapping[str, Any]) -> Dict[str, str]:
    """{function key: flowchart name} for every function of a model's `functions`."""
    return chart_names_of((fid, f.get("qualifiedName", "")) for fid, f in (functions or {}).items()
                          if isinstance(f, dict))


def stored_chart(charts: dict, units, chart_name: str, qualified_name: str, short_name: str = ""):
    """`(chart, names)`: a function's chart out of `charts` (`{unit: {name: chart}}`, the unit
    under either of its spellings in `units`), and the names its pictures are stored under.

    A chart is stored under its chart name. For every function but an overload that is the
    qualified name, with the short name behind it (charts written before names were
    qualified). An overload has a name of its own since 2026-10-13; a version generated before
    that holds it under the qualified name, shared with its siblings, and it is found there, as
    it was then. When its OWN chart is found, only its own name names a picture: the shared
    one may be a sibling's."""
    def _get(name):
        for unit in units:
            hit = (charts.get(unit) or {}).get(name) if unit and name else None
            if hit:
                return hit
        return None

    plain = [n for n in dict.fromkeys((qualified_name, short_name)) if n]
    if chart_name and chart_name not in plain:
        own = _get(chart_name)
        if own:
            return own, [chart_name]
    for name in plain:
        hit = _get(name)
        if hit:
            return hit, plain
    return None, plain


def without_signature(name: str, function_key: str, overloads: Mapping[str, str]) -> str:
    """A printed name without the parameter types an overload's carries, for a line that writes
    the parameters out itself (a signature: `int Calc::scale(int a)`, not `...scale(int)(int a)`).
    `overloads` is `overload_signatures(functions)`."""
    suffix = (overloads or {}).get(function_key)
    return name[:-len(suffix)] if suffix and name.endswith(suffix) else name
