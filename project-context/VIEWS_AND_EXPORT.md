# Phases 3 and 4 — views, the flowchart engine, the DOCX export

> **Project context — one part of it.** Start at [PROJECT_CONTEXT.md](../PROJECT_CONTEXT.md),
> the index: current state, how to read the context, every file. The sections below moved here
> from the single-file context on 2026-09-28, unchanged except link paths, and keep their numbers —
> "PROJECT_CONTEXT §N" still finds them. Some of it has drifted since: read the index's [What changed
> after the numbered sections](../PROJECT_CONTEXT.md#what-changed-after-the-numbered-sections) first.

**Sections:** [12. Phase 3 — `engine/run_views.py` + `engine/views/`](#12-phase-3--enginerun_viewspy--engineviews) · [13. The flowchart engine — `engine/flowchart/`](#13-the-flowchart-engine--engineflowchart) · [14. Phase 4 — `engine/docx_exporter.py`](#14-phase-4--enginedocx_exporterpy)

## 12. Phase 3 — `engine/run_views.py` + `engine/views/`

### Orchestration — [engine/run_views.py](../engine/run_views.py)

CLI:
```
python engine/run_views.py [--output-dir <dir>] [--selected-group <name>]
```

Loads model via `core.model_io.load_model(FUNCTIONS, GLOBALS, UNITS, COMPONENTS, optional=[DATA_DICTIONARY])`.

When a group is selected, run_views resolves the name case-insensitively
against `get_flat_groups(config)` and stuffs two extra keys into the config
dict that's passed down into views:

- `_analyzerSelectedGroup` = the resolved group name
- `_analyzerAllowedComponents` = sorted list of component names from that group's entry

It also calls `get_layer_components(config, resolved)` and passes the result to
`_filter_model_to_components(model, layer_comps)` — this filters all four model
dicts (functions/globals/units/components) to only entities in the same layer,
so cross-component call edges within the layer stay visible in the views.

Then it calls `views.run_views(filtered_model, output_dir, model_dir, config)`, and records what
it built for the export guard: `_record_derivation` writes `_derivations.json` in the output
directory — the views that ran, their components, the documents each was built for, and when the
inputs were read (2026-09-29; review handover §4.9).

### View dispatch — [engine/views/__init__.py](../engine/views/__init__.py)

```python
def run_views(model, output_dir, model_dir, config):
    views_cfg = (config or {}).get("views", {})
    for view_name, run_fn in VIEW_REGISTRY.items():
        default = view_name == "interfaceTables"
        val = views_cfg.get(view_name)
        enabled = default if view_name not in views_cfg else (val is not False)
        if enabled:
            with timed(view_name):
                run_fn(model, output_dir, model_dir, config)
```

`interfaceTables` is the only view enabled by default; the others must be
explicitly configured. Setting any view's value to `false` disables it.

Since then (the block above is the original): a doc type's `DOC_TYPE_VIEWS` entry forces its views
(SWE.4: `flowcharts`, `testSpecs`, `utExport`), `unitHeaders` is on by default too, and the choice
is its own function — `views_to_run(doc_type, config)` — so the derivation record can say which
document each view was built for. `run_views` returns the names it ran (2026-09-29).

An update's Phase 3 (2026-10-07e): `run_views --views a,b,…` runs only those of the views the doc type
needs (`run_views(…, only=)`), and `--rewrite-labels <request>` puts the charts whose labels are written
again into the config (`_analyzerRewriteLabels`, read by the flowcharts view). `run.py` takes both flags
and hands them to Phase 3 alone. The derivation record merges per view, so the views not run keep
their stamps.

The four view modules are imported at the bottom of `__init__.py` so their
`@register("name")` decorators populate `VIEW_REGISTRY`.

### View 1: `interfaceTables` — [engine/views/interface_tables.py](../engine/views/interface_tables.py)

Output: `output/interface_tables.json` (or `output/<group>/interface_tables.json`).
Full logic and column definitions: `docs/spec/SWE3_SPEC.md` — Interface Tables.

- Iterates `.cpp` units only; header-only units skipped.
- Filters by `_analyzerAllowedComponents` if set.
- Includes `PUBLIC` and `PROTECTED` functions and globals; excludes `PRIVATE`.
- Entries sorted by source line number within each unit.
- For each function: builds `callerUnits` / `calleesUnits` (all units including
  same-module). **3.15:** `sourceDest` (rendered as Source/Destination) lists
  **callers only** (external units; `"-"` if none) — each cross-unit relationship is
  documented once, from the provider (callee) unit's row. `calleesUnits` is still
  emitted as a JSON field but no longer feeds `sourceDest`.
- Enriches parameters with `range` from the data dictionary via `get_range()`.
- Function entries also carry `returnType` (verbatim from the model; `""` when
  absent → rendered as `VOID`). Globals have no `returnType`.
- Strips file extensions from `location.file`.
- Columns: Interface ID, Interface Name, Information, Data Type, Data Range,
  Direction (In/Out), Source/Destination, Interface Type.

### View 2: `unitDiagrams` — [engine/views/unit_diagrams.py](../engine/views/unit_diagrams.py)

One Mermaid `.mmd` (and optionally `.png`) per unit into
`output/unit_diagrams/`.
Full logic and layout rules: `docs/spec/SWE3_SPEC.md` — Unit Diagrams (REQ-UD-XX).

- `.cpp` units only; filtered by `allowed_modules` when set.
- Layout: partners on the left / right of the **yellow** module box in the centre,
  flowing left-to-right (In-oriented owned interfaces inbound on the left, Out-oriented
  outbound on the right; a mutual partner appears on both sides).
- **3.15:** only edges the unit **owns** (from `calledByIds`, i.e. its callers) are
  drawn; the callee/consumer loop (interfaces this unit *uses*, `callsIds`) is dropped —
  those edges render in the provider unit's own diagram, so every relationship appears
  once model-wide. 3.6 owner-orientation is unchanged; it now operates over the reduced
  (caller-only) edge set.
- The main unit is **blue with a thick border** (`mainUnit` class); sibling units in the module subgraph are blue thin (`internal` class).
- Edges labelled with `interfaceId` values, **blank-line separated** for multi-edge
  (`_edge_label` / `_LABEL_SEP` — see "Edge-label spacing" below).
- Self-calls (callee in the same unit) produce no edge.
- Functions published by a function-pointer table (`addressTakenByUnits`) also draw an
  edge to the registering/consuming unit — they have no caller function, so without it
  the relationship would never be drawn.
- Project root resolved from `dirname(model_dir)` (NOT `output_dir`) so
  grouped output paths work.
- PNG rendered by `mmdc` (mermaid-cli). 60s timeout per diagram.
- **Which mmdc (2026-10-01c).** Every mermaid render command is built by `utils.mmdc_command`
  (`_run_mmdc` and the behaviour view alike): the `minlag/mermaid-cli` docker image when it is
  loaded (never pulled) and a test drawing in it works (`utils.mermaid_in_docker`, once per
  process), else local mmdc as `mmdc_path` finds it. The image's `latest` is mermaid 11, local is
  10.9.5 — see the version caveats below.
- Header uses the **ELK renderer** (`%%{init: {'flowchart': {'defaultRenderer': 'elk'}}}%%`).
  See **"ELK renderer everywhere"** below for the rationale and the version caveats.

#### Edge-label spacing — the ELK options are a no-op here (2026-08-08)

Reported: *"function mapping is difficult to read in the Static Diagram, there is less
space between the lines/labels."* REQ-UD-05 puts every interface id for a unit pair on ONE
arrow, so a busy edge stacks 10+ ids in a single label; joined with a bare `<br/>` they
render as contiguous rows with no leading.

**Measured, do not re-litigate.** Rendering `Sample-Core_Core` (edges of 1 / 10 / 7 ids)
through the pinned mermaid **10.9.5**:

| variant | PNG |
|---|---|
| baseline | 1374 × 700 |
| `elk.spacing.edgeEdge` + `edgeLabel` + `edgeNode` + `nodeNode` + `layered.spacing.*` | **1374 × 700 — byte-identical** |
| blank-line label separator (text only) | 1374 × 1270 |
| both | 1374 × 1270 |

Mermaid 10.9.5 **silently ignores** the `elk.*` spacing options, so no config block was
added — it would be dead weight that reads as if it does something. Spacing lives in the
**graph text**, in `_edge_label(ifaces)`.

**The whitespace goes between GROUPS, not between rows.** ELK lays every edge's label out in
one column, so a uniform blank line between rows still let two arrows' ids run together —
the reader could see each id but not where one arrow's group ended. Ids on the SAME arrow
stay tight (`_ROW_SEP = "<br/>"`) and each label is padded above and below
(`_GROUP_PAD_ROWS = 2`), so Mermaid's grey label background reads as one block per arrow.
Padding rows are a single space; an empty string renders as no row at all.

The blank-line node-padding hack (`n_extra_lines`) was deliberately **left keyed to edge
count**. Re-keying it to label height was tried and rejected: padding of 10 and 18 lines
both rendered byte-identically to none, because once labels are tall the label column —
not the node — sets the height. Only an absurd 36 lines moved it, and that draws the unit
as a grotesque tall bar.

Not changed, per the user: no label splitting (REQ-UD-05 mandates the shared arrow), no id
capping (the diagram stays complete), no DOCX width change, and diagram height is
explicitly not a concern. A `to <partner>` header on each block was tried and **reverted**
(`76fa866` / `fb281cb`) — the ask was spacing, not relabelling.

**Private functions are now skipped when building edges.** `interface_tables.py` skips
`visibility == "private"`, but this view never did, so a function annotated `PRIVATE` in
source that still has cross-unit callers (explicit annotation wins in `_fn_is_private`) drew
an edge labelled with a `PIF_*` id that appears in no table — e.g. `PIF_LAYER1_FULL_
READWRITE_01/02`, `PIF_LAYER1_FULL_POINTRECT_01`, `PIF_LAYER1_FULL_TYPES_01`, all called
from `App|Main`. Table and diagram now agree.

`render_mermaid_cached` is content-addressed on the Mermaid text, so changed text
re-renders automatically; no cache wipe needed.

#### ELK renderer everywhere (2026-07-14)

**All** non-placeholder diagram generators now emit the ELK renderer directive
`%%{init: {'flowchart': {'defaultRenderer': 'elk'}}}%%`, replacing the older dagre
headers (`splines: 'ortho'` on unit diagrams; `ranksep`/`nodesep` on the three
component diagrams in [src/docx_exporter.py](../src/docx_exporter.py)). Flowcharts
([builder.py](../src/flowchart/mermaid/builder.py)) were already ELK.

- **Why:** dagre's `splines: 'ortho'` silently fails to route edges orthogonally
  (peripheral edges render diagonal on both mermaid v10 and v11); ELK routes at true 90°.
- **Keep the header minimal** — do NOT copy the flowchart builder's *full* header, whose
  `theme: base` + `themeVariables` override `classDef` fills (nodes go white on v10). The
  one-line `defaultRenderer: elk` directive preserves `classDef` node colours on both versions.
- **Known caveat — inline subgraph `style … fill`** (the unit-diagram yellow module box and
  the component-container yellow box) is **dropped by ELK on mermaid 10.x** (renders default
  purple) but **preserved on 11.x**. Node `classDef` colours survive on both. The component
  container diagram has no edges, so ELK there is purely for consistency.
- **mmdc version caveat for diamonds:** v11's ELK renderer draws diagonal stubs off decision
  diamonds (flowcharts / future behaviour diagrams); **v10 gives clean 90°**. Rectangle-only
  diagrams (unit + component) are unaffected. Net tension: flowcharts want **v10**,
  subgraph-fill styling wants **v11**. The pipeline's [mmdc_path](../src/utils.py#L59) prefers the
  local `node_modules` mmdc (pinned to mermaid **10.9.5** via `@mermaid-js/mermaid-cli ^10.6.1`);
  a global mmdc (currently **11.x**) is only used as a fallback when local deps are absent —
  which is what silently changed flowchart rendering. Run `npm ci` before generating.
- Placeholder generators (`behaviour_diagram_generator.py`, `fake_flowchart_generator.py`,
  disabled behaviour-diagram view) were left on plain `flowchart TD` — not real product output.

### View 3: `behaviourDiagram` — [engine/views/behaviour_diagram.py](../engine/views/behaviour_diagram.py)

Generates one `.mmd` per (current function, external caller) pair via
`SequenceDiagramGenerator` in the
[engine/behaviour_diagram/](../engine/behaviour_diagram/) package.

> **behaviour diagram package replaced — 2026-08-22** (branch `fix/behaviour-diagram`, off `poc-4`; commit
> `9a22f0c` = the transcribed drop-in, later fixes uncommitted). All 7 modules (`generator`, `selector`,
> `tracer`, `mermaid_builder`, `llm_call_description`, `cli`, `utils`) were replaced wholesale with an
> external version; `__init__.py` was left as-is and still matches. What changed that callers care about:
> **(1) `filterMode` is now consumed** — `_get_filter_mode` reads `views.sequenceDiagrams.filterMode`,
> `create_diagram_selector` maps it to one of 5 selector classes. **Default changed** from the old
> `default`→`AllExternalCallersDiagramSelector` to **`skip_within_unit`**, which emits a diagram only when
> the target's own component spans 2+ units. On `SampleCppProject` (3 units, 3 separate components) that
> means **0 diagrams by default** where the old code produced 11 — verified, not theoretical. The old mode
> vocabulary (`all_external_callers`, `single_external_module`, `single_function`, `multi_unit_function`,
> `default`) is **gone**; those strings now fall through to `skip_within_unit` silently.
> **(2) `generate_all_diagrams` return shape changed** `List[str]` → `List[List[str]]` (one description
> list per diagram). This **fixes a silent docx bug**: `_add_behavior_description_table` guards on
> `isinstance(..., list)`, so the old string made the Requirements cell render **empty** in every Dynamic
> Behaviour table. **(3) `skip_within_unit` bridges** — `tracer.trace_forward_within_component` threads an
> `origin` arg so a skipped intra-unit hop re-attributes the downstream cross-unit edge to the last real
> boundary instead of orphaning it. The reachability filter in `generate_diagram_for_caller` is now
> redundant (its own comment says so) and prunes nothing.
> **(4) LLM path rewired to `llm_core`** — the transcribed code imported `_ollama_available` / `_call_llm`
> from `llm_client`, a module deleted in the version2→version3 refactor (it was `src/llm_client.py`, renamed
> to `engine/llm_enrichment.py`; `_ollama_available`→`llm_provider_reachable`, `_call_ollama`→`_call_llm`).
> Both imports failed → `except ImportError` → every description silently fell back to `"X calls Y"`.
> `CallDescriptionGenerator` now builds a real `LlmClient` via `from_config(load_llm_config(config))` into
> the `self._llm_client` field the code already declared but never used, gates on
> `llm.descriptions and llm_provider_reachable(...)` (same pattern as `docx_exporter.py:404`), calls
> `.generate()` inside `tokens.stage("behaviour.call_description")` so calls appear in the LLM report, and
> passes `_get_domain_context(config)` as the system prompt for Task 3.14 anchoring. `except ImportError`
> widened to `except Exception` — `llm_provider_reachable` **raises** `LlmConfigError` on a config missing
> `llm.defaultModel`, which would otherwise kill the whole view.
> **(5) A behaviour description is *call*-specific and is NOT the callee's function description.** Both the
> old code and an interim fix here used `functions_data[calleeFn]["description"]` as a fallback; that is
> wrong — it answers "what is this function" where the table asks "why does this caller call it", and the
> docx already prints the function description at `docx_exporter.py:1072/1143/1726`. Fallback chain is now
> **LLM call-description → `"X calls Y"`**, both call-shaped.
> **Bugs fixed in the transcribed code** (it did not run as delivered): `generator.py:322` joined unit ids
> with `_` while `mermaid_builder.py:247` splits on `/` → `IndexError` in **all 5 modes**;
> `generator.get_selection_summary` never returned `summary`; `SkipWithinUnitDiagramSelector.get_selection_summary`
> called `_get_units_in_call_chain`, which only exists on `MultiUnitFunctionDiagramSelector`.
> **Tests:** [tests/unit/test_behaviour_diagram_package.py](../tests/unit/test_behaviour_diagram_package.py) —
> 19 tests, the package's first coverage. Mutation-checked: reintroducing the `_`/`/` bug fails 12 of 19.
> Note `tests/unit/test_behaviour_diagram_generator.py`, described in the test-inventory table below, **does
> not exist** — that row is stale.
> **Known gap:** `generator.py` was transcribed from screenshots that ended at line 460; the closing
> `return summary` is reconstructed, and anything after it is unknown.

- Filtered to `allowed_modules` (only generates diagrams for functions inside
  the selected group, but uses the full model so external callers outside the
  group are still discovered).
- Excludes `private` functions.
- Filename: `current_key__caller_key.mmd` (sanitized via `safe_filename`).
- Each `.mmd` currently contains a fixed sample Mermaid string (placeholder).
- Renders to PNG via `mmdc` with the puppeteer config when present.
- Writes `output/behaviour_diagrams/_behaviour_pngs.json`:

```jsonc
{
  "_docxRows": {
    "<module>": {
      "<unit>": [
        { "currentFunctionName": "...", "externalUnitFunction": "...", "pngPath": "..." }
      ]
    }
  }
}
```

This file is what `docx_exporter.py` reads to build the Dynamic Behaviour
section.

### View 4: `flowcharts` — [engine/views/flowcharts.py](../engine/views/flowcharts.py)

Wraps the **real flowchart engine** under `engine/flowchart/`. Steps:

1. Resolves `out_dir = output_dir/flowcharts/`.
2. Builds clang args in three layers (in order):
   - Manual `clang.clangArgs` from config (if set).
   - `-I<basePath>` from `metadata.json` (always added).
   - **Layer-scoped paths** from `model/clang_include_paths.json` via
     `_resolve_layer_dirs(config, group_name, layer_paths)`: when a group is
     selected, only the dirs belonging to that group's layer are added (e.g.
     group "Sample" → Layer1 dirs only). When no group is selected, dirs from
     all layers are added. This prevents headers from unrelated layers
     polluting the include path for a single-group run.
3. If a group is selected, **filters `functions.json` by module-prefix** and
   writes `model/functions_<group>.json`. The filtered file is passed to the
   engine instead of the full one. (Module-prefix filtering, not units.json
   traversal — see Risk 2 in §16.)
4. Builds the engine command:
   ```
   python engine/flowchart/flowchart_engine.py
       --interface-json <functions[_group].json>
       --metaData-json  model/metadata.json
       --std            c++14
       --out-dir        output/flowcharts
       --llm-url        <baseUrl>/api/generate
       --llm-model      <defaultModel>
       --llm-num-ctx    <numCtx>
       [--knowledge-json model/knowledge_base.json]
       [--clang-arg=... ]+
   ```
5. Runs the subprocess with `cwd=project_root`. Logs full argv on launch.
6. When `renderPng: true`, walks every per-unit JSON in `out_dir`, writes a
   temp `.mmd` per `(unit, function)`, calls `mmdc` (with puppeteer config if
   present), captures the PNG to `<unit>_<func>.png`, deletes the temp file.
   Progress is reported via `core.progress.ProgressReporter`.

   Since then (the step above is the original): the PNG comes from the DOT through
   `render_dot_cached` (the picture cache), and **only for the charts the directory's SWE.3
   document prints** (2026-10-07f, `_pictures_to_draw`): each public function's flowchart and its
   private callees', by the exporter's own rule — `docx_common.printed_flowcharts`, read from the
   `interface_tables.json` beside it and the model; the exporter prints by `flowchart_section` and
   `private_callee_flowcharts` from the same module. Hidden functions count (hiding is Phase 4's
   alone). The other charts keep their JSON, labels and web SVG. Without interface tables to read,
   every chart is drawn as before; a chart an incremental run carried is drawn when it is printed
   and has no picture on disk.

---

## 13. The flowchart engine — `engine/flowchart/`

A self-contained C++ → Graphviz **DOT** CFG generator (switched from Mermaid
2026-07-27; the `FlowchartResult.mermaid_script` field name is kept for schema
compat but carries DOT). Invoked as a subprocess by the `flowcharts` view but
can also run standalone.

### Label policy (2026-08-10)

**A label is descriptive prose that names every function the node calls, each
written `Name()` with arguments stripped.** Held constant: the content (every
call present, uniform `Name()` form). Not constant: the phrasing — the name
goes where the code puts it, because `via X()` misattributes the action
whenever the callee only supplies an object rather than performing the work.

| C++ shape | What the call does | Label |
|---|---|---|
| `sz = functionJ();` | supplies a value | Get somethingZ by calling `functionJ()` |
| `functionX()->timeSlot = False;` | supplies the object written | Set the time slot in `functionX()` to False |
| `sa = &functionA()->sa;` | supplies the object read | Update sa with the address of sa in `functionA()` |
| `ServerReplicate(part, id);` | **is** the action | Replicate partition state with `ServerReplicate()` |

Enforced in three places that must agree, all keyed off
[cpp_tokens.py](../engine/flowchart/cpp_tokens.py): the enricher declares
`call_names`, the prompt requires every one of them, and
`enforce_call_names` verifies/repairs afterwards. **Not named** (each has its
own prompt rule): logging macros, assertions, casts, constructors.

### Subpackage layout

```
engine/flowchart/
  flowchart_engine.py        Main entry, orchestrates per-function pipeline
  project_scanner.py         Standalone scanner that builds project_knowledge.json
  config.py                  EngineConfig dataclass (CLI defaults)
  cpp_tokens.py              Single definition of "a call": CPP_KEYWORDS,
                             extract_call_names / render_call / short_name
  models.py                  CfgNode / CfgEdge / ControlFlowGraph / FunctionEntry / …
  ast_engine/
    parser.py                SourceExtractor + TranslationUnitParser
    cfg_builder.py           libclang AST → ControlFlowGraph (handles ASSERT, goto/label, switch/break)
    resolver.py              find_function_cursor — resolve qn+location to a cursor
  pkb/
    builder.py               ProjectKnowledgeBase (in-memory index, BFS callee context)
    knowledge.py             ProjectKnowledge dataclass + load/save
    cache.py                 PkbCache (disk cache keyed by functions.json hash)
  enrichment/
    enricher.py              NodeEnricher — attach PKB context to CFG nodes
  llm/
    prompts.py               SYSTEM_PROMPT + build_user_prompt
    generator.py             LabelGenerator — batched LLM labeling with auto-halving
  mermaid/
    builder.py               build_mermaid(cfg) → Mermaid string
    normalizer.py            label sanitisation
    validator.py             validate_cfg + validate_mermaid
  output/
    writer.py                Per-file JSON output + _summary.json
  tests/
    test_cfg_topo.py         CFG topology asserts
    diagnose_assert.py       Repro for the ASSERT-pollutes-CFG bug
```

### Per-function pipeline (`_process_function`)

1. **Source extraction** — `SourceExtractor.extract_by_lines(file, line, end_line)`
   reads the function body text by line range.
2. **TU parse** — `TranslationUnitParser.get_tu_full(abs_path)` parses the
   file with bodies (cached per-file).
3. **Cursor resolution** — `find_function_cursor(tu, func_entry, abs_path)`.
   Strategy 1 is direct position lookup using `loc.file.name == abs_path`;
   fallback strategies use qualified name + line range.
4. **CFG build** — `CFGBuilder.build(func_cursor, func_entry)`. Walks AST
   traversal that distinguishes statement nodes (`IF_STMT`, `FOR_STMT`,
   `WHILE_STMT`, `DO_STMT`, `CXX_FOR_RANGE_STMT`, `SWITCH_STMT`, `RETURN_STMT`,
   `BREAK_STMT`, `CONTINUE_STMT`, `CXX_TRY_STMT`, `GOTO_STMT`, `LABEL_STMT`)
   from sequential statement segments. Rules are absolute:
   - structural truth comes only from the AST (no heuristics)
   - loop back-edges are explicit
   - `break` → after-loop / after-switch
   - `continue` → loop head
   - `return` → END node
   - all open exits connect to the next sequential node
5. **ASSERT filtering** — `_collect_assert_locations(src_lines)` pre-builds a
   `frozenset` of `(line, col)` pairs by regex-scanning source for assert
   macro calls (`ASSERT(`, `static_assert(`, `(?:[A-Z][A-Z0-9_]*_)*ASSERT(`).
   The CFG traversal then does O(1) lookups against
   `cursor.extent.start.line/.column` (NOT `get_expansion_location()`, which
   was the original bug source) and skips ASSERTs so they don't pollute the
   diagram. **Do not modify this code without re-running
   `tests/diagnose_assert.py`** — the linter has previously reverted this fix.
6. **Enrichment** — `NodeEnricher.enrich(cfg, func_entry)` attaches PKB
   context (callee descriptions, type meanings, project-knowledge comments).
   Also emits **`call_names`** — every call in the node via
   `cpp_tokens.extract_call_names`, in source order, receiver kept
   (`doc.AddMember`), with known type names excluded so constructors don't
   register as calls. This is the list the label naming rule is written
   against; `function_calls` is a PKB-resolved subset capped at 3 and carries
   descriptions only.
7. **Optional CFG simplification** (version3) — if
   `llm.enrichment.cfgSimplification=true` and the CFG has >15 labelable
   nodes, `LabelGenerator._simplify_cfg()` asks the LLM for a merge/drop
   plan: `{"merge": [["N3","N4"], ["N7","N8","N9"]], "drop": ["N12"]}`.
   Safety constraints enforced AFTER the LLM replies (regardless of what it
   proposed):
   - Only merges **strict linear chains**: each inner node has exactly one
     predecessor (= its prev-in-group) and one successor (= its next-in-group).
     `_is_linear_chain()` verifies this on the live `cfg.edges`.
   - Only drops nodes with one incoming and one outgoing edge
     (`_has_single_in_single_out`). Merges are capped at 2–4 nodes per group.
   - Only touches `NodeType.ACTION` — decisions, loops, switches, returns,
     breaks, continues, and case nodes are never offered to the LLM and
     never mutated.
   - Uses `extract_and_validate()` to parse the JSON plan.
8. **LLM labeling** — `LabelGenerator.label_cfg(cfg, func_entry, source, base)`
   batches up to `BATCH_SIZE=4` nodes per LLM call. Two failure modes are
   handled differently:
   - Empty response (`raw=None`, prompt > num_ctx) → retry **without** any
     "retry note" (would inflate the prompt). After all retries fail, the
     batch is auto-halved and recursed up to depth 3. This adapts to any
     model's actual context window without manual tuning.
   - Bad JSON / missing nodes → append a targeted retry note with the failing
     `node_id`s so the LLM can correct precisely.
   Version3: JSON parsing routes through `llm_core.structured_output.parse_label_response()`
   which handles markdown fences, trailing commas, single quotes, and
   partial/missing braces — significantly fewer fallback labels than the
   version2 ad-hoc `_extract_json()` path. `MAX_PROMPT_CHARS=6000` stays as
   a legacy-standalone fallback only; the coherence pass now sizes via
   `ContextBudget(task="cfg_coherence")` when `max_context_tokens` is
   threaded in (it is, from `flowchart_engine.py`).
9. **Coherence pass** — `_coherence_pass()` normalises terminology and
   phrasing across all labels in one LLM call. Version3: prompt strengthened
   (inconsistent terminology, passive voice, too-literal vs. too-abstract
   labels, decision nodes without "?"). Sized via
   `_fits_coherence_budget()` using the authoritative
   `self._max_context_tokens` — no more `getattr(client, "_num_ctx", 8192)`
   fallback.
9b. **Call-name enforcement** — `generator.enforce_call_names(cfg)`,
    deterministic, no LLM. Runs **last**, after the coherence pass, so a
    coherence rewrite can't strip a name back out. Two steps per node:
    normalise existing mentions to `Name()` (arguments stripped, bare
    identifiers parenthesised), then append names with no mention at all as a
    trailing `<br/>Calls: X()` segment. The appended form is deliberately not
    a connector phrase — the pass can't know where the name belongs in the
    sentence, and inventing one produces the mechanical "… via X()" filler the
    prompt forbids. **Prose safety:** a bare word is only converted when
    `_is_identifier_shaped` says it can't be English (qualified/member,
    snake_case, or an internal capital), otherwise "Validate the request"
    becomes "Validate() the request"; ambiguous bare words count as absent and
    are appended instead. Also normalises the raw-C++ fallback labels
    (`result = add(result, a)` → `result = add()`). A per-function append count
    is logged — a high count means the prompt isn't landing, which is the thing
    to fix, not this pass.
10. **Validation** — `validate_cfg(cfg)` then `validate_mermaid(script)`.
    Failures are logged at WARNING but don't abort the run.
11. **Build DOT** — `build_dot(cfg)`. (`_escape` turns `<br/>` into the DOT
    line-break sequence, which is how the enforcement pass's appended segment
    renders.)

Steps 8–9b are `_label_chart` (2026-10-07e): the cached labels (keyed by the source and the model)
when every node is covered, else the LLM's, cached unless a node fell back. Before the first chart the
LLM labels, `_with_current_descriptions` lays the model's descriptions over the knowledge base Phase 2
wrote — the context packet reads a chart's purpose and its callers', callees' and globals' descriptions
there, and a reviewer's save changes the model alone. **Writing charts again** (an update, FAST_WORD_FILE_UPDATES
P5): `--rewrite-labels <request>` names charts that skip the cache; their new labels replace the cached
ones (`_replace_labels`) and each is appended to the request's report — unless a node fell back, when
the chart keeps its earlier labels. `--only-rewrite` charts those functions alone; the flowcharts view
then splices them into the stored unit files (`_splice_rewritten`) and puts every other file back.
`_flush_labels` lands the label cache's buffered writes once every chart is labelled: without it a run's
last minute of labels was lost at exit.

### `LIBCLANG_PATH` env var (feat/test-framework)

At import time, `flowchart_engine.py` checks `os.environ["LIBCLANG_PATH"]`.
If set (and the path is a file), it calls
`clang.cindex.Config.set_library_file(path)` before any libclang call.
`run.py` sets this env var from `clang.llvmLibPath` in config so the value
propagates automatically into the flowchart engine subprocess.

### LLM client construction + banner + enrichment config (version3)

At the top of `run()`, [engine/flowchart/flowchart_engine.py](../engine/flowchart/flowchart_engine.py)
calls `_load_analyzer_llm_config()` which walks `cwd` and one parent for
`engine/config/config.defaults.json`, loads it with `utils.load_config`, then resolves it
strictly with `utils.load_llm_config` (raising `LlmConfigError` with the
specific failing field on any invalid input). The resolved llm_cfg is
displayed via `format_llm_config_banner()` before any real work begins, so
the subprocess is self-documenting.

`_build_llm_client(config, llm_cfg_resolved)` then builds the `LlmClient`:
- When the analyzer config is reachable: `llm_core.client.from_config(llm_cfg)` —
  provider, custom headers, retries, and API key all flow through. CLI
  `--llm-num-ctx` still wins if it is explicitly larger than the config
  value (useful for one-off standalone invocations).
- When running outside the analyzer tree: falls back to the legacy
  positional constructor (Ollama only, backwards compatible).

The `LabelGenerator` is constructed with two version3 parameters threaded
from the resolved config:
- `enrichment_config=llm_cfg["enrichment"]` — feature flags.
- `max_context_tokens=resolve_max_tokens(llm_cfg)` — authoritative
  budget used by the coherence pass and CFG simplification pass. This
  replaces the old `getattr(client, "_num_ctx", 8192)` fallback.

A log line `Coherence/simplify budget = N tokens (provider=…)` is printed
right after the banner.

### PKB caching

`pkb.cache.PkbCache` keys on the SHA of `functions.json` text. If unchanged,
the in-memory PKB is restored from disk under `.flowchart_cache/`. Pass
`--no-cache` to force rebuild.

### project_scanner.py (separate tool)

A standalone scanner that walks every C++ source file under `--project-dir`
with libclang and writes a richer `project_knowledge.json`: function
signatures + Doxygen comments + call graph + enum definitions with per-value
comments + `#define`s with values + typedefs + struct member fields. With
`--llm-summarize`, also runs the 4-level hierarchy summarization.

This tool is **not** in the standard run.py pipeline — it's used to bootstrap
a richer knowledge base for projects where the analyzer's `model_deriver`
output isn't enough. The flowchart engine accepts either kind of knowledge
file via `--knowledge-json`.

### Outputs

Per source file: `out_dir/<source_file_name>.json` containing
`[{name, flowchart}, …]`. Plus `_summary.json` with per-file counts.

---

## 14. Phase 4 — `engine/docx_exporter.py`

### Entry: `export_docx(json_path, docx_path, selected_group)`

- `json_path` defaults to `output/interface_tables.json`.
- `artifacts_dir = os.path.dirname(json_path)` — every PNG path, every
  flowchart JSON, every behaviour-pngs file is resolved relative to this.
  This is the critical fix for grouped output (`output/<group>/`).
- Loads `model/functions.json`, `globalVariables.json`, `units.json`,
  `dataDictionary.json`.
- Loads abbreviations from `config.llm.abbreviationsPath`.
- Iterates modules in sorted order.

### Function hiding (Phase 4 only, no Phase 3 needed)

Functions can be hidden from DOCX output without re-running Phase 3.
The `hidden` flag lives in `model/functions.json` per function entry:
`{"hidden": true, ...}`. It is set via the UI (§14b) and never written
by any pipeline phase.

At the top of `export_docx`, after loading `functions_data`:
- `_hidden_fids` — set of all fids where `hidden == True`.
- `_hidden_by_mod_unit` — `(module, unit) → set of base function names`,
  built from `_hidden_fids` for the Dynamic Behaviour lookup.

What is filtered in Phase 4:

| Output | Filtered? |
|---|---|
| Interface table entries | ✅ fid not in `_hidden_fids` |
| Per-function DOCX section + its flowchart | ✅ iface excluded before loop |
| Private callee flowcharts | ✅ callee_fid not in `_hidden_fids` |
| Dynamic Behaviour entries | ✅ currentFunctionName in `_hidden_by_mod_unit` |
| Component/Unit description table | ✅ uses already-filtered interfaces |
| Unit diagram PNG | ❌ pre-rendered in Phase 3 |
| Behaviour diagram PNG | ❌ pre-rendered in Phase 3 |
| Module container/header PNG | ❌ pre-rendered in Phase 3 |

Pre-rendered PNGs from Phase 3 are embedded as-is — they still show
hidden functions as nodes. Only text sections are filterable in Phase 4.

### CLI

```
python engine/docx_exporter.py [json_path] [docx_path] [--selected-group <name>]
```

`--selected-group` is stripped before positional parsing.

### Cover page (`_build_cover_page`)

Rendered as the first page before the TOC. Layout (top → bottom):

- **Project name** — 54 pt, bold, navy (`#1E3C78`), thick double underline, right-aligned. Read from `model/metadata.json → projectName`.
- **Subtitle** — `"Software Detailed Design Specification  —  <group>"` (16 pt bold navy, right-aligned). Group label: `selected_group` with `-`→space, or joined `selected_components`, or `"All Components"`.
- **Version** — `"Version 1.0.0"` (12 pt, right-aligned). Hardcoded default; override via `_build_cover_page(..., version=...)`.
- **Date** — `YYYY-MM-DD` of export run (12 pt, right-aligned).
- **Copyright image** — `assets/copyright.png`, 2.6 in wide, left-aligned. Falls back to plain text if file missing.
- **Copyright text** — one line below the image, 8 pt, gray (`#808080`), left-aligned. Defaults to `"© <year> All Rights Reserved."`. Override via `config.docx.copyrightText`.
- **Bottom arc** — `assets/bottom_arc.png`, full body width, centered. Omitted if file missing.
- Page break added after cover before TOC.

**OOXML note:** `w:spacing` must appear before `w:jc` in `w:pPr` — Word silently ignores alignment if order is wrong. Both XML manipulation and `para.alignment` API are set together as belt-and-suspenders.

### DOCX section structure

```
[Cover page — see above]
[Table of Contents — _add_toc(); field ' TOC \o "1-4" \h \z \u '; covers Headings 1-4;
 w:updateFields=true auto-updates on open; placeholder text shown until field is refreshed]
1 Introduction                                                 (Heading 1)
  1.1 Purpose   — text from config.docx.introduction.purpose
  1.2 Scope     — scopeIntro text, then component names (• bullet each),
                  then scopeBody text, then scopeItems (- dash each)
                  (config.docx.introduction.scopeIntro/scopeBody/scopeItems)
  1.3 Terms, Abbreviations and Definitions
2 <ModuleName>                                                 (Heading 1)
  2.1 Static Design                                            (Heading 2)
    [Module container diagram — light-yellow subgraph box, blue unit nodes inside (TB)]
    [Horizontal rule]
    [Header dependency diagram — BT flowchart, header nodes at top, source nodes below]
    [Component / Unit table — Component | Unit | Description | Note]
    2.1.1 <UnitName>                                           (Heading 3)
      [Unit diagram PNG if available]
      2.1.1.1 unit header                                      (Heading 4)
        Path: <path/without/extension>
        [Unit header table — globals/typedef/enum/define | information]
      2.1.1.2 unit interface                                   (Heading 4)
        [Interface table — 8 cols, see below]
      2.1.1.3 <UnitName>-<FuncName>                            (Heading 4)
        [Flowchart table — 5 rows, see below]
      ... one Heading-4 sub-section per **function** (globals excluded) ...
  2.2 Dynamic Behaviour                                        (Heading 2)
    2.2.1 <UnitName> - <FuncName> (<ExternalUnitFunc>)         (Heading 3)
      [Behaviour description table]
      [Behaviour PNG if rendered]
N Code Metrics, Coding Rule, Test Coverage                     (Heading 1)
Appendix A. Design Guideline                                   (Heading 1)
```

### Module container diagram (`_build_module_container_mermaid`)

Mermaid TB `subgraph` — light-yellow container (`fill:#fef9c3, stroke:#fbbf24`)
holding all unit nodes as blue boxes (`fill:#2563eb`). Rendered into
`artifacts_dir/module_container_diagrams/<module>.png` at 6 inches wide.
Appears first under `{N}.1 Static Design`, followed by a horizontal rule.

### Header dependency diagram (`_build_module_header_dependency_mermaid`)

Mermaid BT flowchart (no outer box): header nodes at top (dark, `fill:#1e293b`),
source file nodes at bottom (blue, `fill:#2563eb`), edges `source → header`.
Node labels strip extensions — headers show `<name>\nHeader`, sources show `<name>`.
Only same-module headers are shown; folder prefix is derived from unit paths
(not module name, since config module name ≠ filesystem folder). Rendered into
`artifacts_dir/module_header_dependency_diagrams/<module>.png` at 6 inches wide.
Appears after the horizontal rule, before the Component/Unit table.
`includedHeaders` field populated in `units.json` by `model_deriver._read_local_includes`
during Phase 2 — re-run from Phase 2 after any source tree changes.

### Component/Unit table (`_add_component_unit_table`)

4 columns: Component | Unit | Description | Note

Description derivation:
1. If LLM available → `llm_enrichment.get_unit_description(unit_name, fn_items, gv_items, config, abbreviations)` produces a summary (≤25 words).
2. Fallback → join all function/global descriptions, truncate to 120 chars.
3. Final result truncated to **140 chars max** (hardcoded).
4. Note column is always `N/A`.

The Component column is merged vertically across all unit rows of a module.

### Unit header table (`_build_unit_header_table`)

2 columns: `global variables / typedef / enum / define` | `information`

Rows from:
- **Globals** (`globalVariables.json`) — private excluded, declaration read
  from source line, value from `initializer`.
- **Typedefs** (`dataDictionary`) — declaration snippet from source; info
  column shows enum values for typedef-to-enum, struct description for
  typedef-to-struct, else `NA`. Multiple aliases from the same declaration
  (`typedef struct {…} one_s, *one_s_2;`) are suppressed: libclang stores
  each alias as a separate `TYPEDEF_DECL` at the line where the alias name
  appears (e.g. `} one_s, *one_s_2;`), so `_read_decl_snippet` returns
  `"-"` for those entries (line doesn't start with `typedef`). Any typedef
  whose snippet is `"-"` is skipped entirely — the full declaration is
  always emitted by the entry at the actual `typedef struct` line.
- **Enums** — declaration snippet; info column is `NAME=value, …`.
- **Defines** — full macro text; info column is the value. Include guards
  (`#define __FILE_NAME_H__` — empty value, name matches
  `^_*[A-Z][A-Z0-9_]*(?:_H|_HPP)_*$`) are skipped.

Struct/class entries are NOT shown directly — only via `typedef struct {…}
Name;`. Deduplicates by declaration text, preferring richer `name=value` info.

### Interface table (`_add_interface_table`)

8 columns: Interface ID | Interface Name | Information | Data Type |
Data Range | Direction(In/Out) | Source/Destination | Interface Type

- Functions: `Data Type` = `; `.join of param types (or `VOID` if none), then a
  second line `return: <returnType>`. `void` (any casing) is displayed as `VOID`;
  other types render verbatim. `Data Range` = `; `.join of param ranges from
  `get_range()`, then a second line `return: <returnRange>` where `returnRange` is
  `get_range(returnType)` (the view enriches each function entry with `returnRange`;
  a void return shows range `NA`, not a range value). When a function has **no** captured return type the
  `return:` line is omitted from both columns (not shown as `VOID`/`NA`). The `\n`
  renders as a Word line break in DOCX and needs `whitespace-pre-line` on the web
  cell (`DocumentInspectorPage.tsx`); the compare/diff view flattens it to a space
  via `_table_to_markdown`. Return type is captured verbatim from Clang's canonical
  spelling (`parser.py` unchanged — a `VOID` **macro** resolves to `void` via
  `--macros`, then the renderer uppercases it back to `VOID`).
- Globals: `Data Type` = variable type; `Data Range` from data dictionary.
- Private functions/globals are already filtered out by Phase 3.
- `Interface Name` is generated by `_readable_label(qn)` (strip prefixes,
  underscores → spaces).

### Flowchart table per interface (`_add_flowchart_table`)

The per-interface loop (`2.1.1.3`, `2.1.1.4`, …) iterates **functions only**
— global variable entries are excluded from this loop even though they appear
in the interface table above. Globals have no flowchart section.

5-row table: Requirements | Risk | Capacity(Density) | Input Name | Output Name

Requirements cell contains:
1. Function description (or function name as fallback).
2. The function's own flowchart (PNG if available, else Mermaid text)
   labelled with the signature `returnType functionName(params)`.
3. Each **private callee's** flowchart labelled with its signature, deduped
   per unit via a `rendered_private_fids` set so the same private helper isn't
   embedded twice.

Input/Output Name = `inputName` / `outputName` from
`functions.json`. Risk = `"Medium"` (hardcoded). Capacity(Density) =
`"Common"` (hardcoded).

### Dynamic Behaviour section

Reads `artifacts_dir/behaviour_diagrams/_behaviour_pngs.json`. For every
`(module, unit, [{currentFunctionName, externalUnitFunction, pngPath}])`:
- Heading: `<sec>.2.<idx> <unitName> - <functionName> (<externalUnitFunction>)`
- Behaviour description table (`_add_behavior_description_table`) with input/output names from the model.
- Embedded PNG if `pngPath` is non-empty and exists.

---

