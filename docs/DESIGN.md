# Design

> See also: [README](../README.md) | [software_detailed_design.json](software_detailed_design.json) (output doc structure)

## Architecture

Parse C++ → model (single source of truth) → views → software_detailed_design.docx.

The **Flowchart Engine** is embedded inside the analyzer at `src/flowchart/` and runs as
Phase 3's flowchart view. It reads the model files produced by Phases 1–2 and generates
real Control Flow Graph (CFG) Mermaid diagrams for every function.

```
run.py
  │
  ├─ Phase 1: src/parser.py
  │    libclang AST → model/functions.json (+ comment field)
  │                 → model/globalVariables.json
  │                 → model/dataDictionary.json (+ comment fields on types)
  │                 → model/metadata.json
  │
  ├─ Phase 2: src/model_deriver.py  [--llm-summarize ON by default]
  │    Standard enrichment:
  │      → model/units.json, model/modules.json
  │      → interfaceIds, direction, behaviourNames, LLM descriptions
  │    LLM summarization (skipped only with --no-llm-summarize):
  │      → model/functions.json  += phases[]
  │      → model/summaries.json  (file/module/project hierarchy summaries)
  │    Always:
  │      → model/knowledge_base.json  (rich context for Flowchart Engine)
  │
  ├─ Phase 3: src/run_views.py
  │    ├─ flowcharts view → src/flowchart/flowchart_engine.py (subprocess)
  │    │    reads: functions.json + metadata.json + knowledge_base.json
  │    │    CFG build (libclang, statement-level) + LLM labeling
  │    │    writes: output/flowcharts/{unit}.json  (Mermaid strings)
  │    ├─ unitDiagrams, behaviourDiagram, moduleStaticDiagram, interfaceTables
  │    └─ renderPng (mmdc) for each enabled view
  │
  └─ Phase 4: src/docx_exporter.py
       reads: output/  → software_detailed_design.docx
```

| Component | Role | Key inputs → outputs |
|-----------|------|----------------------|
| **run.py** | Orchestrator | Invokes Phase 1 → 2 → 3 → 4 |
| **parser.py** | Phase 1: C++ parse | C++ source → model JSON files |
| **model_deriver.py** | Phase 2: Model enrichment + knowledge base | Model → enriched model + knowledge_base.json |
| **run_views.py** | Phase 3: Views | Model → output/ |
| **flowchart_engine.py** | Phase 3 sub-process: CFG flowcharts | functions.json + knowledge_base.json → output/flowcharts/ |
| **docx_exporter.py** | Phase 4: DOCX export | output/ → .docx |

---

## Config ([config/config.json](../config/config.json))

| Key | Default | Description |
|-----|---------|-------------|
| `views.flowcharts.scriptPath` | `src/flowchart/flowchart_engine.py` | Path to flowchart engine |
| `views.flowcharts.renderPng` | `true` | Render flowchart Mermaid → PNG via mmdc |
| `views.unitDiagrams.renderPng` | `true` | Render unit diagrams to PNG |
| `views.behaviourDiagram.renderPng` | `true` | Render behaviour diagrams to PNG |
| `views.moduleStaticDiagram.enabled` | `true` | Generate module static diagrams |
| `views.moduleStaticDiagram.renderPng` | `true` | Render module diagrams to PNG |
| `clang.llvmLibPath` | — | Path to libclang.dll / libclang.so |
| `clang.clangIncludePath` | — | Path to clang system headers |
| `clang.clangArgs` | `[]` | Extra clang arguments (e.g. `-I/path`) |
| `llm.baseUrl` | `http://localhost:11434` | Ollama base URL |
| `llm.defaultModel` | `qwen2.5-coder:14b` | LLM model for all calls |
| `llm.numCtx` | `8192` | Ollama context window tokens |
| `llm.timeoutSeconds` | `120` | HTTP timeout per LLM call |
| `llm.descriptions` | `true` | Enable LLM function descriptions |
| `llm.behaviourNames` | `true` | Enable LLM behaviour Input/Output name polish |
| `llm.abbreviationsPath` | `config/abbreviations.txt` | Domain abbreviation expansions |
| `export.docxPath` | `output/software_detailed_design_{group}.docx` | Output path |
| `export.docxFontSize` | `8` | Font size in the DOCX |

Override any key without modifying `config.json` by creating `config.local.json` in the
same folder — it is merged on top at runtime.

---

## CLI Reference

### run.py

```
python run.py [options] <project_path>

Options:
  --clean              Delete output/ and model/ before running
  --all-groups         Run the full pipeline once per modulesGroup defined in config
  --no-llm-summarize   Skip LLM phase/hierarchy summarization (faster, lower quality)
  --from-phase N       Resume from phase N (1=Parse, 2=Derive, 3=Views, 4=Export)
```

**`--no-llm-summarize`** — LLM summarization is **on by default**. It generates function
phase breakdowns and file/module/project hierarchy summaries that the Flowchart Engine
uses for richer node labels. Pass `--no-llm-summarize` to skip this for faster runs
when label quality is less important.

**`--from-phase N`** — Useful after a crash. If Phase 3 failed but `model/` is intact,
restart without redoing Phases 1 and 2 (which include LLM calls):

```bash
python run.py --from-phase 3 test_cpp_project   # re-run views only
python run.py --from-phase 4 test_cpp_project   # re-export DOCX only
```

Alternatively, run `python src/run_views.py` directly to re-run Phase 3 standalone.

---

## Model Format

All model files live in `model/`. Keys use `|` (KEY_SEP) as separator. Paths use `/`.

### metadata.json
```json
{
  "basePath":      "absolute/path/to/project",
  "projectName":   "project_name",
  "generatedAt":   "ISO8601",
  "version":       1
}
```

### functions.json
**Key format:** `module|unitname|qualifiedName|paramTypes`
(e.g. `app|main|calculate|`, `math|utils|add|int,int`)

| Field | Type | Description |
|-------|------|-------------|
| `qualifiedName` | string | C++ full/scoped name |
| `location` | object | `file`, `line`, `endLine` |
| `comment` | string | Preceding source comment (empty if none) |
| `calledByIds` | string[] | Function IDs that call this |
| `callsIds` | string[] | Function IDs this calls |
| `interfaceId` | string | `IF_project_unit_index` |
| `parameters` | array | `{name, type}` per parameter |
| `returnType` | string | C++ return type |
| `direction` | string | `In` or `Out` |
| `description` | string | LLM-generated description (if no source comment) |
| `phases` | array | LLM phase breakdown — `{start_line, end_line, description}` per phase |

**`phases`** is populated by Phase 2 when `--llm-summarize` is active (the default). Each
entry divides the function body into a logical section so the Flowchart Engine can inject
the right phase description into each node's LLM prompt.

### globalVariables.json
**Key format:** `module|unitname|qualifiedName`

| Field | Type | Description |
|-------|------|-------------|
| `qualifiedName` | string | Variable full name |
| `location` | object | `file`, `line` |
| `type` | string | C++ type |
| `interfaceId` | string | `IF_project_unit_index` |
| `direction` | string | `In/Out` |

### units.json
**Key format:** `module|unitname`

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Display name |
| `path` | string \| string[] | Path(s) without extension |
| `fileName` | string | Basename of source file |
| `functionIds` | string[] | Function IDs in this unit |
| `globalVariableIds` | string[] | Global variable IDs in this unit |
| `callerUnits` | string[] | Units that call into this unit |
| `calleesUnits` | string[] | Units this unit calls into |

### modules.json
**Key format:** module name (first path segment, e.g. `app`, `math`)

| Field | Type | Description |
|-------|------|-------------|
| `units` | string[] | Unit keys belonging to this module |

### dataDictionary.json
Keyed by type name or qualified name. Contains structs, classes, enums, typedefs, macros,
and primitives. All type entries now carry a `comment` field with the preceding source
comment (if present), and struct fields / enum constants carry an inline `comment`.

| Field | Type | Description |
|-------|------|-------------|
| `kind` | string | `struct`, `class`, `enum`, `typedef`, `define`, `primitive` |
| `name` | string | Type name |
| `qualifiedName` | string | Fully qualified name |
| `comment` | string | Source-level doc comment |
| `range` | string | Value range (e.g. `0-0xFF`, `NA`) |
| `fields` | array | (struct/class) `{name, type, comment}` per member |
| `enumerators` | array | (enum) `{name, value, comment}` per constant |
| `underlyingType` | string | (typedef) underlying type |
| `value` | string | (define) macro expansion |

### knowledge_base.json  *(generated by Phase 2)*
Rich semantic context consumed by the Flowchart Engine. It is always generated; content
is richer when `--llm-summarize` is active (default).

```json
{
  "project_name":    "my_project",
  "base_path":       "/abs/path/to/project",
  "project_summary": "One-paragraph project description (LLM, --llm-summarize)",
  "module_summaries": { "app": "...", "math": "..." },
  "file_summaries":   { "app/main.cpp": "..." },
  "functions": {
    "MyClass::myMethod": {
      "qualifiedName": "MyClass::myMethod",
      "signature":     "void MyClass::myMethod(int count)",
      "file":          "app/main.cpp",
      "line":          42,
      "comment":       "Source comment or LLM description",
      "calls":         ["Helper::compute"],
      "phases":        [{"start_line": 1, "end_line": 5, "description": "Validate input"}]
    }
  },
  "enums":    { "Status": { "qualifiedName": "Status", "file": "...", "comment": "...", "values": { "OK": {"value": "0", "comment": ""} } } },
  "macros":   { "MAX_RETRIES": { "name": "MAX_RETRIES", "value": "3", "file": "...", "comment": "" } },
  "typedefs": { "StatusCode": { "name": "StatusCode", "underlying": "int", "file": "...", "comment": "" } },
  "structs":  { "Config": { "qualifiedName": "Config", "file": "...", "comment": "...", "members": { "timeout": {"type": "int", "comment": "ms"} } } }
}
```

### summaries.json  *(generated by Phase 2, --llm-summarize only)*
```json
{
  "project": "Narrative project summary",
  "modules": { "app": "Module summary", "math": "..." },
  "files":   { "app/main.cpp": "File summary", ... }
}
```

---

## Logic Flow

### Phase 1 — Parse (parser.py)

1. Walk project dir for `.cpp`, `.cc`, `.cxx` source files.
2. For each file, run **three libclang passes**:
   - `parse_file` → `visit_definitions` (functions) + `visit_type_definitions` (types)
   - `parse_calls` → `visit_calls` → build call graph (`calledByIds`, `callsIds`)
   - `parse_global_access` → `visit_global_access` → read/write sets per function
3. **Comment extraction** (new): `_preceding_comment(cursor)` reads `//` or `/* */` lines
   immediately above a function/type definition. `_inline_comment(cursor)` reads trailing
   `//` comment on the same line as a struct field or enum constant.
4. Write `metadata.json`, `functions.json` (with `comment`), `globalVariables.json`,
   `dataDictionary.json` (with `comment` on types and members).

### Phase 2 — Derive model (model_deriver.py)

1. Load functions, globals, metadata.
2. `_build_units_modules` → `units.json`, `modules.json`.
3. `_build_interface_index` → stable per-file index (01, 02, …).
4. `_enrich_interfaces` → `interfaceId`, `parameters`.
5. `_propagate_global_access` → transitive global read/write sets.
6. `_enrich_behaviour_names` → static Input/Output names from params/globals/returnType.
7. `_enrich_behaviour_names_llm` → LLM polish for generic static names.
8. **`_run_hierarchy_summarizer`** *(skipped with --no-llm-summarize)*:
   - Imports `HierarchySummarizer` from `src/flowchart/project_scanner.py`.
   - Builds `ProjectKnowledge` from model data (no extra libclang parse).
   - Runs 4-level LLM summarization: function summaries → phase breakdowns →
     file summaries → module summaries → project summary.
   - Writes phases back into `functions_data` in place.
   - Returns `{project, modules, files}` dict → written to `summaries.json`.
9. **`_enrich_from_llm`**: generates LLM descriptions for functions that have **no source
   comment** (functions with a `comment` field from parser.py are skipped — their source
   comment is already the best description available).
10. Persist enriched `functions.json`, `globalVariables.json`.
11. **`_generate_knowledge_base`** *(always runs)*: assembles `knowledge_base.json` from
    all enriched model data + dataDictionary + summaries.

### Phase 3 — Generate views (run_views.py)

Loads model from `model/` then calls each enabled view in `config.views`:

- **flowcharts** → spawns `flowchart_engine.py` subprocess (see Flowchart Engine below)
- **interfaceTables** → `output/interface_tables.json`
- **unitDiagrams** → per-unit Mermaid diagrams → `output/unit_diagrams/`
- **behaviourDiagram** → per-function Mermaid behaviour diagrams
- **moduleStaticDiagram** → module→units tree diagram

### Phase 4 — Export (docx_exporter.py)

Reads all view outputs from `output/` and assembles `software_detailed_design.docx`:
- Section 1: Introduction (Purpose, Scope, Terms)
- Sections 2..N: Per-module — Static Design (module diagram, unit diagrams, interface
  tables), Dynamic Behaviour (flowcharts, behaviour diagrams per function)
- Code Metrics, Coding Rule, Test Coverage
- Appendix A: Design Guideline

---

## Flowchart Engine

The flowchart engine lives at `src/flowchart/` and is invoked as a subprocess by the
`flowcharts` view. It does **statement-level** CFG analysis — a separate, deeper libclang
pass that the declaration-level parser.py cannot do in a single shared traversal.

### Entry point: flowchart_engine.py

```bash
# Standalone usage:
python src/flowchart/flowchart_engine.py \
    --interface-json  model/functions.json \
    --metaData-json   model/metadata.json \
    --knowledge-json  model/knowledge_base.json \
    --out-dir         output/flowcharts \
    --llm-url         http://localhost:11434/api/generate \
    --llm-model       qwen2.5-coder:14b \
    --std             c++17
```

Key arguments:

| Argument | Default | Description |
|----------|---------|-------------|
| `--interface-json` | required | `model/functions.json` |
| `--metaData-json` | required | `model/metadata.json` |
| `--knowledge-json` | none | `model/knowledge_base.json` — richer labels when provided |
| `--out-dir` | required | Output directory for `{unit}.json` files |
| `--llm-model` | `qwen2.5-coder:14b` | LLM model name |
| `--llm-url` | `http://localhost:11434/api/generate` | Ollama endpoint |
| `--llm-num-ctx` | `8192` | Context window tokens |
| `--llm-batch-size` | `4` | AST nodes per LLM call |
| `--llm-retries` | `2` | Retry attempts on validation failure |
| `--no-cache` | off | Rebuild PKB from scratch |
| `--function-key` | none | Process only one function (for debugging) |
| `--verbose` | off | Enable debug logging |

### Internal pipeline per function

```
functions.json
       │
       ▼
  ProjectKnowledgeBase (pkb/builder.py)
  ├─ builds fast lookup by key and qualifiedName
  └─ loads ProjectKnowledge from knowledge_base.json (if provided)
       │
       ▼  for each source file → for each function:
  SourceExtractor  (ast_engine/parser.py)
  └─ reads function body lines from .cpp file
       │
       ▼
  TranslationUnitParser  (ast_engine/parser.py)
  └─ libclang full parse with function body (statement-level)
       │
       ▼
  find_function_cursor  (ast_engine/resolver.py)
  └─ walks the AST to find the exact function CursorKind
       │
       ▼
  CFGBuilder  (ast_engine/cfg_builder.py)
  └─ walks function body statements → builds CFG (nodes + edges)
       │
       ▼
  NodeEnricher  (enrichment/enricher.py)
  └─ attaches PKB context to each node (callee descriptions, type info)
       │
       ▼
  LabelGenerator  (llm/generator.py)
  ├─ batches N nodes per LLM call (--llm-batch-size, default 4)
  ├─ injects: source snippet + base context + targeted callee context
  └─ parses LLM JSON response → assigns labels to nodes
       │
       ▼
  build_mermaid  (mermaid/builder.py)
  └─ converts labeled CFG → Mermaid flowchart string
       │
       ▼
  validate_mermaid  (mermaid/validator.py)
  └─ structural check; retries LabelGenerator on failure
       │
       ▼
  OutputWriter  (output/writer.py)
  └─ writes output/flowcharts/{unit}.json
```

### CFG node types (ast_engine/cfg_builder.py)

The CFG builder maps C++ AST cursor kinds to these node types:

| Node type | Trigger | Description |
|-----------|---------|-------------|
| `START` | function entry | Entry point |
| `END` | function end | Normal exit |
| `RETURN` | `return` statement | Early return |
| `ACTION` | sequential statements | One or more non-branching statements |
| `DECISION` | `if`/`else if` | Boolean branch — edges labelled `Yes` / `No` |
| `LOOP_HEAD` | `for`, `while`, `do` | Loop condition — edges `Yes` (body) / `No` (exit) |
| `SWITCH_HEAD` | `switch` | Switch entry |
| `CASE` | `case` / `default` | Switch arm |
| `BREAK` | `break` | Loop/switch exit |
| `CONTINUE` | `continue` | Loop next iteration |
| `TRY_HEAD` | `try` | Exception block entry |
| `CATCH` | `catch` | Exception handler |

### PKB context packet (pkb/builder.py)

For every function, the PKB assembles a context string injected at the top of every LLM
prompt. It has up to five sections:

1. **Project hierarchy** — `[Project] name: summary` / `[Module] path/: summary` /
   `[File] name.cpp: summary` (from `knowledge_base.json` summaries).
2. **Caller context** — up to 5 functions that call this one, with their signatures and
   purpose comments. Gives the LLM the "why" behind a helper function.
3. **Parameters + type resolution** — parameter list; for each enum/typedef parameter,
   injects the enum value names or underlying type from `knowledge_base.json`.
4. **Function purpose** — source comment (preferred) or LLM description.
5. **Execution phases** — `Phase 1 (lines N–M): description` sections from `phases[]`
   in `knowledge_base.json`, so the LLM knows which logical chapter it is labeling.

Per-batch, the `build_targeted_callee_context()` method adds context only for the
functions actually called within that batch of nodes — preventing prompt bloat from
injecting the entire 4-level BFS call graph at once.

### LLM call types

| Call type | Where | Trigger | Purpose |
|-----------|-------|---------|---------|
| Function description | `llm_client.py` | Phase 2, undocumented functions | `description` field in functions.json |
| Behaviour names | `llm_client.py` | Phase 2, poor static names | `behaviourInputName`, `behaviourOutputName` |
| Function summary | `project_scanner.HierarchySummarizer` | Phase 2 + `--llm-summarize` | Function-level comment for knowledge_base |
| Phase breakdown | `project_scanner.HierarchySummarizer` | Phase 2 + `--llm-summarize` | `phases[]` in functions.json |
| File summary | `project_scanner.HierarchySummarizer` | Phase 2 + `--llm-summarize` | `file_summaries` in knowledge_base |
| Module summary | `project_scanner.HierarchySummarizer` | Phase 2 + `--llm-summarize` | `module_summaries` in knowledge_base |
| Project summary | `project_scanner.HierarchySummarizer` | Phase 2 + `--llm-summarize` | `project_summary` in knowledge_base |
| CFG node labels | `llm/generator.py` | Phase 3, per function | Mermaid node labels in flowchart |

**No LLM call is duplicated.** Functions with source comments skip the description call
(Phase 2). When `--llm-summarize` is active, `HierarchySummarizer` generates a description
for undocumented functions and writes it back, so the Phase 2 description enrichment then
skips those too.

---

## Output: output/flowcharts/{unit}.json

Each file contains an array, one entry per function:

```json
[
  {
    "functionKey": "app|main|calculate|",
    "name":        "calculate",
    "flowchart":   "flowchart TD\n  START([Start])\n  ..."
  }
]
```

`name` is the simple function name used by `docx_exporter.py` to embed the flowchart in
the DOCX Dynamic Behaviour section for that function.

---

## Direction Inference (Phase 2)

Convention: **Get** (reads a global) = **Out**; **Set** (writes a global) = **In**;
both = **In**; no global access = **In**.

- `_propagate_global_access` walks the call graph to add transitive read/write sets —
  outer functions inherit inner globals so direction is accurate even for wrappers.
- `_enrich_behaviour_names` derives static Input/Output labels from params, globals,
  and return expression; `_enrich_behaviour_names_llm` asks the LLM to improve them
  when the static result is generic (e.g. ends in " input" or " result").

---

## Extensibility

**Adding a new view:** 1) Add `src/views/my_view.py` with `@register("myView")` and
`run(model, output_dir, model_dir, config)`. 2) Add `"myView": true` to `config.views`.
3) Import the module in `views/__init__.py`. Views read the model and write to `output/`.

**Running the flowchart engine standalone** (useful for debugging one function):

```bash
python src/flowchart/flowchart_engine.py \
    --interface-json model/functions.json \
    --metaData-json  model/metadata.json \
    --knowledge-json model/knowledge_base.json \
    --out-dir        output/flowcharts \
    --function-key   "app|main|calculate|" \
    --verbose
```
