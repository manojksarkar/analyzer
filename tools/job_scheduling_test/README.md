# job_scheduling_test — job scheduling, end to end through the REST API

One script that does what the web app and the command line do with the job queue, on projects of its
own, and checks every answer: submits that start, wait or are refused, the limits, the server cap,
priority, pause and resume, cancel and remove, updates beside generations, a failed job, the command
line in the lanes, and — with review & update and incremental runs — the features working together.
Complex mode also runs the server under different `jobs` settings, one set per scenario; cli mode
does the whole feature through `analyzer.py`. On the terminal it prints each scenario, what it tests
and every check; at the end, a report of every requirement of
[JOB_SCHEDULING_SPEC](../../docs/spec/JOB_SCHEDULING_SPEC.md) with the scenarios that showed it.

It reads this machine's `engine/config/config.local.json` and `config.defaults.json` (never writes
them) for the `jobs` settings, the LLM server, and where a local repository may be. The projects it
creates are made with the server's `config.defaults.json`, as any new project is: no config file is
uploaded, because an upload in the web wizard only fills in the form, and the script sends those
fields itself.

> **Never against the review site's database or API.** It creates projects and runs analyses in
> them. Use a test API on a test database — [docs/JOB_SCHEDULING_TESTING.md](../../docs/JOB_SCHEDULING_TESTING.md)
> §1–§2 says how to set one up beside the real one.

## Run it

```bash
# 1. your config -- config.json is git-ignored: it holds passwords
cp tools/job_scheduling_test/config.example.json tools/job_scheduling_test/config.json
#    fill in: server.base_url, email, password; developer.email, password (or leave empty);
#    sample.source_dir: your SampleCppProject copy (or leave empty for the repository's)

# 2. once: a super admin, and a developer user (on the TEST database)
python tools/grant_access.py --set-superuser --email admin@aspice.dev
python analyzer.py user add --email dev@example.com --name Dev      # prints its password

# 3. the API running
python -m uvicorn api.main:app --port 8000

# 4. normal mode
python tools/job_scheduling_test/job_scheduling_test.py --mode normal

# 5. complex mode: stop the API of step 3 and set complex.manage_api true in config.json -- the
#    script runs the API itself, to restart it and to give each scenario its jobs settings.
#    Nothing to change in config.local.json.
python tools/job_scheduling_test/job_scheduling_test.py --mode complex

# 6. cli mode: the same (complex.manage_api true, your API stopped)
python tools/job_scheduling_test/job_scheduling_test.py --mode cli
```

Each mode on its own, or `--mode all` for the three in one run. `--only C12,L02` runs a few — with
`--mode all`, so that enough projects are made for any scenario.

Run it from the repository, on the API's machine, in a shell that uses the API's database (the same
`config.local.json` `db`, or the same `DATABASE_URL`): the command-line scenarios run `analyzer.py`
here, and it must reach the database the API reads. Needs `requests`, `psutil` and `python-docx`
(all in `requirements.txt`) and `git`. On Windows keep the API's folder and `sample.repo_dir` on
short paths: the server clones the sample under `workspaces/`, and git cannot write a path past 260
characters unless `git config --global core.longpaths true`.

**A server with `repositories.localRoots`** in its `config.local.json` clones a local repository only
from inside those folders, and the test projects' repository is the sample copy, not your
SampleCppProject. So the copies' folder, `sample.repo_dir`, must be one of them or inside one —
for example, with SampleCppProject at `C:/work/SampleCppProject` and `sample.repo_dir` `C:/jst`:

```json
"repositories": {"localRoots": ["C:/work/SampleCppProject", "C:/jst"]}
```

The server reads that list on every request: no restart. The script checks it before it creates
anything and, when the copies' folder is not allowed, stops and prints the line to add. Uploading a
config file in the wizard does not lift this limit: the server ignores a `repositories` block in an
uploaded file.

| `--mode` | What | Time |
|---|---|---|
| `normal` | every requirement once — short runs without the LLM; review & update and incremental runs through the queue | about 20 minutes |
| `complex` | what takes long runs, the LLM, a restart, a killed process, many requests at once; and the server's `jobs` settings — a cap of 1 and of 3, nothing held after a restart, the records' and the paused days, the silence, wrong values | about 50 minutes without the LLM; the LLM scenario adds two of its runs |
| `cli` | the feature through `analyzer.py`: each command a job of its lane, every refusal, `--ignore-queue`, `--detach`, Ctrl+C, a run killed or asleep, many at once, beside a paused job | about 40 minutes |
| `all` | `normal`, `complex`, then `cli` | |

| Option | |
|---|---|
| `--list` | the scenarios, their requirements and what each needs; then stop |
| `--only N02,N09` / `--skip C01` | run only these / leave these out |
| `--yes` | do not ask before creating projects |
| `--keep` | keep the projects even when `cleanup.delete_projects` is true |
| `--log-dir DIR` | where the command-line runs and the API it starts write their output |
| `--make-sample-repo DIR` | only make the git copy of SampleCppProject in DIR |

Exit code: **0** every check passed (warnings allowed), **1** a check failed, **2** it could not run
(config, sign-in, the projects).

## What a scenario needs

A scenario that cannot run says why and is skipped; the report says what would let it run.

| Need | Without it |
|---|---|
| the user in `server.email` is a **super admin** | N05, N08, C02 skipped; the all-queues checks of N01, C13, C16, L01, L02 skipped |
| a **developer** user in `developer` | N13 skipped; the 403 checks of N01, N05 skipped |
| **this machine is the API's** (`server.same_machine`) | the command line (N11, cli mode, parts of C02, C03, C12, C16), killing a run (C03, C05, L08) skipped |
| an **LLM server** in `config.local.json` (`complex.use_llm`) | C01 skipped |
| the test **runs the API itself** (`complex.manage_api`) | C02, C14, C16 skipped; C12, C13, C15, L02, L03, L05, L10 skipped unless your server already has their `jobs` values; C03, C04, L08 skip their timed part when its value is longer than `complex.max_wait_minutes` |
| web runs **in the background** — the API's default; `JOB_DETACH=false` makes them its children, which a restart stops | C02, C14 skipped, saying so |
| `jobs.maxGenerations` + 1 projects (`projects.count` 0 makes them) | N08 skipped |
| no generation of another project running | the scenarios that need a free server slot skipped while it lasts |

**The API the test runs** (`complex.manage_api`, complex and cli modes): `python -m uvicorn
api.main:app`, on the port of `server.base_url`. Its data folder is the test's own —
`<log dir>/api-data` — and there it reads a **copy** of this machine's `config.local.json` (the same
database, LLM server and repository folders) whose `jobs` block the test writes: before each
scenario, the defaults with that scenario's values over them; when they differ from what the API
runs under, the test ends the test projects' jobs and restarts it. The command-line runs the test
starts use the same folder, so they read the same settings. A restart stops only the API's own
process: the analyses it started go on, as on a real restart. Stop your own API on that database
first — one API per database. At the end the copy is deleted (it holds the database's password and
the LLM's key), and so are the runs' frozen copies; the logs stay.

| Scenario | Its `jobs` settings (the rest: the defaults — 2, false, 7, 10, 90) |
|---|---|
| C03 | `interruptedAfterMinutes` 2 — the least the server takes: a running job says it is alive every minute |
| C04 | `pausedDays` 0.003 — about four minutes |
| C12, L02, L03, L10 | `maxGenerations` 1 |
| C13 | `maxGenerations` 3 |
| C14 | `startQueuedAfterRestart` true |
| C15 | `keepFinishedDays` 0.002 — about three minutes |
| C16 | a wrong value in each key: `maxGenerations` 1.5, `pausedDays` 0, `interruptedAfterMinutes` 1, `keepFinishedDays` "90", `startQueuedAfterRestart` "yes", and `maxRunning`, no setting |
| L05 | `maxGenerations` 2 |
| L08 | `interruptedAfterMinutes` 2 |

> **C15 prunes the whole test database's records**, not only the test's: every ended job older than a
> few minutes goes, as the server does with `keepFinishedDays` — except the job that made each
> version. One more reason to run it on a test database only.

## The config

| Key | What |
|---|---|
| `server.base_url`, `email`, `password` | the API and a super admin; `request_timeout_seconds`, `verify_tls` |
| `server.same_machine` | true: this machine is the API's — the command line, killing a run, folders |
| `developer.email`, `password` | a user who is not an admin; added to the test projects as a developer |
| `sample.source_dir` | the SampleCppProject code to test with, a folder on this machine — a copy with fewer components makes every run shorter. Copied, never changed (a `.git` in it is left out); empty: the repository's own SampleCppProject |
| `sample.repo_dir` | the folder each run's git copy of that code goes in, as a new `jst-sample-<time>` folder; empty: the first `repositories.localRoots` that does not hold the sample code, else the temp folder. On a server with `repositories.localRoots` it must be inside one of them — see above |
| `projects.count`, `max_count` | how many projects; 0: the server's cap plus one (at least 3, 4 in complex) |
| `projects.build_config`, `architecture_layers` | the projects' settings (empty: the server's defaults) and the sample's components — as shipped, App, Math, Outer and Sample of Layer1. A short run is one component; the first group (two or more components) is a project's first version and gets the incremental changes; the last group's first folder is the one N10's commit removes. At least 3 groups, and every folder named must be in the sample — the script stops at once, naming any that is not |
| `runs.poll_seconds`, `job_timeout_minutes`, `llm_job_timeout_minutes` | how jobs are followed |
| `cli.enabled` | the command-line scenarios |
| `complex.manage_api` | complex and cli modes: the test runs the API itself, with each scenario's `jobs` settings — see above |
| `complex.use_llm`, `max_wait_minutes` | see above |
| `cleanup.delete_projects` | delete the test projects at the end |
| `report.json`, `report.markdown` | the reports' names and folder; each run adds `_<mode>_<start>` before the extension |

## The scenarios

`python tools/job_scheduling_test/job_scheduling_test.py --list` prints them with their
requirements.

| | Normal | Requirements |
|---|---|---|
| N01 | Who sees the queues | 30 |
| N02 | Three answers, and a lane in its order — the next starts by itself | 01 02 06 16 30 31 35 |
| N03 | The lane's limit; remove and cancel | 04 06 16 25 26 31 35 |
| N04 | Checked at submit: names, duplicates, retries, commits, scopes | 07 08 09 35 |
| N05 | Priority in the generation lane | 11 16 |
| N06 | Two lanes at once; the update lane in its order | 01 02 08 12 16 22 |
| N07 | One writer per version: an update waits for an export of its version | 01 03 12 35 |
| N08 | The server's cap, and the longest wait first; a waiting job's baseline cannot be deleted | 05 13 16 35 |
| N09 | Pause and resume a generation | 22 23 24 32 35 |
| N10 | A failed job frees its lane and its name | 16 21 35 |
| N11 | The command line in the lanes | 27 28 29 35 |
| N12 | Review & update and incremental runs, through the queue | 01 02 10 |
| N13 | Who may do what: a developer | 26 |
| N14 | Recorded, told and measured — every refusal and ending in words | 32 33 34 35 |

| | Complex | Requirements |
|---|---|---|
| C01 | Pause during the LLM's descriptions; the same Word files as a run never paused | 22 23 |
| C02 | A restart: waiting jobs held, running ones carry on, held jobs released in order | 14 18 19 28 32 33 |
| C03 | A run whose process dies is interrupted — at once, or after its silence | 16 20 32 35 |
| C04 | A job paused too long is cancelled — and, paused, said when it would be | 24 25 32 35 |
| C05 | A stopped web run resumes as its own job | 21 23 |
| C06 | Cancelled in any phase, a new version leaves nothing | 25 |
| C07 | Many requests at the same moment | 04 09 15 |
| C08 | The update lane at its limit, first come first served | 04 12 |
| C09 | An incremental chain: each baseline chosen when its job starts | 10 |
| C10 | A commit gone before its job starts | 07 16 21 |
| C11 | An update cancelled half way | 25 |
| C12 | One generation at a time: another project waits for the slot; a paused job gives it up; its resume takes it before a job that waited longer; the command line refused, the server full | 05 13 16 23 24 28 31 35 |
| C13 | Three generations at once, a fourth waits for a slot | 05 16 30 |
| C14 | A restart that holds nothing: the waiting jobs start by themselves, in order | 14 16 18 19 |
| C15 | Old job records go — not before `keepFinishedDays`, by twice it — with their record; the job that made a version stays | 33 34 |
| C16 | Wrong values: the server names each, goes on with its defaults; the command line reads the same | 05 28 35 |

| | Command line (`--mode cli`) | Requirements |
|---|---|---|
| L01 | Each command a job of its lane — `generate` and `reexport` at once, `export` — recorded, told, measured, ended by its run | 01 14 29 30 32 33 34 |
| L02 | Refused, exit 2, naming the jobs in the way: the lane taken (generate, export, reexport), jobs waiting, the server full, no such project — and nothing queued; no queue command | 02 05 27 28 35 |
| L03 | `--ignore-queue`: beside the lane's job, past a full server, recorded as forced, counted in the cap | 05 16 28 33 |
| L04 | A command-line run is the project's running job: the Run dialog, a web job behind it, the limit counts it, no pause or cancel from the web | 04 16 22 25 29 31 35 |
| L05 | Command-line runs take the server's slots: a web job waits, a third run refused | 05 16 28 31 |
| L06 | A run that fails (a commit the repository lacks), and one stopped with Ctrl+C | 16 21 25 29 35 |
| L07 | `--detach`: the command ends, the job runs on with its alive signal, through a restart of the API | 19 20 29 |
| L08 | Gone silent: killed — interrupted, `analyzer.py resume` finishes its version; asleep — interrupted, woken, it takes its real end | 16 20 21 23 32 35 |
| L09 | Three runs at the same moment: one runs, two refused | 15 28 |
| L10 | Beside a paused web job: generate and resume refused there; another project runs; the resume waits for it | 05 23 24 28 |

REQ-JS-17 (a short database outage) is not done through the API: the report says so, and how to try
it by hand.

## The report

On the terminal, as each scenario runs: its title, what it tests, its steps (`->`) and every check —
`PASS`, `FAIL`, `WARN` (shown, but not as well as it should be: a pause that took two minutes, not one)
or `SKIP` (and why). At the end: each scenario's result and time, each requirement's result and the
scenarios that showed it — `NOT RUN` when they were not chosen this time, `NOT HERE` when the API cannot
show it — and the failed checks. Each run also writes its own pair of files, named for its mode and
start, so one run never overwrites another: `job_scheduling_test_report_normal_20261026-101500.md`
and `.json` (`report.markdown` and `report.json` give the name's start and folder). Under each
scenario they hold what the terminal showed — its steps, the jobs' states as they were followed,
and its checks — so the report alone is enough to see what went wrong; the JSON has every detail.

N09, C01 and C05 also compare Word files: the paused or killed run's against a run of the same commit
never stopped — what they say ([doccheck](../doccheck/README.md): no difference at P1 or P2) and word
for word. A difference is shown per document, with the first words that differ; both versions' Word
files are kept in the log folder (`documents/<version id>/`) to open side by side. With a difference,
the report also has each run's own line on its description cache, from the API's logs on this machine
-- `never paused: 74 described (pass 1) — cache: 72 hits, 2 misses`: a miss in the second run is a
description the LLM wrote again.

## What it leaves

The test projects (unless `cleanup.delete_projects`), the sample repository it made, and the logs of
the command-line runs and of the API it ran (`<log dir>/api`, `<log dir>/api-data/logs`). The frozen
copies of the runs of the API it ran, and its copy of `config.local.json`, go at the end; a web run
of your own API keeps its frozen copy (`runs/`) 7 days.
