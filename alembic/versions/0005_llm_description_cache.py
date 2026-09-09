"""llm_description_cache — the LLM cache leaves local disk (doc 10 step 10, doc 04 §13)

Revision ID: 0005_llm_desc_cache
Revises: 0004_kb_and_plans
Create Date: 2026-08-18

`.flowchart_cache/llm_descriptions/**.json` and `aux_descriptions/**.json` were one JSON file per
entity on the machine that ran the job. On the container deployment that cache dies with the
container and is invisible to every other node, so N nodes share roughly a 1/N hit rate.

That matters more than a cache miss usually does: the gateway admits about one call every three
seconds, and the FULL generation path has no other protection — the reuse index carries
descriptions forward on the incremental path only.

Additive: a new table, no change to existing ones. Safe against a populated database.
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_llm_desc_cache"
down_revision = "0004_kb_and_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_description_cache",
        sa.Column("project_id", sa.String(),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("namespace", sa.String(), nullable=False),
        sa.Column("cache_version", sa.Integer(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "namespace", "cache_version", "entity_id",
                            "content_hash", name="pk_llm_description_cache"),
    )
    # The read is one query per (project, namespace, cache_version) — see DbEntityCache.
    op.create_index("ix_llm_description_cache_scope", "llm_description_cache",
                    ["project_id", "namespace", "cache_version"])


def downgrade() -> None:
    op.drop_index("ix_llm_description_cache_scope", table_name="llm_description_cache")
    op.drop_table("llm_description_cache")
