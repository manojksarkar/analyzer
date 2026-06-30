# API Implementation Plan — Real Pipeline-Backed Server

> Goal: make `api/` implement **every endpoint defined in `mock-api/api/openapi.yaml`**
> (the 70-route reference surface), backed by **both** the in-memory and JSON
> databases, where the analysis/document operations **invoke the real analyzer
> pipeline (`run.py`)** and **read real artifacts** (`model/`, `output/`,
> `versions/`) instead of the mock's simulation + committed fixtures.

---

## 0. Current state (verified)

| | `api/` (target, real) | `mock-api/api/` (reference) |
|---|---|---|
| Endpoints | 51 (older snapshot) | 70 |
| `schemas.py` (Pydantic response models) | ❌ | ✅ ~80 models |
| `routes/repositories.py`, `routes/users.py` | ❌ | ✅ |
| `services/git_cli.py`, `repo_git.py` | ❌ | ✅ (real git) |
| `services/job_runner.py` | ❌ (job stuck at `queued`) | ✅ (simulated) |
| `services/doc_render.py` + `fixtures/` | ❌ | ✅ (fixture-backed) |
| `/documents/{id}/render`, `/assets/{path}` | ❌ | ✅ |
| `IUserRepository.search` | ❌ | ✅ both adapters |
| `version_tag`/`branch` on jobs, token-stripped `build_config` | ❌ | ✅ |
| in-memory + JSON DB swap (`API_DB_BACKEND`) | ✅ | ✅ |
| `json_db` loads `model/functions.json` | ✅ | ✅ |

**Two kinds of work:** (A) *port* the missing endpoints/files from the mock, and
(B) *upgrade* the simulated/fixture pieces to invoke real commands and read real
output. The plan does both, organised so the API stays runnable at every step.

---

## 1. Reference: the real commands & artifacts to drive

The analyzer is a subprocess pipeline driven by `run.py` (repo root). The API
becomes a thin orchestrator over it.

### Pipeline entry point

```bash
python run.py [flags] <project_path>
```

Relevant flags (see root `PROJECT_CONTEXT.md` §5):

| API concept | run.py flag |
|---|---|
| `StartJobRequest.layer_filter` | `--selected-layer <L>` (or `--selected-group`) |
| `StartJobRequest.pause_after_phase1` | run phases 1–2 only, then hold (stop after `--from-phase` boundary) |
| per-project config (layers/clang/llm) | `--config <path>` (also honours `ANALYZER_CONFIG` env) |
| project display name | `--project-name <name>` |
| re-export only (reexport endpoint) | `--use-model --from-phase 4` |
| clean rebuild | `--clean` |
| uploaded data dictionary / macros | `--data-dictionary <csv>` / `--macros <csv>` |

### Incremental / versions (`reference_version_id` → incremental run)

- Full version-producing generation: `src/incremental/generate.py`
  (writes `versions/<id>/` + `cache/index.json`).
- Incremental: `src/incremental/engine.py::generate_incremental` (baseline →
  classify → impact BFS → selective LLM regen → reuse accounting report).
- Version-scoped reads already exist in the pipeline via `?projectId=&versionId=`
  request scoping (root `PROJECT_CONTEXT.md` §23, M3.9).

### Artifacts the API reads back

```
model/metadata.json, functions.json, globalVariables.json,
      units.json, components.json, dataDictionary.json,
      knowledge_base.json, summaries.json
output/<group>/interface_tables.json
output/<group>/unit_diagrams/*.{mmd,png}
output/<group>/behaviour_diagrams/*.{mmd,png}
output/<group>/flowcharts/*.{json,png}
output/<group>/software_detailed_design_<group>.docx
versions/<id>/...           (per-version snapshot)
versions/<id>/report.txt    (reuse accounting)
logs/run_<YYYYMMDD>.log     (live progress source for SSE)
```

### Git (clone the commit to analyse)

Port `api/services/git_cli.py` (self-contained, `shell=False`, credential
scrubbing, `GIT_TERMINAL_PROMPT=0`). Checkout target `commit_sha` into a
workspace under `workspaces/<project_id>/<commit_sha16>/` (gitignored). This
checkout is the `<project_path>` passed to `run.py`.

---

## 2. Milestones

### M0 — Sync the static surface (low risk, no behaviour change)

Port from `mock-api/api/` verbatim, then wire into `main.py`:

1. `schemas.py` — ~80 Pydantic response models, attached via
   `responses={<status>: {"model": X}}` (documentation only, no runtime
   filtering — keep handlers returning plain dicts, as the mock does).
2. `routes/users.py` + `IUserRepository.search` in `repositories/interfaces.py`,
   `db/in_memory.py`, `db/json_db.py` (case-insensitive name/email match,
   name-sorted, capped, excludes caller).
3. `routes/repositories.py` + `services/git_cli.py` + `services/repo_git.py`
   (real `ls-remote` / depth-1 clone+`ls-tree` / commit listing / uploads).
4. `models/domain.py`: add `version_tag` to `AnalysisJob`; ensure `Document`
   carries `layer`/`group`/`subtitle`; `Project` carries `default_branch`,
   `build_config`, `architecture_layers`.
5. `routes/projects.py`: `_project_view` returns `default_branch` +
   **token-stripped** `build_config` (drop `repo_access_token`);
   `CreateProjectRequest.access_token` stored in `build_config`, never echoed.
6. `routes/commits_versions.py`: lazy `_backfill_commits_from_repo` (real
   `git log` via `repo_git.list_commits`) so a fresh project shows real commits
   and Run-Analysis can start.
7. Register `repositories_router`, `users_router` in `main.py`; update
   `__init__.py`, `README.md`, `PROJECT_CONTEXT.md`, route count.

**Exit check:** app imports, `/openapi.json` + `/docs` 200, all 70 routes present,
every existing endpoint byte-identical to before (the mock proved this is safe).

---

### M1 — Real analysis worker (replaces the mock's simulation)

New `api/services/pipeline_runner.py` (the real counterpart to the mock's
`job_runner.py`). `POST /jobs` still spawns a background **thread**, but `_run`:

1. **Resolve source:** clone/checkout `commit_sha` of the project's `repo_url`
   (token from `build_config`) into `workspaces/<project_id>/<sha16>/` via
   `git_cli`. Skip if already checked out.
2. **Materialise per-project config:** write a config JSON (from
   `project.build_config` + `architecture_layers` → `layers` schema) to
   `workspaces/<project_id>/config.json`; pass via `--config`.
3. **Invoke `run.py`** as a subprocess (`shell=False`,
   `cwd=<repo root>`, `LOG_LEVEL` inherited), with flags mapped from
   `StartJobRequest`:
   - `layer_filter` → `--selected-layer`
   - `pause_after_phase1` → first invoke `--from-phase 1 ...` bounded to
     phases 1–2; mark job `paused`; on `resume` continue with
     `--use-model --from-phase 3`.
   - `reference_version_id` set → incremental path
     (`src/incremental/generate.py` / `engine.generate_incremental` with the
     baseline version), else full generation.
   - `version_tag` → `--project-name` / version tag for the produced version.
4. **Stream real progress over SSE:** map subprocess phase boundaries to the
   four `AnalysisPhase` records; tail `logs/run_<date>.log` and emit `log_line`
   events with real lines (replace the mock's fake `[tick N]` text). Phase % is
   derived from which subprocess phase is active + log markers.
5. **Honour cancel:** terminate the subprocess on `status=="cancelled"`.
6. **On completion:** register a real `Version` (pointing at `versions/<id>/`
   if the incremental store produced one, else the run's `model/`+`output/`),
   and create `Document`s by **enumerating real `output/<group>/` dirs**
   (one SWE.2 per group, one SWE.3 per component present, plus SYS.2/SWE.1),
   not from a hard-coded architecture walk. Flip project → `in_review`.
   Persist everything through the DB adapter (write-through works for JSON DB).
7. **Failure:** non-zero exit → job `failed` with the tail of stderr/log as
   `error_message`.

`POST /jobs/{id}/resume` and `/cancel` operate on the real subprocess lifecycle.
`reexport` → run `python run.py --use-model --from-phase 4 <path>` and refresh
the version's DOCX artifacts.

**Exit check:** against a small local repo (e.g. the seeded `samplecpp`
workspace), `POST /jobs` drives a real run, SSE shows real log lines, and on
completion `GET /documents` lists docs derived from actual `output/` groups.

---

### M2 — Real functions, render, and document artifacts

1. **Functions** (`/jobs/{id}/functions`): already reads
   `model/functions.json` via `json_db._load_pipeline_functions`. Extend so the
   in-memory adapter can also point at the active run's `model/` for the job,
   and `is_new` is computed against the `reference_version_id` baseline (diff of
   entity keys / `model/hashes.json`).
2. **Render** (`/documents/{id}/render`): port `services/doc_render.py` but point
   it at the **live run output** for the document's `version_id` instead of
   `fixtures/`:
   - `cover`/`meta` from `model/metadata.json` + project.
   - `sections` from real `output/<group>/interface_tables.json` (tables) and
     per-component/unit `diagram` sections referencing real PNG/MMD via the
     assets route. `source:"pipeline"` when artifacts exist, else fall back to
     the synthesized `source:"model"` payload (keep the fixture/synthesized path
     as the no-artifact fallback so the endpoint never 500s).
3. **Assets** (`/documents/{id}/assets/{path}`): unauthenticated `FileResponse`
   from the version's `output/<group>/` dir, path-traversal-guarded (reuse the
   mock's `resolve_asset`). Replaces fixture root with the real output root.
4. **Single-doc download/export** (`/download`, `/export`): stream the real
   `output/<group>/software_detailed_design_<group>.docx`
   (`FileResponse`, DOCX media type). If absent, lazily run
   `--use-model --from-phase 4 --selected-group <group>` to produce it.
5. **export-all**: produce/collect all groups' DOCX for the version and return a
   real ZIP (`StreamingResponse`) or a real signed-path URL backed by a
   download route — replace the current fake `download_url` string.

**Exit check:** `/render` returns real interface tables + diagram URLs that load
via `/assets`; `/download` returns a valid DOCX produced by the pipeline.

---

### M3 — Real compare (versions / commits)

`routes/compare.py` currently serves seeded diffs. Back it with the incremental
engine:

1. Resolve `current`/`baseline` (version tag, version id, or commit SHA) to
   two version snapshots (`versions/<id>/`), generating the baseline on demand
   if only a commit is given (incremental run against it).
2. `GET /compare`: summary + changed-document list from the engine's change
   classification (`versions/<id>/report.txt` + `model/incremental_plan.json` →
   added/modified/impacted/reused).
3. `GET /compare/documents` and `/compare/documents/{doc_id}`: section-level
   diff by comparing the two versions' `output/<group>/interface_tables.json`
   and rendered sections.

**Exit check:** comparing two real versions of `samplecpp` returns non-empty,
accurate changed sections.

---

### M4 — Persistence, config, docs, tests

1. **DB:** confirm both adapters implement the extended interface
   (`IUserRepository.search`, any new fields). JSON DB write-through must persist
   jobs/versions/documents created by the runner so state survives restart.
   `API_DB_BACKEND=json|memory` switch unchanged.
2. **Config/paths:** central settings (env) for repo-root location, workspaces
   dir, `JOB_MAX_CONCURRENCY`, subprocess timeout, `LIBCLANG_PATH` propagation,
   and where `model/`/`output/`/`versions/` live per project (recommend
   per-project workspace roots so concurrent projects don't collide on the
   shared repo-root `model/`).
3. **`.gitignore`:** add `workspaces/`, `api/db/data/`, generated `output/`.
4. **Docs:** update `api/README.md` + `api/PROJECT_CONTEXT.md` (route count,
   "real pipeline" architecture, the simulation→real swap, command table).
5. **Tests:** `TestClient` smoke tests with `JOB_SIM`→real run stubbed by a tiny
   fixture repo; mock `git_cli`/subprocess for unit tests; one e2e against
   `samplecpp`.

---

## 3. Key design decisions (recommendations)

1. **Per-project workspace isolation.** Run each project's pipeline in
   `workspaces/<project_id>/` with its own `model/`/`output/`/`versions/` rather
   than the shared repo-root dirs, so concurrent jobs and the swagger demo data
   don't clobber each other. (Pass project path = the checkout; set output dirs
   via config/`ProjectPaths.set_project_root`.)
2. **Thread + subprocess, not a real queue.** Keep the mock's daemon-thread
   model for `POST /jobs` (returns 202 immediately); the thread shells out to
   `run.py`. A real broker (Celery/RQ) is out of scope for the POC but the
   `pipeline_runner` boundary keeps it swappable.
3. **Fixtures become a fallback, not the source.** `doc_render`/assets read live
   output first; the committed `fixtures/` + synthesized payload remain only as
   the graceful "no run yet" fallback.
4. **Both DBs stay first-class.** No code outside `db/` and `session.py` knows
   which backend is active; the runner persists through the repository
   interfaces so JSON-mode runs survive restarts.

---

## 4. Work order (dependency-ordered checklist)

- [ ] M0.1 Port `schemas.py` + wire `responses=` into all routes
- [ ] M0.2 `IUserRepository.search` (interface + both adapters) + `routes/users.py`
- [ ] M0.3 `git_cli.py` + `repo_git.py` + `routes/repositories.py`
- [ ] M0.4 domain/model field additions (`version_tag`, project config fields)
- [ ] M0.5 projects/commits: token-stripped config + real commit backfill
- [ ] M0.6 register routers, update docs, verify 70 routes
- [x] M1 `pipeline_runner.py` (clone → config → `run.py` → SSE → version+docs)
- [x] M1.x wire `POST /jobs`/`cancel`/`resume`/`reexport` to the runner
- [x] M2 real functions diff, `doc_render` on live output, assets, download/export, export-all ZIP
- [x] M3 compare via incremental engine over real versions
- [ ] M4 persistence/config/gitignore/docs/tests

---

## 5. Resolved decisions (owner-confirmed)

1. **Execution host — co-located.** The API runs on a host where `LLVM/libclang`,
   `git`, and the analyzer Python env are available, so it shells out to
   `run.py` directly (no remote-worker design needed). `pipeline_runner` invokes
   the subprocess in-process on a daemon thread.
2. **Per-project work repo — confirmed.** Each project gets its own workspace
   (`workspaces/<project_id>/`) with isolated checkout + `model/`/`output/`/
   `versions/`, so concurrent projects never collide on the shared repo-root
   dirs. `run.py` is pointed at the per-project checkout/output via `--config`
   (+ `ProjectPaths.set_project_root`).
3. **LLM-on by default.** API-triggered runs enable LLM enrichment
   (`llm.descriptions`/`behaviourNames` + summarization on) in the generated
   per-project config. Expect longer run times; the incremental path
   (`reference_version_id`) is the mitigation for re-runs. A future per-run
   override can expose an LLM-off toggle, but the default is on.
