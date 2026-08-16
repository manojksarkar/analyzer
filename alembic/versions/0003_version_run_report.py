"""versions.run_report — the run manifest/report moves into the database (doc 09, C1 follow-up)

Revision ID: 0003_run_report
Revises: 0002_parse_snapshots
Create Date: 2026-08-16

C1 put the queryable accounting (decision / regenerated / reused / baseline) on the version
row, but the manifest also carries `warnings`, `carriedForward`, `crossVersionReused` and
`documents`, which no column covered. That left versions/<ver>/manifest.json genuinely
load-bearing rather than redundant — an operator on another node could not see why a run
warned.

Additive and nullable; existing rows read as NULL and fall back to the file exactly as before.
"""
from alembic import op
import sqlalchemy as sa

from api.db.postgres.schema import _JSONB

revision = "0003_run_report"
down_revision = "0002_parse_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("versions", sa.Column("run_report", _JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("versions", "run_report")
