"""reuse_index.version_id gets a foreign key — dead pointers were blocking live reuse

Revision ID: 0006_reuse_index_fk
Revises: 0005_llm_desc_cache
Create Date: 2026-08-19

`reuse_index.version_id` had no foreign key, so deleting a version left its pointers behind
forever. That is worse than untidy, because the index is **first-writer-wins**: a pointer to a
deleted version still occupies `(project_id, fingerprint)`, so a LIVE version with identical
content can never claim it. `carry_forward_from_index` then resolves the fingerprint, finds
nothing at the dead version, and regenerates — permanently, for that content.

Found by `tools/check_db.py`, which reported six such pointers on a development database.

Orphans are deleted first, or adding the constraint would fail on any database that already has
them. Batch mode so SQLite — which cannot ALTER TABLE ADD CONSTRAINT — is rebuilt instead.
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_reuse_index_fk"
down_revision = "0005_llm_desc_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Delete pointers to versions that no longer exist. They can never resolve, and each one
    # blocks the fingerprint it holds.
    op.execute(
        "DELETE FROM reuse_index WHERE version_id IS NOT NULL AND version_id NOT IN "
        "(SELECT id FROM versions)")
    with op.batch_alter_table("reuse_index") as batch:
        batch.create_foreign_key("fk_reuse_index_version", "versions",
                                 ["version_id"], ["id"], ondelete="CASCADE")


def downgrade() -> None:
    with op.batch_alter_table("reuse_index") as batch:
        batch.drop_constraint("fk_reuse_index_version", type_="foreignkey")
