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

Deep engineering context (kept current, start here): **[PROJECT_CONTEXT.md](PROJECT_CONTEXT.md)**.

- **Architecture** — [docs/design/DESIGN.md](docs/design/DESIGN.md) (model format, config, logic flow)
- **Planning** (leadership) — [ROADMAP](docs/planning/ROADMAP.md) · [doc-gen method](docs/planning/DOC_GENERATION_PLAYBOOK.md) · plans: [SWE.4](docs/planning/SWE4_PLAN.md) / [SWE.2](docs/planning/SWE2_PLAN.md) / [SYS.2](docs/planning/SYS2_PLAN.md) · [backlog](docs/BACKLOG.md)
- **Specs** (engineering, per doc-type) — [SWE3_SPEC](docs/spec/SWE3_SPEC.md) · [SWE4_SPEC](docs/spec/SWE4_SPEC.md) · [test inventory](docs/spec/TEST_INVENTORY.md)
- **Subsystems** — [api/](api/README.md) · [web-app/](web-app/README.md) · [flowchart engine](engine/flowchart/README.md)
