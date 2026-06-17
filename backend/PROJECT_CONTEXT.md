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

### Analyzer pipeline — phase by phase

The pipeline is **subprocess-based and crash-recoverable**: each phase is
its own Python entry point, and `run.py` can resume from any phase via
`--from-phase N`. The four canonical phases:

#### Phase 1 — Parse C++ source (`src/parser.py`)
- libclang-based AST walk.
- Inputs: project directory.
- Outputs:
  - `model/functions.json` — every function keyed by `module|unit|qname|params`.
    Carries `qualifiedName`, `location {file, line, endLine}`, `returnType`,
    `parameters`, `comment` (raw doxygen), `visibility`, `calledByIds`,
    `callsIds`, `writesGlobalIds`, `behaviourInputName`,
    `behaviourOutputName`.
  - `model/globalVariables.json` — globals.
  - `model/dataDictionary.json` — types, typedefs, enums (for LLM context).
  - `model/metadata.json` — `basePath`, `projectName`, `generatedAt`.

#### Phase 2 — Derive model (`src/model_deriver.py`)
- Builds units / modules from per-file function lists.
- Propagates global-access through the call graph (so a caller transitively
  inherits its callees' globals).
- Synthesises behaviour names (Input / Output labels) from params + globals.
- Runs LLM enrichment when enabled in `config.json::llm.descriptions`:
  - Two-pass description generation (callee-context then caller-context).
  - Few-shot prompt selection, cache, optional self-review.
  - Token-budgeted prompts (`maxContextTokens`).
- Outputs:
  - `model/functions.json` — enriched (descriptions added).
  - `model/units.json`, `model/modules.json`.
  - `model/knowledge_base.json` — flat keyed-by-qname view for downstream
    consumers (PATCH writes here in addition to per-module files).
  - `model/summaries.json` — optional phase/file/module hierarchy summary
    when `--llm-summarize` is passed.

#### Phase 3 — Generate views (`src/run_views.py`)
- Drives a registry of view scripts (each registered via `@register("name")`
  in `src/views/`).
- Key views and what they produce:
  - **interfaceTables** → `output/interface_tables.json` (drives the docx
    interface tables).
  - **unitDiagrams** → `output/unit_diagrams/*.png` (per-unit class-like
    Mermaid renders).
  - **moduleStaticDiagram** → `output/module_static_diagrams/*.png` (per-
    module box-and-lines layout).
  - **behaviourDiagram** → `output/behaviour_diagrams/*.png` (per-function
    sequence diagrams).
  - **flowcharts** → `output/flowcharts/<unit>.json` containing
    `[{functionKey, name, flowchart: "<mermaid>"}]` + matching `*.png`
    files. The PNGs are auto-sliced into `__part_K_of_N.png` when their
    aspect ratio would overflow a Word page (commit `8560de4`).
  - **sequenceDiagrams** → reuses the flowchart engine.
- When `modulesGroups` is configured, Phase 3 runs **once per group**
  via `views.flowcharts.scriptPath = src/flowchart/flowchart_engine.py`
  with `--selected-group <name>` so each group's output lands under
  `output/<group>/`.

#### Phase 4 — Export DOCX (`src/docx_exporter.py`)
- Reads `output/interface_tables.json` + per-group artifacts.
- Templates a Word document using `python-docx`.
- Embeds rendered flowchart PNGs (sliced parts inserted in order so the
  document flows across pages).
- Output path comes from `config.json::export.docxPath` with `{group}`
  substituted by the `--selected-group` value or `"all"`.

#### Mermaid flowchart specifics (analyzer subsystem)
Used by Phase 3's `flowcharts` view:
- `src/flowchart/flowchart_engine.py` — CLI entry that the views layer
  spawns as a subprocess (because libclang inside libclang is fragile).
- `src/flowchart/ast_engine/` — re-parses each function's body with
  libclang to build a CFG.
- `src/flowchart/mermaid/builder.py` — emits Mermaid `flowchart TD` plus a
  YAML frontmatter and `%%{init}%%` directive that select the ELK
  renderer and tune layout (commit `d4d4d3d`: `feedbackEdges: true` so
  loop back-edges route along the periphery instead of crossing forward
  edges).
- `src/flowchart/llm/generator.py` — single LLM call per function to
  label nodes/edges; respects `maxContextTokens` budget.

#### Key invariants the backend depends on
- `logs/run_<UTC>.log` (rolling) is configured by `src/core/logging_setup.py`
  using **UTC date** for the filename.
- `orchestration.py` emits `[N/M] === Phase ... ===` immediately before
  each phase starts and `[N/M] Phase Name — Xs` after each completes.
- The `--selected-group` flag's accepted names are the OUTER keys of
  `config.modulesGroups`. Case-insensitive resolution (`_resolve_group_name`).
- Per-module files live at `model/functions_<safe(group)>.json` with
  `_safe_filename()` (re.sub of `[<>:"/\\|?*]`) applied to the group name.

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

### Key endpoint examples (inline)

These are the responses a UI dev actually consumes — read this section
to integrate without needing `API_DOC.md` open in another tab.

#### Repository list (`GET /repository`)
```json
[
  { "name": "test_cpp_project", "path": "C:\\...\\test_cpp_project" },
  { "name": "other_repo",       "path": "D:\\cpp_code" }
]
```

#### Components (`GET /components/FTL`) — abbreviated
```jsonc
{
  "id": "FTL", "code": "FTL", "name": "FTL", "desc": "",
  "modules": [
    {
      "id": "core", "name": "core", "path": "core", "files": 3, "loc": "0",
      "tree": {
        "id": "core", "type": "submodule", "name": "core", "meta": null,
        "children": [
          { "id": "app", "type": "submodule", "name": "app", "children": [
            { "id": "app/main.cpp", "type": "submodule", "name": "main.cpp", "children": [
              { "id": "core|main|calculate|", "type": "fn", "name": "calculate" }
              /* ... */
            ]}
          ]},
          { "id": "math", "type": "submodule", "name": "math", "children": [/* ... */] }
        ]
      }
    },
    /* support, tests, ... */
  ]
}
```
A complete fixture for the test project is at
`backend/fixtures/get_components_FTL.json` (711 lines).

#### Function detail (`GET /functions/core|main|main|`)
```jsonc
{
  "id": "core|main|main|",
  "name": "main",
  "file": "app/main.cpp",
  "line": "75",
  "ret": "int",
  "description": "Top-level orchestrator for the calculation suite.",
  "callers": [],
  "callees": [
    { "id": "core|main|calculateWithCallback|",     "name": "calculateWithCallback",     "loc": "0" },
    { "id": "core|main|calculateWithPolymorphism|", "name": "calculateWithPolymorphism", "loc": "0" }
  ],
  "flowchart": "flowchart TD\n    N1([Start: main])\n    N3[int result1 = calculate#40;#41;#59;]\n    ...",
  "hidden": false
}
```

#### Update description (`PATCH /functions/{fn_id}`)
Request:
```json
{ "description": "Top-level orchestrator for the calculation suite." }
```
Response:
```json
{ "fnId": "core|main|main|", "savedAt": "14:32" }
```
Writes to `model/functions_<group>.json` (per-module file) **and**
`model/knowledge_base.json`. Does NOT touch `model/functions.json`.

#### Start prepare (`POST /jobs/prepare?name=test_cpp_project`)
Body (path optional when `?name=` is supplied):
```json
{ "moduleId": "core" }
```
Response:
```json
{ "jobId": "prep_4f7a1b8e2c9d" }
```

#### Job status (`GET /jobs/{job_id}/status`)
Running (mid-pipeline, multi-group prepare):
```json
{
  "jobId": "prep_4f7a1b8e2c9d",
  "type": "prepare",
  "complete": false,
  "progress": 50,
  "overallProgress": 68,
  "phase": "Generate views",
  "phaseNumber": 3,
  "totalPhase": 4,
  "error": null,
  "selectedGroup": "core",
  "commandLine": "python.exe run.py C:\\... --selected-group core"
}
```
Complete:
```json
{
  "jobId": "prep_4f7a1b8e2c9d",
  "type": "prepare",
  "complete": true,
  "progress": 100,
  "overallProgress": 100,
  "phase": "",
  "phaseNumber": 4,
  "totalPhase": 4,
  "error": null,
  "selectedGroup": "core",
  "commandLine": "..."
}
```

#### Download readiness (`GET /jobs/{job_id}/export/status`)
```json
{
  "jobId": "prep_4f7a1b8e2c9d",
  "complete": true,
  "stage": "done",
  "phase": "",
  "phaseNumber": 4,
  "totalPhase": 4,
  "progress": 100,
  "overallProgress": 100,
  "error": null,
  "filename": "software_detailed_design_core.docx",
  "downloadUrl": "/api/v1/jobs/prep_4f7a1b8e2c9d/export/download",
  "hiddenCount": 0,
  "selectedGroup": "core",
  "commandLine": "..."
}
```

#### Project structure (`GET /project/structure?dirsOnly=true`)
```json
{
  "name": "test_cpp_project",
  "children": [
    { "name": "app",   "children": [] },
    { "name": "math",  "children": [] },
    { "name": "outer", "children": [ { "name": "inner", "children": [] } ] },
    { "name": "tests", "children": [
      { "name": "access",    "children": [] },
      { "name": "direction", "children": [] }
      /* ... */
    ]}
  ]
}
```
Files have **no** `children` key at all; directories always have it
(possibly empty). UI inference: `"children" in node` → directory.

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

---

## 11. Development History & Lessons Learned

Things this team has paid for in time and that cannot be re-derived from
code or git log alone. Read this before re-litigating a decision; many
of these are "tried it, didn't work, here's why we ended up here."

### 11.1 The venv mismatch (always check first when a job fails on import)
**What happened:** Office machine kept getting `ModuleNotFoundError: No module named 'clang'` from Phase 1. Same `run.py` worked from the terminal.
**Root cause:** `uvicorn` was launched inside a venv that didn't have `libclang` installed. `_spawn_run_py` uses `sys.executable`, which inherits the venv interpreter. The terminal python was the system one (where `libclang` was installed).
**Lesson:** Whenever a job fails on a `ModuleNotFoundError`, the first question is "is uvicorn's Python the same one that runs the analyzer from the CLI?" Either install the analyzer's deps into the venv (`pip install -r requirements.txt` inside it) or run uvicorn without the venv.
**Backend follow-up:** `_spawn_run_py` redirects child stdout+stderr to `logs/job_<job_id>.out.log` so this is now visible immediately via `GET /jobs/{id}/prepare/logs` (commit `80bcfa4`).

### 11.2 Office config.json splice failure (the 80%-truncation bug)
**What happened:** The user's office `config.json` (700+ `clangArgs`) made `POST /config` produce a corrupt file. The diagnostic dump showed only ~80% of the original got written, with a JSON parse error mid-stream.
**First hypothesis:** Brace-tracking failure on a giant array. We added diagnostic dumps and a `?dryRun=true` query param.
**Second hypothesis (the lossy escape hatch):** We added a parse-modify-rewrite fallback that drops comments. User pushed back — the comments are documentation, not noise.
**Actual root cause:** The previous `_splice_modules_groups` used a naïve `str.find('"modulesGroups"')` that could match inside a `//` comment that happened to mention the literal `"modulesGroups"` string. When that happened, the brace tracker started scanning from inside a comment region and walked into the wrong part of the file.
**Fix:** `_find_modules_groups_key_pos` walks the whole file with full JSONC awareness (strings with `\\"` escape handling, both comment flavours, brace nesting) and only accepts a root-level match followed by `:`. The lossy fallback was removed.
**Lesson:** When parsing JSONC for surgical edits, do NOT rely on `str.find` for key positions. Walk the file with a state machine that understands comments and strings.

### 11.3 Multi-group progress went backwards (the 75 → 25 → 100 bug)
**What happened:** `overallProgress` started at 75%, then jumped down to 25%, then to 100%. `totalPhase` always showed 2 instead of 4.
**Root cause:** `src/core/group_planner.py` splits a prepare with `modulesGroups` configured into multiple plans. Each plan emits its own `[N/M]` markers (commonly `[N/2]`). My code took the latest `[N/M]` and divided N by M, so progress collapsed every time a new plan restarted at `[1/2]`.
**Fix:** Canonical 4-phase mapping by phase NAME (Parse / Derive / Views / Export). `totalPhase` is always 4. `overallProgress` is now `(markers_seen - 0.5) / total_expected * 100`, where `total_expected` is computed upfront from `_expected_phase_markers(selected_group, from_phase)` mirroring the planner's branching rules. For a 3-group prepare without `--selected-group`, the expected total is `2 + 3*2 = 8` markers, so progress climbs `6 → 18 → 31 → 43 → 56 → 68 → 81 → 93 → 100`.
**Caveat:** `phaseNumber` still bounces 3 ↔ 4 because that reflects what's actually running for each group. UI should bind the progress bar to `overallProgress` and the "current phase" label to `phase` — both are stable; `phaseNumber` is best read as "which canonical phase is happening right now."
**Lesson:** `_expected_phase_markers` and `src/core/group_planner.py::plan_runs` must stay in sync. If the planner branching changes, the helper needs to follow. (The helper's docstring deliberately references the planner file for this reason.)

### 11.4 hiddenFns: accepted, ignored, defaulted to None
**Decision history:** Originally `hiddenFns: Dict[str, bool]` (required). Caused 422s on direct callers (Postman) who sent just `{"path": "..."}`. Made it `Dict[str, bool] = {}` (optional with empty default). Caused some Pydantic-strict office instances to still 422. Finally settled on `Optional[Dict[str, bool]] = None` — Pydantic 2 always accepts omitting a nullable field, regardless of strictness.
**Current status:** Field is accepted on `ExportJobRequest` and PATCH on `/functions/{fn_id}` for shape parity with the office mock, but it's not forwarded to the analyzer pipeline yet. PATCH's `hidden` flag toggles an in-memory `_db["hidden_functions"]` set that GET `/functions/{fn_id}` reflects, but the docx exporter doesn't see it.
**Open question (see §9):** When a function is hidden, should it also disappear from caller/callee lists in other functions' detail views? Not decided.

### 11.5 The `loc: "0"` field everywhere
**Why it exists:** Office-side `models.py` declared `loc` as a required field on Repository / Module / ModuleSummary / FunctionCaller. The simplest path to shape parity was to add the field with a placeholder value.
**Why string and not int:** Office contract used string; we matched.
**Why `"0"` and not `null`:** Pydantic v2 strictness rules + simpler UI consumption.
**Trade-off:** UI shows "0 LOC" everywhere which is misleading. UI should either hide the field or show a dash. Real LOC computation is on the §8 roadmap.

### 11.6 Trailing-slash on POST
**Decision:** All POST URLs use no trailing slash (`POST /api/v1/repository`, NOT `POST /api/v1/repository/`). FastAPI redirects via 307 with the trailing slash form, but it's a round-trip the UI doesn't need.

### 11.7 PATCH writes to per-module file, not to functions.json
**Why:** `model/functions.json` is RAW parser output. The analyzer re-overwrites it on every prepare. If we wrote descriptions there, they'd vanish on the next run.
**Where they go:**
  1. `model/functions_<group>.json` — per-module subset that the docx export step reads. Survives across re-prepares because per-module files are written by the views step (Phase 3), not the parser.
  2. `model/knowledge_base.json` — flat by-qualifiedName view; mirror.
**Read path:** GET `/functions/{fn_id}` calls `_read_description_override()` which looks at the per-module file first, then falls back to `functions.json`.

### 11.8 Flowchart slicing for tall PNGs
**Problem:** A 41-node function (`NTR_OP_FLUSH_Complete`) rendered as a tall PNG that overflowed a single Word page and got clipped — ~40% of the function was invisible in the docx.
**Decision:** Slice at whitespace bands. Approach A (PNG slicing) was chosen over Approach B (CFG semantic split) for reliability — ELK's `rankSpacing: 60` guarantees a white horizontal band between every layer, so the slicer always finds clean cut points.
**Where:** `src/views/flowcharts.py::_maybe_slice_tall_png()`. Writes `<stem>__part_K_of_N.png` files; `docx_exporter` picks them up via `_resolve_flowchart_pngs`.
**Trigger:** aspect ratio H/W > 1.875 × 1.15 buffer. Wide layouts (W/H > 1.5) are skipped — height slicing wouldn't help. Tiny tail slices (<20% of a target) are merged into their predecessor.
**Constants:** `_SLICE_EMBED_WIDTH_IN = 4.0`, `_SLICE_USABLE_HEIGHT_IN = 7.5`. Tied to the `Inches(4.0)` width used in `docx_exporter._add_flowchart_table`.

### 11.9 Mermaid frontmatter + ELK back-edge routing
**Why we use ELK and not the default Dagre renderer:** for CFGs with loops, Dagre routes back-edges through the central column and causes crossings. ELK with `feedbackEdges: true` routes them along the periphery.
**Where:** `src/flowchart/mermaid/builder.py::build_mermaid()` emits a YAML frontmatter (`---\nconfig:\n  flowchart:\n    defaultRenderer: elk\n---`) plus an `%%{init}%%` directive that also sets `defaultRenderer` (some Mermaid CLI versions only honor one or the other).
**Gotcha that bit us:** the analyzer's `validate_mermaid()` originally rejected scripts that didn't start with `flowchart` — but with frontmatter, the script starts with `---`. We extended the validator to skip optional YAML frontmatter and `%%{init}%%` directives before the `flowchart` keyword check (commit `db9c7bc`).
**Casing:** The ELK options inside `%%{init}%%` are camelCase (`nodeSpacing`, not `nodespacing`). Lowercase keys are silently dropped by Mermaid (commit `db9c7bc` again).

### 11.10 In-memory jobs survive intent, not restarts
**The contract:** A `jobId` is valid only within one uvicorn session. When uvicorn restarts:
- The `_jobs` dict is empty. `GET /jobs/{old_id}/*` → 404.
- The on-disk model + docx files are untouched.
- The UI should clear cached jobIds on a 404 and prompt the user to start a fresh job.
**Why we didn't add persistence:** The team explicitly chose this scope. A single-user analyzer doesn't need durable job history. If we ever need it, see §8 "Persistent job state."

### 11.11 The previous "commit-strip" episode
**What happened:** While debugging the office config splice failure, we briefly switched POST `/config` to a parse-and-rewrite ("lossy") implementation that worked reliably but stripped `//` comments. User pushed back hard: comments are documentation, not formatting. We reverted to surgical-only. **No backup file is created on POST `/config`** (was added during the lossy era, removed when surgical-only became the only path).
**Lesson:** When a change visibly degrades the on-disk artifact the user cares about, even if it "works," it's a regression. Test against artifacts the user actually inspects, not just round-trip data shape.

### 11.12 PowerShell + Windows quirks we kept hitting
- `python -c "..."` in PowerShell sometimes triggers `goto :error` indentation errors when the inline script contains certain characters. We worked around by writing tiny `_probe_*.py` files and `rm`-ing them after.
- Unicode arrows (`→`) in `print()` calls fail with `UnicodeEncodeError` on the default `cp1252` console. Probes use plain `->`.
- `subprocess.run([...], shell=True)` on Windows is required for the analyzer per a long-standing project preference (logged in CLAUDE.md / memory). The backend follows the same pattern in `_spawn_run_py`.

---

## 12. Testing convention

There is **no automated test suite**. Verification is done via short
`_probe_*.py` scripts written at the analyzer repo root, run once, then
deleted. The pattern:

```python
# _probe_<name>.py
import asyncio, sys
sys.path.insert(0, ".")
sys.path.insert(0, "backend")

from backend.main import some_endpoint_handler
from models import SomeRequest

async def main():
    # call handler directly, assert on response
    ...

if __name__ == "__main__":
    asyncio.run(main())
```

Run with `python _probe_<name>.py` then `rm _probe_<name>.py`. Probes
are intentionally not committed — they're one-shot verification, not
regression coverage.

For changes that touch the analyzer pipeline itself (rare from the
backend side), the real test is running `python run.py test_cpp_project`
end-to-end and checking the produced docx.

---

_End of file. For analyzer internals beyond what's here, see the
repo-root `PROJECT_CONTEXT.md`._
