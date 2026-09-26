"""text_overrides.slot_shape — a node override knows which graph it was written against

Spec: REQ-ID-02 · Design: docs/design/REVIEW_UPDATE_DESIGN.md §2.1

`cfg.nodes[].id` is `n0, n1, n2…` — a POSITION, not an identity. The first draft of this
feature reused a node override in the next version whenever the function's `source_hash` was
unchanged, on the reasoning that identical source yields an identical CFG. It does not:

  * a change to the CFG builder (an analyzer upgrade) renumbers nodes with the source untouched;
  * `cfgSimplification` merges nodes once a function has more than 15 labelable ones, so
    flipping that setting -- or a function growing past the threshold -- renumbers everything
    after the first merge.

Either way the correction lands on a DIFFERENT node and nothing reports an error, which is the
same silent-wrong-attribution shape as the September interface-id collision.

The flowchart label cache already defends against this: `_apply_cached_labels` stores the
node-id set with the labels and throws the whole entry away unless it matches exactly, because
"a change to the BUILDER would shift ids while the source hash stayed the same -- that would
silently attach the wrong label to the wrong node". This column gives an override the same
guard: carry it forward only when `source_hash` is unchanged AND the node list still matches.

Nullable, and null for the six non-`nodeLabel` kinds, which have no graph to be wrong about.
Additive -- existing rows keep working; a null shape simply means "no shape claim", which is
what every row written before this migration is.
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_slot_shape"
down_revision = "0010_text_overrides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("text_overrides", sa.Column("slot_shape", sa.String()))


def downgrade() -> None:
    op.drop_column("text_overrides", "slot_shape")
