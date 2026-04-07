# C++ Codebase Analyzer — Project Context

## What it is
A Python tool that parses C++ source code using libclang and generates a Software Detailed Design document (DOCX).
CLI: `python run.py <project_path> [flags]`

## 4-Phase Pipeline
| Phase | Script | Role |
|---|---|---|
| 1 | `src/parser.py` | C++ source → `model/` JSON via libclang |
| 2 | `src/model_deriver.py` | Enrich model (direction, call graph, units/modules) |
| 3 | `src/run_views.py` | `model/` → `output/` JSON views |
| 4 | `src/docx_exporter.py` | `output/` → `software_detailed_design_{group}.docx` |

When discussing model changes, always check all 4 phases — a field added in Phase 1 may need to flow through Phase 2/3/4.

## CLI Flags
```bash
python run.py <project> --clean                    # wipe model/ and output/ before run
python run.py <project> --use-model                # skip Phase 1+2, reuse existing model/
python run.py <project> --selected-group <name>    # run only one module group
```

## Model Schema (model/)
- `functions.json` — keyed as `module|unit|qualifiedName|param_types`
  - Fields: `qualifiedName`, `location`, `params`, `returnType`, `returnExpr`, `calledByIds`, `callsIds`, `readsGlobalIds`, `writesGlobalIds`, `direction` (In/Out), `visibility` (private/public/protected/default), `syntheticFromVarDecl`, `declarationOnly`
- `globalVariables.json` — Fields: `qualifiedName`, `location`, `type`, `value`, `visibility`
- `metadata.json` — `basePath`, `projectName`, `generatedAt`, `version`
- `modules.json`, `units.json` — derived in Phase 2

## Config (config/config.json)
No inline comments. Key sections: `clang`, `llm`, `views`, `modulesGroups`, `export`.
Local overrides: `config/config.local.json` (not committed).

### modulesGroups rules
- Group names and module names: **CapitalCamelCase**
- Each folder path must appear **exactly once** across all groups (no duplication)
- Each group generates its own DOCX: `output/software_detailed_design_{group}.docx`

```json
"modulesGroups": {
  "GroupName": {
    "ModuleName": ["path/to/folder"]
  }
}
```

## Key Design Decisions

### PRIVATE / PUBLIC / PROTECTED
Codebase-specific macros, not C++ keywords. Supplied as `-DPRIVATE= -DPUBLIC= -DPROTECTED=` Clang args — **no need to `#define` them in source files**.
Visibility is recovered by `_detect_visibility()` in `parser.py`, which scans raw source text up to 5 lines back from the declaration line.

### Visibility filtering by view
| View | Private functions | Private globals |
|---|---|---|
| interfaceTables | excluded | excluded |
| behaviourDiagram | excluded | — |
| DOCX unit header | — | excluded |
| flowcharts / unitDiagrams | included | included |
| DOCX flowchart | own chart + private callee charts (deduplicated via `rendered_private_fids`) | — |

### Module name resolution (utils.py)
`_resolve_module_from_rel()` matches file paths against config folder entries.
All comparisons are **case-insensitive** — `os.path.normcase` lowercases paths on Windows, so both sides are lowercased before `startswith`. Bug to watch: if this is ever changed, Windows will silently return `"unknown"` for all modules.

### syntheticFromVarDecl
Clang sometimes misparses `TYPE FuncName(arg1)` as a VAR_DECL when macros expand to nothing. Parser detects and reclassifies these as functions.

### direction field
- `Out` = function only reads globals (getter pattern)
- `In` = function writes globals or accesses no globals

## Test Fixture Project (test_cpp_project/)
Planned rename: **`CppFixtures/`** — designed as input for a future test framework.

### Folder structure (view-based, CapitalCamelCase)
```
test_cpp_project/
  InterfaceTables/
    Types/        → enums (Types.h/cpp), structs/unions (PointRect.h/cpp)
    Visibility/   → all 3 visibility macros, getter/setter patterns (AccessVisibility.h/cpp)
    Direction/    → In/Out direction inference from global reads/writes (ReadWrite.h/cpp)
  Flowcharts/
    ControlFlow/  → 20 control-flow patterns: if/else, loops, switch, nested (Flowcharts.h/cpp)
  BehaviourDiagram/
    CrossModule/  → hub with 5+ module fan-out (Hub.h/cpp)
    Polymorphism/ → virtual dispatch, abstract classes, callbacks (Dispatch.h/cpp)
  UnitDiagrams/
    BasicMath/    → simple functions, internal call chain (Utils.h/cpp)
    Nested/Inner/ → nested directory path resolution (Helper.h/cpp)
    Namespaces/   → Vehicle namespace, overloading, default params (Advanced.h/cpp)
  Diagnostics/
    ParserEdge/   → syntheticFromVarDecl, forward decls, preprocessor splits (6 .cpp files)
  QuickSample/    → fastest group: all views, all scenarios, ~10 functions
    Core/         → Sample.h/cpp (10 functions: types, visibility, direction, flowcharts)
    Utils/        → SampleUtils.h/cpp (cross-module target for behaviour diagram arcs)
```

### Config groups
```
InterfaceTables → ItTypes, ItVisibility, ItDirection
Flowcharts      → FcControl
BehaviourDiagram→ BdCross, BdPoly
UnitDiagrams    → UdMath, UdNested, UdNamespaces
Diagnostics     → DiagParser
QuickSample     → QsCore, QsUtils
```

### Quick run commands
```bash
# Fastest — all views, ~10 functions
python run.py --clean test_cpp_project --selected-group QuickSample

# By view type
python run.py --clean test_cpp_project --selected-group InterfaceTables
python run.py --clean test_cpp_project --selected-group Flowcharts
python run.py --clean test_cpp_project --selected-group BehaviourDiagram
python run.py --clean test_cpp_project --selected-group UnitDiagrams

# Everything
python run.py --clean test_cpp_project
```

## LLM Integration
`src/llm_client.py` — optional Ollama-backed descriptions for functions and behaviour names.
Configured via `config.llm` (`descriptions`, `behaviourNames`, `baseUrl`, `defaultModel`). Off by default.
