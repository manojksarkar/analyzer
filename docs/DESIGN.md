# Design

> See also: [README](../README.md) | [software_detailed_design.json](software_detailed_design.json) (output doc structure)

## Architecture

Parse C++ → model (single source of truth) → views → software_detailed_design.docx.

![Architecture](images/architecture.png)  
*Source: [architecture.drawio](images/architecture.drawio) (edit in draw.io, export to PNG)*

| Component | Role | Input/Output |
|-----------|------|--------------|
| **run.py** | Orchestrator | Invokes Phase 1 → 2 → 3 → 4 in sequence |
| **parser.py** | Phase 1: Parse | C++ files → model/metadata, functions, globalVariables, dataDictionary |
| **model_deriver.py** | Phase 2: Derive model | Model → units, modules, enriched functions/globals (persist to model/) |
| **run_views.py** | Phase 3: Generate views | Load model → run_views → output/interface_tables.json, etc. |
| **docx_exporter.py** | Phase 4: Export | interface_tables.json → software_detailed_design.docx |

**Model (single source of truth):** functions.json, globalVariables.json, units.json, modules.json, dataDictionary.json, metadata.json. See [Model Format](#model-format) below.

**Call graph (DAG):** The parser builds `call_graph` and `reverse_call_graph` and stores them per function as `calledByIds` and `callsIds` in functions.json. Phase 2 (model_deriver) uses these for unit aggregation (caller/callee units) and direction inference. Phase 3 (interface_tables) uses them for `callerUnits` and `calleesUnits` in the view output.

**LLM:** `llm_client.py` integrates with Ollama for function descriptions and direction labels. Model_deriver uses it to enrich functions (via `_get_description_overrides`). The flowcharts view (stub) uses LLM for diagram generation. Config provides `llm.baseUrl`, `llm.defaultModel`, `llm.timeoutSeconds`.

**Views (read-only projections):** Each view reads the model and writes output. Configurable via `config.views`. Implemented: interfaceTables → interface_tables.json; behaviourDiagram → output/behaviour_diagrams/ (calls external behaviour_diagram.py per function). Stubs: sequenceDiagrams, flowcharts, componentDiagram.

**Output:** software_detailed_design.docx — structure spec in [software_detailed_design.json](software_detailed_design.json): 1 Introduction, 2..N Modules (Static Design with unit interface tables, Dynamic Behaviour), Code Metrics, Appendix A.

---

## Config ([config/config.json](../config/config.json))

| Key | Description |
|-----|-------------|
| views | interfaceTables, sequenceDiagrams, flowcharts, componentDiagram (true/false), behaviourDiagram (object with scriptPath) |
| views.behaviourDiagram | { scriptPath } — scriptPath to behaviour_diagram.py; .mmd→.png via node_modules/.bin/mmdc (run npm install) |
| clang | llvmLibPath, clangIncludePath |
| llm | baseUrl, defaultModel, timeoutSeconds |
| export | docxPath, docxFontSize |

---

## Model Format

All keys use `|` (KEY_SEP) as separator. Paths use `/`.

### metadata.json
```json
{
  "basePath": "absolute/path/to/project",
  "projectName": "project_name",
  "generatedAt": "ISO8601",
  "version": 1
}
```

### functions.json
**Key format:** `module|unitname|qualifiedName|paramTypes` (e.g. `app|main|calculate|`, `math|utils|add|int,int`)

| Field | Type | Description |
|-------|------|-------------|
| qualifiedName | string | C++ full/scoped name |
| location | object | file, line, endLine |
| calledByIds | string[] | Function IDs that call this |
| callsIds | string[] | Function IDs this calls |
| interfaceId | string | IF_project_unit_index |
| parameters | array | name, type; range resolved at view time |
| direction | string | In, Out |
| description | string | (optional) |

**Example:**
```json
"app|main|calculate|": {
  "qualifiedName": "calculate",
  "location": { "file": "app/main.cpp", "line": 13, "endLine": 17 },
  "calledByIds": ["app|main|main|"],
  "callsIds": ["math|utils|add|int,int", "tests|dispatch|multiply|int,int"],
  "interfaceId": "IF_TEST_CPP_PROJECT_APP_MAIN_02",
  "parameters": [],
  "direction": "Out"
}
```

### globalVariables.json
**Key format:** `module|unitname|qualifiedName` (e.g. `app|main|g_globalResult`)

| Field | Type | Description |
|-------|------|-------------|
| qualifiedName | string | Variable full name |
| location | object | file, line |
| type | string | C++ type |
| interfaceId | string | IF_project_unit_index |
| direction | string | In, Out, In/Out, - |

**Example:**
```json
"tests|read_write|g_readWrite": {
  "qualifiedName": "g_readWrite",
  "location": { "file": "tests/direction/read_write.cpp", "line": 5 },
  "type": "int",
  "interfaceId": "IF_TEST_CPP_PROJECT_TESTS_DIRECTION_READ_WRITE_03",
  "direction": "In/Out"
}
```

### units.json
**Key format:** `module|unitname` (e.g. `app|main`, `tests|types`). Unitname = filename without extension. Multiple .cpp files with the same `module|unitname` merge into one unit (e.g. `tests/enum/types.cpp` and `tests/param/types.cpp` → `tests|types`).

| Field | Type | Description |
|-------|------|-------------|
| name | string | Display name (unitname) |
| path | string \| string[] | Path(s) without extension; single string for one-file unit, array when merged |
| fileName | string | Basename of first contributing file (e.g. `types.cpp`) |
| functionIds | string[] | Function IDs (`module\|unitname\|qualifiedName\|paramTypes`) in this unit |
| globalVariableIds | string[] | Global variable IDs (`module\|unitname\|qualifiedName`) in this unit |
| callerUnits | string[] | Unit keys that call functions in this unit (derived from calledByIds) |
| calleesUnits | string[] | Unit keys that functions in this unit call (derived from callsIds) |

**Example (single-file unit):**
```json
"app|main": {
  "name": "main",
  "path": "app/main",
  "fileName": "main.cpp",
  "functionIds": ["app|main|main|", "app|main|calculate|", ...],
  "globalVariableIds": ["app|main|g_globalResult"],
  "callerUnits": [],
  "calleesUnits": ["math|utils", "tests|types", ...]
}
```

**Example (merged unit):**
```json
"tests|types": {
  "name": "types",
  "path": ["tests/enum/types", "tests/param/types"],
  "fileName": "types.cpp",
  "functionIds": ["tests|types|checkStatus|Status", "tests|types|testInt32|param_int32_t,param_int32_t", ...],
  "globalVariableIds": [],
  "callerUnits": ["app|main"],
  "calleesUnits": []
}
```

### modules.json
**Key format:** Module name (first path segment, e.g. `app`, `math`, `outer`, `tests`). Groups units by top-level directory.

| Field | Type | Description |
|-------|------|-------------|
| units | string[] | Unit keys (`module|unitname`) belonging to this module; ordered by discovery |

**Example:**
```json
{
  "app": { "units": ["app|main"] },
  "math": { "units": ["math|utils"] },
  "outer": { "units": ["outer|helper"] },
  "tests": {
    "units": [
      "tests|classes",
      "tests|dispatch",
      "tests|namespaces",
      "tests|point_rect",
      "tests|read_write",
      "tests|types"
    ]
  }
}
```

### dataDictionary.json
**Key:** type name (e.g. `param_uint8_t`, `Status`)

| Field | Type | Description |
|-------|------|-------------|
| kind | string | struct, class, enum, typedef, primitive |
| name | string | Type name |
| qualifiedName | string | Fully qualified name |
| range | string | Value range (e.g. 0-0xFF, NA) |
| underlyingType | string | (typedef) underlying type |
| location | object | file, line |

### interface_tables.json (view)
Top-level keys: `unitNames` (unitKey → display name), then unit keys with `{ name, entries }`. Each entry has interfaceId, type (Function/Global Variable), interfaceName, qualifiedName, parameters, direction, callerUnits, calleesUnits.

---

## Logic Flow

### Phase 1 – Parse (parser.py)
1. Walk project dir for `.cpp`, `.h`, `.hpp`, etc.
2. For each file: libclang parse → `visit_definitions`, `visit_type_definitions` → collect functions, globals, types (structs, enums, typedefs, primitives in dataDictionary keyed by name/qualifiedName with kind).
3. Second pass: `visit_calls` → build call graph (call_graph, reverse_call_graph).
4. Write metadata.json, functions.json, globalVariables.json, dataDictionary.json.

### Phase 2 – Derive model (model_deriver.py)
1. Load functions, globals, metadata.
2. `_compute_unit_maps` → file list, qualified name → file mapping, unit names.
3. `_build_units_modules` → units.json, modules.json (per-file units with callerUnits, calleesUnits).
4. `_build_interface_index` → stable per-file interface index (01, 02, …).
5. `_get_description_overrides` → LLM descriptions for functions.
6. `_enrich_interfaces` → interfaceId, interfaceName, parameters (range), callerUnits, calleesUnits.
7. `_infer_direction_from_code` → direction for globals and functions (see below).
8. Persist enriched functions.json, globalVariables.json.

### Phase 3 – Generate views (run_views.py)
1. Load model (functions, globals, units, modules, dataDictionary) from model/.
2. `run_views` → for each enabled view in `config.views`, call view builder. interfaceTables → output/interface_tables.json.

### Phase 4 – Export (docx_exporter.py)
1. Load interface_tables.json.
2. Build Software Detailed Design structure ([spec](software_detailed_design.json)):
   - 1 Introduction (Purpose, Scope, Terms)
   - 2..N Modules (Static Design: unit header, unit interface table, per-interface sections; Dynamic Behaviour: 2.2.x per function with behaviour diagram PNG from mermaid-cli)
   - Code Metrics, Coding Rule, Test Coverage
   - Appendix A. Design Guideline
3. Table columns: Interface ID, Interface Name, Information, Data Type, Data Range, Direction, Source/Destination, Interface Type.
4. Save software_detailed_design.docx.

### Direction inference (Phase 2)
- **Globals:** Aggregate read/write in function bodies → In / Out / In/Out / -.
- **Functions:**  
  1. Write any global → Out.  
  2. Else read any global → In.  
  3. Else calls an Out function → Out.  
  4. Else called from another unit → In.  
  5. Else default In.

---

## Traversals

| What | Where | How |
|------|-------|-----|
| Call graph | parser.py | `visit_calls` builds call_graph, reverse_call_graph; stored in functions.calledByIds, callsIds |
| Direction propagation | model_deriver.py `_infer_direction_from_code` | If callee is Out, mark caller Out |
| Unit/module build | model_deriver.py `_build_units_modules` | Iterate file_paths; map to unit keys (module\|unitname); aggregate caller/callee units |
| View build | views/interface_tables.py | Builds interface tables; derives callerUnits/calleesUnits from calledByIds/callsIds; param range via get_range() |

---

## Extensibility

**Adding a new view:** 1) Add `src/views/my_view.py` with `@register("myView")` and `run(model, output_dir, model_dir, config)`. 2) Add `"myView": true` to `config.views`. 3) Import the module in `views/__init__.py`. Views read the model (functions, globals, units, modules, dataDictionary) and write to output/.
