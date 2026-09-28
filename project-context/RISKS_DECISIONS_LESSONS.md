# Known risks, key design decisions, past mistakes

> **Project context — one part of it.** Start at [PROJECT_CONTEXT.md](../PROJECT_CONTEXT.md),
> the index: current state, how to read the context, every file. The sections below moved here
> from the single-file context on 2026-09-28, unchanged except link paths, and keep their numbers —
> "PROJECT_CONTEXT §N" still finds them. Written over time: where a section and a newer dated
> entry in [history/](history/) disagree, the newer entry and the code win.

**Sections:** [16. Known risks / technical debt](#16-known-risks--technical-debt) · [17. Key design decisions](#17-key-design-decisions) · [18. Past mistakes / lessons learned](#18-past-mistakes--lessons-learned)

## 16. Known risks / technical debt

### Risk 1 — `parser.is_project_file()` uses `startswith` for path containment

```python
abs_path = os.path.normcase(os.path.abspath(file_path))
abs_base = os.path.normcase(os.path.abspath(MODULE_BASE_PATH))
if not abs_path.startswith(abs_base):
    return False
```

Allows `C:\foo` to match `C:\foobar`. The correct helper exists at
[utils.path_is_under](../engine/utils.py); migrating `is_project_file` to use it
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
[engine/flowchart/ast_engine/cfg_builder.py](../engine/flowchart/ast_engine/cfg_builder.py),
re-run `python engine/flowchart/tests/diagnose_assert.py`.

### Risk 5 — header inline function appears in interface table but gets no flowchart — RESOLVED 2026-07-31 (first attempt reverted; see "Why the first fix was reverted")

**Symptom:** a public inline function defined in a header (e.g. `Foo.h`) showed an interface row /
section header with a description but **no flowchart figure** ("header but no table"). Unit keys
strip the extension ([utils.py `_path_to_component_unit`](../engine/utils.py#L238)) so `Foo.h`+`Foo.cpp`
collapse into one unit and the interface table renders the header fn's row
([interface_tables.py:43](../engine/views/interface_tables.py#L43)), but the flowchart engine
**dropped every header-defined function** via a blanket file-extension filter (`_is_header_file`).

**Root cause + fix (flowchart engine only):** the drop keyed on the wrong thing — file extension.
The correct criterion is "has a body." `functions.json` only ever holds **definitions** (parser's
`visit_definitions` is guarded by `cursor.is_definition()`, so the `declarationOnly` branch at
[parser.py:873](../engine/parser.py#L873) is **dead code — never emitted**; verified 0 across all
functions), *plus* one no-body category: `syntheticFromVarDecl` (var-decls parsed as pseudo-functions,
e.g. a macro-obscured `UNIT _f(arg);`). Fix: `FunctionEntry` gained `synthetic_from_var_decl` (plumbed
through `pkb/builder.py` build/to_dict/from_dict); `flowchart_engine.run()` now skips only
`synthetic_from_var_decl` entries and processes everything else — **including header-defined inline
functions**, which libclang parses fine as their own TUs (3.2 already parses headers as TUs). Verified:
`signalGain` (`SignalInline.h`) now emits a real CFG/DOT; `_SOME_FUNCTION` (synthetic) is cleanly
skipped (previously an empty/error entry); `.cpp` inline fns unchanged (the old filter never touched
them). **Follow-up (engine-dev):** the dead `declarationOnly` branch in `parser.py` can be removed or
its guard relaxed — out of the flowchart engine's scope.

#### Why the first fix was reverted — output-filename collision (2026-07-30 → re-fixed 2026-07-31)

`fa42e6b` (drop the header filter) was reverted by `1a59190` because it made **functions declared
`extern` in a header and defined in the `.cpp` disappear** from the document. Root cause is NOT the
header filter — it is [output/writer.py:44-45](../engine/flowchart/output/writer.py#L44-L45), which names
each output `Path(source_file).stem + ".json"` with the **extension stripped**, while `run()` grouped
by full path. `Foo.h` and `Foo.cpp` therefore became two `FileResult`s that both wrote `Foo.json`, and
`sorted(by_file.items())` puts `.h` last (`'c' < 'h'`) → **the header write clobbered every `.cpp`
flowchart in that unit**. Invisible while headers were filtered out; guaranteed the moment they weren't.

**Fix (2026-07-31, flowchart engine only):** keep the `synthetic_from_var_decl` filter from `fa42e6b`
*and* group by **output stem** rather than path, so `Foo.h` + `Foo.cpp` merge into one `FileResult` →
one `Foo.json` holding both. `FileResult.source_file` = first non-header path in the group (`.cpp`
still named in `_summary.json`); entries sorted by `(file, line)` for determinism. Stem grouping also
matches the rest of the pipeline, which already collapses `Foo.h`+`Foo.cpp` into one unit
([utils.py `_path_to_component_unit`](../engine/utils.py#L238)) and whose incremental path
([views/flowcharts.py `_apply_incremental_plan`](../engine/views/flowcharts.py#L150)) already assumes one
JSON per stem. Side benefit: two same-stem `.cpp`s in different components now merge instead of one
silently overwriting the other.

#### Follow-up — "Could not resolve cursor" for header-defined functions (2026-08-02)

Once headers stopped being skipped, real projects surfaced a second failure:
`Could not resolve cursor for '<fn>' in <path>.h:<line>`. Cause: `_process_function` parses the
function's **own file** as the TU ([flowchart_engine.py:270-271](../engine/flowchart/flowchart_engine.py#L270-L271)),
so a header that is **not self-contained** (macros/types supplied by an include the `.cpp` pulls in
first — `#include "cfg.h"` then `#include "foo.h"`) is a syntax error when parsed alone and yields no
cursor. Phase 1 is immune because it captures the function from the **`.cpp` TU**; headers-as-TUs is
only its additive fallback.

**Fix:** on resolution failure, retry inside a TU that **includes** the header. Phase 1 already writes
`model/tu_includes.json` (TU → included project headers); `_build_including_tus` reverses it (same-stem
`.cpp` first, then sorted — deterministic), `views/flowcharts.py` passes `--tu-includes`, and
`EngineConfig.tu_includes_json_path` carries it. `abs_path` stays the header — only the TU changes,
since the cursor still reports the header as its location. Purely additive: self-contained headers
still resolve on the first try. Failure messages now append the real clang diagnostics
(`_parse_error_hint`). Repro'd + verified on a `SIG_API`/`SIG_VAL`-macro header fixture: before =
`✗ 1` with the cursor error, after = `Resolved 'clampSignal' via including TU …/SignalDriver.cpp`,
`✓ 5 ✗ 0`, CFG identical to the self-contained case.

**A/B verified** on a two-function fixture (`Foo.h` = `extern int fooMain(int);` + inline `fooInline`;
`Foo.cpp` = `fooMain`): path-grouping wrote `Foo.json` twice and left only `fooInline`; stem-grouping
writes once with **both** `fooMain` and `fooInline`. Full sample run: 124 ✓ / 1 ✗ across 21 units with
`SignalInline.json` (`signalGain`, header-only) now emitted. `pytest --skip-pipeline`: 631 passed, 0 failed.

### Risk 6 — duplicate interfaceId when a unit spans .h and .cpp — RESOLVED 2026-08-03

**Symptom:** two different public interfaces in one unit carry the **same** interface ID, e.g.
`IF_LAYER1_SIGNAL_SIGNAL_01` on both `normalize` (`Signal.cpp`) and `clampSignal` (`Signal.h`).
Duplicate IDs break traceability in an ASPICE deliverable.

**Root cause:** mismatch between what the ID *encodes* and what the counter is *keyed by*. The ID
string carries the **unit** — `make_unit_key(rel)` strips the extension, so `Foo.h` and `Foo.cpp`
collapse to one unit ([model_deriver.py:385-387](../engine/model_deriver.py#L385-L387)) — but
`_build_interface_index` bucketed **by file** and restarted `idx = 1` for each, so both halves of a
`.h`+`.cpp` unit numbered from 01.

**Pre-existing, not caused by the header-flowchart work** (Risk 5): the pristine sample model already
carried one — `PIF_LAYER1_FULL_READWRITE_01` shared by `writeGlobal` (`ReadWrite.cpp`) and
`g_hdrGlobal` (`ReadWrite.h`). Header-defined *functions* simply never reached the document before, so
the collision was rare; once they did, it became routine.

**Fix:** bucket by unit, not by file. `_unit_of(data, base_path)` derives the same `component|unit`
key the ID uses; `_iface_sort_key` orders within a bucket by `(file, line)` since a bucket can now
span two files. Buckets renamed `*_by_file` → `*_by_unit`, `all_files` → `all_units`. `.cpp` sorts
before `.h` (`'c' < 'h'`), so **existing `.cpp` numbering is preserved and header entries append
after it** — chosen deliberately to minimise churn on IDs that may already be in delivered documents.

**Blast radius measured, not assumed:** re-deriving the sample changed **1 interfaceId out of 139** —
`g_hdrGlobal` `PIF_..._01` → `PIF_..._06`, exactly the colliding entity. Every other ID byte-identical
(`writeGlobal` keeps `_01`). Duplicates 1 → 0. A unit living in one file numbers exactly as before,
because bucketing by unit then equals bucketing by file and the sort collapses to `line`.

**Follow-on — table row ORDER (same root shape, different file):** the interface table sorted rows by
source **line** ([interface_tables.py](../engine/views/interface_tables.py)) while numbering sorts by
`(file, line)`. Those agree only while a unit's interfaces live in ONE file, so once a unit spans
`.h`+`.cpp` the table rendered IDs shuffled — reproduced as `02 clampSignal / 01 normalize / 03 SIG_VAL`
when the header function sits at a lower line than the `.cpp` ones. Verified this was NOT a
pre-existing defect: the pre-change artifact had 0 of 3 unit tables out of order. **Fix:** sort rows by
the interface ID's trailing index (`_iface_order`, numeric so `_99` precedes `_100`), rather than
re-deriving the numbering's sort key in a second place — the table now tracks the numbering by
construction. Also fixes the per-function section order (`2.1.1.3`, `2.1.1.4`, …), which follows the
same list.

**Still open — cross-unit collisions (latent, NOT fixed):** `_id_seg` keeps only letters, so units whose
names differ solely by digits/underscores collapse to one ID stem (`Signal2` → `SIGNAL`, `Timer_1` →
`TIMER`) and each restarts at 01 — e.g. `IF_LAYER1_PLATFORM_UART_01` issued in both `Uart1` and `Uart2`.
The layer segment is immune (`_id_seg_layer` keeps digits); group + unit segments were never given the
same treatment. Sample project is clean (0 shared stems), but digit-suffixed unit names are everyday
firmware naming. Fix = keep digits in the unit/group segments; deferred because it renames IDs for
every unit with a digit in its name (far larger churn than the 1-of-139 above, and IDs may already be
in delivered documents).

**Regression tests:** `tests/unit/test_model_deriver.py::TestInterfaceIndexUnitKeyed` — uniqueness
across `.h`+`.cpp`, header-numbered-after-cpp, header-global vs cpp-function collision (the original
defect), and single-file numbering unchanged (the churn guard). Verified meaningful: 3 of the 4 fail
against the pre-fix code; the churn guard passes on both by design.

### Pre-V1 correctness batch (targets V1; numbered 3.1–3.19 internally — status in git/PR history + the `> Updated:` log above)

Of the ten findings from pre-V1 review (2026-07-10), **3.1–3.7 are done and
removed** (roots + interface direction/consistency + export; see WORK STATUS
block at top). Remaining open items below.

**Flowchart rendering (§13):**
- **3.8 — if/else condition depiction.** Conditional branches are not rendered
  correctly in the flowchart.
- **3.9 — overlapping edges.** Flowchart edges overlap — layout / ELK spacing.

**Behaviour:**
- **3.10 — dynamic-behaviour issue.** Under-specified; needs a concrete repro /
  definition before it can be scoped (flagged in the roadmap open questions).

### Risk 7 — a visibility macro leaks across an access label in `_detect_visibility`

`_detect_visibility` (parser.py) runs BEFORE the C++ access specifier and wins
wherever it finds a marking. It scans up to 5 lines back and stops at a line
ending in `;`, `}` or `{` — but an access label ends in `:`, so it is not a
terminator. Inside a class, a macro-marked declaration therefore marks the
declarations that follow it under a LATER label:

```cpp
public:
    PUBLIC void macroPub();
private:
    void afterMacro();   // text-scan returns "public"; clang access never consulted
```

`afterMacro` is C++-private but ships as an interface row. Same neighbour-
adoption bug the existing comment in `_detect_visibility` fixed for statement
terminators; access labels were missed. **Latent, not live** — it needs a
macro-marked declaration within 5 lines inside the same class, and the client
project does not use `PRIVATE`/`PUBLIC`/`PROTECTED` macros inside classes.
Repeated or interleaved access labels on their own are handled correctly:
access is read from `cursor.access_specifier` (clang's effective access) and
no code text-parses the labels.

Fix when it becomes live: break the scan on an access label too, with an
explicit `^(public|private|protected)\s*:` match rather than adding `":"` to
the `endswith` tuple, so `case X:` and goto labels do not break the multi-line
`PRIVATE UNIT __OVLYINIT` form the scan exists for.

### Risk 8 — storage class

**FIXED 2026-09-24 by S3-7, with no storage-class clause.** A file-scope `static` (or `const`,
internal linkage in C++) used to record as `public` and earn an interface row. Since S3-7 a global needs a
reader or writer in another unit, and nothing outside its file can name an internal-linkage variable, so it
never qualifies (`Access/NestedTypes.cpp` `s_fileLocal` is now private). The one way through: a `static`
or `const` defined in a HEADER included by several units is one model entry keyed to that header, so its
readers in the including units count as outside users and publish it under the header's unit — which, for
an orphan header, has no section to render it in.

**FIXED — `UNION_DECL` and `TYPE_ALIAS_DECL`** (`147c4cd`, client answer Q16). They used to
reach the data dictionary never: `visit_type_definitions` dispatched on STRUCT_DECL /
CLASS_DECL / ENUM_DECL / TYPEDEF_DECL only. A union now joins the struct/class branch, a
`using` alias records as a typedef, and both have fixtures in `Access/NestedTypes.h`.

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
… as group names, then `core`, `support`, `tests`. The current `config.defaults.json`
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

