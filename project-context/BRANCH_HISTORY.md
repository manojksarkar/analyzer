# Earlier refactors and feature branches

> **Project context — one part of it.** Start at [PROJECT_CONTEXT.md](../PROJECT_CONTEXT.md),
> the index: current state, how to read the context, every file. The sections below moved here
> from the single-file context on 2026-09-28, unchanged except link paths, and keep their numbers —
> "PROJECT_CONTEXT §N" still finds them. Written over time: where a section and a newer dated
> entry in [history/](history/) disagree, the newer entry and the code win.

**Sections:** [4. Refactor history (`version2` branch)](#4-refactor-history-version2-branch) · [4b. LLM layer upgrade (`version3` branch)](#4b-llm-layer-upgrade-version3-branch) · [4c. Test-framework branch (`feat/test-framework`)](#4c-test-framework-branch-feattest-framework) · [4d. feat/from-main changes](#4d-featfrom-main-changes) · [4e. feat/auto-clang-includes changes](#4e-featauto-clang-includes-changes) · [4f. Component-level DOCX export + space normalization](#4f-component-level-docx-export--space-normalization)

## 4. Refactor history (`version2` branch)

Six refactor batches landed on this branch on top of `main`. Each batch is a
self-contained consolidation; together they introduce the `engine/core/` and
`engine/llm_core/` layers and shrink the legacy hot files.

| # | Batch | Result |
|---|---|---|
| 1 | LLM Foundation | New `engine/llm_core/` — single `LlmClient` for OpenAI gateway + Ollama with shared retry, think-section stripping, token tracking |
| 2 | Progress & Logging | `core.logging_setup` (stderr + daily file), `core.progress.ProgressReporter`, `LOG_LEVEL` env propagation to subprocesses |
| 3 | Config & Paths | `core.paths.ProjectPaths` (cached snapshot), `core.config` typed accessors with JSONC parser |
| 4 | Model IO | `core.model_io` — canonical filename constants, `read_model_file` / `write_model_file` (opt-in atomic), `load_model(*required, optional=...)` |
| 5 | Phase Orchestration | `core.orchestration.Phase` + `PhaseRunner` (single subprocess authority), `core.group_planner.plan_runs` (collapses 3-branch dispatch), run.py 257 → 152 lines |
| 6 | Config Relocation | Moved `load_config` / `load_llm_config` / JSONC strippers from `utils.py` into `core.config`, leaving thin re-export shims so existing call sites keep working |

The result: `engine/core/` is the bottom of the dependency graph and has no
imports from analyzer-level modules. Verified by `grep -r "from utils" engine/core/`
returning nothing.

---

## 4b. LLM layer upgrade (`version3` branch)

Three commits on top of `version2` implement a full LLM upgrade plan. Original
plan lives at `.claude/plans/zippy-riding-shell.md`. Shipped commits:

| Commit | Title |
|---|---|
| `17f6636` | feat: LLM layer upgrade — budgeting, two-pass, cache, review, ensemble, CFG simplify |
| `66cc98f` | fix: make maxContextTokens authoritative for coherence + simplify passes |
| `4d10df6` | feat(config): strict LLM validation + startup banner |

### Goals (why this exists)

The version2 LLM layer shipped with hardcoded char caps (`MAX_PROMPT_CHARS=6000`,
`CONTEXT_BUDGET=1200`), single-pass descriptions that never saw caller context,
nearly-useless global-variable descriptions, no few-shot examples, no cache, no
self-review, and no structured-output repair. On large models this wasted the
context window; on small models prompts silently overflowed and returned empty.
version3 rewrites the LLM subsystem around a token budget and a set of
reusable helpers in `engine/llm_core/`.

### What was NOT adopted (explicit out-of-scope)

- Tool-calling agentic loop (Ollama doesn't support it reliably).
- YAML config migration (keep JSONC).
- Full pipeline rewrite — still the same 4-phase subprocess architecture.

### Batch matrix (what every phase delivered)

| Phase | Delivered | Key files |
|---|---|---|
| **P1 — Foundation** | TokenCounter (tiktoken + char fallback), ContextBudget with `TASK_RATIOS`, `LlmClient.call()` multi-message API, config additions (`maxContextTokens`, `enrichment.*`, `fewShotExamplesDir`, `cacheVersion`) | `llm_core/token_counter.py`, `llm_core/budget.py`, `llm_core/client.py`, `core/config.py`, `engine/config/config.defaults.json` |
| **P2 — Context quality** | Degradation ladder (`ContextBuilder`), scoped `RepoMap` (neighborhood → file → module → project tiers), `get_rich_description()` with callees / callers / types / globals / siblings / repo-map, `get_rich_global_description()` for variables | `llm_core/context_builder.py`, `llm_core/repo_map.py`, `llm_enrichment.py` |
| **P3 — Two-pass + few-shot** | Two-pass descriptions (Pass 1 bottom-up, Pass 2 refines with caller context), `FewShotPool` with keyword-overlap ranking, seed example directories (`few_shot_examples/{descriptions,labels,globals,behaviour_names}`) | `llm_core/few_shot.py`, `llm_enrichment.py`, `few_shot_examples/` |
| **P4 — Cache + structured output** | `EntityCache` with composite hash keys (source + sorted callee hashes + version), `extract_and_validate()` (strip fences → extract JSON → repair → validate keys), `parse_label_response()` for flowchart batches | `llm_core/cache.py`, `llm_core/structured_output.py` |
| **P5 — Self-review, ensemble, CFG simplify** | `self_review()` generate→review→revise (≥20-line functions), `ensemble_generate()` for unit/module summaries (3 temperatures + synthesis), LLM-guided CFG simplification (merge linear ACTION chains + drop single-in/single-out), strengthened coherence prompt | `llm_core/review.py`, `llm_enrichment.py`, `flowchart/llm/generator.py` |
| **Follow-up — strict config + banner** | `LlmConfigError`, strict validation of every required and optional llm field, `format_llm_config_banner()` displayed at the start of every subprocess, removal of `getattr(client, "_num_ctx", 8192)` style hardcoded fallbacks, `LlmClient.num_ctx` property | `core/config.py`, `run.py`, `flowchart/flowchart_engine.py` |

### `llm.enrichment` flag semantics

Every feature ships gated behind `config.llm.enrichment.<flag>`:

| Flag | Default | What it does | Cost multiplier |
|---|---|---|---|
| `twoPassDescriptions` | `true` | Pass 2 refines function descriptions using caller context from Pass 1 | 2x descriptions |
| `selfReview` | `false` | generate → review → revise for function descriptions (≥20 non-blank lines) and high-visibility summaries | 3x on reviewed items |
| `ensemble` | `false` | 3 temperatures + synthesis call for unit / module summaries | 4x on synthesized items |
| `cfgSimplification` | `false` | LLM proposes merge/drop plan for CFGs with >15 nodes; only linear chains + single-in/single-out drops are applied, decisions/loops/returns are never touched | 1 extra call per large CFG |
| `variableEnrichment` | `true` | Rich global-variable descriptions (write-site + read-site evidence vs. the old one-line declaration) | — |

The defaults trade conservative cost for quality on the features that most
affect DOCX output (`twoPassDescriptions`, `variableEnrichment`). The expensive
features (`selfReview`, `ensemble`, `cfgSimplification`) are **opt-in** — set
them in `engine/config/config.json` or `config.local.json`.

### Token budgeting — `ContextBudget` + `TASK_RATIOS`

One config knob (`maxContextTokens`) now scales every prompt allocation.
[engine/llm_core/budget.py](../engine/llm_core/budget.py) defines `TASK_RATIOS` — a
dict of per-task section ratios summing to ~1.0 — for:

- `function_description`, `function_description_refined`
- `variable_description`, `behaviour_names`
- `function_summary`, `file_summary`, `module_summary`, `project_summary`
- `cfg_node_labeling`, `cfg_coherence`, `cfg_simplification`
- `self_review`, `ensemble_synthesis`

`ContextBudget(max_tokens, task, counter)` reserves a 10 % safety margin then
hands each named section (`system_prompt`, `few_shot`, `callees`, …) its
absolute token budget. Callers feed content through `ContextBuilder` /
`RepoMap` / `FewShotPool` which return text sized to fit the section budget.

`resolve_max_tokens(llm_cfg)` derives `max_context_tokens`:
1. Explicit `llm.maxContextTokens` in config → used as-is.
2. Otherwise `openai` → 127488 (~128K − 512 reserve).
3. Otherwise `ollama` → `numCtx − 512`.

No silent default for `provider` or `numCtx` any more — the field must be
validated first by `load_llm_config()`.

### Strict config + startup banner (why runs are now self-documenting)

`core.config.load_llm_config()` raises **`LlmConfigError`** with the exact
failing field name when any required field is missing / empty / wrong type:
`provider`, `baseUrl`, `defaultModel`, `timeoutSeconds`, `numCtx`, `retries`.
Optional fields (`enrichment.*`, `descriptions`, `behaviourNames`,
`maxContextTokens`, `cacheVersion`, `fewShotExamplesDir`, `customHeaders`,
`rateLimitSeconds`)
are type-checked the same way. `provider` is restricted to
`"ollama"`|`"openai"`.

`core.config.format_llm_config_banner(llm_cfg)` returns a multi-line summary.
Both [run.py](../run.py) and [engine/flowchart/flowchart_engine.py](../engine/flowchart/flowchart_engine.py)
print it at the top of every run so the user sees exactly which
provider / baseUrl / model / `numCtx` / `maxContextTokens` (resolved, e.g.
`auto -> 7680`) / timeout / retries / enrichment flags are active:

```
------------------------------------------------------------
LLM configuration (will be used for this run)
------------------------------------------------------------
  provider          : ollama
  baseUrl           : http://localhost:11434
  defaultModel      : qwen2.5-coder:14b
  numCtx            : 8192  (used)
  maxContextTokens  : auto -> 7680
  timeoutSeconds    : 120
  retries           : 1
  rateLimitSeconds  : 3.0  (ignored on ollama)
  apiKey            : (none)
  cacheVersion      : 1
  fewShotExamplesDir: few_shot_examples
  descriptions      : False
  behaviourNames    : False
  enrichment ON     : twoPassDescriptions, variableEnrichment
  enrichment OFF    : cfgSimplification, ensemble, selfReview
------------------------------------------------------------
```

The banner is ASCII-only — `─` and `→` were removed because Windows cp1252
stderr choked on the Unicode characters.

### Quality impact ranking (original plan — for reference)

1. Richer description prompts (get_rich_description) — biggest DOCX impact
2. Two-pass descriptions — fixes the biggest blind spot (no caller context)
3. Degradation ladder — stops silently dropping callees
4. Variable enrichment — global descriptions go from useless to useful
5. Few-shot examples — teaches output style, helps weaker models
6. CFG simplification — complex flowcharts become readable
7. Scoped repo map — reduces hallucinated symbols
8. Self-review — polish for high-visibility descriptions
9. Entity cache — productivity (10× faster re-runs), no quality impact
10. Structured output — robustness (fewer fallback labels)

---

## 4c. Test-framework branch (`feat/test-framework`)

Three categories of change landed on this branch on top of `version3`:

### 1. `LIBCLANG_PATH` auto-wiring

> **Corrected 2026-07-01** — the original text below was aspirational/never true.
> `run.py` does **not** set `LIBCLANG_PATH`, and the flowchart engine did **not**
> read it. The API (`api/services/pipeline_runner.py::_execute_subprocess`) sets
> `env["LIBCLANG_PATH"]` only when `cfg.libclang_path` is configured, but nothing
> in `engine/flowchart/` consumed it — `clang.cindex` never auto-reads that env var —
> so flowcharts failed with `LibclangError` on any host where `libclang.dll` isn't
> on the loader path. Now fixed: `flowchart_engine.py::_configure_libclang()` (called
> first thing in `run()`) resolves the DLL from `LIBCLANG_PATH` **or** the analyzer
> config's `clang.llvmLibPath`, does `os.add_dll_directory` + `Config.set_library_file`
> (mirroring `engine/parser.py:79-90`), before any `Index.create()`.

_Original (inaccurate) note:_ "`run.py` reads `clang.llvmLibPath` and exports it as
`os.environ["LIBCLANG_PATH"]`; `flowchart_engine.py` picks it up at import time." Only
Phase 1 (`engine/parser.py`) ever configured libclang; the flowchart engine did not until
the fix above.

### 2. `llm.summarize` config flag

`run.py` now respects a new optional `llm.summarize` boolean in
`config.defaults.json`. When `false`, it sets `no_llm_summarize = True` before calling
`plan_runs`, suppressing Phase 2 hierarchy summarization. This mirrors what
`--no-llm-summarize` does on the CLI, but can be committed in `config.local.json`
for a permanent local preference.

### 3. Unit-test suite overhaul

| File | What changed |
|---|---|
| `tests/unit/test_llm_client.py` | Fully rewritten to test `llm_core.client.LlmClient` + `from_config` (was testing legacy `llm_client` module). Covers constructor validation, `generate()` / `call()`, retry logic, `from_config` builder. |
| `tests/unit/test_behaviour_diagram_generator.py` | Switched from `fake_behaviour_diagram_generator.FakeBehaviourGenerator` to the real `behaviour_diagram_generator.SequenceDiagramGenerator` (alias kept as `FakeBehaviourGenerator`). Patch target updated to `behaviour_diagram_generator.llm_client`. No-LLM pass: module docstring now lists which classes need no LLM (ExternalCallerFiltering, FileNaming, MmdContent) vs which are xfail (LlmContract); repeated `functions` dict extracted into `_ONE_EXTERNAL_CALLER` module-level constant; stale fence-strip comment removed from `TestMmdContent`. |
| `tests/unit/test_utils.py` | `_strip_json_comments` / `_strip_trailing_commas` now imported from `core.config`, not from `utils`. |
| `engine/flowchart/tests/test_cfg_topo.py` | Added `src/` to `sys.path` so `ast_engine.*` imports resolve when running from the project root. |
| `tests/conftest.py` | Logs the full pipeline command string before executing it (aids debugging failed CI runs). |
| `tests/unit/test_unit_diagrams_view.py` | Expanded with 10 new tests covering: subgraph module label, `mainUnit`/`internal` CSS classes, incoming caller edges, multi-iface edge joining, external caller/callee layout (before-subgraph / after-end), combined escape sequences, `_fid_to_unit` with missing key. Snapshot `tests/snapshots/Sample/unit_diagrams.json` refreshed to match current output. |

---

## 4d. feat/from-main changes

### `module` → `component` rename

Every occurrence of "module" in source, model files, config, and keys was
renamed to "component". Specific impacts:

| Old | New |
|---|---|
| `model/modules.json` | `model/components.json` |
| `core.model_io.MODULES` constant | `core.model_io.COMPONENTS` |
| `get_module_name(file, base)` in `utils.py` | `get_component_name(file, base)` |
| `init_module_mapping(config)` in `utils.py` | `init_component_mapping(config)` |
| `_MODULE_OVERRIDES` / `_MODULE_FOLDERS` | `_COMPONENT_OVERRIDES` / `_COMPONENT_FOLDERS` |
| `function["moduleName"]` in model JSON | `function["componentName"]` |
| `_build_units_modules(...)` in Phase 2 | `_build_units_components(...)` |
| `module_functions` / `function_to_module` | `component_functions` / `function_to_component` |
| `config.modulesGroups` | `config.layers` (new two-level schema, see §6) |
| `_analyzerAllowedModules` in config | `_analyzerAllowedComponents` in config |
| `moduleStaticDiagram` view key | `componentStaticDiagram` view key |
| `knowledge_base.json: "modules"` key | `knowledge_base.json: "components"` key |
| `summaries.json: "modules"` key | `summaries.json: "components"` key |
| `run.py` checks for `MODULES` on `--use-model` | checks for `COMPONENTS` |

### New `layers` config schema

`config.defaults.json` now uses a two-level `layers` structure instead of the flat
`modulesGroups`. Format:

```jsonc
"layers": {
  "Layer1": {
    "path": "Layer1",          // relative to <project_path>
    // Build INPUTS moved to the top-level `cores` section (2026-09-02): a core
    // owns one macro set + one data dictionary + one compile_commands.json, and a
    // layer names the cores it is built from. `layer_source()` resolves through
    // the layer's core, falling back to a layer-level "dataDictionary"/"macros"
    // key so pre-`cores` configs and --macros-layer still work unchanged.
    // At most ONE core per layer today (config.MAX_CORES_PER_LAYER); a second
    // exits 1 rather than merging two different -D sets. See §4g.
    "cores": ["Core1"],
    "groups": {
      "Sample": {              // group name (for --selected-group)
        "Core": "Sample/Core", // component → path (relative to layer path)
        "Lib":  "Sample/Lib",
        "Util": "Sample/Util"
      },
      "Full": {
        "Iface": ["Direction", "Types", "Flow"],  // list of paths also OK
        "Cross": ["Hub", "Poly"]
      }
    }
  },
  "Layer2": {
    "path": "Layer2",
    "groups": {
      "Platform": {
        "Gpio": "Platform/Gpio",
        "Uart": "Platform/Uart",
        ...
      }
    }
  }
}
```

`core.config.get_flat_groups(cfg)` flattens this into
`{groupName: {componentName: resolvedPath}}` with layer paths prepended.
Falls back to the old `layer` key for backwards compatibility. `_resolve_layer_paths`
reads only `path` + `groups`, so the per-layer input keys above are ignored there and
adding more of them needs no change.

Per-layer inputs are read via `core.config.layer_source(cfg, layer, key)` /
`layer_sources(cfg, key)` → `{layer: path}`. Adding a third per-layer input costs one
call, not a new schema. `clang.macrosByLayer` still works but is **deprecated** —
`layers.<L>.macros` wins for the same layer.

**Config is per-layer only.** The project-wide dictionary and macro list are CLI
(`--data-dictionary`, `--macros`); there is no `dataDictionary.file` key. The single
exception is `clang.macrosFile` / `clang.macroScopes`, still honoured in code because
the API has no CLI path for macros (see §17, 2026-08-18) — but absent from the shipped
`config.json`.

### Same-layer model filtering

When generating a group's SDD (Phase 3 + 4), the model is now filtered to
**all components in the same layer** — not just the selected group's
components. This ensures cross-component call edges within the layer remain
visible.

- `run_views.py` calls `get_layer_components(config, group)` and then
  `_filter_model_to_components(model, layer_comps)` before passing the model
  to `views.run_views()`.
- `docx_exporter.py` applies the same filter to `units_data`, `components_data`,
  `global_variables_data`, and `functions_data`.
- `_analyzerAllowedComponents` (set on the config dict) still contains only
  the **selected group's** component names — this is what `interface_tables.py`
  and other views use to filter their output. The same-layer filter just
  ensures the model fed to the views has all same-layer data available for
  cross-component edge discovery.

### Layer include paths (`model/clang_include_paths.json`)

Before Phase 1, `run.py` walks every directory under every configured layer
path and writes the results to `model/clang_include_paths.json` as
`{layerName: [dir1, dir2, ...]}`. Phase 1 (`parser.py`) reads this file and
adds a `-I` flag for each directory so all layer headers are resolvable.

Since 2026-09-02 that walk can be **supplemented by the build's own
`compile_commands.json`** — see `core/compile_commands.py` and the dated entry
above. Walked dirs stay first; compile_commands dirs are appended per layer.
Inert unless a layer declares a `compileCommands` block.

### `SampleCppProject` restructure

The test fixture was reorganised from a flat `SampleCppProject/` into:

```
SampleCppProject/
  Layer1/        — existing test fixtures (Access, App, Diag, Direction, Flow, Hub,
                   Math, Outer/Inner, Poly, Types) + new Sample/ group
    Sample/
      Core/      — Core.cpp / Core.h
      Lib/       — Lib.cpp / Lib.h
      Util/      — Util.cpp / Util.h
  Layer2/
    Platform/    — 15 new platform components (stub .cpp/.h files):
                   Adc, Cache, Config, Display, EventBus, Gpio, I2c,
                   Logger, Network, Protocol, Scheduler, Spi, Storage,
                   Timer, Uart  (each with 3-5 sub-files)
```

`config.defaults.json` defines two layers pointing at these directories. The old
`test_cpp_project/` fixture is **no longer used** (replaced by
`SampleCppProject/`).

---

## 4e. feat/auto-clang-includes changes

### Layer-scoped Phase 1 parsing

Previously, Phase 1 always parsed every file across all configured layers regardless of `--selected-group`. Since there is no cross-layer communication (only cross-group/cross-component within the same layer), this was wasted work. A selection naming several layers narrows to the UNION of them (2026-09-07), not to the first.

**What changed:**

- `parser.py` now accepts `--selected-group <G>` and `--selected-layer <L>` flags (passed by `group_planner`).
  - `--selected-group`: calls `get_group_layer_name(cfg, G)` to find the layer, then `get_layer_flat_groups(cfg, layer)` to build `_COMPONENT_FOLDERS` from that layer only.
  - `--selected-layer`: calls `get_layer_flat_groups(cfg, L)` directly.
  - No flag: falls back to `get_flat_groups(cfg)` — all layers (existing behaviour).

- `run.py` resolves the target layer before walking directories for `clang_include_paths.json`, so only the selected layer's directories are written to that file.

- `group_planner._build_model_phases` passes `--selected-group G` or `--selected-layer L` to `parser.py` depending on which CLI flag was given.

- `--selected-group` and `--selected-layer` are **mutually exclusive** — `run.py` exits with code 1 if both are set.

### New `--selected-layer` CLI flag

`--selected-layer <L>` is a new top-level flag that:
1. Restricts Phase 1+2 to layer L only.
2. Runs Phase 3+4 for every group defined inside layer L.

This is equivalent to running `--selected-group G` once per group in the layer, but in one command.

### New helpers in `core.config`

- `get_group_layer_name(cfg, group_name)` → layer name or `None`
- `get_layer_flat_groups(cfg, layer_name)` → `{groupName: {componentName: resolvedPath}}` for one layer

---

## 4f. Component-level DOCX export + space normalization

### New CLI flags

**`--selected-component <name>`** (repeatable) — generate a DOCX for the named component(s). Repeat the flag for each component. **They may sit in DIFFERENT layers** (2026-09-07); Phase 1+2 parse the union of their layers, each with its own include paths and `-D` set. Names are layer-qualified ids (`Layer1.Math`); a bare name is accepted while only one layer defines it. **Add `--component-per-docx` for one document per component** (`output/<C>/software_detailed_design_<C>.docx`) — that is what `analyzer.py --scope "component:…"` now passes. Without it they are bundled into one: `output/<C1_C2>/software_detailed_design_<C1_C2>.docx`. Mutually exclusive with `--selected-group` and `--selected-layer`.

```bash
python engine/run.py --selected-component Gpio SampleCppProject
python engine/run.py --selected-component "Sample Core" --selected-component Lib SampleCppProject
```

**`--component-per-docx`** — modifier flag (no value). Splits output into **one DOCX per component** instead of one per group. Combines with every selection, `--selected-component` included (2026-09-07) — a component scope used to be the one shape that came back bundled while every other scope split.

```bash
python engine/run.py --selected-group "My Sample" --component-per-docx SampleCppProject
python engine/run.py --selected-layer Layer1 --component-per-docx SampleCppProject
python engine/run.py --component-per-docx SampleCppProject   # all components in all layers
```

### Naming conventions for identifiers

Group and component names may contain spaces (e.g. `"My Sample"`, `"Sample Core"`). Two rules apply everywhere a name becomes an identifier (filename, output dir, model key, Mermaid node ID):

- **Space within a name → `-`**: `"Sample Core"` → `Sample-Core`
- **Separator between component names in a bundle → `_`**: `["Sample-Core", "Lib"]` → `Sample-Core_Lib`

Display contexts (DOCX section headings, log labels) keep the original name with spaces.

### Where normalization is applied

| Location | What changed |
|---|---|
| `engine/utils.py` — `safe_filename` | Spaces → `-` before unsafe-char replacement |
| `engine/utils.py` — `_resolve_component_from_rel` | Returns `component.replace(" ", "-")` |
| `engine/parser.py` — `_build_file_component_map` | Both `setdefault` calls store `component.replace(" ", "-")` |
| `engine/views/unit_diagrams.py` — `_unit_part_id` | `replace(" ", "_")` → `replace(" ", "-")` |
| `engine/core/group_planner.py` — group output paths | `g.replace(" ", "-")` for dir + DOCX name |
| `engine/core/group_planner.py` — component bundle | `virtual_name = "_".join(selected_components)` |
| `engine/run_views.py` — `_filter_model_to_components` | `{c.lower().replace(" ", "-") for c in allowed}` |
| `engine/run_views.py` — `_analyzerAllowedComponents` | Keys normalized on set: `k.replace(" ", "-")` |
| `engine/docx_exporter.py` — same-layer filter | Both `lower` sets normalized with `.replace(" ", "-")` |
| `engine/core/config.py` — `get_component_layer_name` | Normalizes both sides of comparison |
| `run.py` — `--selected-component` collection | Normalizes input at `append` time |

**Important after this change**: any existing `model/functions.json` built before this change will have `"Sample Core|..."` keys (with spaces). Re-run from Phase 1 (`--clean` or `--from-phase 1`) after updating to get normalized `"Sample-Core|..."` keys.

### `plan_runs` dispatch shapes (updated)

`--component-per-docx` adds a new branching mode inside the existing per-group loop. When set, `plan_runs` iterates each group's components and emits one `RunPlan` per component (using `--selected-component`) instead of one per group. Since 2026-09-07 it does the same inside the `--selected-component` branch: the named components are split into one view+export plan each, sharing the single model build.

| `--component-per-docx` | CLI selection | Plans emitted |
|---|---|---|
| No | `--selected-group G` | 1 plan (whole group) |
| No | `--selected-layer L` | 1 plan per group in L |
| **Yes** | `--selected-group G` | 1 plan **per component** in G |
| **Yes** | `--selected-layer L` | 1 plan **per component** across all groups in L |
| **Yes** | (none) | 1 plan **per component** across all groups in all layers |

### flowcharts.py — scoped functions temp file

`model/functions_<key>.json` casing and separator:
- Group run: `functions_My-Sample.json` (group name, spaces → `-`)
- Single component: `functions_Sample-Core.json` (component name, correct casing from `_analyzerAllowedComponents`)
- Multi-component bundle: `functions_Lib_Sample-Core.json` (sorted, `_`-joined, correct casing)

### interface_tables.py — log fix

The hardcoded log string `"output/interface_tables.json"` was replaced with the actual `out_path` so the log shows the real absolute path written.

---

