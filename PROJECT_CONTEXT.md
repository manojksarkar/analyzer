# C++ Codebase Analyzer — Complete Project Context
> Generated: 2026-04-08 (updated x2). Validated against current source code.

---

## 1. Repository Overview

A Python tool that parses C++ source code using **libclang** and generates a **Software Detailed Design** document (DOCX).

### Top-level paths

```
run.py                          — CLI entry point (all phases)
config/config.json              — Main config (no inline comments natively, but // and /* */ stripped at load)
config/config.local.json        — Local overrides (not committed)
src/parser.py                   — Phase 1: C++ AST → model/ JSON
src/model_deriver.py            — Phase 2: enrich model (units, modules, call graph, direction, behaviour names)
src/run_views.py                — Phase 3: load model → invoke view builders
src/docx_exporter.py            — Phase 4: views output → DOCX
src/utils.py                    — Shared helpers (keys, logging, config loading, path helpers)
src/llm_client.py               — Ollama LLM integration (descriptions, behaviour names)
src/views/
  __init__.py                   — run_views() orchestrator + view imports
  registry.py                   — @register decorator and VIEW_REGISTRY dict
  interface_tables.py           — interfaceTables view
  unit_diagrams.py              — unitDiagrams view (Mermaid + PNG per unit)
  behaviour_diagram.py          — behaviourDiagram view (Mermaid + PNG per external caller)
  flowcharts.py                 — flowcharts view (invokes fake_flowchart_generator.py)
fake_flowchart_generator.py     — Generates per-unit flowchart JSON (one Mermaid per function)
fake_behaviour_diagram_generator.py — FakeBehaviourGenerator class: one .mmd per external caller
model/                          — Phase 1+2 output (JSON)
output/                         — Phase 3+4 output (JSON, .mmd, .png, .docx)
test_cpp_project/               — Fixture C++ project used for testing (only fixture; no _extend variants)
docs/DESIGN.md                  — Design documentation
```

> **Important**: `test_cpp_project_extend` and `tes_cpp_project_extend` referenced in older docs **do NOT exist** in this repo. Only `test_cpp_project` is present.

---

## 2. 4-Phase Pipeline

```
Phase 1  src/parser.py          C++ source → model/functions.json, globalVariables.json,
                                             dataDictionary.json, metadata.json
Phase 2  src/model_deriver.py   model/ → model/units.json, modules.json
                                         enriches functions.json (interfaceId, direction,
                                         behaviourNames, LLM descriptions)
Phase 3  src/run_views.py       model/ → output/ (interface_tables.json, unit_diagrams/,
                                         behaviour_diagrams/, flowcharts/)
Phase 4  src/docx_exporter.py   output/ → software_detailed_design_{group}.docx
```

---

## 3. CLI — run.py

### Syntax

```bash
python run.py [--clean] [--use-model|--skip-model] [--selected-group <name>] <project_path>
```

### Argument parsing (`_parse_args`)

Implemented with an explicit token-scanning loop (no `argparse`). Flags are consumed by name; any non-flag non-consumed token becomes `project_path` (last one wins). **This fixed an older bug** where `--selected-group core` left `core` as the project path.

### Group resolution (`_resolve_group_name`)

Case-insensitive match of `--selected-group` against `config.modulesGroups` keys using `.casefold()`. Logs a message if casing differs. Exits with code 2 and lists valid groups if no match.

### Runtime behavior

| Condition | Behavior |
|---|---|
| `modulesGroups` in config, no `--selected-group` | Build model once (all modules), then export **each** group to `output/<group>/` |
| `modulesGroups` in config, `--selected-group <G>` | Build model once (all modules), then export only group `G` to `output/` (no subdir) |
| No `modulesGroups` in config | Single run over whole project, output to `output/` |
| `--use-model` / `--skip-model` | Skip Phase 1+2, verify model files exist, then run Phase 3+4 |
| `--clean` | Delete `model/` and `output/` before starting |

### Output path difference between modes

- **All-groups mode**: Phase 3 called with `--output-dir output/<group> --selected-group <G>`. Phase 4 called with explicit JSON and DOCX paths inside `output/<group>/`.
- **Single-group mode**: Phase 3 called with just `--selected-group <G>` (no `--output-dir`). Phase 4 called with just `--selected-group <G>`. Output goes to `output/` (not a subdirectory).

### Required model files for `--use-model`

`model/functions.json`, `model/globalVariables.json`, `model/units.json`, `model/modules.json`

---

## 4. Config — config/config.json

Config supports `//` and `/* */` comments and trailing commas (`_strip_json_comments` + `_strip_trailing_commas` in `utils.py`). Local overrides via `config/config.local.json` (merged on top).

### Schema

```json
{
  "views": {
    "interfaceTables": true,
    "unitDiagrams": { "renderPng": true },
    "flowcharts": { "scriptPath": "fake_flowchart_generator.py", "renderPng": true },
    "behaviourDiagram": { "renderPng": true },
    "moduleStaticDiagram": { "enabled": true, "renderPng": true, "widthInches": 5.5 }
  },
  "clang": {
    "llvmLibPath": "C:\\Program Files\\LLVM\\bin\\libclang.dll",
    "clangIncludePath": "C:\\Program Files\\LLVM\\lib\\clang\\17\\include",
    "clangArgs": []
  },
  "llm": {
    "descriptions": false,
    "behaviourNames": false,
    "baseUrl": "http://localhost:11434",
    "defaultModel": "llama3.2",
    "timeoutSeconds": 60,
    "abbreviationsPath": "config/abbreviations.txt"
  },
  "modulesGroups": {
    "InterfaceTables": {
      "ItTypes":      ["InterfaceTables/Types"],
      "ItVisibility": ["InterfaceTables/Visibility"],
      "ItDirection":  ["InterfaceTables/Direction"]
    },
    "Flowcharts":      { "FcControl":    ["Flowcharts/ControlFlow"] },
    "BehaviourDiagram":{ "BdCross":      ["BehaviourDiagram/CrossModule"],
                         "BdPoly":       ["BehaviourDiagram/Polymorphism"] },
    "UnitDiagrams":    { "UdMath":       ["UnitDiagrams/BasicMath"],
                         "UdNested":     ["UnitDiagrams/Nested/Inner"],
                         "UdNamespaces": ["UnitDiagrams/Namespaces"] },
    "Diagnostics":     { "DiagParser":   ["Diagnostics/ParserEdge"] },
    "QuickSample":     { "QsCore":       ["QuickSample/Core"],
                         "QsUtils":      ["QuickSample/Utils"] }
  },
  "export": {
    "docxPath": "output/software_detailed_design_{group}.docx",
    "docxFontSize": 8
  }
}
```

### Key config rules

- Group names and module names: **CapitalCamelCase**
- Each folder path must appear **exactly once** across all groups
- `selectedGroup` was **intentionally removed** from config — selection is CLI-only
- `config.modules` top-level key is supported as an alternative to `modulesGroups`; if both exist, `modules` wins for module mapping. Currently only `modulesGroups` is used.
- LLM is **off by default** (`descriptions: false`, `behaviourNames: false`)

---

## 5. Model Schema (`model/`)

### model/functions.json

Keyed as: `module|unit|qualifiedName|paramTypes`

Example: `QsCore|Sample|MyClass::getValue|int`

| Field | Type | Description |
|---|---|---|
| `qualifiedName` | string | Full C++ qualified name (e.g. `MyClass::getValue`) |
| `location.file` | string | Relative path from project root |
| `location.line` | int | Declaration start line |
| `location.endLine` | int | Declaration end line |
| `params` | list | Raw list (before Phase 2 normalizes to `parameters`) |
| `parameters` | list | Normalized: `[{name, type}]` — set in Phase 2 |
| `returnType` | string | C++ return type string |
| `returnExpr` | string | First return expression token(s) captured by parser |
| `visibility` | string | `private`, `public`, `protected`, or `default` |
| `calledByIds` | list | Function IDs that call this function |
| `callsIds` | list | Function IDs this function calls |
| `readsGlobalIds` | list | Direct global var reads |
| `writesGlobalIds` | list | Direct global var writes |
| `readsGlobalIdsTransitive` | list | Transitive reads (Phase 2 propagation) |
| `writesGlobalIdsTransitive` | list | Transitive writes (Phase 2 propagation) |
| `direction` | string | `In` or `Out` (never empty after Phase 2) |
| `interfaceId` | string | `IF_<PROJECT>_<UNIT_CODE>_<INDEX>` — set in Phase 2 |
| `description` | string | LLM-generated description (optional) |
| `behaviourInputName` | string | Human label for input (static or LLM) |
| `behaviourOutputName` | string | Human label for output (static or LLM) |
| `syntheticFromVarDecl` | bool | True if recovered from misparsed VAR_DECL |
| `declarationOnly` | bool | True if only forward declaration, no body |

### model/globalVariables.json

Keyed as: `module|unit|qualifiedName`

| Field | Description |
|---|---|
| `qualifiedName` | Full C++ name |
| `location.file` | Relative path |
| `location.line` | Declaration line |
| `type` | C++ type string |
| `value` | Initializer value (if any) |
| `visibility` | `private`, `public`, `protected`, or `default` |
| `interfaceId` | Set in Phase 2 |
| `direction` | Always `In/Out` (set in Phase 2) |
| `description` | LLM-generated (optional) |

### model/units.json

Keyed as: `module|unitname`

| Field | Description |
|---|---|
| `name` | Unit name (filename without extension) |
| `path` | Relative path without extension |
| `fileName` | Filename with extension |
| `functionIds` | Ordered list of function IDs in this unit |
| `globalVariableIds` | Ordered list of global IDs in this unit |
| `callerUnits` | Unit keys that call into this unit |
| `calleesUnits` | Unit keys this unit calls into |

Only `.cpp`/`.cc`/`.cxx` files produce units.

### model/modules.json

Keyed by module name. Contains: `{ "units": [unit_key, ...] }`

### model/metadata.json

Fields: `basePath`, `projectName`, `generatedAt`, `version`

### model/dataDictionary.json

Contains entries for:
- `primitive` — all C/C++ primitive types with ranges
- `struct` / `class` — fields with types and ranges
- `enum` — enumerators with values
- `typedef` — underlying type and range
- `define` — `#define` macros with value and full text

Key format varies by kind:
- struct/enum/typedef: qualified name (or `typedef@qn:file:line` if duplicate)
- define: `NAME@rel_file:line_no`

---

## 6. Phase 1: Parser (`src/parser.py`)

### Initialization

- Reads `config/config.json` to get clang config
- Loads libclang from `config.clang.llvmLibPath`; uses `os.add_dll_directory()` on Windows (Python 3.8+)
- Builds `_MODULE_FOLDERS` from merged union of all `modulesGroups` entries
- Sets up `CLANG_ARGS`:
  - `-std=c++17`
  - `-I<MODULE_BASE_PATH>`
  - `-I<clangIncludePath>`
  - `-DPRIVATE=` `-DPROTECTED=` `-DPUBLIC=` `-D__OVLYINIT=` (macro visibility placeholders)
  - `-DVOID=void` (handles codebases using VOID as a macro)
  - Any extra args from `config.clang.clangArgs`

### Visibility detection (`_detect_visibility`)

Scans backwards up to 5 lines from the declaration line, looking for a line whose first token is `PRIVATE`, `PUBLIC`, or `PROTECTED`. Returns lowercase: `private`, `public`, `protected`, or `default`.

Used for both functions and global variables. Needed because visibility macros are often on the preceding line, e.g.:
```c
PRIVATE UNIT __OVLYINIT
_SomeFunction(GG *gg) { ... }
```

### File filtering (`is_project_file`)

Checks that:
1. File is under `MODULE_BASE_PATH` via `os.path.normcase` + `startswith` (**known risk**: see Section 10)
2. If `_MODULE_FOLDERS` is non-empty: file's relative path must start with one of the configured folder prefixes (case-insensitive after normcase)

### Three-pass parsing (`main`)

1. **`parse_file`** → `visit_definitions` + `visit_type_definitions` — collects function/global/type declarations
2. **`parse_calls`** → `visit_calls` — builds `call_graph` (caller→callees) and `reverse_call_graph` (callee→callers)  
3. **`parse_global_access`** → `visit_global_access` — tracks which globals each function reads/writes

### Function collection (`visit_definitions`)

- Handles `FUNCTION_DECL` and `CXX_METHOD` cursors
- Records both definitions (with body) and forward declarations (`declarationOnly: True`)
- Internal key: `get_function_key(cursor)` uses mangled name, or `qualified@file:line` fallback
- For each function: collects parameters via `get_arguments()`, records `endLine` from cursor extent
- Also handles `VAR_DECL` that should be reclassified as functions (see synthetic functions below)

### Synthetic function detection (`_var_decl_should_record_as_function_not_global`)

Clang sometimes emits `VAR_DECL` for `TYPE FuncName(id1)` when macros expand to nothing. Detected by:
1. Cursor is `VAR_DECL`
2. Source text contains `name(` pattern (not `=` sign)
3. All init args are `DECL_REF_EXPR` (identifier references, not literals)

When detected: stored in `functions` dict with `syntheticFromVarDecl: True` and reconstructed parameters from the `DECL_REF_EXPR` children.

### Global variable collection

Only global-scope variables (semantic parent is `TRANSLATION_UNIT` or `NAMESPACE`). Excludes class members. Initializer value extracted by scanning source line for `=` assignment.

### Call graph (`visit_calls`)

Traverses all `CALL_EXPR` nodes inside function definitions. Tries cursor.referenced first; falls back to name-match in known functions. Both `call_graph[caller]` → `{callees}` and `reverse_call_graph[callee]` → `{callers}` are built.

### Global access tracking (`visit_global_access`)

Tracks `DECL_REF_EXPR` to global `VAR_DECL` nodes. Distinguishes:
- Pure write (`=`): adds to `global_access_writes`
- Compound operator (`+=`, `-=`, etc): adds to both reads and writes
- `++`/`--` unary: adds to writes
- Read: adds to `global_access_reads`
- Also captures first `RETURN_STMT` token sequence as `returnExpr`

### Direction assignment (in `build_metadata`)

Based on direct global access per function:
- Only writes: `direction = "In"` (setter)
- Only reads: `direction = "Out"` (getter)
- Both or neither: `direction = "In"`

Phase 2 overrides to ensure always `"In"` or `"Out"` (never empty).

### Key generation (`build_metadata` + `utils.make_function_key`)

Final model key: `module|unit|qualifiedName|paramTypes`

Where:
- `module` = `get_module_name(file_path, base_path)` → `_resolve_module_from_rel(rel_path)` → matches against configured folder prefixes (case-insensitive)
- `unit` = filename without extension
- `qualifiedName` = full C++ qualified name including namespace/class
- `paramTypes` = comma-joined type strings from parameters

### Type collection (`visit_type_definitions`)

Collects into `data_dictionary`:
- `STRUCT_DECL` / `CLASS_DECL` with field list
- `ENUM_DECL` with enumerator values and computed range
- `TYPEDEF_DECL` with underlying type and range lookup
- `_maybe_add_typedef_for_struct`: when a struct is found inside `typedef struct { ... } Name;` pattern, adds a typedef entry too

### Define scanning (`_scan_defines`)

Scans all `.cpp`, `.h`, `.hpp` files for `#define` lines. Handles backslash-continuation. Stores: name, value, full macro text, location.

---

## 7. Phase 2: Model Deriver (`src/model_deriver.py`)

### `_build_units_modules`

Groups all functions and globals by their file path. Creates:
- `model/units.json` — one entry per `.cpp` file (`.h` files are excluded from unit keys)
- `model/modules.json` — one entry per module, listing its unit keys

For each unit: collects `functionIds` (sorted by source line), `globalVariableIds`, and derives `callerUnits`/`calleesUnits` by traversing `calledByIds`/`callsIds`.

### `_build_interface_index`

Assigns a per-file sequential index to every function and global. Used to build stable `interfaceId` codes.

### `_enrich_interfaces`

Assigns `interfaceId = IF_<PROJECTUPPER>_<UNITPATH_UPPER>_<INDEX>` to each function and global. Also normalizes `parameters` format (strips extra fields, keeps `name` and `type`).

### `_propagate_global_access`

Fixed-point propagation: for each function, unions in its callees' read/write sets. Stores results as `readsGlobalIdsTransitive` and `writesGlobalIdsTransitive`. Used for behaviour naming (sees what a "wrapper" function ultimately touches).

### `_enrich_behaviour_names` (static)

Populates `behaviourInputName` and `behaviourOutputName` from heuristics:

**Input Name priority:**
1. First parameter name → `_readable_label(name)` (strips `g_`, `s_`, `t_` prefixes; converts underscores to spaces)
2. First written global name
3. First read global name
4. Fallback: `"<FunctionBaseName> input"`

**Output Name priority:**
1. First token of `returnExpr` if it looks like an identifier
2. Last word of `returnType` if non-primitive
3. First written global name
4. First read global name
5. Fallback: `"<FunctionBaseName> result"`

### `_static_behaviour_name_is_poor`

Returns True if names end with ` input` or ` result` (generic fallback). Used to decide whether to call LLM for improvement.

### `_enrich_behaviour_names_llm`

If LLM is available and names are poor: calls `get_behaviour_names()` with source code, params, globals read/written, return type, return expr, draft input/output, and abbreviations. Only fires when `config.llm.behaviourNames: true`.

### `_enrich_from_llm`

Only when `config.llm.descriptions: true` and Ollama is available:
- `enrich_functions_with_descriptions` — processes functions bottom-up through call graph, so callees are described first and passed as context to callers
- `enrich_globals_with_descriptions` — one line of source per global; uses abbreviations

### Final cleanup

- Direction forced to `"In"` or `"Out"` for all functions (never empty)
- Globals get `direction = "In/Out"`
- `params` field removed (replaced by normalized `parameters`)
- Writes back `model/functions.json` and `model/globalVariables.json`

---

## 8. Phase 3: Views (`src/run_views.py` + `src/views/`)

### Orchestration

`run_views.py` parses `--output-dir` and `--selected-group` from argv. For a selected group:
1. Resolves group name case-insensitively
2. Adds `_analyzerSelectedGroup` and `_analyzerAllowedModules` to the config dict
3. `_analyzerAllowedModules` = sorted list of module names from that group's config entry

`run_views()` iterates `VIEW_REGISTRY` and calls each enabled view's `run(model, output_dir, model_dir, config)`.

**View enable logic**: `interfaceTables` is enabled by default (no config entry needed). All other views must be explicitly configured. Setting a view to `false` disables it.

### View: `interfaceTables` (`src/views/interface_tables.py`)

Generates `output/interface_tables.json`.

- Iterates only `.cpp` units
- Filters by `allowed_modules` when set
- Excludes `private` functions and globals
- For each function: builds caller/callee unit references and marks them as internal/external
- Internal = same module (or within `allowed_modules` when a group is selected)
- External caller/callee units formatted as `module/unit` strings
- Enriches parameters with range from data dictionary via `get_range()`
- Strips file extensions from location.file

### View: `unitDiagrams` (`src/views/unit_diagrams.py`)

Generates one Mermaid `.mmd` (and optionally `.png`) per unit into `output/unit_diagrams/`.

- Only `.cpp` units; filtered by `allowed_modules` when set
- Diagram structure: Left-to-right flowchart with external callers on left, internal module box (yellow) in center, external callees on right
- Edges labeled with `interfaceId` values (br-separated when multiple)
- Main unit: blue with thick border; internal peers: blue thin border; module box: yellow
- **Project root resolved from `model_dir` parent** (not from `output_dir`) — this avoids the broken path when running under `output/<group>/`
- PNG rendered by `mmdc` (mermaid-cli), 60s timeout per diagram

### View: `behaviourDiagram` (`src/views/behaviour_diagram.py`)

Generates behaviour diagrams for functions called by external units. Uses `FakeBehaviourGenerator`.

- Filters to `allowed_modules` when a group is selected
- Excludes `private` functions
- `FakeBehaviourGenerator.generate_all_diagrams(fid, out_dir)` creates one `.mmd` per external caller (functions whose module differs from the current function's module)
- Each `.mmd` has a fixed sample Mermaid diagram (placeholder for real implementation)
- Naming: `current_key__caller_key.mmd` (sanitized with `safe_filename`)
- External = different module (or outside `allowed_modules` when group is selected)
- Writes `output/behaviour_diagrams/_behaviour_pngs.json`: `{ "_docxRows": { module: { unit: [ {currentFunctionName, externalUnitFunction, pngPath} ] } } }`
- **Project root from `model_dir` parent** — same fix as unit_diagrams

### View: `flowcharts` (`src/views/flowcharts.py`)

Invokes `fake_flowchart_generator.py` subprocess to produce per-unit JSON flowcharts.

- When `allowed_modules` is set (group export): filters `model/functions.json` by `fid.split(KEY_SEP, 1)[0].lower() in allowed_modules` and writes the filtered subset to **`model/functions_<group>.json`** (persistent, not temp)
- Passes `model/functions_<group>.json` to the generator when filtering; otherwise passes full `model/functions.json`
- Generator writes one JSON per unit into `output/flowcharts/` (or `output/<group>/flowcharts/`)
- Each JSON is an array of `{name, flowchart}` (Mermaid string)
- Optionally renders each flowchart to PNG via `mmdc` (temp `.mmd` file per function, cleaned up after render)
- **Project root from `model_dir` parent** — same fix

**Current filtering implementation**: key-prefix based (`fid.split(KEY_SEP, 1)[0].lower()`), NOT units.json traversal. A better approach (traversing units.json → functionIds) was discussed but **not implemented** in the current code.

### `fake_flowchart_generator.py`

- Groups functions by unit (first two segments of fid: `module|unit`)
- For each function: produces a fixed sample Mermaid diagram (`SAMPLE_FLOWCHART`)
- Writes one JSON file per unit: `{unit_name}.json` containing array of `{name, flowchart}`
- Output unit file name = last segment of unit_key (e.g. `Sample.json` not `QsCore_Sample.json`)

### `fake_behaviour_diagram_generator.py` — `FakeBehaviourGenerator`

- Takes paths to `modules.json`, `units.json`, `functions.json` at init
- `generate_all_diagrams(function_key, output_dir)` → for each external caller in `calledByIds` (different module): writes one `.mmd` with `SAMPLE_MERMAID`
- Returns list of created `.mmd` paths (empty if no external callers)

---

## 9. Phase 4: DOCX Exporter (`src/docx_exporter.py`)

### Entry: `export_docx(json_path, docx_path, selected_group)`

- `json_path` defaults to `output/interface_tables.json`
- `artifacts_dir = os.path.dirname(json_path)` — **all PNGs, flowcharts, unit_diagrams resolved relative to this dir** (critical fix for grouped output)
- Loads `model/functions.json`, `globalVariables.json`, `units.json`, `dataDictionary.json`
- Loads abbreviations from `config.llm.abbreviationsPath`
- Groups data by module → iterates sorted modules

### CLI (`main`)

```
python src/docx_exporter.py [json_path] [docx_path] [--selected-group <name>]
```
`--selected-group` is stripped before positional arg parsing.

### DOCX structure

```
Software Detailed Design (H0)
1 Introduction
  1.1 Purpose
  1.2 Scope
  1.3 Terms, Abbreviations and Definitions
2 <ModuleName>
  2.1 Static Design
    [Module static structure diagram: PNG or Mermaid text]
    [Component/Unit table: Component | Unit | Description | Note]
    2.1.1 <UnitName>
      [Unit diagram PNG if available]
      2.1.1.1 unit header
        Path: ...
        [Unit header table: global variables/typedef/enum/define | information]
      2.1.1.2 unit interface
        [Interface table: 8 columns]
      2.1.1.3 <UnitName>-<InterfaceId>
        [Flowchart table or description paragraph]
      ... (one sub-section per interface)
  2.2 Dynamic Behaviour
    2.2.1 <UnitName> - <FunctionName> (<ExternalUnitFunc>)
      [Behaviour description table]
      [Behaviour PNG]
N Code Metrics, Coding Rule, Test Coverage
Appendix A. Design Guideline
```

### Module static structure diagram

Mermaid TB flowchart: dark module box → blue unit boxes. Rendered by `mmdc` to PNG placed in `artifacts_dir/module_static_diagrams/<module>.png`.

### Component/Unit table (`_add_component_unit_table`)

4 columns: Component | Unit | Description | Note

Description derivation:
1. If LLM is available: `get_unit_description(unit_name, fn_items, gv_items, config, abbreviations)` — unit summary from its function and global descriptions
2. Fallback: join all descriptions, truncate to 120 chars
3. Final result truncated to **140 chars max** (hardcoded)
4. Note column: always `N/A`

Component column merged vertically across all unit rows.

### Unit header table (`_build_unit_header_table`)

2 columns: `global variables / typedef / enum / define` | `information`

Rows from:
- **Globals** (from `globalVariables.json`) — private globals excluded; declaration read from source; value from `initializer`
- **Typedefs** (from `dataDictionary`) — declaration snippet from source; info = enum values if typedef-to-enum, struct description if typedef-to-struct, else NA
- **Enums** — declaration snippet; info = `NAME=value, ...`
- **Defines** — stored text (full macro); info = value

Struct/class entries in dataDictionary are NOT directly shown (only typedef → struct pattern). Deduplicates by declaration text, preferring richer `name=value` info.

### Interface table (`_add_interface_table`)

8 columns: Interface ID | Interface Name | Information | Data Type | Data Range | Direction(In/Out) | Source/Destination | Interface Type

- For functions: Data Type = `; `.join of parameter types, Data Range = `; `.join of parameter ranges
- For globals: Data Type = variable type, Data Range = looked up from data dictionary
- Private functions/globals excluded (already filtered in Phase 3)

### Flowchart table per interface (`_add_flowchart_table`)

5-row table: Requirements | Risk | Capacity(Density) | Input Name | Output Name

Requirements cell contains:
1. Function description (or function name as fallback)
2. Own flowchart (PNG if available, else Mermaid text) labeled with signature `returnType functionName(params)`
3. Each **private callee's** flowchart labeled with its signature (deduplicated per unit via `rendered_private_fids`)

Input Name / Output Name from `behaviourInputName` / `behaviourOutputName` in `functions.json`.

Risk = "Medium" (hardcoded), Capacity(Density) = "Common" (hardcoded).

### Dynamic Behaviour section

Reads `artifacts_dir/behaviour_diagrams/_behaviour_pngs.json`. For each entry:
- Creates subheading: `<sec>.2.<idx> <unitName> - <functionName> (<externalUnitFunction>)`
- Adds behaviour description table (`_add_behavior_description_table`) with behaviourInputName/behaviourOutputName from model
- Embeds PNG if available

---

## 10. utils.py — Key Helpers

### Key functions

| Function | Purpose |
|---|---|
| `KEY_SEP = "\|"` | Separator for all model keys |
| `make_function_key(module, rel_file, full_name, parameters)` | Build `module\|unit\|qualifiedName\|paramTypes` |
| `make_global_key(rel_file, full_name)` | Build `module\|unit\|qualifiedName` |
| `make_unit_key(rel_file)` | Build `module\|unitname` |
| `get_module_name(file_path, base_path)` | Absolute path → module name via `_resolve_module_from_rel` |
| `_resolve_module_from_rel(rel_file)` | Match relative path against `_MODULE_OVERRIDES` (case-insensitive via `.lower()`) |
| `init_module_mapping(config)` | Build `_MODULE_OVERRIDES` from config; merges all `modulesGroups` entries if no top-level `modules` |
| `path_is_under(base, candidate)` | Safe path containment using `os.path.relpath` (not `startswith`) |
| `mmdc_path(project_root)` | Local `node_modules/.bin/mmdc` or system `mmdc` |
| `safe_filename(s)` | Replace unsafe chars (including `,`, `&`, `;`) with `_` |
| `load_config(project_root)` | Loads `config/config.json` + `config.local.json`, merges |
| `get_range(type_str, data_dictionary)` | Look up range for a type; falls back through typedefs, then to `get_range_for_type` |
| `_strip_json_comments` | Remove `//` and `/* */` from JSON text |
| `_strip_trailing_commas` | Remove trailing commas before `}` or `]` |

### Module resolution behavior

1. `init_module_mapping` is called **at import time** with the on-disk config (default init)
2. `parser.py` also calls its own merge logic at startup — separate from `utils.py` init
3. Both use the same algorithm: merge all `modulesGroups` entries if no top-level `modules`
4. Path matching: always lowercased on both sides — safe on Windows (where `normcase` lowercases anyway)

---

## 11. llm_client.py — LLM Integration

All LLM calls use Ollama HTTP API (`POST /api/generate`). Optional dependency on `requests` library.

### `_ollama_available(config)`

Checks `GET <baseUrl>/api/tags` with 3s timeout. Returns False if `requests` not installed.

### Functions

| Function | Purpose |
|---|---|
| `load_abbreviations(project_root, config)` | Load `key: value` / `key=value` lines from `config.llm.abbreviationsPath` file |
| `extract_source(base_path, loc)` | Read function body using `line` and `endLine` from location |
| `extract_source_line(base_path, loc)` | Read single line (for globals) |
| `get_description(source, config, callee_descriptions, abbreviations)` | One-line function description. Callee descriptions passed as context |
| `get_global_description(source, config, abbreviations)` | One-line global variable description. **Abbreviations are included** |
| `get_unit_description(unit_name, fn_items, gv_items, config, abbreviations)` | Unit summary (≤25 words) from function + global descriptions |
| `get_struct_description(struct_name, fields, config, abbreviations)` | One-line struct description using name AND fields |
| `get_behaviour_names(source, params, globals_read, globals_written, return_type, return_expr, draft_input, draft_output, config, abbreviations)` | Returns `{behaviourInputName, behaviourOutputName}` |
| `enrich_functions_with_descriptions(functions_data, base_path, config)` | Process all functions; bottom-up (callees first) |
| `enrich_globals_with_descriptions(globals_data, base_path, config)` | Process all globals; sequential |

### Abbreviations usage

Abbreviations are now passed into **all** LLM calls:
- `get_description` — for function descriptions
- `get_global_description` — for global descriptions
- `get_unit_description` — for unit summaries
- `get_struct_description` — for struct descriptions
- `get_behaviour_names` — for behaviour input/output naming

### Processing order for functions

`_enrich_functions_loop` processes functions in topological order (callees before callers) so each function's callee descriptions are available as context. Falls back to arbitrary order if cycle detected.

---

## 12. Visibility Filtering Rules

| Context | Private functions | Private globals |
|---|---|---|
| `interfaceTables` view | Excluded | Excluded |
| `behaviourDiagram` view | Excluded | — |
| DOCX unit header table | — | Excluded |
| Flowcharts / `fake_flowchart_generator` | **Included** | **Included** |
| DOCX flowchart section | Own chart included; private callee charts shown below (dedup per unit) | — |

---

## 13. Known Risks / Technical Debt

### Risk 1: `is_project_file()` uses `startswith` for path containment

```python
# parser.py line ~172
abs_path = os.path.normcase(os.path.abspath(file_path))
abs_base = os.path.normcase(os.path.abspath(MODULE_BASE_PATH))
if not abs_path.startswith(abs_base):
    return False
```

This can give false positives: `C:\foo` would match `C:\foobar`. The correct helper `path_is_under()` exists in `utils.py` and uses `os.path.relpath`, but `parser.py` does not use it in `is_project_file()`. Should be fixed to use `path_is_under()`.

### Risk 2: Flowchart filtering uses module prefix, not units.json

Current: `fid.split(KEY_SEP, 1)[0].lower() in allowed_modules`

Better approach (traversing units.json → functionIds for the selected group) was discussed but never implemented. Module-prefix filtering can include stray functions that have the correct module prefix but aren't in the selected group's configured folders.

### Risk 3: `make_function_key` module fallback

If `module` is empty string, it falls back to `parts[0]` (first path segment) instead of a config-resolved module. This should only happen if `get_module_name` returns `""`, which is currently impossible but could regress if the function is changed.

---

## 14. Test Fixture Project (`test_cpp_project/`)

### Folder structure

```
test_cpp_project/
  InterfaceTables/
    Types/        → Types.h/cpp (enums), PointRect.h/cpp (structs/unions)
    Visibility/   → AccessVisibility.h/cpp (all 3 visibility macros, getter/setter patterns)
    Direction/    → ReadWrite.h/cpp (In/Out direction from global reads/writes)
  Flowcharts/
    ControlFlow/  → Flowcharts.h/cpp (~20 patterns: if/else, loops, switch, nested)
  BehaviourDiagram/
    CrossModule/  → Hub.h/cpp (hub with 5+ module fan-out)
    Polymorphism/ → Dispatch.h/cpp (virtual dispatch, abstract classes, callbacks)
  UnitDiagrams/
    BasicMath/    → Utils.h/cpp (simple functions, internal call chain)
    Nested/Inner/ → Helper.h/cpp (nested directory path resolution)
    Namespaces/   → Advanced.h/cpp (Vehicle namespace, overloading, default params)
  Diagnostics/
    ParserEdge/   → 6 .cpp files (syntheticFromVarDecl, forward decls, preprocessor splits)
  QuickSample/
    Core/         → Sample.h/cpp (~10 functions: types, visibility, direction, flowcharts)
    Utils/        → SampleUtils.h/cpp (cross-module target for behaviour diagram arcs)
```

### Quick run commands

```bash
# Fastest — all views, ~10 functions, all scenarios
python run.py --clean test_cpp_project --selected-group QuickSample

# By view type
python run.py --clean test_cpp_project --selected-group InterfaceTables
python run.py --clean test_cpp_project --selected-group Flowcharts
python run.py --clean test_cpp_project --selected-group BehaviourDiagram
python run.py --clean test_cpp_project --selected-group UnitDiagrams

# Everything
python run.py --clean test_cpp_project

# Reuse model, re-export one group
python run.py --use-model test_cpp_project --selected-group QuickSample
```

---

## 15. Key Design Decisions

### `PRIVATE` / `PUBLIC` / `PROTECTED` macros

Passed to Clang as `-DPRIVATE=` etc. so they expand to nothing. **Not** defined in source files. Parser recovers them by scanning raw source text (`_detect_visibility`).

### `selectedGroup` removed from config

Was removed intentionally to simplify code. Group selection is CLI-only (`--selected-group`). There is no env-based override either (was added then removed for same reason: preference for simplicity).

### Model always built for all groups

The parser builds the model for the **union of all configured module folders**, regardless of `--selected-group`. The group filter only affects Phase 3 (views) and Phase 4 (DOCX). This ensures cross-module call edges are available even when exporting a single group.

### Artefact path resolution in exporter

All diagram paths are resolved relative to `artifacts_dir = os.path.dirname(json_path)`. This ensures grouped outputs (`output/<group>/`) work correctly. Deriving root from `output_dir` was the original bug that broke PNG embedding in grouped exports.

### Project root in views derived from `model_dir`

All three diagram views (`unit_diagrams`, `behaviour_diagram`, `flowcharts`) compute:
```python
project_root = os.path.dirname(os.path.abspath(model_dir))
```
This is stable regardless of `output_dir` value.

### Case-insensitive path matching (Windows safety)

`_resolve_module_from_rel` lowercases both the configured folder prefix and the relative file path before comparison. This is essential on Windows where `normcase` lowercases paths.

---

## 16. Important Lessons Learned (Past Mistakes)

### Shell: Windows uses `cmd.exe` / PowerShell, not bash

On this machine, `&&` chaining in shell commands does not work in PowerShell. Use `;` for sequential commands.

### run.py arg parsing bug (fixed)

An intermediate version stripped `--selected-group` from argv but left its value (`core`) as a positional, making it the project path. Fix: parse all flags explicitly in a loop, only treat truly unrecognized non-`-` tokens as positional.

### Broken grouped output paths (fixed in two places)

**Root cause**: `output_dir` was used to infer the repo root. When group output goes to `output/<group>/`, `dirname(output_dir) = output/`, not the repo root.
**Fix 1**: Views use `os.path.dirname(os.path.abspath(model_dir))` for project root.
**Fix 2**: Exporter uses `os.path.dirname(json_path)` as artifacts dir.

### Flowchart filtering implementation mismatch

Discussed traversing `units.json → functionIds` for building `functions_<group>.json`. Code in `flowcharts.py` still uses module-prefix filtering. Always re-read source after edits to confirm the implementation matches the discussion.

### Config switching confusion

Earlier docs reference group names `core`, `support`, `tests`. Current config has `InterfaceTables`, `Flowcharts`, etc. When validating CLI behavior, always confirm which config is active.

### `--all-groups` flag removed

Was present in an intermediate version. Removed because it was redundant (all-groups is now the default behavior when `modulesGroups` is configured and no `--selected-group` is passed).

### Env-based group override removed

An `os.environ`-based selected-group override was added then removed. Preference in this codebase: minimal optional code paths, explicit CLI-only control.

---

## 17. Current Valid Example Commands

```bash
# Full run, all groups
python run.py test_cpp_project

# Full run, clean + one group (output to output/, not output/<group>/)
python run.py --clean test_cpp_project --selected-group QuickSample

# Reuse model, regenerate views + docx for one group
python run.py --use-model test_cpp_project --selected-group Flowcharts

# INVALID — 'core' is not a valid group name in current config
python run.py test_cpp_project --selected-group core
```

---

## 18. Test Framework

### Directory structure

```
tests/
├── conftest.py                        — shared session fixture (run_pipeline), JSON fixtures
├── pytest.ini                         — testpaths = tests, -v --tb=short
├── integration/                       — pipeline runs once, check intermediate JSON artifacts
│   └── test_interface_tables.py       — ACTIVE: output/interface_tables.json assertions + snapshot
├── e2e/                               — pipeline runs once, check the final DOCX
│   └── test_docx.py                   — ACTIVE: opens DOCX with python-docx, asserts tables/images/headings
└── snapshots/
    └── Sample/
        └── interface_tables.json      — golden snapshot (committed); regenerate with --update-snapshots
```

**When to add files:**
- New view ready to test → add `tests/integration/test_<view>.py`
- New snapshot needed → run once with `--update-snapshots`, review `git diff tests/snapshots/`, commit
- Pure Python utility tests (no pipeline) → add `tests/unit/` dir + `test_*.py`

### Test fixture project for automated tests

All automated tests run against the **`SampleCppProject`** fixture (not `test_cpp_project`).
`conftest.py` runs: `python run.py SampleCppProject --clean --selected-group Sample`

```
SampleCppProject/Sample/
  Core/   — Core.h/cpp   (public: coreAdd, coreCompute, coreLoopSum, coreCheck, coreSumPoint,
                           coreSetResult, coreProcess, coreOrchestrate, coreSetMode, coreGetCount
                           private: coreHelper, coreSwitch
                           public global: g_result  private global: g_count)
  Lib/    — Lib.h/cpp    (public: libAdd, libNormalize  private: libClamp)
  Util/   — Util.h/cpp   (public: utilCompute, utilScale  private: utilClip
                           public global: g_utilBase)
```

### Run commands

```bash
# All tests (pipeline runs once automatically)
python -m pytest tests/ -v

# Skip pipeline rerun — test against existing output/
python -m pytest tests/ -v --skip-pipeline

# Interface tables only
python -m pytest tests/integration/test_interface_tables.py -v

# DOCX only
python -m pytest tests/e2e/test_docx.py -v

# Regenerate golden snapshot after intentional pipeline change
python -m pytest tests/integration/test_interface_tables.py --update-snapshots --skip-pipeline
# then: git diff tests/snapshots/  → review → git commit
```

### conftest.py fixtures

| Fixture | Scope | What it provides |
|---|---|---|
| `run_pipeline` | session, autouse | Runs pipeline once; skipped if `--skip-pipeline` |
| `interface_tables` | session | Full `output/interface_tables.json` as dict |
| `core_entries` | session | `interface_tables["Core|Core"]["entries"]` |
| `lib_entries` | session | `interface_tables["Lib|Lib"]["entries"]` |
| `util_entries` | session | `interface_tables["Util|Util"]["entries"]` |
| `all_entries` | session | `core_entries + lib_entries + util_entries` |
| `update_snapshots` | session | True if `--update-snapshots` passed |
| `assert_snapshot` | function | Compares or regenerates a golden JSON snapshot |

### What test_interface_tables.py checks (integration, 51 tests total)

Parametrized where applicable — adding a new unit or function only requires updating the data, not new test functions.

- Structure: `unitNames` present; Core, Lib, Util units all exist and have entries
- Required fields: every entry (`all_entries`) has `interfaceId`, `type`, `name`, `unitKey`, `unitName`, `direction`; functions also have `functionId`
- Filtering: `coreHelper`, `coreSwitch`, `libClamp`, `utilClip`, `g_count` absent (PRIVATE)
- Direction (parametrized): `coreGetCount` → Out, `coreSetResult` → In, `utilCompute` → Out
- Direction validity: all functions only In or Out; all globals → In/Out
- IDs: every `interfaceId` starts with `IF_`
- Public functions (parametrized per unit): all 10 Core, 2 Lib, 2 Util
- Public globals (parametrized): `g_result` (Core), `g_utilBase` (Util)
- Snapshot: full JSON matches `tests/snapshots/Sample/interface_tables.json`

### What test_docx.py checks (e2e, 51 tests total)

Column map (`COLS` in `docx_exporter.py`):
`0=Interface ID, 1=Interface Name, 2=Information, 3=Data Type, 4=Data Range, 5=Direction(In/Out), 6=Source/Destination, 7=Interface Type`

- File exists and is non-empty
- Interface tables present (header row col-0 = "Interface ID")
- Every data row col-0 starts with `IF_`
- Private names (`coreHelper`, `coreSwitch`, `libClamp`, `utilClip`, `g_count`) absent from all cells
- Public names (parametrized, 16 cases): all 10 Core, 2 Lib, 2 Util functions + `g_result`, `g_utilBase`
- Direction (parametrized): `coreGetCount` col-5 = "Out", `coreSetResult` col-5 = "In", `g_result` col-5 = "In/Out"
- Interface Type values only "Function" or "Global Variable"
- At least one embedded image (`doc.inline_shapes`)
- Headings (parametrized): "Dynamic Behaviour" and "Static" present

---

## 19. Dependencies

```
libclang (LLVM 17)        — C++ AST parsing (via Python clang bindings)
python-docx               — DOCX generation
requests (optional)       — Ollama LLM API calls
mermaid-cli (mmdc)        — Mermaid → PNG rendering (npm install @mermaid-js/mermaid-cli)
```

Requirements file: `requirements.txt` (Python packages)  
Node.js: `package.json` for mmdc (local install in `node_modules/`)
