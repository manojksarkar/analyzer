# C++ Codebase Analyzer

Parse C++ source → raw model (model/) → design views (output/).

## Structure (Option A)

```
├── config/           config.json, schema.json
├── src/              parser.py, generator.py, llm_client.py, utils.py
├── model/            raw model (single source of truth)
│   ├── functions.json
│   ├── globalVariables.json
│   ├── dataDictionary.json
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
  "export": {
    "enableDocx": true,
    "docxPath": "output/interface_tables.docx",
    "docxFontSize": 8
  },
  "ollamaBaseUrl": "http://localhost:11434",
  "ollamaModel": "llama3.2"
}
```

**LLM (Ollama):** Set `enableDescriptions` to `true` to add function descriptions to the interface table. Requires Ollama running locally and `pip install requests`.

**DOCX export:** Phase 3 exports to DOCX when `export.enableDocx` is true. Config: `export.docxPath`, `export.docxFontSize`. Requires `pip install python-docx`.

## Outputs

| Output | Purpose |
|--------|---------|
| **model/** | Raw model (parser + generator) |
| model/functions.json | functions dict; **one entry per function**, including location, params, call graph, and enriched interface metadata (see below) |
| model/globalVariables.json | globalVariables dict; **one entry per global variable**, with enriched interface metadata (see below) |
| model/dataDictionary.json | structs, enums, typedefs (name, qualifiedName, fields/enumerators/underlyingType, location) |
| model/units.json | units dict; functions, globalVariables, callerUnits, calleesUnits per file |
| model/modules.json | modules dict; units grouped by module |
| **output/** | Design views |
| output/interface_tables.json | { unit_name: [{ interfaceId, type, interfaceName, ... }] } grouped by unit |
| output/interface_tables.docx | Word document with interface tables per unit |

## Core JSON shapes (simplified)

- **`model/functions.json`** (keyed by `"<relPath>:<line>"`)

```json
{
  "app_main/main.cpp:12": {
    "name": "calculate",
    "qualifiedName": "calculate",
    "location": { "file": "app_main/main.cpp", "line": 12, "endLine": 16 },
    "module": "app_main",
    "params": [
      { "name": "a", "type": "int" },
      { "name": "b", "type": "int" }
    ],
    "callersFunctionNames": ["main"],
    "calleesFunctionNames": ["add", "multiply"],

    "interfaceId": "IF_TEST_CPP_PROJECT_APP_MAIN_MAIN_02",
    "interfaceName": "MAIN_calculate",
    "parameters": [
      { "name": "a", "type": "int", "range": "-2147483648-2147483647" },
      { "name": "b", "type": "int", "range": "-2147483648-2147483647" }
    ],
    "callerUnits": ["app_main/main"],
    "calleesUnits": ["math_utils/utils"],
    "direction": "Out",
    "description": "Short LLM-generated description (optional)"
  }
}
```

- **`model/globalVariables.json`** (keyed by `"<relPath>:<line>"`)

```json
{
  "app_main/main.cpp:6": {
    "name": "g_globalResult",
    "qualifiedName": "g_globalResult",
    "location": { "file": "app_main/main.cpp", "line": 6 },
    "module": "app_main",
    "type": "int",

    "interfaceId": "IF_TEST_CPP_PROJECT_APP_MAIN_MAIN_01",
    "interfaceName": "MAIN_g_globalResult",
    "callerUnits": [],
    "calleesUnits": [],
    "direction": "In/Out"
  }
}
```

- **`output/interface_tables.json`** (view, grouped by unit; no extra metadata)

```json
{
  "app_main/main": [
    {
      "interfaceId": "IF_TEST_CPP_PROJECT_APP_MAIN_MAIN_01",
      "type": "globalVariable",
      "interfaceName": "MAIN_g_globalResult",
      "name": "g_globalResult",
      "qualifiedName": "g_globalResult",
      "location": { "file": "app_main/main", "line": 6 },
      "variableType": "int",
      "direction": "In/Out",
      "callerUnits": [],
      "calleesUnits": []
    },
    {
      "interfaceId": "IF_TEST_CPP_PROJECT_APP_MAIN_MAIN_02",
      "type": "function",
      "interfaceName": "MAIN_calculate",
      "name": "calculate",
      "qualifiedName": "calculate",
      "location": { "file": "app_main/main", "line": 12, "endLine": 16 },
      "parameters": [
        { "name": "a", "type": "int", "range": "-2147483648-2147483647" },
        { "name": "b", "type": "int", "range": "-2147483648-2147483647" }
      ],
      "direction": "Out",
      "callerUnits": ["app_main/main"],
      "calleesUnits": ["math_utils/utils"],
      "description": "Short LLM-generated description (optional)"
    }
  ]
}
```

**Key points:**
- **Model files** (`functions.json`, `globalVariables.json`, `units.json`, `modules.json`, `dataDictionary.json`) are the **single source of truth**.
- **Views** (`interface_tables.json`, `interface_tables.docx`, future diagrams/tables) are **read-only projections** that can always be recomputed from the model.
