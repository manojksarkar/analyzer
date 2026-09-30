# Engine infrastructure — `engine/core/`, `engine/llm_core/`, `engine/utils.py`

> **Project context — one part of it.** Start at [PROJECT_CONTEXT.md](../PROJECT_CONTEXT.md),
> the index: current state, how to read the context, every file. The sections below moved here
> from the single-file context on 2026-09-28, unchanged except link paths, and keep their numbers —
> "PROJECT_CONTEXT §N" still finds them. Some of it has drifted since: read the index's [What changed
> after the numbered sections](../PROJECT_CONTEXT.md#what-changed-after-the-numbered-sections) first.

**Sections:** [7. `engine/core/` — infrastructure layer](#7-enginecore--infrastructure-layer) · [8. `engine/llm_core/` — unified LLM client + token-budget toolkit](#8-enginellm_core--unified-llm-client--token-budget-toolkit) · [9. `engine/utils.py` — analyzer-specific helpers](#9-engineutilspy--analyzer-specific-helpers)

## 7. `engine/core/` — infrastructure layer

Eight modules, all with no upward imports. Anything analyzer-specific stays
in `engine/utils.py` or one of the phase scripts.

### `core.paths` — [engine/core/paths.py](../engine/core/paths.py)

- `ProjectPaths` frozen dataclass with `project_root`, `src_dir`, `config_dir`,
  `config_path`, `config_local_path`, `model_dir`, `output_dir`, `logs_dir`,
  `cache_dir`.
- `paths()` returns a cached singleton; `set_project_root(path)` clears it.
- Auto-detects root by walking two parents up from `paths.py` (so the snapshot
  works no matter where you launch from).

### `core.config` — [engine/core/config.py](../engine/core/config.py)

- `_strip_json_comments` / `_strip_trailing_commas` — JSONC parser.
- `load_config(project_root)` — merges `engine/config/config.json` + `config.local.json`. **If `ANALYZER_CONFIG`
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
  `layer.path` to each component path inside the layer's groups. Keys BOTH levels by
  layer-qualified id (`Layer1.Support` → `Layer1.Math`), so two layers reusing a name are
  two entries, not one overwriting the other.
- **Layer-qualified identity** (dated entry 2026-09-06): `LAYER_SEP = "."`,
  `make_qualified_id(layer, name)`, `split_qualified_id(id)`, `qualified_layer(id)`,
  `display_name(id)`. All re-exported through `utils`. The id is what KEYS everything
  (component, unit, function, global, output dir, diagram filename); `display_name` is what
  the document SHOWS. Applied always when the config has `layers`, never for a legacy
  `layer`/`modulesGroups` config. Key arity is unchanged — only the component string gained
  a prefix.
- `resolve_group_id(groups, requested)` / `resolve_component_id(components, requested)` →
  `(resolved_or_None, candidates)`. Accepts the qualified id, or a bare name while exactly
  one layer has it; two candidates means AMBIGUOUS and the caller must refuse
  (`ambiguous_group_message` writes the message). Used by `run.py`, `group_planner` and
  `run_views`.
- `validate_layer_names(cfg)` → one message per name problem in `layers`, `[]` when clean.
  **Cross-layer duplicate names are NOT reported** — they are legal. Reported: the same name
  twice inside ONE layer, a path claimed by two components or nested inside another's, two
  layer names that collapse to one identifier, and a name containing `LAYER_SEP`. `run.py`
  exits 2 on any message before Phase 1; `tools/new_project.py` and
  `api/services/pipeline_runner` refuse before writing anything. Comparison uses
  `name_ident(name)` (`strip().replace(" ", "-").casefold()`).
- `default_clang_macro_defs()` — returns the `-D` macro list shared by
  Phase 1 and the flowchart engine's per-function re-parser.

### `core.model_io` — [engine/core/model_io.py](../engine/core/model_io.py)

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

### `core.logging_setup` — [engine/core/logging_setup.py](../engine/core/logging_setup.py)

- `configure_logging(*, project_root, quiet, verbose, log_dir)` installs:
  - **stderr** handler at INFO (or DEBUG/WARNING based on flags + `LOG_LEVEL`)
  - **daily file** handler at DEBUG → `<project_root>/logs/run_YYYYMMDD.log`
- Idempotent; later calls just adjust the stderr level.
- `get_logger(name)` auto-configures with defaults if no caller has yet.
- `set_level(level)` re-tunes stderr after the fact.
- Registers an `atexit` hook that dumps `llm_core.tokens.format_report()` so
  every subprocess records its own LLM token usage to the log file.

### `core.progress` — [engine/core/progress.py](../engine/core/progress.py)

`ProgressReporter(component, *, total, logger, log_every)` with `start()`,
`step(label=...)`, `done(summary=...)`, and a context-manager API. On a TTY
it uses `\r` for live updates; when piped it falls back to periodic INFO log
lines (every ~10% by default). Quiet mode suppresses the live line entirely
but still logs the final summary.

### `core.orchestration` — [engine/core/orchestration.py](../engine/core/orchestration.py)

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

### `core.group_planner` — [engine/core/group_planner.py](../engine/core/group_planner.py)

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

### `core.__init__` — [engine/core/__init__.py](../engine/core/__init__.py)

Re-exports every public symbol so call sites can write
`from core import PhaseRunner, plan_runs, FUNCTIONS, ...`.

---

## 8. `engine/llm_core/` — unified LLM client + token-budget toolkit

Post-version3, `engine/llm_core/` is a full toolkit: one HTTP client plus a set of
composable helpers (counter, budget, context builder, repo map, few-shot,
cache, structured output, review). Everything LLM-related in the project
flows through this layer.

```
engine/llm_core/
  client.py              LlmClient + from_config — single HTTP client (ollama + openai)
  headers.py             build_openai_headers + resolve_api_key
  think.py               strip_think_section
  tokens.py              per-process LLM call metrics — latency/throttle/outcome/tokens,
                         stage() attribution, format_report, write_json, merge_dir
  token_counter.py       TokenCounter (tiktoken wrapper + char/3.5 fallback) — version3
  budget.py              ContextBudget + TASK_RATIOS + resolve_max_tokens      — version3
  context_builder.py     ContextBuilder — callee/caller/types degradation ladder — version3
  repo_map.py            RepoMap — scoped repo signature view (4 tiers)          — version3
  few_shot.py            FewShotPool — keyword-ranked example selection          — version3
  cache.py               EntityCache — composite-hash cache, `llm_description_cache` table (doc 10 step 10)
  structured_output.py   extract_and_validate + parse_label_response             — version3
  review.py              self_review + ensemble_generate                        — version3
```

Public API re-exported from `llm_core.__init__`:
`LlmClient`, `from_config`, `strip_think_section`, `tokens`,
`TokenCounter`, `get_counter`, `ContextBudget`, `resolve_max_tokens`,
`extract_and_validate`, `parse_label_response`, `self_review`,
`ensemble_generate`.

### `llm_core.client.LlmClient` — [engine/llm_core/client.py](../engine/llm_core/client.py)

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
- Every OpenAI call is followed by `time.sleep(llm.rateLimitSeconds)` even on
  failure, because the corporate gateway throttles ~1 req/3s. Default `3.0`
  (`_OPENAI_RATE_LIMIT_SEC`); `0` disables the pause entirely. Ollama never
  sleeps. Cost: the engine is single-threaded, so this is ~1.5 batches +
  ~0.25 coherence calls per function ≈ **5.4 s/function** on a flowchart run.

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

### `llm_core.cache.EntityCache` (doc 10 step 10 — now database-backed)

Per-entity cache with composite hash keys, stored in the **`llm_description_cache`
table** (migration `0005`). It was one JSON file per entity under
`.flowchart_cache/`; on the container deployment that dies with the container and
is invisible to other nodes, giving N nodes a ~1/N hit rate.

```python
EntityCache(project_id, namespace, cache_version)   # namespace: llm_descriptions | aux_descriptions
  .get(entity_id, content_hash) -> Optional[str]
  .put(entity_id, content_hash, value, metadata=None)   # buffered
  .flush()                                              # call at the end of a pass
  .stats() -> "N hits, M misses, W writes, X% hit rate [db|in-memory only]"
```

**Scoped per project, not per version** — the hit that matters is the next version
finding a description an earlier one paid for. The whole scope loads in **one
query** at construction and `get()` is a dict lookup; per-entity SELECTs would be
~20k round trips on a 20k-function project. Writes buffer and flush with
`ON CONFLICT DO NOTHING`.

`cache_version` is part of the unique key, so bumping `llm.cacheVersion`
invalidates by construction and leaves old rows unreferenced.

With no database it degrades to an **in-process memo** — still dedupes within a
run (several call sites ask for the same struct during one export), just does not
survive it. `put()` never raises; a cache failure costs LLM calls, never output.

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

## 9. `engine/utils.py` — analyzer-specific helpers

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
| `get_range_for_type(type_str)` | Map a **known primitive** to a range; anything else `NA`. **Case-sensitive** (2026-08-03) — lowercasing made `Size_t` match `size_t`; `size_t` is matched by exact name, not substring |
| `get_range(type_str, data_dictionary)` | Range lookup with typedef recursion (depth 10). **`"NA"` on a dd entry means "unknown", not an answer** — see below |

Note: `init_component_mapping` runs at import time using the on-disk config, so
`make_*_key` works immediately. `parser.py` builds its own folder list from
the same config via `get_flat_groups` (kept separate to avoid the analyzer's
import order constraints).

### `get_range` resolution order (2026-08-03)

Ranges reaching the interface tables are resolved **lazily here**, not in Phase 1 —
`interface_tables` is the only caller (parameters, `returnRange`, globals). Phase 1
*bakes* a `range` into typedef/struct-field entries with `get_range_for_type()`, which
never sees the dictionary, so an alias of a project type is stored as `"NA"` even when
the underlying type has a range (e.g. one supplied later by the external CSV).

Order, for the direct key hit (`dd[base]` / `dd[base.lower()]`):
1. `range` present and ≠ `"NA"` → return it.
2. `kind == "typedef"`, `underlyingType` set **and ≠ the entry's own name** → recurse
   (depth 10); return the result only if it is not `"NA"`.
3. Otherwise return the entry's own `"NA"` — **do not** fall through to the
   qualifiedName scan.

The qualifiedName scan (reached only when no key matches) applies the same precedence,
and first-match still wins.

Two traps this encodes:
- **Self-referential aliases.** `_maybe_add_typedef_for_struct` stores
  `underlyingType == the type's own name` (`UINT8 → UINT8`), so recursion needs the
  `underlying != base` guard or it burns the depth budget doing O(n) scans.
- **qualifiedName collisions.** The parser emits both `Name` and
  `typedef@Name:file:line` for the same type (Sample: `GG`×4, `Size_t`, `Rect`,
  `Widget_t`, `Mode_t`, `DB_TYPE`, `PUBLIC`). Letting a `"NA"` direct hit fall through
  to the scan lets a *sibling* answer — and the sibling's baked range can be garbage:
  `get_range_for_type` matches `"size_t" in base` on the lowercased name, so the struct
  `Size_t {int width; int height;}` has a sibling carrying `0-0xFFFFFFFFFFFFFFFF`.
  That substring rule is still in `get_range_for_type` (baked into parser output, so
  fixing it needs a re-parse) — see `docs/BACKLOG.md`.

Tests: `tests/unit/test_utils.py::TestGetRangeBakedNA`,
`tests/unit/test_data_dictionary_csv.py`.

---

