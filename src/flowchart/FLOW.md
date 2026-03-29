# Flowchart Engine — Complete Flow Reference

This document describes every execution path through the system, with the
exact function names involved at each step.

---

## Overview — Two-Phase Pipeline

```
PHASE 1  project_scanner.py   (run once per project)
         Scans all C++ source files with libclang
         Outputs  →  project_knowledge.json

PHASE 2  flowchart_engine.py  (run per analysis)
         Reads functions.json + project_knowledge.json
         Outputs  →  one JSON file per source file  +  _summary.json
```

---

## PHASE 1 — Project Scanner (`project_scanner.py`)

### Entry Point

```
main()
  _parse_args()                    reads CLI flags
  discover_files()                 walks project_dir, returns List[Path]
  ci.Index.create()                creates one shared libclang index
  FileKnowledgeExtractor(...)      instantiated once, reused per file
  HierarchySummarizer(...)         instantiated if --llm-summarize
  ProjectKnowledge()               empty container, filled incrementally
  save_knowledge()                 writes project_knowledge.json
```

### Per-File Extraction — `FileKnowledgeExtractor.extract(file_path)`

```
FileKnowledgeExtractor.extract(file_path, knowledge, base_path)
  file_path.read_text()            read raw source lines
  index.parse(abs_path, args)      libclang parses the file into a TU
      parse options:
        PARSE_DETAILED_PROCESSING_RECORD  (expose MACRO_DEFINITION cursors)
        PARSE_INCOMPLETE                  (tolerate missing headers)
        NOTE: PARSE_SKIP_FUNCTION_BODIES is NOT set
              → CALL_EXPR nodes visible for call-graph extraction
  _traverse(tu.cursor, ...)        walks the AST recursively (depth-capped at 30)
```

### AST Traversal — `_traverse(cursor, ...)`

```
for each child cursor:
  if child is a CONTAINER (namespace / class / struct / union):
      skip if system header
      recurse into it  (_traverse called again)
      if struct/class in THIS file → _extract_struct()
      continue

  if child is NOT from THIS file → skip (prevents duplication)

  dispatch by cursor kind:
    MACRO_DEFINITION     → _extract_macro()
    ENUM_DECL            → _extract_enum()
    TYPEDEF_DECL /
    TYPE_ALIAS_DECL      → _extract_typedef()
    FUNCTION_DECL /
    CXX_METHOD /
    CONSTRUCTOR /
    DESTRUCTOR /
    FUNCTION_TEMPLATE    → _extract_function()
```

### What Each Extractor Produces

```
_extract_function(cursor, lines, rel_path, knowledge)
    reads: cursor.spelling, cursor.result_type, PARM_DECL children
    builds: FunctionKnowledge(qualified_name, signature, file, line,
                              comment, calls=[])
    if cursor.is_definition():
        _collect_calls(cursor)     → walks CALL_EXPR nodes in the body
                                     filters out std:: / boost:: / __
                                     returns list of project callee qnames
    stores: knowledge.functions[qname] = FunctionKnowledge
    upgrade logic: if existing entry has no comment/calls, upgrade it

_extract_enum(cursor, lines, rel_path, knowledge)
    builds: EnumKnowledge(qualified_name, values={name: EnumValueKnowledge})
    each value: enum_value + inline/preceding comment
    stores: knowledge.enums[name]

_extract_macro(cursor, lines, rel_path, knowledge)
    skips: include guards (_H_ pattern), empty macros
    for function-like macros: _funclike_macro_body() extracts expansion body
    builds: MacroKnowledge(name, value, file, comment)
    stores: knowledge.macros[name]

_extract_typedef(cursor, lines, rel_path, knowledge)
    reads: underlying_typedef_type.spelling
    builds: TypedefKnowledge(name, underlying, file, comment)
    stores: knowledge.typedefs[name]

_extract_struct(cursor, lines, rel_path, knowledge)
    reads: FIELD_DECL children
    builds: StructKnowledge(qualified_name, members={field: StructMemberKnowledge})
    each member: field_type + inline/preceding comment
    stores: knowledge.structs[qname]  (also stores short name alias)
```

### Comment Extraction (used by all extractors)

```
_preceding_comment(lines, func_line_idx)
    walks up from func_line_idx-1 skipping blank lines
    handles // single-line block and /* */ block styles
    returns joined comment text

_inline_comment(line)
    scans the line for // outside string literals
    returns trailing comment text
```

### Optional LLM Summarization — `HierarchySummarizer`

```
Only runs when --llm-summarize flag is set.
4 passes, each makes LLM HTTP calls:

Pass 1 — Functions (summarize_functions)
    for each FunctionKnowledge with no comment:
        batch up to batch_size functions per LLM call
        SYSTEM: "write ONE sentence per function"
        stores result back into fk.comment

Pass 1b — Phases (summarize_phases)
    for each function that HAS a comment (documented enough):
        sends function body source to LLM
        SYSTEM: "break into 2-6 logical phases with start/end lines"
        stores: fk.phases = [{start_line, end_line, description}]

Pass 2 — Files (summarize_files)
    for each source file scanned:
        collects all function signatures + comments from that file
        one LLM call per file
        SYSTEM: "2-3 sentence description of this file's responsibility"
        stores: knowledge.file_summaries[rel_path]

Pass 3 — Modules (summarize_modules)
    groups files by parent directory
    for each directory (module):
        collects file summaries from that directory
        one LLM call per module
        SYSTEM: "2-3 sentence description of this module's responsibility"
        stores: knowledge.module_summaries[module_path]

Pass 4 — Project (summarize_project)
    if README.md exists: sends README content to LLM
    else: sends all module summaries
    one LLM call total
    SYSTEM: "overall project description"
    stores: knowledge.project_summary
```

### Output

```
save_knowledge(knowledge, out_path)
    serializes ProjectKnowledge to project_knowledge.json
    contains: functions, enums, macros, typedefs, structs,
              file_summaries, module_summaries, project_summary
```

---

## PHASE 2 — Flowchart Engine (`flowchart_engine.py`)

### Entry Point

```
run(config)
  _load_project_meta()             reads metadata.json → ProjectMeta(base_path, project_name)
  _load_functions()                reads functions.json → raw dict
  load_knowledge()                 reads project_knowledge.json → ProjectKnowledge (optional)
  _build_pkb()                     builds ProjectKnowledgeBase
  pkb.load_project_knowledge()     attaches ProjectKnowledge to PKB (if provided)
  filter non-header entries        _is_header_file() removes .h/.hpp etc.
  group by source file             by_file dict
  SourceExtractor(base_path)       instantiated once
  TranslationUnitParser(std, args) instantiated once
  LlmClient(url, model, ...)       instantiated once
  LabelGenerator(client, pkb, ...) instantiated once
  OutputWriter(out_dir)            instantiated once
  for each source file:
      for each function entry:
          _process_function(...)
      writer.write_file_result()
  writer.write_summary()
```

### PKB Construction — `_build_pkb()`

```
_build_pkb(functions_data, config)
    PkbCache(cache_dir).invalidate_stale()   removes stale cache files
    PkbCache.load()                          tries to load cached PKB
    if cache hit:
        pkb.from_dict()                      restores from cache, done
    else:
        pkb.build(functions_data)            iterates functions.json entries
            for each entry:
                FunctionEntry(key, qualified_name, file, line, end_line,
                              params, calls_ids, called_by_ids, ...)
                stored in pkb._functions[key]
        PkbCache.save()                      persists new PKB to disk
    cache key = MD5(functions.json content)[:16]
```

### Header File Filtering

```
_is_header_file(func_entry.file)
    Path(path).suffix in {'.h','.hpp','.hxx','.hh', ...}
    → True: skip entirely, no output written
    → False: proceed to _process_function()

Reason: headers cannot be parsed as standalone TUs.
        header-defined functions already appear as ACTION nodes
        in their callers' flowcharts.
```

### Per-Function Processing — `_process_function()`

```
_process_function(func_entry, pkb, source_extractor, tu_parser,
                  label_generator, config, base_path, project_knowledge)

Step 1 — Source extraction
    source_extractor.extract_by_lines(file, line, end_line)
        → source_code string (function body text)
    source_extractor.get_lines(file)
        → source_lines list (full file, cached)

Step 2 — Parse TranslationUnit
    source_extractor.abs_path(file)
    tu_parser.get_tu_full(abs_path)
        → cached or newly parsed TU
        parse options:
            PARSE_DETAILED_PROCESSING_RECORD
            PARSE_INCOMPLETE
            NOTE: PARSE_SKIP_FUNCTION_BODIES is NOT set here either

Step 3 — Resolve function cursor
    find_function_cursor(tu, func_entry, abs_path)
        (see Resolver section below)
        → ci.Cursor or None
        if None → raise RuntimeError

Step 4 — Build CFG
    CFGBuilder(source_lines, max_stmts, max_lines)
        _collect_assert_locations(source_lines)
            → frozenset of (line, col) pairs  (pre-scan, O(1) lookup)
    builder.build(func_cursor, func_entry)
        (see CFG Builder section below)
        → ControlFlowGraph

Step 5 — Enrich CFG nodes
    NodeEnricher(pkb, source_lines_by_file, knowledge)
    enricher.enrich(cfg, func_entry)
        (see Node Enricher section below)

Step 6 — Generate LLM labels
    label_generator.label_cfg(cfg, func_entry, source_code, base_path)
        (see Label Generator section below)

Step 7 — Validate CFG
    validate_cfg(cfg)
        checks: START node, END node, edge references, empty labels,
                reachability via _reachable()

Step 8 — Build Mermaid script
    build_mermaid(cfg)
        (see Mermaid Builder section below)

Step 9 — Validate Mermaid
    validate_mermaid(mermaid_script)
        checks: starts with "flowchart", unmatched quotes

Returns FlowchartResult(function_key, qualified_name, mermaid_script)
On any exception → FlowchartResult with error field set
```

---

## Resolver (`ast_engine/resolver.py`)

```
find_function_cursor(tu, func_entry, abs_path)

Strategy 1 — Direct position lookup  (fast path)
    _position_lookup(tu, abs_path, target_line, target_end, simple_name)
        for each filename in [tu.spelling, abs_path]:
            ci.File.from_name(tu, filename)
            probe positions: (target_line, col 1/5), next 5 lines at col 5
            ci.SourceLocation.from_position(tu, file, line, col)
            ci.Cursor.from_location(tu, loc)
            _is_function_match(cursor, simple_name, target_line)
                checks: cursor.kind in _FUNCTION_KINDS or _UNEXPOSED_KINDS
                        extent.start.line within ±_START_SLOP (10 lines)
                        cursor.spelling contains simple_name
            if no match on cursor itself:
                walk lexical parents (up to depth 25) via cursor.lexical_parent
                _is_function_match() on each parent
    returns cursor if found, else None

Strategy 2 — Full AST traversal  (comprehensive fallback)
    _visit(tu.cursor)   recursive DFS, skips system headers
        for each cursor of kind _FUNCTION_KINDS or _UNEXPOSED_KINDS:
            _accept(cursor)
                file_match: loc.file.name endswith target_file
                null_file_match: loc.file is None + start line proximity
                tight match: extent fully contains [target_line, target_end]
                loose match: start within ±10 lines AND name match
                _score(cursor, simple_name, target_line, target_end)
                    +100 exact name, +40 partial name
                    -abs(start_line - target_line)
                    +20 if is_definition()
                penalties: -15 loose, -10 null-file, -20 unexposed
    sort candidates by score, return best

Strategy 3 — Broad line-range scan  (last resort)
    _visit_broad(tu.cursor)
        accepts ANY cursor kind (not just function kinds)
        proximity: ±_BROAD_SLOP (25 lines)
        name: simple_name in spelling
        file penalty: -30 if file clearly wrong
        base score penalty: -50
    sort broad_candidates by score, return best

if all 3 strategies fail → logs WARNING, returns None
```

---

## CFG Builder (`ast_engine/cfg_builder.py`)

```
CFGBuilder.__init__(source_lines, max_stmts, max_lines)
    _collect_assert_locations(source_lines)
        _ASSERT_RE.finditer() on every line
        builds frozenset{(line, col)} of ASSERT call sites

CFGBuilder.build(func_cursor, func_entry)
    _new_node(START)
    get_function_body(func_cursor)  → COMPOUND_STMT cursor
    _process_compound(body_cursor, open_exits)
    _new_node(END)
    connect all remaining open_exits → END
    returns ControlFlowGraph

_process_compound(cursor, open_exits)
    iterates child cursors of a COMPOUND_STMT
    for each child:
        _is_assert_stmt(child, self._assert_locs)
            (cursor.extent.start.line, col) in assert_locs → skip
        dispatch by cursor.kind:
            IF_STMT           → _process_if()
            FOR_STMT          → _process_for()
            WHILE_STMT        → _process_while()
            DO_STMT           → _process_do_while()
            SWITCH_STMT       → _process_switch()
            RETURN_STMT       → _process_return()
            BREAK_STMT        → _process_break()
            CONTINUE_STMT     → _process_continue()
            CXX_TRY_STMT      → _process_try()
            anything else     → accumulated into ACTION buffer
                                flush() when buffer hits max_stmts or max_lines

_process_if(cursor, open_exits)
    _new_node(DECISION)
    recurse into THEN branch → _process_compound() or _process_stmt()
    if ELSE branch present: recurse into ELSE
    merges exits from both branches

_process_for / _process_while(cursor, open_exits)
    _new_node(LOOP_HEAD)
    recurse into body
    back-edge from body tail → LOOP_HEAD
    exits: loop_head "No" exit + any BREAK exits

_process_do_while(cursor, open_exits)
    process body first
    _new_node(LOOP_HEAD) at bottom
    back-edge → body start
    exits: LOOP_HEAD "No" + BREAK exits

_process_switch(cursor, open_exits)
    _new_node(SWITCH_HEAD)
    _process_case_stmts() for each CASE/DEFAULT
        each case: _new_node(CASE or DEFAULT_CASE)
        _is_assert_stmt() checked here too
        recurse into case body

_process_return(cursor, open_exits)
    flush() ACTION buffer
    _new_node(RETURN)
    dead_exit (no further connections from this node)

_process_break / _process_continue(cursor, open_exits)
    _new_node(BREAK or CONTINUE)
    stored separately for loop/switch exit wiring

_process_try(cursor, open_exits)
    _new_node(TRY_HEAD)
    process try body
    for each CATCH_STMT: _new_node(CATCH), process catch body
```

---

## Node Enricher (`enrichment/enricher.py`)

```
NodeEnricher.enrich(cfg, func_entry)
    src_lines = source_lines for func_entry.file
    for each node in cfg.nodes:
        _enrich_node(node, func_entry, src_lines)

_enrich_node(node, func_entry, src_lines)
    skip: START, END, BREAK, CONTINUE

    _resolve_calls(node.raw_code, func_entry.calls_ids)
        _CALL_PATTERN.findall(raw_code)  → candidate call names
        for each name: lookup in PKB by calls_ids
        returns: [{signature, description}]
        stores: node.enriched_context["function_calls"]

    _nearest_comment(src_lines, node.start_line)
        scans up from start_line for inline // comments
        stores: node.enriched_context["inline_comment"]

    _resolve_enum_context(raw_code, knowledge)
        extracts ALL_CAPS tokens from raw_code
        matches against knowledge.enums and knowledge.macros
        stores: node.enriched_context["enum_context"]
                node.enriched_context["macro_context"]

    _resolve_typedef_context(raw_code, knowledge)
        extracts identifiers, matches against knowledge.typedefs
        stores: node.enriched_context["typedef_context"]

    _resolve_struct_member_context(raw_code, knowledge)
        _MEMBER_ACCESS_RE.findall(raw_code) → field names
        matches against knowledge.structs[*].members
        stores: node.enriched_context["struct_member_context"]
```

---

## Label Generator (`llm/generator.py`)

```
LabelGenerator.label_cfg(cfg, func_entry, source_code, base_path)

    Build per-function static context:
        pkb.build_context_packet(func_entry, base_path)
            build_base_context_packet()
                _build_hierarchy_context()    [Project]/[Module]/[File] block
                _build_caller_context()       1-level upward, calledByIds
                _resolve_param_types()        enum/typedef meanings for params
                get_function_phases()         phase breakdown from scanner
            _build_callee_bfs_context()
                BFS up to 4 levels via calls_ids / fk.calls
                up to _MAX_CALLEES_PER_LEVEL (10) per level
                fallback: _extract_callee_from_source() for unknown callees
        pkb.get_function_phases(func_entry)

    Topological sort:
        _topo_sort(cfg)
            iterative DFS post-order
            detects back-edges (loop edges)
            returns (ordered_node_ids, back_edges)

    Region-aware batching:
        _make_region_batches(ordered_labelable, cfg, batch_size, back_edges)
            pred_count: count forward-edge predecessors only
            flush current batch at:
                merge points (pred_count > 1)
                DECISION / LOOP_HEAD / SWITCH_HEAD nodes
                batch_size reached
            _merge_small_batches()  merges 1-node batches with neighbour

    For each batch:
        _label_batch_with_split(batch, ...)
            calls _label_batch()
            if ALL attempts return no LLM response AND batch > 1:
                split in half, recurse (up to _MAX_SPLIT_DEPTH = 3)

    _label_batch(batch, func_entry, base_context, source_code, ...)
        Build batch-specific prompt:
            _extract_batch_callee_names(batch)
                reads node.enriched_context["function_calls"]
            pkb.build_targeted_callee_context(func_entry, callee_names)
                exact qname match then short-name fallback via
                _knowledge_by_short_name index
            _build_size_aware_prompt(batch, ...)
                Attempt 1: no source excerpt
                    build_user_prompt(..., source_code="")
                    if fits (≤ MAX_PROMPT_CHARS=6000): try adding excerpt
                        _extract_batch_source() → numbered lines ±SOURCE_PADDING
                        if with-excerpt version fits: use it
                Attempt 2: trim context packet
                    _trim_context(context_packet, CONTEXT_BUDGET=1200)
                    rebuild prompt with trimmed context
        Retry loop (range(1, max_retries)):
            client.generate(SYSTEM_PROMPT, prompt) → raw response
            if raw is None:
                no_response_attempts++
                last_failures = "LLM returned no response"
                continue
            _parse_partial(raw, remaining_ids)
                _extract_json(raw)  strips markdown fences, finds {}
                json.loads()
                validates: string type, non-empty, ≤ _MAX_LABEL_LEN (300)
                returns (accepted, failures)
            accumulate accepted labels
            if remaining empty → done
            else: append _build_retry_note(failures) to prompt
        After all retries:
            for remaining nodes: _fallback_label(node)
                rule-based: "Check: ...", "Loop: ...", "Return ..." etc.

    Coherence pass (≥ 5 nodes):
        _coherence_pass(cfg, func_entry, label_map, ordered_nodes)
            sends all labels in execution order to LLM
            SYSTEM: fix inconsistent terminology, passive voice
            merges improvements back into label_map

    _apply_labels(cfg, label_map)
        cfg.nodes[id].label = label for each id in label_map
    START node → "Start: <function_short_name>"
    END node   → "End"
```

---

## Mermaid Builder (`mermaid/builder.py`)

```
build_mermaid(cfg)
    lines = ["flowchart TD"]

    Node definitions (_topo_order BFS from entry node):
        _node_def(node)
            label = node.label or node.raw_code[:60] or node.node_id
            _enforce_line_length(label, max_chars=40)
                splits at <br/> boundaries, word-wraps long segments
            _escape_label(label)
                single-pass _NODE_LABEL_RE.sub() → #NNN; entity codes
                protects <br/> tags via _BR_PLACEHOLDER
            shape by node_type:
                START/END          → nodeId([label])   stadium
                DECISION/LOOP_HEAD/
                SWITCH_HEAD        → nodeId{label}     diamond
                CATCH              → nodeId[[label]]   subroutine
                everything else    → nodeId[label]     rectangle

    Edge definitions:
        _edge_def(edge)
            normalize_edge_label(edge.label)
                standardises Yes/No/True/False
                passes through case labels unchanged
            if label: "source -->|label| target"
            else:     "source --> target"
```

---

## Output Writer (`output/writer.py`)

```
OutputWriter.write_all(file_results)
    for each FileResult:
        if fr.flowcharts is non-empty:
            write_file_result(fr)
                out_name = Path(source_file).stem + ".json"
                _serialize_file_result(fr)
                    for each FlowchartResult:
                        {functionKey, name, flowchart}
                        + "error" field if error present
                json.dump(payload, out_path)
    returns list of written paths

OutputWriter.write_summary(file_results, total_functions, total_errors)
    writes _summary.json:
        {totalFunctions, totalErrors, files: [{sourceFile,
         flowchartsGenerated, errors}]}
```

---

## Data Models (`models.py`)

```
FunctionEntry       key, qualified_name, file, line, end_line,
                    params, calls_ids, called_by_ids, interface_id, description

ControlFlowGraph    function_key, qualified_name, source_file,
                    start_line, end_line, nodes{}, edges[], entry_node_id,
                    exit_node_ids[]

CfgNode             node_id, node_type (NodeType enum), raw_code,
                    start_line, end_line, label, enriched_context{}

CfgEdge             source, target, label

NodeType enum       START, END, ACTION, DECISION, LOOP_HEAD, SWITCH_HEAD,
                    CASE, DEFAULT_CASE, RETURN, BREAK, CONTINUE,
                    TRY_HEAD, CATCH

FlowchartResult     function_key, qualified_name, mermaid_script, error

FileResult          source_file, flowcharts[]

ProjectMeta         base_path, project_name
```

---

## Key Decision Points and Special Scenarios

### Scenario: Function defined in a header file (.h/.hpp)
```
run()
  _is_header_file(func_entry.file)  → True
  function is filtered out before by_file grouping
  no TU parsed, no output written
  INFO log: "Skipping N header-defined function(s)"
```

### Scenario: ASSERT macro in function body (UTIL_DEBUG_ASSERT, POS_ASSERT, etc.)
```
CFGBuilder.__init__
  _collect_assert_locations(source_lines)
    _ASSERT_RE.finditer() on every line  → frozenset{(line, col)}

_process_compound() / _process_case_stmts()
  for each child cursor BEFORE kind dispatch:
    _is_assert_stmt(child, self._assert_locs)
      (cursor.extent.start.line, col) in assert_locs  → True
      child skipped entirely — never becomes DECISION or ACTION node
```

### Scenario: LLM returns no JSON (cloud API / format issue)
```
_label_batch()
  raw is not None but _extract_json(raw) returns None
  all node_ids → failures["No JSON object found in LLM response"]
  next attempt: _build_retry_note(failures) appended to prompt
  after all retries: _fallback_label(node) for remaining nodes
    rule-based labels from raw_code
  WARNING logged: "Fallback labels applied for N node(s)"
```

### Scenario: LLM returns no response at all (context overflow)
```
_label_batch()
  client.generate() returns None
  no_response_attempts++
  prompt is NOT enlarged (retry note would make it worse)
  after all retries: all_no_response = True

_label_batch_with_split()
  if all_no_response AND batch > 1 AND depth < 3:
    split batch in half
    recurse each sub-batch independently
    WARNING: "Auto-splitting in half (depth N of 3)"
  if depth == 3 AND still no response: fallback labels applied
```

### Scenario: Cursor not found for a .cpp function
```
find_function_cursor() returns None after all 3 strategies
flowchart_engine._process_function()
  raise RuntimeError("Could not resolve cursor for ...")
  caught by outer except → FlowchartResult(error=str(exc))
  WARNING logged, processing continues for other functions
```

### Scenario: PKB cache hit (functions.json unchanged)
```
_build_pkb()
  PkbCache.invalidate_stale()  removes old pkb_*.json files
  PkbCache.load()
    MD5(functions.json)[:16] → cache filename
    file exists → json.load → pkb.from_dict()
  → skip pkb.build(), return immediately
  INFO: "PKB loaded from cache"
```

### Scenario: Large function exceeds prompt size budget
```
_build_size_aware_prompt()
  Attempt 1: build prompt without source excerpt
    total_chars = len(SYSTEM_PROMPT) + len(prompt_no_src)
    if ≤ MAX_PROMPT_CHARS (6000): try adding source excerpt
    if with-excerpt still fits: use it; else use no-excerpt version
  Attempt 2: if still too large:
    available = MAX_PROMPT_CHARS - SYSTEM_PROMPT - non-context chars
    _trim_context(context_packet, min(available, 1200))
      cuts at last newline before budget, appends "… [context trimmed]"
    rebuild prompt with trimmed context
  if still too large: DEBUG log, auto-halving will handle it upstream
```

---

## File Map

```
src/flowchart/
  project_scanner.py          Phase 1 entry point
  flowchart_engine.py         Phase 2 entry point

  ast_engine/
    parser.py                 SourceExtractor, TranslationUnitParser
    resolver.py               find_function_cursor() — 3-strategy resolver
    cfg_builder.py            CFGBuilder — AST → CFG

  enrichment/
    enricher.py               NodeEnricher — annotates CFG nodes with PKB context

  llm/
    client.py                 LlmClient — HTTP wrapper (Ollama + OpenAI formats)
    generator.py              LabelGenerator — batching, retry, coherence pass
    prompts.py                SYSTEM_PROMPT, build_user_prompt(), _build_node_list()

  mermaid/
    builder.py                build_mermaid() — CFG → Mermaid text
    normalizer.py             normalize_condition(), normalize_edge_label()
    validator.py              validate_cfg(), validate_mermaid()

  pkb/
    builder.py                ProjectKnowledgeBase — context packet construction
    cache.py                  PkbCache — MD5-keyed disk cache for PKB
    knowledge.py              ProjectKnowledge dataclasses (FunctionKnowledge, etc.)

  output/
    writer.py                 OutputWriter — JSON file writer

  models.py                   Core dataclasses (FunctionEntry, CfgNode, etc.)
  config.py                   EngineConfig dataclass
```
