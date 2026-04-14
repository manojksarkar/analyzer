# C++ Codebase Analyzer

Parses C++ source code using **libclang** and generates a **Software Detailed Design** document (DOCX).

```
C++ source  →  Phase 1: parse (AST)
            →  Phase 2: enrich (units, call graph, direction, interface IDs)
            →  Phase 3: views (interface tables, flowcharts, diagrams)
            →  Phase 4: export → software_detailed_design_{group}.docx
```

---

## Prerequisites

- Python 3.10+
- LLVM 17 with libclang (`C:\Program Files\LLVM\bin\libclang.dll`)
- Node.js + mermaid-cli for diagram rendering: `npm install @mermaid-js/mermaid-cli`
- Python packages: `pip install -r requirements.txt`

---

## Quick start

```bash
# Full run — all groups, all phases
python run.py <project_path>

# Full run — one group only
python run.py --clean <project_path> --selected-group Sample

# Skip parsing, reuse existing model (re-run views + export only)
python run.py --use-model <project_path> --selected-group Sample
```

Output: `output/software_detailed_design_{group}.docx`

---

## CLI flags

| Flag | Description |
|---|---|
| `--clean` | Delete `model/` and `output/` before starting |
| `--selected-group <name>` | Run views + export for one group only (case-insensitive) |
| `--use-model` / `--skip-model` | Skip Phase 1+2, reuse existing `model/` files |
| `--from-phase <1-4>` | Start from a specific phase (e.g. `4` = export only) |

**Group behaviour:**
- With `--selected-group`: output goes to `output/` (flat)
- Without `--selected-group`: each group exports to `output/<group>/` (subdirectory per group)

---

## Config

Main config: `config/config.json` (supports `//` and `/* */` comments)  
Local overrides: `config/config.local.json` (not committed, merged on top)

Key settings:

```json
{
  "clang": { "llvmLibPath": "...", "clangIncludePath": "..." },
  "views": {
    "interfaceTables": true,
    "unitDiagrams": { "renderPng": true },
    "flowcharts": { "renderPng": true },
    "behaviourDiagram": { "renderPng": true },
    "moduleStaticDiagram": { "enabled": true, "renderPng": true }
  },
  "llm": { "descriptions": false, "behaviourNames": false },
  "modulesGroups": {
    "Sample": { "Core": ["Sample/Core"], "Lib": ["Sample/Lib"] }
  }
}
```

LLM integration (Ollama) is **off by default**. Set `"descriptions": true` to enable.

---

## Views produced

| View | Output | Description |
|---|---|---|
| Interface Tables | `output/interface_tables.json` | Public functions and globals per unit with IF_ IDs, direction, data type |
| Unit Diagrams | `output/unit_diagrams/*.png` | Mermaid class diagram per unit |
| Behaviour Diagrams | `output/behaviour_diagrams/*.png` | One diagram per external caller showing call flow |
| Flowcharts | `output/flowcharts/*.json` + PNG | One Mermaid flowchart per function |
| Module Static | `output/module_static_diagrams/*.png` | Module-level structure diagram |

---

## Testing

Three layers — run only what you need:

```bash
# Unit tests — instant, no pipeline needed
python -m pytest tests/unit/ -v

# Integration — pipeline runs once, checks intermediate JSON/Mermaid artifacts
python -m pytest tests/integration/ -v

# E2E — pipeline runs once, checks the final DOCX
python -m pytest tests/e2e/ -v

# Everything
python -m pytest tests/ -v

# Reuse existing output (skip the pipeline rerun)
python -m pytest tests/ -v --skip-pipeline

# Regenerate golden snapshots after an intentional pipeline change
python -m pytest tests/integration/test_interface_tables.py --update-snapshots --skip-pipeline
```

Or select by marker: `-m unit`, `-m integration`, `-m e2e`.

Tests run against `SampleCppProject` with `--selected-group Sample`.
The pipeline only runs when integration or e2e tests are collected — unit tests are always instant.

---

## Documentation

| Document | Description |
|---|---|
| [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) | Full pipeline, model schema, config, CLI, design decisions, test framework |
| [docs/DESIGN.md](docs/DESIGN.md) | Architecture and logic flow |
