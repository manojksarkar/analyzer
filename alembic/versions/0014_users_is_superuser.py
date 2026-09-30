"""users.is_superuser — an operator account that may act on every project.

Access in this system is per project, through `project_members`, and that is still the model.
This is one deliberate exception for the operator account, not a second model: a `project_members`
row can be missed by any code path that forgets to write it — which is exactly how a CLI-onboarded
project became unreachable over HTTP — so the operator's access must not depend on one existing.

It is a column rather than a hard-coded email so that it is DATA: testable, greppable, visible in
the database, and changeable without a deploy.

`server_default` is not decoration. This column is added to databases that already have user rows,
and a NOT NULL column with no default cannot be added to a table that is not empty.

**Nobody is promoted here.** The column arrives `false` for every user and is set on purpose only,
with `python tools/grant_access.py --set-superuser --email <address>`. This migration used to
promote the seeded `admin@aspice.dev` / `admin` login -- a published password, re-created on
startup when deleted, under a JWT secret whose default makes a token for it forgeable -- which
turned the one login everybody knows into a key to every project. A database that ran that earlier
0014 keeps the flag until it is taken away: `--unset-superuser --email admin@aspice.dev`.

Revision ID: 0014_users_is_superuser
Revises: 0013_render_jobs
"""
from alembic import op
import sqlalchemy as sa

revision = "0014_users_is_superuser"
down_revision = "0013_render_jobs"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("users", sa.Column("is_superuser", sa.Boolean(), nullable=False,
                                     server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_column("users", "is_superuser")
