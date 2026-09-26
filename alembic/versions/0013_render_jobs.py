"""render_jobs — pictures waiting to be redrawn after a label was corrected

Spec: REQ-IM-01/02/03 · Design: docs/design/REVIEW_UPDATE_DESIGN.md §7

Correcting a flowchart node label changes the picture, not just the text. The redraw is recorded
as a job rather than left implicit, for one reason above all: **the export has to be able to ask
whether a picture is still being produced**. Without a durable answer, an export a second after an
edit ships the new text everywhere and the old image -- the same split-origin failure that once
left a stored graph and a document picture coming from different versions.

It also lets the render run where the resources are. Rendering needs an output tree and Graphviz,
and the host that saves a correction is not guaranteed to have either.

Deliberately NOT unique on (version_id, flowchart_id). A second correction arriving while the
first render is still pending is a second job: collapsing them would let a render that began
before the second edit satisfy it, leaving the picture one edit behind with nothing pending to say
so.

Additive -- one new table, nothing existing touched. An empty table is the state of every project
today.
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_render_jobs"
down_revision = "0012_regeneration_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "render_jobs",
        sa.Column("job_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
                  primary_key=True, autoincrement=True),
        sa.Column("version_id", sa.String(), sa.ForeignKey("versions.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("flowchart_id", sa.String(), nullable=False),
        sa.Column("png_name", sa.String()),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("requested_by", sa.String()),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_render_jobs_pending", "render_jobs", ["version_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_render_jobs_pending", table_name="render_jobs")
    op.drop_table("render_jobs")
