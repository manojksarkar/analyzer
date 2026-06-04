# Project Context — Analyzer + Backend + UI

> Updated: 2026-06-04 (version3 branch). This file is the all-in-one
> reference for anyone working on the FastAPI backend or its UI
> integration. For deep analyzer internals (LLM pipeline, CFG builder,
> docx layout, etc.) see the repo-root `PROJECT_CONTEXT.md` — that
> file is ~1900 lines of analyzer detail and is intentionally NOT
> duplicated here.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [Current State](#3-current-state)
4. [Design Decisions](#4-design-decisions)
5. [APIs](#5-apis)
6. [Storage Schema (no DB)](#6-storage-schema-no-db)
7. [Known Issues](#7-known-issues)
8. [Future Roadmap](#8-future-roadmap)
9. [Open Questions](#9-open-questions)
10. [Quick Start](#10-quick-start)

---

## 1. Project Overview

### What it does
Takes a C++ source project as input and produces an **ASPICE SWE.3 Software
Detailed Design** document (`.docx`) plus the supporting JSON model and
PNG/Mermaid flowcharts. A FastAPI backend wraps the CLI pipeline so a
separate UI can drive it interactively (edit descriptions, trigger
re-exports, browse the project structure, download results).

### Inputs
- A C++ source tree (path stored in `backend/repository_config.json`).
- `config/config.json` — analyzer + LLM + module-grouping config (JSONC,
  comments preserved across edits).
- LLM (Ollama / OpenAI-compatible) — optional, but enabled by default.

### Outputs
- `output/software_detailed_design_<group>.docx` — the SWE.3 document.
- `model/functions.json`, `model/functions_<group>.json`,
  `model/knowledge_base.json` — structured function metadata.
- `output/flowcharts/<unit>.json` — per-function Mermaid scripts.
- `output/flowcharts/*.png` — rendered flowcharts (sliced for tall ones).
- A REST API (17 endpoints, see §5).

### Users
Engineers documenting C++ codebases for ASPICE compliance. They:
1. Point the backend at a C++ repo (POST `/repository`).
2. Trigger a prepare job (POST `/jobs/prepare`).
3. Browse the resulting functions, edit descriptions, re-export.
4. Download the finished `.docx`.

---

## 2. Architecture

### Three tiers

```
┌─────────────────────────────────────────────────────────────────┐
│  UI  (Vite/React, separate repo, http://localhost:5173)         │
└──────────────────────────────┬──────────────────────────────────┘
                               │  REST / JSON
┌──────────────────────────────▼──────────────────────────────────┐
│  Backend  (FastAPI, port 8000, backend/main.py)                 │
│   - 17 endpoints                                                │
│   - in-memory job tracking                                      │
│   - reads/writes JSON files on disk                             │
│   - spawns run.py as subprocesses                               │
└──────────────────────────────┬──────────────────────────────────┘
                               │  subprocess.Popen
┌──────────────────────────────▼──────────────────────────────────┐
│  Analyzer pipeline  (python run.py)                             │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│   │ Phase 1  │→ │ Phase 2  │→ │ Phase 3  │→ │ Phase 4  │        │
│   │ Parse    │  │ Derive   │  │ Views    │  │ Export   │        │
│   │ libclang │  │ LLM enr. │  │ JSON+PNG │  │ docx     │        │
│   └──────────┘  └──────────┘  └──────────┘  └──────────┘        │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
                  model/, output/ on disk
```

### Process model
- One backend process (uvicorn).
- Each prepare or export request spawns a child `python run.py` subprocess.
- Child subprocesses are tracked in an **in-memory** `_jobs` dict — lost on
  uvicorn restart, but the on-disk model/ and output/ survive.
- Process tree kill on cancel (Windows: `taskkill /F /T`; POSIX:
  `killpg(SIGKILL)`).

### Multi-plan execution (important for progress UX)
For projects with `modulesGroups` configured, the analyzer's planner
(`src/core/group_planner.py:87`) splits the run into multiple plans:
- 1 build-model plan (Parse + Derive).
- N per-group plans (Generate views + Export to DOCX), one per group.

Each plan emits its own `[N/M] === Phase ... ===` log markers. The
backend canonicalises these to a 4-phase pipeline for the UI (see §4
"Canonical 4-phase mapping").

---

## 3. Current State

### Analyzer (✓ stable)
- 4-phase pipeline mature. See repo-root `PROJECT_CONTEXT.md`.
- LLM enrichment, CFG flowcharts, docx export all working.
- Per-module file outputs (`functions_<group>.json`) used as canonical
  description storage.

### Backend (✓ 17 endpoints, all wired)
- Repository CRUD (1a–1e).
- Component / module / function / flowchart reads (2–7).
- Job lifecycle: prepare, logs, status, cancel, export (8–12).
- Docx artifact: status + download (13, 14).
- Config: read + surgical write (15, 16).
- Project structure (17, with `?dirsOnly=` filter).

### UI (separate, external team)
- Vite dev server on `:5173`, CORS allow-listed.
- Active integration in progress against this backend.

### Recent backend milestones
| Date  | Change |
|---|---|
| Multi-repository CRUD (commit `17f9f2e`) | Replaced single hardcoded repo with `[{name, path}]` list + 5 CRUD endpoints. |
| `?name=` on job endpoints (commit `62a0df1`) | UI can spawn jobs against a registered repo without sending the full path. |
| Monotonic progress (commit `0fdd285`) | Fixed multi-group runs where `overallProgress` went backwards as new plans restarted at `[1/2]`. |
| `?dirsOnly=` on /project/structure (commit `f42c232`) | Nav sidebars can request a dirs-only tree. |
| Flowchart PNG slicing (commit `8560de4`) | Tall flowcharts (e.g. NTR_OP_FLUSH_Complete) split across Word pages instead of clipping. |
| ELK back-edge routing (commit `d4d4d3d`) | `elk.layered.feedbackEdges: true` so loop back-edges don't cross forward edges. |

---

## 4. Design Decisions

### 4.1 No database
**Decision:** All state lives in JSON files on disk + in-memory `_jobs` dict.
**Why:** The analyzer is single-user, file-based by nature (CPP repos, model
artifacts). Adding a DB would be incidental complexity. The team explicitly
chose this scope.
**Trade-off:** Job state is lost on uvicorn restart. Workaround: the on-disk
docx + model files survive, so the user can always start a fresh job.

### 4.2 In-memory jobs (no persistence)
**Decision:** `_jobs[job_id]` is a plain Python dict, never serialised.
**Why:** A typical session is one user kicking off one prepare → one export.
Persisting that history adds operational complexity (cleanup, retention)
for marginal UX gain.
**Trade-off:** UI must clear cached `jobId`s on a 404 from `/jobs/...` and
start a fresh job after a restart.

### 4.3 Subprocess spawning (not in-process)
**Decision:** Backend spawns `python run.py <path> [...]` as a child rather
than importing and calling the analyzer in-process.
**Why:** The analyzer was built as a CLI long before the backend existed —
re-using it as-is is cheaper than refactoring it into a library AND it
naturally isolates the heavy LLM work from the API thread.
**Trade-off:** Per-job process startup cost (~1 second). Acceptable since
prepare jobs run for minutes.

### 4.4 Per-module file as canonical description store
**Decision:** PATCH `/functions/{fn_id}` writes to
`model/functions_<group>.json` (NOT `model/functions.json`) +
`model/knowledge_base.json`.
**Why:** The per-module files are what the analyzer pipeline re-reads
during phase 4 (export). `functions.json` is raw parser output and gets
overwritten on every prepare run. Writing to the per-module file means
edits survive a re-export.
**Trade-off:** GET `/functions/{fn_id}` must look in the per-module file
first, then fall back to `functions.json`. Implemented via
`_read_description_override`.

### 4.5 Surgical JSONC editing (POST `/config`)
**Decision:** Walk the raw text with a JSONC-aware state machine, replace
just the `modulesGroups` block, write back. No parse-and-dump.
**Why:** `config/config.json` carries inline `//` documentation comments
the team uses (Linux libclang paths, env-var hints, etc.). A naïve
parse-and-write would strip them on every save.
**Trade-off:** The state machine has to handle strings, both comment
flavours, and brace nesting correctly. The previous `find()` based finder
had a bug with comment-mentioned `"modulesGroups"`; the current
`_find_modules_groups_key_pos()` walks the file properly and accepts only
root-level matches.

### 4.6 Canonical 4-phase mapping (for progress UX)
**Decision:** `totalPhase` is always **4** in the status response, even
though `src/core/group_planner.py` emits multiple plans with their own
`[N/M]` denominators (often `[N/2]`).
**Why:** The UI thinks in terms of `Parse → Derive → Views → Export`. A
3-group prepare emits 8 markers across 4 plans, but the *conceptual*
pipeline is still 4 phases. `phaseNumber` maps the latest log line's name
to the canonical 1..4.
**Trade-off:** `phaseNumber` can bounce between 3 and 4 as each group's
views+export pair runs. Mitigation: `overallProgress` is derived from
*marker count vs total expected* (`_expected_phase_markers`), which is
strictly monotonic — pair it with `phase` (latest label) for a smooth
progress bar.

### 4.7 `?name=` selector everywhere
**Decision:** `GET /project/structure`, `POST /jobs/prepare`, and
`POST /jobs/export` all accept `?name=<repo_name>` to look up the path
from `repository_config.json`.
**Why:** Once the UI has a repository picker, sending the name is more
robust than rebuilding the path string. Backward compatibility preserved
— body `path` still works.
**Trade-off:** None significant. When both are supplied, `?name=` wins.

### 4.8 CORS pinned to `http://localhost:5173`
**Decision:** Only the Vite dev server origin is allow-listed.
**Why:** Production deployment hasn't been specified yet. Wide-open
`*` would mask configuration mistakes.
**Trade-off:** When a staging/prod URL is decided, the list needs to be
extended.

### 4.9 Comments NOT preserved on POST /config (current)
**Decision** *(reversed — preserved again per team request)*: The surgical
splice IS used and `//` comments are kept across writes. The earlier
parse-and-rewrite attempt (lossy) was reverted after the user objected to
comment stripping.

### 4.10 No backup file on POST /config
**Decision:** The endpoint either succeeds (atomic temp-file + os.replace)
or refuses to write. No `config.json.bak.<stamp>` is created.
**Why:** The previous backup logic was added during the lossy-rewrite era
when comment loss was the risk. With the surgical splice the file is
either updated correctly or untouched, so a backup adds clutter.

---

## 5. APIs

Full reference: [`backend/API_DOC.md`](./API_DOC.md). Quick summary by
functional group:

### Repository (1a–1e)
| Method | Path | Purpose |
|---|---|---|
| GET    | `/api/v1/repository`         | List configured repos |
| GET    | `/api/v1/repository/{name}`  | Fetch one by name |
| POST   | `/api/v1/repository`         | Add new (auto-creates the file) |
| PUT    | `/api/v1/repository/{name}`  | Update path (no rename) |
| DELETE | `/api/v1/repository/{name}`  | Remove (file becomes `[]` if last) |

### Components / Modules / Functions / Flowcharts (2–7)
| Method | Path | Purpose |
|---|---|---|
| GET   | `/api/v1/components`                          | List components (hardcoded `FTL`) |
| GET   | `/api/v1/components/{component_id}`           | Component detail + full tree |
| GET   | `/api/v1/components/{component_id}/modules`   | Module summaries (no tree) |
| GET   | `/api/v1/functions/{fn_id}`                   | Function detail + flowchart |
| PATCH | `/api/v1/functions/{fn_id}`                   | Update description / hidden flag |
| GET   | `/api/v1/flowcharts/{fn_id}`                  | Raw Mermaid for one function |

### Jobs (8–14)
| Method | Path | Purpose |
|---|---|---|
| POST   | `/api/v1/jobs/prepare`                          | Spawn `python run.py <path> ...` |
| GET    | `/api/v1/jobs/{job_id}/prepare/logs`            | Tail of subprocess output |
| GET    | `/api/v1/jobs/{job_id}/status`                  | Generic job status |
| DELETE | `/api/v1/jobs/{job_id}`                         | Cancel (full tree kill) |
| POST   | `/api/v1/jobs/export`                           | Spawn `... --from-phase 4` |
| GET    | `/api/v1/jobs/{job_id}/export/status`           | Docx-artifact status |
| GET    | `/api/v1/jobs/{job_id}/export/download`         | Stream the docx |

`POST /jobs/prepare` and `POST /jobs/export` both accept `?name=<repo>` as
an alternative to body `path` (path lookup from `repository_config.json`).

### Config (15, 16)
| Method | Path | Purpose |
|---|---|---|
| GET  | `/api/v1/config` | Parsed `config/config.json` (JSONC → JSON) |
| POST | `/api/v1/config` | Surgically replace `modulesGroups` (preserves comments) |

### Project structure (17)
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/project/structure` | Directory tree of one configured repo |

Accepts `?name=<repo>` and `?dirsOnly=true`.

### Auto-generated docs
- `GET /openapi.json` — machine-readable OpenAPI 3.
- `GET /docs` — Swagger UI.
- `GET /redoc` — ReDoc UI.

---

## 6. Storage Schema (no DB)

All state lives in JSON files on disk + the in-memory `_jobs` dict.

### Files written by the analyzer
| Path | Producer | Purpose |
|---|---|---|
| `model/metadata.json`        | parser.py | `basePath`, `projectName`, `generatedAt`. Used by backend's `_walk_project_structure` to resolve paths. |
| `model/functions.json`       | parser.py (raw) → model_deriver.py (enriched) | All functions keyed by composite `module|unit|qname|params`. |
| `model/functions_<group>.json` | views/flowcharts.py:288 | Per-group filtered subset. **Canonical store for UI-edited descriptions.** |
| `model/knowledge_base.json`  | model_deriver.py | Functions/enums/macros/typedefs keyed by qualifiedName. Mirror of descriptions. |
| `model/globalVariables.json` | parser.py + enriched | Global variables. |
| `model/dataDictionary.json`  | parser.py | Type aliases + enums for LLM context. |
| `model/modules.json`         | model_deriver.py | Module → units mapping. |
| `model/units.json`           | model_deriver.py | Unit metadata. |
| `output/interface_tables.json` | run_views.py | Per-function interface metadata for docx export. |
| `output/flowcharts/<unit>.json` | views/flowcharts.py | `[{functionKey, name, flowchart: "mermaid"}]` per unit. |
| `output/flowcharts/*.png`      | mmdc | Rendered flowcharts. Tall ones split into `__part_K_of_N.png`. |
| `output/software_detailed_design_<group>.docx` | docx_exporter.py | The final document. |

### Files written by the backend
| Path | Purpose |
|---|---|
| `backend/repository_config.json` | List of `{name, path}`. Auto-created on first POST `/repository`. Auto-migrates legacy `{path}` shape on read. |
| `logs/run_<UTC>.log`             | Rolling daily log from analyzer subprocesses (already there pre-backend). |
| `logs/job_<job_id>.out.log`      | Per-job stdout+stderr capture from the spawned `run.py`. Read by GET `/jobs/{id}/prepare/logs`. |

### In-memory state (lost on restart)
- `_jobs[job_id]` — per-job dict with `process`, `pid`, `output_file`,
  `output_docx_path`, `selected_group`, `command_line`, `complete`,
  `error`, `return_code`, `total_phase_markers`, and (for export jobs)
  `progress: ExportProgress`.
- `_db["hidden_functions"]` — set of `fn_id`s flagged hidden via PATCH.
  Not persisted; resets on uvicorn restart.

### Composite IDs
- **`fn_id`**: `<inner_module>|<unit>|<qualified_name>|<param_types>`
  Example: `core|utils|add|int,int`.
- **`module_id`** / outer key in `modulesGroups`: `core`, `support`, `tests`.
- **Inner keys** (logical groups) under each outer: e.g.
  `modulesGroups.tests = { tests_a: [...], tests_b: [...] }`.

---

## 7. Known Issues

### 7.1 Within-phase progress is always 50% mid-phase
**Symptom:** `progress` field jumps 0 → 50 → 100, never anything in between.
**Cause:** `src/core/orchestration.py` only logs phase BOUNDARIES, not
within-phase activity. No signal to derive a finer percentage.
**Mitigation:** `overallProgress` is monotonic (count of markers / total
expected), so the overall progress bar is smooth even though `progress`
is a step function. UI should prefer `overallProgress` for the bar.

### 7.2 `phaseNumber` bounces 3↔4 on multi-group runs
**Symptom:** Status shows `phaseNumber: 4` then `phaseNumber: 3` then
`phaseNumber: 4` again as each module group's `Generate views` →
`Export to DOCX` runs.
**Cause:** Each group is one plan, and the planner restarts at phase 3
(Generate views) for every group.
**Mitigation:** `overallProgress` doesn't bounce. UI can use
`phaseNumber` for "what's happening now" and `overallProgress` for
"how far along are we."

### 7.3 Single shared `model/` directory
**Symptom:** Running a prepare against repo B overwrites the model files
from repo A. Component / function / flowchart endpoints (APIs 2–7) only
see whichever repo was prepared last.
**Cause:** The analyzer writes to `<repo>/model/` (single path).
**Mitigation:** Not yet. See §8 roadmap.

### 7.4 Jobs lost on uvicorn restart
**Symptom:** A `jobId` from before a restart 404s on every `/jobs/...`
endpoint afterwards. The on-disk artifacts (docx, model files) still
exist but no `downloadUrl` can be served via the old jobId.
**Cause:** `_jobs` is in-memory by design.
**Mitigation:** UI clears the cached jobId on 404 and asks the user to
start a fresh job.

### 7.5 `hiddenFns` accepted but not wired
**Symptom:** Export job body accepts `hiddenFns: {<fn_id>: true}` but
the resulting docx still shows those functions.
**Cause:** The hide flag isn't forwarded to `docx_exporter.py`.
**Mitigation:** PATCH `/functions/{fn_id}` toggles an in-memory flag
that GET reflects, but the analyzer itself doesn't see it.

### 7.6 `loc` field is always `"0"`
**Symptom:** Every API response includes `loc: "0"` (Repository,
Module, ModuleSummary, FunctionCaller).
**Cause:** Lines-of-code computation was never wired; the field exists
for shape parity with the office-side `models.py`.
**Mitigation:** Treat it as a placeholder. UI should hide the field or
show a dash.

### 7.7 `componentId` is hardcoded `FTL`
**Symptom:** `GET /components` always returns one component named
`FTL`; `GET /components/{id}` 404s for anything else.
**Cause:** The multi-component case wasn't scoped for v1.
**Mitigation:** UI should treat the single returned component as a
fixed value for now.

### 7.8 Within-phase log file shared across jobs (small race)
**Symptom:** `logs/run_<UTC>.log` is a rolling daily file. If two
prepare jobs overlap, both write to the same file.
**Cause:** `src/core/logging_setup.py` opens by date, not by job.
**Mitigation:** The backend's per-job `logs/job_<job_id>.out.log`
captures stdout+stderr separately and is what GET `/prepare/logs`
returns — that file IS isolated.

---

## 8. Future Roadmap

Ordered by likely value, not commitment:

### Near-term (next batch)
- **Hidden functions in export** — wire the `_db["hidden_functions"]`
  flag through `docx_exporter.py` so PATCHed `hidden: true` actually
  removes the function from the docx.
- **Auto `repository_config.json` write from UI** — the user mentioned
  having a "set repository path" flow on another machine; merge it in.
- **GET `/downloads/{filename}`** — direct file download without a
  jobId, so post-restart docx download works.

### Medium-term
- **Per-repo `model/` directories** — each repo gets `model_<name>/`
  so APIs 2–7 can serve any prepared repo without races. Requires
  threading `?name=` through every read endpoint.
- **Persistent job state** — sqlite or just a `jobs.json` next to
  `_jobs`. Removes the "lose-jobId-on-restart" caveat.
- **Real LOC computation** — `wc -l` style walk on each repo's path
  populates `Repository.loc`, `Module.loc`, etc.
- **Multi-component support** — generalise `componentId` from
  hardcoded `FTL` to a configurable list (config.json or
  repository_config.json).

### Long-term
- **Real within-phase progress** — add finer log markers in
  `src/core/orchestration.py` so the UI shows continuous progress.
- **Auth** — current backend trusts the network. Production would
  need at least an API key.
- **Production deploy model** — backend currently runs via
  `uvicorn --reload`. A proper deploy story (Docker? Windows service?)
  is undecided.

---

## 9. Open Questions

Questions that genuinely need a team / user decision before they can
be implemented:

### 9.1 Multi-tenancy semantics
When two repositories are registered, what does
`GET /components/FTL` mean? Does it serve the most-recently-prepared
repo's data, or do we need per-repo `model/` directories first?

### 9.2 Authentication model
Who is the user? Single-user desktop? Multi-user web app? The CORS,
auth, and rate-limit answers all depend on this.

### 9.3 Production deployment
Windows service? Linux + systemd? Docker container? Each implies
different `_REPO_ROOT` detection, log paths, and credentials story.

### 9.4 Hidden function semantics
When a function is hidden:
- Does it disappear from the docx? (Yes, intended.)
- Does it disappear from caller / callee lists in other functions?
  (Not yet decided.)
- Does it still appear in the source-tree view? (Probably yes.)

### 9.5 Description-edit conflict resolution
Two UI sessions both PATCH the same `fn_id` description. Last-write-wins?
The current implementation is "yes" (no concurrency control).

### 9.6 Should `componentId` go away?
We've been carrying it through every endpoint for shape parity, but
it's never used in the backend logic. Drop it from request bodies?
That's a breaking change for the office mock that already sends it.

### 9.7 LOC: real or just remove?
The field is shape-parity-only today. Options:
- Compute it lazily on read (slow but accurate).
- Compute it at prepare-time (fast but stale until next prepare).
- Drop the field entirely and update the office contract.

### 9.8 Backend restart and recovery
The known behaviour is "lose all jobIds; on-disk artifacts survive."
Is that the long-term answer or do we want resumable jobs?

---

## 10. Quick Start

### Run the backend
```
# From the analyzer repo root:
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# Or from inside backend/:
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
The path detector (`_detect_analyzer_root`) walks up from `backend/`
looking for `src/core/` + `config/` so the layout
`analyzer/fast-app/backend/main.py` also works.

### Smoke test
```
# Repository list
curl http://localhost:8000/api/v1/repository

# Project structure
curl http://localhost:8000/api/v1/project/structure?dirsOnly=true

# Components
curl http://localhost:8000/api/v1/components
```

### Trigger a prepare via the UI flow
```
1. POST /api/v1/repository                # if not already registered
   { "name": "my_repo", "path": "C:\\code\\my_proj" }

2. POST /api/v1/jobs/prepare?name=my_repo
   { "moduleId": "core" }

3. Loop GET /api/v1/jobs/{jobId}/status until complete=true.

4. GET /api/v1/jobs/{jobId}/export/download to stream the docx.
```

### Where everything lives
```
analyzer/
├── run.py                            # analyzer CLI entry
├── config/config.json                # analyzer + LLM + modulesGroups config
├── src/                              # analyzer pipeline (phases 1-4)
│   ├── parser.py                     # phase 1
│   ├── model_deriver.py              # phase 2
│   ├── run_views.py                  # phase 3
│   ├── docx_exporter.py              # phase 4
│   ├── core/
│   │   ├── orchestration.py          # phase runner
│   │   ├── group_planner.py          # plan_runs (multi-group splitting)
│   │   ├── config.py                 # JSONC config loader
│   │   └── logging_setup.py          # rolling daily log file
│   └── views/
│       ├── flowcharts.py             # spawns flowchart_engine + slicer
│       └── ...                       # other views
├── model/                            # parser/derive outputs
├── output/                           # views + docx + flowchart artifacts
├── logs/                             # rolling + per-job log files
└── backend/                          # THIS DIRECTORY — FastAPI app
    ├── main.py                       # 17 endpoints
    ├── models.py                     # Pydantic models (frozen contract)
    ├── repository_config.json        # multi-repo registry
    ├── API_DOC.md                    # endpoint-by-endpoint reference
    └── PROJECT_CONTEXT.md            # this file
```

### Key invariants the backend assumes
- `_REPO_ROOT` resolves to the analyzer root (walked up from
  `backend/`'s parent looking for `src/core/` and `config/`).
- `run.py` lives at `_REPO_ROOT/run.py`.
- Spawned subprocesses inherit the same Python interpreter
  (`sys.executable`). Mismatched venvs (uvicorn in venv A, analyzer
  expecting venv B) is the most common deployment failure — install
  the analyzer's deps into uvicorn's venv.
- `config/config.json` is JSONC; comments must survive every
  `POST /config` write.

---

_End of file. For analyzer internals beyond what's here, see the
repo-root `PROJECT_CONTEXT.md`._
