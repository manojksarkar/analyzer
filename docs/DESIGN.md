# Design

## Architecture

Parse C++ → model (single source of truth) → views (interface tables, DOCX).

![Architecture](images/architecture.png)  
*Editable: `docs/images/architecture.drawio` (draw.io)*

| Component | Role | Input/Output |
|-----------|------|--------------|
| **run.py** | Orchestrator | Invokes Phase 1 → 2 → 3 in sequence |
| **parser.py** | Phase 1: Parse | C++ files → model/metadata, functions, globalVariables, dataDictionary |
| **generator.py** | Phase 2: Derive & views | Model → units, modules, enriched functions/globals, interface_tables.json |
| **docx_exporter.py** | Phase 3: Export | interface_tables.json → interface_tables.docx |

**Model (single source of truth):** functions.json, globalVariables.json, units.json, modules.json, dataDictionary.json, metadata.json. See [Model Format](#model-format) below.

**Views (read-only projections):** interface_tables.json, interface_tables.docx. Recomputable from model.

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
| description | string | (optional) LLM-enriched |

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
Top-level keys: `unitNames` (unitKey → display name), then unit keys with `{ name, entries }`. Each entry has interfaceId, type (function/globalVariable), interfaceName, qualifiedName, parameters, direction, callerUnits, calleesUnits.

---

## Logic Flow

### Phase 1 – Parse (parser.py)
1. Walk project dir for `.cpp`, `.h`, `.hpp`, etc.
2. For each file: libclang parse → `visit_definitions`, `visit_type_definitions` → collect functions, globals, types (structs, enums, typedefs, primitives in dataDictionary keyed by name/qualifiedName with kind).
3. Second pass: `visit_calls` → build call graph (call_graph, reverse_call_graph).
4. Write metadata.json, functions.json, globalVariables.json, dataDictionary.json.

### Phase 2 – Derive & views (generator.py)
1. Load functions, globals, metadata.
2. `_compute_unit_maps` → file list, qualified name → file mapping, unit names.
3. `_build_units_modules` → units.json, modules.json (per-file units with callerUnits, calleesUnits).
4. `_build_interface_index` → stable per-file interface index (01, 02, …).
5. `_enrich_interfaces` → interfaceId, interfaceName, parameters (range), callerUnits, calleesUnits.
6. Optional: `_maybe_enrich_descriptions` (LLM) → description per function.
7. `_infer_direction_from_code` → direction for globals and functions (see below).
8. Persist enriched functions.json, globalVariables.json.
9. `build_interface_tables` → interface_tables.json (grouped by unit).

### Direction inference
- **Globals:** Aggregate read/write in function bodies → In / Out / In/Out / -.
- **Functions:**  
  1. Write any global → Out.  
  2. Else read any global → In.  
  3. Else calls an Out function → Out.  
  4. Else called from another unit → In.  
  5. Else default In; optional LLM refine (`enableDirectionLLM`).

### Phase 3 – Export (docx_exporter.py)
1. Load interface_tables.json.
2. Group by module → units → tables with columns (Interface ID, Interface Name, Information, Data Type, Data Range, Direction, Source/Destination, Interface Type).
3. Save DOCX.

---

## Traversals

| What | Where | How |
|------|-------|-----|
| Call graph | parser.py | `visit_calls` builds call_graph, reverse_call_graph; stored in functions.calledByIds, callsIds |
| Direction propagation | generator.py `_infer_direction_from_code` | If callee is Out, mark caller Out |
| Unit/module build | generator.py `_build_units_modules` | Iterate file_paths; map to unit keys (module\|unitname); aggregate caller/callee units |
| View build | interface_tables.py `build_interface_tables` | Derive callerUnits/calleesUnits from calledByIds/callsIds; resolve param range via get_range(); produce { unitKey: { name, entries } } |

---

## Extensibility

New views: create a view builder that reads model (functions, globals, units, modules, dataDictionary), traverses as needed, writes output. Call it from `generator.main()` after `build_interface_tables`.
