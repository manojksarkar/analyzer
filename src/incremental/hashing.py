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


def hash_cursor(cursor, *, comment: str = "") -> str:
    """Token-hash a libclang cursor's source extent (includes the comment tokens
    that fall inside the extent).

    `comment` is the entity's *preceding* doc comment (which lives outside the
    extent) so a doc-comment-only change still changes the hash.
    """
    try:
        spellings = [t.spelling for t in cursor.get_tokens()]
    except Exception:
        spellings = []
    return hash_tokens(spellings, comment=comment)


def hash_macro_text(text: str) -> str:
    """Token-hash a `#define` body. `_scan_defines` is a text scan (no cursor), so
    normalize to whitespace-separated tokens (collapsing indentation and the
    line-continuation backslashes) to stay formatting-insensitive."""
    tokens = (text or "").replace("\\\n", " ").replace("\\", " ").split()
    return hash_tokens(tokens)
