# C++ Codebase Analyzer

Parse C++ source → model/ (Phase 1–2) → output/ (Phase 3 views) → **software_detailed_design.docx** (Phase 4).

## Quick start

The `SampleCppProject/` test fixture lives directly in this repo, so a plain clone has
everything:

```bash
python engine/run.py SampleCppProject
```

Config: [engine/config/config.json](engine/config/config.json) (override with `config.local.json`).

## Web UI

The web client is [web-app/](web-app/) (React + Vite) talking to the FastAPI backend in
[api/](api/) — see each folder's README to run them. (The legacy Streamlit `ui/` was
removed when the web app landed.)

## Documentation

Deep engineering context (agent-facing, start here): **[PROJECT_CONTEXT.md](PROJECT_CONTEXT.md)**.

- **Architecture** — [DESIGN.md](docs/design/DESIGN.md) (model format, config, logic flow, DOCX export)
- **Planning** (leadership) — [ROADMAP](docs/planning/ROADMAP.md) · [doc-gen method](docs/planning/DOC_GENERATION_PLAYBOOK.md) · plans: [SWE.4](docs/planning/SWE4_PLAN.md) / [SWE.2](docs/planning/SWE2_PLAN.md) / [SYS.2](docs/planning/SYS2_PLAN.md) · [backlog](docs/BACKLOG.md)
- **Specs** (engineering, per doc-type) — [SWE3_SPEC](docs/spec/SWE3_SPEC.md) · [SWE4_SPEC](docs/spec/SWE4_SPEC.md) · [UT export](docs/spec/UT_EXPORT_SPEC.md) · [test inventory](docs/spec/TEST_INVENTORY.md)
- **Production redesign** (POC→production studies) — [01 tech](docs/production-redesign/01-technology-selection-study.md) · [02 database](docs/production-redesign/02-database-design-study.md) · [03 incremental](docs/production-redesign/03-incremental-changes-design.md) · [04 impl](docs/production-redesign/04-incremental-changes-implementation.md) · [05 API spec](docs/production-redesign/05-incremental-api-spec.md) · [06 runbook](docs/production-redesign/06-end-to-end-runbook.md) · [07 PG migration](docs/production-redesign/07-postgresql-migration-plan.md) · [08 storage seam](docs/production-redesign/08-storage-seam-version-identity.md) · [09 post-migration plan](docs/production-redesign/09-post-migration-consolidation-plan.md) · [10 DB-native pipeline](docs/production-redesign/10-db-native-pipeline.md)
- **Subsystems** — [api/](api/README.md) (+ [PLAN](api/PLAN.md)) · [web-app/](web-app/README.md) (+ [PLAN](web-app/PLAN.md)) · engine/ (+ [PLAN](engine/PLAN.md)) · [flowchart engine](engine/flowchart/README.md)
- **Agent roles** (`.claude/skills/`) — `docs-maintainer` · `ui-dev`
