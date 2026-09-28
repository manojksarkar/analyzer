# Architecture — what the analyzer is, its layout, the pipeline end to end

> **Project context — one part of it.** Start at [PROJECT_CONTEXT.md](../PROJECT_CONTEXT.md),
> the index: current state, how to read the context, every file. The sections below moved here
> from the single-file context on 2026-09-28, unchanged except link paths, and keep their numbers —
> "PROJECT_CONTEXT §N" still finds them. Some of it has drifted since: read the index's [What changed
> after the numbered sections](../PROJECT_CONTEXT.md#what-changed-after-the-numbered-sections) first.

**Sections:** [1. What this project does](#1-what-this-project-does) · [2. Top-level layout](#2-top-level-layout) · [3. The 4-phase pipeline](#3-the-4-phase-pipeline) · [15. Test fixture — `SampleCppProject/`](#15-test-fixture--samplecppproject) · [20. Dependencies](#20-dependencies) · [21. End-to-end code flow — single command, full pipeline](#21-end-to-end-code-flow--single-command-full-pipeline)

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
analyzer/                     (repo root — cwd of the pipeline; model/ output/ logs/ resolve here)
  engine/                    The analysis engine + CLI + its own config/assets
    run.py                    Entry point — argv parsing, plan + dispatch (SCRIPT_DIR = repo root, one up)
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
    behaviour_diagram/        Sequence/behaviour diagram generator package (SequenceDiagramGenerator)
    config/
      config.defaults.json    Base defaults (JSONC: // and /* */ comments allowed)
      config.local.json       Secrets (gitignored): db + llm creds; deep-merged over defaults
      config.local.json       Local overrides (gitignored)
      abbreviations.txt       Abbreviation expansions for LLM prompts
      data_dictionary.csv     Sample data-dictionary CSV (--data-dictionary <path>)
      config.defaults.json.example  ANNOTATED twin of config.defaults.json: same data,
                                          every key explained. Not loaded by anything;
                                          a test asserts the two parse to identical data.
      data_dictionary.core1.example.csv  Core1's sample (cores.Core1.dataDictionary)
      data_dictionary.core2.example.csv  Core2's — shares BufferSize_t at a different
                                          range (the per-scope case). Both now WIRED
                                          via the `cores` section.
      macros.csv              Sample macros CSV (--macros <path>)
      macros.core1.example.json   Core1's toolchain macro list, client schema (cu "fcore")
      macros.core2.example.json   Core2's list (cu "hil") — the two-file case
      compile_commands.core1.example.json  Core1's compilation database (24 entries),
                                          include paths pointing into SampleCppProject
      compile_commands.core2.example.json  Core2's (71 entries). Build-machine
                                          `directory` values, both separator styles,
                                          armclang flag soup. See §4g.
      puppeteer-config.json   Optional headless-chrome args for mmdc
    few_shot_examples/        Few-shot pools (descriptions / behaviour_names / globals)
    assets/                   DOCX cover assets (bottom_arc.png, copyright.png)
  api/                        FastAPI backend — kept at repo root, imports `api.*` (see §19/§21)
  web-app/                    React web client (Vite + TS + Tailwind; see §24)
  SampleCppProject/           Fixture C++ tree — Layer1 + Layer2/Platform (see §15)
  tools/                      Dev-only tooling — mock-api (mock backend), create-sample-project, import-output-project,
                              dump_docx.py (flatten a generated .docx to diffable text: headings/tables/`[image … sha=…]`),
                              doccheck/ (compare two .docx by CONTENT — extract→match→compare→report, SWE.3+SWE.4,
                              `--self` one document, `--pair` SWE.3-vs-SWE.4; see tools/doccheck/README.md)
  tests/  docs/
  model/                      Phase 1+2 output (JSON) — at repo root (cwd)
    clang_include_paths.json  Written by run.py before Phase 1; {LayerName:[abs_dirs]}
  output/                     Phase 3+4 output (JSON, .mmd, .png, .docx)
  workspaces/                 Per-project API checkouts + per-commit output
  logs/                       Daily log files (run_YYYYMMDD.log)
  CLAUDE.md                   Onboarding pointer (says "read PROJECT_CONTEXT.md")
  PROJECT_CONTEXT.md          This file

Note: config/ few_shot_examples/ assets/ and both generators live UNDER engine/;
load_config(<dir>) reads <dir>/config, so engine callers pass the engine dir
(paths().src_dir). Dev tooling (mock-api + dev scripts) now lives under `tools/`.
model/ output/ workspaces/ logs/ stay at the repo root (the gitignored `.data/`
grouping is still deferred). api/ is intentionally not renamed (absolute `from api.`
imports + a hyphen would break).
```

---

## 3. The 4-phase pipeline

```
Phase 1  engine/parser.py          C++ source → model/metadata.json,
                                             model/functions.json,
                                             model/globalVariables.json,
                                             model/dataDictionary.json
Phase 2  engine/model_deriver.py   model/ → model/units.json,
                                          model/components.json,
                                          model/knowledge_base.json (for flowchart engine),
                                          model/summaries.json (LLM hierarchy summaries)
                                  + enriches functions.json with interfaceId,
                                    direction, transitive globals, behaviour
                                    names, and (optionally) LLM descriptions
Phase 3  engine/run_views.py       model/ → output/interface_tables.json,
                                          output/unit_diagrams/*.mmd|.png,
                                          output/behaviour_diagrams/*.mmd|.png,
                                          output/flowcharts/*.json|.png
Phase 4  engine/docx_exporter.py   output/ → software_detailed_design_<group>.docx
```

Each phase is launched as a subprocess by [engine/core/orchestration.py](../engine/core/orchestration.py).
That keeps the phases hermetic (separate Python processes inherit `LOG_LEVEL`)
and lets `--from-phase N` skip earlier phases on a resume.

---

## 15. Test fixture — `SampleCppProject/`

`SampleCppProject/` is **vendored directly in this repo** — committed as normal tracked
files, so a plain `git clone` has the full fixture (no submodule, no `git submodule update
--init`, no empty folder). It is the single source of truth for the fixture. It was briefly
a git submodule → `github.com/manojksarkar/SampleCppProject`; that standalone repo is now
abandoned and the analyzer no longer depends on it. The incremental-diff **unit tests build
their own throwaway git repos** in a temp dir, so they don't need any external fixture repo;
for a manual incremental-UI demo, onboard the analyzer repo's own URL (a shallow, single-
branch clone) rather than maintaining a separate sample repo.

The old `test_cpp_project/` fixture is superseded. Current fixture (matches
`config.defaults.json` `layers`):

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
    Sample/                            — the CROSS-LAYER TWIN of Layer1/Sample (2026-09-06)
      Core/   Core.cpp/.h              — group "My Sample", component "Sample Core"
      Lib/    Lib.cpp/.h               — group "My Sample", component "Lib"
```

**The `Layer2/Sample` twin is deliberate and must not be "tidied".** It reuses Layer1's
group name (`My Sample`), component names (`Sample Core`, `Lib`), unit names (`Core`,
`Lib`), function names (`coreAdd`, `coreSetResult`, `libAdd`, `libNormalize`, …), global
names (`g_result`, `g_count`, `g_libTotal`, `g_libCalls`) and even its `Mode`/`Status`
enum names. It is the fixture for layer-qualified identity: with bare names all of those
collapsed into one component, one unit key and one set of function keys. The BODIES are
different on purpose (saturating/byte-oriented rather than arithmetic) so a generated
document shows at a glance which layer it describes. It is self-contained — it does NOT
include Layer1's `Types/`, because a cross-layer include would undo the separation the
fixture exists to demonstrate.

Consequence: **`--selected-group "My Sample"` is now AMBIGUOUS** and exits 2. The e2e
suite scopes to `Layer1.My Sample` (`tests/e2e_paths.GROUP`), which is also its coverage
of qualified selection.

`config.defaults.json`'s `layers` maps these to:
- **Layer1**: groups `My Sample` (Sample Core/Lib/Util), `Full` (Iface/Cross), `Support`
  (Math/App/Outer), `Access`, `Signal`, `Diag`
- **Layer2**: groups `My Sample` (Sample Core/Lib — the twin) and `Platform` (all 15
  platform components)

Group and component IDS are layer-qualified, so the two `My Sample` groups are
`Layer1.My Sample` and `Layer2.My Sample`, and the two `Sample Core` components are
`Layer1.Sample-Core` and `Layer2.Sample-Core`. See the 2026-09-06 entry.

### Key docs

- `docs/spec/SWE3_SPEC.md` — view logic requirements with verification criteria (REQ-IT-XX for Interface Tables, REQ-UD-XX for Unit Diagrams). Update first before changing any view logic.
- `docs/spec/TEST_INVENTORY.md` — maps every SWE3_SPEC requirement to its test case. Update after adding/changing tests.
- `.coveragerc` — single `.coverage` file written per run.

### Quick run commands

```bash
# Full run, all groups
python engine/run.py SampleCppProject

# Full clean run, single group
python engine/run.py --clean SampleCppProject --selected-group Sample

# Skip the LLM hierarchy summaries (faster, lower quality)
python engine/run.py --no-llm-summarize SampleCppProject

# Reuse model/, regenerate views + docx for one group
python engine/run.py --use-model SampleCppProject --selected-group Platform

# Resume after a Phase 4 crash without re-parsing
python engine/run.py --from-phase 4 SampleCppProject

# Verbose stderr (DEBUG); inherited by every subprocess phase
python engine/run.py --verbose SampleCppProject --selected-group Sample
```

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
python engine/run.py --selected-group Sample SampleCppProject
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
5. **`PhaseRunner.run(plan1.phases)`** — subprocess `python engine/parser.py
   <abs_project_path>`. The parser inherits `LOG_LEVEL` from env.
6. **Parser (Phase 1)** — loads libclang, reads `model/clang_include_paths.json`
   and extends `CLANG_ARGS` with `-I<dir>` for all layer subdirs. Walks every
   `.cpp/.h` under `MODULE_BASE_PATH`, runs three traversal passes, calls
   `build_metadata`, writes `metadata.json` / `functions.json` /
   `globalVariables.json` / `dataDictionary.json` to `model/`.
7. **`PhaseRunner.run(plan1.phases)` continues** — subprocess
   `python engine/model_deriver.py`.
8. **Model deriver (Phase 2)** — loads model via `core.model_io.load_model`.
   Builds units + components, propagates global access transitively, assigns
   interface IDs, runs static behaviour-name heuristics, optionally calls
   the LLM for descriptions and behaviour names, optionally runs the
   `HierarchySummarizer` for `summaries.json`, generates `knowledge_base.json`
   for the flowchart engine. Writes everything back to `model/` including the
   new `model/components.json`.
9. **`PhaseRunner.run(plan2.phases)`** — subprocess
   `python engine/run_views.py --output-dir output/Sample --selected-group Sample`.
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
    via component prefix, launches `python engine/flowchart/flowchart_engine.py …`
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
    `python engine/docx_exporter.py output/Sample/interface_tables.json output/Sample/software_detailed_design_Sample.docx --selected-group Sample`.
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

