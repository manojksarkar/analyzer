# Re-architecture + PostgreSQL Migration — Master Implementation Plan

> Status: DRAFT rev-6 · **This is the single master plan** covering all agreed activity:
> (A) regression/accuracy safety net, (B) one-AST-pass, (C) in-process flowchart engine +
> package layout, (D) JSON → PostgreSQL everywhere, (E) Incremental on Postgres,
> (F) context-service + cache consolidation.
> Grounded in the **current** `engine/` + `api/` code — doc 04's directory structure is obsolete;
> use it only for incremental *approach*. Background: `01`/`02` (why Postgres), `03` (incremental design).

## 0. The two hard constraints (these govern every decision below)

| # | Constraint | How it is enforced |
|---|---|---|
| **C-1** | **Existing functionality must not break** | The revived e2e suite (**627 passed / 4 skipped**) + regenerated snapshots become a **CI gate** on every change (Workstream A). |
| **C-2** | **LLM result accuracy must not go down** | **You cannot diff LLM outputs — they are non-deterministic.** So we diff *inputs*: every refactor must produce **byte-identical prompts** and a **byte-identical model**. See §2. |

---

## 1. Decisions locked

| # | Decision | Chosen |
|---|---|---|
| D-1 | Scope | API domain DB + incremental metadata + **rich model & dependency graph** → Postgres. Postgres = system of record for the model. |
| D-2 | Artifacts | DOCX/PNG/mermaid + git checkouts stay on the filesystem (object storage later). |
| D-3 | **Version identity** (finalised rev-8) | The **UI-supplied version, unique within a project** (`UNIQUE(project_id, version)`), used end-to-end. No auto `v0.N.0`, no silent `-1` rename, no `commit[:16]` namespace, no `ver…`↔commit translation. Duplicate ⇒ **409**. <br>**API contract (agreed):** the field is **MANDATORY** — missing ⇒ **400**. The **wire name stays `version_tag`** (DB column is `version`) so the UI's strict zod response mappers keep validating. UI-side mandatory enforcement is owned by the UI engineer. **Both** creation paths (`POST /jobs` and `VersionsPage`/`useVersionMutations`) enforce the same rule. |
| D-4 | Hosting | Docker Postgres 16 (compose for dev; container on the office box). |
| D-5 | Existing data | **Start fresh** — no importer. |
| D-7 | Tooling | SQLAlchemy 2.0 + Alembic + psycopg 3. Keep `InMemoryDatabase` for tests; drop `JsonDatabase`. |
| **D-8** | **Keep RBAC exactly as-is; build no new RBAC** ⭐final rev-8 | **Migrate the existing RBAC unchanged** — `project_members` (incl. `role`/`status`), `access_requests`, and every members/team/access-request endpoint and guard are ported as-is. The UI actively calls `/members`, `/members/invite`, `/members/{id}/role`, `/members/pending`, `/team`, `/access-requests`, so nothing here may change (C-1). **No new RBAC work** is in scope: no new roles, permissions, policies or enforcement rules. Only `organizations` is dropped — it is genuinely vestigial (no repository, no route, hardcoded `"org1"`). |
| **D-9** | **Storage model = manifest of pointers** ⭐rev-8 (replaces "full snapshot" and rev-7's partial dedup) | A version is a **complete manifest of thin pointer rows**; content lives **once**, content-addressed. Three layers: `entities` (stable identity across versions) → `entity_versions` (thin, queryable, one row per entity per version) → `content_blobs` (payload stored once). **Carry-forward = point at the same `content_hash`** — literally zero copying. Storage ≈ O(model) *tiny* rows + O(**changes**) content. Explicitly **not** a delta chain (see §4.1). |
| **D-10** | **One AST pass** ⭐ | Phase 1 parses each TU **once** and runs all visitors on the retained TU. (Verified: 3 identical parses today.) Landed **standalone, before** the DB work. |
| **D-11** | **Flowchart engine in-process** ⭐ | Convert the nested subprocess to a function call — **by fixing the package layout**, not by wrapping. Done **together with** the DB-native model change (one touch, §5-D). |
| **D-12** | **No knowledge base** ⭐ | No KB table, no KB file, no whole-project KB object. One **context service** returns the working set via `fetch_context(version, target_fids)`. |
| **D-13** | **Normalize derived relationships** ⭐ | Relationship arrays (`model_units.function_ids/caller_units/…`, `model_components.units/header_files`) are **derived by query**, not stored as jsonb. *(Reversible if profiling objects.)* |
| **D-14** | **Zero JSON data** ⭐rev-7 | **All project data lives in Postgres.** Every JSON data file and all JSON read/write code is **deleted, not left dormant** — incl. flowchart Mermaid, interface tables, behaviour rows, unit-diagram Mermaid, per-version resolved config, report, data-dictionary + macros CSVs. Only **binary artifacts** (PNG/DOCX), **git checkouts**, **logs**, and **app config/test fixtures** (`engine/config/config.defaults.json` + gitignored `config.local.json` secrets, `package.json`, `tests/snapshots/`) remain as files. *(Per-version resolved config is now in PG — `versions.resolved_config`, written by `pipeline_runner`; see root PROJECT_CONTEXT §6.)* |
| **D-15** | **Three hashes, three jobs** ⭐rev-8 | Do not conflate them: **`source_hash`** (token hash of the source ⇒ *did the code change?* → drives `classify`) · **`fingerprint`** (source + dep hashes + LLM recipe ⇒ *can I reuse the LLM output?* → drives `reuse_index`) · **`content_hash`** (hash of the stored payload ⇒ *is this byte-identical to something already stored?* → drives dedup). All three live on `entity_versions`. |
| **D-16** | **Postgres is required** ⭐rev-7 | No file-backed fallback for the pipeline. A **fail-fast startup check** errors clearly if the DB is unreachable. (`JsonModelSource` survives only as a read-only debug input for the flowchart engine.) |
| **D-17** | **Phase atomicity** ⭐rev-7 | Each phase writes in **one transaction**; all writes are **idempotent upserts**; `versions.status` tracks `parsing → deriving → viewing → exporting → complete/failed`. A crashed phase rolls back, and `--from-phase N` re-runs it cleanly. *(Strictly better than files, which cannot roll back.)* |
| **D-18** | **User intent carries forward** ⭐rev-7 | `is_visible` (function hide/unhide) carries forward for reused entities alongside descriptions — otherwise every new version silently resets the user's hide choices. Covered by a test. |

---

## 2. ⭐ The parity harness — how C-1 and C-2 are actually guaranteed

**This is the backbone of the plan. Build it first (Workstream A); every later milestone is gated on it.**

Because LLM output varies run to run, "the descriptions still look fine" is not evidence. We instead prove that **nothing the LLM sees changed**, at three levels:

| Level | What is compared | Proves | Tooling |
|---|---|---|---|
| **L1 — Model parity** | `entity_hashes` + functions/globals/types/edges, before vs after | The refactor did not change the extracted model | reuse existing hashing; assert **hash-for-hash identity** |
| **L2 — Prompt parity** ⭐ | **Every LLM prompt (system + user), byte-for-byte** | The LLM's *input* is unchanged ⇒ accuracy cannot have changed | new `LLM_PROMPT_DUMP=<dir>` hook at the choke points |
| **L3 — Artifact parity** | `interface_tables.json`, `unit_diagrams.json` snapshots, DOCX structure, 627 tests | End-user output unchanged | existing e2e suite + snapshots |

**L2 mechanics.** ⚠ **rev-8 correction — hook the LLM *client*, not the call sites.** An earlier draft proposed hooking `llm_enrichment._call_llm` + `build_user_prompt`; that would have captured only a fraction of prompts, making the accuracy guarantee **silently incomplete**. There are **12 call sites that bypass `_call_llm`**:
`flowchart/llm/generator.py` ×3 (labels/simplify/coherence) · `flowchart/project_scanner.py` ×6 (function/phases/file/component/project summaries) · `llm_core/review.py` ×3 (self-review/revise/ensemble).

**All of them call `LlmClient.generate()`** — so put the env-gated dump (`LLM_PROMPT_DUMP=<dir>`) in **`llm_core/client.py::generate`**. One hook, **complete by construction**, recording `{system, user, model, params, call-site tag}`.

Capture a **golden set** on `SampleCppProject` *before* any refactor; after each change, re-run and `diff`. **Byte-identical prompts + same model + same params ⇒ identical accuracy by construction.** Also assert the **call count** matches (a dropped call is as bad as a changed prompt).

> Any milestone that *intentionally* changes a prompt (there should be none in this plan) must justify it and re-baseline the golden set explicitly.

**Where accuracy could silently degrade — each has a guard:**
| Risk | Guard |
|---|---|
| Scoped `fetch_context` misses a lookup path the builder uses | **L2** prompt parity |
| `model_types` loses struct `fields` / macro `value`+`text` | `payload jsonb` (§4.2) + **L2** |
| One-AST-pass changes visitor ordering ⇒ different model | **L1** hash identity |
| Consolidating 3 knowledge representations changes any consumer's view | **L2** |
| Cache re-keying (`PkbCache`, `EntityCache`) causes regeneration with different context | **L2** + cache-hit-rate assertion |

---

## 3. Storage inventory

**Into Postgres:** API domain DB (`api/db/data/*.json`, 12 repo ABCs / 15 dataclasses, single swap point `api/db/session.py`); incremental metadata (`VersionStore/HashStore/EdgeStore/ReuseIndex`); the rich model (`functions`, `globalVariables`, `dataDictionary`, `units`, `components`, `hashes`+`entity_files`, `edges`, `tu_includes`, `summaries`, `override_pairs`, `func_keys`).

**Also into Postgres (⭐rev-7 — found by sweeping every write site):**

| Was a file | Why it is data (not an artifact) | Lands as |
|---|---|---|
| `output/<scope>/flowcharts/*.json` (Mermaid) | **Read across versions** — `_carry_forward_flowcharts` copies the *baseline's* JSONs ([flowcharts.py:39](engine/views/flowcharts.py#L39)) and `_merge_incremental_flowcharts` splices into them | `model_flowcharts` + `content_blobs` |
| `versions/<id>/config.json` ([stores.py:142](engine/incremental/stores.py#L142)) | resolved config per version — reproducibility, feeds `parse_fingerprint` | `versions.resolved_config jsonb` |
| `datadict/<id>.csv` ([stores.py:92](engine/incremental/stores.py#L92)) | **user-uploaded project data** | `data_dictionaries` + entries |
| macros CSV (`--macros`) | project input; **per-layer macros is an open V1 requirement** — far easier as rows | `macro_definitions` (layer-scoped) |
| `interface_tables.json`, behaviour `_docxRows`, unit-diagram `.mmd` | Phase-3 output consumed by Phase 4 **and the API** (`_make_sections` counts units from it) | `view_interface_tables`, `view_behaviour_rows`, `model_unit_diagrams` |
| `report.txt` | per-version generation report | `versions.report` |

> **Deleting the flowchart JSONs is a simplification, not extra work.** `_merge_incremental_flowcharts`, `_carry_forward_flowcharts` and `_prune_orphan_flowcharts` exist **only to merge JSON files**. As rows, carry-forward is `INSERT…SELECT` from the baseline and regeneration is an `UPDATE` — that code largely deletes itself. It also fixes the **overload collision** (the JSON keys entries by `qualifiedName`, so two overloads share one entry *and* one PNG name; `entity_key` does not).

**Stays on disk:** git checkouts; **binary** artifacts (PNG/DOCX); `.mmdc_cache/`; logs; app config + test fixtures.

**Deleted outright:** `clang_include_paths.json`, `metadata.json` (→ `versions` columns), `knowledge_base.json`, `functions_<scope>.json`, `functions_incremental.json` (all derived), `modules.json` (**dead code** — zero references).

> **Rule that decides file-vs-DB:** *does any **other** version or later run read it?* → Postgres. Regenerated within one run and consumed immediately → not storage. (This test corrected two earlier mistakes: `override_pairs` and `func_keys` are **baseline-read by narrowed parse**, so they are storage.)

---

## 4. Schema

### 4.0 ⭐rev-8 — The storage model (how incremental storage is actually managed)

```
entities(entity_id PK, project_id FK, entity_key, kind)        -- STABLE identity across versions
    UNIQUE(project_id, entity_key)

entity_versions(version_id FK, entity_id FK, unit_id FK, component_id FK,
                direction, visibility, is_visible,
                source_hash bytea, fingerprint bytea, content_hash FK -> content_blobs,
                PK(version_id, entity_id))                     -- thin + queryable; the MANIFEST

content_blobs(content_hash PK bytea, kind, payload jsonb)      -- stored ONCE per distinct content
```

**Per-run write path (this is the storage management answer):**
| Step | What is written | Scales with |
|---|---|---|
| 1 | `versions` row (baseline ptr, status, resolved_config, parse_fingerprint, report) | 1 row |
| 2 | `entities` — **resolve-or-insert**; only genuinely NEW functions/globals/types create rows | O(new) |
| 3 | `entity_versions` — one thin row per entity, so the version is **self-contained** | O(model), ~120–150 B each |
| 4 | `content_blobs` — **only for changed content**; unchanged entities reuse the existing hash | **O(changes)** |
| 5 | `model_edges`, flowcharts, view outputs | see below |

**Why this is efficient:** an unchanged function in version N+1 costs **one thin row**, not a copy of its description/parameters/phases. `carry_forward_descriptions` stops copying values and simply reuses `content_hash`. Reused **flowcharts** work the same way — a pointer to the same Mermaid blob, which is exactly what M3.6's file-splice did by hand.

**Rough size (10k entities, 100 versions):** manifest ≈ **120–150 MB**; content ≈ *distinct* payloads only (vs. hundreds of MB of duplicated text under full snapshots). Edges are the other O(model) structure — kept as **real indexed rows per version** because reverse traversal (`who calls X`) is the impact-analysis hot path and **correctness there outranks bytes**. *(A content-keyed edge table would cut this further but risks dangling references to entities deleted in later versions — deferred as a measured optimization, not day-one.)*

**Reclaim:** `ON DELETE CASCADE` from `versions` drops `entity_versions` + edges + flowcharts in one statement. `content_blobs` are shared, so they need **refcount-or-sweep GC** (delete blobs with no referencing row) — run on version delete or as a periodic job. Retention policy deferred (D-16/B6).

**Explicitly NOT a delta chain.** Storing only changes and resolving unchanged entities by walking baseline→baseline would be O(changes) too, but the dominant query here is *"give me the full model of version X"*; chain-walking makes that slow and breaks when an intermediate version is deleted. A **complete manifest of pointers gives delta-like size with single-query reads.**

### 4.1 Three lifetimes
- **Per-version snapshot:** `model_functions`, `model_globals`, `model_types`, `model_units`, `model_components`, `model_edges`, `entity_hashes`, `tu_includes`, `model_summaries`
- **Project-scoped (shared):** `projects`, `commits`, `users`, `project_members`, **`reuse_index`** (the only deliberate cross-version structure)
- **Per-run records:** `versions`, `analysis_jobs`, `documents`…

*Graduation (not now):* content-addressed dedup keyed by the **fingerprint we already compute** — `entity_bodies(fingerprint PK, …)` + `version_entities(version_id, entity_key, fingerprint)`. Storage ∝ distinct content. Adds a join per read + GC on version delete; revisit with real numbers.

### 4.2 Tables (20)
**Access:** `users`, `projects`, `project_members` *(no roles; no `org_id`)*
**Ops:** `analysis_jobs` (phases jsonb), `notifications`
**Versions/Commits:**
```
versions(id PK, project_id FK, version NOT NULL, commit_sha, branch, description, status,
         docs_count, created_by, created_at, baseline_version_id FK, decision,
         regenerated, reused, base_path, project_name, parse_fingerprint,
         UNIQUE(project_id, version))          -- ⭐ D-3
commits(project_id FK, sha, branch, message, author_name, author_email,
        committed_at, has_version, doc_status, PK(project_id, sha))
```
**Documents:** `documents(… docx_path)`, `document_sections`, `document_assignments`, `compare_results`, `document_diffs`

**Model (per version):**
```
-- ⭐rev-8: functions / globals / types are ALL `entities` (see §4.0). `entities.kind`
-- distinguishes them; per-version state is `entity_versions`; payload is a shared blob.
entities        (entity_id PK, project_id FK, entity_key, kind, qualified_name,
                 UNIQUE(project_id, entity_key))     -- kind ∈ function|global|type|macro
entity_versions (version_id FK, entity_id FK, unit_id FK, component_id FK, file, line, end_line,
                 direction, direction_reason, visibility, interface_id, is_visible bool DEFAULT true,
                 source_hash, fingerprint, content_hash FK,   -- D-15: three distinct hashes
                 PK(version_id, entity_id))
content_blobs   (content_hash PK, kind, payload jsonb)
   -- payload holds the heavy/variable part per kind:
   --   function : description, behaviour_in/out, return_type, return_expr, parameters[], phases[]
   --   global   : type, value
   --   type     : underlying_type, range, comment, enumerators | fields | value+text  (the payload fix)

model_units     (version_id, unit_id, name, path, file_name, PK(version_id, unit_id))
model_components(version_id, component_id, name, PK(version_id, component_id))
model_summaries (version_id, scope, key, text_hash FK -> content_blobs, PK(version_id, scope, key))
```
⭐ **D-13 applied:** `model_units.{function_ids, global_ids, caller_units, callee_units, included_headers}` and `model_components.{units, header_files}` are **gone** — all derivable (`functions know their unit`; caller/callee units from `model_edges`; headers from `tu_includes`).
⭐ **`model_types.payload jsonb`** holds kind-specific data — `dataDictionary` entries are heterogeneous: `enum`→`enumerators[{name,value,comment}]`, `class`/`struct`→**`fields`**, `define`→**`value`+`text`**, `typedef`→`underlyingType`, `primitive`→almost nothing. Without it we'd silently lose struct members and macro bodies (**no test would fail** — labels would just get worse).

**Graph (one table):**
```
model_edges(version_id, kind, src_key, dst_key, mode)
  kind ∈ call | global_access | type_use | macro_use | override
  INDEX (version_id, kind, dst_key)   -- reverse traversal = impact analysis
  INDEX (version_id, kind, src_key)
```
`override` = fid-level virtual override→base pairs (was `override_pairs.json`), consumed by `parse_merge.spread_virtual_families` **from the baseline**.

**⭐rev-7 — content-addressed heavy text (D-15):**
```
content_blobs(hash PK, content text)      -- each distinct text stored ONCE
model_functions   … description_hash FK, detail_hash FK   -- (parameters+phases)
model_flowcharts(version_id, entity_key, mermaid_hash FK, error, PK(version_id, entity_key))
model_summaries   … text_hash FK
```
Carry-forward = *point at the same blob*. Two scopes at one commit **share** blobs instead of duplicating. Thin structural columns stay per-version so interface-table queries (component/unit/direction filters) need no join.

**⭐rev-7 — project inputs + view outputs:**
```
data_dictionaries(id PK, project_id FK, name, uploaded_at) + data_dictionary_entries(...)
macro_definitions(project_id FK, layer, name, value)          -- layer-scoped (open V1 req)
view_interface_tables(version_id, scope, payload jsonb)
view_behaviour_rows(version_id, scope, payload jsonb)
model_unit_diagrams(version_id, unit_key, mermaid_hash FK)
```

**Change detection / reuse:**
```
entity_hashes(version_id, entity_key, entity_kind, file, hash, PK(version_id, entity_key))
reuse_index  (project_id, fingerprint, version_id, entity_key, PK(project_id, fingerprint))
tu_includes  (version_id, tu_path, headers jsonb, PK(version_id, tu_path))
```
`func_keys` is **derived** (`SELECT entity_key FROM model_functions WHERE version_id=?`).
**Deferred:** `embeddings` (pgvector) — created only when similarity reuse lands.

---

## 5. Workstreams

### A — Safety net (FIRST, everything depends on it)
1. **CI**: run the full suite on every push (`pytest --skip-pipeline` = 627 green) + snapshot diff. *The e2e suite was dead from PR #19 until 2026-07-21 — a refactor this size cannot proceed without this gate.*
2. **Prompt-dump hook** (`LLM_PROMPT_DUMP=<dir>`) at `llm_enrichment._call_llm` and `build_user_prompt`.
3. **Capture golden baselines** on SampleCppProject: L1 model hashes, L2 prompt corpus, L3 snapshots.
4. `scripts/parity_check.py` — one command diffing all three levels against the goldens.

### B — One AST pass (D-10) — standalone, before the DB work
Today `parse_file` / `parse_calls` / `parse_global_access` each call `index.parse()` on the **same file with identical args** ([:1190](engine/parser.py#L1190)/[:1202](engine/parser.py#L1202)/[:1211](engine/parser.py#L1211)) — **~11.9s of Phase 1's 13.05s**.
1. Parse once per file; run `visit_definitions`, `visit_type_definitions`, `visit_usage`, `_collect_macro_defs`, `_capture_tu_includes`, `visit_calls`, `visit_global_access` on the **retained TU**; release before the next file (do **not** hold all TUs — memory).
2. Verify the ordering assumption: visitors must collect raw keys and defer cross-file resolution to `main()` (the pattern already used — `parser.py:357`).
3. **Gate: L1 hash identity** (model byte-identical) + L3 snapshots. Expected: **Phase 1 −55–60%**.

### C — Package layout + in-process flowchart (D-11) — merged into D below
The blocker isn't `subprocess`, it's that `engine/flowchart/llm/` **shadows** `llm_core` (hence `model_deriver`'s ordered `sys.path.insert`) and the `@response-file` hack for clang args.
1. Make `engine.flowchart.*` a normally importable package (resolve the `llm` shadowing).
2. Replace the subprocess spawn in `views/flowcharts.py` with a function call.
3. **Keep Phase 3's own process boundary** — libclang can segfault; we're only removing a *nested* process.
4. **Gate: L2 prompt parity** (identical prompts) + L3.

### D — PostgreSQL migration

> **Detailed runbook for PG-3 → PG-5:** [08-storage-seam-version-identity.md](08-storage-seam-version-identity.md) — the correct-architecture approach (honour the `stores.py` seam; real `ver…` id; `FileStore`/`PgStore`).

| Step | Deliverable |
|---|---|
| **PG-0** | docker-compose Postgres 16; deps; `DATABASE_URL`; Alembic scaffold; `db.py` in API + engine |
| **PG-1** | ORM + initial migration for the 20 tables (§4) incl. `UNIQUE(project_id, version)` |
| **PG-2** | `PostgresDatabase` = 12 repos + mappers; default backend; drop `JsonDatabase`; **RBAC landing** (guards → authenticated-only in one function; drop invite/role/approve routes) |
| **PG-3** | **Version identity (D-3)**: required+unique version, 409, delete the `v0.N.0` fallback and `-1` loop ([pipeline_runner.py:1008-1011](api/services/pipeline_runner.py#L1008)), **decouple `--project-name`** from the version ([:615](api/services/pipeline_runner.py#L615)), **split checkout (per commit) from artifacts (per version)**, engine `--version` |
| **PG-4** | Postgres `VersionStore/HashStore/EdgeStore/ReuseIndex`; `project_db` → Postgres; **engine writes directly** |
| **PG-5** ⭐ | **Combined touch**: `ModelStore` (phases persist/read the model) **+ Workstream C** (in-process flowchart) **+ `fetch_context`** **+ delete `clang_include_paths.json`/`metadata.json`** and their 7 call sites |
| **PG-6** | Incremental on Postgres (§E) |
| **PG-7** | Cutover: remove `api/db/data`, fresh-start onboarding, docs |

### E — Incremental on Postgres
Code is **complete** (M1–M4 + PERF caches, no TODOs). Remaining is storage + identity + validation:
1. Baseline reads from Postgres: `classify` (entity_hashes), `impact` (model_functions + model_edges), `parse_merge` (the per-version rows **are** the parser snapshot — `versions/<id>/parse/` disappears), `select_baseline` (versions+commits).
2. `incremental_plan.json` → a `job_plan` row keyed by version.
3. Version identity per D-3.
4. **Validation/graduation:** LLM-on timing on the office box; `--verify-parse` across a diff matrix on a **large** repo → then flip `--narrowed-parse` to default.
5. *Optional later:* impact via `WITH RECURSIVE` over `model_edges` (keep the tested Python BFS as reference + parity test).

### F — Context service + cache consolidation (D-12)
1. **One context service** replacing three parallel knowledge representations (model_deriver enrichment context, `project_scanner.ProjectKnowledge`, flowchart `PKB`): `fetch_context(version, target_fids)` returning the **neighbourhood** — target functions + 1-level callers + targeted callees + their param types + their globals + the (tiny) summary set. `target=all` reproduces today's whole-project behaviour and is the fallback flag.
   *Constant query count (bulk-fetch, never per-entity — N+1 is the failure mode); one `REPEATABLE READ` transaction; test asserts the query count does not scale with project size.*
2. **Rationalize four reuse mechanisms** — `EntityCache` (descriptions), `aux_descriptions`, `PkbCache`, `.mmdc_cache`, plus the DB `reuse_index`. Descriptions in Postgres + `reuse_index` make parts redundant; keep `.mmdc_cache` (binary renders). **Gate: cache-hit-rate must not drop** (else we silently pay for regeneration).
3. **Reserved:** pgvector retrieval when neighbourhood isn't enough.

### G — Operational hardening (⭐rev-7; lands with PG-4/PG-5)
1. **Phase atomicity (D-17)** — one transaction per phase; idempotent upserts; `versions.status` lifecycle. Test: kill Phase 2 mid-run → version state equals post-Phase-1 exactly; `--from-phase 2` completes cleanly.
2. **Fail-fast DB check (D-16)** — a single startup probe in both the API and the engine entry points: if Postgres is unreachable, exit with a clear, actionable message (not a stack trace). Delete every JSON read/write path — **no dormant fallback**.
3. **`is_visible` carry-forward (D-18)** — extend the carry-forward for reused entities; test that hiding a function in v1 keeps it hidden in v2.
4. **Concurrency** — `reuse_index` upsert uses `ON CONFLICT (project_id, fingerprint) DO NOTHING` (matches today's first-writer-wins). Once model + artifacts are per-version, raise/confirm `JOB_MAX_CONCURRENCY` deliberately (see defect 26).
5. **UTF-8 end-to-end (B7)** — DB created UTF-8, client encoding forced; round-trip test with a Korean comment + Unicode description. *(This codebase has documented cp1252 failures and task 3.20 handled Korean text.)*
6. **Retention** — `ON DELETE CASCADE` from `versions` + a delete-version action now; an automatic retention policy **deferred** until measured.

---

## 6. Sequencing & gates

```
A (CI + parity harness)          ← nothing starts before this
   └─ B (one AST pass)           ← independent of DB; gate L1+L3
        └─ PG-0 → PG-1 → PG-2 → PG-3 → PG-4
             └─ PG-5 (DB model + in-process flowchart + fetch_context)   ← gate L1+L2+L3
                  └─ PG-6 (incremental on PG)  → PG-7 (cutover)
                       └─ F2 cache rationalization, then optional graduations
```
**Why this order:** B is independently valuable and DB-free, so it lands early with a clean L1 proof. C and PG-5 both rewrite the flowchart engine's *input layer* — doing them separately means touching it twice, so they are **one milestone**. Every arrow is a **parity gate**, not a code review.

**PG-5 is the largest and riskiest step.** Mitigations: the `ModelSource`/`ModelStore` seam keeps a `JsonModelSource` for dev/test/standalone (permanent test seam, not throwaway); land "persist-after-phase" before "read-from-DB"; L2 prompt parity is mandatory to merge.

---

## 7. Risks
| # | Risk | Mitigation |
|---|---|---|
| R1 | **PG-5 breadth** (all 4 phases + flowchart engine) | stable seam; two-step landing; L1+L2+L3 gate |
| R2 | **Silent accuracy loss** (scoped context, lost `payload`, cache re-key) | **L2 prompt parity** — the whole reason it exists |
| R3 | One-AST-pass changes model semantics | **L1 hash identity**; verify visitors defer cross-file resolution |
| R4 | Holding TUs blows memory on a large repo | parse→visit→release per file |
| R5 | In-process libclang segfault takes down Phase 3 | Phase 3 keeps its own process boundary |
| R6 | Version-identity ripple (routes, runner, CLI, paths, compare) | isolated milestone PG-3 with its own tests |
| R7 | Bulk write volume | `COPY`/bulk insert; one transaction per phase |
| R8 | Fresh start ⇒ must re-onboard + regenerate a baseline | documented in the runbook |

---

## 8. Reversible decisions (change cheaply if you disagree)
1. **B before D** (one-AST-pass standalone first) — could be folded into PG-5 instead, at the cost of a muddier L1 proof.
2. **D-13** normalizing relationship arrays — restore jsonb columns if a query proves hot.
3. `versions` surrogate `id` + `UNIQUE(project_id, version)` vs composite `(project_id, version)` FKs everywhere.
4. Impact via SQL CTE — after cutover vs during PG-6.
5. Cut `compare_results`/`document_diffs`/`notifications` if those features are dropped.
6. **Out of scope:** UI-editable descriptions. If added later, `fetch_context` needs **no change**; it would add edit-provenance columns + a "manual wins" rule in carry-forward, and would invalidate the version-immutability assumption used by `PkbCache` keying.

---

## 9. Verified-defect log (why these details exist)
Found by inspection during planning; each would have shipped as a silent bug:
1. `commit[:16]` version namespace contradicted D-3 → removed.
2. Two versions can target one commit → **checkout (per-commit) split from artifacts (per-version)**.
3. `version_tag` doubles as `--project-name` → DOCX title would follow the version → decoupled.
4. Silent `-1` rename violated "unique version" → DB constraint + 409.
5. 4 edge tables unjustified → one `model_edges` with `kind`.
6. `branch_baselines` redundant (derivable) → dropped.
7. `function_visibility` overlay for one boolean → folded into `model_functions.is_visible`.
8. `organizations`/`access_requests` had no repository or route → dropped.
9. `embeddings` created before it's needed → deferred.
10. **`override_pairs.json` is baseline-read by narrowed parse** ([parser.py:1625](engine/parser.py#L1625), [parse_merge.py:114](engine/incremental/parse_merge.py#L114)) — mis-classified as scratch; missing it would break virtual-dispatch spreading ⇒ **stale impact analysis**.
11. **`func_keys.json` is baseline-read** ([engine.py:248](engine/incremental/engine.py#L248)) — now derived per version.
12. `metadata.json` (basePath/projectName/parseFingerprint) → `versions` columns.
13. `modules.json` is **dead code** — delete, don't migrate.
14. **`model_types` would have dropped struct `fields` and macro `value`/`text`** → `payload jsonb`.
15. `clang_include_paths.json` holds **machine-specific absolute paths** — derived, never stored (keep its *compute-once* property).
16. `functions_<scope>.json` is a query result → a `WHERE` clause (this **deletes** code in `_apply_incremental_plan`).
17. A "non-duplicated KB residue" table would be **empty** → no KB at any level.
18. The materialize-to-file shim was throwaway → replaced by the permanent `ModelSource` seam.
19. Version immutability is an **assumption**, valid only while UI editing is out of scope.
20. Even "whole KB in memory" was wrong — `builder.py` proves context is **local** (*"does NOT include callee BFS … only relevant callees are injected"*).
21. **Phase 1 parses every TU 3× with identical args** — ~11.9s of 13.05s (D-10).
22. `engine/flowchart/llm/` **shadows** `llm_core`, forcing ordered `sys.path.insert` — the real blocker to in-process (D-11).
23. `model_units`/`model_components` jsonb arrays were a **mechanical carry-over** of file shape — derived, not stored (D-13).
24. **Flowchart Mermaid JSONs are read ACROSS versions** ([flowcharts.py:39](engine/views/flowcharts.py#L39)) — they are storage, not artifacts. Moving them to rows **deletes** the splice/carry/prune machinery and fixes the `qualifiedName` **overload collision**.
25. **`versions/<id>/config.json`, datadict/macros CSVs, view outputs and `report.txt`** were all still file-resident in rev-6 — now in Postgres (D-14).
26. ⚠ **LATENT BUG — concurrent jobs corrupt each other.** `job_max_concurrency` defaults to **2** ([settings.py:47](api/services/settings.py#L47)) and jobs are rejected only **per project** ([jobs.py:110](api/routes/jobs.py#L110)) — but the pipeline writes a **single shared `model/` + `output/` at the repo root** (`cwd=repo_root`; `generate.py` does `_rmtree_force(project_root/output)`). Two jobs from different projects would clobber each other. Masked today because you run one at a time; it would surface on the shared office deployment. **The migration fixes it** — model becomes per-version rows and artifacts move to per-version dirs (D-3), after which `JOB_MAX_CONCURRENCY>1` is finally safe.
27. **Storage contradicted the incremental feature** — a full copy of every unchanged entity per version is the opposite of "don't redo unchanged work".
28. ⭐rev-8 — **rev-7's dedup was still a half-measure**: it shared heavy text but still wrote a *full row set* per version, repeating `Component|Unit|qname|params` strings everywhere. Fixed by the three-layer **manifest-of-pointers** model (D-9): stable `entities` + thin `entity_versions` + shared `content_blobs`. Carry-forward becomes pointer reuse (zero copying); "what changed" becomes a hash comparison — i.e. `classify` and storage are now the *same* idea. Doc 04's D3 "reuse index" had this instinct already; rev-8 promotes it from a side index over files to **the** storage model.
30. ⭐rev-8 — **UI/API audit found two breakages** (C-1 violations that would have shipped):
    (a) **Required version breaks the current UI** — [`jobs.ts:7`](web-app/src/services/api/jobs.ts#L7) has `version_tag?` *optional* and [`ProjectDetailPage.tsx:256`](web-app/src/pages/ProjectDetailPage.tsx#L256) sends `undefined` when blank. D-3 makes it required/unique ⇒ the form must make it mandatory and handle **409**. A **second creation path** (`VersionsPage`/`useVersionMutations`, `{tag, commit_sha…}`) must enforce the same uniqueness.
    (b) **D-8 as originally written would break the Team page** — the UI calls `/members`, `/members/invite`, `/members/{id}/role`, `/members/pending`, `/team`, `/access-requests`. **Corrected:** keep tables + endpoints, drop only enforcement.
    (c) **Watch:** [`mappers/job.ts`](web-app/src/services/mappers/job.ts) validates responses with **zod** — adding fields is safe, **renaming is not**. Keep the wire name `version_tag` even though the column is `version`.
31. ⭐rev-8 — **concurrency claim corrected**: defect 26 describes **today's** code only. Once model rows are per-version and artifacts per-version, concurrent jobs are safe. Residual work: give the clang-args response file a **per-run temp path** (it currently lives in the shared `model/` dir) and make `.mmdc_cache`/`.flowchart_cache` writes **atomic** (temp+rename) since two jobs may legitimately write the same content-addressed key. **Interim: set `JOB_MAX_CONCURRENCY=1` until the migration lands.**
