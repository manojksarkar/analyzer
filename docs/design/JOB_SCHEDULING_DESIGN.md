# Job scheduling — design

How [JOB_SCHEDULING_SPEC](../spec/JOB_SCHEDULING_SPEC.md) is built; the HTTP contract is
[JOB_SCHEDULING_API_SPEC](../spec/JOB_SCHEDULING_API_SPEC.md). Status 2026-10-22: agreed with the user
([§20](#20-decisions-beyond-the-spec) confirmed) and built on `feat/job-scheduling` — the queue, the
scheduler, the API, the command line and pause; the web screens are Manoj's ([§14](#14-web-app)). One
server now; [§18](#18-two-servers-later) says what is left for two. Testing it on a server:
[JOB_SCHEDULING_TESTING](../JOB_SCHEDULING_TESTING.md).

**Outline:** [1 Principles](#1-principles) · [2 Data](#2-data--migration-0019) ·
[3 States](#3-a-jobs-states) · [4 Submitting](#4-submitting) · [5 Scheduler](#5-the-scheduler) ·
[6 Running](#6-running-a-job) · [7 Alive signal](#7-alive-signal-and-interrupted) ·
[8 Pause and resume](#8-pause-and-resume) · [9 Cancel and remove](#9-cancel-and-remove) ·
[10 Restart](#10-restart-and-held-jobs) · [11 CLI](#11-the-cli) · [12 Config](#12-config) ·
[13 API](#13-api) · [14 Web app](#14-web-app) · [15 Notices, record, measures](#15-notices-record-measures) ·
[16 Cases](#16-cases) · [17 Files](#17-files-that-change) · [18 Two servers](#18-two-servers-later) ·
[19 Tests](#19-tests) · [20 Decisions](#20-decisions-beyond-the-spec) · [21 Risks](#21-risks)

```
 web app ─► API submit ─────────────┐                         ┌─ heartbeat_at, every 60 s ──┐
                                    ▼                         │                             │
 analyzer.py (CLI) ─ check+record ─► analysis_jobs  (PostgreSQL primary: the queue)          │
                                    ▲          │                                            │
         scheduler thread ── claim ─┘          └─► job thread ─► analyzer.py … --job-id J ─► run processes
         (the job-runner server)                   (follows it)   (--detach: outlives the API)
         wakes every 10 s, and at once on: a submit, a job's end, a release, a resume
```

## 1. Principles

- **The database is the queue.** Every job, its state and its order are rows in `analysis_jobs`; no
  count lives in a process's memory. A restart loses nothing (REQ-JS-14).
- **One atomic claim starts a job.** A transaction under one database lock re-checks the lane, the cap
  and the version, then moves the job to `running`; a partial unique index refuses a second running job
  in a lane even if the code is wrong (REQ-JS-15).
- **A state changes only by compare-and-set; progress never touches it.** A status change is
  `UPDATE … SET status = :to WHERE id = :j AND status IN (:from)`, through `db.jobs.transition()`,
  which says whether it applied — and answers "not changed" when the change would put a second job in
  a lane (the unique index). `db.jobs.update()` writes a job's progress, never its state
  (`JOB_STATE_FIELDS`) nor the queue's own fields (`JOB_QUEUE_FIELDS`: the lane, the place and the
  priority, a pause or a resume asked, the alive signal, who runs it), and nothing to a job that has
  closed. Before, the job's thread rewrote the whole row for almost every log line
  (`_update_activity`), from a copy read a moment before, so a cancel made in between was undone — and
  a pause asked in between was erased. A waiting job's message is written the same way, only while it
  still waits as it was read. `tests/unit/test_job_state_writers.py` fails when code outside
  the job repository sets a job's status, as `test_output_row_writers.py` guards its table.
- **The run speaks for itself.** It sends its alive signal, notices a pause request, and says how it
  ended by its exit code — so it does not depend on the API being up (REQ-JS-19).
- **Reuse what is there.** The version writer lock (`core/version_run.py`), background runs
  (`--detach`, `core/frozen_run.py`), and `analyzer.py resume`, which already carries on a version
  from wherever it stopped (staged generation, 2026-10-02c). A pause is a stop at a safe point,
  followed by that resume.

## 2. Data — migration 0019

`alembic/versions/0019_job_scheduling.py`; a database upgrades with `analyzer.py setup`. Twin docs:
`docs/design/DB_SCHEMA.md` and `schema-atlas.html`.

**`analysis_jobs` — new columns**

| Column | Type | Meaning |
|---|---|---|
| `lane` | text, not null | `generation` \| `update`. Backfill: `mode = 'reexport'` → `update`, else `generation` |
| `priority` | smallint, not null, default 1 | 0 High, 1 Normal, 2 Low; generation lane only. Wire: `high`/`normal`/`low` |
| `submitted_at` | timestamptz | when it joined its lane; the order. Backfill: `started_at` |
| `heartbeat_at` | timestamptz | the alive signal ([§7](#7-alive-signal-and-interrupted)) |
| `pause_requested_at`, `paused_at`, `resume_requested_at` | timestamptz | [§8](#8-pause-and-resume) |
| `paused_seconds` | integer, default 0 | time spent paused, left out of elapsed time and estimates |
| `origin` | text, default `web` | `web` \| `cli` |
| `runner` | text | who runs it: `api <host> pid N`, `cli <user>@<host> pid N` |
| `forced` | boolean, default false | a CLI run started with `--ignore-queue` |
| `request_key` | text | the submit's idempotency key (REQ-JS-09) |

- `started_at` now means when it **started running** (NULL while waiting). Readers that mean "newest"
  (`get_current`, `list_for_version`) order by `submitted_at`, else `started_at`.
- Statuses: `held`, `queued` (waiting), `running`, `paused`, `complete`, `failed`, `interrupted`,
  `cancelled`, `removed`. The first four are the lane's — written once, in `engine/core/job_lanes.py`,
  and the same tuples in `api/models/domain.py` (`tests/unit/test_job_lanes.py` checks they agree).
- `pause_after_phase1` stays, unused: the request field is ignored (the spec's
  [What changes](../spec/JOB_SCHEDULING_SPEC.md#what-changes-from-today)).
- Indexes: `ux_jobs_lane_active` UNIQUE (`project_id`, `lane`) WHERE `status IN ('running','paused')
  AND NOT forced`; `ix_jobs_waiting` (`status`, `lane`, `submitted_at`); `ux_jobs_request` UNIQUE
  (`project_id`, `request_key`) WHERE `request_key IS NOT NULL`.
- The migration's `backfill` sets `lane` and `submitted_at` on existing rows and, before the unique
  index is made, interrupts all but the newest of any lane's two running jobs; `analyzer.py setup`
  calls it and `create_indexes` too, as `create_all` adds no index to an existing table.

**`projects` — new columns:** `generation_limit` integer not null default 3, `update_limit` integer not
null default 10 (REQ-JS-04).

**`job_events` — new table** (REQ-JS-33, the measures of REQ-JS-34): `id` text (`jev…`), `job_id` (NULL
for a limit change or a held-queue action), `project_id` → projects ON DELETE CASCADE, `kind`,
`actor_id` (NULL: the system), `at`, `detail` JSONB. Kinds: `submitted`, `started`, `pause_requested`,
`paused`, `resume_requested`, `resumed`, `cancelled`, `removed`, `interrupted`, `failed`, `completed`,
`priority_changed`, `limits_changed`, `held`, `released` — a cancel after `jobs.pausedDays` is a
`cancelled`, its message says why. Indexes (`project_id`, `at`), (`job_id`).

`version_runs.outcome` gains `paused`.

## 3. A job's states

```
 submit ───────────► queued ───── restart ─────► held ◄── submit while the project is held
                       │   ◄──── start held ──────┘
                 claim │
 CLI records itself ──►▼
                     running ──► complete | failed | cancelled | interrupted
                      │   ▲
                pause │   │ resume, then claim
                      ▼   │
                     paused ──► cancelled   (cancel, or paused for jobs.pausedDays)

 queued, held ── remove, clear ──► removed
```

| From → to | When | By |
|---|---|---|
| — → `queued` / `held` | submitted; `held` when the project has held jobs | the submitter |
| — → `running` | a CLI run records itself | `analyzer.py` |
| `queued` → `held` | the server starts and `jobs.startQueuedAfterRestart` is false | the scheduler |
| `held` → `queued` | start all, or start the rest | a super admin |
| `queued`, `held` → `removed` | remove, or clear | submitter (own), project admin, super admin |
| `queued` → `running` | claim | the scheduler |
| `running` → `paused` | the run exits 75 after a pause request | the job's thread |
| `paused` → `running` | claim of a resume request | the scheduler |
| `running`, `paused` → `cancelled` | cancel; `paused` for `jobs.pausedDays` | as remove; the scheduler |
| `running` → `complete` \| `failed` | the run ends | the job's thread; a CLI run itself |
| `running` → `interrupted` | silent too long, or its process gone ([§7](#7-alive-signal-and-interrupted)) | the scheduler; the job's thread |

"Pausing…" and "Resuming — waits for a server slot" are `running` + `pause_requested_at` and `paused`
+ `resume_requested_at`, not states of their own. Every change goes through `db.jobs.transition()`
and writes a `job_events` row. A run that ends after all, its job taken for dead while it was silent,
moves it from `interrupted` to how it really ended (`_complete`, `_complete_reexport`,
`job_queue.end_cli_run`).

## 4. Submitting

`api/services/job_queue.py` `enqueue()` — one path for the four starts: `POST …/jobs` (generation),
`…/versions/{v}/documents/generate` (export), `…/versions/{v}/resume`, `…/versions/{v}/reexport`
(update). `pipeline_runner.start_export()`, `start_resume()` and `start_update()` make their job and
hand it to `enqueue()`; a reopened web generation goes back through `requeue()` — one that failed,
was interrupted or cancelled, or was resumed and then removed before its turn. A command-line run's job
is never reopened (its run ends it, [§11](#11-the-cli)): a version made from the command line resumes as
a job of its own. The HTTP contract:
[JOB_SCHEDULING_API_SPEC](../spec/JOB_SCHEDULING_API_SPEC.md).

1. **Checks that do not need the lock** — today's (architecture, version name, scope, baseline,
   `NO_DOCUMENTS`, `VERSION_NOT_READY`, `INVALID_COMPONENTS`, `NOTHING_TO_RESUME`) plus, so a waiting
   job does not fail hours later on a typo (REQ-JS-07): the commit is one the project knows — its
   `commits` row, else the repository when it is a folder here, else a clone a run made under
   `workspaces/<project>/` (`pipeline_runner.commit_known`, 422 `UNKNOWN_COMMIT`); the project's config
   builds — `_write_project_config` into a scratch folder (`config_problem`, 409 `CONFIG_INVALID`).
   An error is answered as today (400/404/409/422).
2. **Idempotency** — an `Idempotency-Key` header the web app sends with every submit; a job with that
   key in the project is answered again, nothing new (REQ-JS-09).
3. **Under the project's lock** (`SELECT … FROM projects WHERE id = :p FOR UPDATE`):
   - update lane: a running update of the version that covers the components → that job, `joined`
     (WORD_FILE_UPDATES D6, today); a waiting or held one that covers them → that job, `already_queued`;
   - generation lane: a waiting or held generation with the same commit, mode, scope, baseline, LLM
     switch, data dictionary and narrowed-parse switch → 409 `DUPLICATE_JOB` naming it;
   - the lane's jobs (running, paused, waiting, held) ≥ its limit → 409 `LANE_FULL` naming them;
   - a new version (`generate`) reserves its name: the draft row, as today, whose unique constraint is
     the name check (REQ-JS-08);
   - insert the job, `held` if the project has held jobs, else `queued`; priority other than Normal
     only from a super admin; `started_by` always.
4. **Start at once if it can** — on the server that runs jobs, a scheduler round in the request
   (`try_start`, [§5](#5-the-scheduler)). The answer is exact:
   `202 {job, status: running | queued | held, position, ahead, estimated_start, message}`.

A job's place is its `submitted_at`, which `next_place()` gives strictly after the last one this process
gave: Windows' clock moves in steps of about 15 ms, and two submits in a row had the same time — a tie
the job id, which is random, then ordered.

**Position and estimate.** Position counts the waiting jobs ahead of it, plus one ("waits as #2").
Estimated start = the running job's remaining time (its `eta_seconds`, else the median run time of the
project's last five ended jobs of that kind, less what it has run) + the median run time of each job
ahead. A paused job ahead, or a full server cap, makes it "after J1 resumes" / "and a free server slot",
without a time. Paused time is never counted.

## 5. The scheduler

`api/services/job_scheduler.py`: one daemon thread, only in the server that holds the job-runner lock
(`claim_job_runner`, today). It never dies: a round that fails is logged and the next runs. If the lock is
lost (a database restart drops it in silence) it is claimed again on the next round — today's sweep
drops a lost claim, but nothing would schedule then.

**A round** — every 10 s, and at once when kicked (a submit, a job's end, a release, a resume):

1. **Sweeps**, in the first round and then at most once a minute: background runs nobody follows,
   followed again; interrupted jobs ([§7](#7-alive-signal-and-interrupted)); paused past
   `jobs.pausedDays` → cancelled ([§9](#9-cancel-and-remove)); in the first sweep and then once a day —
   or every `jobs.keepFinishedDays` when that is shorter — retention ([§15](#15-notices-record-measures)).
2. **Claims**, each in its own short transaction under the queue lock (`core.job_lanes.lock_queue`:
   `pg_advisory_xact_lock(0x41524658, 2)`, beside the runner lock's key 1):
   1. **resume requests** first — paused jobs with `resume_requested_at`, oldest request first — while
      the cap has room. A paused job holds its project's slot, so nothing in its project can be ahead of it;
   2. **generations** — each project whose generation lane has no running or paused job and no held job
      offers its head: highest priority, then oldest `submitted_at` (REQ-JS-11). Of those heads, the one
      that has waited longest starts, while running generations < `jobs.maxGenerations` (REQ-JS-13).
      A head whose version is busy waits; the lane is not skipped (what can hold it is an update, minutes);
   3. **updates** — each project whose update lane is free starts its oldest waiting update whose
      version is free (REQ-JS-12). An update whose version is busy is passed, and keeps its place:
      what holds it is an export or a paused job, which can take a day.
3. **Launch** each job claimed ([§6](#6-running-a-job)) — inside the round, before another round may
   begin: a round that came meanwhile (a submit's own) finds the job's thread there, not a job claimed
   and not yet started. A round that stops part way (the database gone a moment) still launches what
   it claimed before: a job claimed is running, and with no thread it would be interrupted as silent.

**The claim** re-reads, under the lock: the lane is free, the cap has room (generation; a paused job
does not count, a CLI run does, `forced` or not), and the version is free — no other job running or
paused on it, and (PostgreSQL) nobody holds its writer lock (`version_run.holder`: a CLI run of older
code that recorded no job). The counts are `core.job_lanes.holding` and `running_generations`, which
the command line's record of its run uses too. Then `UPDATE … SET status = 'running', started_at
(kept on a resume), heartbeat_at = now(), runner WHERE id = :j AND status = 'queued'` (or `paused` for
a resume). SQLite has no advisory lock: there the unique index guards the lane and the cap is checked
without a lock across processes (local use).

## 6. Running a job

`pipeline_runner.launch_job(db, job, resumed)` starts the job's thread — today's bodies, picked by kind:

| Job | Lane | Thread (pipeline_runner) | Command |
|---|---|---|---|
| generation (`auto`, `full`) | generation | `_run` | `analyzer.py generate` |
| export | generation | `_run_export` | `analyzer.py export` |
| resume, and a paused job resumed | generation | `_run_resume` | `analyzer.py resume` |
| Word-file update | update | `_run_reexport` | `analyzer.py reexport` |

Each command gets `--job-id J`, last, and `--detach` when the API has a database (`_detach_enabled`,
today).

What changes in them: no `status = "running"` at their start (the claim did it); no semaphore
(`_inner_run`, `_refollow`); the commit is checked again at the start by the checkout itself — one gone
since the submit fails the job, and the next starts (REQ-JS-07); each end goes through `transition()`.
The thread wrapper (`_job_thread`) sends the job's alive signal while it works, and at its end books it
(`job_queue.after_end`: the event, the notices of [§15](#15-notices-record-measures), the waiting jobs'
messages) and kicks the scheduler — then, last, leaves the lists of job threads, so whoever waits on
the thread finds all of that done. `JOB_ALREADY_RUNNING`, `REEXPORT_RUNNING`, `EXPORT_RUNNING`,
`RUN_ACTIVE` and `VERSION_BUSY` are no longer answers to a submit: those jobs wait. An update joins a
running update that covers it only when this server is at work on it: a row a stopped server left
running is interrupted by the sweep, and a request that joined it would end with it.

A version reopened for resume — a web generation that failed or was interrupted — is submitted again:
back of the lane, Normal priority, a new `submitted_at` (REQ-JS-20), as `start_resume` reopens it today.

## 7. Alive signal and interrupted

**Who beats** (`heartbeat_at = now()`, every 60 s, `job_queue.Heartbeat`; the claim, or the command
line's record, writes the first): the job's thread in the API while it works on the job — checkout,
config, launch, a child run, following a background one — and the run's own `analyzer.py` process, for
its whole life (`analyzer._run_as_job`): a web run's (`--job-id J`) and a command-line run's. So a run
in the background is not called silent while the API restarts.

**Interrupted** (REQ-JS-20), by the scheduler, when all hold:

- `running`, and no thread of this server follows it;
- `heartbeat_at` older than `jobs.interruptedAfterMinutes` (10);
- the version's writer lock is free (PostgreSQL; not asked on SQLite);
- the scheduler has reached the database without a break for the last 2 minutes — an outage stops
  every beat, so runs get 2 minutes after it ends to beat again (REQ-JS-17).

Sooner when it is certain: a follower that sees the background run's process gone with no exit code
and the lock free (today's `STOPPED_MESSAGE` case) interrupts the job at once.

Then: the slot is freed and the scheduler kicked; the version is kept when it holds work to resume, and
deleted otherwise so its name is free (`_fail_keeping_work`, today); the submitter and the project's
admins are told. A process that is alive but makes no progress is not interrupted — it is flagged stuck
([§15](#15-notices-record-measures)).

## 8. Pause and resume

**Request** — `POST …/jobs/{j}/pause`: a running web generation → `pause_requested_at` (a second click
changes nothing). An update, a waiting job (remove it instead) or a CLI run is refused.

**The run notices** — `engine/core/pause.py`:

- `requested()` — the run's job's `pause_requested_at` while it runs, read at most every 15 s per
  process (`ASK_EVERY`), and once asked, asked for the rest of the process; False without a job id or a
  database, and when the database cannot answer. The job id is `ANALYZER_JOB_ID`, which every process
  of the run inherits: `analyzer.py` sets it from `--job-id` or its own record ([§11](#11-the-cli)), as
  the API already set it for a run's metrics.
- `check(where)` — a **pause point**, on the main thread only (a `SystemExit` raised in a worker thread
  does not stop the process): when requested, raise `PauseRequested`, a `BaseException`, so the
  pipeline's `except Exception` blocks let it through.
- `exits_paused` — on each step script's entry (`parser.py`, `model_deriver.py`, `run_views.py`,
  `docx_exporter.py`, `swe4_exporter.py`, the flowchart engine): catches `PauseRequested` and exits
  **75** (`EXIT_PAUSED`) — before the phase lands its model, so a phase cut short saves nothing of its
  own. The LLM pool cancels the calls not started (`llm_core.parallel.executor`, as today); the
  process's exit waits for the calls already in flight, then runs its exit hooks — checked on Python
  3.12: 3 calls in flight and 7 queued, the 7 cancelled, the 3 finished, all 3 answers saved.
- **Every cache saves its buffer when the process exits** — an `EntityCache` backed by the database
  registers its `flush` with `atexit` (`_flush_at_exit`, by weak reference); one change for the three
  caches (descriptions, aux descriptions — whose own hook went — flowchart labels). A pause or a Ctrl+C
  then keeps every answer received; a crash or a kill loses what came since the last save (writes are
  buffered up to 60 s or 1,000 rows), which resume asks again. No write per answer: resume redoes work
  anyway (below).

**Pause points**: between phases (`PhaseRunner`); between components (`run.py`'s plan loop); per
translation unit in both passes of the parse; before each item or round in `map_in_order` (the unit and
struct descriptions, the global descriptions), `_run_in_rounds` (the function descriptions), the
behaviour-names loop, the behaviour diagrams' loop, and the flowchart label loop — sequential or
parallel, checked on the main thread before each result. The flowchart engine is a child of the views
phase: its exit 75 pauses that phase too (`views/flowcharts.py`). The incremental engine's steps are
`run.py` runs, so they pause at those points. A missed one only makes the pause wait for the next.

**Exit 75 travels up** — each place that reads a run's exit code learns it:

| Where | Today | With 75 |
|---|---|---|
| step script | — | flushes, exits 75 |
| `PhaseRunner.run` | `SystemExit(rc)` | unchanged |
| `run.py` `_component_states` | non-zero → components `failed`, the run goes on with the others | the components back to `waiting`; re-raised: the run stops |
| flowchart engine, under `views/flowcharts.py` | non-zero → the view logs it, the phase goes on | 75 → `PauseRequested`: the views phase exits 75 |
| `incremental/engine.py`, `generate.py` | `rc not in (0, 3)` → a `failed` manifest, `AnalyzerRunFailed(rc)` | 75 → `AnalyzerRunFailed(75)`, no manifest: the version stays where it stopped, not `failed` |
| `analyzer.py` `_generate`, `_render_version`, `_resume` | 2, 3 handled, others raise | 75 → "Paused at a safe point", return 75 |
| `version_run.writing()` | outcome `complete` \| `failed` | 75 → `paused` |
| `_main_recording_exit` | writes the code to exit.json | unchanged |
| API `_follow_detached`, `_execute_subprocess` | `rc in (0, 3)` ok, else failed | 75 → `paused`, `paused_at = now`, version kept (`_record_paused`) |
| `incremental/staged.py` | `resume_plan`'s "busy" is the writer lock, not the outcome | unchanged; `progress` says PAUSED |

**Resume redoes the step it stopped in, not the exact item** (the user, 2026-10-19) — `resume_plan`
already decides which: paused in the parse → the parse again; in Phase 2 → Phase 2 again from the
stored parse; in Phases 3–4 → the components not finished (put back to `waiting`); an export that was
adding a layer and stopped before its model was stored → that export again. Answers already saved come
back from the cache in milliseconds; one not saved is asked again. Example: paused in Phase 2 at function
120 of 500 with about 100 answers saved — resume takes those 100 from the cache, asks the others again,
and goes on to 500. Nothing is left out, for two reasons:

- **A step counts as done only when it has finished.** Each phase saves its database work once, at its
  end, in one transaction (the `model_repo` buffer, `flush_model` after `main()`); `pipeline_status`
  names the phase under way; a component is `generated` only once it is stored
  ([§9](#9-cancel-and-remove)). A step cut short is never taken for a finished one.
- **"Must be rewritten" is forgotten only together with the rewrite.** Phase 2 retires a
  regeneration-queue entry (a text a correction made stale) in the same transaction as the model it
  rewrote. Today `_retire_regeneration_queue` commits on its own, earlier: a stop between the two left the
  old text and no entry saying so — the next run kept it, as enrichment skips a text already filled in.
  The fast Word-file update already writes each text and retires its entry together (`rewrite._Writer`).

**Resume** — `POST …/jobs/{j}/resume` (today's route, new meaning): `resume_requested_at`; the scheduler
claims it first when the cap has room ([§5](#5-the-scheduler)), clearing the request, and runs
`_run_resume` with this job — `analyzer.py resume --job-id J`, which runs a recorded `generate` again
inside the same job; `paused_seconds` grows by the pause. A `--no-llm` version resumed (or re-exported)
from Phase 3 keeps the LLM off (`--no-llm-summarize`): before, a machine with no LLM server refused it.
`tests/e2e/test_pause_resume.py` pauses a real run once Phase 2 has begun, resumes it, and finds its
views those of a run never paused. **Paused too long** — `jobs.pausedDays` (7) after `paused_at`:
cancelled ([§9](#9-cancel-and-remove)), told; the pause notice names that date. A server that wants
longer sets `jobs.pausedDays` (15, say).

## 9. Cancel and remove

`POST …/jobs/{j}/cancel` does both, by state (REQ-JS-25, 26):

- `queued`, `held` → `removed`; a generation's draft version is deleted, its name freed.
- `running` → `cancelled`; the process tree or background run is stopped (today's `cancel_subprocess`,
  `stop_background_run`); once it has exited, a version that never finished is deleted, one with Word
  files keeps them (`_release_draft_version`, `_finish_if_it_finished`, today).
- `paused` → `cancelled`; no process; the version as above.
- a CLI run (`origin = cli`) → 409 `CLI_RUN`: "started from the command line by … on …; stop it there".

Who: the submitter their own, a project admin any of the project's, a super admin any.

**What a cancel leaves — nothing is undone call by call.** Each phase saves its database work once, at
its end, in one transaction: a phase cut short has saved nothing (the database also throws away a
transaction whose process died). And everything a run saves is under its version: every per-version
table deletes its rows with the version (`ON DELETE CASCADE`; `PER_VERSION_TABLES`,
`tests/unit/test_schema.py`).

| A new version, cancelled during | Already saved | After the cancel |
|---|---|---|
| Phase 1 (parse), at 80% | nothing — the parse is saved at its end | the version is deleted; nothing else is left |
| Phase 2 (model), at 80% | the parse | the version is deleted, its parse with it |
| Phase 3 (views), at 80% | the parse, the model, the finished components' views | the version is deleted, all of it with it |
| Phase 4 (Word files), at 80% | the same, and Word files on disk | the version is deleted, and its folder |

Shown end to end by `tests/e2e/test_cancel_leaves.py`: a real run stopped in each of Phases 1–3, then
cancelled, leaves no row of its version in any table and no folder.

An export or an update of an existing version is not deleted: Word files are swapped in whole
(`docx_common.save_docx`), and what the job had not finished stays out of date or not generated, so the
next run makes it.

- **Kept on purpose:** the LLM answers in the cache — right for any later run on the same code, so they
  are not paid for again — and the shared entity ids and content blobs (insert only: a run never
  overwrites a good row; `reuse_index` too).
- **Stop first, then delete:** the stop takes the whole process tree and waits for it
  (`frozen_run.stop`, `_stop_tree`); the version is deleted once its writer lock is free.
- **The version's folder goes too.** `delete_version` deletes rows only: today its Word files and
  pictures stay on disk. Deleted after the rows.
- **Each component is stored when it is finished.** Today `run.py` marks a component `generated` when
  its Word files are made, and the run stores its text once, at its end (`capture_output`): cancelled in
  between, an export's finished component says `generated` and is not stored. Now each component is
  stored after its Phase 4 — its text, its Word files' time (`word_file_at`) and `generated`, in one
  transaction — so a cancel keeps the finished components whole and the next run makes only the rest.

## 10. Restart and held jobs

**Start-up**, in this order (`api/main.py`; replaces most of `_fail_interrupted_jobs`):

1. Claim the job-runner lock (today). Not claimed → this server submits but schedules nothing.
2. Follow again every running web job (`origin = web`) with a background run (`_reattach_detached`,
   today); one with none ran inside the server that stopped → `interrupted`. CLI runs are left to their
   alive signal: the API neither follows nor ends them.
3. `jobs.startQueuedAfterRestart` false → in the scheduler's first round, the queue of each project a
   job was left waiting in is held: those jobs → `held`, and so does any submitted to the project since
   the start-up, which goes after them. A project that had none left waiting is not held — the first
   round can be a submit's own, and before, it held that submit too. Each held project's admins — super
   admins are admins of every project — are told "N jobs held after a server restart". True → they stay
   `queued`.
4. Paused jobs stay paused; a resume already asked for stays asked for (an admin's decision).
5. Start the scheduler. On the in-memory backend (no database) too, but it neither holds nor sweeps:
   nothing outlives that process, and its seeded "running" job has no process to interrupt.

**A project's queue is held while it has a held job**; a job submitted meanwhile is held too (REQ-JS-18).
`POST /queues/held {project_id?, remove: [job ids] | "all"}` (super admin): the listed jobs, or all, are
removed; the rest go back to `queued` with their `submitted_at`, so in their order. Start all =
`remove: []`; clear all = `remove: "all"`; clear some and start the rest = the list. Without
`project_id`: every project.

## 11. The CLI

`generate`, `export`, `resume` (generation lane) and `reexport` (update lane), first thing — before
`--detach` hands over (`analyzer.py` `main()` → `_as_job`):

1. **`--job-id J`** — the run is job J's (the API's run, or a CLI run's background half): no checks,
   nothing new recorded; the process beats for J. `resume` runs a recorded `generate` again inside its
   own job (`main(argv, queue=False)`), the recorded command line without its `--job-id`.
2. **Checks** (REQ-JS-28), in one transaction under the queue lock and the project's row lock: refused,
   exit 2, naming the jobs, `LANE_BUSY` when the project's lane has a running or paused job (listed with
   any waiting behind it), `JOBS_WAITING` when it has a waiting or held one, and for the generation lane
   `SERVER_FULL` when running generations ≥ `jobs.maxGenerations`. `--ignore-queue` skips them — the
   CLI is the super admin's. A project with no database row: `NO_PROJECT`, onboard it.
3. **Record** (REQ-JS-29), in the same transaction (`job_queue.record_cli_run` → `db.jobs.record_run`):
   a job `origin = cli`, `running`, `runner = cli <user>@<host> pid N`, `forced` with `--ignore-queue`;
   events `submitted` and `started`; the project's admins told. With `--detach` the launcher records it
   and adds `--job-id J` to the background run's command line; a launch that fails ends the job failed.
4. **End** — a CLI job is ended by its own run (`_run_as_job` → `job_queue.end_cli_run`): `complete`
   (exit 0, or 3: some components failed, the others made), `failed`, or `cancelled` on Ctrl+C; the
   scheduler sees the lane free on its next round. Killed → interrupted when silent
   ([§7](#7-alive-signal-and-interrupted)); interrupted while it slept, it takes its real end when it
   ends after all. A web job's end is the API's, as today.

No database configured: no queue — the run says itself what it lacks. A database from before 0019:
refused, `analyzer.py setup` upgrades it. The phases a run starts know its job by `ANALYZER_JOB_ID`,
which the API already set for a web run's metrics. The rule "lane busy, jobs waiting, cap full" and
the SQL that counts it are written once, in `engine/core/job_lanes.py`, which the CLI's record and the
API's claim both use. No queue commands (REQ-JS-27).

## 12. Config

`config.local.json` only (REQ-JS-05, 18, 20, 24, 34):

```jsonc
"jobs": {
  "maxGenerations": 2,              // generations running at once, all projects
  "startQueuedAfterRestart": false, // true: waiting jobs are not held at start-up
  "pausedDays": 7,                  // a job paused this long is cancelled
  "interruptedAfterMinutes": 10,    // silent this long: interrupted
  "keepFinishedDays": 90            // ended jobs' records
}
```

- `jobs` joins `SERVER_BLOCKS` (`engine/core/config.py`): never in the defaults, a project's or a
  version's config. Not in `RUN_SERVER_BLOCKS`: read by its own reader, `core.config.jobs_settings()`,
  as `auth` is — a missing file, block or key gives the default; a bad value is said and ignored. The API
  reads it at start-up (restart it after a change), the CLI at each run.
- Each value a number above zero, `startQueuedAfterRestart` true or false. `maxGenerations` a whole
  number (`JOBS_WHOLE`): 1.5 was taken, and the claim counted to 1 while the waiting messages and the
  Run dialog counted to 1.5. `interruptedAfterMinutes` at least 2 (`JOBS_LEAST`) — a running job beats
  every minute ([§7](#7-alive-signal-and-interrupted)), and at 1 a live run was interrupted between two
  beats, the next job started beside it; a smaller value is said and raised to 2. `pausedDays` and
  `keepFinishedDays` take parts of a day: a test server sets 0.003 (about four minutes) and 0.002 (about
  three) — `tools/job_scheduling_test` complex mode does (2026-10-29).
- `config.local.json.example` gets the block. **Removed:** `JOB_MAX_CONCURRENCY`
  (`settings.job_max_concurrency`), the semaphore `_SEMAPHORE`, and their mentions in docs.
  `JOB_DETACH` is not part of this and stays.

## 13. API

The contract, with every field and refusal: [JOB_SCHEDULING_API_SPEC](../spec/JOB_SCHEDULING_API_SPEC.md).

| Route | Who | Answer |
|---|---|---|
| `POST /projects/{p}/jobs` | project admin | 202 `{job, status, position, ahead, estimated_start, message}`; 409 `LANE_FULL`, `DUPLICATE_JOB`, `VERSION_EXISTS`, `CONFIG_INVALID`; 422 `UNKNOWN_COMMIT` |
| `POST /projects/{p}/versions/{v}/documents/generate` | project admin | as above (export) |
| `POST /projects/{p}/versions/{v}/resume` | project admin | as above (resume) |
| `POST /projects/{p}/versions/{v}/reexport` | member | as above, or 200 with `joined` / `already_queued` |
| `POST /projects/{p}/jobs/{j}/pause` | project admin | 200 the job; 409 `NOT_PAUSABLE` |
| `POST /projects/{p}/jobs/{j}/resume` | project admin | 200 the job; 409 `NOT_PAUSED` |
| `POST /projects/{p}/jobs/{j}/cancel` | own, project admin | 200 the job (`cancelled` or `removed`); 409 `JOB_FINISHED`, `CLI_RUN` |
| `PATCH /projects/{p}/jobs/{j}` `{priority}` | super admin | 200; 409 when not a waiting generation. Set from the status the job has — a hold or a release made since the page was read stays made |
| `GET /projects/{p}/queues` | member | both lanes: active job, waiting and held jobs (position, estimate, submitter, what), limits, cap use, flags |
| `GET /projects/{p}/queues/preview?lane=` | member | the Run dialog's answer: `start` \| `wait` (position, estimate) \| `refuse` (the jobs) |
| `PATCH /projects/{p}/job-limits` `{generation_limit, update_limit}` | project admin | 200; 422 outside 1–50 |
| `GET /queues` | super admin | every project's queues, cap use, held count, flags |
| `POST /queues/held` `{project_id?, remove}` | super admin | 200 what was removed and released |
| `DELETE /projects/{p}/versions/{v}` | project admin | 409 `RUN_ACTIVE` while a job of the project runs or is paused; `VERSION_NEEDED` while a waiting job needs the version ([§16](#16-cases)) |

**Messages, one field per place (REQ-JS-35)** — the fields the web app already reads, never a new one:

| What | Field | The web app reads it in |
|---|---|---|
| a refused request | `detail: {code, message, status, …}`; the jobs in the way as extra fields | `lib/http.ts` → `ApiError.message`, `.code` |
| a submit's answer | `message`: "Starts now", "Waits as #2 — about 3 h", "Held: the queue is held after a restart" | the answer |
| a job's state | `current_activity`: "Waiting as #2 — after J1, generate v4", "Waiting for v4: the export of Lib is writing it", "Held after a restart", "Pausing at the next safe point…", "Paused — cancelled on 28 Oct unless resumed" | `services/mappers/job.ts` |
| how a job ended | `error_message`: a headline line, then `- ` lines for the reasons and what to do | `lib/failure.ts` `failureParts` |
| a notice | `notifications.message` | the notification list |

`GET /projects/{p}/jobs/current` becomes the project's running or paused generation, else its latest
ended one — never a waiting one. A super admin is a project admin everywhere (`require_project_admin`,
today). Job lists carry the new fields: `lane`, `priority`, `position`, `estimated_start`, `origin`,
`runner`, `heartbeat_at`, `pause_requested`, `resume_requested`, `submitted_at`, `flags`.

## 14. Web app

**Manoj builds the screens** (the user, 2026-10-21); this branch changes nothing in `web-app/`. What the
screens need, for him — from the routes of [§13](#13-api), whose contract is
[JOB_SCHEDULING_API_SPEC](../spec/JOB_SCHEDULING_API_SPEC.md). Mockups first (`docs/ui-mockups/`); WCAG
2.2 AA as the rest (`ui-dev` skill §8, `web-app/src/__tests__/accessibility.test.ts`).

- **Run dialog**, and the Generate, Resume and Update buttons: the preview line under the action — "Starts
  now", "Waits as #2 — about 3 h", or "Refused: 3 of 3 places taken — J1 running, J2 and J3 waiting",
  the action disabled then (REQ-JS-31). The baseline line says it is chosen when the job starts (REQ-JS-10).
- **Project Overview — Queue card**: per lane, the active job (progress; Pause, Resume, Cancel) and the
  waiting ones (position, submitter, what, estimated start, Remove; a priority select for a super admin);
  a "held" banner.
- **Queues page**, super admins only (new; the web app has no admin area yet): every project; cap use ("1 of 2 running"); held jobs with
  Start all, Clear all, and select + "Clear selected, start the rest"; flagged jobs.
- **Project settings**: the two limits.
- **Versions page and Subbar**: a waiting job's draft version reads "Waiting (#2)" and is never the
  default selection.
- Status badges for `held`, `interrupted`, `removed`, "Pausing…", "Resuming…"; the notification types
  of §15; today's 409 handlers (`JOB_ALREADY_RUNNING`, `REEXPORT_RUNNING`, `VERSION_BUSY`,
  `EXPORT_RUNNING`, `RUN_ACTIVE`) replaced by the new answers. Files: `services/api/jobs.ts`,
  `hooks/useJobs.ts`, `components/run/GenerationBanner.tsx`, `hooks/useWordFiles.ts`, `lib/wordFiles.ts`,
  `pages/ProjectDetailPage`, `pages/VersionsPage.tsx`, `types/index.ts`, and new ones for the screens above.

## 15. Notices, record, measures

- **Notices** (REQ-JS-32): a `notifications` row per person — the submitter (a web job's) and the
  project's admins — when a job starts, completes, fails, is paused, cancelled, interrupted or cancelled
  after its paused days (`job_cancelled`, its message says why); the project's admins for a restart's
  held jobs. Types `job_started`, `job_completed`, `job_failed`, `job_paused`, `job_cancelled`,
  `job_interrupted`, `jobs_held`. An update's end keeps today's text to its starter (`tell_update_end`).
  An end is recorded and told once — by whichever of the job's thread and the act that ended it (a
  cancel) comes first — and once per run: a job submitted again (`requeue`) that fails again is told
  again (`after_end` counts the ends since the job last began).
- **Record** (REQ-JS-33): a `job_events` row for every change of [§3](#3-a-jobs-states), and for
  priority, limits and held-queue actions, with the person and the time — a cancel's with who
  cancelled.
- **Measures** (REQ-JS-34), from the rows: queue length per lane; waiting time (`started_at −
  submitted_at`); run time (`completed_at − started_at − paused_seconds`) and per phase (`phases[].
  duration_seconds`). Flags: waiting more than a day; running with no progress for 30 minutes
  (`version_runs.progress_at`) — "stuck", shown, not stopped.
- **Retention** (once a day, or every `jobs.keepFinishedDays` when that is shorter — so a record is gone
  by twice its days): ended jobs older than `jobs.keepFinishedDays` go, with their events and
  `job_functions` — **except each existing version's newest generation job**: an update reads how the
  version was generated from it (`start_update`), and the version's functions hang off it.

## 16. Cases

| Case | What happens |
|---|---|
| Two submits at once, one place left | the project lock: one is accepted, the other gets `LANE_FULL` |
| Two claims at once (a second server, later) | the queue lock and the unique index: one starts |
| Cancel at the moment of the claim | compare-and-set: a removed job is not claimed; a job just claimed is stopped |
| Pause asked, the run ends first | `complete`; the request is cleared |
| Pause asked, then cancel | `cancelled`, the process stopped |
| The server restarts while a job is pausing | the run exits 75 on its own; the follower, attached again, reads exit.json: `paused` |
| A CLI `--ignore-queue` run beside a web job in the lane | both run; the next starts when both have ended |
| Database down for 5 minutes | runs wait and retry (`retry_connects`, `_when_db_answers`); nobody is interrupted ([§7](#7-alive-signal-and-interrupted)) |
| A limit lowered below what is accepted | nothing removed; submits refused until the count is under it |
| The commit gone while the job waits | fails at its start; the next starts |
| Delete a version | refused while a job runs or is paused in the project (today's `RUN_ACTIVE`), or a waiting job needs the version (its own, or its chosen baseline), naming them; other waiting jobs do not stop it |
| An update while an export into its version runs | it waits; later updates of other versions pass it |

## 17. Files that change

| File | Change |
|---|---|
| `alembic/versions/0019_job_scheduling.py`, `api/db/postgres/schema.py`, `analyzer.py setup` | [§2](#2-data--migration-0019) |
| `api/services/job_queue.py` (new) | `enqueue`, `requeue`, positions, estimates, messages, held actions, limits, cancel and remove, interrupt, the alive signal (`Heartbeat`), a CLI run's record and end, the views, the version delete guard |
| `api/services/job_scheduler.py` (new) | the loop, claims, sweeps, retention, `kick` |
| `engine/core/job_lanes.py` (new) | the lanes, the CLI's rule, the queue lock and the counts a claim and a CLI record share |
| `engine/core/pause.py` (new) | `requested`, `check`, `exits_paused`, `EXIT_PAUSED`, `PauseRequested` |
| `api/services/pipeline_runner.py` | starts → `enqueue`; `launch_job` from the scheduler; no semaphore; `--job-id`; states via `transition`; exit 75; interrupted; start-up; the commit and config checks at submit; a deleted version's folder deleted |
| `api/main.py` | start-up order of [§10](#10-restart-and-held-jobs); the scheduler instead of `_watch_jobs` |
| `api/routes/jobs.py`, `api/routes/version_components.py`, `api/routes/queues.py` (new) | [§13](#13-api) |
| `api/routes/commits_versions.py` | the version delete guard of [§16](#16-cases) |
| `api/db/postgres/database.py`, `api/db/in_memory.py` | `transition` (a lane's second job is "not changed"); `update()` never writes the state; queue queries — `add_to_lane`, `claim`, `record_run`, `lane_jobs`, `in_status`, `prune_ended`; `get_current` |
| `api/models/domain.py` | job fields, statuses, project limits |
| `api/services/settings.py` | `job_max_concurrency` gone |
| `api/services/word_files.py` | the update's answer: its place and message |
| `engine/core/config.py`, `engine/config/config.local.json.example` | `jobs` block, `jobs_settings()` |
| `engine/core/version_run.py` | outcome `paused` |
| `engine/core/db.py` | the SQLite foreign-key hook runs on SQLite connections alone: on a PostgreSQL one its failed `PRAGMA` left the transaction aborted |
| `tests/api/conftest.py` | every API test has a scheduler without its thread, no job left waiting by an earlier test, its job threads ended with it; the SQLite test database's one connection taken in turns |
| `tests/conftest.py` | `ANALYZER_JOB_ID` put back after every test: `analyzer.main()` called in-process sets it, and the next tests' pause points read it |
| `tools/job_scheduling_test/` (new) | the whole feature against a running API, through REST and the command line: `--mode normal`, `--mode complex` (the `jobs` settings too, each scenario under its own, on an API the test runs) and `--mode cli` (through `analyzer.py`), a report per requirement ([its README](../../tools/job_scheduling_test/README.md)) |
| `engine/llm_core/cache.py` | every cache saves its buffer at process exit (`atexit`) |
| `engine/model_deriver.py`, `engine/core/model_repo.py` | regeneration-queue entries retired in the model's transaction ([§8](#8-pause-and-resume)) |
| `engine/run.py`, `engine/incremental/store.py` | each component stored when it is finished ([§9](#9-cancel-and-remove)) |
| `engine/parser.py`, `engine/model_deriver.py`, `engine/llm_enrichment.py`, `engine/flowchart/flowchart_engine.py`, `engine/core/orchestration.py`, `engine/run.py`, `engine/incremental/engine.py`, `engine/incremental/generate.py`, `engine/incremental/staged.py` | pause points, exit 75 ([§8](#8-pause-and-resume)) |
| `analyzer.py` | `--job-id`, `--ignore-queue`, checks and record, the run's alive signal, its end — Ctrl+C → cancelled; 75 |
| `web-app/` | Manoj, from [§13](#13-api) and [§14](#14-web-app) — not this branch |
| docs | this design, the spec, `docs/spec/JOB_SCHEDULING_API_SPEC.md` (new: the HTTP contract for the screens), `docs/CLI_COMMANDS.md`, `DB_SCHEMA.md` + `schema-atlas.html`, the project context |

## 18. Two servers, later

Ready: the queue is in the database; a claim is one transaction under one database lock, with the
unique index behind it; liveness is a heartbeat and the writer lock, not a thread; `runner` names the host.
Not yet: only the job-runner server schedules (another only submits); a job's live log and its SSE stream
are in the memory of the server that runs it; Word files, pictures and checkouts are on that server's
disk; the restart hold assumes one server; the cap counts the whole database — a cap per server beside it
comes then.

## 19. Tests

| Test | Covers |
|---|---|
| `tests/api/test_job_queue.py` — both backends, a fresh database per test | the queue: the three answers, limits, duplicates, idempotency, held submits, position and estimate; the scheduler: priority, first come first served, fairness across projects, the cap, a paused job not counted, resume first, a busy version (head waits; an update is passed), the claim, interrupted with the outage guard, `pausedDays`, retention keeps each version's generation job and runs every `keepFinishedDays` when shorter than a day; a CLI run's record and end — REQ-JS-02–13, 16, 18, 20, 21, 24, 28, 29, 34 |
| `tests/unit/test_core_config.py` `TestJobsSettings` | the `jobs` block read as [§12](#12-config) says: parts of a day, a whole-number cap, `interruptedAfterMinutes` at least 2, a wrong value said and its default used |
| `tests/api/test_job_state_writes.py` | compare-and-set: a progress write after a cancel leaves it cancelled; `update()` never writes the state ([§1](#1-principles)) |
| `tests/unit/test_job_state_writers.py` | no code outside the job repository sets a job's status; the check would notice a new one ([§1](#1-principles)) |
| `tests/unit/test_job_lanes.py` | the CLI's rule, the counts on the schema's table, the API's statuses the same as the lanes' |
| `tests/unit/test_pause.py` (the cache's exit hook too) | the request, read and cached; `PauseRequested` past `except Exception`, not raised on a worker thread; the step entry exits 75; the LLM loops drop the items not started; 75 through `PhaseRunner`, the run record (`paused`) and the CLI; every cache saves its buffer at exit — REQ-JS-22, 23 |
| `tests/unit/test_review_queue_consumers.py` | a stop between Phase 2's rewrite and its model save leaves the queue entries in place |
| `tests/e2e/test_cancel_leaves.py` | a new version's real run stopped in Phase 1, 2 or 3 — its whole process tree, as a cancel stops it — then cancelled: no row of it in any table, no folder, though the parse, the model and some views had been saved — REQ-JS-25. An export cancelled half way keeps its finished components whole (`tests/unit/test_staged_generation.py`, `store_finished`) |
| `tests/unit/test_cli_job_gate.py` | the three refusals, `--ignore-queue`, the record, `--job-id` attaches, `resume` drops a recorded one — REQ-JS-27–29 |
| `tests/api/test_queue_routes.py` | every route of [§13](#13-api), the permissions table, cancel vs remove, the commit and config checks at submit, the version delete guard — REQ-JS-07, 25, 26, 30, 31, 33 |
| `tests/e2e/test_pause_resume.py` | a real run (`--no-llm`) paused once Phase 2 has begun exits 75, recorded `paused`, its version not failed, its web job left to the API; resumed as the same job, it completes, its views those of a run never paused; it deletes its version, rows and folder, before and after — REQ-JS-22, 23 |
| `tests/unit/test_job_claims_pg.py` (a scratch PostgreSQL, `ANALYZER_TEST_PG_DSN`) | claims at once start one job; a lane's waiting jobs claimed at once start one; the cap under claims at once; CLI records at once in a free lane start one; the unique index; a silent job whose version is being written is not interrupted — REQ-JS-05, 14, 15, 20, 28 |

Tests that expected the old 409s (`JOB_ALREADY_RUNNING`, `REEXPORT_RUNNING`, `VERSION_BUSY`,
`EXPORT_RUNNING`, `RUN_ACTIVE`) now expect the new answers; tests that expected a dead run to end
`failed` expect `interrupted`.

## 20. Decisions beyond the spec

Confirmed by the user on 2026-10-21; the spec says the same where it shows to a user.

1. **A paused job keeps its version.** Other jobs on that version wait until it is resumed and ends, or is
   cancelled — an update of it can wait up to `pausedDays`. Simple and safe: a paused export may be half way
   through changing the model. Later, updates of other components could pass a paused job that does not
   change the model.
2. **A blocked update is passed; a blocked generation waits** ([§5](#5-the-scheduler)).
3. **A resumed job takes the first free server slot**, before waiting generations.
4. **A followed run whose process is gone is interrupted at once**, not after 10 minutes.
5. **`--ignore-queue`, not `--force`**: `reexport --force` already means "export past the stale-views
   guard", and one flag should not skip two different checks.
6. **Every status change by compare-and-set**, and the progress writes no longer write `status`.
7. **Retention keeps each version's generation job** past `keepFinishedDays`.
8. **Resume redoes the step it stopped in**, not the exact item (the user, 2026-10-19): answers already
   saved come from the cache, the others are asked again ([§8](#8-pause-and-resume)). No write per answer.
9. **A cancel undoes nothing call by call** ([§9](#9-cancel-and-remove)): each phase saves once, at its end;
   a new version is deleted whole, its folder too; an existing one keeps only what was finished, whole.

## 21. Risks

- **LLM gateway rate.** `llmServer.rateLimitSeconds` is per process: two generations and some updates at
  once ask the gateway more often than it allows (the warning in `api/services/settings.py`). Until a
  shared limiter: a `rateLimitSeconds` that allows for the cap, or the `speedups.llms` lanes
  ([PIPELINE_SPEED_PLAN](PIPELINE_SPEED_PLAN.md)).
- **A pause point missed** in a long LLM loop: the pause waits for the next one. Every loop that asks the
  LLM about many items is listed in [§8](#8-pause-and-resume) and checked by `test_pause.py`.
- **Notices**: admins of a busy project get one per update's start and end. If too many: tell admins only
  of generation-lane events and failures.
- **Held after every restart**, updates too: a server restarted often (development) sets
  `startQueuedAfterRestart: true`.
- **Waiting drafts** show in version lists until the web app reads them as waiting ([§14](#14-web-app)).
- **Cancelled after 7 days paused**: a version that never finished is deleted; its LLM answers stay
  cached, so running it again pays no LLM twice.
