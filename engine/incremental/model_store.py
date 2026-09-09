"""Backwards-compatible re-export of the model persistence layer.

The implementation moved to `core.model_store` so `core/model_io.py` can use it: model_io is
the choke point 51 of the 76 model read/write sites already go through, and `core/` is the
bottom of the dependency graph — it may not import from `incremental/`. Persisting the model
to Postgres is infrastructure, not incremental-specific, so it belongs in core.

This shim keeps the ~39 existing `incremental.model_store` imports working rather than
rewriting them in the same commit as the move. New code should import `core.model_store`.
"""
from core.model_store import *          # noqa: F401,F403
from core.model_store import (          # noqa: F401  - explicit, for the private names in use
    _FN_PAYLOAD_FIELDS,
    _GLOBAL_PAYLOAD_FIELDS,
    _DUMP_FILES,
    _content_hash,
    _ensure_entities,
    _entity_rows,
    _insert_blobs,
    _loc_cols,
    _split_key,
)
