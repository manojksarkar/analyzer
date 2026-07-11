# C++ Codebase Analyzer

Parse C++ source → model/ (Phase 1–2) → output/ (Phase 3 views) → **software_detailed_design.docx** (Phase 4).

## Quick start

```bash
python backend/run.py test_cpp_project
```

Config: [backend/config/config.json](backend/config/config.json) (override with `config.local.json`).

## UI

A Streamlit web interface for configuring, running the pipeline, and viewing results.

### Install

```bash
pip install -r requirements.txt
pip install -r ui/requirements.txt
```

### Run

```bash
streamlit run ui/app.py
```

Opens at `http://localhost:8501` in your browser.

> The UI reads and writes `backend/config/config.json`. Set your project path, configure groups/modules, then click **Run full** to execute the pipeline.

## Documentation

| Document | Description |
|----------|-------------|
| [docs/design/DESIGN.md](docs/design/DESIGN.md) | Architecture, model format, config, logic flow |
| [docs/spec/software_detailed_design.json](docs/spec/software_detailed_design.json) | Document structure spec for the output DOCX |
| [docs/design/images/architecture.drawio](docs/design/images/architecture.drawio) | Architecture diagram (edit in draw.io, export to PNG) |
