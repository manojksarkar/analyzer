"""Per-TU include-closure capture — the pure core (M4.0, doc 04 §11.2).

A translation unit's parse result is a pure function of its preprocessed input: the
`.cpp` plus every transitively `#include`d file. Recording that closure per TU lets a
future incremental parse (M4) mark a TU "affected" iff its closure intersects the
`git diff` — soundly covering header/macro/template fan-out (all three propagate only
through `#include`).

This module is deliberately libclang-free so it is unit-testable: given the raw
included-file paths libclang reports for a TU (`TranslationUnit.get_includes()`), it
normalizes them to **repo-relative, forward-slash** paths and keeps only the **in-repo**
ones (system / third-party headers outside the repo can never appear in a git diff).

Paths are stored **case-preserved** so the closure lines up byte-for-byte with
`functions.json` `location.file` and `git diff` output. Case-insensitive *matching*
(Windows) is M4.1's concern, applied uniformly at compare time — not baked in here.
"""
from __future__ import annotations

import os
from typing import Iterable, List, Optional


def to_repo_relative(abs_path: str, base_path: str) -> Optional[str]:
    """Return `abs_path` as a repo-relative, forward-slash path, or None if it lies
    outside `base_path` (a system / third-party header git never tracks).

    The in-repo test is case-insensitive (Windows) and guards against a `foo` vs
    `foobar` prefix collision; the returned path preserves the original casing.
    """
    if not abs_path:
        return None
    a = os.path.abspath(abs_path)
    b = os.path.abspath(base_path)
    a_nc, b_nc = os.path.normcase(a), os.path.normcase(b)
    if a_nc != b_nc and not a_nc.startswith(b_nc + os.sep):
        return None
    return os.path.relpath(a, b).replace("\\", "/")


def build_closure(source_path: str, included_paths: Iterable[str], base_path: str) -> List[str]:
    """Normalize libclang's included-file list for one TU into a sorted, de-duped list
    of in-repo, repo-relative paths. Excludes the TU's own source file and any
    out-of-repo headers."""
    src_rel = to_repo_relative(source_path, base_path)
    out = set()
    for p in included_paths:
        rel = to_repo_relative(p, base_path)
        if rel is not None and rel != src_rel:
            out.add(rel)
    return sorted(out)
