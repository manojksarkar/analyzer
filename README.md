# C++ Codebase Analyzer

C++ source → a model of every function, global and type, stored in a database (PostgreSQL, or
SQLite locally) → ASPICE documents per component: **SWE.3 Software Detailed Design** and **SWE.4 Unit
Test Specification** (DOCX).

## Quick start

Installation, dependencies, configuration and every command: **[docs/SETUP.md](docs/SETUP.md)**. In short:

```
pip install -r requirements.txt
npm install
python analyzer.py setup
python analyzer.py doctor
```

Then either the web app — `start-app` (Windows) or `python tools/start_app.py`, which checks for old
servers and stale code, then starts the API and [web-app/](web-app/) — or the command line,
[docs/CLI_COMMANDS.md](docs/CLI_COMMANDS.md).

Config: [engine/config/config.defaults.json](engine/config/config.defaults.json), overridden by
`engine/config/config.local.json` (machine settings and secrets; template
[config.local.json.example](engine/config/config.local.json.example)).

## Web UI

The web client is [web-app/](web-app/) (React + Vite) talking to the FastAPI backend in
[api/](api/), which runs the real pipeline. (The legacy Streamlit `ui/` was removed when the web app
landed.)

## Documentation

Deep engineering context (agent-facing, start here): **[PROJECT_CONTEXT.md](PROJECT_CONTEXT.md)** — the index into
[project-context/](project-context/) (topic files and the dated history).

- **Install and run** — [SETUP.md](docs/SETUP.md) (dependencies, config, database, web app, tests) · [CLI_COMMANDS.md](docs/CLI_COMMANDS.md) (every `analyzer.py` command)
- **Architecture** — [DESIGN.md](docs/design/DESIGN.md) (model format, config, logic flow, DOCX export) · [review & update](docs/design/REVIEW_UPDATE_DESIGN.md) · [review & update — merge handover](docs/design/REVIEW_UPDATE_HANDOVER.md) · [review & approval](docs/design/REVIEW_APPROVE_DESIGN.md) · [Word file updates after corrections](docs/design/WORD_FILE_UPDATES.md) (approved) · [fast Word-file updates](docs/design/FAST_WORD_FILE_UPDATES.md) (built) · [Bitbucket repositories](docs/design/BITBUCKET_SUPPORT.md) (built) · [live logs](docs/design/LIVE_LOGS_DESIGN.md)
- **Database** — [DB_SCHEMA.md](docs/design/DB_SCHEMA.md) (ER diagrams + debugging query cookbook) · [zoomable viewer](docs/design/schema-atlas.html) (offline HTML, pan/zoom diagrams)
- **Planning** (leadership) — [ROADMAP](docs/planning/ROADMAP.md) · [doc-gen method](docs/planning/DOC_GENERATION_PLAYBOOK.md) · plans: [SWE.4](docs/planning/SWE4_PLAN.md) / [SWE.2](docs/planning/SWE2_PLAN.md) / [SYS.2](docs/planning/SYS2_PLAN.md) · [backlog](docs/BACKLOG.md)
- **Specs** (engineering, per doc-type) — [SWE3_SPEC](docs/spec/SWE3_SPEC.md) · [SWE4_SPEC](docs/spec/SWE4_SPEC.md) · [UT export](docs/spec/UT_EXPORT_SPEC.md) · [test inventory](docs/spec/TEST_INVENTORY.md) · [review & update](docs/spec/REVIEW_UPDATE_SPEC.md) · [review & update API](docs/spec/REVIEW_UPDATE_API_SPEC.md) · [review & approval API](docs/spec/REVIEW_APPROVE_API_SPEC.md) · [live logs](docs/spec/LIVE_LOGS_SPEC.md) · [review & update requirements](docs/REVIEW_UPDATE_REQUIREMENTS.md) (plain English, for sign-off)
- **Wikis** (client-facing, "how each section is generated") — [SWE3_WIKI](docs/spec/SWE3_WIKI.md) · [SWE4_WIKI](docs/spec/SWE4_WIKI.md)
- **Production redesign** (POC→production studies) — [01 tech](docs/production-redesign/01-technology-selection-study.md) · [02 database](docs/production-redesign/02-database-design-study.md) · [03 incremental](docs/production-redesign/03-incremental-changes-design.md) · [04 impl](docs/production-redesign/04-incremental-changes-implementation.md) · [05 API spec](docs/production-redesign/05-incremental-api-spec.md) · [06 runbook](docs/production-redesign/06-end-to-end-runbook.md) · [07 PG migration](docs/production-redesign/07-postgresql-migration-plan.md) · [08 storage seam](docs/production-redesign/08-storage-seam-version-identity.md) · [09 post-migration plan](docs/production-redesign/09-post-migration-consolidation-plan.md) · [10 DB-native pipeline](docs/production-redesign/10-db-native-pipeline.md)
- **Subsystems** — [api/](api/README.md) (+ [PLAN](api/PLAN.md)) · [web-app/](web-app/README.md) (+ [PLAN](web-app/PLAN.md)) · engine/ (+ [PLAN](engine/PLAN.md)) · [flowchart engine](engine/flowchart/README.md)
- **Tools** — [doccheck](tools/doccheck/README.md) (compare two generated documents by content) · [import-output-project](tools/import-output-project/README.md)
- **Agent roles** (`.claude/skills/`) — `docs-maintainer` · `ui-dev`
