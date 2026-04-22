# Test Inventory

**411 tests total** — 258 unit (7 xfail) · 145 e2e passing · 8 e2e failing (flowcharts — fake generator) · 18 e2e errors (flowchart fixture setup)

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
| `test_behaviour_diagram_generator.py` | ExternalCallerFiltering · FileNaming · MmdContent · LlmContract*(xfail)* | SequenceDiagramGenerator: caller filtering, file naming, Mermaid content, LLM seam contract |
| `test_cli.py` | ResolveGroupName · RunPyCli | `_resolve_group_name` case-insensitivity; CLI exit codes and error messages for bad flags |
| `test_core_config.py` | LoadLlmConfigValid · LoadLlmConfigErrors · EnvOverrides · FormatBanner | `load_llm_config`: all required/optional fields, all `LlmConfigError` cases, every env-var override, banner format |
| `test_core_group_planner.py` | ResolveGroupName · PlanRunsNoGroups · PlanRunsAllGroups · PlanRunsSelectedGroup | `plan_runs`: all three dispatch shapes, `--from-phase` translation, `--use-model`, unknown group error |
| `test_core_model_io.py` | Constants · ModelFileMissing · ModelFilePath · ModelFilesPresent · ReadModelFile · LoadModel · WriteInPlace · WriteAtomic | Every public function in `model_io`: path helpers, read/write, required vs optional, atomic write, round-trip |
| `test_flowchart_generator.py` | FunctionIdToUnitKey · SafeFilename · BuildFlowchartForFunction*(xfail)* · Run | `fake_flowchart_generator`: key splitting, filename sanitization, run() output shape and Mermaid validity |
| `test_interface_tables_view.py` | StripExt · FidToUnit · BuildInterfaceTables | `_build_interface_tables`: public/private filtering, range enrichment, sorting, allowed_modules, all entry keys |
| `test_llm_client.py` | Constructor · GenerateOllama · GenerateOpenAI · Call · FromConfig | `LlmClient`: provider validation, endpoint building, generate/call/retry logic, from_config builder |
| `test_llm_core_budget.py` | TaskRatios · ContextBudgetConstruction · Allocate · Sections · Remaining · ResolveMaxTokens | `TASK_RATIOS` sum invariants; `ContextBudget` arithmetic; `resolve_max_tokens` for Ollama/OpenAI/explicit/clamp |
| `test_model_deriver.py` | IdSeg · ReadableLabel · PropagateGlobalAccess · EnrichBehaviourNames · EnrichInterfaces | Pure model-deriver helpers: identifier transformations, transitive global propagation, behaviour name heuristics, interfaceId format |
| `test_unit_diagrams_view.py` | UnitPartId · EscapeLabel · FidToUnit · BuildUnitDiagram | `_build_unit_diagram`: Mermaid LR output, subgraph structure, cross-unit edges, self-call exclusion |
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
| `test_behaviour_diagram.py` | `output/behaviour_diagrams/` — .mmd existence, `_behaviour_pngs.json` structure, external vs internal caller filtering, Mermaid validity |
| `test_flowcharts.py` | `output/flowcharts/*.json` — one file per unit, `[{name, flowchart}]` shape, Mermaid validity, all expected public functions present |
| `test_behaviour_names.py` | `model/functions.json` Phase 2 fields — all public functions have behaviourInput/OutputName; static derivation heuristics (param, returnExpr, global read, fallback) |
| `test_docx.py` | `output/software_detailed_design_Sample.docx` — file exists, tables present, IF_ IDs, public names, direction values, embedded images, all section headings, flowchart/behaviour tables |

---

## xfail tests (7)

Marked `@pytest.mark.xfail` — define the contract the real generators must satisfy once wired.

| Test | Waiting on |
|---|---|
| `TestLlmContract::test_llm_response_written_to_mmd` | `behaviour_diagram_generator` LLM seam |
| `TestLlmContract::test_code_fences_stripped_from_llm_response` | `behaviour_diagram_generator` LLM seam |
| `TestLlmContract::test_fallback_on_empty_llm_response` | `behaviour_diagram_generator` LLM seam |
| `TestBuildFlowchartForFunction::test_returns_llm_response` | `fake_flowchart_generator` LLM seam |
| `TestBuildFlowchartForFunction::test_strips_code_fences` | `fake_flowchart_generator` LLM seam |
| `TestBuildFlowchartForFunction::test_fallback_on_empty_llm_response` | `fake_flowchart_generator` LLM seam |
| `TestBuildFlowchartForFunction::test_prompt_contains_source_code` | `fake_flowchart_generator` LLM seam |

---

## Rule coverage (from DESIGN_SPEC.md)

### Interface Tables — `tests/e2e/test_interface_tables.py`

| Requirement | Rule | Test | Status |
|---|---|---|---|
| REQ-IT-01 | Only `.cpp`-backed units included | `test_expected_units_present` | Covered |
| REQ-IT-01 | Header-only units excluded | — | Not tested |
| REQ-IT-01 | Module-scoped run filters units | — | Not tested |
| REQ-IT-02 | PUBLIC functions included | `test_public_functions_present` | Covered |
| REQ-IT-02 | PROTECTED functions included | `test_protected_functions_included` | Covered |
| REQ-IT-02 | PUBLIC globals included | `test_public_global_present` | Covered |
| REQ-IT-02 | PRIVATE functions excluded | `test_private_functions_excluded` | Covered |
| REQ-IT-02 | PRIVATE globals excluded | `test_private_globals_excluded` | Covered |
| REQ-IT-03 | Entries sorted by source line order | `test_function_entries_sorted_by_line` | Covered (functions only) |
| REQ-IT-04 | All column fields present on every entry | `test_required_fields_present` | Covered |
| REQ-IT-04 | Entry type is `Function` or `Global Variable` | `test_entry_types_valid` | Covered |
| REQ-IT-05 | Writes any global → `In` | `test_function_direction[coreSetResult-In]` | Covered |
| REQ-IT-05 | Reads globals, writes none → `Out` | `test_function_direction[coreGetCount-Out]`, `test_function_direction[utilCompute-Out]` | Covered |
| REQ-IT-05 | No global access → `Out` | `test_function_direction[coreAdd-Out]`, `test_function_direction[libAdd-Out]` | Covered |
| REQ-IT-05 | Nested lambda writes → enclosing gets `In` | — | Not tested |
| REQ-IT-05 | Direction value is `In` or `Out` only | `test_function_direction_values_valid` | Covered |
| REQ-IT-05 | Global variables always `In/Out` | `test_global_variable_direction_is_inout` | Covered |
| REQ-IT-06 | Interface Name is short unqualified name | `test_public_functions_present`, `test_public_global_present` | Covered (presence) |
| REQ-IT-07 | Information is `-` when LLM off | — | Not tested (LLM off in CI) |
| REQ-IT-08 | Data Type — param types or `VOID` for functions | `test_interface_tables_view.py::BuildInterfaceTables` (unit) | Covered (unit) |
| REQ-IT-08 | Data Type — variable type for globals | `test_interface_tables_view.py::BuildInterfaceTables` (unit) | Covered (unit) |
| REQ-IT-09 | Data Range — from data dictionary, `NA` if none | `test_interface_tables_view.py::BuildInterfaceTables` (unit) | Covered (unit) |
| REQ-IT-10 | Interface Type is `Function` or `Global Variable` | `test_entry_types_valid` | Covered |
| REQ-IT-11 | Interface ID starts with `IF_` | `test_interface_ids_start_with_IF` | Covered |
| REQ-IT-11 | Interface ID matches `IF_<UPPER>..._<NN>` format | `test_interface_id_segments_uppercase` | Covered |
| REQ-IT-11 | `<GROUP>` omitted when no group resolves | — | Not tested |
| REQ-IT-12 | `callerUnits` and `calleesUnits` present | `test_required_fields_present` | Covered |
| REQ-IT-12 | `callerUnits` populated for called functions | `test_caller_units_populated` | Covered |
| REQ-IT-12 | `calleesUnits` populated for calling functions | `test_callee_units_populated` | Covered |
| REQ-IT-12 | Both lists include same-module units | `test_callee_units_populated` | Covered |
| REQ-IT-12 | `sourceDest` shows external units only | `test_sourcedest_dash_when_no_external_connections` | Covered (negative) |
| REQ-IT-12 | `sourceDest` is `"-"` when no external connections | `test_sourcedest_dash_when_no_external_connections` | Covered |
| REQ-IT-12 | Global entries have empty caller/callee lists | `test_global_entries_have_empty_caller_callee` | Covered |

#### Gaps

| Requirement | Gap | Reason |
|---|---|---|
| REQ-IT-01 | Header-only units excluded | Needs a header-only unit in SampleCppProject |
| REQ-IT-01 | Module-scoped filtering | Needs a separate run fixture scoped to one module |
| REQ-IT-05 | Nested lambda writes → enclosing `In` | Needs a C++ fixture with a lambda writing a global |
| REQ-IT-07 | Information field when LLM is on | LLM disabled in CI |
| REQ-IT-11 | `<GROUP>` omitted when no group resolves | Needs a project with no `modulesGroups` config |
