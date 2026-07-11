# Analyzer — Complete End-to-End Flow Reference

Starting point: `python run.py <project_path>`

Everything in this document traces from that single command through every
module, function, file read/write, LLM call, and output artifact.

---

## Top-Level Pipeline — `run.py`

```
run.py  main block
  parse CLI flags:
    --clean              → delete output/ and model/ before running
    --all-groups         → iterate every modulesGroups key in config.json
    --no-llm-summarize   → skip LLM phase/hierarchy summarization
    --from-phase N       → skip phases before N

  load_config(PROJECT_ROOT)          reads config/config.json
                                     merges config.local.json if present

  if --all-groups:
      load_config() → modulesGroups keys
      for each group:
          write config.local.json  {"selectedGroup": "<group>"}
          _run_pipeline(from_ph)
  else:
      _run_pipeline(from_ph)

_run_pipeline(from_ph)
  subprocess: python src/parser.py        <project_path>   → Phase 1
  subprocess: python src/model_deriver.py                  → Phase 2
  subprocess: python src/run_views.py                      → Phase 3
  subprocess: python src/docx_exporter.py                  → Phase 4
  each phase must exit 0, else pipeline stops
```

---

## PHASE 1 — C++ Source Parser (`src/parser.py`)

**Purpose:** Walk every C++ source file in the project and extract the raw
structural model using libclang.

```
parser.py  top-level (script body)
  load_config()                   reads config.json / config.local.json
  cindex.Config.set_library_file()  loads libclang.dll / libclang.so
  resolve selectedGroup / modulesGroups → MODULE_FOLDERS filter
  build CLANG_ARGS: [-std=c++14, -I<project>, -I<clang_include>, ...]

  cindex.Index.create()           one shared libclang index

  walk MODULE_BASE_PATH:
      for each .cpp / .h / .hpp file:
          parse file with libclang (PARSE_DETAILED_PROCESSING_RECORD)
          traverse AST:
              FUNCTION_DECL / CXX_METHOD / CONSTRUCTOR / DESTRUCTOR
                  → extract: qualifiedName, returnType, params,
                              location (file, line, endLine),
                              comment (preceding // or /* */ doc)
                              returnExpr, calls (CALL_EXPR children)
              ENUM_DECL
                  → extract: name, enumerator values + comments
              MACRO_DEFINITION
                  → extract: name, value, comment
              TYPEDEF_DECL / TYPE_ALIAS_DECL
                  → extract: name, underlyingType, comment
              STRUCT_DECL / CLASS_DECL
                  → extract: fields (name, type, comment)
              VAR_DECL (global scope)
                  → extract: qualifiedName, type, location
          build call graph: caller → callsIds[], callee → calledByIds[]
          detect global reads/writes per function

  write model/metadata.json       {basePath, projectName, timestamp}
  write model/functions.json      {functionKey: {qualifiedName, location,
                                    parameters, returnType, callsIds,
                                    calledByIds, comment, ...}}
  write model/globalVariables.json
  write model/dataDictionary.json  {enums, macros, typedefs, structs}
```

**Key output files consumed by all later phases:**
```
model/metadata.json        → basePath, projectName
model/functions.json       → every function's key, location, call graph
model/globalVariables.json → global variable declarations
model/dataDictionary.json  → enums, macros, typedefs, structs
```

---

## PHASE 2 — Model Deriver (`src/model_deriver.py`)

**Purpose:** Enrich the raw parser model: derive units/modules, assign
interface IDs, propagate global access, generate LLM descriptions, build
the knowledge_base.json that the flowchart engine reads.

```
model_deriver.py  main()
  _load_model()
      reads model/metadata.json   → base_path, project_name
      reads model/functions.json  → functions_data dict
      reads model/globalVariables.json
      reads model/dataDictionary.json  (if present)

  ┌─ Step 1: Units & Modules ──────────────────────────────────────────┐
  │ _build_units_modules(base_path, functions_data, global_vars_data)  │
  │     groups functions and globals by source file                    │
  │     for each .cpp file:                                            │
  │         make_unit_key(rel_path)  → unit key string                 │
  │         derive callerUnits / calleesUnits from callsIds            │
  │     writes model/units.json     {unitKey: {name, path, functionIds,│
  │                                  globalVariableIds, callerUnits,   │
  │                                  calleesUnits}}                    │
  │     writes model/modules.json   {moduleName: {units: [...]}}       │
  └────────────────────────────────────────────────────────────────────┘

  ┌─ Step 2: Interface IDs ─────────────────────────────────────────────┐
  │ _build_interface_index()                                            │
  │     assigns sequential index per file                              │
  │ _enrich_interfaces()                                                │
  │     adds interfaceId: "IF_<PROJECT>_<UNIT>_<NN>" to each function  │
  │     normalizes parameters to [{name, type}]                        │
  └─────────────────────────────────────────────────────────────────────┘

  ┌─ Step 3: Global Access Propagation ────────────────────────────────┐
  │ _propagate_global_access(functions_data)                           │
  │     fixed-point traversal of call graph                            │
  │     propagates readsGlobalIds / writesGlobalIds from callees       │
  │     to callers (transitive closure)                                │
  │     writes: readsGlobalIdsTransitive, writesGlobalIdsTransitive    │
  └────────────────────────────────────────────────────────────────────┘

  ┌─ Step 4: Behaviour Names (static) ─────────────────────────────────┐
  │ _enrich_behaviour_names(functions_data, global_vars_data)          │
  │     for each function:                                             │
  │         behaviourInputName ← main param, or first written global,  │
  │                               or first read global, or function name│
  │         behaviourOutputName ← return expr identifier, or non-      │
  │                                primitive return type, or written   │
  │                                global, or function name            │
  │         _readable_label(name) → strips g_/s_/t_ prefixes,         │
  │                                  replaces _ with space             │
  └────────────────────────────────────────────────────────────────────┘

  ┌─ Step 5: Behaviour Names (LLM polish) ─────────────────────────────┐
  │ _enrich_behaviour_names_llm(base_path, functions_data,             │
  │                              global_vars_data, config)             │
  │     skips if config.llm.behaviourNames = false                     │
  │     skips functions where static names are already good            │
  │     _static_behaviour_name_is_poor(f) → True if name ends with    │
  │          " input" / " result" or is empty                          │
  │     for each poor-name function:                                   │
  │         extract_source(base_path, loc) → raw C++ source text       │
  │         get_behaviour_names(source, params, globals_read,          │
  │                              globals_written, return_type,         │
  │                              return_expr, draft_input,             │
  │                              draft_output, config, abbreviations)  │
  │             → LLM call via llm_client.py                          │
  │         updates: f["behaviourInputName"], f["behaviourOutputName"] │
  └────────────────────────────────────────────────────────────────────┘

  ┌─ Step 6: LLM Summarization (--llm-summarize only) ─────────────────┐
  │ _run_hierarchy_summarizer(base_path, project_name,                 │
  │                            functions_data, config)                 │
  │                                                                    │
  │     Imports from src/flowchart/ (reuses flowchart module):         │
  │         from project_scanner import HierarchySummarizer            │
  │         from llm.client import LlmClient                           │
  │         from pkb.knowledge import FunctionKnowledge, ProjectKnowledge│
  │                                                                    │
  │     Builds ProjectKnowledge from functions_data in memory:         │
  │         for each function:                                         │
  │             FunctionKnowledge(qualified_name, signature, file,     │
  │                               line, comment, calls=[qnames])       │
  │             knowledge.functions[qname] = fk                       │
  │                                                                    │
  │     Creates LlmClient(url, model, num_ctx) from config.llm         │
  │                                                                    │
  │     HierarchySummarizer(knowledge, client, base_path).summarize()  │
  │         ┌ Pass 1a: Function summaries ──────────────────────────── │
  │         │ for each function with no comment:                       │
  │         │     batch up to batch_size functions                     │
  │         │     LLM: "one sentence per function"                     │
  │         │     → writes fk.comment                                  │
  │         │                                                          │
  │         ├ Pass 1b: Phase breakdown ─────────────────────────────── │
  │         │ for each documented function:                            │
  │         │     sends function body source to LLM                    │
  │         │     LLM: "break into 2-6 logical phases"                 │
  │         │     → writes fk.phases [{start_line,end_line,description}]│
  │         │                                                          │
  │         ├ Pass 2: File summaries ──────────────────────────────────│
  │         │ for each source file:                                    │
  │         │     collect all function signatures + comments from file │
  │         │     LLM: "2-3 sentence description of this file"         │
  │         │     → writes knowledge.file_summaries[rel_path]          │
  │         │                                                          │
  │         ├ Pass 3: Module summaries ────────────────────────────────│
  │         │ groups files by parent directory                         │
  │         │ for each module directory:                               │
  │         │     collect that directory's file_summaries              │
  │         │     LLM: "2-3 sentence module description"               │
  │         │     → writes knowledge.module_summaries[dir]             │
  │         │                                                          │
  │         └ Pass 4: Project summary ───────────────────────────────  │
  │           if README.md exists → send README to LLM                 │
  │           else → send all module summaries                         │
  │           LLM: "overall project description"                       │
  │           → writes knowledge.project_summary                       │
  │                                                                    │
  │     Back-fills into functions_data:                                │
  │         fk.phases → functions_data[fid]["phases"]                  │
  │         fk.comment (if LLM-generated) → functions_data[fid]       │
  │                                                                    │
  │     Returns: {project: str, modules: {}, files: {}}               │
  │     Writes model/summaries.json                                    │
  └────────────────────────────────────────────────────────────────────┘

  ┌─ Step 7: Function Descriptions (LLM) ──────────────────────────────┐
  │ _enrich_from_llm(base_path, functions_data,                        │
  │                   global_vars_data, config)                        │
  │     skips functions that already have a source comment             │
  │     (parser.py extracted it; flowchart engine prefers source       │
  │      comments over LLM descriptions)                               │
  │     enrich_functions_with_descriptions(funcs_list, base_path,      │
  │                                         config)                    │
  │         → LLM calls via src/llm_client.py                         │
  │         → writes f["description"] for undocumented functions       │
  │     enrich_globals_with_descriptions(globals_list, base_path,      │
  │                                       config)                      │
  └────────────────────────────────────────────────────────────────────┘

  ┌─ Step 8: Knowledge Base Generation ────────────────────────────────┐
  │ _generate_knowledge_base(base_path, project_name,                  │
  │                           functions_data, data_dict, summaries)    │
  │                                                                    │
  │ This is the CRITICAL BRIDGE from the analyzer to the flowchart     │
  │ engine. Converts the analyzer's model format into the format       │
  │ flowchart/pkb/builder.py (ProjectKnowledgeBase) expects.           │
  │                                                                    │
  │ Builds functions_kb:                                               │
  │     for each function:                                             │
  │         {qualifiedName, signature, file, line,                     │
  │          comment (source comment OR LLM description),              │
  │          calls: [qualified callee names],                          │
  │          phases: [{start_line, end_line, description}]}            │
  │                                                                    │
  │ Converts dataDictionary to flowchart format:                       │
  │     "enum" entries   → enums_kb   {name: {values, comment}}       │
  │     "define" entries → macros_kb  {name: {value, comment}}        │
  │     "typedef" entries→ typedefs_kb{name: {underlying, comment}}   │
  │     "struct/class"   → structs_kb {name: {members, comment}}      │
  │                                                                    │
  │ writes model/knowledge_base.json:                                  │
  │     {project_name, base_path,                                      │
  │      project_summary, module_summaries, file_summaries,            │
  │      functions: functions_kb,                                      │
  │      enums, macros, typedefs, structs}                             │
  └────────────────────────────────────────────────────────────────────┘

  Persists enriched data:
      writes model/functions.json   (enriched: +interfaceId, +description,
                                     +behaviourInputName, +behaviourOutputName,
                                     +phases, +readsGlobalIdsTransitive, ...)
      writes model/globalVariables.json
```

**Key output files consumed by Phase 3:**
```
model/functions.json         → enriched function metadata + call graph
model/metadata.json          → basePath (unchanged from Phase 1)
model/knowledge_base.json    → the full knowledge base for LLM context
model/units.json             → unit structure
model/modules.json           → module grouping
```

---

## PHASE 3 — Views Generator (`src/run_views.py`)

**Purpose:** Load the enriched model and generate all output views.
Flowcharts are one of four views.

```
run_views.py  main()
  _load_model()
      reads model/functions.json
      reads model/globalVariables.json
      reads model/units.json
      reads model/modules.json
      reads model/dataDictionary.json  (if present)

  load_config()
  run_views(model, OUTPUT_DIR, MODEL_DIR, config)
      iterates VIEW_REGISTRY (populated by @register decorators):
          "interfaceTables" → interface_tables.run()
          "unitDiagrams"    → unit_diagrams.run()
          "behaviourDiagram"→ behaviour_diagram.run()
          "flowcharts"      → flowcharts.run()   ← flowchart engine entry
```

### Flowcharts View — `src/views/flowcharts.py`

```
flowcharts.run(model, output_dir, model_dir, config)
  reads config.views.flowcharts.scriptPath
      → resolves to src/flowchart/flowchart_engine.py

  reads model/metadata.json basePath → derive -I<basePath> clang arg
  reads config.llm: baseUrl, defaultModel, numCtx

  if model/knowledge_base.json exists → --knowledge-json argument

  builds subprocess command:
      python src/flowchart/flowchart_engine.py
          --interface-json  model/functions.json
          --metaData-json   model/metadata.json
          --std             c++14
          --out-dir         output/flowcharts/
          --llm-url         <config.llm.baseUrl>/api/generate
          --llm-model       <config.llm.defaultModel>
          --llm-num-ctx     <config.llm.numCtx>
          --knowledge-json  model/knowledge_base.json   (if exists)
          --clang-arg=<I>   (from config.clang.clangArgs)

  subprocess.run(cmd)  → launches flowchart_engine.py as a child process
  if returncode != 0 → log error, return

  if config.views.flowcharts.renderPng:
      for each .json in output/flowcharts/:
          for each {name, flowchart} entry:
              write flowchart string to temp .mmd file
              mmdc -i <file.mmd> -o <unit_func.png>
              delete temp .mmd file
      logs: "N PNGs rendered"
```

---

## PHASE 3 (cont.) — Flowchart Engine Subprocess
### `src/flowchart/flowchart_engine.py`

This runs as a child process launched by `flowcharts.run()`.

```
flowchart_engine.py  run(config)
  _load_project_meta()
      reads model/metadata.json → ProjectMeta(base_path, project_name)

  _load_functions()
      reads model/functions.json → raw functions dict

  load_knowledge()   [pkb/knowledge.py]
      reads model/knowledge_base.json → ProjectKnowledge
          .project_name, .base_path
          .project_summary     (from HierarchySummarizer Pass 4)
          .module_summaries{}  (from HierarchySummarizer Pass 3)
          .file_summaries{}    (from HierarchySummarizer Pass 2)
          .functions{}         → FunctionKnowledge per qname
                                   .signature, .comment, .calls[], .phases[]
          .enums{}             → EnumKnowledge per name
          .macros{}            → MacroKnowledge per name
          .typedefs{}          → TypedefKnowledge per name
          .structs{}           → StructKnowledge per name

  _build_pkb(functions_data, config)
      ┌─ Cache check ──────────────────────────────────────────────────┐
      │ PkbCache(cache_dir).invalidate_stale(functions_json_str)       │
      │     MD5(functions.json content)[:16] → cache key               │
      │     deletes pkb_*.json files that don't match current hash     │
      │ PkbCache.load(functions_json_str)                              │
      │     if cache hit: pkb.from_dict() → restore from disk, done   │
      │     if cache miss: pkb.build() → index all functions, save     │
      └────────────────────────────────────────────────────────────────┘
      pkb.build(functions_data)
          for each function entry:
              FunctionEntry(key, qualified_name, file, line, end_line,
                            params, calls_ids, called_by_ids,
                            interface_id, description)
              stored in pkb._functions[key]
              also indexed in pkb._by_qualified_name[qname]

  pkb.load_project_knowledge(project_knowledge)
      attaches ProjectKnowledge to PKB
      builds _knowledge_by_short_name{} index:
          qname.split("::")[-1] → FunctionKnowledge
          enables O(1) short-name lookup in targeted callee context

  Header file filter:
      _is_header_file(func_entry.file)
          Path(file).suffix in {'.h','.hpp','.hxx','.hh', ...}
      → True:  skip entirely, never enter pipeline, no output written
               INFO: "Skipping N header-defined function(s)"
      → False: proceed to processing

  Group remaining functions by source file (by_file dict)

  Instantiate shared infrastructure (once per run):
      SourceExtractor(base_path)
      TranslationUnitParser(std, clang_args)
      LlmClient(url, model, timeout, temperature, num_ctx)
      LabelGenerator(client, pkb, max_retries, batch_size)
      OutputWriter(out_dir)

  for each source file in by_file:
      for each function entry:
          _process_function(func_entry, ...)
      writer.write_file_result(file_result)
          → output/flowcharts/<stem>.json

  writer.write_summary(...)
      → output/flowcharts/_summary.json
```

---

### Per-Function Pipeline — `_process_function()`

```
_process_function(func_entry, pkb, source_extractor, tu_parser,
                  label_generator, config, base_path, project_knowledge)

━━━ STEP 1: Source Extraction ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
source_extractor.extract_by_lines(file, line, end_line)
    → source_code string (the function's raw C++ text)
source_extractor.get_lines(file)
    → source_lines[] (full file, LRU-cached by filename)

━━━ STEP 2: Parse Translation Unit ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
tu_parser.get_tu_full(abs_path)
    cache key = abs_path + "__full"
    if cached: return cached TU
    else:
        index.parse(abs_path, args=[-std=c++14, -x c++, -I...])
            options: PARSE_DETAILED_PROCESSING_RECORD | PARSE_INCOMPLETE
            NOTE: PARSE_SKIP_FUNCTION_BODIES is NOT set
                  → function bodies are fully parsed for CFG traversal
        _log_diagnostics(): logs clang errors/warnings
    returns libclang TranslationUnit

━━━ STEP 3: Resolve Function Cursor ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
find_function_cursor(tu, func_entry, abs_path)

    Strategy 1 — Direct position lookup (fast path):
        _position_lookup(tu, abs_path, target_line, target_end, simple_name)
        try filenames: [tu.spelling, abs_path]
        probe positions: (target_line, col 1), (target_line, col 5),
                         then lines target_line+1 through +5 at col 5
        ci.SourceLocation.from_position(tu, file, line, col)
        ci.Cursor.from_location(tu, loc)
        _is_function_match(cursor, simple_name, target_line)
            cursor.kind in FUNCTION_KINDS or UNEXPOSED_KINDS
            extent.start.line within ±10 lines of target
            cursor.spelling contains simple_name
        if no match on cursor → walk lexical_parent chain (depth ≤ 25)
        → returns cursor if found

    Strategy 2 — Full AST traversal (fallback):
        _visit(tu.cursor) recursive DFS, skips system headers
        for each FUNCTION_DECL / CXX_METHOD / UNEXPOSED_DECL:
            _accept(cursor):
                file_match: loc.file.name endswith target_file
                null_file_match: loc.file=None + line proximity
                tight match: extent contains [target_line, target_end]
                loose match: start ±10 lines AND name match
                _score(): +100 exact name, +40 partial, -line distance,
                          +20 if is_definition()
                penalties: -15 loose, -10 null-file, -20 unexposed
        sort candidates by score → return best

    Strategy 3 — Broad scan (last resort):
        _visit_broad(): any cursor kind, ±25 lines, -50 base penalty
        → return best broad candidate

    if all fail → RuntimeError → FlowchartResult(error=...)

━━━ STEP 4: Build Control Flow Graph ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CFGBuilder(source_lines, max_stmts, max_lines).__init__
    _collect_assert_locations(source_lines)
        _ASSERT_RE.finditer() on every source line
        builds frozenset{(line, col)} for ASSERT / POS_ASSERT /
        UTIL_DEBUG_ASSERT / static_assert etc.
        stored as self._assert_locs  (pre-scan, O(1) lookup per cursor)

CFGBuilder.build(func_cursor, func_entry)
    _new_node(START)
    get_function_body(func_cursor) → COMPOUND_STMT cursor
    _process_compound(body_cursor, open_exits=[START → None])
    _new_node(END)
    connect all remaining open_exits → END
    returns ControlFlowGraph

_process_compound(cursor, open_exits)
    for each child cursor of COMPOUND_STMT:
        ASSERT check (BEFORE kind dispatch):
            _is_assert_stmt(child, self._assert_locs)
                (cursor.extent.start.line, col) in assert_locs → skip
                prevents ASSERT macros from becoming DECISION nodes
        dispatch by cursor.kind:
            IF_STMT      → _process_if()
                               _new_node(DECISION)
                               recurse THEN branch
                               recurse ELSE branch (if present)
                               merge exits from both branches
            FOR_STMT     → _process_for()
                               _new_node(LOOP_HEAD)
                               recurse body
                               back-edge: body tail → LOOP_HEAD
                               exits: LOOP_HEAD "No" + BREAK exits
            WHILE_STMT   → _process_while()   (same pattern as FOR)
            DO_STMT      → _process_do_while()
                               process body first
                               _new_node(LOOP_HEAD) at bottom
                               back-edge → body start
            SWITCH_STMT  → _process_switch()
                               _new_node(SWITCH_HEAD)
                               _process_case_stmts()
                                   ASSERT check here too
                                   _new_node(CASE / DEFAULT_CASE)
                                   recurse case body
            RETURN_STMT  → _process_return()
                               flush ACTION buffer
                               _new_node(RETURN)
                               dead exit (not connected forward)
            BREAK_STMT   → _new_node(BREAK)  stored for loop exit wiring
            CONTINUE_STMT→ _new_node(CONTINUE)
            CXX_TRY_STMT → _process_try()
                               _new_node(TRY_HEAD)
                               process try body
                               for each CATCH: _new_node(CATCH)
            anything else→ accumulated into ACTION buffer
                           flush() when:
                               buffer reaches max_stmts statements, OR
                               buffer spans more than max_lines source lines

━━━ STEP 5: Enrich CFG Nodes ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NodeEnricher(pkb, {file: source_lines}, project_knowledge)
enricher.enrich(cfg, func_entry)
    for each node (skips START/END/BREAK/CONTINUE):
        _enrich_node(node, func_entry, src_lines)

        _resolve_calls(node.raw_code, func_entry.calls_ids)
            _CALL_PATTERN.findall(raw_code) → candidate function names
            match against PKB calls_ids
            → node.enriched_context["function_calls"]
               [{signature, description}]

        _nearest_comment(src_lines, node.start_line)
            scans source lines near node for // comment
            → node.enriched_context["inline_comment"]

        _resolve_enum_context(raw_code, knowledge)
            extracts ALL_CAPS tokens
            matches knowledge.enums, knowledge.macros
            → node.enriched_context["enum_context"]
            → node.enriched_context["macro_context"]

        _resolve_typedef_context(raw_code, knowledge)
            matches knowledge.typedefs
            → node.enriched_context["typedef_context"]

        _resolve_struct_member_context(raw_code, knowledge)
            _MEMBER_ACCESS_RE: obj.field / ptr->field
            matches knowledge.structs[*].members
            → node.enriched_context["struct_member_context"]

━━━ STEP 6: Generate LLM Labels ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(see full LLM Label Generation section below)

━━━ STEP 7: Validate CFG ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
validate_cfg(cfg)
    checks: START node exists, END node exists
    checks: all edge source/target node_ids are known
    checks: no empty labels on non-sentinel nodes
    _reachable(cfg) BFS from entry → warns on unreachable nodes

━━━ STEP 8: Build Mermaid Script ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
build_mermaid(cfg)
    "flowchart TD"
    _topo_order(cfg): BFS from entry_node_id
    for each node:
        _node_def(node)
            _enforce_line_length(label, max_chars=40)
                splits <br/>-separated segments, word-wraps long ones
            _escape_label(label)
                single-pass _NODE_LABEL_RE.sub()
                → #40; #41; #60; #91; #93; etc. (no double-encoding)
            shape:
                START/END        → nodeId([label])   stadium
                DECISION/
                LOOP_HEAD/
                SWITCH_HEAD      → nodeId{label}      diamond
                CATCH            → nodeId[[label]]    subroutine
                all others       → nodeId[label]      rectangle
    for each edge:
        _edge_def(edge)
            normalize_edge_label(): Yes/No standardisation
            "source -->|label| target"  or  "source --> target"

━━━ STEP 9: Validate Mermaid ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
validate_mermaid(mermaid_script)
    checks: starts with "flowchart"
    checks: no unmatched double-quotes per line

Returns FlowchartResult(function_key, qualified_name, mermaid_script)
On any exception → FlowchartResult(error=str(exc))
```

---

## LLM Label Generation (Step 6 detail)

### `src/flowchart/llm/generator.py`

```
LabelGenerator.label_cfg(cfg, func_entry, source_code, base_path)

━━━ Build per-function static context ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
pkb.build_context_packet(func_entry, base_path)
    build_base_context_packet()
        _build_hierarchy_context()
            reads knowledge.project_summary     → [Project] line
            reads knowledge.module_summaries    → [Module] line
            reads knowledge.file_summaries      → [File]   line
        _build_caller_context()
            for each calledByIds entry (up to 5):
                looks up caller in knowledge.functions
                → "Called by: funcName → description"
        _resolve_param_types()
            for each param type:
                match knowledge.enums   → enum summary
                match knowledge.typedefs→ typedef summary
        get_function_phases(func_entry)
            knowledge.functions[qname].phases
            → [{start_line, end_line, description}]
    _build_callee_bfs_context()
        BFS up to 4 levels via calls_ids / fk.calls
        up to 10 callees per level (deduplicated)
        for unknown callees: _extract_callee_from_source() fallback
            parses source file to extract signature + preceding comment
        → "=== Called Functions Context ==="
           "Direct calls:", "Calls at depth 2:", ...

━━━ Topological sort ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_topo_sort(cfg)
    iterative DFS post-order
    detects back-edges (loop body → loop head)
    returns (ordered_node_ids[], back_edges set)

━━━ Region-aware batching ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_make_region_batches(ordered_labelable, cfg, batch_size, back_edges)
    pred_count: count forward-edge predecessors (excludes back-edges)
    new batch starts when:
        merge point reached (pred_count > 1) — after if/else join
        DECISION / LOOP_HEAD / SWITCH_HEAD node encountered
        current batch reaches batch_size
    _merge_small_batches(): merge 1-node batches with neighbour
    → List[List[CfgNode]]

━━━ Per-batch labeling ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
for each batch:
    _label_batch_with_split(batch, ...)
        calls _label_batch()
        if ALL attempts return no response AND batch > 1 AND depth < 3:
            WARNING: "Auto-splitting in half (depth N of 3)"
            split batch in half, recurse each sub-batch

_label_batch(batch, func_entry, base_context, source_code, ...)
    ┌─ Build batch-specific prompt ──────────────────────────────────── │
    │ _extract_batch_callee_names(batch)                                │
    │     reads node.enriched_context["function_calls"]                │
    │     collects qualified names + short names                        │
    │ pkb.build_targeted_callee_context(func_entry, callee_names)      │
    │     exact qname match → knowledge.functions[qname]               │
    │     short-name fallback → _knowledge_by_short_name[short]        │
    │     → "=== Relevant Called Functions ==="                         │
    │ _build_size_aware_prompt(batch, func_entry, context, source, ...) │
    │     Attempt A: prompt without source excerpt                      │
    │         build_user_prompt(source_code="")                         │
    │         if total ≤ MAX_PROMPT_CHARS (6000):                       │
    │             try adding source excerpt:                            │
    │             _extract_batch_source() → numbered lines ±5 of batch │
    │             if with-excerpt ≤ 6000: use it                        │
    │         else use no-excerpt version                               │
    │     Attempt B: if still too large:                                │
    │         _trim_context(context, min(available, 1200))              │
    │             cuts at last newline before budget                    │
    │             appends "… [context trimmed to fit model window]"     │
    │         rebuild prompt with trimmed context                       │
    └────────────────────────────────────────────────────────────────── │

    Retry loop — range(1, self._max_retries):
        ┌─ Choose prompt ────────────────────────────────────────────── │
        │ attempt 1 OR previous had no response:                        │
        │     use base_prompt  (do NOT add retry note — larger prompt   │
        │     would make context overflow worse)                        │
        │ attempt > 1 AND previous returned bad JSON:                   │
        │     prompt + _build_retry_note(last_failures)                 │
        │         "=== CORRECTION REQUIRED ==="                         │
        │         lists failing node_ids with reasons                   │
        └────────────────────────────────────────────────────────────── │

        LlmClient.generate(SYSTEM_PROMPT, prompt)
            if Ollama format:
                POST /api/generate
                {model, system, prompt, stream:false,
                 options:{num_ctx, temperature, top_p, num_predict}}
                reads data["response"]
            if OpenAI format:
                POST /v1/chat/completions
                {model, messages:[{system},{user}],
                 temperature, max_tokens}
                reads choices[0].message.content
            → raw (str) or None

        if raw is None:
            no_response_attempts++
            last_failures = "LLM returned no response"
            continue  (retry with same prompt)

        _parse_partial(raw, remaining_ids)
            _extract_json(raw)
                strips ```json ``` fences
                finds first { ... } balanced brace block
                → cleaned JSON string or None
            if None:
                all nodes → "No JSON object found in LLM response"
                → failures dict
            else:
                json.loads(cleaned)
                for each required node_id:
                    validates: present, string, non-empty, ≤300 chars
                    → accepted or failed
            returns (accepted{}, failures{})

        accumulated.update(accepted)
        remaining -= accepted keys
        if remaining empty → batch complete, return
        last_failures = failures
        WARNING: "Batch attempt N/M: X node(s) still need labels — ..."

    After all retries exhausted:
        all_no_response = (no_response_attempts == total_attempts)
        for remaining nodes: _fallback_label(node)
            DECISION   → "Check: <raw_code>?"
            LOOP_HEAD  → "Loop: <raw_code>?"
            SWITCH_HEAD→ "Switch on: <raw_code>?"
            CASE       → "Case: <raw_code>"
            RETURN     → "Return <expr>"
            BREAK      → "Exit loop"
            CONTINUE   → "Continue to next iteration"
            TRY_HEAD   → "Execute with exception handling"
            CATCH      → "Handle exception: <raw_code>"
            ACTION     → first non-empty line of raw_code[:80]
        WARNING: "Fallback labels applied for N node(s): [...]"
        returns (accumulated, all_no_response)

━━━ Coherence pass (when ≥ 5 nodes) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_coherence_pass(cfg, func_entry, label_map, ordered_nodes)
    builds ordered list of (node_id, label, type) in execution order
    one LLM call total:
        SYSTEM: "fix inconsistent terminology, passive voice"
        prompt: all labels in execution order
        → changes dict {node_id: improved_label}
    merges changes back into label_map
    INFO: "Coherence pass updated N label(s)"

━━━ Apply labels ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_apply_labels(cfg, label_map)
    cfg.nodes[id].label = label for each id

START node → "Start: <function_short_name>"
END node   → "End"

Report fallback usage:
    _looks_like_fallback(node): label starts with "Check: "/"Loop: " etc.
    WARNING if fallback_count > 0: "'func': N/M node(s) used fallback"
```

---

## PHASE 4 — DOCX Exporter (`src/docx_exporter.py`)

```
docx_exporter.py
    reads model/functions.json
    reads model/units.json
    reads model/modules.json
    reads output/flowcharts/<stem>.json  (Mermaid scripts)
    reads output/flowcharts/<stem>_<func>.png  (rendered PNGs)
    assembles software_detailed_design_{group}.docx
    writes output/software_detailed_design_{group}.docx
```

---

## Data Flow Summary — What Each File Contains

```
model/metadata.json
    {basePath, projectName, timestamp}
    written by: parser.py
    read by:    model_deriver.py, flowcharts.py (for -I clang arg)

model/functions.json
    {functionKey: {qualifiedName, location:{file,line,endLine},
                   parameters, returnType, callsIds[], calledByIds[],
                   comment, description, interfaceId, phases[],
                   behaviourInputName, behaviourOutputName,
                   readsGlobalIdsTransitive[], writesGlobalIdsTransitive[]}}
    written by: parser.py (raw), model_deriver.py (enriched)
    read by:    flowchart_engine.py (as --interface-json)

model/globalVariables.json
    {varKey: {qualifiedName, type, location, direction}}
    written by: parser.py, model_deriver.py

model/dataDictionary.json
    {key: {kind:"enum"|"define"|"typedef"|"struct",
           qualifiedName, values/value/fields, comment, location}}
    written by: parser.py

model/units.json
    {unitKey: {name, path, functionIds[], globalVariableIds[],
               callerUnits[], calleesUnits[]}}
    written by: model_deriver.py

model/modules.json
    {moduleName: {units: [unitKey, ...]}}
    written by: model_deriver.py

model/knowledge_base.json                   ← THE KEY BRIDGE
    {project_name, base_path,
     project_summary,                        (LLM, Pass 4)
     module_summaries:{dir: summary},        (LLM, Pass 3)
     file_summaries:{file: summary},         (LLM, Pass 2)
     functions:{qname: {signature, comment,  (LLM, Pass 1)
                        calls:[], phases[]}},
     enums:{name: {values:{}, comment}},
     macros:{name: {value, comment}},
     typedefs:{name: {underlying, comment}},
     structs:{name: {members:{}, comment}}}
    written by: model_deriver._generate_knowledge_base()
    read by:    flowchart_engine.py as --knowledge-json
                → load_knowledge() → ProjectKnowledge
                → pkb.load_project_knowledge()
                → injected into every LLM prompt as context

output/flowcharts/<stem>.json
    [{functionKey, name, flowchart:"flowchart TD\n..."}]
    written by: flowchart_engine OutputWriter
    read by:    flowcharts.run() for PNG rendering
                docx_exporter.py for DOCX assembly

output/flowcharts/<stem>_<func>.png
    rendered by: mmdc (Mermaid CLI)
    read by:    docx_exporter.py

output/flowcharts/_summary.json
    {totalFunctions, totalErrors, files:[{sourceFile,
     flowchartsGenerated, errors}]}
    written by: OutputWriter.write_summary()
```

---

## How the Knowledge Base Feeds Each LLM Prompt

Every LLM call for node labeling receives the following context, all
sourced from knowledge_base.json:

```
SYSTEM_PROMPT (constant — defines role + label rules)

USER PROMPT per batch:
  ┌──────────────────────────────────────────────────────────────────┐
  │ Function: QualifiedName(params)                                  │
  │ Purpose:  knowledge.functions[qname].comment                     │
  │                                                                  │
  │ === Project Context ===                                          │
  │ [Project] <project_name>: <project_summary>     ← Pass 4 LLM    │
  │ [Module]  <dir/>: <module_summaries[dir]>       ← Pass 3 LLM    │
  │ [File]    <file>: <file_summaries[file]>        ← Pass 2 LLM    │
  │                                                                  │
  │ Called by (callers of this function):                            │
  │   - CallerFunc → caller description             ← calledByIds   │
  │                                                                  │
  │ Parameters: type name, ...                                       │
  │ Parameter type context:                                          │
  │   MyEnum (enum): val1=0 (meaning), val2=1 ...   ← enums         │
  │   MyType: underlying type description            ← typedefs      │
  │                                                                  │
  │ Function execution phases:                                       │
  │   Phase 1 (lines 5-12): Initialize connection   ← Pass 1b LLM   │
  │   Phase 2 (lines 13-25): Process request        ← Pass 1b LLM   │
  │                                                                  │
  │ === Called Functions Context ===                                 │
  │ Direct calls:                                                    │
  │   - FuncA(args) → what FuncA does               ← functions     │
  │   - FuncB(args) → what FuncB does                               │
  │ Calls at depth 2:                                                │
  │   - FuncC(args) → ...                                           │
  │ (up to 4 levels deep, 10 per level)                             │
  │                                                                  │
  │ === Relevant Called Functions ===   (targeted, per-batch)        │
  │   - ExactCallee(args) → description             ← targeted       │
  │                                                                  │
  │ --- Function Source Code ---   (if fits in 6000 chars)          │
  │ 42: void MyFunc() {                                              │
  │ 43:   ...                                                        │
  │                                                                  │
  │ --- Nodes to Label ---                                           │
  │ [{node_id, type, raw_code,                                       │
  │   called_functions: [{sig: desc}],   ← enriched_context         │
  │   source_comment,                    ← enriched_context         │
  │   enum_context, macro_context,       ← enriched_context         │
  │   typedef_context,                   ← enriched_context         │
  │   struct_member_context,             ← enriched_context         │
  │   preceding_node_code,               ← neighbour context        │
  │   following_node_code,               ← neighbour context        │
  │   phase_hint,                        ← phase description        │
  │   data_flow_shared: [identifiers]}]  ← shared state hint        │
  │                                                                  │
  │ Return ONLY the JSON object mapping each node_id to its label.  │
  └──────────────────────────────────────────────────────────────────┘
```

---

## Complete File Map

```
analyzer/                          ← project root
  run.py                           pipeline entry point (4 phases)
  config/config.json               llm, clang, views, modulesGroups settings
  config/abbreviations.txt         domain abbreviations for LLM behaviour names

  src/
    parser.py                      Phase 1: C++ → model/ (libclang AST scan)
    model_deriver.py               Phase 2: enrich model, build knowledge_base.json
    run_views.py                   Phase 3: load model, invoke all views
    docx_exporter.py               Phase 4: model + outputs → DOCX
    llm_client.py                  LLM client for Phase 2 (descriptions, behaviour names)
    utils.py                       load_config, log, timed, make_function_key, ...

    views/
      __init__.py                  run_views() + VIEW_REGISTRY imports
      registry.py                  @register decorator
      flowcharts.py                launches flowchart_engine.py subprocess + PNG render
      interface_tables.py          interface table view
      unit_diagrams.py             unit diagram view
      behaviour_diagram.py         behaviour diagram view

    flowchart/                     flowchart sub-module (integrated into Phase 3)
      flowchart_engine.py          flowchart engine entry (subprocess)
      project_scanner.py           standalone scanner + HierarchySummarizer
                                   (imported by model_deriver.py for Phase 2 LLM)
      models.py                    FunctionEntry, CfgNode, ControlFlowGraph, ...
      config.py                    EngineConfig dataclass

      ast_engine/
        parser.py                  SourceExtractor, TranslationUnitParser
        resolver.py                find_function_cursor() — 3-strategy resolver
        cfg_builder.py             CFGBuilder: AST cursor → ControlFlowGraph

      enrichment/
        enricher.py                NodeEnricher: annotates nodes with PKB context

      llm/
        client.py                  LlmClient: HTTP wrapper (Ollama + OpenAI formats)
        generator.py               LabelGenerator: batching, retry, auto-halving,
                                   coherence pass
        prompts.py                 SYSTEM_PROMPT, build_user_prompt(),
                                   _build_node_list()

      mermaid/
        builder.py                 build_mermaid(): CFG → Mermaid TD text
        normalizer.py              normalize_condition(), normalize_edge_label()
        validator.py               validate_cfg(), validate_mermaid()

      pkb/
        builder.py                 ProjectKnowledgeBase: context packet construction,
                                   4-level BFS callee graph, targeted callee context
        cache.py                   PkbCache: MD5-keyed disk cache
        knowledge.py               ProjectKnowledge dataclasses (FunctionKnowledge,
                                   EnumKnowledge, MacroKnowledge, ...)

      output/
        writer.py                  OutputWriter: per-file JSON + _summary.json

  model/                           Phase 1+2 outputs (intermediate)
    metadata.json
    functions.json
    globalVariables.json
    dataDictionary.json
    units.json
    modules.json
    knowledge_base.json            ← critical bridge: Phase 2 → flowchart engine
    summaries.json                 (if --llm-summarize)

  output/                          Phase 3+4 outputs (final)
    flowcharts/
      <stem>.json                  [{functionKey, name, flowchart}]
      <stem>_<func>.png            (if renderPng: true)
      _summary.json
    software_detailed_design_{group}.docx
```
