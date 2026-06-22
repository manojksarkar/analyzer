# C++ Codebase Analyzer — Complete Project Context

> Updated: 2026-06-22 (feat/frontend-app branch created from `main`; `frontend/app/` (51 files, full React/Vite/TS/Tailwind v4 app) landed here; see §24 for frontend stack detail; branch supersedes `feat/product-ui-redesign`).
> Previous update: 2026-06-18 (version4 — **Incremental Changes feature** design + foundations: backend **adapted** to main's `layers`/`component` schema; `backend/git_service.py` added (git ingestion — done); **P1 onboarding stub `backend/seed_workspace.py` — done** (seeds `workspaces/samplecpp/` from the `github.com/vishal9359/SampleCppProject` test repo; branches `main`+`feature1/2/3` built for nearest/far/divergent-ancestor tests); incremental design docs `docs/production-redesign/04` (approach, v2.1) + `05` (UI API spec); implementation plan M1–M3; **M1.1 `--config`/`ANALYZER_CONFIG` config-injection — done**; **M1.2 entity hashing + slim usage index — done** (`src/incremental/{hashing,edges}.py`; `parser.py` writes `model/hashes.json` `{entityKey→token-sha256}` for functions/globals/types/macros **and** `model/edges.json` `{typeUsers, macroUsers}`; token-based, deterministic, edges cross-reference hashes); **M1 fully done** (`--config`/`ANALYZER_CONFIG`; entity hashing `model/hashes.json`; slim usage index `model/edges.json`; D9 stores `src/incremental/stores.py` + fingerprints + version-producing full-gen `generate.py`; backend `POST …/generate` + `versions` APIs in `backend/main.py`; verified e2e on `samplecpp` → `versions/v2` + seeded `cache/index.json`); **M2 in progress** — **M2.1** baseline+preview (`git_ops.py`+`baseline.py`) **+ M2.2** classify+impact BFS (`impact.py`) **+ M2.3** the incremental engine (`engine.py::generate_incremental`) **done** (verified e2e on `samplecpp`: v1@C3→v2@HEAD, 3 new + 6 impact incl. transitive deleted-caller, 109 reused); **parse strategy = FULL-parse + selective-LLM-regen (D10)**; **M2 fully done** — **M2.4a** `mode:"auto"` dispatch + **M2.4b** file-level flowchart reuse (`views/flowcharts.py` gated on `model/incremental_plan.json`); **M1+M2 complete; M3.1 (precise flowchart reuse) + M3.2 (function-summary reuse) + M3.3 (full Phase-2 enrichment reuse — behaviour-names/descriptions/globals restricted to the impact set; file/component summary gating; PNG reuse; + documents-capture bug fix) done**. The LLM-on payoff is now real (behaviour-names were the hidden 417s cost — config has descriptions+behaviourNames on). Re-test LLM-on **with a real diff** (baseline at an earlier commit than the target). **M3.4 end-of-run report done** (`src/incremental/report.py`: logged to `logs/run_<date>.log` + saved to `versions/<id>/report.txt`; inputs + change classification + reuse accounting %). Remaining M3: version-scoped reads (`?versionId=`), git_ops/git_service consolidation. **Full session summary + decisions + status in §23** — read it first when resuming incremental work).
> Previous update: 2026-06-17 (version4 integration branch: brought the FastAPI backend (§21) + the production-redesign design docs (§22; `docs/production-redesign/`) from `version3` onto the newer `main` code line. The backend was built against the older `modulesGroups`/`module` schema — adapting it to main's `layers`/`component`/`components.json` schema and new CLI flags is an open follow-up; see §21).
> Previous update: 2026-06-16 (fix/issues branch: three DOCX fixes — (1) TOC field depth extended from `"1-3"` to `"1-4"` so Heading 4 entries (`2.1.1.1`, `2.1.1.2`, …) appear in the table of contents; (2) `scopeItems` in 1.2 Scope section now render with `-` instead of `•` while actual component names keep `•`; (3) copyright sentence added below `assets/copyright.png` on cover page — 8 pt, gray (`#808080`), left-aligned, text defaults to `"© <year> All Rights Reserved."` and is overridable via `config.docx.copyrightText`; `_build_cover_page` gains a `copyright_text` param; see §12).
> Previous update: 2026-06-16 (feat: styled DOCX cover page — `_build_cover_page(doc, project_name, group_name)` added to `docx_exporter.py`; replaces the old bare `Heading 0` title; first page now renders: project name (54 pt bold, navy, thick double underline) right-aligned, subtitle `"Software Detailed Design Specification — <group>"` (16 pt bold, right-aligned), version + date (12 pt, right-aligned), copyright image left-aligned below text, full-width decorative arc at bottom; project name read from `model/metadata.json → projectName` at export time; group label derived from `selected_group` / `selected_components` / `"All Components"`; static assets stored in `assets/copyright.png` and `assets/bottom_arc.png`; OOXML schema order (`w:spacing` before `w:jc`) enforced to avoid Word silently ignoring alignment; see §12).
> Previous update: 2026-06-16 (`--project-name <name>` CLI flag — overrides the project name written into `model/metadata.json` as `projectName`; default remains `os.path.basename(project_path)`; parsed in `parser.py` and forwarded via `group_planner._build_model_phases`; propagates automatically to `model_deriver` (reads `projectName` from metadata), flowchart engine, and LLM prompts; `ui/app.py` derives display name from path directly and is unaffected; see §5).
> Previous update: 2026-06-15 (fix: DOCX component display names — `component_name` (normalized identifier, spaces→`-`) was being used as visible text in section headings and the Component/Unit table; introduced `component_display = component_name.replace("-", " ")` in the `export_docx` loop and passed it to `_add_component_unit_table` and `_build_component_container_mermaid`; all key lookups and filenames keep using `component_name`; see §12).
> Previous update: 2026-06-15 (`interfaceId` format change — first segment is now the layer name instead of project name: `IF_<LAYER>_<GROUP>_<UNIT>_<NN>` / `PIF_<LAYER>_<GROUP>_<UNIT>_<NN>`; digits preserved via new `_id_seg_layer` helper so "Layer1" → "LAYER1" not "LAYER"; `get_component_layer_name(config, component)` used per entry; falls back to project name for configs without a `layers` key; see §11).
> Previous update: 2026-06-15 (feat/component-level-doc branch: `--include-path <layer> <dir>` CLI flag (repeatable) — merges extra `-I` include directories into `model/clang_include_paths.json` under the named layer before Phase 1 runs; existing layer-scoping in Phase 1 (`parser.py`) and Phase 3 (`flowcharts.py` `_resolve_layer_dirs`) handles the rest automatically; unknown layer or missing directory exits with code 1; see §5).
> Previous update: 2026-06-12 (feat/component-level-doc branch: `--macros <path>` CLI flag — reads 2-column CSV (Name, Value; header row required), converts to `-D` Clang flags for Phase 1; rows with `Value="ne"` (case-insensitive) are skipped; empty Value → `-DNAME`; written to `model/clang_macros.json` so Phase 3 flowchart engine picks them up via `flowcharts.py`; sample at `config/macros.csv`; see §5, §10).
> Previous update: 2026-06-11 (feat/auto-clang-includes branch: component-level DOCX export + space normalization — `--selected-component` (repeatable, bundles into one DOCX), `--component-per-docx` (splits group/layer into one DOCX per component); spaces in group/component names replaced with `-` in all identifiers (keys, filenames, output dirs, Mermaid IDs) while display names keep spaces; `_build_file_component_map` in `parser.py` now normalizes component name values; `safe_filename` spaces→`-`; `get_component_layer_name` uses normalized comparison; see §4f, §5, §7, §9, §10).
> Previous update: 2026-06-11 (feat/auto-clang-includes branch: `--selected-component` flag added — repeatable, accumulates a list; all components must be in the same layer; output to `output/<C1_C2>/`; new `get_component_layer_name` in `core.config`; `group_planner` has a fifth dispatch shape; `run_views` and `docx_exporter` both handle the new flag; see §5).
> Previous update: 2026-06-09 (feat/auto-clang-includes branch: Phase 1 parsing scoped to selected layer — `--selected-group` passes itself to `parser.py` which derives the layer via `get_group_layer_name`; new `--selected-layer` flag parses one layer and generates DOCX for all its groups; both flags together are an error; `clang_include_paths.json` also scoped to the selected layer; new `get_group_layer_name` / `get_layer_flat_groups` helpers in `core.config`; see §4e, §5, §7).
> Previous update: 2026-06-09 (feat/from-main branch: `module` → `component` rename throughout source + model + config; `modulesGroups` → `layers` two-level config schema; same-layer model filtering in Phase 3 + Phase 4; `SampleCppProject` restructured with Layer1 + Layer2/Platform; `model/modules.json` → `model/components.json`; new `get_flat_groups` / `get_layer_components` helpers in `core.config`; `--trace-prompts` + `--filter-mode` CLI flags; `model/clang_include_paths.json` written by `run.py` before any phase; see §5, §6, §7, §9, §10, §11, §12, §15).
> Current active branch: `feat/frontend-app` (React frontend implementation — branched from `main` 2026-06-22; `frontend/app/` contains the full Vite + React + TS + Tailwind v4 app; HTML designs in `frontend/designs/`; see §24 for full frontend stack detail).
> Previous active branch: `feat/product-ui-redesign` (earlier UI redesign exploration; superseded by `feat/frontend-app`).
> Pipeline branch: `version4` (integration base off `main`: main code + version3 backend + production-redesign docs).
> Validated against current source. Reading this file end-to-end is the
> intended way to onboard or to refresh context after compaction.
>
> Quick orientation:
> - §4 covers the version2 refactor batches (architecture layer `src/core/`, `src/llm_core/`).
> - §4b covers the version3 LLM layer upgrade (token budgeting, two-pass descriptions, few-shot, cache, review, CFG simplify, strict config + startup banner).
> - §4c covers the feat/test-framework changes (test overhaul, LIBCLANG_PATH, llm.summarize).
> - §4d covers the feat/from-main changes (component rename, layers config, same-layer filtering, SampleCppProject restructure).
> - §4e covers the feat/auto-clang-includes changes (layer-scoped Phase 1 parsing, `--selected-layer` flag).
> - §4f covers component-level DOCX export (`--selected-component`, `--component-per-docx`) and space normalization in identifiers.
> - §21 orients you to the FastAPI backend (`backend/`; detail in backend/PROJECT_CONTEXT.md).
> - §22 orients you to the Production Redesign (POC→production design; docs in docs/production-redesign/).
> - All pre-existing sections have been updated in place where these branches changed behaviour.

---

## 1. What this project does

Parses a C++ source tree with **libclang**, derives a structured model of every
function / global / type, runs a set of "views" that turn the model into JSON
+ Mermaid + PNG artifacts, and finally renders a **Software Detailed Design**
DOCX document. An optional LLM pipeline enriches the model with descriptions,
behaviour names, and per-function CFG flowcharts.

The pipeline is **subprocess-based and crash-recoverable**: each of the four
phases is its own Python entry point, and `run.py` resumes from any phase via
`--from-phase N`.

---

## 2. Top-level layout

```
analyzer/
  run.py                      Entry point — argv parsing, plan + dispatch
  config/
    config.json               Main config (JSONC: // and /* */ comments allowed)
    config.local.json         Local overrides (gitignored)
    abbreviations.txt         Abbreviation expansions for LLM prompts
    puppeteer-config.json     Optional headless-chrome args for mmdc
  src/
    parser.py                 Phase 1 — libclang AST → model/*.json
    model_deriver.py          Phase 2 — units / modules / call-graph / LLM enrich
    run_views.py              Phase 3 — load model, dispatch view registry
    docx_exporter.py          Phase 4 — output/* → software_detailed_design_*.docx
    utils.py                  Analyzer-specific helpers (keys, types, ranges)
    llm_enrichment.py         Prompt builders + enrichment loops (uses llm_core)
    core/                     Cross-cutting infrastructure (no upward imports)
    llm_core/                 Unified LLM HTTP client (Ollama + OpenAI gateway)
    views/                    View registry + four built-in views
    flowchart/                Real C++ → Mermaid CFG flowchart engine
  fake_behaviour_diagram_generator.py    Placeholder behaviour-diagram emitter
  ui/
    app.py                    Streamlit UI — run/export controls + function browser (see §14b)
    requirements.txt          streamlit, pyvis, networkx
  SampleCppProject/           Fixture C++ tree — Layer1 + Layer2/Platform (see §15)
  model/                      Phase 1+2 output (JSON)
    clang_include_paths.json  Written by run.py before Phase 1; {LayerName:[abs_dirs]}
  output/                     Phase 3+4 output (JSON, .mmd, .png, .docx)
  logs/                       Daily log files (run_YYYYMMDD.log)
  CLAUDE.md                   Onboarding pointer (says "read PROJECT_CONTEXT.md")
  PROJECT_CONTEXT.md          This file
```

---

## 3. The 4-phase pipeline

```
Phase 1  src/parser.py          C++ source → model/metadata.json,
                                             model/functions.json,
                                             model/globalVariables.json,
                                             model/dataDictionary.json
Phase 2  src/model_deriver.py   model/ → model/units.json,
                                          model/components.json,
                                          model/knowledge_base.json (for flowchart engine),
                                          model/summaries.json (LLM hierarchy summaries)
                                  + enriches functions.json with interfaceId,
                                    direction, transitive globals, behaviour
                                    names, and (optionally) LLM descriptions
Phase 3  src/run_views.py       model/ → output/interface_tables.json,
                                          output/unit_diagrams/*.mmd|.png,
                                          output/behaviour_diagrams/*.mmd|.png,
                                          output/flowcharts/*.json|.png
Phase 4  src/docx_exporter.py   output/ → software_detailed_design_<group>.docx
```

Each phase is launched as a subprocess by [src/core/orchestration.py](src/core/orchestration.py).
That keeps the phases hermetic (separate Python processes inherit `LOG_LEVEL`)
and lets `--from-phase N` skip earlier phases on a resume.

---

## 4. Refactor history (`version2` branch)

Six refactor batches landed on this branch on top of `main`. Each batch is a
self-contained consolidation; together they introduce the `src/core/` and
`src/llm_core/` layers and shrink the legacy hot files.

| # | Batch | Result |
|---|---|---|
| 1 | LLM Foundation | New `src/llm_core/` — single `LlmClient` for OpenAI gateway + Ollama with shared retry, think-section stripping, token tracking |
| 2 | Progress & Logging | `core.logging_setup` (stderr + daily file), `core.progress.ProgressReporter`, `LOG_LEVEL` env propagation to subprocesses |
| 3 | Config & Paths | `core.paths.ProjectPaths` (cached snapshot), `core.config` typed accessors with JSONC parser |
| 4 | Model IO | `core.model_io` — canonical filename constants, `read_model_file` / `write_model_file` (opt-in atomic), `load_model(*required, optional=...)` |
| 5 | Phase Orchestration | `core.orchestration.Phase` + `PhaseRunner` (single subprocess authority), `core.group_planner.plan_runs` (collapses 3-branch dispatch), run.py 257 → 152 lines |
| 6 | Config Relocation | Moved `load_config` / `load_llm_config` / JSONC strippers from `utils.py` into `core.config`, leaving thin re-export shims so existing call sites keep working |

The result: `src/core/` is the bottom of the dependency graph and has no
imports from analyzer-level modules. Verified by `grep -r "from utils" src/core/`
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
reusable helpers in `src/llm_core/`.

### What was NOT adopted (explicit out-of-scope)

- Tool-calling agentic loop (Ollama doesn't support it reliably).
- YAML config migration (keep JSONC).
- Full pipeline rewrite — still the same 4-phase subprocess architecture.

### Batch matrix (what every phase delivered)

| Phase | Delivered | Key files |
|---|---|---|
| **P1 — Foundation** | TokenCounter (tiktoken + char fallback), ContextBudget with `TASK_RATIOS`, `LlmClient.call()` multi-message API, config additions (`maxContextTokens`, `enrichment.*`, `fewShotExamplesDir`, `cacheVersion`) | `llm_core/token_counter.py`, `llm_core/budget.py`, `llm_core/client.py`, `core/config.py`, `config/config.json` |
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
them in `config/config.json` or `config.local.json`.

### Token budgeting — `ContextBudget` + `TASK_RATIOS`

One config knob (`maxContextTokens`) now scales every prompt allocation.
[src/llm_core/budget.py](src/llm_core/budget.py) defines `TASK_RATIOS` — a
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
`maxContextTokens`, `cacheVersion`, `fewShotExamplesDir`, `customHeaders`)
are type-checked the same way. `provider` is restricted to
`"ollama"`|`"openai"`.

`core.config.format_llm_config_banner(llm_cfg)` returns a multi-line summary.
Both [run.py](run.py) and [src/flowchart/flowchart_engine.py](src/flowchart/flowchart_engine.py)
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

`run.py` now reads `clang.llvmLibPath` from the loaded config and, if the
file exists, exports it as `os.environ["LIBCLANG_PATH"]` before launching any
subprocess. `src/flowchart/flowchart_engine.py` picks it up at import time:

```python
_libclang = os.environ.get("LIBCLANG_PATH", "")
if _libclang:
    import clang.cindex as _ci; _ci.Config.set_library_file(_libclang)
```

This means `clang.llvmLibPath` no longer needs to be set only for
`parser.py` — it propagates to the flowchart engine subprocess too, without
any CLI flag change.

### 2. `llm.summarize` config flag

`run.py` now respects a new optional `llm.summarize` boolean in
`config.json`. When `false`, it sets `no_llm_summarize = True` before calling
`plan_runs`, suppressing Phase 2 hierarchy summarization. This mirrors what
`--no-llm-summarize` does on the CLI, but can be committed in `config.local.json`
for a permanent local preference.

### 3. Unit-test suite overhaul

| File | What changed |
|---|---|
| `tests/unit/test_llm_client.py` | Fully rewritten to test `llm_core.client.LlmClient` + `from_config` (was testing legacy `llm_client` module). Covers constructor validation, `generate()` / `call()`, retry logic, `from_config` builder. |
| `tests/unit/test_behaviour_diagram_generator.py` | Switched from `fake_behaviour_diagram_generator.FakeBehaviourGenerator` to the real `behaviour_diagram_generator.SequenceDiagramGenerator` (alias kept as `FakeBehaviourGenerator`). Patch target updated to `behaviour_diagram_generator.llm_client`. No-LLM pass: module docstring now lists which classes need no LLM (ExternalCallerFiltering, FileNaming, MmdContent) vs which are xfail (LlmContract); repeated `functions` dict extracted into `_ONE_EXTERNAL_CALLER` module-level constant; stale fence-strip comment removed from `TestMmdContent`. |
| `tests/unit/test_utils.py` | `_strip_json_comments` / `_strip_trailing_commas` now imported from `core.config`, not from `utils`. |
| `src/flowchart/tests/test_cfg_topo.py` | Added `src/` to `sys.path` so `ast_engine.*` imports resolve when running from the project root. |
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

`config.json` now uses a two-level `layers` structure instead of the flat
`modulesGroups`. Format:

```jsonc
"layers": {
  "Layer1": {
    "path": "Layer1",          // relative to <project_path>
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
Falls back to the old `layer` key for backwards compatibility.

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

`config.json` defines two layers pointing at these directories. The old
`test_cpp_project/` fixture is **no longer used** (replaced by
`SampleCppProject/`).

---

## 4e. feat/auto-clang-includes changes

### Layer-scoped Phase 1 parsing

Previously, Phase 1 always parsed every file across all configured layers regardless of `--selected-group`. Since there is no cross-layer communication (only cross-group/cross-component within the same layer), this was wasted work.

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

**`--selected-component <name>`** (repeatable) — generate one DOCX covering the named component(s). Repeat the flag for each component; all must be in the same layer. Phase 1+2 parse that layer only. Output: `output/<C1_C2>/software_detailed_design_<C1_C2>.docx`. Mutually exclusive with `--selected-group`, `--selected-layer`, and `--component-per-docx`.

```bash
python run.py --selected-component Gpio SampleCppProject
python run.py --selected-component "Sample Core" --selected-component Lib SampleCppProject
```

**`--component-per-docx`** — modifier flag (no value). When combined with `--selected-group`, `--selected-layer`, or no selection, splits output into **one DOCX per component** instead of one per group. Cannot be combined with `--selected-component`.

```bash
python run.py --selected-group "My Sample" --component-per-docx SampleCppProject
python run.py --selected-layer Layer1 --component-per-docx SampleCppProject
python run.py --component-per-docx SampleCppProject   # all components in all layers
```

### Naming conventions for identifiers

Group and component names may contain spaces (e.g. `"My Sample"`, `"Sample Core"`). Two rules apply everywhere a name becomes an identifier (filename, output dir, model key, Mermaid node ID):

- **Space within a name → `-`**: `"Sample Core"` → `Sample-Core`
- **Separator between component names in a bundle → `_`**: `["Sample-Core", "Lib"]` → `Sample-Core_Lib`

Display contexts (DOCX section headings, log labels) keep the original name with spaces.

### Where normalization is applied

| Location | What changed |
|---|---|
| `src/utils.py` — `safe_filename` | Spaces → `-` before unsafe-char replacement |
| `src/utils.py` — `_resolve_component_from_rel` | Returns `component.replace(" ", "-")` |
| `src/parser.py` — `_build_file_component_map` | Both `setdefault` calls store `component.replace(" ", "-")` |
| `src/views/unit_diagrams.py` — `_unit_part_id` | `replace(" ", "_")` → `replace(" ", "-")` |
| `src/core/group_planner.py` — group output paths | `g.replace(" ", "-")` for dir + DOCX name |
| `src/core/group_planner.py` — component bundle | `virtual_name = "_".join(selected_components)` |
| `src/run_views.py` — `_filter_model_to_components` | `{c.lower().replace(" ", "-") for c in allowed}` |
| `src/run_views.py` — `_analyzerAllowedComponents` | Keys normalized on set: `k.replace(" ", "-")` |
| `src/docx_exporter.py` — same-layer filter | Both `lower` sets normalized with `.replace(" ", "-")` |
| `src/core/config.py` — `get_component_layer_name` | Normalizes both sides of comparison |
| `run.py` — `--selected-component` collection | Normalizes input at `append` time |

**Important after this change**: any existing `model/functions.json` built before this change will have `"Sample Core|..."` keys (with spaces). Re-run from Phase 1 (`--clean` or `--from-phase 1`) after updating to get normalized `"Sample-Core|..."` keys.

### `plan_runs` dispatch shapes (updated)

`--component-per-docx` adds a new branching mode inside the existing per-group loop. When set, `plan_runs` iterates each group's components and emits one `RunPlan` per component (using `--selected-component`) instead of one per group.

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

## 5. CLI — `run.py`

### Syntax

```bash
python run.py [options] <project_path>
```

### Flags

| Flag | Effect |
|---|---|
| `--clean` | Delete `model/` and `output/` before starting |
| `--config <path>` | Use this config file instead of `config/config.json` — a per-project/per-version config (carries the project's `layers`). Resolved+validated, then exported as `ANALYZER_CONFIG` **before** the import-time config load in `utils`, so every phase subprocess (env inherited) honors it. `config.local.json` is **not** merged on top (used as-is, for reproducibility); a set-but-missing path fails loud. Foundation for incremental per-project runs (§23, M1.1). |
| `--use-model` (alias `--skip-model`) | Skip Phases 1+2; verify required model files exist; run Phases 3+4 only |
| `--no-llm-summarize` | Skip Phase 2 LLM hierarchy summarization (faster, lower quality). Summarization is **on by default**. Can also be set via `llm.summarize: false` in config (see §4c). |
| `--llm-summarize` | Accepted for back-compat; no-op (already default) |
| `--selected-group <name>` | Export only the named group. Phase 1+2 parse only that group's layer. Case-insensitive. Mutually exclusive with `--selected-layer` and `--selected-component`. |
| `--selected-layer <name>` | Parse only the named layer (Phase 1+2) and generate DOCX for every group in it (Phase 3+4 per group). Mutually exclusive with `--selected-group` and `--selected-component`. |
| `--selected-component <name>` | Export a DOCX for the named component only. Repeatable — use once per component to bundle multiple into one DOCX. All named components must be in the same layer. Output: `output/<C1_C2>/software_detailed_design_<C1_C2>.docx` (`_` between names, `-` replaces spaces). Mutually exclusive with `--selected-group`, `--selected-layer`, and `--component-per-docx`. |
| `--component-per-docx` | Modifier: split group/layer runs into one DOCX per component instead of one per group. Compatible with `--selected-group`, `--selected-layer`, or no selection. Cannot be combined with `--selected-component`. See §4f. |
| `--from-phase N` | Resume from phase N (1=Parse, 2=Derive, 3=Views, 4=Export). Lets you continue after a Phase 4 crash without re-parsing |
| `--data-dictionary <path>` | CSV file merged into `model/dataDictionary.json` at end of Phase 1. External entries win on conflict. See `config/data_dictionary.csv` for format. |
| `--project-name <name>` | Override the project name written into `model/metadata.json` as `projectName`. Default: `os.path.basename(project_path)`. Propagates to `model_deriver` (interfaceId fallback segment, LLM knowledge base), flowchart engine, and LLM prompts. `ui/app.py` derives its display name from the path directly and is unaffected. |
| `--macros <path>` | CSV file (columns: `Name`, `Value`; first row is header) passed as `-D` flags to Clang in Phase 1. Rows where `Value` is `"ne"` (case-insensitive) are skipped. Empty `Value` → `-DNAME`; non-empty → `-DNAME=VALUE`. Macros are also written to `model/clang_macros.json` so the Phase 3 flowchart engine picks them up. Sample: `config/macros.csv`. |
| `--include-path <layer> <dir>` | Add an extra `-I` include directory for the named layer. Repeatable — use once per directory. The directory is merged into `model/clang_include_paths.json` under the named layer key before Phase 1 runs, so Phase 1 and Phase 3 (`_resolve_layer_dirs`) pick it up automatically via existing layer-scoping. Unknown layer → exit 1. Missing directory → exit 1. |
| `--filter-mode <mode>` | Override `views.sequenceDiagrams.filterMode` for this run (e.g. `single_per_function`) |
| `--trace-prompts` | Print full LLM prompts (system + user) to stdout. Sets `LLM_TRACE_PROMPTS=1` env var. **Warning**: large runs emit tens of MB. |
| `--quiet` | stderr handler raised to WARNING |
| `--verbose` | stderr handler lowered to DEBUG |

`--quiet` and `--verbose` set `LOG_LEVEL` in the environment so child phases
inherit the same verbosity.

### Argument parsing

Hand-rolled token-scanning loop in [run.py](run.py) (no `argparse`). Two
historical bugs are guarded against here:

1. `--selected-group core` used to leave `core` as a positional after the flag
   was consumed. Fix: each flag explicitly consumes its value (`i += 1`).
2. `--from-phase` is validated to 1–4 and exits with a clear error otherwise.

### Plan + dispatch

After parsing flags, run.py:

0. **Layer include paths** — resolves the selected layer (from `--selected-group` or `--selected-layer`), then walks only that layer's directories (or all layers if neither flag is set) and writes `model/clang_include_paths.json`. Phase 1 reads this to extend `CLANG_ARGS` with `-I<dir>` for each collected directory.
1. Loads `config/config.json` (+ `config.local.json`) via `load_config`.
1a. **Collects layer include paths** — walks the relevant layer directory/directories under `<project_path>` recursively (skipping hidden dirs), stores result as `{LayerName: [abs_dir, …]}`, and writes it to `model/clang_include_paths.json` before any phase starts. When `--selected-group` or `--selected-layer` is set, only the targeted layer is walked. Read by Phase 1 (`parser.py`) and Phase 3 (`flowcharts.py`) — neither re-walks the filesystem.
2. **Resolves the LLM block strictly via `load_llm_config(cfg)`** and prints the
   `format_llm_config_banner` to the log so the operator sees exactly which
   provider, baseUrl, model, `numCtx`, resolved `maxContextTokens`, retries,
   cache version, and enrichment flags will be used. If the LLM block is
   missing, malformed, or has an invalid value, `LlmConfigError` is raised and
   `run.py` exits with code 2 — there are no silent defaults. (See §17 design
   decision "Fail loud on config errors".)
3. Validates `<project_path>` exists.
4. If `--use-model` is set, verifies `model/functions.json`, `globalVariables.json`,
   `units.json`, and `modules.json` are all present (paths via
   `core.model_io.model_file_path`). Exits 2 if missing.
5. Calls [core.group_planner.plan_runs(...)](src/core/group_planner.py) which
   returns a flat `List[RunPlan]`.
6. Iterates the plans through a single [PhaseRunner](src/core/orchestration.py)
   instance. Each plan corresponds to one `runner.run(plan.phases, from_phase=plan.runner_from_phase)` call.

The banner also re-renders inside `flowchart_engine.py::run()` when Phase 3
(flowchart engine) starts, because that engine can be invoked standalone — see
§13.

### Dispatch shapes (collapsed inside `plan_runs`)

| Config state | CLI | Phase 1+2 parses | Phase 3+4 generates |
|---|---|---|---|
| No `layers` (or `layer`) | (any) | everything | one DOCX |
| `layers` present | no flag | all layers | DOCX per group (all groups) |
| `layers` present | `--selected-group <G>` | G's layer only | DOCX for G only |
| `layers` present | `--selected-layer <L>` | L only | DOCX per group in L |
| `layers` present | `--selected-component C [--selected-component C2 …]` | C's layer only (all named components must be same layer) | 1 DOCX for C[_C2…] |
| `layers` present | any of above + `--component-per-docx` | same as without flag | 1 DOCX **per component** instead of per group |

`--selected-group`, `--selected-layer`, and `--selected-component` are mutually exclusive; combining any two exits with code 1. `--component-per-docx` cannot be combined with `--selected-component` (already at component granularity).

Phase 4 (`docx_exporter.py`) receives the group's `interface_tables.json`
and DOCX path as positional args plus `--selected-group <G>` (group path) or
`--selected-component C [--selected-component C2]` (component path) so it can
apply the same-layer model filter (see §4d).

`--from-phase` translation also lives here:
- `from_phase ≤ 2`: build-model plan starts at that index, group plans start at 1.
- `from_phase ≥ 3`: build-model plan is **suppressed**; each group plan uses `local_from = max(1, from_phase - 2)` (so 3→1, 4→2 inside the views+export plan).

---

## 6. Config — `config/config.json`

JSONC: `//`, `/* */`, and trailing commas are tolerated by
`core.config._strip_json_comments` + `_strip_trailing_commas`. A sibling
`config.local.json` is merged on top if present.

### Current schema

```jsonc
{
  "views": {
    "interfaceTables": true,
    "unitDiagrams":     false,
    "flowcharts":       false,
    "behaviourDiagram": false,
    "componentStaticDiagram": true   // was "moduleStaticDiagram" in older versions
  },
  "clang": {
    "llvmLibPath":       "C:\\Program Files\\LLVM\\bin\\libclang.dll",
    "clangIncludePath":  "C:\\Program Files\\LLVM\\lib\\clang\\17\\include"
  },
  "llm": {
    // ── required fields — load_llm_config raises LlmConfigError if missing ──
    "provider":          "ollama",        // "ollama" | "openai"  (strictly validated)
    "baseUrl":           "http://localhost:11434",
    "defaultModel":      "llama3.2",
    "timeoutSeconds":    300,             // positive int
    "numCtx":            8192,            // Ollama context window (positive int)
    "retries":           1,               // >=0; up to (1+retries) total tries

    // ── optional fields ──
    "descriptions":      false,           // enable LLM function descriptions (Phase 2)
    "behaviourNames":    false,           // enable LLM behaviour input/output names
    "summarize":         false,           // false = suppress Phase 2 hierarchy summarization
    "apiKey":            "",              // openai bearer; prefer env LLM_API_KEY
    "customHeaders":     { "x-dep-ticket": "credential:", "User-Type": "AD_ID", ... },

    // version3 — token budgeting
    "maxContextTokens":  127488,          // null → auto: numCtx-512 for Ollama, 127488 for OpenAI
    "cacheVersion":      1,               // bump to invalidate llm entity cache
    "fewShotExamplesDir": "few_shot_examples",

    // version3 — enrichment feature flags (every flag must be a bool)
    "enrichment": {
      "twoPassDescriptions": true,   // Pass 2 refines with caller context   (2x desc cost)
      "selfReview":          false,  // generate→review→revise (≥20-line fns) (3x cost)
      "ensemble":            false,  // 3 temps + synthesis for unit/component summaries (4x cost)
      "cfgSimplification":   false,  // LLM proposes merge/drop plan for >15-node CFGs
      "variableEnrichment":  true    // rich global-variable descriptions
    }
  },
  // Two-level layer structure (replaces old "modulesGroups").
  // paths inside groups are relative to the layer's "path".
  "layers": {
    "Layer1": {
      "path": "Layer1",
      "groups": {
        "Sample": {
          "Core": "Sample/Core",
          "Lib":  "Sample/Lib",
          "Util": "Sample/Util"
        },
        "Full": {
          "Iface": ["Direction", "Types", "Flow"],
          "Cross": ["Hub", "Poly"]
        },
        "Support": { "Math": "Math", "App": "App", "Outer": "Outer/Inner" },
        "Access":  { "Access": "Access" },
        "Diag":    { "Diag": "Diag" }
      }
    },
    "Layer2": {
      "path": "Layer2",
      "groups": {
        "Platform": {
          "Gpio": "Platform/Gpio", "Uart": "Platform/Uart",
          "Spi":  "Platform/Spi",  "I2c":  "Platform/I2c",
          "Adc":  "Platform/Adc",  "Display": "Platform/Display",
          // … (15 components total)
        }
      }
    }
  },
  "ui": { "theme": "Light" }
}
```

### Environment-variable overrides for `llm`

`load_llm_config()` (in [src/core/config.py](src/core/config.py)) honors:

| Env var | Wins over |
|---|---|
| `LLM_PROVIDER` | `llm.provider` |
| `LLM_BASE_URL` | `llm.baseUrl` |
| `LLM_DEFAULT_MODEL` | `llm.defaultModel` |
| `LLM_TIMEOUT_SECONDS` | `llm.timeoutSeconds` |
| `LLM_NUM_CTX` | `llm.numCtx` |
| `LLM_RETRIES` | `llm.retries` |
| `LLM_API_KEY` | `llm.apiKey` |

Custom-header values can be overridden via `X_DEP_TICKET`, `USER_TYPE`,
`USER_ID`, `SEND_SYSTEM_NAME` (handled inside `llm_core.headers`).

### Config rules

- Group names and component names: **CapitalCamelCase or snake_case**, both are tolerated.
- Each folder path should appear in exactly one component; the parser merges all
  layers/groups into one big folder set so cross-layer calls are still discoverable.
- `selectedGroup` is **not** a config key — group selection is CLI-only.
- Layer `"path"` is relative to `<project_path>`. Component paths inside a group
  are relative to the layer's path and are prepended by `get_flat_groups()`.
- Old `modulesGroups` / `layer` top-level keys still load via `get_flat_groups()`
  for backwards compatibility. New code always uses `layers`.
- LLM is off by default for descriptions/behaviour names. Phase 2 hierarchy
  summarization (which writes `summaries.json` + `knowledge_base.json`) is
  on by default and is controlled by `--no-llm-summarize`.
- **Strict validation** (version3): missing/empty/wrong-type required fields
  cause `run.py` (and `flowchart_engine.py`) to print `Invalid LLM config:
  <specific field>` and exit(2). There are no silent defaults for the required
  fields. Fix the JSON (or the matching env var) and re-run.
- **Startup banner** (version3): every run prints the resolved LLM
  configuration — provider, baseUrl, model, numCtx, `maxContextTokens`
  (resolved, e.g. `auto -> 7680`), timeout, retries, apiKey status,
  `cacheVersion`, `fewShotExamplesDir`, and which enrichment flags are ON/OFF.
  See §4b for an example.

---

## 7. `src/core/` — infrastructure layer

Eight modules, all with no upward imports. Anything analyzer-specific stays
in `src/utils.py` or one of the phase scripts.

### `core.paths` — [src/core/paths.py](src/core/paths.py)

- `ProjectPaths` frozen dataclass with `project_root`, `src_dir`, `config_dir`,
  `config_path`, `config_local_path`, `model_dir`, `output_dir`, `logs_dir`,
  `cache_dir`.
- `paths()` returns a cached singleton; `set_project_root(path)` clears it.
- Auto-detects root by walking two parents up from `paths.py` (so the snapshot
  works no matter where you launch from).

### `core.config` — [src/core/config.py](src/core/config.py)

- `_strip_json_comments` / `_strip_trailing_commas` — JSONC parser.
- `load_config(project_root)` — merges `config/config.json` + `config.local.json`. **If `ANALYZER_CONFIG`
  env points to a file, that file is loaded instead, as-is (JSONC), with no local merge** — the per-project
  config-injection seam (§23, M1.1); set-but-missing fails loud.
- `load_llm_config(cfg)` — env-var overlay + normalised `llm` block (see §6).
- `app_config(*, refresh=False)` — process-cached merged dict.
- Typed accessors: `llm_config()`, `views_config()`, `exporter_config()`,
  `clang_config()`, `components_groups()`.
- `get_flat_groups(cfg)` — flattens `layers` (or fallback `layer`) into
  `{groupName: {componentName: resolvedPath}}` with layer path prepended.
- `get_layer_components(cfg, group_name)` → `set` of all component names in
  the same layer as `group_name`. Used by Phase 3 and Phase 4 for same-layer
  model filtering.
- `get_group_layer_name(cfg, group_name)` → the layer name that owns `group_name`, or `None`. Used by `parser.py` and `run.py` to derive the layer from `--selected-group`.
- `get_component_layer_name(cfg, component_name)` → the layer name that owns `component_name` (searches all layers/groups), or `None`. Comparison is space-normalized (both sides `.replace(" ", "-")`) so normalized identifiers match raw config keys. Used by `run.py` and `group_planner` to derive the layer from `--selected-component`.
- `get_layer_flat_groups(cfg, layer_name)` → flat groups for a single named layer only (layer paths resolved). Used by `parser.py` to restrict `_COMPONENT_FOLDERS` when a layer is selected.
- `_resolve_layer_paths(layers_cfg)` — internal helper that prepends
  `layer.path` to each component path inside the layer's groups.
- `default_clang_macro_defs()` — returns the `-D` macro list shared by
  Phase 1 and the flowchart engine's per-function re-parser.

### `core.model_io` — [src/core/model_io.py](src/core/model_io.py)

Canonical filenames (use these constants, never bare strings):
`METADATA`, `FUNCTIONS`, `GLOBALS`, `UNITS`, `COMPONENTS`, `DATA_DICTIONARY`,
`KNOWLEDGE_BASE`, `SUMMARIES`. Tuple `ALL_MODEL_NAMES` lists them all.
(`MODULES` constant was removed; `COMPONENTS` is its replacement.)

Functions:
- `model_file_path(name)` → absolute path under `paths().model_dir`.
- `model_files_present(*names)` → list of MISSING canonical names.
- `read_model_file(name, *, required=True, default=None)` → dict, raises
  `ModelFileMissing` if required and absent.
- `load_model(*required, optional=None)` → `{name: data}`. Optional names
  default to `{}` when missing.
- `write_model_file(name, data, *, atomic=False, indent=2)` → writes JSON.
  When `atomic=True`, writes to a sibling tempfile then `os.replace()`s into
  place.
- `ensure_model_dir()` → mkdirs and returns the model dir.

### `core.logging_setup` — [src/core/logging_setup.py](src/core/logging_setup.py)

- `configure_logging(*, project_root, quiet, verbose, log_dir)` installs:
  - **stderr** handler at INFO (or DEBUG/WARNING based on flags + `LOG_LEVEL`)
  - **daily file** handler at DEBUG → `<project_root>/logs/run_YYYYMMDD.log`
- Idempotent; later calls just adjust the stderr level.
- `get_logger(name)` auto-configures with defaults if no caller has yet.
- `set_level(level)` re-tunes stderr after the fact.
- Registers an `atexit` hook that dumps `llm_core.tokens.format_report()` so
  every subprocess records its own LLM token usage to the log file.

### `core.progress` — [src/core/progress.py](src/core/progress.py)

`ProgressReporter(component, *, total, logger, log_every)` with `start()`,
`step(label=...)`, `done(summary=...)`, and a context-manager API. On a TTY
it uses `\r` for live updates; when piped it falls back to periodic INFO log
lines (every ~10% by default). Quiet mode suppresses the live line entirely
but still logs the final summary.

### `core.orchestration` — [src/core/orchestration.py](src/core/orchestration.py)

```python
@dataclass(frozen=True)
class Phase:
    name: str               # "Phase 1: Parse C++ source"
    script: str             # "parser.py"
    args: List[str]         # CLI argv after the script

class PhaseRunner:
    def run(self, phases, *, from_phase=1) -> float
```

Single subprocess authority. Phases with `idx < from_phase` are skipped with a
log line. On a non-zero exit code the runner emits
`resume with: --from-phase {idx}` and raises `SystemExit(returncode)`.

### `core.group_planner` — [src/core/group_planner.py](src/core/group_planner.py)

Constants: `PHASE_PARSE=1`, `PHASE_DERIVE=2`, `PHASE_VIEWS=3`, `PHASE_EXPORT=4`.

```python
@dataclass
class RunPlan:
    label: str
    phases: List[Phase]
    runner_from_phase: int = 1

def plan_runs(cfg, *, project_path, selected_group, use_model,
              no_llm_summarize, from_phase=1) -> List[RunPlan]
```

Implements the three dispatch shapes from §5 in one place. Raises `ValueError`
on unknown `--selected-group`.

### `core.__init__` — [src/core/__init__.py](src/core/__init__.py)

Re-exports every public symbol so call sites can write
`from core import PhaseRunner, plan_runs, FUNCTIONS, ...`.

---

## 8. `src/llm_core/` — unified LLM client + token-budget toolkit

Post-version3, `src/llm_core/` is a full toolkit: one HTTP client plus a set of
composable helpers (counter, budget, context builder, repo map, few-shot,
cache, structured output, review). Everything LLM-related in the project
flows through this layer.

```
src/llm_core/
  client.py              LlmClient + from_config — single HTTP client (ollama + openai)
  headers.py             build_openai_headers + resolve_api_key
  think.py               strip_think_section
  tokens.py              process-wide token usage counter (record + format_report)
  token_counter.py       TokenCounter (tiktoken wrapper + char/3.5 fallback) — version3
  budget.py              ContextBudget + TASK_RATIOS + resolve_max_tokens      — version3
  context_builder.py     ContextBuilder — callee/caller/types degradation ladder — version3
  repo_map.py            RepoMap — scoped repo signature view (4 tiers)          — version3
  few_shot.py            FewShotPool — keyword-ranked example selection          — version3
  cache.py               EntityCache — composite-hash disk cache                 — version3
  structured_output.py   extract_and_validate + parse_label_response             — version3
  review.py              self_review + ensemble_generate                        — version3
```

Public API re-exported from `llm_core.__init__`:
`LlmClient`, `from_config`, `strip_think_section`, `tokens`,
`TokenCounter`, `get_counter`, `ContextBudget`, `resolve_max_tokens`,
`extract_and_validate`, `parse_label_response`, `self_review`,
`ensemble_generate`.

### `llm_core.client.LlmClient` — [src/llm_core/client.py](src/llm_core/client.py)

Two providers behind one interface:

| Provider | Endpoint (single-call / chat) | Auth |
|---|---|---|
| `ollama` | `POST {baseUrl}/api/generate` and `/api/chat` | none |
| `openai` | `POST {baseUrl}/chat/completions` | bearer + custom headers |

Two public call methods:
- `generate(system_prompt, user_prompt)` — simple system+user pair.
- `call(messages, *, temperature=None)` (version3) — multi-message chat API
  with per-call temperature override. Backing for ensemble + self-review.

Shared pipeline:
1. **Retry loop** — `max_retries+1` total tries, retries on Timeout /
   ConnectionError / HTTPError / empty response.
2. **`strip_think_section`** — strips `<think>...</think>` blocks before returning.
3. **Token tracking** — every successful call records prompt+completion tokens
   into `llm_core.tokens` (process-wide counter dumped at exit).

Hard rules baked in for the OpenAI route:
- A class-level `_OPENAI_LOCK` serialises every OpenAI request process-wide.
- Every OpenAI call is followed by `time.sleep(3.0)` (`_OPENAI_RATE_LIMIT_SEC`)
  even on failure, because the corporate gateway throttles ~1 req/3s.

Public properties (version3 adds `num_ctx`):
`client.provider`, `client.model`, `client.num_ctx` — prefer these over
poking `_provider` / `_model` / `_num_ctx`.

`from_config(llm_cfg)` builds an `LlmClient` from a `load_llm_config()` dict.
Legacy positional args (`url=`, `use_openai_format=`) still accepted so the
flowchart engine's standalone subprocess invocation keeps working.

### `llm_core.headers`, `llm_core.think`, `llm_core.tokens`

- `headers` — `build_openai_headers`, `resolve_api_key`. Resolves `LLM_API_KEY`
  env var first, falls back to `llm.apiKey`. Handles the corporate-gateway
  custom-header format and `X_DEP_TICKET`/`USER_TYPE`/`USER_ID`/`SEND_SYSTEM_NAME`
  env overrides.
- `think.strip_think_section(text)` — removes `<think>...</think>` sections
  (gpt-oss / DeepSeek R1 style) so downstream consumers see just the answer.
- `tokens.record(provider, model, prompt, completion)` + `format_report()` —
  process-wide counter dumped automatically by the logging atexit hook so
  each subprocess writes its own report into `logs/run_YYYYMMDD.log`.

### `llm_core.token_counter.TokenCounter` (version3)

Thin wrapper around `tiktoken.get_encoding("cl100k_base")` when tiktoken is
installed, otherwise falls back to `len(text) / 3.5` (C++ code tokenizes at
roughly 2–3 chars/token, so 3.5 is conservative).

```python
counter = TokenCounter(model="qwen2.5-coder:14b")
counter.count(text)                          # int
counter.fits(text, budget)                   # bool
counter.truncate_to_budget(text, budget)     # str — binary-search by token count
```

Module-level `get_counter(model)` caches one instance per model.

### `llm_core.budget.ContextBudget` + `TASK_RATIOS` + `resolve_max_tokens` (version3)

See §4b for the full story. Summary:

- `TASK_RATIOS: Dict[str, Dict[str, float]]` — per-task section ratios
  (sum to ~1.0, enforced by assertion). Tasks include `function_description`,
  `function_description_refined`, `variable_description`, `behaviour_names`,
  `function_summary`, `file_summary`, `module_summary`, `project_summary`,
  `cfg_node_labeling`, `cfg_coherence`, `cfg_simplification`, `self_review`,
  `ensemble_synthesis`.
- `ContextBudget(max_tokens, task, counter)` — holds a 10 % safety margin;
  `.allocate(section)` returns the section's token budget.
- `resolve_max_tokens(llm_cfg)` — priority: explicit `maxContextTokens` →
  `numCtx − 512` (ollama) → 127488 (openai). Expects a validated llm_cfg —
  no silent default for `provider` or `numCtx` any more.

### `llm_core.context_builder.ContextBuilder` (version3)

Degradation ladder: prefers breadth over depth. Starts every callee / caller /
type at Level 0 (full source + description), and when the total exceeds the
budget it promotes the lowest-priority items one level at a time until it
fits. Levels:

```
Level 0: Full source + description
Level 1: Signature + 3-line description
Level 2: Signature + 1-line purpose
Level 3: Signature only
Level 4: Qualified name only
```

Public methods: `fit_callees(callees, budget)`, `fit_callers(callers, budget)`,
`fit_types(types, budget)`. Priority ranking is by call-site count,
public/exported status, and usage frequency in the target function.

### `llm_core.repo_map.RepoMap` (version3)

Compact signature-level view built from `knowledge_base.json` (no extra
parsing). Four tiers tried from most-specific to most-general until one fits
the budget:

1. Function neighborhood — callees + callers + same-file functions
2. File level — all functions in the same file with signatures
3. Module level — all files in the module with function counts
4. Project level — module names with file counts

```python
RepoMap(knowledge).for_function(qn, budget, counter) -> str
```

Injected as a new section in both `pkb/builder.build_base_context_packet()`
(for flowchart labels) and `llm_enrichment.get_rich_description()` (for
function descriptions).

### `llm_core.few_shot.FewShotPool` (version3)

Loads hand-curated examples from
`few_shot_examples/{descriptions,labels,globals,behaviour_names}/*.json`.
Each example: `{"tags": [...], "input_context": "...", "ideal_output": "..."}`.

```python
FewShotPool(examples_dir).select(task, target_input, budget, counter) -> str
```

Ranking: keyword overlap (callee names, param types, tags). Budget-aware
greedy fill. Returns `""` if the directory is missing or empty — that is the
supported off-path, not an error.

### `llm_core.cache.EntityCache` (version3)

Per-entity disk cache with composite hash keys. Stored at
`.flowchart_cache/llm_descriptions/` (or whatever `cache_dir` the caller
passes).

```python
EntityCache(cache_dir, cache_version)
  .get(entity_id, content_hash) -> Optional[dict]
  .put(entity_id, content_hash, value, metadata=None)
  .stats() -> "N hits, M misses, X% hit rate"
```

Cache key = `sha256(entity_source + sorted_callee_hashes + str(cache_version))[:16]`.

Dependency tracking is implicit: when function A's source changes, its hash
changes, so its cache misses. When A's callee B changes, B's hash changes,
so A's composite hash (which includes B's hash) also changes, causing A to
miss too. Bumping `llm.cacheVersion` invalidates everything.

### `llm_core.structured_output.extract_and_validate` (version3)

```python
extract_and_validate(raw_response, expected_keys=None) -> Optional[Dict]
```

Robust JSON extraction + repair + schema validation in one function. Handles
markdown fences, trailing commas, single quotes, explanatory text around JSON,
and missing closing braces. Replaces the old ad-hoc `_extract_json()` in
`flowchart/llm/generator.py` and ad-hoc parsing paths in `llm_enrichment.py`.

`parse_label_response(raw)` is the flowchart-specific helper that extracts
a `{node_id: label}` dict from an LLM reply.

### `llm_core.review` — `self_review`, `ensemble_generate` (version3)

```python
self_review(client, draft, evidence) -> str
ensemble_generate(client, system, user, temperatures=[0.0, 0.3, 0.7]) -> str
```

- `self_review` — generate → review → revise cycle. Review prompt asks
  "is this accurate? does it miss behaviours? are side effects listed?".
  Returns an issues list or "OK"; revision happens only if issues are found.
  3 LLM calls worst case. Applied to function descriptions (≥20 non-blank
  lines) and high-visibility summaries when `llm.enrichment.selfReview=true`.
- `ensemble_generate` — 3 temperatures + synthesis call (4 total). Only
  applied to unit / module / project summaries when
  `llm.enrichment.ensemble=true`. Scales to ~80 extra calls for a
  ~20-module project.

Both helpers use `extract_and_validate` when parsing verdicts.

---

## 9. `src/utils.py` — analyzer-specific helpers

Post-Batch-6, this file is ~360 lines and only owns analyzer-specific logic.
Anything that touches files or env or generic infra has moved into `core.*`.

### Re-exports (back-compat shims)

```python
from core.config import load_config, load_llm_config
```

So legacy `from utils import load_config` still works.

### What lives here

| Function / constant | Purpose |
|---|---|
| `KEY_SEP = "\|"` | Separator for module / unit / function / global keys |
| `log(msg, component, *, err=False)` | Thin wrapper around `core.logging_setup.get_logger` |
| `timed(component)` ctx-mgr | Logs `<elapsed>s` on exit |
| `mmdc_path(project_root)` | Local `node_modules/.bin/mmdc` or system `mmdc` |
| `safe_filename(s)` | Replace spaces with `-`, then `<>:"/\\|?*,&;` with `_` |
| `init_component_mapping(config)` | Build `_COMPONENT_OVERRIDES` from `components` or merged `layers` groups (via `get_flat_groups`) |
| `_resolve_component_from_rel(rel)` | Match relative path against `_COMPONENT_OVERRIDES` (case-insensitive) |
| `make_unit_key(rel_file)` | `component\|unitname` |
| `make_global_key(rel_file, qn)` | `component\|unit\|qualifiedName` |
| `make_function_key(component, rel_file, qn, params)` | `component\|unit\|qualifiedName\|paramTypes` |
| `path_from_unit_rel(rel)` | Strip extension, normalise slashes |
| `short_name(qn)` | Last `::` segment |
| `path_is_under(base, candidate)` | Safe containment via `os.path.relpath` |
| `get_component_name(file_path, base_path)` | Absolute path → component name (uses `_resolve_component_from_rel`) |
| `resolve_group(component)` | Component name → group name (from `_GROUP_MAP` built at import) |
| `norm_path(path, base_path)` | Resolve relative paths against `base_path` |
| `PRIMITIVES` dict | C++ primitive types → range string |
| `get_range_for_type(type_str)` | Map type to range; falls back to `NA` |
| `get_range(type_str, data_dictionary)` | Range lookup with typedef recursion (depth 10) |

Note: `init_component_mapping` runs at import time using the on-disk config, so
`make_*_key` works immediately. `parser.py` builds its own folder list from
the same config via `get_flat_groups` (kept separate to avoid the analyzer's
import order constraints).

---

## 10. Phase 1 — `src/parser.py`

### Initialization

- Reads `core.config.app_config()` and `clang_config()`.
- Loads libclang from `clang.llvmLibPath`. On Windows, calls
  `os.add_dll_directory(<llvm/bin>)` so dependent DLLs are found, with a
  `PATH`-extension fallback.
- Builds `_FILE_COMPONENT_MAP` via `_build_file_component_map` from merged `layers` groups via `get_flat_groups` (or `components`/`modules` top-level fallback). Component name values are stored normalized (spaces → `-`) so all model keys use the identifier form.
- Reads `model/clang_include_paths.json` (written by `run.py` before any phase)
  and extends `CLANG_ARGS` with `-I<dir>` for every directory in every layer.
- Sets `CLANG_ARGS`:
  - `-std=c++14`
  - `-I<MODULE_BASE_PATH>`, `-I<clangIncludePath>`
  - `-I<every dir from clang_include_paths.json>` (all layer subdirectories)
  - `-DPRIVATE=` `-DPROTECTED=` `-DPUBLIC=` `-D__OVLYINIT=` (visibility macros via `default_clang_macro_defs()`)
  - **Auto-derived layer paths** — reads `model/clang_include_paths.json`
    (written by `run.py` before Phase 1) and appends `-I<dir>` for every
    directory across all layers. No manual listing in `clang.clangArgs` needed
    for directories already declared in `layers` config.
  - Any extras from `config.clang.clangArgs`.
  - **User macros** (when `--macros <path>` is set) — reads the 2-column CSV,
    appends `-DNAME=VALUE` (or `-DNAME` for empty value) for each non-`ne` row,
    then writes the list to `model/clang_macros.json` so `flowcharts.py` can
    apply the same flags to the Phase 3 flowchart engine re-parser. Sample:
    `config/macros.csv` (`VOID,void`).

### Visibility detection (`_detect_visibility`)

Scans **backwards up to 5 source lines** from a declaration line looking for
the first token `PRIVATE`, `PUBLIC`, or `PROTECTED`. Returns the matching
lowercase string or `default`. Required because the visibility macros are
expanded to nothing by `-DPRIVATE=` and Clang doesn't surface them.

### File filtering (`is_project_file`)

Rejects anything outside `MODULE_BASE_PATH` and (when `_COMPONENT_FOLDERS` is
non-empty) anything whose relative path doesn't start with one of the
configured folder prefixes (case-insensitive after `os.path.normcase`).

> **Known risk** — uses `startswith` rather than `path_is_under()`, so
> `C:\foo` and `C:\foobar` would alias. The fix is in `utils.path_is_under`;
> migrating `is_project_file` to use it is open work.

### Three traversal passes (`main`)

1. `parse_file` → `visit_definitions` + `visit_type_definitions` — collects
   functions, globals, and type declarations.
2. `parse_calls` → `visit_calls` — builds `call_graph` (caller → callees) and
   `reverse_call_graph` (callee → callers) by walking `CALL_EXPR` cursors
   inside function bodies. Tries `cursor.referenced` first, falls back to
   name match in known functions.
3. `parse_global_access` → `visit_global_access` — for each function body,
   walks `DECL_REF_EXPR` cursors that point at global `VAR_DECL`s. Distinguishes:
   - Pure write (`=`) → adds to `global_access_writes`
   - Compound op (`+=`, `-=`, …) → both reads and writes
   - `++` / `--` → writes
   - Otherwise → reads
   Uses its own `_visited_global_access_keys` set (separate from `visit_calls`)
   so function bodies are not skipped. When a nested `FUNCTION_DECL` or
   `CXX_METHOD` (e.g. a lambda) is encountered inside an outer function, its
   children are visited under the inner key and any writes are propagated back
   to the outer function's `global_access_writes`.
   Also captures the first `RETURN_STMT` token sequence as `returnExpr`.

### Function collection (`visit_definitions`)

- Cursor kinds: `FUNCTION_DECL`, `CXX_METHOD`. Forward decls are kept with
  `declarationOnly: True`.
- Internal key during collection: mangled name, or `qualified@file:line`.
- Captures `parameters` via `cursor.get_arguments()`, records `extent.end.line`
  as `endLine`.
- Handles `_var_decl_should_record_as_function_not_global` — when Clang emits
  a `VAR_DECL` for `TYPE FuncName(id1)` because a `__OVLYINIT`-style macro
  expanded to nothing, it's reclassified as a function with
  `syntheticFromVarDecl: True` and parameters reconstructed from the
  `DECL_REF_EXPR` children.

### Global variable collection

Only globals at translation-unit or namespace scope (excludes class members).
The initializer value is extracted by scanning the source line for `=`.

### Type collection (`visit_type_definitions`)

Builds `data_dictionary`:
- `STRUCT_DECL` / `CLASS_DECL` with field list
- `ENUM_DECL` with enumerators and computed range
- `TYPEDEF_DECL` with underlying type and range lookup
- Special pattern: `_maybe_add_typedef_for_struct` adds a typedef entry when
  the source uses `typedef struct { ... } Name;`

### Define scanning (`_scan_defines`)

Plain text scan of every `.cpp`, `.h`, `.hpp` for `#define` lines. Honours
backslash continuation. Stores `name`, `value`, full macro text, and
`location`.

### Direction assignment (`build_metadata`)

Based on direct global access recorded by `visit_global_access`:
- writes any global (including via nested lambda) → `direction = "In"`
- reads globals, writes none → `direction = "Out"`
- no global access → `direction = "Out"` (pure function)

Phase 2 forces every function's direction to `"In"` or `"Out"` (never empty)
and every global to `"In/Out"`.

### Final keying (`build_metadata` + `utils.make_function_key`)

Final model key: `component|unit|qualifiedName|paramTypes`.

- `component` from `get_component_name(file_path, base_path)` → `_resolve_component_from_rel`.
- `unit` from filename without extension.
- `qualifiedName` includes namespace + class.
- `paramTypes` is the comma-joined list of normalised parameter type strings.

### External data dictionary merge

After `_scan_defines()` and before writing `dataDictionary.json`, if `--data-dictionary <path>` was passed (or `dataDictionaryPath` is set in config), `_merge_external_data_dictionary(path)` is called:

- Reads a CSV with columns: `Name, Kind, EntryName, Range, Comment`.
- **Top-level rows** (non-empty `Name`): copy existing auto-parsed entry, overwrite `kind`/`range`/`comment` from CSV, reset `enumerators`/`fields` list if the kind uses them.
- **Child rows** (empty `Name`, Kind=`enumerator` or `field`): carry forward the last non-empty `Name` as parent key and append `{name: EntryName, value/range, comment}` to the parent's list. Empty `Name` matches Excel merged-cell CSV exports.
- External entries win on conflict. New entries (not in parsed source) are added as-is.
- `location` and other auto-parsed fields are preserved on updated entries via `dict(existing)` copy.

### Outputs

`metadata.json`, `functions.json`, `globalVariables.json`, `dataDictionary.json`
written to `model/` via `core.model_io.write_model_file`.

---

## 11. Phase 2 — `src/model_deriver.py`

Loads via `core.model_io.load_model(METADATA, FUNCTIONS, GLOBALS)` and exits
with a clear "Run Phase 1 first" message on `ModelFileMissing`.

### `_build_units_components`

Groups all functions and globals by file path. Produces:
- `model/units.json` — one entry per `.cpp/.cc/.cxx` (headers excluded from
  unit keys). Each entry has `name`, `path`, `fileName`, `functionIds` (sorted
  by source line), `globalVariableIds`, `callerUnits` (set), `calleesUnits` (set),
  and `includedHeaders` (read from local `#include` directives).
- `model/components.json` — one entry per component containing its unit keys
  and `headerFiles` list. (Was `model/modules.json` in older versions.)

### `_build_interface_index` / `_enrich_interfaces`

Assigns a per-file sequential index and sets `interfaceId` on each function and global. Rules:

- **Functions are numbered first** (sorted by line), then **globals continue the same counter** — so globals always have higher indices than functions in the same file.
- **Public entries** use prefix `IF_` → `IF_<LAYER>_<GROUP>_<UNIT>_<NN>`
- **Private entries** use prefix `PIF_` → `PIF_<LAYER>_<GROUP>_<UNIT>_<NN>`, numbered in a separate independent sequence (so public IDs have no gaps).
- Private functions/globals are excluded from `output/interface_tables.json` (view filter unchanged).

`<LAYER>` is resolved per entry via `get_component_layer_name(config, component)` and processed by `_id_seg_layer` (keeps uppercase letters **and digits**, so "Layer1" → "LAYER1"). Falls back to `_id_seg(project_name)` for old-style configs without a `layers` key. `<GROUP>`, `<UNIT>` use the existing `_id_seg` (uppercase letters only). Example: `IF_LAYER1_FULL_READWRITE_01`.

**Function privacy rule (call-graph based, `_fn_is_private`):**
A function is private if either condition holds:
1. Its source-level `visibility` is `"private"` (detected by `_detect_visibility` in parser.py), OR
2. None of its `calledByIds` entries belong to a different file — i.e. it has no cross-unit callers (including the case of zero callers).

Explicit `PUBLIC` source annotation does **not** protect a function from being classified private — the call graph is authoritative. Two helpers implement this:
- `_has_external_caller(f, functions_data, base_path)` — returns `True` if any caller lives in a different file.
- `_fn_is_private(f, functions_data, base_path)` — combines the two conditions above.

Globals use the old visibility-only rule (they have no call graph).

Also normalises `parameters` to `[{name, type}]`, dropping any extra fields the parser captured.

### `_propagate_global_access`

Fixed-point: each function's read/write set is unioned with each callee's
sets. Stored as `readsGlobalIdsTransitive` / `writesGlobalIdsTransitive`.
Used by behaviour-name heuristics so a wrapper function can be labelled by
what it ultimately touches.

### `_enrich_behaviour_names` (static heuristics)

**Input name** priority:
1. First parameter name (run through `_readable_label`: strip `g_`/`s_`/`t_`,
   underscores → spaces).
2. First written global name.
3. First read global name.
4. Fallback: `"<FunctionBaseName> input"`.

**Output name** priority:
1. First identifier-looking token of `returnExpr`.
2. Last word of `returnType` if non-primitive.
3. First written global name.
4. First read global name.
5. Fallback: `"<FunctionBaseName> result"`.

`_static_behaviour_name_is_poor` returns True if the name ends with ` input`
or ` result` (i.e. fell through to the fallback) — used to gate the LLM call.

### `_enrich_behaviour_names_llm`

When `config.llm.behaviourNames: true` and the static result is poor: calls
`llm_enrichment.get_behaviour_names(...)` with source, params, globals
read/written, return type, return expression, draft input/output names, and
abbreviations. The unified `LlmClient` runs the request through the
appropriate provider.

### `_enrich_from_llm` (version3 — rich path)

When `config.llm.descriptions: true`:

1. Tries to load `model/knowledge_base.json` (may not exist on first run —
   the rich path still works, just without repo-map / sibling context).
2. Calls **`enrich_functions_rich(functions_data, base_path, config, knowledge=…)`**
   from [src/llm_enrichment.py](src/llm_enrichment.py) — the version3
   budget-aware function enrichment path. It:
   - Resolves `max_context_tokens` via `resolve_max_tokens(llm_cfg)`.
   - Builds `ContextBuilder`, `RepoMap`, `FewShotPool`, `EntityCache`.
   - Topologically orders functions (callees first) and skips any that
     already have a source `comment`.
   - **Pass 1 (always)** — bottom-up. Each function sees callee descriptions
     built at this pass. Uses `get_rich_description()` with budget-allocated
     sections: repo_map, function source, callees, types/globals, siblings,
     few_shot, abbreviations.
   - **Pass 2 (when `enrichment.twoPassDescriptions=true`, default true)** —
     re-runs in the same order. Now both callee AND caller descriptions from
     Pass 1 are available. Uses `_get_refined_description()` which compares
     the prior description against caller context.
   - **Self-review (when `enrichment.selfReview=true`)** — for functions with
     ≥20 non-blank lines, runs `_run_self_review()` which wraps
     `llm_core.review.self_review(client, draft, evidence)`. 3 LLM calls
     worst case per reviewed function.
   - Every result goes into `EntityCache` keyed on
     `sha256(source + sorted_callee_hashes + cache_version)[:16]`. Re-runs
     are 10× faster because unchanged functions (and functions whose callees
     are unchanged) hit the cache.
3. Calls **`enrich_globals_rich(...)`** when `enrichment.variableEnrichment=true`
   (default true). This replaces the old one-line declaration prompt with
   rich evidence: declaration + write-site 2–3-line snippets + read-site
   snippets + containing-file summary + related functions. Falls back to
   `enrich_globals_with_descriptions` (the old version2 path) when
   `variableEnrichment=false`.
4. A `ProgressReporter` reports `[idx/total]` progress for every pass.

### `_enrich_with_hierarchy_summaries`

Default-on (disabled by `--no-llm-summarize`). Uses the flowchart engine's
`HierarchySummarizer` (in `src/flowchart/pkb/`) to produce a 4-level summary:

1. Function level — one-sentence summary for any undocumented function.
2. File level — 2–3 sentences per source file.
3. Module level — 2–3 sentences per module directory.
4. Project level — overall description (prefers a README if present).

The summarizer is fed a `ProjectKnowledge` object built from the parsed
`functions_data` (no extra libclang or scanning). The LLM client is built via
`_build_llm_client_from_config(load_llm_config(config))`, so provider
switching, custom headers, and retries all work.

After the run, `phases` and `comment` fields are written back into
`functions_data` so they're persisted in `functions.json`.

### `_generate_knowledge_base`

Writes `model/knowledge_base.json` in the format the flowchart engine's
`pkb.builder.ProjectKnowledgeBase` consumes:

```jsonc
{
  "functions": { qn: { qualifiedName, signature, file, line, comment, calls[], phases[] } },
  "enums":     { qn: { values: { name: { value, comment } } } },
  "macros":    { name@file:line: { value, text, comment } },
  "typedefs":  { qn: { underlyingType, comment } },
  "structs":   { qn: { fields: [...] } }
}
```

This file is what `views/flowcharts.py` passes to `flowchart_engine.py` via
`--knowledge-json` so the per-function LLM prompts get rich context.

### Final cleanup

- Direction forced to `"In"` or `"Out"` for all functions.
- Globals assigned `direction = "In/Out"`.
- `params` field dropped (replaced by normalised `parameters`).
- All four files (`functions.json`, `globalVariables.json`, `units.json`,
  `modules.json`) plus `summaries.json` and `knowledge_base.json` written via
  `core.model_io.write_model_file`.

---

## 12. Phase 3 — `src/run_views.py` + `src/views/`

### Orchestration — [src/run_views.py](src/run_views.py)

CLI:
```
python src/run_views.py [--output-dir <dir>] [--selected-group <name>]
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

Then it calls `views.run_views(filtered_model, output_dir, model_dir, config)`.

### View dispatch — [src/views/__init__.py](src/views/__init__.py)

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

The four view modules are imported at the bottom of `__init__.py` so their
`@register("name")` decorators populate `VIEW_REGISTRY`.

### View 1: `interfaceTables` — [src/views/interface_tables.py](src/views/interface_tables.py)

Output: `output/interface_tables.json` (or `output/<group>/interface_tables.json`).
Full logic and column definitions: `docs/DESIGN_SPEC.md` — Interface Tables.

- Iterates `.cpp` units only; header-only units skipped.
- Filters by `_analyzerAllowedComponents` if set.
- Includes `PUBLIC` and `PROTECTED` functions and globals; excludes `PRIVATE`.
- Entries sorted by source line number within each unit.
- For each function: builds `callerUnits` / `calleesUnits` (all units including
  same-module), and `sourceDest` (external units only; `"-"` if none).
- Enriches parameters with `range` from the data dictionary via `get_range()`.
- Strips file extensions from `location.file`.
- Columns: Interface ID, Interface Name, Information, Data Type, Data Range,
  Direction (In/Out), Source/Destination, Interface Type.

### View 2: `unitDiagrams` — [src/views/unit_diagrams.py](src/views/unit_diagrams.py)

One Mermaid `.mmd` (and optionally `.png`) per unit into
`output/unit_diagrams/`.
Full logic and layout rules: `docs/DESIGN_SPEC.md` — Unit Diagrams (REQ-UD-XX).

- `.cpp` units only; filtered by `allowed_modules` when set.
- Layout: external callers on the left, **yellow** module box in the centre,
  external callees on the right, all flowing left-to-right.
- The main unit is **blue with a thick border** (`mainUnit` class); sibling units in the module subgraph are blue thin (`internal` class).
- Edges labelled with `interfaceId` values, `<br/>`-separated for multi-edge.
- Self-calls (callee in the same unit) produce no edge.
- Project root resolved from `dirname(model_dir)` (NOT `output_dir`) so
  grouped output paths work.
- PNG rendered by `mmdc` (mermaid-cli). 60s timeout per diagram.

### View 3: `behaviourDiagram` — [src/views/behaviour_diagram.py](src/views/behaviour_diagram.py)

Generates one `.mmd` per (current function, external caller) pair via the
placeholder `FakeBehaviourGenerator` in
[fake_behaviour_diagram_generator.py](fake_behaviour_diagram_generator.py).

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

### View 4: `flowcharts` — [src/views/flowcharts.py](src/views/flowcharts.py)

Wraps the **real flowchart engine** under `src/flowchart/`. Steps:

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
   python src/flowchart/flowchart_engine.py
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

---

## 13. The flowchart engine — `src/flowchart/`

A self-contained C++ → Mermaid CFG generator. Invoked as a subprocess by the
`flowcharts` view but can also run standalone.

### Subpackage layout

```
src/flowchart/
  flowchart_engine.py        Main entry, orchestrates per-function pipeline
  project_scanner.py         Standalone scanner that builds project_knowledge.json
  config.py                  EngineConfig dataclass (CLI defaults)
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
10. **Validation** — `validate_cfg(cfg)` then `validate_mermaid(script)`.
    Failures are logged at WARNING but don't abort the run.
11. **Build Mermaid** — `build_mermaid(cfg)`.

### `LIBCLANG_PATH` env var (feat/test-framework)

At import time, `flowchart_engine.py` checks `os.environ["LIBCLANG_PATH"]`.
If set (and the path is a file), it calls
`clang.cindex.Config.set_library_file(path)` before any libclang call.
`run.py` sets this env var from `clang.llvmLibPath` in config so the value
propagates automatically into the flowchart engine subprocess.

### LLM client construction + banner + enrichment config (version3)

At the top of `run()`, [src/flowchart/flowchart_engine.py](src/flowchart/flowchart_engine.py)
calls `_load_analyzer_llm_config()` which walks `cwd` and one parent for
`config/config.json`, loads it with `utils.load_config`, then resolves it
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

## 14. Phase 4 — `src/docx_exporter.py`

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
python src/docx_exporter.py [json_path] [docx_path] [--selected-group <name>]
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

- Functions: `Data Type` = `; `.join of param types; `Data Range` = `; `.join of param ranges from `get_range()`.
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

Input/Output Name = `behaviourInputName` / `behaviourOutputName` from
`functions.json`. Risk = `"Medium"` (hardcoded). Capacity(Density) =
`"Common"` (hardcoded).

### Dynamic Behaviour section

Reads `artifacts_dir/behaviour_diagrams/_behaviour_pngs.json`. For every
`(module, unit, [{currentFunctionName, externalUnitFunction, pngPath}])`:
- Heading: `<sec>.2.<idx> <unitName> - <functionName> (<externalUnitFunction>)`
- Behaviour description table (`_add_behavior_description_table`) with input/output names from the model.
- Embedded PNG if `pngPath` is non-empty and exists.

---

## 14b. Streamlit UI — `ui/app.py`

Run with: `streamlit run ui/app.py` (opens at `http://localhost:8501`).

### What it does

Single-page app. Left column: all config controls + run buttons. Right
column: tabbed output (`Output log` / `Modules Groups`).

### Config controls (left column)

Reads `config/config.json` + `config.local.json` on init, writes back to
`config.local.json` on every run and on the hide/show toggle.
Covers: project path, clang paths, all LLM fields, all views toggles,
export settings, and `modulesGroups` (editable group/module/path tree).

### Run buttons

| Button | What it runs |
|---|---|
| Run full pipeline | `python run.py [--no-llm-summarize] [--selected-group G] <proj>` |
| Export only | `python run.py --from-phase 4 --use-model [--selected-group G] <proj>` |

### Modules Groups tab — function browser

Hierarchical tree: Group → Module → Unit → functions. Each function row
has two columns:
- **Function button** (col 5): opens `_function_dialog` modal (description,
  callers/callees, flowchart viewer). Shows `fname() [hidden]` and is
  disabled when hidden.
- **Hide/Show button** (col 1): calls `_toggle_function_hidden(fid, bool)`,
  which writes `{"hidden": true/false}` directly into `model/functions.json`.
  No config change. Triggers `st.rerun()` so the label updates immediately.

### `_toggle_function_hidden(fid, hidden)`

Writes the `hidden` field into `model/functions.json` at `ROOT/model/functions.json`.
Uses the same path as `_save_function_description` — no group-aware path logic.
The `hidden` field is read by Phase 4 (`export_docx`) to filter output
(see §14 — Function hiding). Phase 3 does **not** read this field.

### `_function_dialog` modal

Opens on function button click. Left panel: signature, description textarea
+ Save button, Calls/Called-by expanders, Behaviour names. Right panel:
flowchart viewer (reads pre-rendered PNG or Mermaid from `output/`).

---

## 15. Test fixture — `SampleCppProject/`

The old `test_cpp_project/` fixture is superseded. Current fixture (matches
`config.json` `layers`):

```
SampleCppProject/
  Layer1/
    Access/   AccessVisibility.cpp/.h  — PRIVATE/PUBLIC/PROTECTED macros
    App/      Main.cpp                 — top-level entry
    Diag/     ForwardVoidDecl, MultilineOvlyinit, PreprocIf*, VoidAsVar,
              VoidIsVoid               — synthetic-from-VAR_DECL recovery cases
    Direction/ ReadWrite.cpp/.h        — In/Out direction from globals
    Flow/     Flowcharts.cpp/.h        — control-flow patterns (if/else, switch, loops)
    Hub/      Hub.cpp/.h               — cross-component fan-out
    Math/     Utils.cpp/.h             — small math helpers
    Outer/Inner/ Helper.cpp/.h         — nested-directory component path
    Poly/     Dispatch.cpp/.h          — virtual dispatch / polymorphism
    Sample/
      Core/   Core.cpp/.h              — Sample group, Core component
      Lib/    Lib.cpp/.h               — Sample group, Lib component
      Util/   Util.cpp/.h              — Sample group, Util component
    Types/    PointRect.cpp/.h, Types.cpp/.h — struct + union types, enum/typedef
  Layer2/
    Platform/                          — 15 stub platform components (3-5 files each)
      Adc/ AdcCal/ AdcFilter/          — ADC components
      Cache/ CachePol/ LruCache/       — Cache components
      Config/ CfgParse/ CfgStore/      — Config components
      Display/ DispBuf/ DispFont/ FrameBuf/ — Display components
      EventBus/ EvbQueue/ Event/       — EventBus components
      Gpio/ Gpio{Alt,Cfg,Debounce,Group,Input,Irq,Mux,Output,Pin,Port}/ — GPIO
      I2c/ I2cMaster/ I2cScan/         — I2C components
      Logger/ LogBuf/ LogFmt/          — Logger components
      Network/ NetBuf/ Socket/ TcpClient/ — Network components
      Protocol/ ProtoCrc/ ProtoFrame/ ProtoHdlr/ — Protocol components
      Scheduler/ SchedCfg/ Task/ TaskQueue/ — Scheduler components
      Spi/ SpiCfg/ SpiDev/             — SPI components
      Storage/ Eeprom/ Flash/ StorCache/ — Storage components
      Timer/ TmrHw/ TmrMgr/            — Timer components
      Uart/ Uart{Buf,Clock,Debug,Dma,Error,Fifo,Flow,Init,Irq,Mode,...}/ — UART
```

`config.json`'s `layers` maps these to:
- **Layer1**: groups `Sample` (Core/Lib/Util), `Full` (Iface/Cross), `Support`
  (Math/App/Outer), `Access`, `Diag`
- **Layer2**: group `Platform` (all 15 platform components)

### Key docs

- `docs/DESIGN_SPEC.md` — view logic requirements with verification criteria (REQ-IT-XX for Interface Tables, REQ-UD-XX for Unit Diagrams). Update first before changing any view logic.
- `docs/TEST_INVENTORY.md` — maps every DESIGN_SPEC requirement to its test case. Update after adding/changing tests.
- `.coveragerc` — single `.coverage` file written per run.

### Quick run commands

```bash
# Full run, all groups
python run.py SampleCppProject

# Full clean run, single group
python run.py --clean SampleCppProject --selected-group Sample

# Skip the LLM hierarchy summaries (faster, lower quality)
python run.py --no-llm-summarize SampleCppProject

# Reuse model/, regenerate views + docx for one group
python run.py --use-model SampleCppProject --selected-group Platform

# Resume after a Phase 4 crash without re-parsing
python run.py --from-phase 4 SampleCppProject

# Verbose stderr (DEBUG); inherited by every subprocess phase
python run.py --verbose SampleCppProject --selected-group Sample
```

---

## 16. Known risks / technical debt

### Risk 1 — `parser.is_project_file()` uses `startswith` for path containment

```python
abs_path = os.path.normcase(os.path.abspath(file_path))
abs_base = os.path.normcase(os.path.abspath(MODULE_BASE_PATH))
if not abs_path.startswith(abs_base):
    return False
```

Allows `C:\foo` to match `C:\foobar`. The correct helper exists at
[utils.path_is_under](src/utils.py); migrating `is_project_file` to use it
is open work.

### Risk 2 — flowchart filtering uses module prefix, not units.json

`views/flowcharts.py` filters `functions.json` to a group via
`fid.split(KEY_SEP, 1)[0].lower() in allowed_modules`. A more accurate
approach would walk `units.json → functionIds` for the units in that group.
The current approach can include stray functions whose key happens to start
with the right module token but whose source file isn't in any of the
group's configured folders.

### Risk 3 — `make_function_key` module fallback

If `module` is empty when called, it falls back to `parts[0]` (first path
segment). This shouldn't happen any more (`get_module_name` always returns a
real module or `"unknown"`), but a regression here would silently change keys.

### Risk 4 — ASSERT-fix linter regressions

The CFG builder skips ASSERT calls using
`cursor.extent.start.line/.column` checked against a frozen set of
`(line, col)` pairs from a regex source-scan. **Do not switch back to
`get_expansion_location()`** — that's the original bug. Linters and
auto-formatters have reverted this fix in the past. After any change to
[src/flowchart/ast_engine/cfg_builder.py](src/flowchart/ast_engine/cfg_builder.py),
re-run `python src/flowchart/tests/diagnose_assert.py`.

---

## 17. Key design decisions

### Subprocess phases (vs in-process)

Each phase is its own process, launched by `core.orchestration.PhaseRunner`.
Trade-off: a fresh Python interpreter per phase costs ~200ms but gives:
- Isolated libclang state (no leaks across phases).
- `LOG_LEVEL` env propagation just works.
- `--from-phase N` is a one-line skip in the runner.
- Pre-existing CLI entry points stay unchanged.

### Plan-once / run-many (Batch 5)

`group_planner.plan_runs()` returns a flat `List[RunPlan]`. The runner has no
knowledge of groups or `--from-phase` translation. Translation happens once at
plan time:
- `from_phase ≤ 2`: build-model plan included; group plans use local index 1.
- `from_phase ≥ 3`: build-model plan omitted; group plans use `from_phase - 2`.

### Model always built for all groups

Phase 1 parses the **union** of all configured module folders, regardless of
`--selected-group`. The group filter only affects Phases 3 + 4. This ensures
cross-group call edges remain visible even when exporting one group.

### Function hidden flag in model, not config

`hidden: true/false` is stored per-function in `model/functions.json`,
not in `config.local.json`. Rationale: it is function-specific data that
lives alongside descriptions, direction, interfaceId, etc. Config is for
pipeline behaviour settings, not per-entity data. This also means the flag
survives config resets and is visible to any future tool that reads the
model, not just the DOCX exporter.

Phase 3 does not read the `hidden` field — it still writes every function
to `interface_tables.json`. Phase 4 filters at export time, so hiding and
re-running export only (Phase 4) is the correct workflow.

### Artifacts dir from `json_path`, not `output_dir`

`docx_exporter.export_docx` uses `os.path.dirname(json_path)` as
`artifacts_dir`. This is what fixes embedded-PNG paths under `output/<group>/`.

### Project root in views from `model_dir`

The three diagram views all compute
`project_root = os.path.dirname(os.path.abspath(model_dir))`. Stable
regardless of `output_dir` value (which can be `output/<group>/`).

### Single LLM client class

Anything LLM goes through `llm_core.client.LlmClient`. There is no second
HTTP client, no per-feature wrapper. Provider switching is a config change,
not a code change. Token tracking and think-section stripping are baked in.

### `selectedGroup` is CLI-only

Was previously a config field; intentionally removed to keep group selection
unambiguous. There is no env-based override either.

### LLM is off by default for `descriptions` / `behaviourNames`

Both default to `false`. Hierarchy summarization (`--no-llm-summarize` to
disable) is the **only** LLM step that runs by default in Phase 2, because
its outputs (`summaries.json`, `knowledge_base.json`) feed the flowchart
engine.

### JSONC config

`//`, `/* */`, and trailing commas are accepted. The strippers live in
`core.config` and operate before `json.loads`.

### Fail loud on config errors (version3)

The version2 LLM config path silently defaulted missing fields (e.g.
`.get("provider", "ollama")`, `.get("numCtx", 8192)`). Debugging the
difference between "what config says" and "what's actually used" wasted
enough time that version3 replaced every silent default with a
`LlmConfigError` that names the failing field. If a user wants a different
provider/model/budget they must put it in the config — the tool will not
guess. The startup banner exists so the user can verify which values were
actually read before the long-running pipeline starts. See §4b.

### One token budget, many sections (version3)

Every LLM call in the project derives its section limits from one knob
(`llm.maxContextTokens`) via `ContextBudget(task, …)` + `TASK_RATIOS`.
Adding a new LLM task type means adding an entry in `TASK_RATIOS` — no
other code changes. Section ratios must sum to ~1.0 (enforced by assertion).

### Enrichment features are individually gated (version3)

Every enrichment feature (`twoPassDescriptions`, `selfReview`, `ensemble`,
`cfgSimplification`, `variableEnrichment`) can be turned on or off
independently via `llm.enrichment.*`. Defaults favour the cheapest safe
option: the two features with the biggest quality payoff for DOCX output
(`twoPassDescriptions`, `variableEnrichment`) are ON; the expensive ones
are OFF. Users opt into cost by flipping the flag.

---

## 18. Past mistakes / lessons learned

### `visit_global_access` used wrong visited-set (fixed)

`visit_global_access` was checking `_visited_call_keys` (shared with `visit_calls`)
instead of its own `_visited_global_access_keys`. Since `visit_calls` runs first and
adds every function, `visit_global_access` skipped every function body — no global
reads were ever recorded, so every function defaulted to `"In"`. Fixed by using
`_visited_global_access_keys` (which already existed but was never used).

### Direction default was wrong (fixed)

Functions with no global access were assigned `"In"` (the `else` branch fallback).
The correct value is `"Out"` — a pure function that touches no globals provides a
result without side effects. Fixed by making the `else` branch return `"Out"`.

### Shell on this machine

Native shell is `bash` (Git Bash) on Windows 11; `&&` chaining works there
but **not** in PowerShell. Use forward slashes for paths even on Windows.
Use `/dev/null`, not `NUL`.

### `run.py` arg parsing bug (fixed)

An older version stripped `--selected-group` from argv but left the value
(e.g. `core`) as a positional, which then became `project_path`. Fix: each
flag explicitly consumes its own value via `i += 1`.

### Broken grouped output paths (fixed in two places)

Root cause: `output_dir` was used to derive the repo root. When group output
went to `output/<group>/`, `dirname(output_dir) = output/`, not the repo
root. Fix 1: views use `dirname(abspath(model_dir))`. Fix 2: exporter uses
`dirname(json_path)` as artifacts dir.

### `--all-groups` removed

Was present in an intermediate version as a redundant flag. Removed because
all-groups is the default whenever `modulesGroups` is set and no
`--selected-group` is passed.

### Env-based group override removed

An `os.environ`-driven selected-group was added then removed. Preference in
this codebase: minimal optional code paths, explicit CLI control.

### Linter reverts the ASSERT fix

See Risk 4 in §16. The ASSERT fix in `cfg_builder.py` has been reverted by
linters/tools more than once. Always re-run `diagnose_assert.py` after
touching that file.

### Flowchart filtering implementation mismatch

Discussion in earlier sessions described traversing `units.json → functionIds`
for the group filter. The actual code in `flowcharts.py` still uses module
prefix matching (Risk 2). Re-read source after edits — discussion is not
implementation.

### Configs with `core` / `support` / `tests` vs current group names

Earlier docs referenced `InterfaceTables`, `Flowcharts`, `BehaviourDiagram`,
… as group names, then `core`, `support`, `tests`. The current `config.json`
uses `Sample`, `Full`, `Support`, `Access`, `Diag`, `Platform` (matching the
`SampleCppProject` fixture). When validating CLI behaviour, always check
which config is active before quoting group names.

### `module` → `component` rename is pervasive — don't mix old and new

The rename from "module" to "component" touched source, model JSON keys,
config, and constants. Any code that uses the old names (`MODULES`,
`_analyzerAllowedModules`, `get_module_name`, `moduleName`, `modulesGroups`,
`moduleStaticDiagram`) will silently fail to filter or produce empty output.
After any refactor, grep for the old names to confirm nothing was missed.

### `interface_tables.json` total = components in the file, not the group

Phase 4 (`docx_exporter.py`) counts sections from the `interface_tables.json`
it reads — never from the selected group's component count. If that file was
generated with more components than the selected group has, the progress
total will be wrong. Ensure Phase 3 was run for the group (which writes a
group-filtered `interface_tables.json` to `output/<group>/`) before running
Phase 4. Stale files from a previous full-project run cause the mismatch.

### Do not reach into private `_attrs` on `LlmClient` (version3)

The coherence pass used to have
`int(getattr(self._client, "_num_ctx", 8192) or 8192)` as a fallback. That
kind of access is indistinguishable from a hardcode — the config file could
say 32000 and the pass would still silently use 8192 if anything upstream
misreferenced the attribute. Fix: threaded `max_context_tokens` down from
the caller via a constructor parameter, added `LlmClient.num_ctx` as a
public property, and removed every `getattr(client, "_*", default)`. If a
new LLM helper needs to know a budget, take it as a parameter — do not
peek.

### Windows cp1252 stderr kills Unicode box-drawing (version3)

The first version of `format_llm_config_banner()` used `─` (U+2500) and
`→` (U+2192) and crashed on Windows because Python's stderr defaults to
cp1252. Fixed by switching to ASCII `-` and `->`. Rule of thumb: if text
may be printed to stderr on Windows without a deliberate UTF-8 setup, keep
it to ASCII.

### Shell heredocs fail under Git Bash on Windows (ongoing)

Multi-line `python -c "…"` with indented code hits
`IndentationError: unexpected indent` because `bash.exe` (Git Bash) on
Windows does weird things to newlines inside double-quoted strings. When
you need a multi-line Python snippet, write a temp `.py` file and run it,
or use a single expression with `;` separators. Do not try to fix heredocs
on this machine — it's a known loss.

---

## 19. API Server (`api/`)

> Full context lives in **[`api/PROJECT_CONTEXT.md`](api/PROJECT_CONTEXT.md)** — read that file for anything API-related. This section is a brief pointer only.

The `api/` directory is a standalone FastAPI REST server added on branch
`feat/api-server`. It exposes all platform functionality over HTTP and ships
with an in-memory database seeded with realistic dummy data.

Key facts:
- **Start:** `uvicorn api.main:app --reload --port 8000` (after `pip install -r api/requirements.txt`)
- **Docs:** http://localhost:8000/docs (Swagger UI)
- **Auth:** `POST /api/v1/auth/signin` → Bearer token → `Authorization: Bearer <token>` on every request
- **Seed credentials:** any of the five seed users (e.g. `alice@aspice.dev`) with password `secret`
- **Swap the DB:** set `API_DB_BACKEND=json` env var (or change one line in `api/db/session.py`) — two built-in adapters: `InMemoryDatabase` (default) and `JsonDatabase`
- **JSON DB:** `API_DB_BACKEND=json` persists state to `api/db/data/*.json` and automatically loads `model/functions.json` from the pipeline output on startup
- **51 endpoints** across auth, projects, commits/versions, analysis jobs, documents, team, compare, functions, notifications

See [`api/PROJECT_CONTEXT.md`](api/PROJECT_CONTEXT.md) for architecture decisions, known issues, seed data, SSE streaming, error envelope, the full route list, and JSON DB adapter details (§11).

---

## 20. Dependencies


```
libclang (LLVM 17)        — C++ AST parsing (clang.cindex)
python-docx               — DOCX generation
requests                  — HTTP client for both Ollama and OpenAI gateways
mermaid-cli (mmdc)        — Mermaid → PNG (npm install @mermaid-js/mermaid-cli)
```

Python deps: `requirements.txt`. Node.js: `package.json` (mmdc installed
locally into `node_modules/.bin/`). The analyzer prefers the local mmdc
binary and falls back to system `mmdc`.

---

## 21. End-to-end code flow — single command, full pipeline

For the literal-minded: this is what happens when you run

```bash
python run.py --selected-group Sample SampleCppProject
```

1. **`run.py` startup** — sets `cwd` to its own directory; prepends
   `src/` to `sys.path`; calls `core.logging_setup.configure_logging` (which
   creates `logs/run_YYYYMMDD.log` and the stderr handler).
2. **Argv loop** — parses flags. Sets `selected_group_arg = "Sample"`,
   `from_phase = 1`, `use_model = False`, `no_llm_summarize = False`.
3. **`load_config(SCRIPT_DIR)`** (re-exported from `core.config`) — reads
   JSONC, merges `config.local.json` if present. Sets `LIBCLANG_PATH` env var
   from `clang.llvmLibPath` if the file exists (propagates to all subprocesses).
   If `llm.summarize` is `false` in config, forces `no_llm_summarize = True`.
3a. **Layer include path collection** — walks each `layers.<L>.path` directory
   under `SampleCppProject/`, collecting every subdirectory. Writes
   `model/clang_include_paths.json` as `{LayerName: [abs_dirs…]}`. Runs before
   any subprocess so Phase 1 can extend its `-I` flags from it.
3b. **`load_llm_config(cfg)` + banner** — strictly validates the `llm` block
   (required: `provider`, `baseUrl`, `defaultModel`, `timeoutSeconds`, `numCtx`,
   `retries`; type-checked enrichment toggles; env-var overrides). Renders
   `format_llm_config_banner` and writes it to the log so the run begins with a
   visible record of which provider/model/budget will be used. On any
   validation failure → `LlmConfigError` → exit 2 (no silent defaults).
4. **`plan_runs(cfg, …)`** — calls `get_flat_groups(cfg)`, sees `layers` is set
   and `selected_group = "Sample"`. Returns two plans:
   - Plan 1: "Build model (all modules)" → `[parser.py <abs_project_path>, model_deriver.py]`
   - Plan 2: "Group: Sample" → `[run_views.py --output-dir output/Sample --selected-group Sample, docx_exporter.py output/Sample/interface_tables.json output/Sample/software_detailed_design_Sample.docx --selected-group Sample]`
5. **`PhaseRunner.run(plan1.phases)`** — subprocess `python src/parser.py
   <abs_project_path>`. The parser inherits `LOG_LEVEL` from env.
6. **Parser (Phase 1)** — loads libclang, reads `model/clang_include_paths.json`
   and extends `CLANG_ARGS` with `-I<dir>` for all layer subdirs. Walks every
   `.cpp/.h` under `MODULE_BASE_PATH`, runs three traversal passes, calls
   `build_metadata`, writes `metadata.json` / `functions.json` /
   `globalVariables.json` / `dataDictionary.json` to `model/`.
7. **`PhaseRunner.run(plan1.phases)` continues** — subprocess
   `python src/model_deriver.py`.
8. **Model deriver (Phase 2)** — loads model via `core.model_io.load_model`.
   Builds units + components, propagates global access transitively, assigns
   interface IDs, runs static behaviour-name heuristics, optionally calls
   the LLM for descriptions and behaviour names, optionally runs the
   `HierarchySummarizer` for `summaries.json`, generates `knowledge_base.json`
   for the flowchart engine. Writes everything back to `model/` including the
   new `model/components.json`.
9. **`PhaseRunner.run(plan2.phases)`** — subprocess
   `python src/run_views.py --output-dir output/Sample --selected-group Sample`.
10. **`run_views.py`** — loads model (`load_model(FUNCTIONS, GLOBALS, UNITS, COMPONENTS, optional=[DATA_DICTIONARY])`),
    resolves the group name case-insensitively, calls `get_layer_components` to
    find all Layer1 components, filters the full model to same-layer components
    via `_filter_model_to_components`, sets `_analyzerSelectedGroup = "Sample"`
    + `_analyzerAllowedComponents = ["Core","Lib","Util"]` on the config dict,
    calls `views.run_views(filtered_model, output/Sample, model_dir, config)`.
11. **`interface_tables` view** — writes `output/Sample/interface_tables.json`
    filtered to the Sample group's components (Core/Lib/Util). Other Layer1
    components are in the filtered model for call-edge discovery but not in the
    output.
12. **`unit_diagrams` view** — emits one `.mmd` per `.cpp` unit into
    `output/Sample/unit_diagrams/`, then renders each with `mmdc`.
13. **`behaviour_diagram` view** — uses `FakeBehaviourGenerator` to emit
    `.mmd` files plus `_behaviour_pngs.json`.
14. **`flowcharts` view** — filters `functions.json` to `functions_Sample.json`
    via component prefix, launches `python src/flowchart/flowchart_engine.py …`
    with `--knowledge-json model/knowledge_base.json`. The engine:
    - builds (or restores from `.flowchart_cache/`) the PKB
    - groups functions by source file
    - for each function: source extract → libclang TU parse → cursor resolve
      → CFG build (with ASSERT skip) → enrich with PKB → batched LLM labeling
      with auto-halving on empty responses → validate → build Mermaid
    - writes one JSON per source file into `output/Sample/flowcharts/`
    - writes `_summary.json`
    The view then walks the per-unit JSONs and renders every flowchart to
    PNG via `mmdc`.
15. **`PhaseRunner.run(plan2.phases)` continues** — subprocess
    `python src/docx_exporter.py output/Sample/interface_tables.json output/Sample/software_detailed_design_Sample.docx --selected-group Sample`.
16. **`docx_exporter.py`** — `artifacts_dir = output/Sample/`, loads model +
    abbreviations, applies same-layer filter (all Layer1 components) to model
    dicts, iterates only Sample's components (Core/Lib/Util), builds the DOCX
    via `python-docx`. Embeds component static diagrams, unit diagrams, flowchart
    PNGs, and behaviour-diagram PNGs from paths under `artifacts_dir`. Writes
    `output/Sample/software_detailed_design_Sample.docx`.
17. **Back in `run.py`** — `runner.run` returns elapsed seconds; the loop logs
    `Done. Total: <secs>s` and `Full log: logs/run_YYYYMMDD.log`. Each
    subprocess's `atexit` hook has already dumped its LLM token usage to the
    log file.

If anything in steps 5–16 fails with a non-zero exit code, the runner logs
`<phase> failed with exit code N; resume with: --from-phase <idx>`. The user
can fix the underlying issue and rerun with that flag, skipping straight to
the failed step.

---

## 21. Companion: the FastAPI backend (`backend/`)

> **Integration status (version4):** the `backend/` layer and the
> `docs/production-redesign/` design docs were brought onto this branch from
> `version3`, on top of the newer `main` code line. The backend was written
> against the **older `modulesGroups` / `module` schema** and the
> `model/modules.json` filename. This `main`-based code line instead uses the
> **`layers` config + `component` terminology + `model/components.json`** (see
> §4d, §6) and adds CLI flags (`--selected-layer`, `--selected-component`,
> `--data-dictionary`, `--macros`, `--include-path`, `--project-name`).
> **Adapting the backend to that schema and flag set is an open follow-up**
> before it runs correctly against this analyzer. The description below is the
> backend *as built on version3*.

Starting in version3, the analyzer pipeline is also reachable over HTTP
through a small FastAPI service that the external UI talks to. This
section is intentionally short — it orients you to the layer; the
authoritative reference is **[backend/PROJECT_CONTEXT.md](backend/PROJECT_CONTEXT.md)**
(~930 lines covering all endpoints, request/response shapes, design
decisions, and the development history).

### What the backend is, and isn't

- **What it is**: a thin async wrapper around `run.py`. It spawns the
  analyzer as a subprocess (`_spawn_run_py`), tails its stdout+stderr
  to per-job log files, parses `[N/M] === Phase X: ... ===` markers
  for progress, and exposes the model artifacts that the analyzer
  already produces (functions, components, flowcharts, the exported
  DOCX).
- **What it isn't**: a re-implementation of the pipeline. The backend
  never imports analyzer internals — it only reads JSON the analyzer
  writes and shells out to `python run.py`. The pipeline contract
  documented in §3, §10–§14 is the single source of truth.

### Process model

- FastAPI on `:8000`, CORS pinned to `http://localhost:5173` (the Vite
  dev server the UI runs on).
- Jobs live in an in-memory `_jobs: dict[str, JobState]` — **no
  persistence by design**. Restarting the backend forgets in-flight
  jobs, but already-exported DOCX files on disk remain downloadable
  via `GET /jobs/{jobId}/download` (the endpoint resolves by reading
  `output/*.docx` directly).
- Each spawned subprocess writes to
  `logs/job_<job_id>.out.log` (interleaved stdout+stderr). The
  `GET /jobs/{jobId}/preplogs` endpoint tails this file rather than
  buffering in process memory.
- Process tree kill uses `taskkill /F /T` on Windows and `killpg(SIGKILL)`
  on POSIX so cancelling a job actually stops the whole subprocess tree
  (parser/model_deriver/run_views/docx_exporter can spawn children).

### Progress: canonical 4-phase mapping

The pipeline has variable plan counts (build-only vs build+views vs
views-only, multi-group runs) and inside-plan phase counts (some plans
have 2 phases, others 4). To give the UI a stable progress bar:

- A **canonical 4-phase** taxonomy is exposed regardless of the
  actual plan shape: Parse C++ source → Derive model → Generate
  views → Export to DOCX.
- `_PHASE_NAME_TO_NUMBER` maps phase labels (case-folded) to
  `phaseNumber` 1..4.
- `_CANONICAL_TOTAL = 4` is always returned as `totalPhase` (even when
  the actual plan has only 2 phases — `totalPhase` is canonical, not
  literal).
- `_expected_phase_markers(selected_group, from_phase)` predicts the
  total number of `=== Phase ... ===` markers the run will emit, used
  to compute `overallProgress` monotonically. This was the fix for the
  "75% → 25% → 100%" regression: previously `overallProgress` was
  computed from "markers seen / markers in current plan", which jumped
  backwards across plan boundaries.
- The `phase` field strips a leading `Phase N: ` prefix
  (`_PHASE_LABEL_PREFIX_RE`) — the UI wants the bare phase name.

### Config editing: surgical JSONC splice

`POST /api/v1/config` updates only the `modulesGroups` key inside
`config/config.json` while preserving every comment and every other
key in the file. The implementation (`_find_modules_groups_key_pos`)
is a small JSONC-aware state machine that tracks strings, line
comments, block comments, and brace nesting depth — a regex or a
`json.loads` + `json.dumps` round-trip would either miss commented
duplicates or strip every `//` and `/* */` comment from the file.
Earlier attempts to do this with `json.loads` deleted ~80% of the
config; the surgical splice is the only safe path. Backup files are
**not** written (the user explicitly opted out — git is the backup).

> **Schema note (version4):** on this `main`-based code line the config key
> is **`layers`** (two-level), not `modulesGroups`, and the model file is
> `model/components.json`, not `modules.json`. The splice target and the
> component/module-keyed read paths must be updated when the backend is
> adapted (see the Integration status note above).

### Multi-repository CRUD

`backend/repository_config.json` is a list of `{name, path}` entries
(see `backend/models.py:Repository`). Endpoints that previously took
just a path now accept `?name=<repo>` query parameters; the backend
resolves the name to a directory via `_resolve_repository_path` and
auto-migrates legacy single-repo `{path: "..."}` files to
`[{name: "default", path: "..."}]` on first read.

### Where to read more

The full endpoint catalog (17 endpoints), request/response examples,
and the lessons-learned section (12 entries: venv mismatches, the
config splice 80% bug, progress monotonicity, hiddenFns evolution,
PNG slicing, ELK feedbackEdges, lossy-rewrite reversal, Windows
shell=True quirks, etc.) is in
[backend/PROJECT_CONTEXT.md](backend/PROJECT_CONTEXT.md). API examples
with curl payloads are in [backend/API_DOC.md](backend/API_DOC.md). A
sample response fixture lives at
[backend/fixtures/get_components_FTL.json](backend/fixtures/get_components_FTL.json).

---

## 22. Production Redesign (POC → Production) — design decisions

> This section captures the forward-looking **production platform** design work done in the
> 2026-06 design sessions. Everything in §1–§21 is the **POC**; this is the plan to productionize it.
> **Full detail lives in three design docs under `docs/production-redesign/` (brought onto `version4`).
> Read those for depth — this section is the orientation + the decisions, so a fresh session can
> pick up without re-deriving them.** Where this section references analyzer specifics it uses this
> code line's `layers`/`component` terminology (§4d).

### 22.1 Design documents (read these for full detail)

- **`docs/production-redesign/01-technology-selection-study.md`** (v1.2) — overall production stack + deployment.
- **`docs/production-redesign/02-database-design-study.md`** — DB selection (PostgreSQL), POC-grounded, with storage estimation.
- **`docs/production-redesign/03-incremental-changes-design.md`** (**v1.2** — §12 records the chosen path: **Approach 2**, git-diff narrowed parse) — the incremental / delta regeneration feature.

### 22.2 The vision

A **multi-tenant, on-premise production platform**: users register a C++ project (a path or, going
forward, a **git/Bitbucket URL → clone**), the platform runs the analyzer and produces the ASPICE
SWE.3 document, browsable/downloadable in a UI. Must be **scalable, reliable, durable, consistent**.

### 22.3 Hard constraints (these drive every decision)

- **On-prem only** — C++ firmware IP must not leave the corporate network → **no cloud services**.
- **Open-source only (OSI-approved)** → rules out *source-available* licenses: **SSPL** (MongoDB),
  **CSL** (CockroachDB, since 2024), **BSL** (ArangoDB/Memgraph), and **MinIO/Redis** post-relicense.
- **Firmware-scale** — up to ~50k functions/project (~20k typical), ~40 tenants/project
  (tenants **share** the codebase, so they do *not* multiply data), 10+ branches/project.
- **Rewrite the analyzer to read/write the DB directly** (no more `model/`+`output/` JSON files) —
  this also removes the local-disk phase handoff, which is what enables **distributed workers**.

### 22.4 Selected stack (key decisions)

- **Database: PostgreSQL 16+** (single-primary + HA via **CloudNativePG/CNPG**) with **pgvector**.
  The **system of record** (replaces the JSON files).
  - *Why Postgres:* one engine covers **relational + JSONB (document) + recursive CTEs
    (graph/impact analysis) + pgvector (similarity)**; ACID; OSI open-source; on-prem; won't rug-pull;
    modest structured scale **fits one node**.
  - **NOT a distributed DB** (Citus/Cockroach/Yugabyte) — structured data fits one node; we scale the
    **stateless worker tier**, not the DB.
- **Job queue:** Postgres-as-queue (`SELECT … FOR UPDATE SKIP LOCKED`) — **not** RabbitMQ/Kafka/Redis
  (extra stateful system for throughput we don't need; long, few jobs).
- **Graph / impact analysis:** Postgres **recursive CTE / materialized closure table** (not a graph DB;
  **Apache AGE** is the in-Postgres graduation path, then NebulaGraph).
- **Object storage: DEFERRED to a future phase.** History worth knowing: chose MinIO → discovered
  **MinIO Community Edition was archived ("no longer maintained") in Feb 2026** → switched to
  **SeaweedFS** (Apache-2.0) → then **deferred object storage entirely for now**. v1: keep **latest
  document per branch** in the DB; **flowchart images generated on demand, not stored**; **Mermaid
  scripts kept in the DB** (text).
- **Deployment:** containers on **Kubernetes**, **3-node cluster** (quorum = 2, survives **1** node
  failure; 5 nodes survive 2). **Stateless tier** (API + workers) vs **stateful quorum-bound data
  core** (Postgres + etcd [+ object store later]). **Local SSD (NVMe-ready)** via TopoLVM/OpenEBS
  LocalPV; redundancy = **app-level replication** (CNPG), not a storage layer. No existing
  CSI/distributed storage. Worker VMs are **not** quorum members → scale them freely.
- **LLM:** internal **corporate gateway** (OpenAI-compatible, off-cluster) → **no GPU nodes** in-cluster.
- **Auth:** **in-app auth + RBAC on PostgreSQL** (simple roles now); **Keycloak + corporate SSO** is the
  graduation path. Tenant isolation via `tenant_id` + optional Postgres **Row-Level Security (RLS)**.

### 22.5 Rejected DB options (for the record)

- **MongoDB** — SSPL (not OSI); weak graph/relational; on-prem vector is Atlas-only.
- **CockroachDB** — CSL (not OSI since 2024); distributed-scale we don't need.
- **Citus / YugabyteDB** — solve a write-scale problem we don't have; AGPL (Citus); less-mature pgvector.
- **MySQL / MariaDB** — weaker JSONB; immature vector ecosystem vs pgvector.
- **SQLite** — single-writer; no multi-tenant concurrency.
- **Neo4j / dedicated graph DB** — GPLv3 Community has no open-source clustering; our graph need is
  bounded transitive closure that Postgres handles.
- **Qdrant / Milvus as the primary store** — augment, not replace; pgvector covers current scale
  (kept as a graduation path).

### 22.6 Incremental (delta) regeneration feature — design summary

Goal: **hours → minutes** for small changes (skip the rate-limited LLM work for unchanged functions).
"Incremental build for documents" (the make/ccache/Bazel principle).

- **Change detection — two layers:**
  - **`git diff --name-only`** for *which files* changed (fast, reliable — **not** its scattered hunk
    output).
  - **Entity hashing** for *which entities* changed: hash **four entity types — functions, globals,
    macros, types**. **Token-based** (libclang; ignores whitespace/indentation/CRLF, **includes
    comments**), **full SHA-256** (32 bytes, never truncated), one **uniform** hash per entity's source
    extent, **keyed by identity including the defining file/location** (so same-named macros/types in
    different files are distinct).
  - **One hash per entity** now; **per-artifact hashing is deferred**.
  - Classification: unchanged / changed / new / deleted; **move/rename = delete(old key) + add(new key)**.
  - *Why hash globals/macros/types separately:* changing a global/macro/type does **not** change a
    *using* function's tokens (a function still just writes `MAX` after `#define MAX` changes value), so
    those entities must be hashed on their own; impact analysis then refreshes the functions that use them.
- **Impact analysis (dependency-graph propagation):** changes flow **UP to callers/users**. Axes:
  **call graph (transitive callers), type usage, globals, macros, containment (file/component/project
  summaries), diagrams (call-edge changes), cross-group**. Hard cases: **indirect calls / virtual
  dispatch → over-approximate** (treat as edges to all overrides / any address-taken function);
  **move/rename → key change**. Algorithm: reverse-reachability BFS / recursive CTE / closure table over
  the stored edges.
- **Selective regeneration:** re-run the LLM only for the impact set; **reuse** stored outputs for the
  rest. **Reassemble** the document from pieces (re-run Phase 3 views + Phase 4 export; **not** in-place
  patching).
- **Chosen approach & baseline (updated — see `docs/production-redesign/03` §12, v1.2):** v1 uses
  **Approach 2** — **git-diff narrowed parse** (parse only changed files; reuse the baseline version's
  stored model + outputs for the rest) + **stored-graph impact** + **selective regen**. The product model
  is **a document version per code version, branch-agnostic** — each generation stores its own document +
  metadata; reuse is **content-addressed across all generated versions**. The diff baseline is the
  **nearest generated ancestor** (via `git merge-base`), with **Approach 1's full parse as the fallback**
  for first-generation / no-ancestor / diverged history.
- **Versioning:** a document version per generation; **full Git-style cross-version dedup is deferred**.
- **Tech additions (no new DB or system):** the **`git` CLI** in the worker image + **repo credentials**
  (SSH deploy key or HTTP access token, from a deployment-appropriate secrets store — K8s Secrets / Vault
  / env injection; the project owner supplies it at registration, stored encrypted). Operator-side recipe
  changes (LLM model/prompts/config) → a manual full-regen, separate from the user's code-diff path.

### 22.7 Storage estimation (DB structured data only; excludes images/docs)

- **~250 MB / branch** (20k functions + 3k entities), dominated by **embeddings (~120 MB) + Mermaid
  (~60 MB)**.
- **~2.5 GB / project** (×10 branches; v1 stores per-branch, no cross-branch dedup).
- Platform: ~25 GB (10 projects) → **~500 GB logical / ~1.5 TB physical at 200 projects** → a
  **single primary + replicas** comfortably suffices.
- Cross-branch dedup (deferred) would shrink ~2.5 GB → **~0.5 GB + small deltas**.

### 22.8 Explicitly deferred to later phases

- **Object storage** (images, documents at scale).
- **Per-artifact hashing** (finer-grained reuse — e.g. a comment-only change reusing the flowchart).
- **Image-render cache** (skip re-rendering unchanged flowcharts — tied to object storage).
- **Full version history** (Git-style dedup across versions/branches).
- **Non-Functional Requirements section** for the DB study.

### 22.9 What's next

- **Incremental implementation (in progress on `version4`)** — Approach 2 over the current JSON-file
  pipeline first, to migrate to Postgres later. Workstreams: git ingestion + project onboarding, per-project /
  per-version storage, entity hashing + dependency-edge persistence, the detect→impact→regenerate→reassemble
  engine wired into Phases 1–4, and the supporting APIs (onboard / projects / branches / commits / generate).
- **Detailed database schema design** — tables for entities, dependency edges, `{key → hash}` records,
  per-version baselines, RBAC, and the job queue (owned by the DB engineer).
- (Optional) the NFR section for the DB study; the object-storage study (future phase).

### 22.10 Cross-cutting lessons from this session

- **MinIO Community Edition is dead** (archived Feb 2026); **SeaweedFS** (Apache-2.0) is the maintained
  alternative *if/when* object storage is needed.
- **Watch licensing rug-pulls:** SSPL / CSL / BSL / RSAL are *source-available, not OSI*. PostgreSQL
  (PostgreSQL License) is the low-risk anchor; **Valkey** is the OSI-clean Redis fork.
- **Hashing for change detection** must be **token-based** (to ignore formatting/CRLF) and **full
  SHA-256** (collisions effectively impossible). A *token change is always a line change*, so git diff
  never *under*-detects — it only over-detects on formatting, which is the safe direction.
- **The whole incremental design biases to over-regenerate, never to stale** — every ambiguous case
  (indirect/virtual calls, formatting noise, non-ancestor commits) regenerates *more*, with a manual
  full-regen escape hatch.

---

## 23. version4 — Incremental Changes feature (this session, 2026-06-18)

> `version4` is the **active working branch**. This section is the orientation + **decisions + status**
> for the **incremental document regeneration** feature. Authoritative design lives in
> **[docs/production-redesign/04-incremental-changes-implementation.md](docs/production-redesign/04-incremental-changes-implementation.md)**
> (approach, v2.1) and **[docs/production-redesign/05-incremental-api-spec.md](docs/production-redesign/05-incremental-api-spec.md)**
> (UI HTTP API). Read those for depth; this is the map.

### 23.1 What `version4` is
- Created off `origin/main` (`f3946bd`). `main` is the live code line: **`layers`/`component` schema** (§4d —
  `modulesGroups`→`layers`, `module`→`component`, `modules.json`→`components.json`), plus
  `--data-dictionary`/`--macros`/`--include-path`/`--selected-layer`/`--selected-component` CLI, a Streamlit
  `ui/`, and the `SampleCppProject` fixture.
- Brought over from `version3`: `backend/` and `docs/production-redesign/01..03`. This `PROJECT_CONTEXT.md`
  = main's §1–§20 + §21 (backend) + §22 (production redesign) + this §23.

### 23.2 Done this session
1. **Backend adapted to layers/component** ([backend/main.py](backend/main.py), [backend/models.py](backend/models.py)):
   config source `modulesGroups`→`get_flat_groups(layers)`; component-keyed `fn_id`s + `functions_<group>.json`
   naming (`safe_filename` spaces→`-`); `_resolve_group_name` vs group names; `POST /config` splice generalized
   to the `layers` key; `UpdateConfigRequest.layers`. Verified (25 routes import + functional probe).
2. **Backend docs corrected** to layers/component ([backend/API_DOC.md](backend/API_DOC.md),
   [backend/PROJECT_CONTEXT.md](backend/PROJECT_CONTEXT.md)); `backend/repository_config.json` → `SampleCppProject`.
3. **`backend/git_service.py`** (M0 #1 — **DONE**): `clone_repo` (HTTPS user/token; token reset out of
   `.git/config`, never logged), `fetch`, `checkout`, `current_commit`, `list_branches`, `list_commits`, and the
   baseline primitives `is_ancestor` / `nearest_ancestor` / `merge_base` / `changed_files`. `shell=False`
   deliberately (credential/URL safety). Verified against the repo + a local clone.
4. **Design docs**: `04` (incremental approach, **v2.1**), `05` (UI API spec).

### 23.3 Incremental — key decisions (do NOT re-derive these)
- **Approach 2** (doc 03 §12): git-diff **narrowed parse** + stored-graph impact + selective regen; **full
  parse is the fallback** (first version / no ancestor / `mode:"full"`).
- **Version = one generation run** (`versionId`); records branch/commit/scope/dataDictId/baselineVersionId/
  counts. **All versions kept.** Same commit generated twice (different scope/data-dict) = two versions.
- **Baseline = auto nearest-ancestor** (`git merge-base --is-ancestor` over prior versions' commits; nearest by
  `rev-list --count`); **optional user override** (`baseVersionId`) with ancestor/nearest **warnings**; none →
  full gen. **Correctness is base-independent** — the base only affects *parse speed* (reuse is content-addressed).
- **`edges.json` is SLIM** — only **type/macro usage**. Calls/globals come from `functions.json`
  (`calledByIds`/`callsIds`, `reads`/`writesGlobalIds`); the **recursive/transitive closure is computed by
  reverse-BFS**, not stored. (Don't re-store the call graph — it already exists in `functions.json`.)
- **Reuse = `cache/index.json`**, a `{fingerprint → (versionId, entityKey)}` **POINTER index** — **NOT** a
  duplicate blob store. Output content lives **once** in each version's `model/output`; reuse = look up the
  fingerprint → copy from the pointed-to version. Plus **carry-forward** from the baseline version.
- **`fingerprint`** = `sha256(source_hash + sorted(dependency source-hashes) + recipeFingerprint)`;
  `recipeFingerprint` = LLM model + prompt version + cacheVersion (gives operator-change invalidation).
- **Data dictionary** is per-version, replaceable; **uploaded by onboarding's separate API**; `generate` only
  references a `dataDictId`. A data-dict-only change → cheap reassembly (interface-table ranges), **no LLM**.
- **Onboarding is OUT of scope** (other engineer): registration, git credentials, the initial clone, the
  project's `layers`, the data-dict upload. Incremental **consumes** `projectId` + `repo/` + `layers` +
  data dict + `branch`+`commit`.
- **version-id assignment**: sequential per project (`v1, v2, …`), assigned at generation start. **Collision-
  free** because generations are **serialized per project** (single shared clone → one `git checkout` at a
  time; a 2nd concurrent `generate` → `409`). Global key = `(projectId, versionId)`. `projectId` uniqueness is
  onboarding's responsibility.
- **Engine flow** (doc 04 §5 — validated 8 steps): copy baseline → new version; `git diff` changed files;
  partial-parse + merge; classify changed/new/deleted; **impact BFS** (all axes; over-approx virtual/fn-ptr;
  move/rename); selective regen (index-check before LLM); reassemble (Phase 3 + 4); record version.
  **Impact analysis is the #1 correctness trap** — must regenerate dependents that live in *unchanged* files,
  else the document goes stale.
- **Regenerated dependents are cached too** (doc 04 §5 steps 6+8): every entity in
  `{changed ∪ new ∪ impacted}` that is LLM-regenerated gets a **new `cache/index.json` pointer entry** (→ the
  new version), so a future version / revert / cross-branch-identical run reuses it. Because the fingerprint
  includes `sorted(dependency source-hashes)`, an impacted dependent correctly **misses** on this version
  (its dep changed) and **hits** later when that dep state recurs. *Carried-forward* (unchanged & unimpacted)
  entities get **no** new entry — their fingerprint already points at the version that first produced them.
- **Storage interface (D9 — doc 04 §3):** all incremental-store access goes through a thin interface
  (`src/incremental/stores.py`: `VersionStore`, `ReuseIndex`, `HashStore`, `EdgeStore`) — **JSON-file impl now,
  Postgres impl later behind the same methods**. The §5 engine + the APIs call *only* the interface (no
  scattered `open()`/`json.load`), so the §10 Postgres swap is one implementation, not a refactor. **Scope =
  the incremental *metadata* stores only** (versions/hashes/edges/reuse-index/jobs); the analyzer's per-version
  `model/`+`output/` stay file-based until the DB-native pipeline rewrite (§22.3). Git auth is **D8** (POC
  plaintext: token injected into the URL then `origin` reset credential-free; `backend/git_service.py`).

### 23.4 Storage (per project) — examples in doc 04 §4
```
workspaces/<projectId>/
  project.json                 [onboarding]  name, layers, repo ref, current dataDictId
  repo/                        [onboarding]  single clone; incremental does `checkout <commit>`
  datadict/<dataDictId>.csv    [onboarding / separate API]
  cache/index.json             [INCREMENTAL]  {fingerprint -> {versionId, entityKey}}  (pointer index)
  versions/index.json          [INCREMENTAL]
  versions/<versionId>/        manifest.json, hashes.json (full entity->source-hash snapshot),
                               edges.json (SLIM: type/macro only), config.json, model/ output/ documents/
```

### 23.5 Implementation plan + status
- **P0 `git_service` — ✅ done.**
- **P1 onboarding stub fixture — ✅ done.** [backend/seed_workspace.py](backend/seed_workspace.py) seeds
  `workspaces/<projectId>/` with the **onboarding-owned** parts only (doc 04 §4): `project.json` (name, the
  project's `layers`, repo ref, `currentDataDictId`), `repo/` (a real **full** clone via
  `git_service.clone_repo`, public/no-creds), and `datadict/dd-001.csv` (seeded from
  `config/data_dictionary.csv`). Leaves `cache/`+`versions/` to the incremental engine. Default fixture =
  `projectId=samplecpp`, repo `github.com/vishal9359/SampleCppProject` (branches `main` + `feature1/2/3`,
  topology purpose-built for nearest/far/divergent-ancestor tests — see the repo's `README.md`). `workspaces/`
  is gitignored (data); the seed script is tracked. Re-seed with `python backend/seed_workspace.py --force`.
- **M1 — version-producing FULL gen + substrate** — *in progress.*
  - **M1.1 `--config`/`ANALYZER_CONFIG` — ✅ done.** `run.py --config <path>` resolves+validates the path and
    exports `ANALYZER_CONFIG` **before** importing `utils` (which loads config at import time), so this process
    and every phase subprocess (env inherited) honor it. `core/config.py load_config()` reads `ANALYZER_CONFIG`
    first: if set it loads that file **as-is** (JSONC) — **no `config.local.json` merge**, for reproducibility —
    and **fails loud** (`FileNotFoundError`) on a set-but-missing path; unset → existing `config.json`+local
    behavior. Tests: `tests/unit/test_core_config.py::TestLoadConfigAnalyzerConfigOverride` (5).
  - **M1.2a entity hashing — ✅ done.** New `src/incremental/hashing.py` (token-based full SHA-256;
    formatting-insensitive, comment-inclusive — folds in the preceding doc comment; visibility macros expand
    away and are intentionally excluded since the hash governs *output reuse*, and visibility is caught by the
    changed-file re-parse). `parser.py` stores `_sourceHash` on function/global entries (internal — does **not**
    leak into `functions.json`) and writes `model/hashes.json` `{entityKey→token-sha256}` for all four kinds:
    functions (model key), globals (model key), types (qn), macros (`name@relFile`, line-stable). `model_io`
    gains `HASHES`/`EDGES` (not in `ALL_MODEL_NAMES`). Verified on `SampleCppProject`: 353 entities, all 64-hex,
    **deterministic** across re-parse, and a one-function edit changed **exactly 1** hash while a whitespace-only
    reformat of a sibling changed **none**. Tests: `tests/unit/test_incremental_hashing.py` (12).
  - **M1.2b slim usage index — ✅ done.** `parser.py` adds a `visit_usage` pass (3rd walk on the same TU, no
    extra parse) that threads the enclosing function like `visit_calls`: **type usage** via AST
    (`_project_type_qn` resolves return/param/`TYPE_REF`/`VAR_DECL` types through pointer/ref/array layers to a
    project type's qn) and **macro usage** via per-function identifier-token capture. New pure
    `src/incremental/edges.py::build_edges` (no libclang — unit-tested) inverts to
    `model/edges.json` `{typeUsers, macroUsers}` keyed by model fid, **filtered to types/macros that have a hash**
    so every key cross-references `hashes.json`; keys+values sorted for byte-stable output. Macro keys
    `name@relFile`, type keys qn — identical to `hashes.json`. Calls/globals are deliberately **not** here
    (functions.json has them). Verified on `SampleCppProject`: 14 types / 1 macro used, **0** key/fid mismatches
    vs `hashes.json`, `Point`/`Status`/`Mode` resolve to the right functions, deterministic. Tests:
    `tests/unit/test_incremental_edges.py` (8). *Known limits (M2/M3): typedef→underlying transitive type edges
    and synthetic-from-VAR_DECL functions are not tracked; macro detection over-approximates (token-name match).*
  - **M1.3a substrate — ✅ done.** **D9 store interface** `src/incremental/stores.py`
    (`Workspace`/`VersionStore`/`HashStore`/`EdgeStore`/`ReuseIndex`, JSON-file impl, atomic writes) +
    **fingerprints** `src/incremental/fingerprint.py` (`recipe_fingerprint`,
    `compute_fingerprints` = `sha256(source_hash + sorted(dep source_hashes) + recipeFingerprint)` over
    functions+globals; deps = callees/globals from functions.json + types/macros forward-inverted from edges) +
    the **version-producing full-gen orchestrator** `src/incremental/generate.py` (CLI:
    `python src/incremental/generate.py --project-id … --branch … --commit … --scope group:G --no-llm`): checkout
    → resolved config (global + project layers) → run `run.py --config` → capture `model/output/documents` +
    `hashes.json`/`edges.json` into `versions/<vN>/` → seed `cache/index.json` → write manifest + index. Verified
    e2e on `samplecpp` (scope group:Support, LLM off): `versions/v2` complete, 127 entities fingerprinted, docx
    captured, reuse index seeded; failed attempts recorded (status=failed) and still consume a versionId. Tests:
    `tests/unit/test_incremental_stores.py` (13) + `test_incremental_fingerprint.py` (7).
  - **M1.3b backend HTTP — ✅ done.** [backend/main.py](backend/main.py) gains `POST /api/v1/projects/{id}/generate`
    (FULL path only — spawns `src/incremental/generate.py` as a job via `_spawn_generate`; pre-allocates the
    versionId, serializes per project with **409**, returns `{versionId, jobId, decision:"full", …}`),
    `GET …/versions`, `GET …/versions/{id}` (+ per-doc `downloadUrl`), `…/versions/{id}/download`
    (`.docx`, or `.zip` for multi-doc). generate.py: `--version-id` (pre-allocatable) + early **running** manifest
    (so the version is queryable immediately) + analyzer stdout/stderr **inherited** (so run.py phase markers land
    in the per-job log → existing `/jobs/{id}/status` tracks progress). Verified via TestClient on `samplecpp`:
    versions list/detail/download (real 47 KB docx) + validation (404/400/409). *POST happy-path not exercised
    live (TestClient blocks on the watcher; orchestrator is e2e-tested via the identical CLI path) — test live on a
    running server. `mode:"auto"`/baseline (incremental) is M2.*
- **M2 — incremental engine — ✅ done** (M2.1–M2.4 below; incremental generation works e2e + via the API).
  - **M2.1 baseline selection + preview — ✅ done.** `src/incremental/git_ops.py` (engine-local git wrapper —
    checkout/current_commit/is_ancestor/merge_base/rev_list_count/changed_files/nearest_ancestor; decoupled from
    `backend/git_service.py`, consolidation deferred to M3) + `src/incremental/baseline.py::select_baseline`
    (auto nearest-ancestor among *complete* versions → none = full; optional `baseVersionId` override with
    **divergent** [not-ancestor] / **not-nearest** warnings; base only narrows the parse, never staleness) +
    backend `GET …/generate/preview?commit=&baseVersionId=` (read-only, no checkout). `generate.py` now uses
    `git_ops`. Verified: tmp-repo unit tests (`test_incremental_git_ops.py` 12 + `test_incremental_baseline.py` 11)
    + TestClient preview on `samplecpp` (main→incremental/v2/nearest/0-changed, feature1→full, override-v2→divergent
    +warning, unknown→404).
  - **M2.2 classify + impact BFS — ✅ done.** `src/incremental/impact.py` (pure): `classify(baseline_hashes,
    target_hashes)` → {changed/new/deleted/unchanged}; `impact_set(changed_keys, functions, edges,
    extra_seed_functions=)` → set of function fids to regenerate = changed/new functions + **everything
    transitively depending on any changed entity** (reverse-BFS: callers via `calledByIds`, global users via
    inverted reads/writes, type/macro users via `edges.json`; visited-set handles cycles; `extra_seed_functions`
    injects deleted entities' baseline callers). The #1 staleness trap — covered. Tests:
    `tests/unit/test_incremental_impact.py` (12).
  - **PARSE-STRATEGY DECISION (D10):** the M2 engine uses a **FULL parse** of the checked-out commit (correct
    call graph by construction), and the incremental win comes from **selective LLM regeneration** (classify →
    impact BFS → reuse). **Narrowed/partial parse (doc 03 D2 "Approach 2") is DEFERRED** to a later optimization
    (doc 04 §10's parse cache): correct narrowed parse needs cross-file call/reverse-edge reconciliation that is
    complex and easy to get subtly wrong → staleness, whereas the *primary* benefit (skip the rate-limited LLM for
    unchanged+unimpacted entities = hours→minutes) is parse-strategy-independent and a full parse is **never
    stale** (D7). Parse time becomes the bottleneck to optimize only after LLM time is removed.
  - **M2.3 incremental engine — ✅ done.** `src/incremental/engine.py::generate_incremental`: baseline-pick →
    checkout → full parse (`run.py`) → `plan_incremental` (classify vs baseline `hashes.json` + impact BFS +
    deleted-caller seeding) → **carry forward** baseline outputs (description/behaviour names) for the reuse set
    (`carry_forward_descriptions`) → reassemble (`run.py --from-phase 4 --use-model`) → capture version + seed
    reuse index + manifest (decision/regenerated/reused/baselineVersionId/carriedForward). Falls back to
    `generate_full` when no baseline. Pure helpers `plan_incremental`/`carry_forward_descriptions` unit-tested
    (`test_incremental_engine.py` 8). **Verified e2e on `samplecpp`**: baseline v1@C3 (125 entities) → incremental
    v2@main-HEAD = decision=incremental, baseline=v1, **3 new** (multiply/clampPositive/coreReset) + impact **6**
    (incl. a deleted function's transitive callers App::main/calculate via MultiplyOperation::apply), **109
    reused/carried-forward**, 14.4s vs 31.7s full. (The `Cross::Dispatch::multiply` "deleted" is a pre-existing
    parser name-resolution fuzziness → safe over-regeneration, never stale.) *Descriptions reuse via the version3
    EntityCache on LLM-on runs; flowchart-level reuse (restrict the engine to the impact set) is M2.4.*
  - **M2.4a mode:auto dispatch — ✅ done.** `POST /api/v1/projects/{id}/generate` now resolves the target +
    runs `select_baseline` and **dispatches**: `mode:"auto"` (default) → incremental (spawn `engine.py`) when a
    baseline ancestor exists, else full (`generate.py`); `mode:"full"` forces full. Response carries the real
    `decision` + `baselineVersionId`/`baselineCommit` + `warnings`; `baseVersionId` override forwarded. `commit not
    in repo` → 409. Verified via TestClient (auto@main→incremental/engine.py/baseline=v2, full→generate.py,
    auto@feature1[no ancestor]→full, 400/409).
  - **M2.4b flowchart-level reuse — ✅ done (file-level).** `views/flowcharts.py::_apply_incremental_plan`
    (gated on `model/incremental_plan.json`; absent → unchanged full behaviour) **carries forward** the baseline
    version's `output/<scope>/flowcharts/*.json` then **restricts** the flowchart engine's functions file to the
    impacted source files (engine overwrites only those). `engine.py` computes `impactedFiles` BEFORE the run
    from the **baseline model + `git diff`** (over-approx, safe — no Phase-split) and writes/cleans the plan.
    The `src/flowchart/` engine is unchanged. Verified e2e on `samplecpp` (carried 3 / restricted 16 in 9 files;
    output complete, plan not leaked into the version). *(Superseded by M3.1: the impacted-file seeding is now
    precise/function-level, not file+git-diff.)*
- **M3 — hardening** — *in progress.*
  - **M3.1 precise function-level flowchart reuse — ✅ done.** Added **`run.py --to-phase N`** (stop after a phase;
    additive filter over `plan_runs`' output by script→phase, gated — `None` = unchanged). `generate_incremental`
    now **Phase-splits**: `--to-phase 2` (parse+derive) → compute the **precise** impact from the fresh target
    model (`plan_incremental`) → carry forward descriptions + write the impacted-files plan → `--from-phase 3
    --use-model` (views+export; flowcharts restricted to impacted files, rest carried). One impact computation
    drives both description + flowchart reuse. Verified e2e on `samplecpp`: impacted files 9→**4**, restricted
    16→**14** (exactly the 6 impacted functions' source files); v2 complete, output correct, no plan leak.
  - **M3.2 hierarchy-summary reuse — ✅ done (the real payoff fix).** Diagnosis: descriptions/behaviourNames are
    **off by default**, so M2.3's description carry-forward was a no-op; the dominant default LLM costs are
    **flowchart labeling** (fixed by M3.1) and **hierarchy summarization** (Phase 2) — and the `PkbCache` keys on
    the *whole* `functions.json` hash, so any change re-summarized **everything** (this is why an 8-line diff took
    full time). Fix: the engine now Phase-splits at **Phase 1** (`--to-phase 1` → impact → carry forward baseline
    `description`+`phases` for the reuse set → `--from-phase 2`). The summarizer only summarizes functions with no
    `description` (`project_scanner._summarize_functions`), so carrying it forward makes it **skip the reuse set**
    — function-level summarization (the big cost) is restricted to the impact set with **no `model_deriver`/
    summarizer change**. Verified e2e (C1→C3, scope Support): regenerated 9 / reused 104, flowcharts restricted to
    5 files, output correct. *File/module/project summaries still re-run (~minor, not function-gated) — a later
    refinement.*
  - **M3.3 full Phase-2 enrichment reuse + 4 fixes — ✅ done.** An LLM-on test (744s for an 8-line diff) exposed
    that M3.2 only covered function summaries, while the user's config has `descriptions:True`+`behaviourNames:True`
    and the dominant cost was **behaviour-names (417s) re-run for all 113 functions**, plus globals (46s),
    file/component summaries (117s), and PNG re-render (92s) — none reused; and the captured `documents` list had
    **stale/duplicate docx** from prior runs. Fixes:
    (1) **documents** — `engine`/`generate` clean `output/` before each run so a version captures only its own docs.
    (2) **`model_deriver` incremental mode** — reads `incremental_plan.json` (`impactFids`/`impactedGlobals`) and
    restricts behaviour-names + descriptions + global enrichment to the impact set (the engine carries forward the
    reuse set's `description`/behaviour-names/`phases` into `functions.json` and global descriptions into
    `globalVariables.json` before Phase 2). (3) **file/component summary gating** — `_run_hierarchy_summarizer`
    pre-populates `knowledge.file_summaries`/`component_summaries` from the baseline for unchanged files/components,
    and `project_scanner._summarize_files`/`_summarize_components` skip those already present. (4) **flowchart PNG
    reuse** — `views/flowcharts.py` carries forward baseline PNGs and re-renders only impacted units. Verified e2e
    (LLM-off flow): "enriching 9 functions + 3 globals; reusing the rest", documents=[just the scope's doc], PNGs
    carried. `tests/unit/test_incremental_engine.py` +2 (carry_forward_globals).
  - **M3.4 end-of-run report — ✅ done.** `src/incremental/report.py` (`build_report` pure + `emit_report`): both
    `generate_incremental` and `generate_full` print a summary at the end — **logged** (to `logs/run_<date>.log` via
    `get_logger`) **and saved** to `versions/<id>/report.txt`. Sections: inputs (project/branch/commit/scope/
    **baseline + changed-file count**/dataDict/LLM recipe/status/**wall-clock**), **change classification** (changed/
    new/deleted/unchanged, broken down by kind), and **reuse accounting** (functions/globals/flowcharts:
    regenerated vs reused + %; summaries note). Tests: `tests/unit/test_incremental_report.py` (6). Example on
    C1→C3: `Functions regenerated 9/113 -> reused 104 (92%)`, `Globals 3/12 -> reused 9 (75%)`, `Flowcharts 5/18
    files -> carried 13 (72%)`.
  - **M3.5 flowchart impact-scoping fix — ✅ done (big speedup).** An LLM-on real-diff (C1→C3) took 1021s with the
    **flowchart engine alone = 497s**, even though only 3 functions changed. Cause: flowcharts were regenerated
    for the **full impact set** (changed + transitive callers), pulling in `App/Main.cpp`'s *large* functions
    because they call the changed `Math`. But **a function's flowchart is its own CFG + call-site labels — it does
    NOT change when a callee's *body* changes**. Fix: the plan now carries a separate **`flowchartFiles`** = files
    of only the *directly* changed/new/deleted functions (descriptions/summaries keep the full-impact
    `impactedFiles`, since those genuinely depend on callees, and are cheap); `views/flowcharts.py` restricts on
    `flowchartFiles`. (Also confirmed: the flowchart `PkbCache` caches the PKB *index* keyed by the whole
    functions.json hash — **not** LLM labels; there is no label cache — so unifying caches wouldn't help; reuse is
    handled by version-level carry-forward.) Verified e2e: C1→C3 flowcharts dropped from **12 functions / 5 files**
    to **3 functions / 1 file** (App no longer re-labeled); report shows `Flowcharts carried 15/18 (83%)`.
  - *Remaining:* **version-scoped reads** (`?versionId=` on `components`/`functions`/`flowcharts`); move/rename
    polish; consolidate `git_ops`/`git_service`; unit-diagram reuse. (Recipe-fingerprint invalidation is
    automatic; multi-doc zip shipped in M1.3b.)
- **Next concrete step:** **M3.2 — version-scoped reads**: `?versionId=` on the browse endpoints
  (`/components`, `/functions/{fn_id}`, `/flowcharts/{fn_id}`) so the UI reads a specific version's
  `model/`+`output/` (removes the single-shared-`model/` limitation; doc 05 §8). Then the remaining M3 items.
  (M3.1 done — precise flowchart reuse + `run.py --to-phase`.)
- **Testing convention:** `_probe_*.py` (run once, delete) + end-to-end on `SampleCppProject`; run **LLM off**
  to validate the logic (hashing / diff / impact / reuse counts), LLM on only for the time-savings payoff.

### 23.6 Analyzer changes M1/M2 will make
`run.py` (`--config`/`ANALYZER_CONFIG`, `--incremental`); `core/config.py` (honor `ANALYZER_CONFIG`);
`parser.py` (partial-parse; entity hashing; slim type/macro index); `model_deriver.py` (incremental mode;
extend `EntityCache`); `views/flowcharts.py` (restrict the engine's functions file to the impact set; the
`src/flowchart/` engine itself is unchanged); new `src/incremental/` — incl. `stores.py` (D9 interface:
`VersionStore`/`ReuseIndex`/`HashStore`/`EdgeStore`, JSON-file impl now, Postgres later) that all version /
hash / edge / reuse-index access goes through.

### 23.7 Key `version4` commits (this session)
`a2edee1` bring-over backend+docs · `3498153` PROJECT_CONTEXT merge · `1cf4eb5` backend→layers/component ·
`082ec8b` backend doc corrections · `a74a560` **git_service** · `4651fe9` + `d1ee2bd` + `98b2ce1` doc 04
(incremental approach → slim edges + pointer index) · `8ea45a2` doc 05 (UI API spec). Branch is pushed to
`origin/version4`.

---

## 24. Frontend — `frontend/designs/`

Branch: `feat/product-ui-redesign`. HTML design mockups in `frontend/designs/` are the reference specs for the React frontend implementation. Full UI context in `frontend/UI_CONTEXT.md`.

### Design system

- Tailwind CSS + Material Symbols Outlined (Google Fonts)
- Fonts: Inter (body/headlines), JetBrains Mono (labels/code)
- Color tokens: navy `#041627`, blue `#0058be`, green `#00a572`

### Page inventory

| # | File | Sidebar | Subbar | What it covers |
|---|------|---------|--------|----------------|
| 1 | `signin.html` | none | no | Two-panel auth: branding left, SSO + email/password form right |
| 2 | `projects.html` | 220px | yes | All-projects table; ADMIN/DEV badges, row kebab menu (Settings / Archive / Delete) |
| 3 | `projects-empty.html` | 220px | yes | Empty state + 5-step onboarding wizard; Request Project Access modal |
| 4 | `project-detail.html` | 220px | yes | Project overview: KPI cards, generation progress, documents table, team list, review queue, function-visibility slide-over, Run Analysis modal, Admin/Developer role switcher |
| 5 | `documents.html` | 56px collapsed | yes | Document list: process filter tabs, status/assignee filters, batch actions, edit-section modal, assign-reviewers slide panel |
| 6 | `compare.html` | 56px collapsed | yes | Split diff: reference left / current right; per-section Accept/Decline/Edit; review footer with progress dots |
| 7 | `versions.html` | 56px collapsed | yes | Tagged version cards (In Review / Approved); untagged commits timeline; filter tabs |
| 8 | `team.html` | 220px | yes | Team table: role dropdowns, pending invites, Invite Member modal, permission legend |

### Shell rules

**Sidebar** — context-progressive:
- `signin.html` and `projects.html` have **no sidebar** — full-width, logo top-left.
- All project-scoped pages (4–8): **project sidebar** (220px expanded / 56px collapsed):
  - `← All Projects` → `projects.html`
  - Project name label (10px uppercase)
  - Overview → `project-detail.html` · Documents → `documents.html` · Compare → `compare.html` · Versions → `versions.html` · Team → `team.html`
  - Settings at bottom (below `border-t`)
- `documents.html`, `compare.html`, `versions.html` default to **collapsed (56px)**.

**Subbar** (all project-scoped pages):
```
[ 📁 VCU Engine Firmware ▾ ]  ·  [ v1.2.0 ▾ ]  ·  ⑂ main @ d9a0c55  ·  Jun 15    [CTA]
```
- CTAs: project-detail `[▶ RUN ANALYSIS]`, documents `[↓ Download All]`, compare `[✓ Accept All] [✗ Reject All]`, team `[+ Invite]`, versions — none

**Breadcrumbs** — always start with `[⬡]` home (→ `projects.html`):
`Overview` · `Documents` · `Documents / Compare` · `Versions` · `Team`

### Navigation flow

```
signin.html → projects.html (no sidebar)
  └─ click row → project-detail.html (220px sidebar)
       ├─ Documents → documents.html (56px) → Compare → compare.html (56px)
       ├─ Versions  → versions.html (56px)
       └─ Team      → team.html (220px)
```

---

_End of file._
