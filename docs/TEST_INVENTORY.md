# Test Inventory

**421 tests total** — 268 unit (7 xfail) · 145 e2e passing · 8 e2e failing (flowcharts — fake generator) · 18 e2e errors (flowchart fixture setup)

> Two layers: **unit** (instant, no pipeline) and **e2e** (pipeline runs once, checks all artifacts + DOCX).

```bash
pytest tests/unit/   # instant, no pipeline
pytest tests/e2e/    # pipeline runs once, checks everything
pytest tests/        # everything
```

Coverage: **~69–76% total** (full suite with pipeline). Unit-only: ~26%.
See `tests/coverage_html/index.html` for the line-by-line report.

---

## Unit tests (`tests/unit/`)

No pipeline, no network. All external calls mocked.

| File | Classes | What it tests |
|---|---|---|
| `test_cli.py` | ResolveGroupName · RunPyCli | `_resolve_group_name` case-insensitivity; CLI exit codes and error messages for bad flags |
| `test_core_config.py` | LoadLlmConfigValid · LoadLlmConfigErrors · EnvOverrides · FormatBanner | `load_llm_config`: all required/optional fields, all `LlmConfigError` cases, every env-var override, banner format |
| `test_core_group_planner.py` | ResolveGroupName · PlanRunsNoGroups · PlanRunsAllGroups · PlanRunsSelectedGroup | `plan_runs`: all three dispatch shapes, `--from-phase` translation, `--use-model`, unknown group error |
| `test_core_model_io.py` | Constants · ModelFileMissing · ModelFilePath · ModelFilesPresent · ReadModelFile · LoadModel · WriteInPlace · WriteAtomic | Every public function in `model_io`: path helpers, read/write, required vs optional, atomic write, round-trip |
| `test_flowchart_generator.py` | FunctionIdToUnitKey · SafeFilename · BuildFlowchartForFunction*(xfail)* · Run | `fake_flowchart_generator`: key splitting, filename sanitization, run() output shape and Mermaid validity |
| `test_interface_tables_view.py` | StripExt · FidToUnit · BuildInterfaceTables | `_build_interface_tables`: public/private filtering, range enrichment, sorting, allowed_modules, all entry keys |
| `test_llm_client.py` | Constructor · GenerateOllama · GenerateOpenAI · Call · FromConfig | `LlmClient`: provider validation, endpoint building, generate/call/retry logic, from_config builder |
| `test_llm_core_budget.py` | TaskRatios · ContextBudgetConstruction · Allocate · Sections · Remaining · ResolveMaxTokens | `TASK_RATIOS` sum invariants; `ContextBudget` arithmetic; `resolve_max_tokens` for Ollama/OpenAI/explicit/clamp |
| `test_model_deriver.py` | IdSeg · ReadableLabel · PropagateGlobalAccess · EnrichBehaviourNames · EnrichInterfaces | Pure model-deriver helpers: identifier transformations, transitive global propagation, behaviour name heuristics, interfaceId format |
| `test_unit_diagrams_view.py` | UnitPartId · EscapeLabel · FidToUnit · BuildUnitDiagram | `_build_unit_diagram`: Mermaid LR output, subgraph label, mainUnit/internal classes, outgoing/incoming cross-unit edges, multi-iface edges, self-call exclusion, external caller/callee layout, allowed_modules |
| `test_utils.py` | StripJsonComments · StripTrailingCommas · LoadConfig · SafeFilename · ShortName · GetRangeForType · MakeUnitKey · GetRange | All pure helpers in `utils.py` and `core.config` JSONC parsers |
| `test_views_registry.py` | ViewRegistry · ResolveScript | `@register` decorator behaviour; `_resolve_script` default/absolute/relative path logic |

---

## E2E tests (`tests/e2e/`)

Pipeline runs **once** before the suite against `SampleCppProject`. Tests read `model/` and `output/` artifacts.

| File | What it checks |
|---|---|
| `test_model_json.py` | `functions.json`, `globalVariables.json`, `units.json`, `modules.json` — field presence, key format, interfaceId uniqueness, call-graph topology |
| `test_interface_tables.py` | `output/interface_tables.json` — see rule coverage below |
| `test_unit_diagrams.py` | `output/unit_diagrams/*.mmd` — Mermaid LR direction, subgraph labels, cross-module edge labels, Util/Core call-direction invariants, golden snapshot |
| `test_flowcharts.py` | `output/flowcharts/*.json` — one file per unit, `[{name, flowchart}]` shape, Mermaid validity, all expected public functions present |
| `test_docx.py` | `output/software_detailed_design_Sample.docx` — file exists, tables present, IF_ IDs, public names, direction values, embedded images, all section headings, flowchart/behaviour tables |

---

## xfail tests (7)

Marked `@pytest.mark.xfail` — define the contract the real generators must satisfy once wired.

| Test | Waiting on |
|---|---|
| `TestBuildFlowchartForFunction::test_returns_llm_response` | `fake_flowchart_generator` LLM seam |
| `TestBuildFlowchartForFunction::test_strips_code_fences` | `fake_flowchart_generator` LLM seam |
| `TestBuildFlowchartForFunction::test_fallback_on_empty_llm_response` | `fake_flowchart_generator` LLM seam |
| `TestBuildFlowchartForFunction::test_prompt_contains_source_code` | `fake_flowchart_generator` LLM seam |

---

## Rule coverage (from DESIGN_SPEC.md)

### Document Structure — `tests/e2e/test_docx.py`

| Requirement | Rule | Test | Status |
|---|---|---|---|
| REQ-DS-01 | Introduction sub-headings present (Purpose, Scope, Terms) | `test_introduction_section_headings` (parametrized) | Covered |
| REQ-DS-01 | Code Metrics heading present | `test_code_metrics_heading_present` | Covered |
| REQ-DS-01 | Appendix heading present | `test_appendix_heading_present` | Covered |
| REQ-DS-02 | Module names as Heading 1 | `test_module_level1_heading_present` (parametrized) | Covered |
| REQ-DS-02 | Unit diagram present after unit heading | `test_unit_diagram_image_placed_after_heading` (parametrized) | Covered |
| REQ-DS-02 | Unit header table present | `test_unit_header_table_present` | Covered |
| REQ-DS-03 | Static Design heading present | `test_heading_present[Static]` | Covered |
| REQ-DS-03 | Flowchart tables present | `test_flowchart_tables_present` | Covered |
| REQ-DS-03 | Component/unit table present | `test_component_unit_table_present` | Covered |
| REQ-DS-03 | Module architecture diagram present | `test_module_static_diagram_content_present` | Covered |
| REQ-DS-04 | Dynamic Behaviour heading present | `test_heading_present[Dynamic Behaviour]` | Covered |
| REQ-DS-04 | Scenario sub-headings present for Core | `test_dynamic_behaviour_sub_headings_for_core` | Covered |

---

### Interface Tables — `tests/unit/test_interface_tables_view.py` + `tests/e2e/test_interface_tables.py`

| Requirement | Rule | Test | Status |
|---|---|---|---|
| REQ-IT-01 | Only source-backed units included | `test_expected_units_present` (e2e) | Covered |
| REQ-IT-01 | Header-only units excluded | — | Not tested |
| REQ-IT-01 | Module-scoped run filters units | — | Not tested |
| REQ-IT-02 | Public functions included | `test_public_functions_present` (e2e) | Covered |
| REQ-IT-02 | Protected functions included | `test_protected_functions_included` (e2e) | Covered |
| REQ-IT-02 | Public globals included | `test_public_global_present` (e2e) | Covered |
| REQ-IT-02 | Private functions excluded | `test_private_functions_excluded` (e2e) | Covered |
| REQ-IT-02 | Private globals excluded | `test_private_globals_excluded` (e2e) | Covered |
| REQ-IT-03 | Entries sorted by source line order | `test_function_entries_sorted_by_line` (e2e) | Covered (functions only) |
| REQ-IT-04 | All column fields present on every entry | `test_required_fields_present` (e2e) | Covered |
| REQ-IT-04 | Entry type is `Function` or `Global Variable` | `test_entry_types_valid` (e2e) | Covered |
| REQ-IT-05 | Modifier function → `In` | `test_function_direction[coreSetResult-In]` (e2e) | Covered |
| REQ-IT-05 | Read-only function → `Out` | `test_function_direction[coreGetCount-Out]`, `test_function_direction[utilCompute-Out]` (e2e) | Covered |
| REQ-IT-05 | Pure function (no globals) → `Out` | `test_function_direction[coreAdd-Out]`, `test_function_direction[libAdd-Out]` (e2e) | Covered |
| REQ-IT-05 | Nested lambda modifier → enclosing gets `In` | — | Not tested |
| REQ-IT-05 | Direction value is `In` or `Out` only | `test_function_direction_values_valid` (e2e) | Covered |
| REQ-IT-05 | Global variables always `In/Out` | `test_global_variable_direction_is_inout` (e2e) | Covered |
| REQ-IT-06 | Interface Name is short unqualified name | `test_public_functions_present`, `test_public_global_present` (e2e) | Covered (presence) |
| REQ-IT-07 | Information is `-` when LLM off | — | Not tested (LLM off in CI) |
| REQ-IT-08 | Data Type — param types or `VOID` | `BuildInterfaceTables` (unit) | Covered (unit) |
| REQ-IT-08 | Data Type — variable type for globals | `BuildInterfaceTables` (unit) | Covered (unit) |
| REQ-IT-09 | Data Range — from data dictionary, `NA` if none | `BuildInterfaceTables` (unit) | Covered (unit) |
| REQ-IT-10 | Interface Type is `Function` or `Global Variable` | `test_entry_types_valid` (e2e) | Covered |
| REQ-IT-11 | Interface ID starts with `IF_` | `test_interface_ids_start_with_IF` (e2e) | Covered |
| REQ-IT-11 | Interface ID segments are uppercase | `test_interface_id_segments_uppercase` (e2e) | Covered |
| REQ-IT-11 | `<GROUP>` omitted when no group resolves | — | Not tested |
| REQ-IT-12 | `callerUnits` and `calleesUnits` present | `test_required_fields_present` (e2e) | Covered |
| REQ-IT-12 | `callerUnits` populated for called functions | `test_caller_units_populated` (e2e) | Covered |
| REQ-IT-12 | `calleesUnits` populated for calling functions | `test_callee_units_populated` (e2e) | Covered |
| REQ-IT-12 | `sourceDest` shows external units only | `test_sourcedest_dash_when_no_external_connections` (e2e) | Covered (negative) |
| REQ-IT-12 | `sourceDest` is `-` when no external connections | `test_sourcedest_dash_when_no_external_connections` (e2e) | Covered |
| REQ-IT-12 | Global entries have empty caller/callee lists | `test_global_entries_have_empty_caller_callee` (e2e) | Covered |

#### Gaps

| Requirement | Gap | Reason |
|---|---|---|
| REQ-IT-01 | Header-only units excluded | Needs a header-only unit in SampleCppProject |
| REQ-IT-01 | Module-scoped filtering | Needs a separate run fixture scoped to one module |
| REQ-IT-05 | Nested lambda modifier → enclosing `In` | Needs a C++ fixture with a lambda writing a global |
| REQ-IT-07 | Information field when LLM is on | LLM disabled in CI |
| REQ-IT-11 | `<GROUP>` omitted when no group resolves | Needs a project with no `modulesGroups` config |

---

### Unit Architecture Diagrams — `tests/unit/test_unit_diagrams_view.py` + `tests/e2e/test_unit_diagrams.py`

| Requirement | Rule | Test | Status |
|---|---|---|---|
| REQ-UD-01 | Only source-backed units produce a diagram | `test_non_cpp_unit_returns_none` (unit) | Covered |
| REQ-UD-01 | Source-backed unit returns a diagram | `test_cpp_unit_returns_string` (unit) | Covered |
| REQ-UD-01 | Group-scoped: only allowed units generated | `test_allowed_modules_marks_internal_units` (unit) | Covered |
| REQ-UD-02 | Node IDs contain no invalid characters | `test_pipe_replaced_by_underscore`, `test_space_replaced_by_underscore` (unit) | Covered |
| REQ-UD-02 | Empty key maps to safe fallback `"u"` | `test_empty_string_returns_u`, `test_none_returns_u` (unit) | Covered |
| REQ-UD-03 | Double-quotes → single-quotes in labels | `test_double_quotes_replaced_by_single` (unit) | Covered |
| REQ-UD-03 | Newline → space in labels | `test_newline_replaced_by_space` (unit) | Covered |
| REQ-UD-03 | Pipe → broken-bar in labels | `test_pipe_replaced_by_broken_bar` (unit) | Covered |
| REQ-UD-03 | Multiple escapes combined | `test_multiple_escapes_combined` (unit) | Covered |
| REQ-UD-04 | Diagram direction is left-to-right | `test_output_contains_flowchart_lr` (unit), `test_flowchart_direction_is_lr` (e2e) | Covered |
| REQ-UD-04 | Subgraph present | `test_output_contains_subgraph_for_module` (unit), `test_subgraph_present` (e2e) | Covered |
| REQ-UD-04 | Subgraph label matches module name | `test_subgraph_labelled_with_module_name` (unit), `test_subgraph_label_matches_module` (e2e) | Covered |
| REQ-UD-05 | Outgoing cross-unit call edge labelled with `IF_` ID | `test_callee_edge_labeled_with_interface_id` (unit), `test_cross_module_edge_with_if_label` (e2e) | Covered |
| REQ-UD-05 | Incoming call edge labelled with `IF_` ID | `test_incoming_caller_edge_labeled_with_interface_id` (unit) | Covered |
| REQ-UD-05 | Same-unit calls produce no edge | `test_self_calls_not_added_as_edges` (unit) | Covered |
| REQ-UD-05 | Multiple calls share one edge with all IDs | `test_multiple_ifaces_on_same_edge_both_appear` (unit) | Covered |
| REQ-UD-06 | External caller node appears left of subgraph | `test_external_caller_node_appears_before_subgraph` (unit) | Covered |
| REQ-UD-06 | External callee node appears right of subgraph | `test_external_callee_node_appears_after_subgraph` (unit) | Covered |
| REQ-UD-07 | Current unit has `mainUnit` style | `test_mainunit_class_applied_to_current_unit` (unit), `test_main_unit_has_main_unit_class` (e2e) | Covered |
| REQ-UD-07 | Same-module peers have `internal` style | `test_internal_peer_gets_internal_class` (unit) | Covered |
| REQ-UD-07 | Peers not styled as `mainUnit` | `test_internal_peer_gets_internal_class` (unit), `test_peer_not_styled_as_main_unit` (e2e) | Covered |
| REQ-UD-08 | Group boundary defines internal vs external | `test_allowed_modules_marks_internal_units` (unit) | Covered |

#### Gaps

| Requirement | Gap | Reason |
|---|---|---|
| REQ-UD-01 | Header-only unit excluded from e2e output | No header-only unit in SampleCppProject fixture |

---

### Static Design / Flowcharts — `tests/unit/test_flowchart_generator.py` + `tests/e2e/test_flowcharts.py`

| Requirement | Rule | Test | Status |
|---|---|---|---|
| REQ-FC-01 | Every expected function has a flowchart entry | `test_expected_functions_present` (e2e) | Covered |
| REQ-FC-01 | Every unit has a flowchart file | `test_flowchart_file_exists` (e2e), `test_creates_one_file_per_unit` (unit) | Covered |
| REQ-FC-01 | Empty input produces no output | `test_empty_functions_json_produces_no_files` (unit) | Covered |
| REQ-FC-02 | Entry labelled with short function name | `test_function_names_are_simple_not_qualified` (unit) | Covered |
| REQ-FC-02 | Entry name is non-empty | `test_function_names_are_nonempty` (e2e) | Covered |
| REQ-FC-03 | Every flowchart is a valid Mermaid diagram | `test_flowchart_content_is_valid_mermaid` (unit), `test_flowchart_strings_are_valid_mermaid` (e2e) | Covered |
| REQ-FC-03 | Flowchart content is non-empty | `test_flowchart_content_is_valid_mermaid` (unit) | Covered |
| REQ-FC-04 | Flowchart metadata table present in DOCX | `test_flowchart_tables_present` (e2e/docx) | Covered |
| REQ-FC-04 | `Capacity(Density)` row label present | `test_flowchart_tables_present` (e2e/docx) | Covered |
| REQ-FC-04 | LLM called with function source in prompt | `TestBuildFlowchartForFunction::test_prompt_contains_source_code` *(xfail)* | Not yet |
| REQ-FC-04 | LLM response used as flowchart content | `TestBuildFlowchartForFunction::test_returns_llm_response` *(xfail)* | Not yet |
| REQ-FC-04 | Code fences stripped from LLM response | `TestBuildFlowchartForFunction::test_strips_code_fences` *(xfail)* | Not yet |
| REQ-FC-04 | Fallback on empty LLM response | `TestBuildFlowchartForFunction::test_fallback_on_empty_llm_response` *(xfail)* | Not yet |

#### Gaps

| Requirement | Gap | Reason |
|---|---|---|
| REQ-FC-04 | LLM seam contract (4 tests) | `fake_flowchart_generator` LLM seam not yet wired |

---

### Component Overview — `tests/e2e/test_docx.py`

| Requirement | Rule | Test | Status |
|---|---|---|---|
| REQ-CO-01 | Component/unit table present with correct headers | `test_component_unit_table_present` | Covered |
| REQ-CO-02 | All module names in Component column | `test_component_unit_table_has_module_names` | Covered |
| REQ-CO-03 | Module architecture diagram present in Static Design | `test_module_static_diagram_content_present` | Covered |
