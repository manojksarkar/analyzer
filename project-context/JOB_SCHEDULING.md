# Job scheduling — the queue, the scheduler, the command line's checks, a run's pause

> **Project context — topic file.** Start at [PROJECT_CONTEXT.md](../PROJECT_CONTEXT.md), the index.
> Requirements [JOB_SCHEDULING_SPEC](../docs/spec/JOB_SCHEDULING_SPEC.md) (`REQ-JS-`) · design
> [JOB_SCHEDULING_DESIGN](../docs/design/JOB_SCHEDULING_DESIGN.md) · HTTP contract
> [JOB_SCHEDULING_API_SPEC](../docs/spec/JOB_SCHEDULING_API_SPEC.md) · CLI guide
> [Runs and the job queue](../docs/CLI_COMMANDS.md#runs-and-the-job-queue). History: 2026-10-19 →
> 2026-10-22 in [history 15](history/15-2026-10-07h.md), 2026-10-22b (the review) in
> [history 16](history/16-2026-10-22b.md). How to test it on a server:
> [JOB_SCHEDULING_TESTING.md](../docs/JOB_SCHEDULING_TESTING.md).

**State (2026-10-22b, branch `feat/job-scheduling`):** built and reviewed — the queue, the scheduler,
the API, the command line's checks and record, the commit and config checks at submit, the version
delete guard, and pause (exit 75 through the whole chain); checked on PostgreSQL 16 (claims at once, the
unique index, `setup` fresh and from 0018 rows). One review round (2026-10-22b): eight findings fixed,
and one found writing the test steps — invariants 1 and 11–14 below. The web screens are Manoj's
(design §14) — nothing in `web-app/`.

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
| `api/services/job_queue.py` | `enqueue` / `requeue` (a submit; `decide` is pure — no repository read inside the transaction; `requeue` takes a failed, interrupted, cancelled or removed job); `answer_for` (position, estimate, `message`); `waiting_message`, `refresh_messages` (`current_activity` of waiting jobs, by `transition` from the status read); estimates read each typical time once per call (`memo`); pause, resume, priority (from the status the job has), limits; `hold_waiting(before=)`, `release_held`; `cancel`, `interrupt`, `cancel_paused_too_long`, `after_end` (record, notices, kick; once per end and per run — `actor_id` for a cancel); `Heartbeat`; `record_cli_run`, `end_cli_run`; `delete_refusal`; the views `queues`, `all_queues`, `preview`; `next_place` |
| `api/services/job_scheduler.py` | `Scheduler.round` — first round holds the queues of the projects a job was left waiting in before the start-up (`hold_before`), sweeps (first round, then each minute: re-follow, silent → interrupted, paused too long → cancelled; retention first sweep, then daily), claims, launches **inside the round's lock** — and in a `finally`, so a round that raises launches what it claimed; `try_start` (a round in the request); `install`, `start_up(persists=)`, `kick` |
| `api/services/pipeline_runner.py` | `start_update` / `start_export` / `start_resume` → `enqueue`; `launch_job`; `_job_thread` (alive signal, `after_end`, kick, then leaves the thread lists); `fail_interrupted_jobs` (start-up: re-follow or interrupt running web jobs); `_follow_detached` → `conclude` (75 → paused, no exit code → interrupted at once); `commit_known`, `config_problem` (REQ-JS-07); `_complete` / `_complete_reexport` also finish an `interrupted` job |
| `api/db/postgres/database.py`, `api/db/in_memory.py` | `transition` (compare-and-set; a lane's second running job → False), `update` (never the state nor the queue's fields — `JOB_STATE_FIELDS`, `JOB_QUEUE_FIELDS` in `api/models/domain.py` — nothing on a closed job), `add_to_lane`, `claim`, `record_run`, `lane_jobs`, `in_status`, `find_by_request_key`, `recent_ended`, `prune_ended`; `job_events`. The in-memory backend emulates `ux_jobs_lane_active` in `transition` and `record_run` |
| `api/routes/jobs.py`, `queues.py`, `version_components.py`, `commits_versions.py` | the routes of the API spec; `DELETE V` asks `delete_refusal`; a submit whose draft meets its name taken since the check (a double click) answers the first job of its key, else `VERSION_EXISTS` |
| `api/main.py` | start-up: `_fail_interrupted_jobs`, then `_start_scheduler` (the scheduler replaced `_watch_jobs`); the in-memory backend starts it too, `persists=False` — no hold, no sweeps |
| `analyzer.py` | `main()` → `_as_job` (the gate: `--job-id` attaches, else checks + record, `--ignore-queue`); `_run_as_job` (alive signal, the CLI job's end: exit 0/3 complete, else failed, Ctrl+C cancelled); `resume` runs a recorded `generate` with `main(argv, queue=False)` |
| `engine/core/config.py` | `jobs_settings()`; `jobs` is a `SERVER_BLOCKS` block — config.local.json only |
| `engine/core/pause.py` | `requested()` (the run's `ANALYZER_JOB_ID`, read at most every 15 s), `check()` (a pause point: `PauseRequested`, a BaseException, main thread only), `exits_paused` (a step's entry exits 75), `EXIT_PAUSED` |
| pause points | `PhaseRunner` before each phase; `run.py` between plans; both parse passes per TU; `llm_core.parallel.map_in_order`; `llm_enrichment._run_in_rounds`; the behaviour names and diagrams loops; the flowchart label loops. The flowchart engine's exit 75 pauses the views phase (`views/flowcharts.py`) |
| exit 75 up the chain | `run.py` `_component_states` (components back to `waiting`), `incremental/generate.py` and `engine.py` (`AnalyzerRunFailed(75)`, no failed manifest), `analyzer.py` (says so, returns 75), `version_run` (outcome `paused`), the API (`conclude`, `_execute_subprocess` → `_record_paused`), `progress` (PAUSED) |
| `alembic/versions/0019_job_scheduling.py`, `tools/db_setup.py` | columns, `job_events`, indexes; `setup` step 8 calls `backfill` and `create_indexes` (`create_all` adds no index to an existing table) |

## Invariants — each broke, or would break, silently

1. **A status changes only by `db.jobs.transition()`, and so do the queue's own fields**
   (`tests/unit/test_job_state_writers.py`; `JOB_QUEUE_FIELDS`). A whole-row write from an old copy
   undid a cancel (bug B1, fixed 2026-10-21) — and erased a pause asked in between, or put back a
   claimed job's runner and alive signal (fixed 2026-10-22b). A waiting message is written by
   `transition` from the status read, so it never lands on a job that started.
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
8. **A phase cut short saves nothing**: a pause exits 75 from inside `main()`, before the `__main__`
   block lands the model (`flush_model`); a cancel kills the tree before it. Every database-backed
   `EntityCache` saves its buffer at exit (`_flush_at_exit`), so the LLM answers received are kept.
9. **A pause is not a failure**: no `failed` manifest (which would set `pipeline_status = failed`), no
   component `failed`; the version stays where it stopped and `resume` picks the step from it.
10. **The SQLite foreign-key hook touches SQLite connections alone** (`core.db`): it is global, and on a
   PostgreSQL connection its PRAGMA left the transaction aborted in any process that had made a SQLite
   engine first.
11. **An end is recorded and told once per run** (`after_end`: the ends since the job last began —
   `submitted`, `started`, `resumed`). A cancel goes through it, with who cancelled; before, it
   recorded its event first, so `after_end` found it and no cancel was ever told — and a job submitted
   again that failed again was neither recorded nor told.
12. **The restart's hold is per project and dates from the start-up** (`hold_before`): the first round
   can be a submit's own, and it held that submit — in a project nothing was left waiting in.
13. **A round launches what it claimed even when it raises** (the launch is in a `finally`): a job
   claimed is `running`; with no thread it was interrupted as silent ten minutes later, its turn lost.
14. **The web never reopens a command-line run's job** (`start_resume` reopens only an `origin = web`
   generation): a CLI job is ended by its own run (`_as_job`), so a reopened one was ended twice and
   could be neither paused nor cancelled from the web. A version made from the command line resumes as
   a job of its own — as before CLI runs had jobs.

## Tests

`tests/api/test_job_queue.py` (both backends, a fresh database per test, a scheduler whose launch only
records), `test_queue_routes.py`, `test_job_state_writes.py`; `tests/unit/test_job_lanes.py`,
`test_cli_job_gate.py`, `test_job_state_writers.py`, `test_pause.py`; `tests/e2e/test_pause_resume.py`
(a real run paused once Phase 2 began, resumed as the same job: the views of a run never paused; it
deletes its version, rows and folder, before and after — a database kept between sessions) and
`test_cancel_leaves.py` (a new version's run stopped in Phases 1–3, then cancelled: no row, no folder);
`tests/unit/test_job_claims_pg.py` on a scratch PostgreSQL (`ANALYZER_TEST_PG_DSN`, skipped without).
The review's (2026-10-22b), each failing on the code before it: in `test_job_queue.py` — only the projects
a restart left waiting are held; a resume removed before its turn can be asked again; a priority change
keeps a release made meanwhile; a progress line keeps a pause asked meanwhile; a waiting message never
lands on a job that started; a round that stops part way launches what it claimed; the in-memory backend
starts its scheduler and neither holds nor sweeps; a cancel is recorded with its person and told; a job
submitted again is told its end again; a lane's messages read each typical time once. In
`test_queue_routes.py` — a name taken since its check is `VERSION_EXISTS`, the same request twice at
once answers its first job. In `test_staged_generation_db.py` — a command-line run stopped is resumed by
a job of its own.

The API suite's conftest gives every test a scheduler without its thread (`_job_scheduler`; a submit
starts its job at once when it may), removes jobs an earlier test left waiting (a later round would
start them — a real `git clone`), joins the job threads a test started, and makes the threads take
turns with the SQLite test database's one connection (`_Turn`, on `checkout` / `reset`;
`pool_reset_on_return=None`: StaticPool sends one `checkin` for two connections out at once, and the
pool's rollback could undo another thread's work); its session's start-up hook starts no scheduler of
the app's own (`_startup_meets_no_database`). The root conftest puts `ANALYZER_JOB_ID` back after
every test (`_run_job_stays_in_its_test`): `analyzer.main()` called in-process sets it, as its own
process would, and the next tests' pause points and run records named a job of a database long gone.
