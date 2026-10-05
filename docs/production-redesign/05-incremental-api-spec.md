# Incremental Feature — API Specification (for UI integration)

| | |
|---|---|
| **Document** | Incremental Document Generation — HTTP API Specification |
| **Project** | C++ Codebase Analyzer — Production Platform (POC → Production) |
| **Status** | Spec for UI integration |
| **Version** | 1.0 |
| **Date** | 2026-06-18 |
| **Branch** | `version4` |
| **Audience** | UI / frontend engineer |
| **Design ref** | `04-incremental-changes-implementation.md` (approach + storage model) |

> This is the **HTTP API the UI calls** to drive **incremental document generation** (generate a new
> document *version* for a commit, reusing unchanged work). It covers the **git-read** endpoints and the
> **incremental generate / versions** endpoints.
>
> **Onboarding is a separate workstream** (project registration, git credentials, the initial clone,
> the project's `layers` config, the data-dictionary upload). This spec **assumes a project already
> exists** and you have its `projectId`. Onboarding endpoints are **not** specified here.
>
> **Implementation status:** these endpoints were implemented in `engine/main.py`, a standalone
> service that no longer exists: the API server in `api/` replaced it. **Starting a generation is
> `POST /api/v1/projects/{projectId}/jobs`**, documented in §5.2 below with its current request
> body; the rest of this document is the record of the original contract. The scope object (§1)
> is current.

---

## 1. Conventions

- **Base URL:** `http://<host>:8000`
- **Path prefix:** `/api/v1`
- **Content-Type:** `application/json` for all requests/responses (downloads stream binary).
- **Error shape (4xx/5xx):**
  ```json
  { "detail": "human-readable error string" }
  ```
  Pydantic validation failures return `422` with a `detail` array.

### Status codes
| Code | Meaning |
|---|---|
| 200 | OK |
| 202 | Accepted (a long job was started; poll its status) |
| 400 | Bad request (invalid scope / commit / base / dataDictId) |
| 404 | Not found (unknown project / version / job / commit) |
| 409 | Conflict (e.g. download before the job is complete) |
| 422 | Body failed schema validation |
| 500 | Server error |

### Identifiers
| Name | Format / example |
|---|---|
| `projectId` | opaque id from onboarding, e.g. `ftl-a1b2c3` |
| `versionId` | `v-7` (one document generation) |
| `commit` | full or short git SHA, e.g. `a12b34c…` |
| `branch` | git branch name, e.g. `main`, `feature/x` |
| `fn_id` | composite function key `component|unit|qualifiedName|paramTypes`, e.g. `Sample-Core|Core|init|` (component segment is space-normalized: `"Sample Core"` → `Sample-Core`) |
| `dataDictId` | id of an uploaded data dictionary (managed by onboarding), e.g. `dd-002` |

### The `scope` object (used by generate / preview)
Selects how much of the project the document covers:
```jsonc
{ "type": "project" }                                          // whole project (all layers)
{ "type": "layer",     "names": ["Layer1"] }                   // one or more layers, by name
{ "type": "group",     "names": ["Layer1.My Sample"] }         // one or more groups
{ "type": "component", "names": ["Layer1.Sample Core"] }       // one or more components
```
Groups and components are named by their **layer-qualified id**, `<Layer>.<Name>`: two layers may
use the same name (SampleCppProject's Layer1 and Layer2 both have `My Sample` / `Sample Core`), and
a bare name that matches two is refused, **400 `INVALID_SCOPE`** with the `candidates`. A bare name
only one layer uses still resolves; case and spaces never decide (`layer1.my sample` is
`Layer1.My Sample`).

---

## 2. Backend git operations (already implemented — `git_service.py`)

These back the UI-facing endpoints; you do **not** call them directly, but it's useful to know what
exists:

| Function | Purpose |
|---|---|
| `clone_repo(url, user, token, dest)` | clone a repo (HTTPS + token); used by **onboarding** |
| `fetch / checkout / current_commit` | update the clone / move to a commit (used by generation) |
| `list_branches(repo)` | → the **G1** endpoint |
| `list_commits(repo, branch, limit, offset)` | → the **G2** endpoint |
| `is_ancestor / nearest_ancestor / merge_base` | baseline selection (used by **preview** / **generate**) |
| `changed_files(repo, base, target)` | `git diff --name-only` (used by incremental generation) |

---

## 3. Endpoint index

| # | Method | Path | Purpose |
|---|---|---|---|
| **G0** | GET | `/projects` | List onboarded projects (call FIRST to get `projectId`) |
| **G1** | GET | `/projects/{projectId}/branches` | List branches |
| **G2** | GET | `/projects/{projectId}/branches/{branch}/commits` | List commits of a branch (paged) |
| **1** | GET | `/projects/{projectId}/generate/preview` | Preview the plan (baseline, incremental/full, warnings) — call BEFORE generate |
| **2** | POST | `/projects/{projectId}/generate` | Start a generation → returns a `jobId` + `versionId` |
| **3** | GET | `/projects/{projectId}/versions` | List generated versions |
| **4** | GET | `/projects/{projectId}/versions/{versionId}` | Version detail |
| **5** | GET | `/projects/{projectId}/versions/{versionId}/download` | Download the document(s) |
| **6** | GET | `/jobs/{jobId}/status` | Job progress (4-phase) |
| **7** | GET | `/jobs/{jobId}/prepare/logs` | Tail of the job's logs |
| **8** | DELETE | `/jobs/{jobId}` | Cancel a running job |
| **9** | GET | `/jobs/{jobId}/export/status` | Document-artifact readiness + downloadUrl |
| **10** | GET | `/jobs/{jobId}/export/download` | Stream the document (by job) |
| **11** | GET | `/components?projectId=&versionId=` | Component / unit / function tree of a version |
| **12** | GET / PATCH | `/functions/{fn_id}?projectId=&versionId=` | Function detail / edit description |
| **13** | GET | `/flowcharts/{fn_id}?projectId=&versionId=` | Raw Mermaid for one function |
| **14** | GET | `/config?projectId=` | Resolved config used (read-only) |
| **15** | GET | `/project/structure?projectId=` | Source tree of the checked-out commit |

---

## 4. Projects & git reads

### G0. GET `/projects`
List every onboarded project. **The UI calls this first** — every other endpoint needs a
`projectId`, and this is how it's discovered. A project is a `workspaces/<projectId>/`
directory with a `project.json` (created by onboarding).
**200**
```json
[
  {
    "projectId": "samplecpp",
    "name": "SampleCppProject",
    "repoUrl": "https://github.com/acme/SampleCppProject.git",
    "defaultBranch": "main",
    "currentDataDictId": "dd-001",
    "versionCount": 2,
    "latestVersionId": "v2"
  }
]
```
Returns `[]` when no projects are onboarded. (Onboarding/registration of a new project is a
separate workstream — see §1.)

### G1. GET `/projects/{projectId}/branches`
List the project's branches (newest commit first).
**200**
```json
[
  { "name": "main",      "lastCommit": "9f3c1a…", "lastCommitDate": "2026-06-15T10:22:00Z" },
  { "name": "feature/x", "lastCommit": "a12b34…", "lastCommitDate": "2026-06-16T08:05:00Z" }
]
```
**Errors:** 404 (unknown project).

### G2. GET `/projects/{projectId}/branches/{branch}/commits?limit=50&offset=0`
List commits of a branch, newest first, paged.
**200**
```json
{
  "branch": "feature/x",
  "total": 312,
  "commits": [
    { "sha": "a12b34c…", "shortSha": "a12b34c", "author": "dev", "date": "2026-06-16T08:05:00Z", "message": "fix foo" },
    { "sha": "9988ee1…", "shortSha": "9988ee1", "author": "dev", "date": "2026-06-15T17:40:00Z", "message": "add bar" }
  ]
}
```
**Query:** `limit` (default 50), `offset` (default 0). **Errors:** 404 (unknown project / branch).

---

## 5. Incremental generation

### 1. GET `/projects/{projectId}/generate/preview?commit=<sha>&baseVersionId=<vid?>`
**Call this BEFORE `generate`.** Read-only — changes nothing. Shows what the generation *would* do so
the user can confirm or pick a different base. `baseVersionId` is optional (omit to preview the
auto-chosen nearest-ancestor baseline).
**200**
```json
{
  "targetCommit": "a12b34c…",
  "autoBaselineVersionId": "v-4",       // nearest-ancestor version (null → would be a FULL generation)
  "autoBaselineCommit": "9f3c1a…",
  "chosenBaseVersionId": "v-2",         // echoes ?baseVersionId if supplied, else = auto
  "chosenIsAncestor": true,             // is the chosen base an ancestor of the target?
  "chosenIsNearest": false,             // is it the *nearest* ancestor?
  "changedFiles": 12,                   // git diff <base>..<target> file count for the chosen base
  "decision": "incremental",            // "incremental" | "full"
  "warnings": [
    "v-2 is an ancestor but not the nearest (v-4); v-4 will be faster"
  ]
}
```
**Warnings the UI should surface:**
- *not an ancestor* → "this base is on a divergent branch; the run will be close to a full generation (correct, but slow)."
- *not the nearest* → "v-N is the nearest ancestor and will be faster."
**Errors:** 400 (bad commit/base), 404 (unknown project), 409 (commit not in repo).

### 2. POST `/projects/{projectId}/jobs` — start a generation

Was `POST /projects/{projectId}/generate` (camelCase body, `engine/main.py`). Project **admin** only.
Returns **202** at once; follow the job with `GET /projects/{projectId}/jobs/{jobId}` or the
`GET …/jobs/{jobId}/events` stream. Request and response fields are `snake_case`
(`api/routes/jobs.py` `StartJobRequest`).

**Request fields**

| Field | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `commit_sha` | string | **yes** | — | Full 40-character commit id to generate for. The branch is the commit's (else the project's default). |
| `version_tag` | string | **yes** | — | The version's name, **new in the project**: a used one is 409 `VERSION_EXISTS`. A failed or cancelled job frees its tag. |
| `scope` | object | no | whole project | What to generate — the **scope object**, §1. Groups and components by their layer-qualified id. |
| `mode` | string | no | `"auto"` | `"auto"` = incremental when a baseline ancestor exists, else full; `"full"` = force a full generation. |
| `reference_version_id` | string | no | `null` | Explicit baseline, one of this project's versions (its id or tag). Omit = nearest ancestor. |
| `data_dict_id` | string | no | `null` | An uploaded data dictionary to merge in. |
| `no_llm` | bool | no | `false` | `true` = fully **LLM-free** run (no descriptions / behaviour names / flowchart labels / struct summaries) — deterministic; for timing tests / offline runs. |
| `narrowed_parse` | bool | no | `true` | `false` = re-parse everything in an incremental run. |

**Request body — examples** (SampleCppProject's architecture: `engine/config/api_start_job.*.example.json`)

*Auto (incremental if a baseline ancestor exists, else full), whole project:*
```json
{ "commit_sha": "<full 40-character commit id>", "version_tag": "v1", "mode": "auto" }
```
*Incremental against a specific baseline, one group:*
```json
{ "commit_sha": "<full 40-character commit id>", "version_tag": "v2",
  "scope": { "type": "group", "names": ["Layer1.Support"] }, "reference_version_id": "v1" }
```
*Force a full generation, one component:*
```json
{ "commit_sha": "<full 40-character commit id>", "version_tag": "v1", "mode": "full",
  "scope": { "type": "component", "names": ["Layer1.Sample Core"] } }
```
*LLM-free run (deterministic; for timing tests), one group:*
```json
{ "commit_sha": "<full 40-character commit id>", "version_tag": "v1", "mode": "full",
  "scope": { "type": "group", "names": ["Layer1.My Sample"] }, "no_llm": true }
```
*Explicit data dictionary + several components:*
```json
{ "commit_sha": "<full 40-character commit id>", "version_tag": "v3",
  "scope": { "type": "component", "names": ["Layer1.Math", "Layer1.App"] }, "data_dict_id": "dd-002" }
```

> **JSON gotcha (422):** every string value must be quoted — `"version_tag": "v1"`, **not** `"version_tag": v1`. An unquoted/bare value makes the body invalid JSON and the API returns **422 Unprocessable Entity** before the handler runs. In Postman use **Body → raw → JSON**.

**202**
```json
{ "job_id": "job4f7a1b8e", "status": "queued" }
```
The job (`GET …/jobs/{jobId}` → `{"job": {…}}`) carries `version_id` (the generated `ver…` id),
`version_tag`, `status` (`queued` → `running` → `complete` | `failed` | `cancelled`), `phase`,
`error_message`, and once done `decision` (`incremental` | `full`).

**Errors**

| Code | When |
|---|---|
| 400 `VALIDATION_ERROR` | no `version_tag`; `mode: "reexport"` or `"export"` (each has its own route) |
| 400 `INVALID_SCOPE` | a scope name that matches nothing, or two layers (`candidates` lists the choices); an unknown scope `type` |
| 403 | not a project admin |
| 404 | unknown project; a `reference_version_id` that is not one of this project's versions |
| 409 `VERSION_EXISTS` | `version_tag` used by a version that is running or finished |
| 409 `JOB_ALREADY_RUNNING` | the project has a job queued or running |
| 409 `NO_ARCHITECTURE` | the project was onboarded with `analyzer.py onboard` — generate it with `analyzer.py generate` |

---

## 6. Versions

### 3. GET `/projects/{projectId}/versions`
List all generated versions (newest first).
**200**
```json
[
  {
    "versionId": "v-7", "branch": "feature/x", "commit": "a12b34c…",
    "scope": { "type": "project" }, "dataDictId": "dd-002",
    "decision": "incremental", "baselineVersionId": "v-4",
    "regenerated": 48, "reused": 952,
    "status": "complete", "createdAt": "2026-06-18T10:00:00Z"
  }
]
```
`status`: `running` | `complete` | `failed`. `regenerated`/`reused` = entity counts (the reuse payoff).

### 4. GET `/projects/{projectId}/versions/{versionId}`
Full detail of one version, including a download link per produced document.
**200**
```json
{
  "versionId": "v-7", "branch": "feature/x", "commit": "a12b34c…",
  "scope": { "type": "project" }, "dataDictId": "dd-002",
  "decision": "incremental", "baselineVersionId": "v-4",
  "regenerated": 48, "reused": 952, "status": "complete",
  "createdAt": "2026-06-18T10:00:00Z",
  "documents": [
    { "name": "software_detailed_design_All.docx", "downloadUrl": "/api/v1/projects/ftl-a1b2c3/versions/v-7/download" }
  ]
}
```
**Errors:** 404 (unknown project / version).

### 5. GET `/projects/{projectId}/versions/{versionId}/download`
Streams the document. A single `.docx` for one-document scopes, or a **`.zip`** when the scope produced
several documents (e.g. one per component).
**200:** binary (`Content-Disposition: attachment; filename="…"`).
**Errors:** 404 (unknown version / file missing), 409 (version not complete).

---

## 7. Job lifecycle (shared with the existing pipeline)

A `generate` call returns a `jobId`. Poll these until the job completes, then download.

> **Survives a backend restart.** Job metadata is persisted to `logs/jobs/<jobId>.json`, so
> `/jobs/{jobId}/status` and `/jobs/{jobId}/prepare/logs` keep working after a `uvicorn`
> restart (they reload the job and reconcile its final state from the version manifest —
> which the generation subprocess writes). A job that was mid-run when the backend died is
> reported `complete` with an `interrupted (...)` error if its process is gone, or kept
> `running` if the (orphaned) subprocess is still alive.

### 6. GET `/jobs/{jobId}/status`
```json
{
  "jobId": "gen_4f7a1b8e2c9d",
  "type": "generate",
  "complete": false,
  "progress": 50,                 // within-current-phase %
  "overallProgress": 68,          // monotonic 0..100
  "phase": "Generate views",      // current phase label
  "phaseNumber": 3,               // 1=Parse 2=Derive 3=Views 4=Export
  "totalPhase": 4,
  "decision": "incremental",      // generate-job extras
  "regenerated": 48, "reused": 952,
  "error": null
}
```
**UI tip:** bind the progress bar to `overallProgress` (always monotonic); show `phase` as the label.
**Errors:** 404 (unknown job).

### 7. GET `/jobs/{jobId}/prepare/logs`
Up to the most recent log lines from the run. Works for **both `generate` and `prepare`
jobs** (the `jobId` returned by `POST /generate` is valid here). **400** if the job has no
tailable logs (e.g. an export job — use #9/#10 for those); **404** for an unknown job.
```json
[ { "id": "0", "t": "10:00:01", "level": "info", "msg": "[1/4] === Phase 1: Parse C++ source ===" } ]
```

### 8. DELETE `/jobs/{jobId}`
Cancel a running job (full process-tree kill). Idempotent.
```json
{ "status": "cancelled" }
```

### 9. GET `/jobs/{jobId}/export/status`
Document-artifact readiness — poll until `complete`, then use `downloadUrl`.
```json
{
  "jobId": "gen_4f7a1b8e2c9d", "complete": true, "stage": "done",
  "phase": "", "phaseNumber": 4, "totalPhase": 4,
  "progress": 100, "overallProgress": 100, "error": null,
  "filename": "software_detailed_design_All.docx",
  "downloadUrl": "/api/v1/jobs/gen_4f7a1b8e2c9d/export/download",
  "versionId": "v-7"
}
```
`stage`: `running` | `done` | `failed` | `cancelled`.

### 10. GET `/jobs/{jobId}/export/download`
Streams the document for this job (same content as endpoint #5, but addressed by `jobId` during the
session). **Errors:** 404 (file missing), 409 (job not complete / failed).

> **Two ways to download:** by **job** (#10 — during the session) and by **version** (#5 — survives a
> backend restart). Prefer #5 for browsing history.

---

## 8. Browsing a generated version (version-scoped reads)

These read **one version's** results (pass `?projectId=&versionId=`).

### 11. GET `/components?projectId=&versionId=`
Component / unit / function tree of the version.
```jsonc
{
  "id": "FTL", "code": "FTL", "name": "FTL", "desc": "",
  "modules": [
    { "id": "My Sample", "name": "My Sample", "path": "My Sample", "files": 6,
      "tree": { "id": "My Sample", "type": "submodule", "name": "My Sample",
        "children": [ { "id": "Sample Core", "type": "submodule", "name": "Sample Core",
          "children": [ { "id": "Sample-Core|Core|init|", "type": "fn", "name": "init" } ] } ] } }
    /* Full, Support, Platform, … */
  ]
}
```

### 12. GET / PATCH `/functions/{fn_id}?projectId=&versionId=`
**GET** — function detail:
```json
{
  "id": "Sample-Core|Core|init|", "name": "init",
  "file": "Layer1/Sample/Core/Core.cpp", "line": "12", "ret": "void",
  "description": "Initializes the core subsystem.",
  "callers": [],
  "callees": [ { "id": "Lib|Lib|add|int,int", "name": "add", "loc": "0" } ],
  "flowchart": "flowchart TD\n  N1([Start: init])\n  ...",
  "hidden": false
}
```
**PATCH** — edit the description (persists to that version's model):
Request `{ "description": "new text" }` → `{ "fnId": "Sample-Core|Core|init|", "savedAt": "14:32" }`.

### 13. GET `/flowcharts/{fn_id}?projectId=&versionId=`
```json
{ "id": "Sample-Core|Core|init|", "name": "init", "code": "flowchart TD\n  N1([Start: init])\n  ..." }
```

### 14. GET `/config?projectId=`
The resolved analyzer config used for the project (read-only).

### 15. GET `/project/structure?projectId=`
Directory/file tree of the checked-out source. Directories have `children`; files do not.
```json
{ "name": "SampleCppProject", "children": [
  { "name": "Layer1", "children": [ { "name": "Sample", "children": [ { "name": "Core", "children": [] } ] } ] }
] }
```

---

## 9. Recommended UI flow

```
A. Pick a target
   1. GET /projects/{id}/branches                          → branch list
   2. GET /projects/{id}/branches/{branch}/commits         → commit list (user picks one)

B. Preview & confirm
   3. GET /projects/{id}/generate/preview?commit=<sha>     → show incremental/full, baseline, #changed files, warnings
      (optional) user picks a different base → re-call with &baseVersionId=<vid>

C. Generate
   4. POST /projects/{id}/generate { branch, commit, scope, mode:"auto" }   → { jobId, versionId, decision }

D. Track
   5. loop GET /jobs/{jobId}/status                        → progress bar (overallProgress) + phase
      (optional) GET /jobs/{jobId}/prepare/logs            → log panel
   6. GET /jobs/{jobId}/export/status                      → wait stage="done", get downloadUrl

E. Use the result
   7. GET /jobs/{jobId}/export/download   (or  GET /projects/{id}/versions/{versionId}/download)
   8. GET /projects/{id}/versions                          → version history
   9. browse: GET /components / /functions / /flowcharts  (?projectId=&versionId=)
```

---

_End of document._
