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
> **Implementation status:** ✅ **all endpoints below (G0, G1, G2, 1–15) are implemented** in
> [engine/main.py](../../engine/main.py); the git operations live in `engine/git_service.py` +
> `src/incremental/git_ops.py` (clone, fetch, checkout, branch/commit listing, ancestry, diff). The
> spec remains the **contract** the UI is built against.

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
{ "type": "project" }                                   // whole project (all layers)
{ "type": "layer",     "names": ["Layer1"] }            // one or more layers
{ "type": "group",     "names": ["My Sample"] }         // one or more groups
{ "type": "component", "names": ["Gpio", "Uart"] }      // one or more components
```

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
| **R1-R9** | - | `.../versions/{versionId}/overrides*`, `.../flowcharts/{token}/labels`, `.../export-readiness` | Review & Update - see section 10 |

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

### 2. POST `/projects/{projectId}/generate`
Start a generation. Returns immediately with a `jobId` (poll #6/#9) and the `versionId` being produced.
**Request fields**

| Field | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `branch` | string | **yes** | — | Branch the commit is on (recorded on the version). |
| `commit` | string | **yes** | — | Target commit SHA to generate for. |
| `scope` | object | no | `{"type":"project"}` | What to generate — see **scope object** below. |
| `mode` | string | no | `"auto"` | `"auto"` = incremental when a baseline ancestor exists, else full; `"full"` = force a full generation. |
| `baseVersionId` | string | no | `null` | Explicit baseline to diff against (e.g. `"v1"`). Omit/null = auto nearest-ancestor. **Quote it** (`"v1"`, not `v1`). |
| `dataDictId` | string | no | project's current | Data dictionary to use; omit = the project's current one. |
| `noLlm` | bool | no | `false` | `true` = fully **LLM-free** run (no descriptions / behaviour names / flowchart labels / struct summaries) — deterministic; for timing tests / offline runs. |

**scope object** (one of):

| Scope | JSON |
|---|---|
| Whole project | `{ "type": "project" }` |
| One layer | `{ "type": "layer", "names": ["Layer1"] }` |
| One group | `{ "type": "group", "names": ["Support"] }` |
| One or more components | `{ "type": "component", "names": ["Math", "App"] }` |

**Request body — examples**

*Auto (incremental if a baseline ancestor exists, else full), whole project:*
```json
{ "branch": "main", "commit": "a12b34c", "scope": { "type": "project" }, "mode": "auto" }
```
*Incremental against a specific baseline, one group:*
```json
{ "branch": "main", "commit": "a12b34c", "scope": { "type": "group", "names": ["Support"] }, "baseVersionId": "v1" }
```
*Force a full generation (ignore any baseline):*
```json
{ "branch": "main", "commit": "a12b34c", "scope": { "type": "project" }, "mode": "full" }
```
*LLM-free run (deterministic; for timing tests), one group:*
```json
{ "branch": "main", "commit": "a12b34c", "scope": { "type": "group", "names": ["Support"] }, "noLlm": true }
```
*Explicit data dictionary + selected components:*
```json
{ "branch": "main", "commit": "a12b34c", "scope": { "type": "component", "names": ["Math", "App"] }, "dataDictId": "dd-002" }
```

> **JSON gotcha (422):** every string value must be quoted — `"baseVersionId": "v1"`, **not** `"baseVersionId": v1`. An unquoted/bare value makes the body invalid JSON and the API returns **422 Unprocessable Entity** before the handler runs. In Postman use **Body → raw → JSON**.

**200**
```json
{
  "versionId": "v-7",
  "jobId": "gen_4f7a1b8e2c9d",
  "decision": "incremental",            // what it actually did: "incremental" | "full"
  "baselineVersionId": "v-4",           // null when full
  "baselineCommit": "9f3c1a…",
  "dataDictId": "dd-002",
  "warnings": []
}
```
**Notes:** the **data dictionary file is uploaded by a separate (onboarding) API**; here you only
*reference* one by `dataDictId` (or omit to use the project's current). A data-dict-only change
re-runs only the cheap document assembly, not the LLM.
**Errors:** 400 (bad scope/commit/base/dataDictId), 404 (unknown project), 409 (commit not in repo).

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


## 10. Review & Update - correcting the LLM's text

A reviewer reads the generated document and corrects wording the LLM got wrong. The correction is
stored with the LLM original beside it, shows in the HTML view, reaches the exported DOCX, and
survives a regeneration.

Requirements: [REVIEW_UPDATE_SPEC](../spec/REVIEW_UPDATE_SPEC.md) (`REQ-` ids below) ·
design: [REVIEW_UPDATE_DESIGN](../design/REVIEW_UPDATE_DESIGN.md).

### 10.1 What can be edited

Seven **slot kinds** (`REQ-ED-01`). Every request names one:

| `slotKind` | what it is |
|---|---|
| `description` | a function's or global's description |
| `behaviourInputName` | the behaviour table's input name |
| `behaviourOutputName` | the behaviour table's output name |
| `behaviourDescription` | a Dynamic Behaviour row - a **list** of bullets, edited as one block |
| `unitDescription` | a unit's description |
| `structDescription` | a struct's description |
| `nodeLabel` | one flowchart node's label |

### 10.2 Slot keys, and why they are not in the path

A `slotKey` addresses one slot. It is **built by the server** and returned to you - never assembled
in the UI (`REQ-ID-01`).

| `slotKind` | `slotKey` |
|---|---|
| `description`, `behaviourInputName`, `behaviourOutputName`, `structDescription` | the entity key |
| `unitDescription` | the unit key, `Component|Unit` |
| `behaviourDescription` | `functionId` + `U+0001` + `externalCallerId` |
| `nodeLabel` | `entityKey` + `U+0001` + `nodeId` |

A key contains `|`, `:`, `,`, `*`, spaces and a `U+0001` separator, so **keys travel in the body or
a query parameter, never in a path segment.** The one exception is `{flowchartToken}`, which is the
flowchart id in base64url (no padding) - its alphabet is `[A-Za-z0-9_-]`, so nothing needs
escaping.

### 10.3 Endpoint index

| # | Method | Path | Purpose |
|---|---|---|---|
| **R1** | GET | `/projects/{projectId}/versions/{versionId}/overrides` | The corrections in a version (an overlay - see 10.4) |
| **R2** | GET | `/projects/{projectId}/versions/{versionId}/overrides/slot` | One slot's correction |
| **R3** | PUT | `/projects/{projectId}/versions/{versionId}/overrides/slot` | Correct one slot |
| **R4** | DELETE | `/projects/{projectId}/versions/{versionId}/overrides/slot` | Undo - restore the LLM original |
| **R5** | GET | `/projects/{projectId}/versions/{versionId}/overrides/history` | The retained edits of one slot |
| **R6** | PUT | `/projects/{projectId}/versions/{versionId}/overrides/behaviour` | Correct one Dynamic Behaviour row |
| **R7** | GET | `/projects/{projectId}/versions/{versionId}/flowcharts/{flowchartToken}/labels` | Every node label of one flowchart |
| **R8** | PUT | `/projects/{projectId}/versions/{versionId}/flowcharts/{flowchartToken}/labels` | Correct a flowchart, one call |
| **R9** | GET | `/projects/{projectId}/versions/{versionId}/export-readiness` | Would exporting now ship stale text? |

All require project **membership** (`REQ-API-05`).

### 10.4 R1. GET `.../overrides`

**This is an overlay, not a list of every slot.** A version holds roughly **57,000** slots, so
enumerating them would rebuild the document you already fetched from `/components`, `/functions`
and `/flowcharts`. Fetch this and merge by `slotKey`; a version nobody has corrected returns an
empty list.

Query: `slotKind` (optional), `limit` (1-1000, default 200), `offset`.

**200**
```json
{
  "overrides": [
    {
      "slotKind": "description",
      "slotKey": "Gpio|GpioDrv|Gpio_Init|void",
      "llmText": "Initializes the module.",
      "humanText": "Initialises the GPIO driver and clears pending interrupts.",
      "isOrphaned": false,
      "updatedBy": "u-17",
      "updatedAt": "2026-09-18T09:14:22Z"
    }
  ],
  "total": 1, "limit": 200, "offset": 0
}
```

`isOrphaned` - the slot stopped resolving (the function was renamed or deleted). The correction is
**kept**, never auto-deleted (`REQ-ID-03`), and is not applied to the document.

### 10.5 R2 / R3 / R4. One slot

**R2 GET** `.../overrides/slot?slotKind=&slotKey=` returns the object above, or **404** when that
slot has no correction.

**R3 PUT** `.../overrides/slot`
```json
{ "slotKind": "description",
  "slotKey": "Gpio|GpioDrv|Gpio_Init|void",
  "text": "Initialises the GPIO driver and clears pending interrupts." }
```
**200**
```json
{ "slotKind": "description", "slotKey": "Gpio|GpioDrv|Gpio_Init|void",
  "humanText": "Initialises the GPIO driver and clears pending interrupts.",
  "llmText": "Initializes the module.",
  "previousText": "Initializes the module.",
  "firstEdit": true, "viewsDerived": ["interfaceTables"] }
```

`llmText` is captured on the **first** edit and never rewritten (`REQ-ST-03`) - it is what undo
restores and the "wrong" half of the training pair. `previousText` is what this call replaced.

Not offered for `nodeLabel` (use R8) or `behaviourDescription` (use R6).

**R4 DELETE** `.../overrides/slot?slotKind=&slotKey=` - undo (`REQ-API-04`).

Undo is an ordinary edit whose text happens to be the original, so **the record survives** with
both texts and its history. **409** when there is no original to restore, which happens when the
slot was empty before the first correction.

### 10.6 R6. PUT `.../overrides/behaviour`

A Dynamic Behaviour row is a **list** of bullets, one per call arrow, edited as one block
(`REQ-ED-02`).

```json
{ "functionId": "Gpio|GpioDrv|Gpio_Init|void",
  "externalCallerId": "App|AppMain|App_Start|void",
  "bullets": ["App_Start calls Gpio_Init to bring the port up",
              "Gpio_Init returns the port state"] }
```

**Both ids are entity keys.** Not the row's `externalUnitFunction` display label - that is
`"<unit> - <name>"` and two different callers can share one, so a correction addressed by it would
land on the wrong row (`REQ-ID-01`).

Each bullet is collapsed onto one line. A correction here renders **no image**: the description is
not in the diagram, whose arrows are labelled with the callee's name.

### 10.7 R7 / R8. A flowchart, in one call

A flowchart **is one function's control-flow graph**, so `flowchartToken` is that function's entity
key, base64url-encoded (`REQ-ID-04`).

**R7 GET** `.../flowcharts/{flowchartToken}/labels`
```json
{ "flowchartId": "Gpio|GpioDrv|Gpio_Init|void",
  "flowchartToken": "R3Bpb3xHcGlvRHJ2fEdwaW9fSW5pdHx2b2lk",
  "functionName": "Gpio_Init",
  "labels": [
    { "nodeId": "n0", "text": "Start", "llmText": null, "isOverridden": false },
    { "nodeId": "n7", "text": "Check the write-protect flag",
      "llmText": "Check flag", "isOverridden": true }
  ] }
```

**R8 PUT** `.../flowcharts/{flowchartToken}/labels`
```json
{ "labels": { "n7": "Check the write-protect flag", "n9": "Increment the retry count" } }
```

Three rules (`REQ-API-08`):

1. **Send only the labels the reviewer changed.** Not the whole flowchart. A stale copy of an
   untouched label would overwrite a correction somebody else made to it seconds earlier, and the
   server cannot tell that from a deliberate revert.
2. **All or nothing.** If any label is rejected - empty text, or a node that no longer exists -
   nothing is written and the response names the node.
3. **One re-render per call**, however many labels it carried.

**200**
```json
{ "flowchartId": "Gpio|GpioDrv|Gpio_Init|void",
  "applied": ["n7", "n9"], "firstEdits": ["n9"],
  "slotShape": "9f2c...", "renderPending": true,
  "viewsDerived": ["flowcharts", "testSpecs"] }
```

`renderPending` - the picture is being redrawn; the text is already stored. `slotShape` identifies
the graph the correction was written against, so it is not reused later against a renumbered one.

Each label is stored as **its own record** with its own original and history, even though the API
is per flowchart. The two granularities are deliberately different (`REQ-ST-07`).

### 10.8 R5. GET `.../overrides/history`

`?slotKind=&slotKey=` returns the retained edits of one slot, oldest first, bounded by
`llm.overrideHistoryDepth` (`REQ-ST-04`). The LLM original is **not** in here - it is on the
override itself, which is what makes "the original is never evicted by the cap" structural.

```json
{ "history": [ { "seq": 1, "humanText": "...", "updatedBy": "u-17",
                 "updatedAt": "2026-09-18T09:14:22Z" } ] }
```

### 10.9 R9. GET `.../export-readiness`

Whether exporting now would ship text a correction has already replaced (`REQ-AP-04`). Call it
before offering a download.

**200**
```json
{ "stale": true,
  "reason": "a correction is newer than the derived output",
  "explanation": "a correction is newer than the derived output (3 correction(s) in this version)",
  "overrideCount": 3,
  "newestOverrideAt": "2026-09-18T09:14:22Z",
  "oldestDerivationAt": "2026-09-18T08:02:10Z" }
```

`stale: true` means the views need re-deriving - `reexport --from-phase 3`. The CLI refuses a stale
`--from-phase 4` export for the same reason.

### 10.10 Errors

| Code | When |
|---|---|
| 400 | malformed slot key or flowchart token |
| 403 | not a member of the project |
| 404 | unknown version, slot, flowchart, or a node named in a flowchart save |
| 409 | undo with no LLM original to restore |
| 422 | empty or whitespace-only text (`REQ-ST-06`) |
| 501 | a slot kind that has no save path in this build |
| 503 | no database configured - corrections live nowhere else, so the write is refused rather than dropped |

Two people editing the same slot: **last write wins**, no locking and no conflict response
(`REQ-API-07`). Sending only changed labels (10.7) is what keeps that true *per slot* when a whole
flowchart is saved at once.

---

_End of document._
