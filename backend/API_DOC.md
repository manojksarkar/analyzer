# Analyzer Backend — API Reference

Single source of truth for the FastAPI backend that the UI talks to.
All endpoints live under `/api/v1/`. Generated from the implementation
in `backend/main.py` and `backend/models.py`.

---

## Conventions

**Base URL:** `http://<host>:8000`
**Path prefix:** `/api/v1`
**CORS allow-list:** `http://localhost:5173` (the Vite dev server)
**Content-Type:** `application/json` for all bodies and JSON responses.

### Error shape (all 4xx / 5xx)
```json
{ "detail": "human-readable error string" }
```
or, for Pydantic validation failures (422):
```json
{ "detail": [ { "type": "missing", "loc": ["body","path"], "msg": "Field required", "input": { ... } } ] }
```

### Common status codes
| Code | Meaning in this API |
|---|---|
| 200 | OK |
| 400 | Validation error in business logic (e.g. wrong job type, unknown module name) |
| 404 | Resource not found (unknown id, missing file) |
| 409 | Resource exists but is in the wrong state (e.g. download requested before job complete) |
| 422 | Pydantic schema validation failed (e.g. missing required field in body) |
| 500 | Server-side failure (file IO, parse error, etc.) |
| 501 | Endpoint declared but not yet wired (none remaining in v1) |

### Notes the UI dev should know

- **Jobs are in-memory only.** A `jobId` returned from POST is valid only until the next uvicorn restart. The on-disk model + docx files survive restarts; the jobId tracker does not. UI should clear cached jobIds on a 404 from any `/jobs/...` endpoint.
- **`componentId` everywhere is the literal string `"FTL"`** for now. Multi-component support is on the roadmap.
- **`moduleId` is a group name from `config.layers`** — e.g. `My Sample`, `Full`, `Support`, `Access`, `Diag`, `Platform` in the current config (a "group" lives under a layer: `layers.<Layer>.groups.<Group>`). Case- and space-insensitive on input; the API echoes back the canonical key.
- **`fn_id` is the composite function key** used throughout the analyzer:
  `<component>|<unit>|<qualified_name>|<param_types>` — e.g. `Sample-Core|Core|init|` or `Lib|Lib|add|int,int`. The component segment is space-normalized (`"Sample Core"` → `Sample-Core`).
- **`loc` is a placeholder field** (string `"0"`) — the analyzer doesn't compute lines-of-code for the UI yet. It exists for shape parity with the office models.

---

# Endpoint Index

| # | Method | Path | Purpose |
|---|---|---|---|
| 1a | GET    | `/api/v1/repository` | List all repositories from `backend/repository_config.json` |
| 1b | GET    | `/api/v1/repository/{name}` | Get one repository by name |
| 1c | POST   | `/api/v1/repository` | Add a new repository (auto-creates the file if missing) |
| 1d | PUT    | `/api/v1/repository/{name}` | Update an existing repository's path |
| 1e | DELETE | `/api/v1/repository/{name}` | Remove a repository |
| 2 | GET    | `/api/v1/components` | List components |
| 3 | GET    | `/api/v1/components/{component_id}` | Component detail with full directory/file/function tree |
| 4 | GET    | `/api/v1/components/{component_id}/modules` | Module summaries (no tree) |
| 5 | GET    | `/api/v1/functions/{fn_id}` | Function detail (callers, callees, flowchart, description, hidden) |
| 6 | PATCH  | `/api/v1/functions/{fn_id}` | Update function description / hidden flag (persists to disk) |
| 7 | GET    | `/api/v1/flowcharts/{fn_id}` | Raw Mermaid script for one function |
| 8 | POST   | `/api/v1/jobs/prepare` | Start `python run.py <path>` (full pipeline) |
| 9 | GET    | `/api/v1/jobs/{job_id}/prepare/logs` | Tail of this job's stdout/stderr (≤ 40 lines) |
| 10 | GET   | `/api/v1/jobs/{job_id}/status` | Generic job status — works for prepare AND export |
| 11 | DELETE | `/api/v1/jobs/{job_id}` | Cancel a running job (full process-tree kill) |
| 12 | POST   | `/api/v1/jobs/export` | Start `python run.py <path> --from-phase 4` (re-render docx only) |
| 13 | GET   | `/api/v1/jobs/{job_id}/export/status` | Docx-artifact status (works for prepare AND export jobs) |
| 14 | GET   | `/api/v1/jobs/{job_id}/export/download` | Stream the docx (works for prepare AND export jobs) |
| 15 | GET   | `/api/v1/config` | Parsed `config/config.json` (JSONC → JSON) |
| 16 | POST  | `/api/v1/config` | Replace `layers` in config.json (surgical splice; preserves comments + other keys; no backup file) |
| 17 | GET   | `/api/v1/project/structure` | Full directory/file tree of the CPP project |

---

# 1. Repository CRUD

Storage: `backend/repository_config.json`. Shape on disk is a list:
```json
[
  { "name": "SampleCppProject", "path": "C:\\Users\\...\\SampleCppProject" },
  { "name": "other_repo",       "path": "D:\\cpp_code" }
]
```

The file is auto-created on the first POST when it doesn't exist. The
legacy single-repo format `{"path": "..."}` is auto-migrated on read to
a one-entry list named `default`, so existing installs keep working
without a manual edit.

## 1a. GET /api/v1/repository — list all

### Response 200
```json
[
  { "name": "SampleCppProject", "path": "C:\\Users\\...\\SampleCppProject" },
  { "name": "other_repo",       "path": "D:\\cpp_code" }
]
```
Returns `[]` when no repositories are configured yet.

## 1b. GET /api/v1/repository/{name} — fetch one

### Response 200
```json
{ "name": "SampleCppProject", "path": "C:\\Users\\...\\SampleCppProject" }
```
### Errors
- 404 — no repository has that name

## 1c. POST /api/v1/repository — add new

### Request body
```json
{ "name": "new_repo", "path": "C:\\new_cpp_project" }
```
Both fields are required and stripped of surrounding whitespace before
storage.

### Response 201
```json
{ "name": "new_repo", "path": "C:\\new_cpp_project" }
```

### Errors
- 400 — `name` or `path` missing / empty / whitespace-only
- 409 — a repository with that name already exists (names are
  case-sensitive)
- 500 — IO failure during write

Auto-creates `backend/repository_config.json` (and its parent directory)
when the file doesn't exist yet.

## 1d. PUT /api/v1/repository/{name} — update path

### Request body
```json
{ "name": "new_repo", "path": "D:\\new_cpp_project" }
```
The body's `name` MUST match the URL `{name}` — renames aren't
supported via PUT; do DELETE + POST instead.

### Response 200
```json
{ "name": "new_repo", "path": "D:\\new_cpp_project" }
```

### Errors
- 400 — body `name` doesn't match URL `{name}`, or `path` is empty
- 404 — no repository has that name
- 500 — IO failure during write

## 1e. DELETE /api/v1/repository/{name} — remove

### Response 204
Empty body.

### Errors
- 404 — no repository has that name
- 500 — IO failure during write

The on-disk file becomes `[]` (not deleted) when the last repository
is removed — the UI can keep POSTing without re-bootstrapping the file.

---

# 2. GET /api/v1/components

List all known components. Currently always returns a single hardcoded
`FTL` entry; `moduleCount` is read live from `config.layers` (the flattened
group count) so adding a new group to config increments the count without
restart.

### Response 200
```json
[
  {
    "id": "FTL",
    "code": "FTL",
    "name": "FTL",
    "desc": "",
    "moduleCount": 6
  }
]
```

---

# 3. GET /api/v1/components/{component_id}

Per-module breakdown with the full directory/file/function tree.
`component_id` is matched case-insensitively (`FTL`/`ftl`/`Ftl` all work).

### Tree shape

Each `TreeNode` has:
```
{
  "id":   string,
  "type": "module" | "submodule" | "fn",
  "name": string,
  "meta": null | string,
  "children": null | TreeNode[]
}
```
- **Module top node** → type=`submodule`, name = group name (a `config.layers` group)
- **Component level** → each component of the group (e.g. `Sample Core`, `Lib`,
  `Util` under `My Sample`) appears as a `submodule` node; collapsed only when a
  group has a single component sharing the group's name
- **Directory nodes** → type=`submodule`, id = path relative to project root,
  name = basename
- **File nodes** → type=`submodule`, id = relative file path, name = basename
- **Function leaves** → type=`fn`, id = composite function key, name = qualifiedName

### Response 200 (abbreviated)
```json
{
  "id": "FTL",
  "code": "FTL",
  "name": "FTL",
  "desc": "",
  "modules": [
    {
      "id": "My Sample",
      "name": "My Sample",
      "path": "My Sample",
      "files": 6,
      "tree": {
        "id": "My Sample",
        "type": "submodule",
        "name": "My Sample",
        "meta": null,
        "children": [
          {
            "id": "Sample Core",
            "type": "submodule",
            "name": "Sample Core",
            "children": [
              {
                "id": "Layer1/Sample/Core",
                "type": "submodule",
                "name": "Core",
                "children": [
                  {
                    "id": "Layer1/Sample/Core/Core.cpp",
                    "type": "submodule",
                    "name": "Core.cpp",
                    "children": [
                      { "id": "Sample-Core|Core|init|", "type": "fn", "name": "init" }
                    ]
                  }
                ]
              }
            ]
          },
          { "id": "Lib",  "type": "submodule", "name": "Lib",  "children": [ ... ] },
          { "id": "Util", "type": "submodule", "name": "Util", "children": [ ... ] }
        ]
      },
      "loc": "0"
    },
    { "id": "Full",     ... },
    { "id": "Support",  ... },
    { "id": "Platform", ... }
  ]
}
```

A sample response (generated from the legacy `SampleCppProject`) is committed at
`backend/fixtures/get_components_FTL.json`; regenerate it against
`SampleCppProject` after a pipeline run to refresh the fixture.

### Errors
- 404 — `component_id` doesn't match `FTL` (case-insensitive)

---

# 4. GET /api/v1/components/{component_id}/modules

Same module list as API 3 minus the heavy tree — fast endpoint for "what
modules are here." Case-insensitive `component_id`.

### Response 200
```json
[
  { "id": "My Sample", "name": "My Sample", "path": "My Sample", "files": 6,  "loc": "0" },
  { "id": "Full",      "name": "Full",      "path": "Full",      "files": 10, "loc": "0" },
  { "id": "Support",   "name": "Support",   "path": "Support",   "files": 6,  "loc": "0" },
  { "id": "Platform",  "name": "Platform",  "path": "Platform",  "files": 45, "loc": "0" }
]
```

### Errors
- 404 — unknown `component_id`

---

# 5. GET /api/v1/functions/{fn_id}

Full function detail: location, signature info, description (with PATCH
override applied), full caller/callee lists, raw Mermaid flowchart, and
the in-memory `hidden` flag.

`fn_id` is URL-path-encoded — typical id: `Sample-Core|Core|init|`. Pipes are
safe in modern clients; URL-encode if your HTTP client complains.

### Response 200 (some collections trimmed)
```json
{
  "id": "Sample-Core|Core|init|",
  "name": "init",
  "file": "Layer1/Sample/Core/Core.cpp",
  "line": "12",
  "ret": "void",
  "description": "",
  "callers": [],
  "callees": [
    { "id": "Lib|Lib|add|int,int", "name": "add",   "loc": "0" },
    { "id": "Util|Util|clamp|int", "name": "clamp", "loc": "0" }
  ],
  "flowchart": "flowchart TD\n    N1([Start: init])\n    N3[Lib::add#40;#41;#59;]\n    ...",
  "hidden": false
}
```

### Field sourcing
- `description` ← `functions_<group>.json[fn_id].description` if present, else
  `functions.json[fn_id].description` or legacy `comment`.
- `callers` ← `functions.json[fn_id].calledByIds` resolved to qualifiedName.
- `callees` ← `functions.json[fn_id].callsIds` resolved to qualifiedName.
- `flowchart` ← scanned from `output/flowcharts/*.json` matching `functionKey == fn_id`.
- `hidden` ← in-memory only (set via PATCH; not persisted to disk).

### Errors
- 404 — `fn_id` not present in `model/functions.json`

---

# 6. PATCH /api/v1/functions/{fn_id}

Update a function's description (persisted to disk) and/or hidden flag
(in-memory only). Both fields optional; omit either to leave it unchanged.

### Request body
```json
{
  "description": "Top-level orchestrator for the calculation suite.",
  "hidden": false
}
```
Both fields are nullable; the PATCH applies only the fields you send.

### Persistence rules
- `description`:
  - Writes to `model/functions_<group>.json` (per-module file — canonical
    location, written via atomic temp-file + os.replace).
  - Writes to `model/knowledge_base.json` (keyed by qualifiedName).
  - Removes any legacy `comment` field at both locations.
  - **Does NOT touch `model/functions.json`** (the raw parser output).
- `hidden`:
  - Toggles in the in-memory `_db["hidden_functions"]` map only.
  - Lost on uvicorn restart (no JSON storage by team decision).

### Response 200
```json
{ "fnId": "Sample-Core|Core|init|", "savedAt": "14:32" }
```

### Errors
- 404 — `fn_id` not present in `model/functions.json`

---

# 7. GET /api/v1/flowcharts/{fn_id}

Raw Mermaid script for one function — handy when the UI wants to render
the flowchart inline (mermaid.js) instead of relying on the PNG
generated by the analyzer.

### Response 200
```json
{
  "id": "Sample-Core|Core|init|",
  "name": "main",
  "code": "flowchart TD\n    N1([Start: main])\n    N3[int result1 = calculate#40;#41;#59;]\n    ..."
}
```

### Errors
- 404 — no flowchart entry matches `fn_id` in `output/flowcharts/*.json`
  (the pipeline hasn't rendered it yet)

---

# 8. POST /api/v1/jobs/prepare

Spawn `python run.py <path> [--selected-group <name>]` — full pipeline:
parse → derive → views → docx export. Returns a `jobId` to track progress
and download the resulting docx.

### Project path resolution (in priority order)
1. **`?name=<repo>` query param** — looked up in
   `backend/repository_config.json`; 404 if no such repository.
2. **Request body `path`** — used directly. Backward-compatible with
   pre-multi-repo clients.

Exactly one of the two must yield a directory.

### Query params
- `?name=<repo_name>` — optional. When provided, takes precedence over
  body `path` (useful when a UI has just picked a repo from the list
  and wants to spawn against it without re-sending the full path).

### Request body
```json
{
  "moduleId": "Support",
  "componentId": "FTL"
}
```
…or, for callers that don't use `?name=`:
```json
{
  "path": "C:\\aspice\\SampleCppProject",
  "moduleId": "Support",
  "componentId": "FTL"
}
```

| Field | Required | Notes |
|---|---|---|
| `path` | no (required if `?name=` is omitted) | Absolute path to the CPP project. Relative paths resolve against analyzer repo root. |
| `moduleId` | no (omit or `""` for full project) | Maps to `--selected-group <name>`. Validated against `config.layers` group names, case- and space-insensitive. |
| `componentId` | no | Accepted for shape parity, not forwarded to `run.py`. |

### Example calls
```
POST /api/v1/jobs/prepare?name=SampleCppProject
{ "moduleId": "Support" }

POST /api/v1/jobs/prepare
{ "path": "C:\\aspice\\SampleCppProject", "moduleId": "Support" }
```
Both spawn the same `python run.py <path> --selected-group Support` invocation.

### Response 200
```json
{ "jobId": "prep_4f7a1b8e2c9d" }
```

### Errors
- 400 — neither `?name=` nor body `path` supplied, OR the resolved
  path isn't a directory
- 400 — `moduleId` non-empty but doesn't match any `config.layers` group
  (detail includes the valid list)
- 404 — `?name=` doesn't match any configured repository
- 500 — failed to spawn the subprocess (e.g. python not on PATH)

### Verifying what the backend actually ran
GET `/jobs/{job_id}/status` includes:
```json
{
  "selectedGroup": "Support",
  "commandLine": "python.exe run.py C:\\aspice\\SampleCppProject --selected-group Support"
}
```

---

# 9. GET /api/v1/jobs/{job_id}/prepare/logs

Return up to the most recent **40** lines emitted by this prepare job's
subprocess. Each entry is parsed from the rolling-log format
`[HH:MM:SS] LEVEL logger.name: message`; lines that don't match are
attached to the previous timestamp/level as a continuation (typical for
Python tracebacks).

### Response 200
```json
[
  { "id": "0",  "t": "14:21:09", "level": "info",  "msg": "Starting parse phase" },
  { "id": "1",  "t": "14:21:09", "level": "info",  "msg": "[1/4] === Phase 1: Parse C++ source ===" },
  { "id": "2",  "t": "14:21:15", "level": "warn",  "msg": "macro CHK redefined" },
  { "id": "3",  "t": "14:21:21", "level": "error", "msg": "timeout after 60s" }
]
```

Per-job isolation: completed jobs see only their own slice; running
jobs read up to current EOF.

### Errors
- 404 — unknown `job_id`
- 400 — `job_id` exists but is not a prepare job

---

# 10. GET /api/v1/jobs/{job_id}/status

Generic job status — works for BOTH prepare and export jobs.

### Response shape
| Field | Type | Notes |
|---|---|---|
| `jobId` | string | Echo of the request id |
| `type` | `"prepare"` \| `"export"` | Job kind |
| `complete` | boolean | True once the subprocess has exited |
| `progress` | int (prepare) \| `ExportProgress` (export) | Within-current-phase %. While running: **50** (rough midpoint — the analyzer only logs phase boundaries, not within-phase progress). On complete: **100**. For export jobs this is wrapped in `ExportProgress({pct, stage})`. |
| `overallProgress` | int | Pipeline-wide %. **Monotonic** — derived from marker count vs. total expected (which is computed upfront from the planner branching rules in `src/core/group_planner.py`). For a full prepare on a 3-group config the expected total is `2 + 3*2 = 8` markers, so progress climbs 6 → 18 → 31 → 43 → 56 → 68 → 81 → 93 → 100. Never goes backwards even when phases 3+4 repeat per group. |
| `phase` | string | **Latest** phase label, with the `Phase N: ` prefix stripped (e.g. `"Derive model"`, not `"Phase 2: Derive model"`). Reflects the current truth — for multi-group runs the same name (e.g. `"Generate views"`) appears repeatedly as each group is processed. |
| `phaseNumber` | int | Canonical pipeline phase (1=Parse, 2=Derive, 3=Views, 4=Export). For multi-group runs this bounces 3 ↔ 4 as each group's views+export pair runs — pair with `overallProgress` (always monotonic) for a stable progress bar. 0 before any marker is logged. |
| `totalPhase` | int | Always **4** (the canonical pipeline length). UI never sees the inner `[N/M]` denominators that change per plan. |
| `error` | string \| null | Error description (set on non-zero exit or cancellation) |
| `selectedGroup` | string \| null | Resolved module key (or null when no moduleId) |
| `commandLine` | string | Literal CLI being run — useful for verification |
| `stage` | string (export only) | Same value as `progress.stage` |

### Response 200 — prepare job running (mid-pipeline)
```json
{
  "jobId": "prep_4f7a1b8e2c9d",
  "type": "prepare",
  "complete": false,
  "progress": 50,
  "overallProgress": 37,
  "phase": "Derive model",
  "phaseNumber": 2,
  "totalPhase": 4,
  "error": null,
  "selectedGroup": "Support",
  "commandLine": "python.exe run.py C:\\aspice\\SampleCppProject --selected-group Support"
}
```

### Response 200 — prepare job complete
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
  "selectedGroup": "Support",
  "commandLine": "python.exe run.py C:\\aspice\\SampleCppProject --selected-group Support"
}
```

### Response 200 — export job running
```json
{
  "jobId": "exp_91d2c4e5f7a3",
  "type": "export",
  "complete": false,
  "progress": { "pct": 50, "stage": "running" },
  "overallProgress": 50,
  "phase": "Export DOCX",
  "phaseNumber": 1,
  "totalPhase": 1,
  "stage": "running",
  "error": null,
  "selectedGroup": "Support",
  "commandLine": "python.exe run.py C:\\aspice\\SampleCppProject --from-phase 4 --selected-group Support"
}
```

### Errors
- 404 — unknown `job_id`

---

# 11. DELETE /api/v1/jobs/{job_id}

Cancel a running job. Full process-tree kill:
- Windows: `taskkill /F /T /PID <pid>`
- POSIX: `os.killpg(pgid, SIGKILL)`

Waits up to 2s for the OS to reap the process, then finalises so a
follow-up `/status` immediately returns `complete=True` with
`error="cancelled by user"`.

Idempotent: cancelling an already-complete job is a no-op — the original
`error` field stays unchanged (so a successful run isn't retroactively
flagged as cancelled).

### Response 200
```json
{ "status": "cancelled" }
```

### Errors
- 404 — unknown `job_id`

---

# 12. POST /api/v1/jobs/export

Spawn `python run.py <path> --from-phase 4 [--selected-group <name>]` —
re-renders only the docx using existing model data on disk. Use this
after editing function descriptions via PATCH to regenerate the document
without re-parsing.

### Project path resolution
Same rules as POST /jobs/prepare (see API 8):
1. `?name=<repo>` query param wins if provided.
2. Otherwise body `path` is used.

### Query params
- `?name=<repo_name>` — optional. Same semantics as `/jobs/prepare`.

### Request body
```json
{
  "moduleId": "Support",
  "componentId": "FTL",
  "hiddenFns": {}
}
```
…or with `path` instead of `?name=`:
```json
{
  "path": "C:\\aspice\\SampleCppProject",
  "moduleId": "Support",
  "componentId": "FTL"
}
```

| Field | Required | Notes |
|---|---|---|
| `path` | no (required if `?name=` is omitted) | Same rules as POST /jobs/prepare |
| `moduleId` | no | Same rules; should match (or be a subset of) what was prepared earlier so the per-module model files exist on disk |
| `componentId` | no | Accepted, not forwarded |
| `hiddenFns` | no (defaults to `null`) | Accepted but **currently ignored** — per-function hide isn't wired through `run.py` yet |

### Response 200
```json
{ "jobId": "exp_91d2c4e5f7a3" }
```

### Errors
- 400 — neither `?name=` nor body `path` supplied; OR `moduleId` invalid
- 404 — `?name=` doesn't match any configured repository
- 500 — Popen failure

### Important constraint
Export with `moduleId: "X"` assumes `model/functions_X.json` (and the
related per-module derivations) already exist on disk — typically from
a previous prepare that used the same `moduleId`. Otherwise phase 4 will
fail noisily.

---

# 13. GET /api/v1/jobs/{job_id}/export/status

Docx-artifact status — works for BOTH prepare AND export jobs (prepare
runs phase 4 too as part of the full pipeline, so it produces the same
docx). Extends `/status` with `filename`, `downloadUrl`, and a normalized
`stage` label. Carries the same `progress` / `overallProgress` /
`phase` / `phaseNumber` / `totalPhase` fields as API 10 — see that
section for their exact semantics.

### Response 200 — running
```json
{
  "jobId": "prep_4f7a1b8e2c9d",
  "complete": false,
  "stage": "running",
  "phase": "Export DOCX",
  "phaseNumber": 4,
  "totalPhase": 4,
  "progress": 50,
  "overallProgress": 87,
  "error": null,
  "filename": null,
  "downloadUrl": null,
  "hiddenCount": 0,
  "selectedGroup": "Support",
  "commandLine": "python.exe run.py C:\\... --selected-group Support"
}
```

### Response 200 — complete
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
  "filename": "software_detailed_design_Support.docx",
  "downloadUrl": "/api/v1/jobs/prep_4f7a1b8e2c9d/export/download",
  "hiddenCount": 0,
  "selectedGroup": "Support",
  "commandLine": "python.exe run.py C:\\... --selected-group Support"
}
```

`stage` values: `running` / `done` / `failed` / `cancelled`.
`downloadUrl` is non-null only when the docx file exists on disk.
`hiddenCount` is always 0 (hiddenFns is ignored).

### Errors
- 404 — unknown `job_id`

---

# 14. GET /api/v1/jobs/{job_id}/export/download

Stream the docx for this job back to the caller. Works for prepare jobs
too. Returns a `FileResponse` with:
- `Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document`
- `Content-Disposition: attachment; filename="software_detailed_design_<group>.docx"`

### Response 200
Raw `.docx` bytes. Browser will trigger a download.

### Errors
- 404 — unknown `job_id`, OR the docx file is missing on disk
- 409 — job hasn't completed yet, or completed with an error

---

# 15. GET /api/v1/config

Parsed contents of `config/config.json`. The on-disk file is JSONC
(supports `//` line comments and trailing commas); this endpoint strips
those and returns standard JSON. `config.local.json` overrides are NOT
applied — only the canonical version-controlled values are returned.

### Response 200 (top-level shape)
```json
{
  "views": { ... },
  "clang": { ... },
  "llm": { ... },
  "layers": {
    "Layer1": {
      "path": "Layer1",
      "groups": {
        "My Sample": { "Sample Core": "Sample/Core", "Lib": "Sample/Lib", "Util": "Sample/Util" },
        "Support":   { "Math": "Math", "App": "App", "Outer": "Outer/Inner" }
      }
    },
    "Layer2": {
      "path": "Layer2",
      "groups": { "Platform": { "Gpio": "Platform/Gpio", "Uart": "Platform/Uart" } }
    }
  },
  "ui": { "theme": "Light" }
}
```

### Errors
- 404 — `config/config.json` not found
- 500 — file exists but is unparseable

---

# 16. POST /api/v1/config

Replace ONLY the `layers` block in `config/config.json`. Every
other top-level key (`views`, `clang`, `llm`, `ui`, ...), every
`//` and `/* */` comment, every trailing comma, and the whitespace /
indentation everywhere else are preserved byte-for-byte.

### Strategy

Pure surgical splice — no fallback. A JSONC-aware key-finder walks
the file with full string and comment awareness, so a literal
`"layers"` substring appearing inside a string value or a `//`
comment can't trigger a false match. Once the real key is located,
brace-nesting (also string/comment-aware) finds the matching `}` of
its value and only that range is replaced.

If the splice produces text that doesn't re-parse, the endpoint dumps
the failed output to `logs/config_splice_failed_<UTC-stamp>.json` and
returns 400 with the parser error position and that path. The on-disk
file is never modified in that case. **No backup file is created**
(the on-disk file stays exactly as-is on both success and failure).

### Request body
```json
{
  "layers": {
    "Layer1": {
      "path": "Layer1",
      "groups": {
        "My Sample": { "Sample Core": "Sample/Core", "Lib": "Sample/Lib", "Util": "Sample/Util" },
        "Support":   { "Math": "Math", "App": "App", "Outer": "Outer/Inner" }
      }
    },
    "Layer2": {
      "path": "Layer2",
      "groups": { "Platform": { "Gpio": "Platform/Gpio", "Uart": "Platform/Uart" } }
    }
  }
}
```

| Field | Required | Notes |
|---|---|---|
| `layers` | yes | Layer name → `{ "path": <layer dir>, "groups": { <group>: { <component>: <path> \| [paths] } } }`. The whole `layers` object is replaced verbatim. |

### Query params
- `dryRun=true` — run the parse + rewrite pipeline but do NOT touch
  disk. Returns the would-have-been-written byte size. Useful for
  the UI to validate a new `layers` block before committing.

### Response 200
```json
{
  "status": "ok",
  "layerCount": 2,
  "layers": ["Layer1", "Layer2"]
}
```

### Response 200 — dryRun
```json
{
  "status": "dryRun",
  "wouldWrite": "C:\\aspice_v2\\config\\config.json",
  "layerCount": 2,
  "layers": ["Layer1", "Layer2"],
  "previewBytes": 3214
}
```

### Errors
- 400 — body missing `layers`; OR existing on-disk `config.json`
  isn't parseable (the endpoint refuses to overwrite an already-broken
  file)
- 404 — `config/config.json` doesn't exist
- 500 — IO failure during backup or write

### What's preserved across the write

| Element | Preserved? |
|---|---|
| Other top-level keys (`views`, `clang`, `llm`, `ui`) | ✓ byte-identical |
| `layers` content | replaced with body value |
| Single-line comments (`// ...`) | ✓ |
| Block comments (`/* ... */`) | ✓ |
| Trailing commas (JSONC quirk) | ✓ |
| Whitespace / indentation outside the layers block | ✓ |

Writes are atomic (temp-file + `os.replace`) so an interrupted save
can't leave a half-written file. **No backup file is created** — the
splice either succeeds or refuses to touch the live file.

---

# 17. GET /api/v1/project/structure

Return the full directory/file tree of one configured repository. Used
by the UI to render the source-tree explorer.

### Query params
- `?name=<repo_name>` — pick a specific repository by name. When
  omitted, the **first** entry in `backend/repository_config.json` is
  used (matches the historical single-repo behaviour).
- `?dirsOnly=true` — return a **directories-only** tree (file entries
  are omitted everywhere in the response). Default is `false` (files
  included). Useful for navigation sidebars that don't need leaf nodes.

### Source of the project path
The endpoint reads `backend/repository_config.json` — see the
Repository CRUD section (1a–1e) for shape and lifecycle. If that file
is missing/empty, or the requested `name` isn't found, the endpoint
returns 404.

### Example — `?dirsOnly=true`
```
GET /api/v1/project/structure?dirsOnly=true
GET /api/v1/project/structure?name=SampleCppProject&dirsOnly=true
```
```json
{
  "name": "SampleCppProject",
  "children": [
    { "name": "Layer1", "children": [
      { "name": "Sample", "children": [
        { "name": "Core", "children": [] },
        { "name": "Lib",  "children": [] },
        { "name": "Util", "children": [] }
      ] },
      { "name": "Math", "children": [] },
      { "name": "App",  "children": [] }
      /* ... Direction, Types, Flow, Hub, Poly, Access, Diag, Outer/Inner ... */
    ] },
    { "name": "Layer2", "children": [
      { "name": "Platform", "children": [
        { "name": "Gpio", "children": [] },
        { "name": "Uart", "children": [] }
        /* ... 15 components ... */
      ] }
    ] },
    { "name": "Layer3", "children": [] }
  ]
}
```
Empty `children: []` is the right signal for a directory that contains
only files (filtered out) — the directory itself is still present, just
with no leaf nodes underneath. This keeps the response shape uniform:
every node either has `children` (directory) or doesn't (file). With
`dirsOnly=true` the file branch never appears.

### Response shape
Recursive, intentionally minimal:
```
directory -> { "name": str, "children": StructureNode[] }
file      -> { "name": str }                                  (no `children` key)
```
UI infers type from presence/absence of `children` (`"children" in node`).

- Dotfiles and dot-directories are skipped (`.git`, `.flowchart_cache`,
  `.vscode`, etc.) — cross-platform via the dotfile convention.
- Sort order: directories first, then files; alphabetical within each
  group. Identical projects produce byte-identical responses across
  runs.
- Depth is unlimited (small/medium projects only — be mindful for
  very deep trees).

### Response 200 (abbreviated for the test project)
```json
{
  "name": "SampleCppProject",
  "children": [
    {
      "name": "Layer1",
      "children": [
        {
          "name": "Sample",
          "children": [
            { "name": "Core", "children": [ { "name": "Core.cpp" }, { "name": "Core.h" } ] },
            { "name": "Lib",  "children": [ { "name": "Lib.cpp" },  { "name": "Lib.h" } ] },
            { "name": "Util", "children": [ { "name": "Util.cpp" }, { "name": "Util.h" } ] }
          ]
        },
        { "name": "Math", "children": [ { "name": "Math.cpp" }, { "name": "Math.h" } ] }
        /* ... App, Direction, Types, Flow, Hub, Poly, Access, Diag, Outer/Inner ... */
      ]
    },
    {
      "name": "Layer2",
      "children": [
        {
          "name": "Platform",
          "children": [
            { "name": "Gpio", "children": [ { "name": "Gpio.cpp" }, { "name": "Gpio.h" } ] }
            /* ... Uart, Spi, I2c, Adc, ... 15 components */
          ]
        }
      ]
    },
    { "name": "Layer3", "children": [] }
  ]
}
```

### Errors
- 404 — no repositories configured in `repository_config.json`
- 404 — `?name=` doesn't match any configured repository
- 404 — repository's path doesn't exist on disk or isn't a directory

---

# Recommended UI Flows

### A. First-time run for a project (using `?name=`)
```
1. GET  /api/v1/repository                                // list of registered repos
2. GET  /api/v1/components                                // sidebar
3. GET  /api/v1/components/FTL                            // module tree
4. POST /api/v1/jobs/prepare?name=SampleCppProject        // body: { "moduleId": "Support" }
5. Loop:
     GET /api/v1/jobs/{jobId}/status                      // progress + phase
     GET /api/v1/jobs/{jobId}/prepare/logs                // optional, for log panel
6. GET /api/v1/jobs/{jobId}/export/status                 // wait for stage="done", downloadUrl set
7. GET /api/v1/jobs/{jobId}/export/download               // file download
```
Step 4 can also use `body.path` instead of `?name=` (legacy form).

### B. Edit a description and re-export
```
1. GET   /api/v1/functions/{fn_id}                        // load editor
2. PATCH /api/v1/functions/{fn_id} {"description": "new text"}
3. POST  /api/v1/jobs/export?name=SampleCppProject        // body: { "moduleId": "Support" }
4. Same status-poll + download as flow A from step 5 onward
```

### B'. Register a new repo, then run
```
1. POST  /api/v1/repository { "name": "my_repo", "path": "D:\\code\\my_proj" }
2. POST  /api/v1/jobs/prepare?name=my_repo
3. Same as flow A from step 5 onward
```

### C. Cancel a runaway job
```
1. DELETE /api/v1/jobs/{jobId}
2. GET    /api/v1/jobs/{jobId}/status        // should immediately show complete=true, error="cancelled by user"
```

---

# Auto-generated OpenAPI

FastAPI also exposes:
- `GET /openapi.json` — full machine-readable OpenAPI 3 spec
- `GET /docs` — Swagger UI (interactive)
- `GET /redoc` — ReDoc UI

These reflect the *exact* current shape of every endpoint and stay in
sync without manual edits. Use this Markdown doc for the higher-level
narrative and field semantics; use the OpenAPI for codegen.

---

_Generated against `backend/main.py` and `backend/models.py` on the
`version4` branch (backend adapted to main's `layers`/`component` schema).
Update this file whenever a route signature changes._
