"""text_overrides, text_override_history, view_derivations — Review & Update

A reviewer corrects the LLM's wording in a generated document; the correction is stored,
shows in the UI, reaches the exported DOCX, and carries into the next version.
Spec: docs/spec/REVIEW_UPDATE_SPEC.md · Design: docs/design/REVIEW_UPDATE_DESIGN.md

Three tables, each doing one job:

  **text_overrides** — the CURRENT state of one slot, one row. Read on every page render, so
  it is a single indexed lookup rather than "the newest row in history": read cost must not
  grow with how often someone edited a slot (REQ-ST-05). It carries BOTH texts, because the
  LLM original is what undo restores and the "wrong" half of the training pair — a correction
  without it teaches nothing.

  **text_override_history** — append-only, one row per edit, trimmed to the newest N per slot.
  `llm_text` deliberately does NOT live here: keeping it on `text_overrides` is what makes
  "the original is never evicted by the cap" structural instead of a rule someone must
  remember (REQ-ST-04).

  **view_derivations** — when each view was last derived from the model. Input to the export
  guard: an override newer than the oldest derivation means the rendered views are stale.
  Without that check `reexport --from-phase 4`, which is "export only" and skips the phase
  that rebuilds the views, ships the previous text silently (REQ-AP-04).

All three cascade from `versions` and are registered in `PER_VERSION_TABLES`, so deleting a
version takes them with it.

Additive: three new tables, no existing table touched. Safe to apply ahead of the code — an
empty `text_overrides` is exactly the state of a project where nobody has corrected anything,
which is every project today.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0010_text_overrides"
down_revision = "0009_model_units_description"
branch_labels = None
depends_on = None

_JSONB = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "text_overrides",
        sa.Column("version_id", sa.String(), sa.ForeignKey("versions.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("slot_kind", sa.String(), nullable=False),
        sa.Column("slot_key", sa.String(), nullable=False),
        sa.Column("llm_text", sa.Text()),
        sa.Column("human_text", sa.Text(), nullable=False),
        sa.Column("is_orphaned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_by", sa.String()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("llm_model", sa.String()),
        sa.Column("llm_cache_version", sa.Integer()),
        sa.Column("llm_context", _JSONB),
        sa.UniqueConstraint("version_id", "slot_kind", "slot_key", name="pk_text_overrides"),
    )
    op.create_index("ix_text_overrides_version_kind", "text_overrides",
                    ["version_id", "slot_kind"])
    op.create_index("ix_text_overrides_updated", "text_overrides",
                    ["version_id", "updated_at"])

    op.create_table(
        "text_override_history",
        sa.Column("history_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
                  primary_key=True, autoincrement=True),
        sa.Column("version_id", sa.String(), sa.ForeignKey("versions.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("slot_kind", sa.String(), nullable=False),
        sa.Column("slot_key", sa.String(), nullable=False),
        sa.Column("human_text", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.String()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
    )
    op.create_index("ix_override_history_slot", "text_override_history",
                    ["version_id", "slot_kind", "slot_key", "seq"])

    op.create_table(
        "view_derivations",
        sa.Column("version_id", sa.String(), sa.ForeignKey("versions.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("view_name", sa.String(), nullable=False),
        sa.Column("group_name", sa.String(), nullable=False, server_default=""),
        sa.Column("derived_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("version_id", "view_name", "group_name", name="pk_view_derivations"),
    )


def downgrade() -> None:
    op.drop_table("view_derivations")
    op.drop_index("ix_override_history_slot", table_name="text_override_history")
    op.drop_table("text_override_history")
    op.drop_index("ix_text_overrides_updated", table_name="text_overrides")
    op.drop_index("ix_text_overrides_version_kind", table_name="text_overrides")
    op.drop_table("text_overrides")
