"""llm_call_stats — how many LLM calls a run made, and how many produced nothing

Revision ID: 0007_llm_call_stats
Revises: 0006_reuse_index_fk
Create Date: 2026-08-19

Token counts say what was SPENT. They do not say whether the spending bought anything, and that
gap hid a real failure: a run took 2062 seconds and produced mechanical flowchart labels while
the gateway answered every request correctly — the replies were being destroyed after arrival.
Token usage looked healthy throughout. "1 call in 3 came back empty" is the number that would
have pointed straight at it, and nothing was recording it.

One row per (version, phase, kind, outcome). Phases are separate subprocesses, so each flushes
its own tally and the orchestrator sums them for the end-of-run report. Deliberately not
deduplicated: `phase` keeps the breakdown, which is what says WHERE the failures are.

Additive. Safe against a populated database.
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_llm_call_stats"
down_revision = "0006_reuse_index_fk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_call_stats",
        sa.Column("version_id", sa.String(),
                  sa.ForeignKey("versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("phase", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False),
    )
    op.create_index("ix_llm_call_stats_version", "llm_call_stats", ["version_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_call_stats_version", table_name="llm_call_stats")
    op.drop_table("llm_call_stats")
