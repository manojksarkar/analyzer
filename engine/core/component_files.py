"""Which source files each configured component gets -- and the paths that give it none.

Phase 1's rule, in one place (parser.py imports it from here):

* a path with a C/C++ extension is one file; any other path is a folder, and every source
  file under it belongs to the component (`build_file_component_map`);
* where two components list the same file, the first one in the config keeps it;
* the parse then reads the translation units and headers among them (`PARSED_EXTS`), minus the
  files `excludeNamePatterns` drops (`exclude_name_patterns`).

`component_path_problems` reads a config against a checkout with that same rule BEFORE the
parse. The parser skips a folder that is not there without a word, so a mistyped, moved or
wrongly-cased path surfaced only after the whole parse: a component left with no file is not in
the model, and Phase 3 stops the run on it (run_views._assert_components_in_model) with a message
about re-export scopes - not about the path.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

SOURCE_EXTS = {'.cpp', '.cc', '.cxx', '.c', '.h', '.hpp', '.hxx'}
TU_EXTS = (".cpp", ".cc", ".cxx")         # parsed first, as translation units
HEADER_EXTS = (".h", ".hpp", ".hxx")      # parsed after them
PARSED_EXTS = TU_EXTS + HEADER_EXTS       # a `.c` file is mapped to its component, never parsed

# A report of 200 lines is read by nobody: the first ones name the problem.
_MAX_MESSAGES = 40


def exclude_name_patterns(cfg: Dict[str, Any], include_emulator: bool = False) -> List[str]:
    """Basename substrings (lower case) whose files Phase 1 skips: the config's
    `excludeNamePatterns`, `["emul"]` when it has none (3.1), nothing with --include-emulator."""
    patterns = cfg.get("excludeNamePatterns")
    if patterns is None:
        patterns = ["emul"]
    return [] if include_emulator else [str(p).lower() for p in patterns if p]


def merge_group_components(groups: Any) -> dict:
    """{component: path | [paths]} across every group, the way Phase 1 reads a layered config:
    a component listed by two groups keeps each of its paths once, first seen first."""
    merged: dict = {}
    if not isinstance(groups, dict):
        return merged
    for _, grp in groups.items():
        if not isinstance(grp, dict):
            continue
        for component, paths in grp.items():
            if not paths:
                continue
            if isinstance(paths, str):
                paths_list = [paths]
            else:
                paths_list = list(paths) if isinstance(paths, list) else []
            if component not in merged:
                merged[component] = paths_list if len(paths_list) != 1 else paths_list[0]
            else:
                existing = merged.get(component)
                if isinstance(existing, str):
                    existing_list = [existing]
                else:
                    existing_list = list(existing) if isinstance(existing, list) else []
                for p in paths_list:
                    if p and p not in existing_list:
                        existing_list.append(p)
                merged[component] = existing_list if len(existing_list) != 1 else existing_list[0]
    return merged


def build_file_component_map(components_cfg: dict, base_path: str) -> dict:
    """Resolve component config to {lowercase_relpath: component}.

    Each entry (string or element of a list) is inspected individually:
    - Known C/C++ extension → added as an exact file.
    - No recognised extension → treated as a directory; all source files
      under it are included recursively.

    setdefault ensures the first component in config iteration order wins on overlap.
    """
    file_map: dict = {}
    for component, paths in (components_cfg or {}).items():
        if isinstance(paths, str):
            paths = [paths]
        for p in (paths or []):
            p_norm = (p or "").replace("\\", "/").lstrip("./").rstrip("/")
            if not p_norm:
                continue
            _, ext = os.path.splitext(p_norm)
            if ext.lower() in SOURCE_EXTS:
                # Explicit file entry — add directly
                file_map.setdefault(p_norm.lower(), component.replace(" ", "-"))
            else:
                # Directory entry — walk the filesystem
                abs_dir = os.path.join(base_path, p_norm)
                if not os.path.isdir(abs_dir):
                    continue
                for root, _, files in os.walk(abs_dir):
                    for fname in files:
                        if os.path.splitext(fname)[1].lower() in SOURCE_EXTS:
                            full = os.path.join(root, fname)
                            key = os.path.relpath(full, base_path).replace("\\", "/").lower()
                            file_map.setdefault(key, component.replace(" ", "-"))
    return file_map


# ---------------------------------------------------------------------------
# The check before the parse
# ---------------------------------------------------------------------------

def _entries(cfg: Dict[str, Any]) -> List[Tuple[str, str, List[str], List[str]]]:
    """(component id, display name, resolved paths, group ids) for every component, in config
    order. The id is the one the parser keys files by; the name reads `Layer1 / Group / Component`."""
    from core.config import get_flat_groups, make_qualified_id
    legacy = cfg.get("components") or cfg.get("modules")
    if legacy:
        return [(c, c, [p] if isinstance(p, str) else list(p or []), [])
                for c, p in legacy.items()]
    names: Dict[str, str] = {}
    for lname, layer in (cfg.get("layers") or {}).items():
        for gname, comps in ((layer or {}).get("groups") or {}).items() if isinstance(layer, dict) else ():
            for cname in (comps if isinstance(comps, dict) else {}):
                names.setdefault(make_qualified_id(lname, cname), f"{lname} / {gname} / {cname}")
    flat = get_flat_groups(cfg)
    groups_of: Dict[str, List[str]] = {}
    for gid, comps in (flat or {}).items():
        for cid in (comps if isinstance(comps, dict) else {}):
            groups_of.setdefault(cid, []).append(gid)
    merged = merge_group_components(flat)
    return [(c, names.get(c, c), [p] if isinstance(p, str) else list(p or []), groups_of.get(c, []))
            for c, p in merged.items()]


def _ident(name: Any) -> str:
    """How run_views compares component names: spaces as '-', any case."""
    return str(name or "").strip().replace(" ", "-").casefold()


def _rendered(entries, scope: Optional[Dict[str, Any]]) -> set:
    """The components this run renders a document for - so the ones Phase 3 stops on when the
    parse gave them nothing: every one for the project scope, those of the named groups, or the
    named components. None for a `layer:` scope, which writes the model and no document."""
    stype = (scope or {}).get("type") or "project"
    names = {_ident(n) for n in ((scope or {}).get("names") or [])}

    def said(qualified: str) -> bool:
        # A scope names `Layer1.Support`, or just `Support`: either counts. Erring this way
        # can only stop a run Phase 3 would have stopped anyway.
        return bool({_ident(qualified), _ident(str(qualified).split(".", 1)[-1])} & names)

    if stype == "project":
        return {c for c, *_ in entries}
    if stype == "group":
        return {c for c, _, _, groups in entries if not groups or any(said(g) for g in groups)}
    if stype == "component":
        return {c for c, *_ in entries if said(c)}
    return set()


def _norm(p: str) -> str:
    return (p or "").replace("\\", "/").lstrip("./").rstrip("/")


def _spelling(root: str, rel: str, cache: Dict[str, Optional[List[str]]]) -> Optional[str]:
    """`rel` as the checkout spells it, matched case-insensitively; None when it is not there."""
    cur, out = root, []
    for seg in rel.split("/"):
        if cur not in cache:
            try:
                cache[cur] = os.listdir(cur)
            except OSError:
                cache[cur] = None
        names = cache[cur]
        if not names:
            return None
        hit = seg if seg in names else next((n for n in names if n.lower() == seg.lower()), None)
        if hit is None:
            return None
        out.append(hit)
        cur = os.path.join(cur, hit)
    return "/".join(out)


def component_path_problems(cfg: Dict[str, Any], checkout: str,
                            include_emulator: bool = False,
                            scope: Optional[Dict[str, Any]] = None) -> Tuple[List[str], List[str]]:
    """(warnings, errors) about the component paths in `cfg`, read against `checkout` - the
    source tree the run parses - with Phase 1's own rule.

    Warnings, one per path the parse gets nothing from:
      * the path is not in the checkout;
      * a folder spelled in another case: found on Windows, missed on a case-sensitive file
        system (a FILE entry matches in any case everywhere, so it is fine);
      * a folder with no file the parse reads, or a path the parse cannot read at all.
    A component left with NO file - for one of those reasons, or because a component listed
    before it took its files - is an error when this run renders it (`scope`, see _rendered):
    Phase 3 would stop the run on it after the whole parse, so the run stops before the parse
    instead, saying why. A component the run does not render is a warning. When no component
    gets a file at all, the checkout, branch or config is the wrong one: an error, first.
    """
    if not checkout or not os.path.isdir(checkout):
        return [], []
    entries = _entries(cfg)
    if not entries:
        return [], []                   # no component config: the parser reads every file
    excluded = exclude_name_patterns(cfg, include_emulator)
    cache: Dict[str, Optional[List[str]]] = {}
    # Which component each file goes to - first listed wins, exactly as in the parse.
    owner = build_file_component_map({c: ps for c, _, ps, _ in entries}, checkout)
    # A file found by walking a folder is there; a file the config names may not be.
    named = {_norm(p).lower() for _, _, ps, _ in entries for p in ps
             if os.path.splitext(_norm(p))[1].lower() in SOURCE_EXTS}

    def read(key: str) -> bool:
        """Would the parse read this file? Parsed extension, not excluded, and there."""
        return (key.endswith(PARSED_EXTS)
                and not any(pat in key.rsplit("/", 1)[-1] for pat in excluded)
                and (key not in named or _spelling(checkout, key, cache) is not None))

    files_of: Dict[str, int] = {}
    for key, comp in owner.items():
        if read(key):
            files_of[comp] = files_of.get(comp, 0) + 1
    shown = {comp.replace(" ", "-"): where for comp, where, *_ in entries}    # map id -> name
    rendered = _rendered(entries, scope)

    warnings: List[str] = []
    errors: List[str] = []
    empty = 0
    for comp, where, paths, _groups in entries:
        for raw in paths:
            p = _norm(raw)
            if not p:
                continue
            actual = _spelling(checkout, p, cache)
            is_file_entry = os.path.splitext(p)[1].lower() in SOURCE_EXTS
            if actual is None:
                warnings.append(f"{where}: `{p}` is not in the checkout")
                continue
            abs_path = os.path.join(checkout, actual)
            if is_file_entry:
                if not os.path.isfile(abs_path):
                    warnings.append(f"{where}: `{p}` is a folder, but its name ends like a "
                                    f"source file, so the parse looks for a file")
                elif not p.lower().endswith(PARSED_EXTS):
                    warnings.append(f"{where}: `{p}` is a .c file, which the parse does not read")
                elif not read(p.lower()):
                    warnings.append(f"{where}: `{p}` is skipped by excludeNamePatterns "
                                    f"({', '.join(excluded)})")
                continue
            if not os.path.isdir(abs_path):
                warnings.append(f"{where}: `{p}` is a file the parse does not read - it reads "
                                f"{' '.join(PARSED_EXTS)} files, and folders")
                continue
            if actual != p:
                if os.path.isdir(os.path.join(checkout, p)):
                    warnings.append(f"{where}: `{p}` is spelled `{actual}` in the checkout - "
                                    f"found here, but missed on a case-sensitive file system "
                                    f"(Linux)")
                else:
                    warnings.append(f"{where}: `{p}` is not in the checkout - it has `{actual}`")
                    continue
            got = build_file_component_map({comp: [p]}, checkout)
            if not any(read(k) for k in got):
                warnings.append(f"{where}: `{p}` has no file the parse reads "
                                f"({' '.join(PARSED_EXTS)})")
        key = comp.replace(" ", "-")
        if not files_of.get(key):
            empty += 1
            candidates = [k for k in build_file_component_map({comp: paths}, checkout) if read(k)]
            others = sorted({shown.get(owner[k], owner[k]) for k in candidates
                             if owner.get(k) not in (None, key)})
            why = (f" (its files belong to {', '.join(others)}, listed before it)"
                   if candidates and others else "")
            if comp in rendered:
                errors.append(f"{where} gets no source file{why}: Phase 3 would stop the run on "
                              f"it after the whole parse. Fix its path, or take it out")
            else:
                warnings.append(f"{where} gets no source file{why}: a run that renders it "
                                f"stops in Phase 3")

    if empty == len(entries):
        errors.insert(0, f"None of the {len(entries)} components has a source file in the "
                         f"checkout {checkout} - is it the right repository, branch or config?")
    return _cut(warnings), _cut(errors)


def _cut(messages: List[str]) -> List[str]:
    """The first _MAX_MESSAGES, and how many more there are."""
    if len(messages) <= _MAX_MESSAGES:
        return messages
    return messages[:_MAX_MESSAGES] + [f"... and {len(messages) - _MAX_MESSAGES} more"]
