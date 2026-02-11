# C++ Codebase Analyzer

Parse C++ source → model/ → output/ (interface tables). See [docs/DESIGN.md](docs/DESIGN.md).

```
python run.py test_cpp_project
```

Config: `config/config.json` (override with `config.local.json`). Keys: `llvmLibPath`, `clangIncludePath`, `enableDescriptions`, `export.enableDocx`, `llm`.
