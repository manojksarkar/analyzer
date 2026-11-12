# Job Scheduling — Design Overview

**Status, 2026-11-12:** built and tested in the server, the REST API and the command line, on branch
`feat/job-scheduling` (not yet merged into `develop`). The web screens are separate work, on the
ready API.

## 1. Purpose

Before, a second run of a project was refused ("already running"), and running jobs were counted in
one API process's memory. Now:

- Jobs **wait their turn** and start by themselves.
- **Two queues per project**, a limit per project and a cap for the server.
- **Pause, resume, cancel, remove.**
- The queue lives **in the database**: a restart or a crash loses nothing.
- The **command line** follows the same rules.

## 2. Key terms

| Term | Meaning |
|---|---|
| Lane | A project's queue for one kind of job. **Generation:** generate, export, resume. **Update:** Word-file update. |
| Running job | At most one per lane per project. A paused job keeps its lane. |
| Project limits | 3 generation jobs and 10 update jobs per project, running and waiting together. A project admin can change them. |
| Server cap | Generations running at once, all projects together: 2 by default. Updates have no cap. |
| One writer per version | One job writes a version at a time; the others wait. |
| Priority | High, Normal or Low, for generations; set by a super admin. |

## 3. How the scheduler works

```
                    Web app                                  Command line
                       |  submit                                   |  analyzer.py
                       v                                           v
  +----------------------------------------+   +---------------------------------------+
  | API submit                             |   | CLI gate: never queues                |
  |  1 checks: commit, scope, config, name |   |  lane busy, jobs waiting or server    |
  |  2 same request key: the same job      |   |  full: refused (exit 2)               |
  |  3 project lock: duplicate, or lane    |   |  else: records itself as the lane's   |
  |    full: refused with the reason       |   |  running job, and runs                |
  |  4 insert as waiting (held after a     |   |  --ignore-queue: super admin override |
  |    restart); wake the scheduler        |   +-------------------+-------------------+
  +--------------------+-------------------+                       |
                       |                                           |
                       v                                           v
  +------------------------------------------------------------------------------------+
  | analysis_jobs table: the queue, in the database                                    |
  |                                                                                    |
  |   Project A   generation lane:  [running]  <- waiting <- waiting     limit 3       |
  |               update lane:      [running]  <- waiting                limit 10      |
  |   Project B   generation lane:  [paused]   <- waiting                              |
  |               update lane:      (free)                                             |
  +------------------------------------------^-----------------------------------------+
                                             |  claim, under the queue lock:
                                             |  lane, cap and version checked again
  +------------------------------------------+-----------------------------------------+
  | SCHEDULER: one thread, on the server that runs jobs                                |
  | wakes every 10 s, and at once on a submit, a job's end, a release or a resume      |
  |                                                                                    |
  | each round:                                                                        |
  |  1 sweeps, at most once a minute:                                                  |
  |      silent 10 min -> interrupted     paused 7 days -> cancelled                   |
  |      ended jobs' records older than 90 days -> deleted                             |
  |  2 claims, in this order:                                                          |
  |      a. resume requests, oldest first                                              |
  |      b. generations: each project's next job (priority, then oldest);              |
  |         the longest wait starts first, while running generations < cap (2)         |
  |      c. updates: each project's oldest job whose version is free                   |
  |  3 launch each claimed job                                                         |
  +------------------------------------------+-----------------------------------------+
                                             |  launch
                                             v
           +------------------------------------------------------------------+
           | RUN: analyzer.py <command> --job-id J --detach                   |
           |  a background process: it outlives an API restart                |
           |  sends its alive signal every 60 s; pauses at safe points        |
           +---------------------------------+--------------------------------+
                                             |  exit code
                                             v
             0 or 3: complete          75: paused          other: failed
             then: event recorded, people told, scheduler woken -> next job
```

- **One start per job.** A claim is one database transaction under a lock, and a unique index
  refuses a second running job in a lane.
- **No lost changes.** A job's state changes only by compare-and-set: a cancel and a claim at the
  same moment cannot both win.
- **Runs outlive the API.** Each run is a background process with its own alive signal; a restarted
  API follows it again.

## 4. A job's states

| State | Meaning |
|---|---|
| Waiting | In its lane, in order, with its place ("#2") and an estimated start. |
| Held | Waiting after a server restart, until a super admin starts or clears it. |
| Running | Started by the scheduler, or a command-line run. |
| Paused | Stopped at a safe point. Frees its server slot, keeps its lane. Cancelled after 7 days. |
| Complete, failed | Ended by the run. A failed job keeps its version for a resume. |
| Interrupted | Silent for 10 minutes, or its process gone. The next job starts. |
| Cancelled, removed | Stopped while running or paused; taken out while waiting. |

## 5. What is implemented

| Area | Key points |
|---|---|
| Submitting | Three answers: "starts now", "waits as #2, about 3 h", or refused with the reason · commit, scope, config and name checked at submit and again at start · no duplicate jobs · a request sent twice makes one job · an incremental job picks its baseline when it starts |
| Order | Generations by priority, then fair across projects: the longest wait starts first · updates first come, first served |
| Reliability | The next job starts by itself · a short database or LLM outage makes a job wait, not fail · after a restart, waiting jobs are held until a super admin releases them · running jobs carry on through an API restart |
| Pause and resume | A generation pauses at the next safe point, within about a minute · resume redoes the step it stopped in and reuses the LLM answers already saved |
| Cancel and remove | A cancel stops the job at once and leaves nothing half-made · a waiting job can be removed |
| Command line | Never queues · refuses when the lane is busy, jobs are waiting or the server is full · a super admin can override (`--ignore-queue`) · a command-line run counts as the project's running job |
| Visibility | Each project's queues, and every project's for a super admin · the Run dialog says what will happen before you submit · notices on start, end, failure, pause, cancel and interrupt · every action recorded with who and when · waiting and run times measured, stuck jobs flagged · messages in plain words |

## 6. Who may do what

| Action | Super admin | Project admin | Developer, reviewer |
|---|---|---|---|
| Submit a generation | Yes | Yes | No |
| Submit a Word-file update | Yes | Yes | Yes |
| Pause or resume a generation | Yes | Yes | No |
| Cancel a running job, remove a waiting one | Any | Any in the project | Their own |
| Set priority | Yes | No | No |
| Change a project's limits | Yes | Yes | No |
| Start or clear held jobs | Yes | No | No |

## 7. Server settings

The `jobs` block in `config.local.json`. The API reads it at start-up, the command line at each run.

| Setting | Default | Meaning |
|---|---|---|
| `maxGenerations` | 2 | Generations running at once, all projects together |
| `startQueuedAfterRestart` | false | false: waiting jobs are held after a restart |
| `pausedDays` | 7 | A job paused this long is cancelled |
| `interruptedAfterMinutes` | 10 | A job silent this long is interrupted |
| `keepFinishedDays` | 90 | How long ended jobs' records are kept |

## 8. Interfaces and data

| Purpose | REST routes |
|---|---|
| Submit | `POST /projects/{p}/jobs` · `.../versions/{v}/documents/generate` · `.../versions/{v}/resume` · `.../versions/{v}/reexport` |
| Control a job | `POST /projects/{p}/jobs/{j}/pause`, `/resume`, `/cancel` · `PATCH /projects/{p}/jobs/{j}` (priority) |
| See the queues | `GET /projects/{p}/queues` · `GET /projects/{p}/queues/preview` · `GET /queues` (all projects) |
| Administer | `PATCH /projects/{p}/job-limits` · `POST /queues/held` (start or clear held jobs) |

Database (migration 0019, applied by `analyzer.py setup`): `analysis_jobs` gains the lane, priority,
place in the queue, alive signal, pause and resume requests, origin and runner; `projects` gains the
two limits; a new `job_events` table records every action.

## 9. How it was verified

- Unit and API tests on SQLite and PostgreSQL; real pipeline runs paused, resumed and cancelled in
  each phase.
- An end-to-end test tool through the REST API and the command line: 40 scenarios (normal 14,
  complex 16, command line 10), with a result for every requirement. All pass here; one office re-run
  with the real LLM is pending.

## 10. Known limits

- Jobs have no CPU, memory or disk limits: the cap counts generations, not their size.
- Word-file updates have no server cap.
- The LLM rate limit applies per process, so jobs running together can call the LLM gateway more
  often than it allows. Until there is a shared limit, set `llmServer.rateLimitSeconds` with the cap
  in mind.
- Resume repeats the step it stopped in: a long parse runs again.
- One server runs jobs. A second needs Word files, pictures, checkouts and logs reachable from both.

## 11. What is left

- **Web screens** (Manoj): the Run dialog's answer, the project's queue card, the queues page for
  super admins, the limits in project settings, waiting versions in the versions list.
- **Small fixes and checks:** on SQLite only, two submits at the same instant can overfill a lane by
  one; two runs of one commit can word a few LLM sentences differently (cause to confirm); a manual
  database-outage check; the office re-run above.
- **Release:** merge into `develop`; on each server, `analyzer.py setup` (database upgrade) and the
  `jobs` settings if the defaults don't fit.

**In the repository:** `docs/spec/JOB_SCHEDULING_SPEC.md` (requirements REQ-JS-01 to 35) ·
`docs/design/JOB_SCHEDULING_DESIGN.md` (full design) · `docs/spec/JOB_SCHEDULING_API_SPEC.md` (HTTP
contract) · `docs/planning/JOB_SCHEDULING_SUMMARY.md` (status per requirement).
