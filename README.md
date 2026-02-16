# C++ Codebase Analyzer

Parse C++ source → model/ (Phase 1–2) → output/ (Phase 3 views) → **software_detailed_design.docx** (Phase 4).

## Quick start

```bash
python run.py test_cpp_project
```

Config: [config/config.json](config/config.json) (override with `config.local.json`).

## Documentation

| Document | Description |
|----------|-------------|
| [docs/DESIGN.md](docs/DESIGN.md) | Architecture, model format, config, logic flow |
| [docs/software_detailed_design.json](docs/software_detailed_design.json) | Document structure spec for the output DOCX |
| [docs/images/architecture.drawio](docs/images/architecture.drawio) | Architecture diagram (edit in draw.io, export to PNG) |
