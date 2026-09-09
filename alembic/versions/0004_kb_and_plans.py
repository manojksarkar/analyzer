"""knowledge_base + incremental_plans — the last two engine->engine files move (doc 10, step 6)

Revision ID: 0004_kb_and_plans
Revises: 0003_run_report
Create Date: 2026-08-17

`model/knowledge_base.json` (Phase 2 -> Phase 3) and `model/incremental_plan.json` (the engine ->
Phases 2 and 3) were hand-offs on local disk. That works while every phase runs on one machine
and breaks the moment one does not: a cross-machine `--from-phase 3` loses the knowledge base and
the flowchart engine quietly degrades.

Storing the plan is also what lets the flowchart engine restrict itself by version id — the
changed-function list cannot fit on a command line.

Additive and nullable-free by construction (both tables are new). Safe against a populated
database.
"""
from alembic import op
import sqlalchemy as sa

from api.db.postgres.schema import _JSONB

revision = "0004_kb_and_plans"
down_revision = "0003_run_report"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("knowledge_base", "incremental_plans"):
        op.create_table(
            name,
            sa.Column("version_id", sa.String(),
                      sa.ForeignKey("versions.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("payload", _JSONB, nullable=False),
        )


def downgrade() -> None:
    op.drop_table("incremental_plans")
    op.drop_table("knowledge_base")
