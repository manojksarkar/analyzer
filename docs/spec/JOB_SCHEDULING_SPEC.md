# JOB_SCHEDULING Spec — queues, limits, pause and resume

Update this doc first when changing how jobs wait, start, pause or stop; then code + tests. Status
2026-10-21: requirements and design ([JOB_SCHEDULING_DESIGN](../design/JOB_SCHEDULING_DESIGN.md)) agreed
with the user; being built on `feat/job-scheduling`; the web screens are Manoj's. Scope: **one server
now**, built so a second server can join later ([Later](#later)).

**Outline:** [Terms](#terms) · [Lanes](#lanes) · [Limits and cap](#limits-and-cap) ·
[Submitting](#submitting) · [Order](#order) · [The queue](#the-queue) ·
[Restarts and failures](#restarts-and-failures) · [Pause, resume, cancel, remove](#pause-resume-cancel-remove) ·
[Who may do what](#who-may-do-what) · [CLI](#cli) · [Seeing the queues](#seeing-the-queues) ·
[What changes from today](#what-changes-from-today) · [Limitations](#limitations) · [Later](#later) ·
[Open items](#open-items)

## Terms

| Term | Meaning |
|---|---|
| Job | One run that writes a version: a generation, a resume, an `export` of new components, or a Word-file update |
| Lane | Where a job waits: **generation** or **update** |
| Limit | How many jobs one project may hold in a lane: the running (or paused) one plus those waiting |
| Cap | How many generations may run at once on the server, all projects together |
| Held | Waiting jobs that start only when a super admin releases them |
| Interrupted | A running job that stopped sending its alive signal |

---

## Lanes

### REQ-JS-01 — Two lanes per project
**Generation:** generate (full or incremental), resume, `export` (the Word files of components a version
does not have yet). **Update:** Word-file updates after review corrections. Downloading Word files that
already exist is not a job.
**Verification:** each kind of job waits in its lane.

### REQ-JS-02 — One running job per lane per project
A project runs at most one generation and one update at the same time. A paused generation counts as the
running one.
**Verification:** a second generation of one project waits; an update of another version starts at once.

### REQ-JS-03 — One writer per version
A job also needs its version free: a job whose version another job is writing waits, and says why --
"waiting: v4 is being written by the export of Lib, started Tue 10:00". This happens only in staged
generation (one version made by several jobs). A paused job keeps its version: the others wait until it
is resumed and ends, or is cancelled. Corrections in the components a running job writes are refused, as
today ([WORD_FILE_UPDATES §4.6](../design/WORD_FILE_UPDATES.md)); others go through.
**Verification:** an update of v4 waits while an `export` into v4 runs, and starts when it ends.

---

## Limits and cap

### REQ-JS-04 — Per-project limits
Two fields per project, stored with it in the database: **generation limit**, default 3 (1 running or
paused + 2 waiting), and **update limit**, default 10 (1 running + 9 waiting). A project admin or super
admin changes them; each change is recorded. Lowering a limit cancels nothing already accepted.
**Verification:** with limit 3 and 3 jobs held, a 4th is refused; lowered to 2, the 3 jobs stay.

### REQ-JS-05 — Server cap for generations
At most `jobs.maxGenerations` generations run at once on the server, all projects together (default 2,
`config.local.json`). It is read from that file only: the `JOB_MAX_CONCURRENCY` environment variable is
no longer read. A paused job does not count. Updates have no server cap.
**Verification:** cap 2, three projects each submit a generation: two run, the third starts when one ends.

---

## Submitting

### REQ-JS-06 — Three answers
A submission starts now, waits (with its position), or is refused because the lane's limit is reached --
the refusal names the jobs running and waiting.
**Verification:** each answer, from the web app and the API.

### REQ-JS-07 — Checked twice
At submit -- commit, scope, version name, configuration -- so a waiting job does not fail hours later on a
typo; and again when it starts.
**Verification:** an unknown commit is refused at submit; a branch deleted while the job waits fails it at
start, and the next job starts.

### REQ-JS-08 — No duplicates
The version name is reserved at submit and freed when the job is removed. A generation identical to one
waiting (same commit, scope and settings) is refused, naming that one. An update identical to one waiting
(same version, same components) is not added: "already queued".
**Verification:** two submissions with one version name: the second is refused; the same update twice:
one job.

### REQ-JS-09 — A retried submission is one job
A request sent again (a network retry) returns the job it made the first time.
**Verification:** the same request id twice: one job.

### REQ-JS-10 — Baseline chosen at start
A waiting incremental generation chooses its baseline when it starts, not when it was submitted, so the
version the job ahead of it made can be its baseline.
**Verification:** v5 submitted while v4 runs: v5's baseline is v4.

---

## Order

### REQ-JS-11 — Priority in the generation lane
High, Normal or Low; default Normal. Only a super admin sets or changes it. It orders the jobs of one
project: priority first, then the oldest.
**Verification:** a High job submitted after two Normal ones starts first.

### REQ-JS-12 — Updates first come, first served
The update lane has no priority. An update whose version is busy ([REQ-JS-03](#req-js-03--one-writer-per-version))
is passed by the next one, and keeps its place.
**Verification:** updates start in the order they were submitted; one whose version an export writes is
passed by an update of another version.

### REQ-JS-13 — Fair across projects
When a server slot frees, the generation that has waited longest, across projects, starts. Example: cap 2,
A and B run; C has waited since 10:00, A's next job since 10:30. A finishes: C starts.
**Verification:** the example above.

---

## The queue

### REQ-JS-14 — In the database
Jobs, their states and their order are kept in the database -- the PostgreSQL primary, never read from a
replica -- so a restart loses nothing.
**Verification:** restart the server with jobs waiting: they are all there, in order.

### REQ-JS-15 — One start per job
Starting a job is one atomic claim in the database: never the same job twice, never two running in one
project's lane, never over the cap -- also when a second server joins later.
**Verification:** two schedulers claiming at the same moment start one job.

### REQ-JS-16 — The next job starts by itself
When a job finishes, fails, is cancelled or is interrupted, the next one that may run starts -- unless
the queues are held ([REQ-JS-18](#req-js-18--held-after-a-restart)).
**Verification:** a job ends; the next starts within a minute, with nobody acting.

### REQ-JS-17 — A short outage waits
A database or LLM gateway outage of a few minutes makes a job wait and retry, not fail.
**Verification:** stop the database for 2 minutes during a run: the run carries on.

---

## Restarts and failures

### REQ-JS-18 — Held after a restart
After a server restart, waiting jobs are held. A super admin starts all, clears all, or clears some and
starts the rest -- for one project or for all. `jobs.startQueuedAfterRestart: true` in
`config.local.json` starts them by themselves instead (default false). A job submitted while the queues
are held is held too.
**Verification:** restart with jobs waiting: none starts; "start all" starts them in order; a job
submitted before that is held.

### REQ-JS-19 — Running jobs carry on
A job running when the web server restarts carries on -- it is a process of its own, as today -- and is
followed again.
**Verification:** restart the web server during a run: the run ends normally and its job says so.

### REQ-JS-20 — A job that stops answering
A running job sends an alive signal every minute. Silent for 10 minutes: it is **interrupted**, its slot
is freed, the next job starts, and the project's admins are told; the user starts it again, and it joins
the back of its lane at Normal priority. Example: J1
crashes at 3:00 with J2 waiting; at 3:10 J1 is interrupted and J2 starts. A server that follows the run
and sees its process end unfinished interrupts it at once. Moving a job to another server is not handled.
**Verification:** kill a job's process: within 10 minutes it is interrupted and the next job runs.

### REQ-JS-21 — A failed job
Frees its slot, the next job starts, and its version is kept for a resume when it holds work (a stored
parse or more), as today; a version that failed before that is deleted, its name freed.
**Verification:** a job that fails: the next starts; the failed version can be resumed.

---

## Pause, resume, cancel, remove

### REQ-JS-22 — Pause, generations only
A running generation pauses at the nearest safe point: it starts no new LLM call, the calls already sent
finish, and the process stops. Updates take seconds to minutes and are not paused; they can be
cancelled.
**Verification:** pause during descriptions: it stops within a minute.

### REQ-JS-23 — Resume
Resume runs again the step the job stopped in -- the parse, the model, or the components not finished --
not from the exact item. LLM answers already saved come back from the cache; one not saved yet is asked
again. Nothing is left out: a step counts as done only when it has finished, so a step cut short is
always done again ([Limitations](#limitations)).
**Verification:** pause and resume a run: the same Word files as a run not paused; the only extra LLM
calls are for answers not saved when it paused.

### REQ-JS-24 — A paused job keeps its place
It keeps the project's generation slot -- the next waits until it is resumed or cancelled -- but does not
count against the server cap. Resumed, it takes the first free server slot, before waiting generations.
Paused time is not counted in its elapsed time or estimate. After `jobs.pausedDays` paused (default 7;
a server may set more, e.g. 15) it is cancelled, with notice -- as any cancel
([REQ-JS-25](#req-js-25--cancel)): a version that never finished is deleted.
**Verification:** pause a job: the project's next generation waits, another project's starts.

### REQ-JS-25 — Cancel
A running or paused job stops at once. As today, a version that never finished is deleted and its
name freed; a version that already had Word files keeps them. To stop and keep the work, pause. Nothing
half-made is left: a deleted version takes all its data and its folder with it, whichever phase it had
reached; in a kept version, what the job had not finished still shows as not done (out of date, or not
generated), and the components it had finished are complete.
**Verification:** cancel a first generation in each phase: the process stops within seconds and nothing
of the version is left; cancel a paused one: the same; cancel an update half way: the components it had
not finished still show out of date.

### REQ-JS-26 — Remove
A waiting job can be removed; waiting jobs are not paused. Its version name is freed.
**Verification:** remove a waiting job: it is gone, its name can be used again.

---

## Who may do what

| Action | Super admin | Project admin | Developer, reviewer |
|---|---|---|---|
| Submit a generation | ✓ | ✓ | — |
| Submit a Word-file update | ✓ | ✓ | ✓ |
| Pause or resume a generation | ✓ | ✓ | — |
| Cancel a running job, remove a waiting one | ✓ any | ✓ any in the project | ✓ their own |
| Set priority | ✓ | — | — |
| Change a project's limits | ✓ | ✓ | — |
| Start or clear held jobs | ✓ | — | — |

**Verification:** a reviewer can cancel their own update and not another's.

---

## CLI

### REQ-JS-27 — No queue in the CLI
The scheduler lives in the web server. The CLI never queues a job and has no queue commands.
**Verification:** none of `analyzer.py`'s commands adds a waiting job.

### REQ-JS-28 — The CLI refuses what would break the rules
`generate`, `export` and `resume` (generation lane) and `reexport` (update lane) refuse, naming the jobs in
the way, when the project has a job running in that lane, when jobs are waiting in it (held or not), or
when the server cap is full. A super admin's `--ignore-queue` starts the run anyway (not `--force`:
`reexport --force` already means "export past the stale-views guard").
**Verification:** each of the three refusals; `--ignore-queue` starts the run.

### REQ-JS-29 — A CLI run is the project's running job
A CLI run records itself where web jobs are recorded and sends the same alive signal: the scheduler waits
for it, starts the next job when it ends, and marks it interrupted if it dies. The web app does not cancel
it; the developer who started it does.
**Verification:** a CLI run in progress: a web submission waits behind it and starts when it ends.

---

## Seeing the queues

### REQ-JS-30 — One queue or all
For each job: lane, state (running, paused, waiting, held), position, estimated start, who submitted it,
and what it makes (version, commit, scope). A project page shows its two queues; a super admin sees every
project's.
**Verification:** with jobs in two projects, a super admin sees both, a project admin only theirs.

### REQ-JS-31 — Before submitting
The Run dialog says what will happen: "starts now", "waits as #2" or "refused: the limit is reached".
**Verification:** the three messages.

### REQ-JS-32 — Told when it changes
A notice when a job starts, finishes, fails, is paused, cancelled, interrupted or cancelled after its
paused days -- to the submitter and the project's admins.
**Verification:** each event reaches the submitter.

### REQ-JS-33 — Recorded
Who submitted, paused, resumed, cancelled, removed, changed a priority or a limit, started or cleared held
jobs, and when.
**Verification:** each action appears in the record with its user and time.

### REQ-JS-34 — Measured
Queue length, waiting time and run time per phase; long waits and stuck jobs flagged. Finished jobs'
records are kept for `jobs.keepFinishedDays` (default 90).
**Verification:** a job's waiting and run times are shown; a job stuck past its limit is flagged.

### REQ-JS-35 — Messages where the web app already shows them
Every refusal, wait, warning and failure says, in plain words, what happened and what to do next -- in
the field the web app already shows, never a new one: a refused request in its error's `message` (with
its `code`); a submit's answer in its `message`; a job's state -- waiting and why, held, pausing,
paused until when -- in its `current_activity`; how a job ended in its `error_message`, a headline line
then `- ` lines for the reasons; a notice in the notification's `message`.
**Verification:** each refusal, wait and ending of this spec shows its message in the web app with no
change to the web app's error handling.

---

## What changes from today

| Today | With this spec |
|---|---|
| A second generation is refused (409 `JOB_ALREADY_RUNNING`) | it waits ([REQ-JS-06](#req-js-06--three-answers)) |
| A second update of a version is refused (409 `REEXPORT_RUNNING`), and so is a busy version (409 `VERSION_BUSY`) | it waits ([REQ-JS-03](#req-js-03--one-writer-per-version)) |
| `JOB_MAX_CONCURRENCY` environment variable, counted per API process | `jobs.maxGenerations` in `config.local.json`; the variable is no longer read |
| The `pause_after_phase1` job option, kept in memory, used by no screen | removed; [REQ-JS-22](#req-js-22--pause-generations-only) |
| Running and waiting jobs counted in the API process's memory | in the database ([REQ-JS-14](#req-js-14--in-the-database)); job logs stay as today until two servers run jobs |
| A version cannot be deleted while any job of its project is active | only while one runs or is paused, or a waiting job needs that version |

**Corrections across versions do not change.** A version generated from a baseline starts with the
baseline's corrections wherever the code is unchanged
([REVIEW_UPDATE_SPEC REQ-VR-01](REVIEW_UPDATE_SPEC.md#req-vr-01--unchanged-code-keeps-the-human-text)); a
correction made after that start stays in its own version; a full generation starts with none
([REQ-VR-03](REVIEW_UPDATE_SPEC.md#req-vr-03--a-full-regeneration-uses-fresh-llm-text-and-keeps-the-overrides)).

---

## Limitations

- Resume repeats the step it stopped in -- mostly the parse, which for a large layer can be hours -- and
  the LLM calls whose answers were not saved yet. Saving progress inside a step is a later improvement.
- In staged generation, an update of a version waits while another job writes that version
  ([REQ-JS-03](#req-js-03--one-writer-per-version)). Accepted: an `export` is not expected to run long.
- A job whose server is lost is interrupted; it is not moved to another server.
- No server cap for updates: many projects updating at once start many processes. A cap can be added later
  as a setting.

## Later

Designed when two servers run jobs: Word files, pictures and checkouts reachable from both servers (today
on the disk of the server that made them); a cap for the whole solution beside each server's; one server
restarting while the other keeps scheduling. This spec already keeps the queue in the database and makes
starting a job one atomic claim ([REQ-JS-15](#req-js-15--one-start-per-job)), so the second server can join
without changing it.

## Open items

None. The five points left open on 2026-10-19 were confirmed by the user the same day.
