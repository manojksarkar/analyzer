# UT Export Spec — unit-test JSON

Update this doc first when changing UT-export logic, then code + tests.
Companion: [SWE4_WIKI](SWE4_WIKI.md) (what the specs mean) · Plan: [engine/PLAN.md](../../engine/PLAN.md)

**Current understanding** of the target format and how each field is derived from the ArtiFex model.
Items marked **?** are not settled yet; see Open items.

---

## 1. The two files

### 1.1 The hierarchy file

Maps the test tree onto the source tree.

> **Superseded** by the 1.0 sample (`TestEnvironments`, no `Units` / `unit_id` / `Corresponding_cpp`):
> the generated shape is [REQ-UE-09](#req-ue-09--hierarchy-file--implemented) and
> [hierarchy.template.json](ut_templates/hierarchy.template.json). Kept for the record of the v0.1 guide.

```
<hierarchy file>
├── Macros
│   ├── HCoreMacros
│   ├── FCoreMacros
│   └── NCoreMacros
└── LayerMapping
    └── [Layer]                       e.g. "HIL"
        ├── searchdirectories: [dir1, dir2, ...]
        └── Sections
            └── [Section]
                ├── SectionID
                ├── SectionName
                └── Units
                    └── [Unit]
                        ├── unit_id
                        ├── Filename
                        ├── FilePath
                        ├── CoreType
                        ├── IsHeader
                        ├── Corresponding_cpp        (if IsHeader = true)
                        ├── Corresponding_cpp_path   (if IsHeader = true)
                        └── Testcases → [Testcase]   (see §2)
```

`Layer` is our **layer**. `Section` is **assumed** to be our **component** — unconfirmed, it could be
our group (a doubt, see the section row in [readiness](UT_EXPORT_READINESS.md#hierarchy-file--hierarchyjson)). The `Corresponding_cpp` pairing is the same
idea as our "a unit is a path, not a file" rule — `Foo.h` and `Foo.cpp` are one unit, see
[SWE4_WIKI § Precondition](SWE4_WIKI.md).

### 1.2 The test-spec file

```jsonc
{
  "format_version": "1.0",
  "environment": {
    "flags":      [ /* how to spell paths: namespace style, nullptr style, … */ ],
    "probepoint": [ /* custom code before/after a specific line of the original source */ ],
    "usercode":   [ /* code invoked just before the test, e.g. memory init, setup */ ]
  },
  "cases": [ /* one object per test case */ ]
}
```

Each case carries its sections **in this order**:

```
id → name → level → trace → review → target → preconditions → stubs → inputs → expected
```

| field | type | meaning |
|---|---|---|
| `id` | String | Unique test-case identifier, e.g. `"TC-ROUTER-001"` |
| `name` | String | Human-readable description of what the test validates |
| `level` | String | `"UT"` — one function in isolation |
| `trace` | String | Requirement ID(s) validated, e.g. `"REQ-ROUTER-010"` |
| `review` | Object | DO-178C compliance: author and reviewer information |
| `target` | Object | Which function/class is under test |
| `preconditions` | Object | State that exists before the test runs |
| `stubs` | Array | Dependencies replaced with stubs |
| `inputs` | Array | What is passed to the function |
| `expected` | Object | Return, globals, class members, stub params |

Testcase-level identity fields: `TestcaseID`, `ClassName`, `FunctionName`.

---

## 2. Derivation

### REQ-UE-01 — Everything SWE.4 emits is `level: "UT"`

Both SWE.4 spec kinds are unit-test specifications — the two sections of one
`Software Unit Test Specification` document:

| spec kind | `level` | source |
|---|---|---|
| per-function spec | `"UT"` | `test_specs.json` → `<unit>.functions[]` |
| dynamic-behaviour spec | `"UT"` | `test_specs.json` → `dynamicSpecs[]` |

`"IT"` cases (with `steps[]`) are not emitted: integration tests will be derived from SWE.2,
not SWE.4 (decided 2026-09-23). Field readiness → [UT_EXPORT_READINESS](UT_EXPORT_READINESS.md).

**Verification:** every emitted case has `level: "UT"`.

### REQ-UE-02 — Field mapping

| field | source | status |
|---|---|---|
| `id` | `spec.testCaseId` (`TC_<interfaceId>`) | ready |
| `name` | `spec.name` / `spec.qualifiedName` | ready |
| `level` | REQ-UE-01 | ready |
| `trace` | — no requirements source (Polarion / SWE.1) | **gap** — emit empty |
| `review` | not derivable from code | **config** — author/reviewer keys |
| `target.ClassName` / `.FunctionName` | split `spec.qualifiedName` on `::` | ready |
| `preconditions` | `spec.precondition.globals` + each global's `value` (initial value, in the model) | ready |
| `stubs` | `spec.precondition.mocks` — signature + declaring header | ready |
| `expected` | `spec.expected` — `returns[]`, `outParameters[]`, `globals[]` | ready |
| `inputs` | `spec.input.entries[]` — typed, with ranges | ranges only — REQ-UE-04 |

Hierarchy file (v0.1 guide shape — superseded by REQ-UE-09):

| field | source | status |
|---|---|---|
| `Layer` | run layer | ready |
| `SectionID` / `SectionName` | component (assumed — could be group; a doubt in the readiness doc) | ready once settled |
| `unit_id` / `Filename` / `FilePath` | `spec.unitKey`, `unit.fileName`, `spec.location.file` | ready |
| `IsHeader` | `views/test_specs.py::_is_header` | ready |
| `Corresponding_cpp[_path]` | the unit's `.cpp` sibling — units are already path-keyed | ready |
| `searchdirectories` | layer/component paths from config | ready |
| `CoreType` | H/F/N core concept, matching `Macros` | **?** — needs definition |
| `Macros` (H/F/NCoreMacros) | our per-layer macros config | **?** — confirm the split |

### REQ-UE-03 — Stubs need full signatures — **implemented**

`_mock_functions` returns bare strings (`"FilReadPage()"`), which is all Table A needs. A `stubs`
entry replaces a dependency and `expected` asserts on stub params — neither is possible without the
callee's return type, parameter types and declaring header.

`views/test_specs.py::_mock_signatures` projects them into `precondition.mocks`, **alongside**
`mockFunctions` rather than replacing it — that list has six consumers across the exporter, the
step transcription and the dynamic specs. Both derive from the same `mocked_ids`, so they cannot
disagree about which callees are stubbed. `dynamic_specs.py` carries the same field.

`declaredIn` resolves through `_unit_headers`: a unit is a path, so its header is the `.cpp`
sibling, and the component's `headerFiles` decides the extension rather than assuming `.h`. When the
component declares no matching header the field is `""` — an empty string beats a guessed path a
generator would fail to open.

```jsonc
"mocks": [ { "functionId": "Lib|Lib|libAdd|int,int", "name": "libAdd",
             "qualifiedName": "libAdd", "returnType": "int",
             "parameters": [ { "name": "a", "type": "int" }, { "name": "b", "type": "int" } ],
             "declaredIn": "Layer1/Sample/Lib/Lib.h" } ]
```

**Verification:** `tests/unit/test_test_specs_view.py` — `mocks` mirrors `mockFunctions` one-to-one,
carries return type and typed parameters, and resolves `declaredIn` from the component.

### REQ-UE-04 — One `cases[]` object per test case, not per function

**This is the crux.** `cases` is one object per *test case*; SWE.4 v1 emits one spec per *function*,
covering every exit in a single row. A generator handed one case per function has to invent the
split itself.

The bridge already exists in the model: `spec.expected.returns[].step` names which numbered step
each return exits from, so the paths are already distinguished — they are simply collapsed into one
spec for the document. Splitting them yields one case per path, each with its own `inputs` and
`expected`.

What each case then needs beyond the split:

- **`inputs` with values, not only ranges.** V1 gives `type name[low-high]` per input. A case needs
  an assignment that reaches its path.
- **Path conditions.** The predicate for each branch currently exists only as English inside
  `testSteps[].text` (*"Check whether sample < 0."*). The CFG has the structure; the view flattens
  it. Without it neither side can solve for values.

**Implemented** in `views/ut_export.py` → `output/<group>/ut_export.json`. The split is done; the
values are not. Each input carries its declared range and `"value": null`, and `expected.return`
stays the source expression (`"libAdd()"`, not `7`) — resolving it is the *same* step as choosing the
inputs, so neither lands before path conditions do.

Three consequences of the union-over-paths mock list, worth knowing:

- **`expected` names no called mocks.** The spec's mock list covers every path, so on any one path
  most of it did not run. Asserting it would fail three times out of four on a four-way branch.
- **`stubs` is not narrowed** to the callee a path reaches. Over-listing is harmless — an unused
  stub is registered and never called — where over-asserting is not.
- Which mock a path reaches *is* knowable: the transcription writes "expect mock function X" into a
  step. But only as prose, so it waits on the same structural work as the predicates.

**Every case id is `<specId>_<NN>`, uniformly** — including a spec with no return, which still gets
`_01`. Interface ids already end in `_NN`, so a bare id would be ambiguous:
`TC_IF_LAYER1_CORE_02` could be spec `02` with one path, or spec `CORE` path `02`. The suffix scheme
itself is still provisional.

**Verification:** `tools/ut_export_audit.py` cross-checks the export against the `test_specs.json`
beside it — case count equals the path count, every `atStep` is a real step, and every case returns
what the spec returns at that step. `tests/unit/test_ut_export.py` covers the rules directly.

### REQ-UE-05 — `environment` is configuration, not derivation

`flags`, `probepoint` and `usercode` describe the test harness, not our source. Carry them from
config verbatim; never synthesise them.

**Verification:** the emitted `environment` block equals the configured one byte for byte.

### REQ-UE-06 — Our format carries the solved values — **implemented**

`ut_export.json` keeps its shape (the user asked to keep it: it may prove useful, and our reading of
the target format may be wrong). Filled from REQ-UE-10:

| Key | Holds |
|---|---|
| `inputs[].value` | the value chosen for this path (was always `null`) |
| `preconditions.globals[].value` | the value a read global must hold (new) |
| `expected.value` | what this path returns, next to the source `expected.return` (new) |
| `solve` | `status` (solved · partial · unsolved), `inputs` (solved · partial), `expected` (known · open), `notes` — why anything is missing (new) |

**Verification:** `tests/unit/test_ut_export.py` — values per path, the `solve` block, no CFG → nulls
plus the reason, called without solutions → exactly the old shape.

### REQ-UE-07 — Target-format test-case file, one per unit — **implemented**

`output/ut/<environment>.json` — one `ut/` folder for the whole project, beside the group folders —
`<environment>` = `<LAYER>_<COMPONENT>_<UNIT>_TS`. Same cases and ids as ours. Keys and shapes exactly as
[ut_templates](ut_templates/README.md).

| Field | From |
|---|---|
| `environment.name` | the environment name |
| `environment.flags` / `probepoint` / `usercode` | config `views.utExport.environment`, overridden per environment by `views.utExport.environments.<env>.testcase` |
| `target` | free function: `{unit: <our unit>, function}`; member: `{unit: <class>, function}`; constructor / destructor: plus `class` and `constructor` / `destructor: true` |
| `preconditions.globals[]` | each global the path reads: `{unit: its class or unit, name, value}` |
| `stubs[]` | one per mock — REQ-UE-08 |
| `inputs[]` | each parameter: `{param, value}`; a struct parameter with solved fields: `{type, fields}` |
| `expected.return` | `{value, derived_from: ""}`; `value` null when void or not computed |
| `expected.globals[]` | each written global whose value on this path is computed |
| `expected.class_members[]` | empty — the parser records no member writes (A22) |
| `expected.stub_params[]` | each mock called on the path with its known arguments; out-parameters left out |

**Verification:** `tests/unit/test_ut_target.py`; `tools/check_ut_json.py` reports 0 errors.

### REQ-UE-08 — Stub mode — **implemented**

`prototype` when the function reads a field the stub writes back through one of its pointer
parameters (`test_specs.mock_writeback_sources`), `faked` otherwise (user, 2026-09-24).

| Mode | `unit` | `function` | extra |
|---|---|---|---|
| `faked` | the callee's class or unit | short name | `returns.value` |
| `prototype` | `uut_prototype_stubs` | qualified name | `returns.value`, `prototype_values {"<param>.<field>": value}` |

A void stub keeps `returns` with an empty value — the format has it on every stub (open question: how does the format write void?).

**Verification:** `tests/unit/test_ut_target.py` — both modes, void stub, `prototype_values` keys.

### REQ-UE-09 — Hierarchy file — **implemented**

`output/ut/hierarchy.json` — **one per project** (per version in the web app), listing every layer
(user, 2026-09-25). Section = unit per core; one core per layer today, so one section and one
environment per unit (user, 2026-09-24).

**Rebuilt whole, never patched.** Views run per group, so every group run, after writing its own
test-case files:

| Step | What |
|---|---|
| 1 | collects the units from the `test_specs.json` every group left in its own folder under the output root, keeping only units whose component the config still names |
| 2 | deletes each `*_TS.json` in `ut/` that none of those units owns — a component removed from the config, a unit with no specs any more. Nothing else in the folder is touched |
| 3 | writes `hierarchy.json` from scratch for the test-case files that remain |

Group runs are sequential, so the last one leaves the whole project. The web app starts every version
from an empty output folder; the pruning is what keeps a reused command-line `output/` clean. This is
the second place a view reads view output: its own group's specs (REQ-UE-04) and, here, every group's.

| Field | From |
|---|---|
| `Macros.<core>Macros` | the defines the layer was parsed with (`clang_macros.json`, `-D` stripped); `<core>` = the layer's core, the layer name when it has none |
| `LayerMapping.<layer>.searchdirectories` | the layer's include dirs (`clang_include_paths.json`), project-relative |
| `….Librarydirectories` | config `views.utExport.libraryDirectories.<layer>` |
| `….Sections.<unit>` | `SectionID` = unit key, `SectionName` = unit name (component-qualified when two units of a layer share a name) |
| `….TestEnvironments.<env>` | `EnvironmentId` = `EnvironmentName` = env; `Filename` / `FilePath` = the unit's source file; `CoreType` = the layer's core; `IsHeader` = header-only unit; `Probepoint` / `usercode` = config `views.utExport.environments.<env>.hierarchy`; `Testcase` = `<env>.json` |

The project root for relative paths is the model's `metadata.basePath`, else recovered from the
include dirs.

**Verification:** `tests/unit/test_ut_target.py`, `tests/unit/test_ut_export.py` — one folder and one
hierarchy for two groups, a group generated again leaves the file byte-identical, a removed component and
a unit without specs leave no trace, only `*_TS.json` is ever deleted; `tests/e2e/test_ut_export.py`
on the real pipeline; validator 0 errors.

### REQ-UE-10 — Path solving — **implemented, simple conditions** (`views/ut_paths.py`)

Per return: walk the CFG from the entry to that RETURN; every DECISION / LOOP_HEAD / SWITCH_HEAD on the
way adds its condition on the edge taken. Conditions are parsed and rewritten over what a tester
controls — parameters, globals read, mock returns, fields a mock writes back, fields of a struct
parameter — and solved.

| Solved | Not solved (a note says why) |
|---|---|
| `x OP c` for `== != < <= > >=`, `x + c OP c` | a call to a function that runs for real |
| `&&`, `||`, `!`, a bare truth test (`if (p)`) | array index, pointer arithmetic, `sizeof` |
| `a OP b` between two inputs | non-linear arithmetic in a condition (`x / 2 > 1`) |
| bit tests `x & M`, `(x & M) == V` | a local the path never assigns |
| enum constants (data dictionary), numeric macros (the layer's defines) | `!=` against a symbol with no known value |
| `switch` `case` / `default`; `for` init, `while`, `do-while` (first iteration) | a pointer that must be valid (needs a real object) |
| locals assigned on the path (`s = Mock(); if (s != 0)`), `++`, `+=` | |

Then the path's return value, written globals and stub arguments are evaluated with the chosen values
(`?:`, arithmetic, bit operators included). Value choice: the admissible value nearest 0 (a stub
return nearest 1); an enum takes an enumerator. Constants: enumerators and `#define`s from the data
dictionary (the layer's own first), and the layer's `-D` defines.

**Execution, where algebra stops.** Every function with a CFG can be *run*, concretely:

| Step | What runs | Used for |
|---|---|---|
| 1. helper | a same-unit function that runs for real, called with the chosen values | its result — a return like `return clip(v, lo, hi)` gets a known value |
| 2. check | a condition that could not be inverted (`h = helper(x); if (h > 50)`) | confirmed with the chosen values; if it fails, a bounded search (small values, the function's own literals ± 1) finds values that pass |
| 3. whole function | the function under test, when step 1–2 leave the case unsolved | inputs that really exit through the case's return; the run's return value and globals become the expected values |

Loops iterate for real (20 000-node limit), `switch` picks its case, helper calls nest up to 4 deep.
A write through a pointer or into an array is skipped — safe, because reading one back is refused.

Two verdicts per case — inputs solved / partial, expected known / open. Deterministic: file-order walk,
fixed candidate order, no randomness.

**Verification:** `tests/unit/test_ut_paths.py` — one test per condition shape, per loop kind, per
execution step and per "not solved" reason; rerun gives identical results.

Config (`views.utExport`): `targetFormat` (default true), `libraryDirectories {<layer>: [...]}`,
`environments {<env>: {testcase: {flags, probepoint, usercode}, hierarchy: {Probepoint, usercode}}}`
— split by file because the two `usercode` shapes differ.

---

## 3. Worked example

`coreNestedBranch` — four paths and three stubbed callees, the smallest function that exercises both
REQ-UE-03 and REQ-UE-04. Source at [Core.cpp:112](../../SampleCppProject/Layer1/Sample/Core/Core.cpp#L112):

```c
PUBLIC int coreNestedBranch(int a, int b) {
    if (a > 0) {
        if (b > 0) return libAdd(a, b);            // step 2.1.1.1
        else       return utilCompute(a, -b);      // step 2.1.1.2
    } else {
        if (b > 0) return libNormalize(b, a < -100 ? 100 : -a);   // step 2.2.1.1
        else       return 0;                       // step 2.2.1.2
    }
}
```

### What SWE.4 emits today — one spec, four returns

```jsonc
{
  "testCaseId": "TC_IF_LAYER1_CORE_06",
  "qualifiedName": "coreNestedBranch",
  "precondition": { "mockFunctions": ["libAdd()", "libNormalize()", "utilCompute()"],
                    "parameters": [ { "name": "a", "type": "int" },
                                    { "name": "b", "type": "int" } ] },
  "input": { "entries": [ { "kind": "parameter",  "name": "a", "text": "int a[-0x80000000-0x7FFFFFFF]" },
                          { "kind": "parameter",  "name": "b", "text": "int b[-0x80000000-0x7FFFFFFF]" },
                          { "kind": "mockReturn", "name": "libAdd()",       "type": "int" },
                          { "kind": "mockReturn", "name": "libNormalize()", "type": "int" },
                          { "kind": "mockReturn", "name": "utilCompute()",  "type": "int" } ] },
  "expected": { "returns": [ { "step": "2.1.1.1", "expression": "libAdd()",       "source": "libAdd(a, b)" },
                             { "step": "2.1.1.2", "expression": "utilCompute()",  "source": "utilCompute(a, -b)" },
                             { "step": "2.2.1.1", "expression": "libNormalize()", "source": "libNormalize(b, …)" },
                             { "step": "2.2.1.2", "expression": "0",              "source": "0" } ] },
  "testSteps": [ { "number": "2",     "type": "DECISION", "text": "Check whether a > 0." },
                 { "number": "2.1.1", "type": "DECISION", "text": "Check whether b > 0." },
                 { "number": "2.2.1", "type": "DECISION", "text": "Check whether b > 0." } ]
}
```

### The four paths

| case | path conditions | inputs | stub reached | expected return |
|---|---|---|---|---|
| `…_01` | `a > 0`, `b > 0` | `a=1, b=1` | `libAdd` | the stub's value |
| `…_02` | `a > 0`, `b ≤ 0` | `a=1, b=0` | `utilCompute` | the stub's value |
| `…_03` | `a ≤ 0`, `b > 0` | `a=0, b=1` | `libNormalize` | the stub's value |
| `…_04` | `a ≤ 0`, `b ≤ 0` | `a=0, b=0` | none | `0` |

**Only one stub is reached per path.** The spec's `mockFunctions` is the union across all paths;
a per-path case narrows `stubs` to the callee actually executed — a refinement the split enables.

### The hierarchy file for this group

Layer `Layer1`, group `My Sample` — three components, one unit each:

```jsonc
{
  "Macros": {
    "HCoreMacros": [ /* … */ ],
    "FCoreMacros": [ /* … */ ],
    "NCoreMacros": [ /* … */ ]
  },
  "LayerMapping": {
    "Layer1": {
      "searchdirectories": [ "Layer1/Sample/Core", "Layer1/Sample/Lib", "Layer1/Sample/Util" ],
      "Sections": [
        {
          "SectionID": "Sample-Core",
          "SectionName": "Sample Core",
          "Units": [
            {
              "unit_id": "Sample-Core|Core",
              "Filename": "Core.cpp",
              "FilePath": "Layer1/Sample/Core/Core.cpp",
              "CoreType": "",
              "IsHeader": false,
              "Testcases": [ "TC_IF_LAYER1_CORE_06_01", "TC_IF_LAYER1_CORE_06_02",
                             "TC_IF_LAYER1_CORE_06_03", "TC_IF_LAYER1_CORE_06_04" ]
            },
            {
              "unit_id": "Sample-Core|Core.h",
              "Filename": "Core.h",
              "FilePath": "Layer1/Sample/Core/Core.h",
              "CoreType": "",
              "IsHeader": true,
              "Corresponding_cpp": "Core.cpp",
              "Corresponding_cpp_path": "Layer1/Sample/Core/Core.cpp",
              "Testcases": []
            }
          ]
        },
        { "SectionID": "Lib",  "SectionName": "Lib",  "Units": [ /* Lib.cpp,  Lib.h  */ ] },
        { "SectionID": "Util", "SectionName": "Util", "Units": [ /* Util.cpp, Util.h */ ] }
      ]
    }
  }
}
```

Every value above except `Macros` and `CoreType` comes straight from the model — `searchdirectories`
from the group's configured component paths, `SectionID`/`SectionName` from the component,
`unit_id`/`Filename`/`FilePath` from the unit, and the `Corresponding_cpp` pair from the unit's path
(`Foo.h` and `Foo.cpp` are one unit, so the sibling is already known).

> **One file or two — unresolved, and deferrable.** The hierarchy ends
> `Testcases → [Testcase] → "refer section 4"`, which reads as full case objects nested under each
> Unit. But §4.1 describes a spec file whose `cases` is a flat top-level array. Above, `Testcases`
> holds **ids** referencing the separate spec file; the alternative is to inline the case objects
> and drop the separate file.
>
> This does not block derivation: the case objects are identical either way. Build `cases` as a
> plain list and leave packaging to a thin writer, and the choice stays a few lines at the end.
> It only becomes expensive if nesting is wired into the derivation.

### What the export produces

First and last case in full; the middle two follow the same shape.

```jsonc
{
  "format_version": "1.0",
  "environment": { "flags": [], "probepoint": [], "usercode": [] },
  "cases": [
    {
      "id": "TC_IF_LAYER1_CORE_06_01",
      "name": "coreNestedBranch returns libAdd(a, b) when a and b are both positive",
      "level": "UT",
      "trace": "",
      "review": { "author": "", "reviewer": "" },
      "target": { "ClassName": "", "FunctionName": "coreNestedBranch" },
      "preconditions": {},
      "stubs": [
        { "name": "libAdd", "returnType": "int",
          "parameters": [ { "name": "a", "type": "int" }, { "name": "b", "type": "int" } ],
          "declaredIn": "Layer1/Sample/Lib/Lib.h",
          "returns": 7 }
      ],
      "inputs":   [ { "name": "a", "type": "int", "value": 1 },
                    { "name": "b", "type": "int", "value": 1 } ],
      "expected": { "return": 7, "calls": [ "libAdd" ] }
    },
    {
      "id": "TC_IF_LAYER1_CORE_06_04",
      "name": "coreNestedBranch returns 0 when neither a nor b is positive",
      "level": "UT",
      "trace": "",
      "review": { "author": "", "reviewer": "" },
      "target": { "ClassName": "", "FunctionName": "coreNestedBranch" },
      "preconditions": {},
      "stubs": [],
      "inputs":   [ { "name": "a", "type": "int", "value": 0 },
                    { "name": "b", "type": "int", "value": 0 } ],
      "expected": { "return": 0, "calls": [] }
    }
  ]
}
```

Three things this makes concrete:

- **`ClassName` is empty** for a free function. Only a `Class::method` qualified name fills it.
- **The expected return is the stub's own value** on three of the four paths — `expression` is
  `libAdd()`, not a literal. Choosing the stub's return value and stating the expected result are
  therefore the same decision, not two.
- **Inputs are solved, not guessed.** `a=1, b=1` comes from intersecting the path conditions
  (`a > 0`, `b > 0`) with the declared range — which is why REQ-UE-04 needs those predicates
  structurally rather than as English in `testSteps[].text`.

> The **inner** shapes of `target`, `preconditions`, `stubs`, `inputs` and `expected` above are
> assumed, and the `_NN` id suffix is provisional. Both are Open items.

---

## Limitations

- **`trace` is empty.** No requirements source exists yet (Polarion / SWE.1), the same gap that
  leaves SWE.4 Table B's *Alias Test ID · Risk · Test Method · Linked Work Items* as `-`.
- **`review`** (DO-178C author/reviewer) has no code-derived source — configuration only.
- **Inline public functions get no case**, because they get no SWE.4 spec — they are covered through
  their own unit's callers. An inline function with no caller in its own unit is covered nowhere;
  known gap, see [SWE4_WIKI § Who gets a spec](SWE4_WIKI.md).
- **A helper that runs for real** decides the return value on many paths (`return clip(v, lo, hi)`):
  the inputs are solved, the expected value stays open. Computing it means executing the helper.
- **One feasible path per return** for the symbolic walk (loops on their first iteration); the
  execution fallback (REQ-UE-10) runs loops for real.
- **Constructors / destructors get no case**: the parser does not record them (checked,
  `_DIAG_FUNCTIONISH_KINDS`). The target builder handles them once they arrive.
- **The UT files are stored with the version** (`version_output_files` walks `output/` recursively)
  **but not served**: no API route or web-app page exposes them yet. Version compare skips `ut/` — it
  is not a group (`api/services/output_reader.py`).

## Decisions (user)

| Date | Decision |
|---|---|
| 2026-09-23 | UT only, from SWE.4. IT (`level: "IT"`, `steps[]`) comes from SWE.2 |
| 2026-09-23 | Never change the target format: no key added or removed |
| 2026-09-23 | Config is user input: layer / core names, macros, paths are whatever the project configures |
| 2026-09-23 | `CoreType` = our `cores` (per-core macros, compile commands, data dictionary) |
| 2026-09-24 | Section = unit per core; one core per layer, so section = unit |
| 2026-09-24 | One test-case file per unit (= test environment) |
| 2026-09-24 | Stub mode: `prototype` when the stub writes back through a pointer, `faked` otherwise |
| 2026-09-24 | Keep our `ut_export.json` too; the target format is a second output |
| 2026-09-24 | Path solving: simple conditions, deterministic |
| 2026-09-25 | One hierarchy for the project, not one per group; rebuilt whole every run, stale entries dropped |

## Assumptions (not confirmed — each is one place in the code to change)

| # | Assumption | Why |
|---|---|---|
| A1 | Environment name `<LAYER>_<COMPONENT>_<UNIT>_TS` | sample `<LAYER>_<SECTION>_<UNIT>_TS`; with section = unit the component fills the middle |
| A2 | `EnvironmentId` = `EnvironmentName`; `SectionID` = our unit key | formats unknown (open questions) |
| A3 | `unit` of a free function / file global = our unit (file); of a member = its class | the sample only shows classes |
| A4 | `faked`: unit = the callee's class or unit, function = short name; `prototype`: unit `uut_prototype_stubs`, function = qualified | as the sample writes them |
| A5 | `prototype_values` key = `<stub parameter>.<field>` | sample `<stParam.nField>` |
| A6 | Void stub: `returns: {"value": ""}` | every stub in the format has `returns` (format kept); the sample has no void stub (open question) |
| A7 | Values are C-expression strings; a `bool` input is a JSON bool; a null pointer is `null` | the sample's types |
| A8 | Unconstrained: inputs 0, stub returns 1, enums the enumerator nearest 0 | any admissible value works; these read naturally |
| A9 | Preconditions list only globals the path reads | a write-only global has nothing to set |
| A10 | Expected globals only when computed on the path | an unknown value cannot be asserted |
| A11 | `inputs` lists every parameter, out-parameters included; an out-parameter the function writes gets `null` plus a note | the call needs every argument; the format has no value for "a buffer" (open question) |
| A12 | A pointer that must be valid gets `null` plus a note | the format has no value for "a real object" (open question) |
| A13 | A struct / pointer-to-struct parameter's value is `{type, fields}` | the sample's struct form |
| A14 | The hierarchy is rebuilt from the specs each group left in its own folder + the current config | the target format carries no unit key or source path; the group folders do |
| A15 | `searchdirectories` = the layer's include dirs, project-relative | what clang parsed with |
| A16 | `Macros` values = the layer's parse defines, `-D` stripped | sample `NAME=value` / `NAME` |
| A17 | `FilePath` = the unit's source file, project-relative | the sample leaves it empty |
| A18 | `IsHeader` = the unit has only a header | a unit is a path (`Foo.h` + `Foo.cpp`) |
| A19 | `Testcase` = `<env>.json`, beside the hierarchy file | both are written to `output/ut/` |
| A20 | Case ids stay ours: `TC_<interfaceId>_NN` | format unknown (open question) |
| A21 | Dynamic-behaviour specs go to their entry unit's file, solved on its CFG | their interaction runs other units for real |
| A22 | `expected.class_members` empty | checked: the parser records no `this`-member access and no field writes — needs a parser change |
| A23 | `trace`, `derived_from` empty | no requirement IDs yet |
| A24 | A helper's writes to globals are not carried back to the caller | only its return value is used |
| A25 | Search candidates: 0, ±1, ±2, 3, 5, ±10, ±100, ±1000, the function's literals ± 1 | bounded (600 checks / 400 runs per return) |
| A26 | The UT folder is `output/ut/`, beside the group folders | one per version; a group or component named `ut` would collide with it |
| A27 | A test-case file is stale when its unit's component left the config or its group's specs no longer list it; only `*_TS.json` is ever deleted | the config and the specs are the current truth; other files in the folder are not ours |
| A28 | `SectionName` = the unit name; `<component>.<unit>` when two units of one layer share a name | a section key must be unique in its layer |
| A29 | `stub_params` = each stub called on the path, with the arguments known there; out-parameter arguments left out | an out-parameter is a buffer the stub fills — nothing to assert |
| A30 | A run of one group gives a hierarchy of that group only (web app) | the version holds only that group's output, the same as its documents |

## Open items

- [ ] Confirm the full field descriptions for each case section.
- [x] `CoreType` — our `cores`; a unit gets its layer's core (user, 2026-09-23).
- [x] `Macros` — the layer's parse defines, keyed by its core (REQ-UE-09).
- [ ] A void stub: `returns: {"value": ""}` (A6). Confirm how the format writes void.
- [ ] How an out-parameter buffer is passed in `inputs` (A11).
- [ ] How an input that must be a valid pointer / object is given (A12).
- [ ] `format_version` to target — the guide is `v0.1`, the sample says `"1.0"` (we write `"1.0"`).
- [ ] **One file or two** — does `Units[].Testcases` hold full case objects, or ids referencing a
      separate spec file? The hierarchy implies nesting, §4.1 implies a flat `cases` array.
      Deferrable: it is a packaging choice, not a derivation one. See §3.
- [ ] `id` scheme vs our `TC_<interfaceId>` — the sample reads `"TC-ROUTER-001"`. Per-path cases
      (REQ-UE-04) also need a suffix scheme, and dynamic-behaviour cases need ids distinct from the
      same function's own spec — still unsettled in SWE.4 itself.
- [ ] Where a dynamic-behaviour spec's step transcription goes — its content is a multi-unit call
      sequence, and the per-case shape has no field that carries one.
