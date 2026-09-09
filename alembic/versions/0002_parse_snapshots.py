"""parse_snapshots — the post-Phase-1 skeleton moves into the database (doc 09, C2)

Revision ID: 0002_parse_snapshots
Revises: 0001_initial
Create Date: 2026-08-15

The blank skeleton a narrowed parse merges against lived at `versions/<ver>/parse/` on
local disk, so narrowed parse only worked on the machine that produced the baseline —
useless on a multi-node deployment, and lost whenever a workspace was cleaned.

Additive: the table is new, nothing existing changes, and the writers keep writing the
files until C11c. Safe to run against a populated database.
"""
from alembic import op
import sqlalchemy as sa

from api.db.postgres.schema import _JSONB

revision = "0002_parse_snapshots"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "parse_snapshots",
        sa.Column("version_id", sa.String(),
                  sa.ForeignKey("versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("payload", _JSONB, nullable=False),
        sa.UniqueConstraint("version_id", "name", name="pk_parse_snapshots"),
    )
    op.create_index("ix_parse_snapshots_version", "parse_snapshots", ["version_id"])


def downgrade() -> None:
    op.drop_index("ix_parse_snapshots_version", table_name="parse_snapshots")
    op.drop_table("parse_snapshots")
