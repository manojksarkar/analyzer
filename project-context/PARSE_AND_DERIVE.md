# Phases 1 and 2 — parse and derive

> **Project context — one part of it.** Start at [PROJECT_CONTEXT.md](../PROJECT_CONTEXT.md),
> the index: current state, how to read the context, every file. The sections below moved here
> from the single-file context on 2026-09-28, unchanged except link paths, and keep their numbers —
> "PROJECT_CONTEXT §N" still finds them. Written over time: where a section and a newer dated
> entry in [history/](history/) disagree, the newer entry and the code win.

**Sections:** [10. Phase 1 — `engine/parser.py`](#10-phase-1--engineparserpy) · [11. Phase 2 — `engine/model_deriver.py`](#11-phase-2--enginemodel_deriverpy)

## 10. Phase 1 — `engine/parser.py`

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
  - **User macros** (`--macros <path>` global, `--macros-layer <layer> <path>` per
    layer, or `clang.macrosFile` / `clang.macrosByLayer` in config) — read by
    `core/macro_input.py` from CSV or any accepted JSON shape, then written to
    `model/clang_macros.json` **scope-keyed** (`{"*": [...], "Layer1": [...]}`) so
    `flowcharts.py` applies the same flags to the Phase 3 re-parser. Args are
    resolved **per TU** by `clang_args_for(path)` (file → component → layer), not
    baked into the global `CLANG_ARGS`. Sample: `engine/config/macros.csv`
    (`VOID,void`).

### Visibility detection (`_detect_visibility`, `_function_visibility`, `_global_visibility`)

Two sources, annotation first. **Phase 1 is the only place visibility is recorded**, and so the
only place this policy lives.

1. `_detect_visibility` scans **backwards up to 5 source lines** from a declaration line for a
   first token of `PRIVATE`, `PUBLIC`, or `PROTECTED`, and maps it through
   `_MACRO_TO_VISIBILITY`. Required because the macros are expanded to nothing by `-DPRIVATE=`
   and Clang doesn't surface them.
2. With no macro, `_function_visibility` gives a **method** its C++ access specifier and
   `_global_visibility` gives a **static data member** its own, both through
   `_ACCESS_TO_VISIBILITY`. Read off the visited cursor — Clang reports access on an out-of-line
   definition (`int Foo::bar()` in the .cpp), so no `canonical` resolution is needed. A free
   function has no access specifier and falls through to unmarked.

**Recorded values are `public` and `private`, and nothing else.** An unmarked declaration records as
`public` via `_as_recorded`; `"default"` is only the lookup's internal sentinel. Both maps send
`PROTECTED` / `protected:` to `"private"`: a protected item is reachable from another unit only
through inheritance, and no later phase distinguishes it from private. Collapsing here is what
lets `_fn_is_private`, the five view filters and the two exporter filters all test one string.
Lossy by design — see the 2026-09-20 entry.

Clang reports the **effective** access, so an unlabelled `class` member is `private` and an
unlabelled `struct` member `public`. Both are taken at face value: private-by-default binds
another unit exactly as a written label does.

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
- `TYPEDEF_DECL` with underlying type (`_typedef_underlying`) and range lookup

**`_typedef_underlying(cursor)` (2026-08-03).** `cursor.type` on a `TYPEDEF_DECL` is
the typedef type *itself*, so its spelling is the alias's own name — never what it
aliases. Reading it (the pre-2026-08-03 behaviour) made **every** typedef
self-referential with `range: "NA"`, so every typedef'd parameter printed `NA` in the
Data Range column. Now uses `cursor.underlying_typedef_type`, then strips elaborated
keywords (`struct `/`enum `/`union `/`class `) via `_ELABORATED_RE` so the value works
as a dataDictionary key:

| source | before | after |
|---|---|---|
| `typedef unsigned char UINT8;` | `UINT8` | `unsigned char` |
| `typedef int UNIT;` | `UNIT` | `int` |
| `typedef enum {…} Mode_t;` | `Mode_t` | `Mode_t` (from `enum Mode_t`) |
| `typedef struct {…} Widget_t;` | `Widget_t` | `Widget_t` (from `struct Widget_t`) |

The anonymous enum/struct forms stay self-referential **on purpose** — the unit header
table looks `underlyingType` up in the dictionary to print the enumerator list
(`docx_exporter._build_unit_header_table`, `api/services/doc_render.py:281`), and an
elaborated `"enum Mode_t"` would miss.

`_maybe_add_typedef_for_struct` stores `range: "NA"` rather than
`get_range_for_type(qn)` — its `underlyingType` is the type's own *name*, so deriving a
range from it reads a range out of a type name (`"size_t" in "Size_t"` stamped
`0-0xFFFFFFFFFFFFFFFF` on a `{int width; int height;}` struct).

### Where a data range comes from (precedence, 2026-08-03; layer scoping 2026-08-18)

**Scope is resolved before precedence.** `get_range(type, dd, layer)` first decides *which
entries may answer at all*: the layer's own (`name@<layer>`, or a bare entry stamped with
that layer) and the global tier (`layer: None` — builtins, `PRIMITIVES`, the project-wide
CSV). **Another layer's entry is never eligible**, at any of the three lookup paths. Only
among the eligible entries does the order below apply. `layer=None` disables the filter
entirely, which is what keeps every layer-unaware caller behaving as before.

Highest wins. The order is enforced by *when* each source runs in Phase 1, not by
branching logic:

1. **External CSV** — merged last (`_merge_dd_rows`), so it overrides everything *within its
   scope*. This is why ranges must NOT be frozen onto each parameter in `functions.json`:
   parameters are collected before the merge, and a baked parameter range would make
   `--data-dictionary` unable to override anything.
2. **libclang** — `_range_from_clang_type(ctype)`: `get_canonical()` walks the typedef
   chain to the real builtin, `get_size()` gives its width **for the parsed target**
   (`long` = 4 bytes on Windows, 8 on Linux — the table below cannot express that).
   `VOID` for void, `0-1` for bool, `NA` for structs/enums/pointers/floats.
   `_register_builtin_range(ctype)` runs for every parameter / return type / global /
   field and records the range under the type's **canonical** spelling
   (`unsigned char`, `long`) — never the written spelling, which would let a `UINT8`
   parameter overwrite the `UINT8` *typedef* entry with a primitive one and lose the
   location the unit header table needs. It also refuses to shadow a non-primitive.
3. **`PRIMITIVES` table** — seeded with `setdefault` (not assignment), so it fills gaps
   without overwriting a measured value.
4. **`get_range_for_type(name)`** — last resort for CSV-authored or unparsed types.
5. `NA`.

Consequence: the **dataDictionary is the single registry**; views keep resolving by type
name (`get_range(p["type"], dd)`) and need no libclang, no schema change, and no
`functions.json` churn.

**Coverage log.** `interface_tables.run()` logs one line per group —
`data ranges: 64/65 resolved, 1 NA (int[6] x1)` — via the pure helpers
`_range_coverage` / `_format_range_coverage`. Deliberately a log, **not** a per-entry
`rangeSource` field: nothing renders `directionReason` into the DOCX either, so a
provenance field would ride on every row and churn the snapshot for an audit aid with no
reader. To trace one type, see the precedence above or query `model/dataDictionary.json`
directly.

Tests: `tests/unit/test_typedef_underlying.py`.
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

**Phase 2 direction precedence (roadmap 3.17).** The finalize loop in `model_deriver`
(after `_propagate_global_access`) decides each function's direction by the first rule
that applies — the parser's `build_metadata` value above is only the rule-3 fallback:
1. **Name match.** Tokenize the function's short name into words (camelCase + snake_case
   aware, via `_name_words`/`_WORD_RE`). If a whole word equals `set` → **In** (tested
   first: write intent dominates, mirroring the both-read-and-write → In fallback); else
   if a whole word equals `get` → **Out**. Whole-word matching catches `SetX`/`setX`/
   `Module_SetX`/`coreSetResult` (infix camelCase) while excluding `Setup`/`Settings`/
   `Setter`/`Reset`/`offset`/`target`. Known edge: predicate names like `isSet` match.
2. **Non-void return** (`returnType` present and ≠ `"void"`; `void *` counts as a value)
   → **Out** (data flows out through the return value).
3. **Global-access fallback (the 3.4 rule).** Writes a global directly or transitively
   → **In**; else reads one → **Out**; else **Out** (pure). Reuses
   `writesGlobalIdsTransitive`/`readsGlobalIdsTransitive`.

**`directionReason` (audit trail).** Alongside `direction`, the same loop writes a
human-readable `directionReason` on every function and global so the decision is
verifiable in the interface tables (which surface `f["directionReason"]` as the `reason`
field). Forms:
- `In: function name '<n>' contains 'Set' (writes/updates state).` — rule 1 set.
- `Out: function name '<n>' contains 'Get' (reads/returns state).` — rule 1 get.
- `Out: returns a value (<type>).` — rule 2.
- `In: writes global(s) <names> directly.` — rule 3, direct write.
- `In: writes global(s) transitively: <g> (via <callee(s)>); …` — rule 3, transitive-only
  write; names the direct callee(s) that actually write each global, so the chain
  is auditable.
- `Out: reads global(s) <names> but writes none.` — rule 3.
- `Out: accesses no globals (reads none, writes none).` — rule 3, pure function.
- Globals: `In/Out: global variables are bidirectional interfaces.`

### Final keying (`build_metadata` + `utils.make_function_key`)

Final model key: `component|unit|qualifiedName|paramTypes`.

- `component` from `get_component_name(file_path, base_path)` → `_resolve_component_from_rel`.
- `unit` from filename without extension.
- `qualifiedName` includes namespace + class.
- `paramTypes` is the comma-joined list of normalised parameter type strings.

> **Never change `get_qualified_name`.** Every fid is built from it, so any change re-keys
> the whole model — breaking interface IDs, the fid-keyed hidden-function rows in
> `api/db/json_db.py`, and every incremental baseline. To surface more of a symbol's scope,
> add a separate field (see `className` below), never widen `qualifiedName`.

### `className` — class scope for display (2026-08-08)

Interface tables built every Name cell with `short_name()`, which keeps only the last `::`
segment. `AddOperation::apply` and `MultiplyOperation::apply` — two real methods in unit
`Cross|Dispatch` of SampleCppProject — both rendered as `apply`, indistinguishable.

The class *is* in `qualifiedName`, but that string cannot be split back into namespace vs
class parts (`pos::QosEventManager::_RateLimit` — is `pos` a namespace or an outer class?).
So the class is captured separately at parse time, where the cursor's `semantic_parent`
kinds are still known:

- `parser.get_class_scope(cursor)` — walks `semantic_parent` keeping only `CLASS_DECL`,
  `STRUCT_DECL`, `CLASS_TEMPLATE` and its partial specialization. Namespaces and
  empty-spelling parents are dropped. Nested classes join as `Outer::Inner`; `""` for free
  functions. Stored as `className` on functions and globals.
- `utils.scoped_name(qualifiedName, className)` — the display form, `ClassName::foo`.
  Falls back to `short_name()` when `className` is absent, so models parsed before this
  existed render as they did rather than half-qualified.

**`CLASS_TEMPLATE` is matched here but not by `get_qualified_name`** — a template class's
method therefore has a *bare* `qualifiedName` (`run`, not `Foo::run`), with the class
already lost upstream. `get_class_scope` recovers it, so the rendered name is still
`Foo::run`. Template arguments are not in the spelling, so `Foo<int>::run` and
`Foo<char>::run` both read `Foo::run`; mangled names still keep them apart in the model.

**Where it shows:** interface-table cells, DOCX per-function headings, flowchart table
titles + signatures, behaviour subheaders, and the API's `class_name` field for the hide
list. **Where it does not:** flowchart diagram nodes and behaviour message arrows stay
short — qualifying every arrow re-creates the label crowding the static diagram already
suffers from.

**`name` vs `interfaceName`.** Interface-table entries keep `name` **short**, because
downstream code uses it as a lookup key (flowchart stems, behaviour rows); `interfaceName`
carries the qualified display form. Don't collapse the two.

Three genuine short-name collisions were fixed alongside (wrong-function bugs, not
cosmetics): `doc_render` looked flowcharts up by short name although they are keyed by
`qualifiedName`, so **class methods silently got no flowchart in the web preview**;
behaviour Input/Output labels were resolved by first short-name match within a unit, so
both `apply` sections got the first one's labels; and hiding was matched against a
short-name-per-unit set, so hiding one `apply` suppressed every `apply` in the unit. All
three now key on the fid or `qualifiedName`. Behaviour rows carry `currentFunctionId` and
`currentFunctionDisplay` for this, with the old short-name path kept as a fallback for
artifacts written before those fields existed.

### Address-taken functions are public (2026-08-08)

`_fn_is_private` (`model_deriver.py`) equates "public" with "has a caller in another file".
A layered-firmware entry point reached only through a registration table has
`calledByIds == []`, so it was relabelled `visibility: "private"`, given a `PIF_` id, and
dropped from the interface table (`views/interface_tables.py`) and behaviour diagrams —
missing from the very ASPICE artifact it belongs in. The parser detected **no** address-of-
function usage at all.

**Rule: a function named in a file-scope array/struct initializer is public.**

```c
static const fp_t table[] = { fn1, fn2 };   // detection point
table[0]();                                 // the reason — NOT resolved
```

Which entry `table[0]()` reaches is statically unknowable and is deliberately not resolved
(the long-standing documented limitation stands). Membership in the table is sufficient
evidence on its own.

The rule is by **shape, not by file**: a file-scope initializer counts even when the table
sits in the same `.c` as the function — the canonical firmware pattern, which a cross-file
rule would have missed entirely. An **in-body** take (`p = &helper;`) is different: it
becomes an ordinary `call_graph` edge, so the existing cross-file caller rule applies
unchanged and a locally-used comparator stays private.

- `parser._walk_address_taken(cursor, on_hit, in_callee=False)` — a bare function name used
  as a value is a take; the same name in **callee position** is not. clang wraps a call's
  callee as `CALL_EXPR → UNEXPOSED_EXPR → DECL_REF_EXPR`, so the suppression flag propagates
  through `_CALLEE_WRAPPER_KINDS`. **If it ever stops propagating, every direct call reads
  as an address-take.** The exposure is the file-scope path (which ignores the file rule):
  `static int g = compute();` would wrongly publish `compute`. Guarded by a fixture and a
  test; only *resolved* `referenced` cursors count — never the spelling-match fallback used
  for calls, or any identifier sharing a function's name would qualify.
- Hooked in `visit_definitions` (both the file-scope `VAR_DECL` branch and each function
  body) rather than `visit_calls`, so the rule lives in one place and the call visitor's hot
  loop is untouched. `_get_var_init_value` only slices one declaration line, so a multi-line
  table is invisible to it — the AST walk is what actually sees these.
- `addressTakenByUnits` on the function = the registering unit **plus the units that read
  the table**. The consumers matter more: the table usually lives in the same unit as the
  function it publishes, and `_keep_unit` filters the own unit out of Source/Destination.
  Readers are matched by the global's **qualified name**, not var id, so an `extern`
  redeclaration in the consuming file (its own cursor, its own var id) still resolves.
- `_fn_is_private` gains a third escape clause, ranked **below** the explicit `PRIVATE`
  annotation — a source-level marking stays authoritative.
- Consumed by `interface_tables` (Source/Destination) and `unit_diagrams` (edge).
- Persisted to `model/address_taken.json` (`ADDRESS_TAKEN`, not in `ALL_MODEL_NAMES`) and
  replayed by `incremental/parse_merge._merge_address_taken` + `_apply_address_taken`,
  mirroring `override_pairs`. **Also added to `_PARSE_ARTIFACTS` (`incremental/engine.py`)
  and `_PARSE_SNAPSHOT_FILES` (`incremental/generate.py`)** — miss either and a narrowed
  parse silently demotes the function back to private, so the same source produces a
  different document run to run.

**Known consequence:** `_build_interface_index` numbers public and private separately, so
each function flipped private→public shifts `IF_*_NN` for the rest of its unit. Client docs
cite those IDs; a version diff will show the renumbering.

Fixture: `SampleCppProject/Layer1/Poly/OpsTable.cpp` (table + ops, deliberately plain
`static` not `PRIVATE`, plus an `opsSeed()` call-in-initializer false-positive guard) and
`OpsClient.cpp` (a different unit consuming the table via `extern`). Verified: `opsAdd`/
`opsSub` get `IF_` ids with Source/Destination `Cross/OpsClient`; `opsSeed` stays private.

### External data dictionary merge

After `_scan_defines()` and before writing `dataDictionary.json`, every source in `_dd_sources` is merged by `_merge_dd_rows(path, layer)` (`_merge_external_data_dictionary(path)` is the thin project-wide wrapper the tests drive). Sources in order — **config first, CLI second**, matching the macro block:

1. `layers.<L>.dataDictionary` — config, scoped to that layer
2. `--data-dictionary <path>` — CLI, project-wide
3. `--data-dictionary-layer <layer> <path>` — CLI, repeatable, scoped

**The project-wide dictionary is CLI-only — it has no config key, by design.** Every entry point already passes it as a flag: `run.py` from `--data-dictionary`, and the API/incremental path from `currentDataDictId` → `ws.datadict_path(...)` → `--data-dictionary` (`incremental/generate.py:214`). A config key would be a second, silent source for the same input. Config carries **per-layer** dictionaries only.

A layer's rows never touch another layer's entries: `_dd_target_key()` writes the bare name only when the slot is free or already that layer's, and `name@<layer>` when the global tier or another layer holds it. So "last wins" applies **within one scope only**. In the API/incremental path the project-wide CSV still arrives from `currentDataDictId` → `ws.datadict_path(...)`. Because the merge happens inside Phase 1, these are a **silent no-op with `--from-phase 2+` or `--use-model`**; changing a CSV requires a re-parse.

- Reads a CSV with columns: `Name, Kind, EntryName, Range, Comment`.
- **Top-level rows** (non-empty `Name`): copy existing auto-parsed entry, overwrite `kind`/`range`/`comment` from CSV, reset `enumerators`/`fields` list if the kind uses them.
- **Child rows** (empty `Name`, Kind=`enumerator` or `field`): carry forward the last non-empty `Name` as parent key and append `{name: EntryName, value/range, comment}` to the parent's list. Empty `Name` matches Excel merged-cell CSV exports.
- External entries win on conflict. New entries (not in parsed source) are added as-is.
- `location` and other auto-parsed fields are preserved on updated entries via `dict(existing)` copy.
- A range set here reaches the interface tables through `utils.get_range`, including via an alias whose own range was baked `"NA"` — see [§9 `get_range` resolution order](CORE_AND_LLM.md#get_range-resolution-order-2026-08-03). `fields[].range` inside a struct entry is **re-answered after every CSV** by `_reresolve_struct_field_ranges()` — it is baked during the parse from the canonical clang type, long before the CSV is read, so a `BOOL32` field kept `0-0xFFFFFFFF` while the CSV set the `BOOL32` *type* to `0-1`. Only two cases are re-answered: baked range is `"NA"`, or the field's base type was named by a CSV **visible to that entry's layer** (`_csv_top_level_names`, keyed by layer) — a measured width outranks anything name-derived. Derived spellings (`*`, `&`, `[`, `(`) are skipped unless CSV-named, so a `const char *` keeps `NA` instead of taking a signed-char range from its pointee. The lookup is layer-scoped (`get_range(ftype, dd, entry.layer)`).
- **Merge report** (`_format_csv_merge_report`): after the count, the parser prints which rows landed on a parsed type and which were **new, not found in source**. A typo'd or renamed type name is otherwise silently added as its own entry and looks identical to a successful override. Orphan child rows (no `Name` above them) are counted too, as are **duplicated Names** (last row wins, and the earlier entry's `enumerators`/`fields` are reset out from under it) and **rows dropped for an empty `Name` on a non-child `Kind`** — a merged-cell Excel export becomes a file of these, and they were previously counted in neither `merged` nor the orphan tally. matched-vs-new is decided against a snapshot taken **before** the row loop, so the second row of a duplicated Name cannot see what the first wrote and be mis-filed as a successful override. The function **returns** its lines as well as logging them, so the counting is assertable in tests. The line is prefixed `[<layer>]` for a layer-scoped source.
  ```
  data dictionary: merged 6 entries from data_dictionary.csv
      4 matched a parsed type: DB_TYPE, Status, Color, GG
      2 new, not found in source: MotorSpeed_t, Voltage_t
      1 name(s) appear on more than one row (last row wins): BOOL32
      3 row(s) dropped: empty Name on a row that is not Kind=enumerator/field
  ```

### Outputs

`metadata.json`, `functions.json`, `globalVariables.json`, `dataDictionary.json`
written to `model/` via `core.model_io.write_model_file`.

---

## 11. Phase 2 — `engine/model_deriver.py`

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

The unit key is `<componentId>|<basename without extension>`, where the component id carries
its layer (`Layer1.Core|Util`) — that is what keeps two layers' same-named components apart.
It carries **no directory**, so a
`.cpp` and its `.h` are one unit by design — and two files with the same stem in DIFFERENT
directories of one component fold into one unit too, carrying both files' functions and globals
but only the first's `path`/`fileName`. That is logged as a WARNING naming both files (compared
on the extension-stripped path, so the `.cpp`/`.h` pair is not flagged) and **not repaired**: the
key is the model's public identity, embedded in function/global IDs, snapshots and DB rows.
Dated entry 2026-09-04.

### `_build_interface_index` / `_enrich_interfaces`

Assigns a per-file sequential index and sets `interfaceId` on each function and global. Rules:

- **Functions are numbered first** (sorted by line), then **globals continue the same counter** — so globals always have higher indices than functions in the same file.
- **Public entries** use prefix `IF_` → `IF_<LAYER>_<GROUP>_<UNIT>_<NN>`
- **Private entries** use prefix `PIF_` → `PIF_<LAYER>_<GROUP>_<UNIT>_<NN>`, numbered in a separate independent sequence (so public IDs have no gaps).
- Private functions/globals are excluded from `output/interface_tables.json` (view filter unchanged).

`<LAYER>` is resolved per entry via `get_component_layer_name(config, component)` and processed by `_id_seg_layer` (keeps uppercase letters **and digits**, so "Layer1" → "LAYER1"). Falls back to `_id_seg(project_name)` for old-style configs without a `layers` key. `<GROUP>`, `<UNIT>` use the existing `_id_seg` (uppercase letters only). Example: `IF_LAYER1_FULL_READWRITE_01`.

**Function privacy rule (`_fn_is_private`)** — first match wins:
1. `visibility == "private"` → private. Covers `PRIVATE` and `PROTECTED` markings and `private:` /
   `protected:` methods alike, since phase 1 records all of them as `"private"`.
2. `addressTakenByUnits` non-empty → public. Reachable through a file-scope pointer table even
   though no call names it. This is *evidence*, not an annotation, which is why it survives.
3. Otherwise: private unless some `calledByIds` entry lives in a **different file**.

`visibility == "public"` used to short-circuit at rule 2 and guarantee a row. **Removed 2026-09-20** —
a marking may restrict, never promote, so an unmarked declaration and a `PUBLIC`-marked one are the same
thing here and only `private` decides anything. Consequences and the revert in the 2026-09-20 entry.

Rule 4 compares FILES, while a unit collapses `Foo.h` + `Foo.cpp` — so a helper defined inline in
the header and called from its own .cpp counts as externally called. Known, untouched.
Two helpers implement this:
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
   from [engine/llm_enrichment.py](../engine/llm_enrichment.py) — the version3
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

### Domain anchoring + description blocklist (task 3.14)

Every description prompt — `get_description`, `get_global_description`,
`get_unit_description`, `get_struct_description`, `get_rich_description` —
routes through **`_call_llm(prompt, config, *, system, kind)`** in
[engine/llm_enrichment.py](../engine/llm_enrichment.py) with `kind="description"`.
Two guards apply there, and **only** for `kind="description"` (behaviour-name
and other calls are untouched):

- **Domain anchoring (root-cause fix).** `load_domain_context(project_root,
  config)` reads a free-text brief from `config.llm.domainContextPath` (default
  `config/domain.txt`; `#` lines are comments) and `_call_llm` **appends it to
  the `system` message** — so the model is told the codebase's real domain and
  stops inventing unrelated vocabulary. The brief is memoized per path
  (`_get_domain_context`, project root resolved via `core.paths`) so the file is
  read once, not per description. It stacks on top of `get_rich_description`'s
  own `_RICH_DESCRIPTION_SYSTEM`. The shipped `config/domain.txt` describes the
  client's flash-storage firmware (FTL/HIL/FIL layers, explicitly *not*
  audio/video). Per-layer briefs are a future option.
- **Blocklist (deterministic backstop).** `_scrub_blocklist(text, config)`
  strips `config.llm.descriptionBlocklist` words (default `["audio", "video"]`)
  from the returned description — whole-word, case-insensitive, so identifiers
  like `videoDecoderId` are left intact; it also tidies the leftover
  whitespace/punctuation. Empty list = no-op. Stays on permanently even with
  anchoring, as a safety net.

Because both affect output, `llm.cacheVersion` was bumped **1→2** so
previously-cached descriptions regenerate. Offline runs are unaffected —
`_call_llm` returns `""` early when the client is `None`, before either guard.
Tests: [tests/unit/test_llm_scrub.py](../tests/unit/test_llm_scrub.py) (14 cases:
scrubber, loader, and prompt-only anchoring assertions).

### `_enrich_with_hierarchy_summaries`

Default-on (disabled by `--no-llm-summarize`). Uses the flowchart engine's
`HierarchySummarizer` (in `engine/flowchart/pkb/`) to produce a 4-level summary:

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

