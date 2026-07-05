# ArtiFex — Roadmap & Task List

> Last updated: 2026-07-04. Est = person-days of effort (rough ±).
> Pri: **P0** blocks V1 · **P1** soon · **P2** later. TBD = unknown until discovery.

## Milestones
| Milestone | When | Definition of done |
|---|---|---|
| **V1** | by **2026-07-15**, **hard** | Deployed in office; client uses it to generate + review **SWE.3 only**; flowchart-in-DOCX fixed; data-dictionary/macros ingested correctly; function hide/unhide works. |
| **V1.1 (next)** | right after V1 | **SWE.2** (Software Architectural Design) doc generation — the next doc type. |
| **V1.x** | after V1 | Test framework + CI, real DB (Postgres), progress bar, config pages + settings UI, rerun-after-config, **optimizations (overall pipeline time + LLM calls)**, phase-model revisit. |
| **V2** | ~end Aug 2026 | Add **SYS.1, SYS.2, SWE.1** — requirements gathered then built. Scope will expand. |
| **Later** | — | Bulk office-code re-code → deep restructuring; external-site DOCX upload; import-doc→metadata (feasibility first). |

**Target doc-type scope = 5 ASPICE processes: SYS.1, SYS.2, SWE.1, SWE.2, SWE.3.** SWE.3 done;
**SWE.2 next (right after V1)**; SYS.1/SYS.2/SWE.1 in V2. Out of scope for now: SWE.4 unit tests, SWE.5/6, SYS.3/4/5.

## Task list (task → sub-tasks)
Parent tasks are numbered + bold with a rollup estimate; sub-tasks (↳) sit under them.

| # | Task / sub-task | Est (days) | Milestone | Pri | Notes / dependency |
|---|---|---|---|---|---|
| 1 | **Office-code diff inventory** (size the delta; informs what to port) — do FIRST | 1–2 | V1 | P0 | gates task 3 & the office bulk re-code (task 20) |
| 2 | **Simple folder restructuring** (component folders + fix imports; no logic/optimize/dedup) | 1–2 | V1 | P0 | do day 0–1 so import breakage surfaces early |
| 3 | **Port only office changes V1 needs** (cherry-pick per task 1) | 1–4 | V1 | P1 | gated by task 1; bulk re-code is task 20 |
| 4 | **Deploy in office** | **~5–8.5** | V1 | P0 | |
| | ↳ environment (server, domain, network, LLM host, libclang/LLVM) | 1–2 | V1 | P0 | depends on office IT/access |
| | ↳ runtime setup (offline deps, Python+Node build, LLM backend) | 1–2 | V1 | P0 | |
| | ↳ serve web-app + API (reverse proxy, domain, persistent workspaces) | 1–1.5 | V1 | P0 | |
| | ↳ auth/users (SSO stub disabled → simple accounts) | 1–2 | V1 | P0 | |
| | ↳ end-to-end smoke test from a client machine | 1 | V1 | P0 | after the others |
| 5 | **V1 fixes** | **~3–7** | V1 | P0 | |
| | ↳ flowcharts generated but missing from DOCX | 2–4 | V1 | P0 | `src/views/flowcharts.py` vs `src/docx_exporter.py` |
| | ↳ data dictionary + macros not ingested properly | 1–3 | V1 | P0 | `config/macros.csv` path |
| 6 | **Function hide/unhide** → re-run Phases 3–4 in full (reuse 1–2) | 2–4 | V1 | P1 | `Function.is_visible` modeled; optimize later (task 14) |
| 7 | **Release & client review** | **~3.5–6.5** | V1 | | |
| | ↳ define V1 scope + deliverables list | 0.5 | V1 | P0 | |
| | ↳ release plan: branch, tag, changelog, build | 0.5 | V1 | P1 | |
| | ↳ client SWE.3 review: intake + triage points | 0.5 | V1 | P1 | client-blocked |
| | ↳ client review-point fixes (buffer) | 2–5 | V1 | P1 | scope unknown |
| | **V1 subtotal (tasks 1–7)** | **~17–34** | | | of ~30–33 capacity (3 people); task 1 decides if task 3 fits |
| 8 | **SWE.2 doc generation** (Software Architectural Design) | **~12–24** | V1.1 | P1 | next deliverable after V1 |
| | ↳ requirements discovery (sections, template, what to derive from code) | 2–4 | V1.1 | P1 | |
| | ↳ implement generation | 10–20+ | V1.1 | P1 | after discovery; TBD, large |
| 9 | **Test framework + CI** (regression incl. flowchart; api/unit coverage; gate builds) | 2–4 | V1.x | P1 | flowchart regression slice rides with task 5 |
| 10 | **Real DB (Postgres)** — via SQLAlchemy over the 12 repo interfaces | **~16–19** | V1.x | P1 | swap-in; start foundation (deps/ORM/migration/mapping) in parallel |
| | ↳ deps (SQLAlchemy/Alembic/psycopg) + engine/session + DSN | 0.5 | V1.x | P1 | |
| | ↳ ORM tables for 14 entities (PK/FK, JSON cols, indexes) | 1.5–2 | V1.x | P1 | mirror `api/models/domain.py` |
| | ↳ Alembic initial migration | 0.5 | V1.x | P1 | |
| | ↳ domain↔ORM mapping helpers | 0.5–1 | V1.x | P1 | |
| | ↳ repos Users, Projects, Members, AccessRequests | 1.5 | V1.x | P1 | |
| | ↳ repos Versions, Commits (paginated), Jobs | 1.5 | V1.x | P1 | |
| | ↳ repos Documents (filters+stats), Sections, Assignments | 2 | V1.x | P1 | |
| | ↳ repos Functions (+visibility, overlay), Compare, Notifications | 1.5 | V1.x | P1 | |
| | ↳ register backend in `session.py` + BaseDatabase ABC / route types | 0.5 | V1.x | P1 | |
| | ↳ decouple seeding into backend-agnostic script | 1 | V1.x | P1 | |
| | ↳ pipeline `model/functions.json` startup overlay | 0.5–1 | V1.x | P1 | |
| | ↳ one-time data migration `api/db/data/*.json` → Postgres | 1 | V1.x | P1 | |
| | ↳ run `tests/api` against SQL backend + parity tests | 1.5 | V1.x | P1 | |
| | ↳ concurrency + restart-durability smoke | 0.5 | V1.x | P1 | |
| | ↳ Postgres server/container, pooling, backups, deploy wiring | 1–2 | V1.x | P1 | |
| 11 | **Actual progress bar** (granular backend events → API → frontend) | 2–3 | V1.x | P1 | |
| 12 | **Config & rerun** | **~7.5–11** | V1.x | P1 | |
| | ↳ general Settings page (not hardcoded to layers) | 2–3 | V1.x | P1 | |
| | ↳ layer editing | 1.5–2 | V1.x | P1 | some exists |
| | ↳ data dictionary + macros settings UI (edit in-app) | 2–3 | V1.x | P1 | distinct from the task-5 ingestion fix |
| | ↳ rerun-after-config-change (generalize task 6's Phase-3–4 trigger) | 2–3 | V1.x | P1 | reuses task 6 |
| 13 | **Optimizations** | **~4–8** | V1.x | P1 | |
| | ↳ optimize overall pipeline time (profile → targeted fixes) | 2–4 | V1.x | P1 | |
| | ↳ optimize LLM calls (batch/cache/reuse) | 2–4 | V1.x | P1 | extend incremental reuse |
| 14 | **Phase model & function-exclude** | **~3–5** | V1.x | P2 | |
| | ↳ revisit phase model (+ optimize function-hide: export-only/scoped) | 1–2 | V1.x | P2 | unblocks exclude-before-run |
| | ↳ function exclude-before-run (filter + full rerun) — only after Phase 1 | 2–3 | V1.x | P2 | phase-model concern |
| | **V1.x subtotal (tasks 9–14)** | **~35–50** | | | incl. DB ~16–19 |
| 15 | **SYS.2 doc generation** | **~12–24** | V2 | P2 | |
| | ↳ requirements discovery | 2–4 | V2 | P2 | |
| | ↳ implement generation | 10–20+ | V2 | P2 | after discovery; TBD |
| 16 | **SWE.1 doc generation** | **~12–24** | V2 | P2 | |
| | ↳ requirements discovery | 2–4 | V2 | P2 | |
| | ↳ implement generation | 10–20+ | V2 | P2 | after discovery; TBD |
| 17 | **SYS.1 doc generation** | **~12–24** | V2 | P2 | |
| | ↳ requirements discovery | 2–4 | V2 | P2 | |
| | ↳ implement generation | 10–20+ | V2 | P2 | after discovery; TBD |
| 18 | **Push DOCX to external website** | 2–4 | Later | P2 | depends on their API |
| 19 | **Import document → generate metadata** | 1–2 spike (+TBD) | Later | P2 | |
| | ↳ feasibility spike (is it viable?) | 1–2 | Later | P2 | |
| | ↳ build (if viable) | TBD | Later | P2 | after the spike |
| 20 | **Office code (bulk) & deep restructuring** | **~10–21** | Later | | |
| | ↳ re-code remaining office changes (not copy-paste) | 3–8 | Later | P1 | after task 1; TBD by diff |
| | ↳ deep restructuring: boundaries + layout + CI (web-app, api, server, `src/`, tests, incremental engine, mock-api, scripts) | 7–13 | Later | P2 | after the bulk re-code |

**Rough grand total (excludes the SWE.2/SYS.2/SWE.1/SYS.1 implement + import build): ~55–90 person-days.**
Rollups: **V1 ~17–34 · V1.1 (SWE.2) ~12–24 · V1.x ~35–50 (incl. DB ~16–19) · V2 discovery ~6–12 · Later ~13–27** (+ doc-type builds TBD/large).

## Key decisions
- **V1 ships SWE.3 only**, deployed in office, **hard** by 2026-07-15; shared across 3 people.
- **SWE.2 is the next deliverable, right after V1** (task 8: discovery → implement), ahead of V1.x.
  SYS.1/SYS.2/SWE.1 remain V2 (~end Aug 2026).
- **Office code:** diff first (task 1) → cherry-pick only what V1 needs (task 3) → bulk re-code later
  (task 20) → **then** deep restructuring (task 20). **Simple folder restructuring (task 2) is separate + early.**
- **Real DB = PostgreSQL** via SQLAlchemy over the 12 repo interfaces (`api/repositories/interfaces.py`)
  — swap-in, no route/service changes. After V1; foundation can start in parallel. V1 runs JSON with a
  single uvicorn worker + `api/db/data/` backups.
- **Function hide/unhide** = full Phase 3–4 rerun (reuse 1–2); optimize later (task 14).
  **Exclude-before-run** needs Phase 1's parsed list → with/after the phase revisit (task 14).
- **Doc scope = SYS.1, SYS.2, SWE.1, SWE.2, SWE.3.** SWE.4 unit tests (longer-term vision) out of scope now.

## Open questions / TBD
- V1 auth model in office (simple accounts vs SSO)?
- Office-code delta size (answered by task 1) — does task 3 fit the hard V1?
- SWE.2 template — client reference, or design from scratch? (blocks task 8 detail)
- External upload site — API/contract available?
- Owners per task (intentionally unassigned here).
