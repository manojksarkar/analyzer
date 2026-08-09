# ArtiFex — Roadmap

> High-level milestones, decisions, and remaining work. Kept intentionally short.
> Engineering detail (fixes, estimates, design notes) lives in the repo's `PROJECT_CONTEXT.md`.

**What ArtiFex does:** analyses a C++ codebase and generates ASPICE process documents from it.
Target scope = 6 processes: **SYS.1, SYS.2, SWE.1, SWE.2, SWE.3, SWE.4**. SWE.3 (detailed design) ships
first; the rest follow in the order below.

## Domain context

**The codebase under analysis** is automotive firmware, forked from the **UFS** firmware codebase.
Automotive delivery is what creates the documentation requirement: an ASPICE assessment expects specific
process documents as audit evidence at a defined capability level (`ASPICE_L2` / `ASPICE_L3`, the API's
`compliance_standard`). ArtiFex generates those documents from the source instead of having engineers
author them by hand.

**Delivered scope is SWE.3 only.** SWE.4 is in flight on `feat/swe4-unit-test-spec`; SWE.2, SYS.1, SYS.2
and SWE.1 are roadmap. The 6-process target above is the destination, not the current state.

> **ISO 26262 is not in scope.** It appears in the API description string and in seeded demo fixtures
> (`api/db/in_memory.py` — "BMW", "VCU Engine Firmware", "ADAS Sensor Fusion" are placeholder rows).
> Both are illustrative; no ISO 26262 work is implemented.

## Milestones

| Milestone | Focus | Done when |
|---|---|---|
| **V1** | SWE.3 detailed-design generation, deployed in the office | Client uses ArtiFex in-office to generate and review SWE.3 documents; known review fixes cleared |
| **V1.1** | **SWE.4** — Software Unit Verification (test specifications) | SWE.4 documents generated from the SWE.3 design |
| **V1.2** | **SWE.2** — Software Architectural Design | SWE.2 architecture document generated |
| **V1.x** | Platform hardening | Automated testing/CI, database, progress bar, in-app settings + re-run, performance/LLM optimisation |
| **V2** | **SYS.1, SYS.2, SWE.1** generation | Requirements-side documents generated (scope to be discovered) |
| **Later** | Integrations | Publish documents to an external site; import an existing document to seed metadata |

## Key decisions

- **Document order:** SWE.3 first, then **SWE.4**, then **SWE.2**. SWE.4 comes before SWE.2 because it is
  smaller, faster, and reuses the SWE.3 machinery almost directly.
- **Scope:** the 6 ASPICE processes above. Others are out of scope for now.
- **V1 is deployed in the office** and shared across the team.
- **Database:** moves to a real database (PostgreSQL) after V1; V1 runs on the current file-based store.
- **How the documents are generated:** see [DOC_GENERATION_PLAYBOOK.md](DOC_GENERATION_PLAYBOOK.md).

## Remaining work

> Item-level known issues and deferred fixes: [../BACKLOG.md](../BACKLOG.md).

**V1**
- [ ] Deploy in the office (server, runtime, web app + API, user accounts, end-to-end smoke test)
- [x] Complete macro ingestion — toolchain JSON dumps, per-layer scoping, wired through the web app
- [ ] Complete data-dictionary ingestion
- [ ] Remaining flowchart-rendering polish
- [ ] Function show/hide in the generated document
- [ ] Release + client review of SWE.3, with a buffer for review fixes

**V1.1 — SWE.4** → see [SWE4_PLAN.md](SWE4_PLAN.md)
**V1.2 — SWE.2** → see [SWE2_PLAN.md](SWE2_PLAN.md)

**V1.x**
- [ ] Automated test suite + CI
- [ ] Real database (PostgreSQL)
- [ ] Real progress bar during generation
- [ ] In-app settings + re-run after a configuration change
- [ ] Performance and LLM-usage optimisation

**V2** → SYS.2 (see [SYS2_PLAN.md](SYS2_PLAN.md)), plus SWE.1 and SYS.1 (discovery first)

**Later**
- [ ] Publish generated documents to an external site
- [ ] Import an existing document to generate metadata (feasibility spike first)
