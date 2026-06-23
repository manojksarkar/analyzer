# Incremental Changes — Implementation Approach (POC, JSON-backed)

| | |
|---|---|
| **Document** | Incremental Changes (Delta Regeneration) — Implementation Approach |
| **Project** | C++ Codebase Analyzer — Production Platform (POC → Production) |
| **Status** | Draft for Review |
| **Version** | 2.3 |
| **Date** | 2026-06-23 |
| **Branch** | `version4` (off `main`: `layers`/`component` schema) |
| **Builds on** | `03-incremental-changes-design.md` §12 (v1.2 — **Approach 2** chosen) |
| **Scope note** | **Onboarding is a SEPARATE workstream (other engineer).** This doc covers **incremental generation only** and *consumes* what onboarding produces (see §2). |

> Implementation plan for doc 03's **Approach 2** on the current JSON pipeline (`version4`,
> `layers`/`component` schema). Postgres comes later; every JSON store named here maps 1:1 onto a
> future DB table.

---

## 1. Purpose & scope

**Goal:** regenerate the document for a new commit by **reusing** everything that didn't change and
**regenerating only what changed (plus what depends on it)** — *hours → minutes* — with **no stale
content**.

**In scope (this doc):** the version model, per-version storage, the cross-version reuse index,
the `detect → impact → regenerate → reassemble` engine, baseline selection, the analyzer-side
changes, and **all incremental APIs**.

**Out of scope (other engineer's workstream — "onboarding / project management"):** registering a
project, providing git URL / credentials, the initial clone, the project's `layers` config, browsing
the project tree. This feature **consumes** those (see §2) and never creates them.

---

## 2. What incremental *consumes* (provided by onboarding / project-mgmt)

Incremental generation assumes a project already exists and reads these — it does **not** create them:

| Input | Provided by | Used for |
|---|---|---|
| `projectId` | onboarding | identifies the workspace |
| `repo/` (git clone) | onboarding | `git checkout` / `diff` / ancestry per generation |
| `layers` config (the project's) | onboarding | injected per-run so the analyzer parses the right components |
| current data dictionary | onboarding (replaceable per version — §5 step 7) | interface-table ranges + LLM type context |
| target `branch` + `commit` | the UI (picked from the project-mgmt git browser) | the commit to generate for |

The shared git helper `backend/git_service.py` (already built) backs both workstreams: onboarding
uses `clone_repo`/`list_branches`/`list_commits`; incremental uses `checkout`/`changed_files`/
`is_ancestor`/`nearest_ancestor`.

---

## 3. Locked decisions

| # | Decision |
|---|---|
| D1 | **A "version" = one generation run** (`versionId`). It records `{branch, commit, scope, dataDictId, baselineVersionId, counts, createdAt}`. The **commit** is stored and used to find the **ancestor** for future versions. **All versions kept.** |
| D2 | **Approach 2** — stored-graph impact + selective regen, with **full parse as the fallback** (first version, no ancestor, or `mode:"full"`). *Parse strategy refined by **D10** below: full parse now, narrowed parse = §11 / M4.* |
| D3 | **Reuse is content-addressed across *all* versions** via a fingerprint **pointer index** (`cache/index.json`) — the output content is **never duplicated**; the index points at the version where it already lives. The baseline **only narrows the parse**; it never limits reuse. |
| D4 | **Baseline = auto nearest-ancestor (default).** The user may **override** with an explicit `baseVersionId`; the system **warns** if it is not an ancestor / not the nearest, but still runs it (correct, slower). See §6. |
| D5 | **Scope is a request parameter** — whole project (all layers) / a layer / a group / a component → maps to `--selected-layer` / `--selected-group` / `--selected-component`. |
| D6 | **Data dictionary is per-version, replaceable.** A data-dict-only change → recompute the **cheap** interface-table ranges at reassembly; **no forced LLM regeneration**. |
| D7 | **Bias to over-regenerate, never stale** — every ambiguous case (indirect/virtual calls, move/rename, non-ancestor base) regenerates *more*. |
| D8 | **Auth (POC) = plaintext credentials.** For HTTPS, `username:token` is injected into the clone/fetch URL, then the clone's `origin` is reset to the credential-free URL so the token is **not** persisted in `.git/config`; the token is never logged. Production graduation: a deployment-appropriate secrets store (K8s Secrets / Vault / env injection). Implemented in `backend/git_service.py`. |
| D9 | **All incremental-store access goes through a thin interface** (`src/incremental/stores.py`: `VersionStore`, `ReuseIndex`, `HashStore`, `EdgeStore`) — a **JSON-file** implementation now, a **Postgres** implementation later behind the *same* methods. The §5 engine and the APIs call only the interface — no scattered `open()` / `json.load`. This makes the §10 "Postgres seam" a **swap of one implementation**, not a refactor. **Scope: the incremental *metadata* stores only** (versions / hashes / edges / reuse-index / jobs); the analyzer's per-version `model/`+`output/` artifacts stay file-based until the DB-native pipeline rewrite (`03`/§22.3). |
| D10 | **Parse strategy = FULL parse now; narrowed (incremental) parse = M4 (designed in §11, deferred).** Every incremental generation runs a full libclang parse (Phase 1), so the call graph is **correct by construction** and impact analysis can never go stale. The hours→minutes win comes from **selective LLM regeneration**, *not* from narrowing the parse — the parse is cheap next to the LLM. Narrowed parse (parse only the TUs whose preprocessed input changed, reuse the baseline model for the rest) is fully specced in **§11** and scheduled as **M4**; implement it once Phase-1 parse time is the **measured** bottleneck on a large codebase. |

---

## 4. Directory structure (per project)

Ownership matters: **onboarding owns the top of the tree; incremental owns `cache/` and
`versions/`** (and may add per-version data dicts).

```
workspaces/
  <projectId>/
    project.json                 # [onboarding-owned]  name, layers, repo ref, current dataDictId, ...
    repo/                        # [onboarding-owned]  single git clone; incremental does `checkout <commit>`
    datadict/
      <dataDictId>.csv           # [onboarding / separate API]  data dictionaries; generate references one by dataDictId

    # ───────────── owned by INCREMENTAL ─────────────
    cache/
      index.json                 # {fingerprint -> {versionId, entityKey}}  — cross-version reuse POINTER index
                                 #   (NO output content here; the output lives once in that version's model/output)
    versions/
      index.json                 # [{versionId, branch, commit, scope, dataDictId, baselineVersionId,
                                 #   decision, regenerated, reused, status, createdAt}]
      <versionId>/
        manifest.json            # the full version record (incl. counts, warnings)
        hashes.json              # {entity_key -> token-sha256}   ← FULL snapshot of all entities at this commit
        edges.json               # SLIM: type-usage + macro-usage only (axes functions.json lacks).
                                 #   calls/globals read from model/functions.json; recursive closure via BFS
        config.json              # the resolved per-run config (global clang/llm + this project's layers)
        model/  output/          # the fully-assembled pipeline artifacts for THIS version (browse)
        documents/               # one or more .docx (multiple when component-per-docx)
```

### Example file contents

`versions/v4/hashes.json` — the full *entity → source-hash* snapshot at v4's commit:
```json
{
  "Core|Core|init|":       "9af1…(64 hex)",
  "Core|Core|helper|":     "3b7c…",
  "Lib|Lib|add|int,int":   "c0d2…"
}
```

`versions/v4/edges.json` — **SLIM**: only the axes `functions.json` does *not* already have —
**type-usage** and **macro-usage** (reverse: which entities use each type / macro). The call graph and
globals are read from `model/functions.json` (`callsIds` / `calledByIds`, `reads`/`writesGlobalIds`);
the **recursive/transitive** closure is **computed by reverse-BFS** over those, not stored.
```json
{
  "typeUsers":  { "Core::Config":           ["Core|Core|init|"] },
  "macroUsers": { "MAX_RETRIES@Core/Core.h": ["Core|Core|init|"] }
}
```

`cache/index.json` — the cross-version reuse **index**: one pointer per content fingerprint, **not** a
copy of the output. The output itself (description / behaviour names / flowchart Mermaid) lives **once**,
in the pointed-to version's `model/functions.json` + `output/flowcharts/*.json`:
```json
{
  "<fingerprint-of-helper>": { "versionId": "v2", "entityKey": "Core|Core|helper|" },
  "<fingerprint-of-init>":   { "versionId": "v4", "entityKey": "Core|Core|init|" }
}
```
*Reuse:* compute an entity's fingerprint → look it up here → **copy its output from the pointed-to
version** into the new version. The content is therefore never duplicated or regenerated.

`versions/v4/manifest.json` — the full version record:
```json
{
  "versionId": "v4", "branch": "main", "commit": "C4_sha",
  "scope": { "type": "project" }, "dataDictId": "dd-001",
  "baselineVersionId": "v3",
  "decision": "incremental", "regenerated": 12, "reused": 988,
  "status": "complete", "warnings": [], "createdAt": "2026-06-18T10:00:00Z"
}
```

`versions/index.json` — the registry of all versions (one row each):
```json
[
  { "versionId": "v3", "branch": "main", "commit": "C3_sha", "status": "complete", "createdAt": "…" },
  { "versionId": "v4", "branch": "main", "commit": "C4_sha", "status": "complete", "createdAt": "…" }
]
```

`versions/v4/config.json` — the resolved per-run config actually used (global `clang`/`llm`/`views`
from `config/config.json` **+ this project's `layers`** injected via `--config`), stored so the run is
reproducible.

### The stores — what lives where (no duplication)
- **`versions/<vN>/model/` + `output/`** = the **single source of truth for every output**
  (descriptions, behaviour names, flowchart Mermaid). The analyzer's Phase 3/4 read these to build the
  document, so output content lives **here only**.
- **`versions/<vN>/hashes.json`** = a **complete snapshot** of *which entities existed and their
  source-hashes* at version N's commit. **Per version**; the thing the *next* version **diffs against**.
- **`versions/<vN>/edges.json`** = the **slim** type/macro-usage index (calls/globals come from
  `functions.json`).
- **`cache/index.json`** = a project-wide **pointer index** `{fingerprint → (versionId, entityKey)}`
  that lets a new version reuse an output **already produced by an earlier version** (revert /
  cross-branch) **without copying it** — it only records *where* the content lives.

> `versions/<vN>/` = the complete self-contained snapshot of version N (model + outputs + document).
> `cache/index.json` = a tiny pointer map for cross-version reuse — content is never duplicated.

Where the hashes come from:
- `source_hash(entity)` = token-based **full SHA-256** of the entity's own source (the 4 entity
  types: function / global / macro / type, keyed by identity incl. defining file/location).
- `fingerprint(entity)` = `sha256(source_hash + sorted(dependency_source_hashes))`
  — the **content-only reuse-index key** for that entity's output. It deliberately does **not** fold in the
  LLM recipe (model/prompt/engine): an already-generated, approved document is reused regardless of which
  model produced it. **(Decision: recipe-fingerprint invalidation dropped — we do not re-run the LLM just
  because the model or prompt changed.)**

---

## 5. The incremental engine (the validated flow)

**Terminology (so this section reads standalone):** a **version** is one past document generation,
stored under `versions/<id>/`. In the walkthrough below, **v4** is an example *existing* version
(already generated and stored) and **v7** is the *new* version being created now. **C4** and **C7**
are their git **commits** — `C4` is the commit `v4` was built from; `C7` is the commit the user now
wants a document for. **v4 is the "baseline"** — the existing version we reuse from (normally the
nearest-ancestor version of `C7`; see §6). The numbers (v4, v7) are illustrative labels, not a fixed
count.

Generating **v7** at commit **C7**, baseline **v4** at commit **C4** (auto nearest-ancestor, or user
override):

```
1. base = v4 (auto nearest-ancestor, or user override). Copy v4/{model,output,hashes,edges} -> v7.
2. git checkout C7;  git diff C4..C7 --name-only -> changed files.
3. Parse ONLY changed files -> fresh entities/hashes/edges.
   Merge into v7: update changed, add new, REMOVE deleted.
4. Classify vs v4/hashes.json -> {changed, new, deleted} entities.
5. IMPACT ANALYSIS: reverse-BFS UP the dependency graph -- calls/globals from functions.json,
   types/macros from edges.json, containment derived from location (visited-set handles
   recursion/cycles); over-approximate virtual/fn-ptr; handle move/rename
   -> full impact set (includes dependents in UNCHANGED files).
6. For each entity in {changed ∪ new ∪ impacted}:
       fingerprint -> index hit? copy that output from the pointed-to version
                    :          LLM-regenerate, then add a cache/index.json entry -> v7.
   Reused (unchanged & unimpacted) entities keep v4's carried-forward output (already in v7 from step 1).
7. REASSEMBLE: merge v7's data-dict; run Phase 3 (views) + Phase 4 (export) over v7's (scoped) model
   -> v7/documents/.
8. Write v7/manifest.json (commit C7, baselineVersionId v4, counts); append versions/index.json;
   add cache/index.json entries for the newly-generated fingerprints (-> v7).
```

### Why each non-obvious step is mandatory (the correctness checklist)
These are the difference between a **correct** and a **stale** document:

| Step | Why it cannot be skipped |
|---|---|
| **5. Impact analysis** | "changed files" gives only the **directly** changed entities. If `a()` (unchanged file A) calls `b()` (changed file B), `a`'s description/flowchart describe `b`'s behavior → `a` is **stale** unless impact propagates UP to it. **This is the #1 trap.** |
| **3. REMOVE deleted** | a changed file may have *removed* a function → it must be deleted from v7's model/outputs/edges (and its callers impacted). |
| **5. Move/rename** | a moved entity's key changes → delete(old)+add(new); callers in unchanged files have a dangling edge → impact them **and** re-resolve their edges (re-parse the impacted caller's file). |
| **5. All axes** | not just calls — a changed **global / macro / type** impacts its **users**, usually in unchanged files. (Calls/globals from `functions.json`; types/macros from `edges.json`.) |
| **6. Index-check before LLM** | for each impact-set entity, look up `cache/index.json` by fingerprint first — a **revert** or **cross-branch identical code** is a hit → **copy** the existing output from the version it points at, no LLM. |
| **7. Reassemble** | "updating entities" is not a document — Phase 3 + Phase 4 must run over v7's model to produce `documents/`. (No LLM here; cheap.) |

### Full-generation path (fallback / first version)
When there is **no baseline** (first version, no ancestor, or `mode:"full"`): skip steps 1–2 and
parse the **whole project**; everything is `new` → regenerate all (each still index-checked, so a
re-run of an unchanged commit is cheap); then steps 7–8. This is the Approach-1 safety net.

---

## 6. Baseline selection

- **Default = auto nearest-ancestor.** Among prior versions' stored commits, keep those that are
  ancestors of the target (`git merge-base --is-ancestor`), pick the **nearest** (smallest
  `rev-list --count base..target`). **None → full generation.** (Implemented: `git_service.nearest_ancestor`.)
- **Optional override (`baseVersionId`).** If the user hand-picks a base:
  - **not an ancestor** ("**divergent base**" — a version on a branch that split away from the target;
    *only ever reachable via this override, never auto-picked*) → **strong warning**: big diff,
    runs close to a **full generation**; still **correct**.
  - **ancestor but not the nearest** → **mild warning** + suggest the nearest (faster).
- **Correctness is independent of the base** (`git diff` compares trees; carried-forward
  byte-identical files are valid; impact analysis catches the rest). **The base only affects *parse
  speed*** — because reuse (the LLM cost) is handled by carry-forward from the baseline plus the
  cross-version pointer index (D3). So a "wrong" base is **slow, never stale**.

---

## 7. Analyzer-side changes required (`version4`)

| Area | Change |
|---|---|
| `run.py` | `--config <path>` → sets `ANALYZER_CONFIG` env (inherited by phases); `--incremental --baseline-dir <versions/<base>> --changed-files <file>` path. |
| `core/config.py` | `load_config()` honors `ANALYZER_CONFIG` (per-project `layers`) before falling back to `config/config.json`. |
| `parser.py` | **partial-parse** a given file set; **entity hashing** (token-based full SHA-256, 4 types); emit the **slim type/macro-usage index** (calls/globals already go into `functions.json`). |
| `model_deriver.py` | **incremental mode**: regenerate impact set, carry the rest from baseline; **extend `EntityCache`** to behaviour names + summaries. |
| `views/flowcharts.py` (Phase-3 view) | already filters `functions.json` → `functions_<group>.json` and **launches the `src/flowchart/` engine** via `--interface-json`. Change: restrict that functions file to the **impact set**; merge engine output into the carried-forward `flowcharts/*.json`. **The engine (`src/flowchart/`) is unchanged.** |
| `src/incremental/` (new) | orchestrates the §5 flow; reads/writes `hashes.json` / `edges.json` / `cache/index.json`. |

Most of the dependency graph already exists in `functions.json` (call / reverse-call edges, transitive
globals); the **recursive closure is just a BFS** over it. The genuinely-new work is the **slim
type/macro-usage index**, **entity hashing**, and **partial-parse + merge**.

---

## 8. APIs (incremental only)

Base `http://<host>:8000`, prefix `/api/v1`. JSON unless noted. Errors `{ "detail": "…" }`.
These assume the project already exists (onboarded). **No onboarding endpoints are defined here.**

### 8.1 Generate a version  ← the incremental trigger
`POST /api/v1/projects/{projectId}/generate` — `application/json`.

Request body:
```json
{
  "branch": "feature/x",
  "commit": "a12b34c…",
  "scope":  { "type": "project" },        // project | {"type":"layer","names":[…]}
                                          //         | {"type":"group","names":[…]}
                                          //         | {"type":"component","names":[…]}
  "mode":   "auto",                       // "auto" (incremental if ancestor exists) | "full"
  "baseVersionId": null,                  // optional override; null = auto nearest-ancestor
  "dataDictId":    null                   // optional; null = the project's current data dictionary
}
```
**200**
```json
{ "versionId": "v-7", "jobId": "gen_4f7a1b8e", "decision": "incremental",
  "baselineVersionId": "v-4", "baselineCommit": "C4…", "dataDictId": "dd-002",
  "warnings": [] }
```
`scope.type` → analyzer flags (`project`→none, `layer`→`--selected-layer`, `group`→`--selected-group`,
`component`→repeated `--selected-component`). `decision` = `incremental | full`. `warnings` carries
base-override advice (`"base v-4 is not an ancestor — running close to full"`, etc.). The **data
dictionary file is uploaded/managed by a separate API (onboarding workstream)** — `generate` only
*references* one by `dataDictId` (or uses the project's current). A data-dict-only change re-runs the
**cheap** reassembly (interface-table ranges), **not** the LLM (D6).
**Errors:** 400 (bad scope/commit/base/dataDictId), 404 (unknown project), 409 (commit not in repo).

### 8.2 Generate preview (baseline advice — called BEFORE generate)
`GET /api/v1/projects/{projectId}/generate/preview?commit=<sha>&baseVersionId=<vid?>`
**When:** call this **before** `generate` — once the user has picked a target commit (and optionally a
base) — to show the plan and let them confirm or change the base before starting the (possibly long)
run. It is **read-only** (changes nothing) and returns what `generate` *would* do:
```json
{
  "targetCommit": "a12b…",
  "autoBaselineVersionId": "v-4",         // nearest ancestor (null -> would be FULL)
  "autoBaselineCommit": "C4…",
  "chosenBaseVersionId": "v-2",           // echoes ?baseVersionId if supplied
  "chosenIsAncestor": true,
  "chosenIsNearest": false,
  "changedFiles": 12,                     // git diff <base>..<target> count for the chosen/auto base
  "decision": "incremental",              // or "full"
  "warnings": ["v-2 is an ancestor but not the nearest (v-4); v-4 will be faster"]
}
```

### 8.3 Versions
- `GET /api/v1/projects/{projectId}/versions` →
  ```json
  [ { "versionId": "v-7", "branch": "feature/x", "commit": "a12b…",
      "scope": {"type":"project"}, "dataDictId": "dd-002",
      "decision": "incremental", "regenerated": 48, "reused": 952,
      "status": "complete", "createdAt": "2026-06-18T…" } ]
  ```
- `GET /api/v1/projects/{projectId}/versions/{versionId}` → full detail + per-document `downloadUrl`s.
- `GET /api/v1/projects/{projectId}/versions/{versionId}/download` → the `.docx` (or a **zip** when
  the scope produced multiple documents, e.g. `component-per-docx`).

### 8.4 Job status / logs / cancel / download  (existing endpoints — reused as-is)
Generation reuses the backend's current job lifecycle (the same machinery the pipeline already uses):
- `GET /api/v1/jobs/{jobId}/status` → canonical 4-phase progress + `decision` + `regenerated`/`reused`.
- `GET /api/v1/jobs/{jobId}/prepare/logs` → tail of this job's stdout/stderr.
- `DELETE /api/v1/jobs/{jobId}` → full process-tree kill (cancel).
- `GET /api/v1/jobs/{jobId}/export/status` → docx-artifact readiness (filename + downloadUrl).
- `GET /api/v1/jobs/{jobId}/export/download` → stream the docx for this job.

### 8.5 Supporting reads (shared — git_service-backed; used to pick the generate target)
Not onboarding, not incremental-core — these just let the UI choose a `branch`/`commit`. Backed by
`git_service`; may be shared with the project-mgmt layer:
- `GET /api/v1/projects/{projectId}/branches`
- `GET /api/v1/projects/{projectId}/branches/{branch}/commits?limit=&offset=`

### 8.6 Browsing a generated version (existing backend reads — reused, version-scoped)
The existing read endpoints serve a generated version's results; for incremental they take
`?projectId=&versionId=` so they read **that version's** `model/`+`output/` (which removes the
single-shared-`model/` limitation). **Onboarding (`POST /projects`) and the old `repository/*` CRUD are
NOT part of this feature.**
- `GET /api/v1/components?projectId=&versionId=` — component / unit / function tree of the version
- `GET /api/v1/functions/{fn_id}?projectId=&versionId=` · `PATCH …` — function detail / edit description
- `GET /api/v1/flowcharts/{fn_id}?projectId=&versionId=` — raw Mermaid for one function
- `GET /api/v1/config?projectId=` — the resolved config used (read-only)
- `GET /api/v1/project/structure?projectId=` — source tree of the checked-out commit

---

## 9. Milestones (incremental delivery; `git_service` already done)

- **M1 — Version-producing FULL generation + substrate.** Per-project run via `--config` (inject the
  project's `layers`); after a full run, capture **entity hashes** + the **slim type/macro index** +
  assembled `model/output/documents`, store as a **version**; seed `cache/index.json`. `POST …/generate`
  (full path) + `versions` APIs. All version / hash / edge / reuse-index persistence goes through the
  **store interface** (D9 — `src/incremental/stores.py`), so the Postgres swap is one implementation, not a
  rewrite. *This is the foundation — every incremental run diffs against a version.*
- **M2 — Incremental engine (the §5 flow).** Baseline pick (auto nearest-ancestor + optional override),
  `generate/preview`, partial-parse + merge, classify, **impact BFS** (all axes), selective regen with
  the reuse index, reassemble; `mode:"auto"`. *Delivers hours → minutes.*
- **M3 — Hardening.** Move/rename re-resolution, deletions, over-approximation polish, version-scoped
  reads (`components`/`functions`/`flowcharts` take `?versionId=`),
  multi-doc zip download. *(M3.1–M3.6 done — incl. function-level flowchart reuse; remaining:
  version-scoped reads, git layer consolidation, unit-diagram reuse.)* **Recipe-fingerprint invalidation:
  dropped by decision** — an approved document is reused regardless of LLM model/prompt changes, so the
  reuse fingerprint is content-only (no recipe component).
- **M4 — Narrowed (incremental) parse** (see §11; only worth doing once Phase-1 parse time is the
  measured bottleneck). Per-TU include-closure tracking → affected-TU set from the git diff → parse
  only affected TUs, reuse the baseline model for the rest, recompute all reverse/aggregate edges,
  behind an assemble-vs-full **self-check**. Turns Phase-1 cost from *O(codebase)* into *O(diff)*.
  *Delivered behind `--verify-parse` until proven byte-identical to full parse.*

---

## 10. Deferred (and the Postgres seam)

- **Narrowed (incremental) parse — M4, fully specced in §11.** Parse only the TUs whose preprocessed
  input changed, reuse the baseline model for the rest. Turns Phase-1 cost from *O(codebase)* into
  *O(diff)*. Deferred until parse time is the **measured** bottleneck; design + corner-case audit +
  never-stale triggers live in §11. A further generalization — a **content-addressed** parse cache that
  keys each TU by `hash(source + included headers)` and reuses across *all* branches (eliminating
  baseline selection) — is a follow-on to M4.
- **Per-artifact hashing**, **image-render cache**, **cross-version dedup** — deferred (see `03` §22.8).
- **Postgres migration:** every JSON store → a table — `versions`, `entity_hashes`,
  `type_macro_usage`, `entity_outputs` (stored once per version), `reuse_index` (fingerprint →
  version + entity), `data_dictionaries`, `jobs`. Impact-BFS → recursive CTE / closure table; baseline
  ancestry → stored commit graph. **Because every store sits behind the D9 interface
  (`src/incremental/stores.py`), this migration is adding a `Postgres*` implementation of those same
  methods — the §5 engine and the APIs are untouched.** (The analyzer's per-version `model/`+`output/`
  artifacts are *not* part of this seam — they stay file-based until the separate DB-native pipeline
  rewrite, `03`/§22.3.)

---

## 11. Narrowed (incremental) parse — design (planned, **M4**)

Today every incremental run does a **full** libclang parse (D10): correct, but on a huge codebase
Phase-1 parse time becomes the floor once LLM work is reduced. This section specs the optimization —
**parse only the translation units (TUs) whose preprocessed input changed, reuse the baseline
version's model for the rest** — to the depth needed to implement it *without ever silently staling a
document*.

### 11.1 The correctness invariant
> **The incrementally-assembled model must be byte-identical to what a full parse would produce.**

If that holds, classify / impact / reuse are automatically correct. Everything below exists to
guarantee it. It rests on one property of the compiler:

> **A TU's AST is a pure, deterministic function of its preprocessed input + compiler flags.**
> Preprocessed input = the `.cpp` + every transitively `#include`d file (macros expanded) + `-D`
> defines + include paths.

**Corollary (the reuse licence):** if a TU's preprocessed input and flags are unchanged, *every
entity defined in it* — signature, location, `callsIds`, reads/writes-globals, type/macro usages,
source hash — is identical to the full-parse result, so the baseline entity may be reused verbatim.

### 11.2 The design
1. **Record per-TU include closures.** On any parse (full or narrowed) write
   `model/tu_includes.json = {tuPath: [resolved included files]}` (libclang exposes this via
   `TranslationUnit.get_includes()`). Normalize all paths to **repo-relative, case-folded** (Windows).
2. **Affected-TU set** — a *sound over-approximation* — from `git diff baseline..target`:
   `affected = { tu : ( includes(tu) ∪ {tu} ) ∩ changedFiles ≠ ∅ }`.
3. **Parse only the affected TUs** → fresh *local* data (entities, hashes, forward edges, type/macro
   usages) + their fresh include closures.
4. **Merge into a copy of the baseline model:** remove every entity defined in an affected/deleted
   file, add the fresh entities, keep the rest. Dedup header-defined entities (inline / template) by
   the stable key `Component|File|name|params` — the header is unchanged, so all reparsing TUs agree.
5. **Recompute ALL reverse / aggregate maps from the merged forward edges** — *recompute, never
   incrementally patch:* `calledByIds` ← invert `callsIds`; `typeUsers` / `macroUsers` ← invert each
   function's usage list; `writesGlobalIdsTransitive` ← closure over the reassembled call graph. This
   is O(edges), in-memory, and **cannot drift** (it is derived, not maintained).
6. **Refresh the closure map**: reuse unaffected entries, replace affected → store for the next run.

This dispatches both classic hazards by construction:
- **Cross-file reverse edges** → step 5 (recompute from forward edges; a removed call simply isn't
  re-derived, an added one is — no add/remove/delete bookkeeping to get wrong).
- **Header / macro / template fan-out** → step 2: all three propagate **only** through `#include`, so
  any TU that could see the change has the changed file in its closure and is reparsed.

### 11.3 Corner cases — handled incrementally (safe)
| Case | Why it stays byte-identical to a full parse |
|---|---|
| Function body change | Its TU is affected → reparsed; reverse edges recomputed |
| Added / removed call edge | Forward edge is fresh; all reverse maps recomputed from scratch |
| Header / inline / template change | Every including TU is in the closure → affected |
| Macro change | A macro lives in a header → the closure catches it |
| Deleted function / file | Entities removed; aggregates recomputed → no dangling reverse edges |
| Signature change | The *declaration* (header) must change too → callers affected → reparsed |
| Non-`.h` includes (`.inc`, generated headers) | Closure records **every** included file, any extension |
| File-local (`static`) functions | Only same-TU callers exist, and that TU is affected |

### 11.4 MUST full-reparse — the "never-stale" triggers
These change the preprocessed input or AST for TUs the git diff alone can't identify, so they force a
full parse (or a conservative widening):

1. **Compiler flags / `-D` defines / include paths / C++ std changed** → preprocessed input changes
   for *every* TU. Detect via a small **parse fingerprint** = `sha256(clang flags + -D defines +
   include paths + C++ std + libclang version)` stored per version; if it differs from the baseline's,
   full-reparse. *(This is a M4-local parse-inputs hash — distinct from, and unrelated to, the dropped
   recipe fingerprint; it covers only what changes the AST, never the LLM model/prompt.)*
2. **Toolchain (clang / libclang) version changed** → the AST or token stream can differ for
   unchanged source. Covered by the parse fingerprint above (libclang version is one of its inputs).
3. **A header file is ADDED or DELETED** → it may *shadow* an existing `#include` and silently change
   an otherwise-untouched TU's closure. Conservative rule: reparse every TU whose closure references
   that basename / relative path, else full-reparse. (Header **modifications** are fine — handled by
   the closure.)
4. **`tu_includes.json` missing / schema mismatch / first incremental run** → no trustworthy closure
   map → full parse.
5. **PCH (precompiled header) in use** → treat the PCH as included by all TUs (it is) → a PCH change
   forces a full reparse via the closure.

### 11.5 Safety net — assemble-vs-full self-check
Ship M4 behind a **`--verify-parse`** mode (and run it every Nth generation / in CI): do a full parse
and **diff the assembled model against it** — entity sets, per-entity hashes, and forward + reverse
edge sets must match exactly. Any mismatch is a *missed corner case surfaced loudly*, instead of a
quietly-wrong document discovered weeks later. Only graduate narrowed-parse to the default once the
self-check has been clean across a representative range of diffs.

### 11.6 Inherent limit
Changing a **widely-included core header** legitimately invalidates a large fraction of TUs —
incremental can't and *shouldn't* dodge that, because those TUs genuinely changed. The win is the
common case: a small diff touches a handful of TUs, not the whole tree.

### 11.7 New / changed artifacts
- `model/tu_includes.json` **(new)** — per-TU include closure, captured on every parse, stored per
  version (the thing the next run intersects with the git diff).
- **Parse fingerprint (new)** = `sha256(clang flags + -D + include paths + std + libclang version)`,
  stored per version; a mismatch forces a full reparse (§11.4). Distinct from the reuse fingerprint
  (content-only) and unrelated to the dropped recipe fingerprint.
- `parser.py` gains: emit the closure map, and an **"affected files only"** parse mode.
- `src/incremental/` gains the **parse-merge + reverse-recompute** logic and the affected-TU
  computation; the `--verify-parse` self-check.

---

_End of document._
