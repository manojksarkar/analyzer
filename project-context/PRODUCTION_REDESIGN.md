# Production redesign — the POC-to-production decisions

> **Project context — one part of it.** Start at [PROJECT_CONTEXT.md](../PROJECT_CONTEXT.md),
> the index: current state, how to read the context, every file. The sections below moved here
> from the single-file context on 2026-09-28, unchanged except link paths, and keep their numbers —
> "PROJECT_CONTEXT §N" still finds them. Some of it has drifted since: read the index's [What changed
> after the numbered sections](../PROJECT_CONTEXT.md#what-changed-after-the-numbered-sections) first.

**Sections:** [22. Production Redesign (POC → Production) — design decisions](#22-production-redesign-poc--production--design-decisions)

## 22. Production Redesign (POC → Production) — design decisions

> This section captures the forward-looking **production platform** design work done in the
> 2026-06 design sessions. Everything in §1–§21 is the **POC**; this is the plan to productionize it.
> **Full detail lives in three design docs under `docs/production-redesign/` (brought onto `version4`).
> Read those for depth — this section is the orientation + the decisions, so a fresh session can
> pick up without re-deriving them.** Where this section references analyzer specifics it uses this
> code line's `layers`/`component` terminology (§4d).

### 22.1 Design documents (read these for full detail)

- **`docs/production-redesign/01-technology-selection-study.md`** (v1.2) — overall production stack + deployment.
- **`docs/production-redesign/02-database-design-study.md`** — DB selection (PostgreSQL), POC-grounded, with storage estimation.
- **`docs/production-redesign/03-incremental-changes-design.md`** (**v1.2** — §12 records the chosen path: **Approach 2**, git-diff narrowed parse) — the incremental / delta regeneration feature.

### 22.2 The vision

A **multi-tenant, on-premise production platform**: users register a C++ project (a path or, going
forward, a **git/Bitbucket URL → clone**), the platform runs the analyzer and produces the ASPICE
SWE.3 document, browsable/downloadable in a UI. Must be **scalable, reliable, durable, consistent**.

### 22.3 Hard constraints (these drive every decision)

- **On-prem only** — C++ firmware IP must not leave the corporate network → **no cloud services**.
- **Open-source only (OSI-approved)** → rules out *source-available* licenses: **SSPL** (MongoDB),
  **CSL** (CockroachDB, since 2024), **BSL** (ArangoDB/Memgraph), and **MinIO/Redis** post-relicense.
- **Firmware-scale** — up to ~50k functions/project (~20k typical), ~40 tenants/project
  (tenants **share** the codebase, so they do *not* multiply data), 10+ branches/project.
- **Rewrite the analyzer to read/write the DB directly** (no more `model/`+`output/` JSON files) —
  this also removes the local-disk phase handoff, which is what enables **distributed workers**.

### 22.4 Selected stack (key decisions)

- **Database: PostgreSQL 16+** (single-primary + HA via **CloudNativePG/CNPG**) with **pgvector**.
  The **system of record** (replaces the JSON files).
  - *Why Postgres:* one engine covers **relational + JSONB (document) + recursive CTEs
    (graph/impact analysis) + pgvector (similarity)**; ACID; OSI open-source; on-prem; won't rug-pull;
    modest structured scale **fits one node**.
  - **NOT a distributed DB** (Citus/Cockroach/Yugabyte) — structured data fits one node; we scale the
    **stateless worker tier**, not the DB.
- **Job queue:** Postgres-as-queue (`SELECT … FOR UPDATE SKIP LOCKED`) — **not** RabbitMQ/Kafka/Redis
  (extra stateful system for throughput we don't need; long, few jobs).
- **Graph / impact analysis:** Postgres **recursive CTE / materialized closure table** (not a graph DB;
  **Apache AGE** is the in-Postgres graduation path, then NebulaGraph).
- **Object storage: DEFERRED to a future phase.** History worth knowing: chose MinIO → discovered
  **MinIO Community Edition was archived ("no longer maintained") in Feb 2026** → switched to
  **SeaweedFS** (Apache-2.0) → then **deferred object storage entirely for now**. v1: keep **latest
  document per branch** in the DB; **flowchart images generated on demand, not stored**; **Mermaid
  scripts kept in the DB** (text).
- **Deployment:** containers on **Kubernetes**, **3-node cluster** (quorum = 2, survives **1** node
  failure; 5 nodes survive 2). **Stateless tier** (API + workers) vs **stateful quorum-bound data
  core** (Postgres + etcd [+ object store later]). **Local SSD (NVMe-ready)** via TopoLVM/OpenEBS
  LocalPV; redundancy = **app-level replication** (CNPG), not a storage layer. No existing
  CSI/distributed storage. Worker VMs are **not** quorum members → scale them freely.
- **LLM:** internal **corporate gateway** (OpenAI-compatible, off-cluster) → **no GPU nodes** in-cluster.
- **Auth:** **in-app auth + RBAC on PostgreSQL** (simple roles now); **Keycloak + corporate SSO** is the
  graduation path. Tenant isolation via `tenant_id` + optional Postgres **Row-Level Security (RLS)**.

### 22.5 Rejected DB options (for the record)

- **MongoDB** — SSPL (not OSI); weak graph/relational; on-prem vector is Atlas-only.
- **CockroachDB** — CSL (not OSI since 2024); distributed-scale we don't need.
- **Citus / YugabyteDB** — solve a write-scale problem we don't have; AGPL (Citus); less-mature pgvector.
- **MySQL / MariaDB** — weaker JSONB; immature vector ecosystem vs pgvector.
- **SQLite** — single-writer; no multi-tenant concurrency.
- **Neo4j / dedicated graph DB** — GPLv3 Community has no open-source clustering; our graph need is
  bounded transitive closure that Postgres handles.
- **Qdrant / Milvus as the primary store** — augment, not replace; pgvector covers current scale
  (kept as a graduation path).

### 22.6 Incremental (delta) regeneration feature — design summary

Goal: **hours → minutes** for small changes (skip the rate-limited LLM work for unchanged functions).
"Incremental build for documents" (the make/ccache/Bazel principle).

- **Change detection — two layers:**
  - **`git diff --name-only`** for *which files* changed (fast, reliable — **not** its scattered hunk
    output).
  - **Entity hashing** for *which entities* changed: hash **four entity types — functions, globals,
    macros, types**. **Token-based** (libclang; ignores whitespace/indentation/CRLF, **includes
    comments**), **full SHA-256** (32 bytes, never truncated), one **uniform** hash per entity's source
    extent, **keyed by identity including the defining file/location** (so same-named macros/types in
    different files are distinct).
  - **One hash per entity** now; **per-artifact hashing is deferred**.
  - **Path matching folds case on EVERY platform** (`incremental/affected._norm`,
    `parse_merge._norm`). It used to fold only when `os.name == "nt"`, which cannot be right
    for a project parsed on one platform and regenerated on another: libclang reports a path
    as written, so a Windows parse records `01_SRC/x.cpp` where git says `01_src/x.cpp` —
    matched on Windows, not matched on Linux, and the file then read as unchanged with its
    entities keeping the baseline's hashes. These values are only ever set-membership keys
    ("is this file affected / should it be dropped"); everything stored keeps its ORIGINAL
    casing. So folding everywhere can only consider one file too many, which costs a
    re-parse — the sound direction (D7) — where matching too few is a stale document. The
    one real cost is a repo holding two paths differing only by case (separate TUs on
    Linux): `affected.case_collisions` finds them and the parser logs them, so the
    over-approximation is never silent.
    *Not done:* canonicalising STORED paths to git's spelling. That changes model data and
    would make existing baselines mismatch — deliberately deferred; the fold above delivers
    the cross-platform correctness without touching stored data.
  - **A cross-version splice must land BOTH halves — the DOT and every PNG.** Measured on a
    real project (v5 baseline, v7 correct, v8 a second incremental off v5): one function's
    stored graph came from v5 while its picture came from v7, and the function beside it got
    both from v5. Two independent defects in `views/flowcharts.py`, each silent:
    (a) `_merge_incremental_flowcharts` read `fresh` straight from `out_dir`, but
    `_carry_forward_flowcharts` has already copied every BASELINE json there — for a unit
    whose changed functions were *all* diverted to cross-version reuse the engine writes
    nothing, so baseline entries posed as engine output and won the `fresh > x-ver >
    baseline` precedence. A cross-version DOT could never take effect. Now intersected with
    `fresh_pairs`, which is exactly what the engine was handed.
    (b) the image copy handled one filename, `<stem>_<qn>.png`. A flowchart too tall for one
    image is written `_part_1_of_N.png` … and no plain `.png` exists, so nothing was copied
    and the carried baseline images stayed — a big flowchart kept the old picture while a
    small one beside it updated, same unit, same run. `_splice_function_pngs` now takes every
    part and clears the carried ones first, so a shrunken part count leaves no orphan page.
  - **A version AT the target commit is never the auto baseline.** Git calls a commit its own
    ancestor, so a prior version at the target sits at distance 0 — nearer than any real
    ancestor — and won `nearest_ancestor` every time. The run then found **zero changed files**,
    re-parsed nothing, and wrote a verbatim copy of that version (same model, same hashes, same
    flowcharts), logged only as `0 affected TU(s) — reused the baseline skeleton`. Regenerating a
    commit is asked for precisely when the existing version at it is wrong, so the copy reproduced
    the defect. `baseline._auto_candidates` now excludes them and the skip is reported in
    `warnings`; an explicit `--base-version-id` at the target is still honoured, with a warning
    saying the result will be a copy. `generate_incremental` already excluded the run's OWN
    version id for this reason — that only covered a version reserved at its own commit, not a
    *different* version id sitting at the same commit.
  - **Never hash an empty token list.** `clang_tokenize` returns *no tokens* for some perfectly
    valid cursors — a declaration produced by a macro expansion is the common trigger — with **no
    error and a correct-looking extent**. `hash_cursor` used to hash `[]`, so every such entity got
    `sha256("")`: one constant shared by all of them, classified **unchanged in every comparison
    forever**, flowchart and LLM description carried forward from the first version, nothing logged.
    Measured on one firmware project: **2069 of 2818 functions (73%)**, which silently disabled
    incremental change detection for most of the codebase. `hash_cursor` now falls back to the
    extent's **raw source text** (whitespace-split, so reformatting still is not a change), then to
    **name + position** if the file cannot be read — the latter regenerates whenever the entity
    moves, which is the sound direction (D7) rather than pinning it to "unchanged". Counts are
    exposed as `hash_cursor.fallbacks` and logged at end of parse.
    *Recovery:* baselines parsed before this fix hold the constant for those entities, so the first
    run after it reclassifies them all as changed — a one-time large regeneration, and the correct
    repair. `tools/why_unchanged.py` reports how many a stored version is carrying.
  - Classification: unchanged / changed / new / deleted; **move/rename = delete(old key) + add(new key)**.
  - *Why hash globals/macros/types separately:* changing a global/macro/type does **not** change a
    *using* function's tokens (a function still just writes `MAX` after `#define MAX` changes value), so
    those entities must be hashed on their own; impact analysis then refreshes the functions that use them.
- **Impact analysis (dependency-graph propagation):** changes flow **UP to callers/users**. Axes:
  **call graph (transitive callers), type usage, globals, macros, containment (file/component/project
  summaries), diagrams (call-edge changes), cross-group**. Hard cases: **indirect calls / virtual
  dispatch → over-approximate** (treat as edges to all overrides / any address-taken function);
  **move/rename → key change**. Algorithm: reverse-reachability BFS / recursive CTE / closure table over
  the stored edges.
- **Selective regeneration:** re-run the LLM only for the impact set; **reuse** stored outputs for the
  rest. **Reassemble** the document from pieces (re-run Phase 3 views + Phase 4 export; **not** in-place
  patching).
- **Chosen approach & baseline (updated — see `docs/production-redesign/03` §12, v1.2):** v1 uses
  **Approach 2** — **git-diff narrowed parse** (parse only changed files; reuse the baseline version's
  stored model + outputs for the rest) + **stored-graph impact** + **selective regen**. The product model
  is **a document version per code version, branch-agnostic** — each generation stores its own document +
  metadata; reuse is **content-addressed across all generated versions**. The diff baseline is the
  **nearest generated ancestor** (via `git merge-base`), with **Approach 1's full parse as the fallback**
  for first-generation / no-ancestor / diverged history.
- **Versioning:** a document version per generation; **full Git-style cross-version dedup is deferred**.
- **Tech additions (no new DB or system):** the **`git` CLI** in the worker image + **repo credentials**
  (SSH deploy key or HTTP access token, from a deployment-appropriate secrets store — K8s Secrets / Vault
  / env injection; the project owner supplies it at registration, stored encrypted). Operator-side recipe
  changes (LLM model/prompts/config) → a manual full-regen, separate from the user's code-diff path.

### 22.7 Storage estimation (DB structured data only; excludes images/docs)

- **~250 MB / branch** (20k functions + 3k entities), dominated by **embeddings (~120 MB) + Mermaid
  (~60 MB)**.
- **~2.5 GB / project** (×10 branches; v1 stores per-branch, no cross-branch dedup).
- Platform: ~25 GB (10 projects) → **~500 GB logical / ~1.5 TB physical at 200 projects** → a
  **single primary + replicas** comfortably suffices.
- Cross-branch dedup (deferred) would shrink ~2.5 GB → **~0.5 GB + small deltas**.

### 22.8 Explicitly deferred to later phases

- **Object storage** (images, documents at scale).
- **Per-artifact hashing** (finer-grained reuse — e.g. a comment-only change reusing the flowchart).
- **Image-render cache** (skip re-rendering unchanged flowcharts — tied to object storage).
- **Full version history** (Git-style dedup across versions/branches).
- **Non-Functional Requirements section** for the DB study.

### 22.9 What's next

- **Incremental implementation (in progress on `version4`)** — Approach 2 over the current JSON-file
  pipeline first, to migrate to Postgres later. Workstreams: git ingestion + project onboarding, per-project /
  per-version storage, entity hashing + dependency-edge persistence, the detect→impact→regenerate→reassemble
  engine wired into Phases 1–4, and the supporting APIs (onboard / projects / branches / commits / generate).
- **Detailed database schema design** — tables for entities, dependency edges, `{key → hash}` records,
  per-version baselines, RBAC, and the job queue (owned by the DB engineer).
- (Optional) the NFR section for the DB study; the object-storage study (future phase).

### 22.10 Cross-cutting lessons from this session

- **MinIO Community Edition is dead** (archived Feb 2026); **SeaweedFS** (Apache-2.0) is the maintained
  alternative *if/when* object storage is needed.
- **Watch licensing rug-pulls:** SSPL / CSL / BSL / RSAL are *source-available, not OSI*. PostgreSQL
  (PostgreSQL License) is the low-risk anchor; **Valkey** is the OSI-clean Redis fork.
- **Hashing for change detection** must be **token-based** (to ignore formatting/CRLF) and **full
  SHA-256** (collisions effectively impossible). A *token change is always a line change*, so git diff
  never *under*-detects — it only over-detects on formatting, which is the safe direction.
- **The whole incremental design biases to over-regenerate, never to stale** — every ambiguous case
  (indirect/virtual calls, formatting noise, non-ancestor commits) regenerates *more*, with a manual
  full-regen escape hatch.

---

