# Job scheduling — HTTP contract

How jobs wait, start, pause, resume and end, and how a project's queues are read and changed, over
HTTP — what the web app's screens are built on. Update this file first when the contract changes,
then the code and the tests.
Requirements: [JOB_SCHEDULING_SPEC](JOB_SCHEDULING_SPEC.md) (`REQ-JS-` ids) · design (why, rules,
the screens to build): [JOB_SCHEDULING_DESIGN](../design/JOB_SCHEDULING_DESIGN.md) §13–§14.

All paths are under `/api/v1`. `P` = `/projects/{project_id}`, `V` = `P/versions/{version_id}`.
Errors use the API's envelope: `{"detail": {"code", "message", "status", …}}`.

## 1. States

| `status` | Label | Set by |
|---|---|---|
| `held` | Held after a restart | a server restart (unless `jobs.startQueuedAfterRestart`); a submit to a held queue |
| `queued` | Waiting | a submit; a super admin releasing held jobs |
| `running` | Running | the scheduler's claim; a command-line run |
| `paused` | Paused | the run, at a safe point after a pause was asked |
| `complete` | Complete | the run's end |
| `failed` | Failed | the run's end |
| `interrupted` | Interrupted | silent for `jobs.interruptedAfterMinutes`, or its process gone, or a server that stopped mid-run |
| `cancelled` | Cancelled | a cancel of a running or paused job; paused for `jobs.pausedDays` |
| `removed` | Removed | a cancel of a waiting or held job; a super admin clearing held jobs |

A project has two **lanes**: `generation` (generate, export, resume) and `update` (Word-file updates).
Each runs one job at a time — `running`, or `paused`, which keeps its place. A lane's **limit** counts
its running, paused, waiting and held jobs (defaults 3 and 10). The server runs at most
`jobs.maxGenerations` generations at once, every project's together; a paused one is not counted.

## 2. Shapes

**Job** — `GET P/jobs/{job_id}`, `GET P/jobs/current` and every action's answer, as `{"job": Job}`.
The fields from before the queue are unchanged, except `started_at`: `null` while the job waits.
Added:

```json
{
  "lane": "generation", "priority": "normal", "submitted_at": "2026-10-21T09:12:03.120000+00:00",
  "origin": "web", "runner": "api host1 pid 4120", "heartbeat_at": "2026-10-21T09:40:00+00:00",
  "pause_requested": false, "resume_requested": false, "paused_at": null,
  "position": null, "estimated_start": null, "flags": []
}
```

- `priority` — `high` | `normal` | `low`; only the generation lane orders by it.
- `submitted_at` — when it took its place: the order of a lane.
- `origin` — `web` | `cli`. A `cli` job is a command-line run: `runner` says who and where
  (`"cli dev@host2 pid 7"`); the web app cannot pause or cancel it (`CLI_RUN`).
- `position` — 1-based place among the lane's waiting jobs; `null` unless `queued` or `held`.
- `estimated_start` — when a `queued` job should start; `null` when it cannot be told (a paused job
  ahead, a held queue, a kind of job never run before).
- `flags` — `long_wait` (waiting more than a day), `stuck` (running, no progress for 30 minutes):
  shown, never acted on.

**Brief** — a job as an answer or a queue lists it:

```json
{"job_id": "job3f2a9c1e", "kind": "generation", "what": "generate v4.1", "status": "running",
 "version_id": "ver1a2b3c4d", "version_tag": "v4.1", "priority": "normal",
 "submitted_at": "…", "started_by": "u1", "origin": "web", "runner": "api host1 pid 4120"}
```

`kind`: `generation` | `export` | `resume` | `update` | `rebuild`. `what`: the job in words — "generate
v4.1", "export into v4 (Layer1.Can)", "update of v4 (Layer1.Math)".

**Answer** — what every submit returns beside its own fields:

```json
{"job_id": "job3f2a9c1e", "status": "queued", "position": 2,
 "estimated_start": "2026-10-21T12:40:00+00:00",
 "ahead": [{"…": "Brief"}, {"…": "Brief"}],
 "message": "Waits as #2 — about 3 h"}
```

| `status` | `message` |
|---|---|
| `running` | `Starts now` |
| `queued` | `Waits as #2 — about 3 h` · `Waits for v4` (another job writes the version) · `Waits for a free server slot` |
| `held` | `Held: the queue is held after a restart; a super admin starts it` |

`ahead` — the job holding the lane, then the waiting jobs before this one.

## 3. Messages — one field per place (REQ-JS-35)

Every message is a sentence for the person, in a field the web app already reads; none is new.

| What | Field | Example |
|---|---|---|
| a refused request | `detail.message`, with `detail.code`; the jobs in the way as extra fields | `Refused: the generation queue of this project is full — 3 of 3 places are taken (…)` |
| a submit's answer | `message` | `Waits as #2 — about 3 h` |
| a waiting or running job | `current_activity`, `activity_detail` | `Waiting as #2 — about 3 h` / `After: generate v4; export into v4 (Lib)` · `Waiting for v4` / `Export into v4 (Lib) is writing it` · `Pausing at the next safe point…` · `Paused — cancelled on 28 Oct unless resumed` |
| how a job ended | `error_message` — a headline, then `- ` lines | `Interrupted: no sign of life for 10 minutes — its process stopped, or its machine did.`<br>`- Start it again: it joins the back of its lane.` |
| a notice | `notifications.message` | `Finished: generate v4.1.` |

## 4. Routes

| # | Route | Who | Does |
|---|---|---|---|
| Q1 | `POST P/jobs` | project admin | Submit a generation |
| Q2 | `POST V/documents/generate` | project admin | Submit an export of components into a version |
| Q3 | `POST V/resume` | project admin | Submit a resume of a version whose run stopped |
| Q4 | `POST V/reexport` | member (scope rules of WORD_FILE_UPDATES) | Submit a Word-file update |
| Q5 | `POST P/jobs/{job_id}/pause` | project admin | Ask a running generation to pause |
| Q6 | `POST P/jobs/{job_id}/resume` | project admin | Resume a paused job |
| Q7 | `POST P/jobs/{job_id}/cancel` | its submitter, project admin | Cancel a running or paused job; remove a waiting or held one |
| Q8 | `PATCH P/jobs/{job_id}` | super admin | A waiting generation's priority |
| Q9 | `GET P/queues` | member | The project's two lanes |
| Q10 | `GET P/queues/preview?lane=` | member | What a submit to the lane would get now |
| Q11 | `GET P/queues/events` | project admin | The record, newest first |
| Q12 | `PATCH P/job-limits` | project admin | The project's two limits |
| Q13 | `GET /queues` | super admin | Every project's queues |
| Q14 | `POST /queues/held` | super admin | Start, clear, or clear some and start the rest of the held jobs |
| Q15 | `DELETE V` | project admin | Delete a version — refused while jobs need it |

A super admin is a project admin of every project. Every submit (Q1–Q4) takes an **`Idempotency-Key`**
header: the same key again answers the job the first request made, with its answer as it is now
(REQ-JS-09).

### Q1 `POST P/jobs` — 202

Request as before (`commit_sha`, `version_tag`, `reference_version_id`, `scope`, `mode`, `no_llm`, …),
plus `priority` (`high` | `normal` | `low`; anything but `normal` is a super admin's, else 403).
Answer: the Answer, plus `"job": Job`.

| Status | `code` | When |
|---|---|---|
| 400 | `VALIDATION_ERROR`, `INVALID_SCOPE` | as before |
| 403 | `FORBIDDEN` | a priority from someone not a super admin |
| 409 | `NO_ARCHITECTURE`, `VERSION_EXISTS` | as before |
| 409 | `LANE_FULL` | the lane is at its limit; `running`, `waiting`: Briefs; `limit`, `lane` |
| 409 | `DUPLICATE_JOB` | the same generation (commit, mode, scope, baseline, settings) already waits; `job_id` |

The version's name is taken at submit: a waiting job's draft version is listed with the version
(design §14 — "Waiting (#2)", never the default selection). Removing the job frees the name.

### Q2 `POST V/documents/generate` — 202

As before: `{job_id, status, version_id, components, skipped, added_layers}`, plus the Answer's
`position`, `estimated_start`, `ahead`, `message`. Refusals as before, and `LANE_FULL`; another job of
the project or of the version is a wait, no longer `EXPORT_RUNNING`, `RUN_ACTIVE` or `VERSION_BUSY`.

### Q3 `POST V/resume` — 202

`{job_id, status, version_id}` plus the Answer's fields. A web generation that failed or was
interrupted is submitted again — the same job, at the back of its lane, Normal priority; otherwise a
job of its own (`kind: resume`). 409: `NOTHING_TO_RESUME`; `RUN_ACTIVE` (a job of the version waits,
runs or is paused — `job_id`); `VERSION_BUSY` (a process writes the version: it has not stopped);
`NO_BACKGROUND_RUNS`; `LANE_FULL`.

### Q4 `POST V/reexport`

As WORD_FILE_UPDATES §4.1, with the update lane's answers:

- **202** — a new job: `{job_id, status, version_id, scope, components, joined: false,
  already_queued: false, position, estimated_start, ahead, message}`.
- **200** — an update of the version running or waiting already writes these components: its
  `job_id`, `joined: true`; `already_queued: true` when it waits (`message`: `Already queued: …`).
- **200** — `{"job_id": null, "status": "up_to_date", …}`: nothing is out of date.

Another update running in the project, or another job writing the version, is a wait — no longer
`REEXPORT_RUNNING` or `VERSION_BUSY`. 409 `LANE_FULL`; the other refusals as before.

### Q5 `POST P/jobs/{job_id}/pause` — 200 `{"job": Job}`

The job's `pause_requested` becomes true and `current_activity` `Pausing at the next safe point…`; the
run stops at its next safe point and the job becomes `paused`, its place kept (REQ-JS-22). A second
ask changes nothing. 409 `NOT_PAUSABLE` (an update — it takes minutes; a waiting job; one not
running), `CLI_RUN`.

### Q6 `POST P/jobs/{job_id}/resume` — 200 `{"job": Job}`

`resume_requested` true; the job takes the next free server slot, before any waiting generation, and
redoes the step it stopped in (REQ-JS-23, 24). 409 `NOT_PAUSED`.

### Q7 `POST P/jobs/{job_id}/cancel` — 200 `{"job": Job}`

By state (REQ-JS-25, 26): `queued` or `held` → `removed` (a generation's draft version is deleted, its
name free); `running` → `cancelled`, the run stopped; `paused` → `cancelled`. A version that never
finished is deleted; one with Word files keeps them. 403 `FORBIDDEN` (not your job, not an admin);
409 `JOB_FINISHED` (it has ended: `detail.message` says how), `CLI_RUN`.

### Q8 `PATCH P/jobs/{job_id}` — 200 `{"job": Job}`

Body `{"priority": "high" | "normal" | "low"}`. 403 `FORBIDDEN`; 409 `NOT_WAITING` (not a waiting
generation); 422 `INVALID_PRIORITY`.

### Q9 `GET P/queues` — 200

```json
{
  "project_id": "p1", "held": false,
  "cap": {"max_generations": 2, "running_generations": 1},
  "lanes": {
    "generation": {
      "limit": 3,
      "active": [{"…": "Brief", "current_activity": "…", "…queue fields of Job": "…"}],
      "waiting": [{"…": "Brief", "current_activity": "…", "activity_detail": "…",
                   "position": 1, "estimated_start": "…", "flags": []}]
    },
    "update": {"limit": 10, "active": [], "waiting": []}
  }
}
```

`active` holds the lane's running or paused job — two when a command-line run was started past the
queue beside it.

### Q10 `GET P/queues/preview?lane=generation|update` — 200

The Run dialog's line (REQ-JS-31), before anything is submitted:

| `answer` | Fields |
|---|---|
| `start` | `message`: `Starts now` |
| `wait` | `position`, `estimated_start`, `message`: `Waits as #2 — about 3 h` · `Waits for a free server slot: 2 of 2 generations are running` · `Held: …` |
| `refuse` | `code`: `LANE_FULL`, `message`, `running`, `waiting` (Briefs) — the action disabled |

422 `INVALID_LANE`.

### Q11 `GET P/queues/events?limit=100` — 200

`{"events": [{"id", "job_id", "kind", "actor_id", "at", "detail"}]}`, newest first. `actor_id`
`null`: the system did it. `kind`: `submitted`, `started`, `resumed`, `pause_requested`, `paused`,
`resume_requested`, `completed`, `failed`, `interrupted`, `cancelled`, `removed`, `held`,
`released`, `priority_changed`, `limits_changed`.

### Q12 `PATCH P/job-limits` — 200

Body `{"generation_limit"?: 1–50, "update_limit"?: 1–50}`; answer `{project_id, generation_limit,
update_limit}`. Lowering a limit removes nothing already accepted: submits are refused until the lane
is under it. 422 `INVALID_LIMIT`.

### Q13 `GET /queues` — 200

`{"cap": {…}, "held": 3, "projects": [Q9's answer, …]}` — every project with a job in a lane. 403
for anyone not a super admin.

### Q14 `POST /queues/held` — 200

Body `{"project_id"?: "p1", "remove": ["job…", …] | "all"}`: the listed held jobs are removed, the
rest go back to `queued` in their order. Start all = `remove: []`; clear all = `remove: "all"`.
Without `project_id`: every project. Answer `{"removed": [ids], "released": [ids]}`. 422 `NOT_HELD`,
`VALIDATION_ERROR`; 403.

### Q15 `DELETE V` — 204

Refused (409) while: a job of the project runs or is paused — `RUN_ACTIVE`, `jobs`: Briefs; a waiting
job needs the version, its own or the baseline it was submitted with — `VERSION_NEEDED`, `jobs`. Other
waiting jobs do not stop it. `VERSION_BUSY` and `VERSION_IS_BASELINE` as before.

## 5. Notices

`notifications` rows, to the job's submitter (a web job's) and the project's admins (REQ-JS-32):

| `type` | When |
|---|---|
| `job_started` | a job starts — from the command line too |
| `job_paused` | it paused |
| `job_completed`, `job_failed`, `job_interrupted`, `job_cancelled` | it ended (a cancel after `jobs.pausedDays` paused is `job_cancelled`) |
| `jobs_held` | waiting jobs held after a restart (admins) |

An update's starter is told its end in the words of WORD_FILE_UPDATES (`word_files_updated`,
`word_files_update_failed`), not by `job_*`.

## 6. What changed for a client of the API before the queue

- 409 `JOB_ALREADY_RUNNING`, `REEXPORT_RUNNING`, `EXPORT_RUNNING` are gone, and `RUN_ACTIVE` and
  `VERSION_BUSY` no longer answer Q1, Q2 or Q4: those jobs wait. Read `status` and `message`.
- `started_at` is `null` until the job runs; a waiting job has `submitted_at`.
- `GET P/jobs/current` is the project's running or paused generation, else its latest ended one — never
  a waiting one.
- A job's end can be `interrupted` or `removed`; `error_message` is a headline and `- ` lines.
