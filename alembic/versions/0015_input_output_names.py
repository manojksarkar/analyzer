"""The slot kinds `behaviourInputName` / `behaviourOutputName` become `inputName` / `outputName`.

They are a function's input and output names, printed in its flowchart table as well as in the
Dynamic Behaviour table, so "behaviour" named the wrong thing. From this revision the engine, the
model and the review API use the new names; this renames them where they are stored as DATA: a
correction's `slot_kind`, its history, and the regeneration queue (`slot_kind` and
`source_slot_kind`). No table or column changes.

A stored function's payload keeps its old keys: it is a content-addressed blob shared between
versions, and `core.model_store._current_fn_payload` reads it under the new names.

One slot can have rows under BOTH names: the new code saved a correction before this ran, on a
slot that already had one under the old name. A plain rename would then break the unique key
`(version_id, slot_kind, slot_key)`, and leaving the old row would keep a kind nothing reads. So
the two are merged the way a second save on one slot works: the newer row (the new name) keeps
the reviewer's words, it takes the original LLM text from the older row while that one was in
force -- the new code took the older correction's words for the original -- the older row goes,
and its history is renamed and ordered before the newer edits.

`tools/db_setup.py` (`analyzer.py setup`) runs the same `statements`, for a database whose
tables `create_all` made and Alembic never stamped.

Revision ID: 0015_input_output_names
Revises: 0014_users_is_superuser
"""
from alembic import op
import sqlalchemy as sa

revision = "0015_input_output_names"
down_revision = "0014_users_is_superuser"
branch_labels = None
depends_on = None

RENAMED = {"behaviourInputName": "inputName", "behaviourOutputName": "outputName"}


def _twin(table: str, column: str, kind: str) -> str:
    """`EXISTS` a row of `table` for the same slot of the same version with `column` = `kind`."""
    return (f"EXISTS (SELECT 1 FROM {table} twin WHERE twin.version_id = {table}.version_id"
            f" AND twin.slot_key = {table}.slot_key AND twin.{column} = {kind})")


def statements(old: str, new: str):
    """The SQL that renames slot kind `old` to `new`, in order; bound with `:old` and `:new`.

    Run once per renamed kind. Every statement is a no-op where nothing is stored under `old`,
    so running them again changes nothing.
    """
    h, t, q = "text_override_history", "text_overrides", "regeneration_queue"
    same = (f"o.version_id = {t}.version_id AND o.slot_key = {t}.slot_key"
            f" AND o.slot_kind = :old")
    return [
        # History. `seq` counts per slot, so the newer edits move up past the older ones' last
        # before the two lists become one.
        f"UPDATE {h} SET seq = seq + (SELECT MAX(o.seq) FROM {h} o"
        f" WHERE o.version_id = {h}.version_id AND o.slot_key = {h}.slot_key"
        f" AND o.slot_kind = :old) WHERE slot_kind = :new AND {_twin(h, 'slot_kind', ':old')}",
        f"UPDATE {h} SET slot_kind = :new WHERE slot_kind = :old",
        # The correction: one row per slot.
        f"UPDATE {t} SET"
        f" llm_text = (SELECT o.llm_text FROM {t} o WHERE {same}),"
        f" llm_model = (SELECT o.llm_model FROM {t} o WHERE {same}),"
        f" llm_cache_version = (SELECT o.llm_cache_version FROM {t} o WHERE {same}),"
        f" llm_context = (SELECT o.llm_context FROM {t} o WHERE {same})"
        f" WHERE slot_kind = :new AND EXISTS (SELECT 1 FROM {t} o WHERE {same}"
        f" AND NOT o.is_orphaned)",
        f"UPDATE {t} SET slot_kind = :new WHERE slot_kind = :old"
        f" AND NOT {_twin(t, 'slot_kind', ':new')}",
        f"DELETE FROM {t} WHERE slot_kind = :old AND {_twin(t, 'slot_kind', ':new')}",
        # The queue: one pending entry per slot, and the newer one already is it.
        f"UPDATE {q} SET slot_kind = :new WHERE slot_kind = :old"
        f" AND NOT {_twin(q, 'slot_kind', ':new')}",
        f"DELETE FROM {q} WHERE slot_kind = :old AND {_twin(q, 'slot_kind', ':new')}",
        f"UPDATE {q} SET source_slot_kind = :new WHERE source_slot_kind = :old",
    ]


def _rename(pairs) -> None:
    for old, new in pairs.items():
        for sql in statements(old, new):
            op.execute(sa.text(sql).bindparams(old=old, new=new))


def upgrade() -> None:
    _rename(RENAMED)


def downgrade() -> None:
    _rename({new: old for old, new in RENAMED.items()})
