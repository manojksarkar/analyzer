# ArtiFex — Roadmap & Task List

> Last updated: 2026-07-06. Est = person-days of effort (rough ±).
> Pri: **P0** blocks V1 · **P1** soon · **P2** later. TBD = unknown until discovery.

## Milestones
| Milestone | When | Definition of done |
|---|---|---|
| **V1** | by **2026-07-15**, **hard** | Deployed in office; client uses it to generate + review **SWE.3 only**; flowchart-in-DOCX fixed; data-dictionary/macros ingested correctly; function hide/unhide works. |
| **V1.1 (next)** | right after V1 | **SWE.2** (Software Architectural Design) doc generation — the next doc type. |
| **V1.x** | after V1 | Test framework + CI, real DB (Postgres), progress bar, config pages + settings UI, rerun-after-config, **optimizations (overall pipeline time + LLM calls)**, phase-model revisit. |
| **V2** | ~end Aug 2026 | Add **SYS.1, SYS.2, SWE.1** — requirements gathered then built. Scope will expand. |
| **Later** | — | External-site DOCX upload; import-doc→metadata (feasibility first). |

**Target doc-type scope = 5 ASPICE processes: SYS.1, SYS.2, SWE.1, SWE.2, SWE.3.** SWE.3 done;
**SWE.2 next (right after V1)**; SYS.1/SYS.2/SWE.1 in V2. Out of scope for now: SWE.4 unit tests, SWE.5/6, SYS.3/4/5.

## Task list (task → sub-tasks)
Parent tasks are numbered + bold with a rollup estimate; sub-tasks (↳) sit under them.

| # | Task / sub-task | Est (days) | Milestone | Pri | Notes / dependency |
|---|---|---|---|---|---|
| 1 | **Simple folder restructuring** (component folders + fix imports; no logic/optimize/dedup) | 1–2 | V1 | P0 | Cosmetic, folders only. Layout ↓. |
| 2 | **Deploy in office** | **~5–8.5** | V1 | P0 | |
| | ↳ environment (server, domain, network, LLM host, libclang/LLVM) | 1–2 | V1 | P0 | depends on office IT/access |
| | ↳ runtime setup (offline deps, Python+Node build, LLM backend) | 1–2 | V1 | P0 | |
| | ↳ serve web-app + API (reverse proxy, domain, persistent workspaces) | 1–1.5 | V1 | P0 | |
| | ↳ auth/users (SSO stub disabled → simple accounts) | 1–2 | V1 | P0 | |
| | ↳ end-to-end smoke test from a client machine | 1 | V1 | P0 | after the others |
| 3 | **V1 fixes** | **~3–7** | V1 | P0 | |
| | ↳ flowcharts generated but missing from DOCX | 2–4 | V1 | P0 | `src/views/flowcharts.py` vs `src/docx_exporter.py` |
| | ↳ data dictionary + macros not ingested properly | 1–3 | V1 | P0 | `config/macros.csv` path |
| 4 | **Function hide/unhide** → re-run Phases 3–4 in full (reuse 1–2) | 2–4 | V1 | P1 | `Function.is_visible` modeled; optimize later (task 12) |
| 5 | **Release & client review** | **~3.5–6.5** | V1 | | |
| | ↳ define V1 scope + deliverables list | 0.5 | V1 | P0 | |
| | ↳ release plan: branch, tag, changelog, build | 0.5 | V1 | P1 | |
| | ↳ client SWE.3 review: intake + triage points | 0.5 | V1 | P1 | client-blocked |
| | ↳ client review-point fixes (buffer) | 2–5 | V1 | P1 | scope unknown |
| | **V1 subtotal (tasks 1–5)** | **~15–28** | | | of ~30–33 capacity (3 people) |
| 6 | **SWE.2 doc generation** (Software Architectural Design) | **~12–24** | V1.1 | P1 | next deliverable after V1 |
| | ↳ requirements discovery (sections, template, what to derive from code) | 2–4 | V1.1 | P1 | |
| | ↳ implement generation | 10–20+ | V1.1 | P1 | after discovery; TBD, large |
| 7 | **Test framework + CI** (regression incl. flowchart; api/unit coverage; gate builds) | 2–4 | V1.x | P1 | flowchart regression slice rides with task 3 |
| 8 | **Real DB (Postgres)** — via SQLAlchemy over the 12 repo interfaces | **~16–19** | V1.x | P1 | swap-in; start foundation (deps/ORM/migration/mapping) in parallel |
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
| 9 | **Actual progress bar** (granular backend events → API → frontend) | 2–3 | V1.x | P1 | |
| 10 | **Config & rerun** | **~7.5–11** | V1.x | P1 | |
| | ↳ general Settings page (not hardcoded to layers) | 2–3 | V1.x | P1 | |
| | ↳ layer editing | 1.5–2 | V1.x | P1 | some exists |
| | ↳ data dictionary + macros settings UI (edit in-app) | 2–3 | V1.x | P1 | distinct from the task-3 ingestion fix |
| | ↳ rerun-after-config-change (generalize task 4's Phase-3–4 trigger) | 2–3 | V1.x | P1 | reuses task 4 |
| 11 | **Optimizations** | **~4–8** | V1.x | P1 | |
| | ↳ optimize overall pipeline time (profile → targeted fixes) | 2–4 | V1.x | P1 | |
| | ↳ optimize LLM calls (batch/cache/reuse) | 2–4 | V1.x | P1 | extend incremental reuse |
| 12 | **Phase model & function-exclude** | **~3–5** | V1.x | P2 | |
| | ↳ revisit phase model (+ optimize function-hide: export-only/scoped) | 1–2 | V1.x | P2 | unblocks exclude-before-run |
| | ↳ function exclude-before-run (filter + full rerun) — only after Phase 1 | 2–3 | V1.x | P2 | phase-model concern |
| | **V1.x subtotal (tasks 7–12)** | **~35–50** | | | incl. DB ~16–19 |
| 13 | **SYS.2 doc generation** | **~12–24** | V2 | P2 | |
| | ↳ requirements discovery | 2–4 | V2 | P2 | |
| | ↳ implement generation | 10–20+ | V2 | P2 | after discovery; TBD |
| 14 | **SWE.1 doc generation** | **~12–24** | V2 | P2 | |
| | ↳ requirements discovery | 2–4 | V2 | P2 | |
| | ↳ implement generation | 10–20+ | V2 | P2 | after discovery; TBD |
| 15 | **SYS.1 doc generation** | **~12–24** | V2 | P2 | |
| | ↳ requirements discovery | 2–4 | V2 | P2 | |
| | ↳ implement generation | 10–20+ | V2 | P2 | after discovery; TBD |
| 16 | **Push DOCX to external website** | 2–4 | Later | P2 | depends on their API |
| 17 | **Import document → generate metadata** | 1–2 spike (+TBD) | Later | P2 | |
| | ↳ feasibility spike (is it viable?) | 1–2 | Later | P2 | |
| | ↳ build (if viable) | TBD | Later | P2 | after the spike |

**Rough grand total (excludes the SWE.2/SYS.2/SWE.1/SYS.1 implement + import build): ~43–63 person-days.**
Rollups: **V1 ~15–28 · V1.1 (SWE.2) ~12–24 · V1.x ~35–50 (incl. DB ~16–19) · V2 discovery ~6–12 · Later ~3–6** (+ doc-type builds TBD/large).

## Key decisions
- **V1 ships SWE.3 only**, deployed in office, **hard** by 2026-07-15; shared across 3 people.
- **SWE.2 is the next deliverable, right after V1** (task 6: discovery → implement), ahead of V1.x.
  SYS.1/SYS.2/SWE.1 remain V2 (~end Aug 2026).
- **Restructuring:** the folder move (task 1) is intentionally **cosmetic** — decided flat layout `backend/ (=src) · api-server/ (=api) · web-app/`, plus `tools/` (mock-api + dev generators) and gitignored `.data/`; `tests/ docs/ scripts/` stay. It stays `sys.path`-based; the ~47 path-injection sites remain as **known debt, not scheduled** (deeper packaging/CI cleanup is out of scope for now).
- **Real DB = PostgreSQL** via SQLAlchemy over the 12 repo interfaces (`api/repositories/interfaces.py`)
  — swap-in, no route/service changes. After V1; foundation can start in parallel. V1 runs JSON with a
  single uvicorn worker + `api/db/data/` backups.
- **Function hide/unhide** = full Phase 3–4 rerun (reuse 1–2); optimize later (task 12).
  **Exclude-before-run** needs Phase 1's parsed list → with/after the phase revisit (task 12).
- **Doc scope = SYS.1, SYS.2, SWE.1, SWE.2, SWE.3.** SWE.4 unit tests (longer-term vision) out of scope now.

### V1 folder layout (task 1)
```
backend/          ← src/ renamed (the actual engine + run.py, generators)
   config/  few_shot_examples/  assets/
api-server/       ← api/ renamed
web-app/          ← unchanged
tools/            ← mock-api + dev scripts
tests/  docs/  scripts/
.data/  (gitignored) ← model/ output/ workspaces/ logs/
```

## Open questions / TBD
- V1 auth model in office (simple accounts vs SSO)?
- SWE.2 template — client reference, or design from scratch? (blocks task 6 detail)
- External upload site — API/contract available?
- Owners per task (intentionally unassigned here).
