# Incremental + Onboarding — Implementation Approach (POC, JSON-backed)

| | |
|---|---|
| **Document** | Incremental Changes + Project Onboarding — Implementation Approach |
| **Project** | C++ Codebase Analyzer — Production Platform (POC → Production) |
| **Status** | Draft for Review |
| **Version** | 1.0 |
| **Date** | 2026-06-17 |
| **Branch** | `version4` (off `main`: `layers`/`component` schema) |
| **Builds on** | `03-incremental-changes-design.md` §12 (v1.2 — **Approach 2** chosen) |
| **Audience** | Engineering / Architecture review |

> This is the **implementation** plan for what `03` designed. It targets the **current
> JSON-file pipeline on `version4`** (Postgres comes later) and the **`layers`/`component`**
> schema. Storage is JSON now; every store named below maps 1:1 onto a future DB table.

---

## 1. Locked decisions (from review)

| # | Decision |
|---|---|
| D1 | **A "version" = one generation run** (its own `versionId`). It records the **target branch + commit**, the **scope**, the **data-dict used**, a timestamp, and the chosen **baseline**. The target commit is stored and used to find the **nearest ancestor** for future versions. We keep **all** versions. |
| D2 | **Onboarding supplies the full `layers` structure** per project (same shape as `config.json`'s `layers`), stored per-project and injected into the run. |
| D3 | **No auto-start.** Generation is an explicit `POST …/generate` the user triggers. |
| D4 | **Scope is a request parameter** — whole project (all layers) / a layer / a group / a component. The API runs whatever scope is asked. |
| D5 | **Reuse is content-addressed across *all* versions**, regardless of scope or branch. The git-diff **baseline = nearest generated ancestor commit**. **Scope only filters which entities land in the output document**, never what may be reused. |
| D6 | **Data dictionary is per-project but replaceable per version.** A data-dict-only change → **recompute the cheap artifacts** (interface tables / data ranges at reassembly); **no forced LLM regeneration** (descriptions/flowcharts describe code behavior, not data ranges). |
| D7 | **Approach 2** (git-diff narrowed parse + stored-graph impact + selective regen), with **Approach 1's full parse as the fallback** (first generation, no ancestor, diverged history). |
| D8 | **Credentials plaintext for now** (encrypt later). One clone per project, checkout per commit, **HTTPS username+token** auth. |
| D9 | **`/api/v1/repository/*` is dropped** — `projects` supersedes it entirely. **Auth/RBAC deferred** (records carry an `ownerId` stub seam). |

---

## 2. Component boundary

```
┌─ Backend (FastAPI) ───────────────────────────────────────────────┐
│  Onboarding + projects + branches + commits + generate APIs        │
│  Git service (clone / fetch / checkout / diff / merge-base)        │
│  Per-project workspace + version registry + baseline selection     │
│  Job tracking (reuses the existing spawn/watch/log machinery)      │
└───────────────┬───────────────────────────────────────────────────┘
                │ spawns: python run.py … (full or --incremental)
┌───────────────▼───────────────────────────────────────────────────┐
│  Analyzer (version4) — Phases 1–4 + new incremental engine         │
│   parse/hash/edges · impact BFS · selective regen · reassemble     │
└────────────────────────────────────────────────────────────────────┘
```

Rule: **git + version bookkeeping live in the backend; parse / hash / impact / regen live in
the analyzer** (it owns the dependency graph). The backend never re-implements the pipeline.

---

## 3. Storage / workspace layout (`version4`, JSON now)

Everything for a project lives under one gitignored workspace. **Add `workspaces/` to
`.gitignore`.**

```
workspaces/
  index.json                       # [{projectId, name, gitUrl, latestVersionId, cloneStatus}]
  <projectId>/
    project.json                   # onboarding record (see §4) — includes plaintext token (POC)
    repo/                          # single git clone; `git checkout <commit>` per generation
    datadict/
      <dataDictId>.csv             # each uploaded data dictionary (immutable once stored)
    cache/
      outputs/<entity_key>__<fingerprint>.json   # project-wide reusable LLM outputs
    versions/
      index.json                   # [{versionId, commit, branch, scope, dataDictId, baselineVersionId, status, createdAt}]
      <versionId>/
        manifest.json              # full record incl. recipeFingerprint, counts (reused/regenerated)
        config.json                # the resolved per-run config (global clang/llm + project layers)
        hashes.json                # {entity_key -> token-sha256}        (the 4 entity types)
        edges.json                 # dependency graph: call / global / type / macro / containment (+ reverse)
        model/   output/           # pipeline artifacts for this version (browse)
        documents/                 # one or more .docx (multi-doc when component-per-docx)
```

- **`cache/outputs/`** is the **content-addressed reuse store** (the §3-D6 / §12 "global content
  cache"). Key = `<entity_key>__<fingerprint>`. It extends today's `llm_core/cache.py:EntityCache`
  to cover **descriptions, behaviour names, flowchart Mermaid, and summaries** (today it caches
  descriptions only).
- **`fingerprint`** = `sha256(entity_source_hash + sorted(dependency_source_hashes) + recipeFingerprint)`
  where the dependency closure is computed cycle-safe (visited set). `recipeFingerprint` =
  `sha256(llm.defaultModel + promptVersion + llm.cacheVersion + engineVersion)` — an operator recipe
  change flips it and invalidates everything (the §10 operator path, for free).

---

## 4. Onboarding record (`project.json`)

```jsonc
{
  "projectId": "ftl-a1b2c3",                 // slug(name) + short hash
  "name": "FTL",
  "ownerId": null,                           // RBAC seam (deferred)
  "git": {
    "url": "https://bitbucket.org/org/ftl.git",
    "username": "svc-analyzer",
    "token": "<plaintext-for-now>"           // TODO encrypt at rest (D8)
  },
  "layers": { /* full config.json `layers` block, verbatim */ },
  "defaults": { "branch": "main", "commit": "<sha>" },   // initial target (not auto-run)
  "latestDataDictId": "dd-001",
  "cloneStatus": "ready",                    // pending | cloning | ready | error
  "createdAt": "2026-06-17T10:00:00Z"
}
```

**Per-project config injection.** Before each run we write `versions/<vid>/config.json` =
**global `config/config.json` (clang + llm + views)** with its `layers` block **replaced by the
project's `layers`**. The analyzer is pointed at it via a new override (§7): an
`ANALYZER_CONFIG` env var (set by `run.py` from `--config <path>`, inherited by every phase
subprocess, honored in `core.config.load_config`). This keeps the global `config.json` untouched
and lets concurrent projects run with different `layers`.

---

## 5. End-to-end flows

### 5.1 Onboarding
```
POST /projects  (fields + data-dict file)
  -> validate, write project.json + datadict/<id>.csv
  -> async job: git clone <url> (HTTPS token) into repo/, checkout default commit
  -> cloneStatus: cloning -> ready (or error)
  (NO generation starts — D3)
```

### 5.2 Generate a version (the incremental trigger)
```
POST /projects/{id}/generate
  body: { branch, commit, scope, dataDictId? , mode? }   // mode: "auto" (default) | "full"
  |
  [0] BASELINE PICK  (this finds the ancestor — `git diff` does NOT)
      candidates = PRIOR GENERATED versions only (we need their stored model/outputs to reuse)
      keep those whose stored commit is an ancestor of the target:
          git merge-base --is-ancestor <versionCommit> <targetCommit>   (exit 0 = ancestor)
      base = nearest passing version
      NONE pass -> FULL generation (mode:"full" forces it too). We NEVER diff a non-ancestor.
  |
  [1] CHECKOUT + DETECT
      git fetch; git checkout <commit>
      FULL:        parse the whole project  (Approach-1 fallback — used ONLY when
                   there is no baseline to diff against: first generation, no
                   ancestor, diverged history, or mode:"full")
      INCREMENTAL: git diff <baseCommitSha>..<targetCommitSha> --name-only
                   -> changed files   (e.g. `git diff 9f3c..a12b --name-only`)
                   partial-parse ONLY those files -> fresh entities/hashes/edges
                   merge with base version's model (carry unchanged) -> target model
                   classify changed/new/deleted (hash vs base hashes.json)
  |
  [2] IMPACT (incremental only)
      reverse-BFS over the merged stored graph
      axes: call graph (transitive callers), type-usage, globals, macros, containment
      over-approximate virtual/fn-ptr; move/rename -> delete+add -> re-resolve callers
      -> impact set
  |
  [3] SELECTIVE REGEN
      run LLM (Phase 2 descriptions/behaviour/summaries + Phase 3 flowchart labels)
      for impact set ∩ scope only; reuse cache/baseline for the rest
      (data-dict change alone -> NO LLM; ranges refresh in step 4)
  |
  [4] REASSEMBLE  (scoped to the request)
      merge version's data-dict CSV into dataDictionary.json
      Phase 3 views + Phase 4 export over the scoped model
      -> documents/  + manifest/hashes/edges; register version
```

A "next version" is exactly step 5.2 again with a newer target commit; its `base` is found among
the **stored commits** of prior versions (D1).

---

## 6. Incremental correctness — the mandatory pieces (from `03` §12.2)

These are non-negotiable for Approach 2 (the difference between correct and **stale**):

1. **Impact runs over the stored *full* graph** (not just edges inside changed files) — so a changed
   callee in a changed file reaches its caller living in an **unchanged** file.
2. **Move/rename re-resolution** — when a callee's key changes but the caller is in an unchanged
   file, the caller is impacted **and** its file is re-parsed so its edges re-resolve.
3. **Baseline selection + full-regen fallback** — nearest generated ancestor; else full.
4. **Project-wide content cache** — cross-version reuse safety net (revert / identical code on
   another branch is not regenerated).
5. **Recipe fingerprint** — operator model/prompt/cacheVersion change invalidates cache.

Header changes: `#define`s re-hashed by the existing text-scan; types in a changed header →
re-parse one including TU (or over-approximate to TUs that include it). Bias: **over-regenerate,
never stale.**

---

## 7. Analyzer-side changes required (`version4`)

| Area | Change |
|---|---|
| `run.py` | `--config <path>` → sets `ANALYZER_CONFIG` env (inherited by phases); `--incremental --baseline-dir <versions/<base>> --changed-files <file>` path; `--data-dictionary` already exists. |
| `core/config.py` | `load_config()` honors `ANALYZER_CONFIG` (per-project config) before falling back to `config/config.json`. |
| `parser.py` | **partial-parse** a given file set; **entity hashing** (token-based **full SHA-256**, four types: function/global/macro/type, keyed by identity incl. file/location); **edge emission** (call/global/type/macro/containment). |
| `model_deriver.py` | **incremental mode**: regenerate impact set, carry the rest from baseline; **extend `EntityCache`** to behaviour names + summaries. |
| `views/flowcharts.py` (Phase-3 view) | Already filters `functions.json` → `functions_<group>.json` and **launches the `src/flowchart/` engine** via `--interface-json`. Change: restrict that functions file to the **impact set**, then merge engine output into the carried-forward `flowcharts/*.json`. **The engine itself (`src/flowchart/`) is unchanged.** |
| `src/incremental/` (new) | orchestrates detect → merge → classify → impact-BFS → selective-regen → reassemble; reads/writes the workspace `hashes.json` / `edges.json` / `cache/`. |

Most of the dependency graph already exists (parser builds call/reverse-call graphs, transitive
globals, `knowledge_base.json`); the new work is **serializing edges**, **hashing entities**, and
**partial-parse + merge**.

---

## 8. API specifications

Base: `http://<host>:8000`, prefix `/api/v1`. JSON unless noted. Errors: `{ "detail": "…" }`.
Job lifecycle (`status` / `logs` / cancel) **reuses the existing job machinery**.

### 8.1 Onboard a project
`POST /api/v1/projects`  — `multipart/form-data` (fields + the data-dict file).

| Field | Type | Notes |
|---|---|---|
| `name` | string | unique; used to derive `projectId` |
| `gitUrl` | string | HTTPS clone URL |
| `gitUsername` | string | |
| `gitToken` | string | access token / app password (plaintext for now) |
| `branch` | string | initial target branch |
| `commit` | string | initial target commit (sha) |
| `layers` | JSON string | full `layers` structure (D2) |
| `dataDictionary` | file (csv/xlsx) | optional; stored as `datadict/<id>.csv` |

**201**
```json
{ "projectId": "ftl-a1b2c3", "name": "FTL", "cloneStatus": "cloning",
  "dataDictId": "dd-001", "latestVersionId": null }
```
**Errors:** 400 (missing/invalid field, bad `layers`), 409 (name exists), 500 (write failure).
Clone runs **async**; poll `GET /projects/{id}` for `cloneStatus`.

### 8.2 List / get / update / delete projects
- `GET /api/v1/projects` → `[{ projectId, name, gitUrl, cloneStatus, latestVersionId }]`
- `GET /api/v1/projects/{projectId}` → full record (token redacted), `cloneStatus`, version count.
- `PUT /api/v1/projects/{projectId}` → update `layers` / `git` credentials / `branch` defaults.
- `DELETE /api/v1/projects/{projectId}` → remove workspace (204).

### 8.3 Branches & commits (from the local clone)
- `GET /api/v1/projects/{projectId}/branches`
  ```json
  [ { "name": "main", "lastCommit": "9f3c…", "lastCommitDate": "2026-06-15T…" },
    { "name": "feature/x", "lastCommit": "a12b…", "lastCommitDate": "2026-06-16T…" } ]
  ```
- `GET /api/v1/projects/{projectId}/branches/{branch}/commits?limit=50&offset=0`
  ```json
  { "branch": "feature/x", "total": 312,
    "commits": [ { "sha": "a12b…", "shortSha": "a12b", "message": "fix foo",
                   "author": "dev", "date": "2026-06-16T…" } ] }
  ```
  (Backend runs `git fetch` then `git for-each-ref` / `git log` on the clone; no host API.)

### 8.4 Current data dictionary (shown on the generate screen)
`GET /api/v1/projects/{projectId}/datadict` → the **current** (latest-used) data dictionary, so the
UI can display it when the user is about to generate. The user then **keeps it** (generate with no
file) or **modifies it** and sends the new CSV **inline with `generate`** (§8.5). There is **no
separate upload step** — a data dictionary only ever enters the system at onboarding or with a
generate request.
```json
{ "dataDictId": "dd-001", "filename": "ftl_dd.csv", "rows": 214,
  "downloadUrl": "/api/v1/projects/ftl-a1b2c3/datadict/dd-001/download" }
```

### 8.5 Generate a version  ← the incremental trigger
`POST /api/v1/projects/{projectId}/generate` — `multipart/form-data` so an optional **replacement
data dictionary** can ride along with the request.

| Part | Type | Notes |
|---|---|---|
| `request` | JSON string | the generation request (below) |
| `dataDictionary` | file | **optional** — a modified CSV for THIS version; **omit to reuse the current one** (§8.4) |

`request` JSON:
```json
{
  "branch": "feature/x",
  "commit": "a12b34c…",
  "scope": { "type": "project" },          // or {"type":"layer","names":["Layer1"]}
                                           //    {"type":"group","names":["My Sample"]}
                                           //    {"type":"component","names":["Gpio","Uart"]}
  "mode": "auto"                           // "auto" (incremental if ancestor exists) | "full"
}
```
**200**
```json
{ "versionId": "v-7", "jobId": "gen_4f7a1b8e", "decision": "incremental",
  "baselineVersionId": "v-5", "baselineCommit": "9f3c…", "dataDictId": "dd-002" }
```
`scope.type` maps to the analyzer flags: `project` → none, `layer` → `--selected-layer`,
`group` → `--selected-group`, `component` → repeated `--selected-component`. `decision` tells the UI
whether it ran incremental or fell back to full. When a `dataDictionary` file is sent it is stored
as a new `dataDictId` and recorded on the version; otherwise the current one is reused. A
data-dict-only change re-runs just the **cheap** reassembly (interface-table ranges), **not** the LLM
(D6).
**Errors:** 400 (bad scope/commit, project not `ready`), 404 (unknown project), 409 (commit not in repo).

### 8.6 Versions
- `GET /api/v1/projects/{projectId}/versions`
  ```json
  [ { "versionId": "v-7", "branch": "feature/x", "commit": "a12b…",
      "scope": {"type":"project"}, "dataDictId":"dd-002",
      "decision":"incremental", "regenerated": 48, "reused": 952,
      "status":"complete", "createdAt":"2026-06-17T…" } ]
  ```
- `GET /api/v1/projects/{projectId}/versions/{versionId}` → detail + per-document `downloadUrl`s.
- `GET /api/v1/projects/{projectId}/versions/{versionId}/download` → the `.docx` (or a **zip** when
  the scope produced multiple documents, e.g. `component-per-docx`).

### 8.7 Job status / logs / cancel / download  (existing endpoints — reused as-is)
Generation reuses the backend's **current** job lifecycle (the same machinery `prepare`/`export`
use today) — no new job-shaped endpoints are invented:
- `GET /api/v1/jobs/{jobId}/status` → canonical 4-phase progress; for generate jobs we add
  `decision` (incremental|full) and `regenerated`/`reused` counts.
- `GET /api/v1/jobs/{jobId}/prepare/logs` → tail of this job's stdout/stderr.
- `DELETE /api/v1/jobs/{jobId}` → full process-tree kill (cancel).
- `GET /api/v1/jobs/{jobId}/export/status` → docx-artifact readiness (`filename` + `downloadUrl`).
- `GET /api/v1/jobs/{jobId}/export/download` → stream the docx for this job.

The document is downloadable two ways: by **job** via `…/export/download` (during the session) and
by **version** via `…/versions/{versionId}/download` (§8.6, survives restarts). The only *new*
endpoints are the project/version ones in §8.1–§8.6.

### 8.8 Version-scoped reads (existing endpoints, follow-up)
`GET /components`, `/functions/{fn_id}`, `/flowcharts/{fn_id}`, `/project/structure` gain
`?projectId=&versionId=` and read that version's `model/` + `output/` (closes the single-shared-
`model/` issue). `GET/POST /config` is **deprecated for project groups** (now per-project `layers`
in `project.json`); kept only for non-project globals if needed.

---

## 9. Milestones (each independently shippable + testable)

- **M0 — Onboarding + git + FULL generation (no reuse yet).** Workspace, git service, plaintext
  creds, `projects` / `branches` / `commits` / `datadict` / `generate(full)` APIs, per-project
  `layers` config injection, version registry. *Ships the whole onboarding/git/UI story.*
- **M1 — Substrate.** Entity hashing + edge persistence per version (still full-parse). Validate
  against full runs.
- **M2 — Incremental engine (Approach 2).** Baseline pick, partial-parse + merge, classify, impact
  BFS, selective regen (LLM only for impact set), content cache, reassemble; `mode:auto`. *Delivers
  hours → minutes.*
- **M3 — Hardening.** Version-scoped reads, force-full + recipe-fingerprint invalidation,
  move/rename re-resolution polish, credential encryption, multi-doc zip download.

---

## 10. Deferred (and the Postgres seam)

- **Encryption of credentials** (D8 — plaintext now).
- **Postgres migration:** every JSON store maps to a table — `projects`, `versions`,
  `entity_hashes`, `dependency_edges`, `entity_outputs` (the content cache), `data_dictionaries`,
  `jobs`. Impact-BFS → recursive CTE / closure table; baseline ancestry → stored commit graph.
- **SSH deploy keys**, **host-API branch listing**, **image-render cache**, **per-artifact hashing**,
  **cross-version dedup** — all deferred (see `03` §22.8 / §2 deferrals).

---

_End of document._
