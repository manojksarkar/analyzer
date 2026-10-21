"""A project's two job lanes -- the rule the API's queue and the command line share
(docs/design/JOB_SCHEDULING_DESIGN.md §2, §5, §11; docs/spec/JOB_SCHEDULING_SPEC.md REQ-JS-01..05,
REQ-JS-14, 15, 27..29).

Every project has a GENERATION lane (generate, export, resume) and an UPDATE lane (Word-file
updates, `reexport`). A lane runs one job at a time -- running, or paused, which keeps its place --
and the server runs at most `jobs.maxGenerations` generations at once, every project's together.

A web job waits its turn (api/services/job_queue.py, job_scheduler.py). A command-line run does not
wait: it starts now or is refused, naming the jobs in the way (`cli_refusal`), unless
`--ignore-queue`. The API's claim and the command line's record of its run count the same rows the
same way (`holding`, `running_generations`), one after the other under the queue's lock
(`lock_queue`).
"""
from __future__ import annotations

from typing import Any, Iterable, List, Optional, Tuple

GENERATION, UPDATE = "generation", "update"
LANES = (GENERATION, UPDATE)

WAITING = ("held", "queued")            # in its lane, not started
HOLDING = ("running", "paused")         # the lane's one place
IN_LANE = WAITING + HOLDING             # what a lane's limit counts
ENDED = ("complete", "failed", "interrupted", "cancelled", "removed")

#: The mode of a Word-file update (`api.models.domain.REEXPORT_MODE`); every other mode is a
#: generation lane's.
UPDATE_MODE = "reexport"

#: The `analyzer.py` commands that write a version, and their lanes.
COMMAND_LANES = {"generate": GENERATION, "export": GENERATION, "resume": GENERATION,
                 "reexport": UPDATE}

#: The queue's lock (`pg_advisory_xact_lock`): a claim and a command-line run's record take turns.
#: The first key is the job-runner lock's ("ARFX", api/services/pipeline_runner.py), whose second
#: key is 1.
QUEUE_LOCK = (0x41524658, 2)


def lane_of_mode(mode: Optional[str]) -> str:
    return UPDATE if mode == UPDATE_MODE else GENERATION


def lock_queue(cx: Any) -> None:
    """Take the queue's lock until the transaction of `cx` ends. PostgreSQL only: SQLite's writers
    take turns anyway."""
    if cx.dialect.name == "postgresql":
        from sqlalchemy import text
        cx.execute(text("SELECT pg_advisory_xact_lock(:a, :b)"),
                   {"a": QUEUE_LOCK[0], "b": QUEUE_LOCK[1]})


def _count(cx: Any, table: Any, cond: Any) -> int:
    from sqlalchemy import func, select
    return cx.execute(select(func.count()).select_from(table).where(cond)).scalar() or 0


def holding(cx: Any, table: Any, *, project_id: Optional[str] = None,
            lane: Optional[str] = None, version_id: Optional[str] = None,
            but: Optional[str] = None) -> int:
    """How many jobs run or are paused -- in a project's lane, on a version -- `but` one."""
    j = table
    cond = j.c.status.in_(HOLDING)
    if project_id is not None:
        cond = cond & (j.c.project_id == project_id)
    if lane is not None:
        cond = cond & (j.c.lane == lane)
    if version_id is not None:
        cond = cond & (j.c.version_id == version_id)
    if but is not None:
        cond = cond & (j.c.id != but)
    return _count(cx, j, cond)


def running_generations(cx: Any, table: Any, *, but: Optional[str] = None) -> int:
    """How many generations run on the server, every project's: what `jobs.maxGenerations` caps
    (a paused one is not counted, REQ-JS-05)."""
    j = table
    cond = (j.c.status == "running") & (j.c.lane == GENERATION)
    if but is not None:
        cond = cond & (j.c.id != but)
    return _count(cx, j, cond)


def cli_refusal(lane: str, lane_jobs: Iterable[Any], generations_running: int,
                cap: Optional[int]) -> Optional[Tuple[str, List[Any]]]:
    """Why a command-line run in `lane` may not start now (REQ-JS-28): `(reason, the jobs in the
    way)`, or None. `lane_jobs`: the project's jobs of that lane in IN_LANE, of any origin.

    - "busy": a job runs or is paused in the lane -- listed with any waiting behind it;
    - "waiting": jobs wait in the lane, and a run that went first would jump them;
    - "cap": a generation, and the server's generations are at `cap`.
    """
    mine = list(lane_jobs)
    holders = [j for j in mine if j.status in HOLDING]
    waiting = [j for j in mine if j.status in WAITING]
    if holders:
        return "busy", holders + waiting
    if waiting:
        return "waiting", waiting
    if lane == GENERATION and cap is not None and generations_running >= cap:
        return "cap", []
    return None
