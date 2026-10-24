# job_scheduling_test — job scheduling, end to end through the REST API

One script that does what the web app and the command line do with the job queue, on projects of its
own, and checks every answer: submits that start, wait or are refused, the limits, the server cap,
priority, pause and resume, cancel and remove, updates beside generations, a failed job, the command
line in the lanes, and — with review & update and incremental runs — the features working together.
On the terminal it prints each scenario, what it tests and every check; at the end, a report of every
requirement of [JOB_SCHEDULING_SPEC](../../docs/spec/JOB_SCHEDULING_SPEC.md) with the scenarios that
showed it.

It reads this machine's `engine/config/config.local.json` and `config.defaults.json` (never writes
them) for the `jobs` settings, the LLM server, and where a local repository may be.

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

# 5. complex mode: stop the API of step 3 and set complex.manage_api true -- the script runs the
#    API itself, to restart it. Shorten the server's clocks in THIS checkout's
#    engine/config/config.local.json (a test checkout's, never the real server's):
#      "jobs": {"interruptedAfterMinutes": 2, "pausedDays": 0.003}
python tools/job_scheduling_test/job_scheduling_test.py --mode complex
```

Run it from the repository, on the API's machine, in a shell that uses the API's database (the same
`config.local.json` `db`, or the same `DATABASE_URL`): the command-line scenarios run `analyzer.py`
here, and it must reach the database the API reads. Needs `requests`, `psutil` and `python-docx`
(all in `requirements.txt`) and `git`. On Windows keep the API's folder and `sample.repo_dir` on
short paths: the server clones the sample under `workspaces/`, and git cannot write a path past 260
characters unless `git config --global core.longpaths true`.

| `--mode` | What | Time |
|---|---|---|
| `normal` | every requirement once — short runs without the LLM; review & update and incremental runs through the queue | about half an hour |
| `complex` | what takes long runs, the LLM, a restart, a killed process, many requests at once, the server's own clocks | about half an hour without the LLM; the LLM scenario adds two of its runs |
| `all` | `normal`, then `complex` | |

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
| the user in `server.email` is a **super admin** | N05, N08, C02 skipped; N01's all-queues check skipped |
| a **developer** user in `developer` | N13 skipped; the 403 checks of N01, N05 skipped |
| **this machine is the API's** (`server.same_machine`) | the command line (N11, part of C02, C03), killing a run (C03, C05) skipped |
| an **LLM server** in `config.local.json` (`complex.use_llm`) | C01 skipped |
| the test **runs the API itself** (`complex.manage_api`) | C02 (a restart) skipped |
| web runs **in the background** — the API's default; `JOB_DETACH=false` makes them its children, which a restart stops | C02 skipped, saying so |
| short **`jobs` settings** on the test server — `interruptedAfterMinutes` 2, `pausedDays` 0.003 — within `complex.max_wait_minutes` | the silent command-line run of C03 and C04 skipped |
| `jobs.maxGenerations` + 1 projects (`projects.count` 0 makes them) | N08 skipped |
| no generation of another project running | the scenarios that need a free server slot skipped while it lasts |

With `complex.manage_api` the script starts the API (`python -m uvicorn api.main:app`, on the port
of `server.base_url`) and, for C02, stops and starts it again — stopping only the API's own process,
so the analyses it started go on, as on a real restart. Stop your own API on that database first: one
API per database.

## The config

| Key | What |
|---|---|
| `server.base_url`, `email`, `password` | the API and a super admin; `request_timeout_seconds`, `verify_tls` |
| `server.same_machine` | true: this machine is the API's — the command line, killing a run, folders |
| `developer.email`, `password` | a user who is not an admin; added to the test projects as a developer |
| `sample.source_dir` | the SampleCppProject code to test with, a folder on this machine — a copy with fewer components makes every run shorter. Copied, never changed (a `.git` in it is left out); empty: the repository's own SampleCppProject |
| `sample.repo_dir` | the folder each run's git copy of that code goes in, as a new `jst-sample-<time>` folder; empty: the first `repositories.localRoots`, else the temp folder |
| `projects.count`, `max_count` | how many projects; 0: the server's cap plus one (at least 3, 4 in complex) |
| `projects.build_config`, `architecture_layers` | the projects' settings (empty: the server's defaults) and the sample's components — as shipped, App, Math, Outer and Sample of Layer1. A short run is one component; the first group (two or more components) is a project's first version and gets the incremental changes; the last group's first folder is the one N10's commit removes. At least 3 groups, and every folder named must be in the sample — the script stops at once, naming any that is not |
| `runs.poll_seconds`, `job_timeout_minutes`, `llm_job_timeout_minutes` | how jobs are followed |
| `cli.enabled` | the command-line scenarios |
| `complex.manage_api`, `use_llm`, `max_wait_minutes` | see above |
| `cleanup.delete_projects` | delete the test projects at the end |
| `report.json`, `report.markdown` | where the reports go |

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
| C04 | A job paused too long is cancelled | 24 25 32 35 |
| C05 | A stopped web run resumes as its own job | 21 23 |
| C06 | Cancelled in any phase, a new version leaves nothing | 25 |
| C07 | Many requests at the same moment | 04 09 15 |
| C08 | The update lane at its limit, first come first served | 04 12 |
| C09 | An incremental chain: each baseline chosen when its job starts | 10 |
| C10 | A commit gone before its job starts | 07 16 21 |
| C11 | An update cancelled half way | 25 |

REQ-JS-17 (a short database outage) is not done through the API: the report says so, and how to try
it by hand.

## The report

On the terminal, as each scenario runs: its title, what it tests, its steps (`->`) and every check —
`PASS`, `FAIL`, `WARN` (shown, but not as well as it should be: a pause that took two minutes, not one)
or `SKIP` (and why). At the end: each scenario's result and time, each requirement's result and the
scenarios that showed it — `NOT RUN` when they were not chosen this time, `NOT HERE` when the API cannot
show it — and the failed checks. The same is written to `report.markdown` and, with every detail, to
`report.json`.

## What it leaves

The test projects (unless `cleanup.delete_projects`), the sample repository it made, and the logs of
the command-line runs and of the API it ran. A web run's frozen copy of the code (`runs/`) goes by
itself after 7 days.
