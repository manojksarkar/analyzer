# Test Inventory

**612 tests total** — 418 unit (411 passing · 7 xfail) · 114 e2e artifacts · 48 e2e DOCX · 32 e2e behaviour names

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
| `test_interface_tables.py` | `output/interface_tables.json` — unit presence, entry types, direction values, public/private filtering, parameter ranges, golden snapshot |
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
