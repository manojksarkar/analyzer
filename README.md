# C++ Codebase Analyzer

Parse C++ source → raw model (model/) → design views (output/).

## Structure (Option A)

```
├── config/           config.json, schema.json
├── src/              parser.py, generator.py, llm_client.py, utils.py
├── model/            raw model (single source of truth)
│   ├── functions.json
│   ├── globalVariables.json
│   ├── units.json
│   └── modules.json
├── output/           design views
│   ├── interface_tables.json
│   └── interface_tables.docx
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
  "clangIncludePath": "C:\\Program Files\\LLVM\\lib\\clang\\17\\include",
  "enableDescriptions": false,
  "ollamaBaseUrl": "http://localhost:11434",
  "ollamaModel": "llama3.2"
}
```

**LLM (Ollama):** Set `enableDescriptions` to `true` to add function descriptions to the interface table. Requires Ollama running locally and `pip install requests`.

**DOCX export:** Phase 3 exports `output/interface_tables.docx` from the JSON. Requires `pip install python-docx`.

## Outputs

| Output | Purpose |
|--------|---------|
| **model/** | Raw model (parser + generator) |
| model/functions.json | functions dict; basePath, projectName, location, params, callersFunctionNames, calleesFunctionNames |
| model/globalVariables.json | globalVariables dict |
| model/units.json | units dict; functions, globalVariables, callerUnits, calleesUnits per file |
| model/modules.json | modules dict; units grouped by module |
| **output/** | Design views |
| output/interface_tables.json | { unit_name: [{ interfaceId, type, interfaceName, ... }] } grouped by unit |
| output/interface_tables.docx | Word document with interface tables per unit |
