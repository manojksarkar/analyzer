"""Entity hashing for incremental change detection (M1.2).

Token-based, full SHA-256. Properties (doc 04 §4 / §22.6):

  * **Token-based** — libclang tokens, so whitespace / indentation / CRLF do not
    change the hash; a reformat is not a change.
  * **Comment-inclusive** — comment tokens inside the entity's extent are part of
    the hash, and the entity's preceding doc comment is folded in as a prefix, so
    a comment-only edit *does* change the hash (the doc comment feeds the LLM).
  * **Full SHA-256** — 64 hex chars, never truncated (collisions infeasible).
  * **One uniform hash per entity's own source.**

The hash governs **output reuse** (the LLM description / flowchart), so it covers
the entity's code tokens + its doc comment. Visibility macros (`PUBLIC`/`PRIVATE`)
are expanded to nothing by clang and are intentionally *not* in the hash — a
visibility change is caught by the changed-file re-parse (fresh model), not by
output reuse.

Keying (so the same hash table can hold all four entity kinds, and so M2 impact
can cross-reference `edges.json`):
  * function -> the model function key  `component|unit|qualifiedName|paramTypes`
  * global   -> the model global key    `component|unit|qualifiedName`
  * type     -> qualified name          e.g. `Core::Config`
  * macro    -> `name@relFile`          e.g. `MAX_RETRIES@Sample/Core/Core.h`
"""
from __future__ import annotations

import hashlib
import os
from typing import Iterable

# Field separator between tokens so "a b" never hashes the same as "ab".
_SEP = "\x1f"


def hash_tokens(tokens: Iterable[str], *, comment: str = "") -> str:
    """Full SHA-256 hex of a token-spelling sequence, with an optional doc comment
    folded in as a prefix."""
    joined = _SEP.join(tokens)
    if comment:
        joined = comment + _SEP + joined
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _extent_text_tokens(cursor) -> list:
    """The cursor's source range read straight from the file, split on whitespace.

    The fallback for when libclang hands back no tokens. Splitting on whitespace keeps
    most of the token hash's reformat-insensitivity (indentation and line breaks
    collapse); it cannot see that `a+b` and `a + b` are the same, which is a far
    smaller error than not noticing the code changed at all.
    """
    try:
        start, end = cursor.extent.start, cursor.extent.end
        if not (start.file and end.file and start.file.name == end.file.name):
            return []
        lo, hi = start.offset, end.offset
        if hi <= lo:
            return []
        with open(start.file.name, "rb") as fh:
            fh.seek(lo)
            raw = fh.read(hi - lo)
        return raw.decode("utf-8", "replace").split()
    except Exception:
        return []


def _identity_tokens(cursor) -> list:
    """Last resort: the cursor's identity and position.

    Deliberately NOT stable across edits elsewhere in the file — if the entity moves,
    the hash moves and its outputs are regenerated. Over-regenerating is the sound
    direction (doc 04, D7); the alternative is a constant hash, which pins the entity
    to "unchanged" forever and silently serves a stale flowchart.
    """
    try:
        loc = cursor.location
        name = cursor.spelling or ""
        path = os.path.basename(loc.file.name) if loc.file else ""
        return ["\x00unhashable", path, name, str(loc.line), str(cursor.extent.end.line)]
    except Exception:
        return ["\x00unhashable", str(id(cursor))]


def hash_cursor(cursor, *, comment: str = "") -> str:
    """Token-hash a libclang cursor's source extent (includes the comment tokens
    that fall inside the extent).

    `comment` is the entity's *preceding* doc comment (which lives outside the
    extent) so a doc-comment-only change still changes the hash.

    **Never hashes an empty token list.** `clang_tokenize` returns nothing for some
    perfectly valid cursors — notably when the declaration is produced by a macro
    expansion — with no error and a correct-looking extent. Hashing that gave every
    such entity `sha256("")`, one constant shared by all of them: classified UNCHANGED
    in every comparison forever, flowchart and description carried forward from the
    first version, nothing logged. On one firmware project that was 2069 of 2818
    functions. So fall back to the extent's raw text, then to the entity's identity,
    and report which path was taken via `hash_cursor.fallbacks`.
    """
    try:
        spellings = [t.spelling for t in cursor.get_tokens()]
    except Exception:
        spellings = []
    if not spellings:
        spellings = _extent_text_tokens(cursor)
        hash_cursor.fallbacks["extent_text" if spellings else "identity"] += 1
        if not spellings:
            spellings = _identity_tokens(cursor)
    return hash_tokens(spellings, comment=comment)


# {reason -> count} for the current process, so the parser can report how much of the
# model has a hash it did not want to give. Read and logged at end of parse.
hash_cursor.fallbacks = {"extent_text": 0, "identity": 0}


def hash_macro_text(text: str) -> str:
    """Token-hash a `#define` body. `_scan_defines` is a text scan (no cursor), so
    normalize to whitespace-separated tokens (collapsing indentation and the
    line-continuation backslashes) to stay formatting-insensitive."""
    tokens = (text or "").replace("\\\n", " ").replace("\\", " ").split()
    return hash_tokens(tokens)
