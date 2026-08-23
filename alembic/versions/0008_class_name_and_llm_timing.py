"""job_functions.class_name, and timing on llm_call_stats

Two additive columns sets, both carrying poc-4 work into the database.

**class_name** — the parser now records the enclosing class or struct of a method, so the hide
list can render `ClassName::name` and two same-named methods are told apart. It reaches the
DOCX by itself (it lives inside the function record, which is stored whole as a content blob),
but `job_functions` mirrors the `Function` domain model field by field, and a field with no
column made every insert fail with "Unconsumed column names: class_name".

**latency / throttle / tokens on llm_call_stats** — that table counted calls and outcomes,
which says whether the spending bought anything. It could not say where the TIME went, and on
a gateway-throttled run the time is the whole story: a 3s pause per call is invisible in a
token count and dominates the wall clock. The engine now measures each attempt, so the numbers
exist; this gives them somewhere to land next to the counts they belong with.

Additive. Safe against a populated database — new columns are nullable with sane defaults.
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_class_name_and_llm_timing"
down_revision = "0007_llm_call_stats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job_functions", sa.Column("class_name", sa.String(), nullable=True))
    # Seconds, summed per (version, phase, kind, outcome) row alongside `n`. Split because
    # "slow because the gateway throttled us" and "slow because the model was slow" are
    # different problems with different fixes, and one number cannot tell them apart.
    op.add_column("llm_call_stats", sa.Column("latency_seconds", sa.Float(),
                                              nullable=False, server_default="0"))
    op.add_column("llm_call_stats", sa.Column("throttle_seconds", sa.Float(),
                                              nullable=False, server_default="0"))
    op.add_column("llm_call_stats", sa.Column("prompt_tokens", sa.Integer(),
                                              nullable=False, server_default="0"))
    op.add_column("llm_call_stats", sa.Column("completion_tokens", sa.Integer(),
                                              nullable=False, server_default="0"))


def downgrade() -> None:
    for col in ("completion_tokens", "prompt_tokens", "throttle_seconds", "latency_seconds"):
        op.drop_column("llm_call_stats", col)
    op.drop_column("job_functions", "class_name")
