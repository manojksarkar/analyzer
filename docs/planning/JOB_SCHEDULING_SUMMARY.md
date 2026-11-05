# Job Scheduling — Design Summary

What is built and what is left, in key points. For review. The requirements in full:
[JOB_SCHEDULING_SPEC](../spec/JOB_SCHEDULING_SPEC.md); how it is built:
[JOB_SCHEDULING_DESIGN](../design/JOB_SCHEDULING_DESIGN.md).

**Status 2026-11-05:** all 35 requirements are built and tested in the server, the API and the command
line. What is left: the web screens, two small fixes and the release ([section 4](#4-to-be-implemented)).
Branch `feat/job-scheduling`, not yet merged into `develop`.

## 1. What it does

- **Jobs wait instead of being refused.** A second generation of a project used to fail with "already
  running"; now it waits its turn and starts by itself.
- **Two queues per project** (generation, Word-file update), a limit per project, a cap for the server.
- **Pause, resume, cancel, remove.** Pause stops at a safe point; cancel leaves nothing half-made.
- **Survives restarts and crashes.** The queue lives in the database; a job that stops answering is
  found, and the next one starts.
- **The command line follows the same rules** as the web app.
- **Five server settings**, with defaults: 2 generations at once; waiting jobs held after a restart; a
  paused job cancelled after 7 days; a job silent for 10 minutes interrupted; records kept 90 days.

## 2. Requirements implemented

**Done** = built and tested. **Screen to do** = works through the API; its web screen is in
[section 4](#4-to-be-implemented).

**Queues and limits**

| REQ-JS | Key point | Status |
|---|---|---|
| 01 | Two queues per project: generation, and Word-file update | Done |
| 02 | One running job per queue per project; a paused one counts | Done |
| 03 | One job writes a version at a time; the others wait and say why | Done |
| 04 | Per-project limits: 3 generation jobs, 10 update jobs (running + waiting) | Done · screen to do |
| 05 | Server cap: 2 generations at once, all projects together | Done |

**Submitting**

| REQ-JS | Key point | Status |
|---|---|---|
| 06 | Three answers: starts now, waits as #N, or refused with the reason | Done · screen to do |
| 07 | Commit, scope, name and settings checked at submit, and again at start | Done |
| 08 | No duplicate jobs; a version name is reserved | Done |
| 09 | A request sent twice makes one job | Done |
| 10 | An incremental job picks its baseline when it starts, not when submitted | Done |

**Order**

| REQ-JS | Key point | Status |
|---|---|---|
| 11 | Priority High / Normal / Low, set by a super admin | Done · screen to do |
| 12 | Updates: first come, first served | Done |
| 13 | Fair across projects: the longest wait starts first | Done |

**Reliability**

| REQ-JS | Key point | Status |
|---|---|---|
| 14 | The queue is in the database: a restart loses nothing | Done |
| 15 | A job starts exactly once, in one atomic step | Done |
| 16 | When a job ends, the next starts by itself | Done |
| 17 | A short database or LLM outage makes a job wait, not fail | Done · manual check to do |
| 18 | After a restart, waiting jobs are held until a super admin releases them | Done · screen to do |
| 19 | Running jobs carry on through a server restart | Done |
| 20 | A job silent for 10 minutes is interrupted; the next one starts | Done |
| 21 | A failed job frees its place; its version is kept for a resume | Done |

**Pause, resume, cancel, remove**

| REQ-JS | Key point | Status |
|---|---|---|
| 22 | Pause a generation: it stops within a minute | Done · screen to do |
| 23 | Resume redoes the step it stopped in; LLM answers already saved are reused | Done · screen to do |
| 24 | A paused job keeps its place in the project but frees its server slot; cancelled after 7 days | Done |
| 25 | Cancel stops at once and leaves nothing half-made | Done |
| 26 | A waiting job can be removed | Done · screen to do |

Who may do what (super admin, project admin, developer and reviewer): as agreed in the spec — Done.

**Command line**

| REQ-JS | Key point | Status |
|---|---|---|
| 27 | The command line never queues a job | Done |
| 28 | It refuses when the queue is busy or the server is full; a super admin may override | Done |
| 29 | A command-line run counts as the project's running job | Done |

**Seeing the queues**

| REQ-JS | Key point | Status |
|---|---|---|
| 30 | Each project's queues; a super admin sees every project's | Done · screen to do |
| 31 | The Run dialog says what will happen before you submit | Done · screen to do |
| 32 | Notices when a job starts, ends, fails, is paused, cancelled or interrupted | Done (shown in today's notification bell) |
| 33 | Every action recorded with who and when | Done |
| 34 | Waiting and run times measured; stuck jobs flagged | Done · screen to do |
| 35 | Every message in plain words, in fields the web app already shows | Done |

## 3. How it was verified

- **Automated tests** on every change: unit and API tests (SQLite, and PostgreSQL for "starts exactly
  once"), and real runs paused, resumed and cancelled in each phase.
- **End-to-end test tool** through the REST API and the command line: 40 scenarios in three modes —
  normal (14), complex (16: restarts, killed processes, many requests at once, each server setting) and
  command line (10). Its report gives every requirement a result.
- **Latest results:** every scenario passes except the pause test with the real LLM, which failed in
  the office on 30 Oct. Its main cause (flowchart pictures drawn differently in a second run) was fixed
  the same day and passes here; the office re-run is pending.
- Defects found by the code review and the test tool are fixed, each with a test; one small one is open
  (section 4).

## 4. To be implemented

**Web screens** (Manoj; the API and its contract,
[JOB_SCHEDULING_API_SPEC](../spec/JOB_SCHEDULING_API_SPEC.md), are ready):

- Run dialog: "starts now", "waits as #2" or "refused", before submitting (REQ-JS-31).
- Project queue card: running and waiting jobs, Pause, Resume, Remove; priority for super admins
  (REQ-JS-11, 22, 23, 26, 30, 34).
- Queues page for super admins: every project, server cap in use, held jobs with start all / clear
  (REQ-JS-18, 30).
- Project settings: the two limits (REQ-JS-04).
- Versions list: a waiting job's version shown as "Waiting (#2)"; the old "already running" errors
  replaced by the new answers (REQ-JS-06).

**Small fixes**

- On SQLite only, two submits at the same instant can overfill a queue by one job. PostgreSQL, used in
  production, is not affected.
- Two runs of one commit can word a few LLM-written sentences differently (seen once in the office pause
  test). Likely cause: how the LLM cache keys a description; to confirm and fix.

**Checks to finish**

- REQ-JS-17 by hand: stop the database for 2 minutes during a run; the run must carry on.
- Office re-run of the pause test with the real LLM, after the 30 Oct fix.

**Release**

- Merge `feat/job-scheduling` into `develop`. On each server: a database upgrade (`analyzer.py setup`)
  and, if the defaults do not fit, the `jobs` settings.

**Later, not in this release**

- A second server running jobs. Ready now: the queue in the database, the start-once rule. Still to
  design: Word files, logs and checkouts reachable from both servers.
