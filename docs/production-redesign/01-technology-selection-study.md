# Technology Selection Study — C++ Analyzer Production Platform

| | |
|---|---|
| **Document** | Technology Selection Study |
| **Project** | C++ Codebase Analyzer — Production Platform (POC → Production) |
| **Status** | Draft for Review |
| **Version** | 1.0 |
| **Date** | 2026-06-07 |
| **Prepared by** | _______________________ |
| **Reviewed by** | _______________________ |
| **Audience** | Engineering Leadership / Architecture Review |

---

## 1. Purpose & Scope

The C++ Codebase Analyzer currently exists as a **proof of concept (POC)**: a CLI pipeline plus a thin FastAPI wrapper that stores all state as JSON files on local disk. We are now moving to a **production platform** that must be **scalable, reliable, durable, and consistent**, multi-tenant (many C++ project teams), and deployed **on-premise**.

This document records the **technology choices** made for that platform, the **reasons** each was selected, the **options that were rejected** (with reasons), and the **alternatives** that remain available as future graduation paths. Its purpose is to demonstrate that a structured evaluation was performed **before** committing to an implementation.

This is a **selection study**, not an implementation plan. Detailed database schema, deployment topology, and migration sequencing are separate follow-up documents.

---

## 2. Background

The production platform must deliver five capabilities beyond the POC:

1. **Self-service multi-tenant UI** — any C++ project team registers a project (name + path or Git URL), triggers generation, views and downloads the resulting Software Detailed Design document.
2. **Durable structured storage** — replace the JSON-file model/output store with a real database.
3. **LLM result reuse** — store every LLM result against its input (code block), so that on later runs *similar* code can reuse a prior result as an in-context example, giving the whole document a consistent English tone.
4. **Final document storage** — a robust place to keep the generated Word documents.
5. **Incremental regeneration** — when a team changes their C++ code and re-runs, regenerate **only** the changed functions and the functions that depend on them — not the entire document.

Capabilities **2, 3, and 5 are one underlying data-model problem** (versioned, content-addressed metadata with a dependency graph and similarity search); the technology choices are made to serve all three together.

---

## 3. Requirements & Constraints (the basis for selection)

| ID | Requirement / Constraint | Type | Impact on selection |
|---|---|---|---|
| **R1** | Multi-tenant, self-service, concurrent users | Functional | Needs concurrent write-capable DB + background workers + queue |
| **R2** | Durable, queryable, structured storage replacing JSON | Functional | Needs relational + flexible (JSON) storage with ACID |
| **R3** | LLM result reuse by *similar* code block | Functional | Needs content-hash + **vector similarity search** |
| **R4** | Store & serve final Word documents | Functional | Needs blob/object storage |
| **R5** | Incremental (delta) regeneration | Functional | Needs versioning + **dependency-graph traversal** |
| **R6** | **User management with simple role-based access** — users log in and self-register C++ projects | Functional | App-layer auth + role tables in PostgreSQL; tenant-scoped data access |
| **C1** | **On-premise only** — C++ firmware IP must not leave the corporate network | Constraint | Rules out all managed cloud services |
| **C2** | **Open-source only** | Constraint | Rules out commercial DBs and source-available (non-OSI) licenses |
| **C3** | **Very large scale** — 500k+ functions per project, many tenants | Constraint | Needs partitioning, indexing, scalable vector strategy |
| **C4** | **Reliable / durable / consistent** | Non-functional | Favours ACID + HA + backups |
| **C5** | Analyzer to be **rewritten to use the DB directly** | Decision | DB becomes system of record; removes local-file handoff |
| **C6** | LLM served via **internal corporate gateway** (OpenAI-compatible API) | Given | No GPU nodes needed in-cluster |
| **C7** | Storage = **local NVMe per server**; no existing distributed storage (Ceph/vSAN/NAS) | Given | Redundancy must come from app-level replication |
| **C8** | Container deployment on a **new (greenfield) cluster** | Decision | Kubernetes + operators |

---

## 4. Decision Principles (the lens applied)

These principles were applied consistently when choosing between options:

1. **On-prem, fewer moving parts = higher reliability.** Every additional datastore is one more system to secure, back up, patch, monitor, and keep consistent. Prefer one strong engine over several specialised ones until a measured limit forces otherwise.
2. **Keep graduation paths open.** Avoid choices that box us in (e.g. an engine whose open-source tier cannot cluster). Prefer designs where scaling out is "add a swappable component," not "re-architect."
3. **Strong consistency where data integrity matters.** Generation runs update many related records; ACID transactions protect correctness (C4).
4. **Redundancy at the right layer.** With local NVMe (C7), redundancy is provided by the application (DB replication, object-store erasure coding), not by a storage layer.
5. **Open-source in the OSI sense.** "Source-available" licenses (SSPL, RSAL) do **not** satisfy C2.

---

## 5. Selected Technology Stack

> Requirement IDs reference §3. Licenses verified as OSI-approved open source unless noted.

| # | Layer / Concern | Selected | License | Primary Reasons | Satisfies |
|---|---|---|---|---|---|
| 1 | **Primary database** | **PostgreSQL 16+** | PostgreSQL (BSD-like) | ACID + strong consistency + maturity; **JSONB** for schema-loose model data; one engine covers relational + document + vector + graph needs → fewest moving parts on-prem | R2, R3, R5, C4 |
| 2 | **Vector similarity search** | **pgvector** (Postgres extension) | PostgreSQL | Embeddings + HNSW ANN **co-located** with metadata, so similarity search can be filtered by tenant/project in one query; no separate system to operate | R3 |
| 3 | **Object / blob storage** | **MinIO** (distributed) | AGPLv3 (OSI-approved) | S3-compatible, self-hostable on-prem; **built for** clustered, erasure-coded storage on local disks; keeps large binaries out of the DB | R4, C1, C7 |
| 4 | **Background job queue** | **PostgreSQL table + `SELECT … FOR UPDATE SKIP LOCKED`** | PostgreSQL | Zero extra infrastructure; **transactional with the data** (no lost/orphaned jobs); durable; throughput is ample for long-running generation jobs | R1, R5 |
| 5 | **Graph / impact analysis** | **Postgres recursive CTE + materialized closure table** | PostgreSQL | The only graph query we run is **bounded transitive closure** ("who depends on changed function F?"); a dedicated graph DB is not justified | R5 |
| 6 | **Analyzer ↔ storage integration** | **Direct DB read/write (phases rewritten)** | — | Removes the current local-disk file handoff between phases, so phases / sub-jobs can run on **any** node — the enabler for distributed workers | R2, R5, C5 |
| 7 | **Container orchestration** | **Kubernetes** | Apache 2.0 | Self-hostable standard; rich operator ecosystem (CloudNativePG, MinIO); rolling updates; horizontal scale | C3, C4, C8 |
| 8 | **PostgreSQL HA** | **CloudNativePG operator** | Apache 2.0 | Automated primary + replicas, failover, and **PITR backups to MinIO**; designed for local-disk streaming replication | C4 |
| 9 | **Storage substrate** | **Local NVMe + TopoLVM / OpenEBS LocalPV** | Apache 2.0 | Fastest, simplest; avoids a distributed storage layer (the hardest part of on-prem K8s); redundancy provided by app-level replication | C4, C7 |
| 10 | **Application tier** | **Stateless FastAPI API + stateless analyzer workers** | — (in-house) | Horizontal scale on any node; rolling updates; job/state lives in the DB, not process memory | R1, C3 |
| 11 | **LLM access** | **Internal corporate gateway** via existing unified `LlmClient` (OpenAI-compatible) | — (given) | C++ IP stays on-network; reuses existing client; **no GPU nodes needed** in-cluster | C1, C6 |
| 12 | **Cluster size** | **3 nodes to start; 5 if 2-failure tolerance required** | — | 3 nodes survive **1** failure (quorum = 2); 5 survive **2** (quorum = 3). Start lean, scale by uptime need | C4 |
| 13 | **Backup / DR** | **PITR (CloudNativePG → MinIO) + off-cluster copy** | — | Replication is **not** backup; protects against logical errors (e.g. a bad delete that replicates instantly) | C4 |
| 14 | **Authentication & RBAC** | **In-app auth on PostgreSQL** — FastAPI + argon2id password hashing, signed token/session, `roles`/`user_roles` tables, optional Row-Level Security | — (in-house) | Simple role model needs no separate IAM; reuses the DB + API already selected; tenant data-scoping enforceable in Postgres (RLS) | R1, R6 |

---

## 5.1 Architecture Diagram

The two diagrams below realise the stack in §5. The first is the **logical view** (components and how a request and a generation job flow through them); the second is the **physical deployment topology** on a 3-node cluster (the High-Availability behaviour of items #7–#13).

### 5.1.1 Logical architecture & flows

```text
                    +-----------------------------------------------+
   TENANTS          |  Web browser  (multi-tenant C++ project teams)|
                    +-----------------------+-----------------------+
                                            | HTTPS
                                            v
                              +--------------------------+
   EDGE                       |  Ingress / Load Balancer |
                              +-------------+------------+
                        +-------------------+--------------------+
                        v                                        v
                +-----------------+               +-----------------------+
   APP TIER     |  Web UI         |   REST/JSON   |  FastAPI API  x N      |
   (stateless,  |  (Vite/React)   |-------------->|  - enqueue job         |
    any node)   +-----------------+               |  - read model/status   |
                                                  |  - stream .docx        |
                                                  +-----------+------------+
                                                              | (1) enqueue
                        +-------------------------------------+ (3) r/w model
                        |                                     |
                        v (2) claim job (SKIP LOCKED)         | (3) r/w model + results
              +---------------------------------+            |
              |  Analyzer Workers x M           |            |
              |   P1 Parse  (libclang)          |            |
              |   P2 Derive (+ LLM) ------------|--(4) LLM-->[ LLM GATEWAY ]
              |   P3 Views  (+ mmdc PNG)        |            |
              |   P4 Export (.docx) ------------|--(5) blob->[ MinIO ]
              +----------------+----------------+            |
                               | (3) read/write model        |
                               v                             v
   DATA TIER  +--------------------------------------+   +------------------------+
   (stateful, |  PostgreSQL 16 + pgvector  (CNPG)    |   |  MinIO (distributed)   |
    on local  |  primary --> replica --> replica     |   |  erasure-coded:        |
    NVMe)     |  - model: functions / units / modules|   |   - generated .docx    |
              |  - call graph + closure (impact, R5) |   |   - flowchart PNGs     |
              |  - LLM results + embeddings (R3)     |   +-----------+------------+
              |  - jobs queue (SKIP LOCKED)         |               ^
              |  - blob pointers --------------------|---------------+
              +--------------------------------------+

   EXTERNAL   +-------------------------------------------------------------+
   (off-      |  Internal Corporate LLM Gateway (OpenAI-compatible API)      |
    cluster)  |  -- code-derived prompts stay on the corporate network --    |
              +-------------------------------------------------------------+
```

**Flow walkthrough**

1. **Start a job** — the UI calls the API; the API writes a `jobs` row (enqueue) in the *same transaction* as the run record and returns a job ID immediately. *(Selected #4, #10)*
2. **Claim** — an idle Analyzer Worker picks the job with `SELECT … FOR UPDATE SKIP LOCKED`; no two workers get the same job. *(Selected #4)*
3. **Run phases against the DB** — the worker executes Phase 1–4, reading/writing the model, call graph, LLM results and embeddings *directly in PostgreSQL* — no local-file handoff. *(Selected #1, #2, #5, #6)*
4. **LLM enrichment** — workers call the internal gateway over HTTPS; this is the only path code-derived prompts take, and only to the on-network gateway. *(Selected #11)*
5. **Store artifacts** — the generated `.docx` and PNGs are written to MinIO; their pointers (object key + checksum) are saved in Postgres. *(Selected #3)*
6. **Read / download** — the UI polls status via the API; on completion the API streams the `.docx` from MinIO.

### 5.1.2 Physical deployment topology (3 nodes)

```text
+---------------- KUBERNETES CLUSTER . 3 NODES . quorum = 2 -----------------+
|                                                                           |
|  +------- NODE 1 --------+  +------- NODE 2 --------+  +----- NODE 3 -----+|
|  | etcd (quorum member)  |  | etcd (quorum member)  |  | etcd (quorum)    ||
|  | FastAPI API pod       |  | FastAPI API pod       |  | API pod          ||
|  | Analyzer Worker pod(s)|  | Analyzer Worker pod(s)|  | Worker pod(s)    ||
|  | Postgres PRIMARY(CNPG)|  | Postgres replica      |  | Postgres replica ||
|  | MinIO server + drives |  | MinIO server + drives |  | MinIO + drives   ||
|  | [ local NVMe ]        |  | [ local NVMe ]        |  | [ local NVMe ]   ||
|  +-----------------------+  +-----------------------+  +------------------+|
|                                                                           |
|  Redundancy is APP-LEVEL (local NVMe does not move between nodes):         |
|    - Postgres -> CNPG streaming replication (primary + 2 replicas)         |
|    - MinIO    -> erasure coding across the three nodes' drives             |
|    - Backups  -> CNPG PITR to MinIO, plus an off-cluster copy              |
|                                                                           |
|  Failure behaviour (see also Sec 8.6):                                     |
|    - lose 1 node  -> quorum holds (2/3): Postgres fails over, MinIO stays  |
|                      read/write           =>  PLATFORM STAYS UP            |
|    - lose 2 nodes -> quorum lost (1/3): writes halt by design to prevent   |
|                      split-brain          =>  PLATFORM DOWN                |
+---------------------------------------------------------------------------+
                    | LLM requests (HTTPS)
                    v
        +------------------------------------------------+
        |  Internal LLM Gateway (off-cluster, corp net)  |
        +------------------------------------------------+
```

> Scaling to **5 nodes** keeps the same shape — more API/worker pods and Postgres/MinIO members — and raises quorum to 3, so the platform then survives **two** simultaneous node failures (item #12).

---

## 6. Rejected Options

| Concern | Option Rejected | License | Why Rejected |
|---|---|---|---|
| Primary store | **MongoDB** | SSPL | **SSPL is source-available, not OSI open-source** → fails C2 and is commonly blocked by corporate OSS policy. Also weaker relational integrity / cross-entity consistency for the dependency graph (R5). |
| Graph store | **Neo4j / dedicated graph DB** | GPLv3 (Community) | Community edition has **no open-source clustering** (HA requires paid Enterprise) → boxes us in. Our graph need is bounded transitive closure that Postgres handles; avoids a second datastore. |
| Vector store (as primary) | **Qdrant / Milvus** | Apache 2.0 | Excellent, but they **augment** rather than **replace** the metadata store. pgvector covers current scale; adding a separate store now means extra ops + cross-store consistency. Retained as a future path (§7). |
| Primary store | **SQLite** | Public Domain | Single-writer; cannot serve multi-tenant, write-heavy, concurrent generation (R1, C3). Acceptable for the POC only. |
| Primary store | **MySQL / MariaDB** | GPLv2 | Open source and viable, but weaker JSONB ergonomics and a far less mature vector ecosystem than pgvector for our JSON + vector + graph mix. |
| Job broker | **Redis / RabbitMQ (now)** | RabbitMQ: MPL 2.0; Redis: see note | An extra **stateful** system to cluster and operate. Postgres-as-queue meets our throughput for long jobs. *Note:* Redis core left BSD in 2024 (RSAL/SSPL) — the OSI-clean fork is **Valkey**. Retained as a future path (§7). |
| Everything | **Managed cloud services** (RDS, S3, Cloud SQL, managed vector) | — | Violates **C1** (on-prem only — firmware IP cannot leave the network). |
| Storage layer | **Ceph / Longhorn / distributed storage** | LGPL / Apache 2.0 | Unneeded complexity. Local NVMe + app-level replication is faster and simpler; distributed storage is the hardest part of on-prem K8s. Retained as a future path (§7). |
| Document storage | **Word docs as DB BLOBs** | — | Bloats the database, slows backup/restore, hurts performance. Object storage (MinIO) is the standard pattern. |
| Storage model | **JSON files as system of record** (status quo) | — | No indexing, querying, transactions, or concurrency control. Not scalable, durable, or consistent (R2, C3, C4). |
| LLM hosting | **Self-hosted GPU LLM nodes (Ollama in-cluster)** | — | Unnecessary — an internal corporate gateway is available (C6). Avoids significant GPU cost and node complexity. |

---

## 7. Alternatives Retained (Graduation Paths)

Choices made deliberately keep these alternatives available. None require re-architecture to adopt.

| Concern | Current Choice | Alternative | When we would switch |
|---|---|---|---|
| Vector search | pgvector | **Qdrant** / **Milvus** (Apache 2.0) | When embedded chunks reach **tens of millions** and pgvector index build time / memory strains. (Mitigated by starting with function-level embeddings.) |
| Job queue | Postgres SKIP LOCKED | **Valkey** (BSD) + RQ/Arq, or **RabbitMQ** (MPL 2.0) | When job throughput exceeds the DB-queue comfort zone or we need pub/sub fan-out. |
| Graph queries | Postgres CTE + closure table | **Apache AGE → NebulaGraph** (see §7.1) | If traversal / pattern-matching needs deepen substantially beyond transitive closure. |
| Storage substrate | Local NVMe | **Ceph** (LGPL) / **Longhorn** (Apache 2.0) | If stateful pods need volume mobility or shared RWX volumes across nodes. |
| Cluster size | 3 nodes | **5 → 7 nodes** | For higher simultaneous-failure tolerance (5 survives 2, 7 survives 3). |
| Orchestrator | Kubernetes | **Nomad** / **Docker Swarm** / **Patroni-on-VMs** | If full Kubernetes proves too heavy for the team's operational capacity. |
| Identity / Auth | In-app auth on PostgreSQL (local accounts, simple roles) | **Keycloak** (Apache 2.0) + corporate SSO (LDAP / AD / OIDC) | When SSO / directory federation, richer token management, or a full IAM admin UI is required. |

### 7.1 Graph database candidates (if invoked)

Our graph workload is **bounded transitive closure** — impact analysis of the form "which functions depend on changed function F?" It is *not* deep, real-time, multi-hop pattern matching. Therefore **PostgreSQL recursive CTEs + a materialized closure table are expected to suffice for a long time**, and a dedicated graph database is a **contingency, not a planned step**. If it is ever invoked, candidates were evaluated against the same constraints as everything else (OSI open-source, self-hostable on-prem, ideally with open-source clustering):

| Candidate | License | Fit for our use case | Caveat |
|---|---|---|---|
| **Apache AGE** | Apache 2.0 | **Best aligned** — adds openCypher graph queries *inside* PostgreSQL. No new datastore; inherits CloudNativePG HA and backups; preserves the "one engine, fewest moving parts" principle. **Recommended first step.** | Younger project; very-large-scale performance less proven; tracks specific PostgreSQL major versions. |
| **NebulaGraph** | Apache 2.0 | **Best for true distributed scale** — designed for billions of edges with **native open-source clustering**. Use only if a genuinely distributed, dedicated graph engine is required at firmware scale. | Operationally complex (separate meta / storage / graph daemons); smaller Western community. |
| **JanusGraph** | Apache 2.0 | Massive scale via a pluggable storage backend. | Heavy footprint — requires Cassandra/ScyllaDB **plus** Elasticsearch underneath (many moving parts on-prem). |
| **Neo4j Community** | GPLv3 | Most mature tooling and Cypher ecosystem. | **No open-source clustering** (HA requires the paid Enterprise edition) — the same reason it was not chosen as the primary store. Single-node use only. |

**Rejected on license grounds** (source-available, *not* OSI-approved — same basis as the MongoDB/SSPL rejection in §6): **ArangoDB** (moved to BSL in 2023), **Memgraph** (BSL), **Dgraph** (license churn / uncertain status), **TigerGraph** (commercial).

**Direction:** if graduation is ever needed, **Apache AGE first** (stays inside PostgreSQL), and **NebulaGraph** only if a distributed dedicated engine becomes necessary.

---

## 8. Key Decision Rationale (expanded)

**8.1 Why a PostgreSQL-centric design.**
Requirements R2, R3, and R5 are three views of one data-model problem: versioned metadata, similarity search, and dependency-graph traversal. PostgreSQL covers all three in a single ACID engine — JSONB (flexible model data), pgvector (similarity), recursive CTEs (graph) — plus blob *pointers* for MinIO. One engine means one thing to back up, secure, and keep consistent. For on-prem, that operational simplicity is itself a reliability feature (Principle 1).

**8.2 Why MinIO for documents, not the database.**
Generated `.docx` files and flowchart PNGs are large binaries. Storing them in the DB bloats it and slows backup/restore. MinIO is purpose-built for clustered, erasure-coded object storage on local disks — exactly our environment (C7) — and is S3-compatible, so the application uses a standard interface.

**8.3 Why the queue lives in Postgres (for now).**
A generation run is a long, heavy background job and cannot run inside an HTTP request. The work must be handed to background workers via a queue, which also gives durability, retries, and backpressure (protecting the rate-limited LLM gateway). `SELECT … FOR UPDATE SKIP LOCKED` turns an ordinary table into a safe multi-consumer queue with **no extra infrastructure** and **transactional enqueue** (the job is created in the same transaction as the run record, so it can never be lost). A dedicated broker is a documented future path if throughput ever demands it.

**8.4 Why local NVMe with app-level replication.**
Local NVMe is the fastest and simplest substrate and lets us skip a distributed storage layer. The non-negotiable rule: because local disk is node-pinned, **redundancy must come from the application** — CloudNativePG keeps streaming replicas on other nodes' NVMe, and MinIO erasure-codes across nodes. A single stateful pod on one local disk with no replica is never acceptable.

**8.5 Why the analyzer is rewritten to use the DB directly.**
The current pipeline hands work between phases via files on local disk, which assumes a single machine. In a cluster, a later phase may run on a different node with no access to that disk. Writing directly to the DB (and blobs to MinIO) removes every local-disk handoff, which is what makes distributed, horizontally-scaled workers possible.

**8.6 Why 3 nodes to start (and what 5 buys).**
Quorum = majority must be alive. With 3 nodes, majority is 2, so the cluster survives **one** node failure; losing two breaks quorum and halts writes (by design, to prevent split-brain). 5 nodes raise quorum to 3, surviving **two** failures. The choice is a tolerance/cost trade-off, not a capacity one: start at 3 for an internal tool, move to 5 if uptime expectations rise.

**8.7 Why in-app auth on PostgreSQL (initially).**
The initial role model is simple (e.g. Platform Admin / Team Owner / Maintainer / Viewer), so a dedicated identity server is unnecessary. Authentication and RBAC are handled in the FastAPI layer with user, role, and membership tables in the PostgreSQL we already run — no new infrastructure. Enforcement is at two layers: *functional* permissions (which actions an endpoint allows) and *data scoping* (which tenant's rows a user may touch), the latter optionally hardened with Postgres **Row-Level Security** so an application bug cannot leak another team's IP. The `users` table carries an `auth_provider` field from day one, so corporate SSO / Keycloak federation (§7) can be added later **without a data migration**. An audit table records who registered, edited, or generated each artifact — useful for the ASPICE compliance posture.

---

## 9. Known Risks & Mitigations

| Risk | Mitigation |
|---|---|
| On-prem Kubernetes is greenfield; operational maturity required | Start 3-node; use managed operators (CloudNativePG, MinIO operator); lighter orchestrator available as fallback (§7) |
| Local NVMe is node-pinned (data does not move) | App-level replication (CNPG, MinIO erasure coding) + PITR backups; never run single-replica stateful workloads |
| Two simultaneous node failures on a 3-node cluster cause an outage | Accept for an internal tool, or provision 5 nodes for 2-failure tolerance |
| pgvector scaling ceiling at very-large embedding counts (C3) | Start with function-level embeddings; keep the vector backend swappable; graduate to Qdrant/Milvus if needed |
| MinIO is AGPLv3 — some corporate policies scrutinize AGPL | Confirm with legal/OSS review; alternatives (Ceph, SeaweedFS) available if blocked |
| Analyzer DB rewrite is a substantial change (C5) | Phased migration; the existing pipeline contract (PROJECT_CONTEXT) remains the source of truth |
| "Replication is not backup" — logical errors replicate instantly | Enforce PITR + off-cluster backup copy + periodic restore drills |
| Local accounts mean the platform stores user credentials | Hash with **argon2id**, enforce a password policy, design `users` for federation from day one, and plan migration to corporate SSO / Keycloak (§7) |

---

## 10. Summary & Recommendation

A structured evaluation against our requirements (R1–R5) and hard constraints (on-prem, open-source, firmware-scale, reliable/durable/consistent) converges on a **PostgreSQL-centric, open-source, on-premise stack**:

> **PostgreSQL 16+ (with pgvector) as the system of record · MinIO for documents · job queue inside Postgres · Kubernetes on local NVMe · CloudNativePG for database HA · MinIO distributed for object-store HA · stateless API + workers · LLM via the internal corporate gateway · in-app auth + RBAC on PostgreSQL · 3-node cluster to start.**

This stack satisfies every requirement and constraint, minimises the number of systems to operate on-prem (a reliability benefit), and preserves clear graduation paths (dedicated vector store, dedicated queue/broker, distributed storage, larger cluster) without re-architecture. **Recommendation: adopt this stack and proceed to detailed database schema design.**

---

## Appendix A — Glossary

| Term | Meaning |
|---|---|
| **ACID** | Atomicity, Consistency, Isolation, Durability — the transactional guarantees that protect data integrity. |
| **JSONB** | PostgreSQL's binary, indexable JSON column type — stores flexible/nested data inside a relational table. |
| **pgvector / HNSW / ANN** | PostgreSQL extension for vector embeddings; HNSW is an index for fast Approximate Nearest-Neighbor (similarity) search. |
| **OSI** | Open Source Initiative — the body that approves licenses as genuinely "open source." |
| **SSPL / RSAL** | "Source-available" licenses (MongoDB / Redis) that OSI did **not** approve as open source. |
| **Quorum** | The majority of nodes that must be alive for a clustered system to operate safely (avoid split-brain). |
| **`SELECT … FOR UPDATE SKIP LOCKED`** | A SQL pattern that turns a table into a concurrent job queue: each worker locks and claims a different row without blocking others. |
| **Erasure coding** | How MinIO spreads data + parity shards across drives/nodes so it survives drive/node loss. |
| **CSI** | Container Storage Interface — the Kubernetes plug-in standard for providing persistent storage. |
| **PITR** | Point-In-Time Recovery — restoring a database to any past moment from backups + transaction logs. |
| **CloudNativePG (CNPG)** | An open-source Kubernetes operator that runs PostgreSQL with replication, failover, and backups. |
| **NVMe** | A fast, directly-attached solid-state disk interface (local to each server). |
| **AGPL** | GNU Affero GPL — an OSI-approved open-source license with network-use copyleft terms that some companies review carefully. |
| **RBAC** | Role-Based Access Control — permissions are granted to roles, and roles are assigned to users. |
| **RLS** | Row-Level Security — a PostgreSQL feature restricting which rows a given user/session may read or write, enforcing tenant isolation in the database itself. |
| **argon2id** | A modern, memory-hard password-hashing algorithm used to store credentials safely. |

---

_End of document._
