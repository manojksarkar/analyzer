"""Staged generation — per-component document states and the version's latest run.

A version's model (Phases 1-2) covers whole layers; its documents (Phases 3-4) are made per
component, by any number of runs: `generate`, `export` (components not generated yet),
`reexport` (again), `resume` (after a crash). `version_components` holds one row per component a
run asked for (waiting | generating | generated | failed); `version_runs` holds the version's latest
writing run -- its command line, process, log and progress. Whether that run is alive is the
version's writer lock, not a column.

Notes: staged-generation-2026-10-01.md (repo root, temporary).

Revision ID: 0016_staged_generation
Revises: 0015_review_approval
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0016_staged_generation"
down_revision = "0015_review_approval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "version_components",
        sa.Column("version_id", sa.String(), sa.ForeignKey("versions.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("component", sa.String(), primary_key=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
    )
    op.create_table(
        "version_runs",
        sa.Column("version_id", sa.String(), sa.ForeignKey("versions.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("command", sa.String()),
        sa.Column("argv", sa.JSON().with_variant(JSONB(), "postgresql")),
        sa.Column("pid", sa.Integer()),
        sa.Column("host", sa.String()),
        sa.Column("code_dir", sa.String()),
        sa.Column("log_path", sa.String()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("outcome", sa.String()),
        sa.Column("stage", sa.String()),
        sa.Column("done", sa.Integer()),
        sa.Column("total", sa.Integer()),
        sa.Column("stage_started_at", sa.DateTime(timezone=True)),
        sa.Column("progress_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("version_runs")
    op.drop_table("version_components")
