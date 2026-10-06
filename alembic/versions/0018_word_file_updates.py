"""Word file updates — when each document's Word file was written, who started a job and why.

`documents.word_file_at`: when the run that wrote the document's working .docx started. A
correction the document prints saved after it is not in the file: that is what "out of date" means
(docs/design/WORD_FILE_UPDATES.md §4.3), for R9, A15, Approve and the update's scope alike.
`analysis_jobs.started_by` / `.reason`: whom an update's end is told to, and why it ran (update |
rebuild | submit | export | resume). `version_components.stale_layers`: the layer(s) whose addition
made a component stale ("HAL_LAYER added since").

All nullable: `analyzer.py setup` adds them to a database it made (`_add_missing_columns`), and a
document recorded before this migration falls back to its file's time on disk.

Revision ID: 0018_word_file_updates
Revises: 0017_input_output_names
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0018_word_file_updates"
down_revision = "0017_input_output_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("word_file_at", sa.DateTime(timezone=True)))
    op.add_column("analysis_jobs", sa.Column("started_by", sa.String()))
    op.add_column("analysis_jobs", sa.Column("reason", sa.String()))
    op.add_column("version_components",
                  sa.Column("stale_layers", sa.JSON().with_variant(JSONB(), "postgresql")))


def downgrade() -> None:
    op.drop_column("version_components", "stale_layers")
    op.drop_column("analysis_jobs", "reason")
    op.drop_column("analysis_jobs", "started_by")
    op.drop_column("documents", "word_file_at")
