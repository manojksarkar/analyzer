# CLI and config

> **Project context — one part of it.** Start at [PROJECT_CONTEXT.md](../PROJECT_CONTEXT.md),
> the index: current state, how to read the context, every file. The sections below moved here
> from the single-file context on 2026-09-28, unchanged except link paths, and keep their numbers —
> "PROJECT_CONTEXT §N" still finds them. Written over time: where a section and a newer dated
> entry in [history/](history/) disagree, the newer entry and the code win.

**Sections:** [5. CLI — `run.py`](#5-cli--runpy) · [6. Config — `engine/config/config.defaults.json`](#6-config--engineconfigconfigdefaultsjson)

## 5. CLI — `run.py`

### Syntax

```bash
python engine/run.py [options] <project_path>
```

### Flags

| Flag | Effect |
|---|---|
| `--clean` | Delete `model/` and `output/` before starting. Runs **after** `<project_path>` is validated (since 2026-08-11) — it used to run first, so `--clean <typo'd path>` wiped both dirs and then aborted. In database mode it also warns that the stored model **survives** — the directories are no longer where the model is. |
| `--model-scratch` | The model of THIS invocation is scratch, not a version's: it goes to JSON in the run's model dir and carries no version id. One caller - the narrowed parse's partial pass, whose output covers only the changed translation units and is valid only after `parse_merge`. Not a storage choice; no flag points a real run at it. |
| `--version-id <id>` / `--project-id <id>` | The run identity every phase needs once the model is rows rather than files. Applied **before** `paths()` is snapshotted. |
| `--help` / `-h` | Print the option list (the `run.py` module docstring) and exit 0. Handled at the top of the file, before `configure_logging`/`chdir`/config load, so it works even with a broken config and writes no log file. |
| `--config <path>` | Use this config file instead of `engine/config/config.json` — a per-project/per-version config (carries the project's `layers`). Resolved+validated, then exported as `ANALYZER_CONFIG` **before** the import-time config load in `utils`, so every phase subprocess (env inherited) honors it. `config.local.json` is **not** merged on top (used as-is, for reproducibility); a set-but-missing path fails loud. Foundation for incremental per-project runs (§23, M1.1). |
| `--use-model` (alias `--skip-model`) | Skip Phases 1+2; verify required model files exist; run Phases 3+4 only |
| `--no-llm-summarize` | Skip Phase 2 LLM hierarchy summarization (faster, lower quality). Summarization is **on by default**. Can also be set via `llm.summarize: false` in config (see §4c). |
| `--llm-summarize` | Accepted for back-compat; no-op (already default) |
| `--selected-group <name>` | Export only the named group. Phase 1+2 parse only that group's layer. Case-insensitive. Mutually exclusive with `--selected-layer` and `--selected-component`. |
| `--selected-layer <name>` | Parse only the named layer (Phase 1+2) and generate DOCX for every group in it (Phase 3+4 per group). Mutually exclusive with `--selected-group` and `--selected-component`. |
| `--selected-component <name>` | Export a DOCX for the named component. Repeatable; they may span layers, and the parse scope is the union of their layers. With `--component-per-docx`: one document each, `output/<C>/`. Without it: bundled, `output/<C1_C2>/software_detailed_design_<C1_C2>.docx` (`_` between names, `-` replaces spaces). Mutually exclusive with `--selected-group` and `--selected-layer`. |
| `--component-per-docx` | Modifier: split group/layer runs into one DOCX per component instead of one per group. Compatible with `--selected-group`, `--selected-layer`, or no selection. Cannot be combined with `--selected-component`. See §4f. |
| `--from-phase N` | Resume from phase N (1=Parse, 2=Derive, 3=Views, 4=Export). Lets you continue after a Phase 4 crash without re-parsing |
| `--data-dictionary <path>` | CSV file merged into `model/dataDictionary.json` at end of Phase 1. **Project-wide**: its entries answer for every layer. External entries win on conflict. See `engine/config/data_dictionary.csv` for format. **CLI-only — no config key by design** (§17). |
| `--data-dictionary-layer <layer> <path>` | Same format, scoped to one layer. Repeatable, once per layer. Unknown layer → exit 1, missing file → exit 2. A layer's entries answer **only** for that layer; another layer's dictionary is never consulted. Config equivalent: `layers.<name>.dataDictionary`. |
| `--project-name <name>` | Override the project name written into `model/metadata.json` as `projectName`. Default: `os.path.basename(project_path)`. Propagates to `model_deriver` (interfaceId fallback segment, LLM knowledge base), flowchart engine, and LLM prompts. |
| `--macros <path>` | Macro file passed as `-D` flags to Clang in Phase 1, applied to **every** layer. CSV (`Name`, `Value`; header row) **or** JSON — toolchain dump (`macros_by_cu`), `{"NAME":"VALUE"}` map, `["NAME=VALUE"]` list, or `{"Layer1": {…}}`; shape is detected by content, not extension (`core/macro_input.py`). `Value` `"ne"` (any case) skips the entry; empty → `-DNAME`; function-like names are skipped + logged. Written to `model/clang_macros.json` (scope-keyed) so the Phase 3 flowchart engine picks them up. Sample: `engine/config/macros.csv`. |
| `--macros-layer <layer> <path>` | Same formats, applied to the named layer only. Repeatable — once per layer. Unknown layer → exit 1, missing file → exit 2. Clang honours the last `-D`, so a layer value overrides a `--macros` global one. Config equivalents: `clang.macrosFile` / `clang.macrosByLayer`; `clang.macroScopes` maps a multi-CU dump's compilation units to layers. |
| `--include-path-layer <layer> <dir>` | Add an extra `-I` include directory for the named layer. Repeatable — use once per directory. The directory is merged into `model/clang_include_paths.json` under the named layer key before Phase 1 runs, so Phase 1 (`clang_args_for`) and Phase 3 (`_resolve_layer_dirs`) pick it up automatically via existing layer-scoping. **No project-wide form** — an include dir always belongs to a layer. Unknown layer → exit 1. Missing directory → exit 1. Renamed from `--include-path` on 2026-08-18 (§17). |
| `--filter-mode <mode>` | Override `views.sequenceDiagrams.filterMode` for this run. Forwarded by `group_planner` to Phase 3, where `run_views.py` writes it into the in-memory config. **Live since 2026-08-22** — `SequenceDiagramGenerator._get_filter_mode` reads the key and `create_diagram_selector` maps it to a selector class. Vocabulary: `single_per_function`, `single_per_external_component`, `all_callers`, `multi_unit_functions`, `skip_within_unit` (**default**). Still **unvalidated** — an unknown value falls through the factory's `else` to `skip_within_unit` silently, so a typo degrades instead of erroring. Had **no parse branch in `run.py` until 2026-08-11** — the flag was dead and `--filter-mode X` made `--filter-mode` the project path. |
| `--trace-prompts` | Print full LLM prompts (system + user) to stdout. Sets `LLM_TRACE_PROMPTS=1` env var. **Warning**: large runs emit tens of MB. |
| `--quiet` | stderr handler raised to WARNING |
| `--verbose` | stderr handler lowered to DEBUG |

`--quiet` and `--verbose` set `LOG_LEVEL` in the environment so child phases
inherit the same verbosity.

### Argument parsing

Hand-rolled token-scanning loop in [run.py](../engine/run.py) (no `argparse`).
**Strict since 2026-08-11** — the loop has no silent fall-through: a token is a
known flag, a `-`-prefixed unknown (rejected), or the single positional
`<project_path>`. Four historical bugs are guarded against here:

1. `--selected-group core` used to leave `core` as a positional after the flag
   was consumed. Fix: each flag explicitly consumes its value (`i += 1`).
2. `--from-phase` is validated to 1–4 and exits with a clear error otherwise.
3. **Unknown options** (`elif a.startswith("-")`) exit 1 with `Unknown option: <flag>`
   plus a `difflib` "did you mean" line (`n=3, cutoff=0.7` — 0.6 suggests `--help`
   for `--phase`). They used to fall into `raw_args` and be ignored, so
   `run.py <proj> --phase 3` re-ran the whole pipeline from Phase 1 in silence.
4. **Extra positionals** (`len(raw_args) > 1`) exit 1 — usually the orphaned value
   of a mistyped flag. Checked before the path check and before `--clean`, so a bad
   command line never deletes `model/`/`output/`.

`_KNOWN_FLAGS` (module level) backs both the rejection and the suggestions.
`tests/unit/test_cli.py` AST-compares it against the flag literals in the parse
loop, so adding a branch without a `_KNOWN_FLAGS` entry fails the suite.

The phase scripts (`parser.py`, `run_views.py`, `docx_exporter.py`) still ignore
unknown args — open follow-up; they are only spawned by `group_planner` today.

### Plan + dispatch

After parsing flags, run.py:

0. **Layer include paths** — resolves the selected layer (from `--selected-group` or `--selected-layer`), then walks only that layer's directories (or all layers if neither flag is set) and writes `model/clang_include_paths.json`. Phase 1 reads this to extend `CLANG_ARGS` with `-I<dir>` for each collected directory.
1. Loads `engine/config/config.json` (+ `config.local.json`) via `load_config`.
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
5. Calls [core.group_planner.plan_runs(...)](../engine/core/group_planner.py) which
   returns a flat `List[RunPlan]`.
6. Iterates the plans through a single [PhaseRunner](../engine/core/orchestration.py)
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
| `layers` present | `--selected-component C [--selected-component C2 …]` | the union of the named components' layers | 1 DOCX for C[_C2…], or one EACH with `--component-per-docx` |
| `layers` present | any of above + `--component-per-docx` | same as without flag | 1 DOCX **per component** instead of per group |

`--selected-group`, `--selected-layer`, and `--selected-component` are mutually exclusive; combining any two exits with code 1. `--component-per-docx` combines with all three (2026-09-07): with `--selected-component` it splits the named components into one document each instead of bundling them.

Phase 4 (`docx_exporter.py`) receives the group's `interface_tables.json`
and DOCX path as positional args plus `--selected-group <G>` (group path) or
`--selected-component C [--selected-component C2]` (component path) so it can
apply the same-layer model filter (see §4d).

`--from-phase` translation also lives here:
- `from_phase ≤ 2`: build-model plan starts at that index, group plans start at 1.
- `from_phase ≥ 3`: build-model plan is **suppressed**; each group plan uses `local_from = max(1, from_phase - 2)` (so 3→1, 4→2 inside the views+export plan).

---

## 6. Config — `engine/config/config.defaults.json`

JSONC: `//`, `/* */`, and trailing commas are tolerated by
`core.config._strip_json_comments` + `_strip_trailing_commas`.

### Where each setting lives (three sources, three roles)

Config is split by **role**, not scattered — each source has one job:

| Source | Role | Holds | Tracked | Scope |
|---|---|---|---|---|
| `engine/config/config.defaults.json` | built-in **defaults** | the schema below (views/clang/llm-non-secret/layers/docx) | yes | shared |
| `engine/config/config.local.json` | **secrets / infra** | `db` connection + `llm` credentials (baseUrl, customHeaders/token) | **gitignored** | per machine |
| `versions.resolved_config` (Postgres) | **per-version** analysis config | defaults + project `build_config` + `layers` (+ `no_llm`) — **non-secret** | in DB | per version |

Resolution:
- **`load_config(engine_dir)`** deep-merges `config.defaults.json` then `config.local.json`
  (`core.config._deep_merge` — nested dicts merge per key, scalars/lists replace; so
  `config.local.json` can override just `llm.baseUrl` or one `llm.customHeaders` entry without
  restating the block). Used by standalone `python engine/run.py` and by the CLI/db tools.
- **`ANALYZER_CONFIG=<file>`** (set by `run.py --config`) loads that one file *instead* — no merge.
  This is how a per-project/per-version config is injected into the analyzer and every phase
  subprocess (they inherit the env var).
- **API-driven jobs**: `pipeline_runner._write_project_config` builds the per-version **non-secret**
  analysis config (`config.defaults.json` + `build_config` + `layers`), stores it in
  `versions.resolved_config` (via `_store_resolved_config`, on the version row reserved at job
  start), and **materializes** the workspace `config.json` the engine runs with = that config with
  `config.local.json`'s secrets overlaid (llm creds), **`db` section stripped** (the engine reaches
  Postgres via `DATABASE_URL`, so the password is never written to a workspace file). The engine
  reads the workspace file via `ANALYZER_CONFIG`. `_make_version` carries `resolved_config` through
  finalize (the repo's `_put` replaces the whole row).

**Secrets never enter `config.defaults.json` (tracked) or `versions.resolved_config` (per-version).**
Copy `config.local.json.example` → `config.local.json` and fill in `db` + `llm` credentials.

### Current schema (`config.defaults.json` — non-secret defaults)

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
    // SECRETS below → put in config.local.json (gitignored), NOT here. baseUrl also if private.
    "apiKey":            "",              // openai bearer; prefer env LLM_API_KEY
    "rateLimitSeconds":  3.0,             // pause after every OpenAI call (>=0; 0 = off; ollama ignores)
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

`load_llm_config()` (in [engine/core/config.py](../engine/core/config.py)) honors:

| Env var | Wins over |
|---|---|
| `LLM_PROVIDER` | `llm.provider` |
| `LLM_BASE_URL` | `llm.baseUrl` |
| `LLM_DEFAULT_MODEL` | `llm.defaultModel` |
| `LLM_TIMEOUT_SECONDS` | `llm.timeoutSeconds` |
| `LLM_NUM_CTX` | `llm.numCtx` |
| `LLM_RETRIES` | `llm.retries` |
| `LLM_API_KEY` | `llm.apiKey` |
| `LLM_RATE_LIMIT_SECONDS` | `llm.rateLimitSeconds` |

Custom-header values can be overridden via `X_DEP_TICKET`, `USER_TYPE`,
`USER_ID`, `SEND_SYSTEM_NAME` (handled inside `llm_core.headers`).

### Config rules

- Group names and component names: **CapitalCamelCase or snake_case**, both are tolerated.
- **Two layers MAY use the same group or component name** — `FTL/Cache` and `HIL/Cache` are
  two different components. Ids are layer-qualified (`Layer1.Cache`), so they no longer
  collide; see the 2026-09-06 entry. Group and component names must be unique **within their
  own layer**, each folder path must appear in exactly one component (nesting one
  component's path inside another's counts as a clash), and no name may contain `.` (the id
  separator). Enforced by `core.config.validate_layer_names`; `run.py` exits 2.
  A component MAY share a name with a group (`Access`, `Signal`, `Diag` do).
- **A bare group/component name is still accepted on the CLI** while only one layer has it.
  When two do, `run.py` exits 2 naming both candidates rather than picking one —
  `--selected-group Layer1.Support`, or `--selected-layer`, says which.
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

