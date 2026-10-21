"""Job scheduling — the queue in the database (docs/design/JOB_SCHEDULING_DESIGN.md §2).

`analysis_jobs`: its lane (`generation` | `update`), priority (0 High, 1 Normal, 2 Low), when it
was submitted (its place), its alive signal, pause and resume requests, time spent paused, where it
came from and who runs it (`web` | `cli`, the host and process), a CLI run started past the queue
(`forced`), and the submit's idempotency key. One running or paused job per project and lane,
unless forced: `ux_jobs_lane_active`. `projects`: the two limits. `job_events`: the record.

`analyzer.py setup` repeats this on a database it made (tools/db_setup.py, step 8): `create_all`
makes `job_events`, `_add_missing_columns` the columns -- each has a server default -- and
`backfill` and `create_indexes`, here, the rest. Both are idempotent.

`pause_after_phase1` stays, unused: the web app still sends it, and nothing reads it.

Revision ID: 0019_job_scheduling
Revises: 0018_word_file_updates
"""
import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB

revision = "0019_job_scheduling"
down_revision = "0018_word_file_updates"
branch_labels = None
depends_on = None

#: The jobs a project lane holds at once: the running one, or the paused one -- unless a CLI run
#: was started past the queue (`--ignore-queue`), which the scheduler waits for as well.
LANE_ACTIVE_WHERE = "status IN ('running', 'paused') AND NOT forced"

#: What an older running job of a lane says once the index allows one: found at the upgrade.
INTERRUPTED_AT_UPGRADE = (
    "Interrupted: another job of its project and lane was running when the database was "
    "upgraded for job scheduling (0019), and a lane runs one job at a time.\n"
    "- Start it again: it joins the back of its lane.")


def backfill(cx) -> dict:
    """Rows written before 0019: an update's lane, each job's place (`submitted_at`), and -- for
    the lane's unique index -- one running or paused job per project lane, the newest; the older
    ones are interrupted (a server that stopped left them, or two updates of two versions ran at
    once, which a lane no longer allows). Idempotent. Returns what it changed."""
    lanes = cx.execute(text(
        "UPDATE analysis_jobs SET lane = 'update' WHERE mode = 'reexport' AND lane <> 'update'"
    )).rowcount
    placed = cx.execute(text(
        "UPDATE analysis_jobs SET submitted_at = started_at "
        " WHERE submitted_at IS NULL AND started_at IS NOT NULL")).rowcount
    rows = cx.execute(text(
        "SELECT id, project_id, lane, started_at FROM analysis_jobs WHERE " + LANE_ACTIVE_WHERE
    )).fetchall()
    newest = {}
    for r in rows:
        key = (r.project_id, r.lane)
        mark = (r.started_at is not None, str(r.started_at or ""), r.id)
        if key not in newest or mark > newest[key][0]:
            newest[key] = (mark, r.id)
    keep = {rid for _, rid in newest.values()}
    older = [r.id for r in rows if r.id not in keep]
    now = datetime.datetime.now(datetime.timezone.utc)
    for rid in older:
        cx.execute(text("UPDATE analysis_jobs SET status = 'interrupted', completed_at = :now, "
                        "error_message = :msg WHERE id = :id"),
                   {"now": now, "msg": INTERRUPTED_AT_UPGRADE, "id": rid})
    return {"lanes": lanes, "placed": placed, "interrupted": len(older)}


def create_indexes(cx) -> None:
    """The indexes `create_all` makes on a new table and nothing adds to one that exists."""
    cx.execute(text("CREATE INDEX IF NOT EXISTS ix_jobs_waiting "
                    "ON analysis_jobs (status, lane, submitted_at)"))
    cx.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_jobs_lane_active "
                    "ON analysis_jobs (project_id, lane) WHERE " + LANE_ACTIVE_WHERE))
    cx.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_jobs_request "
                    "ON analysis_jobs (project_id, request_key) WHERE request_key IS NOT NULL"))


def upgrade() -> None:
    add = op.add_column
    add("analysis_jobs", sa.Column("lane", sa.String(), nullable=False,
                                   server_default="generation"))
    add("analysis_jobs", sa.Column("priority", sa.SmallInteger(), nullable=False,
                                   server_default=text("1")))
    for name in ("submitted_at", "heartbeat_at", "pause_requested_at", "paused_at",
                 "resume_requested_at"):
        add("analysis_jobs", sa.Column(name, sa.DateTime(timezone=True)))
    add("analysis_jobs", sa.Column("paused_seconds", sa.Integer(), nullable=False,
                                   server_default=text("0")))
    add("analysis_jobs", sa.Column("origin", sa.String(), nullable=False, server_default="web"))
    add("analysis_jobs", sa.Column("runner", sa.String()))
    add("analysis_jobs", sa.Column("forced", sa.Boolean(), nullable=False,
                                   server_default=sa.false()))
    add("analysis_jobs", sa.Column("request_key", sa.String()))
    add("projects", sa.Column("generation_limit", sa.Integer(), nullable=False,
                              server_default=text("3")))
    add("projects", sa.Column("update_limit", sa.Integer(), nullable=False,
                              server_default=text("10")))
    op.create_table(
        "job_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("job_id", sa.String()),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String()),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detail", sa.JSON().with_variant(JSONB(), "postgresql")),
    )
    op.create_index("ix_job_events_project_at", "job_events", ["project_id", "at"])
    op.create_index("ix_job_events_job", "job_events", ["job_id"])
    bind = op.get_bind()
    backfill(bind)
    create_indexes(bind)


def downgrade() -> None:
    for name in ("ux_jobs_request", "ux_jobs_lane_active", "ix_jobs_waiting"):
        op.drop_index(name, table_name="analysis_jobs")
    op.drop_index("ix_job_events_job", table_name="job_events")
    op.drop_index("ix_job_events_project_at", table_name="job_events")
    op.drop_table("job_events")
    for name in ("update_limit", "generation_limit"):
        op.drop_column("projects", name)
    for name in ("request_key", "forced", "runner", "origin", "paused_seconds",
                 "resume_requested_at", "paused_at", "pause_requested_at", "heartbeat_at",
                 "submitted_at", "priority", "lane"):
        op.drop_column("analysis_jobs", name)
