# Job scheduling — testing it on the office machine

How to check branch `feat/job-scheduling` on a server before it merges: the automated suites, the
PostgreSQL checks, then each behaviour by hand. What it must do:
[JOB_SCHEDULING_SPEC](spec/JOB_SCHEDULING_SPEC.md) (`REQ-JS-` ids) · the HTTP routes:
[JOB_SCHEDULING_API_SPEC](spec/JOB_SCHEDULING_API_SPEC.md) · the command line:
[CLI_COMMANDS — Runs and the job queue](CLI_COMMANDS.md#runs-and-the-job-queue).

The queue's web screens are not built yet. The queue is driven over HTTP, in Swagger (`/docs`), and
from the command line; the existing pages already show its messages (`current_activity`,
`error_message`).

> **Never on the review site's database or API.** Everything below runs from a checkout of its own,
> against databases made for the test, on ports of its own. The real database is upgraded last
> ([§5](#5-upgrading-the-real-database)), after a backup.

## 1. A checkout of its own

```powershell
git fetch origin
git worktree add --detach ..\analyzer-jstest origin/feat/job-scheduling
cd ..\analyzer-jstest
copy ..\<your checkout>\engine\config\config.local.json engine\config\
```

In the copy's `config.local.json`, point `db` at the scratch database `js_manual` (§2) and leave
`llmServer` and `llvm` as they are. The test API then writes under this folder's `workspaces/`, and
its `jobs` settings can change without touching the real server. No new packages are needed.

## 2. Scratch databases

In any PostgreSQL client:

```sql
CREATE DATABASE js_tests;    -- the PostgreSQL tests make their own tables here
CREATE DATABASE js_manual;   -- the API and the command line, by hand
```

Then, from `analyzer-jstest`, `python analyzer.py setup` — it builds `js_manual`, the database the copy
names, so nothing the tests below reach is the real one.

## 3. The automated tests

From `analyzer-jstest`, one suite at a time: some unit tests read the e2e documents on disk, so they
fail when an e2e run is rewriting them.

| Run | Expect |
|---|---|
| `python -m pytest tests/unit tests/api -q` | API 1,487 passed. Unit 3,855 passed — on the development machine 4 fail for its libclang and FastAPI versions (`test_perf_prefetch_and_lanes` … `null_check`, `test_review_api_contract` ×3); the same 4 here are that, any other failure is a finding |
| e2e on a fresh SQLite file, below | 188 passed, 4 skipped, about 5 minutes — with a real run paused and resumed, and runs cancelled in Phases 1–3 |
| the PostgreSQL tests, below | 14 passed (all skipped = the DSN was not seen) |
| `python tools/job_scheduling_test/job_scheduling_test.py --mode normal`, then `--mode complex` and `--mode cli` -- against the test API of §4 (its [README](../tools/job_scheduling_test/README.md) says how to set it up) | most of §4's scenarios and more, through the REST API and `analyzer.py`, each check tied to its requirement -- complex mode under each `jobs` setting it needs (the API run by the test, from a copy of `config.local.json`); the report lists every REQ-JS with its result |

```powershell
New-Item -ItemType Directory -Force C:\tmp\js_e2e | Out-Null
$env:DATABASE_URL = "sqlite:///C:/tmp/js_e2e/e2e.db"
python analyzer.py setup
python -m pytest tests/e2e -q
Remove-Item Env:DATABASE_URL

$env:ANALYZER_TEST_PG_DSN = "postgresql+psycopg://USER:PASSWORD@HOST:5432/js_tests"
python -m pytest tests/unit/test_job_claims_pg.py tests/unit/test_version_lock_pg.py -q
Remove-Item Env:ANALYZER_TEST_PG_DSN
```

## 4. By hand

### Set up

1. A fresh `js_manual`: `DROP DATABASE js_manual; CREATE DATABASE js_manual;`, then
   `python analyzer.py setup`.
2. Make the default user a super admin — **on this test database only**, its password is published:
   `python tools/grant_access.py --set-superuser --email admin@aspice.dev`.
3. In the copy's `config.local.json`, the `jobs` block for the test:
   ```json
   "jobs": {"maxGenerations": 1, "startQueuedAfterRestart": false, "pausedDays": 7,
            "interruptedAfterMinutes": 2, "keepFinishedDays": 90}
   ```
   `maxGenerations` 1 makes the server cap easy to reach. The API reads the block when it starts: after
   a change, restart it as in Q10 — and a restart holds what waits, so change it with nothing waiting.
4. Two consoles, both in `analyzer-jstest`. The API alone in one, so a restart (Q10) stops only it:
   ```powershell
   python -m uvicorn api.main:app --port 8100
   ```
   The web app in the other, pointed at that API:
   ```powershell
   cd web-app
   Set-Content .env "VITE_API_URL=http://localhost:8100/api/v1"
   npm install; npm run dev -- --port 5174
   ```
5. In the web app (http://localhost:5174, `admin@aspice.dev` / `admin`): create two projects, **A** and
   **B**, with the wizard, on a repository with a small component, and open each one's commit list once
   (it syncs the commits a submit is checked against). Note their ids and a full commit SHA.
6. Swagger (http://localhost:8100/docs): `POST /api/v1/auth/signin` with
   `{"email": "admin@aspice.dev", "password": "admin"}`, then **Authorize** with the `access_token`.

A generation is `POST /api/v1/projects/{A}/jobs` with, for a short run:

```json
{"commit_sha": "<full SHA>", "version_tag": "q1", "no_llm": true,
 "scope": {"type": "component", "names": ["<Layer.Component>"]}}
```

Each job's state: `GET /api/v1/projects/{A}/jobs/{job_id}`; a project's lanes: `GET
/api/v1/projects/{A}/queues`.

### Scenarios

| # | Do | Expect | REQ |
|---|---|---|---|
| Q1 | Submit three generations to A (`q1`, `q2`, `q3`) | `q1` `Starts now`; `q2` `Waits as #1`, `q3` `Waits as #2` (with "— about …" once A has a finished run); `queues` lists them in order; each starts by itself within about 10 s of the one before ending | 06, 16 |
| Q2 | `PATCH /projects/{A}/job-limits` `{"generation_limit": 2}`, then submit while two are in the lane; `GET /projects/{A}/queues/preview?lane=generation` | 409 `LANE_FULL`, `detail.message` names the jobs; the preview says `refuse`. Set the limit back to 3 | 04, 31 |
| Q3 | A generation running in A, submit one to B | B waits: `Waiting for a free server slot`, "1 of 1 generations are running on this server"; it starts when A's ends | 13 |
| Q4 | The same submit twice with one `Idempotency-Key` header; then the same generation twice without a key, while the first waits | one job for both; 409 `DUPLICATE_JOB` | 08, 09 |
| Q5 | Submit with a SHA the project does not have | 422 `UNKNOWN_COMMIT`; the version name stays free | 07 |
| Q6 | A generation **with** the LLM (`"no_llm": false`) in A and one waiting in B; once A's Phase 2 is under way, `POST /projects/{A}/jobs/{j}/pause`. Once B's has ended, `POST …/{j}/resume` | `Pausing at the next safe point…`, then within about a minute `paused` — `Paused — cancelled on … unless resumed`; `python analyzer.py progress --project-id A --version-id <its ver…>` says PAUSED; B's generation takes the slot the pause freed. On resume: `Resuming…`, it redoes the step it stopped in — its log counts the LLM answers it found in the cache — and completes. Pausing a waiting job or an update: 409 `NOT_PAUSABLE` | 22–24 |
| Q7 | `pausedDays` 0.003 (about 4 minutes) and restart; pause a run and leave it. Then `pausedDays` back to 7 | about 5 minutes later `cancelled`: "Cancelled: paused for 0.003 days and not resumed."; a version that never finished is gone | 24 |
| Q8 | Cancel a running new version; cancel a waiting job | `cancelled`, its draft gone from Versions and no `workspaces\<A>\versions\<id>` folder; the waiting one `removed`, its name free again. `GET /api/v1/notifications`: "Cancelled: …" | 25, 26, 32 |
| Q9 | Two waiting generations in A: `PATCH /projects/{A}/jobs/{second}` `{"priority": "high"}` | it becomes #1; from a user who is not a super admin, 403 | 11 |
| Q10 | `maxGenerations` 2. One running and two waiting in A, nothing in B. Ctrl+C the API console, start it again | the running job's run went on and is followed again; A's waiting jobs `held` ("Held after a restart"); a submit to A is held, one to B starts. `POST /api/v1/queues/held` `{"project_id": "<A>", "remove": []}` releases them in their order; `"remove": "all"` clears them | 18, 19 |
| Q11 | B's generation lane free: `python analyzer.py generate --project-id B --version-id cli1 --commit <SHA> --create-version --no-llm`, then end its python.exe in Task Manager (not Ctrl+C) | the job (`origin: cli`) stays `running` with no sign of life; 2–4 minutes later `interrupted`: "no sign of life for 2 minutes" (`interruptedAfterMinutes` 2). `POST /projects/{B}/versions/{B}.cli1/resume` carries the version on as a job of its own (`kind: resume`, web) — the command line's job stays as it ended | 20 |
| Q12 | A web generation running in A: Q11's command for A, `--version-id cli2`; then again with `--ignore-queue`; cancel it from Swagger; Ctrl+C it | exit 2, "Refused: the generation lane of project A is taken." naming the job; with `--ignore-queue` it runs beside it (`queues` shows two active); the web cancel: 409 `CLI_RUN`; Ctrl+C: its job `cancelled` | 27–29 |
| Q13 | Two finished versions of A: `POST /projects/{A}/versions/{v}/reexport` `{"scope": "all"}` for each, then the first again | the second waits as #1 in the update lane; the repeat answers 200, `already_queued` or `joined`. An update of a version being written waits: `Waiting for <version>` | 12 |
| Q14 | While a job of A runs: `DELETE /projects/{A}/versions/{v}` | 409 `RUN_ACTIVE`, naming the job (API spec Q15) | — |
| Q15 | `GET /projects/{A}/queues/events?limit=100` | every step above, with who did it (`actor_id`; `null` = the system) | 33 |

A finding is best sent as: the job id, what was done, the job as `GET …/jobs/{id}` shows it, and the
API console's lines around it.

## 5. Upgrading the real database

Once the branch is merged:

1. Back up: `pg_dump -Fc -f before_0019.dump <database>`.
2. Pick a time with no run going, stop the API, update the code.
3. `python analyzer.py setup` — migration 0019: the queue's columns, `job_events`, the indexes; each
   job gets its lane, and where two generations of one project were running, the older is marked
   interrupted, with the reason.
4. Optional: the `jobs` block in `config.local.json` — without it, the defaults (2, false, 7, 10, 90).
5. Make yourself a super admin: `python tools/grant_access.py --set-superuser --email <you>`.
6. Start the API. Jobs that were waiting are held until released (`POST /api/v1/queues/held`) — until
   the held-queue screen exists, `"startQueuedAfterRestart": true` starts them instead.

From then on, a command-line run of a project whose lane is busy is refused (exit 2); `--ignore-queue`
runs it anyway.

## 6. Afterwards

```powershell
cd ..\<your checkout>
git worktree remove ..\analyzer-jstest
```

and drop `js_tests` and `js_manual`.
