# Job scheduling — the queue, the scheduler, the command line's checks

> **Project context — topic file.** Start at [PROJECT_CONTEXT.md](../PROJECT_CONTEXT.md), the index.
> Requirements [JOB_SCHEDULING_SPEC](../docs/spec/JOB_SCHEDULING_SPEC.md) (`REQ-JS-`) · design
> [JOB_SCHEDULING_DESIGN](../docs/design/JOB_SCHEDULING_DESIGN.md) · HTTP contract
> [JOB_SCHEDULING_API_SPEC](../docs/spec/JOB_SCHEDULING_API_SPEC.md) · CLI guide
> [Runs and the job queue](../docs/CLI_COMMANDS.md#runs-and-the-job-queue). History: 2026-10-19 →
> 2026-10-21b in [history 15](history/15-2026-10-07h.md).

**State (2026-10-21b, branch `feat/job-scheduling`):** built — the queue, the scheduler, the API, the
command line's checks and record, the commit and config checks at submit, the version delete guard.
Not built — pause in the engine (design §8: `engine/core/pause.py`, pause points, exit 75 through
`run.py`, every `EntityCache` flushed at exit, `staged.resume_plan` reading `paused`); the PostgreSQL
claim test (`tests/live/test_job_claims_pg.py`); `tests/e2e/test_pause_resume.py`;
`tests/unit/test_cancel_leaves.py`. The web screens are Manoj's (design §14) — nothing in `web-app/`.

## What it is

Each project has two **lanes**: `generation` (generate, export, resume) and `update` (Word-file updates,
`reexport`). One job runs at a time in each — `running`, or `paused`, which keeps its place. A lane's
limit (`projects.generation_limit` 3, `.update_limit` 10) counts its running, paused, waiting and held
jobs; the server runs at most `jobs.maxGenerations` (2) generations, every project's together, a paused
one not counted. The queue is `analysis_jobs` itself (migration 0019); `job_events` is its record.

Statuses: `held`, `queued`, `running`, `paused` (the lane's), `complete`, `failed`, `interrupted`,
`cancelled`, `removed` (ended). Written once in `engine/core/job_lanes.py`; the same tuples in
`api/models/domain.py`, checked equal by `tests/unit/test_job_lanes.py`.

## Where it lives

| File | What |
|---|---|
| `engine/core/job_lanes.py` | the lanes and statuses; `cli_refusal` (the CLI's rule); `lock_queue` (`pg_advisory_xact_lock(0x41524658, 2)`); `holding`, `running_generations` — the counts a claim and a CLI record share |
| `api/services/job_queue.py` | `enqueue` / `requeue` (a submit; `decide` is pure — no repository read inside the transaction); `answer_for` (position, estimate, `message`); `waiting_message`, `refresh_messages` (`current_activity` of waiting jobs); pause, resume, priority, limits; `hold_waiting`, `release_held`; `cancel`, `interrupt`, `cancel_paused_too_long`, `after_end` (record, notices, kick; idempotent per end); `Heartbeat`; `record_cli_run`, `end_cli_run`; `delete_refusal`; the views `queues`, `all_queues`, `preview`; `next_place` |
| `api/services/job_scheduler.py` | `Scheduler.round` — first round holds waiting jobs (restart), sweeps (first round, then each minute: re-follow, silent → interrupted, paused too long → cancelled; retention first sweep, then daily), claims, launches **inside the round's lock**; `try_start` (a round in the request); `install`, `start_up`, `kick` |
| `api/services/pipeline_runner.py` | `start_update` / `start_export` / `start_resume` → `enqueue`; `launch_job`; `_job_thread` (alive signal, `after_end`, kick, then leaves the thread lists); `fail_interrupted_jobs` (start-up: re-follow or interrupt running web jobs); `_follow_detached` → `conclude` (75 → paused, no exit code → interrupted at once); `commit_known`, `config_problem` (REQ-JS-07); `_complete` / `_complete_reexport` also finish an `interrupted` job |
| `api/db/postgres/database.py`, `api/db/in_memory.py` | `transition` (compare-and-set; a lane's second running job → False), `update` (never the state, nothing on a closed job), `add_to_lane`, `claim`, `record_run`, `lane_jobs`, `in_status`, `find_by_request_key`, `recent_ended`, `prune_ended`; `job_events`. The in-memory backend emulates `ux_jobs_lane_active` in `transition` and `record_run` |
| `api/routes/jobs.py`, `queues.py`, `version_components.py`, `commits_versions.py` | the routes of the API spec; `DELETE V` asks `delete_refusal` |
| `api/main.py` | start-up: `_fail_interrupted_jobs`, then `_start_scheduler` (the scheduler replaced `_watch_jobs`) |
| `analyzer.py` | `main()` → `_as_job` (the gate: `--job-id` attaches, else checks + record, `--ignore-queue`); `_run_as_job` (alive signal, the CLI job's end: exit 0/3 complete, else failed, Ctrl+C cancelled); `resume` runs a recorded `generate` with `main(argv, queue=False)` |
| `engine/core/config.py` | `jobs_settings()`; `jobs` is a `SERVER_BLOCKS` block — config.local.json only |
| `alembic/versions/0019_job_scheduling.py`, `tools/db_setup.py` | columns, `job_events`, indexes; `setup` step 8 calls `backfill` and `create_indexes` (`create_all` adds no index to an existing table) |

## Invariants — each broke, or would break, silently

1. **A status changes only by `db.jobs.transition()`** (`tests/unit/test_job_state_writers.py`). A
   whole-row write from an old copy undid a cancel (bug B1, fixed 2026-10-21).
2. **One running or paused job per lane**: `ux_jobs_lane_active` (`NOT forced`), the claim's check, the
   CLI record's check, the in-memory emulation. A test that makes a second running job in `p1` (seeded
   `job1` runs there for ever) fails on SQL — give it a project of its own, or free the lane
   (`tests/api/test_staged_generation_db.py` `_seeded_lanes_free`).
3. **A job's place and a record's time are strictly increasing** (`next_place`): Windows' clock moves in
   ~15 ms steps; a tie was ordered by the random id, and the third job of a lane took #1.
4. **Claim and launch in one locked step**, and a job thread leaves the thread lists **last**: else a
   submit's answer came back before its thread existed, and a test's join found nothing to wait for.
5. **An update joins a running update only when this server follows it** (`_reexport_alive`): a row a
   stopped server left would carry the request down with it.
6. **A CLI job is ended by its run; a web job by the API.** `--job-id` of an origin-`cli` job (a
   detached run's background half) ends it; of a web job, never.
7. **The commit is checked at submit** (`UNKNOWN_COMMIT`): known if in `commits`, else in the repository
   folder, else in a clone under `workspaces/<project>/`. API tests submitting a full SHA record it first
   (`tests/api/conftest.py` `record_commit`).

## Tests

`tests/api/test_job_queue.py` (both backends, a fresh database per test, a scheduler whose launch only
records), `test_queue_routes.py`, `test_job_state_writes.py`; `tests/unit/test_job_lanes.py`,
`test_cli_job_gate.py`, `test_job_state_writers.py`. The API suite's conftest gives every test a
scheduler without its thread (`_job_scheduler`; a submit starts its job at once when it may), removes
jobs an earlier test left waiting (a later round would start them — a real `git clone`), joins the job
threads a test started, and makes the threads take turns with the SQLite test database's one
connection (`_Turn`, on `checkout` / `reset`; `pool_reset_on_return=None`: StaticPool sends one
`checkin` for two connections out at once, and the pool's rollback could undo another thread's work).
