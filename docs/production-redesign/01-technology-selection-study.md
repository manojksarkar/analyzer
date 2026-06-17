# Technology Selection Study — C++ Analyzer Production Platform

| | |
|---|---|
| **Document** | Technology Selection Study |
| **Project** | C++ Codebase Analyzer — Production Platform (POC → Production) |
| **Status** | Draft for Review |
| **Version** | 1.2 |
| **Date** | 2026-06-10 |
| **Changes in v1.2** | Generalized storage to **local SSD (NVMe-ready)** with a rolling per-node upgrade path; consolidated the per-node component view into a single §5.1.2 deployment diagram. |
| **Changes in v1.1** | Object store **MinIO → SeaweedFS** (MinIO Community Edition was archived / "no longer maintained" in Feb 2026); added §5.2 Resource Estimation & Scalability. |
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
| **C7** | Storage = **local SSD per server** (NVMe added later); no existing distributed storage (Ceph/vSAN/NAS) | Given | Redundancy must come from app-level replication |
| **C8** | Container deployment on a **new (greenfield) cluster** | Decision | Kubernetes + operators |

---

## 4. Decision Principles (the lens applied)

These principles were applied consistently when choosing between options:

1. **On-prem, fewer moving parts = higher reliability.** Every additional datastore is one more system to secure, back up, patch, monitor, and keep consistent. Prefer one strong engine over several specialised ones until a measured limit forces otherwise.
2. **Keep graduation paths open.** Avoid choices that box us in (e.g. an engine whose open-source tier cannot cluster). Prefer designs where scaling out is "add a swappable component," not "re-architect."
3. **Strong consistency where data integrity matters.** Generation runs update many related records; ACID transactions protect correctness (C4).
4. **Redundancy at the right layer.** With local disk (C7), redundancy is provided by the application (DB replication, object-store replication/erasure coding), not by a storage layer.
5. **Open-source in the OSI sense.** "Source-available" licenses (SSPL, RSAL) do **not** satisfy C2.

---

## 5. Selected Technology Stack

> Requirement IDs reference §3. Licenses verified as OSI-approved open source unless noted.

| # | Layer / Concern | Selected | License | Primary Reasons | Satisfies |
|---|---|---|---|---|---|
| 1 | **Primary database** | **PostgreSQL 16+** | PostgreSQL (BSD-like) | ACID + strong consistency + maturity; **JSONB** for schema-loose model data; one engine covers relational + document + vector + graph needs → fewest moving parts on-prem | R2, R3, R5, C4 |
| 2 | **Vector similarity search** | **pgvector** (Postgres extension) | PostgreSQL | Embeddings + HNSW ANN **co-located** with metadata, so similarity search can be filtered by tenant/project in one query; no separate system to operate | R3 |
| 3 | **Object / blob storage** | **SeaweedFS** (distributed, S3-compatible) | Apache 2.0 | S3-compatible, self-hostable on-prem; rack-aware **replication** (erasure coding optional); excellent with many small files (our flowchart PNGs); keeps large binaries out of the DB. **Actively maintained** — replaces MinIO, whose Community Edition was archived Feb 2026 (see §9). Integration is the **S3 API**, so the store is swappable | R4, C1, C7 |
| 4 | **Background job queue** | **PostgreSQL table + `SELECT … FOR UPDATE SKIP LOCKED`** | PostgreSQL | Zero extra infrastructure; **transactional with the data** (no lost/orphaned jobs); durable; throughput is ample for long-running generation jobs | R1, R5 |
| 5 | **Graph / impact analysis** | **Postgres recursive CTE + materialized closure table** | PostgreSQL | The only graph query we run is **bounded transitive closure** ("who depends on changed function F?"); a dedicated graph DB is not justified | R5 |
| 6 | **Analyzer ↔ storage integration** | **Direct DB read/write (phases rewritten)** | — | Removes the current local-disk file handoff between phases, so phases / sub-jobs can run on **any** node — the enabler for distributed workers | R2, R5, C5 |
| 7 | **Container orchestration** | **Kubernetes** | Apache 2.0 | Self-hostable standard; rich operator/Helm ecosystem (CloudNativePG, SeaweedFS); rolling updates; horizontal scale | C3, C4, C8 |
| 8 | **PostgreSQL HA** | **CloudNativePG operator** | Apache 2.0 | Automated primary + replicas, failover, and **PITR backups to the S3 object store (SeaweedFS)**; designed for local-disk streaming replication | C4 |
| 9 | **Storage substrate** | **Local SSD/NVMe + TopoLVM / OpenEBS LocalPV** | Apache 2.0 | Fastest, simplest; avoids a distributed storage layer (the hardest part of on-prem K8s); redundancy provided by app-level replication. Start on SSD; move to NVMe later via a rolling per-node swap (§8.4) | C4, C7 |
| 10 | **Application tier** | **Stateless FastAPI API + stateless analyzer workers** | — (in-house) | Horizontal scale on any node; rolling updates; job/state lives in the DB, not process memory | R1, C3 |
| 11 | **LLM access** | **Internal corporate gateway** via existing unified `LlmClient` (OpenAI-compatible) | — (given) | C++ IP stays on-network; reuses existing client; **no GPU nodes needed** in-cluster | C1, C6 |
| 12 | **Cluster size** | **3 nodes to start; 5 if 2-failure tolerance required** | — | 3 nodes survive **1** failure (quorum = 2); 5 survive **2** (quorum = 3). Start lean, scale by uptime need | C4 |
| 13 | **Backup / DR** | **PITR (CloudNativePG → SeaweedFS) + off-cluster copy** | — | Replication is **not** backup; protects against logical errors (e.g. a bad delete that replicates instantly) | C4 |
| 14 | **Authentication & RBAC** | **In-app auth on PostgreSQL** — FastAPI + argon2id password hashing, signed token/session, `roles`/`user_roles` tables, optional Row-Level Security | — (in-house) | Simple role model needs no separate IAM; reuses the DB + API already selected; tenant data-scoping enforceable in Postgres (RLS) | R1, R6 |

---

## 5.1 Architecture Diagram

The two diagrams below realise the stack in §5. The first is the **logical view** (components and how a request and a generation job flow through them); the second is the **physical deployment topology** on a 3-node cluster (the High-Availability behaviour of items #7–#13).

### 5.1.1 Logical architecture & flows

```text
        TENANTS  --  C++ project teams (web browsers, multi-tenant)
            |
            |  HTTPS
            v
   +--------------------------+
   |  Ingress / Load Balancer |
   +------------+-------------+
                |
       +--------+--------+
       v                 v
 +-----------+   +-------------------------------+
 |  Web UI   |   |  FastAPI API   [stateless, N] |   any node; lose one,
 | (static)  |   |  enqueue | read | stream      |   the LB uses the rest
 +-----------+   +---------------+---------------+
                                 |
                                 |  SQL (ACID)
                                 v
   +=========================================================+
   |  PostgreSQL   [HA: 1 primary + 2 replicas via CNPG]      |   <- system of record
   |  jobs-queue | model | call-graph + closure | vectors     |
   +====+=========================================+==========+
        ^                                         |
  claim |  job + heartbeat              read/write |  model, LLM results,
        |  (SKIP LOCKED)               each phase  |  embeddings, blob pointers
        |                                          v
   +====+=========================================+==========+
   |  Analyzer Workers   [stateless, M slots over worker VMs] |
   |  one job per slot:   P1 -> P2 -> P3 -> P4  (heartbeats)   |
   +----+-----------------------------------------+----------+
        |  LLM (HTTPS)                             |  S3 put / get
        v                                          v
 +-----------------------------+       +------------------------------+
 | Internal LLM Gateway        |       | SeaweedFS   [HA: replicated] |
 | (off-cluster, corp network) |       | generated .docx + PNGs       |
 +-----------------------------+       +------------------------------+

   Legend:  [HA] survives a node loss      [stateless] add / remove freely
```

There are **two fast, user-facing request flows** and **one slow, asynchronous job flow**. Keeping them separate is what lets the heavy generation work scale independently of the API.

**Request flow (synchronous — what the browser experiences):**
1. Browser → Ingress → **API**. Reads (project tree, functions, job status) are answered from PostgreSQL. The API is stateless, so any replica serves — losing one is invisible to the user.
2. **Download** → the API streams the finished `.docx` straight from SeaweedFS.

**Job flow (asynchronous — the generation pipeline):**
1. **Submit** — the API writes a `jobs` row in the *same transaction* as the run record (so a job can never be lost) and returns a job ID immediately. *(#4, #10)*
2. **Claim** — one idle worker slot takes the job via `SELECT … FOR UPDATE SKIP LOCKED`; exactly one worker owns it. *(#4)*
3. **Run** — the worker executes P1→P4, committing **each phase's** output (model, call graph, LLM results, embeddings) **directly to PostgreSQL**, and heartbeats while running. *(#1, #2, #5, #6)*
4. **LLM** — Phase 2 and flowchart labelling call the internal gateway over HTTPS — the only egress, and only to the on-network gateway. *(#11)*
5. **Artifacts** — `.docx` and PNGs are written to SeaweedFS; the pointer row is committed in PostgreSQL **only after** the object is durably stored (no dangling pointers). *(#3)*
6. **Done** — the job row is marked complete; the UI's next status poll offers the download.

> **Consistency, in one line:** all durable state lives in one ACID database; the enqueue shares the run's transaction; each phase commits atomically and is idempotent; and a blob pointer is written only after its object exists. Failure, HA, and scaling behaviour are detailed in §5.1.3.

### 5.1.2 Physical deployment topology (3 nodes)

The **initial, co-located** 3-node deployment — every node runs the full stack. As load grows, the Analyzer Workers move to dedicated **worker-only VMs** (§5.1.3 / §5.2.4); the data core stays on these three nodes.

```text
+===================== KUBERNETES CLUSTER  (3 nodes, quorum = 2) ======================+
|                                                                                      |
|  +-------- NODE 1 ---------+  +-------- NODE 2 ---------+  +-------- NODE 3 ---------+ |
|  | k8s control plane  [Q]  |  | k8s control plane  [Q]  |  | k8s control plane  [Q]  | |
|  |   etcd / api / sched    |  |   etcd / api / sched    |  |   etcd / api / sched    | |
|  | ingress-controller pod  |  | ingress-controller pod  |  | ingress-controller pod  | |
|  | FastAPI API pod         |  | FastAPI API pod         |  | FastAPI API pod         | |
|  | Analyzer Workers (K)    |  | Analyzer Workers (K)    |  | Analyzer Workers (K)    | |
|  | Postgres PRIMARY (CNPG) |  | Postgres replica (CNPG) |  | Postgres replica (CNPG) | |
|  | SeaweedFS master+vol+S3 |  | SeaweedFS master+vol+S3 |  | SeaweedFS master+vol+S3 | |
|  | TopoLVM local-PV (DS)   |  | TopoLVM local-PV (DS)   |  | TopoLVM local-PV (DS)   | |
|  | local SSD (NVMe-ready)  |  | local SSD (NVMe-ready)  |  | local SSD (NVMe-ready)  | |
|  +-------------------------+  +-------------------------+  +-------------------------+ |
|                                                                                      |
|  Cluster-wide controllers (single replica, scheduled on any one node):               |
|     - CloudNativePG operator        - SeaweedFS operator/coordinator                  |
|                                                                                      |
|  [Q] quorum members: etcd + Postgres failover + SeaweedFS master  (need majority)    |
+======================================================================================+
        ^                          |                                |
        | HTTPS (users)            | HTTPS (workers -> LLM)          | PITR + object copy
        |                          v                                v
 +--------------+       +----------------------------+    +----------------------------+
 | Users        |       | Internal LLM Gateway       |    | Off-cluster backup target  |
 | (browsers)   |       | (off-cluster, corp net)    |    | (S3 / NAS, on-prem)        |
 +--------------+       +----------------------------+    +----------------------------+
```

**What runs on each node** (all three are identical — only the Postgres role differs):

| Tier | Components on the node | Notes |
|---|---|---|
| **Control plane** `[Q]` | etcd · api-server · scheduler | Kubernetes' own quorum |
| **Stateless app** | ingress-controller · FastAPI API pod · Analyzer Workers (K slots) | add/remove freely — **this is where scaling (#5/#6) happens** |
| **Stateful data** `[Q]` | PostgreSQL (CNPG): 1 primary + 2 replicas · SeaweedFS: master + volume + S3 gateway | replicated across nodes; the primary fails over automatically |
| **Storage** | TopoLVM local-PV → **local SSD (NVMe-ready)** | turns the VM's local disk into PersistentVolumes for Postgres & SeaweedFS |
| **Cluster-wide** | CloudNativePG operator · SeaweedFS operator | one controller pod each; they *manage* the stateful sets, they don't serve data |

**Quorum members `[Q]`** — etcd, the Postgres failover coordinator, and the SeaweedFS master each need a **majority alive**, which is why this cluster survives **1** node loss but halts writes on **2** (§8.6). The API and Worker pods are **not** quorum members, so they scale and fail independently of the data core (full failure walkthrough in §5.1.3).

> Scaling to **5 nodes** keeps the same shape — more API/worker pods and Postgres/SeaweedFS members — and raises quorum to 3, so the platform then survives **two** simultaneous node failures (item #12).

### 5.1.3 Failure, HA, Scalability & Consistency

The platform has **two kinds of tier**, and the difference between them is the key to understanding both scaling and failure:

- **Stateless tiers — the API pods and the Analyzer Workers.** They hold no durable state (all job/run state lives in PostgreSQL), so they can be added, removed, or killed freely. **Scaling (#5 / #6) happens here:** add worker VMs → more job slots.
- **Stateful data core — PostgreSQL (CNPG) + SeaweedFS + etcd.** Quorum-bound, sized for HA (3 nodes survive 1 failure, 5 survive 2). You make this tier *redundant*; you do **not** scale it for throughput.

> **This resolves the "#5/#6 vs node-failure" question:** you scale compute by adding **stateless worker VMs, which are not quorum members**, so scaling never touches the data core. At the initial 3-node deployment the workers are co-located on the data-core nodes; as load grows you add **worker-only VMs** (the §5.2.4 scale-out) and the data core is untouched. A worker VM joining or dying is simply ± job slots.

| Goal | How it is achieved |
|---|---|
| **Scalability (#5 / #6)** | Concurrency `C = (#worker VMs) × (slots/VM)`. Add stateless worker VMs → more slots; the shared Postgres queue feeds them. No code/schema change; no quorum impact. |
| **High availability** | Stateless pods → Kubernetes reschedules them onto live nodes. Data core → PostgreSQL failover (CNPG), SeaweedFS replication, etcd quorum. 3 nodes tolerate 1 failure. |
| **Node failure — data** | Postgres primary lost → CNPG promotes a replica in seconds. SeaweedFS node lost → other-node replicas serve, then re-replicate. **No data lost.** |
| **Node failure — in-flight job** | The worker stops heartbeating → a **reaper** flips the job `running → queued` → another worker **resumes from the last committed phase** (DB-direct + `--from-phase`). **No job lost.** |
| **Consistency** | One ACID database. Enqueue shares the run's transaction. Each phase commits atomically and is **idempotent** (safe to re-run). A blob pointer is committed only **after** its object is durable. |

**Concrete scenario — a node dies while jobs are running at peak load.**
Suppose 2 worker VMs each run K = 3 slots → up to **6 concurrent jobs**, and one node (holding a Postgres *replica*, an API pod, and 3 running jobs) suddenly fails:

1. **Data core stays up.** The dead node held a *replica*, so PostgreSQL keeps serving from the primary; the queue and all model data are intact. *(Had it held the primary, CNPG promotes a surviving replica in seconds.)* SeaweedFS serves every object from its other-node replicas and re-replicates to restore redundancy. Quorum is 2 / 3 → holds.
2. **API stays up.** The ingress stops routing to the dead API pod and uses the survivors — no user-visible break.
3. **The 3 in-flight jobs are not lost.** Their workers stop heartbeating; after the timeout the reaper returns them to `queued`.
4. **They resume, not restart.** Surviving workers claim them and continue **from the last committed phase** — a job that had finished Parse + Derive restarts at Views, because those outputs are already in PostgreSQL. At worst, the *currently-running* phase is redone (phases are idempotent).
5. **Capacity degrades gracefully.** Slots drop 6 → 3; queued and requeued jobs simply wait for a free slot. When the node is replaced (or its workers reschedule onto spare capacity), slots return to 6.

**So #5/#6 and node-failure are the same lever — live worker slots.** Adding a VM is +slots; a failing VM is −slots; the queue absorbs both, and the reaper + per-phase checkpointing make an interrupted job *resume* rather than die. The only hard limit is the data core's quorum: you may lose worker VMs freely, but not a **majority** of the 3 (or 5) data-core nodes at once — that halts writes by design (§8.6).

---

## 5.2 Resource Estimation & Horizontal Scalability

### 5.2.1 Workload parameters

| Parameter | Value |
|---|---|
| C++ projects | **N** (unbounded) |
| Functions per project | up to **50,000** |
| Tenants per project | up to **40** |
| Concurrent generation jobs | **configurable** (e.g. start at 2), bounded by system resources |
| Scaling model | **add worker VMs to raise concurrency — no code change** |

A **job** = one full 4-phase generation run for one project. Jobs are queued; the platform runs at most **C** concurrently, where **C** is the total number of worker *slots* across the fleet. The 40-tenants-per-project figure drives queue depth and fairness, not per-job cost (cost is per project-generation).

### 5.2.2 Per-job resource profile (the unit of sizing)

| Phase | CPU | Memory | Notes |
|---|---|---|---|
| 1 Parse (libclang) | bursty, multi-core | **high** | translation units held in RAM — the main memory driver |
| 2 Derive (+ LLM) | low | low–moderate | **dominated by LLM calls** → network/IO-bound and gateway-rate-limited; long wall-clock, little local CPU |
| 3 Views (+ mmdc) | bursty | **high** | each `mmdc` render spawns a headless Chrome (~0.3–1 GB); the flowchart engine re-parses with libclang |
| 4 Export (.docx) | low | low | python-docx |

**Three binding constraints**, in the order they usually bite:
1. **RAM** — libclang + headless-Chrome set the ceiling; exceeding it triggers OOM kills.
2. **CPU cores** — for the parse/render bursts.
3. **LLM-gateway throughput (global)** — shared across *all* jobs and rate-limited (~1 req / 3 s on the corporate gateway). **Adding worker VMs does not speed this up.**

### 5.2.3 How many jobs fit on a VM

```
jobs_per_vm = floor( min( usable_RAM   / peak_RAM_per_job ,
                          usable_cores / cores_per_active_job ) )
```
`usable_*` = total minus ~20–30% reserved for the OS, the worker agent, and headroom.

**Worked example — 32 GB / 8 vCPU (illustrative; confirm by profiling):**

| Input | Assumed value |
|---|---|
| usable RAM | ~24 GB (≈ 75 %) |
| usable cores | ~6 |
| peak RAM per job (50k-function project) | ~8 GB |
| active cores per job | ~2 (much of a job is LLM-wait) |
| RAM-bound limit | 24 / 8 = **3** |
| CPU-bound limit | 6 / 2 = **3** |
| **→ jobs_per_vm** | **≈ 3** |

> These figures are **estimates to validate by measurement** — profile a representative 50k-function run for peak RSS (e.g. cgroup `memory.peak`) and CPU before fixing the limit. Starting at **2 concurrent jobs** is a safe, conservative default; raise it after profiling.

**Key caveat:** because Phase 2 and flowchart labelling are LLM-bound and the gateway is rate-limited, running more jobs at once overlaps their *parse/render* work but **serializes their LLM work** behind the gateway. Once the gateway saturates, per-job wall-clock grows with concurrency — the gateway, not the VM, becomes the bottleneck.

### 5.2.4 Achieving requirements #5 / #6 — scale by adding VMs

This falls out of the **stateless-workers + Postgres-queue** design (items #4, #10) for free:

```text
                 +--------------- Postgres job queue ----------------+
   submissions ->|  pending jobs (fair-scheduled across tenants)     |
                 +------------------------+--------------------------+
                       claim (SKIP LOCKED) |
        +------------------------------------+------------------------------+
        v                                    v                              v
 +--------------+                    +--------------+               +--------------+
 | Worker VM 1  |                    | Worker VM 2  |     ...       | Worker VM n  |
 |  K slots     |                    |  K slots     |               |  K slots     |
 +--------------+                    +--------------+               +--------------+

   Total concurrency  C = n x K       (K = jobs_per_vm from 5.2.3)
```

- **One job = one worker slot;** a VM runs `K = jobs_per_vm` worker processes.
- **Total concurrency `C` = sum of slots across all worker VMs.**
- **To run more jobs at once → add worker VMs** (or worker pods/replicas). New workers simply start claiming from the same queue — **no code or schema change**.
- The **global cap** is the total slot count (set by replica count / config). **Per-tenant fairness** (the 40-tenants case) is enforced in the claim query (round-robin across tenants or a per-tenant max-in-flight) so one tenant cannot starve the rest.
- **The one thing adding VMs does *not* scale: LLM enrichment throughput** — bounded by the corporate gateway's rate. If the LLM phase is the bottleneck, the lever is the gateway's allowed concurrency, not more worker VMs.
- **Queue reliability at this scale:** jobs are few and long, so the Postgres queue is nowhere near any throughput limit. Each claimed job carries a `claimed_at` / heartbeat; a reaper requeues jobs whose worker died mid-run, so a lost worker never strands a job.

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
| Storage layer | **Ceph / Longhorn / distributed storage** | LGPL / Apache 2.0 | Unneeded complexity. Local SSD/NVMe + app-level replication is faster and simpler; distributed storage is the hardest part of on-prem K8s. Retained as a future path (§7). |
| Document storage | **Word docs as DB BLOBs** | — | Bloats the database, slows backup/restore, hurts performance. Object storage (SeaweedFS) is the standard pattern. |
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
| Storage substrate | Local SSD/NVMe | **Ceph** (LGPL) / **Longhorn** (Apache 2.0) | If stateful pods need volume mobility or shared RWX volumes across nodes. |
| Object store | **SeaweedFS** (S3 API) | **Ceph RGW** (LGPL) / **Garage** (AGPLv3) / **RustFS** (Apache 2.0) | Enterprise-scale erasure coding + multi-site (Ceph RGW), dead-simple geo-replication (Garage), or a console-rich newcomer (RustFS). Cheap swap — all speak the S3 API. |
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
Requirements R2, R3, and R5 are three views of one data-model problem: versioned metadata, similarity search, and dependency-graph traversal. PostgreSQL covers all three in a single ACID engine — JSONB (flexible model data), pgvector (similarity), recursive CTEs (graph) — plus blob *pointers* for the object store. One engine means one thing to back up, secure, and keep consistent. For on-prem, that operational simplicity is itself a reliability feature (Principle 1).

**8.2 Why a dedicated S3 object store (SeaweedFS), not the database.**
Generated `.docx` files and flowchart PNGs are large binaries; storing them in the DB bloats it and slows backup/restore. We therefore use a clustered, S3-compatible object store on local disks (C7). **The application depends on the S3 *API*, not on any one product** — this abstraction is deliberate. The original choice, MinIO, had its Community Edition put into maintenance mode and then **archived ("no longer maintained") in February 2026** (binaries/images pulled, admin console gutted), so it is no longer viable. We switched to **SeaweedFS** (Apache 2.0, actively maintained, excellent with many small files like our PNGs); because the integration is the S3 API, the swap is a configuration change, not a code change. Ceph RGW, Garage, and RustFS remain S3-compatible alternatives (§7).

**8.3 Why the queue lives in Postgres (for now).**
A generation run is a long, heavy background job and cannot run inside an HTTP request. The work must be handed to background workers via a queue, which also gives durability, retries, and backpressure (protecting the rate-limited LLM gateway). `SELECT … FOR UPDATE SKIP LOCKED` turns an ordinary table into a safe multi-consumer queue with **no extra infrastructure** and **transactional enqueue** (the job is created in the same transaction as the run record, so it can never be lost). A dedicated broker is a documented future path if throughput ever demands it.

**8.4 Why local disk (SSD now, NVMe later) with app-level replication.**
A local SSD/NVMe disk is the fastest and simplest substrate and lets us skip a distributed storage layer. The non-negotiable rule: because local disk is node-pinned, **redundancy must come from the application** — CloudNativePG keeps streaming replicas on other nodes' disks, and SeaweedFS replicates across nodes. A single stateful pod on one local disk with no replica is never acceptable. **SSD vs NVMe is a performance knob, not a structural one:** the platform starts on ordinary local SSD and moves to NVMe later as a **rolling, one-node-at-a-time disk swap** — drain a node, replace its disk, let CNPG/SeaweedFS re-replicate onto it, repeat — with **no data loss and no full downtime**, precisely because the redundancy already lives in the app layer.

**8.5 Why the analyzer is rewritten to use the DB directly.**
The current pipeline hands work between phases via files on local disk, which assumes a single machine. In a cluster, a later phase may run on a different node with no access to that disk. Writing directly to the DB (and blobs to the S3 object store) removes every local-disk handoff, which is what makes distributed, horizontally-scaled workers possible.

**8.6 Why 3 nodes to start (and what 5 buys).**
Quorum = majority must be alive. With 3 nodes, majority is 2, so the cluster survives **one** node failure; losing two breaks quorum and halts writes (by design, to prevent split-brain). 5 nodes raise quorum to 3, surviving **two** failures. The choice is a tolerance/cost trade-off, not a capacity one: start at 3 for an internal tool, move to 5 if uptime expectations rise.

**8.7 Why in-app auth on PostgreSQL (initially).**
The initial role model is simple (e.g. Platform Admin / Team Owner / Maintainer / Viewer), so a dedicated identity server is unnecessary. Authentication and RBAC are handled in the FastAPI layer with user, role, and membership tables in the PostgreSQL we already run — no new infrastructure. Enforcement is at two layers: *functional* permissions (which actions an endpoint allows) and *data scoping* (which tenant's rows a user may touch), the latter optionally hardened with Postgres **Row-Level Security** so an application bug cannot leak another team's IP. The `users` table carries an `auth_provider` field from day one, so corporate SSO / Keycloak federation (§7) can be added later **without a data migration**. An audit table records who registered, edited, or generated each artifact — useful for the ASPICE compliance posture.

---

## 9. Known Risks & Mitigations

| Risk | Mitigation |
|---|---|
| On-prem Kubernetes is greenfield; operational maturity required | Start 3-node; use managed operators (CloudNativePG, SeaweedFS Helm/operator); lighter orchestrator available as fallback (§7) |
| Local disk (SSD/NVMe) is node-pinned (data does not move) | App-level replication (CNPG, SeaweedFS replication) + PITR backups; never run single-replica stateful workloads. The SSD→NVMe upgrade is a rolling per-node swap (§8.4) |
| Two simultaneous node failures on a 3-node cluster cause an outage | Accept for an internal tool, or provision 5 nodes for 2-failure tolerance |
| pgvector scaling ceiling at very-large embedding counts (C3) | Start with function-level embeddings; keep the vector backend swappable; graduate to Qdrant/Milvus if needed |
| Object-store project risk (a vendor may abandon its OSS edition — as MinIO did, archived Feb 2026) | Depend on the **S3 API**, not one implementation; chose actively-maintained **SeaweedFS** (Apache 2.0); Ceph RGW / Garage / RustFS are drop-in S3 alternatives (§7); pin and mirror the deployed image |
| Analyzer DB rewrite is a substantial change (C5) | Phased migration; the existing pipeline contract (PROJECT_CONTEXT) remains the source of truth |
| "Replication is not backup" — logical errors replicate instantly | Enforce PITR + off-cluster backup copy + periodic restore drills |
| Local accounts mean the platform stores user credentials | Hash with **argon2id**, enforce a password policy, design `users` for federation from day one, and plan migration to corporate SSO / Keycloak (§7) |

---

## 10. Summary & Recommendation

A structured evaluation against our requirements (R1–R5) and hard constraints (on-prem, open-source, firmware-scale, reliable/durable/consistent) converges on a **PostgreSQL-centric, open-source, on-premise stack**:

> **PostgreSQL 16+ (with pgvector) as the system of record · SeaweedFS (S3) for documents · job queue inside Postgres · Kubernetes on local SSD (NVMe-ready) · CloudNativePG for database HA · SeaweedFS distributed for object-store HA · stateless API + workers · LLM via the internal corporate gateway · in-app auth + RBAC on PostgreSQL · 3-node cluster to start.**

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
| **Erasure coding / replication** | How an object store spreads data — full replicas or parity shards — across drives/nodes so it survives drive/node loss. SeaweedFS defaults to replication, with erasure coding optional. |
| **CSI** | Container Storage Interface — the Kubernetes plug-in standard for providing persistent storage. |
| **PITR** | Point-In-Time Recovery — restoring a database to any past moment from backups + transaction logs. |
| **CloudNativePG (CNPG)** | An open-source Kubernetes operator that runs PostgreSQL with replication, failover, and backups. |
| **SeaweedFS** | An Apache-2.0, S3-compatible distributed object store; the store for generated documents and PNGs (replaces the discontinued MinIO). |
| **Local SSD / NVMe** | A disk attached directly to each VM/server (not network storage). The design runs on ordinary local SSD; NVMe is a faster option added later. |
| **AGPL** | GNU Affero GPL — an OSI-approved open-source license with network-use copyleft terms that some companies review carefully. |
| **RBAC** | Role-Based Access Control — permissions are granted to roles, and roles are assigned to users. |
| **RLS** | Row-Level Security — a PostgreSQL feature restricting which rows a given user/session may read or write, enforcing tenant isolation in the database itself. |
| **argon2id** | A modern, memory-hard password-hashing algorithm used to store credentials safely. |

---

_End of document._
