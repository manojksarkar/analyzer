# C++ Codebase Analyzer

Parse -> metadata -> 3 outputs + flowchart (future).

## Structure

```
├── config/           config.json, schema.json
├── src/              parser.py, generator.py, utils.py
├── output/           metadata.json, interfaces.json, component.json, units.json
├── run.py
└── test_cpp_project/
```

## Usage

```bash
python run.py test_cpp_project
```
(project_path is relative to script dir or absolute)

## Config

Edit `config/config.json` or create `config/config.local.json` (gitignored) to override:

```json
{
  "llvmLibPath": "C:\\Program Files\\LLVM\\bin\\libclang.dll",
  "clangIncludePath": "C:\\Program Files\\LLVM\\lib\\clang\\17\\include"
}
```

## Outputs

| Output | Purpose |
|--------|---------|
| interfaces.json | Interface table |
| component.json | Component diagram |
| units.json | Unit design |
