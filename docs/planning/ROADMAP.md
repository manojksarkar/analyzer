# ArtiFex — Roadmap & Task List

> Last updated: 2026-07-10. Est = person-days of effort (rough ±).
> Pri: **P0** blocks V1 · **P1** soon · **P2** later. TBD = unknown until discovery.

## Milestones
| Milestone | When | Definition of done |
|---|---|---|
| **V1** | by **2026-07-15**, **hard** | Deployed in office; client uses it to generate + review **SWE.3 only**; flowchart-in-DOCX fixed; data-dictionary/macros ingested correctly; function hide/unhide works; pre-V1 correctness batch (task 3.1–3.10) cleared. |
| **V1.1 (next)** | right after V1 | **SWE.4** (Software Unit Verification — test *specifications*) doc generation. **Reprioritized ahead of SWE.2 — internal call, NOT client-demanded**: smaller/faster, reuses SWE.3 machinery, and one slice (dynamic-behaviour specs) is buildable today. |
| **V1.2** | after V1.1 | **SWE.2** (Software Architectural Design) doc generation — the following doc type. |
| **V1.x** | after V1 | Test framework + CI, real DB (Postgres), progress bar, config pages + settings UI, rerun-after-config, **optimizations (overall pipeline time + LLM calls)**, phase-model revisit. |
| **V2** | ~end Aug 2026 | Add **SYS.1, SYS.2, SWE.1** — requirements gathered then built. Scope will expand. |
| **Later** | — | External-site DOCX upload; import-doc→metadata (feasibility first). |

**Target doc-type scope now = 6 ASPICE processes: SYS.1, SYS.2, SWE.1, SWE.2, SWE.3, SWE.4.** SWE.3 done;
**SWE.4 next (right after V1), then SWE.2** — internal reprioritization (SWE.4 is *not* client-demanded, but
it's a smaller/faster win that reuses SWE.3 machinery). SYS.1/SYS.2/SWE.1 in V2. Out of scope for now: SWE.5/6, SYS.3/4/5.

## Task list (task → sub-tasks)
Parent tasks are numbered + bold with a rollup estimate; sub-tasks (↳) sit under them.

| # | Task / sub-task | Est (days) | Milestone | Pri | Notes / dependency |
|---|---|---|---|---|---|
| 1 | **Folder restructuring** — engine consolidated under `engine/` | 1–2 | V1 | P0 | **Mostly done** (branch `refactor/folder-restructuring`, 5 tested commits): `src/`→`engine/` + `config/` `few_shot_examples/` `assets/` both generators + `run.py` all under `engine/`. `api/` **kept** (hyphen in `api-server` + absolute `from api.` imports would break). `tools/` (mock-api + dev scripts) also done. **Deferred:** gitignored `.data/`. Layout ↓. |
| 2 | **Deploy in office** | **~5–8.5** | V1 | P0 | |
| | ↳ environment (server, domain, network, LLM host, libclang/LLVM) | 1–2 | V1 | P0 | depends on office IT/access |
| | ↳ runtime setup (offline deps, Python+Node build, LLM backend) | 1–2 | V1 | P0 | |
| | ↳ serve web-app + API (reverse proxy, domain, persistent workspaces) | 1–1.5 | V1 | P0 | |
| | ↳ auth/users (SSO stub disabled → simple accounts) | 1–2 | V1 | P0 | |
| | ↳ end-to-end smoke test from a client machine | 1 | V1 | P0 | after the others |
| 3 | **V1 fixes** | **~9–25** | V1 | P0 | rollup ↑: adds pre-V1 correctness batch (3.1–3.10) from review |
| | ↳ flowcharts generated but missing from DOCX | 2–4 | V1 | P0 | `src/views/flowcharts.py` vs `src/docx_exporter.py` |
| | ↳ data dictionary + macros not ingested properly | 1–3 | V1 | P0 | `config/macros.csv` path |
| | **↳ Pre-V1 correctness batch (10 review findings; fix roots first, re-test dependents):** | **~6–18** | V1 | P0 | 3.3/3.4 are re-test-after-fix — may vanish once roots land |
| | ↳ 3.1 exclude emulator files from analysis/parse scope | 0.5–1.5 | V1 | P0 | root cause; likely resolves 3.3 |
| | ↳ 3.2 parse header files (.h/.hpp), not just sources | 1–3 | V1 | P0 | root cause; likely resolves 3.4 |
| | ↳ 3.3 some functions should not be visible | 0–1 | V1 | P0 | ✅ **resolved by 3.1** — emulator files excluded from parse scope, so their functions never enter the model (sample-verified). Non-emulator residual needs the client project. |
| | ↳ 3.4 interface direction shows "Out" instead of "In" for some functions | 0–1 | V1 | P0 | ✅ **fixed 2026-07-15** (`fix/direction-transitive-writes`): re-derive direction from `writesGlobalIdsTransitive` in `model_deriver` (Phase 2) so transitive-only global writers show `In`. Header-defined globals handled (global-ID based). Root was direct-write-only in the parser, not headers. |
| | ↳ 3.5 include same-component pairs as source/destination too | 0.5–1 | V1 | P0 | table currently drops same-component pairs |
| | ↳ 3.6 make interface-table direction consistent with static diagram | 1–2 | V1 | P0 | ✅ **fixed 2026-07-16** (`fix/unit-diagram-direction`): re-orient the **diagram** to the table's owner In/Out (In→towards owner, Out→away from owner), not the reverse. Only `Out` (getter) edges flip; diagram-only, no model change. Owner-relative so both units' diagrams agree (avoids `da5f07d`'s inversion). |
| | ↳ 3.7 functions missing from DOCX due to access specifier | 0.5–1.5 | V1 | P0 | known issue |
| | ↳ 3.8 if/else condition depiction in flowchart | 1–2 | V1 | P0 | |
| | ↳ 3.9 overlapping / bending flowchart edges | 0.5–2 | V1 | P0 | **already ELK** (`engine/flowchart/mermaid/builder.py:51-93`). Diagnosed 2026-07-15 from a client DOCX flowchart (`GCN_RegisterDelayedBadFromBadInfo`). Two symptoms: (a) edges **bend** — loop back-edges (`feedbackEdges:true`) + long-span branches route around nodes in orthogonal channels, and `mergeEdges:false` leaves doubled parallel tracks; (b) edges meet **diamonds at a slanted angle** — decision rhombi expose no fixed ELK ports, so routes hit the box border on a sloped face (largely inherent). Levers: ↑`rankSpacing`/`nodeSpacing`, `mergeEdges:true`, explicit `elk.edgeRouting:ORTHOGONAL`. Back-edge detours are unavoidable with orthogonal routing — can widen, not straighten. Verify by A/B rendering one busy function before touching the builder. |
| | ↳ 3.10 dynamic-behaviour issue | 1–3 | V1 | P0 | **needs detail** — scope/repro unclear |
| 4 | **Function hide/unhide** → re-run Phases 3–4 in full (reuse 1–2) | 2–4 | V1 | P1 | `Function.is_visible` modeled; optimize later (task 13) |
| 5 | **Release & client review** | **~3.5–6.5** | V1 | | |
| | ↳ define V1 scope + deliverables list | 0.5 | V1 | P0 | |
| | ↳ release plan: branch, tag, changelog, build | 0.5 | V1 | P1 | |
| | ↳ client SWE.3 review: intake + triage points | 0.5 | V1 | P1 | client-blocked |
| | ↳ client review-point fixes (buffer) | 2–5 | V1 | P1 | scope unknown |
| | **V1 subtotal (tasks 1–5)** | **~20–46** | | | high end now exceeds ~30–33 capacity (3 people) — but batch is re-test-first, likely lands lower |
| 6 | **SWE.4 doc generation** (Software Unit Verification — test specs) | **~8–16** *(rough, pre-discovery)* | V1.1 | P1 | **next deliverable after V1**; per-GROUP docs. **Higher-reuse, lower-risk than SWE.2** — stays at unit scope (no aggregation layer), *transforms* SWE.3 outputs. Critical path = design→test-case transform, not view revival. See `docs/planning/SWE4_PLAN.md`. |
| | ↳ document discovery (Q3 field derivability, unit-vs-function granularity, requirements/metrics source) | 2–4 | V1.1 | P1 | Q1/Q2 resolved; Q3 + open items in SWE4_PLAN.md |
| | ↳ implement generation (two-table spec renderer + test-case enumeration; dynamic-behaviour specs — P1 rows) | 6–12+ | V1.1 | P1 | crux = right-sizing cases/function (draft-then-confirm); after discovery |
| 7 | **SWE.2 doc generation** (Software Architectural Design) | **~12–24** | V1.2 | P1 | after SWE.4; **one SAD doc**. Critical path = roll-up §3.N→§2 (aggregate main's component/unit output up) + §2.2.1 feature-list derivation. Revival branches = re-port, not merge. See `docs/planning/SWE2_PLAN.md`. |
| | ↳ discovery: red-bucket data-source spike (client-input vs code-extracted) + §2.2.1 feature-list prototype | 2–4 | V1.2 | P1 | two swing factors (red-bucket ±8–15d; feature-list granularity); spike first |
| | ↳ implement generation (scope-parameterised §2/§3.N builders + roll-up; new input/eval sections) | 10–20+ | V1.2 | P1 | after discovery; TBD, large |
| 8 | **Test framework + CI** (regression incl. flowchart; api/unit coverage; gate builds) | 2–4 | V1.x | P1 | flowchart regression slice rides with task 3 |
| 9 | **Real DB (Postgres)** — via SQLAlchemy over the 12 repo interfaces | **~16–19** | V1.x | P1 | swap-in; start foundation (deps/ORM/migration/mapping) in parallel |
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
| 10 | **Actual progress bar** (granular backend events → API → frontend) | 2–3 | V1.x | P1 | |
| 11 | **Config & rerun** | **~7.5–11** | V1.x | P1 | |
| | ↳ general Settings page (not hardcoded to layers) | 2–3 | V1.x | P1 | |
| | ↳ layer editing | 1.5–2 | V1.x | P1 | some exists |
| | ↳ data dictionary + macros settings UI (edit in-app) | 2–3 | V1.x | P1 | distinct from the task-3 ingestion fix |
| | ↳ rerun-after-config-change (generalize task 4's Phase-3–4 trigger) | 2–3 | V1.x | P1 | reuses task 4 |
| 12 | **Optimizations** | **~4–8** | V1.x | P1 | |
| | ↳ optimize overall pipeline time (profile → targeted fixes) | 2–4 | V1.x | P1 | |
| | ↳ optimize LLM calls (batch/cache/reuse) | 2–4 | V1.x | P1 | extend incremental reuse |
| 13 | **Phase model & function-exclude** | **~3–5** | V1.x | P2 | |
| | ↳ revisit phase model (+ optimize function-hide: export-only/scoped) | 1–2 | V1.x | P2 | unblocks exclude-before-run |
| | ↳ function exclude-before-run (filter + full rerun) — only after Phase 1 | 2–3 | V1.x | P2 | phase-model concern |
| | **V1.x subtotal (tasks 8–13)** | **~35–50** | | | incl. DB ~16–19 |
| 14 | **SYS.2 doc generation** | **~12–24** | V2 | P2 | |
| | ↳ requirements discovery | 2–4 | V2 | P2 | |
| | ↳ implement generation | 10–20+ | V2 | P2 | after discovery; TBD |
| 15 | **SWE.1 doc generation** | **~12–24** | V2 | P2 | |
| | ↳ requirements discovery | 2–4 | V2 | P2 | |
| | ↳ implement generation | 10–20+ | V2 | P2 | after discovery; TBD |
| 16 | **SYS.1 doc generation** | **~12–24** | V2 | P2 | |
| | ↳ requirements discovery | 2–4 | V2 | P2 | |
| | ↳ implement generation | 10–20+ | V2 | P2 | after discovery; TBD |
| 17 | **Push DOCX to external website** | 2–4 | Later | P2 | depends on their API |
| 18 | **Import document → generate metadata** | 1–2 spike (+TBD) | Later | P2 | |
| | ↳ feasibility spike (is it viable?) | 1–2 | Later | P2 | |
| | ↳ build (if viable) | TBD | Later | P2 | after the spike |

**Rough grand total (excludes the SWE.4/SWE.2/SYS.2/SWE.1/SYS.1 implement + import build): ~51–85 person-days.**
Rollups: **V1 ~20–46 · V1.1 (SWE.4) ~8–16 · V1.2 (SWE.2) ~12–24 · V1.x ~35–50 (incl. DB ~16–19) · V2 discovery ~6–12 · Later ~3–6** (+ doc-type builds TBD/large).

## Key decisions
- **V1 ships SWE.3 only**, deployed in office, **hard** by 2026-07-15; shared across 3 people.
- **SWE.4 is the next deliverable, right after V1** (task 6: discovery → implement) — **internal reprioritization
  ahead of SWE.2** (task 7). SWE.4 is **not client-demanded**; chosen first because it is smaller/faster, reuses
  SWE.3 machinery almost directly, and one slice (dynamic-behaviour test specs) is buildable today. **SWE.2 follows**
  (V1.2). SYS.1/SYS.2/SWE.1 remain V2 (~end Aug 2026).
- **Restructuring (task 1) — status:** the **`engine/` bucket is done** (branch `refactor/folder-restructuring`): `engine/` = former `src/` **plus** its `config/`, `few_shot_examples/`, `assets/`, both dev generators, and `run.py`. Turned out **not purely cosmetic** — `config/` is resolved in ~6 sites + read by the api, and `run.py`'s location drives api root-detection; both were rewired (see PROJECT_CONTEXT top entry). **`api/` is kept, NOT renamed** to `api-server` — the hyphen is an illegal Python module name and api uses absolute `from api.` imports. **`tools/` is also done** — `mock-api` + the dev scripts (`create-sample-project`, `import-output-project`) moved under `tools/`. **Deferred (not done):** only the gitignored `.data/` grouping (model/output/workspaces/logs stay at repo root). Still `sys.path`-based; the ~47 path-injection sites remain **known debt, not scheduled**.
- **Real DB = PostgreSQL** via SQLAlchemy over the 12 repo interfaces (`api/repositories/interfaces.py`)
  — swap-in, no route/service changes. After V1; foundation can start in parallel. V1 runs JSON with a
  single uvicorn worker + `api/db/data/` backups.
- **Function hide/unhide** = full Phase 3–4 rerun (reuse 1–2); optimize later (task 13).
  **Exclude-before-run** needs Phase 1's parsed list → with/after the phase revisit (task 13).
- **Doc scope now = SYS.1, SYS.2, SWE.1, SWE.2, SWE.3, SWE.4.** SWE.4 moved *into* scope and *ahead of SWE.2*
  (see V1.1) — internal call, not client-demanded. SWE.5/6, SYS.3/4/5 remain out of scope.
- **Interface-table direction (task 3.6):** the table must follow the **function-call relationship** used by
  the static diagram, and stop factoring **global-variable access** into direction — so table ↔ diagram stay
  consistent. (Confirm this is the intended source of truth before implementing.)

### V1 folder layout (task 1)  — ✅ done · ⏳ deferred
```
engine/          ✅ src/ renamed + run.py + generators
   config/  few_shot_examples/  assets/   ✅ moved under engine/
api/              ✅ KEPT (not renamed to api-server — hyphen breaks `from api.` imports)
web-app/          ✅ unchanged
tools/            ✅ mock-api + dev scripts (create-sample-project, import-output-project)
tests/  docs/                              ✅ unchanged (scripts/ moved into tools/)
.data/ (gitignored) ⏳ model/ output/ workspaces/ logs/  (deferred — still at repo root)
```

## Open questions / TBD
- **Pre-V1 batch dependencies (task 3):** 3.3 (extra visible functions) is *hypothesised* to be caused by
  emulator files (3.1); 3.4 (wrong "Out" direction) by missing header parsing (3.2). Re-test both after the
  root fixes land before scheduling separate work on them.
- **task 3.10 "dynamic-behaviour issue"** — under-specified; get a concrete repro/definition before estimating.
- V1 auth model in office (simple accounts vs SSO)?
- **SWE.4 discovery** — field-level derivability of the two spec tables, "Unit" vs function granularity,
  and the requirements source (SWE.1 not built). See `docs/planning/SWE4_PLAN.md`.
- **SWE.2 red-bucket data source** — Resource/Config/Calibration: client-provided input vs code-extracted?
  (swing factor ±8–15d). See `docs/planning/SWE2_PLAN.md`.
- **Shared blocker:** where do "requirements" / Linked Work Items come from, given SWE.1 isn't built?
  (feeds both SWE.4 step 3 and SWE.2 traceability).
- **Two derivation cruxes** (both open-ended, non-deterministic → **draft-then-confirm**, need a client
  granularity target + sample to judge): SWE.2 §2.2.1 feature-list (collapse 1000s of functions → feature
  list) and SWE.4 test-case enumeration (right-sized cases per function). Judge by coverage + client acceptance.
- SWE.2 template — client reference, or design from scratch?
- External upload site — API/contract available?
- Owners per task (intentionally unassigned here).
