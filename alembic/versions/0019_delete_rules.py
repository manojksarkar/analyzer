"""Delete rules for the five foreign keys that had none, so a project (or a version) can be deleted.

PostgreSQL checks a foreign key without a rule (NO ACTION) at the end of each cascaded delete, not
of the whole statement: deleting a project removed its documents before the comparisons that point
at them, and stopped on `document_diffs_document_id_fkey` (BACKLOG NW-4, found on PostgreSQL --
SQLite checks at the end of the statement and let it through). Now:

    document_diffs.document_id          -> documents  ON DELETE CASCADE   (a diff of a gone document)
    compare_results.current_version_id  -> versions   ON DELETE CASCADE   (a comparison of a gone version)
    compare_results.baseline_version_id -> versions   ON DELETE CASCADE
    versions.baseline_version_id        -> versions   ON DELETE SET NULL  (the newer version stays)
    analysis_jobs.version_id            -> versions   ON DELETE SET NULL  (the job's record stays)

PostgreSQL only: SQLite would need every table rebuilt, and checks at the end of the statement
anyway; a database `create_all` makes has the rules from `schema.py`. `analyzer.py setup` runs
`statements()` itself (it stamps the head without running migrations). Idempotent: whatever the
existing constraint is called, it is dropped and made again with its rule.

Revision ID: 0019_delete_rules
Revises: 0018_word_file_updates
"""
from alembic import op

revision = "0019_delete_rules"
down_revision = "0018_word_file_updates"
branch_labels = None
depends_on = None

#: (table, column, referenced table, ON DELETE rule)
RULES = [
    ("document_diffs", "document_id", "documents", "CASCADE"),
    ("compare_results", "current_version_id", "versions", "CASCADE"),
    ("compare_results", "baseline_version_id", "versions", "CASCADE"),
    ("versions", "baseline_version_id", "versions", "SET NULL"),
    ("analysis_jobs", "version_id", "versions", "SET NULL"),
]


def _drop_fk(table: str, column: str) -> str:
    """Drop every foreign key on `table.column`, whatever its name."""
    return (
        "DO $$ DECLARE r record; BEGIN "
        "FOR r IN SELECT c.conname FROM pg_constraint c "
        "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey) "
        f"WHERE c.contype = 'f' AND c.conrelid = '{table}'::regclass AND a.attname = '{column}' "
        f"LOOP EXECUTE format('ALTER TABLE {table} DROP CONSTRAINT %I', r.conname); END LOOP; "
        "END $$")


def statements(with_rules: bool = True):
    """The SQL, in order: each foreign key dropped and made again, with its rule or without."""
    out = []
    for table, column, ref, rule in RULES:
        out.append(_drop_fk(table, column))
        tail = f" ON DELETE {rule}" if with_rules else ""
        out.append(f"ALTER TABLE {table} ADD CONSTRAINT {table}_{column}_fkey "
                   f"FOREIGN KEY ({column}) REFERENCES {ref} (id){tail}")
    return out


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for sql in statements():
        op.execute(sql)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for sql in statements(with_rules=False):
        op.execute(sql)
