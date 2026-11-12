# Job Scheduling — High-Level Design

**Status, 2026-11-12:** built and tested in the server, the REST API and the command line, on branch
`feat/job-scheduling` (not yet merged into `develop`). The web screens are separate work, on the ready
API. Section 4 is a proposal, not yet built.

## 1. Overview

**Purpose**

- **Before:** a second run of a project was refused ("already running"), and running jobs were counted
  in one API process's memory, so a restart forgot them.
- **Now:** jobs wait their turn in queues per project and start by themselves. The queue lives in the
  database. The command line follows the same rules.

**Scope**

- **In:** queues per project, the scheduler and the server cap, pause, resume, cancel and remove, the
  REST API, the command line's checks, notices and the action record, database migration 0019.
- **Not in this release:** the web screens (separate work); limits on a job's CPU, memory, disk and LLM
  use (section 4); a second server running jobs.

**Key design decisions**

| Decision | Why |
|---|---|
| The queue is a database table (`analysis_jobs`), not a separate queue service | Survives restarts and crashes; one truth for the API and the command line; nothing new to run |
| Each project has two queues, called lanes: one for generations, one for Word-file updates. Each lane runs one job at a time. | A quick update never waits behind a long generation, and no project runs two generations at once. Example: while a 3-day generation of v5 runs, a 20-second update of v4 starts at once. |
| At most 2 generations run at the same time on the server, all projects together. The number is a setting. | Limits how many heavy jobs share the server. Example: A and B each run a generation; C's waits until one of them ends. |
| One scheduler thread; a start is one database transaction under a lock; a unique index allows one running job per lane | A job starts exactly once, even with many requests at the same moment |
| A job's state changes only by compare-and-set | A cancel and a start at the same moment cannot both win |
| Each job runs as its own background process, with an alive signal | It outlives an API restart; a dead run is found within 10 minutes |
| Pause stops at a safe point (exit code 75); resume redoes that step | Nothing half-written; no database write per LLM answer, which would slow every run |
| The command line never queues, but obeys the same rules | A script gets its answer at once, and never competes unseen with web jobs |

**A job's states**

| State | Meaning |
|---|---|
| Waiting | In its lane, in order, with its place ("#2") and an estimated start |
| Held | Waiting after a server restart, until a super admin starts or clears it |
| Running | Started by the scheduler, or a command-line run |
| Paused | Stopped at a safe point; keeps its lane, frees its server slot |
| Complete, failed | Ended by the run; a failed job keeps its version for a resume |
| Interrupted | Silent for 10 minutes, or its process gone; the next job starts |
| Cancelled, removed | Stopped while running or paused; taken out while waiting |

**Server settings** (the `jobs` block in `config.local.json`)

| Setting | Default | Meaning |
|---|---|---|
| `maxGenerations` | 2 | Generations running at once, all projects together |
| `startQueuedAfterRestart` | false | false: waiting jobs are held after a restart |
| `pausedDays` | 7 | A job paused this long is cancelled |
| `interruptedAfterMinutes` | 10 | A job silent this long is interrupted |
| `keepFinishedDays` | 90 | How long ended jobs' records are kept |

To deploy: `analyzer.py setup` upgrades the database; the `jobs` block is needed only where the
defaults do not fit.

## 2. Architecture

```
+----------------------------+                        +----------------------------------+
| WEB APP  (browser)         |                        | COMMAND LINE  analyzer.py        |
+-------------+--------------+                        | generate, export, resume,        |
              |  (1) REST: submit, pause, resume,     | reexport                         |
              |      cancel, remove, see queues       | (7) gate before it runs:         |
              |                                       |  - never queues                  |
+-------------+----------------------------------+    |  - refused (exit 2): lane busy,  |
|             |           API SERVER  (FastAPI)  |    |    jobs waiting or server full   |
|  +----------v------+    +--------------------+ |    |  - else recorded as the lane's   |
|  | REST ROUTES     |    | JOB QUEUE SERVICE  | |    |    running job, then runs        |
|  | jobs, queues,   |--->| checks and answers | |    |  - --ignore-queue: super admin   |
|  | versions        |    | records, notifies  | |    +-------+---------------+----------+
|  +-----------------+    +---------+----------+ |            |               |
|                                   | wake       |            |               |
|  +-----------------+    +---------v----------+ |            | (7) runs      | (7) check,
|  | PIPELINE RUNNER |    | SCHEDULER          | |            |               | and record
|  | starts runs,    |<---| one thread         | |            |               |
|  | follows them    |    | every 10 s         | |            |               |
|  +--------+--------+    +--------------------+ |            |               |
+--+--------+------------------------------------+            |               |
   |        ^                                                 |               |
   |        |  (4) start, in the background                   |               |
   |        |  (6) exit code                                  |               |
   |    +---v-------------------------------------------------v------------+  |
   |    | JOB PROCESS  analyzer.py <command> --job-id J  (one per job)     |  |
   |    |  parse -> derive -> views -> export                              |  |
   |    |  sends an alive signal every 60 s; pauses at a safe point        |  |
   |    |  uses the server's CPU, memory and disk, and the LLM gateway     |  |
   |    +-------------------------------+----------------------------------+  |
   |                                    |                                     |
   | (2) insert, (3) claim              | (5) alive signal                    |
   |                                    |                                     |
+--v------------------------------------v-------------------------------------v----------+
| DATABASE  (PostgreSQL)  -- the queue lives here                                        |
|  analysis_jobs  one row per job: lane, status, place, priority, alive signal,          |
|                 pause and resume requests, web or command line                         |
|  job_events     every action: what, who, when                                          |
|  projects       limits per project: 3 generation jobs, 10 update jobs                  |
+----------------------------------------------------------------------------------------+
```

| Step | What happens |
|---|---|
| 1 | A user submits a job, or pauses, resumes, cancels or removes one. |
| 2 | The job queue service checks the request and answers at once: starts now, waits as #2 with an estimate, or refused with the reason. An accepted job is written as waiting, and the scheduler is woken. |
| 3 | Every 10 s, and at once when woken, the scheduler claims the next jobs in one transaction under the queue lock, checking lane, cap and version again: resume requests first; then generations, each project's next one (by priority, then age), the longest wait first, up to the cap; then updates, oldest first, whose version is free. Each minute it also sweeps: a job silent for 10 minutes is interrupted, one paused for 7 days is cancelled. |
| 4 | The pipeline runner starts each claimed job as a background process. |
| 5 | The run sends an alive signal every 60 s, and stops at a safe point when a pause is asked. |
| 6 | The exit code ends the job: 0 or 3 complete, 75 paused, any other failed. The end is recorded, people are told, and the scheduler is woken for the next job. |
| 7 | A command-line run checks the same rules itself: refused when its lane is busy, jobs are waiting or the server is full; otherwise it records itself as the lane's running job and runs. |

## 3. Requirements implemented

All 35 requirements (REQ-JS-01 to 35) are built and tested in the server, the REST API and the command
line. *(screen to do)* marks one that works through the API and still needs its web screen.

**Queues and limits**

- **REQ-JS-01** Two lanes per project: generation (generate, export, resume) and update (Word-file update).
- **REQ-JS-02** One running job per lane per project; a paused generation counts as the running one.
- **REQ-JS-03** One writer per version: a job whose version is being written waits, and says which job is writing it.
- **REQ-JS-04** Limits per project, running and waiting together: 3 generation jobs, 10 update jobs; a project admin can change them. *(screen to do)*
- **REQ-JS-05** Server cap: at most 2 generations at once, all projects together; a paused job does not count.

**Submitting**

- **REQ-JS-06** Three answers: starts now, waits as #N, or refused, naming the jobs in the way. *(screen to do)*
- **REQ-JS-07** Commit, scope, version name and settings checked at submit, and again at start.
- **REQ-JS-08** No duplicates: the version name is reserved at submit; an identical waiting job is not added twice.
- **REQ-JS-09** A request sent twice (a network retry) makes one job.
- **REQ-JS-10** An incremental job picks its baseline when it starts, so the version the job ahead of it made can be its baseline.

**Order**

- **REQ-JS-11** Priority High, Normal or Low for generations, set by a super admin. *(screen to do)*
- **REQ-JS-12** Updates: first come, first served; one whose version is busy is passed and keeps its place.
- **REQ-JS-13** Fair across projects: when a slot frees, the generation that has waited longest starts.

**Reliability**

- **REQ-JS-14** The queue is in the database: a restart loses nothing.
- **REQ-JS-15** A job starts exactly once, in one atomic claim: never twice, never two in a lane, never over the cap.
- **REQ-JS-16** When a job ends, the next one starts by itself, within a minute.
- **REQ-JS-17** A database or LLM outage of a few minutes makes a job wait and retry, not fail. *(manual check to do)*
- **REQ-JS-18** After a restart, waiting jobs are held until a super admin starts or clears them. *(screen to do)*
- **REQ-JS-19** Running jobs carry on through an API restart, and are followed again.
- **REQ-JS-20** A job silent for 10 minutes is interrupted, the project's admins are told, and the next job starts.
- **REQ-JS-21** A failed job frees its slot; its version is kept for a resume when it holds work.

**Pause, resume, cancel, remove**

- **REQ-JS-22** Pause a generation: it stops at the next safe point, within about a minute. Updates are cancelled, not paused. *(screen to do)*
- **REQ-JS-23** Resume redoes the step it stopped in; LLM answers already saved are reused. *(screen to do)*
- **REQ-JS-24** A paused job keeps its lane but frees its server slot; it is cancelled after 7 days.
- **REQ-JS-25** Cancel stops a running or paused job at once and leaves nothing half-made.
- **REQ-JS-26** A waiting job can be removed; its version name is freed. *(screen to do)*

**Command line**

- **REQ-JS-27** The command line never queues a job.
- **REQ-JS-28** It refuses, naming the jobs in the way, when the lane is busy, jobs are waiting or the server is full; a super admin may override with `--ignore-queue`.
- **REQ-JS-29** A command-line run counts as the project's running job: web jobs wait behind it, and it is interrupted if it dies.

**Seeing the queues**

- **REQ-JS-30** Each project's two queues (state, place, estimated start, who, what); a super admin sees every project's. *(screen to do)*
- **REQ-JS-31** The Run dialog says what will happen before you submit. *(screen to do)*
- **REQ-JS-32** Notices when a job starts, ends, fails, is paused, cancelled or interrupted, to the submitter and the project's admins.
- **REQ-JS-33** Every action recorded with who and when.
- **REQ-JS-34** Waiting and run times measured; long waits and stuck jobs flagged. *(screen to do)*
- **REQ-JS-35** Every message in plain words, in the fields the web app already shows.

**Who may do what**

| Action | Super admin | Project admin | Developer, reviewer |
|---|---|---|---|
| Submit a generation | Yes | Yes | No |
| Submit a Word-file update | Yes | Yes | Yes |
| Pause or resume a generation | Yes | Yes | No |
| Cancel a running job, remove a waiting one | Any | Any in the project | Their own |
| Set priority | Yes | No | No |
| Change a project's limits | Yes | Yes | No |
| Start or clear held jobs | Yes | No | No |

**Verified by** unit and API tests on SQLite and PostgreSQL, real runs paused, resumed and cancelled in
each phase, and an end-to-end tool through the REST API and the command line: 40 scenarios, a result for
every requirement. All pass here; one office re-run with the real LLM is pending.

## 4. Improvements: resource management and segregation

**Proposed, not built; for decision.** Today projects are kept apart by scheduling only: one running
job per lane, limits per project, the server cap and fair order. What a running job uses is measured,
but not limited.

**Gaps today**

| Resource | Gap | Risk |
|---|---|---|
| CPU | No limit or priority per job; Word-file updates have no server cap | Many jobs at once slow every project, and the API |
| Memory | No limit per job; no free-memory check before a start | One large parse runs the server out of memory; the system may kill another project's job, the API or the database |
| Disk | No free-space check; no quota per project | A full disk makes every project's jobs fail |
| LLM gateway, GPU | The rate limit is per process, not per server; no share or budget per project | Jobs together exceed the gateway's limit; refused calls slow runs and leave plain fallback labels |

**Recommended approach**

- **One container per job** (Docker or Podman on our two servers), not one container for all jobs:
  limits then protect projects from each other, not only the server from the application.
- **Start a job only when its size fits.** Each job's CPU, memory and disk size comes from our
  estimation data, corrected by each run's measured peak. A small worker on each server claims from the
  database queue only the jobs that fit, after a reserve for the API, the database and the OS. Size
  fields are named as Kubernetes names them (`cpu`, `memory`, `ephemeral-storage`).
- **A fence around each job:** a memory limit equal to its size, with no swap; a CPU share, larger for
  the API; a scratch-disk limit. When memory runs short, job containers are stopped first, never the API
  or the database.
- **One LLM proxy** in front of the gateway, used by every job: one rate limit for both servers,
  projects taking turns, Word-file updates before generations, a daily budget per project, back-off on
  refusals; it holds the gateway credentials. Jobs change only `llmServer.baseUrl`.
- **Disk:** scratch space per job, deleted when it ends; a quota per project for Word files and
  pictures; the database on its own disk; log rotation; a free-space floor and an alert at 80–90 % full.
- **Fairness between projects:** a resource cap per project, order by recent use as well as waiting
  time, and a usage view for super admins.
- **Fix before the first container run:** `parseWorkers: "auto"` must count the container's CPUs, not
  the server's; Chrome needs a larger `/dev/shm` than Docker's 64 MB default; command-line runs become
  job containers too.

**Plan**

| Step | What |
|---|---|
| 1 | After this release, three safety nets: a server cap for updates (`jobs.maxUpdates`), a free-disk floor (no start below it, admins told), lower OS priority for job processes |
| 2 | The LLM proxy, the shared resource that hurts most often. Until then, set `llmServer.rateLimitSeconds` with the cap in mind |
| 3 | One container per job, started when its size fits; can run beside step 2. If both servers run jobs, Word files, pictures and logs need shared storage first |
| 4 | Fairness: resource caps per project, order by recent use, disk quotas, the usage view |

**Kubernetes and Kueue**

| Need | Docker or Compose alone | Our scheduler + Docker (recommended) | Kubernetes + Kueue |
|---|---|---|---|
| Memory and CPU limit per job | Yes | Yes | Yes |
| A job waits until there is room | No: it starts at once | Built | Yes |
| Starts only when its size fits | No | To add (small) | Yes |
| Limits and fair order per project | No | Job counts built; resource caps to add | Yes |
| Borrowing idle shares, stopping jobs to rebalance | No | Not planned | Yes |
| Our rules: lanes, one writer per version | No | Built | No: they stay ours |
| LLM call limits | No | LLM proxy, to add | No: needs the proxy too |

- **Not Kueue now.** Kubernetes needs three control nodes for failover, more than two servers justify.
  Kueue decides only room and order: it knows none of our rules, does nothing for LLM calls, and books a
  job's peak memory for its whole run.
- **Move to Kueue, under our scheduler, when** we need borrowing or stopping jobs to rebalance,
  big-memory or GPU servers sit beside normal ones, there are three or more servers or several clusters,
  or a Kubernetes cluster is provided. The change is in one place: the scheduler's launch creates a
  Kubernetes job instead of a local process.

---

**In the repository:** `docs/spec/JOB_SCHEDULING_SPEC.md` (requirements) ·
`docs/design/JOB_SCHEDULING_DESIGN.md` (full design) · `docs/spec/JOB_SCHEDULING_API_SPEC.md` (HTTP
contract) · `docs/planning/JOB_SCHEDULING_SUMMARY.md` (status per requirement).
