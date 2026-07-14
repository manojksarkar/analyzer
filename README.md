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

| Document | Description |
|----------|-------------|
| [docs/design/DESIGN.md](docs/design/DESIGN.md) | Architecture, model format, config, logic flow |
| [docs/spec/software_detailed_design.json](docs/spec/software_detailed_design.json) | Document structure spec for the output DOCX |
| [docs/design/images/architecture.drawio](docs/design/images/architecture.drawio) | Architecture diagram (edit in draw.io, export to PNG) |
