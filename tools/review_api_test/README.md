# review_api_test — the whole Review & Update feature, through the REST API

One script that does what a user and the web app would do, and checks every answer:

1. signs in, **onboards a project** (`POST /projects`) and **generates a version** (`POST /projects/{id}/jobs`, then follows the job);
2. corrects **every kind** of LLM-written text — `description`, `behaviourInputName`, `behaviourOutputName`, `unitDescription`, `structDescription` (R3), a Dynamic Behaviour row (R6), flowchart labels (R8);
3. reads everything back through **every route** (R1, R2, R5, R7, R9, R10, R11) and the document page;
4. corrects again, sends **two saves of one slot at the same moment**, **undoes**, and tries the **mistakes a client can make** (empty text, camelCase body, wrong keys, unknown nodes …);
5. **re-exports** the version and opens the **Word file** to find the corrections;
6. generates the **next version** from it and checks every correction is carried.

You provide only the two request bodies — the project and the job. Every id the server generates
(project, job, version, document, slot key) is read from its answers.

## Run it

```bash
# 1. a config of your own -- config.json is ignored by git: it holds your password
cp tools/review_api_test/config.example.json tools/review_api_test/config.json
#    edit: server.base_url / email / password, onboard.create_project, generate.start_job

# 2. the API server must be running, with a database (PostgreSQL, or SQLite for a dev box)
uvicorn api.main:app --port 8000

# 3. run
python tools/review_api_test/review_api_test.py --config tools/review_api_test/config.json
```

Needs `requests` and `python-docx` (both in `requirements.txt`). A run on the sample, without
the LLM, takes about 10 minutes — most of it the two generations and the re-export — and makes
about 110 checks. Exit code: **0** every check passed, **1** a check failed, **2** the test could
not run (config, sign-in, a generation that failed).

On a SQLite server expect one `WARN`: two saves sent at the same moment both land, but only
PostgreSQL's per-version lock orders them, so the winner's `previousText` is checked only there.

### Testing on the sample project

The server clones `repo_url` itself, so it needs a git repository it can reach. For
`SampleCppProject`, on the server's machine:

```bash
python tools/review_api_test/review_api_test.py --make-sample-repo C:/work/sample-repo
```

It prints the path to put in `onboard.create_project.repo_url`. `config.example.json` is already set
up for the sample: groups `My Sample` (Dynamic Behaviour rows — `filterMode: all_callers`; the
default filter gives the 2 rows of Sample Core's `CoreGateway`) and
`Full` (struct, class and union descriptions), so all seven kinds get corrected.

### Re-running on something that exists

Two ready configs — copy one to `config.json`, then fill in your server, login and ids:

| file | what it tests |
|---|---|
| `config.existing-version.example.json` | **a version you already have** — only `project_id` and `version_id`. Step 13 (the next version) is skipped. The test's corrections stay on that version |
| `config.existing-project.example.json` | **a new version in a project you already have** — `project_id`, and a `start_job` body. For `scope`, copy what your first job used: `GET /api/v1/projects/{projectId}/jobs/current` → `job.scope`. Groups and components by their layer-qualified id (`Layer1.Sample Core`): a bare name two layers share is refused, 400 `INVALID_SCOPE` |

The ids: `GET /api/v1/projects` → `projects[].id` (`p…`); `GET /api/v1/projects/{projectId}/versions`
→ `id` (`ver…` — the id, not the `tag`). Or pass them on the command line instead:

```bash
# skip onboarding, test a new version of an existing project
python tools/review_api_test/review_api_test.py --project-id p1a2b3c4d

# skip the generation too -- test an existing version (step 13 is then skipped)
python tools/review_api_test/review_api_test.py --project-id p1a2b3c4d --version-id ver5e6f7a8b
```

The corrections the test makes **stay on the version** — an undo keeps its record — so point it at a
version you do not need, or let it generate a fresh one (the default).

## The config

| key | what |
|---|---|
| `server.base_url` | the API, e.g. `http://localhost:8000` (`/api/v1` is added) |
| `server.email`, `server.password` | a user who may create projects; the creator becomes the project's admin |
| `server.database` | `postgresql` or `sqlite`. With `sqlite`, the two-saves-at-once check only warns: SQLite has no per-version save lock |
| `onboard.project_id` | empty = create a project from `create_project`; set = use that project |
| `onboard.create_project` | **the body of `POST /api/v1/projects`**, sent as it is |
| `generate.version_id` | empty = generate a version from `start_job`; set = test that version |
| `generate.start_job` | **the body of `POST /api/v1/projects/{projectId}/jobs`**. `commit_sha: "latest"` = the newest commit the server lists for the project (`generate.branch` narrows it) |
| `generate.poll_seconds`, `timeout_minutes` | how the jobs are followed |
| `test.kinds` | the slot kinds to correct (all seven by default) |
| `test.slots_per_kind` | how many slots of each kind (default 2) |
| `test.concurrent_saves`, `negative_checks`, `check_page`, `reexport`, `check_word`, `carry_forward` | switch a part off with `false` |
| `test.report_file` | where the JSON report goes |

**Placeholders**, filled in anywhere in the two bodies: `{timestamp}` (this run's start time — use it
where a value must be new, like `version_tag`), `{projectId}`, `{versionId}`, `{versionTag}`. Keys
that start with `_` are comments.

## What it checks

Every line prints `PASS`, `FAIL`, `WARN` or `SKIP`. The report (`test.report_file`) holds every
check, the ids, and the slots the run corrected with every text saved on each.

| step | checks |
|---|---|
| 1 Sign in | a token; a request without one is 401 |
| 2 Onboard | the project is created, you are its admin, it has an architecture |
| 3 Generate | the job completes; the version has documents |
| 4 Before | R9 not stale, R1 empty; every R11 row is a `Slot` (API spec §5) and an uncorrected one has `llmText` = `text`, no undo; R2 reads an uncorrected slot as R11 lists it; R7's nodes are `Slot`s with the diagram |
| 5 First corrections | each save answers the `Slot` as it now is: `text` = `humanText` = the new words, `previousText` = the words before, `llmText` = the LLM's, `firstEdit`, `canUndo`; R8 answers each node in order with the rebuilt `dot`; R10 holds what the description saves queued |
| 6 Read back | R2, R1, R11 and R7 give each slot exactly as its save answered; R5 lists the edits in order; R9 stale with the count; R10 never lists a corrected slot; the document page shows the corrections |
| 7 Correct again | `firstEdit` false, `previousText` = the first correction, `llmText` still the LLM's; R5 has both |
| 8 Two saves at once | both 200; the slot holds one of the two; the winner's `previousText` is the other's text; R5 keeps both |
| 9 Undo | back to the LLM's text with `canUndo` false, like a save; 409 where the LLM wrote nothing; a second undo changes nothing; 409 on a slot nobody corrected |
| 10 Mistakes | 422 empty or camelCase body, 404 unknown slot, 400 malformed key, 501 node label through R3, 400/422/404 on R8's bad inputs (a bad node saves nothing), 404 unknown flowchart / version, 422 unknown kind; a NUL character (`\u0000`) in R3's text, an R6 bullet or an R8 label is 422 and saves nothing — PostgreSQL cannot store one |
| 11 Re-export | R9 stale → re-export job completes → R9 clean; every document downloads; the Word file carries each printed correction and none of the undone ones; struct descriptions reach the page |
| 12 After export | a new correction: not a first edit, the LLM's text kept; R9 stale again |
| 13 Next version | generated from this one (same commit), incremental; every correction carried, in force and printed |

A slot a document does not print (`shownIn: []`) is corrected and read back, but not looked for on
the page or in the Word file. Flowchart labels are pictures in the Word file, so they are checked
through the DOT instead.

Contract behind every check: [REVIEW_UPDATE_API_SPEC](../../docs/spec/REVIEW_UPDATE_API_SPEC.md).

## For developers

`--in-process` runs the API inside the script (FastAPI's test client) against the database in
`DATABASE_URL` or `engine/config/config.local.json` — no server to start:

```bash
DATABASE_URL=sqlite:///C:/tmp/review.db python analyzer.py setup
DATABASE_URL=sqlite:///C:/tmp/review.db python tools/review_api_test/review_api_test.py --in-process
```
