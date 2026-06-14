# Database Design Study — C++ Analyzer Production Platform

| | |
|---|---|
| **Document** | Database Design Study (DB selection) |
| **Project** | C++ Codebase Analyzer — Production Platform (POC → Production) |
| **Status** | Draft for Review |
| **Version** | 1.0 |
| **Date** | 2026-06-12 |
| **Prepared by** | _______________________ |
| **Reviewed by** | _______________________ |
| **Audience** | Engineering Leadership / Architecture Review |

---

## 1. Purpose & Scope

This document records the **database selection** for the production platform and the reasoning behind it. Unlike a purely forward-looking study, this decision is **grounded in the working POC**: because the analyzer already exists, we know the *concrete* shapes of data it produces and the *actual* queries the platform needs. We use that evidence to derive the selection factors, evaluate candidates, and conclude on a database.

**In scope:** the **operational database** — what stores the analyzer's model, the dependency graph, change-detection state, vector embeddings, jobs, users/RBAC, and the *latest* generated document per branch.

**Out of scope (deferred to a future phase):**
- **Object storage** for large binaries (rendered flowchart images, and documents at large scale). For now we keep **one latest document per branch** (and regenerate older states on demand), so a dedicated object store is **not** required yet. It will be its own study when image/document volume warrants it.

---

## 2. Requirements (short)

| ID | Requirement |
|---|---|
| **R1** | Multi-tenant, concurrent users |
| **R2** | Durable, queryable, structured storage to replace the POC's JSON files |
| **R3** | **LLM-result reuse by *similar* code** (vector similarity search) |
| **R4** | Store and serve the generated document |
| **R6** | User management with role-based access |
| **C2** | **Open-source only** (OSI-approved) |
| **C4** | **Highly available**, reliable, durable, consistent |

---

## 3. Storage estimation (structured/operational data)

> Database storage only — **excludes rendered images and the generated `.docx`** (object-storage phase). All figures are estimates to be validated by measurement.

**Assumptions**

| Assumption | Value |
|---|---|
| Functions per project | 20,000 |
| Other entities (globals / macros / types) | 3,000 |
| Branches kept (latest state each) | 10 |
| Tenants | share the codebase → **do not multiply** DB data |
| Embedding | one per function, 768-dim + HNSW index |
| v1 storage model | **per-branch** (no cross-branch dedup — that's the deferred history phase) |

**Per branch** (one project's latest state on one branch)

| Item | Calculation | Size |
|---|---|---|
| Function metadata + description + behaviour | 20,000 × ~2.3 KB | ~46 MB |
| Mermaid scripts (text) | 20,000 × ~3 KB | ~60 MB |
| Vector embeddings (+ HNSW index) | 20,000 × ~6 KB | ~120 MB |
| Other entities (globals/macros/types) | 3,000 × ~1.5 KB | ~5 MB |
| Dependency edges | ~250,000 × ~80 B | ~20 MB |
| Content hashes | 23,000 × 32 B | ~1 MB |
| **Per-branch total** | | **~250 MB** |

**Per project** = ~250 MB × **10 branches** ≈ **~2.5 GB**

**Whole platform**

| Projects | Logical (× ~2.5 GB) | Physical (× 3 replicas) |
|---|---|---|
| 10 | ~25 GB | ~75 GB |
| 50 | ~125 GB | ~375 GB |
| 200 | ~500 GB | ~1.5 TB |

*(Tenancy/RBAC + job-queue tables are platform-wide and tiny — a few MB.)*

**Observations**
- **Dominated by per-function content** (embeddings + Mermaid). The **×10 branches** is the main multiplier, because v1 stores each branch's data independently.
- **Cross-branch dedup (deferred history phase) would shrink this substantially** — branches share ~80–90% of code, so shared embeddings/Mermaid/entities could drop per-project from ~2.5 GB toward **~0.5 GB + small deltas**.
- **Confirms the scale assumption:** even at **200 projects** it is ~500 GB logical / ~1.5 TB physical — comfortably a **single primary + replicas**; **no distributed/sharded DB needed** (the basis for factor F5, §5).

---

## 4. Concrete data & query profile

The platform's data shapes and access patterns are concrete and well understood. Here is what the analyzer produces and what the platform must query.

### 4.1 The data we store

| Data | Shape | Notes |
|---|---|---|
| **Code entities** — functions, global variables, macros, types (struct/enum/typedef), units, modules | **relational**, well-defined schema, composite keys | the backbone of the model |
| **Nested / semi-structured fields** — parameters, behaviour names, raw model attributes | **document-like (JSON)** | varies per entity; benefits from flexible storage |
| **Dependency graph** — call edges, global-access edges, macro-use, type-use | **graph (edges)** | traversed for **impact analysis** (incremental updates) |
| **Content hashes** — one per entity (change detection) | small fixed values (32 bytes) | ~tens of thousands per project |
| **Vector embeddings** — one per function (similarity reuse) | **dense vectors** | for R3 |
| **Per-branch baseline** — latest commit SHA + latest document | small rows | for incremental + R4 |
| **Tenancy & RBAC** — tenants, projects, users, roles | relational | R1, R6 |
| **Jobs** — generation/queue state | relational | the work queue |

### 4.2 The queries / access patterns we need

| Pattern | Where it's used | Implication |
|---|---|---|
| **Bulk transactional writes** | a generation run inserts/updates thousands of entities, edges, hashes **atomically** | needs **ACID**; partial/orphaned state is unacceptable |
| **Graph traversal (transitive closure)** | **impact analysis** — "which entities depend on the changed one?" | needs **recursive graph queries** |
| **Exact-key lookups + hash compares** | change detection (stored vs current hashes) | indexed key lookups |
| **Vector nearest-neighbor (ANN)** | similarity reuse (R3) | needs **vector search** |
| **Relational reads with joins** | UI browse: modules → units → functions; fetch descriptions/flowcharts | needs **rich SQL / joins** |
| **Per-branch baseline lookup** | incremental: get a branch's last commit + doc | indexed lookup |
| **Tenant-scoped filtering** | every read filtered by tenant/project | indexing + row-level isolation |

---

## 5. Selection factors (derived from §4)

From the concrete data and queries above, the database must score well on these factors. *These are not abstract — each traces directly to §4.*

| # | Factor | Why it matters (from §4) |
|---|---|---|
| **F1** | **Multi-paradigm data model in one engine** (relational + document + graph + vector) | §4 shows all four shapes; one engine avoids polyglot complexity |
| **F2** | **ACID transactional integrity** | bulk generation writes must be atomic/consistent (C4) |
| **F3** | **Native graph traversal** (recursive/transitive closure) | impact analysis is the core query for incremental updates |
| **F4** | **Vector similarity search** | R3 result-reuse |
| **F5** | **Scale fit** | structured data is modest → **HA on one node**, *not* horizontal write-scaling |
| **F6** | **Licensing & longevity** (OSI open-source, on-prem, low abandonment risk) | C2 |
| **F7** | **Operational simplicity** (fewest moving parts on-prem) | reliability on-prem (C4) |
| **F8** | **Extensibility / graduation paths** | add specialized stores later only if a measured ceiling is hit |

---

## 6. Selected database — PostgreSQL (single-primary + HA), and why

> **Decision: PostgreSQL 16+** as the operational database, run for high availability via the **CloudNativePG** operator (1 primary + replicas), with the **pgvector** extension.

PostgreSQL is the only single open-source engine that scores well on **every** factor:

| Factor | How PostgreSQL satisfies it |
|---|---|
| **F1 — multi-paradigm** | **JSONB** (document/nested) + relational tables + **recursive CTEs** (graph) + **pgvector** (vectors) — all in one engine |
| **F2 — ACID** | first-class, mature transactional guarantees |
| **F3 — graph traversal** | `WITH RECURSIVE` for transitive closure; optional **materialized closure table** for hot impact-analysis reads |
| **F4 — vector search** | **pgvector** with HNSW ANN, filterable by tenant/project in the same query |
| **F5 — scale fit** | structured data fits one well-provisioned node; **CloudNativePG** gives HA/failover/PITR. (We scale *compute* in the stateless worker tier, not the DB) |
| **F6 — licensing & longevity** | **PostgreSQL License** (permissive, OSI-approved); mature, broadly governed; **very low rug-pull risk** |
| **F7 — operational simplicity** | one engine to run, secure, back up, and monitor on-prem |
| **F8 — graduation paths** | extensions/companions can be added later (vector store, graph engine) without re-architecting |

**The decisive insight:** our workload is *relational + graph + vector with strong-consistency needs at modest structured scale.* PostgreSQL covers all of it in **one** ACID engine, which is also the **lowest-risk** choice on the axis we care about most (open-source, on-prem, won't be abandoned).

---

## 7. Rejected options & why

| Option | License | Why rejected |
|---|---|---|
| **MongoDB** | SSPL | Weak at graph/relational; its vector search is tied to its managed cloud (not usable on-prem). Its one appeal (native JSON) is covered by Postgres **JSONB**. |
| **CockroachDB** | CSL | **Relicensed to source-available in 2024 → fails C2** (same basis as MongoDB). Distributed-scale we don't need; non-native vector. |
| **Citus / YugabyteDB** (distributed SQL) | AGPL / Apache-2.0 | Solve a **write-scaling problem we don't have** (our structured data fits one node). Add distributed-consensus operational complexity; less-mature pgvector than native Postgres. Retained as a *future* path only (§8). |
| **MySQL / MariaDB** | GPLv2 | Open source and viable, but weaker JSONB ergonomics and a far less mature vector ecosystem than pgvector for our JSON + graph + vector mix. |
| **SQLite** | Public Domain | Single-writer; cannot serve multi-tenant, concurrent, write-heavy generation (R1). Fine only for the POC. |
| **Neo4j / dedicated graph DB** | GPLv3 (Community) | Community edition has **no open-source clustering** (HA needs paid Enterprise) → boxes us in. Our graph need is **bounded transitive closure**, which Postgres recursive CTEs handle; a second datastore isn't justified. |
| **Qdrant / Milvus as the *primary* store** | Apache-2.0 | Excellent vector engines, but they **augment**, not replace, the metadata store. pgvector covers current scale; adding one now means extra ops + cross-store consistency. Retained as a future path (§8). |

---

## 8. Alternatives retained (graduation paths, not chosen now)

Deliberately kept open; none requires re-architecture to adopt.

| Concern | Current choice | Alternative | When we'd switch |
|---|---|---|---|
| Vector search | **pgvector** | **Qdrant** / **Milvus** (Apache-2.0) | when embedded vectors reach **tens of millions** and pgvector index build/memory strains |
| Graph traversal | **Postgres recursive CTE / closure table** | **Apache AGE** (graph *inside* Postgres) → **NebulaGraph** | only if graph queries deepen beyond transitive closure |
| Structured scale | **single Postgres + CNPG HA** | **Citus** / **YugabyteDB** | only if structured data ever outgrows one node (**not projected**) |

The principle: **start centralized on Postgres; specialize only when a measured limit forces it.**

---

## 9. Supporting details

### 9.1 High-level data shape (detailed schema is a separate document)

The database organizes into a few logical groups (tables to be specified in the schema doc):
- **Tenancy & access:** tenants, projects, users, roles.
- **Model entities:** functions, globals, macros, types, units, modules.
- **Dependency graph:** call / global-access / macro-use / type-use edges.
- **Change detection:** per-entity content hashes (keyed), per-branch baselines (commit + latest doc).
- **Generated content:** vector embeddings (for similarity reuse).
- **Operations:** the job queue.

### 9.2 High availability & durability

- **CloudNativePG** operator: 1 primary + 2 replicas with automatic failover.
- **PITR backups**; replicas provide read-scaling and failover.
- Survives a single node loss (a 3-node quorum tolerates 1 failure).

### 9.3 How the database serves the Incremental feature

The incremental feature needs **no additional database technology** — it is the reason we favored Postgres-with-CTEs over a graph DB:
- **Change detection** → per-entity content-hash rows (compare stored vs current).
- **Impact analysis** → recursive CTE / materialized closure table over the dependency-edge tables.
- **Per-branch baselines** → small lookup tables (latest commit SHA + latest doc).

*(The companion "Incremental Changes Design" document specifies this end-to-end.)*

### 9.4 Scope & deferrals

- **Object storage = future phase.** We keep **one latest document per branch** in the database for now (and regenerate older states on demand). When rendered-image / multi-version document volume grows, a dedicated object-storage study will follow.

### 9.5 Risks & mitigations

| Risk | Mitigation |
|---|---|
| Deep transitive-closure (impact analysis) gets slow at scale | **materialized closure table** maintained incrementally — *inside* Postgres, no new system |
| pgvector strains at very large vector counts | start function-level; keep the vector backend swappable; graduate to Qdrant/Milvus (§8) |
| Single primary is a write bottleneck *in principle* | our write load fits one node; graduation to Citus/Yugabyte documented (§8) if ever needed |
| Blob volume later (images/docs) | explicitly deferred to the object-storage phase (§9.4) |

---

## 10. Summary & recommendation

A POC-grounded evaluation — derived from the **actual** data shapes and query patterns the analyzer produces — converges on a single, clear choice:

> **PostgreSQL 16+ (with pgvector), run for HA via CloudNativePG.** It satisfies **every** selection factor in one open-source, on-premise, ACID engine: relational + JSONB (document) + recursive-CTE graph traversal + vector search, at our modest structured scale, with the lowest licensing/abandonment risk and the fewest moving parts.

**Recommendation:** adopt PostgreSQL as the operational database and proceed to the detailed **database schema design**. Object storage is intentionally deferred to a later phase.

---

## Appendix A — Glossary

| Term | Meaning |
|---|---|
| **ACID** | Atomicity, Consistency, Isolation, Durability — transactional guarantees protecting data integrity. |
| **JSONB** | PostgreSQL's binary, indexable JSON column — stores flexible/nested data inside a relational table. |
| **Recursive CTE** | A `WITH RECURSIVE` SQL query — walks relationships (e.g., transitive callers) directly in the database. |
| **Closure table** | A precomputed table of transitive relationships, for fast "who depends on X" lookups. |
| **pgvector / HNSW / ANN** | PostgreSQL extension for vector embeddings; HNSW indexes fast Approximate Nearest-Neighbor (similarity) search. |
| **CloudNativePG (CNPG)** | An open-source Kubernetes operator that runs PostgreSQL with replication, failover, and backups. |
| **PITR** | Point-In-Time Recovery — restoring the database to any past moment from backups + transaction logs. |
| **OSI** | Open Source Initiative — the body that approves licenses as genuinely open source. |
| **SSPL / CSL** | "Source-available" licenses (MongoDB / CockroachDB) that OSI did **not** approve as open source. |

---

_End of document._
