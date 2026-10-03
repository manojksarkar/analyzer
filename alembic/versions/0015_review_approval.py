"""Review and approval — a document's review state, its record, one reviewer.

`documents` gains its current review state (the reviewer's and the admin's latest comments, who
approved it and when, the approved Word file's hash and a copy of it, the content fingerprint an
unchanged next version carries the approval by, and the version it was carried from).
`document_review_events` is the record: one row per step. `notifications.document_id` lets a
notification open the document it is about. Then the rows are brought to the new rules -- statuses,
one reviewer per document, a record for documents approved before there was one
(`api/db/postgres/review_repair.py`, which `analyzer.py setup` runs too).

Contract: docs/spec/REVIEW_APPROVE_API_SPEC.md.

Revision ID: 0015_review_approval
Revises: 0014_users_is_superuser
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0015_review_approval"
down_revision = "0014_users_is_superuser"
branch_labels = None
depends_on = None

_DOC_COLUMNS = [
    sa.Column("review_comment", sa.Text()),
    sa.Column("changes_comment", sa.Text()),
    sa.Column("approved_by", sa.String()),
    sa.Column("approved_at", sa.DateTime(timezone=True)),
    sa.Column("approval_comment", sa.Text()),
    sa.Column("docx_sha256", sa.String()),
    sa.Column("approved_docx_path", sa.String()),
    sa.Column("content_fingerprint", sa.String()),
    sa.Column("carried_from", sa.String()),
]


def upgrade() -> None:
    for col in _DOC_COLUMNS:
        op.add_column("documents", col)
    op.add_column("notifications", sa.Column("document_id", sa.String()))
    op.create_table(
        "document_review_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("document_id", sa.String(), sa.ForeignKey("documents.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("version_id", sa.String(), sa.ForeignKey("versions.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String()),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column("payload", sa.JSON().with_variant(JSONB(), "postgresql")),
    )
    op.create_index("ix_review_events_document", "document_review_events", ["document_id"])
    op.create_index("ix_review_events_project_at", "document_review_events", ["project_id", "at"])

    from api.db.postgres.review_repair import repair_review
    repair_review(op.get_bind())


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_document_assignments_document")
    op.drop_index("ix_review_events_project_at", table_name="document_review_events")
    op.drop_index("ix_review_events_document", table_name="document_review_events")
    op.drop_table("document_review_events")
    op.drop_column("notifications", "document_id")
    for col in reversed(_DOC_COLUMNS):
        op.drop_column("documents", col.name)
