"""Affected-TU computation for the narrowed (incremental) parse (M4.1, doc 04 §11).

Given the git diff and the per-TU include closures captured by M4.0 (model/tu_includes.json),
decide which translation units must be re-parsed and whether a corner case forces a full
re-parse instead. Sound over-approximation (D7): when in doubt, parse more.

Pure (operates on plain lists/dicts) so it is unit-testable; the engine supplies the diff
and the baseline's closure map.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Set, Tuple

# Source files we treat as translation units (re-parsed) vs headers (only fan-out via closures).
_TU_EXTS = (".cpp", ".cc", ".cxx", ".c", ".c++")
_HEADER_EXTS = (".h", ".hpp", ".hh", ".hxx", ".h++", ".inc", ".ipp", ".tcc")


def _norm(p: str) -> str:
    """Normalize a repo-relative path for MATCHING: forward slashes, case-folded.

    Case-folding used to be conditional on `os.name == "nt"`, which cannot be right for a
    project built on one platform and regenerated on another. libclang reports a path as
    it was written -- on the command line or in an `#include` -- so a Windows parse can
    record `01_SRC/x.cpp` where git says `01_src/x.cpp`. On Windows both sides folded and
    matched; on Linux neither did, so the file read as unchanged and its entities kept the
    baseline's hashes. Silently: the same shape as every other bug in this area.

    Folding on both platforms is sound in the direction that matters. On Linux `Foo.h` and
    `foo.h` CAN be two files, and folding would treat them as one -- but this value is only
    ever a set-membership key for "is this file affected / should it be dropped", so the
    error is to consider one file too many. Parsing more is the safe side (doc 04, D7);
    matching too few is what leaves a stale document. `case_collisions` reports when a repo
    actually contains such a pair, so the over-approximation is never invisible.

    Callers keep the ORIGINAL casing for anything they store or return -- this is the
    comparison key, not the recorded path.
    """
    return (p or "").replace("\\", "/").strip("/").lower()


def case_collisions(paths: Iterable[str]) -> Dict[str, List[str]]:
    """{folded path -> the distinct spellings seen} for paths that differ ONLY by case.

    Empty for virtually every repo. When it is not, `_norm` is conflating real files, and
    on Linux those are genuinely separate translation units -- worth saying out loud rather
    than silently over-parsing both forever.
    """
    seen: Dict[str, Set[str]] = {}
    for p in paths:
        clean = (p or "").replace("\\", "/").strip("/")
        if clean:
            seen.setdefault(clean.lower(), set()).add(clean)
    return {k: sorted(v) for k, v in sorted(seen.items()) if len(v) > 1}


def _is_tu(path: str) -> bool:
    return path.lower().endswith(_TU_EXTS)


def _is_header(path: str) -> bool:
    return path.lower().endswith(_HEADER_EXTS)


def affected_tus(changed_paths: Iterable[str],
                 tu_includes: Dict[str, List[str]]) -> Set[str]:
    """Return the set of TU paths (keys of `tu_includes`, original casing) to re-parse:
    a TU is affected if it OR any file in its include closure was changed. Newly-added
    TUs (changed `.cpp` not yet in the closure map) are included too.

    `changed_paths` = every path in the diff (any status). `tu_includes` = {tuPath:
    [includedPaths]} from the baseline version."""
    changed = {_norm(p) for p in changed_paths}
    if not changed:
        return set()
    affected: Set[str] = set()
    for tu, includes in (tu_includes or {}).items():
        closure = {_norm(tu)}
        closure.update(_norm(p) for p in (includes or []))
        if closure & changed:
            affected.add(tu)
    # Newly-added TUs aren't in the (baseline) closure map yet — parse them too.
    known = {_norm(tu) for tu in (tu_includes or {})}
    for p in changed_paths:
        if _is_tu(p) and _norm(p) not in known:
            affected.add(p.replace("\\", "/").strip("/"))
    return affected


def full_reparse_reason(status_pairs: Iterable[Tuple[str, str]],
                        tu_includes: Optional[Dict[str, List[str]]]) -> Optional[str]:
    """Return a human-readable reason a FULL re-parse is required (so the engine takes the
    safe path), or None when a narrowed parse is sound. Triggers (doc 04 §11.4):
      * no/empty closure map (first incremental, or a schema change);
      * a HEADER added or deleted -> may shadow an existing #include and silently change
        an untouched TU's closure (we can't bound the blast radius from the diff alone).
    (Compiler-flag / toolchain changes are caught separately by the parse fingerprint.)"""
    if not tu_includes:
        return "no per-TU include closure map (model/tu_includes.json) for the baseline"
    for status, path in status_pairs:
        if status in ("A", "D") and _is_header(path):
            verb = "added" if status == "A" else "deleted"
            return f"header {verb} ({path}) — include-shadowing risk; full re-parse is safe"
    return None
