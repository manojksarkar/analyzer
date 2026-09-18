"""regeneration_queue — slots whose text was built from wording a human has since corrected

Spec: REQ-CS-01 · Design: docs/design/REVIEW_UPDATE_DESIGN.md §6

Some LLM text is generated FROM other LLM text. A function's description is written with its
callees' descriptions as context; a unit's description is built from the descriptions of the
functions in it. So correcting one description leaves the text derived from it describing wording
the human has already rejected.

Those dependents are recorded here rather than regenerated on the spot, for two reasons that were
checked rather than assumed:

  * `get_description` needs the function's SOURCE, and the source is NOT in the model -- it is in
    the git checkout. The host that saves a correction is not guaranteed to have one.
  * regenerating is an LLM call. Saving a sentence must not take minutes.

And it cannot be skipped instead. The description cache is keyed on the callee's source plus its
dependency hashes (`llm_core.cache.compute_hash`), and correcting a DESCRIPTION changes neither --
so the next run hits the cache and the caller keeps its stale wording for ever. This table is what
makes the regeneration eventually happen.

`source_slot_*` records which correction caused the entry, so a reviewer can be told why their edit
changed something they did not touch, and so an old entry can be explained rather than guessed at.

One row per slot: two corrections that both invalidate the same caller need it regenerated once.

Additive -- one new table, nothing existing touched. An empty queue is the state of every project
today.
"""
from alembic import op
import sqlalchemy as sa

revision = "0012_regeneration_queue"
down_revision = "0011_slot_shape"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "regeneration_queue",
        sa.Column("version_id", sa.String(), sa.ForeignKey("versions.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("slot_kind", sa.String(), nullable=False),
        sa.Column("slot_key", sa.String(), nullable=False),
        sa.Column("reason", sa.String()),
        sa.Column("source_slot_kind", sa.String()),
        sa.Column("source_slot_key", sa.String()),
        sa.Column("requested_by", sa.String()),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("version_id", "slot_kind", "slot_key",
                            name="pk_regeneration_queue"),
    )
    op.create_index("ix_regeneration_queue_version", "regeneration_queue", ["version_id"])


def downgrade() -> None:
    op.drop_index("ix_regeneration_queue_version", table_name="regeneration_queue")
    op.drop_table("regeneration_queue")
