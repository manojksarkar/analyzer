"""model_units.description — the unit description becomes stored data

The unit description was produced INSIDE the DOCX exporter and kept nowhere:
`get_unit_description(...)` was called at docx_exporter.py:1074 while rendering the
Component/Unit/Description table, used for that one cell, and discarded.

Three consequences, all fixed by giving it a column:

  * the HTML view could not show it at all — it does not run the exporter, so the cell was
    simply absent from the product's main review surface;
  * every export re-paid for the LLM call, and two exports of one version had no reason to
    word it the same;
  * it could not be corrected by a reviewer, because there was nothing to correct — the
    prerequisite for REQ-PRE-01 in docs/spec/REVIEW_UPDATE_SPEC.md.

Phase 2 now generates it (after the function and global descriptions it is built FROM) and
stores it here; the exporter reads it.

The struct description made the same journey and needs no migration: `persist_types` stores
a type's whole payload minus `location`, so a `description` key added in Phase 2 lands
without a schema change.

Additive and nullable. Safe against a populated database: an existing version simply has no
unit description until it is regenerated, and the exporter keeps its deterministic fallback.
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_model_units_description"
down_revision = "0008_class_name_and_llm_timing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model_units", sa.Column("description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("model_units", "description")
