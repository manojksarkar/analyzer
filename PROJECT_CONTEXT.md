# C++ Codebase Analyzer — Complete Project Context

> Updated: 2026-04-09 (post version2 refactor — Batches 1-6 complete).
> Validated against current source. Reading this file end-to-end is the
> intended way to onboard or to refresh context after compaction.

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
  test_cpp_project/           Fixture C++ tree (see §15)
  model/                      Phase 1+2 output (JSON)
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
                                          model/modules.json,
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

## 5. CLI — `run.py`

### Syntax

```bash
python run.py [options] <project_path>
```

### Flags

| Flag | Effect |
|---|---|
| `--clean` | Delete `model/` and `output/` before starting |
| `--use-model` (alias `--skip-model`) | Skip Phases 1+2; verify required model files exist; run Phases 3+4 only |
| `--no-llm-summarize` | Skip Phase 2 LLM hierarchy summarization (faster, lower quality). Summarization is **on by default** |
| `--llm-summarize` | Accepted for back-compat; no-op (already default) |
| `--selected-group <name>` | Export only the named group from `config.modulesGroups`. Case-insensitive |
| `--from-phase N` | Resume from phase N (1=Parse, 2=Derive, 3=Views, 4=Export). Lets you continue after a Phase 4 crash without re-parsing |
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

1. Validates `<project_path>` exists.
2. If `--use-model` is set, verifies `model/functions.json`, `globalVariables.json`,
   `units.json`, and `modules.json` are all present (paths via
   `core.model_io.model_file_path`). Exits 2 if missing.
3. Calls [core.group_planner.plan_runs(...)](src/core/group_planner.py) which
   returns a flat `List[RunPlan]`.
4. Iterates the plans through a single [PhaseRunner](src/core/orchestration.py)
   instance. Each plan corresponds to one `runner.run(plan.phases, from_phase=plan.runner_from_phase)` call.

### Three dispatch shapes (collapsed inside `plan_runs`)

| Config state | CLI | Plans returned |
|---|---|---|
| No `modulesGroups` | (any) | One plan with all 4 phases (or just 3+4 if `--use-model`) |
| `modulesGroups` present | no `--selected-group` | One "Build model" plan (Phases 1+2) + N "Group: <name>" plans (Phases 3+4 each, with `--output-dir output/<group>/`) |
| `modulesGroups` present | `--selected-group <G>` | One "Build model" plan + one "Group: <G>" plan (Phases 3+4 only, **no `--output-dir`** — output goes to `output/`) |

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
    "unitDiagrams":     { "renderPng": true },
    "flowcharts":       { "scriptPath": "src/flowchart/flowchart_engine.py", "renderPng": true },
    "behaviourDiagram": { "renderPng": true },
    "moduleStaticDiagram": { "enabled": true, "renderPng": true, "widthInches": 5.5 }
  },
  "clang": {
    "llvmLibPath":       "C:\\Program Files\\LLVM\\bin\\libclang.dll",
    "clangIncludePath":  "C:\\Program Files\\LLVM\\lib\\clang\\17\\include",
    "clangArgs":         []
  },
  "llm": {
    "descriptions":      false,
    "behaviourNames":    false,
    "provider":          "ollama",        // "ollama" | "openai"
    "baseUrl":           "http://localhost:11434",
    "defaultModel":      "qwen2.5-coder:14b",
    "timeoutSeconds":    120,
    "numCtx":            8192,             // Ollama context window
    "retries":           1,                // up to (1 + retries) total tries
    "abbreviationsPath": "config/abbreviations.txt",
    "apiKey":            "",               // openai bearer; prefer env LLM_API_KEY
    "customHeaders":     { "x-dep-ticket": "credential:", "User-Type": "AD_ID", ... }
  },
  "modulesGroups": {
    "core":    { "core":    ["app", "math"] },
    "support": { "support": "outer/inner" },
    "tests":   {
      "tests_a": ["tests/direction", "tests/enum", "tests/flow"],
      "tests_b": ["tests/hub", "tests/poly", "tests/structs"]
    }
  },
  "export": {
    "docxPath":      "output/software_detailed_design_{group}.docx",
    "docxFontSize": 8
  }
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

- Group names and module names: **CapitalCamelCase or snake_case**, both are tolerated.
- Each folder path should appear in exactly one group; the parser merges all
  groups into one big folder set so cross-group calls are still discoverable.
- `selectedGroup` is **not** a config key — group selection is CLI-only.
- LLM is off by default for descriptions/behaviour names. Phase 2 hierarchy
  summarization (which writes `summaries.json` + `knowledge_base.json`) is
  on by default and is controlled by `--no-llm-summarize`.

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
- `load_config(project_root)` — merges `config/config.json` + `config.local.json`.
- `load_llm_config(cfg)` — env-var overlay + normalised `llm` block (see §6).
- `app_config(*, refresh=False)` — process-cached merged dict.
- Typed accessors: `llm_config()`, `views_config()`, `exporter_config()`,
  `clang_config()`, `modules_groups()`.

### `core.model_io` — [src/core/model_io.py](src/core/model_io.py)

Canonical filenames (use these constants, never bare strings):
`METADATA`, `FUNCTIONS`, `GLOBALS`, `UNITS`, `MODULES`, `DATA_DICTIONARY`,
`KNOWLEDGE_BASE`, `SUMMARIES`. Tuple `ALL_MODEL_NAMES` lists them all.

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

## 8. `src/llm_core/` — unified LLM client

Five files. The whole point: there is **one** LLM client class in the project.

### `llm_core.client.LlmClient` — [src/llm_core/client.py](src/llm_core/client.py)

Two providers behind one `generate(system_prompt, user_prompt)` method:

| Provider | Endpoint | Auth |
|---|---|---|
| `ollama` | `POST {baseUrl}/api/generate` | none |
| `openai` | `POST {baseUrl}/chat/completions` | bearer + custom headers |

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

`from_config(llm_cfg)` builds an `LlmClient` from a `load_llm_config()` dict.

Legacy positional args (`url=`, `use_openai_format=`) are still accepted so
the flowchart engine's standalone subprocess invocation keeps working.

### `llm_core.headers` — `build_openai_headers`, `resolve_api_key`

Resolves `LLM_API_KEY` env var first, falls back to `llm.apiKey`. Handles
the corporate-gateway custom-header format and `X_DEP_TICKET`/`USER_TYPE`/
`USER_ID`/`SEND_SYSTEM_NAME` env overrides.

### `llm_core.think` — `strip_think_section(text)`

Removes `<think>...</think>` sections (used by `gpt-oss` / DeepSeek R1 style
models) so downstream consumers see just the answer.

### `llm_core.tokens` — `record(provider, model, prompt, completion)`,
`format_report()`

Process-wide counter. Dumped automatically by the logging atexit hook so each
subprocess writes its own report into `logs/run_YYYYMMDD.log`.

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
| `safe_filename(s)` | Replace `<>:"/\\|?*,&;` with `_` |
| `init_module_mapping(config)` | Build `_MODULE_OVERRIDES` from `modules` or merged `modulesGroups` |
| `_resolve_module_from_rel(rel)` | Match relative path against `_MODULE_OVERRIDES` (case-insensitive) |
| `make_unit_key(rel_file)` | `module\|unitname` |
| `make_global_key(rel_file, qn)` | `module\|unit\|qualifiedName` |
| `make_function_key(module, rel_file, qn, params)` | `module\|unit\|qualifiedName\|paramTypes` |
| `path_from_unit_rel(rel)` | Strip extension, normalise slashes |
| `short_name(qn)` | Last `::` segment |
| `path_is_under(base, candidate)` | Safe containment via `os.path.relpath` |
| `get_module_name(file_path, base_path)` | Absolute path → module name (uses `path_is_under`) |
| `norm_path(path, base_path)` | Resolve relative paths against `base_path` |
| `PRIMITIVES` dict | C++ primitive types → range string |
| `get_range_for_type(type_str)` | Map type to range; falls back to `NA` |
| `get_range(type_str, data_dictionary)` | Range lookup with typedef recursion (depth 10) |

Note: `init_module_mapping` runs at import time using the on-disk config, so
`make_*_key` works immediately. `parser.py` builds its own folder list from
the same config (kept separate to avoid the analyzer's import order
constraints).

---

## 10. Phase 1 — `src/parser.py`

### Initialization

- Reads `core.config.app_config()` and `clang_config()`.
- Loads libclang from `clang.llvmLibPath`. On Windows, calls
  `os.add_dll_directory(<llvm/bin>)` so dependent DLLs are found, with a
  `PATH`-extension fallback.
- Builds `_MODULE_FOLDERS` from merged `modulesGroups` (or `modules` top-level).
- Sets `CLANG_ARGS`:
  - `-std=c++17`
  - `-I<MODULE_BASE_PATH>`, `-I<clangIncludePath>`
  - `-DPRIVATE=` `-DPROTECTED=` `-DPUBLIC=` `-D__OVLYINIT=` (visibility macros)
  - `-DVOID=void` (handles codebases that use `VOID` as a type macro)
  - Any extras from `config.clang.clangArgs`.

### Visibility detection (`_detect_visibility`)

Scans **backwards up to 5 source lines** from a declaration line looking for
the first token `PRIVATE`, `PUBLIC`, or `PROTECTED`. Returns the matching
lowercase string or `default`. Required because the visibility macros are
expanded to nothing by `-DPRIVATE=` and Clang doesn't surface them.

### File filtering (`is_project_file`)

Rejects anything outside `MODULE_BASE_PATH` and (when `_MODULE_FOLDERS` is
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

Based purely on **direct** global access:
- writes only → `direction = "In"` (setter)
- reads only → `direction = "Out"` (getter)
- both / neither → `direction = "In"`

Phase 2 forces every function's direction to `"In"` or `"Out"` (never empty)
and every global to `"In/Out"`.

### Final keying (`build_metadata` + `utils.make_function_key`)

Final model key: `module|unit|qualifiedName|paramTypes`.

- `module` from `get_module_name(file_path, base_path)` → `_resolve_module_from_rel`.
- `unit` from filename without extension.
- `qualifiedName` includes namespace + class.
- `paramTypes` is the comma-joined list of normalised parameter type strings.

### Outputs

`metadata.json`, `functions.json`, `globalVariables.json`, `dataDictionary.json`
written to `model/` via plain `json.dump`.

---

## 11. Phase 2 — `src/model_deriver.py`

Loads via `core.model_io.load_model(METADATA, FUNCTIONS, GLOBALS)` and exits
with a clear "Run Phase 1 first" message on `ModelFileMissing`.

### `_build_units_modules`

Groups all functions and globals by file path. Produces:
- `model/units.json` — one entry per `.cpp/.cc/.cxx` (headers excluded from
  unit keys). Each entry has `name`, `path`, `fileName`, `functionIds` (sorted
  by source line), `globalVariableIds`, `callerUnits` (set), `calleesUnits` (set).
- `model/modules.json` — one entry per module containing its unit keys.

### `_build_interface_index` / `_enrich_interfaces`

Assigns a per-file sequential index, then sets
`interfaceId = IF_<PROJECTUPPER>_<UNITPATH_UPPER>_<INDEX>` on each function and
global. Also normalises `parameters` to `[{name, type}]`, dropping any extra
fields the parser captured.

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

### `_enrich_from_llm`

When `config.llm.descriptions: true`:
- `enrich_functions_with_descriptions` processes functions **bottom-up**
  through the call graph (callees first), so each prompt can include the
  callees' descriptions as context.
- `enrich_globals_with_descriptions` processes globals sequentially.
- A `ProgressReporter` reports `[idx/total]` progress.

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

Loads model via `core.model_io.load_model(FUNCTIONS, GLOBALS, UNITS, MODULES, optional=[DATA_DICTIONARY])`.

When a group is selected, run_views resolves the name case-insensitively
against `config.modulesGroups` and stuffs two extra keys into the config dict
that's passed down into views:

- `_analyzerSelectedGroup` = the resolved group name
- `_analyzerAllowedModules` = sorted list of module names from that group's entry

Then it calls `views.run_views(model, output_dir, model_dir, config)`.

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

- Iterates `.cpp` units only.
- Filters by `_analyzerAllowedModules` if set.
- Excludes `private` functions and globals.
- For each function: builds caller/callee unit references and tags them
  internal vs external. Internal = same module (or within `allowed_modules`
  when a group is selected); external is rendered as `module/unit`.
- Enriches parameters with `range` from the data dictionary via `get_range()`.
- Strips file extensions from `location.file`.

### View 2: `unitDiagrams` — [src/views/unit_diagrams.py](src/views/unit_diagrams.py)

One Mermaid `.mmd` (and optionally `.png`) per unit into
`output/unit_diagrams/`.

- `.cpp` units only; filtered by `allowed_modules` when set.
- Layout: external callers on the left, **yellow** module box in the centre,
  external callees on the right, all flowing left-to-right.
- The main unit is **blue with a thick border**; sibling units are blue thin.
- Edges labelled with `interfaceId` values, BR-separated for multi-edge.
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
2. Pulls `clang.clangArgs` from config; if empty, derives `-I<basePath>` from
   `metadata.json`.
3. If a group is selected, **filters `functions.json` by module-prefix** and
   writes `model/functions_<group>.json`. The filtered file is passed to the
   engine instead of the full one. (Module-prefix filtering, not units.json
   traversal — see Risk 2 in §16.)
4. Builds the engine command:
   ```
   python src/flowchart/flowchart_engine.py
       --interface-json <functions[_group].json>
       --metaData-json  model/metadata.json
       --std            c++17
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
7. **LLM labeling** — `LabelGenerator.label_cfg(cfg, func_entry, source, base)`
   batches up to `BATCH_SIZE=4` nodes per LLM call. Two failure modes are
   handled differently:
   - Empty response (`raw=None`, prompt > num_ctx) → retry **without** any
     "retry note" (would inflate the prompt). After all retries fail, the
     batch is auto-halved and recursed up to depth 3. This adapts to any
     model's actual context window without manual tuning.
   - Bad JSON / missing nodes → append a targeted retry note with the failing
     `node_id`s so the LLM can correct precisely.
   `MAX_PROMPT_CHARS=6000` (~1500 tokens) is the hard cap.
8. **Validation** — `validate_cfg(cfg)` then `validate_mermaid(script)`.
   Failures are logged at WARNING but don't abort the run.
9. **Build Mermaid** — `build_mermaid(cfg)`.

### LLM client construction (`_build_llm_client`)

Walks `cwd` and one parent for `config/config.json`. If found, uses
`utils.load_config + load_llm_config + llm_core.client.from_config` so the
analyzer's provider, custom headers, retries, and API key all flow through.
Falls back to a legacy Ollama-only positional constructor when running
standalone outside the analyzer tree.

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

### CLI

```
python src/docx_exporter.py [json_path] [docx_path] [--selected-group <name>]
```

`--selected-group` is stripped before positional parsing.

### DOCX section structure

```
Software Detailed Design                                       (Heading 0)
1 Introduction                                                 (Heading 1)
  1.1 Purpose
  1.2 Scope
  1.3 Terms, Abbreviations and Definitions
2 <ModuleName>                                                 (Heading 1)
  2.1 Static Design                                            (Heading 2)
    [Module static structure diagram — PNG or Mermaid text]
    [Component / Unit table — Component | Unit | Description | Note]
    2.1.1 <UnitName>                                           (Heading 3)
      [Unit diagram PNG if available]
      2.1.1.1 unit header                                      (Heading 4)
        Path: <path/without/extension>
        [Unit header table — globals/typedef/enum/define | information]
      2.1.1.2 unit interface                                   (Heading 4)
        [Interface table — 8 cols, see below]
      2.1.1.3 <UnitName>-<InterfaceId>                         (Heading 4)
        [Flowchart table — 5 rows, see below]
      ... one Heading-4 sub-section per interface ...
  2.2 Dynamic Behaviour                                        (Heading 2)
    2.2.1 <UnitName> - <FuncName> (<ExternalUnitFunc>)         (Heading 3)
      [Behaviour description table]
      [Behaviour PNG if rendered]
N Code Metrics, Coding Rule, Test Coverage                     (Heading 1)
Appendix A. Design Guideline                                   (Heading 1)
```

### Module static structure diagram

Mermaid TB flowchart: dark module box → blue unit boxes. Rendered by `mmdc`
into `artifacts_dir/module_static_diagrams/<module>.png`. Width controlled
by `views.moduleStaticDiagram.widthInches` (default 5.5).

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
  typedef-to-struct, else `NA`.
- **Enums** — declaration snippet; info column is `NAME=value, …`.
- **Defines** — full macro text; info column is the value.

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

## 15. Test fixture — `test_cpp_project/`

Current layout (matches `config.json` modulesGroups):

```
test_cpp_project/
  app/
    main.cpp                       — top-level entry
  math/
    utils.cpp                      — small math helpers
  outer/inner/
    helper.cpp                     — nested-directory module path
  tests/
    access/access_visibility.cpp   — PRIVATE/PUBLIC/PROTECTED macros
    direction/read_write.cpp       — In/Out direction from globals
    enum/types.cpp                 — enum / typedef coverage
    flow/flowcharts.cpp            — control-flow patterns (if/else, switch, loops)
    hub/hub.cpp                    — cross-module fan-out
    poly/dispatch.cpp              — virtual dispatch / polymorphism
    structs/point_rect.cpp         — struct + union types
    void_alias/forward_void_decl.cpp
    void_alias/multiline_ovlyinit.cpp
    void_alias/preproc_if_function.cpp
    void_alias/preproc_if_function_then.cpp
    void_alias/void_as_var.cpp
    void_alias/void_is_void.cpp    — synthetic-from-VAR_DECL recovery cases
```

`config.json`'s `modulesGroups` maps these to three groups: `core`
(`app` + `math`), `support` (`outer/inner`), and `tests` (split into
`tests_a` and `tests_b`).

### Quick run commands

```bash
# Full run, all groups
python run.py test_cpp_project

# Full clean run, single group, output to output/ (not output/<group>/)
python run.py --clean test_cpp_project --selected-group core

# Skip the LLM hierarchy summaries (faster, lower quality)
python run.py --no-llm-summarize test_cpp_project

# Reuse model/, regenerate views + docx for one group
python run.py --use-model test_cpp_project --selected-group tests

# Resume after a Phase 4 crash without re-parsing
python run.py --from-phase 4 test_cpp_project

# Verbose stderr (DEBUG); inherited by every subprocess phase
python run.py --verbose test_cpp_project --selected-group core
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

---

## 18. Past mistakes / lessons learned

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

### Configs with `core` / `support` / `tests` vs `InterfaceTables` / etc.

Earlier docs referenced `InterfaceTables`, `Flowcharts`, `BehaviourDiagram`,
… as group names. The current `config.json` uses `core`, `support`, `tests`
(matching the test fixture). When validating CLI behaviour, always check
which config is active before quoting group names.

---

## 19. Dependencies

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

## 20. End-to-end code flow — single command, full pipeline

For the literal-minded: this is what happens when you run

```bash
python run.py --selected-group core test_cpp_project
```

1. **`run.py` startup** — sets `cwd` to its own directory; prepends
   `src/` to `sys.path`; calls `core.logging_setup.configure_logging` (which
   creates `logs/run_YYYYMMDD.log` and the stderr handler).
2. **Argv loop** — parses flags. Sets `selected_group_arg = "core"`,
   `from_phase = 1`, `use_model = False`, `no_llm_summarize = False`.
3. **`load_config(SCRIPT_DIR)`** (re-exported from `core.config`) — reads
   JSONC, merges `config.local.json` if present.
4. **`plan_runs(cfg, …)`** — sees `modulesGroups` is set and a single
   `selected_group`. Returns two plans:
   - Plan 1: "Build model (all modules)" → `[parser.py, model_deriver.py --llm-summarize]`
   - Plan 2: "Group: core" → `[run_views.py --selected-group core, docx_exporter.py --selected-group core]`
5. **`PhaseRunner.run(plan1.phases)`** — subprocess `python src/parser.py
   <abs_project_path>`. The parser inherits `LOG_LEVEL` from env.
6. **Parser (Phase 1)** — loads libclang, walks every `.cpp/.h` under
   `MODULE_BASE_PATH`, runs three traversal passes, calls `build_metadata`,
   writes `metadata.json` / `functions.json` / `globalVariables.json` /
   `dataDictionary.json` to `model/`.
7. **`PhaseRunner.run(plan1.phases)` continues** — subprocess
   `python src/model_deriver.py --llm-summarize`.
8. **Model deriver (Phase 2)** — loads model via `core.model_io.load_model`.
   Builds units + modules, propagates global access transitively, assigns
   interface IDs, runs static behaviour-name heuristics, optionally calls
   the LLM for descriptions and behaviour names, runs the
   `HierarchySummarizer` for `summaries.json`, generates `knowledge_base.json`
   for the flowchart engine. Writes everything back to `model/`.
9. **`PhaseRunner.run(plan2.phases)`** — subprocess
   `python src/run_views.py --selected-group core`.
10. **`run_views.py`** — loads model (`load_model(FUNCTIONS, GLOBALS, UNITS, MODULES, optional=[DATA_DICTIONARY])`),
    resolves the group name case-insensitively, sets `_analyzerSelectedGroup`
    + `_analyzerAllowedModules` on the config dict, calls
    `views.run_views(model, output_dir, model_dir, config)`.
11. **`interface_tables` view** — writes `output/interface_tables.json`
    filtered to the `core` modules.
12. **`unit_diagrams` view** — emits one `.mmd` per `.cpp` unit into
    `output/unit_diagrams/`, then renders each with `mmdc`.
13. **`behaviour_diagram` view** — uses `FakeBehaviourGenerator` to emit
    `.mmd` files plus `_behaviour_pngs.json`.
14. **`flowcharts` view** — filters `functions.json` to `functions_core.json`
    via module prefix, launches `python src/flowchart/flowchart_engine.py …`
    with `--knowledge-json model/knowledge_base.json`. The engine:
    - builds (or restores from `.flowchart_cache/`) the PKB
    - groups functions by source file
    - for each function: source extract → libclang TU parse → cursor resolve
      → CFG build (with ASSERT skip) → enrich with PKB → batched LLM labeling
      with auto-halving on empty responses → validate → build Mermaid
    - writes one JSON per source file into `output/flowcharts/`
    - writes `_summary.json`
    The view then walks the per-unit JSONs and renders every flowchart to
    PNG via `mmdc`.
15. **`PhaseRunner.run(plan2.phases)` continues** — subprocess
    `python src/docx_exporter.py --selected-group core`.
16. **`docx_exporter.py`** — `artifacts_dir = output/`, loads model + abbreviations,
    iterates modules, builds the DOCX via `python-docx`. Embeds module static
    diagrams, unit diagrams, flowchart PNGs, and behaviour-diagram PNGs from
    paths under `artifacts_dir`. Writes
    `output/software_detailed_design_core.docx`.
17. **Back in `run.py`** — `runner.run` returns elapsed seconds; the loop logs
    `Done. Total: <secs>s` and `Full log: logs/run_YYYYMMDD.log`. Each
    subprocess's `atexit` hook has already dumped its LLM token usage to the
    log file.

If anything in steps 5–16 fails with a non-zero exit code, the runner logs
`<phase> failed with exit code N; resume with: --from-phase <idx>`. The user
can fix the underlying issue and rerun with that flag, skipping straight to
the failed step.
